# Database Architecture

**Developer guide** — full data dictionary: `files/08_Database_Architecture.md` (100+ tables).

---

## 1. PostgreSQL strategy

| Decision | Rationale |
|----------|-----------|
| PostgreSQL 16 as sole primary store | RLS, JSONB, window functions, exclusion constraints, pgvector |
| Shared schema multi-tenant | Operational simplicity for solo/small team; `company_id` on tenant tables |
| Async SQLAlchemy + asyncpg | Fits FastAPI; connection pooling per worker process |
| Raw SQL where needed | Payroll aggregation, statutory reports — SQLAlchemy Core inside repositories |
| UTC storage | All `TIMESTAMPTZ`; company timezone for boundaries only (`files/03`, ADR-0010) |

Extensions (init): `pgcrypto`, `btree_gist`, `vector` (pgvector for AI embeddings).

---

## 2. Multi-tenancy & company isolation

| Layer | Mechanism |
|-------|-----------|
| Application | Every repository query filters `company_id` from `TenantContext` |
| Session | `set_config('app.company_id', uuid, true)` on each transaction |
| Database | `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` per tenant table |
| Policy | `company_id = current_setting('app.company_id')::uuid` |

**Cross-tenant access returns 404**, not 403 (`files/09` §1.4).

`company` table is the tenant root — no `company_id` on itself.

---

## 3. Row-Level Security (RLS)

- Enabled in Alembic migration via `scripts/sql/002_row_level_security.sql`.
- **Every new tenant table** must add RLS in the same migration or a follow-up SQL script.
- Tables without `company_id` (e.g. `role_permission`) rely on parent join + app predicates.

---

## 4. JSONB usage

| Use | Example |
|-----|---------|
| Tenant custom fields | `employee.custom_fields_json` |
| Theme / branding | `company.theme_json` |
| Workflow definition snapshots | Versioned JSON in workflow tables |
| AI feature payloads | Parsed resume structured output |

Not used for core payroll money or leave balances — those stay relational.

---

## 5. Effective-dated records

Pattern (`files/08` §1.2, ADR-0003):

- Child tables: `effective_from`, `effective_to` (NULL = current).
- `EXCLUDE USING gist` prevents overlapping periods per employee.
- Examples: `employee_assignment`, `employee_compensation`.

Application code never "updates history" — closes old row, inserts new row.

---

## 6. Audit tables

| Table | Purpose |
|-------|---------|
| `audit_log` | Append-only state changes (before/after JSON) |
| `sensitive_access_log` | RESTRICTED field reads |

No application `UPDATE`/`DELETE` on audit tables; DB role has no update grant on these tables in production.

---

## 7. Soft deletion

- Business entities: `deleted_at`, `deleted_by` — no hard delete from API.
- Physical delete only via retention job after legal hold period.
- Unique constraints often partial: `WHERE deleted_at IS NULL`.

---

## 8. Indexing strategy

| Pattern | Index |
|---------|-------|
| Tenant list queries | `(company_id, …)` composite |
| Effective dating | `(employee_id, effective_from)` |
| Punch / audit high volume | Partitioned tables + BRIN or time-range indexes (`files/08`) |
| Full-text / search | OpenSearch for employee search; pgvector for AI similarity |
| Foreign keys | Index on all FK columns used in joins |

Review every migration for lock time on large tables (`files/08` §14).

---

## 9. Migration strategy (Alembic)

| Rule | Detail |
|------|--------|
| Tool | Alembic only — **not** Prisma |
| Location | `apps/api/alembic/versions/` |
| Autogenerate | Routine column/table adds |
| Hand-written | RLS, policies, partitioning, exclusion constraints |
| Direction | Forward-only in production; expand-contract for destructive changes |
| Review | Lock behaviour, reversibility, payroll blackout window (`files/16` §2) |
| SQL assets | `apps/api/scripts/sql/` for reusable policy blocks |

Commands:

```bash
cd apps/api
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

---

## 10. ORM conventions

- Models live in `modules/<name>/models.py` only.
- Base: `core/db/base.py` (`Base`, `TimestampMixin`).
- UUID PKs: `gen_random_uuid()` default.
- Money: `BIGINT` minor units + `CHAR(3)` currency (ADR-0006).
- Relationships: explicit `lazy="raise"` on async models to avoid implicit IO in wrong context.

---

## 11. Related ADRs

- [ADR-002 PostgreSQL](../adr/ADR-002-PostgreSQL-as-Primary-Database.md)
- [ADR-0002 RLS](../adr/0002-postgres-rls-multitenancy.md)
- [ADR-0003 Effective dating](../adr/0003-effective-dated-modelling.md)
