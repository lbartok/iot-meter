#!/usr/bin/env python3
"""
IoT Device Client Example
This script demonstrates how to connect an IoT device to the system
"""

import json
import time
import random
from datetime import datetime
import paho.mqtt.client as mqtt


class IoTDevice:
    def __init__(self, device_id, device_type, mqtt_broker="localhost", mqtt_port=1883):
        self.device_id = device_id
        self.device_type = device_type
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.topic = f"iot/{device_id}/telemetry"
        
        # Create MQTT client
        self.client = mqtt.Client(client_id=device_id)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_publish = self.on_publish
        
        self.connected = False
        
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            print(f"[{self.device_id}] Connected to MQTT broker")
        else:
            print(f"[{self.device_id}] Connection failed with code {rc}")
            
    def on_disconnect(self, client, userdata, rc):
        self.connected = False
        print(f"[{self.device_id}] Disconnected from MQTT broker")
        
    def on_publish(self, client, userdata, mid):
        print(f"[{self.device_id}] Message {mid} published")
        
    def connect(self):
        """Connect to MQTT broker"""
        print(f"[{self.device_id}] Connecting to {self.mqtt_broker}:{self.mqtt_port}...")
        self.client.connect(self.mqtt_broker, self.mqtt_port, 60)
        self.client.loop_start()
        
        # Wait for connection
        timeout = 10
        start = time.time()
        while not self.connected and (time.time() - start) < timeout:
            time.sleep(0.5)
            
        return self.connected
        
    def disconnect(self):
        """Disconnect from MQTT broker"""
        self.client.loop_stop()
        self.client.disconnect()
        
    def generate_data(self):
        """Generate sensor data based on device type"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "device_id": self.device_id
        }
        
        if self.device_type == "temperature":
            data["temperature"] = round(random.uniform(18.0, 30.0), 2)
            data["unit"] = "celsius"
        elif self.device_type == "humidity":
            data["humidity"] = round(random.uniform(30.0, 80.0), 2)
            data["unit"] = "percentage"
        elif self.device_type == "power":
            data["voltage"] = round(random.uniform(220.0, 240.0), 2)
            data["current"] = round(random.uniform(0.5, 10.0), 2)
            data["power"] = round(data["voltage"] * data["current"], 2)
            data["unit"] = "watts"
        else:
            data["value"] = round(random.uniform(0.0, 100.0), 2)
            
        return data
        
    def publish_data(self):
        """Generate and publish sensor data"""
        if not self.connected:
            print(f"[{self.device_id}] Not connected, skipping publish")
            return False
            
        data = self.generate_data()
        payload = json.dumps(data)
        
        result = self.client.publish(self.topic, payload, qos=1)
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"[{self.device_id}] Published: {data}")
            return True
        else:
            print(f"[{self.device_id}] Publish failed with code {result.rc}")
            return False
            
    def run(self, interval=5, duration=None):
        """
        Run the device in a loop
        
        Args:
            interval: Seconds between publishes
            duration: Total duration in seconds (None for infinite)
        """
        if not self.connect():
            print(f"[{self.device_id}] Failed to connect")
            return
            
        print(f"[{self.device_id}] Starting to publish every {interval} seconds...")
        
        start_time = time.time()
        try:
            while True:
                self.publish_data()
                time.sleep(interval)
                
                if duration and (time.time() - start_time) >= duration:
                    print(f"[{self.device_id}] Duration {duration}s reached, stopping...")
                    break
                    
        except KeyboardInterrupt:
            print(f"\n[{self.device_id}] Interrupted by user")
        finally:
            self.disconnect()
            print(f"[{self.device_id}] Disconnected")


def main():
    """Example usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='IoT Device Client')
    parser.add_argument('--device-id', default='device-custom-001', help='Device ID')
    parser.add_argument('--device-type', default='temperature', 
                       choices=['temperature', 'humidity', 'power', 'generic'],
                       help='Device type')
    parser.add_argument('--broker', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--interval', type=int, default=5, help='Publish interval in seconds')
    parser.add_argument('--duration', type=int, help='Run duration in seconds (default: infinite)')
    
    args = parser.parse_args()
    
    # Create and run device
    device = IoTDevice(args.device_id, args.device_type, args.broker, args.port)
    device.run(interval=args.interval, duration=args.duration)


if __name__ == "__main__":
    main()
