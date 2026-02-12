"""
Shared pytest fixtures for all test suites.

These fixtures provide v2 payloads per IoT.md v2 requirements.
Any change to IoT.md MUST be reflected here and vice-versa.
"""
import sys
import os
import json
import time
import uuid
import pytest

# Add service directories to path so we can import them
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'device-manager'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'mqtt-collector'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'iot-device-simulator'))


# ---------------------------------------------------------------------------
# Device-manager fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dm_app():
    """Create device-manager Flask app for testing."""
    from app import app
    app.config['TESTING'] = True
    return app


@pytest.fixture
def dm_client(dm_app):
    """Create device-manager Flask test client."""
    return dm_app.test_client()


# ---------------------------------------------------------------------------
# MQTT-collector health-app fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def collector_health_app():
    """Create mqtt-collector health Flask app for testing."""
    from collector import health_app
    health_app.config['TESTING'] = True
    return health_app


@pytest.fixture
def collector_health_client(collector_health_app):
    """Create mqtt-collector health Flask test client."""
    return collector_health_app.test_client()


# ---------------------------------------------------------------------------
# Simulator health-app fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simulator_health_app():
    """Create simulator health Flask app for testing."""
    from simulator import health_app
    health_app.config['TESTING'] = True
    return health_app


@pytest.fixture
def simulator_health_client(simulator_health_app):
    """Create simulator health Flask test client."""
    return simulator_health_app.test_client()


# ---------------------------------------------------------------------------
# Sample data helpers — v2 payloads (IoT.md §4, §6, §11)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_device():
    """Return a sample v2 DC power meter device payload — IoT.md §11."""
    return {
        "device_id": "test-dc-meter-001",
        "device_name": "DC Traction Meter — Test Train",
        "device_type": "power_meter_dc",
        "location": "Test Train / Car 1 / Main DC Bus",
        "status": "active",
        "metadata": json.dumps({
            "voltage_system": "DC 750V",
            "voltage_range": "0-1000V",
            "current_range": "0-2000A",
            "accuracy_class": "0.5R",
            "sampling_cadence_ms": 1000,
            "send_interval_s": 10,
            "hello_interval_s": 30,
            "brokers": [{"host": "localhost", "port": 1883}]
        })
    }


@pytest.fixture
def sample_alert():
    """Return a sample alert payload."""
    return {
        "alert_type": "sequence_gap",
        "severity": "warning",
        "message": "Sequence gap detected: expected seq 42, got 45 (gap=3)"
    }


@pytest.fixture
def single_telemetry_message():
    """Single measurement telemetry message — v1 backward compat (IoT.md §13)."""
    return {
        "timestamp": "2026-02-12T10:00:00",
        "device_id": "test-dc-meter-001",
        "temperature": 23.5,
        "unit": "celsius"
    }


@pytest.fixture
def batch_telemetry_message():
    """Batch telemetry message — v1 backward compat (IoT.md §13)."""
    return {
        "device_id": "test-dc-meter-001",
        "batch": True,
        "measurements": [
            {"timestamp": "2026-02-12T10:00:00", "temperature": 22.1},
            {"timestamp": "2026-02-12T10:00:05", "temperature": 22.3},
            {"timestamp": "2026-02-12T10:00:10", "temperature": 22.8},
            {"timestamp": "2026-02-12T10:00:15", "temperature": 23.1},
            {"timestamp": "2026-02-12T10:00:20", "temperature": 23.5},
        ]
    }


# ---------------------------------------------------------------------------
# v2 payload fixtures (IoT.md §4)
# ---------------------------------------------------------------------------

@pytest.fixture
def v2_telemetry_dc():
    """v2 DC telemetry datagram — IoT.md §4.2 / §12.1.

    10-second window, 1-second sampling cadence → 10 voltage + 10 current = 20 measurements.
    """
    measurements = []
    for second in range(1, 11):
        ts = f"2026-02-12T10:00:{second:02d}Z"
        measurements.append({'ts': ts, 'type': 'voltage_dc', 'val': round(750 + second * 0.5, 1), 'unit': 'V'})
        measurements.append({'ts': ts, 'type': 'current_dc', 'val': round(300 + second * 1.2, 1), 'unit': 'A'})
    return {
        "v": 2,
        "device_id": "test-dc-meter-001",
        "ts": "2026-02-12T10:00:10Z",
        "seq": 42,
        "msg_type": "telemetry",
        "measurements": measurements,
    }


