# Logging, Error Handling & Reliability — Pre-Commit Verification and Staging Preparation

| | |
|---|---|
| **Date** | 2026-10-14 |
| **Branch / HEAD** | `main` @ `c4431f5f3c8ca6d9ac2734efc68f55be6a819fd5` (`main...origin/main [ahead 1]`) |
| **Predecessors** | `LOGGING_ERROR_HANDLING_AUTONOMOUS_EXECUTION_REPORT.md`, `LOGGING_ERROR_HANDLING_STAGING_READINESS_REPORT.md` (both preserved unchanged) |
| **Verdict** | **READY FOR STAGING VALIDATION — NOT production-ready.** Pre-commit checks pass except four pre-existing lint findings in applied migrations. |
| **Git actions** | **None.** Nothing was committed, pushed, merged, rebased, stashed, reset, cleaned, tagged or deployed. No service was restarted and no migration was run. |

---

## 1. Executive summary

- The working tree (nothing staged) holds the uncommitted logging/observability work of the two earlier phases plus the changes below. HEAD contains none of it.
- **The account-invite failure is a stale test expectation, not an application defect, and it is pre-existing.** I reproduced it on a clean `HEAD` worktree, traced the permission contract, and updated the test. All 100 account-invite and employee-document tests pass.
- **Ruff: 13 findings reproduced, identical on clean `HEAD`, so none were caused by this work.** I fixed 9 mechanically in test files (reviewed diffs). **4 remain**, all `E501` inside SQL strings of two already-applied Alembic migrations. `ruff format --check` is now clean.
- Three genuine reliability gaps were found by review and fixed with tests (§6): a failed import enqueue left an orphan `PENDING` batch; the log-drop counter existed but nothing ever surfaced it; two browser tabs refreshing together signed the user out.
- Backend: **2704 passed, 0 failed, 0 skipped** (exit 0, 726.62 s; the previously failing account-invite test now passes). Web: 63 files, 519 passed, `tsc` clean, production build succeeded. Mobile: 478 passed, 1 skipped, analyzer clean. `mypy` clean (186 files); import-linter 1 kept, 0 broken.
- All 20 staging scenarios remain **`NOT RUN`**. Alerting has no destination. The production import backlog has not been measured.

## 2. Starting state

- Branch `main`, HEAD `c4431f5`; **0 staged**, 52 modified files (unstaged), 30 untracked entries (`git status` snapshot saved before any edit).
- Redis DB 0 `reports_exports`: **224** messages. No celery, gunicorn or uvicorn process was running on the machine.
- Attribution of the pre-existing changes (from the earlier reports and diffs): logging/error-handling/observability (API, worker, web, mobile, monitor, docs, CI `mobile` job) and the face-punch/queue/monitor phase. Employee-document work is **committed** in `c4431f5` and untouched. `modules/employee` differs from HEAD only in `tasks.py` (earlier phase).

## 3. Changes made in this phase

