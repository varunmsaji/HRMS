# Demo / Mock User Credentials (local dev seed)

Source of truth: [`apps/api/src/hrms/seed/constants.py`](../../apps/api/src/hrms/seed/constants.py) and [`apps/api/src/hrms/seed/bootstrap.py`](../../apps/api/src/hrms/seed/bootstrap.py).

Applied to the local dev database by running:

```bash
python apps/api/scripts/seed.py
```

This connects to the dev Postgres container (`hrms-postgres`, `localhost:5433`, db `hrms_dev`) and is idempotent — safe to re-run.

**Verified present in the running dev database as of 2026-09-04.**

---

## Users

| Field | Admin user | Viewer user |
|---|---|---|
| Email | `admin@example.com` | `viewer@example.com` |
| Password | `DemoPass123!` | `DemoPass123!` |
| User ID | `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` | `bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb` |
| Status | ACTIVE | ACTIVE |
| Role | `COMPANY_ADMIN` ("Company Administrator") — every permission in the catalogue, COMPANY-wide data scope | `EMPLOYEE_VIEWER` ("Employee Viewer") — only `EMPLOYEE.VIEW` |
| Company membership | **Demo Company A** (primary) + **Demo Company B** (secondary, no role/permissions granted there — see note below) | **Demo Company A** only (primary) |

**Note on the admin's Company B membership:** the seed links `admin@example.com` to Demo Company B via `UserCompany` (so it appears in the company switcher), but never grants a role there. Practical effect: logging in and switching to Demo Company B will authenticate fine but every permission check will fail (empty scope → 403) until a role is manually assigned for that company. Company A is where the admin account actually works.

## Companies

| Field | Company A | Company B |
|---|---|---|
| Name | Demo Company A | Demo Company B |
| ID | `11111111-1111-4111-8111-111111111111` | `22222222-2222-4222-8222-222222222222` |
| Status | ACTIVE | ACTIVE |

## Login

Use the standard login endpoint/UI with either email above and password `DemoPass123!`:

```
POST /auth/login
{
  "email": "admin@example.com",
  "password": "DemoPass123!"
}
```

Or via the web app at `/login`.

---

## Not part of this seed (found in the same dev DB, flagged for awareness)

The dev database also contains a self-registered tenant, `admin@acmedemocorp.io` (Company Admin role), plus a large number of `*.test.example` / `*.acme.example` accounts. These are **not mock/seed data** — they're real rows created by manual `/register` testing and by the automated test suite (which creates and, in most cases, tears down its own throwaway companies/users). Their passwords are not recoverable from the codebase since they were entered live, not hardcoded. If the test-suite leftovers are cluttering the dev DB, that's a separate cleanup task, not something this seed script manages.
