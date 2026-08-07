# Sprint 0 — Architecture Foundation Complete

**Date:** 2026-08-03  
**Scope:** Repository + documentation for enterprise FastAPI development. **No HR business modules implemented.**

---

## 1. Files created

### `docs/` — developer architecture tree

| File | Purpose |
|------|---------|
| `docs/README.md` | Index and read order |
| `docs/architecture/00_Repository_Audit.md` | Part 1 — repo audit |
| `docs/architecture/01_Backend_Structure.md` | Part 2 — `apps/api` layout |
| `docs/architecture/02_Module_Standard.md` | Part 3 — module rules |
| `docs/architecture/03_System_Architecture.md` | Part 4 — system design + flows |
| `docs/architecture/04_Background_Job_Architecture.md` | Part 6 — Celery |
| `docs/database/Database_Architecture.md` | Part 5 — PostgreSQL strategy |
| `docs/security/Auth_Architecture.md` | Part 7 — auth/RBAC plan |
| `docs/development/FastAPI_Development_Standards.md` | Part 8 — coding standards |
| `docs/development/AI_Coding_Guidelines.md` | Part 9 — AI agent rules |
| `docs/adr/ADR-001-FastAPI-as-Core-Backend.md` | Sprint 0 ADR summary |
| `docs/adr/ADR-002-PostgreSQL-as-Primary-Database.md` | Sprint 0 ADR summary |
| `docs/adr/ADR-003-Modular-Monolith-Architecture.md` | Sprint 0 ADR summary |
| `docs/adr/ADR-004-AI-Service-Architecture.md` | Sprint 0 ADR summary |
| `docs/adr/ADR-005-Background-Job-Architecture.md` | Sprint 0 ADR summary |
| `docs/SPRINT0_FOUNDATION.md` | This summary |

### Code (minimal)

| File | Purpose |
|------|---------|
| `apps/api/src/hrms/main.py` | Entry alias for `create_app()` |

---

## 2. Files modified

| File | Change |
|------|--------|
| `docs/adr/README.md` | Index Sprint 0 ADRs + numbering guide |
| `README.md` | Link to `docs/README.md` |
| `files/27_Architecture_Migration_Summary.md` | Repo state (prior session) |

---

## 3. Files removed (prior cleanup)

| Item | Reason |
|------|--------|
| `apps/api-py/` | Empty duplicate scaffold |
| Root `node_modules/` | Stale NestJS workspace |
| Root `package-lock.json` | Stale lockfile |
| NestJS `apps/api` tree | Replaced by Python scaffold |

---

## 4. Remaining migration / foundation risks

| Risk | Mitigation | When |
|------|------------|------|
| No auth yet — endpoints are public | Block B1 identity module | Next sprint |
| Cross-tenant tests not in CI | `tests/security/` suite | B1 |
| Celery not in `npm run dev` | Optional script enhancement | B1 |
| `apps/api/env/` templates vs pydantic field names | Align templates | B1 |
| Golden payroll dataset not in repo | `tests/fixtures/payroll/` | Before B8 |
| OpenAPI contract snapshot CI | Add after auth stabilises | B1 |
| pgvector extension in Docker Postgres | Add to init script when AI lands | B9 |

---

## 5. Recommended next sprint — Block B1 (Auth & tenancy)

1. `core/auth/` — JWT issue/verify, refresh rotation, password hashing  
2. `modules/identity/` — login, logout, refresh, company list  
3. `scripts/seed.py` — permissions catalogue + demo company + admin user  
4. `apps/web` — login page + token handling  
5. `tests/security/` — cross-tenant leakage suite in CI  
6. Wire `Depends(get_current_user)` on all non-public routes  

**Do not start:** employee, leave, payroll, attendance modules until B1 demo works.

---

## 6. Document hierarchy

```text
files/     → WHAT to build (product spec, signed baseline)
docs/      → HOW to build (architecture for developers & AI agents)
docs/adr/  → WHY decisions were made
```

Both trees must stay aligned on stack: **FastAPI, SQLAlchemy, Alembic, Celery, PostgreSQL 16** — not NestJS, Prisma, or BullMQ.
