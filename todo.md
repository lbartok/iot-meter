# IoT Meter — TODO / Improvement Backlog

> **Last Updated:** 2026-02-12

---

## Legend

| Status | Meaning |
|--------|---------|
| ✅ | Done |
| ⬜ | Not started |

---

## ✅ Resolved

### ✅ R1. Fix Flux query injection in `app.py`
Added `_sanitise_flux_id()` and `_sanitise_flux_time()` validators with regex
allowlists. All Flux query inputs are validated before interpolation.

### ✅ R2. Add PostgreSQL connection pooling
`psycopg2.pool.ThreadedConnectionPool` with lazy init via `_get_pool()`.
Pool size: 2–10 connections (configurable via env vars).

### ✅ R3. Fix `datetime.utcnow()` deprecation
Replaced all `datetime.utcnow()` with `datetime.now(timezone.utc)` in
`services/device-manager/app.py` and `services/mqtt-collector/collector.py`.

### ✅ R4. Deduplicate DB boilerplate in `app.py`
Added `get_db()` context manager yielding `(conn, cur)`. All 15+ endpoints
refactored to use `with get_db() as (conn, cur):`.

### ✅ R5. Create MQTT client once for command publishing
Module-level `get_mqtt_client()` with `loop_start()` background thread.
Reused for all command publishes.

### ✅ R6. Add Prometheus metrics endpoints
Both services expose `/metrics` via `prometheus_client`. 40+ custom metrics
covering HTTP traffic, MQTT pipeline, storage backends, and business metrics.

### ✅ R7. Add Grafana dashboard
Auto-provisioned "IoT Meter — Overview" dashboard with 21 panels across 5
sections (Service Health, HTTP Traffic, MQTT Pipeline, Business Metrics,
Kubernetes Cluster).

### ✅ R8. Add Docker health check dependencies
`depends_on` with `condition: service_healthy` for all infrastructure services.
Health checks defined for PostgreSQL, InfluxDB, MinIO, Mosquitto, Prometheus,
Grafana, Alertmanager.

### ✅ R9. Add Alertmanager & incident routing
12 alerting rules across 5 groups. Alertmanager with GitHub Issues integration
via custom webhook receiver. DRY_RUN mode for safe testing.

### ✅ R10. Add k6 performance test suite
`tests/performance/api_load_test.js` + `mqtt_publish_test.js`. Makefile
targets: `perf-test`, `perf-test-api`, `perf-test-mqtt`.

### ✅ R11. Set up CI/CD pipeline
GitHub Actions 3-stage: Build → Test → Deploy. Self-hosted runner on k3s.

### ✅ R12. Kubernetes deployment
Kustomize base + production overlay. k3s single-node with hostPath PVs.

### ✅ R13. Update .md files to match v2 reality
All documentation updated for v2 payload, device types, API endpoints.

### ✅ R14. Clean up stale code & configs (2026-02-12)
- Deleted `test-results.txt` (stale CI artifact, now in `.gitignore`)
- Removed dead `PUBLISH_INTERVAL` from docker-compose, configmap, .env.example
- Fixed `start.sh` broken path (`k8s/` → `k8s/base/`), added 4th image build
- Fixed `deploy.yml` CI — added alertmanager-github-receiver build + import
- Updated `Makefile` — `docker-compose` → `docker compose` (v2 plugin syntax)
- ~~Eliminated duplicate Grafana dashboard JSON (symlink)~~ reverted — kustomize
  rejects symlinks escaping the base directory. Dashboard JSON remains duplicated
  in `config/grafana/dashboards/` and `k8s/base/`
- Fixed stale comments referencing `prometheus_flask_instrumentator`
- Updated `ARCHITECTURE.md` — removed implemented items from "Future Enhancements,"
  updated Monitoring section with Prometheus/Grafana/Alertmanager details
