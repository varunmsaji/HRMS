# HRMS QA Baseline Results — 2026-10-25 (Phase 2, catalogue stage)

Purpose: one place that separates what was **verified in this phase**, what is **inherited** from `FUNCTIONAL_QA_REPORT_2026-10-25.md`, what is **inferred**, what is **blocked**, and what is **unknown**. Nothing here says the system is correct or production-ready.

## 1. Safety statement

No application code, migration, database, container, service or configuration was modified or restarted. No file was deleted. Nothing was committed, pushed or deployed. The only processes started were (a) read-only shell commands and (b) one throwaway in-memory Redis on `127.0.0.1:16410` (`--save "" --appendonly no`, working directory in the session scratchpad) that was shut down with `shutdown nosave` (a later `ping` confirmed connection refused). The unit run used `DATABASE_URL`/`REDIS_URL`/`S3_ENDPOINT_URL` set to unreachable or private addresses, `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` so nothing could reach the shared stack or write to the full root disk. New files, all under `docs/testing/`: `QA_TEST_STRATEGY.md`, `QA_TEST_CASES.csv`, `QA_TRACEABILITY_MATRIX.md`, `QA_DEFECT_REGISTER.md`, `QA_EXECUTION_PLAN.md`, `QA_BASELINE_RESULTS.md`, `QA_TEST_MAP.csv` and the generator `qa_catalogue_src/`. Existing report and `qa_live_2026-10-25/` were not modified.

## 2. VERIFIED in this phase

| # | Observation | How |
|---|---|---|
| V1 | Report present in full: 13 numbered sections + file list, 170 lines; evidence directory has 17 files (12 scripts, `qa.py`, `coverage.py`, `qa_env.sh`, `start_qa.sh`, `start_b.sh`, `register.csv`) | `Read`, `ls` |
| V2 | `register.csv`: 216 rows, 4 columns, 0 duplicate IDs, all rows 4 fields, PASS 214 / INFO 1 / FAIL 1, no evidence column, `ATT-04` gap, 215 empty `detail_if_not_pass` | Python `csv` |
| V3 | Raw per-check outputs (`j*.json`, `api.log`) referenced by the scripts are **absent**; scripts hard-code another session's scratchpad; report and evidence are **untracked** in git | `ls`, `git status`, script text |
| V4 | `LV-28` vacuous (`or True`); `ATT-15` destructive unscoped UPDATE; daily-calculation outputs only printed as INFO | script text (`j3_leave.py:61`, `j4_att.py:32,35-37`, `j5_reg.py:35`) |
| V5 | Root filesystem `/dev/nvme0n1p6`: 560 G, 526 G used, **5.0 G available, 100 %**; `/media/varun/varun12` has 193 G free | `df -h` |
| V6 | `apps/api/.venv/bin/pytest` and `lint-imports` shebang = `/media/varun/varun11/…/python` (stale; repo is on `varun12`; bytecode paths even reference `varun9`). `.venv/bin/python` (3.12.12, uv-managed) works | `head -1`, `ls -l`, traceback path |
| V7 | Flutter/Dart not on `PATH` | `which flutter dart` → empty |
| V8 | Containers: `hrms-postgres` Up 14 h (healthy), `hrms-redis` Up 14 h (healthy), `hrms-minio` Up 41 min (healthy) | `docker ps` (read-only) |
| V9 | `tests/conftest.py` defaults `DATABASE_URL` to `hrms_dev`; root autouse fixture `_reset_credential_rate_limits` connects to `REDIS_URL` for every test (unit included) and deletes `ratelimit:*` keys | code reading; first unit run against a closed Redis port errored on the first test |
| V10 | `test_object_survives_a_minio_container_restart` executes `docker restart --time 10 hrms-minio`, skipped only if docker/container is absent; no opt-in. Other `subprocess` users do not touch Docker (`test_host_monitor.py` uses a fake `docker` in `tmp_path`) | code reading (`test_storage.py:141-165`) |
| V11 | 121 Alembic revision files; newest `20261022090000_face_opensource_engine.py`; 22 `@celery_app.task` definitions; 10 Beat entries | `ls`, `grep` |
| V12 | `run_task()` exists in `core/db/session.py:117` and is used by `leave`, `attendance`, `employee`, `employee_import` task modules; remaining `asyncio.run` sites are CLI scripts (`ops/import_backlog.py`, face tools); `health`/`organisation` tasks have no DB use | `grep` |
| V13 | `test_celery_task_event_loop.py`, `test_runtime_role_grants.py`, `test_db_metrics.py` are **untracked** (not in CI until committed) | `git status` |
| V14 | Test inventory: 264 backend test files / 2,649 `def test_` functions (unit 1,063 · integration 1,556 · security 30; 105 parametrized); 64 web test files / 514 `it`/`test` blocks; 34 mobile test files / 278 blocks; 2,963 map rows, 0 unmapped | AST + regex (`QA_TEST_MAP.csv`) |
| V15 | Runner artefacts from the earlier pass (`test-results/*.xml`, git-ignored): unit **1,354 items, 0 failures**; integration+security **1,839 items, 38 failures**; the rerun file (38 items) shows 38 failures; stage summary: ruff-check/mypy/lint-imports FAIL at 0.1–0.3 s (consistent with the stale shebang), unit PASS 53 s, integration-security FAIL 910 s | `testsuite` attributes |
| V16 | **Unit tier re-run now:** 1,354 items → **1,344 passed, 1 failed, 9 errors in 48.8 s**. All 10 non-passes are `ConnectionRefused` to the deliberately unreachable database: `unit/modules/health/test_router.py::test_readiness_returns_200_when_dependencies_are_up` (readiness probes the DB) and 9 setup errors in `unit/core/test_crypto_keys.py`. They are therefore environmental under this guard, **not** product failures; they show that `tests/unit` is **not** database-free | local run; error text `ConnectionRefusedError … ('127.0.0.1', 1)` |
| V17 | Worked arithmetic used in the payroll cases (e.g. 15000×26/31 = 12,580.645161…) is a calculation I performed from approved formulas; it is an *expected value to be confirmed after CL-04*, not a system result | — |

V16 is the only runtime test result produced in this phase; every other row is an inspection or read-only command result.

## 3. INHERITED claims and how far they were corroborated

| Claim (report) | Status here |
|---|---|
| Backend regression 3,198 passed, 0 failed, 1 deselected | **INHERITED.** Consistent with V15 (1,354 + 1,839 = 3,193 items in the baseline) plus the added regression cases; not re-run (needs MinIO/Postgres/Redis and ~15 min) |
| "unit 1063 PASS" | **Mismatch:** 1,063 is the unit *function* count; the runner executed 1,354 unit items (V15). The inherited figure understates unit execution |
| 38 integration failures all caused by full disk | **INHERITED** (rerun artefact still shows 38 failures; disk still full per V5) |
| Web Vitest 522 passed / 64 files; `tsc` clean; ESLint 110 errors; no `next build` | **INHERITED.** File count 64 verified; 514 static blocks vs 522 reported (difference plausibly `it.each`; not verified) |
| 216 live checks, 214 PASS, 1 INFO, 1 FAIL | **Counts VERIFIED** (V2); the *results* are inherited — the raw evidence is missing (V3) |
| Migrations apply cleanly from empty to head | **INHERITED**; revision count/head file VERIFIED (V11) |
| 335 API operations, 82 web pages | **INHERITED**, not recounted |
| 22 Celery tasks, 10 Beat entries | **VERIFIED** by grep (V11); Beat→task mapping and execution not re-checked |
| DEF-02/03/04 fixed | **Presence of the fix VERIFIED** (V12, `IMPORT_FILE_UNREADABLE` exists); behaviour not re-run |
| Dev DB untouched afterwards; private DB/MinIO/Redis | **INHERITED**; the private resources "have since been removed" (report) so they cannot be inspected |
| Static contract: web 220 calls / mobile 117 calls, 0 mismatches | **INHERITED**; `coverage.py` not re-runnable as committed |
| K-1: `hrms_app` can UPDATE/DELETE `punch` | **INHERITED live fail**; static supporting facts VERIFIED (defect register Part A). Privilege not queried (needs a private DB) |

## 4. INFERRED (heuristic; do not quote as fact)

* `assertion_class_inferred` in `QA_TEST_MAP.csv`: 266 integration/security functions assert only status codes; 29 have no `assert` statement; 1,317 assert bodies or state; 1,037 unit functions classed `UNIT_LOGIC`.
* Live checks: 72 keyword-classed as business/state assertions, 143 as technical or security responses, 1 vacuous.
* Keyword dependency flags per test file (DB 145 files, MinIO/S3 27, Redis 23, Celery 27) over-count (e.g. `engine`, `storage` appear in unrelated code).

## 5. BLOCKED

| Item | Blocker |
|---|---|
| Flutter analyze/test, all `MOB-*` cases | SDK not installed (V7) |
| Any private-stack batch (B1 onwards) | Requires approval **A1** and disk headroom (V5); harness not yet written |
| Web build / browser journeys | Not started; need private stack |
| Payroll equality assertions | Open clarifications CL-04, CL-05, CL-06 |
| Boundary-sensitive attendance assertions | CL-16 |

## 6. UNKNOWN

* Whether the 38 storage failures would pass today (disk still 100 % full; MinIO now 41 min old).
* Real behaviour of attendance daily calculation, shifts, rosters, policies, periods, overtime, payroll arithmetic, platform lifecycle with approval ON, onboarding end to end, Beat firing, web UI, mobile — none was observed in this phase, and the live pass did not assert most of them.
* Whether privileges on `punch` are currently writable on any specific database (K-1 is an inherited live finding plus static reading).
* Whether `Idempotency-Key`-optional endpoints are used by real clients in a way that matters.
* Mixed-interpreter effects: both `cpython-39` and `cpython-312` bytecode exist under `tests/__pycache__`; the lock-vs-`.venv` diff has not been taken.

## 7. Defects and blockers (pointers)

K-1 (open, awaiting approval) · DEF-02/03/04 (fixed, uncommitted) · evidence defects QA-EVID-01…06 · environment ENV-BLK-DISK/SHEBANG/FLUTTER, ENV-RISK-DEVDB/REDIS/RESTART/GRANT/LIVEPORT/SHAREDBUCKET/TZ. Details: [`QA_DEFECT_REGISTER.md`](QA_DEFECT_REGISTER.md).

## 8. Catalogue status snapshot (end of Phase 2 - superseded by section 11)

191 cases: NOT_RUN 171 · BLOCKED 8 · FAIL 5 · NOT_APPLICABLE 7 · PASS 0.

---

# Phase 3 - safe environment readiness and B1 (2026-10-25)

## 9. Preflight (read-only) - what was proved and what was not

**Preserved first:** `git status` = 151 entries (98 tracked modified files, including the application fixes and ~50 mobile UI files; 100 untracked files, including the QA documents, evidence and generator). A full copy was written outside the repository: `/media/varun/varun12/work/staff-spectrum/qa_preserve_2026-10-25/` (`tracked_changes.patch`, `untracked_files.tgz`, `status.txt`, `HEAD.txt`, `SHA256SUMS`). Nothing committed, stashed, reset or cleaned.

