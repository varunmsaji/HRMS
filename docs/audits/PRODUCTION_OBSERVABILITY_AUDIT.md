# Production observability audit

Date: 2026-10-25. Scope: the whole Krewoxa HRMS stack as it exists in this repository (API, Celery worker/beat, PostgreSQL, Redis, MinIO, Nginx, Docker Compose, CI). Method: read the code and configuration, run the existing tests, then run the real processes locally (gunicorn x2 workers + Celery worker, shared metrics directory, local Postgres, an *empty, isolated* Redis DB) and observe. **The production VPS was not inspected or contacted.**

Statuses: **VERIFIED** (observed working), **PARTIAL**, **MISSING**, **BROKEN**, **NOT TESTED**, **BLOCKED** (needs a decision or access).
"Before" = repository state at the start of this audit; "After" = state with the changes of this work (uncommitted, as instructed).

Related: [architecture](../architecture/OBSERVABILITY_ARCHITECTURE.md) - [runbook](../operations/OBSERVABILITY_RUNBOOK.md) - [alerts](../operations/OBSERVABILITY_ALERT_CATALOG.md) - [dashboards](../operations/OBSERVABILITY_DASHBOARD_CATALOG.md) - [verification report](OBSERVABILITY_VERIFICATION_REPORT.md) - earlier logging work: [LOGGING_AUDIT_REPORT](LOGGING_AUDIT_REPORT.md), [LOGGING_ERROR_HANDLING_REMEDIATION_REPORT](LOGGING_ERROR_HANDLING_REMEDIATION_REPORT.md).

## 1. Baseline architecture (evidence)

| Element | What exists | Where |
|---|---|---|
| App init | `create_app()`, lifespan boots engine, checks active encryption key outside development, loads liveness model if enabled; docs/OpenAPI off outside development | `apps/api/src/hrms/app.py` |
| Middleware (outer -> inner) | `RequestContextMiddleware` (request id, access event, last-resort 500 envelope) -> Proxy headers -> security headers -> tenancy -> upload limits -> rate-limit -> CORS | `app.py`, `core/observability/request_context.py` |
| Error contract | `AppError` hierarchy with stable `code`; handlers for validation, DB (pool timeout 503, deadlock/serialization 503 retryable, unique 409), HTTP, unhandled | `core/errors/handlers.py`, `docs/api/ERROR_CODES.md` |
| Logging | structlog JSON to stdout; second sink to per-module files with `flock`-guarded size rotation; redaction processor; `LOG_*` settings; Celery `setup_logging` hook gives worker/beat the same JSON contract | `core/observability/{logging,file_sink,redaction}.py`, `core/celery_app.py` |
| Operation / business / security events | `@logged_operation` (outcome succeeded/rejected/failed + duration), `emit_after_commit` (post-commit only), `security_event` (`security.*`) | `core/observability/{operations,business_events,security_events}.py` |
| Server | gunicorn + `UvicornWorker`, 2 workers, timeout 60 s, graceful 30 s, non-root uid 1000 | `apps/api/Dockerfile` |
| DB | SQLAlchemy 2 async/asyncpg, default pool (5 + 10 overflow, 30 s timeout), `pool_pre_ping`, `hide_parameters=True`; RLS role `hrms_app` | `core/db/session.py` |
| Redis | one instance: rate limiter, idempotency, Celery broker/result (separate DB selectable), AOF on | `docker-compose.prod.yml`, `shared/rate_limit.py` |
| Celery | queues `default`, `reports_exports`; 10 Beat entries; JSON serializer; request id + enqueue time propagated in headers; per-task lifecycle/retry/failure/unknown events; `health.scheduler_heartbeat` every 60 s | `core/celery_app.py`, `modules/health/tasks.py` |
| Background health | read-only `python -m hrms.ops.job_health` (heartbeat age, depth, oldest age) | `ops/job_health.py` |
| Providers | e-mail (`logging`/smtp/mailtrap/hostinger), Face++ (adapter, pooled httpx), MinIO | `modules/onboarding/email_sender.py`, `modules/attendance/face_verification.py`, `core/storage.py` |
| Containers | postgres16, redis7, minio(silo), api, worker, beat, migrate(profile), web, nginx; json-file logs capped 10 MB x 5; healthchecks: api `/health/live`, worker `inspect ping`, beat none | `docker-compose.prod.yml` |
| Edge | Nginx request id header to API; `/health/ready` proxied | `infra/nginx/` |
| Host monitor | cron `hrms_monitor.sh`: readiness, job health, unhealthy/restarting containers, disk, log-grep for 5xx/exceptions/failures, backup freshness; optional `HRMS_ALERT_COMMAND`; tested against a fake docker | `infra/monitoring/hrms_monitor.sh`, `docs/operations/ALERTS_AND_RUNBOOKS.md` |
| CI | `.github/workflows/ci.yml`: ruff, mypy, import-linter, unit then integration+security against Postgres/Redis/MinIO | `.github/workflows/ci.yml` |
| Not present | Prometheus/metrics, tracing, Grafana, alert rules as code, `systemd` units (Docker only), any paid APM | - |

Environment matrix:

| Context | Logging | Metrics | Evidence |
|---|---|---|---|
| Automated tests | file logging forced off (`conftest.py`), stdout JSON captured | single-process default registry | 1 700+ tests, see verification report |
| Local API (gunicorn x2) | stdout + files | multiprocess dir | run in section 7 of the verification report |
| Local Celery worker | JSON + files, task context | same dir, separate process | same run |
| Celery Beat | **not run** (see below) | not run | `NOT TESTED` locally: Beat would fire real scheduled tasks against the dev database; its signal handlers are the same code the worker exercised, and `health.scheduler_heartbeat` was published by a separate publisher process |
| Docker containers / VPS | compose analysed, **not run** | compose analysed | `NOT TESTED` |

