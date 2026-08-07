# Backend Package Structure

**Canonical path:** `apps/api/src/hrms/`  
**Spec reference:** `files/06_Folder_Structure.md`, `files/07_Backend_Architecture.md`

---

## 1. Implemented layout (today)

```text
apps/api/
├── entrypoints/
│   ├── api.py              # uvicorn entrypoints.api:app  → port 8000
│   ├── ingestion.py        # Device punch ingestion surface
│   ├── worker.py           # celery -A entrypoints.worker worker
│   └── beat.py             # celery beat (same app as worker)
├── src/hrms/
│   ├── main.py             # Alias: create_app() for discoverability
│   ├── app.py              # FastAPI factory — middleware, routers, lifespan
│   ├── core/               # Platform (imported by all modules)
│   │   ├── config/         # pydantic-settings
│   │   ├── db/             # SQLAlchemy async engine, session, RLS hook
│   │   ├── tenancy/        # ContextVar + middleware
│   │   ├── errors/         # Exceptions + envelope handlers
│   │   ├── observability/  # structlog
│   │   ├── celery_app.py   # Celery application instance
│   │   ├── auth/           # (planned B1)
│   │   ├── rbac/           # (planned B2)
│   │   ├── audit/          # (planned B2)
│   │   └── events/         # (planned B4)
│   ├── shared/             # Reusable non-domain utilities
│   │   ├── pagination.py   # Response envelopes
│   │   └── value_objects/  # Money, DateRange
│   ├── modules/            # Business domains
│   │   └── health/         # Sprint 0 sample module
│   ├── ingestion/          # Routes mounted only on ingestion entrypoint
│   └── tests/              # Mirror under apps/api/tests/
├── alembic/                # Migrations (not inside src/hrms/)
└── scripts/sql/            # Hand-written SQL for RLS, constraints
```

---

## 2. Mapping — requested names vs implementation

Some guides use alternate folder names. **Use the implemented paths** in code.

| Requested (generic) | Implemented path | Notes |
|--------------------|-------------------|--------|
| `main.py` | `hrms/main.py` + `hrms/app.py` | Factory in `app.py`; `main.py` re-exports |
| `core/security` | `core/auth/` + `core/rbac/` | Security split per domain docs |
| `core/logging` | `core/observability/logging.py` | |
| `core/exceptions` | `core/errors/` | |
| `core/middleware` | `core/tenancy/middleware.py` + Starlette middleware in `app.py` | |
| `database/` | `core/db/` + `alembic/` at package root | Migrations live outside package by Alembic convention |
| `workers/` | `entrypoints/worker.py` + `modules/*/tasks.py` + `core/celery_app.py` | Tasks per module, not a monolithic workers tree |
| `organization/` | `modules/organisation/` | British spelling per `files/06` |
| `reports/` | `modules/reporting/` | Per spec module list |

---

## 3. Target module catalogue (not yet implemented)

Planned packages under `modules/` — **create only when building that block**:

| Module | Package | Phase |
|--------|---------|-------|
| Identity & auth | `identity/` | B1 |
| Organisation | `organisation/` | B2 |
| Employee | `employee/` | B3 |
| Recruitment | `recruitment/` | B9 |
| Attendance | `attendance/` | B6 |
| Leave | `leave/` | B7 |
| Payroll | `payroll/` | B8 |
| Onboarding | `onboarding/` | B10 |
| Exit | `exit/` | B10 |
| Workflow | `workflow/` | B4 |
| Notification | `notification/` | B5 |
| Reporting | `reporting/` | B12 |
| AI / ML | `ai/` | B9+ |
| Integration | `integration/` | B5+ |

Sub-packages like `identity/users` are **not used** — one module package with `models.py` / `repository.py` keeps import-linter contracts simple. Split to `models/` package only when a module exceeds ~15 tables (`files/06` §3.2).

---

## 4. Why this structure scales

| Requirement | How structure supports it |
|-------------|---------------------------|
| **500+ APIs** | One `router.py` per module; `app.py` registers routers; OpenAPI auto-generated |
| **100+ tables** | Table ownership per module `models.py`; cross-module access via `service.py` only |
| **Future multi-developer** | Module boundaries enforced by `import-linter` in CI |
| **AI-assisted development** | Repeatable module anatomy — AI generates `router/service/repository/schemas` from template |
| **Four deployables** | Thin `entrypoints/` — same wheel, different process command (ECS Fargate) |
| **AI in-process** | `modules/ai/` shares SQLAlchemy session and tenancy — no second HTTP service in Phase 1 |

---

## 5. Adding a new module (checklist)

1. Create `modules/<name>/` with files from [Module Standard](02_Module_Standard.md).
2. Register router in `app.py` under `/v1`.
3. Add import-linter allow-list if importing another module's `service.py`.
4. Add Alembic migration for new tables + RLS SQL in `scripts/sql/` if needed.
5. Mirror tests under `tests/unit/modules/<name>/`.
6. Do **not** add routes to `core/` or `shared/` for domain logic.