| File | Purpose |
|---|---|
| `tests/integration/modules/account_invite/test_account_invite.py` | Expected employee permission set now includes `EMPLOYEE.VIEW_DOCUMENTS` (§4) |
| `tests/integration/modules/account_invite/test_account_invite_pagination.py`, `.../employee/test_employee_documents.py`, `.../onboarding/test_onboarding_case_pagination.py`, `tests/security/test_account_invite_onboarding_token_isolation.py`, `tests/unit/core/test_unhandled_exception_logging.py`, `tests/unit/modules/employee/test_document_validation.py` | Mechanical lint/format fixes only (§5). Behaviour-preserving; the 129 tests in these areas pass |
| `src/hrms/core/observability/logging.py` | `_ResilientStdout` now emits one in-band `log_writes_dropped` event when stdout recovers after losing lines |
| `tests/unit/core/test_resilient_log_sink.py` (new) | 3 tests: failed writes are dropped and counted, recovery notice (never mid-line), a second outage is reported separately |
| `infra/monitoring/hrms_monitor.sh`, `tests/unit/ops/test_host_monitor.py`, `docs/operations/ALERTS_AND_RUNBOOKS.md` | New `log_writes_dropped` check (33 monitor tests) |
| `src/hrms/modules/employee_import/service.py`, `exceptions.py` | A failed enqueue now closes the batch `FAILED`, logs `employee_import.batch.enqueue_failed`, and returns `503 IMPORT_QUEUE_UNAVAILABLE` (new `ImportQueueUnavailableError`) |
| `tests/integration/modules/employee_import/test_import_idempotency.py` | New test for the above |
| `apps/web/src/lib/api/client.ts` | Cross-tab refresh lock (§7.B) |
| `apps/web/src/lib/api/client-cross-tab.test.ts` (new) | 3 tests with a strict-replay server model |
| `docs/operations/STAGING_VALIDATION_CHECKLIST.md` | Every scenario now has *Safe for staging*, *Authorisation/configuration* and *Status* fields; B-15 rewritten; Part A extended |
| `docs/operations/ALERTS_AND_RUNBOOKS.md` | §1.1 alert destination configuration and delivery test |
| `docs/operations/EMPLOYEE_IMPORT_BACKLOG_RECONCILIATION.md` | §8 production measurement procedure |
| this report | |

`apps/web/next-env.d.ts` was rewritten by `next build` (a tracked file, clean at the start); I reversed those two lines by hand and confirmed `git status` shows it unmodified.

## 4. Account-invite failure: investigation and conclusion

**Test:** `tests/integration/modules/account_invite/test_account_invite.py::test_invite_employee_accept_and_login_success`.
**Failure:** `assert codes == {…}`; the actual permission set has one extra item, `EMPLOYEE.VIEW_DOCUMENTS`.

Evidence:
1. `organisation/service.py::register_company` grants the base `EMPLOYEE` role a SELF-scope tuple that includes `EMPLOYEE_VIEW_DOCUMENTS` (lines ~766-782); `employee/permissions.py` documents it ("an employee can see their own documents read-only; only HR/Admin can upload, delete, or verify"); migration `20261014091000_employee_view_documents_backfill` grants it to existing companies; `test_employee_documents.py` exercises it.
2. The test was last changed in commit `0aa1300`; the permission was added in `c4431f5`, which did not update this expectation.
3. **Baseline proof.** In a throw-away `git worktree` of `HEAD` outside the repository (removed afterwards), the same test fails with the same extra item. `organisation/service.py` is unmodified in the working tree, so the uncommitted work did not cause it.

**Classification: pre-existing stale test expectation** (not a regression and not a permission defect). The contract is unambiguous, so the fix is to the test: `EMPLOYEE.VIEW_DOCUMENTS` added to the expected set with a comment. The assertion is set *equality*, so it still proves the employee role does **not** hold `EMPLOYEE.UPDATE_SENSITIVE` (document writes) or any extra permission. No permission was granted or changed. Caveat: the worktree run used the main virtualenv with `PYTHONPATH` pointing at the worktree sources; I confirmed the worktree's `hrms` package is the one importable under that path.

## 5. Ruff findings

`ruff 0.16.1` with the repository configuration. Initial: **13 errors**, 5 files needing format. The sorted `(file:line:col rule)` list from the working tree and from a clean `HEAD` worktree is **byte-identical**, so **none were introduced by this work**. The only modified-file finding (`test_unhandled_exception_logging.py:46`) is on a line that exists at `HEAD`.

