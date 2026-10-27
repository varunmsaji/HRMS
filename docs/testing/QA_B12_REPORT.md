# B12 - Security and integrity remediation: plan, results, evidence (2026-10-26)

Scope: the confirmed B11 findings only (DEF-B11-01..06, OBS-HRA-01). No refactors, no commits/pushes/merges/deploys,
no full regression, no web/mobile suites. B11 evidence (`qa_evidence_b11/`, harness `qa_harness/b11/`) is untouched.
This report does **not** claim full regression or production readiness.

## 1. Preflight (before any edit)

| Item | Value |
|---|---|
| Branch / HEAD | `main` / `436a2e5` |
| `git status --short` at start | **223** paths (87 untracked, 136 modified) = the count B11 ended with; saved as `qa_evidence_b12/git_status_start.txt`, `git_diff_stat_start.txt`, full tracked diff `tracked_diff_start.patch` |
| Root free disk | 4.4 GiB at start (gate >= 3, stop < 2); 4.3-4.4 GiB throughout; 4.4 GiB after teardown (`root_disk_after_teardown.txt`) |
| Memory | ~8 GB available, swap <= 444 MB used; per-batch `*.resources.txt` (also container CPU/mem) |
| Stack | fresh disposable `b12-20261026a` (`stack.sh up/guard/migrate`, head `20261026090000`); `ISOLATION PROVED` printed and checked by `qa_harness/b12_run.sh` before **every** run (`*.isolation.txt`) |
| Not touched | shared `hrms-postgres/redis/minio` (same uptime), `002_app_role.sh`, DDL trigger probe, grants, real e-mail/payment/webhook |

Reproduction of the defects came from retained B11 evidence (`QA_DEFECT_REGISTER.md` Part F, `qa_evidence_b11/artifacts/B11-*.jsonl`) and
the source trace below; the new regression tests re-prove each failure mode through negative controls (section 6) instead of re-running the old harness.

## 2. Root causes and fixes

| Defect | Route | Root cause | Fix (files) |
|---|---|---|---|
| **DEF-B11-01** | `POST /v1/attendance/days/calculate` (+ every caller of `AttendanceDayService.calculate`) | `employee_id` taken from the query and never checked against the caller's company; `attendance_day.employee_id` FK has no tenant component, so a foreign id inserted a row; an unknown id hit the FK -> 500 (existence oracle) | `AttendanceDayService.calculate` now first proves the employee belongs to `company_id` (and is in scope) via new `EmployeeService.ensure_employee_visible`; one `NotFoundError` (404) for foreign, unknown and out-of-scope ids - before any read for calculation, write or audit. Because route, punch, sweep, range task and recompute all go through `calculate`, the guard cannot be bypassed by another field or by batch. (`attendance/service.py`, `employee/service.py`, `attendance/router.py`) |
| **DEF-B11-02** | `POST /v1/onboarding-cases/{id}/activate` | read-check-write on `status == VERIFIED` with no lock: 8 parallel requests all passed the check | `OnboardingCaseRepository.get_case_for_update` (`SELECT ... FOR UPDATE`, `populate_existing`) is the first read in `activate_case`; the whole employee graph, status change, audit row and (post-commit) emails share that one transaction. Losers wait, re-read `ACTIVATED`, get the established 409 `ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION`. Lock is in Postgres, so it holds across processes. (`onboarding/repository.py`, `onboarding/service.py`) |
| **OBS-HRA-01** x5 | `calculate`, `{id}/recompute`, `calculate-range`, `{id}/work-on-leave/keep-leave`, `POST /v1/employees/{id}/invite` | scope bound to an unused `_scope` | each handler now passes `scope` + `user.employee_id`; service resolves visibility with the existing `EmployeeService.resolve_visible_employee_ids` before any mutation/enqueue/invite/e-mail. `calculate-range`: explicit ids must all be visible (else whole request 404, nothing queued); omitted ids are narrowed to the visible set, never widened; nobody visible -> 404. COMPANY behaviour unchanged. The 5 `known_gap` entries were **removed** from `scope_guard_exceptions.toml` only after the tests below passed, and the 5 handlers were added to the guard's `FIXED_HANDLERS` pins. |
| **DEF-B11-03 / -05** | `POST /v1/onboarding-cases` | check-then-insert with no lock/unique index; exact-case compare; `scalar_one_or_none()` raised `MultipleResultsFound` -> 500 once duplicates existed | e-mail normalised once (strip + lower - the rule invites/users already use) and stored normalised; `pg_advisory_xact_lock` on `(company, normalised e-mail)` around check+insert (`core/db/locks.py::lock_onboarding_case_email`, leaf lock); lookup is `lower(personal_email)` and returns the oldest match (`.first()`), so legacy duplicate/mixed-case rows give 409, not 500. No schema change. Terminal cases do not block a retry. |
| **DEF-B11-04** | activation, account invite, case invite (also "changes requested") | e-mails were sent (and `email_log` written in its own session) inside the request, before commit | The project has **no transactional outbox**, so none was bypassed. New `core/db/post_commit.py`: actions are queued on the session (SAVEPOINT- and rollback-aware, same model as `business_events`), made ready on commit and awaited by `session_scope`/`get_session` right after `commit()`. `queue_email_after_commit` (in `onboarding/email_sender.py`) delivers then; a failed delivery is logged, never undone-able business state. `email_log.kind` is preserved. |
| **DEF-B11-06** | `POST /v1/employees/{id}/confirm` | status check only; terminating an employment does not move `Employee.status` | `confirm_employee` refuses (409 `EMPLOYMENT_NOT_ACTIVE`) when the employee has employment history and none is ACTIVE; PRE_JOINING/ACTIVE keep `EMPLOYEE_NOT_ON_PROBATION`; a rehired employee (new ACTIVE employment) can still be confirmed. |

