# Quick Start Guide

This guide will help you get the IoT Meter system up and running quickly.

## Prerequisites Check

Before starting, ensure you have:
- [ ] Docker installed (version 20.10+)
- [ ] Docker Compose installed (version 2.0+)
- [ ] At least 4GB of free RAM
- [ ] At least 10GB of free disk space
- [ ] Ports available: 1883, 5432, 8080, 8086, 9000, 9090

Check your Docker installation:
```bash
docker --version
docker-compose --version
```

## Step-by-Step Setup

### 1. Clone the Repository

```bash
git clone https://github.com/lbartok/iot-meter.git
cd iot-meter
```

### 2. Start the System

Using Make (recommended):
```bash
make up
```

Or using Docker Compose directly:
```bash
docker-compose up -d
```

Wait for all services to start (approximately 30-60 seconds).

### 3. Verify Services

Check that all services are running:
```bash
make status
# or
docker-compose ps
```

You should see all services with "Up" status.

### 4. Test the System

#### Test the Device Manager API
```bash
# Health check
curl http://localhost:8080/health

# Get list of devices
curl http://localhost:8080/api/devices

# Get system statistics
curl http://localhost:8080/api/stats
```

Or use Make:
```bash
make test-api
```

#### View Simulated Device Data
```bash
# Watch logs from IoT simulators
docker-compose logs -f iot-simulator

# Watch logs from MQTT collector
docker-compose logs -f mqtt-collector
```

#### Check MQTT Messages
```bash
# Subscribe to all device telemetry
make subscribe-mqtt
# or
docker exec -it iot-mosquitto mosquitto_sub -t "iot/+/telemetry"
```

### 5. Access Web Interfaces

Open in your browser:

- **MinIO Console**: http://localhost:9090
  - Username: `minioadmin`
  - Password: `minioadmin123`
  - Browse the `iot-data` bucket to see raw telemetry files

- **InfluxDB UI**: http://localhost:8086
  - Username: `admin`
  - Password: `adminpassword`
  - Explore the `iot-metrics` bucket to query time series data

### 6. Explore the API

#### Get a specific device:
```bash
curl http://localhost:8080/api/devices/device-001 | python3 -m json.tool
```

#### Get device metrics (last hour):
```bash
curl "http://localhost:8080/api/devices/device-001/metrics" | python3 -m json.tool
```

#### Get raw data files for a device:
```bash
curl http://localhost:8080/api/devices/device-001/raw-data | python3 -m json.tool
```

#### Create a new device:
```bash
curl -X POST http://localhost:8080/api/devices \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "device-100",
    "device_name": "Test Temperature Sensor",
    "device_type": "temperature",
    "location": "Test Lab"
  }' | python3 -m json.tool
```

### 7. Send Test Data

Publish a test MQTT message:
```bash
make test-mqtt
# or
docker exec iot-mosquitto mosquitto_pub \
  -t "iot/device-100/telemetry" \
  -m '{"timestamp":"2026-02-12T16:00:00.000Z","device_id":"device-100","temperature":22.5}'
```

Wait a few seconds, then check if the data appears:
```bash
curl "http://localhost:8080/api/devices/device-100/metrics" | python3 -m json.tool
```

## Common Commands

### View Logs
```bash
# All services
make logs

# Specific service
make logs-collector
make logs-manager
make logs-simulator
```

### Restart Services
```bash
# All services
make restart

# Specific service
make restart-collector
make restart-manager
```

### Stop the System
```bash
# Stop services (keep data)
make down

# Stop and remove all data
make down-volumes
```

### Database Access
```bash
# PostgreSQL shell
make shell-postgres

# InfluxDB CLI
make shell-influx

# Example PostgreSQL query
docker exec iot-postgres psql -U iot_user -d iot_devices -c "SELECT * FROM devices;"
```

## Troubleshooting

### Services won't start
1. Check if ports are already in use:
   ```bash
   netstat -tlnp | grep -E '(1883|5432|8080|8086|9000|9090)'
   ```
2. Check Docker logs:
   ```bash
   docker-compose logs
   ```

### Can't access MinIO console
- Wait 30 seconds after starting for MinIO to initialize
- Clear browser cache and try again
- Check if the container is running: `docker ps | grep minio`

### No data in InfluxDB
- Ensure simulators are running: `docker logs iot-device-simulator`
- Check MQTT collector logs: `docker logs iot-mqtt-collector`
- Verify MQTT broker is receiving messages: `make subscribe-mqtt`

### API returns errors
- Check if PostgreSQL is ready: `docker logs iot-postgres`
- Verify database was initialized: `make shell-postgres` then `\dt`
- Restart the device manager: `make restart-manager`

## Next Steps

1. **Read the full documentation**: See [README.md](README.md) for detailed API documentation
2. **Understand the architecture**: See [ARCHITECTURE.md](ARCHITECTURE.md) for system design
3. **Customize the system**: Modify device types, add new sensors, customize data processing
4. **Scale the system**: Add more collectors, devices, and API instances
5. **Secure the system**: Enable authentication, TLS, and proper secrets management

## Getting Help

- Check the logs: `make logs`
- Review documentation: [README.md](README.md) and [ARCHITECTURE.md](ARCHITECTURE.md)
- Open an issue on GitHub for bugs or questions

## Clean Up

To completely remove the system:
```bash
make clean
```

This will:
- Stop all containers
- Remove all volumes and data
- Clean up Docker resources
