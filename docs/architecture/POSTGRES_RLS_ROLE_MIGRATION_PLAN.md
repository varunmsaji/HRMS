# PostgreSQL RLS Role Migration Plan

**Date:** 2026-08-16
**Status:** Investigation complete. No application code, schema, role, or configuration change has
been made to produce this document — every claim below was independently verified this session
against the live dev database (`postgresql://hrms:***@localhost:5433/hrms_dev`) and the current
working tree.
**Triggering finding:** `EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` Finding F1 (P0) — the
application's PostgreSQL connection role is `SUPERUSER` + `BYPASSRLS`, making every RLS policy in
the schema a no-op for the app's own connection.
**Scope of this document:** the database-role transition only. It does not redesign the
application, does not touch RLS policies themselves, and does not start any new business module.

---

## 1. Current Database-Role Architecture

There is exactly **one** PostgreSQL role in this system today: `hrms`.

```
$ SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin,
         rolreplication, rolbypassrls FROM pg_roles WHERE rolname = 'hrms';

 rolname | rolsuper | rolinherit | rolcreaterole | rolcreatedb | rolcanlogin | rolreplication | rolbypassrls
---------+----------+------------+---------------+-------------+-------------+-----------------+--------------
 hrms    | t        | t          | t             | t           | t           | t               | t
```

`hrms` is the `POSTGRES_USER` from `docker-compose.yml`, which the official `postgres:16-alpine`
image always provisions as a full superuser. It:

- owns the `hrms_dev` database (`datdba = hrms`),
- is, by extension, the effective owner of the `public` schema (`pg_database_owner` in PG15+ is a
  pseudo-role representing whoever owns the current database),
- owns **all 32 tables**, all 224 pgcrypto/btree_gist extension functions, and (there are none) no
  sequences — every `id` primary key defaults to `gen_random_uuid()`, not a serial sequence,
- is used, unconditionally, by **every** consumer of `DATABASE_URL`: the FastAPI app
  (`hrms/core/db/session.py`), Alembic (`alembic/env.py`, same `settings.database_url`), the seed
  scripts (`scripts/seed.py`, `scripts/seed_plans.py`), and the entire test suite
  (`tests/conftest.py` hardcodes the identical `hrms` URL as its own default, independent of
  `.env`).

There is no migration role, no test role, and no distinction anywhere in the codebase between
"the role that runs DDL" and "the role that serves a live HTTP request." One role does everything.

**One pre-existing signal that a second role was always intended:** `apps/api/env/.env.staging.example`
and `apps/api/env/.env.qa.example` already reference a connection string of the shape
`postgresql://hrms_app:__FROM_SECRETS_MANAGER__@...` — i.e., a role named `hrms_app` is already the
documented target for staging/QA/production. **It was never created, and local dev/test never
adopted it.** This plan completes that pre-existing intent rather than inventing a new one.

---

## 2. Current Security Problem

Per Postgres semantics, a role with `rolbypassrls = true` (which every superuser has by default)
bypasses row security unconditionally, and `FORCE ROW LEVEL SECURITY` — confirmed set on all 19
tenant tables that carry a `tenant_isolation` policy (see §4) — does **not** change this; `FORCE`
only affects the table **owner** when the owner lacks `BYPASSRLS`, and only for non-superuser
owners. `hrms` is both the owner and a superuser, so it bypasses on both counts.

This was re-confirmed empirically this session (not just from role flags): with the schema's RLS
policies fully intact and `FORCE`d, a direct query as `hrms` with **no** `app.company_id` GUC set
at all still returns every row in a tenant table. Tenant isolation today is enforced **only** by
the explicit `WHERE company_id = ...` predicate each repository method adds by hand — RLS
contributes nothing.

## 3. All Objects Owned by the Current Application Role

Live query results this session:

| Object type | Count | Owner |
|---|---|---|
| Tables (`public`) | 32 | `hrms` (100%) |
| Sequences (`public`) | 0 | n/a — every PK is `gen_random_uuid()`, no `serial`/`identity` columns |
| Functions (`public`) | 224 | `hrms` — **all** are pgcrypto/btree_gist extension functions (`digest`, `crypt`, `gen_random_uuid`, `pgp_sym_encrypt`, the `gbt_*` GiST support functions, etc.). **Zero application-defined functions or triggers exist.** |
| Database `hrms_dev` | 1 | `hrms` |
| Schema `public` | — | owned by `pg_database_owner` (i.e., effectively `hrms`); `public`'s access-privilege list already grants bare `USAGE` (not `CREATE`) to `PUBLIC` — the PG15+ default |
| Extensions | 3 | `pgcrypto`, `btree_gist`, `plpgsql` — all pre-installed, `gen_random_uuid()` already has `EXECUTE` granted to `PUBLIC` by pgcrypto's own install-time default |

