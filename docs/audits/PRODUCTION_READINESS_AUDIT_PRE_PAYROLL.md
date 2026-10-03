# Production Readiness Audit — Pre-Payroll Baseline

| Field | Value |
|---|---|
| Audit date | 2026-10-01 |
| Commit audited | `83e4d2c` (`main`, **4 commits ahead of `origin/main`, unpushed**) |
| Working tree | Clean except untracked `apps/mobile/` (build artefacts only, no source) |
| Scope | Everything up to, **excluding**, Payroll (Payroll phases 5.1–5.6 exist in the code and share the platform; they are not audited as a feature) |
| Method | Direct source inspection; live read-only queries against the dev Postgres catalog (`hrms_dev`); full backend test run against the isolated `hrms_test` database; frontend `vitest`, `tsc`, `npm audit`; `pip-audit`; GitHub Actions run history. **No application code, configuration, schema, test or CI file was changed.** This report is the only file written. |
| Not done | No load test, no penetration test, no Docker image build, no production-config stack boot, no real SMTP/TLS, no backup/restore drill. Those are listed under *Unknowns*. |

**Evidence convention.** Every finding cites a file/line, a catalog query, a test, or a command
output. Statements are tagged where useful: **VERIFIED** (reproduced or read directly this
session), **STATIC** (read from code, not executed), **UNMEASURED** (architectural expectation
that needs a test), **CANNOT VERIFY** (evidence not obtainable here).

---

## Executive Summary

The domain core of this HRMS is genuinely strong and is the best part of the system: Postgres
row-level security under a non-privileged runtime role on every tenant table, data-scoped RBAC
that fails closed, an append-only punch model with row-locked recalculation, a ledger-based leave
balance with an advisory lock at approval, timezone-correct business dates almost everywhere,
period locks enforced on attendance *and* leave writes, and PII envelope-encrypted at rest. The
previous two audit cycles (2026-09-10, 2026-09-17, 2026-09-25) closed most of their blockers, and
I verified the large majority of those fixes in code.

It is **not ready for production with real organisations today**. No finding meets the P0 bar
(provable cross-tenant leak or auth bypass). There are **thirteen P1 issues**. Several are cheap
to fix but would break the first real deployment (email links pointing at `localhost`, bulk import
never processed). Others are security controls that the documentation says exist but that do not
work: refresh-token reuse detection and account lockout are both silently rolled back. Leavers keep
system access because there is no way to revoke a user. Operationally, scheduled jobs that feed
leave and attendance can fail or be skipped with nobody alerted, and backups have never been
restored in this environment.

The most important new findings, which no previous audit recorded:

1. **Refresh-token reuse detection never takes effect** (PRA-01). The family revocation is
   written, then rolled back with the 401. The existing test asserts the *insecure* behaviour.
   The 2026-09-17 audit listed this as "already solid".
2. **No leaver access revocation** (PRA-03). Deactivating or terminating an employee leaves their
   user, sessions and membership active. No endpoint can suspend a user.
3. **Bulk employee import is never executed in production** (PRA-04). The task is routed to a
   queue the production worker does not consume.
4. **Every outbound email link points to `http://localhost:3000`** in the documented production
   configuration (PRA-05). That covers verification, password reset, invites and onboarding.
5. **The 09:30 IST attendance sweep holds row locks for a whole company in one transaction**, at
   peak punch-in time (PRA-08). Punch requests can stall behind it. This has not been load tested.

---

## Current Application State

| Item | State | Evidence |
|---|---|---|
| Backend | FastAPI modular monolith, ~64.7k LoC Python, 10 domain modules + core | `apps/api/src/hrms` (`wc -l`) |
| Routes | ~296 decorated routes (attendance 82, organisation 70, payroll 43, employee 37, leave 33, …) | `grep -c "@router" */router.py` |
| Frontend | Next.js **14.2.35** App Router, 266 TS/TSX source files, 57 test files | `apps/web/src`, `node_modules/next/package.json` |
| Database | PostgreSQL 16, **102 tables**, 104 Alembic revisions, linear chain | catalog query; `alembic/versions` |
| Workers | Celery worker + single Celery beat; Redis broker/result backend | `core/celery_app.py`, `docker-compose.prod.yml` |
| Object storage | MinIO-compatible `pgsty/silo` (MinIO upstream archived), digest-pinned in prod/CI | `docker-compose.prod.yml:89` |
| Edge | Nginx 1.27 + Let's Encrypt (certbot) on a single VPS | `infra/nginx/` |
| Mobile | `apps/mobile/` untracked on `main`; only `android/ ios/ build/` artefacts, no source | `ls apps/mobile` |
| Git | `main` is 4 commits ahead of `origin/main`. The Face++ provider swap, self-enrollment and test fixture commits have never run through CI | `git status -sb`; `gh run list` (last green: `453d6c7`) |
| Dev DB | One migration behind head (`20261006090000` vs head `20261007090000`) | `alembic_version` in `hrms_dev` vs `hrms_test` |

---

## Architecture Overview

```text
                 Internet
                    │ 80/443
              ┌─────▼─────┐   edge network
              │   Nginx   │──────────────┬───────────────┐
              └─────┬─────┘              │               │
       WEB_DOMAIN   │       API_DOMAIN   │   STORAGE_DOMAIN (full S3 API, presigned URLs)
              ┌─────▼─────┐        ┌─────▼─────┐   ┌─────▼─────┐
              │  web:3000 │        │  api:8000 │   │ minio:9000│
              │ Next.js   │        │ gunicorn  │   │ (silo)    │
              └───────────┘        │ 2×uvicorn │   └─────▲─────┘
                                   └──┬──┬──┬──┘         │ data network
                      ┌───────────────┘  │  └────────────┤
                ┌─────▼─────┐      ┌─────▼─────┐   ┌─────┴─────┐
                │ Postgres  │◄─────│  worker   │   │   beat    │
                │ hrms_app  │      │ celery ×2 │   │ (1 only)  │
                │ (RLS)     │      └─────▲─────┘   └─────┬─────┘
                └───────────┘            │   Redis (broker, rate limits)
                                         └──────────────────┘
External: SMTP or Mailtrap (email), Face++ (face match + liveness, optional)
```

**Middleware stack** (outer → inner, `app.py:62-150`): `ProxyHeadersMiddleware` (trusted
proxies) → `SecurityHeadersMiddleware` → `TenancyMiddleware` (request id, raw `X-Company-Id` →
ContextVar) → onboarding upload rate limiter → 4× `MaxUploadSizeMiddleware` (path-scoped) → CORS
→ routes.

**Tenancy chain** (VERIFIED by reading `core/db/session.py`, `core/auth/dependencies.py`,
`core/tenancy/dependencies.py` and the catalog):
`get_session` sets `app.company_id` (transaction-local) from the raw header. `get_current_user`
then checks `user_company` under RLS. That check only finds a row when the header equals the
token's company, so a mismatched header yields 401. `get_tenant_context` re-sets the GUC from the
verified token. Policies are `company_id = current_setting('app.company_id', true)::uuid`. An
unset GUC returns zero rows, so the policy fails closed.

**Background jobs** (`core/celery_app.py:29-64`, timezone `Asia/Kolkata`):

| Job | Schedule (IST) | Fan-out | Idempotency guard |
|---|---|---|---|
| `leave.run_monthly_accrual` | 01:00 on day 1 | per company | `uq_leave_ledger_cycle_entry` + `insert_if_absent` |
| `leave.run_comp_off_credit_sweep` | hourly :00 | per company | `uq_leave_ledger_comp_off_credit` |
| `leave.run_comp_off_expiry_sweep` | 01:30 daily | per company | advisory lock (per memory/commit `2a37fcd`) |
| `leave.run_year_end_sweep` | 02:00 daily | per company | `exists_for_cycle` + unique encashment index |
| `attendance.run_daily_calculation` | 09:30 daily, trailing 3 days | per company, **one transaction per company** | full-row replace under `FOR UPDATE` |
| `attendance.run_incomplete_reminders` | 10:00 daily | per company | none (re-sends daily by design) |
| `attendance.calculate_range` | on demand | one txn per employee | same as above |
| `employee_import.process_batch` | on demand, queue `reports_exports` | per batch | none, no retry by design |

---

## Module-by-Module Readiness

