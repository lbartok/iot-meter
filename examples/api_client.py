#!/usr/bin/env python3
"""
API Client Example
This script demonstrates how to interact with the Device Manager API
"""

import requests
import json
from datetime import datetime


class IoTMeterAPIClient:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url
        self.session = requests.Session()
        
    def health_check(self):
        """Check API health"""
        response = self.session.get(f"{self.base_url}/health")
        return response.json()
        
    def get_devices(self, status=None, device_type=None):
        """Get all devices with optional filters"""
        params = {}
        if status:
            params['status'] = status
        if device_type:
            params['type'] = device_type
            
        response = self.session.get(f"{self.base_url}/api/devices", params=params)
        return response.json()
        
    def get_device(self, device_id):
        """Get a specific device"""
        response = self.session.get(f"{self.base_url}/api/devices/{device_id}")
        return response.json()
        
    def create_device(self, device_id, device_name, device_type=None, 
                     location=None, status="active", metadata=None):
        """Create a new device"""
        data = {
            "device_id": device_id,
            "device_name": device_name,
            "device_type": device_type,
            "location": location,
            "status": status,
            "metadata": metadata
        }
        response = self.session.post(f"{self.base_url}/api/devices", json=data)
        return response.json()
        
    def update_device(self, device_id, **kwargs):
        """Update a device"""
        response = self.session.put(f"{self.base_url}/api/devices/{device_id}", json=kwargs)
        return response.json()
        
    def delete_device(self, device_id):
        """Delete a device"""
        response = self.session.delete(f"{self.base_url}/api/devices/{device_id}")
        return response.json()
        
    def send_heartbeat(self, device_id):
        """Send device heartbeat"""
        response = self.session.post(f"{self.base_url}/api/devices/{device_id}/heartbeat")
        return response.json()
        
    def get_metrics(self, device_id, start="-1h", stop="now()", metric=None):
        """Get device metrics"""
        params = {"start": start, "stop": stop}
        if metric:
            params['metric'] = metric
            
        response = self.session.get(f"{self.base_url}/api/devices/{device_id}/metrics", 
                                   params=params)
        return response.json()
        
    def get_raw_data(self, device_id):
        """Get raw data files for a device"""
        response = self.session.get(f"{self.base_url}/api/devices/{device_id}/raw-data")
        return response.json()
        
    def get_alerts(self, device_id, acknowledged=None):
        """Get device alerts"""
        params = {}
        if acknowledged is not None:
            params['acknowledged'] = str(acknowledged).lower()
            
        response = self.session.get(f"{self.base_url}/api/devices/{device_id}/alerts", 
                                   params=params)
        return response.json()
        
    def create_alert(self, device_id, alert_type, severity="info", message=""):
        """Create a new alert"""
        data = {
            "alert_type": alert_type,
            "severity": severity,
            "message": message
        }
        response = self.session.post(f"{self.base_url}/api/devices/{device_id}/alerts", 
                                    json=data)
        return response.json()
        
    def acknowledge_alert(self, alert_id):
        """Acknowledge an alert"""
        response = self.session.post(f"{self.base_url}/api/alerts/{alert_id}/acknowledge")
        return response.json()
        
    def get_stats(self):
        """Get system statistics"""
        response = self.session.get(f"{self.base_url}/api/stats")
        return response.json()


def example_usage():
    """Example usage of the API client"""
    
    # Create client
    client = IoTMeterAPIClient()
    
    print("=== IoT Meter API Client Example ===\n")
    
    # 1. Health check
    print("1. Health Check:")
    health = client.health_check()
    print(json.dumps(health, indent=2))
    print()
    
    # 2. Get system statistics
    print("2. System Statistics:")
    stats = client.get_stats()
    print(json.dumps(stats, indent=2))
    print()
    
    # 3. Get all devices
    print("3. All Devices:")
    devices = client.get_devices()
    print(f"Found {len(devices)} devices")
    for device in devices[:3]:  # Show first 3
        print(f"  - {device['device_id']}: {device['device_name']} ({device['status']})")
    print()
    
    # 4. Create a new device
    print("4. Creating New Device:")
    new_device = client.create_device(
        device_id="api-example-001",
        device_name="API Example Sensor",
        device_type="temperature",
        location="Example Lab",
        metadata={"created_by": "example_script"}
    )
    print(json.dumps(new_device, indent=2))
    print()
    
    # 5. Update the device
    print("5. Updating Device:")
    updated = client.update_device(
        "api-example-001",
        location="Updated Example Lab",
        status="active"
    )
    print(json.dumps(updated, indent=2))
    print()
    
    # 6. Send heartbeat
    print("6. Sending Heartbeat:")
    heartbeat = client.send_heartbeat("api-example-001")
    print(json.dumps(heartbeat, indent=2))
    print()
    
    # 7. Create alert
    print("7. Creating Alert:")
    alert = client.create_alert(
        "api-example-001",
        alert_type="test_alert",
        severity="info",
        message="This is a test alert created by the example script"
    )
    print(json.dumps(alert, indent=2))
    print()
    
    # 8. Get alerts
    print("8. Getting Device Alerts:")
    alerts = client.get_alerts("api-example-001")
    print(json.dumps(alerts, indent=2))
    print()
    
    # 9. Get metrics for a device (if any exist)
    print("9. Getting Device Metrics (device-001):")
    try:
        metrics = client.get_metrics("device-001", start="-1h")
        print(f"Found {len(metrics)} metric points in the last hour")
        if metrics:
            print("Sample metric:")
            print(json.dumps(metrics[0], indent=2))
    except Exception as e:
        print(f"Error getting metrics: {e}")
    print()
    
    # 10. Clean up - delete the example device
    print("10. Deleting Example Device:")
    result = client.delete_device("api-example-001")
    print(json.dumps(result, indent=2))
    print()
    
    print("=== Example Complete ===")


if __name__ == "__main__":
    example_usage()