RLS status, live query (`relrowsecurity` / `relforcerowsecurity`):

- **19 tables** carry a real `tenant_isolation` policy, `ENABLE`+`FORCE`d:
  `audit_log, branch, company_feature_flag, company_setup_progress, department, designation,
  employee, employee_assignment, employee_bank, employee_compensation, employee_statutory,
  employment, grade, holiday_calendar, legal_entity, number_series, role, shift, subscription,
  user_company`. Every policy is byte-identical:
  `(company_id = (current_setting('app.company_id'::text, true))::uuid)`, `cmd = ALL`.
- `company` has `relforcerowsecurity = t` but `relrowsecurity = f` (RLS not enabled) and **no**
  policy — correct and intentional: `company` is the tenant root, it has no `company_id` column to
  scope by. The `FORCE` flag with `ENABLE` off is inert either way; not a bug, not touched by this
  plan.
- **10 tables have no RLS at all** and correctly so: `_prisma_migrations`, `alembic_version`,
  `holiday` (scoped indirectly via `holiday_calendar`, which does carry RLS), `permission` (global
  catalog), `plan`/`plan_feature` (global catalog), `refresh_token`, `session`, `user` (global —
  scoped via `user_company`), `user_role`, `role_permission` (join tables scoped transitively
  through `role`, which does carry RLS).

This matches `HRMS_SYSTEM_DESIGN_BASELINE.md §1.6`'s description of the mechanism exactly — the
policies themselves are not in question. What is in question is that no non-owner, non-superuser
role has ever connected through them.

## 4. Required Application Privileges

The application (through the FastAPI process) needs, and only needs:

- `CONNECT` on `hrms_dev` (implicit for any login role that can authenticate)
- `USAGE` on schema `public` (already granted to `PUBLIC` by default — no explicit grant strictly
  required, but will be granted explicitly for clarity and to not depend on an unpinned default)
- `SELECT, INSERT, UPDATE, DELETE` on all 32 tables in `public` — confirmed by reading every
  repository method: the app only ever does DML, never DDL, never `TRUNCATE`
  (grepped `TRUNCATE|ALTER ROLE|SET ROLE|CREATE ROLE|GRANT |ALTER DEFAULT PRIVILEGES` across
  `src/` and `tests/` — zero hits)
- `EXECUTE` on `gen_random_uuid()` (already `PUBLIC`-granted; no action needed) — no other
  extension function is called at runtime (grepped for every pgcrypto primitive used in
  `INSERT ... DEFAULT` paths; only `gen_random_uuid()` appears in any column default)
- No sequence grants (none exist)
- No `TRUNCATE`, `REFERENCES`, `TRIGGER`, or DDL privilege of any kind

## 5. Required Migration Privileges

Alembic (`alembic/env.py`) issues raw DDL every migration: `CREATE TABLE`, `ALTER TABLE`,
`CREATE INDEX`, `CREATE EXTENSION IF NOT EXISTS`, and — critically — `ENABLE ROW LEVEL SECURITY` /
`FORCE ROW LEVEL SECURITY` / `DROP POLICY IF EXISTS` / `CREATE POLICY`, re-asserted idempotently in
every migration that touches an RLS-protected table (`HRMS_SYSTEM_DESIGN_BASELINE.md §1.6`,
confirmed live). Setting a table's RLS policy requires the table **owner** (or superuser).
Migrations therefore need to keep running as the schema **owner** — that role must remain `hrms`,
unchanged. This is exactly the case the task's own instructions anticipate: *"the migration role
may legitimately have stronger privileges if required, but application runtime credentials must
never inherit them."*

## 6. Required Test Privileges

The test suite does not use a role of its own today — it hardcodes the same `hrms` URL
`tests/conftest.py` uses as its own default (`os.environ.setdefault(...)`, independent of `.env`).
Critically, **26 test files** call `hrms.core.db.session.get_session_factory()` directly for
fixture setup/teardown (seeding `Plan` rows, deleting a test company's leftover `employee`/
`number_series` rows, etc. — e.g. `tests/integration/modules/employee/test_employee.py:
_cleanup_employees`) and **none of these raw sessions ever call `set_rls_company_id`** before
issuing their `DELETE`/`INSERT`. They rely entirely on `hrms`'s current `BYPASSRLS` to freely
read/write across tenants for test bookkeeping, even though every such statement already carries
an explicit `WHERE company_id = :cid` predicate.