| Module | Status | Summary |
|---|---|---|
| Registration / tenant bootstrap | READY WITH CONDITIONS | Email verification exists and blocks *subsequent* logins. The new tenant is live immediately. Email links are broken in the documented prod config (PRA-05). |
| Login / session / JWT | NOT READY | Rotation works. Reuse detection and lockout do not (PRA-01/02). Session lifetime is unbounded (PRA-24). |
| Password reset / email verification | READY WITH CONDITIONS | Sound token handling. Revokes all sessions on reset. Depends on PRA-05. Not audited (PRA-16). |
| Authorization / RBAC | READY WITH CONDITIONS | Fails closed and is data-scoped. Permission rollout is fragile and there is no last-admin guard (PRA-19). |
| Tenant isolation / RLS | READY | `ENABLE`+`FORCE` + policy on every tenant table. Runtime role is `NOSUPERUSER NOBYPASSRLS`. Test depth is limited (PRA-13). |
| User lifecycle (invite / role / revoke) | NOT READY | Invite and role assignment work. There is no suspend/revoke at all (PRA-03). |
| Organisation / company config | READY WITH CONDITIONS | Well constrained. Some lists capped rather than paginated. |
| Employee management | READY WITH CONDITIONS | Strong effective-dated model with GiST exclusion constraints. PII encrypted. Deactivation does not cut access (PRA-03). |
| Onboarding (public wizard) | READY WITH CONDITIONS | Upload hardening verified. No malware scanning. Email links (PRA-05). |
| Bulk employee import | NOT READY | Never processed in prod topology (PRA-04). |
| Attendance — punch & calculation | READY WITH CONDITIONS | Server clock, append-only, row-locked recompute. Lock contention with the sweep is unmeasured (PRA-08). |
| Attendance — regularization / OT / periods | READY WITH CONDITIONS | Period locks checked at 16 call sites. Unbounded list endpoints (PRA-09). |
| Face attendance | INCOMPLETE | 4 commits never CI-verified. Third-party biometric processing needs legal review (PRA-20). |
| Shifts / rosters / calendars / holidays / weekly offs | READY WITH CONDITIONS | Versioned and exclusion-constrained. Some policy settings are inert (PRA-21). |
| Leave — types / policies / balances | READY WITH CONDITIONS | Ledger plus unique cycle indexes. Server-clock dates remain (PRA-14). |
| Leave — apply / approve / cancel | READY WITH CONDITIONS | Balance re-checked under lock at approval. Overlap only guarded at approval (PRA-15). |
| Comp-off | READY WITH CONDITIONS | Idempotent credit. Policy decisions D1–D8 open (`COMPOFF_POLICY_SAFETY_REVIEW.md`). |
| Documents / storage | READY WITH CONDITIONS | Private bucket, magic-byte sniffing, attachment disposition. Root credentials (PRA-17). Orphans (PRA-26). |
| Notifications / email | NOT READY | Provider guard is good. Base URL is not configured (PRA-05). Sends are best-effort with silent failure. |
| Background jobs | NOT READY | Queue routing bug (PRA-04). No catch-up, retry or alerting (PRA-07/27). |
| Audit logging | READY WITH CONDITIONS | Broad coverage. Mutable by the runtime role. No read API. Failed or security events are lost (PRA-16). |
| Observability | NOT READY | No error tracking, metrics or alerting (PRA-11). |
| Backups / DR | NOT READY | Scripts and runbook exist. No off-site copy, no encryption, no restore evidence (PRA-10). |
| CI/CD | READY WITH CONDITIONS | Real Postgres/Redis/MinIO in CI. No image build, no branch protection, no CD (PRA-12). |
| Frontend | READY WITH CONDITIONS | CSP with nonce. Refresh token in HttpOnly cookie. Critical Next.js advisory (PRA-06). Multi-tab logout race (PRA-18). |

---

## Authentication & Authorization

**Verified working**

- Argon2id hashing (`core/auth/passwords.py`), with an 8-character, letter+digit policy and a
  ~50-entry offline common-password list.
- HS256 is pinned on both encode and decode, the token `type` is asserted, and the library is
  `pyjwt` (DEP-01 closed: `python-jose` removed, `pyproject.toml`).
- Each request re-checks user status, session revocation and active membership against the DB
  (`core/auth/dependencies.py:29-40`).
- Refresh token is an HttpOnly, `SameSite=Lax` cookie scoped to `Path=/v1/auth`. `Secure` is set
  when the scheme is https (`core/auth/refresh_cookie.py`).
- Login is rate-limited per IP **and** per email (10/min). Refresh is limited per IP. Forgot,
  reset and verify each have their own bucket. All of them fail closed with 503 if Redis is down
  (`shared/rate_limit.py`, `identity/router.py:33-63`).
- Password reset revokes every session and refresh token for the user (`identity/service.py:366`).
- Invite acceptance for an existing account verifies the password (SEC-08 closed,
  `account_invite/service.py:262-270`).
- Anti-enumeration error shapes are uniform. One timing side channel remains (PRA-22).
- Production boot guards refuse default or weak JWT secrets, a missing master key, empty CORS,
  missing storage config, or the logging-only email provider (`core/config/settings.py:318-386`).

**Broken or missing**

- **PRA-01 / PRA-02 (P1):** `get_session` rolls back the whole transaction on *any* exception
  (`core/db/session.py:80-82`). `IdentityService.refresh` revokes the token family and then
  raises (`identity/service.py:124-129`). `IdentityService.login` increments the failure counter
  and then raises (`identity/service.py:70-72`). Both writes are discarded.
  `tests/integration/auth/test_auth_security.py:117-122` replays the old refresh token, gets 401,
  and then asserts that the *rotated* token **still works** (`second.status_code == 200`). That is
  the opposite of family revocation. `tests/integration/auth/test_credential_rate_limit.py:88-97`
  documents that lockout "never actually engages".
- **PRA-03 (P1):** there is no suspend/disable/remove-membership operation anywhere.
  `deactivate_employee` (`employee/service.py:690-717`) only sets `employee.is_active=False`, even
  though its docstring promises "immediate access cutoff". `terminate_employment` does not touch
  `user`, `user_company` or `session`. The only workaround is `PATCH /users/{id}/roles` with
  `role_codes: []` (`account_invite/schemas.py:67`). That strips permissions but leaves the user
  authenticated.
- **PRA-24 (P2):** `Session.expires_at` is never checked (`get_current_user` checks only
  `revoked_at`). Each refresh issues a new 30-day refresh token for the same session, so a session
  never has to end. `logout` revokes the session but not its refresh tokens. A later refresh still
  returns 200 with an access token that `get_current_user` then rejects.
- No MFA. No authenticated "change password" endpoint (only forgot/reset).

**Authorization.** `require_permission` resolves the data scope in one query and fails closed on
empty scope (`core/rbac/dependencies.py`). Writes check that the *target* employee is visible
(`_ensure_employee_visible` in attendance and leave). Cross-tenant IDs return 404. Permissions are
granted per company role row, and new permissions reach existing tenants only through data
migrations keyed on role codes. Tenants using the legacy `COMPANY_ADMIN` role miss the newer
`EMPLOYEE.VIEW_*` permissions (project memory; grants in `alembic/versions/2026092809*`,
`2026100109*`). Replacing roles has no guard against removing the last admin (PRA-19).

---

## Tenant Isolation / RLS

VERIFIED against the live catalog (`pg_class.relrowsecurity/relforcerowsecurity`, `pg_policy`):

- **87 tenant tables** have `ENABLE` + `FORCE` RLS and exactly one `tenant_isolation` policy.
- Tables without RLS: `user`, `session`, `refresh_token`, `permission`, `role_permission`,
  `user_role`, `plan`, `plan_feature`, `encryption_keys`, `email_verification_token`,
  `password_reset_token`, `account_invite`, `onboarding_token`, `alembic_version`. These are
  cross-tenant by nature or documented hash-keyed pre-tenant lookups.
- `company`: `FORCE` without `ENABLE`, so RLS does nothing (SEC-007, still open; documented as the
  tenant root). Background jobs depend on this to enumerate companies
  (`leave/tasks.py:_list_active_company_ids`).
- `hrms_app`: `rolsuper=f`, `rolbypassrls=f`. CI asserts this before the security suite
  (`ci.yml` step "Verify the hrms_app runtime role").
- The one `SECURITY DEFINER` login function has a pinned `search_path` and `EXECUTE` granted only
  to `hrms_app` (`20260828090000_login_lookup_function.py`).
- Background tasks always open `session_scope(company_id=...)`. Mid-transaction commits re-apply
  the GUC where needed (`employee_import/service.py:549-557`).
- Public routers (onboarding, invites) resolve the hash-keyed token first and then set the GUC
  from the token's company (`onboarding/service.py:662`, `account_invite/service.py:220,259`). A
  forged `X-Company-Id` on a public route only sets a GUC that is overwritten before any
  tenant-table query I could find. The footgun noted in 2026-09-17 remains *latent* for any
  future public route that queries before resolving its token.

**No cross-tenant leak path was found.** Limits of that statement: the RLS runtime-role suite is 4
tests focused on the employee lifecycle (`tests/security/test_rls_runtime_role.py`). All other
integration tests run as the `hrms` superuser (`ci.yml` comment at the integration step), so they
prove application filters, not RLS (PRA-13).

---

## Employee Management

- Effective-dated assignment, bank, compensation, statutory, employment and salary tables each
  have a **GiST exclusion constraint** against overlapping ranges (catalog: 14 `EXCLUDE`
  constraints). Employment has status/LWD consistency `CHECK`s. FK deletes are mostly `RESTRICT`
  or `NO ACTION`. The 21 `CASCADE` FKs are all child-detail tables (policy bands, breaks, period
  summaries, OT actions, pay-run lines). No HR fact cascades from an employee delete, and
  employees are never hard-deleted.
- PII: PAN, Aadhaar (employee and dependent) and bank account are encrypted through
  `PiiCryptoService` on every write path I traced (`employee/service.py:611`, onboarding activation
  `onboarding/service.py:1260-1320`). Bulk import does not accept these fields. Reads decrypt in
  narrow paths (`EmployeeBankService.get_bank` → `_decrypt_bank`). Audit redaction exists
  (`core/audit/redact.py`). **CANNOT VERIFY at rest in dev data:** the dev DB currently holds 1
  employee with no PII and 0 bank rows, because the test suite truncates `hrms_dev` (project
  memory).
- Bulk import creates rows through the audited `EmployeeService`, so AUD-01 is effectively closed
  for imported employees. It is not executed in production topology (PRA-04).
- Leaver access: PRA-03.

---

## Attendance

**Time handling.** VERIFIED. Punch instants come from the server clock for self-service
(`PunchService.record_punch`: `requested_punch_time=None ⇒ now`). On-behalf punches cannot be in
the future and cannot predate employment. Business dates use `business_today(company.timezone)` in
every attendance call site. CI runs the API in UTC and the web in `America/New_York`, so
host-clock regressions fail. India has no DST, and TZ-1 (no DST test) still stands for non-IST
tenants, who are blocked anyway by `allowed_company_timezones=("Asia/Kolkata",)`. One documented
approximation remains (WD-30): punch-time period-open checks use the UTC date.

**Punching and concurrency.** Punches are append-only. Duplicates are collapsed at calculation
time (`calculation.collapse_duplicate_punches`). The optional idempotency key is backed by a
partial unique index (`punch_company_idempotency_key_idx`). **The web client never sends one**
(`grep` in `apps/web/src`), so a double click creates two rows, which calculation then collapses.

`calculate()` takes `SELECT … FOR UPDATE` on the day row before reading inputs. It resolves the
first-insert race with a savepoint and re-read (`service.py:2829-2945`), and is protected by
`attendance_day_unique`. A failed immediate recalculation never loses the punch, because it runs
in a savepoint (`service.py:2601-2656`). Under READ COMMITTED, a second concurrent punch's
calculation waits on the row lock and then sees the first punch. This design is correct.

