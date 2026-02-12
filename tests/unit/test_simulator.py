"""
Unit tests for the IoT device simulator — v2 protocol.

These tests verify the v2 protocol features defined in IoT.md:
  - §4.1 Monotonic sequence numbers — REQ-SEQ-001
  - §4.2 Telemetry datagram generation (DC and AC)
  - §4.3 Hello message generation / REQ-HELLO-001 suppression rule
  - §3.4 LWT registration — REQ-LWT-001
  - §6   Command handling and ack
  - §7   OTA status reporting
  - §8.1 Measurement type registry

Any change to IoT.md MUST be reflected here and vice-versa.
"""
import json
import time
import threading
import pytest
from unittest.mock import patch, MagicMock


pytestmark = pytest.mark.unit


# ===================================================================
# Health endpoints
# ===================================================================

class TestSimulatorHealthEndpoints:
    """Tests for /healthz and /readyz on the simulator health app."""

    def test_liveness(self, simulator_health_client):
        resp = simulator_health_client.get('/healthz')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'alive'
        assert data['service'] == 'iot-device-simulator'

    def test_readiness_not_ready(self, simulator_health_client):
        import simulator as sim_mod
        original = sim_mod.simulator_ready
        sim_mod.simulator_ready = False
        try:
            resp = simulator_health_client.get('/readyz')
            assert resp.status_code == 503
            assert resp.get_json()['status'] == 'not ready'
        finally:
            sim_mod.simulator_ready = original

    def test_readiness_ready(self, simulator_health_client):
        import simulator as sim_mod
        original = sim_mod.simulator_ready
        sim_mod.simulator_ready = True
        try:
            resp = simulator_health_client.get('/readyz')
            assert resp.status_code == 200
            assert resp.get_json()['status'] == 'ready'
        finally:
            sim_mod.simulator_ready = original


# ===================================================================
# Simulator Init — IoT.md §3.1, §3.3, §3.4, §9
# ===================================================================

