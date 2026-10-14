# Logging, Error Handling & Observability — Autonomous Execution Report

| | |
|---|---|
| **Date** | 2026-10-14 |
| **Branch / HEAD** | `main` @ `c4431f5f3c8ca6d9ac2734efc68f55be6a819fd5` (unchanged; nothing committed, pushed, merged, deployed or restarted) |
| **Inputs** | `LOGGING_ERROR_HANDLING_OBSERVABILITY_PLAN.md`, `LOGGING_ERROR_HANDLING_REMEDIATION_REPORT.md`. The other two reports named in the brief (`…_FINAL_VERIFICATION.md`, `…_PHASE2_REPORT.md`) do not exist. |
| **Verdict** | **MISSION SUBSTANTIALLY COMPLETE — READY FOR STAGING VALIDATION** (with the open decisions in §18–19 and the not-run checks in §16) |

---

## 1. Mission summary and verdict

This work implemented and tested the remaining logging plan (LOG-06 to LOG-17 and OPS-A) across
the API, Celery worker and Beat, web, mobile and operations. Along the way it found and fixed
three real defects, each proven against a clean `HEAD` worktree:

1. **Onboarding activation was undone by a failing account-invite auto-issue.** A database
   error inside the best-effort step aborted the request transaction, so `POST …/activate`
   returned **500** and the activation was lost. At `HEAD` the regression test fails with
   `assert 500 == 200`.
2. **A redelivered or concurrent import message duplicated employees.** The create-only
   pipeline processed any batch it was given. At `HEAD` both the redelivery test and the
   concurrent test end with `assert 3 == 2`: three employees instead of two.
3. **A log write to a closed stdout aborted business code.** Leave's fan-out loop crashed with
   `ValueError: I/O operation on closed file` from a `_logger.warning(...)`. Logging now goes
   through a resilient sink that drops and counts failed writes instead of raising.

Also fixed, outside the original plan:

- Readiness answered **500 instead of 503** when the database refused connections: a bare
  `ConnectionRefusedError` escaped `_check_database`.
- The test suite could send **real email** (`.env` selects Hostinger) and call **real Face++**.
  Tests also pushed Celery messages into the developer's Redis db0 backlog. Isolation is now
  forced in `tests/conftest.py`.

The verdict is "substantially complete" rather than "complete" for two reasons:

- alerting has no configured destination (D1), and retention is undecided (D2);
- nothing was exercised on staging, real devices or real providers (§16).

The code is ready for staging validation; it is not claimed to be production-ready.

## 2. Initial state

