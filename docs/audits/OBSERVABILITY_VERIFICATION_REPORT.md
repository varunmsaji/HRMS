# Observability verification report

Date: 2026-10-25. Nothing was committed, pushed, deployed or applied to a shared environment. Existing uncommitted work was preserved (some files, e.g. `app.py` and `email_sender.py`, contain both prior changes and the additive ones from this work).

## 1. Verdict

**READY FOR LOCAL VERIFICATION.** Not staging-ready: alert delivery, Beat, the Docker image/compose path, dashboards on live data and the real VPS are unproven. Overall maturity ~2.7/5 (was ~2.0) - see the [audit](PRODUCTION_OBSERVABILITY_AUDIT.md) section 3.

## 2. Changes

| Area | Files |
|---|---|
| Metrics core | `core/observability/{metrics,scrape,metrics_router,db_metrics}.py` (new) |
| Trace correlation | `core/observability/trace_context.py` (new); `request_context.py`, `celery_app.py` |
| Instrumentation hooks | `operations.py`, `business_events.py`, `security_events.py`, `logging.py`, `file_sink.py`, `core/errors/handlers.py`, `core/db/session.py`, `face_verification.py`, `email_sender.py`, `app.py` |
| Settings / deps | `settings.py` (`METRICS_TOKEN`), `pyproject.toml` + `uv.lock` (`prometheus-client`), `.env.example`, `env/.env.production.example` |
| Deployment (inert until used) | `Dockerfile` (`/app/metrics`), `docker-compose.prod.yml` (shared `metrics_mp` volume), `infra/nginx/conf.d/hrms.conf.template` (`/metrics` -> 404), `docker-compose.monitoring.yml` (optional Prometheus + node_exporter, capped, no ports) |
| Alerts / dashboards | `infra/monitoring/prometheus/{prometheus.yml,alerts.yml,alerts.test.yml}`, `infra/monitoring/grafana/{generate_dashboards.py,dashboards/*.json}` |
| Tests (50 new) | `tests/unit/core/test_{metrics,metrics_multiprocess,celery_metrics,trace_correlation,observability_config}.py`, `tests/integration/core/test_db_metrics.py`, additions to `test_file_logging.py`, `test_face_provider_client.py` |
| Docs | audit, architecture, runbook, alert catalog, dashboard catalog, this report |

## 3. Test commands and results

| Command | Result |
|---|---|
| `pytest tests/unit` (in `apps/api`) | 1259 passed, 5 skipped, **2 failed** (`test_liveness.py`: `No module named 'cv2'` - optional extra not installed; unrelated) |
| `pytest tests/integration/core tests/unit/core/test_file_logging.py` | 117 passed |
| `python run_full_tests.py --integration` (isolated `hrms_test` DB, Redis /1) | 1778 tests, **2 failed**: `test_effective_dated_integrity::test_concurrent_revisions_...[compensation]` (concurrency race, got a 422; the same test failed for `[bank]` in an earlier dev-DB run, so it is flaky/non-deterministic) and `test_leave_hardening::test_runtime_role_cannot_rewrite_or_erase_leave_history` (`hrms_app` still has UPDATE on `leave_ledger` in the test DB; a DB-grant issue). Neither touches observability code; I did not prove them pre-existing by running a clean checkout |
| Plain `pytest tests/integration` against `hrms_dev` | 45 errors: the suite's own guard refuses to TRUNCATE the persistent dev DB - expected; superseded by the isolated run above, in which those auth tests pass |
| `ruff check src tests/...new` | clean for new/changed code (pre-existing E501 in old alembic files) |
| `mypy src/hrms` | my 2 errors fixed; 3 remaining are pre-existing (`bootstrap.py`, `liveness.py`) |
| `lint-imports` | 1 contract kept |
| `promtool check rules` / `test rules` | 35 rules OK; 7 unit scenarios pass |
| `promtool check rules` over all 44 dashboard queries | OK |
| `promtool check config prometheus.yml` | only fails on the not-yet-created secret file `metrics_token` (expected) |

## 4. Runtime verification (local, real processes)

gunicorn (2 workers) + Celery worker (concurrency 2), shared `PROMETHEUS_MULTIPROC_DIR`, temporary `LOG_DIR`, local Postgres, Redis DB 12 (checked empty; DB 14 held a real backlog and was not used), e-mail/face providers disabled.

- `/metrics`: 401 without/with wrong token, 200 with token; 215 lines idle. Counters from both API workers and the separate worker process were summed; dependency probes reported database and redis up, pool 5/15, queue depth 0, heartbeat age 6 s.
- 3 failed logins -> `hrms_security_events_total{event="login.failed"}` 3, 401 denials counted, `/v1/employees` unauthenticated and an unknown path (`route="unmatched"`, UUID absent from output).
- A task published from a separate process: published/started/finished/duration/queue-wait series present; an unregistered task name produced `messages_unroutable{state="unknown_task"}` without using the name as a label.
- Trace correlation: a trace id bound in a publisher process appeared on the worker's `celery_task_finished` line; inbound `traceparent` appeared on API `http_request` lines.
- Files written by 4 processes: `api, app, auth, background_jobs, employees, errors` logs.
- Overhead measured: 1.6 us (single process) / 3.75 us (mmap) per recorded request.

Not run: Celery Beat (it would fire real scheduled tasks against the dev database), Docker image build, compose stack, Nginx, any VPS.

## 5. Failure-injection coverage (requested list)

