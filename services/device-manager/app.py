from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
from contextlib import contextmanager
import os
import json
import re
import uuid
import logging
from datetime import datetime, timezone
from influxdb_client import InfluxDBClient
from minio import Minio
import paho.mqtt.client as mqtt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', 5432),
    'database': os.getenv('DB_NAME', 'iot_devices'),
    'user': os.getenv('DB_USER', 'iot_user'),
    'password': os.getenv('DB_PASSWORD', 'iot_password')
}

# InfluxDB configuration
INFLUXDB_URL = os.getenv('INFLUXDB_URL', 'http://localhost:8086')
INFLUXDB_TOKEN = os.getenv('INFLUXDB_TOKEN', 'iot-admin-token-secret-12345')
INFLUXDB_ORG = os.getenv('INFLUXDB_ORG', 'iot-org')
INFLUXDB_BUCKET = os.getenv('INFLUXDB_BUCKET', 'iot-metrics')

# MinIO configuration
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'localhost:9000')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'minioadmin123')
MINIO_BUCKET = os.getenv('MINIO_BUCKET', 'iot-data')

# MQTT broker configuration (for publishing commands to devices — IoT.md §6)
MQTT_BROKER = os.getenv('MQTT_BROKER', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))

# Supported command types — IoT.md §6.2
VALID_COMMANDS = {'update_config', 'start_ota', 'reboot', 'factory_reset', 'request_status'}

# ---------------------------------------------------------------------------
# Database connection pool
# ---------------------------------------------------------------------------
_db_pool = None


def _get_pool():
    """Lazily create a threaded connection pool (1–10 connections)."""
    global _db_pool
    if _db_pool is None or _db_pool.closed:
        _db_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=int(os.getenv('DB_POOL_MAX', 10)),
            cursor_factory=RealDictCursor,
            **DB_CONFIG,
        )
    return _db_pool


