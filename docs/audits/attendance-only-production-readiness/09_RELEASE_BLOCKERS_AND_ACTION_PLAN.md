# Release blockers and action plan

Order is the order to do the work. Do not start with payroll.

## A. Must fix before deployment

These are the only items that should stop an attendance-only release.

| ID | Action | Why it blocks |
|---|---|---|
| ATT-REL-001 | Review and package the working tree. Do not deploy `f6340eb` or `origin/main` as the release artifact. The tenant fix, attendance overview, CSP middleware, and shift-tenant migration are not in that commit. | There is no coherent release commit today. |
| ATT-SEC-001 | The packaged API must be the working-tree tenancy code: middleware does not read `X-Company-Id`; the token sets `app.company_id`; a mismatched header is 404. | The committed middleware sets tenant context from the header before authentication. |
| ATT-QA-001 | Run the existing integration suite and the RLS runtime-role tests on an **isolated** database (CI service containers, not `hrms_dev`). Require green, including `test_attendance_rls_runtime_role.py`, `test_tenant_resolution_runtime_role.py`, `test_company_attendance_overview.py`, and `test_shift_tenant_fk_runtime_role.py`. | This audit did not execute them. They are the proof of punch behaviour and tenant isolation. |
| ATT-DB-001 | Apply Alembic through `20261031090000` on the release database as part of that package. Read the migration’s pre-check. If it aborts on cross-company shift ids, fix the data before forcing it. | Roster and regularization shift tenancy is otherwise application-only. |
| ATT-REG-001 | Either extend both check constraints to include `EARLY_DEPARTURE_APPROVAL`, or remove that type from `schemas.py`, the policy allow-list, and the Flutter form before anyone can select it. | The API accepts a type the database rejects. |
| ATT-OPS-001 | Set `ENVIRONMENT=production`, real JWT and PII secrets, a non-example database password, `hrms_app` as the runtime role, `TRUSTED_PROXY_HOSTS` to Nginx, CORS to the web origin, and build the web image with the HTTPS API URL. | Defaults are a development stack with a non-`Secure` refresh cookie behind TLS. |
| ATT-OPS-002 | Run `pg_backup.sh`, restore into a new empty database with `pg_restore.sh`, confirm `alembic current`, a login, and one attendance read. Record the time in the disaster-recovery doc. Put at least one copy off the VPS. | No restore has been recorded. Same-disk dumps do not survive losing the VPS. |
| ATT-MOB-001 | Before any phone is handed to an employee: release signing config, version code, and `--dart-define=API_BASE_URL=https://…`. Confirm a release build on a device can check in and see the punch on the web. | The current release build is debug-signed and targets localhost over HTTP, which release Android will not cleartext. |
| ATT-CSP-001 | Repeat the CSP suite against the real Nginx URL (`CSP_E2E_BASE_URL`), or perform the same login and dashboard hydration check in a browser on that host. Do not disable CSP to get there. | Local `next start` passed (15 tests). The standalone container and Nginx path did not run. |

After A, a small company can use web check-in and the company dashboard for attendance without payroll. Mobile distribution waits on ATT-MOB-001 plus one device pass.

## B. Should fix soon after deployment

Important, and not a reason to block the first attendance release if A is done and the operating limits below are accepted.

