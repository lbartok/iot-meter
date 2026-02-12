# IoT Meter - IoT Data Collection and Management System

A complete IoT architecture to collect, save, and process data in an IoT environment.

## Architecture Overview

This system implements a scalable IoT solution with the following components:

### Core Services

1. **MQTT Broker (Mosquitto)** - Message broker for IoT device communication
2. **MQTT Collector** - Service that subscribes to MQTT topics and forwards data
3. **MinIO** - S3-compatible object storage for raw data archival
4. **InfluxDB** - Time series database for metrics and analytics
5. **PostgreSQL** - Relational database for device metadata and management
6. **Device Manager API** - REST API for device management and data access
7. **IoT Device Simulator** - Simulates multiple IoT devices for testing

### Data Flow

```
IoT Devices → MQTT Broker → MQTT Collector → MinIO (Raw Data Archive)
                                           → InfluxDB (Time Series)
                                           
Device Manager API ← PostgreSQL (Device Metadata)
                   ← InfluxDB (Metrics Query)
                   ← MinIO (Raw Data Access)
```

## Quick Start

### Prerequisites

- Docker and Docker Compose installed
- At least 4GB of RAM available
- Ports 1883, 5432, 8080, 8086, 9000, 9090 available

### Starting the System

1. Clone the repository:
```bash
git clone https://github.com/lbartok/iot-meter.git
cd iot-meter
```

2. Start all services:
```bash
docker-compose up -d
```

3. Check service status:
```bash
docker-compose ps
```

4. View logs:
```bash
docker-compose logs -f
```

### Stopping the System

```bash
docker-compose down
```

To remove all data volumes:
```bash
docker-compose down -v
```

## Service Access

| Service | URL/Port | Credentials |
|---------|----------|-------------|
| Device Manager API | http://localhost:8080 | N/A |
| MinIO Console | http://localhost:9090 | minioadmin / minioadmin123 |
| InfluxDB UI | http://localhost:8086 | admin / adminpassword |
| PostgreSQL | localhost:5432 | iot_user / iot_password |
| MQTT Broker | localhost:1883 | Anonymous |

## API Documentation

### Device Management Endpoints

#### Get All Devices
```bash
curl http://localhost:8080/api/devices
```

Query parameters:
- `status`: Filter by status (active, inactive)
- `type`: Filter by device type

#### Get Single Device
```bash
curl http://localhost:8080/api/devices/device-001
```

#### Create Device
```bash
curl -X POST http://localhost:8080/api/devices \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "device-004",
    "device_name": "New Sensor",
    "device_type": "temperature",
    "location": "Building C",
    "status": "active",
    "metadata": {"sampling_rate": "5s"}
  }'
```

#### Update Device
```bash
curl -X PUT http://localhost:8080/api/devices/device-004 \
  -H "Content-Type: application/json" \
  -d '{
    "device_name": "Updated Sensor",
    "location": "Building D"
  }'
```

#### Delete Device
```bash
curl -X DELETE http://localhost:8080/api/devices/device-004
```

#### Device Heartbeat
```bash
curl -X POST http://localhost:8080/api/devices/device-001/heartbeat
```

### Metrics Endpoints

#### Get Device Metrics
```bash
# Last hour of data
curl http://localhost:8080/api/devices/device-001/metrics

# Custom time range
curl "http://localhost:8080/api/devices/device-001/metrics?start=-24h&stop=now()"

# Specific metric
curl "http://localhost:8080/api/devices/device-001/metrics?metric=temperature"
```

#### Get Raw Data Files
```bash
curl http://localhost:8080/api/devices/device-001/raw-data
```

### Alert Endpoints

#### Get Device Alerts
```bash
curl http://localhost:8080/api/devices/device-001/alerts

# Only unacknowledged
curl "http://localhost:8080/api/devices/device-001/alerts?acknowledged=false"
```

#### Create Alert
```bash
curl -X POST http://localhost:8080/api/devices/device-001/alerts \
  -H "Content-Type: application/json" \
  -d '{
    "alert_type": "high_temperature",
    "severity": "warning",
    "message": "Temperature exceeded threshold"
  }'
```

#### Acknowledge Alert
```bash
curl -X POST http://localhost:8080/api/alerts/1/acknowledge
```

