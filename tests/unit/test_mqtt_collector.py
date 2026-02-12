"""
Unit tests for the MQTT collector service.

All external dependencies (MQTT broker, MinIO, InfluxDB) are mocked.
"""
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from io import BytesIO


pytestmark = pytest.mark.unit


# ===================================================================
# Health endpoints
# ===================================================================

class TestCollectorHealthEndpoints:
    """Tests for /healthz and /readyz on the collector health app."""

    def test_liveness(self, collector_health_client):
        resp = collector_health_client.get('/healthz')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'alive'
        assert data['service'] == 'mqtt-collector'

    @patch('collector.collector_instance', None)
    def test_readiness_no_instance(self, collector_health_client):
        resp = collector_health_client.get('/readyz')
        assert resp.status_code == 503

    def test_readiness_not_ready(self, collector_health_client):
        import collector as col_mod
        mock_collector = MagicMock()
        mock_collector.is_ready.return_value = False
        original = col_mod.collector_instance
        col_mod.collector_instance = mock_collector
        try:
            resp = collector_health_client.get('/readyz')
            assert resp.status_code == 503
        finally:
            col_mod.collector_instance = original

    def test_readiness_ready(self, collector_health_client):
        import collector as col_mod
        mock_collector = MagicMock()
        mock_collector.is_ready.return_value = True
        original = col_mod.collector_instance
        col_mod.collector_instance = mock_collector
        try:
            resp = collector_health_client.get('/readyz')
            assert resp.status_code == 200
            assert resp.get_json()['status'] == 'ready'
        finally:
            col_mod.collector_instance = original


# ===================================================================
# MQTTCollector class
# ===================================================================

class TestMQTTCollectorInit:
    """Tests for MQTTCollector initialization."""

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_init_sets_defaults(self, mock_mqtt, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        assert collector.mqtt_broker == 'localhost'
        assert collector.mqtt_port == 1883
        assert collector.minio_ready is True
        assert collector.influxdb_ready is True
        assert collector.mqtt_connected is False

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_is_ready_all_connected(self, mock_mqtt, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        collector.mqtt_connected = True
        assert collector.is_ready() is True

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_is_ready_mqtt_not_connected(self, mock_mqtt, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        collector.mqtt_connected = False
        assert collector.is_ready() is False


class TestMQTTCollectorCallbacks:
    """Tests for MQTT callback methods."""

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_on_connect_success(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()

        mock_client = MagicMock()
        collector.on_connect(mock_client, None, None, 0, None)
        assert collector.mqtt_connected is True
        mock_client.subscribe.assert_called_once()

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_on_connect_failure(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()

        collector.on_connect(MagicMock(), None, None, 1, None)
        assert collector.mqtt_connected is False

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_on_disconnect(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        collector.mqtt_connected = True

        collector.on_disconnect(MagicMock(), None, None, 0, None)
        assert collector.mqtt_connected is False


class TestMQTTCollectorMessageProcessing:
    """Tests for on_message and storage methods."""

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_on_message_parses_topic_and_payload(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()

        # Mock storage methods
        collector.store_to_minio = MagicMock()
        collector.store_to_influxdb = MagicMock()

        msg = MagicMock()
        msg.topic = 'iot/device-001/telemetry'
        msg.payload = json.dumps({"temperature": 23.5}).encode('utf-8')

        collector.on_message(MagicMock(), None, msg)

        collector.store_to_minio.assert_called_once_with('device-001', {"temperature": 23.5})
        collector.store_to_influxdb.assert_called_once_with('device-001', {"temperature": 23.5})

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_on_message_invalid_json(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()

        msg = MagicMock()
        msg.topic = 'iot/device-001/telemetry'
        msg.payload = b'not-json'

        # Should not raise — just logs error
        collector.on_message(MagicMock(), None, msg)

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_store_to_minio(self, mock_mqtt_cls, mock_influx, mock_minio_cls):
        mock_minio_instance = MagicMock()
        mock_minio_cls.return_value = mock_minio_instance
        mock_minio_instance.bucket_exists.return_value = True

        from collector import MQTTCollector
        collector = MQTTCollector()

        collector.store_to_minio('device-001', {"temperature": 23.5})
        mock_minio_instance.put_object.assert_called_once()
        call_kwargs = mock_minio_instance.put_object.call_args
        assert call_kwargs[0][0] == 'iot-data'  # bucket name
        assert 'device-001/' in call_kwargs[0][1]  # filename prefix

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_store_to_influxdb_numeric_values(self, mock_mqtt_cls, mock_influx_cls, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        mock_write_api = MagicMock()
        mock_influx_cls.return_value.write_api.return_value = mock_write_api

        from collector import MQTTCollector
        collector = MQTTCollector()

        data = {"timestamp": "2026-02-12T10:00:00", "temperature": 23.5, "humidity": 60.0, "unit": "celsius"}
        collector.store_to_influxdb('device-001', data)

        # Should write 2 points (temperature + humidity), not 'unit' (string) or 'timestamp'
        assert mock_write_api.write.call_count == 2

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_store_to_influxdb_no_numeric_values(self, mock_mqtt_cls, mock_influx_cls, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        mock_write_api = MagicMock()
        mock_influx_cls.return_value.write_api.return_value = mock_write_api

        from collector import MQTTCollector
        collector = MQTTCollector()

        data = {"timestamp": "2026-02-12T10:00:00", "status": "online"}
        collector.store_to_influxdb('device-001', data)
        mock_write_api.write.assert_not_called()
