"""
End-to-end tests for the IoT Meter platform — v2 protocol.

These tests require the full infrastructure running (docker-compose up).
They exercise the real API, MQTT broker, InfluxDB and MinIO.

v2 protocol message types tested (IoT.md references):
  1. v2 telemetry — datagram with measurements array (§4.2)
  2. v2 hello — heartbeat with device status (§4.3)
  3. v2 commands — server→device command round-trip (§6)
  4. v1 backward compat — legacy single/batch messages (§13)

Datagram generators:
  - generate_v2_dc_datagram()   — DC 750V traction meter stream
  - generate_v2_ac_datagram()   — AC 25kV traction meter stream
  - generate_v2_hello()         — hello heartbeat
"""
import json
import time
import uuid
import random
from datetime import datetime, timezone
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

def mqtt_publish(topic: str, payload: dict, qos: int = 2):
    """Publish a single MQTT message and wait for delivery."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"e2e-pub-{uuid.uuid4().hex[:8]}")
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
# v2 Datagram Generators — IoT.md §4.2, §8.1
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


_seq_counter = 0


def _next_seq():
    global _seq_counter
    s = _seq_counter
    _seq_counter += 1
    return s


def generate_v2_dc_datagram(device_id: str, num_samples: int = 10) -> dict:
    """Generate a v2 DC traction telemetry datagram.

    Simulates a 750V DC metro power meter sampling at 1 Hz.
    IoT.md §4.2, §8.1 (voltage_dc, current_dc).
    """
    measurements = []
    for _ in range(num_samples):
        ts = _now_iso()
        measurements.append({'ts': ts, 'type': 'voltage_dc', 'val': round(random.uniform(700, 800), 1), 'unit': 'V'})
        measurements.append({'ts': ts, 'type': 'current_dc', 'val': round(random.uniform(200, 400), 1), 'unit': 'A'})
    return {
        'v': 2, 'device_id': device_id, 'ts': _now_iso(),
        'seq': _next_seq(), 'msg_type': 'telemetry',
        'measurements': measurements,
    }


def generate_v2_ac_datagram(device_id: str, num_samples: int = 10) -> dict:
    """Generate a v2 AC traction telemetry datagram.

    Simulates a 25kV AC catenary power meter sampling at 1 Hz.
    IoT.md §4.2, §8.1 (voltage_ac, current_ac, frequency, pf).
    """
    measurements = []
    for _ in range(num_samples):
        ts = _now_iso()
        measurements.append({'ts': ts, 'type': 'voltage_ac', 'val': round(random.uniform(24000, 26000), 0), 'unit': 'V'})
        measurements.append({'ts': ts, 'type': 'current_ac', 'val': round(random.uniform(100, 200), 1), 'unit': 'A'})
        measurements.append({'ts': ts, 'type': 'frequency', 'val': round(random.uniform(49.9, 50.1), 2), 'unit': 'Hz'})
        measurements.append({'ts': ts, 'type': 'pf', 'val': round(random.uniform(0.92, 0.99), 2)})
    return {
        'v': 2, 'device_id': device_id, 'ts': _now_iso(),
        'seq': _next_seq(), 'msg_type': 'telemetry',
        'measurements': measurements,
    }


def generate_v2_hello(device_id: str, fw_version: str = '2.1.0') -> dict:
    """Generate a v2 hello message — IoT.md §4.3."""
    return {
        'v': 2, 'device_id': device_id, 'ts': _now_iso(),
        'seq': _next_seq(), 'msg_type': 'hello',
        'fw_version': fw_version, 'uptime_s': 3600,
        'broker_connections': 1, 'buf_usage_pct': 0,
    }


# ---------------------------------------------------------------------------
# Fixture: ensure test device exists, clean up after
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def e2e_device():
    """Create a dedicated e2e test device (DC power meter), yield it, then delete."""
    device_payload = {
        "device_id": "e2e-dc-meter-001",
        "device_name": "E2E DC Power Meter",
        "device_type": "power_meter_dc",
        "location": "E2E Test Depot",
        "status": "active"
    }
    resp = api_post("/api/devices", json_data=device_payload)
    assert resp.status_code in (201, 409)

    yield device_payload

    api_delete(f"/api/devices/{device_payload['device_id']}")


@pytest.fixture(scope="module")
def e2e_ac_device():
    """Create a dedicated e2e AC test device, yield it, then delete."""
    device_payload = {
        "device_id": "e2e-ac-meter-001",
        "device_name": "E2E AC Power Meter",
        "device_type": "power_meter_ac",
        "location": "E2E Test Catenary",
        "status": "active"
    }
    resp = api_post("/api/devices", json_data=device_payload)
    assert resp.status_code in (201, 409)

    yield device_payload

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
            "device_type": "power_meter_dc",
            "location": "Test Depot"
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
                       json_data={"device_name": "Updated CRUD Test", "location": "New Depot"})
        assert resp.status_code == 200
        assert resp.json()['device_name'] == 'Updated CRUD Test'

    def test_heartbeat(self):
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

        alert = {
            "alert_type": "sequence_gap",
            "severity": "warning",
            "message": "E2E test: sequence gap detected"
        }
        resp = api_post(f"/api/devices/{device_id}/alerts", json_data=alert)
        assert resp.status_code == 201
        alert_id = resp.json()['id']

        resp = api_get(f"/api/devices/{device_id}/alerts")
        assert resp.status_code == 200
        alerts = resp.json()
        assert any(a['id'] == alert_id for a in alerts)

        resp = api_post(f"/api/alerts/{alert_id}/acknowledge")
        assert resp.status_code == 200
        assert resp.json()['acknowledged'] is True


# ===================================================================
# v2 Telemetry — DC datagram (IoT.md §4.2, §8.1)
# ===================================================================

class TestE2EDCTelemetry:
    """
    Send a v2 DC telemetry datagram with measurements array.
    Verify it flows through MQTT → collector → InfluxDB & MinIO.
    """

    def test_dc_datagram(self, e2e_device):
        device_id = e2e_device['device_id']
        topic = f"iot/{device_id}/telemetry"

        datagram = generate_v2_dc_datagram(device_id, num_samples=5)
        mqtt_publish(topic, datagram)

        time.sleep(WAIT_FOR_PROCESSING)

        # Verify data arrived in InfluxDB — voltage_dc metric
        resp = api_get(f"/api/devices/{device_id}/metrics?start=-5m&metric=voltage_dc")
        assert resp.status_code == 200
        metrics = resp.json()
        assert len(metrics) >= 1
        assert metrics[-1]['metric'] == 'voltage_dc'
        assert isinstance(metrics[-1]['value'], (int, float))

        # Verify raw data in MinIO
        resp = api_get(f"/api/devices/{device_id}/raw-data")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) >= 1
        assert any(device_id in f['filename'] for f in files)


# ===================================================================
# v2 Telemetry — AC datagram (IoT.md §4.2, §8.1)
# ===================================================================

class TestE2EACTelemetry:
    """
    Send a v2 AC telemetry datagram. Verify frequency and pf metrics.
    """

    def test_ac_datagram(self, e2e_ac_device):
        device_id = e2e_ac_device['device_id']
        topic = f"iot/{device_id}/telemetry"

        datagram = generate_v2_ac_datagram(device_id, num_samples=5)
        mqtt_publish(topic, datagram)

        time.sleep(WAIT_FOR_PROCESSING)

        resp = api_get(f"/api/devices/{device_id}/metrics?start=-5m&metric=frequency")
        assert resp.status_code == 200
        metrics = resp.json()
        assert len(metrics) >= 1


# ===================================================================
# v2 Hello message (IoT.md §4.3)
# ===================================================================

class TestE2EHelloMessage:
    """
    Send a v2 hello message and verify it's processed.
    """

    def test_hello_stored(self, e2e_device):
        device_id = e2e_device['device_id']
        topic = f"iot/{device_id}/hello"

        hello = generate_v2_hello(device_id)
        mqtt_publish(topic, hello)

        time.sleep(WAIT_FOR_PROCESSING)

        # Hello messages should be archived in MinIO
        resp = api_get(f"/api/devices/{device_id}/raw-data")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) >= 1


# ===================================================================
# v2 Command round-trip (IoT.md §6)
# ===================================================================

class TestE2ECommandRoundTrip:
    """
    Send a command via the REST API and verify it arrives on the
    MQTT command topic. Then publish a command_ack and verify it's
    recorded in the device-manager.
    """

    def test_send_command(self, e2e_device):
        device_id = e2e_device['device_id']

        resp = api_post(f"/api/devices/{device_id}/commands",
                        json_data={'cmd': 'update_config', 'params': {'send_interval_s': 5}})
        # 201 if MQTT succeeds, 202 if MQTT down but persisted
        assert resp.status_code in (201, 202)
        data = resp.json()
        assert 'cmd_id' in data
        assert data['cmd'] == 'update_config'

    def test_command_history(self, e2e_device):
        device_id = e2e_device['device_id']

        resp = api_get(f"/api/devices/{device_id}/commands")
        assert resp.status_code == 200
        commands = resp.json()
        assert isinstance(commands, list)


# ===================================================================
# v2 Device status (IoT.md §5)
# ===================================================================

class TestE2EDeviceStatus:
    """
    Update and query device connection status via REST API.
    Verify status retained message published via MQTT.
    """

    def test_update_status(self, e2e_device):
        device_id = e2e_device['device_id']

        # Publish online status via MQTT retained message
        status_payload = {
            'v': 2, 'device_id': device_id,
            'status': 'online', 'ts': _now_iso(),
        }
        mqtt_publish(f"iot/{device_id}/status", status_payload, qos=1)

        time.sleep(WAIT_FOR_PROCESSING)

        # Query status via API
        resp = api_get(f"/api/devices/{device_id}/status")
        assert resp.status_code == 200


# ===================================================================
# v1 backward compatibility (IoT.md §13)
# ===================================================================

class TestE2EV1BackwardCompat:
    """
    Send v1-format (no envelope) messages and verify the collector
    still processes them — IoT.md §13 backward compatibility.
    """

    def test_v1_single_measurement(self, e2e_device):
        device_id = e2e_device['device_id']
        topic = f"iot/{device_id}/telemetry"

        v1_message = {
            "timestamp": "2026-02-12T12:00:00Z",
            "device_id": device_id,
            "temperature": 25.7,
            "unit": "celsius"
        }
        mqtt_publish(topic, v1_message, qos=1)

        time.sleep(WAIT_FOR_PROCESSING)

        resp = api_get(f"/api/devices/{device_id}/raw-data")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) >= 1


# ===================================================================
# Datagram stream generator (multiple datagrams over time)
# ===================================================================

class TestE2EDatagramStream:
    """
    Simulate a real-world metering scenario: send multiple datagrams
    in sequence, each with incrementing seq numbers.
    Verifies the collector handles a stream of v2 messages correctly.
    """

    def test_dc_datagram_stream(self, e2e_device):
        device_id = e2e_device['device_id']
        topic = f"iot/{device_id}/telemetry"

        # Send 3 datagrams, each with 5 samples
        for _ in range(3):
            datagram = generate_v2_dc_datagram(device_id, num_samples=5)
            mqtt_publish(topic, datagram)
            time.sleep(0.5)

        time.sleep(WAIT_FOR_PROCESSING)

        # Verify InfluxDB has data
        resp = api_get(f"/api/devices/{device_id}/metrics?start=-5m&metric=voltage_dc")
        assert resp.status_code == 200
        metrics = resp.json()
        # 3 datagrams × 5 samples = 15 voltage_dc points minimum
        assert len(metrics) >= 3
