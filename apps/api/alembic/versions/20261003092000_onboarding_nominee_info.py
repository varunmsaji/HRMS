"""`onboarding_case.nominee_info` — market-parity onboarding-data pass, part 6.

Same `{"items": [...]}` shape as `education_info`/`previous_employment_info`. Additive only.

Revision ID: 20261003092000
Revises: 20261003091000
"""

from alembic import op

revision = "20261003092000"
down_revision = "20261003091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_case
          ADD COLUMN IF NOT EXISTS nominee_info JSONB NOT NULL DEFAULT '{}'::jsonb;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_case
          DROP COLUMN IF EXISTS nominee_info;
        """
    )
