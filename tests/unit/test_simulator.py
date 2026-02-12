"""
Unit tests for the IoT device simulator service.

All external dependencies (MQTT broker) are mocked.
"""
import json
import pytest
from unittest.mock import patch, MagicMock


pytestmark = pytest.mark.unit


# ===================================================================
# Health endpoints
# ===================================================================

class TestSimulatorHealthEndpoints:
    """Tests for /healthz and /readyz on the simulator health app."""

    def test_liveness(self, simulator_health_client):
        resp = simulator_health_client.get('/healthz')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'alive'
        assert data['service'] == 'iot-device-simulator'

    def test_readiness_not_ready(self, simulator_health_client):
        import simulator as sim_mod
        original = sim_mod.simulator_ready
        sim_mod.simulator_ready = False
        try:
            resp = simulator_health_client.get('/readyz')
            assert resp.status_code == 503
            assert resp.get_json()['status'] == 'not ready'
        finally:
            sim_mod.simulator_ready = original

    def test_readiness_ready(self, simulator_health_client):
        import simulator as sim_mod
        original = sim_mod.simulator_ready
        sim_mod.simulator_ready = True
        try:
            resp = simulator_health_client.get('/readyz')
            assert resp.status_code == 200
            assert resp.get_json()['status'] == 'ready'
        finally:
            sim_mod.simulator_ready = original


# ===================================================================
# IoTDeviceSimulator class
# ===================================================================

class TestSimulatorInit:
    """Tests for IoTDeviceSimulator initialization."""

    @patch('simulator.mqtt.Client')
    def test_init(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'temperature')
        assert sim.device_id == 'dev-001'
        assert sim.device_type == 'temperature'
        assert sim.mqtt_topic == 'iot/dev-001/telemetry'
        assert sim.connected is False


class TestTelemetryGeneration:
    """Tests for generate_telemetry method."""

    @patch('simulator.mqtt.Client')
    def test_generate_temperature(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'temperature')
        data = sim.generate_telemetry()
        assert 'timestamp' in data
        assert 'device_id' in data
        assert 'temperature' in data
        assert data['unit'] == 'celsius'
        assert 18.0 <= data['temperature'] <= 28.0

    @patch('simulator.mqtt.Client')
    def test_generate_humidity(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'humidity')
        data = sim.generate_telemetry()
        assert 'humidity' in data
        assert data['unit'] == 'percentage'
        assert 30.0 <= data['humidity'] <= 80.0

    @patch('simulator.mqtt.Client')
    def test_generate_power(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'power')
        data = sim.generate_telemetry()
        assert 'voltage' in data
        assert 'current' in data
        assert 'power' in data
        assert data['unit'] == 'watts'

    @patch('simulator.mqtt.Client')
    def test_generate_generic(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'generic')
        data = sim.generate_telemetry()
        assert 'value' in data
        assert 0.0 <= data['value'] <= 100.0


class TestPublishTelemetry:
    """Tests for publish_telemetry method."""

    @patch('simulator.mqtt.Client')
    def test_publish_when_connected(self, mock_mqtt_cls):
        from simulator import IoTDeviceSimulator
        import paho.mqtt.client as mqtt
        sim = IoTDeviceSimulator('dev-001', 'temperature')
        sim.connected = True

        mock_result = MagicMock()
        mock_result.rc = mqtt.MQTT_ERR_SUCCESS
        sim.mqtt_client.publish.return_value = mock_result

        sim.publish_telemetry()
        sim.mqtt_client.publish.assert_called_once()
        call_args = sim.mqtt_client.publish.call_args
        assert call_args[0][0] == 'iot/dev-001/telemetry'
        # Verify the payload is valid JSON
        payload = json.loads(call_args[0][1])
        assert 'temperature' in payload

    @patch('simulator.mqtt.Client')
    def test_publish_when_disconnected(self, mock_mqtt_cls):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'temperature')
        sim.connected = False

        sim.publish_telemetry()
        sim.mqtt_client.publish.assert_not_called()


class TestSimulatorCallbacks:
    """Tests for MQTT callback methods."""

    @patch('simulator.mqtt.Client')
    def test_on_connect_success(self, mock_mqtt_cls):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'temperature')
        sim.on_connect(MagicMock(), None, None, 0, None)
        assert sim.connected is True

    @patch('simulator.mqtt.Client')
    def test_on_connect_failure(self, mock_mqtt_cls):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'temperature')
        sim.on_connect(MagicMock(), None, None, 1, None)
        assert sim.connected is False

    @patch('simulator.mqtt.Client')
    def test_on_disconnect(self, mock_mqtt_cls):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'temperature')
        sim.connected = True
        sim.on_disconnect(MagicMock(), None, None, 0, None)
        assert sim.connected is False
