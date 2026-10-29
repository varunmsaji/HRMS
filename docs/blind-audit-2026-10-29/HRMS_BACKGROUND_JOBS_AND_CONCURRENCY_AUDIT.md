# HRMS Background Jobs & Concurrency Audit

## 1. Topology (confirmed from `docker-compose.prod.yml`, `core/celery_app.py`)
One `worker` (concurrency `${CELERY_CONCURRENCY:-2}`), one `beat` (`--schedule=/tmp/celerybeat-schedule`, healthcheck disabled), Redis broker/backend, queues `default` and `reports_exports`. Serializer JSON only. Scheduled (timezone `Asia/Kolkata`, `enable_utc=True`):

| Task | Schedule | Idempotency evidence |
|---|---|---|
| leave.run_monthly_accrual | 01:00 daily | unique ledger index `uq_leave_ledger_cycle_entry` |
| leave.run_comp_off_credit_sweep | hourly | `uq_leave_ledger_comp_off_credit` |
| leave.run_comp_off_expiry_sweep | 01:30 | not verified |
| leave.run_year_end_sweep | 02:00 | `leave_year_end_run` unique |
| attendance.run_daily_calculation | 09:30 | `attendance_day` unique + `engine_version`; recompute semantics not verified |
| employee.run_termination_access_sweep | hourly :15 | not verified |
| attendance.run_incomplete_reminders | 10:00 | duplicate-send protection not verified |
| attendance.run_face_cleanup | 03:15 | batched deletes |
| attendance.run_face_deletions | every 2 min | `face_external_deletion` table, alert after N attempts |
| email_outbox.sweep | 60 s | lease columns (`email_outbox_lease_seconds`), max attempts 6, backoff cap |
| health.scheduler_heartbeat | 60 s | – |

## 2. Findings
| ID | Sev | Conf. | Finding | Evidence |
|---|---|---|---|---|
| F-08a | P2 | confirmed | `acks_late` + `reject_on_worker_lost` + bounded `autoretry_for` are set **only** in `leave/tasks.py:55-61`. Other tasks use Celery's default early-ack: a worker crash/redeploy mid-task silently loses it. Daily jobs self-heal next day only if their logic is "catch-up" rather than "today only" (not verified). | `grep acks_late` |
| F-08b | P2 | confirmed | Beat schedule persisted to `/tmp` (comment says "safe to lose"). Crontab entries missed while beat is down are **not** replayed; a deploy at 00:55–01:05 can skip a day of accrual unless the task derives its window from the last run. | compose `:224` |
| F-08c | P2 | probable | One global schedule timezone for a multi-tenant product; attendance calc at 09:30 IST is "yesterday" for India but not for other zones. Fine for an India-only pilot. | `celery_app.py` |
| F-08d | P3 | confirmed | Single beat instance is assumed (correct); nothing prevents an accidental second beat from double-scheduling except task-level idempotency. | |
| F-02 | P1 | probable | Mid-run `commit()` drops transaction-local `app.company_id`. `employee_import` worker path correctly uses `_commit_and_restore_rls`; the **request** path commit at `:177` and its failure branch `:190-197` do not. Under `hrms_app` the UPDATE on RLS table `employee_import_batch` would see an empty GUC (uuid cast error) → the intended "mark FAILED + 503" never happens; batch may remain `PENDING`. Test `test_import_idempotency.py:160` asserts the log event but runs as superuser. | `employee_import/service.py:177-205, 611-620` |
| F-30 | P2 | unverified | Other commit sites to audit for the same class: `account_invite/service.py:337`, `onboarding/email_outbox.py:235,255,274,292,329`, `onboarding/email_sender.py:169`, `attendance/face_service.py:183`, `platform/service.py:132,369`, `core/crypto/provisioning.py:43,67`, `pii_backfill.py`. Several are in their own `session_scope(company_id=…)`; each needs a "next query after commit" check. | grep |

## 3. Idempotency & concurrency design (strengths)
* Postgres advisory locks for cross-aggregate ordering with documented acyclic order and bounded waits → retryable lock-timeout errors instead of hangs (`core/db/locks.py`).
* `idempotency_key` table + `Idempotency-Key` header for write endpoints; replays marked in response.
* Optimistic `If-Match`/`version` on lifecycle transitions.
* Per-company fan-out (`dispatch_per_company`) with soft/hard time limits (1500/1800 s company tasks; 120/180 s fan-out); one company's enqueue failure doesn't abort others.
* Celery task failure/retry/unknown/rejected signals are logged with metrics (`core/celery_app.py` imports `task_failure`, `task_retry`, `task_rejected`, `task_unknown`).

## 4. Gaps
* No dead-letter queue concept besides outbox attempt counters and face-deletion alerting; failed Celery tasks are logged and metered, not parked for replay.
* Employee import: `max_retries=0` by design; broker publish failure handled (modulo F-02).
* Long work in requests: face verification is synchronous with a bounded concurrency (`face_os_max_concurrency`, timeouts) — acceptable; load not tested.
* Result backend retention/TTL for Celery results not verified.

## 5. Recommendations (not implemented)
1. Fix F-02 by calling `_commit_and_restore_rls` (or re-applying the GUC) wherever a request path commits and then continues; add a lint/test helper that fails if `commit()` is followed by a tenant query without GUC restore.
2. Set `task_acks_late=True`, `task_reject_on_worker_lost=True` globally and keep per-task opt-outs for non-idempotent ones; verify each task is idempotent first.
3. Make daily jobs compute from "last successful run" (store watermark) so a missed beat is caught up; or run beat with a persistent volume + `DatabaseScheduler`-style store.
4. Define the schedule-timezone policy (company TZ vs IST) before onboarding non-India tenants.