| Finding | Rule | Disposition |
|---|---|---|
| `test_account_invite_pagination.py:11` (import order), `:12` (`typing.Any` unused), `:22` (line length) | I001, F401, E501 | **Fixed** (`ruff --fix --select I001,F401` limited to the file, then `ruff format`; diff reviewed) |
| `test_onboarding_case_pagination.py:9` (`uuid.UUID` unused) | F401 | **Fixed** |
| `test_account_invite_onboarding_token_isolation.py:11, 44, 189` | I001, E501 ×2 | **Fixed** |
| `test_unhandled_exception_logging.py:46` | E501 | **Fixed** (format wraps it) |
| `test_employee_documents.py:550` (SQL string) | E501 | **Fixed** (wrapped the SQL inside the string) |
| `alembic/versions/20261007090000_face_attendance_facepp_provider.py:29, 40` | E501 | **Left.** SQL inside an applied migration |
| `alembic/versions/20261008090000_compensation_ctc_positive.py:31, 45` | E501 | **Left.** Same |
| Format-only: `test_document_validation.py` and the files above | — | **Fixed** (`ruff format`) |

Result: `ruff check .` **4 errors remain** (exit non-zero; the configured lint command does **not** pass); `ruff format --check .` → 576 files already formatted. Proposal for the remaining four (owner decision): a `per-file-ignores` entry for `alembic/versions/*` limited to `E501` (a lint-configuration change that I did not make), or re-wrap the SQL, which edits applied migration files. I made neither.

## 6. Defects found by review and fixed

1. **Failed import enqueue left an orphan `PENDING` batch (PRA-04 class).** `create_batch` commits the row, then calls `process_batch.delay(...)`. With the broker unreachable the exception escaped: the client got a bare 500 and the batch stayed `PENDING` with no message behind it. Now: batch closed `FAILED`, `employee_import.batch.enqueue_failed` logged (no stack of user data), `503 IMPORT_QUEUE_UNAVAILABLE`, client may re-upload. Test: `test_a_failed_enqueue_closes_the_batch_instead_of_leaving_it_pending`. (`calculate_range.delay` in the attendance service has no persisted state before the enqueue, so it needs no equivalent.)
2. **Log-write failures were counted but never observable.** `dropped_log_writes()` had no caller and no test. Now the sink reports the loss once, in-band, when it recovers, and the monitor alerts on it. Lines written *during* the outage remain lost; that is inherent. Tests: `test_resilient_log_sink.py` (3), monitor signal (1).
3. **Simultaneous tabs signed the user out** (documented limitation of the earlier phase). See §7.B.

## 7. Review of the reliability changes

Each item states what I verified in the code or tests, not what the earlier reports claim.

**A. Request logging / errors.** `RequestContextMiddleware` is outermost; request-ID policy and replacement of bad/oversized IDs are tested (`test_resolve_request_id_policy`, `test_bad_or_missing_request_id_is_replaced_end_to_end`); the unhandled-exception path keeps request ID, CORS and security headers (`test_unhandled_exception_keeps_request_id_cors_and_headers`); one `http_request` per request, raw path never logged; redaction processor covers keys, value patterns, bytes and a failure fallback (`test_log_redaction.py`); engine uses `hide_parameters=True`. Log sink failure cannot raise into callers (now tested). Gap closed: observability of dropped lines (§6.2).

**B. Authentication / refresh.** `_revoke_family_on_reuse` commits before raising; revocation failure yields 500, not a false 401; `_rollback_preserving_cause` keeps the original exception; rotation is a conditional `UPDATE … WHERE revoked_at IS NULL`; 7 integration tests incl. a deterministic row-lock test, passing three consecutive runs earlier today. **Strict replay detection is unchanged** (`service.py`, `repositories/identity.py` not touched in this phase).
*Cross-tab:* the web client had per-tab single-flight only. Evaluation of options: (1) a grace window on the server — **rejected**, it weakens replay protection and needs a policy decision; (2) a server-side "recent rotation" allowance — same objection; (3) client-side coordination — compatible with the architecture because the session (`hrms.session`) is in shared `localStorage` and the refresh token is a shared HttpOnly cookie. **Implemented (3):** `refreshAcrossTabs` takes a Web Lock (`hrms-session-refresh`); the waiting tab first checks whether another tab already renewed the shared session (then it just retries with the new token) and otherwise sends the already-rotated cookie, which is a normal rotation. Without `navigator.locks` it falls back to the old behaviour. **No server or security semantics changed.** Tests (`client-cross-tab.test.ts`) use a strict server that treats a stale cookie as a replay: with the lock both tabs succeed and there is one refresh call; without it the session is revoked; a failed refresh still signs every tab out. **Limit:** vitest simulates tabs with module instances and a mutex; real-browser behaviour is unverified until staging B-15. Stale-token detection is best-effort (the token is read when the 401 is handled).

