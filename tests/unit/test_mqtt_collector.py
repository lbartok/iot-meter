"""
Unit tests for the MQTT collector service.

All external dependencies (MQTT broker, MinIO, InfluxDB) are mocked.

These tests verify the v2 protocol features defined in IoT.md:
  - §2.2 Deduplication via (device_id, seq) — REQ-DEDUP-001
  - §3.1 Multi-topic subscription (telemetry, hello, status, command/ack, ota/status)
  - §4.2 v2 measurements array in telemetry
  - §5   Device last-seen tracking — REQ-ONLINE-001
  - §13  v1 backward compatibility

Any change to IoT.md MUST be reflected here and vice-versa.
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
        """v1 telemetry message on iot/+/telemetry is routed to handle_telemetry."""
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()

        # Mock handlers
        collector.handle_telemetry = MagicMock()

        msg = MagicMock()
        msg.topic = 'iot/device-001/telemetry'
        msg.payload = json.dumps({"temperature": 23.5}).encode('utf-8')

        collector.on_message(MagicMock(), None, msg)

        collector.handle_telemetry.assert_called_once_with('device-001', {"temperature": 23.5})

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

        collector.store_to_minio('device-001', {"temperature": 23.5}, 'telemetry')
        mock_minio_instance.put_object.assert_called_once()
        call_kwargs = mock_minio_instance.put_object.call_args
        assert call_kwargs[0][0] == 'iot-data'  # bucket name
        assert 'device-001/' in call_kwargs[0][1]  # filename prefix
        assert 'telemetry/' in call_kwargs[0][1]  # category subfolder

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


# ===================================================================
# v2 Topic Subscriptions — IoT.md §3.1
# ===================================================================

class TestV2TopicSubscriptions:
    """Tests that on_connect subscribes to all v2 topics (IoT.md §3.1)."""

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_on_connect_subscribes_all_v2_topics(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector, V2_TOPIC_SUBSCRIPTIONS
        collector = MQTTCollector()

        mock_client = MagicMock()
        collector.on_connect(mock_client, None, None, 0, None)

        # Should subscribe to ALL v2 topics
        assert mock_client.subscribe.call_count == len(V2_TOPIC_SUBSCRIPTIONS)
        subscribed_topics = [call[0][0] for call in mock_client.subscribe.call_args_list]
        for topic in V2_TOPIC_SUBSCRIPTIONS:
            assert topic in subscribed_topics


# ===================================================================
# v2 Message Routing — IoT.md §3.1
# ===================================================================

class TestV2MessageRouting:
    """Tests that on_message routes messages to the correct handler."""

    def _make_collector(self, mock_minio, mock_influx, mock_mqtt_cls):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        collector.handle_telemetry = MagicMock()
        collector.handle_hello = MagicMock()
        collector.handle_status = MagicMock()
        collector.handle_command_ack = MagicMock()
        collector.handle_ota_status = MagicMock()
        return collector

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_route_hello(self, mock_mqtt_cls, mock_influx, mock_minio):
        """iot/+/hello → handle_hello (IoT.md §4.3)."""
        collector = self._make_collector(mock_minio, mock_influx, mock_mqtt_cls)

        msg = MagicMock()
        msg.topic = 'iot/dc-meter-007/hello'
        msg.payload = json.dumps({
            "v": 2, "device_id": "dc-meter-007", "seq": 1, "msg_type": "hello",
            "fw_version": "2.1.0", "uptime_s": 100, "broker_connections": 1, "buf_usage_pct": 5
        }).encode()
        collector.on_message(MagicMock(), None, msg)
        collector.handle_hello.assert_called_once()

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_route_status(self, mock_mqtt_cls, mock_influx, mock_minio):
        """iot/+/status → handle_status (IoT.md §3.4)."""
        collector = self._make_collector(mock_minio, mock_influx, mock_mqtt_cls)

        msg = MagicMock()
        msg.topic = 'iot/dc-meter-007/status'
        msg.payload = json.dumps({
            "v": 2, "device_id": "dc-meter-007", "status": "online"
        }).encode()
        collector.on_message(MagicMock(), None, msg)
        collector.handle_status.assert_called_once()

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_route_command_ack(self, mock_mqtt_cls, mock_influx, mock_minio):
        """iot/+/command/ack → handle_command_ack (IoT.md §6.5)."""
        collector = self._make_collector(mock_minio, mock_influx, mock_mqtt_cls)

        msg = MagicMock()
        msg.topic = 'iot/dc-meter-007/command/ack'
        msg.payload = json.dumps({
            "v": 2, "device_id": "dc-meter-007", "seq": 5, "msg_type": "command_ack",
            "cmd_id": "test-cmd-id", "result": "accepted"
        }).encode()
        collector.on_message(MagicMock(), None, msg)
        collector.handle_command_ack.assert_called_once()

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_route_ota_status(self, mock_mqtt_cls, mock_influx, mock_minio):
        """iot/+/ota/status → handle_ota_status (IoT.md §7.2)."""
        collector = self._make_collector(mock_minio, mock_influx, mock_mqtt_cls)

        msg = MagicMock()
        msg.topic = 'iot/dc-meter-007/ota/status'
        msg.payload = json.dumps({
            "v": 2, "device_id": "dc-meter-007", "seq": 10, "msg_type": "ota_status",
            "cmd_id": "ota-id", "ota_state": "downloading", "progress_pct": 50
        }).encode()
        collector.on_message(MagicMock(), None, msg)
        collector.handle_ota_status.assert_called_once()


# ===================================================================
# v2 Deduplication — IoT.md §2.2 / REQ-DEDUP-001
# ===================================================================

class TestV2Deduplication:
    """Tests for sequence-based deduplication.

    See IoT.md §2.2 — messages with same (device_id, seq) must be dropped.
    Gap detection must log warnings.
    """

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_first_message_not_duplicate(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        assert collector.is_duplicate('dc-meter-007', 0) is False

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_sequential_not_duplicate(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        assert collector.is_duplicate('dc-meter-007', 0) is False
        assert collector.is_duplicate('dc-meter-007', 1) is False
        assert collector.is_duplicate('dc-meter-007', 2) is False

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_duplicate_detected(self, mock_mqtt_cls, mock_influx, mock_minio):
        """Same seq number must be identified as duplicate (REQ-DEDUP-001)."""
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        assert collector.is_duplicate('dc-meter-007', 5) is False
        assert collector.is_duplicate('dc-meter-007', 5) is True  # exact duplicate

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_out_of_order_duplicate(self, mock_mqtt_cls, mock_influx, mock_minio):
        """seq < last_seen → treated as duplicate/out-of-order."""
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        assert collector.is_duplicate('dc-meter-007', 10) is False
        assert collector.is_duplicate('dc-meter-007', 8) is True  # out of order

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_gap_detection(self, mock_mqtt_cls, mock_influx, mock_minio):
        """Sequence gap is detected but message is still accepted."""
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        assert collector.is_duplicate('dc-meter-007', 0) is False
        # Jump from 0 to 5 — gap of 4
        assert collector.is_duplicate('dc-meter-007', 5) is False
        # Tracker should now be at 5
        assert collector._seq_tracker['dc-meter-007'] == 5

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_v1_no_seq_never_deduped(self, mock_mqtt_cls, mock_influx, mock_minio):
        """v1 messages with seq=-1 or None should never be deduplicated (IoT.md §13)."""
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        assert collector.is_duplicate('device-001', None) is False
        assert collector.is_duplicate('device-001', -1) is False
        assert collector.is_duplicate('device-001', None) is False  # still not duplicate

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_different_devices_independent_seq(self, mock_mqtt_cls, mock_influx, mock_minio):
        """Each device has independent seq tracking."""
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        assert collector.is_duplicate('meter-A', 0) is False
        assert collector.is_duplicate('meter-B', 0) is False  # different device, same seq OK
        assert collector.is_duplicate('meter-A', 0) is True   # same device, same seq → dupe


# ===================================================================
# v2 InfluxDB storage with measurements array — IoT.md §4.2
# ===================================================================

class TestV2InfluxDBStorage:
    """Tests for v2 telemetry storage in InfluxDB."""

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_store_v2_measurements_array(self, mock_mqtt_cls, mock_influx_cls, mock_minio):
        """v2 datagram with measurements array writes one point per measurement."""
        mock_minio.return_value.bucket_exists.return_value = True
        mock_write_api = MagicMock()
        mock_influx_cls.return_value.write_api.return_value = mock_write_api

        from collector import MQTTCollector
        collector = MQTTCollector()

        data = {
            "v": 2, "device_id": "dc-meter-007", "ts": "2026-02-12T10:00:10Z",
            "seq": 42, "msg_type": "telemetry",
            "measurements": [
                {"ts": "2026-02-12T10:00:01Z", "type": "voltage_dc", "val": 756.3, "unit": "V"},
                {"ts": "2026-02-12T10:00:01Z", "type": "current_dc", "val": 312.8, "unit": "A"},
                {"ts": "2026-02-12T10:00:02Z", "type": "voltage_dc", "val": 754.1, "unit": "V"},
            ]
        }
        collector.store_to_influxdb('dc-meter-007', data)
        assert mock_write_api.write.call_count == 3

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_store_v1_fallback(self, mock_mqtt_cls, mock_influx_cls, mock_minio):
        """v1 flat key/value message uses fallback storage (IoT.md §13)."""
        mock_minio.return_value.bucket_exists.return_value = True
        mock_write_api = MagicMock()
        mock_influx_cls.return_value.write_api.return_value = mock_write_api

        from collector import MQTTCollector
        collector = MQTTCollector()

        data = {"timestamp": "2026-02-12T10:00:00", "temperature": 23.5, "humidity": 60.0}
        collector.store_to_influxdb('device-001', data)
        assert mock_write_api.write.call_count == 2


# ===================================================================
# v2 Last-seen tracking — IoT.md §5 / REQ-ONLINE-001
# ===================================================================

class TestLastSeenTracking:
    """Tests that any incoming message updates device last_seen."""

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_telemetry_updates_last_seen(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        collector.handle_telemetry = MagicMock()

        msg = MagicMock()
        msg.topic = 'iot/dc-meter-007/telemetry'
        msg.payload = json.dumps({"v": 2, "device_id": "dc-meter-007", "seq": 0, "msg_type": "telemetry", "measurements": []}).encode()

        collector.on_message(MagicMock(), None, msg)
        assert 'dc-meter-007' in collector._device_last_seen

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_hello_updates_last_seen(self, mock_mqtt_cls, mock_influx, mock_minio):
        mock_minio.return_value.bucket_exists.return_value = True
        from collector import MQTTCollector
        collector = MQTTCollector()
        collector.handle_hello = MagicMock()

        msg = MagicMock()
        msg.topic = 'iot/dc-meter-007/hello'
        msg.payload = json.dumps({
            "v": 2, "device_id": "dc-meter-007", "seq": 1, "msg_type": "hello",
            "fw_version": "2.1.0", "uptime_s": 100, "broker_connections": 1, "buf_usage_pct": 5
        }).encode()

        collector.on_message(MagicMock(), None, msg)
        assert 'dc-meter-007' in collector._device_last_seen
