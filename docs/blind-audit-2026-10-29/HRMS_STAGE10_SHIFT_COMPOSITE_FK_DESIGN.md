# Stage 10 — Composite tenant FK for shift references: audit and migration design

Date: 2026-10-29 · Follows F-10 (fixed in Stage 9 at service level) and F-01 in `HRMS_STAGE7_TENANT_ISOLATION_AUDIT.md`. **Design only: no migration was written or run, no application code changed, no database write or schema change was made.** Evidence tags: **[DB]** read-only catalog/`SELECT` on `rls-h1`; **[CODE]** read from the repository; **[ASSUMED]** not verified by execution.

## 1. Schema findings

Server: PostgreSQL 16.14 [DB]; `docker-compose.yml:5` and `docker-compose.prod.yml:49` both pin `postgres:16-alpine` [CODE]. Alembic head: `20261030090000` (`down_revision 20261029090000`) [CODE]; the new revision would chain from it.

| Table | Relevant columns | Existing constraints [DB] |
|---|---|---|
| `shift` | `id uuid NOT NULL`, `company_id uuid NOT NULL`, `deleted_at` | `shift_pkey (id)`; `shift_company_id_fkey → company(id)`; indexes `shift_company_id_idx`, `shift_company_active_idx`. **No `UNIQUE (company_id, id)`.** |
| `shift_roster` | `company_id NOT NULL`, `employee_id NOT NULL`, `shift_id uuid` **nullable** | `shift_roster_shift_id_fkey (shift_id) → shift(id) ON DELETE SET NULL`; unique index `shift_roster_unique_idx (company_id, employee_id, roster_date) WHERE deleted_at IS NULL`; CHECKs: status, override-exclusive only |
| `attendance_regularization_request` | `company_id NOT NULL`, `requested_shift_id uuid` **nullable** | `…_requested_shift_id_fkey (requested_shift_id) → shift(id) ON DELETE SET NULL`; no CHECK ties the column to `request_type` |
| `shift_version` (context) | `shift_id NOT NULL`, `company_id NOT NULL` | `shift_version_shift_id_fkey → shift(id) ON UPDATE CASCADE ON DELETE RESTRICT` |

Other single-column FKs onto `shift(id)` (not in scope, same gap) [DB]: `employee_assignment.shift_id`, `attendance_day.shift_id`, `shift_version.shift_id`.

* The referenced key. A composite FK needs a unique constraint on exactly `(company_id, id)` in `shift`. `id` is the primary key, so such a constraint is trivially satisfiable, but **it does not exist yet** and must be added first.
* No trigger exists on any of the three tables [DB]. RLS is ENABLE+FORCE on all three [DB].
* Shifts are never hard-deleted by the application (no `delete(Shift)` / `DELETE FROM shift` in `modules/organisation`) [CODE], so `ON DELETE SET NULL` is currently unreachable in practice; it is retained only as a safeguard.
* Precedent in this repo [CODE/DB]: `20261027092000_attendance_day_tenant_fk.py` (employee, `NOT VALID` + `VALIDATE`, pre-flight that refuses to run and lists offending rows, never rewrites data, owner-role check) and `20261030090000_attendance_geofencing.py` (`employee_workplace_authorization`/`geofence_attempt` composite FKs). Existing keys: `employee_company_id_id_key`, `branch_company_id_id_key`.

## 2. Read-only data checks

Run as the schema owner (a role subject to RLS sees no rows and would report a false "clean"). The script returns one row per check; any non-zero `*_cross_company` / `*_orphan_*` / `shift_dup_*` / `shift_null_company` blocks the migration.