- Updated `IMPLEMENTATION_SUMMARY.md` — marked Grafana + Prometheus as ✅ Done
- Updated `assessment.md` — marked §3.3 Prometheus as ✅ Implemented, roadmap updated
- Rewrote `examples/iot_device_client.py` — v1→v2 payload, paho-mqtt v1→v2 API
- Rewrote `examples/test-api.sh` — updated device types/IDs to v2
- Added `.gitignore` entries for test artifacts, backup files, `.pytest_cache`

---

## 🔴 Critical — Security

### ⬜ S1. Add API authentication & authorization

**Files:** `services/device-manager/app.py`

Zero authentication on the REST API. Anyone with network access can
create/delete devices, send commands, and read all data.

**Fix:** Add JWT or API key authentication middleware. Implement RBAC.

### ⬜ S2. Add MQTT TLS + client authentication

**Files:** `config/mosquitto.conf`

`allow_anonymous true` on plain port 1883. IoT.md §10 requires TLS 1.3
and X.509 client certificates. No topic ACLs implemented.

**Fix:** Configure TLS listener, generate CA + client certs, add ACL file.

### ⬜ S3. Remove plaintext secrets from version control

**Files:** `k8s/base/secrets.yaml`, `docker-compose.yml`, `.env.example`

Dev passwords (`iot_password`, `minioadmin123`, `iot-admin-token-secret-12345`)
committed in cleartext across multiple files.

**Fix:** Use SealedSecrets or SOPS for K8s. For docker-compose, use `.env`
(already gitignored) and remove all hardcoded values from `docker-compose.yml`.

### ⬜ S4. Add non-root USER to Dockerfiles

**Files:** All 4 `services/*/Dockerfile`

Containers run as root by default. K8s manifests set `runAsNonRoot` for infra
services but not for custom services.

**Fix:** Add `RUN adduser --disabled-password --no-create-home appuser` and
`USER appuser` to each Dockerfile. Add `securityContext` to K8s deployments.

### ⬜ S5. Sanitize error responses — don't leak internals

**File:** `services/device-manager/app.py`

Every `except Exception as e: return jsonify({'error': str(e)})` exposes
stack traces, DB errors, and internal paths to API consumers.

**Fix:** Return generic error messages. Log details server-side only.

---

## 🟠 High — Reliability & Performance

### ⬜ H1. Bound in-memory dicts in collector

**File:** `services/mqtt-collector/collector.py` — `_seq_tracker`, `_device_last_seen`

These dicts grow unbounded as new device IDs arrive. A malicious or
misconfigured device fleet can cause OOM.

**Fix:** Use `cachetools.TTLCache` with configurable max size.

### ⬜ H2. Add request/response validation

**File:** `services/device-manager/app.py`

POST/PUT endpoints accept arbitrary JSON without type/length/schema checks.
Invalid data passes silently to PostgreSQL.

**Fix:** Add `pydantic` or `marshmallow` schemas for all request bodies.

### ⬜ H3. Add API rate limiting

**File:** `services/device-manager/app.py`

No rate limiting on any endpoint, including device creation and command
publishing.

**Fix:** Add `flask-limiter` with configurable per-endpoint limits.

### ⬜ H4. Add pagination to list endpoints

**File:** `services/device-manager/app.py`

`GET /api/devices` and `GET /api/devices/{id}/alerts` return all records.
With thousands of entries this is slow and memory-intensive.

**Fix:** Add `?page=1&per_page=50` query parameters with cursor-based or
offset pagination.

### ⬜ H5. Use production WSGI server for collector & simulator

**Files:** `services/mqtt-collector/collector.py`, `services/iot-device-simulator/simulator.py`

Both run Flask's development server (`app.run()`) for health endpoints in
production. Only device-manager uses gunicorn.

**Fix:** Use `waitress` or `gunicorn` for the health server in collector and
simulator.

### ⬜ H6. Add health checks for custom services in docker-compose

**File:** `docker-compose.yml`

Infrastructure services have `healthcheck` definitions. Custom services
(device-manager, mqtt-collector, iot-simulator, alertmanager-github-receiver) don't.

