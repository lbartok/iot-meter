import os
import json
import time
import threading
from datetime import datetime, timezone
from io import BytesIO
import paho.mqtt.client as mqtt
from minio import Minio
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from flask import Flask, jsonify
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Health check Flask app
health_app = Flask(__name__)
collector_instance = None


@health_app.route('/healthz', methods=['GET'])
def liveness():
    """Liveness probe - is the process alive?"""
    return jsonify({'status': 'alive', 'service': 'mqtt-collector'}), 200


@health_app.route('/readyz', methods=['GET'])
def readiness():
    """Readiness probe - is the service ready to process messages?"""
    if collector_instance and collector_instance.is_ready():
        return jsonify({'status': 'ready', 'service': 'mqtt-collector'}), 200
    return jsonify({'status': 'not ready', 'service': 'mqtt-collector'}), 503


# -----------------------------------------------------------------------
# v2 Topic subscriptions — see IoT.md §3.1
# -----------------------------------------------------------------------
V2_TOPIC_SUBSCRIPTIONS = [
    'iot/+/telemetry',       # Measurement datagrams
    'iot/+/hello',           # Heartbeat / hello messages
    'iot/+/status',          # Online/offline (LWT)
    'iot/+/command/ack',     # Command acknowledgements
    'iot/+/ota/status',      # OTA progress reports
]