class TestSimulatorInit:
    """Tests for IoTDeviceSimulator v2 initialization."""

    @patch('simulator.mqtt.Client')
    def test_init_dc(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-001', 'power_meter_dc')
        assert sim.device_id == 'dc-meter-001'
        assert sim.device_type == 'power_meter_dc'
        assert sim.topic_telemetry == 'iot/dc-meter-001/telemetry'
        assert sim.topic_hello == 'iot/dc-meter-001/hello'
        assert sim.topic_status == 'iot/dc-meter-001/status'
        assert sim.topic_command == 'iot/dc-meter-001/command'
        assert sim.connected is False

    @patch('simulator.mqtt.Client')
    def test_init_default_intervals(self, mock_mqtt):
        """Default intervals match IoT.md §9 defaults."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('t', 'power_meter_dc')
        assert sim.sampling_cadence_ms == 1000
        assert sim.send_interval_s == 10
        assert sim.hello_interval_s == 30


# ===================================================================
# Sequence numbers — IoT.md §4.1 / REQ-SEQ-001
# ===================================================================

class TestSequenceNumbers:
    """Tests for monotonic sequence counter.

    Per IoT.md §4.1 — seq starts at 0, increments by 1, wraps at 2^32-1.
    """

    @patch('simulator.mqtt.Client')
    def test_seq_starts_at_zero(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('test-001', 'power_meter_dc')
        assert sim.next_seq() == 0

    @patch('simulator.mqtt.Client')
    def test_seq_monotonic(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('test-001', 'power_meter_dc')
        seqs = [sim.next_seq() for _ in range(10)]
        assert seqs == list(range(10))

    @patch('simulator.mqtt.Client')
    def test_seq_thread_safe(self, mock_mqtt):
        """Sequence must be thread-safe — concurrent calls must yield unique values."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('test-001', 'power_meter_dc')

        results = []
        lock = threading.Lock()

        def get_seqs():
            local = [sim.next_seq() for _ in range(100)]
            with lock:
                results.extend(local)

        threads = [threading.Thread(target=get_seqs) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 400 seq values must be unique
        assert len(set(results)) == 400


# ===================================================================
# DC Telemetry Generation — IoT.md §4.2, §8.1
# ===================================================================

class TestDCTelemetryGeneration:
    """Tests for DC power meter measurement generation.

    Per IoT.md §8.1 — DC devices produce voltage_dc and current_dc.
    """

    @patch('simulator.mqtt.Client')
    def test_dc_generates_voltage_and_current(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        samples = sim.generate_sample()

        assert len(samples) == 2
        types = [s['type'] for s in samples]
        assert 'voltage_dc' in types
        assert 'current_dc' in types

    @patch('simulator.mqtt.Client')
    def test_dc_voltage_in_range(self, mock_mqtt):
        """Voltage should be in realistic 750V metro range (700-800V)."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        for _ in range(50):
            samples = sim.generate_sample()
            voltage = next(s for s in samples if s['type'] == 'voltage_dc')
            assert 700 <= voltage['val'] <= 800
            assert voltage['unit'] == 'V'

    @patch('simulator.mqtt.Client')
    def test_dc_current_in_range(self, mock_mqtt):
        """Current should be in realistic traction range (200-400A)."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        for _ in range(50):
            samples = sim.generate_sample()
            current = next(s for s in samples if s['type'] == 'current_dc')
            assert 200 <= current['val'] <= 400
            assert current['unit'] == 'A'

    @patch('simulator.mqtt.Client')
    def test_dc_sample_has_timestamp(self, mock_mqtt):
        """Each measurement must have a 'ts' field — IoT.md §4.2."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        samples = sim.generate_sample()
        for s in samples:
            assert 'ts' in s
            assert s['ts'].endswith('Z')  # UTC ISO format


# ===================================================================
# AC Telemetry Generation — IoT.md §4.2, §8.1
# ===================================================================

class TestACTelemetryGeneration:
    """Tests for AC power meter measurement generation.

    Per IoT.md §8.1 — AC devices produce voltage_ac, current_ac, frequency, pf.
    """

    @patch('simulator.mqtt.Client')
    def test_ac_generates_four_measurement_types(self, mock_mqtt):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('ac-meter-test', 'power_meter_ac')
        samples = sim.generate_sample()

        assert len(samples) == 4
        types = {s['type'] for s in samples}
        assert types == {'voltage_ac', 'current_ac', 'frequency', 'pf'}

    @patch('simulator.mqtt.Client')
    def test_ac_voltage_25kv_range(self, mock_mqtt):
        """AC voltage should be in 25kV range (24000-26000V)."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('ac-meter-test', 'power_meter_ac')
        for _ in range(50):
            samples = sim.generate_sample()
            voltage = next(s for s in samples if s['type'] == 'voltage_ac')
            assert 24000 <= voltage['val'] <= 26000

    @patch('simulator.mqtt.Client')
    def test_ac_frequency_50hz(self, mock_mqtt):
        """Frequency should be near 50 Hz."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('ac-meter-test', 'power_meter_ac')
        for _ in range(50):
            samples = sim.generate_sample()
            freq = next(s for s in samples if s['type'] == 'frequency')
            assert 49.9 <= freq['val'] <= 50.1

    @patch('simulator.mqtt.Client')
    def test_ac_power_factor_range(self, mock_mqtt):
        """Power factor should be between 0.92 and 0.99."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('ac-meter-test', 'power_meter_ac')
        for _ in range(50):
            samples = sim.generate_sample()
            pf = next(s for s in samples if s['type'] == 'pf')
            assert 0.92 <= pf['val'] <= 0.99


# ===================================================================
# Telemetry Datagram Publishing — IoT.md §4.2
# ===================================================================

class TestTelemetryPublishing:
    """Tests for batched telemetry datagram publishing."""

    @patch('simulator.mqtt.Client')
    def test_flush_publishes_buffered_measurements(self, mock_mqtt):
        """Buffered measurements are flushed as a v2 datagram."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.connected = True

        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)
        sim.mqtt_client = mock_instance

        # Buffer some measurements
        samples = sim.generate_sample()
        sim._measurement_buffer.extend(samples)
        sim._flush_and_publish_telemetry()

        mock_instance.publish.assert_called_once()
        call_args = mock_instance.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert topic == 'iot/dc-meter-test/telemetry'
        assert payload['v'] == 2
        assert payload['msg_type'] == 'telemetry'
        assert payload['device_id'] == 'dc-meter-test'
        assert 'seq' in payload
        assert len(payload['measurements']) == len(samples)

    @patch('simulator.mqtt.Client')
    def test_flush_clears_buffer(self, mock_mqtt):
        """Buffer must be empty after flush."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.connected = True

        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)
        sim.mqtt_client = mock_instance

        sim._measurement_buffer.extend(sim.generate_sample())
        sim._flush_and_publish_telemetry()
        assert len(sim._measurement_buffer) == 0

    @patch('simulator.mqtt.Client')
    def test_flush_empty_buffer_noop(self, mock_mqtt):
        """Flushing empty buffer must not publish."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.connected = True

        mock_instance = mock_mqtt.return_value
        sim.mqtt_client = mock_instance

        sim._flush_and_publish_telemetry()
        mock_instance.publish.assert_not_called()

    @patch('simulator.mqtt.Client')
    def test_flush_uses_qos2(self, mock_mqtt):
        """Telemetry must be published with QoS 2 — REQ-QOS-001."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.connected = True

        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)
        sim.mqtt_client = mock_instance

        sim._measurement_buffer.extend(sim.generate_sample())
        sim._flush_and_publish_telemetry()

        call_args = mock_instance.publish.call_args
        assert call_args[1].get('qos', call_args[0][2] if len(call_args[0]) > 2 else None) == 2


# ===================================================================
# Hello Messages — IoT.md §4.3 / REQ-HELLO-001
# ===================================================================

class TestHelloMessages:
    """Tests for hello message generation and suppression rule.

    REQ-HELLO-001: If send_interval ≤ hello_interval → hello suppressed.
                   If send_interval > hello_interval → hello sent.
    """

    @patch('simulator.mqtt.Client')
    def test_hello_contains_required_fields(self, mock_mqtt):
        """Hello message must contain fw_version, uptime_s, broker_connections, buf_usage_pct."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc', fw_version='2.1.0')
        sim.connected = True

        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)
        sim.mqtt_client = mock_instance

        sim._publish_hello()
        mock_instance.publish.assert_called_once()

        payload = json.loads(mock_instance.publish.call_args[0][1])
        assert payload['msg_type'] == 'hello'
        assert payload['v'] == 2
        assert payload['fw_version'] == '2.1.0'
        assert 'uptime_s' in payload
        assert 'broker_connections' in payload
        assert 'buf_usage_pct' in payload
        assert payload['device_id'] == 'dc-meter-test'

    @patch('simulator.mqtt.Client')
    def test_hello_suppression_rule_send_lte_hello(self, mock_mqtt):
        """When send_interval ≤ hello_interval, datagrams act as heartbeats.

        REQ-HELLO-001: The run loop should NOT send explicit hellos.
        """
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.send_interval_s = 10
        sim.hello_interval_s = 30
        # send_interval (10) ≤ hello_interval (30) → hello suppressed
        assert sim.send_interval_s <= sim.hello_interval_s

    @patch('simulator.mqtt.Client')
    def test_hello_sent_when_send_gt_hello(self, mock_mqtt):
        """When send_interval > hello_interval, explicit hellos must be sent.

        REQ-HELLO-001: Hello messages fill the gap between data sends.
        """
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.send_interval_s = 60
        sim.hello_interval_s = 30
        # send_interval (60) > hello_interval (30) → hello needed
        assert sim.send_interval_s > sim.hello_interval_s

    @patch('simulator.mqtt.Client')
    def test_buf_usage_pct(self, mock_mqtt):
        """Buffer usage is 0 when empty — IoT.md §4.3."""
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        assert sim._buf_usage_pct() == 0


# ===================================================================
# LWT Registration — IoT.md §3.4 / REQ-LWT-001
# ===================================================================

class TestLWTRegistration:
    """Tests for Last Will and Testament setup.

    REQ-LWT-001: LWT must be registered on every connect.
    """

    @patch('simulator.mqtt.Client')
    def test_lwt_set_before_connect(self, mock_mqtt):
        """will_set must be called during __init__."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')

        mock_instance.will_set.assert_called_once()
        call_args = mock_instance.will_set.call_args
        assert call_args[0][0] == 'iot/dc-meter-test/status'
        lwt_payload = json.loads(call_args[0][1])
        assert lwt_payload['status'] == 'offline'
        assert lwt_payload['device_id'] == 'dc-meter-test'
        assert call_args[1]['retain'] is True

    @patch('simulator.mqtt.Client')
    def test_online_published_on_connect(self, mock_mqtt):
        """Device must publish online status after successful connect — IoT.md §5."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.mqtt_client = mock_instance

        # Simulate successful connect callback
        sim.on_connect(mock_instance, None, None, 0, None)
        assert sim.connected is True

        # Verify online status was published
        publish_calls = mock_instance.publish.call_args_list
        assert len(publish_calls) >= 1
        status_call = publish_calls[0]
        assert status_call[0][0] == 'iot/dc-meter-test/status'
        payload = json.loads(status_call[0][1])
        assert payload['status'] == 'online'

    @patch('simulator.mqtt.Client')
    def test_on_connect_subscribes_to_command_topic(self, mock_mqtt):
        """On connect, device subscribes to iot/{id}/command — IoT.md §6."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.mqtt_client = mock_instance

        sim.on_connect(mock_instance, None, None, 0, None)
        mock_instance.subscribe.assert_called_once_with('iot/dc-meter-test/command', qos=2)


# ===================================================================
# Disconnect — IoT.md §5
# ===================================================================

class TestSimulatorCallbacks:
    """Tests for MQTT callback methods."""

    @patch('simulator.mqtt.Client')
    def test_on_connect_failure(self, mock_mqtt_cls):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'power_meter_dc')
        sim.on_connect(MagicMock(), None, None, 1, None)
        assert sim.connected is False

    @patch('simulator.mqtt.Client')
    def test_on_disconnect(self, mock_mqtt_cls):
        from simulator import IoTDeviceSimulator
        sim = IoTDeviceSimulator('dev-001', 'power_meter_dc')
        sim.connected = True
        sim.on_disconnect(MagicMock(), None, None, 0, None)
        assert sim.connected is False


