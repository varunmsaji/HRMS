# Document 06 — Folder Structure

**Version:** 2.0 — new document. The original Document 03 v1.0 gave a one-level sketch of the
NestJS `src/` tree (§4); at 500+ APIs, 100+ tables and 20+ modules, the structure needs to be
specified to a depth that removes ambiguity for both a human developer and an AI coding assistant
generating new modules — an unambiguous, mechanically-repeatable layout is what lets AI-assisted
development stay consistent across 20+ modules without a second reviewer catching drift
(Document 01 §2, Document 05). See [Document 07](07_Backend_Architecture.md) for what goes *inside*
each layer.

---

## 1. Repository Layout

```
hrms/
├── apps/
│   ├── api/                 # Backend monorepo root (this document covers this tree in depth)
│   ├── web/                 # Next.js 14 frontend (unchanged, Document 24)
│   └── mobile/               # React Native/Expo app (unchanged, Document 24)
├── infra/                    # Terraform, Docker Compose, Postgres init scripts (Document 13)
├── docs/
│   └── adr/                  # Architecture Decision Records
└── files/                    # This canonical spec document set
```

This document covers `apps/api/` — the Python backend monorepo, which itself contains the four
deployables described in Document 03 §1.1 as one installable package plus separate thin entrypoints.

---

## 2. `apps/api/` Top Level

```
apps/api/
├── pyproject.toml            # Single dependency manifest (uv), tool config (ruff, mypy, pytest)
├── uv.lock
├── alembic.ini
├── .importlinter              # Module boundary contracts (Document 07 §3)
├── Dockerfile                 # Multi-stage; same image builds api/worker/beat/ingestion (Document 13)
├── docker-compose.yml         # Local dev: postgres, redis, minio, api, worker, beat, ingestion
├── src/
│   └── hrms/                  # The installable package — see §3
├── alembic/
│   ├── env.py
│   └── versions/               # One file per migration (Document 08 §14)
├── tests/                      # Mirrors src/hrms/ (Document 15 §2)
├── scripts/                    # One-off/maintenance scripts (demo tenant generator, etc.)
└── entrypoints/
    ├── api.py                  # `uvicorn entrypoints.api:app`
    ├── ingestion.py             # `uvicorn entrypoints.ingestion:app` — mounts only ingest routes
    ├── worker.py                 # `celery -A entrypoints.worker worker`
    └── beat.py                    # `celery -A entrypoints.worker beat`
```

**Why entrypoints are separate from `src/hrms/`:** the four deployables (Document 03 §1.1) are thin
composition roots — each imports what it needs from the shared package and does nothing else. This
keeps "what does the ingestion process expose" answerable by reading one 20-line file, not by
tracing which routers happen to get registered.

---

## 3. `src/hrms/` — The Application Package

```
src/hrms/
├── __init__.py
├── core/                       # Framework-level concerns, imported freely by every module
│   ├── config/                  # Settings (pydantic-settings), per-environment config
│   ├── db/                      # Async engine/session factory, base declarative model, RLS session hook
│   ├── auth/                    # JWT issuance/verification, password hashing, MFA (Document 10)
│   ├── rbac/                    # Permission dependency, data-scope resolver (Document 19)
│   ├── tenancy/                  # Tenant context (contextvars), tenant middleware, connection resolver
│   ├── audit/                    # Audit dependency + Celery task, sensitive-access logging
│   ├── errors/                   # Exception hierarchy, FastAPI exception handlers (Document 09 §1.3)
│   ├── events/                    # Domain event base class, outbox writer (Document 07 §7)
│   ├── observability/             # OpenTelemetry setup, structured logging config
│   └── celery_app.py                # Celery application instance + shared task base class
│
├── shared/                      # Reusable domain-agnostic building blocks, imported freely
│   ├── value_objects/             # Money, DateRange, EffectivePeriod (Pydantic/dataclass, Document 07 §6)
│   ├── pagination.py               # Cursor + offset pagination helpers (Document 09 §1.5)
│   ├── files/                       # S3/MinIO client wrapper, presigned URL helpers
│   ├── notifications_client/         # Thin client used by modules to *request* a notification send
│   │                                  # (actual dispatch logic lives in modules/notification/)
│   └── testing/                      # Shared pytest fixtures, factory base classes (Document 15 §2)
│
├── modules/                     # One package per business module — the 20+ in Document 03 §1
│   ├── identity/
│   ├── organisation/
│   ├── employee/
│   ├── recruitment/
│   ├── attendance/
│   ├── leave/
│   ├── payroll/
│   ├── onboarding/
│   ├── exit/
│   ├── performance/
│   ├── workflow/
│   ├── notification/
│   ├── task/
│   ├── asset/
│   ├── expense/
│   ├── helpdesk/
│   ├── learning/
│   ├── visitor/
│   ├── experience/
│   ├── ai/                        # Resume parsing, matching, assistant, anomaly/attrition (Document 12)
│   ├── reporting/
│   └── integration/                # Device, accounting, calendar, messaging adapters (Document 22)
│
├── ingestion/                    # The device-ingestion-only route surface mounted by entrypoints/ingestion.py
│   └── routes.py                    # Imports modules/attendance's public service — nothing else
│
└── app.py                        # FastAPI app factory: registers routers, middleware, exception handlers
```

