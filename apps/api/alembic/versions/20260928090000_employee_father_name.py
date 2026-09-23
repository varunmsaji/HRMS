"""Employee identity — `father_or_husband_name`.

Market-parity onboarding-data pass: EPF Form 11 field 2 (father's/husband's name) is a
near-universal field on every Indian HRMS onboarding form; `employee` had no equivalent column.
Plain, not `_enc` — same sensitivity tier as `first_name`/`last_name`, not PAN/Aadhaar-grade.

Additive only (`ADD COLUMN IF NOT EXISTS`), same style as `20260813180000_employee_foundation.py`
— no RLS/constraint changes needed, `employee` is already RLS-protected.

Revision ID: 20260928090000
Revises: 20260927090000
"""

from alembic import op

revision = "20260928090000"
down_revision = "20260927090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee
          ADD COLUMN IF NOT EXISTS father_or_husband_name VARCHAR(150);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee
          DROP COLUMN IF EXISTS father_or_husband_name;
        """
    )