## 3. Behaviour / contract changes to review

1. **`email_sent` now means "queued for delivery after commit"** (account invite and case invite responses). It can no longer report a provider failure, because delivery happens after the response is decided. The failure is logged (`email.delivery.failed`) and `invite_url` is still returned for manual hand-over. `test_email_delivery_failure_does_not_fail_the_invite` was updated accordingly; the web client's "could not be delivered" toast will therefore not appear for provider failures.
2. **Not a durable outbox.** A process crash between commit and delivery loses that e-mail (at-most-once). HR can re-issue (`send-invite`, `POST /employees/{id}/invite`). If at-least-once delivery is required, add an `email_outbox` table + worker (migration, needs approval) - not done.
3. Onboarding-case e-mails are stored lower-cased from now on (existing rows are matched case-insensitively and left as they are).
4. `calculate`/`recompute`/`keep-leave`/`invite` return 404 (not 403) for out-of-scope targets - the project's existing non-disclosing convention.
5. A rejected `calculate-range` for a restricted caller rejects the whole request; it does not silently drop foreign ids.
6. `AttendanceDayService.calculate` adds one primary-key employee lookup per call (nightly sweep: per employee-date).

## 4. Migration implications

**None applied. No Alembic revision was added or changed.** Recommended hardening for review (not applied, would need approval and a data check on production):
* `CREATE UNIQUE INDEX CONCURRENTLY ... ON onboarding_case (company_id, lower(personal_email)) WHERE deleted_at IS NULL AND status NOT IN ('ACTIVATED','EXPIRED','CANCELLED')` - **will fail while duplicate active rows exist**; de-duplicate first (the legacy test shows the shape). The advisory lock already covers every code path that inserts cases (only `create_case` does).
* Composite FK `attendance_day(company_id, employee_id) -> employee(company_id, id)` (needs `UNIQUE (company_id, id)` on `employee`; add `NOT VALID`, clean up stray cross-tenant rows, then `VALIDATE`). Same pattern is worth checking on other `employee_id` FKs; B11 only proved attendance.

## 5. Tests (all new, normal regression tests; no skips, no xfail)

