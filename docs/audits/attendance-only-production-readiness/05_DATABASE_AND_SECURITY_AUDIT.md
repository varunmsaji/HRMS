# Database, authentication, authorization, and tenant isolation

Evidence: migration files and working-tree source. Alembic was not executed. No query was issued against `hrms_dev` or any other database. RLS runtime tests were read and not run.

## Migration head

128 version files, one linear chain, no merge revisions found by following `down_revision`. The only revision nothing else points at is `20261031090000` in `apps/api/alembic/versions/20261031090000_shift_tenant_fk.py` (`down_revision = "20261030090000"`). That file is **untracked**. Whether any database has applied it is unknown. This audit did not read `alembic_version`.

### ATT-DB-001 — Shift composite foreign keys are not in git

- Severity: High for roster and regularization integrity. Not a punch-insert blocker.
- Path: `20261031090000_shift_tenant_fk.py`.
- What it does: aborts if a roster or regularization shift id points at another company; otherwise adds `UNIQUE (company_id, id)` on `shift` and two composite foreign keys (`ON DELETE SET NULL` on the shift column only), `NOT VALID` then validated.
- The service already rejects a foreign shift. Until the migration is applied, that rejection is application-only. A foreign-key check does not consult RLS, which is why the composite key exists.
- Blocks deployment: apply it with the release if rosters or shift corrections are in use. Do not claim the database enforces shift tenancy before that.

## Constraints that attendance relies on

| Table | Rule | Where |
|---|---|---|
| `punch` | Partial unique `(company_id, idempotency_key)` when the key is not null. No unique punch time. `punch_time` is `timestamptz`. | `20260820090000_punch.py` |
| `attendance_day` | Unique `(company_id, employee_id, attendance_date)`. Composite FK to `employee (company_id, id)`. | `20260820100000_attendance_day.py`, `20261027092000_attendance_day_tenant_fk.py` |
| `shift_roster` | Partial unique `(company_id, employee_id, roster_date)` where not deleted. | `20260821090000_shift_roster.py` |
| `attendance_regularization_request` | Partial unique on `SUBMITTED` per employee-date. Status and type check constraints. | `20260822090000_regularization_request.py` |
| `holiday` | Partial unique `(calendar_id, date)` for active rows. | `20260818100000_holiday_expand.py` |
| `leave_application_day` | Unique `(leave_application_id, calendar_date)`. Overlap across applications is not a constraint. | `20260904090000_leave_l4_application.py` |
| `overtime_record` | Unique `attendance_day_id`. | model `attendance/models.py` 984–986 |

Correctness of “one open check-in” is **not** a database invariant. It depends on the idempotency key and on calculation-time collapse.

`punch.employee_id` references `employee(id)` only (`20260820090000_punch.py` 43–44). A foreign-key check ignores RLS. The punch API checks visibility first. The same class of gap is what the shift migration closes for shifts. A cross-tenant punch is refused in application code; the database will not reject a raw insert by the table owner.

Cascade: shift delete on the new composite FK sets the shift column null and does not delete roster or request rows. Punch rows are insert-only through the API. Attendance days are updated in place by `replace_derived_fields`. Historical punches remain. The `is_regularized` flag does not (ATT-CALC-003).

## Indexes for the hot reads

From the migrations (not from `EXPLAIN`):

- Punch: `(company_id, employee_id, punch_time)`, `(company_id, punch_time)`.
- Attendance day: unique employee-date, plus `(company_id, attendance_date, attendance_status)` and `(company_id, employee_id, attendance_date DESC)`.
- Overview query joins employee, current employment, current assignment, and the day for one date, then `GROUP BY` department and bucket (`overview.py` 123–172). That is one statement, not an N+1. It was not planned or timed.

A monthly history for one employee is the unique employee-date index. A company-wide day list without a tight date filter can still return up to the 500-row page cap per request.

## Row-level security

Attendance tables use `ENABLE` and `FORCE ROW LEVEL SECURITY` with `company_id = current_setting('app.company_id', true)::uuid`. Covered tables include punch, attendance day, breaks, roster, regularization and children, overtime, periods, policies, face profile, liveness, workplace authorization, and geofence attempts. A missing GUC fails closed.

`role_permission` and `user_role` have no `company_id` and no RLS. Isolation is the join through `role` and `user_company`, which are protected.

The schema owner bypasses RLS. Enforcement exists only when the API connects as `hrms_app` (`NOBYPASSRLS`). Tests that prove this are `tests/security/test_rls_harness.py`, `test_rls_runtime_role.py`, `test_tenant_resolution_runtime_role.py`, and the attendance runtime-role tests. **None of them were executed in this audit.**

### ATT-SEC-001 — Committed middleware trusts `X-Company-Id`

- Severity: Critical.
- Platform: API. Feature: every tenant-scoped query, including attendance.
- Committed file (`git show HEAD:apps/api/src/hrms/core/tenancy/middleware.py`): if the header parses as a UUID, `set_tenant` runs **before** `call_next`.
- Working tree (`apps/api/src/hrms/core/tenancy/middleware.py` 8–29): the middleware only clears context in `finally`. It does not read the header. `get_current_user` sets `app.company_id` from the signed token. `get_tenant_context` returns 404 when the header is present and is not the token’s company (`tenancy/dependencies.py` 26–42).
- Unit test `tests/unit/core/test_tenancy_middleware.py` asserts a raw header never becomes the tenant. **Executed: 2 passed** (included in the 180-test batch).
- Impact of shipping `HEAD`: tenant context can be chosen by the client before authentication. That is the bug the working tree is in the middle of fixing. This audit did not demonstrate a cross-tenant attendance read against a live database.
- Correction: release the working-tree tenancy files, not `f6340eb` alone. Re-run `tests/security/test_tenant_resolution_runtime_role.py` and `test_attendance_rls_runtime_role.py` on an isolated database.
- Blocks deployment: yes.