If the *default* test role loses `BYPASSRLS`, all 26 of these files would need their raw session
blocks updated to `SELECT set_config('app.company_id', :cid, true)` before every cross-tenant
fixture operation, or every such `DELETE` silently affects zero rows — this is a real, large,
non-trivial refactor with meaningful regression risk on top of the test suite's **already-confirmed
non-deterministic** state (Finding F6). §8/§13 below explain why this plan does not do that refactor
and what it does instead.

## 7. Proposed Role Architecture

Three roles, two of which already exist in name only (documented, never created) or exist today
under an overloaded identity:

| Role | Login | `SUPERUSER` | `BYPASSRLS` | `CREATEDB`/`CREATEROLE` | Purpose |
|---|---|---|---|---|---|
| `hrms` (existing, **unchanged**) | yes | yes (unchanged) | yes (unchanged) | yes (unchanged) | Schema owner. Runs Alembic migrations, `scripts/seed*.py`, and remains the role the existing 290+-test suite's raw fixture/cleanup helpers connect through. **Never used to serve live application traffic after this change.** |
| `hrms_app` (**new**) | yes | **no** | **no** | **no** | The application runtime role. This is what `DATABASE_URL` resolves to for the FastAPI process in dev/staging/prod, and what the new RLS-proof security tests connect through. Holds only `SELECT/INSERT/UPDATE/DELETE` on the 32 tables + `USAGE` on `public`. |
| *(test role)* | — | — | — | — | **No new role.** The existing test suite keeps using `hrms` for the reasons in §6/§13. A dedicated, disposable `hrms_app`-scoped connection is used only inside the new RLS-verification tests, via `DATABASE_URL` env-var override + engine disposal (§13) — not a separate Postgres role. |

This is a deliberately **minimal** separation, not a full three-role system, because the codebase's
own test-fixture pattern (§6) makes a wholesale test-role swap disproportionately risky for a task
whose actual requirement is the *runtime* role. `hrms` keeps doing double duty as
migration-role-and-fixture-role; that duty is now explicitly documented and bounded (§21) rather
than accidental.

## 8. Role Separation Strategy

- **Ownership never moves.** `hrms` remains the owner of the database, schema, and all 32 tables.
  `hrms_app` is granted privileges on those objects; it does not own anything. This means `hrms_app`
  is subject to every `tenant_isolation` policy unconditionally — a non-owner, non-superuser,
  non-`BYPASSRLS` role has no path around RLS regardless of `FORCE`, so `FORCE ROW LEVEL SECURITY`
  does not even need to be relied upon for `hrms_app` (it matters only for `hrms`, if `hrms` ever
  lost `BYPASSRLS` — out of scope here, see §21).
- **`ALTER DEFAULT PRIVILEGES FOR ROLE hrms IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON
  TABLES TO hrms_app`** is set once, so every table any *future* migration creates (Attendance,
  Leave, Payroll — out of scope to build, but their migrations will run under `hrms` and should not
  each require a manual re-grant) is automatically visible to `hrms_app` without this plan being
  re-run.
- **Migrations keep running as `hrms`.** No change to who runs `alembic upgrade head` locally; only
  the connection string used is renamed (see §11).

## 9. Development Environment Strategy

- `docker-compose.yml`'s `postgres` service is unchanged (still provisions `hrms` as
  `POSTGRES_USER`, which Postgres always makes a superuser — that's fine, `hrms` keeps its admin
  role).
- A new idempotent SQL file, `infra/docker/postgres/init/002_app_role.sql`, creates `hrms_app` with
  a fixed local-dev-only password (following this repo's existing convention of a committed,
  clearly-local placeholder password, same as `hrms_dev_password` already in `docker-compose.yml`
  and `.env`) and grants it the privileges from §4. This file only runs automatically against a
  **fresh** `postgres_data` volume (Postgres only executes `/docker-entrypoint-initdb.d/*.sql` on
  first initialization) — so it also gets applied manually once against the current, already-
  initialized dev volume (§19, step 2).
- `apps/api/.env`'s `DATABASE_URL` is repointed at `hrms_app`. A new `MIGRATIONS_DATABASE_URL` is
  added, pointing at `hrms` — this is what Alembic will read (§11).
- `tests/conftest.py` is **not** changed — it keeps its own hardcoded `hrms` default, which is
  correct per §6/§13.

## 10. Production Environment Strategy

Out of this repository's direct control (no live production infrastructure exists yet — confirmed,
`docs/architecture/00_HRMS_SYSTEM_ARCHITECTURE.md` and the `.env.production.example` both describe
AWS ECS + RDS + Secrets Manager as the target, not yet provisioned). This plan aligns the
**local/dev** posture with what `.env.staging.example`/`.env.qa.example` already specify, so that
whenever staging/production infrastructure is actually provisioned:

