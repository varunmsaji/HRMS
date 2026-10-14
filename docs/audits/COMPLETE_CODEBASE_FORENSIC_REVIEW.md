# COMPLETE CODEBASE FORENSIC REVIEW

Audit date: 2026-10-08  
Protocol: `docs/audits/CODE_REVIEW_AGENT_PROTOCOL.md` (version 1.0)  
Method: read-only source, schema, migration, and configuration review. Findings below were re-opened in source during this pass and then challenged. A same-day draft of this file was not treated as evidence.

## 1. Executive Summary

**CODEBASE AUDIT — PRODUCTION BLOCKERS FOUND**

No cross-tenant data escape and no authentication bypass were proved on the paths that were traced. Authenticated business routes go through a JWT session, a permission dependency, and a company id written into `app.company_id` for PostgreSQL row-level security. The runtime role the deployment documents is `hrms_app` (NOSUPERUSER, NOBYPASSRLS).

The system is not production-ready. Four confirmed P1 defects block a correct rollout:

1. Verification, password-reset, invite, and onboarding links are built from `web_app_base_url`, which defaults to `http://localhost:3000`. The production boot guard and `apps/api/env/.env.production.example` never set it.
2. Company registration issues a full admin session before the email is verified. Password login later refuses an unverified user. Refresh and `get_current_user` do not, so the session can be rotated for the refresh lifetime.
3. Income tax is computed on every earning line, including components flagged `is_taxable=false`, and that month’s total is multiplied by the months left in the financial year.
4. Leave year-end lapse and carry-forward use the lifetime ledger sum at the moment the job runs, so leave approved in the new year before the sweep reduces the amount that is forfeited.

Face “liveness” is face detection. That is a P1 only when `FACE_VERIFICATION_PROVIDER=facepp`. The default and the production example are `disabled`.

Terminal condition: **TERMINAL C**. Implementation was stopped. No application code, tests, or migrations were changed by this review.

## 2. Architecture

```
Browser / Flutter
  → Next.js (apps/web) or Flutter (apps/mobile)
  → FastAPI routers (apps/api)
  → get_current_user (JWT + session + membership)
  → require_permission / data scope
  → get_tenant_context (JWT company; header must match)
  → set_config('app.company_id')
  → service → repository → SQLAlchemy
  → PostgreSQL RLS (ENABLE + FORCE + tenant_isolation on tenant tables)
```

| Layer | What it is |
|---|---|
| Backend | FastAPI, SQLAlchemy 2 async, Alembic, Pydantic |
| Frontend | Next.js 16, React 18, Vitest |
| Mobile | Flutter |
| Database | PostgreSQL 16 |
| Cache / queue | Redis, Celery |
| Object storage | MinIO via aioboto3 (`S3_ENDPOINT_URL`) |
| Auth | Argon2 passwords, JWT access, rotating refresh tokens |
| Email | SMTP or Mailtrap; logging sender refused outside development |
| Payments | No bank integration. Payroll `mark_paid` is a status change. |

`TenancyMiddleware` copies `X-Company-Id` before authentication. `get_tenant_context` then rejects a header that disagrees with the JWT and sets the GUC from the verified company. Tables resolved before a company is known (`user`, `session`, `refresh_token`, invites, verification tokens) are outside tenant RLS.

## 3. Module Status

No `docs/audits/*_FINAL_REVIEW.md` closure report exists. No module is CLOSED. This pass stopped at confirmed production blockers (protocol §32 TERMINAL C) and did not remediate.

| Module | Status | P0 | P1 | P2 | P3 |
|---|---:|---:|---:|---:|---:|
| Authentication / Account | OPEN | 0 | 1 | 0 | 0 |
| RBAC / Permissions / Tenant Isolation | OPEN | 0 | 0 | 0 | 0 |
| Organisation | OPEN | 0 | 0 | 0 | 0 |
| Employee / Employment Lifecycle | OPEN | 0 | 0 | 1 | 0 |
| Employee Documents | OPEN — uncommitted work not closed | 0 | 0 | 0 | 0 |
| Onboarding / Employee Import | OPEN | 0 | 0 | 0 | 0 |
| Attendance | OPEN | 0 | 1 | 1 | 0 |
| Leave | OPEN | 0 | 1 | 1 | 0 |
| Overtime / Regularization | OPEN | 0 | 0 | 0 | 0 |
| Payroll | OPEN | 0 | 1 | 0 | 0 |
| Notifications / Email | OPEN | 0 | 1 | 0 | 0 |
| Files / Object Storage | OPEN | 0 | 0 | 0 | 0 |
| Audit / Compliance | OPEN | 0 | 0 | 0 | 0 |
| Frontend | OPEN | 0 | 0 | 0 | 0 |
| Mobile | OPEN | 0 | 0 | 0 | 0 |
| Background Jobs / Celery | OPEN | 0 | 0 | 0 | 0 |
| Database / RLS / Migrations | OPEN | 0 | 0 | 1 | 0 |
| Docker / CI/CD / Production Operations | OPEN | 0 | 0 | 0 | 0 |

