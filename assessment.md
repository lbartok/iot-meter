# Assessment — Improvement Options

> **Version:** 2.0  
> **Scope:** IoT Meter platform (v2 — rail mobility DC/AC power metering)  
> **Last Updated:** 2025-07

---

## 1. Current State Summary

The v2 platform delivers the core requirements with rail mobility focus:

| # | Requirement | Current Implementation |
|---|------------|------------------------|
| 1 | Secure channel | MQTT plaintext (port 1883). TLS config documented but not enforced. |
| 2 | Device identification | `device_id` in payload + topic. No authentication on the broker. |
| 3 | Data ingestion | MQTT → Collector → MinIO (raw) + InfluxDB (time-series). REST API for device management. |

The sections below assess concrete improvements, each with **pros, cons, effort estimate, and priority**.

---

## 2. Security Improvements

### 2.1 Enable MQTT over TLS (mTLS)

| Aspect | Detail |
|--------|--------|
| **What** | Configure Mosquitto with server + client certificates. Devices authenticate via X.509. |
| **Pros** | Encrypted channel. Strong device identity. Industry standard. No password management. |
| **Cons** | Certificate lifecycle management (rotation, revocation). Slightly higher CPU on broker. Firmware must bundle certs. |
| **Effort** | Medium — Mosquitto config + cert generation scripts + K8s Secret for CA. |
| **Priority** | 🔴 **High** — required before any production deployment. |

### 2.2 API Authentication & Authorization

| Aspect | Detail |
|--------|--------|
| **What** | Add JWT or API-key authentication to the Device Manager REST API. Role-based access (admin, read-only). |
| **Pros** | Prevents unauthorized device registration/deletion. Audit trail. |
| **Cons** | Adds auth middleware complexity. Token refresh management. |
| **Effort** | Medium — Flask middleware + user/role table in PostgreSQL. |
| **Priority** | 🔴 **High** |

### 2.3 MQTT Topic ACLs

| Aspect | Detail |
|--------|--------|
| **What** | Restrict each device to publishing only on `iot/{its-own-id}/telemetry`. |
| **Pros** | Prevents spoofing. Defence in depth. |
| **Cons** | ACL file or plugin management. |
| **Effort** | Low — Mosquitto `acl_file` with pattern `iot/%u/telemetry`. |
| **Priority** | 🟡 **Medium** |

---

## 3. Reliability & Observability

### 3.1 Message Queue Between Collector and Storage

| Aspect | Detail |
|--------|--------|
| **What** | Place a durable queue (e.g. Redis Streams, Apache Kafka, NATS JetStream) between the MQTT Collector and the storage backends. |
| **Pros** | Decouples ingestion from storage. Handles InfluxDB/MinIO downtime without data loss. Enables replay. |
| **Cons** | Additional infrastructure. Increased latency (milliseconds). Operational complexity. |
| **Effort** | High — new service, schema design, consumer groups. |
| **Priority** | 🟡 **Medium** — important for production scale. |

### 3.2 Structured Logging & Distributed Tracing

| Aspect | Detail |
|--------|--------|
| **What** | Switch to JSON-structured logs. Add OpenTelemetry traces across Collector → Storage. |
| **Pros** | Searchable logs (ELK / Loki). End-to-end latency visibility. Easier root-cause analysis. |
| **Cons** | Log volume increases slightly. OTel SDK dependency. |
| **Effort** | Medium — Python `structlog` + OTel SDK + collector sidecar. |
| **Priority** | 🟡 **Medium** |

### 3.3 Prometheus Metrics & Alerting — ✅ Implemented

| Aspect | Detail |
|--------|--------|
| **What** | `/metrics` endpoints on both services (40+ custom metrics). Prometheus + Grafana + Alertmanager deployed. |
| **Status** | ✅ **Done** — `prometheus_client`, 12 alerting rules, Grafana dashboard (21 panels), GitHub Issues integration. |
| **Priority** | ✅ **Complete** |

