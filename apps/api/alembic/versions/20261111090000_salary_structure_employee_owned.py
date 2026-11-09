"""Payroll - a salary structure owned by one employee.

Lets HR start an employee from a company template and change its percentages for that one
person on the employee's Salary tab. The changed lines are saved as a structure of their own,
versioned and published like any other, so the pay-run engine reads it unchanged.

- `employee_id` set: the structure belongs to that employee only. It is left out of the
  company's structure list and cannot be assigned to anyone else. At most one per employee.
- `based_on_structure_id`: the company template it was copied from (informational).

Existing rows are company templates and stay so (both columns NULL).

Revision ID: 20261111090000
Revises: 20261110090000
"""

from alembic import op

revision = "20261111090000"
down_revision = "20261110090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE salary_structure
          ADD COLUMN IF NOT EXISTS employee_id UUID REFERENCES employee (id) ON DELETE RESTRICT,
          ADD COLUMN IF NOT EXISTS based_on_structure_id UUID
            REFERENCES salary_structure (id) ON DELETE RESTRICT;
        CREATE UNIQUE INDEX IF NOT EXISTS salary_structure_one_per_employee_idx
          ON salary_structure (employee_id)
          WHERE employee_id IS NOT NULL AND deleted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS salary_structure_one_per_employee_idx;
        ALTER TABLE salary_structure
          DROP COLUMN IF EXISTS based_on_structure_id,
          DROP COLUMN IF EXISTS employee_id;
        """
    )