P1 counts are the confirmed blockers. A module can appear in more than one row when one defect spans it (email links are both Email and Authentication; year-end is Leave; the reminder bug is Attendance and Background Jobs). The table counts each finding once, on its primary module, except where the finding’s impact is the module itself.

Primary assignment used below: FINDING-001 Email, FINDING-002 Authentication, FINDING-003 Payroll, FINDING-004 Leave, FINDING-005 Attendance, FINDING-006 Database/RLS, FINDING-007 Employee, FINDING-008 Leave, FINDING-009 Attendance.

## 4. Critical Findings

No P0.

Confirmed P1:

- FINDING-001 — production links default to localhost
- FINDING-002 — unverified registration session survives refresh
- FINDING-003 — TDS annualizes the whole month’s gross and ignores `is_taxable`
- FINDING-004 — year-end forfeiture uses the lifetime balance
- FINDING-005 — face liveness is face detection (only when Face++ is enabled)

## 5. Security Findings

## FINDING-001 — Production email links default to localhost

Severity: P1

Confidence: HIGH

Module: Notifications / Email

Location: `apps/api/src/hrms/core/config/settings.py`

Function/Class: `Settings.web_app_base_url`, `Settings._guard_non_development_config`

Evidence: `web_app_base_url` defaults to `http://localhost:3000` (line 219). `_guard_non_development_config` (lines 341–422) requires JWT secrets, CORS, S3, and `email_provider` of `smtp` or `mailtrap`. It does not require `web_app_base_url`. `apps/api/env/.env.production.example` has no `WEB_APP_BASE_URL`. Links are built in `identity/service.py` (`reset_url`, `verify_url`), `account_invite/service.py`, `onboarding/service.py`, and `attendance/reminders.py`.

Problem: A production process that follows the example sends real email whose links point at the API host’s localhost.

Failure/Attack Scenario: An operator copies `.env.production.example`, fills the required secrets, and boots. Verification, reset, invite, and onboarding messages are delivered. Every link is `http://localhost:3000/...`. The recipient cannot complete the flow. Combined with FINDING-002, the registrant already has a session, and the victim who owns the inbox cannot use the link to get there first.

Expected: Non-development boot refuses to start until `web_app_base_url` is an explicit absolute URL, and the production example sets it beside `CORS_ALLOWED_ORIGINS`.

Actual: Boot succeeds. The default is localhost.

Impact: Account verification, password reset, company invites, and onboarding links are wrong in any deployment that does not discover this undocumented setting.

Why Existing Tests Don't Catch It: Tests run with `ENVIRONMENT=development`, where the localhost default is correct. Nothing asserts that the production guard rejects a missing base URL.

Recommended Fix: In `_guard_non_development_config`, reject an empty `web_app_base_url` and reject the localhost default. Add `WEB_APP_BASE_URL` to `.env.production.example` and the deployment runbook. Do not change the development default.

Adversarial result: CONFIRMED. The guard was re-read in full. There is no later check.

## FINDING-002 — Unverified registration session survives refresh

Severity: P1

Confidence: HIGH

Module: Authentication / Account

Location: `apps/api/src/hrms/modules/organisation/service.py`; `apps/api/src/hrms/modules/identity/service.py`; `apps/api/src/hrms/core/auth/dependencies.py`

Function/Class: `OrganisationService` registration (`issue_tokens_for` at lines 824–831); `IdentityService.login`; `IdentityService.refresh`; `get_current_user`

Evidence: Registration calls `issue_tokens_for` and only then `send_verification_email`. The comment at `organisation/service.py` lines 832–836 says the session is unaffected and that a later login is blocked. `login` raises `EmailNotVerifiedError` when `email_verified_at` is None (identity `service.py` lines 85–92). `refresh` (lines 150–161) re-checks session, `user.status == ACTIVE`, and membership. It does not read `email_verified_at`. `get_current_user` (dependencies.py lines 36–46) does the same.

Problem: The verification gate exists only on the password-login method. The token issued at registration never passes through that method, and rotating the refresh token does not add the check.

Failure/Attack Scenario: Public registration with an email the caller does not control creates a company-admin session immediately. Password login is refused until verification, which does not matter: the caller refreshes the token until `JWT_REFRESH_TTL_DAYS` (30 in the production example). The inbox owner receives a localhost link (FINDING-001) or a real link that no longer prevents the existing session.