**Fix:** Add `healthcheck` blocks using each service's `/health` endpoint.

### ⬜ H7. Fix remaining `datetime.now()` without timezone

**File:** `services/mqtt-collector/collector.py` — `store_to_minio`

Uses `datetime.now().isoformat()` (no timezone) while the rest of the codebase
uses `datetime.now(timezone.utc)`. Inconsistent timestamp format in MinIO.

**Fix:** Change to `datetime.now(timezone.utc).isoformat()`.

---

## 🟡 Medium — Code Quality & Maintainability

### ⬜ M1. Add type hints to all service files

**Files:**
- `services/device-manager/app.py`
- `services/mqtt-collector/collector.py`
- `services/iot-device-simulator/simulator.py`

**Fix:** Add return types, parameter types. Run `mypy` in CI.

### ⬜ M2. Add structured JSON logging

**Files:** All services using `logging.basicConfig()` with plain text.

**Fix:** Switch to `structlog` or `python-json-logger`. Add `request_id`,
`device_id` as structured fields for log aggregation.

### ⬜ M3. Add linting/formatting to CI

**File:** `.github/workflows/deploy.yml`

CI runs tests but not linters. Code style inconsistencies creep in.

**Fix:** Add `ruff` (lint + format) as a CI step before tests.

### ⬜ M4. Add DB migration framework

**File:** `config/init-db.sql`

Schema changes require manual SQL editing and full re-deploy.

**Fix:** Add Alembic for versioned schema migrations.

### ⬜ M5. Add `.dockerignore` files

**Files:** All 4 `services/*/` directories.

Every `docker build` sends `__pycache__/`, `.git`, etc. as build context.

**Fix:** Add `.dockerignore` to each service directory.

### ⬜ M6. Align `requests` package version across files

- `services/alertmanager-github-receiver/requirements.txt` → `2.32.3`
- `examples/requirements.txt` → `2.32.5`
- `requirements-test.txt` → `2.32.5`

**Fix:** Pin all to the same version.

### ⬜ M7. Add module docstrings and `__all__` exports

**Files:** All 3 service entry-point files.

**Fix:** Add module-level docstrings and `__all__` lists.

### ⬜ M8. DRY — single-source Prometheus alert rules

**Files:** `config/alert_rules.yml` vs inline in `k8s/base/prometheus.yaml`

Alert rules are duplicated. Docker Compose reads the file; K8s inlines the
content in the ConfigMap. Changes must be made in both places.

**Fix:** Extract inline rules from `prometheus.yaml`. Use a kustomize
`configMapGenerator` to include `config/alert_rules.yml` as a separate
ConfigMap key (similar to how the Grafana dashboard is handled).

### ⬜ M9. DRY — single-source Alertmanager config

**Files:** `config/alertmanager.yml` vs inline in `k8s/base/alertmanager.yaml`

Same duplication issue as M8.

**Fix:** Use kustomize `configMapGenerator` referencing `config/alertmanager.yml`.

---

## 🟢 Low — Nice-to-Have

### ⬜ L1. Add `LICENSE` file

README says "MIT License — See LICENSE file" but no file exists.

### ⬜ L2. Create `CHANGELOG.md`

No changelog. Hard to track what changed between deployments.

### ⬜ L3. Add `CODEOWNERS` file

Ensures PR reviews are routed to the right people.

### ⬜ L4. Consistent `imagePullPolicy` across K8s manifests

`device-manager` uses `IfNotPresent` while `alertmanager-github-receiver`
uses `Never`. Both are locally-built images. Should be consistent.

### ⬜ L5. Validate e2e tests still work

`tests/e2e/test_e2e.py` exists but hasn't been verified recently.
May be broken against the current v2 API.

### ⬜ L6. Remove hardcoded default credentials from service code

**File:** `services/device-manager/app.py`

`os.getenv('INFLUXDB_TOKEN', 'iot-admin-token-secret-12345')` silently
falls back to an insecure default if the env var is missing.

**Fix:** Make required env vars fail fast with a clear error on startup.
