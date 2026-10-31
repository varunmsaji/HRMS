"""shift_roster and attendance_regularization_request must reference a shift of the SAME company.

Revision ID: 20261031090000
Revises: 20261030090000

`shift_roster.shift_id` and `attendance_regularization_request.requested_shift_id` were plain
foreign keys to `shift(id)`. A foreign-key check ignores row-level security, so a row of company A
could point at a shift of company B (F-10; reproduced through the API, fixed in the service layer in
Stage 9). This adds the database-level backstop (design: docs/blind-audit-2026-10-29/
HRMS_STAGE10_SHIFT_COMPOSITE_FK_DESIGN.md):

* `UNIQUE (company_id, id)` on `shift` (`id` is already the primary key, so it cannot fail on data);
* `shift_roster (company_id, shift_id) -> shift (company_id, id)`;
* `attendance_regularization_request (company_id, requested_shift_id) -> shift (company_id, id)`.

Both are `MATCH SIMPLE` (the default): the check is skipped when the shift column is NULL, so
week-off roster rows and shift-less regularizations stay valid. `ON DELETE SET NULL (col)` (PostgreSQL
15+) clears only the shift column and keeps `company_id`, i.e. the same behaviour as the original
single-column FK, which is left untouched (the migration is purely additive).

The migration NEVER deletes or rewrites rows. If rows already reference a shift of another company,
or a shift that does not exist, it stops before any DDL and raises an error listing them (table, row
id, company, shift id and the shift's actual company or 'missing'); fix the data deliberately and
re-run. It refuses to run as a role that is subject to row-level security (it would see no rows),
sets a `lock_timeout` so a blocked lock aborts the whole (transactional) migration instead of
queueing behind it, and adds each FK `NOT VALID` then validates it so validation needs only a weak
lock. Downgrade drops both FKs, then the unique key; it changes no row, and it re-opens the gap.
"""

# ruff: noqa: E501 - long SQL / diagnostic strings

from alembic import op

revision = "20261031090000"
down_revision = "20261030090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        SET LOCAL lock_timeout = '5s';

        DO $$
        DECLARE
          bad bigint;
          detail text;
        BEGIN
          IF NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user) THEN
            RAISE EXCEPTION 'cannot verify shift tenant integrity as role %: it is subject to row-level security'
              , current_user
              USING HINT = 'Run migrations as the schema-owner role (MIGRATIONS_DATABASE_URL).';
          END IF;

          CREATE TEMP TABLE _shift_fk_violation ON COMMIT DROP AS
            SELECT 'shift_roster'::text AS tbl, r.id, r.company_id, r.shift_id AS shift_id,
                   coalesce((SELECT s.company_id::text FROM shift s WHERE s.id = r.shift_id), 'missing') AS shift_company
            FROM shift_roster r
            WHERE r.shift_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM shift s WHERE s.id = r.shift_id AND s.company_id = r.company_id)
            UNION ALL
            SELECT 'attendance_regularization_request', q.id, q.company_id, q.requested_shift_id,
                   coalesce((SELECT s.company_id::text FROM shift s WHERE s.id = q.requested_shift_id), 'missing')
            FROM attendance_regularization_request q
            WHERE q.requested_shift_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM shift s WHERE s.id = q.requested_shift_id AND s.company_id = q.company_id);

          SELECT count(*) INTO bad FROM _shift_fk_violation;
          IF bad > 0 THEN
            SELECT string_agg(line, E'\\n' ORDER BY line) INTO detail FROM (
              SELECT format('%s id=%s company=%s shift=%s shift_company=%s', tbl, id, company_id, shift_id, shift_company) AS line
              FROM _shift_fk_violation ORDER BY tbl, id LIMIT 100
            ) s;
            RAISE EXCEPTION 'shift references: % row(s) reference a shift of another company or a missing shift; no constraint was added, no row was changed'
              , bad
              USING DETAIL = detail,
                    HINT = 'Preserve the rows as evidence, correct or remove them deliberately, then re-run the upgrade. First 100 rows shown.';
          END IF;
        END $$;

        ALTER TABLE shift ADD CONSTRAINT shift_company_id_id_key UNIQUE (company_id, id);

        ALTER TABLE shift_roster
          ADD CONSTRAINT shift_roster_company_shift_fkey
          FOREIGN KEY (company_id, shift_id) REFERENCES shift (company_id, id)
          ON DELETE SET NULL (shift_id) NOT VALID;
        ALTER TABLE shift_roster VALIDATE CONSTRAINT shift_roster_company_shift_fkey;

        ALTER TABLE attendance_regularization_request
          ADD CONSTRAINT attendance_regularization_request_company_shift_fkey
          FOREIGN KEY (company_id, requested_shift_id) REFERENCES shift (company_id, id)
          ON DELETE SET NULL (requested_shift_id) NOT VALID;
        ALTER TABLE attendance_regularization_request
          VALIDATE CONSTRAINT attendance_regularization_request_company_shift_fkey;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE attendance_regularization_request
          DROP CONSTRAINT IF EXISTS attendance_regularization_request_company_shift_fkey;
        ALTER TABLE shift_roster DROP CONSTRAINT IF EXISTS shift_roster_company_shift_fkey;
        ALTER TABLE shift DROP CONSTRAINT IF EXISTS shift_company_id_id_key;
        """
    )
