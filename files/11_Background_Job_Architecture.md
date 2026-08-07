# Document 11 — Background Job Architecture

**Version:** 2.0 — new document. The original design's background-processing needs (Document 03
v1.0 §1.2 "Worker Service", §6 Payroll pipeline; Document 14 v1.0 §5 scheduled jobs) were described
architecturally but the job system itself (BullMQ) is replaced by **Celery + Redis**
(Document 04 §3 has the comparison and decision rationale). This document specifies how Celery is
organised for this system: queues, task design rules, the full scheduled-job catalogue, and
monitoring.

---

## 1. Queue Topology

| Queue | Purpose | Concurrency policy | Worker pool |
|---|---|---|---|
| `payroll` | Payroll compute steps, statutory file generation, bank advice | **Per-tenant concurrency = 1** (a tenant's own payroll steps run strictly sequentially — Document 03 §5), global concurrency capped by worker count | Dedicated worker process(es), CPU-bound, prefork pool |
| `attendance` | Punch-writer batch inserts, attendance-day recompute (debounced) | High throughput, per-employee-date debounced | Dedicated worker, I/O-bound, gevent/eventlet-style pool acceptable since tasks are mostly DB-bound |
| `notification` | All outbound notification dispatch (email/SMS/WhatsApp/push/in-app) | High concurrency; rate-limited per provider (Document 20 §9.6) | Shared worker pool |
| `reports_exports` | Report generation, bulk exports, bulk imports, bulk letter/PDF generation | Concurrency capped per tenant to protect the read replica (Document 03 §8) | Shared worker pool |
| `ai` | Resume parsing, matching, anomaly detection batches, embedding generation | Quota-metered per tenant plan (Document 12 §4); longer soft/hard time limits than other queues | Dedicated worker — isolates LLM-call latency from the rest of the system so a slow AI provider never starves payroll workers |
| `webhooks` | Outbound webhook delivery with retry/backoff | Standard | Shared worker pool |
| `default` | Everything else: workflow system actions, audit-log writes that couldn't complete synchronously, misc housekeeping | Standard | Shared worker pool |

Queue routing is declared per task (`@app.task(queue="payroll")`), not inferred — an explicit,
greppable decision per task, consistent with the "no magic" principle applied to Celery task
registration in Document 06 §5 (task names are explicit, never auto-discovered).

**Why `payroll` is a dedicated queue with per-tenant concurrency=1, not just "a queue":** two
payroll runs for the *same tenant* computing concurrently is a correctness hazard (both could read
stale intermediate state); two different tenants' payroll runs computing concurrently is fine and
desirable. This is implemented with Celery's `task_routes` plus a Redis-backed per-tenant lock
acquired at the start of the `chain` (Document 07 §7) and released at `FINALISE` or on failure —
the lock, not queue concurrency alone, is the actual correctness guarantee; queue concurrency
tuning is a throughput lever on top of it.

---

## 2. Task Design Rules

Every Celery task in this codebase follows these rules, checked in code review and, for the first
three, by a lightweight custom lint check:

1. **Every task's first argument is `company_id: UUID`.** There is no ambient tenant context in a
   worker process (Document 07 §5) — a task that needs tenant scoping receives it explicitly and
   constructs a `TenantContext` at the top of the task body.
2. **Every task is idempotent.** Re-running a task with the same arguments must not double-apply an
   effect (double-credit a leave ledger entry, double-send a notification, double-charge a fee).
   Idempotency is achieved per-task by the appropriate mechanism: a unique constraint the insert
   relies on (e.g. `punch.idempotency_key`), a status-checked upsert (e.g. "only send if
   `notification_log.status != 'SENT'`"), or an explicit idempotency key passed through from the
   originating request (Document 09 §1.6).
3. **Every task is resumable, or explicitly not resumable and documented why.** The payroll pipeline
   (Document 03 §5) is the canonical resumable example — each step writes its checkpoint before the
   next step starts.
4. **Tasks open their own DB session** from the shared `async_session_factory` (Document 08 §15),
   scoped to the task's execution — never a session passed in from elsewhere, never a
   module-level/global session.
5. **Tasks never call other tasks synchronously by importing and invoking the function directly** —
   composition happens through Celery's `chain`/`group`/`chord` primitives (Document 07 §7) or by
   calling the owning module's `service.py` method, which is the same public interface a router
   would call. This keeps a task's "shape" (what it does, what it depends on) visible in its
   registration rather than buried in ad hoc function calls.
6. **A task's Celery-level retry policy is declared explicitly** — `max_retries`, `retry_backoff`,
   and whether failures after exhausting retries move to a dead-letter queue with an alert
   (Document 13 §2) versus fail silently (never acceptable — Document 16 §5's "alert on
   non-execution" principle applies equally to a task that runs and gives up quietly).

```python
# modules/leave/tasks.py
@celery_app.task(
    name="leave.run_monthly_accrual",
    queue="default",
    max_retries=3,
    retry_backoff=True,
    acks_late=True,        # re-delivered if the worker dies mid-task, not lost
)
def run_monthly_accrual(company_id: str, as_of: str) -> None:
    asyncio.run(_run_monthly_accrual_async(UUID(company_id), date.fromisoformat(as_of)))

async def _run_monthly_accrual_async(company_id: UUID, as_of: date) -> None:
    async with async_session_factory() as session:
        tenant = TenantContext(company_id=company_id)
        service = LeaveService(session, tenant)
        await service.run_monthly_accrual(as_of)  # itself idempotent — checks leave_ledger
                                                     # for an existing ACCRUAL entry this period
```

**On the sync/async boundary:** Celery's task execution model is process/thread-based, not
`asyncio`-native (Document 04 §3), so every task body is a thin synchronous wrapper (`asyncio.run(...)`)
around an async implementation function that reuses the same async SQLAlchemy session machinery as
the rest of the codebase. This is the one place Celery's non-async-native design shows up in code,
and it is deliberately isolated to this one-line pattern repeated at the top of every task, not
spread through business logic — the actual task body (`_run_monthly_accrual_async` above) is
ordinary `async`/`await` code identical in style to a service method called from a router.

---

## 3. The Payroll Pipeline as a Celery Canvas

Full business detail in Document 03 §5. The Celery composition:

```python
def build_payroll_chain(pay_run_id: UUID, employee_batches: list[list[UUID]]) -> chain:
    return chain(
        snapshot_inputs.s(str(pay_run_id)),
        chord(
            group(compute_batch.s(str(pay_run_id), [str(e) for e in batch]) for batch in employee_batches),
            validate_and_summarise.s(str(pay_run_id)),   # the chord callback runs once all batches finish
        ),
        # VARIANCE and REVIEW are not automated — the pipeline pauses here for human approval
        # (Document 03 §5 step 6 "cannot be skipped"); FINALISE is triggered by a separate
        # POST /pay-runs/{id}/finalise call, not chained automatically.
    )
```

This is the concrete realisation of "Document 04 §3's decision to use Celery specifically because
its canvas primitives match this pipeline" — the `chord` here is exactly the fan-out/fan-in the
compute step needs (parallel batches of 200 employees, Document 03 §5 step 3), and the pipeline's
checkpointing (`pay_run.checkpoint`, Document 08 §8.4) is updated by each step on completion so a
crash resumes from the last completed step rather than re-running the whole chain.

---

## 4. Scheduled Jobs (Celery Beat)

Unchanged in business content from Document 14 v1.0 §5; scheduling mechanism is now `celery beat`
with a database-backed schedule (`django-celery-beat`'s scheduler pattern, adapted — this project
uses `celery[redis]` with a Redis-backed periodic task schedule, or a simple static
`beat_schedule` dict in `entrypoints/beat.py` for jobs whose cadence is not tenant-configurable, and
a small custom scheduler for the few jobs that are tenant-configurable, such as scheduled report
delivery).

| Job | Schedule | Queue | Notes |
|---|---|---|---|
| Attendance day resolution | Every 15 min + event-triggered | `attendance` | Debounced per employee/date |
| Absent marking for the previous day | 02:00 company-local | `attendance` | After the punch-sync grace window |
| Leave accrual | Monthly, configurable day, 01:00 | `default` | Idempotent (§2 rule 2) |
| Comp-off expiry | Daily 01:30 | `default` | |
| Leave year-end processing | On the FY boundary, manual confirm | `default` | Preview required |
| Future-dated changes activation | Daily 00:15 | `default` | Assignments, compensation, statutory |
| Probation/confirmation reminders | Daily 08:00 | `notification` | T-30, T-15, T-0 |
| Document expiry alerts | Daily 08:00 | `notification` | 30/15/7 days |
| Birthday/anniversary greetings | Daily 08:00 company-local | `notification` | Opt-out honoured |
| Roster generation | Weekly | `attendance` | N weeks ahead |
| Access revocation for exits | Daily 23:55 | `default` | Per last working day |
| Notification retry sweep | Every 5 min | `notification` | |
| Stuck workflow detection | Hourly | `default` | Flags requests idle > 7 days |
| Device heartbeat check | Every 30 min | `default` | Alert if silent > 2 h |
| Scheduled report delivery | Per user configuration | `reports_exports` | |
| Dashboard metric aggregation | Hourly | `default` | |
| Data retention enforcement | Weekly | `default` | |
| Audit log archival to S3/MinIO | Monthly | `reports_exports` | Partitions older than 12 months |
| Punch partition maintenance | Monthly | `default` | Create next, archive old |
| Backup restore verification | Monthly | — (infra-level, not a Celery task) | Document 13 §5 |
| Statutory due-date reminders | Daily | `notification` | Compliance calendar |
| Outbox event dispatch sweep | Every 10 s | `default` | Polls `outbox_event` for undelivered rows (Document 07 §7) — this is new to this document because it's the mechanical link between the outbox pattern and Celery that didn't need spelling out under BullMQ's different primitives |

**All jobs:** idempotent, resumable, logged to `job_log` (Document 08 §11), monitored for both
failure **and non-execution** (a job that silently stops running is the more dangerous failure —
alert on "expected run did not occur", Document 13 §2).

---

## 5. Monitoring

- **Flower** (Celery's web monitoring dashboard) runs as a small additional deployable in
  non-production and, behind authentication, in production — gives task history, worker status,
  queue depth, and retry counts without hand-rolled tooling (this is one of the concrete advantages
  cited in the Document 04 §3 comparison table).
- **OpenTelemetry** auto-instrumentation for Celery (`opentelemetry-instrumentation-celery`) traces
  a task's execution as a span linked to the originating request's trace where one exists (e.g. a
  `POST /pay-runs/{id}/compute` request's trace ID is propagated into the Celery task headers), so a
  slow payroll run can be traced from the initiating API call through every chain step to the
  database query that's slow — the cross-process tracing story Document 04 §1 flagged as a deciding
  factor for Celery.
- **Queue depth, processing rate, failure rate, DLQ size, oldest message age** feed the "Queue
  health" dashboard (Document 13 §6).
- Dead-letter handling: a task that exhausts its `max_retries` is routed to a per-queue
  `<queue>.dlq` and triggers an alert (Document 13 §2) — nothing fails silently.