- Branch `main`, HEAD `c4431f5` ("feat: employee documents, logging/error-handling
  remediation, refresh-token reuse fix, and Hostinger email").
- `git status --short` was **empty**: the tree was clean. The earlier remediation and the
  user's employee-document work were already committed in `c4431f5`, so there were no
  uncommitted user changes to protect.
- Redis db0 held **224** unconsumed `reports_exports` messages (the historical backlog).

## 3. Files changed by this mission

**Production code (API)**

- `core/observability/`
  - `logging.py`
  - `redaction.py`
  - `request_context.py`
  - `classification.py` (new)
  - `security_events.py` (new)
  - `business_events.py` (new)
- `core/errors/handlers.py`
- `core/db/session.py`
- `core/celery_app.py`
- `core/audit/service.py`
- `core/auth/dependencies.py`, `core/rbac/dependencies.py`, `core/tenancy/dependencies.py`
- `shared/rate_limit.py`
- `modules/`
  - `identity/service.py`
  - `onboarding/email_sender.py`, `onboarding/service.py`
  - `account_invite/service.py`
  - `attendance/face_service.py`, `attendance/reminders.py`, `attendance/tasks.py`
  - `employee/tasks.py`
  - `employee_import/repository.py`, `employee_import/service.py`, `employee_import/tasks.py`
  - `leave/service.py`, `leave/tasks.py`
  - `health/service.py`, `health/tasks.py`
- `ops/__init__.py`, `ops/job_health.py` (new)
- `apps/api/Dockerfile` (dropped the plaintext gunicorn access log)

**API tests**

- Modified:
  - `tests/conftest.py`
  - `unit/core/test_celery_task_failure_logging.py`
  - `unit/core/test_unhandled_exception_logging.py`
  - `unit/modules/leave/test_leave_task_hardening.py`
  - `unit/modules/onboarding/test_email_sender.py`
- New, unit:
  - `unit/test_test_isolation.py`
  - `unit/core/test_log_redaction.py`
  - `unit/core/test_celery_task_lifecycle_logging.py`
  - `unit/core/test_task_hardening.py`
  - `unit/modules/onboarding/test_email_failure_classification.py`
  - `unit/ops/test_host_monitor.py`
- New, integration:
  - `integration/core/test_http_access_event.py`
  - `integration/core/test_db_failure_classification.py`
  - `integration/core/test_business_events.py`
  - `integration/core/test_job_health_and_readiness.py`
  - `integration/auth/test_security_events.py`
  - `integration/modules/employee_import/test_import_idempotency.py`
  - `integration/modules/onboarding/test_activation_failure_isolation.py`

**Web**

- `src/lib/api/client.ts`, `src/lib/api/errors.ts`
- New:
  - `src/app/error.tsx`, `src/app/app/error.tsx`, `src/app/global-error.tsx`
  - `src/components/common/route-error.tsx`
- Tests: `client.test.ts`, `errors.test.ts`, `route-error.test.tsx` (new)

**Mobile**

- `lib/core/api/api_client.dart`, `lib/core/api/api_error.dart`
- `lib/core/diagnostics/app_diagnostics.dart` (new)
- `lib/main.dart`
- `lib/features/attendance/data/attendance_repository.dart`
- `lib/features/attendance/presentation/attendance_self_screen.dart`
- Tests:
  - `test/core/api_error_handling_test.dart`, `test/core/punch_idempotency_test.dart` (new)
  - Two stale test fakes that did not compile at `HEAD`: `test/support/fake_api_client.dart`,
    `test/leave_applications_test.dart`

**Infra, CI, docs**

- `infra/monitoring/hrms_monitor.sh` (new)
- `.github/workflows/ci.yml` (new `mobile` job)
- `docs/deployment/PRODUCTION_DEPLOYMENT.md` (§15–16)
- `docs/operations/LOGGING_AND_OBSERVABILITY.md` (new)
- `docs/operations/ALERTS_AND_RUNBOOKS.md` (new)
- This report

## 4. Pre-existing work preserved

The tree was clean at start, so every modification above belongs to this mission.

- **Formatting scope.** `ruff format` / `ruff check --fix` were run on wider paths than the files
  I edited. `git status` and per-file hunk lists were checked afterwards: no unrelated file was
  changed.
- **Build side effect.** `next build` rewrote the tracked `apps/web/next-env.d.ts`. I restored
  that file. It had been clean at baseline.
- **`HEAD` comparisons.** These ran in a scratchpad `git worktree`, outside the repository
  working tree, which was removed afterwards.
- **No destructive git operations.** No stash, reset, clean or checkout of user files.

## 5. Earlier findings re-validated

TXN-01, PRA-04, LOG-01, LOG-02, LOG-03, LOG-04 and LOG-05 are all present in the code. Their
targeted suites ran under the new isolation: **226 passed**.

That run's import tests enqueued into db15. db0 stayed at **224** throughout the mission (checked
repeatedly, including after every `HEAD` comparison run).

## 6. Implemented work by phase