| Check | Result (VERIFIED) |
|---|---|
| Root filesystem | `/` 560 G, 526 G used, **5.4 G free (99 %)** (5.0 G in Phase 2) |
| Intended non-root volume | `/media/varun/varun12` 469 G, 253 G used, **193 G free**; QA root `/media/varun/varun12/work/staff-spectrum/qa_runs/<RUN_ID>/` (does not exist yet) |
| Shared dev stack | `hrms-postgres` (host 5433), `hrms-redis` (6380), `hrms-minio` (9000/9001) on docker network `hrms_default`; **data volumes are under `/var/lib/docker` on the full root disk**. The compose Postgres init bind mount points at the stale `varun11` path. System Postgres 5432 / Redis 6379 / MySQL 3306 on the host belong to other projects and must not be touched |
| Proposed directories | `.../qa_runs/b1-20261025a/{pgdata,minio,artifacts,logs}`; Redis has no persistence (`--save "" --appendonly no`, tmpfs); container logs capped at 5 MB each (`--log-driver local`) so almost nothing is written to `/` |
| Host environment variables | No `DATABASE_URL`/`REDIS_URL`/`S3_*`/`AWS_*` exported in this shell |
| `.env` that could redirect tests | `apps/api/.env` points `DATABASE_URL`, `MIGRATIONS_DATABASE_URL` (read by `alembic/env.py` straight from `.env`), `REDIS_URL`, `S3_ENDPOINT_URL` + keys at the **shared** stack and also holds `MAILTRAP_API_TOKEN`, `HOSTINGER_MAIL_API_TOKEN`, `FACEPP_*`. `Settings` loads `.env` from the current directory for any variable not set in the environment. Mitigation designed: runner mounts `/dev/null` over `.env` and passes every URL/token explicitly (provider tokens blank) |
| Fixtures that mutate state | Every autouse conftest (root + 13 module conftests) only `SCAN`/`DELETE`s `ratelimit:*` keys on `REDIS_URL`; no `FLUSH*` anywhere. `tenant_wipe.py` and per-module `_cleanup*` issue `DELETE FROM <table> WHERE company_id`. Only `test_storage.py` runs `docker restart`. Destructive setup commands: `run_full_tests.py` (`DROP/CREATE DATABASE hrms_test`), `seed/bootstrap.py` (TRUNCATE, guarded), `scripts/seed*.py` and `create_platform_admin.py` (default to hrms_dev) |
| **New finding ENV-RISK-HARDCODED-DEVDB** | `tests/security/test_rls_runtime_role.py:63-64` hard-coded `localhost:5433/hrms_dev` (owner + `hrms_app`) and monkeypatched `DATABASE_URL` to it, so that module **registered and deleted synthetic tenants in the shared dev DB regardless of `DATABASE_URL`**, including under `run_full_tests.py`. The earlier report's statement "dev DB untouched" is therefore **unproven** for any full run that included `tests/security` (the module cleans up after itself, so leftovers may well be none, but writes did occur); the owner should check `hrms_dev` for leftover `QA`/test tenants (read-only query; not done here because shared dev data was out of bounds) |
| Isolation proof | **Not yet proved at runtime.** Static/design level: the sandbox (internal docker network, read-only repo, masked `.env`, explicit env, `guard_check.py` asserting effective hosts and unreachability of the shared names/IPs/ports/host/internet) is written and syntax-checked; `stack.sh preflight b1-20261025a` passed (disk, name collisions, images local - no pull, uv python root). The runtime proof (`stack.sh guard`) requires creating the network and containers, which needs approval |

## 10. Test-harness safety fixes (all uncommitted; scoped to test infrastructure; no business behaviour touched)

| # | Gap | Change | Validation (VERIFIED unless stated) |
|---|---|---|---|
| F1 | Root fixture clears `ratelimit:*` on shared Redis; suite defaults to `hrms_dev` | New `apps/api/tests/isolation_guard.py` + 6-line hook in `tests/conftest.py`: refuse (`pytest.UsageError`) when `DATABASE_URL` names `hrms_dev` (any host) or `REDIS_URL` is localhost:6380 index 0, unless `CI` is truthy or `HRMS_TEST_ALLOW_SHARED_DEV=1`. New `tests/unit/test_isolation_guard.py` (6 tests) | 9 tests pass (6 new + 3 existing isolation tests) against a throwaway in-memory Redis (:16410, shut down; confirmed refused afterwards). Conftest-level refusal reproduced with a `hrms_dev` URL on an unreachable host. Override honoured. CI/`run_full_tests.py` unaffected by construction (rule-level tests), **not** by running either |
| F1b | ENV-RISK-HARDCODED-DEVDB | `test_rls_runtime_role.py` derives admin/runtime URLs from `DATABASE_URL` (`HRMS_APP_DATABASE_URL` optional) | URL derivation verified for CI defaults (byte-identical to old constants), a QA URL, and an explicit override. The test itself **not run** since the change (needs a DB) - it is part of B1/`TEN-RLS-001` |
| F2 | MinIO restart test | `test_storage.py`: opt-in `HRMS_TEST_ALLOW_CONTAINER_RESTART=1` **and** `HRMS_TEST_MINIO_CONTAINER=<name>`, name must not be `hrms-minio`, container running with label `qa.disposable=true`, and the configured S3 port must be published by that container; otherwise `pytest.skip(reason)` | 4 scenarios run: default, opt-in without name, `hrms-minio`, nonexistent container - all SKIPPED with the expected reason; shared `hrms-minio` uptime unchanged (still "About an hour", never restarted). Positive path **not exercised** |
| F3 | Mobile live test defaults to `localhost:8000` and demo credentials | `live_contract_test.dart`: requires `HRMS_LIVE_API=1`, explicit `--dart-define=API_BASE_URL` not on port 8000, and `HRMS_LIVE_EMAIL`/`PASSWORD`; fallback credentials removed | **Unvalidated** - Flutter is not installed; reviewed by reading only |
| F4 | Stale venv shebangs | **Proposal only** (`qa_harness/README.md`): lock-exact new venv on the non-root volume, no upgrades; harness uses `.venv/bin/python -m` and is unaffected | not applied |
| F5 | `LV-28` `or True` | Original left intact (audit evidence). `qa_live_errata/lv28_replacement.md` gives the real assertion (`balance == 10.00` and `reserved_balance == 2.00`) with its basis in `LeaveBalanceRead` | **Unvalidated** - needs a running API |
| F6 | Attendance live checks only printed | Superseded by asserted DB-backed tests in `qa_harness/b1/`. New verified fact: the live scripts called `/attendance/days/calculate` **without `date`** (`j4_att.py:35`) and with `attendance_date=` (`j5_reg.py:35`); the endpoint parameter is `date` (`router.py:962`), unknown query parameters are ignored, so both calls calculated the server's *today*, not the day under test | verified by reading |
| F7 | `ATT-04` missing | Not invented: `qa_live_errata/register_errata.csv` records `ATT-04` as NOT_RECORDED; re-observed by `ATT-PUNCH-003` | recorded only |

## 11. K-1 investigation status

**Not executed against a database** (no disposable PostgreSQL exists yet; the shared one is out of bounds). What is established:

* *Expected matrix (contract per model docstrings, `test_runtime_role_grants.py`, WD-11):* `hrms_app` has SELECT+INSERT only on `punch`, `attendance_regularization_action`, `attendance_period_action` (as it does on `audit_log`, `leave_ledger`, ...).
* *Observed matrix:* **none yet.** Inherited only: live `ATT-15` FAIL (UPDATE succeeded on a private DB).
* *Static evidence (VERIFIED):* no `update(Punch)`/`delete(Punch)`/raw `UPDATE/DELETE punch` in `src/` or migrations (only `select(Punch)` in `attendance/repository.py`); migration `20261009090000` revokes only `leave_ledger`, `leave_application_action`, `audit_log`; others add `email_log`, `leave_year_end_run`, `platform_audit_log`; `002_app_role.sh` ends with `GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES` + default privileges and is "idempotent, safe to re-run" but re-running restores UPDATE/DELETE on every table (TRUNCATE is never granted by it) (reproduction recorded in the grants test docstring, 2026-10-25, for `leave_ledger`). Re-run behaviour on these three tables follows from the same statements; it is **to be measured**, not assumed.
* *Prepared experiments (in `qa_harness`, disposable DB only):* `k1_privileges.py after-migrate` (owner-side `has_table_privilege` matrix for every public table + `hrms_app` behavioural probes `UPDATE/DELETE ... WHERE false` and `TRUNCATE`, always rolled back; privileges are checked before rows are scanned, so no data is touched); `stack.sh rerun-role-script` then `k1_privileges.py after-rerun`; `usage-probe-install` (BEFORE UPDATE/DELETE/TRUNCATE triggers logging the query text) followed by the attendance, regularization and period integration suites and `usage-probe-report`, which answers empirically whether the application ever needs UPDATE/DELETE on these tables (anything other than cleanup helpers = legitimate need).
* **No grant was changed anywhere.** The remediation remains unapproved (CL-01, CL-24).

## 12. B1 results by case (all BLOCKED on approval A1 - none executed)

Run id proposed: `b1-20261025a`; `H=docs/testing/qa_harness/stack.sh`; evidence under `/media/varun/varun12/work/staff-spectrum/qa_runs/b1-20261025a/artifacts/`. Exact commands, expected results and prerequisites per case are in the `command`, `expected`, `preconditions` columns of `QA_TEST_CASES.csv` (rows `ENV-STACK-001`, `ENV-MIG-001`, `ATT-PUNCH-001…003`, `ATT-PUNCH-006`, `ATT-DAY-001…004`, `TEN-RLS-001`, `TEN-RLS-002`).

| Case | Status | Defect |
|---|---|---|
| `ENV-STACK-001` | BLOCKED (approval A1) | QA-EVID-01 |
| `ENV-MIG-001` | BLOCKED | — |
| `ATT-PUNCH-001`, `-002`, `-003` | BLOCKED | CL-16 for -003 |
| `ATT-PUNCH-006` | BLOCKED | K-1 |
| `ATT-DAY-001`…`004` | BLOCKED | CL-16 (boundary minutes) |
| `TEN-RLS-001`, `TEN-RLS-002` | BLOCKED | ENV-RISK-HARDCODED-DEVDB (fixed) |

## 13. Catalogue status snapshot (current)

192 cases: NOT_RUN 160 · BLOCKED 20 (8 Flutter + 12 B1) · NOT_APPLICABLE 7 · PASS 3 (`ENV-ISOL-001`, `ENV-ISOL-002`, `ENV-MINIO-001` - the harness safety fixes, verified as described in section 10) · FAIL 2 (`ENV-DISK-001`, `ENV-VENV-001`). No functional case has a verified PASS.

## 14. A1 safety review (read-only) - summary

See [`QA_A1_SAFETY_REVIEW.md`](QA_A1_SAFETY_REVIEW.md). The review found and fixed (in scripts and test infrastructure only) 11 issues, the most important being that the `--internal` Docker network design could not guarantee the shared dev ports were unreachable (replaced by a loopback-only shared network namespace), the QA root was overridable from the environment, other `.env*` files in the repo were not masked, and the isolation guard was a name-only deny-list (now an affirmative strict allow-list inside the sandbox). New: 26 guard unit tests pass (`--noconftest`). Nothing was created or started; B1 remains BLOCKED pending explicit A1 approval.

---

# Phase 3b - A1 approved: B1 executed (2026-10-25, 15:17-15:20 UTC)

Approval conditions honoured: preflight first; only resources listed in `QA_A1_SAFETY_REVIEW.md`; isolation guard immediately after startup (`ISOLATION PROVED`) before any migration/SQL/test; 3 GiB root gate (hard) and 2 GiB per-run re-check (hard) never approached; memory caps reduced; no `002_app_role.sh` rerun, no grant change, no full regression, no shared-data access; nothing committed. Host-side log: `/media/varun/varun12/work/staff-spectrum/qa_runs/b1-20261025a/logs/a1_run_full.log`; evidence: `.../b1-20261025a/artifacts/` (`preflight_isolation.json`, `k1_after-migrate.json`, one `.jsonl` per case); second cycle evidence: `.../b1-20261025b/artifacts/preflight_isolation.json`.

## 15. Resources, paths, readings

| Item | Value |
|---|---|
| Run IDs | `b1-20261025a` (B1), `b1-20261025b` (repeatability cycle); DB `hrms_qa_b1_20261025a` / `_b`; containers `qa-<RUN>-{net,pg,redis,minio}` (holder alpine `--network none`, postgres:16-alpine, redis:7-alpine, pgsty/silo) + `--rm` runners/helpers; 0 networks, 0 volumes (volume count 46 -> 46), 0 published ports |
| Resolved paths | `/media/varun/varun12/work/staff-spectrum/qa_runs/<RUN>/{pgdata,minio,artifacts,logs}` on `/dev/sda1`; Redis tmpfs 64 MB; Postgres data after B1: 73 MiB, MinIO 1 MiB, artifacts 68 KiB |
| Root disk (KiB free) | start 5,628,512 -> lowest observed 5,627,272 -> end 5,627,624 (total drift ~0.9 MB, includes the failed first `up` and two full cycles). No unexpected growth |
| Memory | Caps reduced to runner 1.5 GB, PG 512 MB, MinIO 512 MB, Redis 192 MB (+tmpfs 64 MB), holder 16 MB (= ~2.8 GB). MemAvailable 5.7-5.9 GB throughout; container usage at end: PG 54 MiB, MinIO 81 MiB, Redis 8 MiB. Swap used 1,329-1,330 MiB before, during and after (pre-existing, unchanged) |
| Shared stack | `hrms-postgres`/`hrms-redis` Up 15 h, `hrms-minio` Up 2 h (never restarted); 13 pre-existing non-QA containers unchanged |
| Cleanup | `down --confirm` for both runs: 0 labelled containers left; `pgdata`/`minio` dirs removed; empty/artifact dirs of the two runs retained as evidence |
| Incident | First `up` failed (Docker `local` log driver rejects `max-file=1` with default compression) after creating only the holder container and the run directory; fixed with `--log-opt compress=false`, cleaned with `down`, empty dirs removed with `rmdir`; no data touched |
| Strict-guard check (condition 5) | `entry.py` run on the host with `CI=true`, `HRMS_QA_STRICT=0`, and the override set, pointing at shared targets: exit 97, nothing executed. In the sandbox `entry.py` forces strict mode itself and the runner env sets `CI=` empty |