## 2. Findings

Severity: C critical, H high, M medium, L low. "After" status reflects this work.

| ID | Sev | Finding | Evidence (files / tests) | Before | After |
|---|---|---|---|---|---|
| OBS-01 | H | No metrics of any kind: no request rate/latency/error rate, no queue or task metrics, nothing for a scraper | `grep -ri prometheus` found nothing; only log-grep in `hrms_monitor.sh` | MISSING | **VERIFIED locally** - `core/observability/metrics.py`; `tests/unit/core/test_metrics*.py`; live scrape in verification report |
| OBS-02 | H | `/metrics` would be a new exposure | n/a (new) | n/a | **VERIFIED**: 404 w/o token, 401 wrong token, hidden from OpenAPI, Nginx 404, test `test_metrics_endpoint_*`, `test_nginx_never_proxies_metrics...` |
| OBS-03 | H | No trace correlation: request id reached Celery but there was no id spanning edge->API->task, and none for scheduled tasks | `celery_app.py::_propagate_request_id` only | PARTIAL | **VERIFIED** (correlation only): `trace_context.py`; cross-process observed; `test_trace_correlation.py` |
| OBS-04 | H | Alerts only as shell log-grep on Docker logs; no alert rules as code, no routing, no tests of firing logic | `hrms_monitor.sh`; no rules | PARTIAL | rules **VERIFIED by promtool unit tests**; delivery **BLOCKED** (decision D1) |
| OBS-05 | H | Domain failures indistinguishable from policy rejections in aggregate | logs had `outcome` but no aggregate | PARTIAL | **VERIFIED**: `hrms_operations_total{outcome}`; test proves `rejected` does not increment `hrms_errors_total`; alert test proves attendance rejections do not fire |
| OBS-06 | H | Scheduled-job misses not detectable except via the heartbeat; no per-task "last success" | `job_health.py` covers heartbeat only | PARTIAL | **VERIFIED**: `hrms_celery_task_last_success_timestamp_seconds`, publish/start/finish/fail/retry counters; alert `Hrms*Missed` tested |
| OBS-07 | M | Database pool/latency/rollbacks invisible; pool exhaustion visible only as a 503 log line | `session.py` | PARTIAL | **VERIFIED** (`tests/integration/core/test_db_metrics.py`); pool gauge is per-serving-worker (documented limit) |
| OBS-08 | M | No lock-wait / deadlock / long-transaction / slow-query visibility at the server; no `pg_stat_statements`, `log_min_duration_statement=-1`, `log_lock_waits=off`, `statement_timeout=0`, `idle_in_transaction_session_timeout=0` (dev container; prod uses stock `postgres:16-alpine` per compose) | read-only `pg_settings` query on the dev container | MISSING | **BLOCKED** - needs approval to change DB settings (architecture doc section 8) |
| OBS-09 | M | Redis memory/clients/evictions not exported; no queue-age series | - | MISSING | **VERIFIED** locally (`hrms_redis_*`, queue depth/age at scrape time) |
| OBS-10 | M | Payroll has **no background processing**: compute/finalise/payslip run inside API requests (60 s gunicorn limit); `modules/payroll` has no `tasks.py`, no Beat entry | `modules/payroll/`, `celery_app.py` | (capacity risk, undocumented) | documented; monitored as `payroll.*` operations + duration; **capacity risk remains** - a large company's compute approaching 60 s would be killed |
| OBS-11 | M | Beat has no healthcheck (disabled) and one worker serves both queues; a long per-company task can delay everything | `docker-compose.prod.yml` | PARTIAL | heartbeat + `HrmsSchedulerHeartbeatStale` + queue-age alerts compensate; queue isolation is a design change, not done |
| OBS-12 | M | External-provider health only in logs; no denominators, no latency | - | PARTIAL | **VERIFIED**: `hrms_dependency_{calls,errors,call_duration}`; Face++ and e-mail covered; storage (object-store) calls now instrumented as `dependency="storage"` in `core/storage.py` (2026-10-25, unit-tested with mocked errors; **not exercised against a live MinIO**); a missing object is counted as success, not an outage |
| OBS-13 | M | Default file-log retention (10 MB x 6 per channel) is ~1.3 days of `api.log` at 1 000 employees | arithmetic in architecture doc 10.1 | undocumented | documented with scenarios; tunable by env; central retention decision D4 open |
| OBS-14 | M | No CPU/RAM/host metrics | - | MISSING | optional `node_exporter` prepared; **not deployed** |
| OBS-15 | M | Lost-log signal existed only in-band; not alertable | `_ResilientStdout`, `RotatingLineFile` | PARTIAL | **VERIFIED**: `hrms_log_dropped_writes_total{source}` + `HrmsLogWritesFailing` |
| OBS-16 | L | `poll`-style mobile traffic would inflate access-log volume | n/a | NOT TESTED | no change |
| OBS-17 | L | Face++/e-mail payloads, secrets, JWTs, salaries, document bytes: not logged | `redaction.py`, `test_log_redaction.py`, `test_unhandled_exception_logging.py`, provider tests assert keys absent from logs; new test asserts absent from metrics | VERIFIED | VERIFIED (extended to metrics) |
| OBS-18 | L | Observability not exercised in CI beyond unit/integration tests | `ci.yml` | PARTIAL | new unit tests run in the existing unit step: label allow-list, config consistency (rules/dashboards reference only exported series, runbook anchors, catalog completeness, nginx/compose invariants). `promtool` is **not** in CI (needs docker image; see report) |
| OBS-19 | L | Verified at start: tests rely on shared dev Redis DB 0 for rate-limit key cleanup and DB 15 for Celery (isolated by conftest) | `tests/conftest.py` | VERIFIED | unchanged; this work used Redis DB 12 (empty when checked; DB 14 held a backlog and was left untouched) |
| OBS-20 | L | Local dev machine: `/tmp` filesystem is 98.5% full (observed via the new `hrms_log_filesystem_free_ratio`), not a repository issue | runtime scrape | n/a | informational |

