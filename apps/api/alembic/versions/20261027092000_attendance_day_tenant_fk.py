"""attendance_day must reference an employee of the SAME company (database-level invariant).

Revision ID: 20261027092000
Revises: 20261027091000

`attendance_day.employee_id -> employee.id` carried no tenant component, so a row of company A could
point at an employee of company B (B11 / DEF-B11-01 proved it through the API; B12 closed the code
path). This adds `UNIQUE (company_id, id)` on `employee` (trivially true, `id` is the primary key)
and the composite foreign key `attendance_day (company_id, employee_id) -> employee (company_id, id)`
with `ON DELETE RESTRICT` and the default `NO ACTION` on update: changing an employee's company, or an
attendance row's company/employee, to something that no longer matches is rejected. The existing
single-column FKs are left in place (their cascade/restrict behaviour is unchanged).

The migration NEVER deletes or rewrites rows. If rows already violate the invariant it stops before
any DDL and raises an error listing them (attendance_day id, company, employee, and the employee's
actual company or 'missing'); fix the data deliberately and re-run. Refuses to run as a role that is
subject to row-level security (it would see no rows). The constraint is added NOT VALID and then
validated so the validation step only needs a weak lock. Downgrade drops both constraints.
"""

# ruff: noqa: E501 - long SQL / diagnostic strings

from alembic import op

revision = "20261027092000"
down_revision = "20261027091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
          bad bigint;
          detail text;
        BEGIN
          IF NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user) THEN
            RAISE EXCEPTION 'cannot verify attendance_day tenant integrity as role %: it is subject to row-level security'
              , current_user
              USING HINT = 'Run migrations as the schema-owner role (MIGRATIONS_DATABASE_URL).';
          END IF;

          SELECT count(*) INTO bad
          FROM attendance_day a
          WHERE NOT EXISTS (
            SELECT 1 FROM employee e WHERE e.id = a.employee_id AND e.company_id = a.company_id
          );

          IF bad > 0 THEN
            SELECT string_agg(line, E'\\n' ORDER BY line) INTO detail FROM (
              SELECT format('attendance_day=%s company=%s employee=%s employee_company=%s',
                            a.id, a.company_id, a.employee_id,
                            coalesce((SELECT e.company_id::text FROM employee e WHERE e.id = a.employee_id),
                                     'missing')) AS line
              FROM attendance_day a
              WHERE NOT EXISTS (
                SELECT 1 FROM employee e WHERE e.id = a.employee_id AND e.company_id = a.company_id
              )
              ORDER BY a.id LIMIT 100
            ) s;
            RAISE EXCEPTION 'attendance_day: % row(s) reference an employee of another company; no constraint was added, no row was changed'
              , bad
              USING DETAIL = detail,
                    HINT = 'Investigate and correct or remove these rows deliberately, then re-run the upgrade. First 100 rows shown.';
          END IF;
        END $$;

        ALTER TABLE employee ADD CONSTRAINT employee_company_id_id_key UNIQUE (company_id, id);
        ALTER TABLE attendance_day
          ADD CONSTRAINT attendance_day_company_employee_fkey
          FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id)
          ON DELETE RESTRICT NOT VALID;
        ALTER TABLE attendance_day VALIDATE CONSTRAINT attendance_day_company_employee_fkey;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day DROP CONSTRAINT IF EXISTS attendance_day_company_employee_fkey;
        ALTER TABLE employee DROP CONSTRAINT IF EXISTS employee_company_id_id_key;
        """
    )
