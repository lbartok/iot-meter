"""
Integration tests for the device-manager API.

These tests exercise the full request → DB → response path by mocking
only the outermost database connection boundary. The Flask app, routing,
request parsing, and JSON serialisation are all exercised for real.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from psycopg2 import IntegrityError


pytestmark = pytest.mark.integration


class TestDeviceCRUDWorkflow:
    """Full CRUD workflow integration test through the Flask test client."""

    @patch('app.get_db_connection')
    def test_full_device_lifecycle(self, mock_conn, dm_client):
        """Create → Read → Update → Heartbeat → Delete a device."""
        mock_cursor = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cursor

        # 1. CREATE
        device_payload = {
            "device_id": "integ-001",
            "device_name": "Integration Sensor",
            "device_type": "temperature",
            "location": "Lab A",
            "status": "active"
        }
        created_row = {**device_payload, 'id': 1, 'created_at': '2026-02-12', 'updated_at': '2026-02-12'}
        mock_cursor.fetchone.return_value = created_row

        resp = dm_client.post('/api/devices',
                              data=json.dumps(device_payload),
                              content_type='application/json')
        assert resp.status_code == 201
        created = resp.get_json()
        assert created['device_id'] == 'integ-001'

        # 2. READ
        mock_cursor.fetchone.return_value = created_row
        resp = dm_client.get('/api/devices/integ-001')
        assert resp.status_code == 200
        assert resp.get_json()['device_name'] == 'Integration Sensor'

        # 3. UPDATE
        updated_row = {**created_row, 'device_name': 'Updated Sensor', 'location': 'Lab B'}
        mock_cursor.fetchone.return_value = updated_row
        resp = dm_client.put('/api/devices/integ-001',
                             data=json.dumps({"device_name": "Updated Sensor", "location": "Lab B"}),
                             content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['device_name'] == 'Updated Sensor'
        assert resp.get_json()['location'] == 'Lab B'

        # 4. HEARTBEAT
        mock_cursor.fetchone.return_value = {'device_id': 'integ-001'}
        resp = dm_client.post('/api/devices/integ-001/heartbeat')
        assert resp.status_code == 200

        # 5. DELETE
        mock_cursor.fetchone.return_value = {'device_id': 'integ-001'}
        resp = dm_client.delete('/api/devices/integ-001')
        assert resp.status_code == 200


class TestAlertWorkflow:
    """Full alert workflow integration test."""

    @patch('app.get_db_connection')
    def test_create_and_acknowledge_alert(self, mock_conn, dm_client):
        """Create alert → List alerts → Acknowledge alert."""
        mock_cursor = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cursor

        # 1. Create alert
        alert_payload = {
            "alert_type": "high_temperature",
            "severity": "critical",
            "message": "Temperature exceeded safe limits"
        }
        created_alert = {
            'id': 42, 'device_id': 'device-001',
            **alert_payload, 'acknowledged': False,
            'created_at': '2026-02-12'
        }
        mock_cursor.fetchone.return_value = created_alert

        resp = dm_client.post('/api/devices/device-001/alerts',
                              data=json.dumps(alert_payload),
                              content_type='application/json')
        assert resp.status_code == 201
        alert_id = resp.get_json()['id']

        # 2. List alerts
        mock_cursor.fetchall.return_value = [created_alert]
        resp = dm_client.get('/api/devices/device-001/alerts')
        assert resp.status_code == 200
        alerts = resp.get_json()
        assert len(alerts) == 1
        assert alerts[0]['acknowledged'] is False

        # 3. Acknowledge alert
        acked_alert = {**created_alert, 'acknowledged': True}
        mock_cursor.fetchone.return_value = acked_alert
        resp = dm_client.post(f'/api/alerts/{alert_id}/acknowledge')
        assert resp.status_code == 200
        assert resp.get_json()['acknowledged'] is True


class TestMetricsAndRawDataIntegration:
    """Integration tests for metrics and raw-data endpoints."""

    @patch('app.get_influx_client')
    def test_metrics_returns_structured_data(self, mock_influx, dm_client):
        """Query metrics with time range and verify response structure."""
        mock_record1 = MagicMock()
        mock_record1.get_time.return_value = MagicMock(isoformat=lambda: '2026-02-12T10:00:00')
        mock_record1.values = {'device_id': 'd1', 'metric': 'temperature'}
        mock_record1.get_value.return_value = 22.0

        mock_record2 = MagicMock()
        mock_record2.get_time.return_value = MagicMock(isoformat=lambda: '2026-02-12T10:05:00')
        mock_record2.values = {'device_id': 'd1', 'metric': 'temperature'}
        mock_record2.get_value.return_value = 23.5

        mock_table = MagicMock()
        mock_table.records = [mock_record1, mock_record2]
        mock_query_api = MagicMock()
        mock_query_api.query.return_value = [mock_table]
        mock_influx.return_value.query_api.return_value = mock_query_api

        resp = dm_client.get('/api/devices/d1/metrics?start=-1h&metric=temperature')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]['value'] == 22.0
        assert data[1]['value'] == 23.5
        # Verify all fields present
        for item in data:
            assert 'time' in item
            assert 'device_id' in item
            assert 'metric' in item
            assert 'value' in item

    @patch('app.get_minio_client')
    def test_raw_data_lists_files(self, mock_minio, dm_client):
        """List raw data files with full structure check."""
        objs = []
        for i in range(3):
            obj = MagicMock()
            obj.object_name = f'd1/2026-02-12T10-0{i}-00.json'
            obj.size = 256 + i * 10
            obj.last_modified = MagicMock(isoformat=lambda: '2026-02-12T10:00:00')
            objs.append(obj)
        mock_minio.return_value.list_objects.return_value = objs

        resp = dm_client.get('/api/devices/d1/raw-data')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 3
        for item in data:
            assert 'filename' in item
            assert 'size' in item
            assert 'last_modified' in item


class TestStatsIntegration:
    """Integration tests for the stats endpoint."""

    @patch('app.get_db_connection')
    def test_stats_aggregation(self, mock_conn, dm_client):
        """Verify stats aggregation returns proper structure."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'status': 'active', 'count': 10},
            {'status': 'inactive', 'count': 2},
            {'status': 'maintenance', 'count': 1},
        ]
        mock_cursor.fetchone.side_effect = [
            {'total': 13},
            {'count': 5},
        ]
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/stats')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total_devices'] == 13
        assert data['unacknowledged_alerts'] == 5
        assert len(data['device_by_status']) == 3


