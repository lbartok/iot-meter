#!/usr/bin/env python3
"""
IoT Device Client Example — v2 payload format

Demonstrates connecting a DC/AC power meter to the IoT Meter platform
via MQTT using the v2 telemetry payload schema.
"""

import json
import time
import random
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


class IoTDevice:
    """Simulates a rail-mobility power meter sending v2 telemetry."""

    def __init__(self, device_id: str, device_type: str,
                 mqtt_broker: str = "localhost", mqtt_port: int = 1883):
        self.device_id = device_id
        self.device_type = device_type  # power_meter_dc | power_meter_ac
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.topic = f"iot/{device_id}/telemetry"
        self.seq = 0

        # paho-mqtt v2 API
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=device_id,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish

        self.connected = False

    # ── Callbacks (paho-mqtt v2 signature) ────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.connected = True
            print(f"[{self.device_id}] Connected to MQTT broker")
        else:
            print(f"[{self.device_id}] Connection failed: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        print(f"[{self.device_id}] Disconnected from MQTT broker")

    def _on_publish(self, client, userdata, mid, reason_codes, properties):
        pass  # suppress per-message noise

    # ── Connection ────────────────────────────────────────────────

    def connect(self) -> bool:
        print(f"[{self.device_id}] Connecting to {self.mqtt_broker}:{self.mqtt_port}...")
        self.client.connect(self.mqtt_broker, self.mqtt_port, 60)
        self.client.loop_start()

        deadline = time.time() + 10
        while not self.connected and time.time() < deadline:
            time.sleep(0.5)
        return self.connected

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    # ── v2 Payload generation ─────────────────────────────────────

    def _generate_measurements(self) -> list:
        """Generate realistic measurements based on device type."""
        if self.device_type == "power_meter_dc":
            voltage = round(random.uniform(600.0, 800.0), 2)
            current = round(random.uniform(50.0, 300.0), 2)
            return [
                {"n": "voltage_dc", "v": voltage, "u": "V"},
                {"n": "current_dc", "v": current, "u": "A"},
                {"n": "power_dc", "v": round(voltage * current, 2), "u": "W"},
                {"n": "energy_dc", "v": round(random.uniform(100.0, 5000.0), 2), "u": "Wh"},
            ]
        elif self.device_type == "power_meter_ac":
            voltage = round(random.uniform(220.0, 240.0), 2)
            current = round(random.uniform(5.0, 50.0), 2)
            return [
                {"n": "voltage_ac_rms", "v": voltage, "u": "V"},
                {"n": "current_ac_rms", "v": current, "u": "A"},
                {"n": "power_ac", "v": round(voltage * current * 0.95, 2), "u": "W"},
                {"n": "frequency", "v": round(random.uniform(49.9, 50.1), 2), "u": "Hz"},
                {"n": "power_factor", "v": round(random.uniform(0.90, 0.99), 3), "u": ""},
            ]
        else:
            return [{"n": "value", "v": round(random.uniform(0.0, 100.0), 2), "u": ""}]

    def _build_payload(self) -> dict:
        """Build a v2 telemetry message."""
        self.seq += 1
        return {
            "v": 2,
            "ts": datetime.now(timezone.utc).isoformat(),
            "device_id": self.device_id,
            "msg_type": "telemetry",
            "seq": self.seq,
            "measurements": self._generate_measurements(),
        }

    # ── Publish ───────────────────────────────────────────────────

    def publish(self) -> bool:
        if not self.connected:
            print(f"[{self.device_id}] Not connected — skipping")
            return False

        payload = self._build_payload()
        result = self.client.publish(self.topic, json.dumps(payload), qos=1)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"[{self.device_id}] seq={payload['seq']}  "
                  f"measurements={len(payload['measurements'])}")
            return True
        else:
            print(f"[{self.device_id}] Publish failed: rc={result.rc}")
            return False

    def run(self, interval=5.0, duration=None):
        """Publish telemetry in a loop.

        Args:
            interval: Seconds between publishes.
            duration: Total runtime in seconds (None = infinite).
        """
        if not self.connect():
            print(f"[{self.device_id}] Failed to connect")
            return

        print(f"[{self.device_id}] Publishing every {interval}s ...")
        start = time.time()
        try:
            while True:
                self.publish()
                time.sleep(interval)
                if duration and (time.time() - start) >= duration:
                    print(f"[{self.device_id}] Duration {duration}s reached")
                    break
        except KeyboardInterrupt:
            print(f"\n[{self.device_id}] Interrupted")
        finally:
            self.disconnect()
            print(f"[{self.device_id}] Done")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="IoT Device Client (v2 payload)")
    parser.add_argument("--device-id", default="device-custom-001")
    parser.add_argument("--device-type", default="power_meter_dc",
                        choices=["power_meter_dc", "power_meter_ac", "generic"])
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=None)
    args = parser.parse_args()

    device = IoTDevice(args.device_id, args.device_type, args.broker, args.port)
    device.run(interval=args.interval, duration=args.duration)


if __name__ == "__main__":
    main()