**Period locking.** `_ensure_date_open`/`_ensure_punch_date_open` are referenced at 16 sites in
`attendance/service.py`. Leave submit, approve and cancel call `closed_period_overlapping`
(`leave/service.py:2060,2379,2771`). Periods are per legal entity, with a GiST no-overlap
constraint.

**Risks**

- **PRA-08 (P1, UNMEASURED):** `_calculate_company_async` (`attendance/tasks.py`) recalculates
  every active employee × 3 days in **one transaction per company**. Each employee-date takes and
  *keeps* a `FOR UPDATE` lock until the whole company commits. It runs at 09:30 IST. A punch at
  that time calls `calculate()` for today, takes the same row lock, and waits. No `lock_timeout`
  or `statement_timeout` is configured (`grep` in `apps/api/src`: none). Gunicorn's worker timeout
  is 60s and Nginx's is 120s. For a large tenant the punch request can time out, and if the worker
  is killed the punch transaction rolls back. The 2026-09-10 audit estimated ~50–70 queries per
  employee-day (DAT-003, not re-measured). The duration at 500 or 5,000 employees is unknown.
- **PRA-09 (P2):** `GET /attendance/punches`, `/attendance/days`, `/regularizations`, `/overtime`
  and `/leave-projections` are not paginated and do not require a date range
  (`attendance/router.py:860-906`). API-01 is only partially closed.
- **PRA-21 (P3):** settings stored but never applied: `punch_rounding` (`apply_rounding` has zero
  call sites, `calculation.py:696`) and `excess_break_behaviour` (passed into the input at
  `service.py:3489`, never read in `calculation.py`). `round_minutes` NEAREST uses banker's
  rounding (`calculation.py:693`). They are hidden in the UI (PD-1) but still accepted by the API.
- There is no geofence or IP allowlist on self-service web punches. That is a product decision,
  noted for completeness.

---

## Leave

**Verified**

- **Ledger.** The ledger is append-only, with a non-zero `CHECK`. Accrual and carry-forward have
  natural-key uniqueness (`uq_leave_ledger_cycle_entry`), which closes DAT-001. Comp-off credit is
  unique per overtime record, and year-end encashment is unique.
- **Approval.** `_cover_from_balance` takes `pg_advisory_xact_lock(employee, leave_type)` and
  re-reads the balance before debiting (`leave/service.py:2558-2598`, `repository.py:346-354`),
  closing PAY-010. The negative-balance floor is honoured, closing PAY-011. Excess can be approved
  as LOP explicitly.
- **Atomicity.** Approval writes the projection to attendance in the same transaction. A closed
  period aborts the whole approval (`_apply_approval` docstring, LD-12).
- **Cancellation.** Cancellation reverses with an offsetting `ADJUSTMENT` and cancels the
  projections.

**Issues**

- **PRA-14 (P2):** `date.today()` is still used for the backdating window
  (`leave/service.py:2134`) and for the reversal entry's `effective_date` (`:2879`).
  `max_requests_per_month` counts by UTC month of `submitted_at` (`:2145-2150`). DAT-004 and
  DAT-005 from 2026-09-10 are **NOT FIXED**. Containers run `TZ=UTC`, so between 00:00 and
  05:29 IST these dates are a day early. A cancellation made just after midnight IST on the first
  of a month or leave year books the restoring credit in the *previous* period.
- **PRA-15 (P2):** submit only checks *other* leave types for overlap, and only to apply explicit
  "not allowed" combination rules (`repository.py:600-626`; the default is allowed). Two
  applications of the same type for the same day both submit. The second approval fails, but only
  because `LeaveProjectionService.sync` rejects a combined fraction above 1.00
  (`attendance/service.py:~6200`). That check is read-then-insert. The balance lock is per leave
  *type*, and the projection natural key includes `leave_application_id`
  (`leave_day_projection_natural_key`). So two *concurrent* approvals of overlapping applications
  of different types can both pass. `_apply_leave_overlay` would then produce
  `paid_day_fraction = 2.00` (`calculation.py:1141-1180`). No DB `CHECK` bounds
  `paid_day_fraction`/`leave_fraction` (catalog: `attendance_day` has only status and resolution
  checks). DAT-010 (no FK on `leave_day_projection.leave_application_id`) is still open.
- **PRA-07 (P1):** monthly accrual fires once at 01:00 IST on day 1. There is no catch-up for a
  missed firing, no HTTP or admin trigger (no accrual route in `leave/router.py`), the whole
  company runs in one transaction with no per-employee savepoint, there is no retry, and nothing
  alerts. A beat outage at that minute means a silently missing month of accrual.

---

## Background Jobs

| Concern | Finding | Evidence |
|---|---|---|
| Queue routing | **PRA-04 (P1)**: `employee_import.process_batch` uses `queue="reports_exports"`. The prod worker runs `celery -A entrypoints.worker worker` with no `-Q`, and no `task_queues`/`task_routes` is defined, so it consumes only `default`. The batch row is committed before `.delay()` and stays PENDING forever. | `employee_import/tasks.py:32`, `docker-compose.prod.yml` `worker.command`, `grep task_routes` → none |
| Dev parity | `scripts/dev.sh` starts no Celery worker or beat, so scheduled jobs never run in local development and the routing bug cannot be seen there. | `grep celery scripts/` → none |
| Retries / acks | No task sets `autoretry_for`, `acks_late` or time limits. A worker crash mid-task loses the task. | `core/celery_app.py` |
| Beat | Single instance, schedule file in `/tmp`, health check disabled, no leader election (OPS-006 accepted). Crontab entries missed during downtime are not replayed. | `docker-compose.prod.yml` `beat` |
| Failure visibility | Per-employee failures are `_logger.warning` only. Leave tasks log nothing. No dead-letter queue or alert. | `attendance/tasks.py`, `leave/tasks.py` |
| Idempotency | Good for accrual, comp-off, year-end and attendance recalculation (DB-enforced). Reminders resend daily by design. Import is intentionally not retry-safe. | indexes above |
| Timezone | All business-date tasks use `business_today(company.timezone)`. The schedule is interpreted in `Asia/Kolkata`. | `leave/tasks.py:36-45` |

---

## File Storage

| Control | State | Evidence |
|---|---|---|
| Bucket privacy | `mc anonymous set none` at init (prod and dev) | `docker-compose.prod.yml` `minio-init` |
| Object keys | Server-chosen `onboarding/{company}/{case}/{doc}/document.{sniffed-ext}`. The client filename is never part of the key. | `onboarding/document_validation.py:85-95` |
| Type validation | Magic-byte sniffing (PDF, JPEG, PNG). The client `Content-Type` is ignored. | `document_validation.py:27-50` |
| Download | Presigned GET, 300s, `ResponseContentDisposition: attachment` | `core/storage.py:70-100`, `onboarding/service.py:836-850` |
| Size | Nginx 15m, ASGI streaming cap per path, bounded read | `app.py:73-100`, `core/uploads.py` |
| Rate limit | Public upload: 30/IP and 10/token per minute, fails closed | `shared/rate_limit.py:163-260` |
| Credentials | **PRA-17 (P2)**: the API authenticates with the MinIO **root** user (the runbook says `AWS_ACCESS_KEY_ID` must equal `MINIO_ROOT_USER`), and the full S3 API is published at `STORAGE_DOMAIN`. | `.env.prod.example:42`, `infra/nginx/conf.d` storage block |
| Tenant isolation | By key prefix plus DB-mediated URL issuance. There is no per-tenant bucket or policy, so isolation relies on the app. | design |
| Malware scanning | None (documented, accepted for pilot) | `RELEASE_HARDENING_PHASE_6` §25 |
| Orphans | **PRA-26 (P3)**: `put_object` happens before the DB insert (`onboarding/service.py:800-818`), and `delete_object` happens *before* the DB delete (`:864-865`). No reconciliation job exists. | |
| Backup | `mc mirror` to a local tar.gz, 14-day retention, not encrypted, not off-site | `infra/backup/minio_backup.sh` |

---

## Database

**Strengths (VERIFIED):** integer minor units for money, `timestamptz` throughout, 14 GiST
exclusion constraints for effective dating, unique natural keys for attendance day, period
summary, overtime per day, single active regularization per day, accrual cycles, and employee code
per company. Optimistic concurrency via `version` and `If-Match` on mutable aggregates. 280 FKs,
only 21 cascading, all to child detail rows.

**Weaknesses**

- `audit_log` grants `INSERT, SELECT, UPDATE, DELETE` to `hrms_app`. The "architecturally
  immutable" audit trail is not enforced (PRA-16).
- There are no DB bounds on day fractions (PRA-15).
- No `statement_timeout`, `lock_timeout` or pool sizing is configured. SQLAlchemy defaults to
  5+10 connections per process, × 2 gunicorn workers, × worker/beat processes (PRA-08).
- No partitioning of `punch`, `attendance_day` or `audit_log` (DAT-012, deferred). Each
  `calculate()` writes an audit row with full `after_json`. The nightly sweep alone writes ≥3 rows
  per active employee per day (PRA-28).
- The base migration's `downgrade()` raises. Downgrades are not exercised in CI.
- The init script interpolates `HRMS_APP_PASSWORD` into SQL unescaped
  (`infra/docker/postgres/init/002_app_role.sh`). A password containing `'` breaks provisioning.

---

## API

- The error envelope is uniform with a request id. Validation errors return 422 with field paths.
- Cross-tenant and out-of-scope requests return 404.
- Pagination (`shared/pagination.py`) is adopted on 7 endpoints in employee, leave and
  organisation. Organisation config lists use a `LIMIT 1000` safety cap.
  **Attendance has none** (PRA-09).
- Idempotency: only punches support a key. Approvals use optimistic versioning, which safely
  rejects a stale double-submit.
