"""`onboarding_case.education_info` — market-parity onboarding-data pass, part 5.

Same `{"items": [...]}` shape as `previous_employment_info`. Additive only.

Revision ID: 20261002091000
Revises: 20261002090000
"""

from alembic import op

revision = "20261002091000"
down_revision = "20261002090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_case
          ADD COLUMN IF NOT EXISTS education_info JSONB NOT NULL DEFAULT '{}'::jsonb;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_case
          DROP COLUMN IF EXISTS education_info;
        """
    )
