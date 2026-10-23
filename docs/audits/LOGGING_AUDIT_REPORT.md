# Logging Audit Report — Staff Spectrum HRMS / Krewoxa

**Date:** 2026-10-20  **Scope:** `apps/api` (FastAPI API, Celery worker, Celery Beat), deployment
files, existing logging tests.  **Method:** code inspection at `HEAD` (`b6a4eb8`) plus executed
tests; every finding names its file/function.

Evidence labels: **Verified** (code read *and/or* test executed), **Partial** (code exists,
persistence/execution not demonstrated), **Not verified** (environment unavailable), **Missing**.

> This report was written in two passes: Part 1 is the **baseline** found before any change;
> Part 2 records what was implemented and the test evidence. Earlier work
> (`LOGGING_ERROR_HANDLING_*` reports, `docs/operations/LOGGING_AND_OBSERVABILITY.md`) is real and
> was kept — this change is incremental.

---

# Part 1 — Baseline (before this change)

## A. Executive summary

* **Maturity: high for stdout/JSON, none for files.** The API, worker and Beat already shared one
  structlog JSON pipeline with redaction, request-ID correlation, exactly-once exception
  logging, post-commit business events, security events and Celery lifecycle events.
* **Logs were not persisted to local files — Verified.** No `FileHandler`/rotating handler exists
  anywhere at `HEAD` (`git grep FileHandler HEAD` → no hits). The only sink was stdout
  (`_ResilientStdout`, `core/observability/logging.py:29`), i.e. Docker's `json-file` driver
  (10 MiB × 5 per container, `docker-compose.prod.yml` `x-logging`). Re-creating a container lost
  its logs. Local development printed to the terminal only.
* **No per-module separation — Verified.** Everything was one interleaved stream. The `logger`
  name was not even emitted: `structlog.PrintLoggerFactory` ignores the name passed to
  `get_logger(__name__)`, and no `add_logger_name` processor was configured for native loggers.
* **Effective module logging was uneven.** Auth/security, HTTP, DB errors, Celery lifecycle and
  email were well covered. **Payroll, employee management and document handling had no logger at
  all** (`git grep get_logger HEAD -- modules/payroll modules/employee/service.py core/storage.py
  core/uploads.py` → none). Attendance had 2 log calls in a 6.7k-line `service.py`; leave had 4 in
  3.5k lines. Their business transitions were visible only through the post-commit
  `business.audit_recorded` line, and *failures/rejections of an operation were not logged* unless
  they ended as an HTTP 5xx.
* **Adequacy:** local development — inadequate (no files); staging/production — adequate for
  stdout shipping with a bounded Docker driver, inadequate for the requested local per-module
  files and for investigating attendance/leave/payroll problems by module.

## B. Current architecture (baseline)

| Aspect | Finding | Evidence |
|---|---|---|
| Initialisation | `configure_logging()` — API in `hrms/app.py:63`; worker/beat via Celery `setup_logging` signal → `_configure_worker_logging` (`core/celery_app.py:245`) with `configure_stdlib=True`. | Verified |
| Handlers | API: none (structlog → `PrintLogger(_STDOUT)`); worker/beat: one root `StreamHandler` named `hrms-json` that replaces existing root handlers (idempotent). | Verified |
| Names | `get_logger(__name__)` (e.g. `hrms.modules.leave.service`) plus fixed `hrms.http`, `hrms.business`, `hrms.security`. Not hierarchical `app.*`, and **not emitted** in output. | Verified |
| Level/format | `LOG_LEVEL` (default INFO) for API and worker; JSON Lines; UTC ISO-8601 timestamps. | Verified |
| Request IDs | `RequestContextMiddleware` (`core/observability/request_context.py`): validated `X-Request-Id`, bound to structlog contextvars, echoed on every response, one `http_request` line per request, outermost catch-all logs `unhandled_exception` once with traceback. | Verified (tests) |
| Exceptions | `core/errors/handlers.py` (`register_exception_handlers`, `log_unhandled_exception`): one traceback per failure; DB errors classified (`error_category`). | Verified (tests) |
| Workers | `task_prerun`/`task_postrun` bind `task_id`, `task_name`, `request_id`; `celery_task_finished|retry|failed|unknown|rejected`, fan-out incompleteness. | Verified (tests) |
| Redaction | `redact_event` last processor on every pipeline (names + value patterns, bounded length). | Verified (tests) |
| Persistence | **None** (stdout only). | Verified |
| Process model | gunicorn + `UvicornWorker`, `--workers 2` (`apps/api/Dockerfile` CMD); Celery prefork `--concurrency=2` (`docker-compose.prod.yml` worker); one Beat process. Multiple independent writers. | Verified |
| `print()` | Only in ops/CLI scripts (`ops/job_health.py`, `ops/import_backlog.py`, `face_cleanup.py`, `face_deletion.py`) that emit JSON reports — intentional. | Verified |
| Swallowed exceptions | The only bare swallow in `src` is `safe_log` (intentional: logging must not break callers). | Verified |