No finding is rated Critical: nothing observed could cause data loss or a security failure on its own. The highest operational risks are OBS-04/OBS-06 (nobody is told when a scheduled job stops) and OBS-10 (payroll runs synchronously).

## 3. Maturity assessment

Scale (evidence-based, not a vanity number): 0 absent, 1 ad-hoc, 2 partial / works but unmonitored, 3 solid and verified locally, 4 verified in staging, 5 verified in production. Nothing can exceed 3 without a staging/production environment, which this audit did not have.

| Area | Current implementation | Evidence of behaviour | Missing / remaining | Sev | Solution | Cplx | Overhead | Tests | Before | After | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Application logging | JSON, redaction, module files, flock rotation, drop notices | 40+ existing tests (`test_file_logging`, `test_log_redaction`, `test_resilient_log_sink`, `test_worker_logging`); runtime: all channels written by 4 processes | central search (D4) | L | keep | - | none | existing + `test_metrics` log-count | 3 | 3 | VERIFIED |
| API observability | access event, request id, route templates | `test_http_access_event`, runtime scrape | in-flight gauge (omitted by design) | L | `hrms_http_*` | S | ~2-4 us/request | `test_metrics.py` | 2 | 3 | VERIFIED |
| Error monitoring | stable codes, categories, one traceback per failure | `test_db_failure_classification`, `test_unhandled_exception_logging` | no error aggregation product (by choice) | L | `hrms_errors_total`, `HrmsUnhandledExceptions` | S | negl. | `test_metrics` | 3 | 3 | VERIFIED |
| Distributed tracing | request id only | cross-process trace id observed | no spans/backend | M | correlation done; OTel design written, disabled | S / L | none / 300 MB+ if enabled | `test_trace_correlation.py` | 1 | 2 | PARTIAL (by design) |
| Database | pool_pre_ping, categories | `test_db_metrics.py` on real Postgres | server-side slow/lock/deadlock visibility | M | listeners done; settings need approval | S / S | negl. | integration | 1 | 2 | PARTIAL / BLOCKED (D5) |
| Redis | readiness ping | scrape against real Redis | latency per command, queue memory attribution | L | `hrms_redis_*` | S | 1 `INFO`/10 s | `test_unreachable_dependencies...` | 1 | 3 | VERIFIED |
| Celery | lifecycle logs, heartbeat, job_health CLI | live worker: started/finished/duration/queue-wait/unknown-task counters | per-worker liveness series; Beat not run locally | M | signals -> metrics | S | negl. | `test_celery_metrics.py` | 2 | 3 | VERIFIED (Beat NOT TESTED) |
| Attendance | `attendance.*` operation events, face security events | unit tests + alert unit tests | punch latency SLO unknown (no baseline) | M | `hrms_operations_*`, face provider series | S | negl. | alert test | 2 | 3 | VERIFIED |
| Leave | operation events, accrual per-company events | same | reconciliation inconsistencies not metered | M | operations + last-success | S | negl. | alert test | 2 | 3 | PARTIAL (no balance-reconciliation metric) |
| Payroll | operation events, no tasks | code read | synchronous 60 s ceiling; no background path | M | `payroll.*` operations + duration; alert | S | negl. | alert test | 2 | 3 | PARTIAL |
| Authentication | `security.*` events, rate-limit event once/window | runtime: 3 failed logins -> `login.failed` counter, 401 denials | none significant | L | `hrms_security_events_total` | S | negl. | `test_metrics.py` | 3 | 3 | VERIFIED |
| External services | e-mail failure classification; Face++ failure logs | provider tests (MockTransport) | storage instrumented, not run against live MinIO | M | `hrms_dependency_*` | S | negl. | `test_face_provider_client.py` | 2 | 3 | PARTIAL (storage unit-tested only) |
| Infrastructure | docker healthchecks, host cron monitor | monitor tested against fake docker | host CPU/RAM; real VPS not inspected | M | optional node_exporter | S | ~20 MB | `test_optional_monitoring...` | 2 | 2 | PARTIAL / NOT TESTED on VPS |
| Alerting | cron script; rules as code now | `promtool check/test rules` | **no destination, no owner, delivery untested** | H | Alertmanager after D1 | M | ~30 MB | promtool | 1 | 2 | BLOCKED |
| Dashboards | none | 44 queries parse | never rendered on live data | M | JSON ready | S | 100-200 MB if Grafana | config tests | 0 | 2 | NOT TESTED (live) |
| Security / privacy | redaction, RLS, tenant-verified log fields | tests + metrics exposition scan | log-viewer access reviews are procedural | L | token-gated `/metrics`, label allow-list | S | none | `test_metrics.py` | 3 | 3 | VERIFIED |
| Retention | rotation + Docker caps | `test_file_logging` rotation tests | long-term retention decision (D4); defaults short at scale | M | documented scenarios | - | - | - | 2 | 2 | PARTIAL |
| Incident response | `ALERTS_AND_RUNBOOKS.md` for the cron monitor | - | per-failure runbooks | M | `OBSERVABILITY_RUNBOOK.md` (15 procedures) | S | none | config test checks anchors | 2 | 3 | PARTIAL (procedures not rehearsed on a real incident) |