```sql
SELECT 'roster_total' AS check, count(*)::text AS n FROM shift_roster
UNION ALL SELECT 'roster_with_shift', count(*)::text FROM shift_roster WHERE shift_id IS NOT NULL
UNION ALL SELECT 'roster_cross_company', count(*)::text FROM shift_roster r JOIN shift s ON s.id = r.shift_id WHERE s.company_id <> r.company_id
UNION ALL SELECT 'roster_orphan_shift', count(*)::text FROM shift_roster r WHERE r.shift_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM shift s WHERE s.id = r.shift_id)
UNION ALL SELECT 'roster_refs_soft_deleted_shift', count(*)::text FROM shift_roster r JOIN shift s ON s.id = r.shift_id WHERE s.deleted_at IS NOT NULL
UNION ALL SELECT 'reg_total', count(*)::text FROM attendance_regularization_request
UNION ALL SELECT 'reg_with_requested_shift', count(*)::text FROM attendance_regularization_request WHERE requested_shift_id IS NOT NULL
UNION ALL SELECT 'reg_cross_company', count(*)::text FROM attendance_regularization_request q JOIN shift s ON s.id = q.requested_shift_id WHERE s.company_id <> q.company_id
UNION ALL SELECT 'reg_orphan_shift', count(*)::text FROM attendance_regularization_request q WHERE q.requested_shift_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM shift s WHERE s.id = q.requested_shift_id)
UNION ALL SELECT 'shift_total', count(*)::text FROM shift
UNION ALL SELECT 'shift_dup_company_id_id', count(*)::text FROM (SELECT company_id, id FROM shift GROUP BY 1,2 HAVING count(*) > 1) d
UNION ALL SELECT 'shift_null_company', count(*)::text FROM shift WHERE company_id IS NULL
UNION ALL SELECT 'existing_shift_company_id_key', count(*)::text FROM pg_constraint WHERE conrelid = 'shift'::regclass AND contype = 'u'
UNION ALL SELECT 'existing_composite_fks_on_targets', count(*)::text FROM pg_constraint WHERE conname IN ('shift_roster_company_shift_fkey','attendance_regularization_request_company_shift_fkey')
UNION ALL SELECT 'rls_forced_on_targets', count(*)::text FROM pg_class WHERE relname IN ('shift','shift_roster','attendance_regularization_request') AND relforcerowsecurity AND relrowsecurity
UNION ALL SELECT 'current_role_bypasses_rls', (SELECT (rolsuper OR rolbypassrls)::text FROM pg_roles WHERE rolname = current_user);
```

### Results on `rls-h1` (2026-10-29) [DB]
Every count was `0` (`shift_total`, `roster_total`, `reg_total` included), `rls_forced_on_targets = 3`, `current_role_bypasses_rls = true`.

**What this proves and does not prove.** It proves the checks execute and the structural facts (no existing `UNIQUE` on `shift`, no composite FK yet, `id` unique, `company_id` NOT NULL). It proves **nothing about production data**: the QA tables are empty, so "0 cross-company rows" is vacuous. Before any production rollout the script must be run on a production-shaped copy/snapshot, and the F-10 reproduction in Stage 8 shows how such rows could have been created through the API before Stage 9. (`pg_class.reltuples` showed `1` for the regularization table; that is a stale planner estimate, the exact `count(*)` is 0.)

Not verified [ASSUMED]: that the `CREATE`/`ALTER` statements below execute cleanly. I did not run DDL, not even inside a rolled-back transaction, to honour "no schema changes". They must be exercised on the disposable stack and the scratch-database migration tests in the implementation stage.

## 3. Proposed migration

New revision, `down_revision = "20261030090000"`, file `apps/api/alembic/versions/<ts>_shift_tenant_fk.py`, same structure as `20261027092000`.

### 3.1 Constraints

```sql
-- 1. Referenced key. id is already the PK, so this cannot fail on data; it only builds an index.
ALTER TABLE shift
  ADD CONSTRAINT shift_company_id_id_key UNIQUE (company_id, id);

-- 2. Roster: the shift must belong to the roster row's company.
ALTER TABLE shift_roster
  ADD CONSTRAINT shift_roster_company_shift_fkey
  FOREIGN KEY (company_id, shift_id) REFERENCES shift (company_id, id)
  ON DELETE SET NULL (shift_id) NOT VALID;
ALTER TABLE shift_roster VALIDATE CONSTRAINT shift_roster_company_shift_fkey;

-- 3. Regularization: same for the requested shift.
ALTER TABLE attendance_regularization_request
  ADD CONSTRAINT attendance_regularization_request_company_shift_fkey
  FOREIGN KEY (company_id, requested_shift_id) REFERENCES shift (company_id, id)
  ON DELETE SET NULL (requested_shift_id) NOT VALID;
ALTER TABLE attendance_regularization_request
  VALIDATE CONSTRAINT attendance_regularization_request_company_shift_fkey;
```