**C. Face-punch idempotency.** Verified in `face_service.py`/`service.py` and 18 server tests + 3 mobile tests: server-enforced (client key optional but honoured); advisory lock + unique index; replay without provider call; same key with a different direction → 409; malformed key → 422; cross-employee → 409; tenant-scoped; failures leave no key; raw key never logged. A same key with a *different photo* replays the original result without re-verifying (by design). Residuals listed in the earlier report remain (client disconnect mid-request not simulated; keys permanent).

**D. Employee import.** Atomic `PENDING→PROCESSING` claim (`claim_pending_batch`), concurrent and redelivered tests pass; queue routing (`task_queues`, `reports_exports`) confirmed in `celery_app.py`; no automatic retry (create-only); enqueue failure now handled (§6.1). `hrms.ops.import_backlog` is read-only (only `LLEN`/`LRANGE`; `SET TRANSACTION READ ONLY` plus rollback, tested) and keys its verdict on the **batch row**, separating broker messages from `PENDING` batches (`PENDING_NO_MESSAGE`, `NOT_VISIBLE`, duplicates). The guard prevents duplicate runs but not stale runs; the procedure says so. **Production backlog not touched.**

**E. Email.** Senders classify `not_sent` vs `unknown` after read timeout or 5xx (`test_email_failure_classification.py`); logs exclude the recipient address; activation survives an email/auto-issue failure via a SAVEPOINT (`test_activation_failure_isolation.py`). Documentation states there is no outbox and that `email.provider.accepted` is not delivery (`LOGGING_AND_OBSERVABILITY.md` §117-122; `ALERTS_AND_RUNBOOKS.md`). No outbox was added. **Note:** the developer `.env` selects the Hostinger email provider and Face++; that is why the test suite force-overrides them.

**F. Celery / monitoring.** Every task has a hard time limit (enforced by `test_task_hardening.py`); fan-outs isolate per-company enqueue failures (`dispatch_per_company`); heartbeat and lifecycle events tested; readiness returns 503 for database or Redis failure (tests added earlier) and **does not probe MinIO reachability** (documented, tested). A stopped MinIO, worker, Beat or Redis is detected by `containers_not_running` (read-only `docker ps -a --format`). The script never reads or prints credentials; the alert command receives the report on stdin; stderr states `sent|failed|not_configured`; `sent` means only that the command exited 0. Not run against any real host.

**G. Web / mobile.** Error boundaries (`route-error.test.tsx`), request references, and `describeApiError` are covered by component tests (not a browser run). Mobile `AppDiagnostics` stores no message text (sentinel-address test). Mobile writes never auto-retry; the idempotency keys make a user-initiated retry safe for self-punch and face punch. Authentication handling tests unchanged and passing.

## 8. Commands executed and results

Isolation was verified first (§9). All from the repository; exit codes are the tool's.