**Overall maturity: about 2.7 / 5 (after) versus 2.0 / 5 (before)** - an unweighted mean of the table above. It deliberately stops short of 3+ because alert delivery, dashboards on live data, Beat, the Docker/VPS deployment and production behaviour are all unproven.

## 4. Risk assessment (top items)

1. **Nobody is notified** when a scheduled accrual/attendance job stops or the API fails (OBS-04, BLOCKED on D1). The detection logic now exists and is tested; the last mile is a human decision.
2. **Payroll compute runs inside a request** (OBS-10). Observable now (duration + failures), not fixed.
3. **Blind spots at the database** (OBS-08): lock waits, deadlocks and slow statements are invisible server-side until D5.
4. **Short default log retention at scale** (OBS-13).
5. **Unproven deployment path**: the compose/Dockerfile/Nginx edits were validated structurally and by YAML tests, but no image was built and no container started in this work.

## 5. What was changed

See the [verification report](OBSERVABILITY_VERIFICATION_REPORT.md) section 2 for the file-by-file list.

## 6. Second pass - independent re-audit (2026-10-25)

Scope: verify the section 2 claims independently rather than trust them, close the open items from the verification report (two integration failures, leave reconciliation, promtool, dashboards on live data), and fix what was found. Method: re-ran `promtool`, evaluated every dashboard and alert expression against a live Prometheus scraping a real two-worker gunicorn API (throwaway containers and a disposable database), read the middleware, redaction, storage and scrape code against its own documentation, and re-ran the test suites. The production VPS was **not** inspected. Nothing was committed, pushed or deployed; no alert recipient was contacted.

Status vocabulary for this section: PASS / FAIL / BLOCKED / NOT RUN / INSUFFICIENT EVIDENCE.

### 6.1 Findings

| ID | Sev | Finding | Evidence | Action | Status |
|---|---|---|---|---|---|
| OBS2-01 | P1 | **Race in error precedence (the "concurrency" integration failure).** `create_{assignment,compensation,statutory,bank}` rejected the *date* (`INVALID_EFFECTIVE_FROM`, 422) before checking the caller's `If-Match` version. A concurrent loser re-reads the winner's committed row and gets a misleading 422 instead of 409 `STALE_RESOURCE`. Not flaky: 7 of 12 consecutive runs of `test_concurrent_revisions_with_the_same_version_have_exactly_one_winner` failed (bank, compensation, statutory) | `modules/employee/service.py` (4 sites); reproduced on a fresh disposable DB | Stale `If-Match` is now checked first, raising the same `StaleResourceError` with the same body. **25/25 consecutive runs pass** after the change; full runner integration run no longer lists it | FIXED, PASS |
| OBS2-02 | P2 | **`leave_ledger` grant failure is a test-environment ordering bug, not an application defect.** `002_app_role.sh`'s blanket `GRANT ... ON ALL TABLES` re-applied to an already-migrated database overrides the migrations' `REVOKE` (`hrms_app` on `leave_ledger`: `INSERT,SELECT` -> `DELETE,INSERT,SELECT,UPDATE`; test then fails). A fresh database passes. `hrms_test` no longer exists, so the exact precondition of the earlier failure is INSUFFICIENT EVIDENCE, but the mechanism is reproduced | `infra/docker/postgres/init/002_app_role.sh`; `run_full_tests.py` | The runner now always drops and recreates its test DB (guarded by its existing name checks). The test passed in the full runner run. The residual *production* risk (an operator re-running the script) has no detector: decision D11, runbook procedure added | FIXED (runner); OPEN (D11) |
| OBS2-03 | P2 | **Object-store "full" was indistinguishable from any provider error.** Observed live: dev root disk 100% -> MinIO `XMinioStorageFull` -> every upload 500 (38 integration tests failed for this single cause) | `core/storage.py` | New bounded categories from the S3 error *code* only: `storage_full`, `storage_auth`, `storage_config`, `provider_error`; `NoSuchKey` still counts as success. New critical alert `HrmsObjectStorageRejectingCalls` (promtool-tested) | FIXED, PASS (unit + promtool); NOT RUN against production |
| OBS2-04 | P2 | **Log redaction was name-based with a narrow list.** Probe showed raw values for phone/mobile, date of birth, UAN/passport, net/gross pay and `*_minor` amounts, and `image/photo/selfie/frames/base64` fields (a base64 string is not `bytes`, so it bypassed the bytes mask up to 2 000 chars). No current log call passes such a field, so this is defence in depth, not an active leak | `core/observability/redaction.py` | Added field names and an Indian-mobile value pattern (digit-run lookarounds keep ids/epochs intact); 29 new parametrized regression cases incl. false-positive guards | FIXED, PASS |
| OBS2-05 | P3 | **`/metrics` documentation contradicted the code**: docs said rejected scrapes are counted and not logged; code skipped `/metrics` in metrics entirely and *did* log every 401 | `request_context.py`, `metrics_router.py` | A rejected scrape is now counted (`hrms_http_denials_total`) and logged like any request; successful scrapes stay unmeasured. Docs corrected; test added | FIXED, PASS |
| OBS2-06 | P2 | **Dashboards read "No data" while healthy.** Counters have no series until first increment, so error/failure panels were empty on a healthy system, indistinguishable from broken telemetry | live Prometheus evaluation (27 of 44 queries empty in a trafficless run) | Failure-counting panels now `noValue: "0"`; live-value panels keep "No data" on purpose (`zero_when_empty` in the generator) | FIXED; rendering in Grafana NOT RUN |
| OBS2-07 | info | **Leave balance reconciliation does not exist and is not structurally needed.** Balance is `SUM(leave_ledger.amount)` (no mutable balance column), so there is no second copy to drift. Nothing in `modules/leave` reconciles applications against ledger deductions | `modules/leave/models.py`, `repository.py` | No metric invented. If wanted, it is a *new business rule* (approved application <-> ledger deduction consistency): decision D9 | DECISION REQUIRED |
| OBS2-08 | info | **Payroll 60 s ceiling: engine CPU is not the risk.** `compute_employee` measured at 13 us per employee (simple 3-component salary) -> 20 000 employees = 0.25 s. Any 60 s problem would come from per-employee database work, **not measured**. Duplicate runs are blocked by `pay_run_entity_month_uq`; transitions are version-checked | benchmark in this pass; `payroll/models.py` | None. A staging load test at realistic headcount decides sync vs background job: D10 | INSUFFICIENT EVIDENCE (DB cost) |
| OBS2-09 | info | **The whole integration suite fails on a full disk, loudly but misleadingly.** 38 failures = one cause. Re-run against a disposable MinIO with free space: 157 + 37 + 6 targeted tests, 0 failures | section 6.3 | Documented in runbook section 11 and architecture section 14 | PASS (cause proven) |
| OBS2-10 | P3 | **Static-check stage of `run_full_tests.py` always FAILs here** (0.1 s): `uv run ruff/mypy/lint-imports` resolve to a conda Python 3.9 because the project `.venv/bin/*` scripts carry a stale shebang from a previous mount path (`/media/varun/varun11/...`). The runner already works around this for `pytest`/`alembic` (calls the venv interpreter) but not for the static tools | `run_full_tests.py::stage_static_checks` | Not changed (tooling decision). Direct runs below. Fix: `uv sync --reinstall` or call tools through `.venv/bin/python -m` | OPEN |