### Statistics Endpoint

```bash
curl http://localhost:8080/api/stats
```

## MQTT Topics

The system uses the following MQTT topic structure:

```
iot/{device_id}/telemetry
```

Example:
- `iot/device-001/telemetry`
- `iot/device-002/telemetry`

### Message Format

IoT devices should publish JSON messages in the following format:

```json
{
  "timestamp": "2026-02-12T16:00:00.000Z",
  "device_id": "device-001",
  "temperature": 23.5,
  "unit": "celsius"
}
```

## Testing with MQTT

### Publish a test message

```bash
docker exec -it iot-mosquitto mosquitto_pub \
  -t "iot/device-001/telemetry" \
  -m '{"timestamp":"2026-02-12T16:00:00.000Z","device_id":"device-001","temperature":23.5}'
```

### Subscribe to messages

```bash
docker exec -it iot-mosquitto mosquitto_sub \
  -t "iot/+/telemetry"
```

## Database Schema

### PostgreSQL Tables

#### devices
- `id`: Serial primary key
- `device_id`: Unique device identifier
- `device_name`: Human-readable name
- `device_type`: Type of device
- `location`: Physical location
- `status`: Current status (active/inactive)
- `created_at`: Creation timestamp
- `updated_at`: Last update timestamp
- `last_seen`: Last heartbeat timestamp
- `metadata`: JSON metadata

#### device_configs
- Configuration key-value pairs for devices

#### device_alerts
- Alert history for devices

## Data Storage

### MinIO (S3)

Raw telemetry data is stored in MinIO at:
```
s3://iot-data/{device_id}/{timestamp}.json
```

Access the MinIO console at http://localhost:9090 to browse files.

### InfluxDB

Time series metrics are stored in InfluxDB:
- Organization: `iot-org`
- Bucket: `iot-metrics`
- Measurement: `iot_telemetry`

Access the InfluxDB UI at http://localhost:8086 to query and visualize data.

## Monitoring and Troubleshooting

### View service logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f mqtt-collector
docker-compose logs -f device-manager
docker-compose logs -f iot-simulator
```

### Check service health

```bash
# Device Manager API
curl http://localhost:8080/health

# MinIO
curl http://localhost:9000/minio/health/live

# InfluxDB
curl http://localhost:8086/health
```

### Restart a service

```bash
docker-compose restart mqtt-collector
```

## Scaling Considerations

### Horizontal Scaling

1. **MQTT Collector**: Can run multiple instances with load balancing
2. **Device Manager API**: Can run multiple instances behind a load balancer
3. **IoT Simulators**: Can run multiple instances for load testing

### Production Recommendations

1. Use persistent volumes for data
2. Enable MQTT authentication and TLS
3. Set up proper backup strategies for databases
4. Implement monitoring and alerting
5. Use secrets management for credentials
6. Add rate limiting to the API
7. Implement message queue for high-volume scenarios

## Development

### Project Structure

```
iot-meter/
├── config/                     # Configuration files
│   ├── mosquitto.conf          # MQTT broker config
│   └── init-db.sql             # Database initialization
├── services/
│   ├── mqtt-collector/         # MQTT data collector
│   │   ├── collector.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── device-manager/         # REST API service
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── iot-device-simulator/   # Device simulator
│       ├── simulator.py
│       ├── requirements.txt
│       └── Dockerfile
├── docker-compose.yml          # Service orchestration
└── README.md                   # This file
```

### Adding New Device Types

1. Update the simulator in `services/iot-device-simulator/simulator.py`
2. Add device type handling in the `generate_telemetry()` method
3. Update device creation in PostgreSQL

### Customizing the Collector

Edit `services/mqtt-collector/collector.py` to:
- Add data validation
- Implement filtering logic
- Add data transformation
- Integrate additional storage backends

## Security Notes

⚠️ **Important**: The default configuration uses simple passwords and no encryption. For production use:

1. Change all default passwords
2. Enable TLS for MQTT
3. Use proper authentication for all services
4. Implement API authentication and authorization
5. Use environment variables or secrets management for credentials
6. Enable network encryption between services

## License

MIT License - See LICENSE file for details

## Support

For issues and questions, please open an issue on GitHub. 
