# Super admin (platform console) — implementation plan

Status: **implemented** (see `docs/operations/PLATFORM_CONSOLE.md` for the operating guide and the
deviations from this plan). Decisions taken:

| # | Decision |
| --- | --- |
| 1 | Unapproved company's admin can sign in and **view** only (read-only). |
| 2 | Approval is always manual (`COMPANY_APPROVAL_REQUIRED`, default on; off restores the old behaviour). |
| 3 | Suspend = **read-only grace mode** (sign-in and reads work, writes refused). |
| 4 | MFA deferred — not implemented; sign-in is username + password with lockout and rate limit. |
| 5 | First super admin created by `scripts/create_platform_admin.py` (login by **username**, not email). |
| 6 | No impersonation. |
| 7 | Terminated companies have a data **retention period** (`TERMINATED_COMPANY_RETENTION_DAYS`, default 90); nothing purges data automatically. |

The sections below are the original proposal; where the implementation differs it is noted in
`PLATFORM_CONSOLE.md`.

## 1. Goal

Today a company joins by self-registering (`POST /v1/companies/register`): it is created in
status `TRIAL`, its first admin can log in once their email is verified, and nobody on the platform
side sees, approves, suspends or manages it. This plan adds a **platform super admin** who can:

1. **Approve / reject** new companies.
2. **Manage** companies: view, suspend, reactivate, terminate, extend trial, change plan / seat limits,
   help the company's admin (unlock, force password reset).
3. Do all of it with an immutable audit trail, without weakening tenant isolation.

## 2. What exists today (verified in the code / dev DB)

| Area | Fact | Consequence |
| --- | --- | --- |
| `company.status` | DB CHECK allows `TRIAL, ACTIVE, SUSPENDED, TERMINATED`. | No "pending approval" or "rejected" state: needs a migration to widen the CHECK. |
| Enforcement | `SUSPENDED` is checked in **one place** (`OrganisationService.update_company_profile` → `CompanyWriteBlockedError`). Login, refresh and `get_current_user` never look at company status. | Suspending a company today would not stop anyone. Enforcement is the core of this work. |
| Auth | Access JWT = `sub, company_id, session_id, employee_id`; `get_current_user` validates user, session and `user_company` membership per request. Every user belongs to a company. | A super admin does not fit this model; needs a separate identity. |
| Tenancy | Postgres RLS on tenant tables via `app.company_id` GUC; `hrms_app` is NOSUPERUSER/NOBYPASSRLS. `company` and `user` have no RLS; `subscription` and `audit_log` have FORCE RLS. | Cross-tenant reads must not use `BYPASSRLS` on the app role. |
| Billing model | `plan`, `plan_feature`, `subscription` (status, period, trial, `seat_limit_override`) exist. | Plan/seat management can reuse them. |
| Errors / audit | Standard error envelope (`docs/development/API_ERROR_CONTRACT.md`); tenant `audit_log` is RLS-scoped. | Platform actions need their own audit table. |

## 3. Design

### 3.1 Identity: separate `platform_admin`, not a special company role
- New table `platform_admin` (id, email, password_hash, mfa_secret, status, last_login_at, failed-login/lock
  fields). Not in `user`, no `user_company` row, no company RBAC. Compromise of a tenant account can
  never grant platform power, and vice versa.
- Separate login `POST /v1/platform/auth/login` (+ refresh/logout), own rate-limit buckets, own session
  table `platform_session`.
- Access token carries `typ: "platform"` and a different `aud`; `get_current_user` rejects it, the platform
  dependency rejects tenant tokens. Short TTL (e.g. 10 min), no long-lived remember-me.
- **MFA (TOTP) mandatory** for every platform admin; optional IP allow-list setting. **[DECIDE]** TOTP vs
  email OTP.
- **Bootstrap** only by CLI (`scripts/create_platform_admin.py`, run on the server). Never creatable through
  a public endpoint. Roles: start with one (`PLATFORM_ADMIN`); optional later split `SUPPORT` (read-only)
  vs `OWNER` (suspend/terminate).

### 3.2 Company lifecycle (state machine)
```
register ──► PENDING_APPROVAL ──approve──► TRIAL ──► ACTIVE ◄──reactivate── SUSPENDED
                  │                          │          │                      ▲
                  └──reject──► REJECTED      └──────────┴────suspend───────────┘
                                             any of TRIAL/ACTIVE/SUSPENDED ──terminate──► TERMINATED (terminal)
```
- Migration: widen `company_status_check` to add `PENDING_APPROVAL`, `REJECTED`; add columns
  `status_reason text`, `status_changed_at`, `status_changed_by_platform_admin_id`, `approved_at`.
  All existing rows stay as they are (existing `TRIAL`/`ACTIVE` companies are implicitly approved).