| Command | Result |
|---|---|
| `git status --branch --short`; `git rev-parse HEAD`; `git diff --cached --stat` | recorded (§2) |
| `pytest …/test_account_invite.py -k test_invite_employee_accept_and_login_success` (working tree) | failed (extra `EMPLOYEE.VIEW_DOCUMENTS`) |
| same, in a scratch `git worktree` of `HEAD` | failed identically |
| `pytest tests/integration/modules/account_invite tests/integration/modules/employee/test_employee_documents.py` (after fix) | 100 passed |
| `ruff check .` (tree vs. `HEAD` worktree) | 13 vs 13, identical |
| `ruff check --fix --select I001,F401` + `ruff format` on 6 test files; manual SQL wrap | 129 tests in the affected areas pass |
| `ruff check .` (final) | **4 errors, exit 1** (alembic E501) |
| `ruff format --check .` (final) | 576 files already formatted |
| `pytest tests/unit/core/test_resilient_log_sink.py` | 3 passed |
| `pytest tests/unit/ops/test_host_monitor.py` | 33 passed |
| `pytest tests/integration/modules/employee_import` | 14 passed |
| `vitest run src/lib/api` | 22 passed (3 files) |
| **`pytest tests -q -p no:cacheprovider` (full backend)** | **2704 passed, 4 warnings, exit 0**, 726.62 s. Redis DB 0 backlog 224 before and after |
| `mypy src/hrms` | Success, 186 files |
| `importlinter` (`lint-imports` equivalent) | 1 kept, 0 broken |
| `alembic heads` | single head `20261014091000`; **no migration added or run** |
| `npx vitest run` (web) | 63 files, **519 passed** |
| `npx tsc --noEmit` | exit 0 |
| `npx eslint src/lib/api` | no findings |
| `npx next build --webpack` | exit 0 (generated file restored) |
| `flutter analyze` | No issues found |
| `flutter test` | **478 passed, 1 skipped, 0 failed** (skip: opt-in `test/live`) |

**Not run:** `dart format` (the repository is not dart-formatted at baseline); `eslint` over all of `apps/web` (CI marks it non-blocking; the one known error is in an untouched `src/lib/auth` file per the earlier report); migrations; anything on staging, a device, a real browser or a real provider.

## 9. Test isolation and queue safety

Verified, not assumed (effective settings printed after `tests/conftest.py` applies its overrides):

| Property | Observed |
|---|---|
| Email | `EMAIL_PROVIDER=logging` forced (developer `.env` says `hostinger`); `test_test_isolation.py` asserts the resolved sender |
| Face++ | `FACE_VERIFICATION_PROVIDER=disabled` forced (`.env` says `facepp`); face tests inject a fake provider |
| Celery broker / result backend | `redis://localhost:6380/15`, not DB 0 |
| Redis DB 0 `reports_exports` | **224 before and 224 after** every suite run in this phase; the import-backlog tool's CLI run (earlier phase) used `LRANGE` only |
| Workers / Beat | none running; no test starts one against a shared broker |
| Database | `localhost:5433/hrms_dev`. **Caveat:** this is the developer database, not a dedicated test database. Tests create and delete their own tenants, but `_cleanup_scoped_users` removes every `scoped-%` user, and the heartbeat test writes and deletes one key in DB 0. Acceptable locally; do not point the suite at any shared database |
| Object storage | local MinIO `localhost:9000` or an in-memory fake (`FakePhotoStorage`) |
| Network egress | no remote host in any effective setting |

## 10. Known baseline failures and their classification

| Item | Classification | Evidence |
|---|---|---|
| `test_invite_employee_accept_and_login_success` | Pre-existing stale test; **fixed** | §4: fails identically on clean `HEAD` |
| 13 Ruff findings | Pre-existing; 9 fixed, **4 remain** | §5: identical list on clean `HEAD` |
| 5 unformatted files | Pre-existing; **fixed** | §5 |
| CI lint step | Still red until the 4 migration lines are resolved | §5 |

## 11. Staging checklist and scenario status

Path: `docs/operations/STAGING_VALIDATION_CHECKLIST.md` (Part A: 18 local test groups; Part B: **20 scenarios B-01 to B-20**). Every Part B scenario now lists preconditions, actions, expected UI, expected logs/alerts, recovery, evidence, *Safe for staging*, *Human authorisation / external configuration* and *Status*.

**All 20 are `NOT RUN`.** None was executed, because no authorised staging environment, device or alert destination was available; no unit test was counted as an execution.