Verified as already correct (no change): request-id validation (anchored `fullmatch`, 64 chars, safe alphabet; bad values replaced, never rejected); `traceparent` parsed strictly and ignored when malformed; `/metrics` constant-time bearer compare, 404 when disabled, 404 at Nginx; scrape probes are read-only (`LINDEX`, `LLEN`, `GET` - monitoring cannot consume or alter a queue); liveness checks no dependency, readiness returns 503 with ok/error per dependency and no detail; route label collapses unknown URLs to `unmatched` (9 random 404 paths -> 1 series, no UUID or request string in 183 exposition lines, 129 series idle); metrics recording swallows its own failures.

### 6.2 Component status (re-audit)

| Component | Status | Evidence / limit |
|---|---|---|
| Structured logging + redaction | PASS | 88 redaction tests; probe re-run; extended in OBS2-04 |
| Request/trace correlation | PASS (correlation only) | code read + existing tests; no tracing backend by design |
| Metrics correctness / cardinality | PASS | live exposition scan; allow-list test; storage misclassification fixed |
| Alert rules syntax and behaviour | PASS | `promtool check rules` 36 rules exit 0; `promtool test rules` exit 0 |
| Alert rules on live data | PASS (evaluation) | 36/36 `health=ok`; no false firing; disk alerts went `pending` on a genuinely full disk |
| Alert **delivery** | BLOCKED | no destination or owner (D1) |
| Dashboards: JSON + PromQL | PASS | 4 files valid, 40 panels, 44 queries parse |
| Dashboards: live data | PARTIAL | 44/44 evaluate without error; 17 returned data, 27 empty only because no worker/node_exporter/traffic existed; Grafana rendering NOT RUN |
| Celery workers / Beat | NOT RUN in this pass | covered by the first pass for the worker; Beat never run (would fire real tasks) |
| PostgreSQL server-side visibility | BLOCKED | `pg_stat_statements`, slow-query and lock-wait settings need approval (D5) |
| Host / containers / VPS | NOT RUN | VPS not inspected; `node_exporter` not deployed |
| Docker image / compose path | NOT RUN | no image built, no compose stack started |
| SLOs | PROPOSED, not adopted | SLIs defined, no targets (architecture section 13, D8) |

### 6.3 Tests run in this pass (exact)

| Command (cwd `apps/api` unless noted) | Result |
|---|---|
| `docker run ... promtool check rules /p/alerts.yml` | exit 0, 36 rules |
| `docker run ... promtool test rules /p/alerts.test.yml` | exit 0 (8 scenarios; 1 new) |
| `promtool check rules` over all 44 dashboard expressions (variables substituted) | exit 0 |
| ephemeral Prometheus + 2-worker gunicorn, 44 dashboard queries + 36 rules evaluated | 0 query errors, 0 rule errors |
| `pytest tests/integration -k test_concurrent_revisions` x12 before fix | 7 runs failed |
| same x25 after fix | 0 runs failed |
| `pytest tests/unit/core` | 325 passed |
| `pytest tests/unit` (with the `liveness` extra restored) | **1354 passed, exit 0** |
| `python3 run_full_tests.py --backend` (root; isolated `hrms_test`, Redis /1) | unit 1354 tests / 3 failures (all from the missing `liveness` extra, see below); integration+security **1826 tests / 38 failures**, all 38 traced to one cause (full disk); neither the concurrency test nor `test_runtime_role_cannot_rewrite_or_erase_leave_history` is among them |
| the 38 failing tests + all storage/onboarding/import files, against a disposable MinIO with free space | 157 passed + 37 passed + 6 x1 passed, **0 failed** |
| `ruff format --check src tests` | exit 0 (523 files) |
| `.venv/bin/python -m ruff check src tests` | exit 1: **1** pre-existing E501 in `modules/attendance/opensource_face/store.py:4` (not part of this work) |
| `.venv/bin/python -m mypy src/hrms` | exit 1: **1** pre-existing error `seed/bootstrap.py:135` |
| import-linter via `importlinter.cli` | exit 0, 1 contract kept |