class TestCollectorMessageProcessingIntegration:
    """Integration test: message flows through collector's on_message → storage."""

    @patch('collector.Minio')
    @patch('collector.InfluxDBClient')
    @patch('collector.mqtt.Client')
    def test_message_flows_to_both_stores(self, mock_mqtt, mock_influx_cls, mock_minio_cls):
        """A single MQTT message should be stored in both MinIO and InfluxDB."""
        mock_minio_instance = MagicMock()
        mock_minio_cls.return_value = mock_minio_instance
        mock_minio_instance.bucket_exists.return_value = True

        mock_write_api = MagicMock()
        mock_influx_cls.return_value.write_api.return_value = mock_write_api

        from collector import MQTTCollector
        collector = MQTTCollector()

        msg = MagicMock()
        msg.topic = 'iot/sensor-abc/telemetry'
        msg.payload = json.dumps({
            "timestamp": "2026-02-12T10:00:00",
            "temperature": 24.5,
            "humidity": 55.0,
            "status": "ok"
        }).encode('utf-8')

        collector.on_message(MagicMock(), None, msg)

        # MinIO should receive one put_object call
        mock_minio_instance.put_object.assert_called_once()
        put_args = mock_minio_instance.put_object.call_args
        assert 'sensor-abc/' in put_args[0][1]

        # InfluxDB should receive 2 writes (temperature + humidity, not status/timestamp)
        assert mock_write_api.write.call_count == 2
