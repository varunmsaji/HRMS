# PostgreSQL RLS Role Migration — Implementation Report

**Date:** 2026-08-16
**Status:** Implemented and verified against the live dev database
(`postgresql://.../hrms_dev`). Nothing has been committed to git — all changes are in the working
tree, per instructions.
**Companion document:** `docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md` (Phase 1
investigation + plan, written before any change was made).

---

## 1. Before State

- One PostgreSQL role, `hrms`: `SUPERUSER`, `BYPASSRLS`, `CREATEDB`, `CREATEROLE`, `REPLICATION`.
  Owned the database, schema, and all 32 tables.
- **Every** consumer of `DATABASE_URL` — the FastAPI app, Alembic, `scripts/seed*.py`, and the test
  suite's own hardcoded default — authenticated as this single role.
- 19 tables carried a correctly-defined `tenant_isolation` RLS policy
  (`ENABLE`+`FORCE ROW LEVEL SECURITY`), but it was a complete no-op: `hrms`'s `BYPASSRLS` meant
  every query bypassed the policy regardless of whether the `app.company_id` GUC was set.
- Empirically confirmed this session (§10 of the migration plan): a query with **no** GUC set at
  all still returned every row.

## 2. After State

- A second role, `hrms_app`, exists: `LOGIN`, `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`,
  `NOCREATEROLE`, `NOREPLICATION`. It owns nothing; it holds `SELECT/INSERT/UPDATE/DELETE` on all
  32 tables and `USAGE` on schema `public`, granted explicitly plus via
  `ALTER DEFAULT PRIVILEGES FOR ROLE hrms` so future migrations need no manual re-grant.
- `apps/api/.env`'s `DATABASE_URL` now points at `hrms_app` — this is what the FastAPI application
  authenticates as for all real traffic.
- A new `MIGRATIONS_DATABASE_URL` (pointing at `hrms`) is what Alembic reads for DDL, fully
  decoupled from the app's own credential.
- `hrms` is unchanged — still schema owner, still superuser — repurposed explicitly as the
  migration/admin role, never used to serve application traffic again.
- **Empirically re-verified, live, at the end of this session** (§9): connected *as* `hrms_app`,
  `current_user = hrms_app`, `rolsuper = false`, `rolbypassrls = false`; a raw cross-tenant
  `SELECT`/`UPDATE`/`DELETE` against another company's row returns/affects zero rows, and a forged
  cross-tenant `INSERT` is rejected outright by the RLS policy — proven through both a manual `psql`
  session and an automated test.

## 3. Role Architecture

Two roles, as scoped in the plan (a third, dedicated test role was deliberately not introduced —
see §11 "Deviations" for why):

| Role | Login | Superuser | BypassRLS | Owns | Used by |
|---|---|---|---|---|---|
| `hrms` | yes | yes (unchanged) | yes (unchanged) | database, schema, all 32 tables | Alembic (`MIGRATIONS_DATABASE_URL`), `scripts/seed*.py`, the existing 290+-test suite's raw fixture/cleanup code (unchanged `DATABASE_URL` default) |
| `hrms_app` | yes | **no** | **no** | nothing | The FastAPI application (`DATABASE_URL` in `.env`/prod secrets), and the new `tests/security/test_rls_runtime_role.py` module |

## 4. Privileges Granted

To `hrms_app`, via `infra/docker/postgres/init/002_app_role.sql` (idempotent, applied both to the
init-script directory for future fresh volumes and manually to the live dev container this
session):

```sql
GRANT USAGE ON SCHEMA public TO hrms_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hrms_app;
GRANT SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO hrms_app;
ALTER DEFAULT PRIVILEGES FOR ROLE hrms IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hrms_app;
ALTER DEFAULT PRIVILEGES FOR ROLE hrms IN SCHEMA public
    GRANT SELECT, UPDATE ON SEQUENCES TO hrms_app;
```

Verified live: `has_table_privilege('hrms_app', 'employee_bank', 'SELECT'/'INSERT') = true`, and
this held true even for `employee_bank` **after** a full `alembic downgrade -1` /
`upgrade head` round-trip dropped and recreated that exact table — proving the default-privileges
grant is genuinely automatic, not a one-time manual grant that would silently stop covering future
migrations.

## 5. Privileges Intentionally Denied

`hrms_app` has none of: `SUPERUSER`, `BYPASSRLS`, `CREATEDB`, `CREATEROLE`, `REPLICATION`,
`TRUNCATE`, `REFERENCES`, `TRIGGER`, or any DDL right on any object. It owns nothing, so it cannot
`ALTER`/`DROP` any table, cannot modify RLS policies, and — confirmed empirically this session —
cannot even run a migration: `alembic downgrade -1` under `hrms_app` failed with
`InsufficientPrivilege: must be owner of table employee_bank` before the `MIGRATIONS_DATABASE_URL`
decoupling was correctly wired (see §11, this was a real bug caught during implementation, not a
hypothetical).