class MQTTCollector:
    def __init__(self):
        # MQTT Configuration
        self.mqtt_broker = os.getenv('MQTT_BROKER', 'localhost')
        self.mqtt_port = int(os.getenv('MQTT_PORT', 1883))
        self.mqtt_topic = os.getenv('MQTT_TOPIC', 'iot/+/telemetry')

        # MinIO Configuration
        self.minio_endpoint = os.getenv('MINIO_ENDPOINT', 'localhost:9000')
        self.minio_access_key = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
        self.minio_secret_key = os.getenv('MINIO_SECRET_KEY', 'minioadmin123')
        self.minio_bucket = os.getenv('MINIO_BUCKET', 'iot-data')

        # InfluxDB Configuration
        self.influxdb_url = os.getenv('INFLUXDB_URL', 'http://localhost:8086')
        self.influxdb_token = os.getenv('INFLUXDB_TOKEN', 'iot-admin-token-secret-12345')
        self.influxdb_org = os.getenv('INFLUXDB_ORG', 'iot-org')
        self.influxdb_bucket = os.getenv('INFLUXDB_BUCKET', 'iot-metrics')

        # Device Manager API (for status updates, heartbeats)
        self.device_manager_url = os.getenv('DEVICE_MANAGER_URL', 'http://localhost:8080')

        # Connection state tracking
        self.mqtt_connected = False
        self.minio_ready = False
        self.influxdb_ready = False

        # Sequence tracking for deduplication (IoT.md §2.2, REQ-DEDUP-001)
        # Key: device_id, Value: last seen seq number
        self._seq_tracker = {}
        self._seq_lock = threading.Lock()

        # Device last-seen tracking for online/offline (IoT.md §5)
        self._device_last_seen = {}

        # Initialize MinIO client (in background thread for resilience)
        self.minio_client = None
        threading.Thread(target=self.init_minio, daemon=True).start()

        # Initialize InfluxDB client (in background thread for resilience)
        self.influx_client = None
        self.write_api = None
        threading.Thread(target=self.init_influxdb, daemon=True).start()

        # Initialize MQTT client (paho-mqtt v2 API)
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.on_disconnect = self.on_disconnect

    def is_ready(self):
        """Check if the collector is ready to process messages"""
        return self.mqtt_connected and self.minio_ready and self.influxdb_ready

    def init_minio(self):
        """Initialize MinIO client with retry logic"""
        max_retries = 15
        retry_delay = 5
        for attempt in range(max_retries):
            try:
                self.minio_client = Minio(
                    self.minio_endpoint,
                    access_key=self.minio_access_key,
                    secret_key=self.minio_secret_key,
                    secure=False
                )
                # Check if bucket exists (this actually contacts MinIO)
                if not self.minio_client.bucket_exists(self.minio_bucket):
                    logger.warning(f"Bucket {self.minio_bucket} does not exist, waiting for creation...")
                self.minio_ready = True
                logger.info("MinIO client initialized successfully")
                return
            except Exception as e:
                logger.warning(f"MinIO init attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        self.minio_ready = False
        logger.error("Failed to initialize MinIO client after all retries")

    def init_influxdb(self):
        """Initialize InfluxDB client with retry logic"""
        max_retries = 15
        retry_delay = 5
        for attempt in range(max_retries):
            try:
                self.influx_client = InfluxDBClient(
                    url=self.influxdb_url,
                    token=self.influxdb_token,
                    org=self.influxdb_org
                )
                self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)
                self.influxdb_ready = True
                logger.info("InfluxDB client initialized successfully")
                return
            except Exception as e:
                logger.warning(f"InfluxDB init attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        self.influxdb_ready = False
        logger.error("Failed to initialize InfluxDB client after all retries")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to MQTT broker (paho-mqtt v2 API)"""
        if reason_code == 0:
            self.mqtt_connected = True
            logger.info(f"Connected to MQTT broker at {self.mqtt_broker}:{self.mqtt_port}")
            # Subscribe to all v2 topics (IoT.md §3.1)
            for topic in V2_TOPIC_SUBSCRIPTIONS:
                client.subscribe(topic, qos=2)
                logger.info(f"Subscribed to topic: {topic}")
        else:
            self.mqtt_connected = False
            logger.error(f"Failed to connect to MQTT broker, reason code: {reason_code}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Callback when disconnected from MQTT broker (paho-mqtt v2 API)"""
        self.mqtt_connected = False
        logger.warning(f"Disconnected from MQTT broker, reason code: {reason_code}")

    # -------------------------------------------------------------------
    # Deduplication — IoT.md §2.2 / REQ-DEDUP-001
    # -------------------------------------------------------------------

    def is_duplicate(self, device_id, seq):
        """Check if a message is a duplicate based on (device_id, seq).

        Returns True if the message should be dropped.
        Also detects gaps and logs warnings.
        """
        if seq is None or seq < 0:
            # v1 messages (no seq) — never deduplicate
            return False

        with self._seq_lock:
            last_seq = self._seq_tracker.get(device_id, -1)

            if seq <= last_seq:
                # Duplicate or out-of-order
                logger.debug(f"Dropping duplicate message from {device_id}: seq={seq} (last={last_seq})")
                return True

            if last_seq >= 0 and seq > last_seq + 1:
                gap = seq - last_seq - 1
                logger.warning(f"Sequence gap detected for {device_id}: expected {last_seq + 1}, got {seq} (gap={gap})")

            self._seq_tracker[device_id] = seq
            return False

    # -------------------------------------------------------------------
    # Message routing — IoT.md §3.1
    # -------------------------------------------------------------------

    def on_message(self, client, userdata, msg):
        """Callback when message received from MQTT.

        Routes messages by topic suffix to the appropriate handler.
        """
        try:
            topic_parts = msg.topic.split('/')
            device_id = topic_parts[1] if len(topic_parts) >= 2 else 'unknown'
            # Determine message category from topic
            # Possible patterns: iot/{id}/telemetry, iot/{id}/hello,
            #                    iot/{id}/status, iot/{id}/command/ack,
            #                    iot/{id}/ota/status
            topic_suffix = '/'.join(topic_parts[2:]) if len(topic_parts) > 2 else ''

            payload = msg.payload.decode('utf-8')
            data = json.loads(payload)

            # Update last-seen for any device message (IoT.md §5 REQ-ONLINE-001)
            self._device_last_seen[device_id] = datetime.now(timezone.utc).isoformat()

            # v2 deduplication by (device_id, seq)
            seq = data.get('seq', -1)
            msg_type = data.get('msg_type')

            if msg_type and self.is_duplicate(device_id, seq):
                return  # Drop duplicate

            logger.info(f"Received {topic_suffix} from {device_id} (seq={seq})")

            if topic_suffix == 'telemetry':
                self.handle_telemetry(device_id, data)
            elif topic_suffix == 'hello':
                self.handle_hello(device_id, data)
            elif topic_suffix == 'status':
                self.handle_status(device_id, data)
            elif topic_suffix == 'command/ack':
                self.handle_command_ack(device_id, data)
            elif topic_suffix == 'ota/status':
                self.handle_ota_status(device_id, data)
            else:
                # Fallback: treat as generic telemetry (backward compat)
                self.handle_telemetry(device_id, data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    # -------------------------------------------------------------------
    # Message handlers
    # -------------------------------------------------------------------

    def handle_telemetry(self, device_id, data):
        """Process a telemetry datagram (IoT.md §4.2)."""
        self.store_to_minio(device_id, data, 'telemetry')
        self.store_to_influxdb(device_id, data)

    def handle_hello(self, device_id, data):
        """Process a hello / heartbeat message (IoT.md §4.3)."""
        logger.info(
            f"Hello from {device_id}: fw={data.get('fw_version')}, "
            f"uptime={data.get('uptime_s')}s, brokers={data.get('broker_connections')}, "
            f"buf={data.get('buf_usage_pct')}%"
        )
        self.store_to_minio(device_id, data, 'hello')

    def handle_status(self, device_id, data):
        """Process an online/offline status message (IoT.md §3.4 / §5)."""
        status = data.get('status', 'unknown')
        logger.info(f"Device {device_id} status: {status}")
        self.store_to_minio(device_id, data, 'status')

    def handle_command_ack(self, device_id, data):
        """Process a command acknowledgement (IoT.md §6.5)."""
        cmd_id = data.get('cmd_id', 'unknown')
        result = data.get('result', 'unknown')
        detail = data.get('detail', '')
        logger.info(f"Command ack from {device_id}: cmd_id={cmd_id}, result={result}, detail={detail}")
        self.store_to_minio(device_id, data, 'command_ack')

    def handle_ota_status(self, device_id, data):
        """Process an OTA progress message (IoT.md §7.2)."""
        ota_state = data.get('ota_state', 'unknown')
        progress = data.get('progress_pct', 0)
        logger.info(f"OTA status from {device_id}: state={ota_state}, progress={progress}%")
        self.store_to_minio(device_id, data, 'ota_status')

    # -------------------------------------------------------------------
    # Storage
    # -------------------------------------------------------------------

    def store_to_minio(self, device_id, data, msg_category='telemetry'):
        """Store raw data to MinIO, partitioned by device and category."""
        try:
            timestamp = datetime.now().isoformat()
            filename = f"{device_id}/{msg_category}/{timestamp.replace(':', '-')}.json"

            json_data = json.dumps({
                'device_id': device_id,
                'timestamp': timestamp,
                'category': msg_category,
                'data': data
            }, indent=2)
            json_bytes = json_data.encode('utf-8')

            self.minio_client.put_object(
                self.minio_bucket,
                filename,
                data=BytesIO(json_bytes),
                length=len(json_bytes),
                content_type='application/json'
            )
            logger.info(f"Stored {msg_category} to MinIO: {filename}")
        except Exception as e:
            logger.error(f"Failed to store data to MinIO: {e}")

    def store_to_influxdb(self, device_id, data):
        """Store time series data to InfluxDB.

        Handles both v1 (flat key/value) and v2 (measurements array) payloads.
        """
        try:
            msg_ts = data.get('ts', data.get('timestamp', datetime.now().isoformat()))

            # v2 format with measurements array (IoT.md §4.2)
            measurements = data.get('measurements')
            if measurements and isinstance(measurements, list):
                for m in measurements:
                    m_type = m.get('type', 'unknown')
                    m_val = m.get('val')
                    m_ts = m.get('ts', msg_ts)
                    if m_val is not None and isinstance(m_val, (int, float)):
                        point = Point("iot_telemetry") \
                            .tag("device_id", device_id) \
                            .tag("metric", m_type) \
                            .field("value", float(m_val)) \
                            .time(m_ts)
                        if m.get('unit'):
                            point = point.tag("unit", m['unit'])
                        self.write_api.write(
                            bucket=self.influxdb_bucket,
                            org=self.influxdb_org,
                            record=point,
                        )
                logger.info(f"Stored {len(measurements)} measurements to InfluxDB for {device_id}")
                return

            # v1 fallback — flat key/value (IoT.md §13)
            timestamp = data.get('timestamp', datetime.now().isoformat())
            for key, value in data.items():
                if key in ('timestamp', 'device_id', 'v', 'seq', 'msg_type', 'ts'):
                    continue
                if isinstance(value, (int, float)):
                    point = Point("iot_telemetry") \
                        .tag("device_id", device_id) \
                        .tag("metric", key) \
                        .field("value", float(value)) \
                        .time(timestamp)
                    self.write_api.write(
                        bucket=self.influxdb_bucket,
                        org=self.influxdb_org,
                        record=point,
                    )
            logger.info(f"Stored v1 data to InfluxDB for device {device_id}")
        except Exception as e:
            logger.error(f"Failed to store data to InfluxDB: {e}")

    def run(self):
        """Start the MQTT collector"""
        logger.info("Starting MQTT Collector...")

        max_retries = 10
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
                break
            except Exception as e:
                logger.error(f"Failed to connect to MQTT broker (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error("Max retries reached. Exiting...")
                    return

        self.mqtt_client.loop_forever()


def start_health_server():
    """Start the health check HTTP server in a background thread"""
    health_port = int(os.getenv('HEALTH_PORT', 8081))
    health_app.run(host='0.0.0.0', port=health_port, threaded=True)


if __name__ == "__main__":
    collector_instance = MQTTCollector()

    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    logger.info("Health check server started")

    collector_instance.run()