- Most production-sensitive endpoints: `POST /auth/token/refresh` (PRA-01),
  `POST /auth/login` (PRA-02), `DELETE /employees/{id}` (PRA-03, it does not cut access),
  `POST /employee-imports` (PRA-04), `POST /attendance/days/calculate-range` (long Celery job),
  `PATCH /users/{id}/roles` (no last-admin guard), and the public onboarding upload (hardened).
- OpenAPI, Swagger and ReDoc are disabled outside development (`app.py:51-59`).
  **PRA-33 (P2):** `environment` *defaults* to `development` (`settings.py:56`). A production env
  file that omits `ENVIRONMENT` disables every boot guard, re-enables `/docs`, and accepts the
  logging email provider. The template sets it, but nothing enforces it.

---

## Frontend

| Area | State | Evidence |
|---|---|---|
| Auth storage | Access token (15 min) plus metadata in `localStorage`. Refresh token in HttpOnly cookie. | `lib/auth/token-storage.ts` |
| CSP / headers | Nonce-based `script-src 'strict-dynamic'`. `unsafe-eval` only outside production. `frame-ancestors 'none'`. | `src/middleware.ts` |
| Protected routes | Client-side redirect in `app/app/layout.tsx`. The API is the real enforcement point. | |
| 401 handling | Single-flight refresh, then retry once. On failure it clears the session and emits an event. | `lib/api/client.ts:151-200` |
| Multi-tab | **PRA-18 (P2)**: two tabs refreshing with the same cookie means one tab gets 401, calls `clearSession()`, and wipes the *shared* `localStorage` for every tab. This becomes worse once PRA-01 is fixed, because a duplicate refresh would revoke the family. A grace window or cross-tab lock is needed. | `client.ts` |
| Errors | `ApiError` carries code, message and request id. No silent catch blocks found by grep. There is no data-cache layer, so stale views need a manual reload. | |
| Tests | **57 files / 404 tests pass**. `tsc --noEmit` is clean (VERIFIED this session). | |
| Lint | ESLint is non-blocking in CI. `next build` ignores lint. | `ci.yml`, `next.config.mjs` |
| Dependencies | **PRA-06 (P1)**: `npm audit --omit=dev` reports 1 critical (`next` ≤16.3.0-preview), 2 high (`postcss`, `nanoid`). The fix is a Next major upgrade. The CI audit step is `continue-on-error`. | VERIFIED this session |
| Face capture | Web sends `Permissions-Policy: camera=()`. Face capture exists only in the mobile app, which is untracked on `main`. | `middleware.ts` |
| Accessibility / mobile | Not audited in depth. No automated a11y checks exist. | UNKNOWN |

---

## Security

Summary of evidence-based posture (detail in the sections above):

| Control | State |
|---|---|
| SQL injection | SQLAlchemy Core/ORM with bound parameters throughout. The only f-string SQL found is in test fixtures. |
| XSS | React escaping, strict nonce CSP, uploads forced to download, API CSP `default-src 'none'`. |
| CSRF | API uses bearer tokens. The refresh cookie is `SameSite=Lax` and `POST`-only. |
| SSRF | Outbound calls go only to configured hosts (SMTP, Mailtrap, Face++). No user-supplied URLs are fetched. |
| Path traversal | Storage keys are server-built. The display filename is sanitised. |
| Uploads | Size-capped, type-sniffed, rate-limited. No AV scanning. |
| Secrets | Boot guard for secrets. Gitleaks runs blocking in CI (`--no-git`, tree only). `apps/api/.env` (untracked) holds **live Face++ test keys** marked "rotate before production". |
| Transport | TLS 1.2/1.3 at Nginx, HSTS when proxied as https, HTTP→HTTPS redirect. |
| Exposure | Postgres, Redis and MinIO publish no host ports in prod. The MinIO console is not proxied. The S3 API is public (PRA-17). |
| Containers | Non-root API and web images, multi-stage builds. No resource limits. `certbot/certbot:latest` and `zricethezav/gitleaks:latest` are unpinned. |
| Auth controls | See PRA-01/02/03/22/24. |

---

## Error Handling

- The unhandled-exception handler discards the exception (`core/errors/handlers.py:74-81`,
  `_ = exc`, "Sentry hook lands here in a later sprint"). Starlette's `ServerErrorMiddleware`
  re-raises after the response, so a plain-text traceback reaches gunicorn stderr. It is **not**
  correlated with the request id and not structured. OBS-01 is **NOT FIXED**.
- **Transactions.** The request transaction rolls back on any exception, which is the correct
  default and the cause of PRA-01/02/16. Partial work is guarded with savepoints where intended
  (immediate calculation, sweep per employee-date, the insert race).
- **Redis down.** Login, refresh, registration and reset return 503 (fail closed, by design) and
  readiness reports an error.
- **MinIO down.** Upload or URL issuance fails as a 500. DB state is consistent apart from orphan
  ordering (PRA-26).
- **Email failures.** Swallowed everywhere (`except Exception: pass`). For invites the response
  carries `email_sent=false`. For verification and reset the user gets no signal and nothing is
  logged (`identity/service.py:322-325,396-399`).
- **Face++ failures.** Timeout is configured (15s), failed-attempt throttling exists, and the
  feature is disabled by default.

---

## Logging & Observability

| Capability | State |
|---|---|
| Structured logs | structlog JSON is configured, but `get_logger` is used in only 7 files (attendance, face, email, PII backfill). There are no request or business-event logs in identity, leave, employee or organisation. |
| Request id | Generated or propagated in `TenancyMiddleware`, returned in a header and error bodies, stored on audit rows. Not bound into log context, so it is absent from tracebacks. |
| Access logs | gunicorn `--access-logfile -` (plain format). Nginx JSON access log. |
| Error tracking | None. |
| Metrics / tracing | None (no Prometheus or OTel dependency). |
| Health | `/health/live` (process), `/health/ready` (DB, Redis, storage config; returns 503 when not ready), legacy `/health`. Nginx exposes `/health/ready` publicly. |
| Worker health | Worker: `celery inspect ping`. Beat: none. No queue-depth or task-failure metric. |
| Alerting | None. Disk alerting is only a recommendation in the runbook. |

**What an operator could not diagnose in production today:** a missed monthly accrual, a stuck
import batch, an email that never delivered, which request produced a given 500, punch latency at
09:30, a beat process that is alive but not scheduling, or any security event (failed logins and
token reuse are not recorded at all, see PRA-16).

---

## Backup & Recovery

| Item | State |
|---|---|
| DB backup | `pg_backup.sh` runs `pg_dump -Fc` in the container, writes atomically via `.partial`, 14-day retention. **Exists.** |
| Object backup | `minio_backup.sh` runs `mc mirror` to tar.gz. **Exists.** |
| Scheduling | Example crontab in `docs/deployment/PRODUCTION_DEPLOYMENT.md:264-268`. Nothing in the repo installs it. The example puts `MINIO_ROOT_PASSWORD` on the cron line. |
| Off-site copy | **Not implemented.** Only stated as a requirement in `DISASTER_RECOVERY.md`. |
| Encryption of backups | **None.** Dumps contain names, emails, salary and attendance in plaintext. Only PAN, Aadhaar and bank account are app-encrypted. |
| Key custody | Losing `PII_MASTER_KEY` makes PII unrecoverable. Custody is a policy step with no evidence (`DISASTER_RECOVERY.md` §1, Phase 6 §25). |
| Restore tooling | `pg_restore.sh` and `minio_restore.sh` restore into a *new* DB or bucket, with guards against overwriting live data. |
| Restore verified | **CANNOT VERIFY.** No restore was run in this audit, and no committed artefact records a successful restore with row-count verification on production-like data. |
| RPO / RTO | Not set (explicitly deferred as a business decision). Effective RPO with the example cron is ≤24h for DB and objects, assuming the VPS disk survives. |

**Conclusion:** *backups exist*. *Backups have been restored and verified* is **not** established.
If the VPS disk is lost, all backups are lost with it (PRA-10).

---

## CI/CD

What CI verifies on push/PR to `main`/`develop` (`.github/workflows/ci.yml`):

| Gate | Blocking? |
|---|---|
| ruff lint + format, mypy (core package), import-linter | Yes |
| Backend unit tests; integration + security tests with real Postgres 16, Redis 7, digest-pinned MinIO | Yes |
| `hrms_app` NOSUPERUSER/NOBYPASSRLS assertion | Yes |
| Web `tsc`, vitest, `next build` | Yes |
| ESLint | **No** |
| Gitleaks (tree only) | Yes |
| pip-audit, npm audit | **No** (and npm currently reports a critical) |
| Docker image build / compose validation / boot smoke test | **Absent** (CI-02 from Phase 6, still open) |
| Coverage measurement / threshold | **Absent** (TST-003 open) |
| Deployment / CD / rollback automation | **Absent.** Deployment is the manual runbook. |
| Branch protection | **Unavailable.** `gh api …/branches/main/protection` returns 403 "Upgrade to GitHub Pro". Nothing stops an unreviewed or red push to `main`. |

Recent history: the last green run is `453d6c7` (2026-10-01). The 4 later commits (Face++
provider, self-enrollment, fixture) are unpushed, so they are unverified by CI.

---

## Testing

**Backend run this session** (isolated `hrms_test`, `FACE_VERIFICATION_PROVIDER=disabled`, real
Redis and MinIO): see *Appendix A — test results*.

**Frontend:** 57 files / 404 tests pass. `tsc` is clean.

**Coverage quality by risk area**

