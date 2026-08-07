# Document 13 — DevOps Architecture

**Version:** 2.0 — split from Document 14 v1.0 ("DevOps, Deployment & Operations Runbook"). This
document covers infrastructure topology, CI/CD pipeline design, and observability tooling — the
*architecture* of how the system is built and run. Environment definitions, the deployment
checklist/runbook, release cadence, backup/DR procedures, and tenant operations are in
**Document 16 — Deployment Strategy**. The AWS platform choices are unchanged from v1.0
(Document 04 §1); what changed is the application runtime inside each container.

---

## 1. Infrastructure (AWS ap-south-1, Mumbai)

```
Route 53 ──▶ CloudFront (static + CDN) ──▶ S3 (web build)
         └─▶ WAF ──▶ ALB ──▶ ECS Fargate services
                              ├── api            (2–10 tasks, autoscaled) — uvicorn/gunicorn
                              ├── ingestion      (2–6 tasks, separate target group) — uvicorn
                              ├── worker         (2–8 tasks, scaled on queue depth) — celery worker
                              ├── beat           (1 task, no autoscaling — single scheduler instance)
                              └── flower         (1 task, internal-only, monitoring — Document 11 §5)
                                        │
        ┌───────────────────────────────┼────────────────────────────────┐
        ▼                               ▼                                ▼
  RDS PostgreSQL 16              ElastiCache Redis              S3 buckets
  Multi-AZ primary               cluster mode, 2 nodes          documents / payslips
  + 1 read replica               (cache + Celery broker         resumes / exports / backups
  + pgvector extension             + result backend + sessions)  SSE-KMS, versioned
        │
        ▼
  Automated backups (35 d) + PITR + cross-region snapshot copy

Supporting: Secrets Manager · Parameter Store · KMS · CloudWatch · OpenSearch (logs + search)
            SES · SNS · EventBridge (schedules) · ECR (images)
```

**What changed from v1.0:** the `worker` and `ai-service` ECS services collapse into `worker`
(Celery workers, including the `ai` queue — Document 11 §1) plus the new `beat` service (Celery's
scheduler, previously implicit in BullMQ's repeatable jobs and now an explicit single-instance ECS
service, since `celery beat` must run as exactly one instance — Document 03 §1.1). A `flower`
service is added for Celery monitoring (Document 11 §5), internal-only (not behind the public ALB).
Local development additionally runs **MinIO** in place of S3 (Document 04 §1) via
`docker-compose.yml`.

### 1.1 Sizing (Phase 1 launch → 12 months)

Sizing assumptions are unchanged from v1.0 — Python/FastAPI with `asyncpg` and an async request
model is not meaningfully more resource-hungry per request than the equivalent NestJS deployment for
this I/O-bound workload; the CPU-bound payroll compute step was always going to dominate worker
sizing regardless of language.

| Component | Launch | 12 months (500 tenants / 150k employees) |
|---|---|---|
| API tasks | 2 × (1 vCPU, 2 GB) | 6 × (2 vCPU, 4 GB) |
| Worker tasks | 2 × (2 vCPU, 4 GB) | 6 × (2 vCPU, 8 GB) |
| Ingestion tasks | 2 × (0.5 vCPU, 1 GB) | 4 × (1 vCPU, 2 GB) |
| Beat | 1 × (0.25 vCPU, 0.5 GB) | 1 × (0.25 vCPU, 0.5 GB) — never scales horizontally |
| Flower | 1 × (0.25 vCPU, 0.5 GB) | 1 × (0.5 vCPU, 1 GB) |
| RDS | db.r6g.large, 200 GB gp3 | db.r6g.2xlarge, 1.5 TB gp3, 1–2 read replicas |
| Redis | cache.t4g.medium | cache.r6g.large ×2 |
| Estimated monthly cost | ~$900–1,200 | ~$4,500–6,500 |

Costs exclude AI provider charges, SMS/WhatsApp and support tooling. Review quarterly; the largest
growth driver is RDS storage and IOPS from `punch` and `audit_log` (Document 08 §13).

---

## 2. CI/CD Pipeline