## 12. Decision register

| Decision | Current state | Safe next step | Gate |
|---|---|---|---|
| **Alert destination (D1)** | `HRMS_ALERT_COMMAND` interface exists, bounded by `HRMS_ALERT_TIMEOUT`, outcome on stderr. **Unconfigured.** | `ALERTS_AND_RUNBOOKS.md` §1.1: script, delivery test that requires the named recipient's confirmation, negative tests | **Production gate** until a real delivery is confirmed |
| **Production import backlog (D-B)** | Local queue: 224 orphan messages. Production: **unmeasured** | `EMPLOYEE_IMPORT_BACKLOG_RECONCILIATION.md` §8, by an authorised operator using the `api` container; compare Redis messages with `PENDING` batches; queue depth alone proves nothing | **Production gate.** No production worker may consume historical messages before reconciliation and written approval |
| **Cross-tab refresh (D-A)** | Strict replay detection unchanged; client Web Lock added (§7.B) | Staging B-15 in a real browser | Owner to confirm the client change; no server policy change proposed |
| **Log retention (D2)** | Docker `json-file`, `max-size 10m`, `max-file 5` per container (50 MB) in `docker-compose.prod.yml`; Nginx separate. No time-based retention exists | `LOGGING_AND_OBSERVABILITY.md` §7 lists options; the owner picks a period (not invented here), then the log driver or shipper is configured | Required before production |
| **External telemetry (D3)** | None added; no vendor, no external log shipping | Remain so unless approved | n/a |
| **Email outbox (D4)** | Best-effort, no outbox, documented | Owner decision | Risk accepted until decided |
| **Payroll-close job precondition (D5)** | `*_incomplete` events alertable | Owner decision | Before payroll go-live |
| `acks_late` for non-Leave tasks | Unchanged | Owner decision | Recommendation |
| `ruff` migration `E501` | 4 findings | `per-file-ignores` for `alembic/versions/*` (config change) or re-wrap | Owner decision |

## 13. Remaining risks and production blockers

1. **Nothing is committed.** `HEAD` lacks the entire logging/observability implementation.
2. **No alert destination or delivery proof.**
3. **All Part B staging scenarios are unexecuted;** web error boundaries, mobile handlers, Nginx redaction, the monitor on a real host, the cross-tab lock and face-punch retries on a device are unverified in real conditions.
4. **Production backlog unmeasured;** historical messages must not be consumed before reconciliation.
5. **CI lint red** (4 migration lines) until decided.
6. Log retention is size-based only.
7. `/health/ready` does not prove MinIO is reachable; a running-but-unreachable MinIO is detected only by its container healthcheck or by storage-failure log events.
8. Tests run against the developer database `hrms_dev` (§9).
9. Real Face++ and real email providers were never exercised.

## 14. Recommended next actions, in order

1. Review the diff and **commit in logical commits** (owner action; not done here). Suggested groups: observability core; auth/refresh; attendance + face punch; import + queue; monitor + ops tooling + docs; web; mobile; test fixes.
2. Decide the four-line migration lint question; get CI green.
3. Provision an authorised staging environment (placeholders in the checklist; no credentials were invented).
4. Decide D1 and configure a destination; run the delivery test (§1.1 of the runbook).
5. Run the staging checklist B-01 to B-20 with evidence; record statuses in its sign-off table.
6. Have an authorised operator measure the production backlog (§8 of the reconciliation procedure) and obtain HR decisions *before* any production worker is started.
7. Decide log retention (D2) and configure it.
8. Only then consider production, with the remaining decisions in §12.

## 15. Confirmation

No `git commit`, `push`, `merge`, `rebase`, `stash`, `reset`, `clean` or tag was run. A scratch `git worktree` outside the repository was created for baseline comparison and removed. No service, worker or Beat was started or restarted; no migration was run; no email, face-provider or other external call was made; no production system, queue or data was touched.