| Risk | Coverage | Gap |
|---|---|---|
| Tenant isolation (DB-level) | 4 runtime-role tests (employee lifecycle, login/refresh, SELF/REPORTEES scope) | Attendance, leave, payroll and onboarding tables are not exercised as `hrms_app`. ~1,600 integration tests run as superuser. |
| Auth security | Rotation, rate limits, enumeration, verification, reset | **The tests codify the broken reuse detection and lockout** (PRA-01/02): misleading green. |
| Concurrency | `test_attendance_concurrency.py`, `test_leave_comp_off_safety.py`, accrual idempotency | No concurrent leave approval of overlapping applications, no punch-during-sweep test, no refresh race. |
| Scheduled jobs | Called directly as functions | Beat schedule, routing, queue consumption and missed-fire behaviour are untested (PRA-04 slipped through). |
| Timezone | Strong (CI TZ pinning, matrix in `ATTENDANCE_TIMEZONE_TEST_MATRIX.md`) | Leave `date.today()` sites are uncovered (PRA-14). |
| Frontend | Unit/component tests | No E2E, no a11y, no browser matrix. |
| Infra | `test_db01_credential_provisioning.py` | No image or compose boot test in CI. |
| Test isolation | `hrms_test` exists | `tests/conftest.py` defaults to `hrms_dev` and **truncates the dev database** when run without overrides (project memory, observed 2026-09-26). |

---

## Performance & Scalability

No load test exists. Nothing below is measured.

| Employees | Architectural expectation | Main concern |
|---|---|---|
| 25 | Comfortable on one VPS | None material |
| 100 | Expected fine | 09:30 sweep lock window is short |
| 500 | Plausible, **needs load test** | Sweep: 1,500 employee-date calculations in one transaction holding row locks at peak punch time (PRA-08). Unpaginated attendance lists for HR (PRA-09). |
| 1,000 | **Unknown, likely problematic** without changes | Sweep duration and locks, per-calculation audit-row volume, `/attendance/days` range queries, Celery concurrency 2 |
| 5,000 | **Not supported as designed** | Single-transaction company sweep, no partitioning, single Postgres, single worker host, synchronous cross-module recompute (ARC-004) |

Other notes:

- Login does argon2 verification on the request thread. With 2 gunicorn workers, a burst of logins
  at shift start will queue.
- Reports and exports run synchronously in the request (payroll aside).

---

## Privacy / Data Protection

PII held: name, contact details, DOB, address, emergency contacts, dependants and nominees
(including Aadhaar), PAN, Aadhaar, UAN, bank details, salary, attendance with timestamps, leave
reasons and attachments, onboarding documents (ID scans), face images and Face++ face-set tokens,
IP and user agent in sessions and audit rows.

| Area | State |
|---|---|
| Encryption at rest | App-level envelope encryption for PAN, Aadhaar and bank account only. Other PII is plaintext in DB and backups. No disk-encryption evidence for the VPS. |
| Access control | RBAC with `EMPLOYEE.VIEW_SENSITIVE`/`VIEW_*` permission split, data scopes |
| Logging exposure | Audit redaction for registered sensitive fields. Application logs carry few PII fields (sparse logging). |
| Biometrics | Face images go to Face++ (Megvii) at `api-us.faceplusplus.com`, which is a third-party, cross-border processor. Consent is recorded with `consent_recorded_at`. A review photo is stored in MinIO. Needs **legal review** under DPDP (PRA-20). |
| Retention / deletion | No retention schedule, no erasure workflow, no data-subject export. The audit log is designed as immutable, which conflicts with erasure requests and needs legal review (PRA-31). |
| Privacy notice / consent | No product privacy notice found. Phase 6 marks it `LEGAL-REVIEW`. |

This is not legal certification. Items above require counsel's review before real employee data
is processed.

---

## Cross-Module Risks

| Boundary | Risk |
|---|---|
| Auth → transaction model | Security-relevant writes (failure counters, family revocation, audit of failures) share the request transaction and roll back with the error (PRA-01/02/16). |
| Employee → Identity | Employee lifecycle (deactivate, terminate) and identity (user, membership, session) are disconnected (PRA-03). |
| Attendance ↔ Leave | Overlap is enforced only in Attendance's projection sync, with no shared lock (PRA-15). Leave uses server-clock dates while Attendance uses company time (PRA-14). The `leave ↔ attendance` import cycle is still hidden by function-scoped imports (ARC-002). |
| Scheduler → Attendance writes | The nightly sweep's long transaction contends with live punches (PRA-08). |
| API → Celery | Queue name mismatch (PRA-04). Import commits before `.delay()`, so a broker outage strands the batch. |
| API → Email → Frontend | Links depend on `WEB_APP_BASE_URL`, which is absent from the prod template (PRA-05). |
| Frontend → Auth | Multi-tab refresh race (PRA-18) will collide with a fixed PRA-01. |
| API → MinIO | Root credentials, public S3 API (PRA-17). Non-atomic put/delete versus DB (PRA-26). |
| CI → Docker → Prod | Images are not built in CI. Prod-only config paths (env decode, beat permissions, DB-01) were each found only by manual runs (Phase 3B, Phase 6 history). |
| Backup → Restore | Restore not verified. Key custody not evidenced (PRA-10). |
| RBAC → Migrations | New permissions reach tenants only through role-code-targeted data migrations (PRA-19). |

---

## Pre-Payroll Architecture Readiness

Payroll was not audited. These are the prerequisites the current data must meet for any payroll
consumer.

| Prerequisite | State |
|---|---|
| Attendance day facts trustworthy | **Mostly.** Server-assigned instants, deterministic recompute, locks, `paid_day_fraction`/`lop_fraction`, summary `paid_days`/`payable_days`/`not_employed_days` (catalog). There is no DB bound on fractions (PRA-15). Inert policy settings exist (PRA-21). |
| Period locking sufficient | **Yes for writes** (attendance + leave), per legal entity, with reopen gated by a separate permission. Reopen after a payroll consumed the period needs a downstream contract. Arrears (5.5) exist but are out of scope. |
| Leave balances consistent | **Mostly.** Ledger, unique cycles, approval lock. Gaps: missed accrual has no catch-up (PRA-07), `date.today()` effective dates (PRA-14), concurrent overlap race (PRA-15). |
| Employee/organisation relationships | Effective-dated with exclusion constraints. Legal-entity ownership per employee-date exists (`_owning_legal_entity`). |
| Dates / timezones | Reliable in attendance. Two leave sites remain (PRA-14). India-only timezone is enforced by setting. |
| Audit history | Broad, but mutable by the runtime role and not readable through the product (PRA-16). |
| Corrections traceable | Regularizations, OT actions, ledger adjustments and period actions each have action tables. |
| Consumable by payroll | Yes. `PayrollPeriodInputs` and closed-period summaries exist (`attendance/service.py:5213`). |

**Must be addressed before any payroll run is trusted:** PRA-07, PRA-14, PRA-15 (DB bound plus
submit-time overlap), PRA-16 (audit immutability), PRA-03 (exited employees retaining access to
payslips).

---

## Previous Audit Verification

Statuses: VERIFIED FIXED · PARTIALLY FIXED · NOT FIXED · REGRESSED · CANNOT VERIFY. "Never
worked" means a prior audit claimed the control worked and it did not.

### PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17

| ID | Status | Evidence |
|---|---|---|
| OPS-01 CORS | VERIFIED FIXED | `settings.py:cors_allowed_origins` + boot guard `:356-360` |
| SEC-01 JWT defaults | VERIFIED FIXED | `settings.py:318-341` (default, empty and weak secrets refused) |
| SEC-02 login/refresh throttle | VERIFIED FIXED | `identity/router.py:46-63` |
| DATA-01 PII plaintext | VERIFIED FIXED in code / CANNOT VERIFY at rest | `PiiCryptoService` on all write paths. Dev DB has no PII rows to inspect. |
| API-01 pagination | PARTIALLY FIXED | 7 endpoints paginated. Attendance lists are not (PRA-09). |
| SEC-03 upload buffering | VERIFIED FIXED | `core/uploads.py`, `app.py:73-100` |
| SEC-04 MIME / filename / disposition | VERIFIED FIXED (no AV) | `document_validation.py`, `storage.py` |
| SEC-05 security headers | VERIFIED FIXED | `core/security_headers.py`, `web/src/middleware.ts` |
| SEC-06 refresh token in localStorage | VERIFIED FIXED | HttpOnly cookie. The access token remains in `localStorage` by design. |
| SEC-07 reset leaves sessions | VERIFIED FIXED | `identity/service.py:366` |
| SEC-08 invite without password | VERIFIED FIXED | `account_invite/service.py:262-270` |
| OPS-02 proxy IPs | VERIFIED FIXED | `ProxyHeadersMiddleware`, `trusted_proxy_hosts` |
| SEC-09 unverified tenants | PARTIALLY FIXED | Verification blocks later logins. The tenant is live and the first session is issued at registration. |
| DEP-01 python-jose | VERIFIED FIXED | `pyproject.toml` uses `pyjwt` |
| OBS-01 swallowed 500s | NOT FIXED | `handlers.py:79-80` |
| OBS-02 access log / metrics | PARTIALLY FIXED | gunicorn and Nginx access logs. No metrics or tracing. |
| OPS-03 health split | VERIFIED FIXED | `/health/live`, `/health/ready` |
| OPS-04 root image | VERIFIED FIXED | `apps/api/Dockerfile` (`USER hrms`, HEALTHCHECK, gunicorn) |
| OPS-05 web image / build | PARTIALLY FIXED | Web Dockerfile exists and CI runs `next build`. CI never builds images. |
| OPS-06 docs exposure | VERIFIED FIXED (conditional on `ENVIRONMENT`, PRA-33) | `app.py:51-59` |
| QA-01 ESLint | PARTIALLY FIXED | Configured, but non-blocking |
| SEC-10 password policy | PARTIALLY FIXED | ~50-entry blocklist. No MFA. |
| SEC-11 limiter failure policy | VERIFIED FIXED | 503 fail-closed, `shared/rate_limit.py:36-50` |
| AUD-01 import audit / credential audit | PARTIALLY FIXED | Import is audited through `EmployeeService`. Password reset is not audited. Failed logins are lost. |
| §6 "replaying a spent token revokes the entire family" | **Never worked** (claim was false) | PRA-01, `test_auth_security.py:117-122` |
| §6 "per-account lockout after five failures" | **Never worked** | PRA-02, `test_credential_rate_limit.py:88-97` |

### TECHNICAL_DEBT_REGISTER (2026-09-10), selected