```
Push / PR
  ├─ Lint + format + type check         (ruff check, ruff format --check, mypy)
  ├─ Module boundary check              (lint-imports, Document 07 §3)
  ├─ Unit tests (parallel shards) + coverage gate     (pytest, Document 15 §2)
  ├─ Build (Docker, multi-stage, non-root, minimal base — one image, four entrypoints)
  ├─ SAST (Semgrep) + dependency scan (pip-audit/Safety + Snyk) + secret scan
  ├─ Integration tests (Testcontainers: real Postgres + Redis, Python)
  ├─ Security suites: cross-tenant isolation, permission matrix, data scope, field masking
  ├─ Contract tests against the OpenAPI snapshot (Document 09 §8)
  └─ Image push to ECR (tagged with commit SHA)

Merge to develop
  ├─ Deploy to Dev, then QA
  ├─ Run Alembic migrations (online-safe, Document 08 §14)
  ├─ E2E suite (Playwright) against QA
  ├─ Accessibility scan
  └─ Notify (solo developer — a Slack/email/push notification, not a team channel, Document 25)

Promote to Staging (manual)
  ├─ Deploy, migrate, smoke test
  ├─ Load test (light, k6)
  └─ UAT available

Promote to Production (manual)
  ├─ Pre-deploy checklist (Document 16 §2)
  ├─ Blue-green deploy with health checks
  ├─ Migrations run before the new version takes traffic
  ├─ Smoke tests against production
  ├─ Gradual traffic shift, automatic rollback on error-rate spike
  └─ Post-deploy verification + release notes
```

**Migration safety, unchanged in principle:** every Alembic migration is reviewed for lock behaviour.
Long-running or locking migrations run in a maintenance window outside the payroll blackout.
Expand-contract pattern for all schema changes; never a destructive change in a single release
(Document 08 §14).

**One image, four entrypoints:** the Dockerfile builds a single image containing the full `hrms`
package; which process runs is decided by the container's command
(`entrypoints/api.py` / `entrypoints/ingestion.py` / `entrypoints/worker.py` / `entrypoints/beat.py`
— Document 06 §2), not by four separate images. This keeps the CI pipeline's build/scan/push steps
running once per commit instead of four times, and guarantees all four deployables are always
running identical dependency versions.

**Solo-developer note on the "two approvers" gate:** the original Document 14 v1.0 §3 required two
approvers to promote to Production. With one developer, this is replaced by a **self-review
checklist gate** (Document 05 §7) plus, where the change touches payroll/RBAC/tenancy, a mandatory
cooling-off period (the change sits in Staging for a minimum period — recommend 24 hours — before
Production promotion, giving time for the golden-dataset suite, load tests, and simply re-reading
the diff with fresh eyes to catch what a second reviewer would have) rather than pretending a second
approver exists. If a contractor or second developer is engaged (Document 25), the two-approver gate
is reinstated for their contributions.

---

## 3. Observability Stack

| Layer | Tool | What changed |
|---|---|---|
| Tracing | OpenTelemetry, auto-instrumented for FastAPI, SQLAlchemy, Celery, and `asyncpg` | Python auto-instrumentation packages replace the Node equivalents; the trace propagation story (API → Celery task → DB query) is equivalent or better, since `opentelemetry-instrumentation-celery` propagates trace context into task headers naturally (Document 11 §5) |
| Metrics & dashboards | Grafana Cloud | Unchanged platform |
| Error tracking | Sentry | Unchanged platform; Python SDK (`sentry-sdk`) replaces the Node SDK, same project/alerting configuration |
| Logs | Structured JSON logging (Python `structlog` or stdlib `logging` with a JSON formatter), correlation ID (`X-Request-Id`, Document 09 §1.2) propagated via `contextvars` (Document 07 §5) into every log line, shipped to CloudWatch/OpenSearch | Implementation detail changed; the requirement (structured, correlated logs across API → queue → worker) is unchanged from the original NFR-M9 |
| Dashboards (unchanged content) | Platform health, Queue health, Business metrics, Per-tenant, Cost | See Document 16 §6 for the full alert threshold table — that table is operational/runbook content and belongs there, not here |

---

## 4. Infrastructure as Code

- **Terraform**, unchanged as the IaC tool. Every environment (Document 16 §1) is defined in
  Terraform; environment differences are variables, not separate configurations.
- ECS task definitions reference the single application image (§2) with a different `command` per
  service — four Terraform-managed ECS services (`api`, `ingestion`, `worker`, `beat`) plus `flower`,
  from one `aws_ecs_task_definition` module parameterised by entrypoint.
- No console changes in production; all infrastructure changes via Terraform in version control.

---

## 5. Local Development Environment

```yaml
# docker-compose.yml (abbreviated)
services:
  postgres:      # postgres:16, with pgvector extension enabled
  redis:         # redis:7
  minio:         # MinIO, S3-compatible, for local file storage (Document 04 §1)
  api:           # uvicorn entrypoints.api:app --reload
  ingestion:     # uvicorn entrypoints.ingestion:app --reload
  worker:        # celery -A entrypoints.worker worker --loglevel=info
  beat:          # celery -A entrypoints.worker beat --loglevel=info
  flower:        # celery -A entrypoints.worker flower
```

A solo developer runs `docker compose up` and has the entire backend topology — all four deployables
plus Postgres, Redis, and MinIO — running locally with no cloud account required, closing the loop
between local development and the actual production topology (Document 03 §8) more tightly than a
stack requiring live AWS credentials for local S3 access would. This is a deliberate, material
improvement over the v1.0 local setup for a single-developer delivery model (Document 01 §2).
