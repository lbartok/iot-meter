# Examples

This directory contains example scripts and clients for interacting with the IoT Meter system.

## Available Examples

### 1. API Test Script (`test-api.sh`)

A bash script that tests all Device Manager API endpoints.

**Usage:**
```bash
./test-api.sh
```

**Prerequisites:**
- `curl` installed
- `jq` (optional, for pretty JSON output)
- IoT Meter system running

### 2. IoT Device Client (`iot_device_client.py`)

A Python script that simulates an IoT device publishing data via MQTT.

**Usage:**
```bash
# Install dependencies
pip install -r requirements.txt

# Run with defaults
python iot_device_client.py

# Custom configuration
python iot_device_client.py \
  --device-id dc-meter-test \
  --device-type power_meter_dc \
  --broker localhost \
  --port 1883 \
  --interval 10 \
  --duration 60
```

**Options:**
- `--device-id`: Unique device identifier (default: device-custom-001)
- `--device-type`: Type of device (`power_meter_dc`, `power_meter_ac`, `generic`)
- `--broker`: MQTT broker host (default: localhost)
- `--port`: MQTT broker port (default: 1883)
- `--interval`: Publish interval in seconds (default: 5)
- `--duration`: Total duration in seconds (default: infinite)

**Example:**
```bash
# Simulate a DC traction power meter for 2 minutes
python iot_device_client.py \
  --device-id dc-meter-lab-01 \
  --device-type power_meter_dc \
  --interval 5 \
  --duration 120
```

### 3. API Client (`api_client.py`)

A Python library and example script for interacting with the Device Manager API.

**Usage:**
```bash
# Install dependencies
pip install -r requirements.txt

# Run the example
python api_client.py
```

**As a Library:**
```python
from api_client import IoTMeterAPIClient

# Create client
client = IoTMeterAPIClient("http://localhost:8080")

# Get all devices
devices = client.get_devices()

# Create a device
device = client.create_device(
    device_id="dc-meter-test",
    device_name="DC Traction Meter — Test",
    device_type="power_meter_dc",
    location="Test Lab"
)

# Get metrics
metrics = client.get_metrics("dc-meter-test", start="-1h")

# Create alert
alert = client.create_alert(
    "my-device",
    alert_type="high_temp",
    severity="warning",
    message="Temperature exceeded threshold"
)
```

## Common Use Cases

### Use Case 1: Add a New Device and Start Sending Data

```bash
# 1. Create device via API
curl -X POST http://localhost:8080/api/devices \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "sensor-001",
    "device_name": "DC Traction Meter — Sensor 001",
    "device_type": "power_meter_dc",
    "location": "Train 1234 / Car 1"
  }'

# 2. Start publishing data
python iot_device_client.py \
  --device-id sensor-001 \
  --device-type power_meter_dc \
  --interval 10
```

### Use Case 2: Query Device Data

```bash
# Get device info
curl http://localhost:8080/api/devices/sensor-001

# Get recent metrics
curl "http://localhost:8080/api/devices/sensor-001/metrics?start=-1h"

# Get specific metric
curl "http://localhost:8080/api/devices/sensor-001/metrics?metric=temperature&start=-24h"
```

### Use Case 3: Monitor Alerts

```python
from api_client import IoTMeterAPIClient

client = IoTMeterAPIClient()

# Get unacknowledged alerts for all devices
devices = client.get_devices()
for device in devices:
    alerts = client.get_alerts(device['device_id'], acknowledged=False)
    if alerts:
        print(f"Device {device['device_id']} has {len(alerts)} unacknowledged alerts")
        for alert in alerts:
            print(f"  - {alert['alert_type']}: {alert['message']}")
```

### Use Case 4: Bulk Device Creation

```python
from api_client import IoTMeterAPIClient

client = IoTMeterAPIClient()

# Create multiple devices
devices_to_create = [
    ("temp-01", "Temperature Sensor 1", "temperature", "Building A"),
    ("temp-02", "Temperature Sensor 2", "temperature", "Building B"),
    ("hum-01", "Humidity Sensor 1", "humidity", "Building A"),
]

for device_id, name, device_type, location in devices_to_create:
    try:
        device = client.create_device(
            device_id=device_id,
            device_name=name,
            device_type=device_type,
            location=location
        )
        print(f"Created: {device_id}")
    except Exception as e:
        print(f"Failed to create {device_id}: {e}")
```

## Integration Examples

### Integrate with Existing IoT Device

If you have an existing IoT device, you can integrate it by:

1. Publishing MQTT messages to topic: `iot/{device_id}/telemetry`
2. Using v2 JSON payload format:
```json
{
  "v": 2,
  "device_id": "your-device-id",
  "ts": "2026-02-12T16:00:00.000Z",
  "seq": 1,
  "msg_type": "telemetry",
  "measurements": [
    {"ts": "2026-02-12T16:00:00.000Z", "type": "voltage_dc", "val": 752.3, "unit": "V"},
    {"ts": "2026-02-12T16:00:00.000Z", "type": "current_dc", "val": 312.7, "unit": "A"}
  ]
}
```

Example using Paho MQTT in Python:
```python
import paho.mqtt.client as mqtt
import json
from datetime import datetime

client = mqtt.Client()
client.connect("localhost", 1883, 60)

data = {
    "v": 2,
    "device_id": "my-device",
    "ts": datetime.now().isoformat(),
    "seq": 1,
    "msg_type": "telemetry",
    "measurements": [
        {"ts": datetime.now().isoformat(), "type": "voltage_dc", "val": 752.3, "unit": "V"}
    ]
}

client.publish("iot/my-device/telemetry", json.dumps(data))
```

### Query Data from External Application

```python
import requests

# Get device metrics
response = requests.get(
    "http://localhost:8080/api/devices/my-device/metrics",
    params={"start": "-24h", "metric": "temperature"}
)

metrics = response.json()

# Process metrics
temperatures = [m['value'] for m in metrics]
avg_temp = sum(temperatures) / len(temperatures) if temperatures else 0
print(f"Average temperature: {avg_temp:.2f}°C")
```

## Testing Tips

1. **Test API endpoints** - Use `test-api.sh` to verify all endpoints work
2. **Simulate load** - Run multiple device clients simultaneously
3. **Monitor logs** - Watch service logs while testing: `docker-compose logs -f`
4. **Check data** - Verify data appears in MinIO and InfluxDB UIs
5. **Test error handling** - Try invalid data, missing fields, etc.

## Troubleshooting

### Cannot connect to MQTT broker
- Ensure the system is running: `docker-compose ps`
- Check MQTT broker logs: `docker-compose logs mosquitto`
- Verify port 1883 is accessible

### API returns 404 or 500 errors
- Check API service logs: `docker-compose logs device-manager`
- Verify PostgreSQL is running: `docker-compose ps postgres`
- Test health endpoint: `curl http://localhost:8080/health`

### No data appears in InfluxDB
- Verify MQTT collector is running: `docker-compose logs mqtt-collector`
- Check if messages are being published: Subscribe with `mosquitto_sub`
- Verify InfluxDB connection in collector logs

## Additional Resources

- [Main README](../README.md) - Full system documentation
- [Quick Start Guide](../QUICKSTART.md) - Getting started guide
- [Architecture Guide](../ARCHITECTURE.md) - System architecture details