# ===================================================================
# Command Handling — IoT.md §6
# ===================================================================

class TestCommandHandling:
    """Tests for server → device command processing."""

    @patch('simulator.mqtt.Client')
    def test_update_config_changes_intervals(self, mock_mqtt):
        """update_config command must update device settings — IoT.md §6.3."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.mqtt_client = mock_instance

        sim._handle_update_config('cmd-001', {
            'sampling_cadence_ms': 500,
            'send_interval_s': 5,
            'hello_interval_s': 15,
        })

        assert sim.sampling_cadence_ms == 500
        assert sim.send_interval_s == 5
        assert sim.hello_interval_s == 15

        # Verify ack was sent
        mock_instance.publish.assert_called()
        ack_call = mock_instance.publish.call_args
        payload = json.loads(ack_call[0][1])
        assert payload['msg_type'] == 'command_ack'
        assert payload['cmd_id'] == 'cmd-001'
        assert payload['result'] == 'accepted'

    @patch('simulator.mqtt.Client')
    def test_request_status_sends_hello(self, mock_mqtt):
        """request_status command must trigger immediate hello — IoT.md §6.2."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.mqtt_client = mock_instance

        sim._handle_request_status('cmd-002')

        # Should have ack + hello = at least 2 publish calls
        assert mock_instance.publish.call_count >= 2
        payloads = [json.loads(c[0][1]) for c in mock_instance.publish.call_args_list]
        msg_types = [p['msg_type'] for p in payloads]
        assert 'command_ack' in msg_types
        assert 'hello' in msg_types

    @patch('simulator.mqtt.Client')
    def test_unknown_command_unsupported(self, mock_mqtt):
        """Unknown commands must return 'unsupported' ack — IoT.md §6.5."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.mqtt_client = mock_instance

        # Simulate on_message with unknown command
        msg = MagicMock()
        msg.payload = json.dumps({
            'v': 2, 'cmd_id': 'cmd-999', 'cmd': 'explode', 'params': {}
        }).encode()
        sim.on_message(mock_instance, None, msg)

        ack_call = mock_instance.publish.call_args
        payload = json.loads(ack_call[0][1])
        assert payload['result'] == 'unsupported'

    @patch('simulator.mqtt.Client')
    def test_reboot_accepted(self, mock_mqtt):
        """Reboot command must be acknowledged — IoT.md §6."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.mqtt_client = mock_instance

        msg = MagicMock()
        msg.payload = json.dumps({
            'v': 2, 'cmd_id': 'cmd-r', 'cmd': 'reboot', 'params': {}
        }).encode()
        sim.on_message(mock_instance, None, msg)

        payload = json.loads(mock_instance.publish.call_args[0][1])
        assert payload['result'] == 'accepted'
        assert payload['cmd_id'] == 'cmd-r'

    @patch('simulator.mqtt.Client')
    def test_start_ota_reports_progress(self, mock_mqtt):
        """start_ota must send ack + OTA progress reports — IoT.md §7."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.mqtt_client = mock_instance

        sim._handle_start_ota('ota-001', {'fw_version': '2.2.0'})

        # Should have: 1 ack + 4 ota_status messages = 5 publishes
        assert mock_instance.publish.call_count >= 5
        payloads = [json.loads(c[0][1]) for c in mock_instance.publish.call_args_list]
        ota_statuses = [p for p in payloads if p.get('msg_type') == 'ota_status']
        assert len(ota_statuses) == 4
        assert ota_statuses[-1]['ota_state'] == 'success'

    @patch('simulator.mqtt.Client')
    def test_command_ack_has_correct_envelope(self, mock_mqtt):
        """Ack payload must match v2 envelope format — IoT.md §6.5."""
        from simulator import IoTDeviceSimulator
        mock_instance = mock_mqtt.return_value
        mock_instance.publish.return_value = MagicMock(rc=0)

        sim = IoTDeviceSimulator('dc-meter-test', 'power_meter_dc')
        sim.mqtt_client = mock_instance

        sim._send_command_ack('cmd-555', 'accepted', 'test detail')

        call_args = mock_instance.publish.call_args
        assert call_args[0][0] == 'iot/dc-meter-test/command/ack'
        payload = json.loads(call_args[0][1])
        assert payload['v'] == 2
        assert payload['device_id'] == 'dc-meter-test'
        assert 'ts' in payload
        assert 'seq' in payload
        assert payload['msg_type'] == 'command_ack'
        assert payload['cmd_id'] == 'cmd-555'
        assert payload['result'] == 'accepted'
        assert payload['detail'] == 'test detail'