- The RDS master user plays the role `hrms` plays here (schema owner, migration runner) and is
  **never** the value injected as the app's own `DATABASE_URL` secret.
- A dedicated `hrms_app` Postgres role (non-superuser, non-`BYPASSRLS`, DML-only — identical
  privilege set to dev) is created once per environment (via the same SQL in §9, run by an operator
  through the RDS master user) and its credential is what Secrets Manager injects as `DATABASE_URL`
  for the ECS task.
- A separate `MIGRATIONS_DATABASE_URL` secret (RDS master user, or an equivalent migration-only
  role) is what the deploy pipeline's `alembic upgrade head` step uses — never the ECS task's own
  runtime secret.
- This plan does not create any AWS resource, RDS user, or Secrets Manager entry — there is nothing
  live to change. It documents the pattern so provisioning follows it correctly on day one.

## 11. Migration/Alembic Strategy

`alembic/env.py` currently derives its connection string from `settings.database_url` — the exact
same field the app uses. This is the one place migrations and app-runtime credentials are currently
fused; decoupling it is the core of this plan's code change:

```python
# before
settings = get_settings()
sync_url = settings.database_url.replace("+asyncpg", "+psycopg")

# after
settings = get_settings()
db_url = os.environ.get("MIGRATIONS_DATABASE_URL") or settings.database_url
if "?schema=" in db_url:
    db_url = db_url.split("?", 1)[0]
if db_url.startswith("postgresql+asyncpg://"):
    sync_url = db_url.replace("+asyncpg", "+psycopg")
elif db_url.startswith("postgresql://"):
    sync_url = "postgresql+psycopg://" + db_url[len("postgresql://") :]
else:
    sync_url = db_url
```

`MIGRATIONS_DATABASE_URL` is read directly from the OS environment (not via the pydantic `Settings`
class — deliberately, so the app's own `Settings` model, which is what gets validated/logged/
injected into every request-serving process, never gains a field that could leak the admin
connection string into app-side code paths). If `MIGRATIONS_DATABASE_URL` is unset, Alembic falls
back to `settings.database_url` exactly as today — so any environment that doesn't yet set the new
variable keeps working unchanged, it just runs migrations with whatever role `DATABASE_URL` points
to (which, after this change, will usually be `hrms_app` unless the operator also sets
`MIGRATIONS_DATABASE_URL` — see §14 failure scenarios for why this fallback direction is safe but
non-functional, not silently insecure: `hrms_app` simply lacks DDL rights and the migration fails
loudly).

`.env`/`.env.*.example` gain `MIGRATIONS_DATABASE_URL="postgresql://hrms:...@.../hrms_dev"` (dev)
or the RDS-master equivalent (staging/QA/prod examples).

## 12. Docker Strategy

- `docker-compose.yml` itself needs no change — `hrms` stays the container's bootstrap superuser,
  which is what creates `hrms_app` in the first place.
- `infra/docker/postgres/init/002_app_role.sql` is added alongside the existing
  `001_extensions.sql`, run in filename order on first container init, so a brand-new contributor
  running `docker compose up` from a clean checkout gets `hrms_app` automatically with no manual
  step.
- The currently-running dev container (`hrms-postgres`, existing `postgres_data` volume) will not
  re-run init scripts — §19 includes the one-time manual `psql` step to apply the same SQL to it.

## 13. CI/Test Strategy

No CI workflow file exists in this repository today (grepped `.github/workflows`, none found) — so
"CI strategy" here means: what a future CI pipeline should do, and what the test suite does right
now.

- **The existing 290+ tests keep running exactly as today**, against `hrms`, with zero file changes.
  This is a deliberate, documented trade-off (§6, §21): `hrms` is doing double duty as both the
  migration role and the test-fixture role. It is *not* the production runtime role, so this does
  not reintroduce F1 — it only means the bulk of the test suite continues to validate business logic
  without also re-proving RLS enforcement on every run (that was never what those tests were
  checking; conflating "business logic is correct" with "RLS is enforced" is exactly the trap F1
  fell into originally).
- **A new, small, dedicated test module** (`tests/security/test_rls_runtime_role.py`) is added
  which, for its own test functions only, uses `monkeypatch.setenv("DATABASE_URL", <hrms_app URL>)`
  + `get_settings.cache_clear()` + `await dispose_engine()` before running, and relies on the
  existing autouse `reset_db_engine` fixture (already present in `tests/conftest.py`) plus
  `monkeypatch`'s automatic env-var restoration to clean up afterward. This is the **only** place
  the actual restricted runtime role is exercised in the test suite, and it is exactly the role the
  real application uses — see §14 (RLS verification strategy) for what it proves.