## C. Module audit matrix

Baseline status → status after this change (Part 2) in the last column.

| Module | Existing logging (baseline) | Important events covered | Missing coverage (baseline) | Sensitive-data risk | File persistence | Test evidence | Baseline → Now |
|---|---|---|---|---|---|---|---|
| API requests | `http_request`, `unhandled_exception`, `app_error`, `db_error` (`request_context.py`, `handlers.py`) | Every request, route template, status, duration, error code | — | Low (path templates, token segments masked) | None | `test_http_access_event`, `test_request_context_and_error_logging`, `test_unhandled_exception_logging` | PASS(stdout) → **PASS** |
| Auth / authorization | `security_event()` ~25 call sites (`identity/service.py`, `core/auth|rbac|tenancy/dependencies.py`, `shared/rate_limit.py`) | Login ok/fail, lockout, refresh reuse, 403, tenant rejection, rate limit | — | Low (`subject_hash` instead of e-mail) | None | `test_email_verification`, redaction tests | PASS(stdout) → **PASS** |
| Attendance | 2 calls in `attendance/service.py`; `face_service.py` provider/orphan errors; `tasks.py` job events | Scheduled-calc failures, face provider failures | Punch outcome/replay, regularization & overtime decisions, day calculation outcome/duration, period reopen — rejections never logged | Medium (biometrics) — handled: no frames/templates ever logged | None | `test_face_punch_idempotency`, `test_celery_*` | PARTIAL → **PASS** |
| Leave | 4 warnings in `leave/service.py` (accrual item failures), `leave/tasks.py` | Accrual/year-end item failures, dispatch failure | Submit/approve/reject/cancel outcomes, encashment, ledger adjustment, comp-off credit/expire | Low | None | `test_leave_task_hardening` | PARTIAL → **PASS** |
| Payroll | **None** (no logger in `modules/payroll`) | Only `business.audit_recorded` (post-commit) | Compute/lock/approve/finalise/mark-paid/rollback outcomes, validation rejections, payslip generation, adjustments | **High** (salary, bank, tax) — handled: IDs only | None | none | **FAIL → PASS** |
| Employee management | **None** in `employee/service.py`, `router.py`; `employee_import/service.py` has batch events | Import batch results; audit events | Create/update/terminate outcomes | High (PII) — IDs only | None | `test_employee_banking` (redaction) | FAIL → **PASS** |
| Recruitment / candidates | `onboarding/service.py` 2 calls | Invite e-mail failures | Case create/submit/activate outcomes. *No recruitment module exists*; candidate onboarding is the nearest feature | Medium | None | `test_onboarding_invite` | PARTIAL → **PASS** (scope noted) |
| Documents / storage | **None** (`core/storage.py`, `core/uploads.py`, `EmployeeDocumentService`) | Audit events only | Upload/delete/review outcomes, storage failures (surface as 5xx only) | High — no content, filenames or URLs logged | None | `test_storage`, `test_uploads` (behaviour only) | FAIL → **PASS** |
| Notifications / e-mail | `email.provider.accepted`, `email.delivery.failed` (`onboarding/email_sender.py`) | Delivery failures with class and retryability | — | Low (addresses redacted) | None | `test_email_failure_classification`, `test_email_sender` | PASS(stdout) → **PASS** |
| Background jobs | Celery lifecycle + failures (`core/celery_app.py`), health tasks | Start/finish/duration/retry/final failure, fan-out incomplete, dispatch failure | — | Low (args never logged) | None | 5 `test_celery_*`/`test_worker_logging` | PASS(stdout) → **PASS** |
| Database errors | Classified `db_*` events, readiness failures (`handlers.py`, `core/db/session.py`, `health/service.py`) | Deadlock, timeout, pool exhaustion, rollback failure | — | Low (`hide_parameters=True`) | None | `test_db_failure_classification`, `test_db_error_handler` | PASS(stdout) → **PASS** |
| Platform console | `platform/service.py` security events | Approval/enforcement | (module under active change by another author) | Low | None | platform integration tests | PARTIAL → **PASS** (routed to `platform.log`) |
| Face / liveness | `face_service.py`, `liveness.py`, `face_verification.py` | Provider errors, orphaned provider persons | — | High — verified no image/template fields logged | None | `test_face_verification`, `test_face_provider_client` | PASS(stdout) → **PASS** |

