"""`onboarding_case.previous_employment_info` — market-parity onboarding-data pass, part 4.

`{"items": [...]}` — a list wrapped in a dict so this column fits the same
`dict[str, object]` shape every other onboarding section uses (`PreviousEmploymentSection`'s own
docstring). Additive only, same style as the O1 migration's original JSONB columns.

Revision ID: 20261001092000
Revises: 20261001091000
"""

from alembic import op

revision = "20261001092000"
down_revision = "20261001091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_case
          ADD COLUMN IF NOT EXISTS previous_employment_info JSONB NOT NULL DEFAULT '{}'::jsonb;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE onboarding_case
          DROP COLUMN IF EXISTS previous_employment_info;
        """
    )
