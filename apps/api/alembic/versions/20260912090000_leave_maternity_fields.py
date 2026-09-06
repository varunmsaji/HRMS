"""Maternity leave — informational fields (client spec §F, LEAVE_DECISION_LOG.md LD-17).

`expected_delivery_date` on `leave_application` (nullable, generic — harmless for every other
leave type, same posture as the existing generic `attachment_reference`/`half_day` fields).
`pre_delivery_days`/`post_delivery_days` on `leave_policy_version` — HR-documented entitlement
split (e.g. "6 weeks pre + 20 weeks post"), purely informational; day-counting still just uses
`start_date`/`end_date` like every other leave type, this is not enforced against them.

Revision ID: 20260912090000
Revises: 20260911090000
"""

from alembic import op

revision = "20260912090000"
down_revision = "20260911090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_application
          ADD COLUMN IF NOT EXISTS expected_delivery_date DATE;

        ALTER TABLE leave_policy_version
          ADD COLUMN IF NOT EXISTS pre_delivery_days INTEGER,
          ADD COLUMN IF NOT EXISTS post_delivery_days INTEGER;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_application
          DROP COLUMN IF EXISTS expected_delivery_date;

        ALTER TABLE leave_policy_version
          DROP COLUMN IF EXISTS pre_delivery_days,
          DROP COLUMN IF EXISTS post_delivery_days;
        """
    )
