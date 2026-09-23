"""Payroll input correctness, step 1b — `attendance_day.weekly_off_fraction` (PAY-012,
`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 3).

The paid off share of a half-day weekly off (`0.50`), `0.00` otherwise. Existing rows default to
`0.00`: before this revision a half-day weekly off was computed as a full weekly off, so no
existing row has a split to record — unlocked half-day weekly-off days pick up the correct split
on their next recompute (the nightly job recomputes the trailing days; older unlocked days need
a manual recompute or the range backfill).

Revision ID: 20261004091000
Revises: 20261004090000
"""

from alembic import op

revision = "20261004091000"
down_revision = "20261004090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day
          ADD COLUMN IF NOT EXISTS weekly_off_fraction NUMERIC(3, 2) NOT NULL DEFAULT 0;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day
          DROP COLUMN IF EXISTS weekly_off_fraction;
        """
    )