| Phase | What changed |
|---|---|
| 0 Test safety | `conftest.py` **forces** these, overriding `.env`: `EMAIL_PROVIDER=logging`, `FACE_VERIFICATION_PROVIDER=disabled`, and the Celery broker/result backend on Redis DB 15 (`HRMS_TEST_CELERY_DB` overrides it). A regression test proves the effective sender, provider and broker resolve this way. |
| 2 Contract | `redact_event` processor on every pipeline (keys, value patterns, length bounds, bytes, failure fallback). `safe_error()` with `error_category`. Resilient stdout sink. One `http_request` access event per request: route template, status, duration, `error_code`, verified tenant; healthy probes quiet. Gunicorn plaintext access line removed. |
| 3 Auth/security | `security.*` events for login (all failure reasons), lockout, refresh rejections, logout, password reset, email verification, rate-limit trips (first per key per window), authorization denials, tenant rejections, and server-state access-token rejections. `subject_hash` (keyed HMAC) for unknown accounts. A test proves a broken log sink cannot weaken lockout. |
| 4 Database | Categories (`db_timeout`, `db_pool_exhausted`, `db_deadlock`, `db_serialization`, `db_connection`, `db_integrity`, …). Pool exhaustion, deadlock and serialization failure → `503 DATABASE_BUSY` + `Retry-After`. A **lost connection stays 500**, because the COMMIT may have landed. A failed rollback no longer replaces the original error. Proven against a real terminated backend and a real unique violation (sentinel value absent from logs). |
| 5 Modules | `business.audit_recorded` from `AuditService.record`, emitted **only after commit** and discarded for rolled-back transactions and SAVEPOINTs. It covers every audited transition in every module, with `from_status`/`to_status` for pay runs and similar. Activation auto-issue now runs in a SAVEPOINT and its outcome is logged. Import: atomic PENDING→PROCESSING claim plus batch lifecycle events. Face clean-up failures now carry `provider_person_id` and `object_key`. The reminder log no longer contains the recipient address. |
| 6 Email | Senders classify each failure: `failure_class`, `retryable`, `outcome` `not_sent` vs **`unknown`** (after a read timeout or 5xx). Callers log one `email.delivery.failed` with `email_kind` and IDs, never the address. All 7 silent swallow sites are now logged. `email.provider.accepted` is explicitly not "delivered". The dev logging sender writes the readable copy to stderr. Best-effort semantics are unchanged; no outbox. |
| 7 Celery | Lifecycle events: `celery_task_finished` (state, duration), `celery_task_retry` (classified by the underlying cause), plus unknown and rejected messages. **Every task now has a hard time limit**, enforced by a test. The create-only import gets a hard limit only, no soft limit. Attendance and termination fan-outs are isolated per company. `SoftTimeLimitExceeded` is no longer swallowed as an item failure. Enqueue-time header added. Beat heartbeat task. Read-only `python -m hrms.ops.job_health`. |
| 8 Web | Route boundary (`app/app/error.tsx`, inside the nav shell), public boundary, `global-error.tsx`. None shows internal error text; all show a request ID or digest reference and offer retry. Client changes: 30 s / 120 s timeouts (never auto-retried; writes warn the outcome is unknown), `OFFLINE` vs `NETWORK_ERROR`, readable proxy 502–504, request-ID fallback (envelope → header → sent ID), `describeApiError` adds "(Reference: …)" for 5xx and status 0, `isRetryableError` for reads, timeout on refresh. |
| 9 Mobile | Dio timeouts: connect 10 s, receive 30 s, send 60 s, transfer 120 s. Timeout and network mapping with write-uncertain wording, request-ID fallback, readable 502–504. Global handlers (`FlutterError.onError`, `PlatformDispatcher.onError`, release `ErrorWidget`) record to an in-memory, bounded `AppDiagnostics` with no message text. Self-punch now always sends an `idempotency_key`, and the screen reuses it only after a no-response failure; the server already replays on the same key. |
| 10 Health/metrics | Readiness logs which dependency failed (and now returns 503 on a refused database). `job_health` gives heartbeat age, queue depth and oldest-message age. **No metrics endpoint was added**: there is no Prometheus or collector to scrape it. Signals are consumed by the host monitor instead. |
| 11 Alerts/runbooks | `infra/monitoring/hrms_monitor.sh`: read-only, 18 checks, JSON report, optional `HRMS_ALERT_COMMAND`. `ALERTS_AND_RUNBOOKS.md`: condition, source, severity, provisional threshold, false positives, diagnosis, safe recovery, what not to do and escalation for each dependency. |
| 12 Retention | `LOGGING_AND_OBSERVABILITY.md` §7: store-by-store bounds, retention options for D2, access, clock, and failure modes (log outage, volume, duplicates). No retention period was invented. |
| 13 Adversarial | Covered by the tests in §13. |
| 14 CI | New `mobile` job (analyze + test, Flutter 3.29.2). New API tests run in the existing unit and integration jobs: `bash`/`jq` are on `ubuntu-latest`, and Redis is a CI service. |

