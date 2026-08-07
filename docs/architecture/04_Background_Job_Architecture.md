# Background Job Architecture

**Replaces:** BullMQ (Node.js)  
**Chosen system:** **Celery + Redis** (broker and result backend)  
**Spec reference:** `files/11_Background_Job_Architecture.md`, `files/04` §3

---

## 1. Candidate evaluation

| | Celery | Dramatiq | ARQ | RQ |
|---|--------|----------|-----|-----|
| Workflow chains (payroll pipeline) | **Best** (canvas) | Good | Minimal | Minimal |
| Scheduled jobs | celery beat | Needs APScheduler | Built-in cron | rq-scheduler |
| Monitoring | **Flower** + OTel | Basic | Minimal | rq-dashboard |
| Maturity / ops knowledge | **Highest** | Medium | Low | Maintenance mode |
| Async-native workers | Partial | Partial | Yes | No |
| Fit for this HRMS | **Selected** | Rejected for payroll orchestration | Rejected — too simple | Rejected |

**Decision:** Celery — payroll `chain`/`chord`, notification `group`, solo-operator visibility via Flower, OpenTelemetry instrumentation across API → worker → DB.

---

## 2. Queue topology (planned)

| Queue | Workload | Concurrency |
|-------|----------|-------------|
| `default` | Notifications, outbox sweep, light tasks | Standard |
| `payroll` | Pay run computation | **1 per tenant** (rate limit / chord) |
| `attendance` | Punch batch resolution | Medium |
| `ai` | Resume parse, embedding batch | Medium, timeout-aware |
| `reports` | Large exports | Low priority |

Configured in `core/celery_app.py` and task `queue=` kwargs.

---

## 3. Worker design

| Rule | Detail |
|------|--------|
| Entrypoint | `celery -A entrypoints.worker worker` |
| Task location | `modules/<name>/tasks.py` |
| Task naming | Explicit `name="module.verb_noun"` — no auto-discovery magic |
| Tenant context | **`company_id` first argument** on every task — no ambient request context |
| Idempotency | `task_id` or business key in Redis; safe retries |
| DB session | Create `AsyncSession` inside task; set RLS company_id |
| Long jobs | Checkpoint fields on domain tables (pay run steps) |

Sample (health module today):

```python
@celery_app.task(name="health.ping")
def ping() -> str:
    return "pong"
```

---

## 4. Retry & failure handling

| Concern | Approach |
|---------|----------|
| Retries | `autoretry_for`, `max_retries`, exponential backoff |
| Permanent failure | Task marked failed; row in `job_log` (planned) |
| Poison messages | Max retries then dead-letter queue / alert |
| Payroll | Never silent fail — alert + block payment (`files/16` runbook 1) |
| Outbox | At-least-once delivery; consumers must be idempotent (ADR-0012) |

---

## 5. Scheduling (Beat)

| Job | Schedule | Task |
|-----|----------|------|
| Outbox sweep | Every 10s | `core.events.tasks.dispatch_outbox` |
| Leave accrual | Monthly cron | `leave.run_monthly_accrual` |
| Attendance lock | Daily | `attendance.lock_period` |

Run: `celery -A entrypoints.worker beat`

Single beat instance in production (ECS service count = 1).

---

## 6. Monitoring

| Tool | Purpose |
|------|---------|
| **Flower** | Queue depth, task history, worker health (local: add to dev script later) |
| OpenTelemetry | Trace propagation via `opentelemetry-instrumentation-celery` |
| Grafana | Queue depth, task latency dashboards |
| Sentry | Worker exceptions with same `request_id` / `company_id` tags |
| Alerts | Oldest task age, worker heartbeat missing (`files/16` §6) |

---

## 7. Local development

```bash
cd apps/api
uv run celery -A entrypoints.worker worker --loglevel=info
uv run celery -A entrypoints.worker beat --loglevel=info
```

Requires Redis (`docker compose up -d`).

---

## 8. Related ADRs

- [ADR-005 Background Jobs](../adr/ADR-005-Background-Job-Architecture.md)
- [ADR-0014 Celery detail](../adr/0014-celery-redis-job-queue.md)
- [ADR-0012 Outbox](../adr/0012-outbox-pattern.md)