---

## 4. Scalability

### 4.1 Horizontal Auto-scaling

| Aspect | Detail |
|--------|--------|
| **What** | Add Kubernetes HPA for Device Manager and Collector based on CPU/memory or custom metrics (messages/sec). |
| **Pros** | Handles traffic spikes. Cost-efficient (scale down during quiet periods). |
| **Cons** | Collector scaling requires MQTT shared subscriptions (MQTT v5 `$share/`). Stateful considerations for InfluxDB write batching. |
| **Effort** | Low (HPA) to Medium (shared subs + batching). |
| **Priority** | 🟢 **Low** for current scale, **High** for production. |

### 4.2 MQTT Broker Clustering

| Aspect | Detail |
|--------|--------|
| **What** | Replace single Mosquitto with a clustered broker (EMQX, HiveMQ, or VerneMQ). |
| **Pros** | High availability. Horizontal scaling. Built-in dashboards. |
| **Cons** | More complex deployment. Licensing costs (some brokers). |
| **Effort** | High — migration, testing, new Helm chart. |
| **Priority** | 🟢 **Low** until device count exceeds ~10 K. |

### 4.3 Database Partitioning / Retention Policies

| Aspect | Detail |
|--------|--------|
| **What** | Add InfluxDB retention policies (e.g. 90 days hot, 1 year downsampled). MinIO lifecycle rules for raw data. |
| **Pros** | Controls storage growth. Faster queries on recent data. |
| **Cons** | Downsampled data loses granularity. Lifecycle rules need monitoring. |
| **Effort** | Low — InfluxDB task + MinIO ILM policy. |
| **Priority** | 🟡 **Medium** |

---

## 5. Data Quality & Payload Validation

### 5.1 JSON Schema Validation at Ingestion

| Aspect | Detail |
|--------|--------|
| **What** | Validate incoming MQTT payloads against a JSON Schema before storage. Reject or quarantine invalid messages. |
| **Pros** | Prevents bad data from reaching storage. Clear error feedback (via MQTT v5 reason codes). |
| **Cons** | Added latency per message (~µs). Schema must be maintained alongside IoT.md. |
| **Effort** | Low — `jsonschema` library in the Collector. |
| **Priority** | 🟡 **Medium** |

### 5.2 CBOR Binary Encoding (v2 payload)

| Aspect | Detail |
|--------|--------|
| **What** | Support CBOR-encoded payloads alongside JSON. Devices indicate encoding via MQTT v5 content-type property or a topic suffix. |
| **Pros** | 30–50% smaller payloads. Faster parsing. Better for constrained devices. |
| **Cons** | Dual-format support in Collector. Debugging is harder (binary). |
| **Effort** | Medium — `cbor2` library + content negotiation. |
| **Priority** | 🟢 **Low** — only needed for very constrained radios (NB-IoT, LoRa). |

---

## 6. DevOps & CI/CD

### 6.1 CI Pipeline (GitHub Actions) — ✅ Implemented

| Aspect | Detail |
|--------|--------|
| **What** | 3-stage pipeline: Build → Test → Deploy on every push to `main`. Self-hosted runner on k3s. |
| **Status** | ✅ **Done** — `.github/workflows/deploy.yml` with unit+integration tests gating deployment. |
| **Priority** | ✅ **Complete** |

### 6.2 Helm Chart

| Aspect | Detail |
|--------|--------|
| **What** | Replace raw Kustomize manifests with a Helm chart for templated, parameterized deployments. |
| **Pros** | Easy per-environment overrides (dev/staging/prod). Rollback via `helm rollback`. Community standard. |
| **Cons** | Learning curve. Template debugging. |
| **Effort** | Medium — convert existing YAML to templates + `values.yaml`. |
| **Priority** | 🟡 **Medium** |

### 6.3 GitOps (ArgoCD / Flux)

