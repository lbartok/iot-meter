# IoT Meter — TODO / Improvement Backlog

> **Last Updated:** 2025-07

---

## Legend

| Status | Meaning |
|--------|---------|
| ⬜ | Not started |
| 🔄 | In progress |
| ✅ | Done |

---

## 🔴 Critical — Security & Data Integrity

### 1. ⬜ Fix Flux query injection in `app.py`

**File:** `services/device-manager/app.py` — `get_device_metrics()` (line ~305)

The `device_id`, `start`, `stop`, and `metric` parameters are interpolated directly
into a Flux query string via f-string. A crafted `device_id` or query parameter can
inject arbitrary Flux code.

**Fix:** Use InfluxDB client parameterised queries or sanitise/validate all inputs
before interpolation.

### 2. ⬜ Add PostgreSQL connection pooling

**File:** `services/device-manager/app.py` — `get_db_connection()` (line ~52)

Every request opens a new `psycopg2.connect()` call and manually closes it. Under
load this exhausts PostgreSQL connection limits and causes latency spikes.

**Fix:** Replace with `psycopg2.pool.ThreadedConnectionPool` (or `psycopg_pool` for
psycopg 3). Initialise the pool once at app startup.

### 3. ⬜ Add `datetime.timezone.utc` — deprecation fix

**Files:**
- `services/device-manager/app.py` (line 593) — `datetime.utcnow()`
- `services/mqtt-collector/collector.py` (line 222) — `datetime.utcnow()`

`datetime.utcnow()` is deprecated in Python 3.12+.

**Fix:** Replace with `datetime.now(datetime.timezone.utc)` everywhere.

---

## 🟠 High — Reliability & Performance

### 4. ⬜ Bound in-memory dicts in collector

**File:** `services/mqtt-collector/collector.py` — `_seq_tracker` (line 81),
`_device_last_seen` (line 85)

These dicts grow unbounded as new device IDs arrive. A malicious or misconfigured
device fleet can cause OOM.

**Fix:** Use an LRU cache (`functools.lru_cache` or `cachetools.TTLCache`) with a
configurable max size.

### 5. ⬜ Deduplicate DB boilerplate in `app.py`

**File:** `services/device-manager/app.py`

15+ endpoints repeat the same `conn = get_db_connection(); try/except/finally
conn.close()` pattern (~100 duplicate lines).

**Fix:** Extract a `with_db()` context manager or decorator. Combine with item #2.

### 6. ⬜ Add request/response validation

**File:** `services/device-manager/app.py`

POST/PUT endpoints don't validate field types or lengths. Invalid data silently
passes to PostgreSQL.

**Fix:** Add `marshmallow` or `pydantic` schemas for request validation.

### 7. ⬜ Create MQTT client once for command publishing

**File:** `services/device-manager/app.py` — `send_command()` (line ~572)

A new MQTT client is created per command request. Under load this exhausts broker
connections.

**Fix:** Create a module-level MQTT client at startup, reuse it for all command
publishes.

---

## 🟡 Medium — Code Quality & Maintainability

### 8. ⬜ Add type hints to all service files

**Files:**
- `services/device-manager/app.py` (724 lines — 0 type hints)
- `services/mqtt-collector/collector.py` (407 lines — 0 type hints)
- `services/iot-device-simulator/simulator.py` (486 lines — partial)

**Fix:** Add `-> None`, `-> dict`, `-> tuple[Response, int]`, etc. Run `mypy` in CI.

### 9. ⬜ Add structured JSON logging

**Files:** All 3 services use `logging.basicConfig()` with plain text format.

**Fix:** Switch to `structlog` or `python-json-logger`. Add `request_id`, `device_id`
as structured fields. Makes log aggregation (ELK, Loki) much easier.

### 10. ⬜ Add `__all__` exports and module docstrings

**Files:** All 3 service entry-point files.

**Fix:** Add module-level docstrings and `__all__` lists.

### 11. ⬜ Add DB migration framework

**File:** `config/init-db.sql`

Schema changes require manual SQL editing and full re-deploy. No version tracking.

**Fix:** Add Alembic (or simple numbered migration files) for versioned schema
migrations.

### 12. ⬜ Add linting to CI pipeline

**File:** `.github/workflows/deploy.yml`

CI runs tests but not linters. Code style inconsistencies creep in.

**Fix:** Add `ruff` (or `flake8` + `black`) as a CI step before tests.

---

## 🟢 Low — Nice-to-Have

### 13. ⬜ Add `LICENSE` file

The README says "MIT License — See LICENSE file" but no LICENSE file exists.

**Fix:** Create `LICENSE` with MIT text.

### 14. ⬜ Create `CHANGELOG.md`

No changelog exists. Hard to track what changed between deployments.

**Fix:** Create `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/).

### 15. ⬜ Add Prometheus metrics endpoint

**Files:** `services/device-manager/app.py`, `services/mqtt-collector/collector.py`

No `/metrics` endpoint for monitoring. Can't track request rates, latencies, error
rates, or collector throughput.

**Fix:** Add `prometheus_flask_exporter` to device-manager, custom Prometheus counters
to collector.

### 16. ⬜ Add Grafana dashboard template

No dashboard template exists for visualising InfluxDB metrics.

**Fix:** Create `config/grafana/` with a JSON dashboard template.

### 17. ⬜ Add health check dependencies to Docker Compose

**File:** `docker-compose.yml`

Services don't wait for their dependencies (PostgreSQL, InfluxDB) to be healthy
before starting.

**Fix:** Add `healthcheck` + `depends_on.condition: service_healthy` for all services.

### 18. ⬜ Add k6 performance test suite

**Directory:** `tests/performance/` (new)

No performance/load tests exist. Can't measure API throughput or regression.

**Fix:** Create k6 scripts for device-manager API endpoints + MQTT publish load.

---

## ✅ Recently Completed

### ✅ Update .md files to match v2 reality
- README.md: Fixed v1→v2 payload, 5 MQTT topics, 5 DB tables, `generate_sample()`,
  `power_meter_dc`/`power_meter_ac`, MinIO category paths, added missing API endpoints,
  fixed test counts (126)
- ARCHITECTURE.md: Fixed Python 3.11→3.13, removed "async" claims, added K8s/CI
- IMPLEMENTATION_SUMMARY.md: Fixed "Next Steps" (K8s/CI marked done), updated line
  counts, 5 topics/tables
- assessment.md: Marked CI pipeline as implemented
- QUICKSTART.md: Fixed v1→v2 examples and device types
- examples/README.md: Fixed v1→v2 payload format and device types

### ✅ Set up CI/CD pipeline
- GitHub Actions 3-stage pipeline (build → test → deploy)
- Self-hosted runner on k3s

### ✅ Kubernetes production deployment
- Kustomize base + production overlay
- k3s single-node with hostPath PVs
- PRODUCTION.md runbook

### ✅ GitHub Secrets management
- 8 secrets + 1 variable configured via `gh` CLI
