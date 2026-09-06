"""Probation-based leave rules — new fields on `leave_policy_version` (client spec §9,
LEAVE_DECISION_LOG.md LD-18).

`allowed_during_probation` gates whether an employee whose `Employee.status = 'PROBATION'` may
submit an application at all for this policy's leave type. `accrue_during_probation` gates
whether the monthly accrual engine credits such an employee. Both default `true` — this
preserves today's exact behavior (neither submission nor accrual currently look at
`Employee.status` at all) for every existing policy version; nothing changes until HR explicitly
turns one off.

Revision ID: 20260913090000
Revises: 20260912090000
"""

from alembic import op

revision = "20260913090000"
down_revision = "20260912090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          ADD COLUMN IF NOT EXISTS allowed_during_probation BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS accrue_during_probation BOOLEAN NOT NULL DEFAULT true;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          DROP COLUMN IF EXISTS allowed_during_probation,
          DROP COLUMN IF EXISTS accrue_during_probation;
        """
    )