- **[DECIDE]** Does an unapproved company's admin get to log in at all?
  - *Recommended:* the admin can verify email and log in, but every tenant API except a small
    allow-list (`/auth/*`, `/me`, `/companies/me` read) returns `403 COMPANY_PENDING_APPROVAL`; the web/mobile
    app shows a "waiting for approval" screen. This keeps registration friction low and gives the
    platform admin real data to judge.
  - *Alternative:* block login entirely until approved.
- **[DECIDE]** Auto-approval switch (setting) for environments / plans that should not need manual approval.
- Transitions are validated in one service (`CompanyLifecycleService`), one transaction, with the previous
  status checked (`version`/`If-Match`) so two operators cannot race. Illegal transitions → `409 INVALID_COMPANY_TRANSITION`.

### 3.3 Enforcement (the part that makes suspension real)
Single choke point, not per-endpoint checks:
1. **Login & refresh**: reject when company status ∈ {PENDING_APPROVAL*, REJECTED, SUSPENDED, TERMINATED}
   with stable codes `COMPANY_PENDING_APPROVAL`, `COMPANY_REJECTED`, `COMPANY_SUSPENDED`, `COMPANY_TERMINATED`
   (403; message user-safe, includes a support request id). No enumeration leak: only after credentials validated.
2. **`get_current_user`**: it already loads user/session/membership each request; extend that query to join
   `company.status` (no extra round trip). A token minted before a suspension stops working immediately —
   not after the 15-minute TTL.
3. **Suspend / terminate revoke all of the company's sessions and refresh tokens** in the same transaction.
4. **Write-block vs full block [DECIDE]:** SUSPENDED = full lock-out (recommended, matches "suspend");
   optional `READ_ONLY` mode for billing grace periods (reuse `CompanyWriteBlockedError`).
5. **Background work**: Celery fan-out tasks (leave accrual, attendance calculation, face cleanup, import)
   skip companies not in {TRIAL, ACTIVE}; public onboarding-link endpoints for a suspended company return 403.
6. **Mobile/web clients**: handle the four new codes with a dedicated screen (no retry loops); mobile uses the
   shared `ApiError` code.

### 3.4 Cross-tenant data access without breaking RLS
- Platform queries touch: `company`, admin `user` + `user_company`, `subscription`, `plan`, aggregate counts
  (employees, active users, last activity). Only `subscription` (and counts over RLS tables) is blocked by RLS.
- Add a dedicated DB role **`hrms_platform`**: NOSUPERUSER, **NOBYPASSRLS**, with
  - `SELECT/UPDATE` on `company`, `SELECT` on `user`, `user_company`, `plan*`, `subscription` (+ explicit
    additional permissive RLS policy `platform_read` limited to `TO hrms_platform`),
  - `UPDATE` on `refresh_token`/`session` revocation columns (for forced logout),
  - `INSERT` only on `platform_audit_log`.
  - Counts come from narrow `SECURITY DEFINER` functions (`platform_company_usage(company_id)`) returning
    aggregates only — never employee-level rows. The console never shows employee PII.
- Platform API uses its own engine/connection settings (`PLATFORM_DATABASE_URL`); the tenant app role gets
  **no** new privileges. Tenant routes can never reach platform tables (separate router, separate dependency).
- Alembic runs as schema owner (`hrms`) and grants to `hrms_platform` in the migration; CI init scripts
  (`infra/docker/postgres/init/`) create the role.

### 3.5 Platform audit log
- `platform_audit_log` (append-only; no UPDATE/DELETE grant, trigger rejects both): actor platform admin,
  action (`COMPANY_APPROVED`, `…_REJECTED`, `…_SUSPENDED`, `…_REACTIVATED`, `…_TERMINATED`, `TRIAL_EXTENDED`,
  `PLAN_CHANGED`, `ADMIN_UNLOCKED`, `ADMIN_PASSWORD_RESET_FORCED`, `PLATFORM_LOGIN`…), target company,
  **mandatory reason** for reject/suspend/terminate, before/after status, IP, user agent, request id.
- Also write a tenant-visible `audit_log` row (status change) so the company's own admin sees "suspended by
  platform" in their history. Never PII in the platform log.
- Security events (`security_event`) for login failures, MFA failures, every state change.

### 3.6 Notifications
Email to the company admin on approve / reject (with reason) / suspend / reactivate / terminate, and to
platform admins on new registration. Uses the existing email provider layer; template per event; failures
are logged and never roll back the state change (outbox/retry, bounded).

## 4. API surface (`/v1/platform`, separate router, platform-token only)

