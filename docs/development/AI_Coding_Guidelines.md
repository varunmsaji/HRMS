# AI Coding Guidelines

Rules for **human developers and AI agents** (Cursor, Claude Code, etc.) working on this repository.

---

## 1. Before writing code

1. **Read architecture docs** — start at [`docs/README.md`](../README.md).
2. **Read the product spec** for your module — `files/17` or `files/18`.
3. **Read data model** for your tables — `files/08` (relevant sections).
4. **Read API conventions** — `files/09`, RBAC — `files/19`.
5. **Check ADRs** — [`docs/adr/README.md`](../adr/README.md) — do not contradict accepted decisions.

---

## 2. Repository rules

| Rule | Detail |
|------|--------|
| Backend path | `apps/api/src/hrms/` **only** |
| No new top-level apps | No `api-py`, no NestJS, no duplicate packages |
| No new root folders | Without updating [Backend Structure](../architecture/01_Backend_Structure.md) + ADR |
| Module template | [Module Standard](../architecture/02_Module_Standard.md) — copy `health/` pattern |
| Do not duplicate services | Extend existing `service.py` or emit events |
| Reuse `core/` and `shared/` | Before adding helpers |

---

## 3. Implementation rules

| # | Rule |
|---|------|
| 1 | **Router thin** — one service call, no business logic |
| 2 | **Repository owns SQL** — tenant predicate on every query |
| 3 | **Schemas for API** — never return ORM models from routers |
| 4 | **Errors** — raise domain exceptions; handlers map to envelope |
| 5 | **Money** — `BIGINT` minor units, never `float` |
| 6 | **Tenancy** — `company_id` on tasks, sessions, repositories |
| 7 | **Idempotent jobs** — Celery tasks safe on retry |
| 8 | **No hard delete** — `deleted_at` pattern |
| 9 | **Effective dating** — close row + insert, not overwrite history |
| 10 | **Permissions** — `Depends(require_permission(...))` on every route |

---

## 4. Testing requirements

- Add tests in the same PR as `service.py` / `router.py` / `repository.py` changes.
- Payroll, RBAC, tenancy: tests are **mandatory**, not optional.
- Prefer `app.dependency_overrides` over monkeypatching internals.
- Name tests: `test_<behavior>_when_<condition>`.

---

## 5. Documentation updates

When you change architecture or conventions, update:

| Change type | Update |
|-------------|--------|
| New dependency / tool | `pyproject.toml` + ADR if significant |
| New module | This guide's module list in Backend Structure |
| New permission domain | `files/19` + module `permissions.py` |
| Schema change | Alembic + note in PR |
| API contract change | Ensure OpenAPI reflects change; flag breaking changes |

Do not edit `files/` casually — change control in `files/26`.

---

## 6. Explain architectural impact

In every PR or AI session summary, state:

- Which **module boundary** is touched
- Whether a **new cross-module import** was added (and why)
- Whether **data model** or **API contract** changed
- Whether **background jobs** or **outbox events** were added
- **Security impact** — tenancy, permissions, sensitive fields

---

## 7. Forbidden actions

- Introduce NestJS, Prisma, BullMQ, or Node backend dependencies
- Put business logic in `router.py` or `core/`
- Import another module's `models.py` or `repository.py`
- Skip migrations for schema changes
- Commit `.env`, secrets, or real credentials
- Implement HR business modules **before B1 auth** unless explicitly scoped

---

## 8. Recommended AI workflow

```text
1. User names module + requirement ID (e.g. FR-AUTH-001)
2. Agent reads docs/README.md + module SRS section
3. Agent lists files to create/modify (plan)
4. Agent implements one layer at a time: models → repository → service → router → tests
5. Agent runs: ruff, mypy, lint-imports, pytest
6. Human reviews tenancy + permission + test quality
```

---

## 9. Sprint boundaries

| Sprint | Build |
|--------|-------|
| **Sprint 0 (now)** | Architecture docs, scaffold, CI — **no HR modules** |
| **Sprint B1 next** | `identity`, `core/auth`, login API, web login page |
| **Sprint B2** | RBAC, organisation setup |

Do not jump to payroll/attendance until auth + RBAC foundations exist.

---

## 10. Quick links

- [FastAPI Development Standards](FastAPI_Development_Standards.md)
- [Module Standard](../architecture/02_Module_Standard.md)
- [Auth Architecture](../security/Auth_Architecture.md)
- Product index: `files/00_README_Document_Index.md`
