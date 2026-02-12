import os
import json
import time
import random
from datetime import datetime
import paho.mqtt.client as mqtt
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class IoTDeviceSimulator:
    def __init__(self, device_id, device_type):
        self.device_id = device_id
        self.device_type = device_type
        self.mqtt_broker = os.getenv('MQTT_BROKER', 'localhost')
        self.mqtt_port = int(os.getenv('MQTT_PORT', 1883))
        self.mqtt_topic = f"iot/{device_id}/telemetry"
        
        self.mqtt_client = mqtt.Client(client_id=device_id)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        
        self.connected = False
        
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            self.connected = True
            logger.info(f"Device {self.device_id} connected to MQTT broker")
        else:
            logger.error(f"Device {self.device_id} failed to connect, return code: {rc}")
            
    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        self.connected = False
        logger.warning(f"Device {self.device_id} disconnected from MQTT broker")
        
    def connect(self):
        """Connect to MQTT broker with retry logic"""
        max_retries = 10
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
                self.mqtt_client.loop_start()
                
                # Wait for connection
                wait_time = 0
                while not self.connected and wait_time < 10:
                    time.sleep(1)
                    wait_time += 1
                
                if self.connected:
                    return True
                    
            except Exception as e:
                logger.error(f"Device {self.device_id} connection attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
        
        return False
        
    def generate_telemetry(self):
        """Generate simulated telemetry data based on device type"""
        base_data = {
            'timestamp': datetime.now().isoformat(),
            'device_id': self.device_id
        }
        
        if self.device_type == 'temperature':
            # Simulate temperature sensor
            base_data.update({
                'temperature': round(random.uniform(18.0, 28.0), 2),
                'unit': 'celsius'
            })
        elif self.device_type == 'humidity':
            # Simulate humidity sensor
            base_data.update({
                'humidity': round(random.uniform(30.0, 80.0), 2),
                'unit': 'percentage'
            })
        elif self.device_type == 'power':
            # Simulate power meter
            base_data.update({
                'voltage': round(random.uniform(220.0, 240.0), 2),
                'current': round(random.uniform(0.5, 10.0), 2),
                'power': round(random.uniform(100.0, 2000.0), 2),
                'unit': 'watts'
            })
        else:
            # Generic sensor
            base_data.update({
                'value': round(random.uniform(0.0, 100.0), 2)
            })
        
        return base_data
        
    def publish_telemetry(self):
        """Generate and publish telemetry data"""
        if not self.connected:
            logger.warning(f"Device {self.device_id} not connected, skipping publish")
            return
            
        try:
            data = self.generate_telemetry()
            payload = json.dumps(data)
            
            result = self.mqtt_client.publish(self.mqtt_topic, payload, qos=1)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Device {self.device_id} published: {data}")
            else:
                logger.error(f"Device {self.device_id} failed to publish, error code: {result.rc}")
                
        except Exception as e:
            logger.error(f"Device {self.device_id} error publishing telemetry: {e}")
            
    def run(self, interval=5):
        """Run the device simulator with specified publish interval"""
        logger.info(f"Starting device simulator for {self.device_id} (type: {self.device_type})")
        
        if not self.connect():
            logger.error(f"Device {self.device_id} failed to connect. Exiting...")
            return
        
        try:
            while True:
                self.publish_telemetry()
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info(f"Device {self.device_id} shutting down...")
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

def main():
    """Main function to run multiple device simulators"""
    device_count = int(os.getenv('DEVICE_COUNT', 3))
    publish_interval = int(os.getenv('PUBLISH_INTERVAL', 5))
    
    # Define device configurations
    devices = []
    device_types = ['temperature', 'humidity', 'power']
    
    for i in range(device_count):
        device_id = f"device-{str(i+1).zfill(3)}"
        device_type = device_types[i % len(device_types)]
        device = IoTDeviceSimulator(device_id, device_type)
        devices.append(device)
    
    # Start first device in main thread
    if devices:
        logger.info(f"Starting {device_count} device simulators with {publish_interval}s interval")
        
        # For simplicity, we'll run devices sequentially with staggered starts
        # In production, you'd use threading or multiprocessing
        import threading
        
        threads = []
        for device in devices:
            thread = threading.Thread(target=device.run, args=(publish_interval,))
            thread.daemon = True
            thread.start()
            threads.append(thread)
            time.sleep(1)  # Stagger the starts
        
        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down all simulators...")

if __name__ == "__main__":
    main()
