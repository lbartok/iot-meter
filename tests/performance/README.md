# Performance Tests (k6)

End-to-end performance tests for the IoT Meter platform using [k6](https://k6.io/).

## Prerequisites

```bash
# macOS
brew install k6

# Linux (Debian/Ubuntu)
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install k6
```

## Running

```bash
# From project root:
make perf-test

# Or directly:
k6 run tests/performance/api_load_test.js

# With custom base URL (production):
k6 run -e BASE_URL=https://iot.bartok.sk tests/performance/api_load_test.js

# MQTT publish load test:
k6 run tests/performance/mqtt_publish_test.js
```

## Test Scenarios

### `api_load_test.js` — Device Manager API

| Stage | Duration | VUs | Purpose |
|-------|----------|-----|---------|
| Ramp-up | 30s | 1→10 | Warm-up |
| Sustained | 1m | 10 | Steady-state |
| Spike | 30s | 10→30 | Burst traffic |
| Cool-down | 30s | 30→0 | Graceful drain |

**Endpoints tested:**
- `GET /healthz` — liveness probe
- `GET /readyz` — readiness probe
- `GET /api/devices` — list devices
- `GET /api/devices/{id}` — get single device
- `POST /api/devices` — create device
- `DELETE /api/devices/{id}` — cleanup
- `POST /api/devices/{id}/heartbeat` — heartbeat
- `GET /api/devices/{id}/metrics` — InfluxDB query
- `GET /api/stats` — system statistics

### `mqtt_publish_test.js` — MQTT Ingestion Pipeline

Tests MQTT → Collector → MinIO + InfluxDB end-to-end by publishing
v2 telemetry datagrams via the k6 WebSocket extension and verifying
they appear in the API.

## Thresholds

| Metric | Threshold | Description |
|--------|-----------|-------------|
| `http_req_duration` (p95) | < 500ms | 95th percentile response time |
| `http_req_duration` (p99) | < 1000ms | 99th percentile response time |
| `http_req_failed` | < 1% | Error rate |
| `healthz_duration` (p95) | < 100ms | Health check latency |
| `list_devices_duration` (p95) | < 300ms | List devices latency |

## Output

k6 prints a summary with all metrics. For JSON output:

```bash
k6 run --out json=results.json tests/performance/api_load_test.js
```
