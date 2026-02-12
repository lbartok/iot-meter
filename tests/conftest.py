"""
Shared pytest fixtures for all test suites.
"""
import sys
import os
import json
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
# Sample data helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_device():
    """Return a sample device payload."""
    return {
        "device_id": "test-device-001",
        "device_name": "Test Temperature Sensor",
        "device_type": "temperature",
        "location": "Test Lab Room 1",
        "status": "active",
        "metadata": '{"sampling_rate": "5s", "unit": "celsius"}'
    }


@pytest.fixture
def sample_alert():
    """Return a sample alert payload."""
    return {
        "alert_type": "high_temperature",
        "severity": "warning",
        "message": "Temperature exceeded 30°C threshold"
    }


@pytest.fixture
def single_telemetry_message():
    """Single measurement telemetry message (one measure unit)."""
    return {
        "timestamp": "2026-02-12T10:00:00",
        "device_id": "test-device-001",
        "temperature": 23.5,
        "unit": "celsius"
    }


@pytest.fixture
def batch_telemetry_message():
    """Batch telemetry message — an array of measurements over a time period."""
    return {
        "device_id": "test-device-001",
        "batch": True,
        "measurements": [
            {"timestamp": "2026-02-12T10:00:00", "temperature": 22.1},
            {"timestamp": "2026-02-12T10:00:05", "temperature": 22.3},
            {"timestamp": "2026-02-12T10:00:10", "temperature": 22.8},
            {"timestamp": "2026-02-12T10:00:15", "temperature": 23.1},
            {"timestamp": "2026-02-12T10:00:20", "temperature": 23.5},
        ]
    }
