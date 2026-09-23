"""`onboarding_case.compensation_info` — market-parity onboarding-data pass, part 3.

Closes an existing gap: `OnboardingActivationService`'s own class docstring lists Compensation
among the employee-module services it composes, but `activate_case` never actually called
`EmployeeCompensationService`/`CompensationCreate` — there was no `compensation_info` section to
source CTC from in the first place. This adds the missing JSONB column; the section
schema/activation wiring lands in application code, not here.

Additive only (`ADD COLUMN IF NOT EXISTS`), same style as the original O1 migration
(`20260905090000_onboarding_o1.py`) that created the sibling `personal_info`/`bank_info`/
`statutory_info` columns.

Revision ID: 20260930090000
Revises: 20260929090000
"""

from alembic import op

revision = "20260930090000"
down_revision = "20260929090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_case
          ADD COLUMN IF NOT EXISTS compensation_info JSONB NOT NULL DEFAULT '{}'::jsonb;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_case
          DROP COLUMN IF EXISTS compensation_info;
        """
    )
