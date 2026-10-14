# Logging, Error Handling & Reliability — Staging Readiness Report

| | |
|---|---|
| **Date** | 2026-10-14 |
| **Branch / HEAD** | `main` @ `c4431f5f3c8ca6d9ac2734efc68f55be6a819fd5` (unchanged) |
| **Predecessor** | `LOGGING_ERROR_HANDLING_AUTONOMOUS_EXECUTION_REPORT.md` |
| **Verdict** | **READY FOR STAGING VALIDATION** — not production-ready (§12). Nothing was committed, pushed, merged, deployed or restarted; no migration was added or applied. |

---

## 1. Initial repository state

- HEAD `c4431f5`, branch `main`.
- **72 working-tree entries were uncommitted at the start** (45 modified files plus untracked
  files/directories). They are the previous mission's work: the observability code, Celery/Next.js/
  Flutter changes, `hrms/ops/`, `infra/monitoring/`, `docs/operations/` and its report. The earlier
  report's "tree was clean" described *its* starting point, not this one.
  **Consequence: none of that work is in any commit.** A deploy from `HEAD` would not contain it.
- Redis DB 0 `reports_exports`: **224** messages at start and at every later check, including after the
  full backend suite. Nothing was consumed, flushed, deleted or replayed.
- Local Postgres 5433, Redis 6380 and MinIO were up. The test environment is forced to the logging
  email provider, the disabled face provider and Celery broker DB 15 by `tests/conftest.py`.

## 2. Current implementation verified (Phase 1)

| Check | Result |
|---|---|
| The seven original fixes are in the code | **Yes.** TXN-01 (`rotate_refresh_token`, `_revoke_family_on_reuse` commits before raising), PRA-04 (`task_queues`), LOG-01/05 (`RequestContextMiddleware`), LOG-02 (`app_error`/`db_error` handlers), LOG-03 (`@setup_logging.connect`), LOG-04 (`TOKEN_PATH_PREFIXES`, Nginx `hrms_log_uri` map, `hide_parameters=True`). |
| Tests cannot send real email or call real Face++ | `tests/unit/test_test_isolation.py` passes (forced env, not `setdefault`). |
| Celery tests cannot consume the shared backlog | Broker is DB 15. Backlog 224 before and after all runs. |
| Host monitor is read-only | `test_monitor_only_issues_read_only_commands` plus a new allow-list test (every docker/compose command recorded must be one of the five documented shapes). |
| Employee-document and onboarding changes preserved | `employee/document_validation.py`, migration `20261014090000_employee_document`, and the onboarding files are present; the only `modules/employee` diff vs `HEAD` is `tasks.py` (prior mission). |
| Previous report's numbers | Reproduced and **superseded**: backend is now 2698 passed / 1 failed (was 2632 / 1) after this phase's additions. Ruff is 13 errors (matches). Mobile was 475 passed, now 478 (+3). Web 516 passed (matches). |
| The one failing test | `test_account_invite.py::test_invite_employee_accept_and_login_success` still fails. The earlier report shows it also fails at clean `HEAD`; **I did not re-prove that myself.** |

Focused run before any change: isolation, ops, task hardening, employee-import integration,
security events → **49 passed**.

## 3. Changes made, with evidence

| Area | Files | Evidence |
|---|---|---|
| Face-punch idempotency | `attendance/service.py`, `face_service.py`, `repository.py`, `router.py` | 18 new integration tests; 51 passed with the existing face suites |
| Mobile face-punch key | `attendance_repository.dart`, `face_punch_card.dart` | 3 new Flutter tests; 478 passed |
| Import reconciliation tool | `hrms/ops/import_backlog.py` | 19 unit + 3 integration tests |
| Refresh-token tests | `tests/integration/auth/test_refresh_token_reuse.py` | +2 tests; 7 passed, 3 repeated runs |
| Monitor | `infra/monitoring/hrms_monitor.sh` | 15 new tests (32 in file) |
| Job-health / readiness tests | `tests/unit/ops/test_job_health.py`, `test_job_health_and_readiness.py` | 7 + 2 new tests |
| Test support | `tests/integration/modules/attendance/conftest.py` (`face_tenant_b` fixture) | used by the tenant-isolation test |
| Docs | `docs/operations/STAGING_VALIDATION_CHECKLIST.md`, `EMPLOYEE_IMPORT_BACKLOG_RECONCILIATION.md` (new); `ALERTS_AND_RUNBOOKS.md` (updated) | |