Environmental limits, stated plainly: the dev machine's root filesystem was 100% full (5 GB free of 560 GB), which made the shared dev MinIO refuse writes; I did not free space on it. The full integration suite was **not** re-run end to end against a healthy store - the failing subset was. A side effect of mine: an early `uv sync --all-groups` removed the optional `liveness` extra (`opencv-python-headless`, `numpy`), which produced the 3 unit failures in the runner; restored with `uv sync --all-groups --all-extras` and the unit suite re-run green.

### 6.4 Files changed in this pass

`modules/employee/service.py` (stale-token precedence, 4 sites); `core/storage.py`; `core/observability/{redaction,request_context,metrics_router}.py`; tests `unit/core/{test_storage_metrics,test_log_redaction,test_metrics}.py`; `infra/monitoring/prometheus/{alerts.yml,alerts.test.yml}`; `infra/monitoring/grafana/{generate_dashboards.py,dashboards/*.json}`; `run_full_tests.py`; docs: this audit, verification report, architecture (sections 5.3, 9, 11, 13, 14), alert catalog, dashboard catalog, runbook (sections 9, 11).

Rollback: every change is an isolated, uncommitted edit. The employee-service change is four self-contained `if` blocks that can be deleted to restore the previous precedence (the concurrency test would then fail again, intermittently). The alert and dashboard changes are additive/regenerable (`python3 infra/monitoring/grafana/generate_dashboards.py`).

## 7. Final local verification and staging readiness gate (2026-10-25, third pass)

Scope: complete the end-to-end test run on healthy disposable infrastructure, diagnose the full root disk, resolve the stale Python tooling without touching the environment, re-confirm the observability evidence, harden the regression coverage, and prepare the owner decisions. **No production VPS inspection, deployment, alert delivery or production change was performed or authorised.** Nothing was committed or pushed.

Column "Run" says whether the result was **NEW** (executed in this pass) or **CARRIED** (from an earlier pass, files unchanged since).

### 7.1 Check register

