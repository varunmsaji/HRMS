# ADR-002: PostgreSQL as Primary Database

**Status:** Accepted  
**Date:** 2026-08-03  
**Related:** [0002-postgres-rls-multitenancy.md](0002-postgres-rls-multitenancy.md), [0015-sqlalchemy-alembic-orm.md](0015-sqlalchemy-alembic-orm.md)

## Context

HRMS requires transactional integrity, complex relational data (100+ tables), statutory payroll, effective-dated employment data, and tenant isolation at scale.

## Decision

**PostgreSQL 16** is the only primary datastore:

- SQLAlchemy 2.x async + asyncpg for application access
- Alembic for migrations
- RLS for tenant backstop
- JSONB for flexible attributes
- pgvector for AI embeddings
- Partitioning for high-volume punch/audit tables (as needed)

## Consequences

- **Positive:** RLS, exclusion constraints, window functions — fit payroll/attendance.
- **Positive:** Single DB for OLTP + embeddings (Phase 1).
- **Negative:** Hand-written SQL for RLS/constraints outside Alembic autogenerate.
- **Negative:** Not swappable to another engine without major rewrite (accepted).

## Alternatives rejected

- MongoDB / document primary store
- MySQL (weak RLS, weaker exclusion constraints)
- Per-tenant databases (ops overhead for solo operator)