### 3.1 Anatomy of a Module (`modules/<name>/`)

Every module follows the **identical internal shape** — this uniformity is what makes the module
boundary rules in Document 07 §3 mechanically enforceable and what makes it realistic for an AI
coding assistant to generate a 21st module that looks like the other 20:

```
modules/leave/
├── __init__.py
├── router.py               # APIRouter; thin — parses request, calls service, returns response schema
├── schemas.py               # Pydantic request/response models (never the ORM model — Document 09 §1)
├── models.py                 # SQLAlchemy ORM models for this module's tables ONLY
├── repository.py              # Query layer — the only place raw SQLAlchemy Core/ORM queries live
├── service.py                  # Business logic; the module's PUBLIC interface other modules may call
├── exceptions.py                # Module-specific exception classes (subclass core.errors base)
├── events.py                     # Domain events this module emits/consumes (Document 07 §7)
├── tasks.py                       # Celery tasks owned by this module (accrual run, year-end process, …)
├── permissions.py                  # Permission codes this module defines (Document 19 §2)
└── dependencies.py                  # FastAPI Depends() specific to this module's routes
```

**The enforceable rule, restated precisely:** another module may `import hrms.modules.leave.service`
(specifically, only the functions/classes exported from `service.py`'s public surface) and
`hrms.modules.leave.events` (to subscribe) and `hrms.modules.leave.schemas` (to reuse a response
shape at an API boundary, e.g. embedding a leave summary in an employee 360° response). It may
**never** import `leave.repository`, `leave.models`, or call into `leave.router` directly. This is
encoded as an `import-linter` contract (Document 04 §1.1) — a violation fails CI, not code review.

### 3.2 Why `models.py` Is Singular, Not a `models/` Package, Below ~15 Tables

Modules whose table count stays under roughly 15 (most modules) keep one `models.py`. Payroll,
Employee and Attendance — the three modules with the largest table counts (Document 08 §5, §6, §8)
— use a `models/` package (`models/pay_run.py`, `models/payslip.py`, etc.) once a single file would
exceed roughly 400–500 lines. This is a readability threshold, not a boundary rule — the
import-linter contract treats `models.py` and `models/__init__.py` re-exports identically.

---

## 4. `tests/` — Mirrors `src/hrms/`

```
tests/
├── conftest.py                  # Root fixtures: async test client, test DB session, tenant factory
├── unit/
│   └── modules/leave/...          # Mirrors src/hrms/modules/leave/ exactly, one test file per source file
├── integration/                  # Real Postgres + Redis via Testcontainers (Document 15 §2)
│   └── modules/leave/...
├── security/                      # Cross-tenant leakage, permission matrix, data scope, field masking
│   └── ...                          # (Document 15 §6 — these run on every CI build, no exceptions)
└── e2e/                            # Playwright, drives the running stack end-to-end (Document 15 §5)
```

A source file `src/hrms/modules/leave/service.py` has its unit tests at
`tests/unit/modules/leave/test_service.py` — a 1:1, greppable mapping. This convention is enforced
by a CI check that flags any `service.py`/`router.py`/`repository.py` with no corresponding test
file, not just by convention (Document 15 §1).

---

## 5. Naming Conventions Specific to This Layout

| Item | Convention | Example |
|---|---|---|
| Module package name | `snake_case`, singular | `modules/leave/`, not `modules/leaves/` |
| Router variable | `router` (module-level, imported by `app.py`) | `from hrms.modules.leave.router import router as leave_router` |
| Service class | `<Module>Service`, one per module, instantiated via FastAPI `Depends` | `LeaveService` |
| Repository class | `<Module>Repository` | `LeaveRepository` |
| SQLAlchemy model class | `PascalCase`, singular, matches the DB table name (Document 08 header) | `class LeaveApplication(Base): __tablename__ = "leave_application"` |
| Pydantic schema classes | `<Entity><Purpose>` — `Create`, `Update`, `Read`, `ListItem` | `LeaveApplicationCreate`, `LeaveApplicationRead` |
| Celery task name | `<module>.<verb_noun>`, registered explicitly (never magic auto-discovery) | `leave.run_monthly_accrual` |
| Permission code | Unchanged from Document 19: `<MODULE>.<RESOURCE>.<ACTION>` | `LEAVE.APPLICATION.APPROVE` |
| Domain event class | `PascalCase`, past tense | `LeaveApproved` |

---

## 6. What This Structure Deliberately Does Not Do

- **No `utils/` grab-bag.** Anything reusable enough to live outside a module belongs in `shared/`
  with a name that says what it does (`shared/value_objects/money.py`), not in an undifferentiated
  `utils.py` that becomes unmaintainable at module #15.
- **No module imports another module's `models.py`, ever**, including for "just a read-only join" —
  that join goes through the owning module's `repository.py` and is exposed via `service.py` if
  another module genuinely needs it, or is denormalised into a materialised view (Document 08 §7)
  for reporting.
- **No business logic in `router.py`.** Routers parse, call one service method, and shape the
  response. This keeps the router layer thin enough that switching API frameworks (should that ever
  happen again) touches `router.py` files only, not business logic — the same insulation principle
  that made Document 08's data model and Document 09's API contracts stack-independent through this
  very migration.