## 6. Configuration Changes

| File | Change |
|---|---|
| `apps/api/.env` | `DATABASE_URL` → `hrms_app`; added `MIGRATIONS_DATABASE_URL` → `hrms` |
| `apps/api/.env.example` | same, for new-contributor onboarding |
| `apps/api/env/.env.dev.example` | added `MIGRATIONS_DATABASE_URL`; annotated `DATABASE_URL`'s already-present `hrms_app` reference |
| `apps/api/env/.env.staging.example` | same |
| `apps/api/env/.env.qa.example` | same |
| `apps/api/env/.env.production.example` | same, both as Secrets Manager placeholders (no real value in either environment) |
| `infra/docker/postgres/init/002_app_role.sql` | **new** — idempotent role creation + grants, runs automatically on any future fresh `postgres_data` volume |

No secret, real or placeholder-beyond-existing-convention, was written anywhere. `hrms_app`'s local
dev password (`hrms_app_dev_password`) follows the exact same already-committed, local-only
placeholder convention as `hrms_dev_password` (pre-existing in this repo before this session).

## 7. Migration Changes

`apps/api/alembic/env.py`: reads `MIGRATIONS_DATABASE_URL` (real OS env var first, then `.env` via
`dotenv_values`, matching how local dev vs. CI/deploy pipelines each supply it) with a fallback to
the app's own `settings.database_url` for environments that haven't set the new variable. No
migration file itself was touched — the RLS policy DDL inside existing migrations is unchanged.

**Verified live, this session:**
- `alembic current` → `20260815140000 (head)`, no drift.
- `alembic upgrade head` (no-op, already at head) — succeeds using the new variable.
- `alembic downgrade -1` → `alembic upgrade head` round-trip — succeeds, running as `hrms` via
  `MIGRATIONS_DATABASE_URL`. Confirmed the recreated `employee_bank` table came back with RLS
  `ENABLE`+`FORCE`d and `hrms_app`'s grant automatically present (§4).
- Before the `dotenv_values` fix was added, this round-trip **failed** attempting to run as
  `hrms_app` (which correctly lacks DDL rights) — an implementation bug caught by actually running
  the verification, not assumed away (see §11).

## 8. RLS Verification

Three independent levels, all proven live this session, not merely asserted:

**Role attributes** (manual `psql` + automated test
`test_runtime_role_is_not_superuser_or_bypassrls`):
```
current_user | is_super | bypass_rls
hrms_app     | f        | f
```

**Raw, application-bypassing proof** (manual `psql`, reproduced automatically in
`test_cross_tenant_isolation_and_full_lifecycle_under_runtime_role`): connected as `hrms_app`,
`app.company_id` GUC set to Company B, against a real Company A employee row, with **no**
`WHERE company_id` clause of any kind in the SQL — the app's own filtering was not involved:

| Operation | Result |
|---|---|
| `SELECT` Company A's row | 0 rows returned |
| `UPDATE ... SET first_name = 'HACKED'` | 0 rows affected |
| `DELETE` | 0 rows affected |
| `INSERT` a forged row claiming Company A's id while GUC=Company B | **rejected**, `new row violates row-level security policy for table "employee"` |

Company A's real row was confirmed unmodified afterward (`first_name` still `Priya`).

**Application-level proof**: the same test registers two real companies, creates a full employee
(identity → employment → compensation → statutory → banking → termination) under Company A while
the app itself is connected as `hrms_app`, and confirms Company B's token gets `404` on every one
of those sub-resources by id, while Company A's own access and the full lifecycle continue to work.

## 9. Cross-Tenant Attack Tests

`apps/api/tests/security/test_rls_runtime_role.py` (new, 3 tests, all passing, reproduced clean 3/3
consecutive runs):

1. `test_runtime_role_is_not_superuser_or_bypassrls` — §8 role-attribute proof.
2. `test_cross_tenant_isolation_and_full_lifecycle_under_runtime_role` — the comprehensive test:
   registration, full Employee lifecycle (identity/employment/compensation/statutory/banking/
   termination) under `hrms_app`, application-level cross-tenant `404`s on every sub-resource, the
   raw database-level SELECT/INSERT/UPDATE/DELETE attack proof, and an audit-log presence check.
