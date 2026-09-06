"""Overtime — `comp_off_day_length_minutes` on `overtime_policy_version`.

Per `docs/architecture/LEAVE_DECISION_LOG.md` LD-14: Leave's L5 comp-off credit engine needs to
convert `OvertimeRecord.comp_off_minutes` into `leave_ledger.amount` (days), and nothing in the
schema previously expressed "how many minutes make one day" for this purpose. Added next to the
existing `comp_off_instead_of_pay`/`comp_off_expiry_days` fields on the same table, following the
same "policy-configured, not hardcoded" convention as every other rate/threshold in this codebase
— an 8-hour day is `480`, but this is never assumed in code.

A plain nullable `ADD COLUMN` regardless of current row counts — existing published versions
simply have no day-length configured until an admin sets one on their next draft, and the
comp-off credit engine skips crediting for a policy version with no value set (mirrors
`LeaveAccrualService`'s existing "skip if not configured" posture for `accrual_rate_per_cycle`).

Revision ID: 20260908090000
Revises: 20260907090000
"""

from alembic import op

revision = "20260908090000"
down_revision = "20260907090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE overtime_policy_version
          ADD COLUMN IF NOT EXISTS comp_off_day_length_minutes INTEGER;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE overtime_policy_version
          DROP COLUMN IF EXISTS comp_off_day_length_minutes;
        """
    )