No payroll code, calculation, approved business rule, authentication, tenant isolation or audit
logic was changed.

**Behaviour changes to be aware of**

1. **Self-punch** (`POST /attendance/punches/me` and on-behalf): reusing a key with a different
   direction or source is now a **409** (was a silent replay of the other punch). A request that loses
   a unique-index race now **replays** the winner when it is the same employee, direction and source
   (was a 409).
2. **Monitor**: new `containers_not_running` check (critical); the alert command's stdout is now
   discarded so it cannot corrupt the JSON report (before, it was mixed into stdout); the alert command
   is bounded by `HRMS_ALERT_TIMEOUT` (default 30 s); `{"alert_delivery":...}` is always written to stderr.
3. **Process incident, fully reverted.** While checking the new Dart test I ran `dart format` on
   a directory. The repository is not dart-formatted, so it rewrote 24 files. The 22 files that were
   unmodified at the start were restored from `HEAD`. For the two files that already carried
   uncommitted changes (`attendance_repository.dart`, `attendance_self_screen.dart`) I recovered the
   original layout with a three-way merge of `HEAD`, `dart format(HEAD)` and the formatted file, and
   resolved the three conflicts by hand. Their diffs against `HEAD` are small again (36 and 20 lines).
   `test/core/*.dart` (untracked, from the previous mission) **stayed in `dart format` layout**; that
   is whitespace only. `flutter analyze` and all 478 tests pass on the final tree.

## 4. Face-punch idempotency: design and results (Phase 2)

**Path before.** `POST /attendance/face-punches/me` (multipart `photo`, `direction`) →
`FacePunchService.punch_self` → attempt limit → enrollment → liveness → verify →
`PunchService.record_punch(idempotency_key=None)`. Self-punch already had a key and
a unique index `punch_company_idempotency_key_idx (company_id, idempotency_key) WHERE NOT NULL`. A
retried face punch after a timeout created a second punch; only the calculation-time duplicate
collapse hid it.

**Design (no migration; the existing index is reused).**

- Optional form field `idempotency_key`, 16–64 characters of `[A-Za-z0-9_-]`. Anything else is a 422
  before any provider call. No key means the previous behaviour, so older apps keep working.
- **Scope.** Tenant by `company_id` (the index and every lookup), employee by comparing the stored
  row's `employee_id` with the authenticated caller (a different employee gets 409, never the other's
  punch), operation by storing `face:<key>` (a self-punch key cannot collide with or replay a face
  punch, and `source` and `direction` are compared as well).
- **Atomicity.** The key is persisted only by the punch insert, in the same transaction as the
  `MATCHED` attempt row and the audit record. A rejected, failed or rolled-back attempt leaves **no**
  key: the same key can be retried. Rejections (their own transaction) never carry the key.
- **Concurrency.** `pg_advisory_xact_lock(hash(company, employee, key))` serialises same-key
  requests, so duplicates wait for the first commit, then take the replay path **without a second
  provider round-trip**. If the lock were ever bypassed, the unique index is the backstop: the insert
  runs in a SAVEPOINT; the loser reads back the winner and replays it (or returns a 409 if the winner is
  a different logical punch).
- **Replay.** Returns the original punch plus the original similarity and liveness scores (read from
  the `MATCHED` attempt). It is evaluated before the failed-attempt limit, so a locked-out employee can
  still retrieve a punch that was already recorded. It does not re-run liveness or matching.
- **Preserved.** Authentication, `ATTENDANCE.PUNCH`, employee-visibility check, liveness, match, attempt
  limit and the audit record are untouched for a first request.
- **Logging.** Only `key_ref` (first 12 hex characters of SHA-256 of the stored key) is logged:
  `attendance.face_punch.replayed` and `attendance.face_punch.idempotency_conflict`. The raw key is never
  logged (tested against stdout, stderr and the `logging` handler).
