# ADR-0002: PostgreSQL With Row-Level Security for Multi-Tenancy

**Status:** Accepted

## Context

The platform is multi-tenant SaaS (Doc 03 A2): hundreds of companies' HR and payroll data share
infrastructure. A single missing `WHERE company_id = ?` in application code must not be able to
leak one tenant's employee or salary data to another — this is the single most damaging class of
bug this product can ship, both legally and reputationally (Doc 10). Relying on application-layer
filtering alone means every new query, every new developer, and every future refactor is a
potential leak, discoverable only by code review discipline.

## Decision

**Shared database, shared schema, `company_id` on every tenant-owned table**, enforced by
PostgreSQL Row-Level Security as a backstop behind the application-layer predicate:

```sql
ALTER TABLE employee ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON employee
  USING (company_id = current_setting('app.company_id')::uuid);
```

The application sets `SET LOCAL app.company_id = '<uuid>'` at the start of every request-scoped
transaction (Doc 03 §1 step 4). If a developer forgets the `WHERE` clause, RLS returns zero rows
instead of another tenant's data. Enterprise clients needing physical isolation get a dedicated
schema or database on the identical codebase (Doc 03 §3.2) — the connection-resolution strategy
changes, nothing else does.

## Consequences

- **Positive:** defence in depth — application predicate + RLS + a CI check that every new table
  has RLS enabled + an automated cross-tenant leakage test suite (Doc 13 §6.1). A single missed
  `WHERE` clause degrades from "data breach" to "test failure."
- **Positive:** one physical database to operate for the standard tier; standard backup/restore/
  monitoring tooling applies uniformly.
- **Negative:** RLS policies add a (small, measured) query planning cost and are easy to forget to
  enable on a new table — mitigated by a CI lint rule checking every new tenant table has RLS
  enabled before merge.
- **Negative:** debugging queries as an operator requires deliberately setting or bypassing the
  session variable — operational tooling must account for this explicitly (Doc 14 §8.3, the
  read-only data inspector).

## Alternatives Considered

- **Separate database per tenant from day one.** Rejected for the standard tier: hundreds of
  small databases multiply operational cost (migrations, connection pooling, monitoring) far past
  what an SME-priced PEPM plan supports. Retained as the enterprise/regulated tier option.
- **Application-layer filtering only, no RLS.** Rejected: no structural backstop — a single ORM
  query missing a scope filter is a live cross-tenant leak with no server-side safety net.
- **MongoDB or another document store.** Rejected in ADR-independent Doc 03 §2.3 discussion:
  no RLS equivalent, and payroll/attendance need transactional and constraint guarantees documents
  stores don't provide well.