## Authentication

| Control | Evidence |
|---|---|
| Login | `POST /v1/auth/login` (`modules/identity/router.py` 60–78). |
| Passwords | Argon2 (`core/auth/passwords.py` 15–21). Length 8–128, letter and digit, common-password blocklist. |
| Access token | HS256, 15 minutes, claims `sub`, `company_id`, `session_id`, `employee_id`, `type=access` (`jwt.py` 15–46). |
| Refresh | Opaque, SHA-256 at rest, 30 days, rotated. Reuse revokes the family (`identity/service.py` 189–234). Cookie is HttpOnly, `SameSite=Lax`, `Path=/v1/auth` (`refresh_cookie.py` 37–48). Not in the JSON body. |
| Logout | Revokes the session and that session’s refresh tokens (`identity/service.py` 290–306). Access checks load the session, so logout kills the access token immediately. |
| Lockout | Five failures, 15 minutes. Counter is committed before the error so rollback cannot erase it. |
| Inactive user or company | Rejected. `SUSPENDED` / `PENDING_APPROVAL` are read-only, so punches are refused (`company_access.py` 19–50). |

### ATT-SEC-002 — Refresh cookie `Secure` follows the request scheme

- Severity: High behind TLS termination if proxies are not trusted.
- Path: `refresh_cookie.py` 46. Scheme becomes HTTPS only after `ProxyHeadersMiddleware` trusts the proxy (`app.py` 183–190). `trusted_proxy_hosts` defaults to empty.
- Impact: an empty setting behind Nginx leaves the cookie non-`Secure` and collapses per-IP rate limits onto the proxy address.
- Correction: set `TRUSTED_PROXY_HOSTS` to the Nginx hop in production. Do not trust the whole internet.
- Blocks deployment: yes as an environment gate (ATT-OPS-001), not as a code change.

### ATT-SEC-003 — `employee_id` in the access token is not re-read for up to 15 minutes

- Severity: Low.
- Path: `core/auth/dependencies.py` copies `employee_id` from the JWT.
- Impact: after an unlink, scope can follow the old claim until the access token expires. The client cannot edit the claim without the signing secret.
- Blocks deployment: no.

`ENVIRONMENT` defaults to `development` (`settings.py` 91), which enables OpenAPI docs. Non-development boot rejects default JWT and PII secrets, empty CORS, and a non-HTTPS app URL. It does not reject the example database password. Copying `.env.example` and changing only the JWT still leaves the example database credential. Do not print or reuse those values. Finding ATT-OPS-001.

Login rate limit is 10/minute per IP and per email, fail-closed to 503 if Redis is down. Self punch is 600/minute. That is a flood ceiling, not a control against a script inside the ceiling.

## Authorization

| Actor | Attendance power | Evidence |
|---|---|---|
| Employee | Own punch, own view, own regularization request | `organisation/service.py` 818–834, scope `SELF` |
| Employee punching for another person | Denied on `/me`. `/punches` requires `PUNCH_ON_BEHALF`, which the employee role does not have. | `router.py` 802–884 |
| Employee approving own request | Denied on the review route | `service.py` 4869–4871 |
| Employee reading another person’s day | List SQL filters `visible_employee_ids`. Direct id outside scope is 404. | `repository.py` 1059–1062; `service.py` 3013–3017 |
| Company admin | Company-wide attendance permissions | `organisation/service.py` 578–581 |
| HR admin | Company view, view-all, approve | `organisation/service.py` 655–684 |
| Reporting manager | Approve codes, no `ATTENDANCE.VIEW` | `organisation/service.py` 711–723. Fail-closed for lists. |

### ATT-SEC-004 — `AUTO` approval skips the self-approval check

- Severity: Low unless a company publishes that chain.
- Path: `service.py` 4668–4678. Default chain is `MANAGER` (`schemas.py` 786).
- Impact: the submitter’s own request is approved in the same call.
- Correction: keep the default, and reject `AUTO` for the subject’s own employee id if dual control is required.
- Blocks deployment: no if no published policy uses `AUTO`.

### ATT-SEC-005 — Policy resolution ignores data scope

- Severity: Low.
- Path: `GET /attendance-policy-resolution` (`router.py` 776–793) takes a client `employee_id` and does not apply the scope object. The seeded holder is company-wide.
- Impact: a custom `SELF` grant of `POLICY_MANAGE` could preview another employee’s policy inside the same tenant.
- Blocks deployment: no.

Geofence coordinates are a device report. They are not proof of presence. Do not describe them as such in a customer claim. GPS can be spoofed; mock locations are not a server-side attestation.

Face verification is off unless configured. `.env.example` states the open-source thresholds are uncalibrated and not approved for production attendance. Leave the provider disabled for this release (ATT-FACE-001, informational for a plain punch launch, critical if someone enables it).

## IDOR

Self and face punch ignore any body employee id. On-behalf punch and regularization check visibility after the permission. Idempotency keys are unique per company; reusing one for a different employee is rejected (`service.py` 2696–2701). No cross-tenant attendance IDOR was proven, and none was disproven by a live request. The code path for the working tree is fail-closed. The committed middleware is not.