Design decisions:
* **Nullable shift columns.** The default `MATCH SIMPLE` skips the check when any referencing column is NULL. `company_id` is NOT NULL, so the check is skipped exactly when the shift column is NULL: week-off roster rows and shift-less regularizations stay valid. `MATCH FULL` would be wrong here.
* **`ON DELETE SET NULL (shift_id)` (PostgreSQL 15+, server is 16).** A plain `SET NULL` on a composite FK would also try to null `company_id`, which is NOT NULL, and fail. The column list nulls only the shift column, preserving today's semantics (delete a shift → references cleared). The precedent migrations used `RESTRICT` because their original FKs were not `SET NULL`; copying `RESTRICT` here would change behaviour for an operation the app never performs but a DBA might.
* **`ON UPDATE`** stays `NO ACTION`: changing a shift's `company_id` or a referencing row's company to a mismatching value is rejected. `company.id` is never updated in practice; a cascade from `company` would update both sides in one statement and still pass.
* **Keep the existing single-column FKs.** They stay unchanged (as in the attendance_day precedent), so cascade behaviour is untouched and the migration is purely additive. The two FKs together are redundant but harmless; dropping the old ones is a later clean-up, not part of this stage.
* **No new index on the referencing side.** The parent key gets its unique index (needed). Lookups from `shift` to the children only happen on shift delete/update, which the application never does, and the existing single-column FKs are already unindexed on that side. Add `(company_id, shift_id)` indexes only if shift deletion becomes a feature.
* **RLS and permissions untouched.** The migration runs as the owner; it neither disables RLS nor changes grants. FK checks run with owner privileges and ignore RLS, which is why a database constraint is needed at all.