Expected: No company-admin capability until `email_verified_at` is set, including refresh and access-token use. Invite acceptance that already sets `email_verified_at` (account invite service) can keep issuing a session.

Actual: The first session and every refresh of it skip the check. The code comments describe this as intentional for the first response and do not mention refresh.

Impact: An unverified address becomes the company administrator for the refresh lifetime.

Why Existing Tests Don't Catch It: A test that only calls `login` after registration sees the 403 and passes. It does not refresh the registration token.

Recommended Fix: After the user load in `refresh` and `get_current_user`, reject `email_verified_at is None` the same way `login` does. Keep invite acceptance, which stamps `email_verified_at` at accept time. Registration should still be able to return a response, but that response must not be a usable admin session unless product explicitly accepts a short pending-verification token that cannot call tenant APIs.

Adversarial result: CONFIRMED. Hidden guards were searched. `email_verified_at` is referenced in identity login, the verification marker, and invite accept. It is not referenced in refresh or `get_current_user`.

## FINDING-005 — Face liveness is face detection

Severity: P1 when `FACE_VERIFICATION_PROVIDER=facepp`. Not a blocker while the provider stays `disabled`.

Confidence: HIGH

Module: Attendance

Location: `apps/api/src/hrms/modules/attendance/face_verification.py`

Function/Class: `FaceppFaceVerificationProvider.check_liveness`

Evidence: The module docstring (lines 19–23) states there is no single-photo anti-spoofing call and that `check_liveness` reports `LIVE` whenever `/detect` finds a face. The method (lines 230–234) returns `LivenessResult("LIVE", None, {})` when a face token exists. `face_service.py` calls `check_liveness` on enrollment and punch. `Settings.face_verification_provider` defaults to `disabled`. The production example sets `FACE_VERIFICATION_PROVIDER=disabled`.

Problem: A printed photo or screen that Face++ detects and matches is accepted as a live punch once the provider is enabled.

Failure/Attack Scenario: Face++ is turned on. An employee, or someone holding their reference photo, submits a still image. Detection succeeds, liveness returns `LIVE`, and search confidence can MATCH.

Expected: A failed or unavailable liveness check rejects the punch. Detection is not labeled liveness.

Actual: Detection is returned as `LIVE`. The source comment says this is deliberate.

Impact: Face attendance is not anti-spoofing. It is safe to leave disabled. It is not safe to enable as a liveness control.

Why Existing Tests Don't Catch It: A test that mocks a `LIVE` result, or that only checks the disabled provider, never proves anti-spoofing.

Recommended Fix: Do not enable `facepp` for production punches until a real liveness step exists. Until then, `check_liveness` should fail closed (reject, or a distinct non-LIVE result that the punch path refuses) if the product requirement is anti-spoofing. Do not invent a score.

Adversarial result: CONFIRMED, conditional. The default path does not call Face++.

## 6. Tenant/RLS Findings