- **Future CI** should run `alembic upgrade head` with `MIGRATIONS_DATABASE_URL` set to the
  admin/migration role, then run the app/tests with `DATABASE_URL` set to `hrms_app` only for the
  new RLS-specific module (or, if CI wants the full suite to also run under `hrms_app` eventually,
  that requires first doing the 26-file fixture refactor flagged as future work in §21 — explicitly
  not part of this task).

## 14. RLS Verification Strategy

Verification happens at three independent levels, because "the app works" and "RLS is enforced" are
different claims (this is the exact conflation F1 warns against repeating):

1. **Role-attribute proof** — raw query against `pg_roles` through a connection authenticated *as*
   `hrms_app`, asserting `rolsuper = false` and `rolbypassrls = false` for `current_user`. Proves
   the role itself is correctly shaped.
2. **Database-level proof, bypassing the application entirely** — a raw SQL session connected as
   `hrms_app`, with `app.company_id` GUC set to Company A, attempting a direct `SELECT`/`INSERT`/
   `UPDATE`/`DELETE` against a Company B row **without going through any repository or `WHERE
   company_id` clause**. If Postgres itself returns zero rows / rejects the write, that is proof the
   *policy*, not app code, is the enforcement layer. This is the test that F1 could never have
   passed under the old role, since `BYPASSRLS` would have made every one of these operations
   succeed regardless of the GUC.
3. **Application-level proof** — real HTTP requests through the ASGI app (`ASGITransport`, the same
   mechanism every existing integration test already uses), with the app's own engine pointed at
   `hrms_app`, exercising registration, Employee CRUD across all six sub-resources, RBAC
   SELF/REPORTEES scope, termination, and audit-log writes end-to-end. Proves the *combination* of
   correct GUC-timing (§16) and the new role's grants doesn't regress any real feature.

## 15. Rollback Strategy

Every step is independently reversible without data loss:

- **Application rollback**: revert `apps/api/.env`'s `DATABASE_URL` to the `hrms` connection string
  (one line). The app immediately returns to today's behavior (superuser, RLS inert). `hrms_app` can
  be left in place harmlessly — an unused role with no login activity is not a regression.
- **Code rollback**: the `alembic/env.py` change is purely additive (new optional env var with a
  safe fallback) — reverting the single `get_tenant_context` GUC-timing fix (§16) and the env.py
  change is a plain `git revert` with no migration required.
- **Role rollback**: `DROP ROLE hrms_app` (only possible after revoking its grants / after no
  session holds it) fully undoes the database-side change. Nothing else references `hrms_app` by
  object ownership (it owns nothing), so this is a clean, no-cascade removal.
- **No migration is required in either direction** — this entire change is role/grant/config, not
  schema. `alembic downgrade` is never invoked as part of this rollback path.

## 16. Failure Scenarios

This is the section the task explicitly warns not to skip: *"do not assume removing `BYPASSRLS`
will make the current policies work."* Investigation this session found one concrete, real gap:

