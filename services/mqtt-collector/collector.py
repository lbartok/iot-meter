import os
import json
import time
from datetime import datetime
from io import BytesIO
import paho.mqtt.client as mqtt
from minio import Minio
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
        
        # Initialize MinIO client
        self.minio_client = None
        self.init_minio()
        
        # Initialize InfluxDB client
        self.influx_client = None
        self.write_api = None
        self.init_influxdb()
        
        # Initialize MQTT client
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.on_disconnect = self.on_disconnect
        
    def init_minio(self):
        """Initialize MinIO client"""
        try:
            self.minio_client = Minio(
                self.minio_endpoint,
                access_key=self.minio_access_key,
                secret_key=self.minio_secret_key,
                secure=False
            )
            # Check if bucket exists
            if not self.minio_client.bucket_exists(self.minio_bucket):
                logger.warning(f"Bucket {self.minio_bucket} does not exist, waiting for creation...")
            logger.info("MinIO client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize MinIO client: {e}")
            
    def init_influxdb(self):
        """Initialize InfluxDB client"""
        try:
            self.influx_client = InfluxDBClient(
                url=self.influxdb_url,
                token=self.influxdb_token,
                org=self.influxdb_org
            )
            self.write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)
            logger.info("InfluxDB client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize InfluxDB client: {e}")
            
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            logger.info(f"Connected to MQTT broker at {self.mqtt_broker}:{self.mqtt_port}")
            client.subscribe(self.mqtt_topic)
            logger.info(f"Subscribed to topic: {self.mqtt_topic}")
        else:
            logger.error(f"Failed to connect to MQTT broker, return code: {rc}")
            
    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        logger.warning(f"Disconnected from MQTT broker, return code: {rc}")
        
    def on_message(self, client, userdata, msg):
        """Callback when message received from MQTT"""
        try:
            # Parse the topic to extract device ID
            topic_parts = msg.topic.split('/')
            device_id = topic_parts[1] if len(topic_parts) >= 2 else 'unknown'
            
            # Parse message payload
            payload = msg.payload.decode('utf-8')
            data = json.loads(payload)
            
            logger.info(f"Received message from device {device_id}: {data}")
            
            # Store to MinIO (raw data archive)
            self.store_to_minio(device_id, data)
            
            # Store to InfluxDB (time series)
            self.store_to_influxdb(device_id, data)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            
    def store_to_minio(self, device_id, data):
        """Store raw data to MinIO"""
        try:
            timestamp = datetime.now().isoformat()
            filename = f"{device_id}/{timestamp.replace(':', '-')}.json"
            
            # Convert data to JSON bytes
            json_data = json.dumps({
                'device_id': device_id,
                'timestamp': timestamp,
                'data': data
            }, indent=2)
            json_bytes = json_data.encode('utf-8')
            
            # Upload to MinIO using BytesIO
            self.minio_client.put_object(
                self.minio_bucket,
                filename,
                data=BytesIO(json_bytes),
                length=len(json_bytes),
                content_type='application/json'
            )
            logger.info(f"Stored data to MinIO: {filename}")
        except Exception as e:
            logger.error(f"Failed to store data to MinIO: {e}")
            
    def store_to_influxdb(self, device_id, data):
        """Store time series data to InfluxDB"""
        try:
            # Extract metrics from data
            timestamp = data.get('timestamp', datetime.now().isoformat())
            
            # Create points for each metric in the data
            for key, value in data.items():
                if key == 'timestamp':
                    continue
                    
                # Only store numeric values in InfluxDB
                if isinstance(value, (int, float)):
                    point = Point("iot_telemetry") \
                        .tag("device_id", device_id) \
                        .tag("metric", key) \
                        .field("value", float(value)) \
                        .time(timestamp)
                    
                    self.write_api.write(bucket=self.influxdb_bucket, org=self.influxdb_org, record=point)
                    
            logger.info(f"Stored data to InfluxDB for device {device_id}")
        except Exception as e:
            logger.error(f"Failed to store data to InfluxDB: {e}")
            
    def run(self):
        """Start the MQTT collector"""
        logger.info("Starting MQTT Collector...")
        
        # Connect to MQTT broker with retry logic
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
        
        # Start the MQTT loop
        self.mqtt_client.loop_forever()

if __name__ == "__main__":
    collector = MQTTCollector()
    collector.run()