Authenticated tenant routes that were traced set `app.company_id` from the JWT company after the header is checked. Tenant business tables created in Alembic use `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, and a `tenant_isolation` policy on `company_id`. CI’s database init creates `hrms_app` as NOSUPERUSER and NOBYPASSRLS, and `tests/security/test_rls_runtime_role.py` is written to connect as that role. This pass did not re-run that test.

`user`, `session`, `refresh_token`, and pre-company tokens are intentionally outside tenant RLS.

## FINDING-006 — `company` is FORCE RLS without ENABLE, so the force does nothing

Severity: P2

Confidence: HIGH on the DDL. No route that lists every company was found in this pass.

Module: Database / RLS

Location: `apps/api/scripts/sql/001_init_schema.sql` lines 464–465, applied by the init Alembic revision. No later migration runs `ALTER TABLE company ENABLE ROW LEVEL SECURITY`.

Function/Class: schema DDL

Evidence: The script runs `ALTER TABLE company FORCE ROW LEVEL SECURITY` and comments that `company` has no `company_id` and needs no policy. PostgreSQL applies row security only after `ENABLE ROW LEVEL SECURITY`. `FORCE` without `ENABLE` does not filter rows. `hrms_app` can `SELECT` every `company` row if a query forgets a predicate.

Problem: The documented RLS backstop does not exist for the tenant root table.

Failure/Attack Scenario: A future or missed `WHERE` on `company` returns every tenant’s profile columns to an authenticated caller. Employee, payroll, and leave tables are not exposed by this gap.

Expected: Either enable RLS with a policy `id = current_setting('app.company_id')::uuid` for tenant-scoped reads, or document `company` as deliberately global and keep every read on an explicit id predicate that is tested.

Actual: FORCE is a no-op. Application company routes that were read filter by id.

Impact: Defense-in-depth hole on company profile data. Not a proved employee/payroll cross-tenant read.

Why Existing Tests Don't Catch It: RLS tests target tables that have policies. A count of `company` as `hrms_app` is not what those tests assert, based on the DDL comment that says RLS is not applicable.

Recommended Fix: New migration: `ENABLE ROW LEVEL SECURITY` on `company` plus a policy that allows a row when `id` equals the GUC, with an explicit bypass only for the pre-tenant registration and login company lookup (those run as a path that must see the row before the GUC is the caller’s company — design that path before enabling, or login breaks). Do not edit `001_init_schema.sql` if it has already been applied.

Adversarial result: CONFIRMED as a missing control. LOWER than P1 because no current cross-tenant business-data query was shown.

`user_role` and `role_permission` are documented in `002_row_level_security.sql` as inheriting a parent policy. PostgreSQL does not filter a child table that has no policy. That is UNVERIFIED as an exploit in this pass: the RBAC queries that were not fully re-traced may always pass `company_id`. Recorded under unverified items.

## 7. Database Findings

Monetary amounts that were inspected in payroll are integer paise. Leave amounts are `Numeric`. Employment overlap is constrained in the employment migrations (not re-proved by executing the database in this pass). Finalised payroll immutability is a later migration (`20261013090000_payroll_finalised_immutable.py`); the trigger body was not re-executed here.

FINDING-006 is the confirmed database defect.

Committed migration head on `a2047b3` is `20261013090000_payroll_finalised_immutable.py`. Two further revisions exist only as untracked files (`20261014090000_employee_document.py`, `20261014091000_employee_view_documents_backfill.py`) and are not part of HEAD.

## 8. Concurrency Findings

Payroll finalise takes `lock_payroll_finalise` and then a shared attendance-period lock, re-reads the run, and refuses to finalise unless status is still `APPROVED` (`payroll/service.py` lines 2840–2904). Leave balance mutations that were read use a transaction advisory lock per employee and leave type. Punch idempotency was not re-traced in this pass.

No new lost-update on finalise was proved. FINDING-004 is a check-then-act on the wrong balance, which is a correctness bug under normal scheduling, not only a lock bug: the lock serializes the sum, and the sum is still the wrong population.

## 9. Idempotency Findings

`idempotency_key` is a tenant table with RLS (`20261011090000_idempotency_key.py`). Payroll arrears application has a database guard (`IntegrityError` mapped to `PayRunArrearsStaleError` in finalise). Mobile retry keys were not re-opened in this pass (unverified).

## 10. Background Job Findings

## FINDING-009 — A failed attendance reminder is recorded as already sent

Severity: P2

Confidence: HIGH

Module: Attendance / Background Jobs

Location: `apps/api/src/hrms/modules/attendance/reminders.py`

Function/Class: reminder send path and `_already_sent`

Evidence: After the send loop, `AuditService.record` runs unconditionally (lines 198–214) and stores `send_failures`. `_already_sent` (lines 217–224) matches action, period, and `as_of`. It does not require `send_failures = 0`.

Problem: The idempotency marker is “an audit row exists,” not “delivery succeeded.”

Failure/Attack Scenario: SMTP is down. Every send fails. The audit row is written. The next run the same day returns at `_already_sent` and sends nothing. The following day may be outside the reminder lead window.

Expected: A run with send failures does not count as sent, or a later run retries recipients that failed.

Actual: The failure is stored and then treated as success.

Impact: Incomplete-day reminders can be silently skipped for that date.

Why Existing Tests Don't Catch It: A test that only asserts an audit row after a successful fake sender never simulates `send_failures > 0` followed by a second run.

Recommended Fix: Skip the audit insert when `send_failures > 0`, or teach `_already_sent` to ignore rows whose `send_failures` is non-zero. Keep the success path idempotent.

Adversarial result: CONFIRMED.

Celery Beat leader election was not re-verified in this pass.

## 11. API Findings

Public routes include login, refresh, forgot/reset password, email verify, company registration, onboarding token, and account-invite token. Health is unauthenticated. Business routes that were sampled take a tenant context and a permission dependency. This pass did not enumerate all 300+ route decorators again.

Payroll finalise does not consult the previous month. `finalise` (lines 2840–2916) locks, checks arrears and input freshness, and sets `FINALISED`. A search of `payroll/service.py` found no prior-month sequence check. Out-of-order months are a payroll correctness risk for TDS year-to-date and are recorded as part of FINDING-003’s operational impact, not as a separately numbered exploit, because the missing predicate was confirmed only for `finalise` and not for every create/approve path.

## 12. Frontend Findings

Not re-audited end to end in this pass. Uncommitted web files `document-panel.tsx`, `document-reject-dialog.tsx`, `employees/[id]/page.tsx`, and `lib/employee/types.ts` are part of the working tree and were not closed. Pay-run 409 handling from the earlier draft was not re-opened; it is unverified here.

## 13. Mobile Findings

Not re-audited in this pass. Refresh-token storage and idempotency-key retries from the earlier draft are unverified here.

## 14. Payroll Findings

## FINDING-003 — TDS annualizes the whole month’s gross and ignores `is_taxable`

Severity: P1 for any live salary run

Confidence: HIGH

Module: Payroll

Location: `apps/api/src/hrms/modules/payroll/engine.py`; `apps/api/src/hrms/modules/payroll/income_tax.py`; `apps/api/src/hrms/modules/payroll/models.py`

Function/Class: payroll compute engine; `compute_tds`; `SalaryComponent.is_taxable`

Evidence: `SalaryComponent.is_taxable` exists (models.py line 55) and is copied onto component snapshots in `payroll/service.py`. `engine.py` never reads `is_taxable`. Gross is `sum` of every `EARNING` line (line 463, after arrears). That integer is passed as `this_month_taxable_earnings_minor` (lines 471–476). `compute_tds` sets `projected_annual = ytd_taxable_earnings_minor + this_month_taxable_earnings_minor * remaining` (income_tax.py line 145). `remaining` is months from this month through March, inclusive (`months_remaining_in_fy`).

Problem: A one-off earning and a non-taxable allowance are both treated as the employee’s monthly run-rate for the rest of the financial year.

Failure/Attack Scenario: April gross includes a taxable salary of ₹50,000 and a one-off taxable bonus of ₹100,000, or a non-taxable allowance. The projection multiplies ₹150,000 (or the untaxable allowance) by 12. TDS withheld in April is the annual tax on that inflated income, divided by months remaining. Later months do not need a second bug for the employee to have been over-withheld. Finalising a later month before an earlier one (no sequence check in `finalise`) makes year-to-date inputs wrong in the other direction.

Expected: Taxable earnings are the sum of earning lines whose component is taxable. Amounts that are not expected to repeat are not multiplied by `remaining`. Months in a legal entity are finalised in order, or year-to-date is computed from finalised months only and refuses a gap.

Actual: The flag is master data. The projection treats the whole month as the run-rate. `finalise` does not require the previous month to be finalised.

Impact: Live payroll over-withholds. This is a statutory-calculation defect, not a duplicate bank payment. `mark_paid` does not call a bank.

Why Existing Tests Don't Catch It: A test that asserts the formula `gross * remaining` matches the implementation while the implementation is the bug. A test that never sets `is_taxable=false` cannot see the unused column.

Recommended Fix: Sum only taxable earning components into `this_month_taxable_earnings_minor`. Project only the recurring taxable portion; add one-off taxable amounts once. Refuse to compute or finalise a month when an earlier month in the same financial year and legal entity is not finalised. This is a payroll-rule change and needs a fixture that states the expected rupees, not a line-coverage test.

Adversarial result: CONFIRMED. `is_taxable` is absent from `engine.py`. The cash-basis comment at lines 465–467 justifies taxing arrears in the payment month. It does not justify multiplying them by months remaining.

## 15. Attendance Findings

FINDING-005 (conditional) and FINDING-009.

Punch idempotency, shift boundaries, and period-close races were not re-traced in this pass.

## 16. Leave Findings

## FINDING-004 — Year-end forfeiture uses the lifetime balance

Severity: P1 at the first leave-year boundary

Confidence: HIGH

Module: Leave

Location: `apps/api/src/hrms/modules/leave/repository.py`; `apps/api/src/hrms/modules/leave/service.py`

Function/Class: `LeaveLedgerRepository.get_balance`; `LeaveAccrualService._year_end_for_employee`

Evidence: `run_year_end_for_company` documents that it applies the year-end rule “against the balance as it stands when this runs” (service.py lines 1734–1735). The catch-up window is `leave_year_end_catchup_days` (default 5). `_year_end_for_employee` locks the balance and calls `get_balance` (lines 1870–1882). `get_balance` (repository.py lines 384–392) is `SUM(amount)` for that company, employee, and leave type with no date predicate. `_year_end_split` lapses the excess of that sum over the carry cap, or the whole sum when the action is `LAPSE`.

Problem: Debits dated on or after the new year start are inside the sum that is supposed to represent the old year.

Failure/Attack Scenario: Balance 20, carry cap 5. On the morning of the new leave year, before the daily sweep, 15 days are approved. The sum is 5. Lapse is 0. The 15 days that should have been forfeited are taken. The sweep then claims `leave_year_end_run`, so a later run will not repair it.

Expected: Lapse and carry-forward are computed from ledger rows effective before the new year start. Leave dated on the new year is not part of that sum.

Actual: The lifetime sum at job time is the input. The docstring states that timing. The business result is still wrong.

Impact: Carry-forward caps and full lapse can be bypassed by approving leave during the catch-up window before the job. A job that runs before any new-year approval does not hit this.

Why Existing Tests Don't Catch It: A test that seeds only old-year rows and runs the sweep sees the correct lapse. It passes while the date filter is missing.

Recommended Fix: Sum ledger rows with `effective_date < year_start` for the forfeiture input. Keep the balance lock. Add a test that approves new-year leave first and asserts the old-year excess is still forfeited.

Adversarial result: CONFIRMED. The “as it stands when this runs” sentence is the bug, not a hidden guard.

## FINDING-008 — A negative leave adjustment does not apply the balance floor

Severity: P2

Confidence: HIGH

Module: Leave

Location: `apps/api/src/hrms/modules/leave/service.py` lines 1304–1329

Function/Class: leave ledger adjustment

Evidence: When `body.amount < 0` the code takes `lock_balance` and inserts `body.amount`. There is no read of the balance and no comparison to `negative_balance_floor` before the insert.

Problem: Approval and encashment re-check the floor under the same lock. Adjustment does not. The lock only orders the insert against those other debits.

Failure/Attack Scenario: A caller with `LEAVE.BALANCE_ADJUST` posts −30 against a balance of 2 and a floor of 0. The balance becomes −28. An application for the same days would have been refused.

Expected: A negative adjustment under the balance lock is rejected when it would pass the floor, using the same rule as approval.

Actual: The row is inserted.

Impact: Authorized HR can drive a balance below the policy floor. This is not an anonymous bypass.

Why Existing Tests Don't Catch It: Tests that only cover approval’s floor check do not call adjustment.

Recommended Fix: Under the existing lock, read the balance and refuse the debit when it would cross the floor. Do not skip the lock.

Adversarial result: CONFIRMED. No floor check sits between the lock and the insert.

## 17. Employee Findings

## FINDING-007 — Termination does not clear `employee.is_active`, and seat counts use that flag

Severity: P2

Confidence: HIGH

Module: Employee / Employment Lifecycle

Location: `apps/api/src/hrms/modules/employee/service.py`; `apps/api/src/hrms/modules/employee/repository.py`

Function/Class: `terminate_employment`; `count_active_employees`

Evidence: `terminate_employment` sets `employment.status` to `TERMINATED` and `last_working_day` (lines 1427–1432). It revokes login via `_end_access` when the last working day is already before the company-local today (lines 1465–1483). It does not set `employee.is_active`. The method comment says nothing is deactivated. `count_active_employees` (repository.py lines 95–103) counts `is_active` and `deleted_at IS NULL`. `deactivate_employee` is a separate `is_active=False` path.

Problem: A terminated employee still consumes an `EMPLOYEE_SEATS` seat. `employee.is_active` and `employment.status` diverge. Login revocation is a different mechanism and does work for a past last working day.

Failure/Attack Scenario: The company is at its seat limit. HR terminates someone whose last working day has passed. Creating the replacement fails the seat check because the terminated row is still `is_active`.

Expected: Seat count matches people who can still be employed, or termination clears `is_active` when access ends. The product rule should be one rule, written down.

Actual: Seats follow `is_active`. Termination does not change it. Access follows membership revocation.

Impact: Seat-limit false full. Not an authentication bypass: `_end_access` removes membership.

Why Existing Tests Don't Catch It: A test that asserts employment status `TERMINATED` and a revoked membership never asserts `count_active_employees`.

Recommended Fix: When access is ended, set `is_active` false if the product seat is “currently employed.” If terminated people are meant to hold a seat until the record is archived, document that and stop treating the mismatch as a defect. Do not invent a second status.

Adversarial result: CONFIRMED. The “nothing is deactivated” comment is about HR records versus login. It does not mention seats. The seat query is real.

`employee.status` versus `employment.status` on this path: termination does not set an employee lifecycle status of `EXITED` in the block that was read. That split is the same finding, not a second defect.

## 18. Documents Findings

`document_validation.py` (untracked) sniffs PDF, JPEG, and PNG magic bytes, sanitizes the display filename, and builds an object key from server-generated ids. That helper, read in isolation, does not trust the client content type or the client filename for the storage key.

The rest of the uncommitted document feature (router, service, repository, migrations, web panel, permission backfill) was not closed in this pass. It must not be treated as audited. It is not on commit `a2047b3`.

## 19. Test Quality

The automated suite was not executed. Historical “N tests passed” figures are not current proof.

CI (`.github/workflows/ci.yml`) does run, on a fresh Postgres and Redis:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src/hrms`
- `uv run lint-imports`
- `uv run alembic upgrade head`
- a SQL check that `hrms_app` is NOSUPERUSER and NOBYPASSRLS
- `uv run pytest tests/unit`
- `uv run pytest tests/integration tests/security` against Postgres, Redis, and MinIO

