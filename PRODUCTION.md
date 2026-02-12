# Production Deployment Guide

Complete runbook for deploying the IoT Meter platform to a production Ubuntu server
using **k3s** (lightweight Kubernetes), with CI/CD via **GitHub Actions**.

**Target server:** `192.168.111.143`
**Domain:** `iot.bartok.sk`
**Architecture:** Single-node k3s (expandable to multi-node cluster)

---

## Table of Contents

1. [Server Preparation](#1-server-preparation)
2. [Create Deployment User](#2-create-deployment-user)
3. [Install Docker CE](#3-install-docker-ce)
4. [Install k3s](#4-install-k3s)
5. [Create Data Directories](#5-create-data-directories)
6. [Install GitHub Actions Runner](#6-install-github-actions-runner)
7. [Firewall Configuration](#7-firewall-configuration)
8. [DNS Configuration](#8-dns-configuration)
9. [NPM (Nginx Proxy Manager) Configuration](#9-npm-nginx-proxy-manager-configuration)
10. [GitHub Repository Secrets & Variables](#10-github-repository-secrets--variables)
11. [First Deployment](#11-first-deployment)
12. [Backup Strategy](#12-backup-strategy)
13. [Monitoring & Troubleshooting](#13-monitoring--troubleshooting)
14. [Multi-Node Expansion](#14-multi-node-expansion)

---

## 1. Server Preparation

Start from a fresh Ubuntu 24.04+ LTS server.

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y curl wget git jq apt-transport-https \
  ca-certificates gnupg lsb-release software-properties-common

# Set timezone
sudo timedatectl set-timezone Europe/Bratislava

# Set hostname
sudo hostnamectl set-hostname iot-meter-prod
```

---

## 2. Create Deployment User

Create a dedicated `iot-deploy` user for running the GitHub Actions runner and
managing deployments.

```bash
# Create user with home directory
sudo adduser --gecos "" iot-deploy

# Add to sudo and docker groups
sudo usermod -aG sudo iot-deploy

# Configure passwordless sudo
echo 'iot-deploy ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/iot-deploy
sudo chmod 0440 /etc/sudoers.d/iot-deploy

# Verify
sudo -u iot-deploy sudo whoami
# Should output: root
```

### SSH Key Setup (optional, for remote management)

```bash
sudo -u iot-deploy mkdir -p /home/iot-deploy/.ssh
sudo -u iot-deploy chmod 700 /home/iot-deploy/.ssh

# Copy your public key
echo "ssh-ed25519 AAAA... your-key" | \
  sudo -u iot-deploy tee /home/iot-deploy/.ssh/authorized_keys

sudo -u iot-deploy chmod 600 /home/iot-deploy/.ssh/authorized_keys
```

---

## 3. Install Docker CE

Docker is needed to build container images on the runner.

```bash
# Add Docker's official GPG key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Add Docker repo
echo "deb [arch=$(dpkg --print-architecture) \
  signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin

# Add iot-deploy to docker group
sudo usermod -aG docker iot-deploy

# Verify
sudo -u iot-deploy docker run --rm hello-world
```

---

## 4. Install k3s

k3s is a lightweight, production-ready Kubernetes distribution. We disable
Traefik since NPM handles reverse proxying.

```bash
# Install k3s (disable Traefik — NPM is our reverse proxy)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable=traefik" sh -

# Verify k3s is running
sudo systemctl status k3s
sudo kubectl get nodes

# Configure kubectl access for iot-deploy user
sudo -u iot-deploy mkdir -p /home/iot-deploy/.kube
sudo cp /etc/rancher/k3s/k3s.yaml /home/iot-deploy/.kube/config
sudo chown iot-deploy:iot-deploy /home/iot-deploy/.kube/config
sudo -u iot-deploy chmod 600 /home/iot-deploy/.kube/config

# Verify iot-deploy can access the cluster
sudo -u iot-deploy kubectl get nodes
```

### k3s and Docker image sharing

The CI pipeline builds images with Docker and imports them into k3s's containerd:

```bash
docker save <image> | sudo k3s ctr images import -
```

This approach works well for single-node. For multi-node clusters, a container
registry will be needed (see [Multi-Node Expansion](#14-multi-node-expansion)).

---

## 5. Create Data Directories

Persistent data is stored on the host filesystem at `/opt/iot-meter/data/`.
Since the entire VM is ZFS-backed, all data automatically benefits from ZFS
checksumming, compression, L2ARC, and ARC caching.

```bash
sudo mkdir -p /opt/iot-meter/data/{postgres,minio,influxdb,mosquitto}

# Set ownership (containers run as various UIDs)
# Postgres runs as UID 70, MinIO as 1000, InfluxDB as 1000
sudo chown -R 1000:1000 /opt/iot-meter/data
sudo chmod -R 755 /opt/iot-meter/data

# Postgres needs specific ownership
sudo chown -R 70:70 /opt/iot-meter/data/postgres
```

### ZFS Snapshot Schedule (recommended)

```bash
# Create a daily snapshot cron job
cat << 'CRON' | sudo tee /etc/cron.d/iot-meter-snapshots
# Daily ZFS snapshots of iot-meter data - keep 7 days
0 2 * * * root zfs snapshot -r $(findmnt -n -o SOURCE /opt/iot-meter/data | head -1)@iot-$(date +\%Y\%m\%d) 2>/dev/null || true
# Clean snapshots older than 7 days
15 2 * * * root zfs list -t snapshot -o name -H | grep @iot- | head -n -7 | xargs -r -L1 zfs destroy 2>/dev/null || true
CRON
```

---

## 6. Install GitHub Actions Runner

Run these commands as the `iot-deploy` user.

```bash
su - iot-deploy

# Create runner directory
mkdir -p ~/actions-runner && cd ~/actions-runner

# Download the latest runner (check https://github.com/actions/runner/releases)
RUNNER_VERSION="2.321.0"  # Update to latest
curl -o actions-runner.tar.gz -L \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
tar xzf actions-runner.tar.gz

# Configure the runner
# Get the token from: GitHub repo → Settings → Actions → Runners → New self-hosted runner
./config.sh --url https://github.com/lbartok/iot-meter \
  --token YOUR_RUNNER_TOKEN \
  --name iot-meter-prod \
  --labels self-hosted,linux,production \
  --work _work

# Install and start as a systemd service
sudo ./svc.sh install iot-deploy
sudo ./svc.sh start
sudo ./svc.sh status
```

---

## 7. Firewall Configuration

```bash
# Enable UFW
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH
sudo ufw allow 22/tcp comment 'SSH'

# HTTP/HTTPS (for NPM)
sudo ufw allow 80/tcp comment 'HTTP - NPM'
sudo ufw allow 443/tcp comment 'HTTPS - NPM'

# MQTT (devices connect from internet)
sudo ufw allow 1883/tcp comment 'MQTT - IoT devices'

# k3s API (optional — only if managing cluster remotely)
# sudo ufw allow 6443/tcp comment 'k3s API'

# k3s NodePort for device-manager (NPM connects locally, but allow it)
sudo ufw allow 30080/tcp comment 'Device Manager NodePort'

# Enable firewall
sudo ufw enable
sudo ufw status verbose
```

---

## 8. DNS Configuration

Create an **A record** pointing to the server's public IP:

| Type | Name | Value             | TTL  |
|------|------|-------------------|------|
| A    | iot  | `<server-public-IP>` | 300  |

Verify DNS resolution:

```bash
dig iot.bartok.sk +short
# Should return your server's public IP
```

---

## 9. NPM (Nginx Proxy Manager) Configuration

NPM is already running on the server and manages HTTPS/Let's Encrypt certificates.

### Add Proxy Host

1. Open NPM admin panel (typically `http://192.168.111.143:81`)
2. **Proxy Hosts** → **Add Proxy Host**
3. Configure:

| Field              | Value                     |
|--------------------|---------------------------|
| Domain Names       | `iot.bartok.sk`           |
| Scheme             | `http`                    |
| Forward Hostname   | `192.168.111.143`         |
| Forward Port       | `30080`                   |
| Block Exploits     | ✅                        |
| Websockets Support | ✅                        |

4. **SSL tab**:
   - Request a new SSL Certificate
   - Force SSL: ✅
   - HTTP/2 Support: ✅
   - HSTS Enabled: ✅

After saving, verify:

```bash
curl -sf https://iot.bartok.sk/healthz
```

> **Note:** NPM handles HTTPS only for the REST API. MQTT uses plain TCP on
> port 1883. TLS for MQTT can be added later with a mosquitto TLS configuration.

---

## 10. GitHub Repository Secrets & Variables

Configure these in: **GitHub repo → Settings → Secrets and variables → Actions**

### Secrets (Settings → Secrets → Actions)

| Secret Name              | Description                    | Example Value               |
|--------------------------|--------------------------------|-----------------------------|
| `DB_USER`                | PostgreSQL username            | `iot_user`                  |
| `DB_PASSWORD`            | PostgreSQL password            | *(strong random password)*  |
| `INFLUXDB_TOKEN`         | InfluxDB admin API token       | *(strong random token)*     |
| `INFLUXDB_ADMIN_USER`    | InfluxDB admin username        | `admin`                     |
| `INFLUXDB_ADMIN_PASSWORD`| InfluxDB admin password        | *(strong random password)*  |
| `MINIO_ROOT_USER`        | MinIO root username            | `minioadmin`                |
| `MINIO_ROOT_PASSWORD`    | MinIO root password            | *(strong random password)*  |

### Variables (Settings → Variables → Actions)

| Variable Name       | Description                          | Default |
|---------------------|--------------------------------------|---------|
| `DEPLOY_SIMULATOR`  | Deploy the IoT device simulator      | `true`  |

### Generate Strong Passwords

```bash
# Generate random passwords
openssl rand -base64 32  # For DB_PASSWORD
openssl rand -hex 32     # For INFLUXDB_TOKEN
openssl rand -base64 32  # For INFLUXDB_ADMIN_PASSWORD
openssl rand -base64 32  # For MINIO_ROOT_PASSWORD
```

### Create Production Environment

1. Go to **Settings → Environments → New environment**
2. Name: `production`
3. (Optional) Add protection rules:
   - Required reviewers for manual approval
   - Wait timer before deployment

---

## 11. First Deployment

After completing all the above steps:

1. **Push to main branch** — the CI/CD pipeline will run automatically
2. **Or trigger manually** — Go to Actions → "Build, Test & Deploy" → Run workflow

### Verify deployment

```bash
# SSH into the server
ssh iot-deploy@192.168.111.143

# Check pods
sudo kubectl get pods -n iot-meter

# Check services
sudo kubectl get svc -n iot-meter

# Check persistent volumes
sudo kubectl get pv,pvc -n iot-meter

# Check logs
sudo kubectl logs -f -l app=device-manager -n iot-meter
sudo kubectl logs -f -l app=mqtt-collector -n iot-meter

# Test MQTT from external
mosquitto_pub -h iot.bartok.sk -p 1883 -t "test/ping" -m "hello"

# Test HTTPS API
curl https://iot.bartok.sk/healthz
curl https://iot.bartok.sk/api/devices
```

---

## 12. Backup Strategy

### PostgreSQL Backup

```bash
# Manual backup
sudo kubectl exec -n iot-meter deployment/postgres -- \
  pg_dump -U iot_user iot_devices > backup_$(date +%Y%m%d_%H%M%S).sql

# Automated daily backup cron (as iot-deploy user)
crontab -e
# Add:
0 3 * * * sudo kubectl exec -n iot-meter deployment/postgres -- pg_dump -U iot_user iot_devices > /opt/iot-meter/backups/pg_$(date +\%Y\%m\%d).sql 2>/dev/null
```

### ZFS Snapshots

ZFS snapshots provide point-in-time recovery for all data:

```bash
# Create manual snapshot
sudo zfs snapshot -r <pool/dataset>@before-upgrade-$(date +%Y%m%d)

# List snapshots
sudo zfs list -t snapshot

# Restore from snapshot (emergency)
sudo kubectl scale deployment --all --replicas=0 -n iot-meter
sudo zfs rollback <pool/dataset>@snapshot-name
sudo kubectl scale deployment --all --replicas=1 -n iot-meter
```

### Backup directory setup

```bash
sudo mkdir -p /opt/iot-meter/backups
sudo chown iot-deploy:iot-deploy /opt/iot-meter/backups
```

---

## 13. Monitoring & Troubleshooting

### Common Commands

```bash
# Overall cluster health
sudo kubectl get nodes
sudo kubectl top nodes                    # Resource usage (if metrics-server installed)

# Pod status and events
sudo kubectl get pods -n iot-meter -o wide
sudo kubectl describe pod <pod-name> -n iot-meter
sudo kubectl get events -n iot-meter --sort-by='.lastTimestamp'

# Logs
sudo kubectl logs -f deployment/device-manager -n iot-meter
sudo kubectl logs -f deployment/mqtt-collector -n iot-meter
sudo kubectl logs -f deployment/iot-simulator -n iot-meter
sudo kubectl logs -f deployment/mosquitto -n iot-meter

# Restart a deployment
sudo kubectl rollout restart deployment/<name> -n iot-meter

# Rollback a deployment
sudo kubectl rollout undo deployment/<name> -n iot-meter

# Check persistent data
ls -la /opt/iot-meter/data/
du -sh /opt/iot-meter/data/*

# k3s service status
sudo systemctl status k3s

# Check disk usage
df -h /opt/iot-meter/data
```

### Health Endpoints

| Service          | Endpoint                            |
|------------------|-------------------------------------|
| Device Manager   | `https://iot.bartok.sk/healthz`     |
| Device Manager   | `https://iot.bartok.sk/readyz`      |
| MQTT Collector   | Internal: `mqtt-collector:8081/healthz` |
| IoT Simulator    | Internal: `iot-simulator:8082/healthz`  |
| InfluxDB         | Internal: `influxdb:8086/health`        |
| MinIO            | Internal: `minio:9000/minio/health/live` |

### Troubleshooting Checklist

1. **Pod won't start:** `kubectl describe pod <name>` — check Events section
2. **CrashLoopBackOff:** `kubectl logs <pod> --previous` — check last crash logs
3. **PVC Pending:** Check PV exists and `storageClassName` matches
4. **MQTT unreachable:** Verify firewall (`ufw status`), mosquitto pod running, hostPort binding
5. **API unreachable:** Verify NPM proxy host config, NodePort service, device-manager pods
6. **Image pull errors:** Images must be imported to k3s containerd after each build

---

## 14. Multi-Node Expansion

When ready to expand to multiple nodes:

### Add Worker Nodes

```bash
# On the master node, get the join token
sudo cat /var/lib/rancher/k3s/server/node-token

# On each worker node
curl -sfL https://get.k3s.io | K3S_URL="https://192.168.111.143:6443" \
  K3S_TOKEN="<node-token>" sh -
```

### Container Registry

For multi-node, images need to be accessible from all nodes. Options:

1. **Private registry** (recommended):
   ```bash
   # Deploy a registry in k3s
   docker run -d -p 5000:5000 --restart=always --name registry registry:2
   ```
   Update image references to `192.168.111.143:5000/iot-meter/<image>:latest`

2. **GitHub Container Registry (ghcr.io)**:
   Push images to `ghcr.io/lbartok/iot-meter/<image>:latest`
   Add imagePullSecrets to deployments

### Storage Considerations

For multi-node, replace hostPath PVs with:
- **Longhorn** (distributed storage for k3s)
- **NFS** (shared storage across nodes)
- **ZFS-backed iSCSI** targets

### Future: Multi-Regional Active-Active

- Deploy k3s clusters in multiple regions
- DNS load balancing (GeoDNS) for `iot.bartok.sk`
- MQTT broker clustering (e.g., EMQX or VerneMQ)
- PostgreSQL replication (streaming or logical)
- InfluxDB Edge Data Replication