| ID | Status | Evidence |
|---|---|---|
| PAY-001 batch attendance | VERIFIED FIXED | Nightly sweep plus `calculate_range` (`attendance/tasks.py`) |
| PAY-002 paid/payable columns | VERIFIED FIXED | Summary has `paid_days`, `payable_days`, `not_employed_days` (catalog) |
| PAY-004/005 NOT_JOINED/EXITED fractions | VERIFIED FIXED (spot) | `calculation.py:926,1080` population-gate handling |
| PAY-003/006/007/012, ATT-013 | CANNOT VERIFY in depth | Reported fixed in `5fda7b9`/`e705550`. Tests present. Not re-derived line by line. |
| PAY-010 approval race | VERIFIED FIXED | Advisory lock, `leave/repository.py:346` |
| PAY-011 negative balance | VERIFIED FIXED | `_negative_floor`, `leave/service.py:549` |
| DAT-001 accrual idempotency | VERIFIED FIXED | `uq_leave_ledger_cycle_entry` |
| DAT-002 pagination | PARTIALLY FIXED | as API-01 |
| DAT-004 `_reverse_approval` `date.today()` | NOT FIXED | `leave/service.py:2879` |
| DAT-005 backdating / UTC month | NOT FIXED | `leave/service.py:2134,2145` |
| DAT-006 same-type overlap | PARTIALLY FIXED | Blocked only at approval via projection (PRA-15) |
| DAT-010 projection FK | NOT FIXED | Catalog: no FK on `leave_application_id` |
| DAT-011 period legal entity | VERIFIED FIXED | Exclusion includes `legal_entity_id` |
| SEC-001 CORS | VERIFIED FIXED | as OPS-01 |
| SEC-002 rate limiting | VERIFIED FIXED | as SEC-02 |
| SEC-004 headers / proxy | VERIFIED FIXED | |
| SEC-005/006 upload | VERIFIED FIXED | |
| SEC-007 `company` RLS no-op | NOT FIXED (accepted) | Catalog `relrowsecurity=f` |
| SEC-011 scanning | PARTIALLY FIXED | Gitleaks blocking. Dependency scans non-blocking. No container or SAST scan. |
| TST-001 CI DB | PARTIALLY FIXED | DB, Redis and MinIO in CI. Integration runs as superuser. |
| TST-002 frontend CI | VERIFIED FIXED | |
| TST-003 coverage | NOT FIXED | No coverage configuration in `pyproject.toml` or CI |
| TST-004 concurrency tests | PARTIALLY FIXED | Attendance and comp-off concurrency tests exist |
| OPS-001 CD / images | PARTIALLY FIXED | Prod compose and images exist. No CD, no CI build. |
| OPS-002 backups | PARTIALLY FIXED | Scripts and runbook. No off-site copy or restore evidence. |
| OPS-003 monitoring | NOT FIXED | |
| OPS-004 health | VERIFIED FIXED | |
| OPS-006 beat leader election | NOT FIXED (accepted, single instance) | |
| OPS-010 task retry / logging | NOT FIXED | |
| AUD-1 audit read API | NOT FIXED | No route or UI |
| ATT-001 rounding | NOT FIXED (hidden in UI) | `apply_rounding` has no callers |
| ATT-004 excess break | NOT FIXED (hidden in UI) | Never read in `calculation.py` |
| ATT-005 night OT window | VERIFIED FIXED | `calculation.py:784-800` |
| ATT-011 banker's rounding | NOT FIXED | `calculation.py:693` |
| ARC-001 god services | NOT FIXED (worse) | `attendance/service.py` is now 6,411 lines (was 5,480) |
| DEAD-1 dead code | PARTIALLY FIXED | gunicorn and `PaginationMeta` now used. `apply_rounding` and `ingestion/routes.py` remain. |
| SEC-003 tokens in localStorage | PARTIALLY FIXED | Refresh moved to a cookie |
| SEC-010 reset / verify / MFA | PARTIALLY FIXED | Reset and verify exist. No MFA. |

### RELEASE_HARDENING_PHASE_6 (2026-09-25)

| ID | Status | Evidence |
|---|---|---|
| REPO-01 uncommitted tree | PARTIALLY FIXED | Committed, but 4 commits unpushed and `apps/mobile/` untracked |
| DB-01 app role password | VERIFIED FIXED | `002_app_role.sh` requires `HRMS_APP_PASSWORD`. Test `test_db01_credential_provisioning.py`. |
| CI-02 image / compose CI job | NOT FIXED | `ci.yml` has no docker build |
| Off-VPS backup / key custody / privacy notice | NOT FIXED (policy items) | No evidence in repo |

---

## Production Blockers

No P0 findings. These P1 items block production:

| ID | Title |
|---|---|
| PRA-01 | Refresh-token reuse detection is rolled back |
| PRA-02 | Account lockout is rolled back (never engages) |
| PRA-03 | No way to revoke a user's access (leavers, deactivation) |
| PRA-04 | Bulk import routed to an unconsumed Celery queue |
| PRA-05 | `WEB_APP_BASE_URL` missing from prod config, no guard; all email links point to localhost |
| PRA-06 | Next.js with a critical advisory; dependency scans non-blocking |
| PRA-07 | Monthly accrual: no catch-up, no trigger, no alert |
| PRA-10 | Backups: no off-site copy, no encryption, no verified restore, no evidence of key custody |
| PRA-11 | No error tracking or alerting |

Conditional P1s (block beyond a small pilot):

| ID | Title |
|---|---|
| PRA-08 | Sweep versus punch lock contention at peak time (UNMEASURED; load test before >100 employees) |
| PRA-12 | No image-build CI, no branch protection, unpushed and unverified commits |
| PRA-13 | RLS proven by only 4 runtime-role tests; most integration tests run as superuser |

## High-Priority Issues (P1) — detail

**PRA-01 — Refresh-token reuse detection never persists**

| Field | Detail |
|---|---|
| Severity / area | P1 · Authentication |
| Evidence | `identity/service.py:124-129` revokes the family and then raises `InvalidTokenError`. `core/db/session.py:80-82` rolls back on any exception. `tests/integration/auth/test_auth_security.py:117-122` asserts the rotated token still works after a replay. |
| Affected | `IdentityService.refresh`, `IdentityRepository.revoke_refresh_family`, `get_session` |
| Why it matters | A stolen refresh token keeps working alongside the victim's. The control documented in Phase 3A and the 2026-09-17 audit does not exist. |
| Verification | Login, refresh (A→B), replay A (401), then refresh with B. It returns 200 today and should return 401. |
| Remediation | Persist the revocation in an independent transaction (separate session or commit before raising), or return a non-exception result that the router converts to 401 after commit. Fix the test. Add a cross-tab grace window (see PRA-18). |
| Blocks production | Yes |

**PRA-02 — Account lockout never engages**

| Field | Detail |
|---|---|
| Evidence | `identity/service.py:70-72` (increment then raise). Acknowledged in `test_credential_rate_limit.py:88-97`. The invite-accept path has the same pattern (`account_invite/service.py:265-267`). |
| Impact | Only the 10/min per-email limiter stands between an attacker and online guessing (~14,400 guesses/day per account, more if spread across IPs). |
| Remediation | Same mechanism as PRA-01. Decide whether lockout is wanted at all, given that it is a DoS lever, and document the decision. |
| Blocks production | Yes, at minimum fix or remove the claim |

**PRA-03 — No user access revocation**

| Field | Detail |
|---|---|
| Evidence | No route that modifies `user.status` or `user_company.status` (`grep` in modules). `deactivate_employee` sets `is_active=False` only (`employee/service.py:690-717`). `terminate_employment` never touches identity. `get_current_user` checks only user/session/membership status. |
| Impact | Exited employees, and dismissed HR admins, keep API access for as long as they keep refreshing, including access to payslips and other employees' PII. |
| Workaround | Strip all roles (`PATCH /users/{id}/roles` with `[]`). The user stays authenticated. |
| Remediation | A suspend/remove-membership operation that also calls `revoke_all_sessions_for_user`. Wire it to deactivate and to last-working-day. Add a last-admin guard. |
| Blocks production | Yes |

**PRA-04 — Employee import never processed in production**

| Field | Detail |
|---|---|
| Evidence | `employee_import/tasks.py:32` `queue="reports_exports"`. The prod worker command has no `-Q`. No `task_queues`/`task_routes` anywhere. |
| Verification | `docker compose exec worker celery -A entrypoints.worker inspect active_queues` shows only `default`. Create an import and it stays `PENDING`. |
| Remediation | Add `-Q default,reports_exports` (or route the task to default). Add a CI or compose smoke test that consumes each declared queue. |
| Blocks production | Yes, for bulk import |

**PRA-05 — Email links point to localhost**

| Field | Detail |
|---|---|
| Evidence | `settings.py:185` defaults to `http://localhost:3000`. It is absent from `apps/api/env/.env.production.example`. No boot guard exists. Used at `identity/service.py:314,391`, `account_invite/service.py:176`, `onboarding/service.py:709`, `attendance/reminders.py:148`. |
| Impact | Verification is required for a second login, so self-registered admins are locked out after their first session. Invites, onboarding and reset are all unusable. |
| Remediation | Add it to the template and refuse to boot outside development when it is localhost or non-https. |
| Blocks production | Yes |

**PRA-06 — Critical frontend dependency advisory**

| Field | Detail |
|---|---|
| Evidence | `npm audit --omit=dev`: `next` critical, `postcss`/`nanoid` high (this session). CI steps are `continue-on-error`. |
| Remediation | Upgrade Next (major), then make `npm audit --audit-level=critical` blocking. |
| Blocks production | Yes, for an internet-facing deployment |

**PRA-07 — Monthly accrual is fragile**

| Field | Detail |
|---|---|
| Evidence | `celery_app.py:30-33` (single crontab firing). `LeaveAccrualService.run_for_company` accrues only the month before `as_of`. No accrual route in `leave/router.py`. One transaction per company with no per-employee savepoint. No retry. |
| Impact | Silently missing or partial accrual, which leads to wrong balances and wrong LOP. |
| Remediation | Catch-up over missed months (idempotent already), per-employee savepoints, an admin re-run endpoint or command, an alert on zero writes or exceptions. |
| Blocks production | Yes, for leave correctness |