## 7. Event conventions and correlation

See `docs/operations/LOGGING_AND_OBSERVABILITY.md` §1–5 for the full catalogue. Correlation:

1. Nginx generates or forwards the request ID.
2. `RequestContextMiddleware` validates it.
3. It appears on every event, the `audit_log` row, the response header and body, and the Celery
   header (alongside `task_id`).
4. Web and mobile show it as the support "Reference".

## 8. Error handling and retry behaviour

- **Expected 4xx:** no error log; `http_request.error_code` only.
- **Transient database failures** (timeout, pool, deadlock, serialization): `503 DATABASE_BUSY`
  with `Retry-After`. Clients never auto-retry writes.
- **Connection loss:** 500, because the outcome is unknown.
- **Email:** a single failure record, no retry, `outcome` marks uncertainty.
- **Celery:** retry policy unchanged (Leave only, `autoretry_for` connection errors). Hard limits
  everywhere; acknowledgement settings unchanged.
- **Imports:** never re-run for a non-PENDING batch.
- **Clients:** timeouts are reported, not retried. Retry controls exist for reads only.

## 9. Privacy and redaction controls and tests

- **API — redaction processor:** 22 key cases, 6 kept-key cases, 10 value-pattern cases,
  template preservation, truncation, bytes, hostile objects, failure fallback.
- **API — end to end:** JSON pipeline sentinel tests (structlog and stdlib); log-injection
  test; DB sentinel and constraint-value tests; token route tests.
- **API — events:** security events never contain the password, token or address; the access
  event never contains the raw path.
- **Web/mobile:** never surface internal error text. Mobile diagnostics hold no message text
  (tested with a sentinel address).

## 10. Frontend and Flutter coverage

**Web:** boundaries and client tests (§13). The production build passes. The boundaries were
**not exercised in a browser**: they are covered by component tests only.

**Mobile:**

- `flutter analyze` is clean (with one documented `ignore`).
- `flutter test`: 475 passed, 1 skipped.
- **Not run on any device or emulator.** Release-mode `ErrorWidget` and
  `PlatformDispatcher.onError` behaviour on Android and iOS is unverified.

## 11. Celery, Beat and integration coverage

**Critical-task inventory after this work:**

| Task | Time limit | Retry | Idempotent | Failure visibility | Stuck detection |
|---|---|---|---|---|---|
| `leave.*` (7) | soft/hard | connection errors ×3 | yes | `leave_task_failed`, `celery_task_*` | heartbeat, queue age |
| `attendance.calculate_company` / `calculate_range` | 1500/1800 s | none | yes (recalculation) | per-item and `_incomplete` events | queue age |
| `attendance.run_daily_calculation`, `run_incomplete_reminders` | 120/180 s | none | yes | `celery_fanout_incomplete` | heartbeat |
| `attendance.send_incomplete_reminders_company` | 1500/1800 s | none | yes (audit-keyed per day) | `email.delivery.failed` | — |
| `employee.enforce_terminations_company`, `run_termination_access_sweep` | 1500/1800 s, 120/180 s | none | yes | fan-out isolation | heartbeat |
| `employee_import.process_batch` | hard 3600 s only | none (create-only) | **now guarded** (PENDING claim) | batch events | manual SQL (RLS) |
| `health.ping`, `health.scheduler_heartbeat` | 10/20 s | — | yes | — | is the detector |

Still open:

- `acks_late` is set only for Leave. Making the other idempotent tasks late-acking is safe, but
  it changes redelivery behaviour, so it is left as a recommendation.
- No automatic retry exists for attendance or termination tasks; their next scheduled run is the
  recovery path.

## 12. Metrics, health and alerting status

| Item | Status |
|---|---|
| Liveness/readiness | **Existing and verified.** Readiness 503 on a refused database **implemented and tested**. |
| Job health (heartbeat, queue depth and age) | **Implemented and tested.** Needs a deploy to start the heartbeat. |
| Host monitor (18 checks) | **Implemented and tested** with a fake `docker`. **Not run on the VPS.** |
| Alert delivery | **Blocked by explicit decision (D1).** The hook exists; no destination is configured. |
| Metrics endpoint / Prometheus | **Not implemented, deliberately.** No collector exists, so log-derived counts are used instead. |
| External uptime check | **Not implemented**, pending D1/D3. |