The default test `DATABASE_URL` is the schema owner `hrms`, which bypasses RLS. `tests/security/test_rls_runtime_role.py` is the suite that reconnects as `hrms_app`. A green integration run does not by itself prove RLS.

False confidence, from the findings above:

- Login-only email-verification tests miss refresh (FINDING-002).
- TDS tests that encode `gross * remaining` miss FINDING-003.
- Year-end tests that never approve new-year leave first miss FINDING-004.
- Development-only settings tests miss FINDING-001.

Web CI runs `tsc --noEmit`, Vitest, and `next build --webpack`. ESLint is `continue-on-error`. Flutter is not a CI job. Those two are operational gaps, not re-proved defects in application logic.

## 20. Dependency/Supply Chain

CI runs `pip-audit` and `npm audit --omit=dev --audit-level=high` as blocking jobs. This pass did not re-run them.

Gitleaks uses image `zricethezav/gitleaks:latest` (`.github/workflows/ci.yml`). A floating tag can change what the gate detects. That is an operational observation, not a confirmed vulnerability in the application.

## 21. Deployment/Operations

Production shape in `.env.production.example` and `docker-compose.prod.yml` is a Hostinger VPS: Compose, Nginx, Postgres, Redis, MinIO. API connects as `hrms_app`. Migrations connect as `hrms`. Email provider must be SMTP or Mailtrap or the process refuses to boot.