## D. Critical failure scenarios (baseline)

| Scenario | Logged at baseline? | Where |
|---|---|---|
| Unexpected exception | **Yes, once, with traceback** | `request_context.RequestContextMiddleware`, `log_unhandled_exception` |
| Validation / business rejection needing investigation | **No** (only `http_request.error_code`) | — fixed: operation lines with `outcome=rejected` |
| Authorization failure | Yes | `security.authorization.denied` |
| DB connection failure | Yes (503/500 with category) | `handlers.py` |
| Transaction rollback | Partly (`db_rollback_failed`); a rolled-back business transition is silently *not* logged by design | `business_events.py` |
| Queue submission failure | Yes | `celery_task_dispatch_failed`, `leave_task_dispatch_failed` |
| Task failure / retry | Yes | `celery_task_failed|retry` |
| Provider timeout / error | Yes (email, Face++) | `email.delivery.failed`, `face_provider_request_failed` |
| Duplicate / conflicting operation | No (409 only in `http_request`) | — fixed: 409 ⇒ WARNING operation line; punch `replayed` flag |
| Scheduled job failure | Yes (attendance, leave); payroll has no scheduled jobs | — |
| File upload / storage failure | **No** (only generic 500) | — fixed: `documents.*` operation `outcome=failed` |
| Unexpected state transition | Business transitions only after commit | `business.audit_recorded` |

**Severity rule adopted** (and documented in the guide): expected 4xx → INFO; 403/409 → WARNING;
retries/degraded dependencies → WARNING; unexpected/5xx/final task failure → ERROR.

## E. Implementation and deployment risks (baseline)

| Risk | Finding |
|---|---|
| Logs vanish on container re-creation | **Real** — stdout/`json-file` only. |
| Multiple writers to one file | Would be **unsafe with stock `RotatingFileHandler`** (gunicorn ×2, Celery prefork ×2, Beat). A file layer needs cross-process locking. |
| Missing directory / permissions | N/A at baseline. Image runs as uid 1000 `hrms` with a root-owned `/app`; a log directory must be created and owned explicitly. |
| Duplicate handlers | Safe at baseline (named root handler replaced on repeat; tested). |
| Disk growth | Bounded only by Docker driver. |
| Lost exceptions | None found; one intentional swallow (`safe_log`). |
| Sensitive data | Redaction pipeline strong; payroll/document code had no logging to leak, but any new logging there needed the same discipline. |
| Request IDs / timestamps | Consistent (UTC ISO-8601; request ID on all paths). |
| Logging failure affecting availability | Handled for stdout (`_ResilientStdout`). |

---

# Part 2 — Implementation and results

## F. What was implemented

| Change | File(s) |
|---|---|
| **File sink**: per-channel append files, size rotation, numbered backups, optional age-based pruning of rotated backups, `flock`-based multi-process safety, per-PID descriptors after `fork`, drop-and-count failure handling with in-band recovery notice, startup directory creation + write probe, `LOG_FILES_REQUIRED` fail-fast | `core/observability/file_sink.py` (new) |
| **Router**: event name → entity type → logger prefix → task context → failing-request route; `app.log` all events; `errors.log` ERROR+ with the only traceback copy | same |
| Pipeline integration: `logger` name now emitted for native structlog loggers; last processor renders once, feeds the sink, returns the line for stdout (stdout contract unchanged apart from the added `logger` field); same code path for API, worker and Beat | `core/observability/logging.py` |
| **Operation logging** `@logged_operation` — outcome (`succeeded/rejected/failed`), duration, allow-listed UUID arguments only, no traceback, re-raises unchanged | `core/observability/operations.py` (new) |
| Applied to 42 service methods: payroll (10), leave (10), attendance incl. face punch (11), employee (6), onboarding (5) | `modules/*/service.py`, `attendance/face_service.py` |
| Settings `LOG_TO_FILES, LOG_DIR, LOG_FILE_MAX_BYTES, LOG_FILE_BACKUP_COUNT, LOG_RETENTION_DAYS, LOG_FILES_REQUIRED` | `core/config/settings.py`, `.env.example`, `env/.env.*.example` |
| Persistence in Docker: `/app/logs` owned by `hrms`, `LOG_DIR=/app/logs`, named volume `api_logs` shared by api/worker/beat | `apps/api/Dockerfile`, `docker-compose.prod.yml` |
| Test isolation: file logging forced off for the suite (opt-in via `HRMS_TEST_LOG_TO_FILES`) | `tests/conftest.py` |
| Tests | `tests/unit/core/test_file_logging.py` (new, 20 tests) |
| Documentation | `docs/operations/LOGGING_GUIDE.md` (new), this report |