| File | Tests | Covers |
|---|---|---|
| `tests/integration/modules/attendance/test_b12_cross_tenant_and_scope.py` | 6 | DEF-B11-01 (valid, foreign, unknown, forged `X-Company-Id`, no-date, day-id siblings, direct service call, range **task body** `_calculate_range_async` + `_calculate_employee_dates` with foreign ids, both tenants' DB fingerprints + audit unchanged); OBS-HRA-01 `calculate`/`recompute`/`calculate-range`/`keep-leave` over SELF/REPORTEES/REPORTEE_TREE/BRANCH/COMPANY, no-employee caller, cross-tenant; keep-leave on a real synthetic leave conflict (approved leave + punches -> `work_on_leave_flagged`) |
| `tests/integration/modules/account_invite/test_b12_invite_scope.py` | 1 | `invite` x 5 scopes: denied = tables unchanged (account_invite, audit_log, email_log); allowed = exactly +1 invite, +1 `email_log`, +1 `ACCOUNT_INVITE_ISSUED`; unknown/foreign/no-employee identical 404 |
| `tests/integration/modules/onboarding/test_b12_activation_integrity.py` | 7 | sequential; repeated; 8 concurrent (1x200 + 7x409, exact row counts for employee/employment/assignment/bank/statutory/compensation/invite/audit/2 e-mails); two independent connection pools; 3 cases x 3 concurrent; injected audit failure -> nothing survives incl. e-mails, retry exact; SAVEPOINT rollback drops only the invite e-mail |
| `tests/integration/modules/onboarding/test_b12_duplicate_onboarding.py` | 5 | exact + case-variant duplicates (no row/audit), other address, other tenant, 8 concurrent creates -> 1x201 + 7x409, 6 concurrent different addresses, legacy duplicate/mixed-case rows -> 409 + stable retry, retry after terminal case |
| `tests/integration/modules/employee/test_b12_confirm_after_termination.py` | 3 | terminated refused + DB/audit unchanged; eligible and rehired confirm; PRE_JOINING/already ACTIVE/unknown |
| `tests/unit/core/test_scope_enforcement_guard.py` (extended) | 16 | the 5 handlers pinned as scope-enforcing and absent from the exception list |
| helper `tests/integration/b12_support.py` | - | per-table row-count + content hash fingerprint |
| existing, updated | 1 | `test_invite_accept_hardening.py::test_email_delivery_failure_does_not_fail_the_invite` (see 3.1) |

## 6. Results (all on disposable `b12-20261026a`, `ISOLATION PROVED` each time; logs in `qa_evidence_b12/`)

| Run (command: `qa_harness/b12_run.sh <name> <paths> -p tests.conftest ...`) | passed | failed | skipped | blocked |
|---|---|---|---|---|
| `final_b12_suite` (the 5 new files + scope-guard unit) | **38** | 0 | 0 | 0 |
| `batch1_3_regression_related` (attendance day/security/range/tasks/leave-projection/period-summary-scope/concurrency/sweep, whole `account_invite`, guard, route-authorization matrix) | 178 | 0 | 0 | 0 |
| `batch2_4_regression` (whole `onboarding`, `account_invite`, email/base-url units, guard) | 320 | 0 | 0 | 0 |
| `batch6_regression` (whole `employee`, `onboarding`, `account_invite`, units) | 719 | 0 | 0 | 0 |
| `batch_session_hook_regression` (session/post-commit change: core business-events, db-failure, celery loop, wait-timeouts, attendance, `tests/unit/core`) | 452 | 0 | 0 | 0 |

Static: `ruff check` clean on all new files and on `core/db`; `ruff format --check` clean on the edited source files; `mypy` (core/db, onboarding, account_invite) clean; import-linter contract kept (1/1).

**Negative controls** (a runtime monkeypatch plugin `qa_harness/b12/negctl.py`, `-p negctl`; **no source file was edited** to do this - the removed protection exists only in memory in the throw-away runner):

| Control | Protection removed | Result of the matching tests |
|---|---|---|
| `att_guard` | attendance employee guard | 4 failed / 2 passed (the 2 range tests pass: the range task body is additionally protected by its employment-span filter, and the HTTP range check uses a separate visibility helper) |
| `invite_scope` | invite visibility set | 1 failed |
| `act_lock` | activation row lock | 3 failed / 4 passed (8-concurrent, two-pool, separate-cases) |
| `email_immediate` | deferred e-mail | 2 failed / 5 passed (failure-rollback, savepoint) |
| `dup_lock` | e-mail advisory lock | 1 failed (concurrent creates) |
| `dup_exact` | case-insensitive lookup | 1 failed (legacy rows) |
| `confirm_guard` | employment-ended check | 1 failed |

## 7. Defect status

All "FIXED - verified (B12 targeted)": the fix is in the working tree (uncommitted), the regression passes on the disposable stack, and its negative control fails as listed. Nothing here is closed for release: it still needs code review and the full suite on CI.
Residual / not covered: seat-limit overrun by parallel activations is prevented by the single-winner lock but was not measured separately; confirm-vs-terminate race (confirm reads employments without a lock; `expected_version` does not cover the employment table) is a narrow window left as is; real provider delivery was not exercised (logging sender only); cross-process behaviour was proved with two independent connection pools, not two OS processes; OBS-HRA-03 (`ONBOARDING.CANCEL`), OBS-B11-01..04 untouched.

## 8. Files changed (all edits layered onto the existing uncommitted changes; none reverted)

Source: `core/db/post_commit.py` (new), `core/db/session.py`, `core/db/locks.py`, `modules/attendance/{router,service}.py`, `modules/employee/service.py`, `modules/account_invite/{router,service}.py`, `modules/onboarding/{service,repository,email_sender}.py`.
Tests: the 5 new files + `tests/integration/b12_support.py`, `tests/unit/core/{test_scope_enforcement_guard.py,scope_guard_exceptions.toml}`, `tests/integration/modules/account_invite/test_invite_accept_hardening.py`.
QA harness/docs (additive): `qa_harness/stack.sh` (one extra read-only `b12` mount, same pattern as B11), `qa_harness/b12/negctl.py`, `qa_harness/b12_run.sh`, `qa_evidence_b12/`, this report, additive sections in `QA_DEFECT_REGISTER.md`, `QA_BASELINE_RESULTS.md`, `QA_TEST_CASES.csv`.

## 9. Cleanup and git

Teardown `stack.sh down b12-20261026a --confirm` removed only the 4 containers labelled `qa.run=b12-20261026a` and the run's pgdata/minio; artifacts kept. Afterwards 0 labelled containers; `hrms-postgres/redis/minio` still running.
`git status --short`: 223 -> 238 paths (96 untracked, 142 modified); every one of the 223 baseline paths is still present (set difference shows additions only). `git diff --stat`: 136 -> 142 tracked files, +3826/-1682 -> +4152/-1717 (cumulative, includes the pre-existing work). No commit, push, merge or deploy.