**PRA-08 — Nightly sweep blocks live punches (UNMEASURED)**

| Field | Detail |
|---|---|
| Evidence | `attendance/tasks.py:_calculate_company_async` (one session and transaction, `FOR UPDATE` per day row, held to the end). Scheduled at 09:30 IST. `PunchService._try_immediate_calculate` locks the same row. No `lock_timeout`. Gunicorn timeout 60s. |
| Remediation | Commit per employee (as `calculate_range` already does), set `lock_timeout` in the immediate path and skip on timeout (the sweep catches up), move the schedule off peak, and load test. |
| Blocks production | Conditional (tenant size) |

**PRA-10 — Backup and DR not production grade**

| Field | Detail |
|---|---|
| Evidence | `infra/backup/*.sh` write local disk only. No encryption. Cron is not installed by any repo artefact. No restore evidence. Key custody is only a policy statement. |
| Remediation | Encrypted off-site copy (restic/rclone to object storage), an installed and monitored schedule, a quarterly restore drill with a recorded result, a documented key custodian. |
| Blocks production | Yes, before real data |

**PRA-11 — No error tracking or alerting**

| Field | Detail |
|---|---|
| Evidence | `handlers.py:79-80`. No metrics, Sentry or OTel dependencies. Jobs log at warning only. |
| Remediation | Log every unhandled exception with the request id through structlog. Add an error tracker (self-hosted acceptable). Alert on job failure, readiness failure, disk, and backup age. |
| Blocks production | Yes, minimum viable alerting |

**PRA-12 — CI/CD gaps** (P1 conditional). No image or compose build (CI-02). No branch
protection (plan limit). 4 unpushed commits. Remediation: add a `docker build` and
`compose up --wait` smoke job, push and verify the face commits, and use PR discipline or a paid
plan.

**PRA-13 — RLS test depth** (P1 conditional). Remediation: run a representative integration
subset (attendance, leave, onboarding, import) as `hrms_app`, or add a table-driven
cross-tenant probe for every RLS table.

## Medium-Priority Issues (P2)

| ID | Area | Title | Evidence | Remediation |
|---|---|---|---|---|
| PRA-09 | API | Unbounded attendance list endpoints | `attendance/router.py:860-906` | Paginate and require a bounded date range |
| PRA-14 | Leave | `date.today()` / UTC month in leave | `leave/service.py:2134,2145,2879` | Use `business_today(company.timezone)` |
| PRA-15 | Leave/Attendance | Overlap blocked only at approval; concurrent race; no fraction bound | `leave/repository.py:600-626`; `calculation.py:1141-1180`; catalog | Submit-time overlap check, per-employee lock at approval, `CHECK (paid_day_fraction <= 1)` |
| PRA-16 | Audit | Audit mutable by runtime role; no read API; failures and security events lost; reset not audited | catalog grants; `identity/service.py` | `REVOKE UPDATE, DELETE`; separate-transaction security event log; audit viewer |
| PRA-17 | Storage | App uses MinIO root credentials; full S3 API public | `.env.prod.example:42`; nginx storage block | Scoped MinIO user/policy per bucket; restrict proxied methods |
| PRA-18 | Frontend | Multi-tab refresh race wipes session in all tabs | `lib/api/client.ts` | BroadcastChannel/lock, retry-after-peer-refresh, server grace window |
| PRA-19 | RBAC | Permission rollout through role-code migrations; legacy roles drift; no last-admin guard | `alembic/versions/*backfill*`; `account_invite/schemas.py:67` | Permission-template sync mechanism; last-admin guard |
| PRA-20 | Face / Privacy | Third-party cross-border biometric processing; unverified commits; live test keys in local `.env` | `face_verification.py`, `settings.py:facepp_*` | Legal review, DPA, key rotation, CI the commits |
| PRA-24 | Auth | Unbounded session lifetime; logout leaves refresh tokens | `core/auth/dependencies.py`; `identity/service.py:logout` | Enforce `Session.expires_at`/absolute max; revoke refresh on logout |
| PRA-27 | Jobs | No retries, `acks_late` or time limits; beat unmonitored; `/tmp` schedule | `celery_app.py`, compose | Retry policy for idempotent tasks, beat heartbeat |
| PRA-29 | Auth | No MFA; no authenticated password change | `identity/router.py` | Add change-password; plan MFA for admins |
| PRA-31 | Privacy | No retention, erasure or export; immutable audit versus erasure | — | Legal-reviewed retention policy and tooling |
| PRA-33 | Config | `ENVIRONMENT` defaults to `development`, which disables all guards when omitted | `settings.py:56` | Default to `production` or require it explicitly |
| PRA-34 | Email | Verification and reset send failures swallowed with no log | `identity/service.py:322-325,396-399` | Log and surface; outbox with retry |

## Low-Priority Improvements (P3)

| ID | Title | Evidence |
|---|---|---|
| PRA-21 | Inert attendance policy settings still accepted by API; banker's rounding | `calculation.py:693,696`; `service.py:3489` |
| PRA-22 | Login timing side channel (no dummy argon2 for unknown emails) | `identity/service.py:62-64` |
| PRA-23 | ESLint and pip-audit non-blocking; `urllib3 2.7.0` has 3 CVEs (fix 2.8.0) | `ci.yml`; pip-audit this session |
| PRA-25 | Rate limiter INCR/EXPIRE non-atomic (a crash between them gives a permanent key); fixed window | `shared/rate_limit.py:82-87` |
| PRA-26 | Storage/DB ordering leaves orphan or dangling objects; no reconciliation | `onboarding/service.py:800,864` |
| PRA-28 | Audit row per recalculation; no audit retention or partitioning | `attendance/service.py:2980-2990` |
| PRA-30 | Repo hygiene: tracked `mavericks-kit.zip`, `shirt.png`, `shorts.png`; README stale ("Sprint 0 scaffold", Terraform); dev DB behind head; dev script runs no Celery; tests default to and truncate `hrms_dev` | `git ls-files`; `README.md`; `tests/conftest.py` |
| PRA-32 | Edge: no Nginx rate limiting; `certbot:latest`, `gitleaks:latest` unpinned; no container resource limits | `infra/nginx`, compose, `ci.yml` |
| PRA-35 | `002_app_role.sh` interpolates the password unescaped into SQL | `infra/docker/postgres/init/002_app_role.sh` |
| PRA-36 | DAT-010: no FK `leave_day_projection.leave_application_id` | catalog |
| PRA-37 | `attendance/service.py` 6,411 lines; module cycle leave↔attendance | ARC-001/002 |
| PRA-38 | Web self-punch sends no idempotency key | `apps/web/src` |

---

## Documentation vs Reality

**Accurate (verified):** `POSTGRES_RLS_ROLE_*` (runtime role, policies), `UPLOAD_BATCH_A/B/C`
(storage, validation, rate limits), `ATTENDANCE_TIMEZONE_*` (business dates, CI TZ), the
`PRODUCTION_DEPLOYMENT.md` topology, `API_01` endpoint list (accurate about its own Tier-1
scope), and `PAYROLL_BUSINESS_DECISIONS.md` progress for leave and attendance fixes.

**Stale**

- `README.md`: "Sprint 0 scaffold", "Terraform", "local dev shell".
- `celery_app.py` comment saying accrual is "the only entry with a real task behind it". Six
  scheduled entries exist.
- `docs/architecture/04_Background_Job_Architecture.md`: the outbox is unimplemented.
- The `refresh_cookie.py` docstring says "no TLS termination anywhere yet". Nginx now terminates
  TLS.
- `middleware.ts` comments say "Nginx/HTTPS is a later phase".

**Claims functionality that does not work**

- 2026-09-17 audit §6 and Phase 3A: refresh-family revocation on reuse (PRA-01).
- The same sources: per-account lockout after five failures (PRA-02).
- `employee/service.py:702-707` docstring: deactivation as "immediate access cutoff" (PRA-03).
- `employee_import/tasks.py` docstring: `reports_exports` queue "per" the architecture doc. That
  queue has no consumer (PRA-04).
- `audit/redact.py` and the design baseline: "architecturally-immutable" audit table. The runtime
  role holds UPDATE and DELETE (PRA-16).

**Implementation without documentation**

- Face attendance self-enrollment and the provider switch. The decision log is stale relative to
  the `fb2feca` Face++ swap; project memory still says Luxand.
- The `calculate-range` backfill endpoint's operational use in the runbook.
- No operator documentation for re-running accrual or year-end. That capability does not exist.

---

## Unknowns / Evidence Gaps

| Unknown | Why | How to close |
|---|---|---|
| Performance at 500 / 1,000 / 5,000 employees | No load test | k6/Locust: punch burst at 09:30 concurrent with the sweep; HR list pages |
| Restore success | No drill run here | Scripted restore into scratch DB and bucket with row/object counts, record the result |
| PII ciphertext at rest | Dev DB has no PII rows | Seed via the API in staging and inspect columns |
| Production image boot with real env | Not built this session (last verified Phase 6, 2026-09-25) | CI-02 job |
| Real SMTP / Mailtrap delivery, TLS issuance | Environment-blocked | Staging with a real domain |
| Accessibility and mobile responsiveness | Not audited | axe + Lighthouse; device matrix |
| Mobile app | Source not on `main` | Separate audit of the mobile branch |
| PAY-003/006/007/012 internals | Not re-derived | Targeted review |
| Face++ liveness robustness | Vendor behaviour | Vendor docs and spoof testing |

---

## Recommended Remediation Sequence

1. **Make the first deploy work** (hours): PRA-05 (base URL plus guard), PRA-04 (queue), PRA-33
   (`ENVIRONMENT` default). Push and CI the 4 face commits (PRA-12).
2. **Restore the claimed auth controls** (days): PRA-01, PRA-02 (shared fix: security writes
   outside the request transaction), PRA-24, and fix the misleading tests.
