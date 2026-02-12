from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging
from datetime import datetime
from influxdb_client import InfluxDBClient
from minio import Minio

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

def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def get_influx_client():
    """Create InfluxDB client"""
    return InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)

def get_minio_client():
    """Create MinIO client"""
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)

# Device Management Endpoints

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'device-manager'}), 200

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get all devices"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
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
        
        cursor.execute(query, params)
        devices = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify(devices), 200
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>', methods=['GET'])
def get_device(device_id):
    """Get a specific device"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM devices WHERE device_id = %s", (device_id,))
        device = cursor.fetchone()
        
        if not device:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Device not found'}), 404
            
        cursor.close()
        conn.close()
        
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
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
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
        
        device = cursor.fetchone()
        conn.commit()
        
        cursor.close()
        conn.close()
        
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
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build update query dynamically
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
        
        cursor.execute(query, params)
        device = cursor.fetchone()
        
        if not device:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Device not found'}), 404
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify(device), 200
    except Exception as e:
        logger.error(f"Error updating device: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    """Delete a device"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM devices WHERE device_id = %s RETURNING device_id", (device_id,))
        deleted = cursor.fetchone()
        
        if not deleted:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Device not found'}), 404
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'message': 'Device deleted successfully'}), 200
    except Exception as e:
        logger.error(f"Error deleting device: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>/heartbeat', methods=['POST'])
def device_heartbeat(device_id):
    """Update device last seen timestamp"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE devices SET last_seen = CURRENT_TIMESTAMP WHERE device_id = %s RETURNING device_id",
            (device_id,)
        )
        
        device = cursor.fetchone()
        
        if not device:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Device not found'}), 404
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'message': 'Heartbeat received'}), 200
    except Exception as e:
        logger.error(f"Error updating heartbeat: {e}")
        return jsonify({'error': str(e)}), 500

# Metrics and Data Endpoints

@app.route('/api/devices/<device_id>/metrics', methods=['GET'])
def get_device_metrics(device_id):
    """Get time series metrics for a device from InfluxDB"""
    try:
        # Get query parameters
        start_time = request.args.get('start', '-1h')  # Default last hour
        stop_time = request.args.get('stop', 'now()')
        metric = request.args.get('metric')
        
        influx_client = get_influx_client()
        query_api = influx_client.query_api()
        
        # Build Flux query
        flux_query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
            |> range(start: {start_time}, stop: {stop_time})
            |> filter(fn: (r) => r["_measurement"] == "iot_telemetry")
            |> filter(fn: (r) => r["device_id"] == "{device_id}")
        '''
        
        if metric:
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
        
        influx_client.close()
        
        return jsonify(metrics), 200
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>/raw-data', methods=['GET'])
def get_device_raw_data(device_id):
    """Get raw data files from MinIO for a device"""
    try:
        minio_client = get_minio_client()
        
        # List objects with device_id prefix
        objects = minio_client.list_objects(MINIO_BUCKET, prefix=f"{device_id}/", recursive=True)
        
        files = []
        for obj in objects:
            files.append({
                'filename': obj.object_name,
                'size': obj.size,
                'last_modified': obj.last_modified.isoformat() if obj.last_modified else None
            })
        
        return jsonify(files), 200
    except Exception as e:
        logger.error(f"Error fetching raw data: {e}")
        return jsonify({'error': str(e)}), 500

# Alerts Endpoints

@app.route('/api/devices/<device_id>/alerts', methods=['GET'])
def get_device_alerts(device_id):
    """Get alerts for a specific device"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        acknowledged = request.args.get('acknowledged')
        
        query = "SELECT * FROM device_alerts WHERE device_id = %s"
        params = [device_id]
        
        if acknowledged is not None:
            query += " AND acknowledged = %s"
            params.append(acknowledged.lower() == 'true')
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        alerts = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify(alerts), 200
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/devices/<device_id>/alerts', methods=['POST'])
def create_alert(device_id):
    """Create a new alert for a device"""
    try:
        data = request.json
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO device_alerts (device_id, alert_type, severity, message) 
               VALUES (%s, %s, %s, %s) RETURNING *""",
            (
                device_id,
                data.get('alert_type', 'general'),
                data.get('severity', 'info'),
                data.get('message', '')
            )
        )
        
        alert = cursor.fetchone()
        conn.commit()
        
        cursor.close()
        conn.close()
        
        return jsonify(alert), 201
    except Exception as e:
        logger.error(f"Error creating alert: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/alerts/<alert_id>/acknowledge', methods=['POST'])
def acknowledge_alert(alert_id):
    """Acknowledge an alert"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE device_alerts SET acknowledged = TRUE WHERE id = %s RETURNING *",
            (alert_id,)
        )
        
        alert = cursor.fetchone()
        
        if not alert:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Alert not found'}), 404
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify(alert), 200
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        return jsonify({'error': str(e)}), 500

# Statistics Endpoint

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get overall system statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get device counts by status
        cursor.execute("""
            SELECT status, COUNT(*) as count 
            FROM devices 
            GROUP BY status
        """)
        device_stats = cursor.fetchall()
        
        # Get total devices
        cursor.execute("SELECT COUNT(*) as total FROM devices")
        total_devices = cursor.fetchone()['total']
        
        # Get unacknowledged alerts count
        cursor.execute("SELECT COUNT(*) as count FROM device_alerts WHERE acknowledged = FALSE")
        unack_alerts = cursor.fetchone()['count']
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'total_devices': total_devices,
            'device_by_status': device_stats,
            'unacknowledged_alerts': unack_alerts
        }), 200
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
