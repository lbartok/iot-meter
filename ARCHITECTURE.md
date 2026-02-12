# IoT Meter Architecture

## System Components

### 1. MQTT Broker (Eclipse Mosquitto)
- **Purpose**: Message broker for IoT device communication
- **Port**: 1883 (MQTT), 9001 (WebSocket)
- **Features**: 
  - Lightweight and efficient
  - Supports QoS levels
  - Topic-based pub/sub

### 2. MQTT Collector Service (Python)
- **Purpose**: Subscribes to MQTT topics and forwards data to storage
- **Technology**: Python with paho-mqtt, minio, influxdb-client
- **Responsibilities**:
  - Listen to all v2 device topics:
    - `iot/+/telemetry` — Measurement datagrams
    - `iot/+/hello` — Heartbeat / hello messages
    - `iot/+/status` — Online/offline (LWT)
    - `iot/+/command/ack` — Command acknowledgements
    - `iot/+/ota/status` — OTA progress reports
  - Parse incoming v2 messages (envelope with `v`, `seq`, `msg_type`)
  - Store raw data to MinIO (partitioned by device and category)
  - Store time series data to InfluxDB
  - Detect sequence gaps for deduplication
  - Handle connection failures and retries

### 3. MinIO (S3-Compatible Storage)
- **Purpose**: Object storage for raw telemetry data archive
- **Ports**: 9000 (API), 9090 (Console)
- **Storage Structure**: `s3://iot-data/{device_id}/{category}/{timestamp}.json`
- **Features**:
  - S3-compatible API
  - Scalable storage
  - Data immutability
  - Web-based console

### 4. InfluxDB (Time Series Database)
- **Purpose**: Store and query time series metrics
- **Port**: 8086
- **Data Organization**:
  - Organization: iot-org
  - Bucket: iot-metrics
  - Measurement: iot_telemetry
- **Features**:
  - Optimized for time series data
  - Built-in aggregation functions
  - Retention policies
  - Flux query language

### 5. PostgreSQL (Relational Database)
- **Purpose**: Device metadata and management data
- **Port**: 5432
- **Tables**:
  - `devices`: Device registry and metadata (with `connection_status`, `fw_version`)
  - `device_configs`: Configuration key-value pairs
  - `device_alerts`: Alert history
  - `device_commands`: Server→device command queue (IoT.md §6)
  - `device_seq_tracking`: Sequence deduplication (IoT.md §2.2)
- **Features**:
  - ACID compliance
  - JSON support for flexible metadata
  - Indexes for fast lookups

### 6. Device Manager API (Flask REST API)
- **Purpose**: Management interface for devices and data access
- **Port**: 8080
- **Technology**: Python Flask with CORS support
- **Endpoints**:
  - Device CRUD operations
  - Metrics querying from InfluxDB
  - Raw data access from MinIO
  - Alert management
  - System statistics

### 7. IoT Device Simulator (Python)
- **Purpose**: Simulate multiple IoT devices for testing
- **Technology**: Python with paho-mqtt
- **Capabilities**:
  - Simulate DC traction power meters (`power_meter_dc`)
  - Simulate AC traction power meters (`power_meter_ac`)
  - Configurable device count and publish interval
  - v2 protocol with sequence numbers, heartbeats, and LWT

## Data Flow Diagram

```
┌─────────────────┐
│  IoT Devices    │
│  (Simulators)   │
└────────┬────────┘
         │ MQTT (1883)
         ▼
┌─────────────────┐
│ MQTT Broker     │
│ (Mosquitto)     │
└────────┬────────┘
         │ Subscribe: iot/+/telemetry, iot/+/hello, ...
         ▼
┌─────────────────┐
│ MQTT Collector  │
└────┬───────┬────┘
     │       │
     │       └──────────────────┐
     │                          │
     ▼                          ▼
┌─────────────┐          ┌──────────────┐
│   MinIO     │          │  InfluxDB    │
│ (S3 Storage)│          │ (Time Series)│
└─────────────┘          └──────────────┘
     │                          │
     │    ┌────────────────┐    │
     └────► Device Manager ◄────┘
          │  REST API      │
          └───────┬────────┘
                  │
                  ▼
          ┌──────────────┐
          │  PostgreSQL  │
          │   (Metadata) │
          └──────────────┘
```

## Technology Stack

### Backend Services
- **Python 3.13**: Primary programming language
- **Flask**: REST API framework
- **paho-mqtt**: MQTT client library
- **psycopg2**: PostgreSQL adapter
- **minio**: MinIO Python client
- **influxdb-client**: InfluxDB 2.x client

### Infrastructure
- **Docker**: Containerization
- **Docker Compose**: Local development orchestration
- **Kubernetes (Kustomize)**: Production deployment (base + overlays)
- **GitHub Actions**: CI/CD pipeline (build → test → deploy)
- **Eclipse Mosquitto**: MQTT broker
- **MinIO**: Object storage
- **InfluxDB 2.7**: Time series database
- **PostgreSQL 15**: Relational database

## Scalability Considerations

### Horizontal Scaling
1. **MQTT Collectors**: Multiple instances can subscribe to different topic patterns
2. **Device Manager API**: Stateless design allows multiple instances behind load balancer
3. **MQTT Broker**: Can be clustered for high availability
4. **Databases**: Support replication and sharding

### Vertical Scaling
- InfluxDB benefits from more RAM for caching
- PostgreSQL can use more CPU for complex queries
- MinIO can utilize more storage for data retention

## Security Features

### Current Implementation
- Service isolation via Docker networks
- Basic authentication for MinIO and InfluxDB
- PostgreSQL password protection

### Production Recommendations
1. Enable TLS/SSL for all connections
2. Implement MQTT authentication (username/password or certificates)
3. Add API authentication (JWT tokens, API keys)
4. Use secrets management (Docker secrets, Vault)
5. Enable audit logging
6. Implement rate limiting
7. Set up firewall rules

## Monitoring and Observability

### Logs
- All services output structured logs
- Docker Compose aggregates logs
- Logs can be forwarded to centralized logging (ELK, Loki)

### Metrics
- Prometheus scrapes `/metrics` endpoints from all services (device-manager, mqtt-collector)
- 40+ custom application metrics (request rates, latencies, MQTT throughput, storage health)
- kube-state-metrics for Kubernetes cluster state
- 12 alerting rules across 5 groups (service health, API performance, MQTT pipeline, device alerts, Kubernetes)

### Dashboards
- Grafana auto-provisioned with "IoT Meter — Overview" dashboard (21 panels, 5 sections)
- Panels cover: service health, HTTP traffic, MQTT pipeline, business metrics, Kubernetes cluster

### Alerting
- Alertmanager for routing, deduplication, and grouping
- GitHub Issues integration via custom webhook receiver
- Critical + warning severity routing with inhibition rules

### Health Checks
- HTTP health endpoints
- Docker health checks
- Database connection checks

## Deployment Options

### Deployment
- Docker Compose for local development
- Kubernetes with Kustomize (base + production overlay) for staging/production
- k3s single-node or multi-node cluster
- CI/CD via GitHub Actions self-hosted runner
- NPM (Nginx Proxy Manager) for HTTPS / Let's Encrypt

## Future Enhancements

1. **Authentication & Authorization**
   - JWT-based API authentication
   - Role-based access control
   - Device authentication certificates

2. **Advanced Analytics**
   - Real-time anomaly detection
   - Predictive maintenance
   - Data aggregation pipelines

3. **Dashboard UI**
   - Web-based management interface
   - Device configuration UI

4. **Edge Computing**
   - Edge data processing
   - Local data buffering
   - Offline operation support
