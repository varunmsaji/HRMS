"""Widen `approval_chain` columns to fit `MANAGER_THEN_HOD_THEN_HR` (24 chars) — both
`leave_policy_version.approval_chain` and `leave_application.approval_chain` were left at
`VARCHAR(20)` (inherited from the original L1/L4 migrations, sized for `MANAGER_THEN_HR`'s 16
chars) when the previous migration (20260917090000) widened their CHECK constraints but not the
column width itself. Found by the LD-23 integration tests failing with a real
`StringDataRightTruncationError`, not caught by ruff/mypy.

Revision ID: 20260918090000
Revises: 20260917090000
"""

from alembic import op

revision = "20260918090000"
down_revision = "20260917090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version ALTER COLUMN approval_chain TYPE VARCHAR(30);
        ALTER TABLE leave_application ALTER COLUMN approval_chain TYPE VARCHAR(30);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_application ALTER COLUMN approval_chain TYPE VARCHAR(20);
        ALTER TABLE leave_policy_version ALTER COLUMN approval_chain TYPE VARCHAR(20);
        """
    )
