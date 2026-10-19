# Platform console (super admin) — operating guide

A platform super admin approves new companies and manages their lifecycle. Design rationale:
`docs/design/SUPER_ADMIN_PLATFORM_CONSOLE_PLAN.md`. Errors: `docs/development/API_ERROR_CONTRACT.md`.

## Company lifecycle

```
register ─► PENDING_APPROVAL ─approve─► TRIAL ◄─► ACTIVE ─suspend─► SUSPENDED ─reactivate─► TRIAL/ACTIVE
                 │ reject                                       any non-terminal ─terminate─► TERMINATED
                 ▼
             REJECTED ─approve─► TRIAL
```

| Status | Sign in | Reads | Writes |
| --- | --- | --- | --- |
| `PENDING_APPROVAL` | yes | yes | **no** — 403 `COMPANY_PENDING_APPROVAL` |
| `TRIAL`, `ACTIVE` | yes | yes | yes |
| `SUSPENDED` | yes | yes | **no** — 403 `COMPANY_SUSPENDED` |
| `REJECTED` | no | no | no — 403 `COMPANY_REJECTED` |
| `TERMINATED` | no | no | no — 403 `COMPANY_TERMINATED`; data retained until `retention_until` |

Enforced in `core/auth/company_access.py`, evaluated on **every** request (`get_current_user`), on
sign-in and on token refresh — a status change takes effect on the user's next request, not when
their token expires. `/v1/auth/*` writes (sign-out, refresh) stay allowed in read-only mode.
Scheduled jobs already skip companies that are not `TRIAL`/`ACTIVE`.
The trial clock (14 days) starts at **approval**. `reactivate` returns to `TRIAL` if the trial has
not ended, otherwise `ACTIVE`. `reject` / `suspend` / `terminate` require a reason (shown to the
company, kept in the audit log); `terminate` also requires typing the company name.

## Creating a super admin

There is no public endpoint. On the server:

```bash
cd apps/api
uv run python scripts/create_platform_admin.py --username admin --password '<password>'
uv run python scripts/create_platform_admin.py --username admin --password '<new>' --reset   # reset / unlock
```

Usernames are 3–64 chars of `a-z 0-9 . _ -`. The script does not enforce the tenant password policy:
use a strong password anywhere that is not a developer machine. **MFA is not implemented** (deferred);
until it is, restrict `/v1/platform` and `/platform` at the reverse proxy (IP allow-list / VPN).

## Using it

- Web: `/platform/login` → company queue (defaults to *awaiting approval*), company detail with
  Approve / Reject / Suspend / Reactivate / Terminate, trial extension, unlock admin; `/platform/audit`.
- API (platform token only): `POST /v1/platform/auth/login`, `GET /dashboard`, `GET /companies`,
  `GET /companies/{id}`, `POST /companies/{id}/{approve|reject|suspend|reactivate|terminate}`,
  `PATCH /companies/{id}/subscription` (`plan_code`, `extend_trial_days`, `seat_limit_override`),
  `POST /companies/{id}/admin/unlock`, `GET /audit-log`.
- Platform tokens: JWT `type=platform`, `aud=platform`, 30 min (`PLATFORM_ACCESS_TTL_MINUTES`), not
  refreshable, backed by a revocable `platform_session`. Tenant tokens are rejected on `/v1/platform`
  and platform tokens on every tenant route (tested).

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `COMPANY_APPROVAL_REQUIRED` | `true` | New registrations start `PENDING_APPROVAL`; `false` → straight into `TRIAL` (old behaviour). |
| `PLATFORM_ACCESS_TTL_MINUTES` | `30` | Platform token lifetime. |
| `TERMINATED_COMPANY_RETENTION_DAYS` | `90` | Sets `company.retention_until` on terminate. |

Migration `20261019090000` adds the statuses/columns and the `platform_admin`, `platform_session`,
`platform_audit_log` tables. Existing companies are untouched.

## Audit

Every platform action writes `platform_audit_log` (actor, action, company, reason, before/after
status, IP, request id). It is append-only: a trigger rejects UPDATE/DELETE for every role, and the
runtime role has no UPDATE/DELETE/TRUNCATE grant. The company's own `audit_log` also gets a
`COMPANY_STATUS_CHANGED_BY_PLATFORM` row. Logs: `security.platform.*` events. Company admins get a
best-effort email on approve/reject/suspend/reactivate/terminate (a failed email never undoes the change).

## Deviations from the plan, and known gaps

- **No separate `hrms_platform` database role.** The platform API uses the normal app role. RLS is not
  bypassed: for the RLS tables it needs (subscription, employee/user counts) the transaction is scoped
  to the one company being viewed. The platform tables are only reachable from `/v1/platform` code.
  A dedicated least-privilege role remains a hardening option.
- **No session revocation on reject/terminate.** Unnecessary — the per-request gate blocks everything
  at once and gives users the specific `COMPANY_*` message; it also keeps reject → approve reversible.
- **Not built:** MFA; forced password reset for a company admin (only *unlock*); retention **purge**
  (nothing deletes terminated data — `retention_until` is recorded for a future, deliberate job);
  email to platform admins about new registrations (platform admins have no email address — check the
  *awaiting approval* queue); per-plan feature gating beyond what subscription already does; public
  onboarding-token endpoints of a suspended company are not blocked.
- Tests that call the tenant API from non-platform suites run with `COMPANY_APPROVAL_REQUIRED=false`
  (set in `tests/conftest.py`); the platform suite turns it on.