## 13. Tests run, with exact results

All backend runs used Postgres `localhost:5433`, Redis `localhost:6380` and local MinIO.
Isolation was forced by `conftest.py` (verified by `tests/unit/test_test_isolation.py`).

| Run | Result |
|---|---|
| Prior-remediation regression (TXN-01, PRA-04, LOG-01/02/04/05, import) | 226 passed |
| `tests/unit` (final) | **1001 passed** |
| New integration files (access event 7, DB classification 17, business events 9, job health/readiness 4, security events 9, import idempotency 3, activation isolation 2) | all passed |
| `tests/unit/ops/test_host_monitor.py` | 17 passed |
| Employee import suite | 10 passed |
| **Full backend suite** `pytest tests` (final) | **2632 passed, 1 failed** (pre-existing, §15) in 655 s |
| Web `vitest run` | 62 files, **516 passed** |
| Web `tsc --noEmit` | clean |
| Web `next build --webpack` | **succeeded** (one Next-internal Edge-runtime warning, pre-existing) |
| Mobile `flutter analyze` | **No issues found** |
| Mobile `flutter test` | **475 passed, 1 skipped** (`test/live`, opt-in) |
| `HEAD` comparisons (scratchpad worktree) | Activation isolation fails at `HEAD` (500); import idempotency fails at `HEAD` (3 ≠ 2, both tests); `account_invite` permission-set failure **reproduces at `HEAD`** |

### 13a. Full backend suite

**First full run: 2629 passed, 4 failed.**

- One failure was the pre-existing `account_invite` permission-set test.
- Three were order-dependent tests: they used `structlog.testing.capture_logs()` against
  module-level loggers that an earlier test had cached (`cache_logger_on_first_use`). They passed
  in isolation.
- Fix: each `capture_logs`-based test module (5 in total) now patches in a fresh logger proxy.

**Final full run: `pytest tests` → 2632 passed, 1 failed, 4 warnings (655 s).** The one failure
is `test_account_invite.py::test_invite_employee_accept_and_login_success`, which also fails at
clean `HEAD` (§15). Redis db0 `reports_exports` was 224 before and after.

## 14. Static analysis

- `ruff check .`: 13 errors, **identical to `HEAD`'s 13** (alembic plus five test files, all
  pre-existing; a separate clean-up task was offered).
- `ruff format --check .`: 5 files, **identical to `HEAD`**.
- New and modified files are clean.
- `mypy src/hrms` (strict): **no issues, 185 files**.
- `lint-imports`: **1 kept, 0 broken**.
- ESLint on touched web files: clean. The one ESLint error in `src/lib/auth` is pre-existing and
  in an untouched file; CI marks ESLint non-blocking.

## 15. Known pre-existing failures

- **`test_account_invite.py::test_invite_employee_accept_and_login_success`.** The permission
  set gained `EMPLOYEE.VIEW_DOCUMENTS`. The same assertion fails at clean `HEAD`
  (scratchpad-worktree run), so it is pre-existing and unrelated.
- **Mobile.** `flutter analyze` at `HEAD` reported 2 compile errors in test fakes plus 1
  warning. Fixed here, as test-only signature updates.
- **Lint debt.** `ruff` at `HEAD`: 13 lint errors and 5 unformatted files. CI's lint step
  therefore fails at `HEAD`, independent of this work.

## 16. Not executed, and why

- **Staging, VPS, production:** none (forbidden). That includes the host monitor on a real
  host, Nginx reload, gunicorn without an access log, and the Beat heartbeat under a real Beat.
- **Real email, Face++ or MinIO outage injection:** mocked or stubbed only. No real provider was
  contacted. Isolation is enforced.
- **Browser runtime of the error boundaries:** not run; component tests and build only.
- **Mobile on a device or emulator:** not run.
- **Real Celery worker subprocess with the new signals:** eager `.apply()` and unit tests only.
  The earlier subprocess logging test (`test_worker_logging.py`) still passes in the unit suite.