| # | Check | Status | Command / procedure | Result, exit | Environment | Run | Remaining risk / next action |
|---|---|---|---|---|---|---|---|
| 1 | Full unit suite | PASS | `python3 run_full_tests.py --unit --integration --security` (stage `unit`) | **1354 tests, 0 failed, 0 skipped**, exit 0, 55 s | repo venv (Python 3.12.12, `liveness` extra installed per `uv.lock`), isolated `hrms_test`, Redis /1 | NEW | none |
| 2 | **Full integration + security suite** | PASS | same run, stage `integration-security`, `PYTEST_ADDOPTS=--deselect ...test_object_survives_a_minio_container_restart`, `S3_ENDPOINT_URL=http://localhost:9100` | **1825 tests, 0 failed, 0 errors, 0 skipped**, first run (no `--lf` rerun needed), exit 0, 844 s | runner-created `hrms_test` (dropped and recreated by the runner; absent before, absent after), disposable MinIO (`pgsty/silo`, data on the non-root disk, container uid 1000), shared dev Redis DB 1 per runner convention | NEW | see row 3 |
| 3 | Test deselected on purpose | NOT RUN | `tests/integration/core/test_storage.py::test_object_survives_a_minio_container_restart` | the test hard-codes the container name `hrms-minio` and runs `docker restart` on it: that is the **shared dev MinIO**, and against a disposable store it would prove nothing. It passed earlier in this session only because it restarted the shared container (a brief, harmless restart that should not have happened - noted) | - | NEW | run it against the real dev MinIO once root-disk space is freed (it needs the shared store healthy) |
| 4 | New regression: stale token beats date check | PASS | `pytest .../test_effective_dated_integrity.py -k test_a_stale_if_match` | 4 cases pass with the fix; **with the fix reverted all 4 fail deterministically (`assert 422 == 409`)**; fix restored (32 added lines, 4 hunks) | disposable DB `hrms_obs_final` (dropped after) | NEW | none |
| 5 | Concurrency race repetitions | PASS | the 4 `test_concurrent_revisions...` cases + the 4 new deterministic cases, run 30 times | **30 of 30 runs clean** (before the fix: 7 of 12 runs failed; earlier fix verification: 25/25) | same | NEW | passing runs cannot prove a race permanently gone; the deterministic test now pins the semantics without relying on timing |
| 6 | New guard: runtime-role grants (D11) | PASS | `pytest tests/integration/core/test_runtime_role_grants.py` | 9 cases pass on a correctly provisioned DB; **after re-running `002_app_role.sh` on the migrated DB the guard fails** (`hrms_app can UPDATE audit_log / email_log / leave_ledger / ...`) | disposable DB only; nothing granted or revoked on any shared DB | NEW | extend `APPEND_ONLY` when D11 is approved |
| 7 | Static: ruff format | PASS | `.venv/bin/python -m ruff format --check .` | 662 files formatted, exit 0 | repo venv interpreter | NEW | - |
| 8 | Static: ruff check | FAIL (baseline) | `.venv/bin/python -m ruff check .` | 6 findings, exit 1, **none from this work**: 5 x E501 in committed, unmodified migrations (`20261007090000`, `20261008090000`, `20261019090000`) and 1 x E501 in `opensource_face/store.py:4` (untracked file, last written 12:05 on 2026-10-25 by the earlier face-engine work) | same | NEW | owners of those files; installed ruff is 0.16.1 while `pyproject` only says `>=0.8` - a newer ruff may flag lines an older one accepted |
| 9 | Static: mypy | FAIL (baseline) | `.venv/bin/python -m mypy src/hrms` | 1 error, exit 1: `seed/bootstrap.py:135` `Item "Connection" of "Engine | Connection" has no attribute "url"`. `bootstrap.py` is a pre-existing uncommitted change (last written 2026-10-24 08:09, before the observability work); I never edited it | same | NEW | owner of that change |
| 10 | Static: import-linter | PASS | `PYTHONPATH=src .venv/bin/python -c "from importlinter.cli import lint_imports_command ..."` | 1 contract kept, 0 broken, exit 0 | same | NEW | - |
| 11 | Prometheus rules | PASS | `docker run --network none --entrypoint promtool ... check rules alerts.yml` | **36 rules, exit 0** | `quay.io/prometheus/prometheus` (promtool 3.15.0) | NEW | - |
| 12 | Rule unit tests | PASS | `... promtool test rules alerts.test.yml` | SUCCESS, exit 0 (8 scenarios incl. the full-object-store one) | same | NEW | - |
| 13 | Dashboard JSON and queries | PASS | JSON load of 4 files; all 44 queries (variables substituted) through `promtool check rules` | 4 valid files, 40 panels, 44 queries parse, exit 0 | same | NEW | - |
| 14 | Dashboard / rule metric names | PASS | `refcheck.py` against the code's exported series | every metric referenced exists; the 4 flagged names are the dynamically-built `hrms_db_pool_*` gauges (confirmed present in the live exposition) | repo venv | NEW | - |
| 15 | Rules and dashboard queries on live data | PASS (evaluation only) | ephemeral Prometheus scraping a real 2-worker gunicorn API; every query and rule evaluated | 0 query errors, 36/36 rules `health=ok`; 17/44 queries returned data, 27 empty only for lack of producers (Celery, node_exporter, traffic) | local containers, since removed | CARRIED (16:15-16:25; **no observability file changed after it**; the dashboards were regenerated afterwards but only to add `noValue`, and checks 11-14 above were re-run on the final files) | needs a run with a worker, Beat and `node_exporter` |
| 16 | Metrics endpoint incl. failed scrapes; redaction; storage classification; correlation | PASS | `tests/unit/core` (includes `test_metrics`, `test_log_redaction`, `test_storage_metrics`, `test_observability_config`) inside the 1354-test unit run | all pass | repo venv | NEW (as part of row 1) | - |
| 17 | Grafana rendering | NOT RUN | - | no Grafana installed or approved | - | - | needs D3 |
| 18 | Alert delivery | BLOCKED | - | no destination, no recipient, no Alertmanager (D1) | - | - | decision D1 |
| 19 | Docker image build and Compose startup | NOT RUN | - | no image built, no stack started in this or the earlier passes | - | - | run on staging |
| 20 | Celery worker, Beat | NOT RUN | - | worker exercised in the first pass; Beat never run (would fire real scheduled tasks) | - | - | staging with a disposable tenant |
| 21 | PostgreSQL server settings | BLOCKED | - | read-only `pg_settings` inspected; no setting changed | - | NEW (inspection) | decision D5 |
| 22 | Production VPS | NOT RUN | - | not inspected, contacted or modified | - | - | needs access and approval |

### 7.2 Disk diagnosis (read-only; nothing deleted by me except my own disposable resources)

* **Cause: capacity, not inodes or a mount fault.** `df -h /`: 560 G total, 526 G used, **5.0 G available, 100%**; `df -i /`: 9% inodes used. The repository lives on a different, healthy filesystem (`/dev/sda1`, 193 G free).
* **Where the space is** (`du -x`, as a non-root user, so about 87 G of the used figure is unreadable to me, most likely `/var/lib/docker`): `/home/varun` 299 G (`Downloads` 122 G, `miniconda3` 32 G, `~/.config` 28 G, `Documents` 27 G, `~/.local` 16 G, `~/.cache` 16 G, `~/.npm` 13 G, `Android` 11 G); `/usr` 104 G of which **`/usr/share/ollama` 74 G**; `/var` 26 G (`/var/lib` 17 G, logs 4.5 G, CUDA repo 3.1 G); journals 4.0 G.
* **Docker is not the cause:** 14.0 G images (5.96 G reclaimable), 97 MB containers, 2.0 G volumes (1.29 G reclaimable), 3.9 G build cache (1.0 G reclaimable).
* **Consequence seen:** MinIO refuses writes below its free-space threshold (`XMinioStorageFull`); every upload 500s; this was the single cause of the 38 earlier integration failures.
* **Cleanup performed:** only my own disposable resources - two throwaway MinIO containers, three throwaway Postgres databases, an ephemeral Prometheus container, and one data directory I created and verified (`/media/varun/varun12/obs-final-minio-data`: canonical path exact, real directory, all 424 entries owned by the current user, no mounts, synthetic data only). **No** `docker system prune`, `git clean`, journal vacuum or wildcard deletion was run. One regenerable file I should not have deleted without checking ownership: `test-results/web-vitest.xml` (git-ignored frontend run output, not produced by this work); it is recreated by the frontend stage of `run_full_tests.py`.
* **Left untouched, needs the owner:** `/media/varun/varun12/obs-audit-minio-data` (2.6 MB, 187 files from the earlier pass; all entries root-owned because that container ran as root, so it cannot be removed without root; an earlier container-based removal was refused by the safety check and was not retried). It is a real directory, canonical path as expected, no container mounts it. To remove it, as root: `sudo rm -r --one-file-system -- /media/varun/varun12/obs-audit-minio-data`.