**GUC-timing gap in `get_tenant_context` / `get_session` (confirmed by reading
`hrms/core/tenancy/dependencies.py` and `hrms/core/db/session.py`).** `get_session()` (the FastAPI
dependency that yields the request's `AsyncSession`) sets the `app.company_id` GUC from
`current_tenant_company_id()` — a `ContextVar` — **at session-creation time**. But
`get_tenant_context` declares `session: Depends(get_session)` as its own sub-dependency, which
FastAPI resolves (and therefore triggers `get_session()`'s body, including the GUC-set) **before**
`get_tenant_context`'s own body runs. `get_tenant_context`'s body is what calls `set_tenant(ctx)`
with the *verified* company (validated against the JWT + an active `UserCompany` membership row) —
but by then the session already exists and its GUC was already set from whatever the ContextVar held
at that earlier moment, which is either:
- the **unverified** value `TenancyMiddleware` set from the raw `X-Company-Id` header (no membership
  check yet) — in this codebase's actual traffic, this always equals the verified value, because a
  header that disagrees with the JWT is rejected with `404` before any endpoint logic runs, and the
  frontend/every test always sends a header that matches the JWT — so this specific sub-case is
  currently benign; **or**
- **nothing at all**, if the request omitted `X-Company-Id` (the header is optional at the type
  level: `Header(alias="X-Company-Id") | None = None`). In that case
  `current_tenant_company_id()` returns `None`, `set_rls_company_id` no-ops (`if company_id is
  None: return`), and the session's GUC is **never set** for the rest of the request — meaning
  `current_setting('app.company_id', true)` evaluates `NULL` and the `tenant_isolation` policy
  (`company_id = NULL`) is never true. **Every query on that session would return zero rows the
  moment `BYPASSRLS` is removed** — not a security hole, but a hard functional break, exactly the
  outcome the task's "APPLICATION WHERE company_id = X → NO DATABASE BACKSTOP... not what we want"
  diagram warns about in the opposite direction (here it would become "backstop blocks everything").

Confirmed this sub-case is **currently unreachable** in practice: the frontend client
(`apps/web/src/lib/api/client.ts:46`) unconditionally attaches `X-Company-Id`, and all 40+ existing
integration tests that hit tenant-scoped routes send it too (grepped, zero counter-examples). But
"currently unreachable" is exactly F2/F3's own shape (a real gap masked only by nobody exercising
the path yet) — the task's instructions are explicit that this must be identified and fixed before,
not discovered by, flipping `BYPASSRLS` off.

**Fix (§16, applied in Phase 2, see implementation report):** `get_tenant_context` calls
`set_rls_company_id(session, str(ctx.company_id))` explicitly, using the *verified* `ctx`, as its
last step before returning — the same pattern `organisation/service.py:178`'s `register_company`
already uses (set the GUC explicitly, right after the authoritative company id is known, rather than
relying on the ContextVar's state at an earlier point in the dependency graph). Every route in the
app declares `tenant: Depends(get_tenant_context)` as its first parameter and every other tenant-
scoped dependency (`require_permission`, the various `get_*_service` functions) resolves afterward
and shares the same cached session — so this one change guarantees the GUC is correct for 100% of
actual business-logic queries, regardless of whether `X-Company-Id` was sent. (The one query that
happens *inside* `get_tenant_context` before this fix — the `UserCompany` membership lookup — already
carries its own explicit `company_id` filter per `IdentityRepository.get_user_company`, so it is
correct independent of the GUC either way; this is the same "belt and suspenders" pattern the design
baseline documents as the norm.)

**Other failure scenarios considered and ruled out:**
- *Background workers / async jobs (Celery)*: the only existing task (`health.ping`) touches no
  database at all. `session_scope()` (the non-FastAPI session context manager used outside request
  handling) already takes an explicit `company_id` parameter and sets the GUC **before** yielding
  the session — it does not have the timing bug `get_session()`/`get_tenant_context` had. No fix
  needed here; flagged as N/A rather than silently assumed safe.
- *Seed/bootstrap scripts* (`scripts/seed.py`, `scripts/seed_plans.py`): insert data directly with
  explicit `company_id` values and no reliance on RLS; they will continue running as `hrms` (see
  §5/§9), unaffected.

## 17. Security Considerations

- Removing `BYPASSRLS`/`SUPERUSER` from the runtime connection is a strict security improvement
  with no new attack surface introduced: `hrms_app` cannot create roles, cannot create databases,
  cannot replicate, cannot alter other roles' privileges, and cannot bypass RLS for any table it
  doesn't own (it owns nothing).
- `hrms` (unchanged, still superuser) is not exposed to the network any differently than today — it
  was already the sole credential in `.env`/`docker-compose.yml`. This plan does not widen its
  exposure; it narrows what the *application process specifically* authenticates as.
- The local-dev password chosen for `hrms_app` follows the existing repo convention (a
  clearly-fake, already-committed local-only placeholder, same posture as `hrms_dev_password`) — not
  a real secret, consistent with `.env` already being a local-dev file, never a production secret
  source (confirmed by `.env.production.example`'s explicit "production NEVER reads a .env file from
  disk" comment).
- No credential of any kind is written to a migration file, a test file, or a log statement as part
  of this plan.

## 18. Compatibility Risks

| Risk | Assessment |
|---|---|
| A repository method relies on an implicit superuser behavior (e.g., unfiltered `SELECT` expecting RLS to have already narrowed it) | **Ruled out** — every repository method reads explicitly filters by `company_id`; RLS was already documented and re-verified as "belt and suspenders," never the sole filter (`HRMS_SYSTEM_DESIGN_BASELINE.md §1.6`, `§14`) |
| A migration needs to run as the app role | **Ruled out** — Alembic is fully decoupled via `MIGRATIONS_DATABASE_URL` (§11); no migration ever runs as `hrms_app` |
| A test fixture needs cross-tenant access under the new role | **Identified and scoped out deliberately** (§6/§13) — the 290+ existing tests keep using `hrms`; only the new RLS-specific module uses `hrms_app`, by design |
| GUC not set when a query runs | **Identified and fixed** (§16) — the `get_tenant_context` ordering gap |
| A future migration creates a table and forgets to grant it to `hrms_app` | **Mitigated** via `ALTER DEFAULT PRIVILEGES` (§8) — grants are automatic for any table `hrms` creates going forward |
| Local `psql`/DBA tooling scripts elsewhere in the repo assume `hrms` as the only role | Grepped `psql`, `PGPASSWORD`, `DATABASE_URL` across `scripts/`, `infra/`, docs — no other script references a hardcoded connection string besides `scripts/seed.py`/`scripts/seed_plans.py`, both intentionally left on `hrms` (§5) |

## 19. Exact Implementation Sequence

1. Write `infra/docker/postgres/init/002_app_role.sql` (idempotent — `DO $$ ... IF NOT EXISTS`
   guard around `CREATE ROLE`) creating `hrms_app` and granting the §4 privilege set +
   `ALTER DEFAULT PRIVILEGES`.
2. Apply the same SQL manually, once, against the live `hrms-postgres` container (`psql ... -f
   002_app_role.sql`), since its data volume already exists and won't re-run init scripts.
3. Fix the GUC-timing gap in `hrms/core/tenancy/dependencies.py::get_tenant_context` (§16).
4. Update `alembic/env.py` to read `MIGRATIONS_DATABASE_URL` with fallback (§11).
5. Update `apps/api/.env` (and `.env.example`, `.env.dev.example`) — `DATABASE_URL` → `hrms_app`,
   add `MIGRATIONS_DATABASE_URL` → `hrms`.
6. Update `.env.staging.example`/`.env.qa.example`/`.env.production.example` to also document
   `MIGRATIONS_DATABASE_URL` alongside the already-present `hrms_app`-based `DATABASE_URL`.
7. Run `alembic upgrade head` using `MIGRATIONS_DATABASE_URL` (as `hrms`) against the live dev DB —
   expect no-op (already at head) — proves the migration path still works end-to-end through the new
   variable.
8. Boot the API locally with the new `.env` and smoke-test one real request end-to-end.
9. Add `tests/security/test_rls_runtime_role.py` (§13/§14).
10. Run the new test module in isolation; then the full backend suite; then repeat the full suite
    (per F6, to characterize determinism — see implementation report); then `ruff`, `mypy`,
    `lint-imports`.
11. Write `POSTGRES_RLS_ROLE_IMPLEMENTATION_REPORT.md` with full before/after evidence.

## 20. Verification Checklist

- [ ] `hrms_app` role exists, `rolsuper = false`, `rolbypassrls = false`, `rolcreatedb = false`,
      `rolcreaterole = false`
- [ ] `hrms` role unchanged (still owner, still superuser — confirms no accidental privilege loss
      on the migration path)
- [ ] `hrms_app` can `SELECT/INSERT/UPDATE/DELETE` its own company's rows on all 19 RLS-protected
      tables through the real app
- [ ] `hrms_app` cannot read/insert/update/delete another company's row, proven via a **raw**
      connection (not through app WHERE-clause filtering)
- [ ] `alembic upgrade head` succeeds using `MIGRATIONS_DATABASE_URL` (as `hrms`)
- [ ] `alembic downgrade -1` / `upgrade head` round-trip succeeds where safe
- [ ] Full application registration → employee lifecycle → termination flow succeeds end-to-end
      against `hrms_app`
- [ ] RBAC SELF/REPORTEES/REPORTEE_TREE scope resolution still correct under `hrms_app`
- [ ] Audit log rows are still written under `hrms_app`
- [ ] Existing 290+ test suite still passes against `hrms` (unchanged baseline, re-run for
      determinism per F6)
- [ ] `ruff check`, `ruff format --check`, `mypy`, `lint-imports` all pass
- [ ] No credential appears in any committed file, log, or test output

## 21. Explicit Things That Must NOT Change

- The `tenant_isolation` policy definition, or its presence/`FORCE` status on any of the 19 tables —
  not touched, not redefined, not dropped-and-recreated with different semantics.
- `hrms`'s own role attributes — it stays superuser/owner; this plan does not attempt to also harden
  the admin role (a real, separately-worth-doing idea, explicitly deferred — see recommendation).
- The 290+ existing tests' fixture code — zero files under `tests/integration/` or
  `tests/security/` (other than the one new file) are modified.
- Business logic, schemas, permissions, or response shapes in the Employee/Organisation/RBAC
  modules — the only application code touched is the one-line GUC fix in `get_tenant_context`.
- Any RLS policy text, `ENABLE`/`FORCE` flags, or migration history.

## 22. Recommendation

Proceed with the plan as scoped: create `hrms_app`, decouple Alembic's connection via
`MIGRATIONS_DATABASE_URL`, fix the `get_tenant_context` GUC-timing gap, and add the dedicated
RLS-proof test module — without touching the 26-file test-fixture pattern or `hrms`'s own
privileges. This closes F1 for the only connection that actually matters (the one serving live
traffic) with the smallest change that is still honestly verifiable at the database level, not just
at the "the app still boots" level.

**Deferred, not forgotten (candidates for a future, separate task):**
- Retrofit the 26 raw-fixture test files to set the RLS GUC explicitly, so the *entire* test suite
  can eventually run under `hrms_app` instead of only the dedicated module — real work, real value,
  not this task's blast radius.
- Consider whether `hrms` itself should shed `CREATEROLE`/`CREATEDB`/`REPLICATION` (none of which
  migrations or seed scripts use) — a legitimate further hardening step, independent of the F1
  runtime-role fix this plan addresses.
- The two leftover `RlsProbe *` synthetic companies in the dev database (from the prior audit's own
  empirical RLS probe) are still present — harmless synthetic data, not touched by this plan;
  removable manually whenever convenient.

## 23. Addendum (2026-10-05) — FINDING-04: `account_invite` and `onboarding_token`

§3's no-RLS table list above was written when the schema had 32 tables (19 with RLS) and predates
both `account_invite` (added for employee/user login provisioning) and `onboarding_token` (added
with the onboarding module) entirely. `PRE_PAYROLL_PRODUCTION_READINESS_FINAL_AUDIT.md`
(`FINDING-04`) flagged this as an undocumented gap — not because either table is unprotected, but
because nothing in this document's exception list had ever been extended to say so in one place.

**Security decision: B — RLS intentionally not required**, for the same reason already given here
for `refresh_token`/`session`: a public, unauthenticated caller resolving a secure link (an invite
accept, an onboarding candidate's wizard) has no tenant context yet, so no `app.company_id` GUC
exists for a policy to evaluate against. Both tables are looked up **only by their `token_hash`** —
a `UNIQUE`, SHA-256-derived column no tenant-scoped predicate could narrow further — and this is
recorded in-code, not just here: `AccountInvite`'s and `OnboardingToken`'s own model docstrings
(`hrms/modules/account_invite/models.py`, `hrms/modules/onboarding/models.py`) and
`OnboardingTokenRepository`'s class docstring state the same reasoning, and `onboarding_token`
already carries a corrective migration (`20260906090000_onboarding_o2`) that explicitly *removed*
a `tenant_isolation` policy an earlier migration had mistakenly given it, for exactly this reason.

What makes this safe rather than merely unenforced:

1. **The lookup key is global and unguessable.** `token_hash` is unique across the whole table, not
   per-company — a cross-tenant row can never be returned by a hash a caller doesn't hold, with or
   without RLS, the same property `refresh_token` already relies on.
2. **`company_id` on these rows is server-written only**, never client input (`AccountInvite`'s
   `issue_for_employee`/`issue_for_user`, `OnboardingTokenService.send_invite` — both set it from
   the authenticated issuer's own `TenantContext`, never from the request body).
3. **Every authenticated query path still filters by `company_id` explicitly in the repository**
   (`account_invite/repository.py`'s `list_user_companies_for_company`,
   `revoke_live_invites_for_employee`/`revoke_live_invites_for_email`; `onboarding/repository.py`'s
   `OnboardingCaseRepository` methods)
   — confirmed by the cross-tenant regression tests below, which is the same "application-level
   filtering, independently verified" standard this document already applied to every RLS-backed
   table's own proof.
4. **A resolved token only ever unlocks a second, RLS-protected lookup** — accepting an
   `account_invite` or completing an `onboarding_token`'s case still resolves `employee`/
   `onboarding_case` by the row's own `company_id`, and those tables do carry RLS (`employee`
   already in §3's list; `onboarding_case` added with the onboarding module, same posture). A
   forged or tampered `company_id` on the invite/token row itself is not reachable from any client
   input (point 2), so there is nothing for RLS to additionally guard here that application code
   and the unguessable hash don't already guard.

**Required regression test, added** (mirrors `tests/security/test_rls_runtime_role.py`'s own
cross-tenant pattern): `tests/security/test_account_invite_onboarding_token_isolation.py` proves,
for both tables, that (a) a token hash issued under company A is never resolved under any other
company's context, (b) `GET /v1/users` and `GET /v1/onboarding-cases` under company B never return
a row created for company A, and (c) directly varying the request's `X-Company-Id` cannot make a
company-B-scoped caller read or list a company-A invite/token/onboarding-case.

No schema or code change was made for this finding — `refresh_token`/`session`/`account_invite`/
`onboarding_token` now share one explicit, cross-referenced exception list, and the previously
undocumented half of it (`account_invite`, `onboarding_token`) has the same written reasoning the
documented half already had.