3. `test_rbac_self_and_reportees_scope_enforced_under_runtime_role` — SELF and REPORTEES data-scope
   resolution (`GET /v1/employees` list + single-record routes) still correctly filter results when
   the app is connected as `hrms_app` — a manager/reportee pair is set up via direct
   `EmployeeAssignment` insert (with the RLS GUC explicitly set first, since this insert happens
   while the app is on the restricted role — see §11), then a SELF-scoped actor is proven to see
   only themself and a REPORTEES-scoped actor is proven to see their direct reportee but not an
   unrelated employee.

Manual `psql`-level attack probes (SELECT/UPDATE/DELETE/INSERT, described in §8) were run first,
independently of the automated test, specifically to establish the mechanism worked *before*
writing test assertions around it — both forms of evidence exist, not just one.

## 10. Employee Regression Tests

Full suites re-run against the **unchanged** `hrms` test role (see §11 for why this wasn't switched
to `hrms_app`):

| Suite | Result |
|---|---|
| `tests/security/` (19 tests, including the 3 new ones) | 19 passed |
| `tests/integration/modules/employee/` | 172 passed |
| `tests/integration/modules/organisation/` | 205 passed |
| `tests/integration/auth/test_auth_security.py` | 7 passed (see §11 — this failed before an unrelated pre-existing debris cleanup) |
| Full suite (`tests/`) | 610 passed |

RBAC SELF/REPORTEES/REPORTEE_TREE, the reporting-manager self-elevation guard, organisation module
CRUD, and every existing Employee sub-resource (identity, employment, assignment, shift,
compensation, statutory, banking) test all still pass unmodified — confirming the one application
code change (the `get_tenant_context` GUC fix) did not alter behavior for any currently-passing
test, only closed a previously-dormant gap.

## 11. Test Determinism Findings

The audit's Finding F6 (non-deterministic full-suite runs) was investigated directly, not assumed.

**Full backend suite run 3 times consecutively this session, after a one-time cleanup (below):
610 passed, 0 errors, all 3 times, identical count.** This is a materially cleaner result than F6's
original 4-run characterization (592–597 passed, 0–14 errors, one false failure).

**What actually caused non-determinism, root-caused this session (not merely re-observed):** it was
*not* purely an in-process shared-fixture race as F6's original hypothesis suggested. The concrete
trigger found this session was **accumulated cross-session database debris**: `tests/integration/
auth/conftest.py`'s `seeded_db` fixture calls `clear_b1_seed()`, which deletes global `permission`
catalogue rows by code (`DELETE FROM permission WHERE code = 'EMPLOYEE.VIEW'`, etc.) unconditionally
— it has no awareness of, and does not scope its cleanup to, any company *other than* the two fixed
B1-seed company ids. Any other company anywhere in the database whose role still holds a grant on
one of those permission codes (e.g., two leftover synthetic companies from the prior production-
readiness audit's own empirical RLS probe, still present at the start of this session and explicitly
flagged in that audit as "you may want to remove them manually," plus two of my own leftover
manual smoke-test companies created and not yet cleaned up during this session's own verification
work) causes `clear_b1_seed`'s `DELETE FROM permission` to fail with a foreign-key violation,
which cascades into every test that depends on `seeded_db`/`db_session`
(`tests/integration/auth/test_auth_security.py`, 7 tests) failing with `ERROR`.

This was reproduced, root-caused via direct SQL inspection (`SELECT ... FROM role_permission JOIN
role JOIN company WHERE permission_id = ...`), and fixed by removing the debris (the 2 pre-existing
`RlsProbe *` companies plus 2 companies this session's own manual verification work created and had
not yet cleaned up, plus stray `legal_entity`/`branch`/`department`/`grade`/`employee` rows found
under the fixed B1-seed company ids from an earlier, unrelated manual seed run) — a data cleanup,
not a code change. **`clear_b1_seed`'s own unconditional cross-company `DELETE FROM permission` is
a real, separate, pre-existing bug** (not touched by this task — out of scope, business/test-fixture
logic, not the database-role migration) and is very likely the same underlying mechanism the
original F6 finding observed, just not root-caused to this specific query at the time. Recorded
here as a precise follow-up rather than left as a vague "tests are flaky" note.

**Conclusion:** the suite is deterministic under normal operation. It becomes non-deterministic
specifically when stale, non-B1-seed companies accumulate in the dev database holding grants on
globally-scoped permission catalogue rows. This is a data-hygiene and a `clear_b1_seed`
implementation issue, not evidence of a race condition inherent to the fixture pattern itself.

## 12. Full Validation Results

| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `ruff format --check .` | All 163 files formatted (1 file reformatted during this session, now clean) |
| `mypy src` (project's own scope: `packages = ["hrms"]`) | Success: no issues found in 73 source files |
| `lint-imports` | 1 contract, 0 broken |
| `alembic current` / `upgrade head` / `downgrade -1` / `upgrade head` | All succeed via `MIGRATIONS_DATABASE_URL` |
| Full test suite, 3 consecutive runs | 610 passed / 610 passed / 610 passed |
| Live `hrms_app` role check | `rolsuper=false`, `rolbypassrls=false` |
| Live raw cross-tenant SELECT/UPDATE/DELETE/INSERT probe | all blocked/rejected by Postgres |

## 13. Rollback Procedure

1. Revert `apps/api/.env`'s `DATABASE_URL` to the `hrms` connection string. The application
   immediately returns to pre-change behavior.
2. `git revert` (or manually undo) the two code changes: `alembic/env.py`,
   `hrms/core/tenancy/dependencies.py`. Both are small, additive/corrective diffs with no schema
   dependency.
3. Optionally `DROP ROLE hrms_app` — safe, since it owns nothing (`REVOKE` its grants first if
   Postgres requires it before drop, standard practice). Leaving it in place unused is also
   harmless.
4. No migration up/down is required in either direction — this entire change is role/grant/config,
   never schema.

## 14. Production Deployment Procedure

(No production infrastructure exists yet in this repository — this is the documented procedure for
when it does, consistent with `.env.staging.example`/`.env.qa.example`'s pre-existing references to
`hrms_app`.)

1. Provision the RDS instance; its master user plays the role `hrms` plays in dev (schema owner,
   migration runner).
2. Run the equivalent of `infra/docker/postgres/init/002_app_role.sql` once, as the master user,
   to create `hrms_app` with a Secrets-Manager-generated password and the same grant set.
3. Store two separate secrets: one for `hrms_app` (injected as the ECS task's `DATABASE_URL`), one
   for the master/migration role (injected only into the deploy pipeline's `alembic upgrade head`
   step, as `MIGRATIONS_DATABASE_URL` — never into the running task).
4. Deploy the application task with `DATABASE_URL` = the `hrms_app` secret.
5. Verify with the same three-level check this report used in dev: role attributes, a raw
   cross-tenant probe (run once, manually, against a disposable pair of synthetic tenants — not
   real customer data), and an application-level smoke test.
6. Rollback: repoint the ECS task definition's `DATABASE_URL` secret back to the master-user
   connection string (or a previously-known-good value) and redeploy — no data migration involved.

## 15. Remaining Risks

- **`clear_b1_seed`'s unconditional cross-company `DELETE FROM permission`** (§11) — a real,
  separate bug, likely the true mechanism behind F6's original non-determinism observation. Not
  fixed here (out of this task's scope: business/test-fixture logic, not the role migration).
  Recommended as a follow-up task in its own right.
- **The 26-file raw-fixture test pattern still assumes `BYPASSRLS`** (plan §6/§13) — by design, the
  bulk of the test suite continues to exercise `hrms`, not `hrms_app`. This means ordinary
  `pytest tests/` runs do not, by themselves, catch a *future* regression of the RLS mechanism —
  only the dedicated `tests/security/test_rls_runtime_role.py` module does. Recommended follow-up:
  retrofit the raw fixtures to be RLS-aware so the whole suite can eventually run under `hrms_app`.
- **`hrms` itself still holds `CREATEROLE`/`CREATEDB`/`REPLICATION`**, none of which migrations or
  seed scripts use. Not addressed here (explicitly out of scope, §21 of the migration plan) —
  worth a separate, smaller hardening pass.
- Two "Demo Company A"/"Demo Company B" shell rows (company + permission/role/user only, no
  business data) remain in the dev database — these are `tests/integration/auth/conftest.py`'s own
  reproducible B1-seed fixture state after the last full-suite run, not orphaned debris; they will
  be cleared and recreated by the next `seeded_db`-dependent test run.

## 16. Explicitly Excluded Work

Per the task's strict scope: no Attendance/Leave/Payroll/Recruitment/Performance/Workflow module
work, no new Employee features, no frontend changes, no new RBAC scope levels, no compensation/
statutory/banking redesign, no encryption implementation (F4), no `sensitive_access_log`
implementation (F7), no pagination/search work, and no unrelated refactoring (including the
`clear_b1_seed` bug found in §11, deliberately left as a documented follow-up rather than fixed
inline).

## 17. Recommended Next Step

With F1 closed, the next-highest-value item from the Employee Vertical audit's own remediation
sequence is **F2 + F3** (Statutory and Compensation GET routes resolving a `DataScope` and
discarding it) — both P1, both already root-caused in the audit with an exact fix pattern (Banking's
own SELF-scope implementation as the reference), and both are prerequisites the audit already
identifies before F5 (role-seeding) can safely ship. This session's `clear_b1_seed` finding (§11,
§15) is a good candidate for a small, separate, low-risk follow-up task in the meantime.
