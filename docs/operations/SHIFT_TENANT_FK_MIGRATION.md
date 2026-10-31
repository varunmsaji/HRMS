# Migration `20261031090000` — shift composite tenant foreign keys

Design and rationale: `docs/blind-audit-2026-10-29/HRMS_STAGE10_SHIFT_COMPOSITE_FK_DESIGN.md`. Finding: F-10 (service fix in Stage 9), F-01 (database backstop).

## What it does
* `shift`: adds `UNIQUE (company_id, id)` (`shift_company_id_id_key`).
* `shift_roster (company_id, shift_id)` and `attendance_regularization_request (company_id, requested_shift_id)` get composite FKs to `shift (company_id, id)`, `ON DELETE SET NULL (<shift column>)`, `MATCH SIMPLE` (a NULL shift is not checked).
* The original single-column FKs, RLS policies and grants are unchanged. Nothing is deleted or rewritten.

## Before you run it
1. Deploy the application build that contains the Stage 9 service check first, so stale code cannot keep writing foreign shifts.
2. Run as the schema-owner role (`MIGRATIONS_DATABASE_URL`). A role subject to RLS is refused: it would see no rows and report "clean".
3. The migration's pre-flight stops, before any DDL, if any row references a shift of another company or a missing shift. The error lists table, row id, company, shift id and the shift's real company (first 100 rows). **It never alters business data.** Preserve the listed rows as evidence (they may show the F-10 flaw being used), decide per row with the tenant (roster: clear `shift_id` or soft-delete; regularization: reject/cancel through the workflow, or clear `requested_shift_id` once decided), then re-run.
4. Run the read-only checks in the design report (section 2) on a production-shaped copy first. Results on the empty QA databases prove nothing about production.

## Locks and downtime
`SET LOCAL lock_timeout = '5s'` is the first statement. The migration is transactional: if a lock cannot be had in 5 seconds the whole revision rolls back (no partial constraints) and can simply be retried. The unique-key build briefly blocks writes to `shift` (a handful of rows per company); each FK is added `NOT VALID` and validated afterwards, which does not block reads or writes of the child table. No downtime is expected; run it in a quiet window.

## Verify
* `pg_constraint`: `shift_company_id_id_key`, `shift_roster_company_shift_fkey`, `attendance_regularization_request_company_shift_fkey` all present with `convalidated = true`.
* `alembic current` = `20261031090000`; single head.

## Rollback
`alembic downgrade 20261030090000` drops both composite FKs then the unique key; it changes no row. Limits: it re-opens the database-level gap (only the Stage 9 service check remains), and it cannot undo any data correction made before the upgrade. Downgrade followed by upgrade is repeatable (covered by test M6).

## Behaviour to know
* Deleting a shift that is referenced clears only the shift column on roster / regularization rows; `company_id` is untouched. (The application never hard-deletes shifts.) `shift_version` still blocks such a delete (RESTRICT).
* Changing a referenced shift's `company_id`, or pointing a row at another company's shift, is rejected by the database.
* The other three FKs onto `shift` (`shift_version`, `attendance_day`, `employee_assignment`) are not covered yet.

## Tests
`apps/api/tests/integration/migrations/test_shift_tenant_fk_migrations.py` (M1–M8, scratch databases) and `apps/api/tests/integration/modules/attendance/test_shift_tenant_fk_runtime_role.py` (R1–R9, raw SQL as owner and `hrms_app`).