## 16. B1 results by case

| Case | Status | Command / evidence | Result |
|---|---|---|---|
| `ENV-STACK-001` | **PASS** | `stack.sh preflight/up/guard/down` x2 | Both cycles `ISOLATION PROVED`; repeatable with a fresh RUN_ID |
| `ENV-MIG-001` | **PASS** | `stack.sh migrate`; `k1_privileges.py after-migrate` | Head `20261022090000`, 113 tables, hrms_app NOSUPERUSER/NOBYPASSRLS |
| `ATT-PUNCH-001` | **PASS** | `test_att_punch_001_self_punch` | Self punch bound to caller; refusals 422/422/403; DB 1 row |
| `ATT-PUNCH-002` | **PASS** | `test_att_punch_002_...` | Replay and 10 parallel -> 1 row per key |
| `ATT-PUNCH-003` | **PASS** | `test_att_punch_003_...` | Duplicate tap accepted and stored; calculation collapses it (540 min). Answers the lost `ATT-04` |
| `ATT-PUNCH-006` | **FAIL (K-1 confirmed)** | `k1_privileges.py after-migrate` | hrms_app has UPDATE+DELETE on `punch`, `attendance_regularization_action`, `attendance_period_action`; TRUNCATE denied everywhere |
| `ATT-DAY-001` | **PASS** | `test_att_day_001_normal_day` | PRESENT 540/540, paid 1.00, DB row = API |
| `ATT-DAY-002` | **PASS** | `test_att_day_002_...` | 09:14 and 09:15 not late; 09:20 = 5 min LATE; 09:50 = 35 min HALF_DAY |
| `ATT-DAY-003` | **PASS** | `test_att_day_003_...[239,240,479,480]` | ABSENT / HALF_DAY / HALF_DAY / PRESENT with matching paid/lop fractions |
| `ATT-DAY-004` | **PASS** | `test_att_day_004_missing_punch` | INCOMPLETE for missing IN/OUT and for a working day with no punches (paid 0.00, lop 0.00 until close) |
| `TEN-RLS-001` | **PASS** | `tests/security/test_rls_runtime_role.py` | 4 passed |
| `TEN-RLS-002` | **PASS** | `test_runtime_role_grants.py`, `test_b05_db_immutability.py` | 17 passed; six append-only tables INSERT+SELECT only |
| `ENV-ISOL-003` | **PASS** | same RLS run | Follows `DATABASE_URL` |

Also run: `tests/unit/test_isolation_guard.py --noconftest` inside the sandbox: 26 passed. Not run (not authorised): usage probe, `002_app_role.sh` rerun, any other suite.

## 17. Status snapshot after B1

192 cases: PASS 15 (3 harness fixes + 12 B1/ENV-ISOL-003) · FAIL 3 (`ATT-PUNCH-006` K-1 product defect; `ENV-DISK-001`, `ENV-VENV-001` environment) · BLOCKED 8 (Flutter) · NOT_RUN 159 · NOT_APPLICABLE 7. "PASS" means the observed behaviour matched the expected result in this isolated sandbox; it is not a claim about production or about untested rules.

---

# Phase 3c - K-1 usage evidence and B2 (2026-10-25, 15:30-15:36 UTC)

Constraints honoured: only the approved isolated-stack procedure (`ISOLATION PROVED` before every run); no `002_app_role.sh` rerun; no grant change; no full regression suite; no shared dev data; nothing committed or pushed. Runs: `b2-20261025a` (development iteration, two failed attempts of my own tests preserved as evidence) and `b2-20261025b` (authoritative). Evidence: `/media/varun/varun12/work/staff-spectrum/qa_runs/b2-20261025b/{artifacts,logs}`, iteration evidence in `.../b2-20261025a/`.

## 18. K-1 usage probe - decision, evidence, code search, uncertainties

**Probe review.** The earlier `usage-probe-install` is **not** read-only: it creates a table (`qa.probe`), a `SECURITY DEFINER` function and row/statement triggers on `punch`, `attendance_regularization_action`, `attendance_period_action` (DDL) and writes a row for each mutation. It changes no grants, but it fails the "strictly read-only apart from rolled-back no-ops" condition, so **it was not run** and is now gated behind `--authorise-schema-change`. It was replaced by `stack.sh stats-snapshot`: one `SELECT` on `pg_stat_user_tables` through a session forced `default_transaction_read_only=on`, after the disposable-DB marker and isolation-proof checks. It reads PostgreSQL's own per-table write counters; it creates and modifies nothing.

**Counters (fresh disposable DB; columns ins | upd | del | hot_upd | live):**

| Table | Baseline | After 10 QA B2 tests | After +80 existing project tests (regularization, period, leave-projection files) |
|---|---|---|---|
| `punch` | 0 | 21 \| **0** \| 21 | 83 \| **0** \| 83 |
| `attendance_regularization_action` | 0 | 8 \| **0** \| 8 | 49 \| **0** \| 49 |
| `attendance_period_action` | 0 | 9 \| **0** \| 9 | 41 \| **0** \| 41 |
| `attendance_day` (control: legitimately mutable) | 0 | 23 \| 56 \| 23 | 76 \| 154 \| 76 |
| `attendance_period` (control) | 0 | 5 \| 5 \| 4 | 40 \| 19 \| 38 |

The deletes equal the inserts because every test's cleanup helper (`_cleanup_*`, `tenant_wipe`) deletes its rows as the owner role; they cannot be told apart from application deletes by counters alone, which is what the code search covers. Grant matrix after B2 is **identical** to the B1 baseline (no drift).

**Code search (VERIFIED by reading `src/` and `alembic/`):**
* The only repository classes for these tables are `PunchRepository`, `AttendanceRegularizationActionRepository`, `AttendancePeriodActionRepository`; their methods are `insert` and read-only `list_*/get_*/page_*`. No `update(...)`, `delete(...)`, `session.delete`, `bulk_*` or raw `UPDATE/DELETE/TRUNCATE` references these tables anywhere in `src/` or the migrations (`grep` for ORM and SQL forms).
* No code assigns to a loaded `Punch` or action row (`row.direction =` etc.: none). The action models carry `updated_at` through `TimestampMixin` but nothing ever modifies them.
* `PunchRepository` is used by `service.py` (intake, calculation, regularization apply) and `face_service.py` (face punch): insert/select only.
* **Caveat for any REVOKE:** the three tables have `recorded_by_user_id` / actor `user_id` columns with `FOREIGN KEY ... ON DELETE SET NULL` to `"user"`. If a `user` row were ever hard-deleted, PostgreSQL would UPDATE these rows through a referential action that runs with the table owner's rights, so a REVOKE from `hrms_app` neither blocks nor is blocked by it. No hard delete of `user` exists in `src/` (grep), so this is dormant today.
* The only DELETEs of these tables are the test helpers (owner role in CI). A future retention purge for TERMINATED companies (CL-24) would need an owner-role path.

**Remaining uncertainties:** counters cover 90 tests through regularization/period/leave-projection/intake paths, not every code path (face punch, import, employee termination); a runtime proof for all paths would need the DDL trigger probe (separate authorisation) or a longer workload. Effect of re-running `002_app_role.sh` after migrations is still unmeasured (not authorised). Whether `hrms_app` truly needs UPDATE/DELETE anywhere on these tables: **no evidence of need** (static + 0 updates), which supports a REVOKE migration but does not replace the product/security decision (CL-01, CL-24).

## 19. B2 results by case

Commands: `docs/testing/qa_harness/stack.sh pytest b2-20261025b /qa/b2/test_b2_attendance.py -p tests.conftest -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml -q -rA` (10 passed in 6.95 s) and, for supplementary evidence only, `stack.sh pytest b2-20261025b tests/integration/modules/attendance/test_regularization.py .../test_attendance_period.py .../test_leave_projection.py -q` (**80 passed** in 40.7 s; these are existing project tests whose assertions QA did not re-derive).

| Case | Status | Verified state / invariant |
|---|---|---|
| `REG-FLOW-001` | PASS | Pending changes nothing; approval adds exactly one `REGULARIZATION` punch, original punch row identical, day INCOMPLETE -> PRESENT 540, `is_regularized`, version 2->3, actions SUBMITTED/APPROVED/APPLIED; 2nd approve 409, no change |
| `REG-FLOW-002` | PASS | Reject: no punch, day byte-identical, no APPLIED; approve-after-reject 409 |
| `REG-VAL-001` | PASS | 4 invalid requests -> 422 (unknown type, type not allowed by policy, empty payload, future date); 0 rows in request/requested-punch/action/punch tables |
| `REG-AUTHZ-001` | PASS | Employee: own 201; forged employee 403; self-approve 403; other tenant 404; DB exactly 1 pending request, 0 punches |
| `REG-POL-001`, `PER-WOL-001`, `ATT-DAY-008` | PASS (existing tests only) | Project tests passed; not re-derived by QA |
| `REG-LOCK-001`, `PER-LOCKED-001` | PASS | Closed period: recalculate, punch, regularization, roster -> 409 `ATTENDANCE_PERIOD_CLOSED`; all DB counts/versions unchanged |
| `PER-LIFE-001` | PASS | Pending request -> BLOCKED `PENDING_REGULARIZATION`, finalize 409, nothing locked; after reject READY -> CLOSED; 5 days locked; actions OPENED, VALIDATION_FAILED, VALIDATED, CLOSED |
| `PER-RECON-001` | PASS | Mixed week: present 2, absent 3, lop 3, paid 2, payable 5, buckets 5.00 = calendar days; joiner/leaver week: present 2, not_employed 3, payable 2, buckets 5.00; paid+lop+unpaid_off = payable in both |
| `PER-LOCK-001` | PASS | INCOMPLETE 0.00/0.00 before close -> lop 1.00 at close, 1 audit row, label unchanged |
| `PER-REOPEN-001` | PASS (scope-limited) | Reason required (422); days unlock; **no recompute** (versions/minutes/fractions unchanged); REOPENED action. BUS-008 block-after-payroll not tested (no payroll in B2) |
| `PER-LE-001` | PASS (scope-limited) | Same-entity overlap 409; other entity 201; each employee only in own entity's summary. Mid-month transfer not tested |
| `ATT-DAY-005` | PASS | HOLIDAY/WEEKLY_OFF NOT_EXPECTED paid 1.00; holiday on weekly off keeps WEEKLY_OFF + flag; special working day expects presence; work on holiday PRESENT 540 flagged |
| `ATT-DAY-006` | PASS | Night shift: 485 worked on the start date, 0 on the next date, one DB row carries the minutes |
| `ATT-DAY-007` | PASS (scope-limited) | Idempotent recalculation (B1) + locked-day refusal with unchanged versions (B2) |
| `ATT-DAY-009` | PASS | NOT_JOINED / EXITED paid 0 lop 0; summary not_employed 3; punches outside employment 422 and not stored |
| `ATT-DAY-010` | PASS | Out-of-window punch reported as orphan, anchors not reported, nothing altered |
| `ATT-PUNCH-008` | PASS | `PUNCH_TIME_BEFORE_EMPLOYMENT`, `EMPLOYEE_TERMINATED` (422) |
| `ATT-PUNCH-007` | NOT_RUN | Business-date/timezone case not written (needs a non-UTC company and shift; CL-17) |

**Defects found by B2:** none in the product. QA-side bugs fixed during development of the tests: wrong calendar-exception endpoint, FK-order in my own teardown, and the observation that the period summary preview only lists employees that already have attendance rows (by design; employees without rows block finalize).

## 20. The two open business decisions (still open, not decided here)