**Design notes.** Logger names stay `hrms.*` (existing convention, referenced by tests and
docs) rather than being renamed to `app.*`; the mapping to the requested file set is the explicit
routing table. No new dependency: stdlib + `fcntl`. No external telemetry. Business logic is
untouched — decorators only wrap methods.

**Deliberate choices / trade-offs.** (1) Operation `succeeded` means the service method returned;
commit is confirmed by `business.audit_recorded`. (2) Failed operations log no traceback (the
middleware/Celery log it once) — so a stack trace exists once in `errors.log`. (3) `fcntl` file
locking: local POSIX filesystems only. (4) Retention applies to rotated backups; size/count is the
hard bound.

## G. Test evidence

See the "Verification results" section at the end of this report (filled from actual runs).

## H. Verification results (actually executed 2026-10-20)

| Check | Command (from `apps/api`) | Result |
|---|---|---|
| New logging tests | `pytest tests/unit/core/test_file_logging.py` | 20 passed (routing, no-duplicates, tracebacks, redaction, request-ID, rotation/retention, 6-process concurrency, unwritable dir, runtime write failure, worker subprocess, isolation) |
| Whole unit suite | `pytest tests/unit` | 1214 passed |
| Integration (core, auth, security, payroll, employee, onboarding, leave, attendance) with file logging **on** into a throwaway dir | `HRMS_TEST_LOG_TO_FILES=true LOG_DIR=<tmp> pytest …` | 1342 passed, 1 failed: `test_credential_rate_limit::test_repeated_attempts_against_same_email_are_rate_limited`. It passes alone (10/10) and in the whole `tests/integration/auth` dir with file logging on (60/60); the failing run overlapped a unit-test run sharing the same Redis rate-limit keys, so it is treated as a test-concurrency artefact, not a logging defect. Not otherwise proven. |
| Lint / format / types | `ruff check src tests`, `ruff format --check`, `mypy` on changed modules | clean (mypy: 17 files, no issues) |
| Import contract | `lint-imports` | 1 kept, 0 broken |

**Real-traffic evidence** (that integration run's log directory, 38 MB): all 13 files created;
`attendance.log` held `attendance.day.calculate`, `attendance.punch.record`,
`attendance.face.punch` (succeeded/rejected); `leave.log` the `leave.application.*` and ledger
operations; `payroll.log` the pay-run lifecycle; documents, employees and recruitment
likewise; `app.log` rotated to `app.log.1` at the size limit; no traceback in `app.log`, tracebacks
only in `errors.log`.

**Not verified:** Docker image build and the `api_logs` volume (compose YAML parsed, not run —
no deployment was touched); systemd; behaviour on NFS (unsupported by design); Celery *Beat* as a
separate process (worker bootstrap verified in a subprocess; Beat uses the same signal).
The full 2.5 k-test suite was not run to completion in one pass (the first attempt was stopped for
time); the modules listed above, which contain every decorated service, were.

## I. Final verdict

**Complete and verified:** local per-module file persistence, routing, rotation/retention,
multi-process safety, failure fallbacks, redaction, one-traceback rule, operation logging for
attendance / leave / payroll / employees / onboarding / documents, test isolation, documentation.
**Incomplete / open:** (1) Docker volume and systemd paths unverified end-to-end;
(2) no log backup, central search or tamper protection — a deployment decision (retention period
D2); (3) `recruitment.log` is candidate onboarding only — no recruitment module exists;
(4) rejected-vs-committed: `succeeded` is service-return, commit is `business.audit_recorded`;
(5) operations not decorated (e.g. organisation master data, platform console) rely on
`business.audit_recorded` and HTTP events only; (6) mobile/web client logging out of scope.
