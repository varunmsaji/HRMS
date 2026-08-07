# Sprint B1 — Identity & Multi-Tenant Foundation

**Status:** Complete  
**Scope:** Users, companies, memberships, roles, permissions, JWT auth, refresh rotation, RBAC, tenant isolation, audit logging foundation.

---

## Delivered capabilities

| Area | Location | Notes |
|------|----------|-------|
| Identity ORM | `core/db/models/identity.py` | Company, User, memberships, RBAC, sessions, refresh tokens |
| Auth | `core/auth/` | Argon2 passwords, JWT access tokens, opaque refresh tokens (hash-only storage) |
| RBAC | `core/rbac/` | `require_permission()`, per-request DB resolution |
| Tenancy | `core/tenancy/` | `X-Company-Id` validation, RLS via `set_config('app.company_id')` |
| Audit | `core/audit/` | `audit_log` table + `AuditService.record()` |
| Identity API | `modules/identity/` | Login, refresh, logout, me, company detail |
| Seed | `seed/bootstrap.py`, `scripts/seed.py` | Demo companies, admin + viewer users, B1 permissions |

---

## API endpoints (`/v1/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/login` | Public | Email + password → access + refresh tokens |
| POST | `/token/refresh` | Refresh body/cookie | Rotating refresh token |
| POST | `/logout` | Bearer | Revoke session |
| GET | `/me` | Bearer + tenant | Profile + permission codes |
| GET | `/admin/users-check` | Bearer + `SETTINGS.USER.MANAGE` | RBAC guard smoke test |
| GET | `/companies/{id}` | Bearer + tenant | Company detail (tenant-scoped) |

---

## Demo seed credentials

Run: `uv run python scripts/seed.py` (from `apps/api/`)

| User | Email | Password | Company A role |
|------|-------|----------|----------------|
| Admin | `admin@example.com` | `DemoPass123!` | Company Administrator (all B1 permissions) |
| Viewer | `viewer@example.com` | `DemoPass123!` | Employee Viewer (`EMPLOYEE.VIEW` only) |

Stable company IDs: see `seed/constants.py`.

---

## Migrations

| Revision | Description |
|----------|-------------|
| `20260803124757` | Initial schema (from SQL) |
| `20260803200000` | B1: `audit_log`, refresh token family, login lockout columns |

---

## Tests

`tests/integration/auth/test_auth_security.py`:

- Successful login
- Invalid password
- Expired access token
- Refresh token rotation + reuse detection
- Permission denied
- Cross-company resource access blocked
- `X-Company-Id` header mismatch blocked

---

## Not in scope (deferred)

Employee, recruitment, payroll, attendance modules.

---

## Related docs

- [Auth Architecture](../security/Auth_Architecture.md)
- [SPRINT0 Foundation](../SPRINT0_FOUNDATION.md)
- Product spec: `files/10_Authentication_Architecture.md`, `files/19_RBAC_and_Permission_Matrix.md`