- **Mobile.** `facePunchMe` always sends a key. `FacePunchCard` keeps the key after a no-response
  failure (status 0: timeout or network) and reuses it for a retry of the same direction; any real
  server answer, or a different direction, starts a new key.

**Tests (`test_face_punch_idempotency.py`, all passing; 51 with the existing face suites)**

| Requirement | Test |
|---|---|
| Normal operation / no key | `test_no_key_keeps_previous_behaviour`, `test_different_keys_are_different_punches` |
| Duplicate request | `test_same_key_replays_original_without_second_punch_or_verification` (same punch ID, time and scores; provider calls unchanged; one attempt row; stored key `face:…`) |
| Concurrent | `test_concurrent_same_key_creates_exactly_one_punch` (6 parallel: all 201, one punch, one `MATCHED` attempt, one `verify` call) |
| Retry after lost response | `test_retry_after_lost_response_returns_original` |
| Failure leaves key reusable | `test_rejected_attempt_leaves_key_reusable`, `test_provider_outage_leaves_key_reusable` |
| Database failure | `test_database_failure_during_punch_write_leaves_no_record` (500, no punch, no attempt, no key; same key succeeds afterwards) |
| Invalid reuse | different direction → 409; malformed key → 422 before any provider call (4 cases); face vs self-punch namespaces; self-punch other direction → 409; other employee → 409 |
| Tenant isolation | `test_same_key_in_another_tenant_is_independent` |
| No raw key in logs | `test_raw_key_never_appears_in_logs` |

**Mutation check.** With the advisory lock disabled, the concurrent test still ends with one punch and
one attempt (the unique-index backstop works) but makes six `verify` calls, so the test fails. The lock
is what avoids duplicated provider calls.

**Not covered / residual.** (a) A client disconnect while the server is mid-request was not simulated;
"lost response" is modelled by discarding a completed 201. (b) A key never expires: the punch row is
permanent, so reusing a key weeks later replays the old punch. Mobile uses a fresh key per
attempt. (c) The advisory lock is held through the provider calls (seconds), but only against the same
key. (d) Real Face++ behaviour was not exercised. (e) The response's `punch.idempotency_key` shows the
stored `face:<key>` form (existing field, visible only to the caller). (f) Payroll: no payroll
code touched; calculation-time duplicate collapse remains as a second line of defence, now needed less.

**Deployment.** No migration, no new dependency. The API change is additive (optional field). Deploy
API first, then the mobile build.

## 5. Employee-import backlog reconciliation (Phase 3)

Procedure: `docs/operations/EMPLOYEE_IMPORT_BACKLOG_RECONCILIATION.md`. Tool:
`python -m hrms.ops.import_backlog [--company-id …] [--all-companies] [--stale-pending-hours N] [--queue NAME]`.

