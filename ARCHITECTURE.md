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
  - Listen to all device telemetry topics (`iot/+/telemetry`)
  - Parse incoming messages
  - Store raw data to MinIO
  - Store time series data to InfluxDB
  - Handle connection failures and retries

### 3. MinIO (S3-Compatible Storage)
- **Purpose**: Object storage for raw telemetry data archive
- **Ports**: 9000 (API), 9090 (Console)
- **Storage Structure**: `s3://iot-data/{device_id}/{timestamp}.json`
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
  - `devices`: Device registry and metadata
  - `device_configs`: Configuration key-value pairs
  - `device_alerts`: Alert history
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
  - Simulate temperature sensors
  - Simulate humidity sensors
  - Simulate power meters
  - Configurable device count and publish interval

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
         │ Subscribe: iot/+/telemetry
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
- **Python 3.11**: Primary programming language
- **Flask**: REST API framework
- **paho-mqtt**: MQTT client library
- **psycopg2**: PostgreSQL adapter
- **minio**: MinIO Python client
- **influxdb-client**: InfluxDB 2.x client

### Infrastructure
- **Docker**: Containerization
- **Docker Compose**: Multi-container orchestration
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
- InfluxDB stores application metrics
- Can be exposed via Prometheus exporters
- Grafana dashboards for visualization

### Health Checks
- HTTP health endpoints
- Docker health checks
- Database connection checks

## Deployment Options

### Development
- Docker Compose on local machine
- All services on single host

### Staging/Production
- Kubernetes for orchestration
- Managed services for databases
- Load balancers for API and MQTT
- Object storage (AWS S3, Azure Blob)
- Monitoring and alerting platforms

## Future Enhancements

1. **Authentication & Authorization**
   - JWT-based API authentication
   - Role-based access control
   - Device authentication certificates

2. **Advanced Analytics**
   - Real-time anomaly detection
   - Predictive maintenance
   - Data aggregation pipelines

3. **Alerting System**
   - Real-time threshold monitoring
   - Email/SMS notifications
   - Webhook integrations

4. **Dashboard UI**
   - Web-based management interface
   - Real-time data visualization
   - Device configuration UI

5. **Edge Computing**
   - Edge data processing
   - Local data buffering
   - Offline operation support

6. **Advanced Monitoring**
   - Prometheus metrics export
   - Grafana dashboards
   - Distributed tracing
