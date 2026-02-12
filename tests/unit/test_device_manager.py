"""
Unit tests for the device-manager Flask API.

All external dependencies (PostgreSQL, InfluxDB, MinIO, MQTT) are mocked.

These tests verify the v2 protocol features defined in IoT.md:
  - §5  Device online/offline status endpoints
  - §6  Server → device command publishing
  - §6.5 Command acknowledgement tracking

Any change to IoT.md MUST be reflected here and vice-versa.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from psycopg2 import IntegrityError


pytestmark = pytest.mark.unit


# ===================================================================
# Health / Liveness / Readiness
# ===================================================================

class TestHealthEndpoints:
    """Tests for /health, /healthz, /readyz endpoints."""

    def test_health(self, dm_client):
        resp = dm_client.get('/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'healthy'
        assert data['service'] == 'device-manager'

    def test_liveness(self, dm_client):
        resp = dm_client.get('/healthz')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'alive'

    @patch('app.get_db_connection')
    def test_readiness_ok(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cursor
        resp = dm_client.get('/readyz')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ready'
        mock_cursor.execute.assert_called_once_with("SELECT 1")

    @patch('app.get_db_connection')
    def test_readiness_fail(self, mock_conn, dm_client):
        mock_conn.side_effect = Exception("DB down")
        resp = dm_client.get('/readyz')
        assert resp.status_code == 503
        assert resp.get_json()['status'] == 'not ready'


# ===================================================================
# GET /api/devices
# ===================================================================

class TestGetDevices:
    """Tests for GET /api/devices."""

    @patch('app.get_db_connection')
    def test_get_all_devices(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'device_id': 'd1', 'device_name': 'Sensor 1'},
            {'device_id': 'd2', 'device_name': 'Sensor 2'},
        ]
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    @patch('app.get_db_connection')
    def test_get_devices_filter_by_status(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{'device_id': 'd1', 'status': 'active'}]
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices?status=active')
        assert resp.status_code == 200
        # Verify the query included the status filter
        call_args = mock_cursor.execute.call_args
        assert 'AND status = %s' in call_args[0][0]
        assert 'active' in call_args[0][1]

    @patch('app.get_db_connection')
    def test_get_devices_filter_by_type(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices?type=temperature')
        assert resp.status_code == 200
        call_args = mock_cursor.execute.call_args
        assert 'AND device_type = %s' in call_args[0][0]

    @patch('app.get_db_connection')
    def test_get_devices_empty(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices')
        assert resp.status_code == 200
        assert resp.get_json() == []

    @patch('app.get_db_connection')
    def test_get_devices_db_error(self, mock_conn, dm_client):
        mock_conn.side_effect = Exception("connection refused")
        resp = dm_client.get('/api/devices')
        assert resp.status_code == 500
        assert 'error' in resp.get_json()


# ===================================================================
# GET /api/devices/<device_id>
# ===================================================================

class TestGetDevice:
    """Tests for GET /api/devices/<device_id>."""

    @patch('app.get_db_connection')
    def test_get_device_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'device_id': 'd1', 'device_name': 'Sensor 1'}
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices/d1')
        assert resp.status_code == 200
        assert resp.get_json()['device_id'] == 'd1'

    @patch('app.get_db_connection')
    def test_get_device_not_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices/nonexistent')
        assert resp.status_code == 404


# ===================================================================
# POST /api/devices
# ===================================================================

class TestCreateDevice:
    """Tests for POST /api/devices."""

    @patch('app.get_db_connection')
    def test_create_device_success(self, mock_conn, dm_client, sample_device):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = sample_device
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.post('/api/devices',
                              data=json.dumps(sample_device),
                              content_type='application/json')
        assert resp.status_code == 201
        assert resp.get_json()['device_id'] == sample_device['device_id']

    @patch('app.get_db_connection')
    def test_create_device_minimal(self, mock_conn, dm_client):
        """Only required fields."""
        payload = {"device_id": "min-001", "device_name": "Minimal"}
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = payload
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.post('/api/devices',
                              data=json.dumps(payload),
                              content_type='application/json')
        assert resp.status_code == 201

    def test_create_device_missing_device_id(self, dm_client):
        payload = {"device_name": "No ID"}
        resp = dm_client.post('/api/devices',
                              data=json.dumps(payload),
                              content_type='application/json')
        assert resp.status_code == 400
        assert 'device_id' in resp.get_json()['error']

    def test_create_device_missing_device_name(self, dm_client):
        payload = {"device_id": "d1"}
        resp = dm_client.post('/api/devices',
                              data=json.dumps(payload),
                              content_type='application/json')
        assert resp.status_code == 400
        assert 'device_name' in resp.get_json()['error']

    @patch('app.get_db_connection')
    def test_create_device_duplicate(self, mock_conn, dm_client, sample_device):
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = IntegrityError()
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.post('/api/devices',
                              data=json.dumps(sample_device),
                              content_type='application/json')
        assert resp.status_code == 409


# ===================================================================
# PUT /api/devices/<device_id>
# ===================================================================

class TestUpdateDevice:
    """Tests for PUT /api/devices/<device_id>."""

    @patch('app.get_db_connection')
    def test_update_device_success(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'device_id': 'd1', 'device_name': 'Updated'}
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.put('/api/devices/d1',
                             data=json.dumps({"device_name": "Updated"}),
                             content_type='application/json')
        assert resp.status_code == 200

    @patch('app.get_db_connection')
    def test_update_device_not_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.put('/api/devices/nonexistent',
                             data=json.dumps({"device_name": "X"}),
                             content_type='application/json')
        assert resp.status_code == 404

    @patch('app.get_db_connection')
    def test_update_device_no_fields(self, mock_conn, dm_client):
        resp = dm_client.put('/api/devices/d1',
                             data=json.dumps({}),
                             content_type='application/json')
        assert resp.status_code == 400


# ===================================================================
# DELETE /api/devices/<device_id>
# ===================================================================

class TestDeleteDevice:
    """Tests for DELETE /api/devices/<device_id>."""

    @patch('app.get_db_connection')
    def test_delete_device_success(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'device_id': 'd1'}
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.delete('/api/devices/d1')
        assert resp.status_code == 200
        assert 'deleted' in resp.get_json()['message'].lower()

    @patch('app.get_db_connection')
    def test_delete_device_not_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.delete('/api/devices/nonexistent')
        assert resp.status_code == 404


# ===================================================================
# POST /api/devices/<device_id>/heartbeat
# ===================================================================

class TestHeartbeat:
    """Tests for POST /api/devices/<device_id>/heartbeat."""

    @patch('app.get_db_connection')
    def test_heartbeat_success(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'device_id': 'd1'}
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.post('/api/devices/d1/heartbeat')
        assert resp.status_code == 200
        assert 'heartbeat' in resp.get_json()['message'].lower()

    @patch('app.get_db_connection')
    def test_heartbeat_not_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.post('/api/devices/nonexistent/heartbeat')
        assert resp.status_code == 404


# ===================================================================
# GET /api/devices/<device_id>/metrics
# ===================================================================

class TestGetMetrics:
    """Tests for GET /api/devices/<device_id>/metrics."""

    @patch('app.get_influx_client')
    def test_get_metrics_success(self, mock_influx, dm_client):
        mock_record = MagicMock()
        mock_record.get_time.return_value = MagicMock(isoformat=lambda: '2026-02-12T10:00:00')
        mock_record.values = {'device_id': 'd1', 'metric': 'temperature'}
        mock_record.get_value.return_value = 23.5

        mock_table = MagicMock()
        mock_table.records = [mock_record]

        mock_query_api = MagicMock()
        mock_query_api.query.return_value = [mock_table]
        mock_influx.return_value.query_api.return_value = mock_query_api

        resp = dm_client.get('/api/devices/d1/metrics?start=-1h')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['value'] == 23.5

    @patch('app.get_influx_client')
    def test_get_metrics_with_metric_filter(self, mock_influx, dm_client):
        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_influx.return_value.query_api.return_value = mock_query_api

        resp = dm_client.get('/api/devices/d1/metrics?metric=temperature')
        assert resp.status_code == 200
        # Verify the Flux query included the metric filter
        call_args = mock_query_api.query.call_args[0][0]
        assert 'temperature' in call_args

    @patch('app.get_influx_client')
    def test_get_metrics_empty(self, mock_influx, dm_client):
        mock_query_api = MagicMock()
        mock_query_api.query.return_value = []
        mock_influx.return_value.query_api.return_value = mock_query_api

        resp = dm_client.get('/api/devices/d1/metrics')
        assert resp.status_code == 200
        assert resp.get_json() == []


# ===================================================================
# GET /api/devices/<device_id>/raw-data
# ===================================================================

class TestGetRawData:
    """Tests for GET /api/devices/<device_id>/raw-data."""

    @patch('app.get_minio_client')
    def test_get_raw_data_success(self, mock_minio, dm_client):
        mock_obj = MagicMock()
        mock_obj.object_name = 'd1/2026-02-12.json'
        mock_obj.size = 256
        mock_obj.last_modified = MagicMock(isoformat=lambda: '2026-02-12T10:00:00')
        mock_minio.return_value.list_objects.return_value = [mock_obj]

        resp = dm_client.get('/api/devices/d1/raw-data')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['filename'] == 'd1/2026-02-12.json'

    @patch('app.get_minio_client')
    def test_get_raw_data_empty(self, mock_minio, dm_client):
        mock_minio.return_value.list_objects.return_value = []
        resp = dm_client.get('/api/devices/d1/raw-data')
        assert resp.status_code == 200
        assert resp.get_json() == []


# ===================================================================
# Alerts endpoints
# ===================================================================

class TestAlerts:
    """Tests for alert-related endpoints."""

    @patch('app.get_db_connection')
    def test_get_alerts(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'device_id': 'd1', 'alert_type': 'high_temp', 'severity': 'warning'}
        ]
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices/d1/alerts')
        assert resp.status_code == 200
        assert len(resp.get_json()) == 1

    @patch('app.get_db_connection')
    def test_get_alerts_filter_acknowledged(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices/d1/alerts?acknowledged=false')
        assert resp.status_code == 200
        call_args = mock_cursor.execute.call_args
        assert 'acknowledged' in call_args[0][0]

    @patch('app.get_db_connection')
    def test_create_alert(self, mock_conn, dm_client, sample_alert):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'id': 1, 'device_id': 'd1', **sample_alert, 'acknowledged': False
        }
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.post('/api/devices/d1/alerts',
                              data=json.dumps(sample_alert),
                              content_type='application/json')
        assert resp.status_code == 201

    @patch('app.get_db_connection')
    def test_acknowledge_alert(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'id': 1, 'acknowledged': True}
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.post('/api/alerts/1/acknowledge')
        assert resp.status_code == 200
        assert resp.get_json()['acknowledged'] is True

    @patch('app.get_db_connection')
    def test_acknowledge_alert_not_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.post('/api/alerts/999/acknowledge')
        assert resp.status_code == 404


# ===================================================================
# GET /api/stats
# ===================================================================

class TestStats:
    """Tests for GET /api/stats."""

    @patch('app.get_db_connection')
    def test_get_stats(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        # fetchall for device_stats, fetchone for total, fetchone for unack
        mock_cursor.fetchall.return_value = [
            {'status': 'active', 'count': 5},
            {'status': 'inactive', 'count': 1},
        ]
        mock_cursor.fetchone.side_effect = [
            {'total': 6},
            {'count': 3},
        ]
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/stats')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total_devices'] == 6
        assert data['unacknowledged_alerts'] == 3
        assert len(data['device_by_status']) == 2


# ===================================================================
# GET/PUT /api/devices/<device_id>/status — IoT.md §5
# ===================================================================

class TestDeviceStatus:
    """Tests for device connection status endpoints.

    Implements REQ-ONLINE-001: backend tracks online/offline state.
    See IoT.md §5.
    """

    @patch('app.get_db_connection')
    def test_get_device_status(self, mock_conn, dm_client):
        """GET /api/devices/<id>/status returns connection status."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'device_id': 'dc-meter-007',
            'connection_status': 'online',
            'last_seen': '2026-02-12T10:00:00',
            'fw_version': '2.1.0',
        }
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices/dc-meter-007/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['connection_status'] == 'online'
        assert data['fw_version'] == '2.1.0'

    @patch('app.get_db_connection')
    def test_get_device_status_not_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices/nonexistent/status')
        assert resp.status_code == 404

    @patch('app.get_db_connection')
    def test_update_device_status_online(self, mock_conn, dm_client):
        """PUT /api/devices/<id>/status sets connection_status."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'device_id': 'dc-meter-007',
            'connection_status': 'online',
        }
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.put(
            '/api/devices/dc-meter-007/status',
            data=json.dumps({'connection_status': 'online', 'fw_version': '2.1.0'}),
            content_type='application/json',
        )
        assert resp.status_code == 200

    @patch('app.get_db_connection')
    def test_update_device_status_invalid(self, mock_conn, dm_client):
        """Invalid connection_status must be rejected."""
        resp = dm_client.put(
            '/api/devices/dc-meter-007/status',
            data=json.dumps({'connection_status': 'banana'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    @patch('app.get_db_connection')
    def test_update_device_status_not_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.put(
            '/api/devices/nonexistent/status',
            data=json.dumps({'connection_status': 'offline'}),
            content_type='application/json',
        )
        assert resp.status_code == 404


# ===================================================================
# POST /api/devices/<device_id>/commands — IoT.md §6
# ===================================================================

class TestSendCommand:
    """Tests for server → device command publishing.

    See IoT.md §6.1–6.4 for command envelope format.
    """

    @patch('app.get_mqtt_client')
    @patch('app.get_db_connection')
    def test_send_update_config_command(self, mock_conn, mock_mqtt, dm_client):
        """POST /api/devices/<id>/commands publishes to MQTT and persists in DB."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'cmd_id': 'test-uuid', 'device_id': 'dc-meter-007',
            'cmd': 'update_config', 'status': 'pending'
        }
        mock_conn.return_value.cursor.return_value = mock_cursor
        mock_mqtt_client = MagicMock()
        mock_mqtt_client.publish.return_value = MagicMock(rc=0)
        mock_mqtt.return_value = mock_mqtt_client

        resp = dm_client.post(
            '/api/devices/dc-meter-007/commands',
            data=json.dumps({'cmd': 'update_config', 'params': {'send_interval_s': 5}}),
            content_type='application/json',
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['cmd'] == 'update_config'
        assert data['status'] == 'pending'
        # Verify MQTT publish was called with correct topic
        mock_mqtt_client.publish.assert_called_once()
        call_args = mock_mqtt_client.publish.call_args
        assert 'iot/dc-meter-007/command' in call_args[0]

    @patch('app.get_db_connection')
    def test_send_command_missing_cmd(self, mock_conn, dm_client):
        """Missing 'cmd' field must return 400."""
        resp = dm_client.post(
            '/api/devices/dc-meter-007/commands',
            data=json.dumps({'params': {}}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        assert 'cmd' in resp.get_json()['error']

    @patch('app.get_db_connection')
    def test_send_command_invalid_type(self, mock_conn, dm_client):
        """Invalid command type must return 400 — IoT.md §6.2."""
        resp = dm_client.post(
            '/api/devices/dc-meter-007/commands',
            data=json.dumps({'cmd': 'self_destruct', 'params': {}}),
            content_type='application/json',
        )
        assert resp.status_code == 400
        assert 'Invalid command' in resp.get_json()['error']

    @patch('app.get_mqtt_client')
    @patch('app.get_db_connection')
    def test_send_command_mqtt_failure(self, mock_conn, mock_mqtt, dm_client):
        """MQTT publish failure still saves command in DB — returns 202."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'cmd_id': 'test-uuid', 'device_id': 'dc-meter-007',
            'cmd': 'reboot', 'status': 'pending'
        }
        mock_conn.return_value.cursor.return_value = mock_cursor
        mock_mqtt.side_effect = Exception("Broker unreachable")

        resp = dm_client.post(
            '/api/devices/dc-meter-007/commands',
            data=json.dumps({'cmd': 'reboot', 'params': {}}),
            content_type='application/json',
        )
        assert resp.status_code == 202
        assert 'mqtt_error' in resp.get_json()

    @patch('app.get_mqtt_client')
    @patch('app.get_db_connection')
    def test_send_start_ota_command(self, mock_conn, mock_mqtt, dm_client):
        """start_ota command is valid — IoT.md §6.4."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'cmd_id': 'ota-uuid', 'device_id': 'dc-meter-007',
            'cmd': 'start_ota', 'status': 'pending'
        }
        mock_conn.return_value.cursor.return_value = mock_cursor
        mock_mqtt.return_value = MagicMock()
        mock_mqtt.return_value.publish.return_value = MagicMock(rc=0)

        resp = dm_client.post(
            '/api/devices/dc-meter-007/commands',
            data=json.dumps({
                'cmd': 'start_ota',
                'params': {'fw_version': '2.2.0', 'fw_url': 'https://ota.example.com/2.2.0.bin'}
            }),
            content_type='application/json',
        )
        assert resp.status_code == 201


# ===================================================================
# GET /api/devices/<device_id>/commands
# ===================================================================

class TestGetDeviceCommands:
    """Tests for command history retrieval."""

    @patch('app.get_db_connection')
    def test_get_commands(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'cmd_id': 'c1', 'cmd': 'update_config', 'status': 'accepted'},
            {'cmd_id': 'c2', 'cmd': 'reboot', 'status': 'pending'},
        ]
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices/dc-meter-007/commands')
        assert resp.status_code == 200
        assert len(resp.get_json()) == 2

    @patch('app.get_db_connection')
    def test_get_commands_filter_status(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'cmd_id': 'c2', 'cmd': 'reboot', 'status': 'pending'},
        ]
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.get('/api/devices/dc-meter-007/commands?status=pending')
        assert resp.status_code == 200
        call_args = mock_cursor.execute.call_args
        assert 'AND status = %s' in call_args[0][0]


