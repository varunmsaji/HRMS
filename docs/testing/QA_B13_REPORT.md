# B13 - Reliability and migration readiness: report (2026-10-26)

Plan: `QA_B13_PLAN.md`. Evidence: `qa_evidence_b13/` (one `.log` + `.isolation.txt` + `.resources.txt` per batch). Disposable stack `b13-20261026a`
(head `20261027092000`), `ISOLATION PROVED` printed before every batch by `qa_harness/b13_run.sh`. No commit/push/merge/deploy. **Not a claim of full regression or
production readiness.** Status words: IMPLEMENTED = in the working tree; VERIFIED = passes on the disposable stack and its negative control fails; UNTESTED / NOT DONE listed in section 9.

## 1. Files changed
Source (new): `alembic/versions/20261027090000_email_outbox.py`, `...091000_onboarding_case_email_unique.py`, `...092000_attendance_day_tenant_fk.py`, `modules/onboarding/email_outbox.py`, `modules/onboarding/tasks.py`.
Source (edited, layered on existing uncommitted work): `modules/onboarding/{email_sender,service,schemas}.py`, `modules/account_invite/{service,schemas}.py`, `modules/employee/service.py` (confirm lock), `modules/platform/models.py` (`EmailOutbox`), `core/config/settings.py` (6 `email_outbox_*` settings), `core/celery_app.py` (beat `email-outbox-sweep`), `core/tenancy/context.py` (`tenant_scope`), `entrypoints/worker.py` (task registration).
Tests (new): `tests/integration/modules/onboarding/test_b13_{email_outbox,onboarding_unique_index,seat_limit_concurrency}.py`, `.../employee/test_b13_confirm_terminate_concurrency.py`, `.../attendance/test_b13_attendance_tenant_fk.py`, `tests/integration/migrations/test_b13_migrations.py`, `tests/integration/{b13_mp,b13_outbox_proc}.py`.
Tests (edited): `tests/conftest.py` (`EMAIL_OUTBOX_DISPATCH=inline`), `tests/integration/b12_support.py` (helpers), `test_b12_duplicate_onboarding.py` (legacy-duplicate test now runs with the index temporarily absent - the migration makes those rows impossible), `test_invite_accept_hardening.py` (closed key set gains the 2 additive fields).
Harness/docs (additive): `qa_harness/stack.sh` (one `/qa/b13` mount), `qa_harness/b13_run.sh`, `qa_harness/b13/negctl13.py`, `qa_evidence_b13/`, `QA_B13_PLAN.md`, this report, appended sections in `QA_DEFECT_REGISTER.md`, `QA_BASELINE_RESULTS.md`, and `docs/api/{models,modules}/{account_invite,onboarding}.md` field tables.

## 2. Outbox (A) - IMPLEMENTED, VERIFIED
* Schema `email_outbox`: `message_id` UNIQUE (stable logical key), status `PENDING|SENDING|SENT|FAILED`, `attempts/max_attempts`, `next_attempt_at`, lease (`locked_by/locked_until`), last failure class/type, `created/updated/sent/failed_at`, bodies (blanked on SENT/FAILED). Tenant-free, no RLS (like `email_log`); no grant change (default privileges).
* Producer: `queue_email_after_commit` inserts the row in the business transaction (own SAVEPOINT) - rolls back with it; a post-commit *dispatch hint* (`celery` / `inline` / `none`) follows. Message keys: `onboarding_activated:<case>`, `account_invite:<invite>`, `onboarding_invite:<case>:<token-hash>`; others random.
* Worker: tasks `email_outbox.deliver_message` and `email_outbox.sweep` (Beat, 60 s). Claim (one UPDATE / `FOR UPDATE SKIP LOCKED`, 300 s lease) -> commit -> send with no transaction open -> guarded UPDATE. Backoff 30 s * 2^(n-1), cap 1 h, 6 attempts; permanent failure -> FAILED at once; lease-exhausted -> FAILED (`lease_expired`).
* Guarantee: durable **at-least-once** + duplicate-logical-message protection. A kill after the provider accepted but before SENT is recorded sends again (asserted by test).
* `email_log` remains the per-attempt ledger; `email.delivery.failed` is still logged per failed attempt.
* Results (`wsA_outbox`): **15 passed**. Negative controls (`negctl13`): `outbox_immediate` 4 fail, `outbox_autocommit` 2 fail, `outbox_noclaim` 9 fail, `outbox_nolease` 1 fail.

## 3. `email_sent` compatibility
References: web `users/page.tsx`, `onboarding/[id]/page.tsx`, `employees/[id]/page.tsx`, `lib/onboarding/types.ts`; mobile `employee_repository.dart` (+ contract fixtures); API tests/docs. Meanings: pre-B12 "provider accepted"; B12 and now "queued" (can be false only if the outbox write failed). Kept unchanged for clients and marked **deprecated**; added `email_queued: bool` and `email_delivery_status: QUEUED|NOT_QUEUED` (additive, defaults). No web/mobile edit. **Client work needing approval:** web toasts say "Invite sent"/"could not be delivered" - the latter can no longer appear; copy should say "queued" and the UI could read delivery status from a new read endpoint (not built). `docs/api/openapi.json` and the mobile contract fixtures were not regenerated.

