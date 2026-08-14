"""Employee assignment (E-04) — new columns, FK constraints, indexes.

Per `docs/modules/employee/09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §6. The live
`employee_assignment` table (`scripts/sql/001_init_schema.sql:259-276`) has zero rows at the
time this migration was written (confirmed against the dev database) — every change below is
additive and safe to apply directly.

- Five new business columns: `dotted_line_manager_id`, `cost_centre_id`,
  `work_location_type`, `change_reason`, `change_type`. `shift_id` is deliberately **not**
  added here — that's E-05's own migration (plan §5), kept separate.
- Six new FK constraints, `ON DELETE SET NULL` (matches the plan's §6 deviation note and the
  organisation module's own convention for optional references): `department_id`,
  `designation_id`, `grade_id`, `branch_id` (-> their respective organisation tables),
  `reporting_manager_id`/`dotted_line_manager_id` (self-referential -> `employee.id`, mirroring
  `designation.next_designation_id`'s existing precedent). `cost_centre_id` has no FK — no
  `cost_centre` table exists anywhere in this codebase (plan §6).
- Two new indexes matching `02_EMPLOYEE_DATA_MODEL.md` §3's proposed shape: a `(company_id,
  employee_id, effective_from DESC)` covering index for "current assignment" lookups, and a
  partial `(company_id, reporting_manager_id) WHERE effective_to IS NULL` index for reporting-tree
  resolution.
- `employee_assignment_no_overlap` (the GiST exclusion constraint) and RLS are already live and
  correct — untouched by this migration except for RLS's idempotent re-assertion, matching every
  prior migration in this series.

Revision ID: 20260814100000
Revises: 20260814090000
"""

from alembic import op

revision = "20260814100000"
down_revision = "20260814090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee_assignment
          ADD COLUMN IF NOT EXISTS dotted_line_manager_id UUID,
          ADD COLUMN IF NOT EXISTS cost_centre_id UUID,
          ADD COLUMN IF NOT EXISTS work_location_type VARCHAR(20),
          ADD COLUMN IF NOT EXISTS change_reason TEXT,
          ADD COLUMN IF NOT EXISTS change_type VARCHAR(30);

        ALTER TABLE employee_assignment
          ADD CONSTRAINT employee_assignment_department_id_fkey
            FOREIGN KEY (department_id) REFERENCES department(id) ON DELETE SET NULL,
          ADD CONSTRAINT employee_assignment_designation_id_fkey
            FOREIGN KEY (designation_id) REFERENCES designation(id) ON DELETE SET NULL,
          ADD CONSTRAINT employee_assignment_grade_id_fkey
            FOREIGN KEY (grade_id) REFERENCES grade(id) ON DELETE SET NULL,
          ADD CONSTRAINT employee_assignment_branch_id_fkey
            FOREIGN KEY (branch_id) REFERENCES branch(id) ON DELETE SET NULL,
          ADD CONSTRAINT employee_assignment_reporting_manager_id_fkey
            FOREIGN KEY (reporting_manager_id) REFERENCES employee(id) ON DELETE SET NULL,
          ADD CONSTRAINT employee_assignment_dotted_line_manager_id_fkey
            FOREIGN KEY (dotted_line_manager_id) REFERENCES employee(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS employee_assignment_current_idx
          ON employee_assignment (company_id, employee_id, effective_from DESC);
        CREATE INDEX IF NOT EXISTS employee_assignment_manager_idx
          ON employee_assignment (company_id, reporting_manager_id) WHERE effective_to IS NULL;

        ALTER TABLE employee_assignment ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_assignment FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_assignment;
        CREATE POLICY tenant_isolation ON employee_assignment
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS employee_assignment_manager_idx;
        DROP INDEX IF EXISTS employee_assignment_current_idx;

        ALTER TABLE employee_assignment
          DROP CONSTRAINT IF EXISTS employee_assignment_dotted_line_manager_id_fkey,
          DROP CONSTRAINT IF EXISTS employee_assignment_reporting_manager_id_fkey,
          DROP CONSTRAINT IF EXISTS employee_assignment_branch_id_fkey,
          DROP CONSTRAINT IF EXISTS employee_assignment_grade_id_fkey,
          DROP CONSTRAINT IF EXISTS employee_assignment_designation_id_fkey,
          DROP CONSTRAINT IF EXISTS employee_assignment_department_id_fkey;

        ALTER TABLE employee_assignment
          DROP COLUMN IF EXISTS change_type,
          DROP COLUMN IF EXISTS change_reason,
          DROP COLUMN IF EXISTS work_location_type,
          DROP COLUMN IF EXISTS cost_centre_id,
          DROP COLUMN IF EXISTS dotted_line_manager_id;
        """
    )