| ID | Issue | Acceptable limit until fixed |
|---|---|---|
| ATT-CALC-003 | `is_regularized` and `is_pending_approval` are overwritten on every recompute. | Trust the regularization request and its action rows, not the day flag, until this is fixed. The synthetic punches remain. |
| ATT-CALC-004 | WFH, WRONG_STATUS, FULL_DAY, and EXCESS_BREAK do not change status by themselves. | Do not enable those types on the published policy. `ON_DUTY` and missing-punch corrections are the ones that do something. |
| ATT-API-001 / ATT-WEB-004 | Attendance page and roster calendar stop at 500 rows with no warning. | Use `/app/dashboard` for headcount. Keep the pilot under the cap or do not quote Attendance-page totals. |
| ATT-WEB-003 | Dashboard “present” includes half days and in-progress open punches. The Attendance page buckets them separately. | Tell admins the dashboard is the daily total. |
| ATT-PUNCH-001 / ATT-MOB-002 | Web sends no idempotency key. Mobile keeps the key only in memory. | Avoid double-taps. A duplicate same-direction punch inside the policy window collapses at calculation time. |
| ATT-PUNCH-002 | Calculate errors after a punch are swallowed. | Watch logs. The sweep at 09:30 IST is the backstop. Beat must be up. |
| ATT-SHIFT-001 | Overnight punches update the punch’s local date first. | Night-shift sites should expect yesterday’s row to catch up at 09:30, or recompute. |
| ATT-CALC-001 | Punch rounding is never applied. | Leave rounding at `NONE`. |
| ATT-CALC-002 | `AUTO_CLOSE` does not set `auto_closed` or synthesize a checkout. | Do not select that policy value. |
| ATT-WEB-001 / ATT-TZ-001 | Web cannot send geolocation, and geofence “today” uses the UTC date. | Leave `geofence_mode=DISABLED`. |
| ATT-WEB-005 | Payroll, salary, and statutory links are in the menu. | Label or hide them so nobody runs a pay run by mistake. Do not delete the module. |
| ATT-REG-002 | Regularization monthly cap uses the UTC month. | Noticeable only around 00:00–05:30 IST on the 1st. |
| ATT-TZ-002 / ATT-TZ-003 | Punch list filters and one calendar warning use the UTC date. | Day status itself uses the company zone. |
| ATT-SEC-003 | Access token `employee_id` can be stale for 15 minutes. | Rare unlink case. |
| ATT-SEC-004 | `AUTO` approval skips self-approval. | Do not publish that chain. |
| ATT-SEC-005 | Policy preview ignores data scope. | Seeded roles that can preview are company-wide. |
| ATT-FACE-001 | Face thresholds are uncalibrated. An enrolled profile blocks plain web punch. | Leave the provider disabled. |
| Performance | No measurement at 50–5,000 employees. | The overview is one grouped query. Do not promise a 5,000-person dashboard until it is timed. |
| iOS | Project exists, no signing team. | Defer unless iOS is in this release. |
| Beat | No leader lock. A second beat would double-fire. | Keep `replicas: 1`. |

## C. Can safely defer

| Item | Why it can wait |
|---|---|
| Payroll processing, salary structures, pay runs, payslips | Not on the punch or day-status path. Reopen of a locked period is the only attendance call into payroll, and only to refuse a finalised run. |
| Tax, PF, ESI, disbursement | Not referenced by check-in. |
| pgBackRest and a 5-minute RPO | Needed for a mature production posture. A tested logical dump plus an off-site copy is the gate in section A. PITR can follow. |
| Offline punch queue | The apps already fail closed. A queue is a later product. |
| MFA | Not required to make punch tenancy correct. |
| Attendance Excel export | Not required to see the day. |
| Department dashboard columns beyond present / absent / leave | The overview already returns the row. Extra columns are presentation. |
| Hiding every unfinished HR screen | Desirable (section B) and not a data-integrity gate. |
| Rewriting `middleware.ts` to Next’s `proxy` convention | The current file passed the CSP browser suite. |

## Suggested execution order

1. Freeze the working tree into a reviewed commit or release branch. Do not mix a drive-by payroll change into it.
2. Fix ATT-REG-001 in that same branch (migration or removal). Do not ship the type half-implemented.
3. Run CI integration and RLS on a disposable database. Fix only what that run shows.
4. Build the web image with the production API URL. Run the CSP suite through Nginx.
5. Restore drill on a copy. Write down the time.
6. Deploy API, worker, **one** beat, web, Nginx. Smoke: employee check-in, check-out, hours, admin dashboard counts, a regularization of type missing punch, an approved leave day showing `LEAVE`.
7. Only then cut a signed Android build and repeat check-in from the phone, then confirm the web shows the same row.

## Module inventory

| Module | Current status | Required for attendance? | Deployment impact | Recommendation |
|---|---|---|---|---|
| Authentication | Implemented | Yes | None if env is production | Ship the working tree |
| Employee management | Implemented | Yes | Needed so a person can punch | Ship |
| Attendance punch and day | Implemented | Yes | Core | Ship after section A |
| Shifts | Implemented | Supporting | Assignment and roster | Ship; apply shift FK migration |
| Work schedules / calendars | Implemented | Supporting | Day type | Ship |
| Weekly offs | Implemented | Supporting | Prevents false absence | Ship |
| Holidays | Implemented | Supporting | Same | Ship |
| Leave | Implemented | Yes for status when leave is used | Approved leave writes a projection in-process | Ship with attendance. Pending leave does not count. |
| Regularization | Implemented, one type broken | In the menus | ATT-REG-001 | Fix or hide the broken type |
| Company dashboard | Implemented in the working tree only | Yes | Uncommitted overview | Ship with the tree |
| Geofence | Implemented, default off | No | Web cannot satisfy REQUIRED | Leave off |
| Face | Implemented, default off | No | Can block web punch if enrolled | Leave off |
| Onboarding | Implemented | Only to create the employee | Does not block punch | Ship as-is |
| Payroll / payslips | Implemented enough to boot and to render screens | No | Import at startup; menu is visible | Keep the code. Hide or label the menu. |
| iOS | Project only | No | Not store-ready | Defer |