@pytest.fixture
def v2_telemetry_ac():
    """v2 AC telemetry datagram — IoT.md §4.2 / §12.2.

    AC 25kV system with voltage, current, frequency, and power factor.
    """
    measurements = []
    for second in range(1, 4):
        ts = f"2026-02-12T10:00:{second:02d}Z"
        measurements.append({'ts': ts, 'type': 'voltage_ac', 'val': round(25000 + second * 10, 0), 'unit': 'V'})
        measurements.append({'ts': ts, 'type': 'current_ac', 'val': round(140 + second * 2, 1), 'unit': 'A'})
        measurements.append({'ts': ts, 'type': 'frequency', 'val': round(50.0 + second * 0.01, 2), 'unit': 'Hz'})
        measurements.append({'ts': ts, 'type': 'pf', 'val': round(0.96 + second * 0.005, 3)})
    return {
        "v": 2,
        "device_id": "test-ac-meter-001",
        "ts": "2026-02-12T10:00:03Z",
        "seq": 87,
        "msg_type": "telemetry",
        "measurements": measurements,
    }


@pytest.fixture
def v2_hello():
    """v2 hello message — IoT.md §4.3 / §12.3."""
    return {
        "v": 2,
        "device_id": "test-dc-meter-001",
        "ts": "2026-02-12T10:00:30Z",
        "seq": 45,
        "msg_type": "hello",
        "fw_version": "2.1.0",
        "uptime_s": 86400,
        "broker_connections": 2,
        "buf_usage_pct": 5,
        "temp_internal": 38.2,
    }


@pytest.fixture
def v2_status_online():
    """v2 online status message — IoT.md §3.4 / §12.6."""
    return {
        "v": 2,
        "device_id": "test-dc-meter-001",
        "ts": "2026-02-12T10:00:00Z",
        "status": "online",
    }


@pytest.fixture
def v2_status_offline():
    """v2 offline status message (LWT) — IoT.md §3.4 / §12.7."""
    return {
        "v": 2,
        "device_id": "test-dc-meter-001",
        "ts": "2026-02-12T09:55:00Z",
        "status": "offline",
    }


@pytest.fixture
def v2_command_update_config():
    """v2 update_config command — IoT.md §6.3 / §12.4."""
    return {
        "v": 2,
        "cmd_id": "a3f7c2e1-9b4d-4e8a-b6f1-2d3e4f5a6b7c",
        "ts": "2026-02-12T10:05:00Z",
        "cmd": "update_config",
        "params": {
            "sampling_cadence_ms": 1000,
            "send_interval_s": 5,
            "hello_interval_s": 30,
        }
    }


@pytest.fixture
def v2_command_start_ota():
    """v2 start_ota command — IoT.md §6.4."""
    return {
        "v": 2,
        "cmd_id": "b4e8f1a2-3c5d-6e7f-8a9b-0c1d2e3f4a5b",
        "ts": "2026-02-12T11:00:00Z",
        "cmd": "start_ota",
        "params": {
            "fw_version": "2.2.0",
            "fw_url": "https://ota.example.com/firmware/dc-meter/2.2.0.bin",
            "fw_sha256": "e3b0c44298fc1c149afbf4c8996fb924",
            "fw_size_bytes": 524288,
        }
    }


@pytest.fixture
def v2_command_ack():
    """v2 command acknowledgement — IoT.md §6.5 / §12.5."""
    return {
        "v": 2,
        "device_id": "test-dc-meter-001",
        "ts": "2026-02-12T10:05:01Z",
        "seq": 50,
        "msg_type": "command_ack",
        "cmd_id": "a3f7c2e1-9b4d-4e8a-b6f1-2d3e4f5a6b7c",
        "result": "accepted",
        "detail": "send_interval_s updated to 5",
    }


@pytest.fixture
def v2_ota_status():
    """v2 OTA status message — IoT.md §7.2."""
    return {
        "v": 2,
        "device_id": "test-dc-meter-001",
        "ts": "2026-02-12T11:00:30Z",
        "seq": 200,
        "msg_type": "ota_status",
        "cmd_id": "b4e8f1a2-3c5d-6e7f-8a9b-0c1d2e3f4a5b",
        "ota_state": "downloading",
        "progress_pct": 50,
        "fw_version_target": "2.2.0",
    }