FINDING-001 is the deployment defect: the example is otherwise strict and still omits the URL embedded in every email.

Redis authentication and metrics/alerting were not re-verified.

## 22. Documentation Drift

`face_verification.py` correctly says liveness is not anti-spoofing. A product description that calls face punch “liveness” would be drift; the code is the accurate one.

`001_init_schema.sql` says RLS is not applicable to `company` while still running `FORCE ROW LEVEL SECURITY`. The comment and the statement disagree with PostgreSQL behavior (FINDING-006).

Leave year-end’s docstring matches the code (current balance) and disagrees with a carry-forward cap that is supposed to apply to the old year (FINDING-004).

## 23. False Confidence

See §19. A passing login verification test, a TDS formula test, and a year-end test without a prior new-year debit can all pass while FINDING-002, FINDING-003, and FINDING-004 remain.

## 24. Accepted Risks

None were accepted in this pass. FINDING-005 is dormant while Face++ is disabled; that is a precondition, not an acceptance that enabling it is safe.

## 25. Unverified Items

- Full pytest, web Vitest, TypeScript, production build, Flutter tests, pip-audit, and npm audit were not run.
- Mobile refresh storage and mobile idempotency keys.
- Employee-import partial-commit replay.
- Payroll permission `data_scope` ignored when every grant is `COMPANY`.
- Celery Beat duplication.
- Redis without authentication.
- Direct `SELECT` of `user_role` / `role_permission` as `hrms_app`.
- Whether any current route lists all `company` rows.
- The uncommitted employee-document feature beyond `document_validation.py`.
- Punch idempotency, overnight shifts, and payroll payment idempotency beyond the arrears integrity error seen in `finalise`.

