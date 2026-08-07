# ADR-0015: SQLAlchemy 2.x (Async) + Alembic, Replacing Prisma

**Status:** Accepted

## Context

Prisma was the ORM/migration tool under the original NestJS-based design (chosen for type safety
and migrations, with raw SQL as an escape hatch for payroll aggregation and reports — Doc 03 v1.0
§2.1). Prisma is a Node/TypeScript-specific tool and cannot come along under ADR-0013's move to
Python. The database itself — PostgreSQL 16, with heavy use of Row-Level Security, GiST exclusion
constraints for effective dating, JSONB, window functions, and monthly partitioning (Doc 08 §1) — is
unchanged and remains the deciding constraint on tooling: whatever replaces Prisma must handle a
schema this relationally complex without fighting the ORM.

## Decision

**SQLAlchemy 2.x in async mode** (`AsyncSession`, typed `Mapped[...]`/`mapped_column(...)` syntax),
with **`asyncpg`** as the driver and **Alembic** for migrations.

- SQLAlchemy Core is used directly (not hidden behind the ORM) for the payroll aggregation and
  reporting queries that needed raw SQL under Prisma too — this need doesn't go away with a new ORM,
  it's inherent to the query complexity, and SQLAlchemy Core gives it without leaving the same
  session/transaction management the ORM layer uses (Doc 08 §1.1).
- RLS policies, GiST exclusion constraints, and table partitioning are **not expressible in
  SQLAlchemy's model layer**, exactly as they were not expressible in Prisma's schema language
  either — both tools hit the same limitation for the same reason (neither is a general-purpose DDL
  language), and both are handled the same way: hand-written raw DDL in migrations, with a comment
  in the model file pointing at the migration that establishes the constraint (Doc 08 §1.1, §14).
  This is not a regression relative to Prisma; it's the same workaround under a different tool.

## Consequences

- **Positive:** SQLAlchemy 2.x's typed declarative syntax integrates with `mypy` the same way
  Prisma's generated client integrated with TypeScript's compiler — a meaningful fraction of the
  type-safety benefit is preserved, not lost, in the migration (Doc 04 §1.1).
- **Positive:** Alembic's autogenerate handles routine schema changes by diffing models against the
  live schema, the same practical workflow Prisma Migrate offered, with the same caveat (manual
  migrations for RLS/exclusion constraints/partitioning) both tools shared.
- **Negative — new failure mode:** async SQLAlchemy's session lifecycle introduces a bug class that
  did not exist under Prisma's generated-client model: lazy-loading a relationship after the owning
  session has closed raises `DetachedInstanceError`, typically surfacing during response
  serialisation rather than at the query site. This is mitigated by a hard rule (Doc 08 §15) —
  eager-load everything a response schema needs, never rely on implicit lazy loading across an
  `await` boundary outside the session's lifetime — enforced by the N+1 query-count assertion in
  integration tests (Doc 23 §1 NFR-P11) catching most violations mechanically.
- **Negative:** SQLAlchemy's session must be explicitly request-scoped via FastAPI's `Depends`
  (Doc 07 §2), whereas Prisma's client instance model made connection lifecycle less of an explicit
  concern for application code. This is a one-time architectural decision (Doc 08 §15), not an
  ongoing per-feature cost, once the pattern is established.

## Alternatives Considered

- **Tortoise ORM.** An async-native, Django-inspired ORM. Rejected: smaller ecosystem, less mature
  migration tooling than Alembic, and weaker support for the raw-SQL escape hatches this schema
  needs (payroll aggregation, reporting) relative to SQLAlchemy Core.
- **Raw `asyncpg` with hand-written SQL everywhere, no ORM.** Rejected: at 100+ tables, losing a
  declarative model layer entirely would mean hand-writing significantly more boilerplate CRUD SQL
  than SQLAlchemy's ORM layer provides "for free," with no offsetting benefit — the tables that
  genuinely need raw SQL (payroll aggregation, reports) already get it via SQLAlchemy Core without
  giving up the ORM for the other 90+ tables that don't need it.

## Related

- Depends on: ADR-0013 (Python/FastAPI backend)
- See: Document 08 (full data dictionary, SQLAlchemy model conventions §1.1, async session
  management §15), Document 06 §3.1 (module `models.py`/`repository.py` conventions)