@contextmanager
def get_db():
    """Context manager that borrows a connection from the pool.

    Usage::

        with get_db() as (conn, cur):
            cur.execute("SELECT 1")
            ...

    Note: uses ``get_db_connection()`` internally so that unit tests can
    ``@patch('app.get_db_connection')`` and the context manager honours the mock.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        yield conn, cur
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            return_db_connection(conn)


def get_db_connection():
    """Legacy helper — prefer `get_db()` context manager."""
    return _get_pool().getconn()


def return_db_connection(conn):
    """Return a connection back to the pool (no-op if pool is not initialised)."""
    try:
        if _db_pool is not None and not _db_pool.closed:
            _db_pool.putconn(conn)
        else:
            conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Module-level InfluxDB & MinIO clients (reused across requests)
# ---------------------------------------------------------------------------
_influx_client = None
_minio_client = None


def get_influx_client():
    """Return the shared InfluxDB client, creating it on first call."""
    global _influx_client
    if _influx_client is None:
        _influx_client = InfluxDBClient(
            url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG,
            enable_gzip=True,
        )
    return _influx_client


def get_minio_client():
    """Return the shared MinIO client, creating it on first call."""
    global _minio_client
    if _minio_client is None:
        _minio_client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False,
        )
    return _minio_client


# ---------------------------------------------------------------------------
# Module-level MQTT client (reused for all command publishes)
# ---------------------------------------------------------------------------
_mqtt_client = None


def get_mqtt_client():
    """Return the shared MQTT client, creating it on first call."""
    global _mqtt_client
    if _mqtt_client is None or not _mqtt_client.is_connected():
        _mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"device-manager-{uuid.uuid4().hex[:8]}",
        )
        _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        _mqtt_client.loop_start()           # background network thread
    return _mqtt_client


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

# Allowed pattern for identifiers used in Flux queries (device IDs, metric names)
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')

# Allowed pattern for Flux time literals like -1h, -24h, -30m, now()
_SAFE_TIME_RE = re.compile(r'^-?\d+[smhd]$|^now\(\)$')


def _sanitise_flux_id(value: str, label: str = 'value') -> str:
    """Validate that *value* is safe for interpolation into a Flux query."""
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def _sanitise_flux_time(value: str, label: str = 'time') -> str:
    """Validate a Flux time literal (e.g. ``-1h``, ``now()``)."""
    if not _SAFE_TIME_RE.match(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value

# Device Management Endpoints

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'device-manager'}), 200


@app.route('/healthz', methods=['GET'])
def liveness():
    """Liveness probe - is the process alive?"""
    return jsonify({'status': 'alive', 'service': 'device-manager'}), 200


@app.route('/readyz', methods=['GET'])
def readiness():
    """Readiness probe - can the service handle requests?"""
    try:
        with get_db() as (conn, cur):
            cur.execute("SELECT 1")
        return jsonify({'status': 'ready', 'service': 'device-manager'}), 200
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return jsonify({'status': 'not ready', 'service': 'device-manager', 'error': str(e)}), 503

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get all devices"""
    try:
        with get_db() as (conn, cur):
            status_filter = request.args.get('status')
            device_type_filter = request.args.get('type')

            query = "SELECT * FROM devices WHERE 1=1"
            params = []

            if status_filter:
                query += " AND status = %s"
                params.append(status_filter)

            if device_type_filter:
                query += " AND device_type = %s"
                params.append(device_type_filter)

            query += " ORDER BY created_at DESC"

            cur.execute(query, params)
            devices = cur.fetchall()

        return jsonify(devices), 200
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>', methods=['GET'])
def get_device(device_id):
    """Get a specific device"""
    try:
        with get_db() as (conn, cur):
            cur.execute("SELECT * FROM devices WHERE device_id = %s", (device_id,))
            device = cur.fetchone()

        if not device:
            return jsonify({'error': 'Device not found'}), 404

        return jsonify(device), 200
    except Exception as e:
        logger.error(f"Error fetching device: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices', methods=['POST'])
def create_device():
    """Create a new device"""
    try:
        data = request.json

        required_fields = ['device_id', 'device_name']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        with get_db() as (conn, cur):
            cur.execute(
                """INSERT INTO devices (device_id, device_name, device_type, location, status, metadata) 
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                (
                    data['device_id'],
                    data['device_name'],
                    data.get('device_type'),
                    data.get('location'),
                    data.get('status', 'active'),
                    data.get('metadata')
                )
            )
            device = cur.fetchone()

        return jsonify(device), 201
    except psycopg2.IntegrityError:
        return jsonify({'error': 'Device with this ID already exists'}), 409
    except Exception as e:
        logger.error(f"Error creating device: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>', methods=['PUT'])
def update_device(device_id):
    """Update a device"""
    try:
        data = request.json

        update_fields = []
        params = []

        for field in ['device_name', 'device_type', 'location', 'status', 'metadata']:
            if field in data:
                update_fields.append(f"{field} = %s")
                params.append(data[field])

        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(device_id)

        query = f"UPDATE devices SET {', '.join(update_fields)} WHERE device_id = %s RETURNING *"

        with get_db() as (conn, cur):
            cur.execute(query, params)
            device = cur.fetchone()

        if not device:
            return jsonify({'error': 'Device not found'}), 404

        return jsonify(device), 200
    except Exception as e:
        logger.error(f"Error updating device: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    """Delete a device"""
    try:
        with get_db() as (conn, cur):
            cur.execute("DELETE FROM devices WHERE device_id = %s RETURNING device_id", (device_id,))
            deleted = cur.fetchone()

        if not deleted:
            return jsonify({'error': 'Device not found'}), 404

        return jsonify({'message': 'Device deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Error deleting device: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>/heartbeat', methods=['POST'])
def device_heartbeat(device_id):
    """Update device last seen timestamp"""
    try:
        with get_db() as (conn, cur):
            cur.execute(
                "UPDATE devices SET last_seen = CURRENT_TIMESTAMP WHERE device_id = %s RETURNING device_id",
                (device_id,)
            )
            device = cur.fetchone()

        if not device:
            return jsonify({'error': 'Device not found'}), 404

        return jsonify({'message': 'Heartbeat received'}), 200
    except Exception as e:
        logger.error(f"Error updating heartbeat: {e}")
        return jsonify({'error': str(e)}), 500

# Metrics and Data Endpoints

@app.route('/api/devices/<device_id>/metrics', methods=['GET'])
def get_device_metrics(device_id):
    """Get time series metrics for a device from InfluxDB"""
    try:
        # Validate / sanitise all values before interpolation
        device_id = _sanitise_flux_id(device_id, 'device_id')
        start_time = _sanitise_flux_time(request.args.get('start', '-1h'), 'start')
        stop_time = _sanitise_flux_time(request.args.get('stop', 'now()'), 'stop')
        metric = request.args.get('metric')

        influx_client = get_influx_client()
        query_api = influx_client.query_api()

        # Build Flux query — all interpolated values are validated above
        flux_query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
            |> range(start: {start_time}, stop: {stop_time})
            |> filter(fn: (r) => r["_measurement"] == "iot_telemetry")
            |> filter(fn: (r) => r["device_id"] == "{device_id}")
        '''

        if metric:
            metric = _sanitise_flux_id(metric, 'metric')
            flux_query += f'''
            |> filter(fn: (r) => r["metric"] == "{metric}")
            '''

        flux_query += '''
            |> sort(columns: ["_time"], desc: false)
        '''
        
        result = query_api.query(flux_query, org=INFLUXDB_ORG)
        
        # Format results
        metrics = []
        for table in result:
            for record in table.records:
                metrics.append({
                    'time': record.get_time().isoformat(),
                    'device_id': record.values.get('device_id'),
                    'metric': record.values.get('metric'),
                    'value': record.get_value()
                })
        
        return jsonify(metrics), 200
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>/raw-data', methods=['GET'])
def get_device_raw_data(device_id):
    """Get raw data files from MinIO for a device.

    Query parameters:
        limit  – max number of files to return (default 100, max 1000)
        prefix – optional sub-path filter appended after device_id/
    """
    try:
        minio_client = get_minio_client()

        limit = min(int(request.args.get('limit', 100)), 1000)
        sub_prefix = request.args.get('prefix', '')
        full_prefix = f"{device_id}/{sub_prefix}"

        # List objects with device_id prefix
        objects = minio_client.list_objects(
            MINIO_BUCKET, prefix=full_prefix, recursive=True,
        )

        files = []
        for obj in objects:
            files.append({
                'filename': obj.object_name,
                'size': obj.size,
                'last_modified': obj.last_modified.isoformat() if obj.last_modified else None,
            })
            if len(files) >= limit:
                break

        return jsonify(files), 200
    except Exception as e:
        logger.error(f"Error fetching raw data: {e}")
        return jsonify({'error': str(e)}), 500

# Alerts Endpoints

@app.route('/api/devices/<device_id>/alerts', methods=['GET'])
def get_device_alerts(device_id):
    """Get alerts for a specific device"""
    try:
        with get_db() as (conn, cur):
            acknowledged = request.args.get('acknowledged')

            query = "SELECT * FROM device_alerts WHERE device_id = %s"
            params = [device_id]

            if acknowledged is not None:
                query += " AND acknowledged = %s"
                params.append(acknowledged.lower() == 'true')

            query += " ORDER BY created_at DESC"

            cur.execute(query, params)
            alerts = cur.fetchall()

        return jsonify(alerts), 200
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>/alerts', methods=['POST'])
def create_alert(device_id):
    """Create a new alert for a device"""
    try:
        data = request.json

        with get_db() as (conn, cur):
            cur.execute(
                """INSERT INTO device_alerts (device_id, alert_type, severity, message) 
                   VALUES (%s, %s, %s, %s) RETURNING *""",
                (
                    device_id,
                    data.get('alert_type', 'general'),
                    data.get('severity', 'info'),
                    data.get('message', '')
                )
            )
            alert = cur.fetchone()

        return jsonify(alert), 201
    except Exception as e:
        logger.error(f"Error creating alert: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/alerts/<alert_id>/acknowledge', methods=['POST'])
def acknowledge_alert(alert_id):
    """Acknowledge an alert"""
    try:
        with get_db() as (conn, cur):
            cur.execute(
                "UPDATE device_alerts SET acknowledged = TRUE WHERE id = %s RETURNING *",
                (alert_id,)
            )
            alert = cur.fetchone()

        if not alert:
            return jsonify({'error': 'Alert not found'}), 404

        return jsonify(alert), 200
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        return jsonify({'error': str(e)}), 500

# Statistics Endpoint

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get overall system statistics"""
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                SELECT status, COUNT(*) as count 
                FROM devices 
                GROUP BY status
            """)
            device_stats = cur.fetchall()

            cur.execute("SELECT COUNT(*) as total FROM devices")
            total_devices = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) as count FROM device_alerts WHERE acknowledged = FALSE")
            unack_alerts = cur.fetchone()['count']

        return jsonify({
            'total_devices': total_devices,
            'device_by_status': device_stats,
            'unacknowledged_alerts': unack_alerts
        }), 200
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return jsonify({'error': str(e)}), 500


# ===================================================================
# Device Status — IoT.md §5 (Online / Offline Detection)
# ===================================================================

@app.route('/api/devices/<device_id>/status', methods=['GET'])
def get_device_status(device_id):
    """Get a device's connection status (online/offline).

    See IoT.md §5 — REQ-ONLINE-001.
    """
    try:
        with get_db() as (conn, cur):
            cur.execute(
                "SELECT device_id, connection_status, last_seen, fw_version FROM devices WHERE device_id = %s",
                (device_id,)
            )
            device = cur.fetchone()

        if not device:
            return jsonify({'error': 'Device not found'}), 404

        return jsonify(device), 200
    except Exception as e:
        logger.error(f"Error fetching device status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>/status', methods=['PUT'])
def update_device_status(device_id):
    """Update a device's connection status (called by collector on status messages).

    Expected body: {"connection_status": "online"|"offline", "fw_version": "..."}
    See IoT.md §5.
    """
    try:
        data = request.json
        connection_status = data.get('connection_status')
        if connection_status not in ('online', 'offline', 'unknown'):
            return jsonify({'error': 'Invalid connection_status. Must be online, offline, or unknown.'}), 400

        with get_db() as (conn, cur):
            update_fields = ["connection_status = %s", "last_seen = CURRENT_TIMESTAMP", "updated_at = CURRENT_TIMESTAMP"]
            params = [connection_status]

            if 'fw_version' in data:
                update_fields.append("fw_version = %s")
                params.append(data['fw_version'])

            params.append(device_id)
            query = f"UPDATE devices SET {', '.join(update_fields)} WHERE device_id = %s RETURNING *"

            cur.execute(query, params)
            device = cur.fetchone()

        if not device:
            return jsonify({'error': 'Device not found'}), 404

        return jsonify(device), 200
    except Exception as e:
        logger.error(f"Error updating device status: {e}")
        return jsonify({'error': str(e)}), 500


# ===================================================================
# Commands — IoT.md §6 (Server → Device Commands)
# ===================================================================

@app.route('/api/devices/<device_id>/commands', methods=['POST'])
def send_command(device_id):
    """Send a command to a device via MQTT.

    Request body: {"cmd": "update_config", "params": {...}}
    See IoT.md §6.1–6.4.
    """
    try:
        data = request.json
        cmd = data.get('cmd')
        params = data.get('params', {})

        if not cmd:
            return jsonify({'error': 'Missing required field: cmd'}), 400

        if cmd not in VALID_COMMANDS:
            return jsonify({
                'error': f'Invalid command: {cmd}. Valid commands: {sorted(VALID_COMMANDS)}'
            }), 400

        cmd_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()

        # Build command payload (IoT.md §6.1)
        command_payload = {
            'v': 2,
            'cmd_id': cmd_id,
            'ts': ts,
            'cmd': cmd,
            'params': params
        }

        # Persist command in DB for tracking
        with get_db() as (conn, cur):
            cur.execute(
                """INSERT INTO device_commands (cmd_id, device_id, cmd, params, status)
                   VALUES (%s, %s, %s, %s, 'pending') RETURNING *""",
                (cmd_id, device_id, cmd, json.dumps(params))
            )
            command_record = cur.fetchone()

        # Publish command to MQTT (IoT.md §3.1)
        topic = f"iot/{device_id}/command"
        try:
            client = get_mqtt_client()
            result = client.publish(topic, json.dumps(command_payload), qos=2)
            logger.info(f"Published command {cmd_id} to {topic}: {cmd}")
        except Exception as mqtt_err:
            logger.error(f"Failed to publish command to MQTT: {mqtt_err}")
            # Command is still persisted in DB with 'pending' status
            return jsonify({
                'cmd_id': cmd_id,
                'status': 'pending',
                'mqtt_error': str(mqtt_err),
                'message': 'Command saved but MQTT publish failed'
            }), 202

        return jsonify({
            'cmd_id': cmd_id,
            'device_id': device_id,
            'cmd': cmd,
            'status': 'pending',
            'message': f'Command published to {topic}'
        }), 201

    except Exception as e:
        logger.error(f"Error sending command: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices/<device_id>/commands', methods=['GET'])
def get_device_commands(device_id):
    """Get command history for a device.

    Optional query params: ?status=pending|accepted|rejected
    """
    try:
        with get_db() as (conn, cur):
            query = "SELECT * FROM device_commands WHERE device_id = %s"
            params = [device_id]

            status_filter = request.args.get('status')
            if status_filter:
                query += " AND status = %s"
                params.append(status_filter)

            query += " ORDER BY created_at DESC"

            cur.execute(query, params)
            commands = cur.fetchall()

        return jsonify(commands), 200
    except Exception as e:
        logger.error(f"Error fetching commands: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/commands/<cmd_id>/ack', methods=['PUT'])
def acknowledge_command(cmd_id):
    """Update a command's status after receiving an ack from the device.

    Called by the collector when it receives a command/ack message.
    Body: {"result": "accepted", "detail": "..."}
    See IoT.md §6.5.
    """
    try:
        data = request.json
        result = data.get('result')
        detail = data.get('detail', '')

        valid_results = {'accepted', 'rejected', 'error', 'unsupported'}
        if result not in valid_results:
            return jsonify({'error': f'Invalid result. Must be one of: {sorted(valid_results)}'}), 400

        with get_db() as (conn, cur):
            cur.execute(
                """UPDATE device_commands 
                   SET status = %s, ack_detail = %s, acked_at = CURRENT_TIMESTAMP
                   WHERE cmd_id = %s RETURNING *""",
                (result, detail, cmd_id)
            )
            command = cur.fetchone()

        if not command:
            return jsonify({'error': 'Command not found'}), 404

        return jsonify(command), 200
    except Exception as e:
        logger.error(f"Error acknowledging command: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