| Aspect | Detail |
|--------|--------|
| **What** | Declarative deployment — git repo is the single source of truth. ArgoCD syncs cluster state. |
| **Pros** | Audit trail. Self-healing. Multi-cluster support. |
| **Cons** | Additional operator to run. Steeper learning curve. |
| **Effort** | Medium — install ArgoCD + Application CRD pointing to this repo. |
| **Priority** | 🟢 **Low** for single cluster. |

---

## 7. Recommended Priority Order

| Phase | Items | Estimated Timeline |
|-------|-------|--------------------|
| **Phase 1 — Secure & Ship** | TLS (2.1), API Auth (2.2), ~~CI pipeline (6.1)~~ ✅ | 2–3 weeks |
| **Phase 2 — Observe & Validate** | ~~Prometheus (3.3)~~ ✅, Structured logs (3.2), Schema validation (5.1), Topic ACLs (2.3) | 2–3 weeks |
| **Phase 3 — Scale** | HPA (4.1), DB retention (4.3), Helm chart (6.2), Message queue (3.1) | 3–4 weeks |
| **Phase 4 — Optimize** | CBOR payloads (5.2), Broker clustering (4.2), GitOps (6.3) | As needed |

---

## 8. Keeping Documentation Up to Date

Documentation rot is the biggest risk to long-term project health. Below are recommended practices:

### 8.1 Documentation-as-Code

| Practice | Detail |
|----------|--------|
| **Co-locate docs with code** | Keep IoT.md, assessment.md, and README.md in the same repo, versioned alongside the code. |
| **PR review includes docs** | Every pull request that changes an API, payload format, or deployment step must update the relevant `.md` file. Enforce via a PR checklist or CODEOWNERS rule. |
| **Automated checks** | Use `markdownlint` in CI to catch formatting issues. Add a GitHub Action that fails if `IoT.md` version field doesn't match a tag. |

### 8.2 ADR (Architecture Decision Records)

| Practice | Detail |
|----------|--------|
| **What** | Create a `docs/adr/` folder. Each significant decision gets a numbered Markdown file (e.g. `001-use-mqtt-over-tls.md`). |
| **Template** | Status, Context, Decision, Consequences. |
| **Why** | Captures *why* decisions were made, not just what. Invaluable for onboarding and future assessments. |

### 8.3 Changelog & Release Notes

| Practice | Detail |
|----------|--------|
| **CHANGELOG.md** | Maintain a human-readable changelog following [Keep a Changelog](https://keepachangelog.com/). |
| **Automated** | Use `conventional-commits` + `release-please` or `semantic-release` to auto-generate changelogs from commit messages. |

### 8.4 Living Specification

| Practice | Detail |
|----------|--------|
| **Version in the doc** | IoT.md has a `Version` field at the top. Bump it with every change. |
| **Deprecation notices** | When a payload version is superseded, mark it as `Deprecated` with a sunset date, don't delete it. |
| **Automated payload examples** | Generate the examples in IoT.md Appendix from actual test fixtures (conftest.py) so they never drift. |

### 8.5 Review Cadence

| Frequency | Action |
|-----------|--------|
| Every PR | Check if docs need updating (PR template checkbox). |
| Monthly | Quick review: are README quick-start steps still accurate? |
| Quarterly | Full audit: IoT.md versions, assessment.md priorities, ADR backlog. |
| Per release | Update CHANGELOG.md, tag IoT.md version if payload changed. |

---

## 9. Summary

The IoT Meter platform has a solid v1 foundation. The highest-impact next steps are:

1. **Enable TLS and device authentication** — without this, no production deployment is viable.
2. **Add API authentication** — protect device management operations.
3. ~~**Set up CI/CD**~~ ✅ **Done** — GitHub Actions 3-stage pipeline with self-hosted runner.

All other improvements can be phased in based on scale requirements and team capacity.
