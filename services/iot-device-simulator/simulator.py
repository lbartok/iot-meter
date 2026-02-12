"""
IoT Device Simulator — v2 Protocol

Simulates rail-mobility power meter devices (DC and AC traction metering)
per the requirements in IoT.md v2.

Key features:
  - v2 envelope with seq numbers (REQ-SEQ-001)
  - QoS 2 exactly-once delivery (REQ-QOS-001)
  - Hello messages with suppression rule (REQ-HELLO-001)
  - LWT registration for offline detection (REQ-LWT-001)
  - Server command subscription and ack (IoT.md §6)
  - 1-second sampling, configurable send/hello intervals (IoT.md §4.2)
"""

import os
import json
import time
import random
import threading
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
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
simulator_ready = False


@health_app.route('/healthz', methods=['GET'])
def liveness():
    """Liveness probe - is the process alive?"""
    return jsonify({'status': 'alive', 'service': 'iot-device-simulator'}), 200


@health_app.route('/readyz', methods=['GET'])
def readiness():
    """Readiness probe - are the simulators connected?"""
    if simulator_ready:
        return jsonify({'status': 'ready', 'service': 'iot-device-simulator'}), 200
    return jsonify({'status': 'not ready', 'service': 'iot-device-simulator'}), 503


class IoTDeviceSimulator:
    """Simulates a single power-meter device using the v2 protocol.

    See IoT.md §4 for payload format, §9 for configuration parameters.
    """

    def __init__(self, device_id, device_type, fw_version='2.1.0'):
        self.device_id = device_id
        self.device_type = device_type  # power_meter_dc | power_meter_ac
        self.fw_version = fw_version
        self.mqtt_broker = os.getenv('MQTT_BROKER', 'localhost')
        self.mqtt_port = int(os.getenv('MQTT_PORT', 1883))

        # Configurable intervals — IoT.md §9
        self.sampling_cadence_ms = int(os.getenv('SAMPLING_CADENCE_MS', 1000))
        self.send_interval_s = int(os.getenv('SEND_INTERVAL_S', 10))
        self.hello_interval_s = int(os.getenv('HELLO_INTERVAL_S', 30))

        # Monotonic sequence counter — IoT.md §4.1 / REQ-SEQ-001
        self._seq = 0
        self._seq_lock = threading.Lock()

        # Uptime tracking
        self._start_time = time.time()

        # Measurement buffer (sampled at cadence, sent at send_interval)
        self._measurement_buffer = []
        self._buffer_lock = threading.Lock()

        # Connection state
        self.connected = False

        # MQTT topics — IoT.md §3.1
        self.topic_telemetry = f"iot/{device_id}/telemetry"
        self.topic_hello = f"iot/{device_id}/hello"
        self.topic_status = f"iot/{device_id}/status"
        self.topic_command = f"iot/{device_id}/command"
        self.topic_command_ack = f"iot/{device_id}/command/ack"
        self.topic_ota_status = f"iot/{device_id}/ota/status"

        # MQTT client setup with LWT — IoT.md §3.4 / REQ-LWT-001
        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=device_id,
            clean_session=False,  # Persistent session — IoT.md §3.3
        )
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.on_message = self.on_message

        # Set LWT before connecting
        lwt_payload = json.dumps({
            'v': 2,
            'device_id': device_id,
            'status': 'offline',
            'ts': self._now_iso(),
        })
        self.mqtt_client.will_set(self.topic_status, lwt_payload, qos=1, retain=True)

    # -------------------------------------------------------------------
    # Sequence management
    # -------------------------------------------------------------------

    def next_seq(self):
        """Return the next sequence number (thread-safe)."""
        with self._seq_lock:
            seq = self._seq
            self._seq = (self._seq + 1) % (2**32)
            return seq

    # -------------------------------------------------------------------
    # Time helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _now_iso():
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _uptime_s(self):
        return int(time.time() - self._start_time)

    # -------------------------------------------------------------------
    # MQTT callbacks — paho-mqtt v2 API (5-param)
    # -------------------------------------------------------------------

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to MQTT broker."""
        if reason_code == 0:
            self.connected = True
            logger.info(f"Device {self.device_id} connected to MQTT broker")

            # Subscribe to command topic — IoT.md §6
            client.subscribe(self.topic_command, qos=2)
            logger.info(f"Device {self.device_id} subscribed to {self.topic_command}")

            # Publish online status — IoT.md §3.4
            self._publish_status('online')
        else:
            logger.error(f"Device {self.device_id} failed to connect, reason code: {reason_code}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Callback when disconnected from MQTT broker."""
        self.connected = False
        logger.warning(f"Device {self.device_id} disconnected from MQTT broker")

    def on_message(self, client, userdata, msg):
        """Handle incoming commands from server — IoT.md §6."""
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            cmd = data.get('cmd')
            cmd_id = data.get('cmd_id', 'unknown')
            params = data.get('params', {})

            logger.info(f"Device {self.device_id} received command: {cmd} (cmd_id={cmd_id})")

            if cmd == 'update_config':
                self._handle_update_config(cmd_id, params)
            elif cmd == 'request_status':
                self._handle_request_status(cmd_id)
            elif cmd == 'start_ota':
                self._handle_start_ota(cmd_id, params)
            elif cmd == 'reboot':
                self._send_command_ack(cmd_id, 'accepted', 'Reboot scheduled')
            elif cmd == 'factory_reset':
                self._send_command_ack(cmd_id, 'accepted', 'Factory reset scheduled')
            else:
                self._send_command_ack(cmd_id, 'unsupported', f'Unknown command: {cmd}')

        except json.JSONDecodeError as e:
            logger.error(f"Device {self.device_id} failed to parse command: {e}")
        except Exception as e:
            logger.error(f"Device {self.device_id} error processing command: {e}")

    # -------------------------------------------------------------------
    # Command handlers — IoT.md §6
    # -------------------------------------------------------------------

    def _handle_update_config(self, cmd_id, params):
        """Apply config update and ack — IoT.md §6.3 / REQ-CONFIG-001."""
        changes = []
        if 'sampling_cadence_ms' in params:
            self.sampling_cadence_ms = params['sampling_cadence_ms']
            changes.append(f'sampling_cadence_ms={self.sampling_cadence_ms}')
        if 'send_interval_s' in params:
            self.send_interval_s = params['send_interval_s']
            changes.append(f'send_interval_s={self.send_interval_s}')
        if 'hello_interval_s' in params:
            self.hello_interval_s = params['hello_interval_s']
            changes.append(f'hello_interval_s={self.hello_interval_s}')

        detail = 'Config updated: ' + ', '.join(changes) if changes else 'No changes applied'
        self._send_command_ack(cmd_id, 'accepted', detail)

    def _handle_request_status(self, cmd_id):
        """Reply with an immediate hello message — IoT.md §6.2."""
        self._send_command_ack(cmd_id, 'accepted', 'Status requested')
        self._publish_hello()

    def _handle_start_ota(self, cmd_id, params):
        """Simulate OTA upgrade — IoT.md §7."""
        fw_version_target = params.get('fw_version', 'unknown')
        self._send_command_ack(cmd_id, 'accepted', f'OTA started for {fw_version_target}')
        # In a real device, OTA would happen here; simulator just acks.
        self._publish_ota_status(cmd_id, 'downloading', 0, fw_version_target)
        self._publish_ota_status(cmd_id, 'downloading', 100, fw_version_target)
        self._publish_ota_status(cmd_id, 'verifying', 100, fw_version_target)
        self._publish_ota_status(cmd_id, 'success', 100, fw_version_target)

    # -------------------------------------------------------------------
    # Publishing helpers
    # -------------------------------------------------------------------

    def _publish_status(self, status):
        """Publish online/offline status — IoT.md §3.4."""
        payload = {
            'v': 2,
            'device_id': self.device_id,
            'status': status,
            'ts': self._now_iso(),
        }
        self.mqtt_client.publish(self.topic_status, json.dumps(payload), qos=1, retain=True)
        logger.info(f"Device {self.device_id} published status: {status}")

    def _send_command_ack(self, cmd_id, result, detail=''):
        """Send command acknowledgement — IoT.md §6.5."""
        payload = {
            'v': 2,
            'device_id': self.device_id,
            'ts': self._now_iso(),
            'seq': self.next_seq(),
            'msg_type': 'command_ack',
            'cmd_id': cmd_id,
            'result': result,
            'detail': detail,
        }
        self.mqtt_client.publish(self.topic_command_ack, json.dumps(payload), qos=2)

    def _publish_ota_status(self, cmd_id, ota_state, progress_pct, fw_version_target):
        """Publish OTA progress — IoT.md §7.2."""
        payload = {
            'v': 2,
            'device_id': self.device_id,
            'ts': self._now_iso(),
            'seq': self.next_seq(),
            'msg_type': 'ota_status',
            'cmd_id': cmd_id,
            'ota_state': ota_state,
            'progress_pct': progress_pct,
            'fw_version_target': fw_version_target,
        }
        self.mqtt_client.publish(self.topic_ota_status, json.dumps(payload), qos=1)

    def _publish_hello(self):
        """Publish a hello message — IoT.md §4.3."""
        payload = {
            'v': 2,
            'device_id': self.device_id,
            'ts': self._now_iso(),
            'seq': self.next_seq(),
            'msg_type': 'hello',
            'fw_version': self.fw_version,
            'uptime_s': self._uptime_s(),
            'broker_connections': 1,
            'buf_usage_pct': self._buf_usage_pct(),
        }
        self.mqtt_client.publish(self.topic_hello, json.dumps(payload), qos=2)
        logger.info(f"Device {self.device_id} sent hello (uptime={payload['uptime_s']}s)")

    def _buf_usage_pct(self):
        """Estimate buffer usage as percentage."""
        max_buf = self.send_interval_s * (1000 // max(self.sampling_cadence_ms, 1)) * 2
        with self._buffer_lock:
            current = len(self._measurement_buffer)
        return min(int(current / max(max_buf, 1) * 100), 100)

    # -------------------------------------------------------------------
    # Telemetry generation — IoT.md §4.2, §8.1
    # -------------------------------------------------------------------

    def generate_sample(self):
        """Generate a single measurement sample at the current timestamp.

        Returns a list of measurement dicts for one sampling instant.
        DC devices: voltage_dc + current_dc.
        AC devices: voltage_ac + current_ac + frequency + pf.
        """
        ts = self._now_iso()

        if self.device_type == 'power_meter_dc':
            return [
                {'ts': ts, 'type': 'voltage_dc', 'val': round(random.uniform(700, 800), 1), 'unit': 'V'},
                {'ts': ts, 'type': 'current_dc', 'val': round(random.uniform(200, 400), 1), 'unit': 'A'},
            ]
        elif self.device_type == 'power_meter_ac':
            return [
                {'ts': ts, 'type': 'voltage_ac', 'val': round(random.uniform(24000, 26000), 0), 'unit': 'V'},
                {'ts': ts, 'type': 'current_ac', 'val': round(random.uniform(100, 200), 1), 'unit': 'A'},
                {'ts': ts, 'type': 'frequency', 'val': round(random.uniform(49.9, 50.1), 2), 'unit': 'Hz'},
                {'ts': ts, 'type': 'pf', 'val': round(random.uniform(0.92, 0.99), 2)},
            ]
        else:
            # Generic fallback
            return [
                {'ts': ts, 'type': 'temperature', 'val': round(random.uniform(18, 45), 1), 'unit': 'Cel'},
            ]

    def _flush_and_publish_telemetry(self):
        """Batch buffered measurements into a datagram and publish — IoT.md §4.2."""
        with self._buffer_lock:
            if not self._measurement_buffer:
                return
            measurements = self._measurement_buffer[:]
            self._measurement_buffer.clear()

        payload = {
            'v': 2,
            'device_id': self.device_id,
            'ts': self._now_iso(),
            'seq': self.next_seq(),
            'msg_type': 'telemetry',
            'measurements': measurements,
        }

        result = self.mqtt_client.publish(self.topic_telemetry, json.dumps(payload), qos=2)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Device {self.device_id} published datagram: {len(measurements)} measurements")
        else:
            logger.error(f"Device {self.device_id} failed to publish, rc={result.rc}")

    # -------------------------------------------------------------------
    # Connection
    # -------------------------------------------------------------------

    def connect(self):
        """Connect to MQTT broker with retry logic."""
        max_retries = 10
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, keepalive=15)
                self.mqtt_client.loop_start()

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

    # -------------------------------------------------------------------
    # Main run loop
    # -------------------------------------------------------------------

    def run(self, interval=None):
        """Run the device simulator.

        Sampling happens at ``sampling_cadence_ms``.
        Publishing happens at ``send_interval_s``.
        Hello happens at ``hello_interval_s`` (see REQ-HELLO-001 for suppression).
        """
        logger.info(
            f"Starting v2 simulator for {self.device_id} "
            f"(type={self.device_type}, sample={self.sampling_cadence_ms}ms, "
            f"send={self.send_interval_s}s, hello={self.hello_interval_s}s)"
        )

        if not self.connect():
            logger.error(f"Device {self.device_id} failed to connect. Exiting...")
            return

        last_send = time.time()
        last_hello = time.time()

        try:
            while True:
                if not self.connected:
                    time.sleep(1)
                    continue

                # Sample at cadence — IoT.md §4.2
                samples = self.generate_sample()
                with self._buffer_lock:
                    self._measurement_buffer.extend(samples)

                now = time.time()

                # Publish datagram at send_interval
                if now - last_send >= self.send_interval_s:
                    self._flush_and_publish_telemetry()
                    last_send = now

                # Hello logic — REQ-HELLO-001
                # Only send explicit hello if send_interval > hello_interval
                if self.send_interval_s > self.hello_interval_s:
                    if now - last_hello >= self.hello_interval_s:
                        self._publish_hello()
                        last_hello = now

                time.sleep(self.sampling_cadence_ms / 1000.0)

        except KeyboardInterrupt:
            logger.info(f"Device {self.device_id} shutting down...")
            self._publish_status('offline')
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()


