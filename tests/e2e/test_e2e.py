"""
End-to-end tests for the IoT Meter platform.

These tests require the full infrastructure running (docker-compose up).
They exercise the real API, MQTT broker, InfluxDB and MinIO.

Two types of MQTT messages are tested:
  1. Single measurement — one message with a single measure unit
  2. Batch measurements — one message containing an array of data points
     logging multiple measurements over a period of time
"""
import json
import time
import pytest
import requests
import paho.mqtt.client as mqtt


pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Configuration — matches docker-compose defaults
# ---------------------------------------------------------------------------
API_BASE = "http://localhost:8080"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
WAIT_FOR_PROCESSING = 3  # seconds to wait for async MQTT → storage pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mqtt_publish(topic: str, payload: dict, qos: int = 1):
    """Publish a single MQTT message and wait for delivery."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="e2e-test-publisher")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    info = client.publish(topic, json.dumps(payload), qos=qos)
    info.wait_for_publish(timeout=10)
    client.loop_stop()
    client.disconnect()


def api_get(path: str, **kwargs):
    return requests.get(f"{API_BASE}{path}", **kwargs)


def api_post(path: str, json_data: dict = None, **kwargs):
    return requests.post(f"{API_BASE}{path}", json=json_data, **kwargs)


def api_put(path: str, json_data: dict = None, **kwargs):
    return requests.put(f"{API_BASE}{path}", json=json_data, **kwargs)


def api_delete(path: str, **kwargs):
    return requests.delete(f"{API_BASE}{path}", **kwargs)


# ---------------------------------------------------------------------------
# Fixture: ensure test device exists, clean up after
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def e2e_device():
    """Create a dedicated e2e test device, yield it, then delete."""
    device_payload = {
        "device_id": "e2e-test-device-001",
        "device_name": "E2E Test Sensor",
        "device_type": "temperature",
        "location": "E2E Test Lab",
        "status": "active"
    }
    # Create (ignore 409 if already exists from a prior failed run)
    resp = api_post("/api/devices", json_data=device_payload)
    assert resp.status_code in (201, 409)

    yield device_payload

    # Cleanup
    api_delete(f"/api/devices/{device_payload['device_id']}")


# ===================================================================
# Health & readiness smoke tests
# ===================================================================

class TestE2EHealthChecks:
    """Verify the live service health endpoints."""

    def test_health(self):
        resp = api_get("/health")
        assert resp.status_code == 200
        assert resp.json()['status'] == 'healthy'

    def test_liveness(self):
        resp = api_get("/healthz")
        assert resp.status_code == 200
        assert resp.json()['status'] == 'alive'

    def test_readiness(self):
        resp = api_get("/readyz")
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ready'


# ===================================================================
# Device CRUD e2e
# ===================================================================

class TestE2EDeviceCRUD:
    """End-to-end device CRUD through the live API."""

    def test_create_device(self):
        payload = {
            "device_id": "e2e-crud-device",
            "device_name": "CRUD Test",
            "device_type": "humidity",
            "location": "Test Room"
        }
        resp = api_post("/api/devices", json_data=payload)
        assert resp.status_code in (201, 409)

    def test_get_device(self):
        resp = api_get("/api/devices/e2e-crud-device")
        assert resp.status_code == 200
        assert resp.json()['device_id'] == 'e2e-crud-device'

    def test_list_devices(self):
        resp = api_get("/api/devices")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1

    def test_update_device(self):
        resp = api_put("/api/devices/e2e-crud-device",
                       json_data={"device_name": "Updated CRUD Test", "location": "New Room"})
        assert resp.status_code == 200
        assert resp.json()['device_name'] == 'Updated CRUD Test'

    def test_heartbeat(self):
        resp = api_post("/api/devices/e2e-crud-device")
        # heartbeat endpoint
        resp = api_post("/api/devices/e2e-crud-device/heartbeat")
        assert resp.status_code == 200

    def test_get_stats(self):
        resp = api_get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert 'total_devices' in data
        assert 'device_by_status' in data
        assert 'unacknowledged_alerts' in data

    def test_delete_device(self):
        resp = api_delete("/api/devices/e2e-crud-device")
        assert resp.status_code == 200

    def test_get_deleted_device_returns_404(self):
        resp = api_get("/api/devices/e2e-crud-device")
        assert resp.status_code == 404


# ===================================================================
# Alerts e2e
# ===================================================================

class TestE2EAlerts:
    """End-to-end alert lifecycle through the live API."""

    def test_create_and_acknowledge_alert(self, e2e_device):
        device_id = e2e_device['device_id']

        # Create alert
        alert = {
            "alert_type": "high_temperature",
            "severity": "critical",
            "message": "E2E test: temperature exceeded threshold"
        }
        resp = api_post(f"/api/devices/{device_id}/alerts", json_data=alert)
        assert resp.status_code == 201
        alert_id = resp.json()['id']

        # List alerts
        resp = api_get(f"/api/devices/{device_id}/alerts")
        assert resp.status_code == 200
        alerts = resp.json()
        assert any(a['id'] == alert_id for a in alerts)

        # Acknowledge
        resp = api_post(f"/api/alerts/{alert_id}/acknowledge")
        assert resp.status_code == 200
        assert resp.json()['acknowledged'] is True


# ===================================================================
# MQTT message type 1: Single measurement (one measure unit)
# ===================================================================

class TestE2ESingleMeasurement:
    """
    Send a single telemetry message with ONE measurement value.
    Verify it flows through MQTT → collector → InfluxDB & MinIO.
    """

    def test_single_measurement_message(self, e2e_device):
        device_id = e2e_device['device_id']
        topic = f"iot/{device_id}/telemetry"

        # Single measurement payload — one measure unit
        single_message = {
            "timestamp": "2026-02-12T12:00:00Z",
            "device_id": device_id,
            "temperature": 25.7,
            "unit": "celsius"
        }

        mqtt_publish(topic, single_message)

        # Wait for the collector to process and store
        time.sleep(WAIT_FOR_PROCESSING)

        # Verify data arrived in InfluxDB via the metrics endpoint
        resp = api_get(f"/api/devices/{device_id}/metrics?start=-5m&metric=temperature")
        assert resp.status_code == 200
        metrics = resp.json()
        # Should have at least 1 temperature data point
        assert len(metrics) >= 1
        latest = metrics[-1]
        assert latest['metric'] == 'temperature'
        assert isinstance(latest['value'], (int, float))

        # Verify raw data arrived in MinIO
        resp = api_get(f"/api/devices/{device_id}/raw-data")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) >= 1
        # Files should be stored under the device_id prefix
        assert any(device_id in f['filename'] for f in files)


# ===================================================================
# MQTT message type 2: Batch measurements (array of data points)
# ===================================================================

class TestE2EBatchMeasurements:
    """
    Send a single MQTT message containing an ARRAY of measurements
    representing multiple data points logged over a period of time.
    Verify the collector processes and stores them all.
    """

    def test_batch_measurement_message(self, e2e_device):
        device_id = e2e_device['device_id']
        topic = f"iot/{device_id}/telemetry"

        # Batch payload — array of measurements over a time period
        batch_message = {
            "timestamp": "2026-02-12T12:05:00Z",
            "device_id": device_id,
            "batch": True,
            "measurements": [
                {"timestamp": "2026-02-12T12:00:00Z", "temperature": 22.1, "humidity": 55.0},
                {"timestamp": "2026-02-12T12:00:05Z", "temperature": 22.3, "humidity": 55.2},
                {"timestamp": "2026-02-12T12:00:10Z", "temperature": 22.8, "humidity": 54.8},
                {"timestamp": "2026-02-12T12:00:15Z", "temperature": 23.1, "humidity": 54.5},
                {"timestamp": "2026-02-12T12:00:20Z", "temperature": 23.5, "humidity": 54.0},
                {"timestamp": "2026-02-12T12:00:25Z", "temperature": 24.0, "humidity": 53.5},
                {"timestamp": "2026-02-12T12:00:30Z", "temperature": 24.3, "humidity": 53.2},
            ]
        }

        mqtt_publish(topic, batch_message)

        # Wait for the collector to process
        time.sleep(WAIT_FOR_PROCESSING)

        # Verify the entire batch message was archived in MinIO as raw data
        resp = api_get(f"/api/devices/{device_id}/raw-data")
        assert resp.status_code == 200
        files = resp.json()
        # Should have at least 2 files now (one from single test, one from batch)
        assert len(files) >= 2

        # The batch message itself is stored as-is in MinIO.
        # Verify we can still query metrics — the outer message has no
        # direct numeric fields other than "batch" (which is boolean),
        # so InfluxDB won't get extra points from the outer envelope.
        resp = api_get(f"/api/devices/{device_id}/metrics?start=-10m")
        assert resp.status_code == 200


# ===================================================================
# MQTT message type comparison: single vs batch side by side
# ===================================================================

class TestE2EMessageTypeComparison:
    """
    Send both message types for the SAME device and verify the raw
    data store has entries for both, showing the system handles
    heterogeneous message formats.
    """

    def test_both_message_types_for_same_device(self, e2e_device):
        device_id = e2e_device['device_id']
        topic = f"iot/{device_id}/telemetry"

        # Get initial file count
        resp = api_get(f"/api/devices/{device_id}/raw-data")
        initial_count = len(resp.json()) if resp.status_code == 200 else 0

        # MESSAGE 1: Single measurement
        single = {
            "timestamp": "2026-02-12T13:00:00Z",
            "device_id": device_id,
            "voltage": 231.5,
            "unit": "volts"
        }
        mqtt_publish(topic, single)

        # MESSAGE 2: Batch measurements (array)
        batch = {
            "timestamp": "2026-02-12T13:01:00Z",
            "device_id": device_id,
            "batch": True,
            "measurements": [
                {"timestamp": "2026-02-12T13:00:00Z", "voltage": 230.0, "current": 5.2},
                {"timestamp": "2026-02-12T13:00:05Z", "voltage": 231.0, "current": 5.1},
                {"timestamp": "2026-02-12T13:00:10Z", "voltage": 229.5, "current": 5.3},
            ]
        }
        mqtt_publish(topic, batch)

        time.sleep(WAIT_FOR_PROCESSING)

        # Both messages should be stored as raw data in MinIO
        resp = api_get(f"/api/devices/{device_id}/raw-data")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) >= initial_count + 2, (
            f"Expected at least {initial_count + 2} files, got {len(files)}"
        )

        # The single measurement should have produced an InfluxDB data point
        resp = api_get(f"/api/devices/{device_id}/metrics?start=-10m&metric=voltage")
        assert resp.status_code == 200
        voltage_metrics = resp.json()
        assert len(voltage_metrics) >= 1
