# Architecture Decision Records

Developer index: [`docs/README.md`](../README.md)  
Product architecture: `../product/03_System_Architecture.md`  
Migration closure: [`../product/27_Architecture_Migration_Summary.md`](../product/27_Architecture_Migration_Summary.md)

---

## ADRs (0001–0015)

| # | Title | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith over microservices for Phase 1 | Accepted (amended) |
| [0002](0002-postgres-rls-multitenancy.md) | PostgreSQL with RLS for multi-tenancy | Accepted |
| [0003](0003-effective-dated-modelling.md) | Effective-dated modelling for all employee attributes | Accepted |
| [0004](0004-leave-ledger.md) | Leave balance as an append-only ledger | Accepted |
| [0005](0005-payroll-snapshot-immutability.md) | Payroll inputs snapshotted; finalised runs immutable | Accepted |
| [0006](0006-money-as-integer-minor-units.md) | Money as integer minor units, never floats | Accepted |
| [0007](0007-separate-ingestion-service.md) | Separate ingestion service for biometric punches | Accepted |
| [0008](0008-generic-workflow-engine.md) | Workflow engine as a generic shared service | Accepted |
| [0009](0009-ai-non-blocking.md) | AI features are strictly non-blocking | Accepted |
| [0010](0010-utc-storage-company-timezone-render.md) | UTC storage, company-timezone rendering | Accepted |
| [0011](0011-statutory-rates-as-data.md) | Statutory rates as effective-dated data, never code | Accepted |
| [0012](0012-outbox-pattern.md) | Outbox pattern for domain events touching money or compliance | Accepted |
| [0013](0013-fastapi-python-backend.md) | Python 3.12 / FastAPI backend | Accepted |
| [0014](0014-celery-redis-job-queue.md) | Celery + Redis job queue | Accepted |
| [0015](0015-sqlalchemy-alembic-orm.md) | SQLAlchemy 2.x + Alembic | Accepted |

New numbered ADR: copy the closest existing file, increment, link here.