def start_health_server():
    """Start the health check HTTP server in a background thread"""
    health_port = int(os.getenv('HEALTH_PORT', 8082))
    health_app.run(host='0.0.0.0', port=health_port, threaded=True)


def main():
    """Main function to run multiple device simulators"""
    global simulator_ready

    device_count = int(os.getenv('DEVICE_COUNT', 3))

    # Start health check server in background thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    logger.info("Health check server started")

    # Define device configurations — rail mobility power meters
    devices = []
    device_configs = [
        ('dc-meter-001', 'power_meter_dc'),
        ('dc-meter-002', 'power_meter_dc'),
        ('ac-meter-001', 'power_meter_ac'),
    ]

    for i in range(device_count):
        idx = i % len(device_configs)
        device_id, device_type = device_configs[idx]
        # Use unique IDs when device_count > len(device_configs)
        if i >= len(device_configs):
            device_id = f"meter-{str(i + 1).zfill(3)}"
        device = IoTDeviceSimulator(device_id, device_type)
        devices.append(device)

    # Start device threads
    if devices:
        logger.info(f"Starting {device_count} v2 device simulators")

        threads = []
        for device in devices:
            thread = threading.Thread(target=device.run, daemon=True)
            thread.start()
            threads.append(thread)
            time.sleep(1)  # Stagger starts

        simulator_ready = True
        logger.info("All simulators started, service is ready")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down all simulators...")


if __name__ == "__main__":
    main()