| # | Scenario | Status |
|---|---|---|
| 1-4 | success, validation error, authorization denial, unexpected exception | covered (`test_metrics`, existing handler tests) |
| 5 | DB connection failure | probe -> `hrms_dependency_up 0` (test); classification test |
| 6 | transaction rollback | `hrms_db_rollbacks_total` (integration test) |
| 7 | Redis unavailable | probe test; `readiness` existing tests |
| 8 | Celery broker unavailable | `celery_publish_failures_total` (test, mocked `delay`) |
| 9-10 | task failure/retry; scheduled job miss | `test_celery_metrics`; promtool missed-job test |
| 11-12 | attendance rejection vs infra failure | `test_metrics` outcome test + promtool test |
| 13-14 | leave accrual / payroll failure | alert rules tested; domain code paths only via the generic `@logged_operation` test, no module-specific failure injection |
| 15 | provider timeout | `test_face_provider_client` (MockTransport) |
| 16-17 | rotation; log dir permission failure | existing file-logging tests + new drop-metric test |
| 18 | metrics access control | covered |
| 19 | trace propagation | covered (signals level + live cross-process) |
| 20 | exporter unavailable | N/A - no exporter exists; metric failures swallowed (test) |

## 6. Remaining dependencies and release blockers

1. D1 alert destination + named owner (alert delivery **not tested**).
2. Decide/deploy Prometheus (+ node_exporter), then 2-4 weeks baseline to calibrate every provisional threshold.
3. Build the image and run compose on staging to prove `/app/metrics` ownership, the shared volume and the Nginx rule.
4. Approve Postgres settings (slow query log, lock waits, `pg_stat_statements`, idle-in-transaction timeout).
5. External uptime probe for `/health/ready`.
6. Payroll runs synchronously inside requests (60 s limit) - capacity risk, now observable but not fixed.
7. Resolve or confirm the two integration failures above and the `cv2` unit failures in CI's environment.
8. Not instrumented: leave balance reconciliation; host metrics until node_exporter is deployed. Storage (MinIO) calls are instrumented as `dependency="storage"` (`core/storage.py`, `tests/unit/core/test_storage_metrics.py`, mocked errors only - not run against a live MinIO).

## 7. Estimated VPS cost if everything optional is enabled

Prometheus 100-250 MB RAM (capped 512 MB), ~27 MB/day disk (15 d, capped 2 GB); node_exporter ~20 MB. Estimates, not measurements - see architecture doc section 10.

## 8. Second-pass verification (2026-10-25)

See the audit, [section 6](PRODUCTION_OBSERVABILITY_AUDIT.md#6-second-pass---independent-re-audit-2026-10-25), for findings and the full command table. Corrections to this report's earlier statements:

* **Two "pre-existing" integration failures (section 3) are resolved.** The concurrency failure was a genuine race in error precedence, reproduced 7/12 and fixed (0/25 after). The `leave_ledger` failure is a test-database ordering problem (role script re-run on a migrated DB), reproduced and fixed in the runner; a fresh database passes. Neither involved observability code, as originally suspected.
* **Section 3 `cv2` unit failures**: the `liveness` extra was not installed in that environment; with `--all-extras` the unit suite is 1354 passed, exit 0.
* **promtool**: re-run, 36 rules (one added), `check` and `test` exit 0.
* **Verdict unchanged: READY FOR LOCAL VERIFICATION, not staging-ready.** What changed is the evidence: rules and all 44 dashboard queries now also evaluated against a live Prometheus scraping a real two-worker API (0 errors); alert delivery, Beat, Docker/compose, Grafana rendering and the VPS are still unproven.


## 9. Final local verification (2026-10-25, third pass)

Full detail, the 22-row check register, the disk diagnosis and the readiness table are in the audit, [section 7](PRODUCTION_OBSERVABILITY_AUDIT.md#7-final-local-verification-and-staging-readiness-gate-2026-10-25-third-pass). Headline results, all newly executed unless stated:

| Check | Result |
|---|---|
| `python3 run_full_tests.py --unit --integration --security` (isolated `hrms_test` recreated by the runner, disposable MinIO with free space, Redis /1) | **PASS, exit 0**: unit 1354 tests / 0 failed; integration + security **1825 tests / 0 failed / 0 skipped**, first run, 844 s |
| Deliberately not run | `test_object_survives_a_minio_container_restart` - it restarts the shared dev container `hrms-minio` by hard-coded name |
| Concurrency regression | new deterministic test fails 4/4 without the fix (`assert 422 == 409`), passes with it; 30 of 30 repeat runs of the race test + the deterministic test clean |
| New grant guard | passes on a correctly provisioned DB, fails when `002_app_role.sh` is re-run on a migrated DB |
| `promtool check rules` / `test rules` | 36 rules / 8 scenarios, both exit 0 |
| Dashboards | 4 valid JSON files, 40 panels, 44 queries parse (promtool, exit 0); live evaluation carried forward from the second pass (no observability file changed since) |
| Static | `ruff format` PASS; `lint-imports` PASS; `ruff check` 6 findings and `mypy` 1 error, **all baseline** with provenance (committed migrations, untracked face-engine file, a pre-existing uncommitted `bootstrap.py` change) |

Corrections to earlier statements in this report: the "static checks fail" noted in section 8 are a tooling fault (stale `.venv/bin` shebangs make `uv run` fall through to conda's Python 3.9), not code failures - run through `.venv/bin/python -m ...` they produce the baseline findings above. The verdict is unchanged: **READY FOR LOCAL VERIFICATION - NOT STAGING-READY** (Grafana rendering, alert delivery, Docker/Compose, Beat, PostgreSQL settings and the VPS are NOT RUN or BLOCKED).