| ID | Question | Evidence now available |
|---|---|---|
| OPEN-1 | Is 09:15 (exactly the grace minute) on time? | B1 `ATT-DAY-002`: with grace_in 15, 09:15 gives `late_minutes 0`, not late; 09:20 gives 5. The engine counts minutes strictly after grace; the V1 document gives only the 09:14/09:20 examples. Owner to confirm intent (CL-16) |
| OPEN-2 | Should a working day with no punches keep LOP 0.00 until period close? | B1 + B2 (`OPEN-2.jsonl`): such a day is INCOMPLETE with paid 0.00 / lop 0.00 until close, then lop 1.00. Approved decision 16 (PAYROLL_BUSINESS_DECISIONS) and the project's period test describe resolution *at close*; the open question is only whether anything that reads attendance *before* close (dashboards, a payroll preview, a live-period payslip) may treat 0.00/0.00 as zero LOP. Owner to confirm (CL-16) |

## 21. Blockers and not-covered items

* No blocker stopped B2; isolation held on both stacks; no destructive operation beyond the harness's own teardown.
* Not covered: `ATT-PUNCH-007` (timezone), BUS-008 reopen-after-payroll, mid-month legal-entity transfer, night-OT classification (CL-10), overtime cases (`OT-*`, B3), shifts/policies depth (B3), leave depth/payroll (B4/B5).
* Flutter, disk (`/` 99 %) and stale venv blockers unchanged (`ENV-FLUTTER-001`, `ENV-DISK-001`, `ENV-VENV-001`).

## 22. Resources and readings (B2)

Containers `qa-b2-20261025{a,b}-{net,pg,redis,minio}` + `--rm` runners; 0 networks, volumes 46 -> 46; DB size 75 MiB, MinIO 1 MiB, artifacts 96 KiB; root free 5,618,536 -> 5,617,804 -> 5,618,196 KiB (no unexpected growth; the ~9 MB fall since the previous report happened outside these runs); MemAvailable 5.5-5.8 GB; swap 1.33 GB unchanged; both stacks removed (0 labelled containers left), shared `hrms-*` containers untouched.

## 23. Status snapshot after B2

192 cases: PASS 35 · FAIL 3 (`ATT-PUNCH-006` K-1 product defect; `ENV-DISK-001`, `ENV-VENV-001`) · BLOCKED 8 (Flutter) · NOT_RUN 139 · NOT_APPLICABLE 7. Three PASS rows rest on existing project tests only (`REG-POL-001`, `PER-WOL-001`, `ATT-DAY-008`). PASS means the observed behaviour matched the stated expectation in this isolated sandbox; it is not a statement about production or about untested rules.

---

# Phase 3d - B3 (2026-10-26, 00:00-00:03 UTC)

Same approved isolated procedure (`ISOLATION PROVED` on both stacks), no grant change, no role-script rerun, no full regression, no shared data, nothing committed. Runs: `b3-20261026a` (dev iteration: two of my own tests failed - wrong publish token for a second policy version, and a teardown order that left rows behind; evidence kept) and `b3-20261026b` (authoritative, fresh stack). Evidence: `/media/varun/varun12/work/staff-spectrum/qa_runs/b3-20261026b/{artifacts,logs}`.

**Host note (not caused by QA):** between B2 and B3 the machine was restarted (`uptime -s` shows a boot after the B2 session; swap fell from 1.33 GB to 0, MemAvailable rose to ~12 GB, and the shared `hrms-*` containers show uptime ~26 min via their restart policy). QA never stopped, restarted or touched those containers; all of B2/B3 teardown was label- and name-scoped. Root free space was 5.81 GB at the start and end of B3.

## 24. B3 results

Commands: `stack.sh pytest b3-20261026b /qa/b3/test_b3_attendance.py -p tests.conftest -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml -q -rA` (**5 passed**, 3.8 s) plus, as supplementary evidence only, 7 existing project files (`test_shift.py`, `test_shift_version.py`, `test_workforce_calendar.py`, `test_shift_roster.py`, `test_overtime_record.py`, `test_attendance_policy.py`, `test_policy_resolution.py`): **108 passed**.

| Case | Status | Verified |
|---|---|---|
| `POL-RESOLVE-001` | PASS | Winner after each assignment = the newly assigned more specific level through LEGAL_ENTITY, BRANCH, DEPARTMENT, DESIGNATION, SHIFT, EMPLOYEE (V1 order); the EMPLOYEE policy's grace 5 is what the calculation applies (09:10 = 5 late) and the day row stores that version. GRADE level untested |
| `POL-VERSION-001` | PASS | Effective dating: same 09:20 arrival = 20 late before the v2 start date, 0 after; each day references the version in force; edit of a published version refused (409 `POLICY_VERSION_NOT_DRAFT`), value unchanged. Publishing a second version requires `expected_previous_version` |
| `ATT-PUNCH-007` | PASS (scope-limited) | Shift-version timezone `Asia/Kolkata` honoured (IST day PRESENT 540; UTC control INCOMPLETE; day row timezone IST). Company/branch/legal-entity zone sources, DST and non-UTC host not tested - CL-17 open |
| `SHIFT-ROSTER-001` | PASS | Draft roster ignored and blocks close (`UNPUBLISHED_ROSTER`); published roster defines the schedule (480) |
| `OT-DETECT-001`, `OT-APPR-001` | PASS | 25 min below threshold -> no record; 80 -> 60 (rounded down), pending not shown as approved; HR approval -> record and day 60; recompute detects 120 but the decided 60 is frozen |
| `SHIFT-DEF-001` | PASS (existing tests only) | Project shift tests passed; not re-derived |

K-1 counters after B3: `punch` 71 inserts / **0 updates**, `attendance_period_action` 2 / 0.

Not run in B3 (blocked on open decisions or out of scope): `OT-ELIG-001` (CL-09), `OT-CLASS-001` (CL-10), `OT-LEAVE-001`, `OT-COMP-001` (CL-08), `SHIFT-ASSIGN-001`, `SHIFT-ROSTER-002`, `SHIFT-FLEX-001`, `POL-INERT-001` (browser), ND-02.

## 25. Status snapshot after B3

192 cases: PASS 42 · FAIL 3 (`ATT-PUNCH-006` K-1; `ENV-DISK-001`, `ENV-VENV-001`) · BLOCKED 8 (Flutter) · NOT_RUN 132 · NOT_APPLICABLE 7.

---

# Phase 3e - B4 (leave) and review (2026-10-26, 00:08-00:12 UTC)

Same approved procedure and gates (`ISOLATION PROVED`, no grant change, no role-script rerun, no full regression, no shared data, nothing committed). Runs: `b4-20261026a` (development iteration: two of my own tests failed - an 7-character idempotency key and a balance lookup that picked the wrong leave type; evidence kept) and `b4-20261026b` (authoritative). Evidence: `/media/varun/varun12/work/staff-spectrum/qa_runs/b4-20261026b/{artifacts,logs}`.

## 26. B4 results

Commands: `stack.sh pytest b4-20261026b /qa/b4/test_b4_leave.py ...` (**8 passed**, 5.8 s; the BUS-006 test was extended once with the `excess_as_lop` path and re-run, passed) and, supplementary only, 15 existing leave test files (**129 passed**, 57 s).

| Case | Status | Verified state / invariant |
|---|---|---|
| `LEAVE-APPLY-001` | PASS | AUTO apply: balance 20 -> 19; ledger = opening +20 and one -1; one application; one projection |
| `LEAVE-APPLY-002/003` | PASS | Replay returns same application; same key + different body 409; overlap 409; over-balance 422; ledger and application count unchanged |
| `LEAVE-APPLY-004` | PASS | end<start 422; Sunday-only 422 (nothing charged) - partial answer to CL-03 |
| `LEAVE-APPR-001/002/003` | PASS | HR chain: pending shows balance 10.00 / reserved 2.00 (**the corrected LV-28 assertion holds**); employee decisions 403; stale If-Match 409; approval debits exactly 2; double approve 409 with no second debit; reject writes no ledger row and releases reservation; cross-tenant 404 |
| `LEAVE-APPR-004` | PASS | Competing pending requests: second approval refused 409 `LEAVE_APPLICATION_BALANCE_SHORTFALL`; with `excess_as_lop` it is approved with 1.00 LOP and only the covered day debited; never negative |
| `LEAVE-CANCEL-001/002` | PASS | Cancel approved: one offsetting +1.00 credit, originals untouched, second cancel refused; pending cancel touches no ledger |
| `LEAVE-CONC-001` | PASS | 6 parallel 4-day requests vs 20 -> exactly 5 approved, balance 0.00; 6 parallel identical dates -> exactly 1 accepted; ledger == balance |
| `LEAVE-LEDGER-001` | PASS | API balance == SUM(ledger) at ~30 checkpoints; runtime role cannot UPDATE/DELETE the ledger or action tables (matrix identical to B1) |
| `LEAVE-LOCK-001` | PASS | Closed attendance period: approval and new applications refused 409 `LEAVE_APPLICATION_PERIOD_CLOSED`; ledger, application and projections unchanged |
| `LEAVE-POL-001`, `LEAVE-YEAR-001`, `LEAVE-ENC-001` | PASS (existing tests only) | 129 project tests; not re-derived by QA |

Counters after B4 (fresh DB): `leave_ledger` 296 inserts / **0 updates**; `leave_application_action` 179 / 0; `punch` 8 / 0. Disk: root free 5,764,924 -> 5,756,596 KiB; MemAvailable ~10 GB; swap 0; volumes 46 -> 46; both stacks removed, shared containers untouched (their ~36 min uptime dates from the host restart noted in section 24).

Not covered in B4: comp-off lifecycle (`LEAVE-COMP-001`, CL-08), manager/HOD approval chains and reassign-approver beyond the project tests, probation/maternity/statutory-minimum rules (customer/compliance inputs), a 0.5-day LOP remainder, accrual/year-end oracle (BUS-013 numbers are policy inputs).

## 27. Review of evidence and defect register after B4

Checks made against `QA_TEST_CASES.csv` and `QA_DEFECT_REGISTER.md`:

* **Status integrity:** 192 cases: PASS 58 · FAIL 3 · BLOCKED 8 · NOT_RUN 116 · NOT_APPLICABLE 7. **Five PASS rows rest only on existing project tests** whose assertions QA did not re-derive (`ATT-DAY-008`, `REG-POL-001`, `SHIFT-DEF-001`, `LEAVE-POL-001`, `LEAVE-YEAR-001`; plus `PER-WOL-001`, `LEAVE-ENC-001` marked in their text). They are PASS in the sense "executed and green in the sandbox", not "independently verified". By priority: P0 47 PASS / 75 NOT_RUN / 2 FAIL / 4 BLOCKED.
* **Defects:** one product defect open and confirmed (**K-1**: UPDATE+DELETE granted on three immutable-history tables; evidence now spans B1-B4 with 0 observed updates in ~300 tests and no code path that needs them). No new product defect from B2, B3 or B4. QA-side defects: all found were in QA's own tests and are fixed; `QA-EVID-02` (vacuous `LV-28`) is now resolved by running the replacement.
* **Open clarifications changed by evidence:** CL-03 (partly answered), CL-25 (observed whole-day behaviour), CL-16 items OPEN-1/OPEN-2 unchanged. New observations OBS-LEDGER-01, OBS-IDEM-02, OBS-PUNCH-01 added; none is a defect until the owner decides.
* **Unchanged environment blockers:** `ENV-DISK-001` (root 99 %), `ENV-VENV-001` (stale venv shebangs), Flutter. `ENV-GRANT-001` (role-script rerun) still unauthorised and unmeasured.
* **What the 75 P0 NOT_RUN cases are:** auth/tenant/RBAC/ABAC security re-verification (25: previously only inherited live results), payroll (22), platform console (8), background jobs (5), documents/storage (3), onboarding/employee/PII (4), others (8).

## 28. Decision: B5 or B6

* **B5 (payroll)** is only partly unblocked. The calculation-oracle cases (`PAYROLL-CALC-*`, `PAYROLL-STAT-001`, `PAYROLL-TDS-001`) cannot get a PASS/FAIL until the owner answers CL-04 (rounding of prorated lines), CL-05 (DA in the OT base) and CL-06 (who verifies statutory rates/TDS and supplies FY values). The run-lifecycle cases (state machine, maker-checker, PD-2/PD-4, payslip visibility, authz) do not need those answers but need a closed attendance period, salary structures and *verified* statutory rates, i.e. a long setup.
* **B6 (platform console + tenant isolation)** has no open owner dependency, covers 8 P0 cases never exercised (the live pass ran with approval OFF), and re-verifies the P0 security cases that currently rest only on inherited results.
* **Recommendation: proceed to B6 next** (scope: platform lifecycle with `COMPANY_APPROVAL_REQUIRED=true`, token separation both ways, audit append-only, status-based access, plus an independent re-run of tenant isolation/RBAC/auth P0 checks as DB-verified tests). Run B5 in two steps afterwards: B5a lifecycle/guards now, B5b oracle after CL-04/05/06 are answered.

