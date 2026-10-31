"""Attendance policy: how early a self-service punch-in may be, before the shift starts.

Revision ID: 20261102090000
Revises: 20261101090000

Adds `attendance_policy_version.early_in_allowance_minutes`, a nullable integer. NULL means "no
early limit", which is what every existing row (published or draft) reads after this migration, so
punch behaviour is unchanged until a policy version sets it. The column is purely additive: no row
is rewritten and no existing column or default is touched.
"""

from alembic import op

revision = "20261102090000"
down_revision = "20261101090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_policy_version
          ADD COLUMN IF NOT EXISTS early_in_allowance_minutes INTEGER;
        ALTER TABLE attendance_policy_version
          ADD CONSTRAINT attendance_policy_version_early_in_allowance_check
            CHECK (early_in_allowance_minutes IS NULL OR early_in_allowance_minutes >= 0);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_policy_version
          DROP CONSTRAINT IF EXISTS attendance_policy_version_early_in_allowance_check,
          DROP COLUMN IF EXISTS early_in_allowance_minutes;
        """
    )
