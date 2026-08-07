# HRMS — Developer Documentation (Sprint 0)

This folder is the **operational architecture guide** for building on the FastAPI backend.
The full product specification remains in [`files/`](../../files/00_README_Document_Index.md).

## Read order (new contributor or AI agent)

1. [Repository audit](architecture/00_Repository_Audit.md) — what exists today
2. [Backend structure](architecture/01_Backend_Structure.md) — `apps/api/src/hrms/`
3. [Module standard](architecture/02_Module_Standard.md) — how to add a module
4. [System architecture](architecture/03_System_Architecture.md) — deployables and flows
5. [Database architecture](database/Database_Architecture.md)
6. [Background jobs](architecture/04_Background_Job_Architecture.md)
7. [Auth architecture](security/Auth_Architecture.md)
8. [FastAPI standards](development/FastAPI_Development_Standards.md)
9. [AI coding guidelines](development/AI_Coding_Guidelines.md)
10. [ADRs](adr/README.md)
11. [UI design foundation](design/00_UI_Vision.md) — vision, design system, IA, navigation, personas (UI Sprint 0)

## Canonical paths

| Layer | Path |
|-------|------|
| Backend package | `apps/api/src/hrms/` |
| API entrypoint | `apps/api/entrypoints/api.py` |
| Migrations | `apps/api/alembic/` |
| Frontend | `apps/web/` |
| Design foundation | `docs/design/` |
| Product specs | `files/` |
| Architecture decisions | `docs/adr/` |

## Local start

```bash
npm run dev
```

See root [`README.md`](../../README.md).

## Sprint deliverables

- [Sprint 0 foundation](SPRINT0_FOUNDATION.md)
- [Sprint B1 identity & multi-tenant](SPRINT_B1_IDENTITY.md)