## 26. Remediation History

This pass changed no application code, tests, or migrations.

Files written:

- `docs/audits/CODE_REVIEW_AGENT_PROTOCOL.md` (the protocol the user asked to save)
- `docs/audits/COMPLETE_CODEBASE_FORENSIC_REVIEW.md` (this report)

## 27. Final Findings Matrix

| ID | Severity | Module | Status | Evidence | Risk |
|---|---|---|---|---|---|
| FINDING-001 | P1 | Email | CONFIRMED, not fixed | `settings.py:219`, guard lines 341–422, `.env.production.example` | Users cannot verify, reset, or join from the links production will send |
| FINDING-002 | P1 | Authentication | CONFIRMED, not fixed | `organisation/service.py:824-838`, `identity/service.py:129-161`, `auth/dependencies.py:36-46` | Unverified registrant keeps a company-admin session via refresh |
| FINDING-003 | P1 | Payroll | CONFIRMED, not fixed | `engine.py:463-476`, `income_tax.py:145` | Live payroll over-withholds; `is_taxable` is unused |
| FINDING-004 | P1 | Leave | CONFIRMED, not fixed | `leave/repository.py:384-392`, `leave/service.py:1734-1882` | Carry-forward cap bypassed if new-year leave is approved before the sweep |
| FINDING-005 | P1 conditional | Attendance | CONFIRMED, not fixed | `face_verification.py:19-23`, `230-234` | Photo spoof if Face++ is enabled |
| FINDING-006 | P2 | RLS | CONFIRMED, not fixed | `001_init_schema.sql:464-465` | `company` has no working RLS backstop |
| FINDING-007 | P2 | Employee | CONFIRMED, not fixed | `employee/service.py:1427-1483`, `repository.py:95-103` | Terminated employees still consume seats |
| FINDING-008 | P2 | Leave | CONFIRMED, not fixed | `leave/service.py:1304-1329` | Authorized adjustment can pass the balance floor |
| FINDING-009 | P2 | Attendance | CONFIRMED, not fixed | `reminders.py:198-224` | A failed reminder is not retried that day |

