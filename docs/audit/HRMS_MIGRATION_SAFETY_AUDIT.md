# HRMS Migration Safety Audit

Nothing was executed. Evidence: [REPO] files; [DEV-DB] `alembic_version`; a read-only `alembic.autogenerate.compare_metadata` comparison of ORM metadata vs the dev DB.

## 1. Facts

| Item | Finding |
|---|---|
| Tool / layout | Alembic, `apps/api/alembic/versions`, 125 revisions `YYYYMMDDHHMMSS_name.py`, linear (single head expected; verify with `alembic heads` in CI) |
| First revision | `20260803124757_init_schema.py` executes raw SQL `scripts/sql/001_init_schema.sql` (20 `CREATE TABLE`) through the driver connection; `downgrade()` raises `NotImplementedError` |
| Downgrades | Only one revision file contains `NotImplementedError`; the remainder have downgrade bodies of unknown quality [UNVERIFIED]. Policy should be **forward-only** (roll forward with a fix, restore from backup for disaster) |
| Runner | Prod: `docker compose -f docker-compose.prod.yml run --rm migrate` (`alembic upgrade head`), profile `tools`, never automatic – correct: avoids API/worker race |
| Credential | `alembic/env.py` prefers `MIGRATIONS_DATABASE_URL`, else app URL. **But** that variable is also present in the API/worker env (F-01) |
| Transaction | `env.py` runs all revisions in one transaction (`context.begin_transaction()` around the whole run) ⇒ a failure rolls the entire upgrade back for transactional DDL (good); but `CREATE INDEX CONCURRENTLY` cannot be used without `autocommit_block` – none is configured |
| Timeouts | `env.py` sets no `lock_timeout` / `statement_timeout`; a DDL waiting behind a long transaction will queue and block all traffic to that table |
| Drift detection | None in CI. The ORM models do **not** mirror the database: autogenerate reports 232 FK, 225+155 index, 20 unique-constraint differences, 16 cosmetic type differences (`TEXT` vs `String`, `CHAR` vs `String`), 1 missing DB unique (`permission.code` declared on the model, absent as constraint in dev DB – check if a unique index covers it) [DEV-DB]. Column existence and nullability: **no differences** |
| Applied state | Dev DB `20261022090000`; repo head `20261027092000`. Pending (4): `20261026090000_hr_admin_attendance_onboarding_grants`, `20261027090000_email_outbox`, `20261027091000_onboarding_case_email_unique`, `20261027092000_attendance_day_tenant_fk` (not applied anywhere verified) |
| Uncommitted | `git status`: 278 modified/untracked paths at audit start, so migrations being written may change |
| Pre-deploy grants | `ALTER DEFAULT PRIVILEGES … GRANT … TO hrms_app` ensures new tables are usable; `tests/integration/core/test_runtime_role_grants.py` checks grants. New append-only tables rely on explicit REVOKEs in their migrations (e.g. `leave_ledger`, `audit_log`) |

## 2. Findings

| ID | Pri | Type | Finding | Fix | Effort | Downtime |
|---|---|---|---|---|---|---|
| M-01 | P1 | C | No `lock_timeout`/`statement_timeout` for DDL ⇒ a migration can stall the whole API behind a lock queue | In `env.py` execute `SET lock_timeout='5s'; SET statement_timeout='15min'` (override for big backfills), retry on failure | 0.5 d | none |
| M-02 | P1 | C | No migration-time backup/gate: nothing forces `pg_dump` before `upgrade head`; `migrate` service is unguarded | Runbook step + script `deploy.sh` that refuses to migrate unless a backup newer than 15 min exists and verifies | 1 d | none |
| M-03 | P1 | C | `MIGRATIONS_DATABASE_URL` shared with runtime containers (F-01) | Separate env files | 0.5 d | none |
| M-04 | P2 | C | No model/migration drift gate; models lack indexes/FKs/uniques that exist in SQL (autogenerate unusable) | Replace autogenerate with a **schema snapshot test**: after `alembic upgrade head` dump `pg_dump --schema-only` normalized and compare to `tests/schema_snapshot.sql`; also a test that upgrades from empty and asserts a single head | 1.5 d | none |
| M-05 | P2 | C | No tested upgrade path from the *previous release* with data. CI always runs `upgrade head` on an empty DB | CI job: restore anonymized fixture at previous tag, upgrade, run smoke tests | 2 d | none |
| M-06 | P2 | R | Large-table rewrite risk in future: column type changes, `NOT NULL` additions with default, `CREATE INDEX` without `CONCURRENTLY` on `punch`/`attendance_day`/`audit_log`/`pay_run_line` once big. Today all tables are small, so existing migrations are safe at Pilot/Early scale. Safe patterns: add nullable column → backfill in batches → add `CHECK … NOT VALID` → `VALIDATE` ; `CREATE INDEX CONCURRENTLY` in `op.get_context().autocommit_block()` | Adopt lint (squawk or custom) in CI | 1 d | none |
| M-07 | P2 | R | Backfill migrations (`*_backfill.py`: default roles, permissions, approval authority) run inside the single transaction under RLS-less owner role; they are idempotent by name but not re-verified | Keep idempotent; test twice | – | none |
| M-08 | P2 | C | Failed-migration recovery is documented only partly (`PRODUCTION_DEPLOYMENT.md`, `DISASTER_RECOVERY.md`). Because the run is single-transaction, a failed upgrade leaves the DB at the old revision – verify with a forced-failure test | Add test T-09 and recovery steps in the runbook | 0.5 d | none |
| M-09 | P3 | R | Composite tenant FK migration (`20261027092000`) adds a constraint that validates existing rows: on a populated table do `ADD CONSTRAINT … NOT VALID` then `VALIDATE CONSTRAINT` | review the revision before production | 0.5 d | none |
| M-10 | P3 | U | 97 of the revision/SQL files match `drop_table|drop_column|DROP TABLE|DROP COLUMN` (most are expected to be `downgrade()` bodies or index swaps). Not individually reviewed; list non-downgrade matches before release and confirm none destroys data | review | 0.5 d | – |

## 3. Recommended production migration procedure

1. Release tag from a clean commit; CI green (including previous-tag upgrade job).
2. `deploy.sh` freezes: `docker compose stop beat worker` (pauses scheduled/async writers), keep API running for read traffic unless the revision is marked *breaking*.
3. `pg_dump -Fc` + checksum + upload off-server; abort on failure (M-02).
4. `docker compose run --rm migrate` (separate env, `lock_timeout=5s`). Single invocation, single host.
5. Start new `api`, `worker`, `beat` images; run smoke tests; check `/health/ready`.
6. On failure: transactional DDL rolled back ⇒ previous images still match the schema ⇒ redeploy previous tag. If the failure is after commit: **roll forward** with a fix migration; restore from the step-3 dump only if data corruption is proven (RPO = time of dump, so inform users).
7. Expand/contract rule for any change that renames/removes columns: release N adds + dual-writes, N+1 switches reads, N+2 drops.