## 29. B6 results - platform console, token separation, tenant isolation, RBAC sweep, auth P0

Same approved procedure and gates (fresh stack, `ISOLATION PROVED`, no grant change, no role-script rerun, no full regression, no shared data, nothing committed). Runs: `b6-20261026a` (development iteration, kept: 8 of my first 12 tests failed for test-side reasons - refresh token is a cookie not a body field, mutations need `If-Match`, platform reasons need 3+ characters, my first append-only check ran as the owner role, empty-body sweeps hide handler-level permission checks, one count was not company-scoped) and `b6-20261026b` (authoritative, fresh stack). Evidence: `/media/varun/varun12/work/staff-spectrum/qa_runs/b6-20261026b/{artifacts,logs}`; tests `docs/testing/qa_harness/b6/test_b6_platform_tenant.py`.

Commands: `stack.sh pytest b6-20261026b /qa/b6/test_b6_platform_tenant.py -p tests.conftest -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml -q` -> **13 passed, 3 xfailed** (14.3 s). The 3 `xfail(strict=True)` tests are the three confirmed product defects; they will turn red the day a defect is fixed. Supplementary, existing project tests only: platform (28) + auth / route matrix / route robustness / cross-tenant / permission matrix / account invite / security = **266 passed** (90 s).

Two choices that make B6 stronger than the project's own suite: the platform tests run with `COMPANY_APPROVAL_REQUIRED=true` (the live pass ran it OFF), and the isolation probes switch the application's engine to the real runtime role `hrms_app` (the project's suite runs the API as the table owner, so RLS is not active in most of its tests).

| Cases | Result |
|---|---|
| `PLAT-AUTHZ-001` | PASS. 335 operations; exactly the 20 expected public ones; anonymous -> 401 on all 315 secured; tenant admin token on all 24 platform operations and platform token on all 291 tenant operations -> 401/403, 0 accepted |
| `PLAT-LIFE-001` | PASS. All 30 status x action combinations match the diagram; every illegal one 409 with the status unchanged; reasons / typed name enforced |
| `PLAT-ACCESS-001` | PASS. Per-status sign-in/read/write/refresh table matches `PLATFORM_CONSOLE.md`; effect on the same token at the next request |
| `PLAT-AUDIT-001` | PASS. One platform audit row and one tenant audit row per action; refused actions write nothing; UPDATE/DELETE/TRUNCATE denied to `hrms_app`, UPDATE/DELETE denied to the owner by the trigger. **Observation:** the owner can TRUNCATE (OBS-AUDIT-TRUNC) |
| `PLAT-SUB-001` | PASS with observations: two trial clocks diverge when the trial is extended while SUSPENDED (OBS-TRIAL-01); nothing moves TRIAL -> ACTIVE or enforces expiry (CL-26) |
| `PLAT-LOG-001` | PASS (anonymous/tenant refused, traversal-shaped channels refused, limit bound); redaction of real log lines relies on the project's own tests |
| **`PLAT-ADMIN-001`** | **FAIL - DEF-B6-03.** Self-disable, session revocation on reset/disable work; two admins disabling each other concurrently left **zero active platform admins in 7 of 8 attempts** |
| `TEN-ISO-001`, `TEN-LIST-001` | PASS. As `hrms_app`: tenant B gets 404 (never 403/409) on A's employee, documents, leave application (read/cancel/approve/reject), pay run (read/delete/approve); lists disjoint; A's row counts and employee-table fingerprint unchanged |
| `TEN-ISO-002` | PASS, scope-limited (imports, regularization requests, onboarding cases, payslips not exercised cross-tenant) |
| **`TEN-HDR-001`** | **FAIL - DEF-B6-01.** Owner role matches the docs; runtime role: header omitted -> 422 `INVALID_VALUE`, mismatched -> 401 `INVALID_TOKEN`, documented as optional / 404. No leak |
| `RBAC-MATRIX-001`, `RBAC-ESS-001` | PASS (scope-limited, see the case rows): EMPLOYEE on 287 operations -> 234 x 403, no 5xx/401, no row changes; handler-level permission routes 403 for valid bodies |
| **`RBAC-ESS-002`** | **FAIL - DEF-B6-02.** Peer data is correctly SELF-scoped everywhere tested **except** `GET /v1/attendance-periods/{id}/summary`, which returns every employee's attendance, LOP, payable and overtime figures to any employee |
| `AUTH-LOGIN-001..004`, `AUTH-TOKEN-001`, `AUTH-REFRESH-001`, `AUTH-LOGOUT-001` | PASS, DB-verified: refresh token only as HttpOnly cookie and stored hashed; unverified e-mail 403; no enumeration; 5th failure locks (423) with `locked_until` ~15 min; forged / `alg:none` / payload-swapped / expired tokens 401; rotation, reuse detection revoking the family, logout revoking the session |
| `AUTH-RESET-001/002`, `AUTH-VERIFY-001`, `AUTH-RATE-001`, `AUTH-INVITE-001`, `AUTH-LINK-001` | PASS on **existing project tests only** (assertions not re-derived) |

Not run in B6: `PLAT-UI-001` (needs the web app, B8), `AUTH-RATE-002` (needs a Redis outage), `AUTH-LOGIN-005`, `AUTH-INVITE-002` (Flutter fixtures), `RBAC-ADM-001`, `RBAC-MGR-001`, `TEN-DEL-001`, a per-permission truth table for the attendance / leave / payroll / onboarding routers.

## 30. Resources and readings (B6)

* Preflight, `up`, `guard` (**ISOLATION PROVED**), `migrate` (head `20261022090000`) for both stacks; each stack removed with `down --confirm` (only containers labelled for that run, plus its data directories; artifacts kept). Labelled containers left: 0. Shared `hrms-postgres / hrms-redis / hrms-minio` untouched (up 4 h at the end).
* Root free about 5.75 GB before and 5.5 GB after (the 3 GiB hard minimum was never approached); memory healthy throughout; no unexpected growth.
* No grant was changed, `002_app_role.sh` was not rerun, no DDL probe, no full regression. Test harness change: one mount (`/qa/b6`) added to `stack.sh`.
* Counters (read-only snapshots, `stats_before/after.txt`) after the B6 run: `punch` 3 inserts / 0 updates, `attendance_period_action` 1 / 0, `attendance_regularization_action` 0 / 0 - the K-1 tables again show no update or delete.
* Working tree: 160 uncommitted entries, as before; nothing committed or pushed.

## 31. Review of evidence and defect register after B6

* **Status integrity:** 192 cases: PASS 82 · FAIL 6 · BLOCKED 8 · NOT_RUN 89 · NOT_APPLICABLE 7. FAIL = K-1 (`ATT-PUNCH-006`), DEF-B6-01 (`TEN-HDR-001`), DEF-B6-02 (`RBAC-ESS-002`), DEF-B6-03 (`PLAT-ADMIN-001`) and the two environment cases (`ENV-DISK-001`, `ENV-VENV-001`). P0: PASS 71 · NOT_RUN 48 · FAIL 5 · BLOCKED 4. **Six PASS rows added by B6 rest only on existing project tests** (`AUTH-RESET-001/002`, `AUTH-VERIFY-001`, `AUTH-RATE-001`, `AUTH-INVITE-001`, `AUTH-LINK-001`), and `PLAT-LOG-001` / `RBAC-MATRIX-001` / `TEN-ISO-002` are explicitly scope-limited in their rows.
* **New product defects (all VERIFIED, none fixed by QA):** DEF-B6-02 (High: any employee can read all employees' attendance-period summaries), DEF-B6-03 (Medium: platform can be left with no active admin), DEF-B6-01 (Low-Medium: `X-Company-Id` contract differs under the runtime role). K-1 unchanged. New observations: OBS-AUDIT-TRUNC, OBS-TRIAL-01, OBS-EMP-ROLE-01, OBS-TEST-ROLE-01 (the project's suite runs as the owner role and therefore cannot see DEF-B6-01 or RLS-dependent behaviour). New clarifications CL-26, CL-27; CL-02 and CL-03 updated.
* **Why the earlier inherited result was not enough:** the live pass and the project's suite both reported the tenant/RBAC areas green; two of the three new defects are only visible with data from two real employees in one tenant (DEF-B6-02) or under the real database role (DEF-B6-01).
* **Remaining P0 NOT_RUN (48):** payroll 24, background jobs 5, employee 3, documents/storage 3, web 3, RBAC 2 (`RBAC-ADM-001`, `RBAC-MGR-001`), attendance 2, and singles (auth Redis outage, platform UI, leave, overtime, observability, environment).

## 32. Next-step options

* **B7 - background jobs and storage** (5 + 3 P0): Celery tasks and event loop (DEF-02 fix verification), documents/storage with the private MinIO, restart behaviour. No owner dependency; needs the worker started inside the sandbox.
* **B5a - payroll lifecycle/guards** (no oracle numbers) and **B5b - payroll calculations** (blocked by CL-04/05/06).
* **B8 - web and mobile** (3 + Flutter): blocked by the Flutter toolchain (A2) and a private web build.
* **Fix verification** (after the owner decides): DEF-B6-02 first; the strict-xfail tests flip automatically.
* Still requiring separate approval: `002_app_role.sh` rerun and the K-1 REVOKE decision, DDL usage probe, full regression, Flutter install, tooling changes.

## 33. B7 results - background jobs, Beat schedule, storage and failure recovery

Same procedure and gates (fresh stack, `ISOLATION PROVED`, no grant change, no role-script rerun, no DDL probe, no full regression, no shared data, nothing committed, no defect fixed). Runs: `b7-20261026a` (development iteration, kept) and `b7-20261026b` (authoritative, fresh). Evidence: `/media/varun/varun12/work/staff-spectrum/qa_runs/b7-20261026b/artifacts` (per-case JSONL, `worker_*.log`, `b7_main_run.txt`, `b7_existing.txt`, `stats_before/after.txt`). Tests: `docs/testing/qa_harness/b7/test_b7_jobs.py`, `test_b7_storage.py` (one mount `/qa/b7` added to `stack.sh`).

Commands: `stack.sh pytest b7-20261026b /qa/b7/test_b7_jobs.py /qa/b7/test_b7_storage.py -p tests.conftest -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml -q` -> **18 passed, 1 xfailed** (87 s; the xfail is strict and is DEF-B7-01). Supplementary, existing project tests only: celery routing/registration, job health, attendance and leave task tests, accrual, comp-off, employee and onboarding documents and upload bounds, employee import, termination -> **123 passed** (46 s). `tests/integration/core/test_storage.py` was deliberately NOT run (it contains an opt-in `docker restart` test).

How it was done: a **real Celery worker** (prefork) was started inside the runner on the private Redis broker through `entry.py` (so the strict isolation check ran for it); Beat was not started (it fires on the wall clock) - the schedule was inspected and evaluated against a stubbed clock; leave tasks used a patched `business_today` where a date had to be controlled; "dead" dependencies are loopback ports with no listener (connection refused) in the sandbox's own network namespace - no container was stopped, no shared service touched; email goes to the logging provider (nothing sent).

| Case | Status | Result |
|---|---|---|
| `JOB-BEAT-001` | PASS | 10 schedule entries all map to registered tasks and declared queues; import routed to `reports_exports`; Asia/Kolkata; due times correct under a stubbed clock incl. 31 Dec / 1 Jan |
| `JOB-LOOP-001` | PASS | DEF-02 fix verified: real single-process worker ran 7 tasks of three modules plus an API-dispatched import; no loop error, no traceback |
| `JOB-RETRY-001` | PASS | 4 attempts then FAILURE + `leave_task_failed`; logic error 1 attempt; recovery; rollback leaves no partial rows; bad inputs; fan-out isolation; malformed payloads do not wedge a real worker; **worker SIGKILL: leave task redelivered and credited once, attendance task lost (OBS-JOB-01)**; broker publish failure on import -> 503 and batch FAILED |
| `JOB-IDEM-001` | PASS (scope-limited) | accrual twice, 6 deliveries on 4 processes, window boundary, year transition, tenant scoping, fan-out eligibility; other tasks rest on existing tests |
| `JOB-HEALTH-001` | PASS | ready/live normal; Redis down -> ready 503 / live 200; `job_health` CLI exit 0 fresh, 1 stale |
| `DOC-UP-001` | PASS | 14-sample matrix: rows == objects == accepted; content/type/key checks; never 5xx |
| `DOC-XT-001` | PASS | other tenant and peer employee refused (404/403), no URL in refusals, storage and rows unchanged |
| `DOC-DL-001` | PASS | SHA-256 equal; tampered/unsigned 403; 2 s URL expires; dangling metadata observed |
| **`DOC-STORE-001`** | **FAIL** | Dead storage handled cleanly (stable 500 envelope, 0 rows/batches, recovers). **DEF-B7-01:** a database failure after the object write leaves an orphan object; after the object delete leaves a dangling row |
| `AUTH-RATE-002` | BLOCKED | Needs decision CL-28: the limiter fails open (valid login 200; account lockout still works) |

First-run failures and harness corrections (all test-side; none was a product defect): wrong schedule count in my assertion (10, not 11), `autoretry_for` attribute missing on tasks without autoretry, router lookup for the import queue (the queue is a task option), ledger/import queries not company-scoped (the owner role bypasses RLS), teardown order (`attendance_day`, `leave_ledger`, import tables before employees), one assertion that ignored the two employees the concurrent import adds, the repository class name for documents, and `asyncio.run` inside a running loop (task bodies are executed in a worker thread with the shared engine disposed on both sides). First-run evidence is kept in `b7-20261026a`.

Not tested / blocked: the real Beat process; `attendance.run_incomplete_reminders` (sends e-mail), `attendance.run_face_cleanup` / `run_face_deletions` (face engine off); comp-off credit/expiry, year-end carry-forward and the termination sweep with data (existing project tests only); attendance partial-failure and soft-time-limit (existing tests only); payroll has no background tasks; a full worker/broker loss and the Redis visibility timeout; black-holed (timeout) dependencies; transient database errors at the API layer; a literal container stop of MinIO/Redis (refused port used instead); onboarding public document endpoints and import file bounds (existing tests only); the ONB-*/EMP-* P0 cases of the B7 plan row (not part of this batch's brief).

## 34. Resources, isolation and teardown (B7)

* `preflight` (root 5.5 GB free, above the 3 GiB minimum; never near 2 GiB), `up`, `guard` -> **ISOLATION PROVED** for both stacks, `migrate` to head `20261022090000`. Memory 15.8 GB total with 1.8-3.2 GB free and 8 GB reclaimable during the runs, swap unused.
* Teardown by `down --confirm` for each run: 0 containers labelled `qa.run` remain, 0 networks with a `qa-` name, Docker volumes unchanged (46), shared `hrms-postgres / hrms-redis / hrms-minio` up 5 hours throughout (not restarted). No grants changed; `002_app_role.sh` not rerun; no DDL probe. External calls: none possible (loopback-only namespace), e-mail via the logging provider.
* K-1 counters (read-only) after the B7 run: `punch` 24 inserts / 0 updates, `attendance_period_action` and `attendance_regularization_action` 0 / 0 - no update or delete again.
* Working tree: `git status` shows 167 entries (160 at the start of B7). The seven extra entries are not from QA (brand assets, mobile and web files, `start-mobile.sh`, `start-web.sh`, modified `pubspec.yaml`): other work is being done in this repository at the same time. QA changed only files under `docs/testing/` (`qa_harness/stack.sh` mount, `qa_harness/b7/`, `qa_catalogue_src/results_phase3.py`, regenerated CSV/MD, this file, the defect register). Nothing committed, pushed or deployed.

## 35. Review after B7

* **Status integrity:** 192 cases: PASS 90 - FAIL 7 - BLOCKED 9 - NOT_RUN 79 - NOT_APPLICABLE 7. P0: PASS 78 - NOT_RUN 39 - FAIL 6 - BLOCKED 5. Previous B1-B6 rows unchanged; DEF-02 note updated (fix verified).
* **New product defect:** DEF-B7-01 (Low-Medium). Open defects overall: K-1, DEF-B6-01/02/03, DEF-B7-01 (none fixed by QA). New observations OBS-JOB-01/02, OBS-DOC-01/02, OBS-AUTH-REDIS-01; new clarification CL-28.
* **Remaining P0 NOT_RUN (39):** payroll 24; employee/onboarding 3; web 3; RBAC-ADM/MGR 2; attendance 2; and singles. Background jobs and documents P0 are now all run.
* **Recommended next batch:** B5a (payroll run lifecycle and guards, no oracle numbers; 24 P0 cases is the largest remaining block, and payroll consumes the attendance and leave results verified in B2-B4), with B5b (calculations) waiting for CL-04/05/06; in parallel the owner should decide on DEF-B6-02 (highest severity open defect). A small separate batch could cover the per-permission matrix and HR-admin/manager scopes (RBAC-ADM-001, RBAC-MGR-001). This does not establish production readiness.

## 36. B5a results - payroll run lifecycle, guards, concurrency, immutability, tenant isolation

Same procedure and gates (fresh stack, `ISOLATION PROVED` before every run, no grant change, no role-script rerun, no DDL probe, no full regression, no shared data, no defect fixed, nothing committed). **Scope is lifecycle and guards only**: no `PAYROLL-CALC-*`, `-STAT`, `-TDS`, `-NET`, `-ARR` case was run and no amount is asserted; lifecycle fixtures are synthetic. The owner's CL-04 decision (**no rounding during calculation, full precision**) is recorded; `PAYROLL-CALC-004` (needs CL-05) and `PAYROLL-STAT-001` / `PAYROLL-TDS-001` (need CL-06) are now marked BLOCKED with that reason.

Runs: `b5a-20261026a` to `-e` were development iterations (evidence kept), `b5a-20261026f` is authoritative. Evidence: `/media/varun/varun12/work/staff-spectrum/qa_runs/b5a-20261026f/artifacts/{PAYROLL-*.jsonl,b5a_main_run.txt,b5a_existing.txt,stats_before.txt,stats_after.txt}`. Tests: `docs/testing/qa_harness/b5/test_b5a_payroll_lifecycle.py` (one mount `/qa/b5` added to `stack.sh`).

Commands: `stack.sh pytest b5a-20261026f /qa/b5/test_b5a_payroll_lifecycle.py -p tests.conftest -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml -q` -> **14 passed, 1 xfailed** (14 s; the xfail is strict and is DEF-B5A-01). Supplementary, existing project tests only: `tests/integration/modules/payroll` -> **68 passed** (46 s).

How: lifecycle driven through the real API; after every step the database is queried and compared (status, version, updated_at, totals, employee-row and line counts, audit count). Refused operations are compared with a before/after snapshot. The full run to PAID and the guard matrix ran with the application engine connected as the runtime role `hrms_app`. A real attendance period close (calculate range, create, validate, finalize) is used for the prerequisite and reconciliation cases; the other cases use the project's closed-period fixture insert, which the project documents as a test shortcut.

| Case | Status | Result |
|---|---|---|
| **`PAYROLL-FLOW-001`** | **FAIL** | State machine fully correct (every illegal action in every state -> 409, DB unchanged; versions, audit, rollbacks, create guards, parallel creates, interrupted operations all as designed). **DEF-B5A-01:** create accepts a pay date before month end that PATCH refuses |
| `PAYROLL-FLOW-002` | PASS | no period / OPEN period / other legal entity -> 409 NOT_CLOSED; real close pins period id and version; reopen -> approve blocked ATTENDANCE_CHANGED; recovery path works |
| `PAYROLL-FLOW-003` | PASS | full run to PAID as `hrms_app`, API == DB at each of 5 steps, audit trail exact, run totals == sum of employee rows |
| `PAYROLL-FLOW-004` | PASS | maker-checker follows the last computer; approver may also finalise / pay (OBS-PAY-02) |
| `PAYROLL-FLOW-005` | PASS | input change after lock -> 409 INPUTS_CHANGED, run unchanged; re-lock recovers |
| `PAYROLL-FLOW-006` | PASS (scope) | variance flag blocks approval until a reason is stored; exact 15.00 % boundary untested (CL-07) |
| `PAYROLL-FLOW-007` | PASS | 8-way races on lock/compute/approve/finalise/mark-paid: exactly one winner, no duplicate rows or audit entries; conflicting approve/rollback/recompute: one winner; parallel delete: one. **OBS-PAY-01:** parallel lock-inputs losers get 503 DATABASE_BUSY |
| `PAYROLL-FLOW-008` | PASS | `hrms_app` UPDATE/DELETE on FINALISED / PAID pay_run, pay_run_employee, pay_run_line refused by DB triggers; API mutations of a PAID run all 409 |
| `PAYROLL-AUTHZ-001` | PASS (scope) | 20 probes x 8 principals as `hrms_app` match the documented permission model; denied calls change nothing; tenant B gets 404 on every verb against tenant A's run |
| `PAYROLL-SLIP-001` | PASS | employees see payslips only from FINALISED runs, only their own |
| `PAYROLL-ADJ-001` | PASS | key required (422), replay same row, changed body 409, parallel same key one row, parallel different keys never exceed payable days |
| `PAYROLL-BANK-001` | PASS | only COMPANY_ADMIN and only after FINALISED; CSV escaping; formula-leading name neutralised; one audit row per download |
| `PAYROLL-PIN-001` | PASS (scope) | snapshot paid/payable/lop == frozen summary for one employee after a real close |

Harness failures before the authoritative run (all test-side, evidence kept in runs a-e): wrong column name (`pay_run_id`, not `run_id`); under `hrms_app` raw queries need the RLS company scope on the connection (unscoped queries fail with `invalid input syntax for type uuid: ""`); my first authz probes were mutating (changed to non-mutating stale-`If-Match` probes); the suite's test client auto-injects an Idempotency-Key (bypassed for the no-key case); a real period close needs an employee wired with shift, calendar and policy (otherwise CONFIG_ERROR blocks validation); compensation revisions require `If-Match` and `revision_type` `ANNUAL`; teardown order (invites, sessions, refresh tokens, attendance assignments before employees). One tool-permission classifier outage interrupted shell commands for a few minutes; no test or stack was affected.

Not tested / blocked: calculation correctness of any amount (B5b); `PAYROLL-ARR-001`; the 15.00 % variance boundary (CL-07); statutory-rate verification gating; salary-structure, component, statutory and settings route permissions; branch-manager and other custom roles; payroll jobs (none exist); a real worker-killed mid-run payroll operation (none is asynchronous - payroll runs synchronously in the request).

## 37. Resources, isolation and teardown (B5a)

* Six disposable stacks (a-f), each `preflight` -> `up` -> `guard` (**ISOLATION PROVED**) -> `migrate` (head `20261022090000`) -> tests -> `down --confirm`. Root free space 4.4 GB throughout (it was 5.5 GB at the start of B7; other work in the repository is consuming it - above the 3 GiB minimum, never near 2 GiB); memory available 4.9-8.4 GB, swap 2 MB.
* After the last teardown: 0 containers labelled `qa.run`, 0 networks named `qa-*`, Docker volumes unchanged (46), no run data directory left, shared `hrms-postgres / hrms-redis / hrms-minio` up 5 hours (not restarted). No grants changed, `002_app_role.sh` not rerun, no DDL probe, no external calls (e-mail via the logging provider, nothing leaves the loopback-only namespace).
* K-1 counters after the run: `punch` 6 inserts / 0 updates, `attendance_period_action` 15 inserts / 0 updates, `attendance_regularization_action` 0 / 0.
* Working tree: `git status` shows 202 entries (167 at the start of B7's report, 160 before it). QA changed only files under `docs/testing/` in this batch (`qa_harness/stack.sh` one mount, `qa_harness/b5/`, `qa_catalogue_src/results_phase3.py`, regenerated catalogue CSV/MD, `QA_DEFECT_REGISTER.md`, this file). The growth is other concurrent work in the repository. Nothing committed, pushed or deployed.

## 38. Review after B5a

* **Status integrity:** 192 cases: PASS 102 - FAIL 8 - BLOCKED 12 - NOT_RUN 63 - NOT_APPLICABLE 7. P0: PASS 90 - NOT_RUN 23 - BLOCKED 8 - FAIL 7. FAIL = K-1 (`ATT-PUNCH-006`), `TEN-HDR-001`, `RBAC-ESS-002`, `PLAT-ADMIN-001`, `DOC-STORE-001`, `PAYROLL-FLOW-001` and the two environment cases. Payroll P0 lifecycle/guard cases are now run; the remaining payroll P0 NOT_RUN are all calculation cases.
* **New product defect:** DEF-B5A-01 (Low). Open defects overall: K-1, DEF-B6-01/02/03, DEF-B7-01, DEF-B5A-01 - none fixed or silently closed. New observations: OBS-PAY-01, OBS-PAY-02, OBS-TEST-IDEM-01. CL-04 recorded as decided; CL-05 and CL-06 open.
* **Positive findings worth keeping:** the payroll state machine, version checks, maker-checker, input-change detection, runtime-role immutability triggers and tenant isolation all held under parallel load and injected failures; payroll is the best-guarded area tested so far (contrast K-1 and DEF-B6-02).
* **Recommended next batch:** B5b needs your answers to CL-05 and CL-06 first (CL-04 is now settled); meanwhile the highest-value non-blocked work is (1) the permission-matrix batch (per-permission truth tables for attendance, leave, payroll setup/statutory/settings and onboarding routes plus HR-admin and manager scopes, which would also have caught DEF-B6-02), then (2) onboarding / employee lifecycle (ONB-*, EMP-* P0), then (3) web and mobile (blocked on the Flutter toolchain).

## 39. B10 results - permission matrix and data-scope security audit

Same gates (fresh stack, `ISOLATION PROVED` before every run, runtime role `hrms_app` for every check, no grant change, no role-script rerun, no DDL probe, no full regression, synthetic users only, no application code or permission changed, nothing committed). Runs: `b10-20261026a` (development iteration, evidence kept) and `b10-20261026b` (authoritative). Evidence: `/media/varun/varun12/work/staff-spectrum/qa_runs/b10-20261026b/artifacts/` (`route_authz_inventory.json`, `role_grants.json`, `B10-*.jsonl`, `b10_main_run.txt`, `b10_existing.txt`, `stats_before/after.txt`). Tests: `docs/testing/qa_harness/b10/{inventory.py,world.py,test_b10_00_world.py,test_b10_01_matrix.py,test_b10_02_scope.py,test_b10_03_admin.py,test_b10_04_custom_scope.py,test_b10_roles_dump.py}` (one mount `/qa/b10` added to `stack.sh`).

Commands: `stack.sh pytest b10-20261026b /qa/b10/test_b10_00_world.py /qa/b10/test_b10_01_matrix.py /qa/b10/test_b10_02_scope.py /qa/b10/test_b10_03_admin.py /qa/b10/test_b10_roles_dump.py -p tests.conftest -p tests.integration.modules.attendance.conftest --rootdir . -c pyproject.toml -q` -> **14 passed, 1 xfailed** (45 s); `test_b10_04_custom_scope.py` -> 1 xfailed (DEF-B10-01, with `--runxfail` the failure is the assertion that an out-of-scope adjustment was accepted). Supplementary, existing project tests only (route authorization matrix, permission matrix, leave RBAC matrix, attendance security, employee data scope, employee default role, pay run): **86 passed**. All three expected failures are `xfail(strict=True)` and were each reproduced with `--runxfail` on the same stack so that no xfail hides a harness error (one did during development: a `NOPERM` string reached a set operation; fixed, evidence kept).

### Route inventory (dependency introspection of the running app; nothing assumed from names)
| Class | Operations |
|---|---|
| Total | 336 |
| Gated by exactly one `require_permission(CODE)` | **276** (72 distinct permission codes exist; 199 of the 276 bind the returned scope to an unused `_scope` parameter, 77 use it) |
| Authenticated, permission chosen inside the handler | 15 (`/auth/me`, `/auth/companies/{id}`, policy-assignments GET/POST, employee assignments POST, regularization create/cancel, leave-types, leave-ledger, leave-balances, leave-applications create/list/detail/cancel) |
| Platform-admin | 24 (separation tested in B6 `PLAT-AUTHZ-001`) |
| Public | 21 |

### Role matrix (system roles, from the DB of a freshly registered company)
`COMPANY_ADMIN` 72 grants COMPANY - `HR_ADMIN` 32 COMPANY - `EMPLOYEE` 14 SELF - `REPORTING_MANAGER` 5 REPORTEE_TREE (attendance OT/regularization approve, EMPLOYEE.VIEW, leave approve, leave balance view-all) - `BRANCH_MANAGER` 7 BRANCH (the same plus ATTENDANCE.VIEW, EMPLOYEE.VIEW_ALL). There is no payroll-administrator system role (HR_ADMIN has RUN_PROCESS/RUN_VIEW/SETUP_MANAGE/STATUTORY_MANAGE; approve and bank advice stay with COMPANY_ADMIN). Principals exercised: anonymous; EMPLOYEE (own and colleague); REPORTING_MANAGER with assigned and unassigned employees; BRANCH_MANAGER in each of two branches; HR_ADMIN; company admin; custom payroll role (RUN_VIEW+RUN_PROCESS+SETUP_MANAGE); custom ATTENDANCE.VIEW at REPORTEES and at SELF; another tenant's admin; platform admin (B6). Reporting tree and branches: branch X = BX, M1, E1, E2 (E1, E2 report to M1); branch Y = BY, M2, E3 (reports to M2). Oracle for visibility: SELF = own; REPORTEES/REPORTEE_TREE = reportees (not self); BRANCH = employees whose current assignment is in the caller's branch; COMPANY = all; grants of one permission from several roles are unioned (`resolve_visible_employee_ids`, `RBAC_DATA_SCOPE_DECISIONS.md`).

### Results by case
| Case | Status | Result |
|---|---|---|
| `RBAC-MATRIX-001` | PASS | 276 gated operations x (anonymous + 7 principals): anonymous 401 on all; 1,932 principal probes, **0 mismatches** with the permissions the DB says each principal holds (denied -> 403, permitted -> passes the gate); denied probes left every company table - incl. audit_log, sessions, refresh tokens, idempotency keys - unchanged |
| **`RBAC-MGR-001`** | **FAIL** | Scope enforced correctly on: employee directory and 12 sub-resource families (336 cells), attendance punches/days/regularizations (lists, `?employee_id=` smuggling, direct objects), 56 out-of-scope approve/reject attempts (all 403, nothing changed), tenant isolation with real identifiers. **Fails:** attendance-period summary leak extended to BRANCH_MANAGER and custom roles (DEF-B6-02); `LEAVE.BALANCE_ADJUST` scope ignored (DEF-B10-01, latent) |
| **`RBAC-ESS-002`** | **FAIL** (unchanged) | DEF-B6-02 re-verified and extended; every other employee read is scoped |
| `RBAC-ADM-001` | PASS | HR_ADMIN ceiling holds (cannot mint COMPANY_ADMIN, cannot approve/finalise/pay, no bank advice, no user/role/org management); self-escalation by EMPLOYEE, manager, branch manager and custom roles refused; 24-29 sensitive writes per denied principal refused with zero database effect. Observations OBS-B10-01/03/04 |
| `TEN-ISO-002` | PASS (extended) | B10 added attendance, regularization, leave approve, employee records, documents, assignment writes and onboarding with real identifiers as `hrms_app` |

Other questions in the brief, answered: read-only operations - 4 payroll `GET`s seed default rows on first use (OBS-B10-01), all others change nothing; audit entries - approvals write one audit row each under the approving user (`REGULARIZATION_APPROVED`, `LEAVE_APPLICATION_APPROVED`) and denied operations write none; custom roles inherit nothing beyond their grants (the 1-permission custom roles were refused on all other 275 operations); indirect routes - handler-level routes were tested separately (leave list/detail/balances/ledger, on-behalf creation, cross-employee cancel, assignments, policy assignments: all refused or scoped, no data change); concurrency/stale versions - stale `If-Match` -> 409 with no change, repeat approval -> 409 with no second punch; export/download - bank advice is COMPANY_ADMIN only (B5a), document URLs follow the document list's scope.

Harness failures (test-side): fixture seat limit (trial plan allows 5 employees: override set in the disposable DB), `user_role` joins through `user_company`, RLS company scope needed on raw queries as `hrms_app`, approval bodies use `reviewer_comment`/`rejection_reason`, `HR_ADMIN` holds no `ATTENDANCE.VIEW` so list probes expect 403, and the xfail-masks-harness-error case above.

Not covered: overtime approve/reject, rosters and leave-projections lists with data (no fixtures built; the static inventory shows them scope-bound, the matrix proves their permission gating); comp-off; import/export beyond bank advice; payroll route data-scope (all payroll permissions are COMPANY-only, nothing to scope); platform console beyond B6; branch-manager multi-branch assignments (not expressible, documented); behaviour after a role change within a live session (permissions are resolved per request; tokens carry no roles).

## 40. Resources, isolation and teardown (B10)

* Two stacks (a, b): `preflight` (root 4.4 GB free, above the 3 GiB minimum, never near 2 GiB; memory available about 5-8 GB; swap 2 MB), `up`, `guard` -> **ISOLATION PROVED**, `migrate` (head `20261022090000`), tests, `down --confirm`. After teardown: 0 containers labelled `qa.run`, 0 networks `qa-*`, Docker volumes unchanged (46); `hrms-postgres / hrms-redis / hrms-minio` up 5 hours throughout. No grant changed, `002_app_role.sh` not rerun, no DDL probe, no external calls.
* K-1 counters (read-only) after the authoritative run: `punch` 142 inserts / 0 updates, `attendance_regularization_action` 25 / 0, `attendance_period_action` 12 / 0, `leave_ledger` 39 / 0.
* Working tree: `git status` shows 202 entries, unchanged from the end of B5a (189 outside `docs/testing`, none from QA). QA changed only: `docs/testing/qa_harness/stack.sh` (one mount), `docs/testing/qa_harness/b10/` (new), `docs/testing/qa_catalogue_src/results_phase3.py`, the regenerated catalogue CSV/MD, `QA_DEFECT_REGISTER.md` and this file. Nothing committed, pushed or deployed; no application code or permission changed.

## 41. Review after B10

* **Status integrity:** 192 cases: PASS 103 - FAIL 9 - BLOCKED 12 - NOT_RUN 61 - NOT_APPLICABLE 7; P0: PASS 91 - FAIL 8 - BLOCKED 8 - NOT_RUN 21. FAIL = K-1, `TEN-HDR-001`, `RBAC-ESS-002`, `RBAC-MGR-001`, `PLAT-ADMIN-001`, `DOC-STORE-001`, `PAYROLL-FLOW-001` and the two environment cases.
* **Defects:** DEF-B6-02 extended (still the highest-severity open item); new DEF-B10-01 (latent). All earlier defects (K-1, DEF-B6-01/02/03, DEF-B7-01, DEF-B5A-01) and OBS-JOB-01 remain open and unresolved. New observations OBS-B10-01..05, clarification CL-29.
* **What the audit shows overall:** permission gating is exact (0 mismatches in 1,932 probes) and cross-tenant isolation held with real identifiers; the weaknesses are all in *data scope on aggregate and administrative routes* - precisely where a scope parameter is accepted but not applied - plus role-definition questions. A CI guard that fails when a route ignores its scope while a restricted grant of its permission exists would have caught both DEF-B6-02 and DEF-B10-01.
* **Recommended next step (needs your decision):** fix DEF-B6-02 first (three routes, same pattern; the strict xfail tests flip when fixed); decide CL-29/OBS-B10-02. Then B5b (needs CL-05/CL-06), onboarding/employee lifecycle (`ONB-*`, `EMP-*` P0), web/mobile (Flutter toolchain).


## 42. HR_ADMIN policy implementation and scope fixes (run `hradm-20261026a`, 2026-10-26)

*Additive; sections 1-41 and every earlier run's evidence are unchanged.* Stack: fresh disposable `hradm-20261026a`, migrated to head `20261026090000` (new, additive data migration); `ISOLATION PROVED` printed before every test run below; root free 4.4 GiB throughout (gate 3 GiB start / 2 GiB stop); memory available 8.0-8.4 GB; swap 2 MB.

| Scope | Command (via `stack.sh pytest`) | Result |
|---|---|---|
| New: DEF-B6-02 | `test_period_summary_scope.py` | 3 passed |
| New: DEF-B10-01 + encashment | `test_adjustment_scope.py` | 7 passed |
| New: payroll SoD + statutory maker-checker | `test_hr_admin_separation.py` | 4 passed |
| New: grants, migration, HR_ADMIN limits | `test_hr_admin_policy_grants.py` | 3 passed |
| New: scope guard | `test_scope_enforcement_guard.py` + `test_scope_guard_live_grants.py` | 11 + 1 passed |
| Attendance (period, security, default role, period/LE, new) | 5 files | 59 passed |
| Leave (whole module dir) | `tests/integration/modules/leave` | 259 passed |
| Payroll (whole module dir) + guard | `tests/integration/modules/payroll` + guard tests | 84 passed (first run 71 passed, 1 failed: `test_p1_hardening` encoded the old edit-and-verify behaviour; fixed, re-run 24/24) |
| Organisation + account invite + onboarding | 3 dirs | 487 passed |
| Employee (lifecycle, data scope, documents) | `tests/integration/modules/employee` | 391 passed |
| B10 harness (independent verification) | 6 files, first run on fixed code with the ORIGINAL strict xfails | 13 passed, **3 failed = 2 XPASS(strict)** (DEF-B6-02 and DEF-B10-01 fixed) **+ 1 expected behaviour change** (`B10-SOD-STATUTORY`: HR_ADMIN self-verify now 403) |
| B10 harness after markers removed / assertion updated | same 6 files | 16 passed |

No skips, no xfails in the new tests. Negative controls (feature disabled on purpose, file restored byte-for-byte afterwards): summary filter removed -> 2/3 fail; leave scope check removed -> 3/7 fail; statutory check removed -> 3/4 fail. Not run: full regression suite, attendance files outside the five listed, web/mobile suites (no frontend change; both gate on `/auth/me` permissions, so HR_ADMIN sees the new pages automatically).


## 43. B11 - onboarding and employee lifecycle (run `b11-20261026a`, 2026-10-26)

*Additive; sections 1-42 and every earlier run's evidence are unchanged.* Scope, gap analysis and matrix: `QA_B11_PLAN.md`. Stack: fresh disposable `b11-20261026a` (network-none holder; Postgres 16, Redis 7, MinIO), migrated to head `20261026090000`. `ISOLATION PROVED` was printed by `stack.sh guard` before every run (`qa_evidence_b11/*.isolation.txt`) and `entry.py` re-checked it inside every runner. Gates: root free 4.4 GiB at start and throughout (>= 3 GiB to start, < 2 GiB to stop; never below 4.4 GiB), memory available 7.8-8.4 GB, swap 2 MB at start / 237 MB later (host, unrelated). No `002_app_role.sh`, no DDL probe, no GRANT change, no external e-mail (provider `logging`), no commit/push/merge/deploy, no application code changed. Only change to harness tooling: one read-only mount `b11` in `qa_harness/stack.sh`.

### Counts (exact; skipped 0 and blocked 0 in every batch)

| Batch | What | Command target | Passed | Failed |
|---|---|---|---|---|
| A (regression) | onboarding module, runtime role = owner `hrms` | `tests/integration/modules/onboarding` | 99 | 0 |
| B1 (regression) | employee lifecycle, employment, data scope, idempotency, confirmation, CRUD | 6 files | 101 | 0 |
| B2 (regression) | account invite + user access, HR_ADMIN grants/migration, scope-guard live grants, payroll separation, scope guard unit | 6 files | 54 | 0 |
| C (new) | five OBS-HRA-01 handlers, role `hrms_app` | `b11/test_b11_01_scope_exceptions.py` | 0 | **7** (each failure = confirmed defect, see register Part F) |
| D (new) | onboarding matrix, tenant, lifecycle, duplicates, concurrency, failure injection, cancel | `b11/test_b11_02_onboarding.py` | 7 | **4** |
| E (new) | employee lifecycle, per-principal authorization (176 probes), concurrency, failure injection, confirm-after-termination, HR_ADMIN ceiling | `b11/test_b11_03_employee.py` | 5 | **1** |
| F (new) | fresh-tenant role matrix, migration on existing tenants | `b11/test_b11_04_seeding.py` | 2 | 0 |
| **Total** | regression 254 passed / 0 failed; new 14 passed / 12 failed | | **268** | **12** |

The 12 failing new tests assert the correct behaviour and fail on real product defects: SG-01, SG-01b, SG-02, SG-03, SG-03b, SG-04, SG-05 (OBS-HRA-01 + DEF-B11-01); `test_duplicate_email_case_variant_blocked` (DEF-B11-05); `test_concurrent_activation_creates_exactly_one_employee` (DEF-B11-02); `test_concurrent_case_creation_creates_exactly_one_case` (DEF-B11-03); `test_failed_activation_sends_no_email` (DEF-B11-04); `test_confirm_after_termination_is_refused` (DEF-B11-06).

Harness-side failures kept as evidence (not product defects): `batchC_dev1_harness_error.log` and `batchC_dev2_teardown_residue.log` (my teardown could not delete tenant A because DEF-B11-01 had created a cross-tenant row; fixed in `b11common.drop_world11`, residue removed with `b11/cleanup_leftovers.py`), `batchD_run1_before_split.log` (assertion order / send-invite-after-ACTIVATED expectation), `batchE_run1_harness_if_match.log` (assignment changes need the current assignment's `If-Match`), `batchE_run2_harness_label.log` (confirm step mislabelled), `batchF_run1_harness_expected_32.log` (HR_ADMIN has 39 grants after the policy: 32 + 7; the 32 came from the pre-policy B10 matrix).

### Results by case

| Case | Status | Result |
|---|---|---|
| `B11-SG-01..05` | **FAIL x5** (+ SG-01b FAIL, SG-03b FAIL) | All five `known_gap` handlers confirmed to ignore the data scope (verdict 2 each, latent); calculate also has a cross-tenant write / 500 (DEF-B11-01) |
| `B11-ONB-MATRIX` | PASS | 81 probes: 8 principals + anonymous x 9 operations; granted -> passes the gate, denied -> 403 with **zero** change in any company table incl. `audit_log`/`idempotency_key`; anonymous 401 |
| `B11-ONB-TENANT` | PASS | other tenant 404 and forged `X-Company-Id` 401 on every id-route; nothing changed in either tenant; case not listed |
| `B11-ONB-LIFE` | PASS | DRAFT -> INVITED (re-invite revokes old link) -> SUBMITTED -> UNDER_REVIEW -> VERIFIED -> ACTIVATED, each persisted with an audit row; activate before VERIFIED, review/changes before submit, second submit, edit after submit, repeated activate all refused with no partial change; one employee created |
| `B11-ONB-DUP` | exact PASS / case-variant **FAIL** / observation | DEF-B11-05, OBS-B11-02 |
| `B11-ONB-CONC` | **FAIL** | DEF-B11-02 (8 employees from one case), DEF-B11-03 (8 cases, later 500) |
| `B11-ONB-FAIL` | business state PASS / e-mail **FAIL** | DEF-B11-04 |
| `B11-ONB-CANCEL` | PASS (evidence) | `ONBOARDING.CANCEL` is a stale grant; see register OBS-HRA-03 |
| `B11-EMP-LIFE` | PASS | create (PRE_JOINING) -> employment (PROBATION) -> INITIAL/TRANSFER/MANAGER_CHANGE assignments (history closed correctly, one open row) -> patch + stale patch 409 -> deactivate/reactivate -> confirm -> terminate (assignment and compensation closed, punches/attendance/bank/ledger counts unchanged, audit rows) ; invalid assignments (same date, self manager, foreign manager, foreign branch) 422 with no change; out-of-order terminate/update 409/404 |
| `B11-EMP-ISO` | PASS | 176 probes: EMPLOYEE sees only own; REPORTING_MANAGER only direct reports; BRANCH_MANAGER only its branch; denied 403 / out-of-scope 404 with zero change; list filtered (BX 4 of 7), smuggled `employee_id`/`branch_id` params ignored; other tenant 404, forged header 401/403/404, anonymous 401 on all 11 operations |
| `B11-EMP-CONC` | PASS | 8 parallel employment creates / identical assignments / terminates / deactivates: one winner each, one audit row |
| `B11-EMP-FAIL` | PASS | injected audit failure on terminate: 500, nothing changed, retry 200 |
| `B11-EMP-ORDER` | **FAIL** | DEF-B11-06 |
| `B11-PERM-HR` | PASS | 55 restricted routes (user/role admin, org, policies, lock/unlock, payroll approve/finalise/mark-paid/bank-advice) 403 with zero change; approved attendance/onboarding reads 200; invite/assign/self-assign COMPANY_ADMIN 403, no table changed. Statutory self-verify denial: regression `test_hr_admin_separation.py` passed (B2) |
| `B11-SEED-N` | PASS | fresh tenant: COMPANY_ADMIN 72 COMPANY, HR_ADMIN 39 COMPANY, EMPLOYEE 14 SELF, REPORTING_MANAGER 5 REPORTEE_TREE, BRANCH_MANAGER 7 BRANCH; `ATTENDANCE.VIEW_ALL` held only by COMPANY_ADMIN/HR_ADMIN, `ATTENDANCE.VIEW` also by BRANCH_MANAGER (BRANCH) and EMPLOYEE (SELF); `ONBOARDING.*` only by COMPANY_ADMIN/HR_ADMIN. Migration on two synthetic tenants: adds exactly the 7 HR_ADMIN rows, second run identical, narrower row (REPORTEES) and custom role untouched, downgrade/upgrade round-trip equal, 0 duplicate rows |
| `B11-ONB-REG`, `B11-EMP-REG`, `B11-SEED` (regression) | PASS | 99 + 101 + 54 |

### Resources, cleanup, git

* Teardown: `stack.sh down b11-20261026a --confirm` removed only containers labelled `qa.run=b11-20261026a` (4) and the run's `pgdata`/`minio` directories; afterwards 0 labelled containers, 0 `qa-*` networks; shared `hrms-postgres/redis/minio` still running with their original uptime. Artifacts retained: `/media/varun/varun12/work/staff-spectrum/qa_runs/b11-20261026a/artifacts/` (copied to `docs/testing/qa_evidence_b11/artifacts/`).
* Working tree: 221 paths at the very start of B11; `git_status_start.txt` (223 lines) was captured right after `QA_B11_PLAN.md` and `qa_evidence_b11/` were created and is identical to the final `git status --short` (223). `git diff --stat` is identical before and after (136 tracked files, +3826/-1682): B11 modified no tracked file. Its only edits to existing (untracked) QA files are the three append-only docs (`QA_DEFECT_REGISTER.md` Part F, this section, `QA_TEST_CASES.csv` +19 rows) and `stack.sh` (one mount).
* Not run: full regression suite, web, mobile, B5b payroll calculation (CL-05/CL-06). This section does not claim regression-complete or production readiness.

## B12 - security and integrity remediation (2026-10-26, additive)

Targeted runs only, on disposable `b12-20261026a` (head `20261026090000`), `ISOLATION PROVED` before every run, root disk 4.3-4.4 GiB free throughout. Full detail: `QA_B12_REPORT.md`; logs `qa_evidence_b12/`.

| Run | Passed | Failed | Skipped | Blocked |
|---|---|---|---|---|
| new B12 regression files + scope-guard unit | 38 | 0 | 0 | 0 |
| attendance + account_invite + route matrix (related) | 178 | 0 | 0 | 0 |
| onboarding + account_invite + units | 320 | 0 | 0 | 0 |
| employee + onboarding + account_invite + units | 719 | 0 | 0 | 0 |
| session/post-commit hook related (core, attendance, units) | 452 | 0 | 0 | 0 |

Negative controls (runtime monkeypatch, no source edits): all 7 fail the matching tests as expected. Not run: full regression, web, mobile, B5b payroll. Not a claim of regression-completeness or production readiness. Working tree 223 -> 238 paths, no baseline path lost; no commit/push/merge/deploy.


## B13 - reliability and migration readiness (2026-10-26, additive)

Disposable `b13-20261026a` (head `20261027092000`), `ISOLATION PROVED` before every batch. Targeted runs only; full table in `QA_B13_REPORT.md` section 9. New tests: outbox 15, confirm/terminate 4, seat limit 5, migrations 7, onboarding index 3, attendance FK 1; B12 group 38 passed with 6 of 7 controls failing as expected (`dup_lock` superseded by the new index); wider targeted regression 2093 passed / 1 failed (pre-existing order-dependent `test_business_events`) / 41 skipped. Not run: full regression, web, mobile, B5b. Not a claim of production readiness.