Candidate cleanups (not executed; each needs the owner's decision):

| Candidate | Recovers | Risk | Notes |
|---|---|---|---|
| Unused Docker images (`docker image prune`, dangling only: 10 untagged images) | about 7.8 G | low-medium: untagged images may be parents of tagged ones or a build someone wants to compare; tagged `hrms-api:prefinal-gate` / `liveness-local` are not candidates | ownership uncertain |
| Docker build cache (`docker builder prune`) | about 1.0 G | low (slower next build) | |
| 10 stopped containers | about 0.1 G | low | some are 4+ weeks old |
| Leftover test databases in the dev Postgres (`hrms_basefix_*`, `hrms_final_*`, `hrms_remed_*`, `hrms_face_hardening_test`) | about 0.23 G | medium: they may be evidence for earlier gates | ownership uncertain |
| Journal vacuum | up to 4.0 G | low | needs root |
| `~/.cache` (Chrome 5.7 G, uv 2.4 G, Playwright 2.2 G) | up to about 10 G | low (re-downloaded) | user's own caches |
| `/usr/share/ollama` (74 G), `~/Downloads` (122 G) | the real fix | user data | not touched |

### 7.3 Python environment (resolved without changing it)

* **Root cause, proven:** the project `.venv/bin` console scripts (`mypy`, `lint-imports`, `pytest`, `alembic`, `gunicorn`) carry the shebang `#!/media/varun/varun11/work/...` from a previous mount path. When `uv run` execs one, the kernel cannot find that interpreter and `execvp` falls through to the next match on `PATH` - the conda environment's Python 3.9 tools. This explains both the wrong-Python `alembic` earlier and the runner's static stage failing in 0.1 s. `.venv/bin/python` itself is a correct symlink to uv's CPython 3.12.12 and `uv run python` resolves to it.
* **Reproducible environment:** `requires-python >=3.12`, `uv.lock` consistent (`uv lock --check`), the `liveness` extra pins `opencv-python-headless 4.14.0.94` + `numpy 2.5.2` and is what the Dockerfile installs (`uv sync --frozen --extra liveness`); the installed packages match the lock. An earlier `uv sync --all-groups` (no extra) had removed them; they were restored with `--all-extras` and now match.
* **Safe way to run tools without changing anything:** `.venv/bin/python -m ruff|mypy` and `PYTHONPATH=src .venv/bin/python -c "from importlinter.cli import lint_imports_command ..."`. Permanent fix (not done - it modifies `.venv`): `uv sync --reinstall` or recreate the venv on the current path.
* **CI gap, found not fixed:** `.github/workflows/ci.yml` runs `uv sync --all-groups` with **no `--extra liveness`**, so the three tests that need numpy/OpenCV (two liveness boot tests and the open-source-face evaluation report test) would fail there. Owner decision: add the extra to the CI install step, or make those tests skip without it.
* **Runner static stage** still calls `uv run <tool>`, so it fails here regardless of code; left as is because it is baseline tooling.

### 7.4 Decisions

D1, D5, D8, D9, D10 and D11 are written up with evidence, options, recommendation and the exact approval needed in [architecture section 15](../architecture/OBSERVABILITY_ARCHITECTURE.md#15-decision-register-prepared-for-approval-2026-10-25). New facts established in this pass: the local Postgres defaults to `log_parameter_max_length=-1` (slow-statement logging without changing it would log bound values); `pg_stat_statements` ships in `postgres:16-alpine`; the runtime role cannot TRUNCATE any of the 113 tables; `punch` and two attendance timeline tables are documented immutable but still writable by the runtime role.

### 7.5 Readiness assessment (each area separately)

| Area | Assessment |
|---|---|
| Local unit and integration tests | **PASS** - 1354 unit, 1825 integration + security, 0 failures, plus 13 new tests; one test deliberately not run (row 3) |
| Static analysis and dependency reproducibility | **PARTIAL** - format and import contracts pass; 6 ruff and 1 mypy findings are baseline; tooling needs the shebang fix; CI lacks the `liveness` extra |
| Prometheus rules and dashboard-query validation | **PASS** (syntax, behaviour, live evaluation) |
| Grafana rendering | **NOT RUN** |
| Alert delivery | **BLOCKED** (D1) |
| Docker build and Compose startup | **NOT RUN** |
| Celery worker and Beat | **PARTIAL** (worker only, first pass); Beat NOT RUN |
| PostgreSQL settings and runtime permissions | settings **BLOCKED** (D5); permissions **PASS** on a fresh database with a new guard; production grants unverified |
| Disk and resource monitoring | **PARTIAL** - application-side log-volume gauge and alerts verified; host and other volumes need `node_exporter`; the dev machine itself is at 100% disk |
| Production VPS | **NOT RUN** - never inspected |

**Verdict: READY FOR LOCAL VERIFICATION - NOT STAGING-READY.** The local evidence is now complete and green, but staging readiness needs the items marked NOT RUN or BLOCKED above, none of which can be satisfied without an approved environment and decisions.

### 7.6 Files changed in this pass

`apps/api/tests/integration/core/test_runtime_role_grants.py` (new); `apps/api/tests/integration/modules/employee/test_effective_dated_integrity.py` (one new parametrised test); docs: this audit, architecture (sections 9 pointer, 15), verification report, runbook, alert and dashboard catalogs. The earlier passes' source changes are listed in section 6.4.

Rollback: delete the two test additions. No source or configuration change was made in this pass.