- **Read-only by construction.** Redis: `LLEN` and `LRANGE` only (a unit test records every command).
  Postgres: `SET TRANSACTION READ ONLY` plus rollback (an integration test proves the database refuses
  an `UPDATE` from the tool's session).
- Nothing is inferred from a message. The batch row decides; a missing or unreadable record is
  `MANUAL_REVIEW`. The tool never marks, replays, discards or deletes anything.
- Verdicts: `ELIGIBLE_TO_RUN`, `SAFE_TO_DRAIN` (terminal or already processing: the claim will skip it),
  `MANUAL_REVIEW` (stale `PENDING`, duplicates, possible resubmission by same filename, `PENDING` with no
  message, stuck `PROCESSING`, not visible, unreadable).
- Employees carry no link to a batch, so "was this batch reprocessed?" is answered only by counters,
  later same-filename batches and the audit log. The procedure says so.
- Operator decision step: mark an unwanted `PENDING` batch `FAILED` before the worker starts. A test
  proves such a batch is then skipped without touching its row.
- **Local result.** All 224 queued messages are import tasks; all 224 are `NOT_VISIBLE` (224 distinct
  company IDs, no visible batch), so a worker would log `reason=missing` for each. The queue stayed at 224.
  **The production backlog is unknown and must be measured with this tool before the worker starts.**
- Tests: 19 unit, 3 integration (real Celery-published messages to a throw-away queue on broker DB 15),
  plus the existing claim/concurrency tests (employee import suite: 32 passed with the unit file).

## 6. Refresh-token concurrency (Phase 4)

The strict policy is unchanged: no grace window.

| Required case | Test |
|---|---|
| Normal rotation | `test_normal_rotation_chain_keeps_one_live_token_and_one_session` (new): 3 rotations, one family, one session, exactly one live token, no `REUSE_DETECTED`, chain continues |
| Reuse of an old token | `test_reuse_revokes_family_and_session_durably` |
| Durable family revocation | same test, read back through a fresh connection; newest token and access token dead |
| Concurrent refresh | `test_concurrent_refresh_of_one_token_has_a_single_winner`; `test_conditional_rotation_is_single_winner_under_a_row_lock` (deterministic, row-lock) |
| Database failure during revocation | `test_revocation_failure_is_a_server_error_not_a_revoked_401` (500, newest token untouched) |
| Unrelated sessions | `test_reuse_does_not_touch_an_unrelated_family`; `test_concurrent_refresh_race_revokes_only_its_own_family` (new) |

Result: 7 passed, three consecutive runs; `tests/integration/auth` 60 passed. (Access tokens minted in
the same second are byte-identical because they carry no `jti`; that is existing behaviour and is not
asserted either way.)

**Simultaneous browser tabs.** The web client has a single-flight refresh *within* a tab only. With
two tabs expiring together, both can send the same cookie: one wins, the other is treated as reuse,
the family is revoked and **both tabs are signed out**; `security.refresh_token_reuse_detected` is
logged (monitor check `refresh_token_reuse`, medium). This is the policy as designed.

**Safe client-side mitigation (not implemented).** Serialise the refresh across tabs with a Web Lock
(`navigator.locks.request('hrms-refresh', …)`). The refresh token lives in a shared HttpOnly cookie, so the
second tab, running after the first finishes, sends the already-rotated cookie and succeeds as a normal
rotation. No server change and no weakening of replay detection. It was left out because jsdom has no
`navigator.locks`, so it cannot be verified here; it needs a real-browser check (staging B-15) and a decision.

## 7. Monitor and alert verification (Phase 5)

Verified against a fake `docker` (no containers touched). 32 monitor tests, 7 job-health tests.

| Condition | Result |
|---|---|
| Database unavailable | `api_ready` fails (readiness 503, logged: `test_readiness_with_unreachable_database…`); log-derived `db_connectivity_errors` fails |
| Redis unavailable | readiness `redis: error` logged (new test); `job_health` exits 2 with `redis_unavailable`; `rate_limiter_unavailable` fails |
| Worker/Beat stopped | `scheduler_heartbeat` stale or missing fails `job_health`; **new** `containers_not_running` fails |
| Queue depth / oldest age | thresholds, env overrides, unknown-age handling (7 unit tests) |
| MinIO unavailable | **Finding, fixed.** `/health/ready` checks only that storage is *configured* (test documents it). A stopped container is not "unhealthy", so nothing detected a stopped MinIO. New `containers_not_running` (read-only `docker ps -a --format`) detects it; one-shot `minio-init`/`migrate` are excluded. `storage_and_orphan_failures` covers failures seen in logs. A MinIO that is running but unreachable from the API is only caught by its own Docker healthcheck. |
| Disk, container health, restarts | existing tests, unchanged |
| Recovery | `test_recovery_after_a_simulated_failure`: fails, then passes with `failing: []` |
| Unparseable job-health output | counted as a failure, not a crash |
| Missing `jq` | exit 2, Docker never called |
| Missing alert command | stderr `{"alert_delivery":"not_configured"}`, exit 1 (it used to be silent) |
| Invalid command / non-zero exit | `{"alert_delivery":"failed"}`, report still intact, exit 1 |
| Hung command | killed by `HRMS_ALERT_TIMEOUT` (1 s in the test; returns in under 15 s) |
| Working fake command | `{"alert_delivery":"sent"}`; its stdout cannot reach the report |
| Read-only guarantee | deny-list test and a stricter allow-list test; only `compose exec`, `compose logs`, `ps`, `inspect` |

**Not claimed:** that any real notification works. Only the command interface was tested, with harmless
fake commands. No destination exists (D1). The monitor is stateless: it alerts every failing run and
sends no "recovered" message. It was not run on a VPS.

## 8. Staging test matrix (Phase 6)

`docs/operations/STAGING_VALIDATION_CHECKLIST.md`: Part A lists 16 local test groups (what they prove);
Part B has 20 scenarios (B-01 to B-20), each with preconditions, action, user-visible result,
log/metric/alert, recovery and required evidence, plus a sign-off table. Part B covers: correlation
and 5xx; CORS/security headers through Nginx; redaction through Nginx; auth failures; database loss
and pool/lock timeouts; Redis outage; email rejection/timeout; Celery failure and stuck jobs; Beat
heartbeat; MinIO outage; import recovery; self/face-punch retries on a real device; Next.js boundaries
in a real browser; Flutter handling on Android and iOS; simultaneous tabs; monitor recovery; the alert
destination; log retention/volume; backup and restore; deployment pre-checks. **None of Part B has
been run.**

## 9. Exact test results and outstanding failures

All backend runs used Postgres `localhost:5433`, Redis `localhost:6380`, broker DB 15, with the
logging email provider and disabled face provider (forced by `conftest.py`).

| Command (from `apps/api`, `.venv/bin/python -m …`) | Result |
|---|---|
| `pytest tests -q -p no:cacheprovider` (full) | **2698 passed, 1 failed**, 4 warnings, 731.97 s. Failure: `tests/integration/modules/account_invite/test_account_invite.py::test_invite_employee_accept_and_login_success` (permission set gained `EMPLOYEE.VIEW_DOCUMENTS`; pre-existing per the earlier report) |
| face-punch: `test_face_punch_idempotency.py`, `test_face_punch.py`, `test_face_enrollment.py` | 51 passed |
| import safety: `tests/integration/modules/employee_import`, `tests/unit/ops/test_import_backlog.py` | 32 passed |
| auth: `tests/integration/auth` | 60 passed |
| monitor/job health: `tests/unit/ops`, `test_job_health_and_readiness.py` | 64 passed |
| `mypy src/hrms` | no issues, 186 source files |
| `importlinter` (`lint-imports` equivalent) | 1 kept, 0 broken |
| `alembic heads` | single head `20261014091000`; no migration added |
| Web (`apps/web`): `npx vitest run`; `npx tsc --noEmit` | 62 files, **516 passed**; typecheck clean (no web files changed in this phase) |
| Mobile (`~/flutter/bin/flutter`): `flutter test`; `flutter analyze` | **478 passed, 1 skipped** (opt-in `test/live`); analyzer: no issues |

**Not run:** `next build` (no web changes in this phase; earlier report: passed); `dart format` (the
repository is not dart-formatted at baseline, so a formatter gate would fail regardless; CI runs only
`flutter analyze` and `flutter test`); anything on staging, a device, a browser or a real provider.

### 9a. Lint (Phase 7)

`ruff check .` → **13 errors**, `ruff format --check .` → 5 files. **None were introduced by this
work.** Every file is unchanged from `HEAD` except `tests/unit/core/test_unhandled_exception_logging.py`, whose
one offending line (46, 101 characters) is from commit `0aa1300`. `ruff check src` is clean; new and modified files are clean.

| Rule | Count | Where |
|---|---|---|
| E501 | 9 | `alembic/versions/20261007090000_face_attendance_facepp_provider.py:29,40`; `alembic/versions/20261008090000_compensation_ctc_positive.py:31,45`; `tests/integration/modules/account_invite/test_account_invite_pagination.py:22`; `tests/integration/modules/employee/test_employee_documents.py:550`; `tests/security/test_account_invite_onboarding_token_isolation.py:44,189`; `tests/unit/core/test_unhandled_exception_logging.py:46` |
| I001 | 2 | `test_account_invite_pagination.py:11`; `test_account_invite_onboarding_token_isolation.py:11` |
| F401 | 2 | `test_account_invite_pagination.py:12` (`typing.Any`); `tests/integration/modules/onboarding/test_onboarding_case_pagination.py:9` (`uuid.UUID`) |

Format-only: the above test files plus `tests/unit/modules/employee/test_document_validation.py`.

**Cleanup proposal (separate change, not done):** `ruff check --fix` resolves the 4 import findings;
`ruff format` the 5 files; wrap the 5 long test lines by hand; for the 4 alembic lines use a per-line
`# noqa: E501` rather than editing already-applied migration SQL. No rule is relaxed and no directory is
excluded. Until then **CI's lint step is red at `HEAD`** independent of this work.

## 10. Required staging configuration

- `ENVIRONMENT=staging` (or equivalent) with production-style settings guards; separate database,
  Redis, MinIO and secrets from production. **No production credentials.**
- `EMAIL_PROVIDER=logging`, or a real provider addressed only to mailboxes you own.
- `FACE_VERIFICATION_PROVIDER`: the provider's sandbox, or the disabled/stub provider for non-face runs.
  A real device test of B-12 needs a working provider.
- Celery broker and result backend on a staging Redis; the worker must **not** be pointed at a queue
  holding unreconciled production messages.
- Monitor: `bash`, `jq`, docker compose plugin; `HRMS_COMPOSE_PROJECT` = the staging project name;
  optional `BACKUP_ROOT`; `HRMS_ALERT_COMMAND` (own notifier script) and `HRMS_ALERT_TIMEOUT`;
  `HRMS_ONESHOT_SERVICES` if the compose file defines other run-once services. Cron `*/5`.
- Job-health thresholds (env, provisional): `HRMS_HEARTBEAT_MAX_AGE_SECONDS` 300,
  `HRMS_QUEUE_MAX_DEPTH` 100, `HRMS_QUEUE_MAX_AGE_SECONDS` 600.
- Rebuild and deploy `api`, `worker`, `beat`, then the mobile build. No migration for this phase.
- A way to read logs by `request_id`; an external uptime probe on `/health/ready` is still advised.
- A real Android and iOS device, and a real browser, for B-12 to B-15.

## 11. Production blockers and approval-only decisions

**Blockers (must be cleared before production)**

1. **The work is uncommitted.** `HEAD` does not contain the logging/observability implementation or this
   phase. Needs the owner's commit/PR decision.
2. **No alert destination (D1).** Real notification is unproven. B-17 must pass with a named recipient.
3. **Staging evidence does not exist.** Part B has not been run; error boundaries, mobile handlers,
   the monitor on a host, Nginx redaction and face-punch retries on a device are unverified.
4. **Production import backlog (D-B)** is unmeasured. Run the reconciliation tool, get HR decisions, and
   only then start the worker against that queue.
5. **CI is red at `HEAD`** (13 ruff errors, 5 unformatted files) and **one backend test fails**
   (`test_account_invite…`). Neither is caused by this work; both must be resolved or explicitly waived.
6. Log retention is size-based only (D2): security events can rotate away within hours under load.

**Decisions only the owner can make**

| ID | Decision |
|---|---|
| D1 | Alert destination and on-call owner |
| D2 | Log retention periods |
| D3 | Any third-party error tracker, uptime service or crash reporter |
| D4 | Email outbox vs best-effort sending |
| D5 | Whether a complete job run is a precondition for payroll period close |
| D-A | Refresh-token grace window (not added); and whether to ship the cross-tab Web Lock |
| D-B | For each stale `PENDING` import batch: run or fail it |
| New | `acks_late` for non-Leave idempotent tasks |
| New | Whether face-punch keys should expire / be required (currently optional and permanent) |
| New | Who commits the working tree, and how |

**Known limits, not blockers:** `/health/ready` does not probe MinIO reachability; the monitor is
stateless (no recovery message); a lost connection stays a 500 because the commit may have landed;
`http_request` volume is unmeasured.

## 12. Final verdict

**READY FOR STAGING VALIDATION.**

The code and tests support controlled validation on staging: face punches are idempotent
server-side and on mobile, the import backlog can be inspected safely without touching it, refresh-token
behaviour is deterministic and unchanged, the monitor now detects a stopped service and reports whether
anyone was told, and a full staging checklist exists.

This is **not** production readiness. Production needs the staging evidence in §8, a working and
tested alert destination, the backlog decision, the owner's decisions above, and the work committed.
The staging environment must be authorised and provisioned by the owner; nothing in this report was
deployed, restarted or applied.