- **Load and volume behaviour** of the new access event (one line per request): not measured.

## 17. Deployment prerequisites

1. Rebuild and redeploy the `api`, `worker` and `beat` images. No migration and no new
   dependency. `infra/monitoring/` is plain bash.
2. **Before the worker starts:** do the import-backlog inventory (decision D-B, §18).
3. Install `jq` on the VPS, then cron `infra/monitoring/hrms_monitor.sh`. It runs in
   report-only mode until D1 picks a destination.
4. **Log-shape changes for anyone with saved queries:**
   - the gunicorn plaintext access line is gone; use `http_request` instead;
   - `exception_message` is removed from `unhandled_exception` and `celery_task_failed`;
   - Leave and attendance per-item events use `exception_type`/`error_category` instead of
     `error`;
   - the `onboarding_email_*_failed` events are replaced by `email.delivery.failed`.
5. **Client contract additions (backward-compatible):**
   - `503 DATABASE_BUSY` now also covers pool exhaustion, deadlock and serialization failure
     (previously 500);
   - web and mobile messages may append "(Reference: …)".

## 18. Outstanding decisions: backlog and refresh-token policy

**D-A, refresh-token reuse.** Strict replay detection is kept unchanged. Two tabs refreshing at
the same moment still revoke the session. A grace window is a product/security decision; it was
not added.

**D-B, historical import backlog.** 224 messages in local db0; the production count is unknown.

- **Implemented:** the atomic PENDING claim. It makes redelivered, duplicate and concurrent
  messages harmless.
- **Not decided:** whether an *old* batch that is still PENDING should run when the queue starts
  draining.

Read-only reconciliation procedure:

1. `LLEN reports_exports` on the broker.
2. As an admin role:
   `SELECT company_id, id, status, created_at FROM employee_import_batch WHERE status='PENDING' ORDER BY created_at;`
3. With each tenant's HR owner, decide which batches to keep. For batches that must not run, set
   `status='FAILED'` **before** deploying the worker: the guard then skips their messages
   (`employee_import.batch.skipped`, `reason=not_pending`). Deleting rows is no longer necessary.
4. Never `FLUSHDB` or `DEL` the queue.

## 19. Other approval-only decisions

| ID | Decision |
|---|---|
| D1 | Alert destination and on-call owner |
| D2 | Log retention periods (`LOGGING_AND_OBSERVABILITY.md` §7 lists the options) |
| D3 | Any third-party error tracker, uptime service or crash reporter (privacy and data residency) |
| D4 | Email outbox vs best-effort sending (unchanged) |
| D5 | Whether a complete job run is a precondition for payroll period close (`*_incomplete` events are alertable now) |
| New | Server-side idempotency for **face** punches. The form has no key, so a retried face punch after a timeout can still record twice; calculation-time duplicate collapsing is the existing backstop. This needs an API contract addition. |
| New | `acks_late` for the non-Leave idempotent tasks |

## 20. Remaining risks, ranked

1. **High: no one is notified yet.** The monitor exists, but D1 is open; until it is decided,
   failures are visible only to someone who looks.
2. **High: the import backlog.** Old PENDING batches will run when a worker drains production's
   queue (D-B). The guard prevents duplicates, not staleness.
3. **Medium: face-punch duplicates after a timeout.** No server-side key. The user is told the
   outcome is uncertain.
4. **Medium: log retention is size-based only (D2).** Security events may rotate away within
   hours under load.
5. **Medium: the new `http_request` volume is unmeasured.** It is one line per request, bounded
   by the 50 MB per-container cap.
6. **Low: unverified runtime behaviour.** Client boundaries and handlers were not run in a real
   browser or on a device.
7. **Low: `subject_hash` is pseudonymous, not anonymous.** It is derived from the JWT secret, so
   rotating that secret breaks correlation across the rotation.

## 21. Recommended next action

1. Deploy to **staging**.
2. Run `infra/monitoring/hrms_monitor.sh` there.
3. Fault-inject: stop Redis, stop the worker, stop MinIO, terminate a Postgres backend. Confirm
   each check fails and recovers.
4. In parallel, the owners decide **D1**, then **D-B**, before the production worker deploy.