| Method & path | Purpose |
| --- | --- |
| `POST /auth/login`, `/auth/mfa/verify`, `/auth/refresh`, `/auth/logout` | platform sign-in |
| `GET /companies?status=&q=&plan=&page=` | list/search with the standard pagination envelope |
| `GET /companies/{id}` | profile, status history, subscription, admin contact, usage aggregates |
| `POST /companies/{id}/approve` | PENDING_APPROVAL → TRIAL (optionally set plan/trial days) |
| `POST /companies/{id}/reject` | requires `reason` |
| `POST /companies/{id}/suspend` · `/reactivate` · `/terminate` | requires `reason` (terminate also requires typed confirmation) |
| `PATCH /companies/{id}/subscription` | plan, `trial_ends_at` extension, `seat_limit_override` |
| `POST /companies/{id}/admin/unlock` · `/admin/force-password-reset` | support actions on the company's admin user |
| `GET /audit-log?company_id=&action=` | platform audit trail |
| `GET /dashboard` | counts by status, pending queue age, trials expiring soon |

All mutating endpoints: `If-Match` version, idempotent per request id, standard error envelope
(`409` illegal transition, `404` unknown company, `403` wrong token type, `429` limits).
**Impersonation ("log in as company admin") is deliberately not included [DECIDE]**; if wanted later it needs
explicit company consent, a time-boxed read-only token, and prominent audit.

## 5. Web console
New route group `apps/web/src/app/platform/` with its own layout, login page and nav (no shared tenant shell, no
tenant tokens in its storage). Screens: pending-approval queue (primary), company list/search, company detail
with action buttons + reason dialogs, audit log, dashboard. Mobile gets **no** platform UI; it only handles the
new company-status error codes.

## 6. Phases

| Phase | Content | Exit criteria |
| --- | --- | --- |
| 0 | Resolve **[DECIDE]** items; ADR for platform identity + `hrms_platform` role | decisions recorded |
| 1 | Migration (status values, columns, `platform_admin`, `platform_session`, `platform_audit_log`, DB role + grants); bootstrap CLI | migration up/down tested on a disposable DB |
| 2 | Platform auth (login, TOTP, refresh, lockout, rate limits, token type separation) | cross-token rejection tests pass |
| 3 | `CompanyLifecycleService` + enforcement (login/refresh/`get_current_user`/Celery) + session revocation; registration creates `PENDING_APPROVAL` (behind a setting so rollout can be staged) | suspended company's live token gets 403 on the next request |
| 4 | Platform API (list/detail/actions/subscription/support) + audit + notifications | endpoint tests incl. audit rows |
| 5 | Web console | manual walkthrough on the emulator-independent web app |
| 6 | Client handling of new codes (web + Flutter), docs (`API_ERROR_CONTRACT.md`, runbook for creating platform admins), rollout | full regression green |

## 7. Test plan
- State machine: every legal and illegal transition; concurrent approve/suspend (one wins, other 409).
- Enforcement: login/refresh/in-flight token for each non-active status; sessions revoked on suspend; Celery fan-out skips
  suspended tenants; public onboarding links blocked.
- Isolation/security: tenant token ≠ platform endpoints and the reverse; `hrms_platform` cannot read employee/payroll/attendance
  tables (assert permission denied); tenant role cannot read platform tables; extend `test_route_authorization_matrix` so
  every `/v1/platform` route requires a platform token; no PII in platform responses or logs.
- Audit: each action writes exactly one platform row (+ tenant row), reason required, log is append-only (UPDATE/DELETE fail).
- MFA/lockout/rate-limit; error envelope and `Retry-After` on platform auth.
- Backward compatibility: existing companies keep working after migration; with the approval setting off, registration behaves as today.

## 8. Risks & mitigations
- **Highest-value target on the platform** → separate identity, mandatory MFA, short tokens, IP allow-list, audit, no shared code path with tenant auth.
- **Locking out paying customers by mistake** → mandatory reason, confirmation for terminate, reversible suspend, notification email, audit.
- **Existing data** → migration only widens a CHECK and adds nullable columns; no data rewrite. Terminate = soft state, no data deletion (retention/erasure is a separate legal decision).
- **Per-request cost** → status joins an existing query; no extra round trip.
- **Scope creep** → billing/payments, impersonation, multi-role platform RBAC, and data export/erasure are explicitly out of this plan.

## 9. Open decisions (answer before Phase 1)
1. Can an unapproved company's admin log in to a "waiting" screen, or is login blocked? (recommended: waiting screen)
2. Is approval always manual, or configurable per environment/plan (auto-approve switch)?
3. Does suspend mean full lock-out only, or also a read-only grace mode?
4. MFA method for platform admins: TOTP (recommended) or email OTP?
5. Who are the first platform admins, and do we need a read-only support role now?
6. Is impersonation wanted at all? (recommended: no)
7. What happens to data on TERMINATED (retention period, export, erasure)?
