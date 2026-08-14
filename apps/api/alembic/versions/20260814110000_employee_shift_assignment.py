"""Employee shift assignment (E-05) — `employee_assignment.shift_id`.

Per `docs/modules/employee/13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §6/§7. The live
`employee_assignment` table has zero rows at the time this migration was written (confirmed
against the dev database) — this is a purely additive change, no backfill required.

- One new column: `shift_id`, nullable UUID.
- One new FK constraint, `ON DELETE SET NULL` (matches every other optional reference FK on this
  table — `department_id`/`designation_id`/`grade_id`/`branch_id`/`reporting_manager_id`/
  `dotted_line_manager_id`), to `shift(id)`.
- No new index — no source calls for one (plan §7.1); Shift itself is never hard-deleted in this
  codebase (only soft-deactivated), so the FK's `ON DELETE SET NULL` exists for referential
  integrity/defensive correctness rather than a routinely-exercised path.
- RLS/GiST exclusion/tenant isolation on `employee_assignment` are already live and correct —
  untouched by this migration.

Revision ID: 20260814110000
Revises: 20260814100000
"""

from alembic import op

revision = "20260814110000"
down_revision = "20260814100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee_assignment
          ADD COLUMN IF NOT EXISTS shift_id UUID;

        ALTER TABLE employee_assignment
          ADD CONSTRAINT employee_assignment_shift_id_fkey
            FOREIGN KEY (shift_id) REFERENCES shift(id) ON DELETE SET NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee_assignment
          DROP CONSTRAINT IF EXISTS employee_assignment_shift_id_fkey;

        ALTER TABLE employee_assignment
          DROP COLUMN IF EXISTS shift_id;
        """
    )