# ===================================================================
# PUT /api/commands/<cmd_id>/ack — IoT.md §6.5
# ===================================================================

class TestAcknowledgeCommand:
    """Tests for command acknowledgement.

    See IoT.md §6.5. Result must be one of:
    accepted, rejected, error, unsupported.
    """

    @patch('app.get_db_connection')
    def test_ack_accepted(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            'cmd_id': 'c1', 'status': 'accepted', 'ack_detail': 'Config updated'
        }
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.put(
            '/api/commands/c1/ack',
            data=json.dumps({'result': 'accepted', 'detail': 'Config updated'}),
            content_type='application/json',
        )
        assert resp.status_code == 200

    @patch('app.get_db_connection')
    def test_ack_rejected(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'cmd_id': 'c1', 'status': 'rejected'}
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.put(
            '/api/commands/c1/ack',
            data=json.dumps({'result': 'rejected', 'detail': 'Invalid param'}),
            content_type='application/json',
        )
        assert resp.status_code == 200

    @patch('app.get_db_connection')
    def test_ack_invalid_result(self, mock_conn, dm_client):
        """Invalid result value must be rejected."""
        resp = dm_client.put(
            '/api/commands/c1/ack',
            data=json.dumps({'result': 'maybe'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    @patch('app.get_db_connection')
    def test_ack_command_not_found(self, mock_conn, dm_client):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.cursor.return_value = mock_cursor

        resp = dm_client.put(
            '/api/commands/nonexistent/ack',
            data=json.dumps({'result': 'accepted'}),
            content_type='application/json',
        )
        assert resp.status_code == 404