### 3.2 Pre-flight, validation and remediation
1. **Role guard** (copy from the precedent): abort if the migration role is not SUPERUSER/BYPASSRLS, otherwise the checks would see no rows.
2. **Pre-flight `DO` block** before any DDL: count `roster_cross_company`, `reg_cross_company` (and orphans); if any are non-zero, `RAISE EXCEPTION` with a `DETAIL` listing up to 100 rows (id, company, referenced shift, the shift's actual company or `missing`), and change nothing. The migration never deletes or rewrites data.
3. **Remediation is deliberate, out-of-band and approved**, not automatic:
   * First preserve evidence (export the offending rows; they indicate either the F-10 flaw being exercised or corruption).
   * Roster rows: soft-delete (`deleted_at`) or clear `shift_id`, decided with the tenant, because a roster row with no shift changes how that employee-date is calculated.
   * Regularization rows: if still `SUBMITTED`, reject/cancel through the application workflow; if decided, clear `requested_shift_id` only.
   * Re-run the §2 script until clean, then re-run the migration.
4. `NOT VALID` then `VALIDATE` so the validating scan does not hold a long write lock.

### 3.3 Ordering, locks, downtime
Order: guard → pre-flight → unique constraint on `shift` → roster FK (`NOT VALID`, `VALIDATE`) → regularization FK (`NOT VALID`, `VALIDATE`), all in the migration transaction.
* `ADD CONSTRAINT … UNIQUE` builds an index under a lock that blocks writes to `shift` for the build. Shifts are a handful of rows per company, so it is milliseconds.
* `ADD … FOREIGN KEY … NOT VALID` takes SHARE ROW EXCLUSIVE on the child and the parent for an instant (no scan).
* `VALIDATE` scans the child under SHARE UPDATE EXCLUSIVE on the child (reads and writes continue) and ROW SHARE on the parent.
* No downtime expected. Run in a quiet window anyway and set a `lock_timeout` so a long-held lock aborts the migration instead of queueing behind it.
* Application must be on the Stage 9 build **before** the migration: otherwise a stale writer could still insert a foreign shift, and would now get an opaque FK violation instead of a clean 404.

### 3.4 Upgrade verification and rollback
* After upgrade: `pg_constraint` contains the three new constraints, all `convalidated = true`; re-run the §2 script (the two `*_cross_company` rows now must be impossible); `alembic current` = new revision.
* **Downgrade** drops, in this order: the two composite FKs, then `shift_company_id_id_key` (it cannot be dropped while the FKs depend on it). It changes no rows, so it is safe. Limitations: it restores the weaker schema, not any data, and rolling back re-opens the F-01 gap (only the Stage 9 service check remains). If remediation edited data before upgrade, the downgrade does not undo those edits.
* Downgrade → upgrade must be repeatable.

## 4. Test matrix

Migration tests on a scratch database (pattern of `tests/integration/migrations/test_b13_migrations.py`):

| # | Case | Expected |
|---|---|---|
| M1 | Upgrade on clean data | 3 constraints exist and are validated |
| M2 | Existing cross-company roster row | Migration aborts before DDL, lists the row, no constraint added, data unchanged |
| M3 | Existing cross-company regularization row | same |
| M4 | Roster/regularization with NULL shift | Upgrade succeeds, rows untouched |
| M5 | Orphaned shift reference (only constructible with FKs dropped in scratch DB) | Aborts with row listing |
| M6 | Downgrade then upgrade | Constraints removed, then re-added; no data change |
| M7 | Upgrade attempted as an RLS-subject role | Refuses with the role message |

Runtime-role tests on `rls-h1`, new file `tests/integration/modules/attendance/test_shift_tenant_fk_runtime_role.py`, same two-tenant fixtures as the Stage 9 file, raw SQL as both the owner role and `hrms_app` with the tenant variable set (pattern of `test_b13_attendance_tenant_fk.py`):

| # | Case | Expected |
|---|---|---|
| R1 | INSERT roster with own shift | succeeds |
| R2 | INSERT roster with other company's shift (service bypassed) | `shift_roster_company_shift_fkey` violation, for owner and `hrms_app` |
| R3 | UPDATE roster `shift_id` to other company's shift | violation |
| R4 | INSERT roster with NULL shift (week-off) | succeeds |
| R5 | Same R1–R4 for `requested_shift_id` | same results with the regularization constraint |
| R6 | UPDATE `shift.company_id` of a referenced shift | rejected |
| R7 | DELETE a referenced own-company shift (owner) | succeeds, `shift_id` set NULL, `company_id` intact |
| R8 | API: foreign shift on roster/regularization | still 404 from the Stage 9 service check (the constraint is the second line, not the first); Stage 9 file must keep passing |
| R9 | Teardown | only the test's tenants removed (`wipe_tenant`); counts unchanged afterwards |

## 5. Rollout plan
1. **Implement** (next stage, after approval): migration, M1–M7, R1–R9; run on a fresh disposable stack (new run id, not `rls-h1`'s data) via `stack.sh migrate`, then `py … alembic downgrade/upgrade`.
2. **Dry-run on a production-shaped copy:** run the §2 script; zero cross-company rows, or an approved remediation list.
3. **Deploy order:** Stage 9 application build → data check → migration in a quiet window with `lock_timeout` → re-run the check script and the Stage 9 + R tests.
4. **Follow-ups (separate stages):** same pattern for `shift_version.shift_id`, `attendance_day.shift_id`, `employee_assignment.shift_id` (the new `shift_company_id_id_key` makes them cheap); later retire the redundant single-column FKs.

## 6. Risks
* **Production data unknown.** The pre-flight may block the migration; remediation needs a business decision per row, and the rows may be evidence of misuse.
* **Syntax and behaviour of `ON DELETE SET NULL (col)` unverified by execution** here. PostgreSQL 16 documents it; confirm in M1/R7. If it misbehaves, fall back to `ON DELETE RESTRICT` (as in the precedent) and accept that deleting a referenced shift becomes an error.
* **Stale writers** between deploy and migration could re-create bad rows; mitigated by deploy order.
* **Lock timeouts** if another transaction holds a lock on `shift`; the migration then fails cleanly and can be retried.
* **Only two of the five FKs onto `shift` are covered.** `shift_version`, `attendance_day` and `employee_assignment` remain unconstrained at the database level (F-01 stays open).
* Existing uncommitted work in the tree (tenancy fixes, runtime-role tests, Stage 7B/9 fixes) must be committed before this ships; this stage adds no code of its own.

## 7. Files changed in this stage
* Added: `docs/blind-audit-2026-10-29/HRMS_STAGE10_SHIFT_COMPOSITE_FK_DESIGN.md` (this report).
* No application code, migration, test, CI or configuration file was created or modified. Only read-only catalog queries and `SELECT` counts were executed on `rls-h1`; no write, DDL or cleanup.