## 4. Onboarding e-mail uniqueness (B) - IMPLEMENTED, VERIFIED on scratch DBs
Rule (existing policy): per company, `lower(personal_email)`, not soft-deleted, status not in `ACTIVATED/EXPIRED/CANCELLED`. Index `onboarding_case_company_live_email_key` (partial, unique). Migration pre-checks, never deletes/merges, raises with every conflicting company/e-mail/case-id/status, refuses to run as an RLS-subject role. Tested: history/deleted/other-tenant rows OK; exact-case + case-variant live duplicates fail safely (version unchanged, table digest identical) and succeed after manual cancel; downgrade/upgrade; pre-migration control proves the gap. App maps the index violation to the established 409 (backstop test with the lock and check bypassed). Production: **will fail until live duplicates are resolved by a person**; plain (non-concurrent) index build.

## 5. Attendance tenant FK (C) - IMPLEMENTED, VERIFIED
`UNIQUE (company_id,id)` on `employee` + `FOREIGN KEY (company_id, employee_id) -> employee (company_id,id) ON DELETE RESTRICT` (NOT VALID then VALIDATE; update = NO ACTION). Writers: one insert (`AttendanceDayService.calculate`, B12-guarded) and 7 computed-column updates - none writes the keys. Tests: valid insert/update; cross-tenant and unknown employee rejected; changing only employee or only company rejected; moving/deleting an employee with attendance rejected - as owner and as `hrms_app` with RLS; invalid existing rows fail safely with diagnostics (nothing rewritten) then pass after operator cleanup; downgrade/upgrade. Changing BOTH company and employee consistently is DB-valid (RLS/app prevent it). Other `employee_id` FKs were not examined.

## 6. Confirm vs terminate (D) - IMPLEMENTED, VERIFIED
`confirm_employee` takes `lock_employee_leave_dates` first (same lock terminate takes). 4 passed; forced orderings across OS processes: in-flight termination -> confirm waits then 409 `EMPLOYMENT_NOT_ACTIVE`, 0 `EMPLOYEE_CONFIRMED`; in-flight confirmation -> terminate waits then 200, both audits once; free-running 2-process race x3 consistent. Control `confirm_lock`: the 2 forced-order tests fail (free-running race is timing-dependent and does not reliably fail).

## 7. Seat limit (E) - VERIFIED, no source change
5 passed: capacity available; exact limit (second case 409 `EMPLOYEE_SEAT_LIMIT_EXCEEDED`, case stays VERIFIED, no audit/rows); rejected then retry after a seat is freed; 6 cases racing for 1 seat (1x200, 5x409); 4 cases in 4 OS processes; 3 activations + 3 direct creates in 6 processes (exactly 4 succeed). Count rule asserted: inactive frees a seat; **terminated-but-active still holds one**. Control `seat_lock`: 3/5 fail. Limit/pricing untouched.

## 8. B12 regression and controls
`wsF_b12_regression`: 38 passed. Controls on the same 38: `att_guard` 4 fail, `invite_scope` 4, `act_lock` 3, `email_immediate` 8 (superseded by `outbox_immediate`), `dup_exact` 1, `confirm_guard` 2, **`dup_lock` 0 fail** - the new unique index now catches the race the advisory lock used to be the only guard for, so that control no longer discriminates (expected, not a gap). The 5 OBS-HRA-01 `known_gap` entries are still absent from `scope_guard_exceptions.toml` (only the word remains in a comment) and pinned in `FIXED_HANDLERS`. B11/B12 evidence and harness files: no file modified (checked by mtime).

## 9. Commands, counts, caveats
Runner: `docs/testing/qa_harness/b13_run.sh <batch> <pytest args> -p tests.conftest [-p negctl13|-p negctl]` with `NEGCTL=` for controls.
| Batch | passed | failed | skipped |
|---|---|---|---|
| wsD_confirm_terminate | 4 | 0 | 0 |
| wsE_seat_limit | 5 | 0 | 0 |
| wsBC_migrations | 7 | 0 | 0 |
| wsB_app_index (+B12 duplicate + activation-failure tests) | 10 | 0 | 0 |
| wsC_attendance_fk | 1 | 0 | 0 |
| wsA_outbox | 15 | 0 | 0 |
| wsF_b12_regression | 38 | 0 | 0 |
| wsA_regression_targeted (first run) | 2080 | 3 | 41 |
| wsA_regression_targeted2 (account_invite, onboarding, employee, new FK/migration tests, tests/unit, integration/core) | 2093 | **1** | 41 |
Blocked: 0. The 41 skips are pre-existing.
**Open failure:** `tests/integration/core/test_business_events.py::test_only_committed_work_is_logged` fails in the full ordering. It is order-dependent and independent of B13: it also fails with only `test_registration_flow.py` + `tests/unit` before it (`scratch_be_order2`), and passes alone and after each suite separately (structlog `cache_logger_on_first_use` vs `capture_logs`). Not fixed (out of scope).
Not done / untested: web, mobile, full regression, B5b payroll; real providers and real Celery worker + broker end-to-end (task body run via `apply`, dispatch `celery` mode never exercised against a live worker); other direct-send emails (password reset, verification, attendance reminders) are not on the outbox; no admin view of outbox state; migrations B/C on production-sized or real data; `openapi.json`.
Resources: root free 3.1 GiB at start and end of every batch (gates >=3 GiB start / <2 GiB stop never tripped); memory ~8 GiB available; teardown `stack.sh down b13-20261026a --confirm` removed only labelled containers (0 left) and its pgdata/minio; shared `hrms-postgres/redis/minio` untouched (still up 12 h). Git: 238 -> 262 paths, every baseline path still present (set difference empty), `git diff --stat` 142 -> 150 tracked files; a new untracked `docs/qa/` appeared mid-session that this run did not create. No commit, push, merge or deploy.