3. **Leaver control** (days): PRA-03 plus a last-admin guard (PRA-19).
4. **Operations minimum** (days): PRA-11 (exception logging with request id, error tracker,
   job-failure, readiness and backup-age alerts), PRA-10 (encrypted off-site backups plus one
   recorded restore drill plus key custodian), PRA-27.
5. **Leave and attendance data correctness** (days): PRA-07, PRA-14, PRA-15 (with DB checks),
   PRA-16 (revoke UPDATE/DELETE on `audit_log`).
6. **Dependency risk** (days to a week): PRA-06 Next upgrade, then make scans blocking (PRA-23).
7. **Scale validation** before onboarding a tenant above ~100 employees: PRA-08 change plus a load
   test, and PRA-09.
8. **Hardening**: PRA-17, PRA-18, PRA-13, PRA-20 (legal), PRA-31 (legal), P3 items.

---

## Final Production Readiness Assessment

The application is **not production-ready for real organisations today**. It is close for a
**single, small, trusted pilot tenant**, but only after steps 1–5 above. The core HR data model
and tenant isolation are solid and should not be reworked. The work that remains is concentrated
in four places:

- auth controls that are claimed but non-functional;
- user lifecycle;
- scheduled-job reliability and visibility;
- backup and operations.

None requires architectural change except PRA-08 at larger tenant sizes.

### Final Readiness Table

| Area | Status | Critical Findings | Production Blocker? | Evidence |
|---|---|---|---|---|
| Authentication | NOT READY | PRA-01, PRA-02, PRA-05, PRA-24 | Yes | `identity/service.py`, `core/db/session.py`, auth tests |
| Authorization | READY WITH CONDITIONS | PRA-03, PRA-19 | Yes (PRA-03) | `core/rbac/*`, `account_invite/*` |
| Tenant Isolation | READY | PRA-13 (test depth) | No | Catalog RLS query; `test_rls_runtime_role.py` |
| Employee Management | READY WITH CONDITIONS | PRA-03, PRA-04 | Yes (import, leavers) | `employee/service.py`, `employee_import/tasks.py` |
| Attendance | READY WITH CONDITIONS | PRA-08, PRA-09, PRA-21 | Conditional (size) | `attendance/service.py:2475-2995`, `tasks.py` |
| Leave | READY WITH CONDITIONS | PRA-07, PRA-14, PRA-15 | Yes (PRA-07) | `leave/service.py`, `leave/tasks.py` |
| Documents | READY WITH CONDITIONS | PRA-26, no AV | No (pilot) | `onboarding/document_validation.py` |
| Storage | READY WITH CONDITIONS | PRA-17 | No (fix soon) | compose, nginx, `core/storage.py` |
| Database | READY WITH CONDITIONS | PRA-15 (bounds), PRA-16 (grants) | No | Catalog constraints/grants |
| API | READY WITH CONDITIONS | PRA-09, PRA-33 | No | routers |
| Frontend | READY WITH CONDITIONS | PRA-06, PRA-18 | Yes (PRA-06) | npm audit, `client.ts` |
| Background Jobs | NOT READY | PRA-04, PRA-07, PRA-27 | Yes | `celery_app.py`, compose |
| Security | NOT READY | PRA-01, PRA-02, PRA-03, PRA-06 | Yes | as above |
| Observability | NOT READY | PRA-11 | Yes | `handlers.py`, absence of tooling |
| Backups | NOT READY | PRA-10 | Yes | `infra/backup`, DR doc |
| CI/CD | READY WITH CONDITIONS | PRA-12, PRA-23 | Conditional | `ci.yml`, `gh` output |
| Testing | READY WITH CONDITIONS | Misleading auth tests, RLS depth, no E2E/coverage | No | Appendix A, vitest |
| Performance | UNKNOWN | PRA-08, PRA-09 | Conditional | No load test |
| Privacy | NOT READY | PRA-20, PRA-31, backup plaintext | Yes (legal) | — |
| Pre-Payroll Architecture | READY WITH CONDITIONS | PRA-07, PRA-14, PRA-15, PRA-16 | For payroll trust | Summary columns, period locks |

---

## Final Verdict

### A. What is genuinely production-ready today?

- Tenant isolation (RLS plus runtime role plus fail-closed policies).
- RBAC data-scope resolution.
- Punch ingestion and attendance-day calculation correctness and locking.
- Period locking across attendance and leave.
- Leave ledger and approval-time balance locking.
- Onboarding document upload hardening.
- PII field encryption design.
- Production boot guards (given `ENVIRONMENT` is set).
- Security headers, CSP and HttpOnly refresh cookie.

### B. What is production-ready only with conditions?

- Attendance at small scale (PRA-08 untested).
- Leave (PRA-14, PRA-15).
- Storage (PRA-17).
- Frontend (PRA-06, PRA-18).
- CI (PRA-12).
- Face attendance (CI, legal).
- Organisation configuration (inert settings).

### C. What currently prevents production deployment?

PRA-01, 02, 03, 04, 05, 06, 07, 10, 11.

### D. Top 10 risks

1. A stolen refresh token is never detected (PRA-01).
2. Leavers retain access (PRA-03).
3. Email links are broken, so users cannot verify, reset or accept invites (PRA-05).
4. Silent missed or partial monthly accrual, leading to wrong balances and LOP (PRA-07).
5. Data loss on VPS failure with no off-site or encrypted backup (PRA-10).
6. Production errors and job failures are invisible (PRA-11).
7. Punch requests stall during the 09:30 sweep at scale (PRA-08).
8. Critical Next.js advisory on an internet-facing app (PRA-06).
9. Online password guessing is limited only by the rate limiter (PRA-02).
10. Bulk import silently never runs (PRA-04).

### E. What could cause data loss or corruption?

- PRA-10 (backups on the same disk).
- Loss of `PII_MASTER_KEY` (custody unproven).
- PRA-15 (double leave on one day, double debit under a race).
- PRA-07 (missing accruals).
- PRA-14 (reversal booked in the wrong period).
- PRA-08 (punch transaction rolled back on worker timeout).
- PRA-16 (audit rows deletable by the app role).
- PRA-26 (dangling document references).

### F. What could cause cross-tenant or security breaches?

No cross-tenant path was found. Security exposure comes from:

- PRA-01, PRA-02, PRA-03;
- PRA-17 (root MinIO credentials with a public S3 API);
- PRA-06;
- PRA-33 (guards off if `ENVIRONMENT` is omitted);
- the latent pre-auth GUC footgun for future public routes.

### G. What could cause incorrect attendance or leave records?

PRA-07, PRA-14, PRA-15, PRA-21 (inert settings an admin may believe apply), PRA-08 (stale day rows
until the next sweep when an immediate calculation fails), and missed sweeps (no alerting).

### H. What areas have insufficient testing?

- DB-level RLS beyond the employee lifecycle.
- Auth reuse and lockout (tests assert the wrong behaviour).
- Celery wiring, routing and schedule.
- Concurrent leave approvals.
- Punch versus sweep contention.
- Leave timezone sites.
- E2E and accessibility.
- Docker image boot.
- Coverage is unmeasured.

### I. What areas have insufficient observability?

- Unhandled exceptions (no request id).
- Scheduled jobs (warning logs only, beat unmonitored).
- Email delivery.
- Security events (failed logins, reuse, lockout, password reset).
- Performance (no metrics).
- Backups (no age or success alert).

### J. What must be fixed BEFORE production?

- PRA-01, 02, 03, 04, 05, 06, 07, 10, 11, 33.
- A legal privacy notice.
- A named custodian for `PII_MASTER_KEY`.
- Push and CI the unverified commits.
- PRA-08 load test before any tenant above ~100 employees.

### K. What can safely be postponed until AFTER initial production?

PRA-09 (small tenants), PRA-13, PRA-17 (soon after), PRA-18, PRA-19 (beyond the last-admin
guard), PRA-21–23, PRA-25–30, PRA-32, PRA-35–38, MFA (except for admins on a public offering), AV
scanning (pilot only), partitioning, and the god-service split.

### L. What must be addressed BEFORE starting (or trusting) Payroll?

- **PRA-07:** accrual reliability and catch-up.
- **PRA-14:** company-timezone dates in leave.
- **PRA-15:** submit-time overlap check, a per-employee approval lock, and DB `CHECK` bounds on
  day fractions.
- **PRA-16:** an immutable audit log for corrections that feed pay.
- **PRA-03:** exited employees must lose access to payslips.
- **PRA-11:** alerting on the daily sweep, so closed periods are not built on stale days.
- A decision on whether the inert policy settings (PRA-21) are removed from the API, so payroll
  consumers never assume they are in effect.
- Payroll phases 5.1–5.6 already exist in code. They should be re-validated against these fixes
  once they land.

---

## Appendix A — Test results (this session)

| Suite | Result | Command / environment |
|---|---|---|
| Backend (unit + integration + security) | **1,809 passed, 0 failed, 0 errors**, 1 deprecation warning, 6m35s | `pytest tests` with `DATABASE_URL`/`MIGRATIONS_DATABASE_URL` set to the isolated `hrms_test` (at head `20261007090000`), Redis db 1, local MinIO, `FACE_VERIFICATION_PROVIDER=disabled`, `ENVIRONMENT=development` |
| Frontend vitest | **404 passed / 57 files** | `npx vitest run` |
| Frontend typecheck | Clean | `npx tsc --noEmit` |
| npm audit (prod deps) | 1 critical, 2 high | `npm audit --omit=dev` |
| pip-audit | 3 CVEs in `urllib3 2.7.0` | `uvx pip-audit` on `uv export` |

**Interpretation.** An all-green suite is consistent with the findings above, not evidence
against them:

- PRA-01 and PRA-02 are asserted by passing tests.
- PRA-04 is invisible because tasks are invoked as plain functions.
- PRA-13: integration tests run as the `hrms` superuser.

The previously known baseline failures recorded in project memory (1 stale permission test and 22
dev-DB pollution errors) did not reproduce against the clean `hrms_test` database.

*Audit performed read-only. No application file, configuration, migration, test, CI workflow or
Docker file was modified; nothing was committed or pushed.*