## 28. Final Production Recommendation

CODEBASE AUDIT — PRODUCTION BLOCKERS FOUND

### Remediation plan (not implemented)

Do these in order. Each is a small change. None of them is a redesign.

1. FINDING-001. Reject a missing or localhost `web_app_base_url` outside development. Add it to the production example. No migration.
2. FINDING-002. Reject unverified users in `refresh` and `get_current_user`. Add a test that registers, then refreshes, and expects rejection. No migration.
3. FINDING-004. Restrict the year-end sum to `effective_date < year_start`. Add a test that approves new-year leave before the sweep. No migration if the ledger already has `effective_date`.
4. FINDING-003. Tax only taxable components, and do not annualize one-off amounts. Add a rupee-level fixture. Refuse finalise when the previous month is open. No migration required for the calculation; a constraint is optional.
5. FINDING-005. Keep Face++ disabled until liveness fails closed. Do not ship a fake score.
6. FINDING-009, FINDING-008, FINDING-007, FINDING-006 after the P1s, in that order. FINDING-006 needs a new migration and a careful exception for login/registration, or those flows lose the ability to read `company`.

Rollback for 1–4 and 8–9 is a code revert. FINDING-006’s migration must be a new revision, not an edit to `001_init_schema.sql`, and its downgrade must `DISABLE ROW LEVEL SECURITY` only if login has been proved against the policy.

### REPOSITORY SNAPSHOT

| Item | Value |
|---|---|
| Branch | `main` (tracks `origin/main`) |
| Commit | `a2047b303c8f35aa3b0d81f8589b27762aac4f07` (`test plan document added`, 2026-10-08) |
| Working tree | Dirty. Uncommitted employee-document work, onboarding/organisation service edits, web document UI, two untracked Alembic revisions, this protocol, and this report. Those edits were not produced as remediations of the findings above. |
| Migration head on HEAD | `20261013090000_payroll_finalised_immutable` |
| Untracked later revisions | `20261014090000_employee_document`, `20261014091000_employee_view_documents_backfill` |
| Backend tests | Not run |
| Frontend tests | Not run |
| Mobile tests | Not run |
| Lint / typecheck / build | Not run |

Commands, from the repo and CI, for a later run:

- Backend: `cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy src/hrms && uv run lint-imports && uv run pytest`
- Frontend: `cd apps/web && npx eslint . && npx tsc --noEmit && npx vitest run && npx next build --webpack`
- Mobile: Flutter test / analyzer (not in CI)

### Phase record

STATUS: TERMINAL C. Audit phases 0–5 were executed as a read-only forensic pass focused on production-risk paths. Phases 7–12 (implementation, tests, regression, module closure) were not started because confirmed P1 blockers remain and the protocol says to stop implementation, document them, and not claim production readiness.

WHAT WAS REVIEWED: Repository layout, git snapshot, CI, settings boot guard, registration and refresh, face liveness, TDS projection, leave year-end balance, leave adjustment floor, termination versus seat count, company RLS DDL, attendance reminder idempotency, payroll finalise locking, and the document-validation helper.

WHAT WAS CHANGED: The protocol file and this report only.

WHAT WAS NOT CHANGED: Application source, tests, migrations, configuration, commits, pushes.

FINDINGS: 5 confirmed P1 (one conditional), 4 confirmed P2, no P0.

TESTS: Not run.

REGRESSION: Not run.

REMAINING RISKS: The confirmed P1s. The uncommitted document feature. Every item in §25.

NEXT PHASE: Remediation of FINDING-001 only, after an explicit request to leave TERMINAL C and start Phase 7. Do not start with payroll or RLS.
