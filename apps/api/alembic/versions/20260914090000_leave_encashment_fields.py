"""Encashment detail — config fields on `leave_policy_version` (client spec §12,
LEAVE_DECISION_LOG.md LD-19).

`max_encashment_days`/`min_balance_after_encashment` are enforced by the new dedicated
`POST /leave-ledger/encashments` path — both nullable, no limit assumed when unset.
`encashment_frequency`/`encashment_calculation_basis` are informational only (LD-19): frequency
enforcement would need a leave-year concept this codebase hasn't decided yet (same open item
blocking yearly accrual), and calculation basis is a Payroll concern — Payroll doesn't exist as a
module yet, so this is documented config for it to read once it does, not something Leave
computes a currency amount from.

Revision ID: 20260914090000
Revises: 20260913090000
"""

from alembic import op

revision = "20260914090000"
down_revision = "20260913090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          ADD COLUMN IF NOT EXISTS max_encashment_days NUMERIC(5, 2),
          ADD COLUMN IF NOT EXISTS min_balance_after_encashment NUMERIC(5, 2),
          ADD COLUMN IF NOT EXISTS encashment_frequency VARCHAR(20),
          ADD COLUMN IF NOT EXISTS encashment_calculation_basis VARCHAR(50);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          DROP COLUMN IF EXISTS max_encashment_days,
          DROP COLUMN IF EXISTS min_balance_after_encashment,
          DROP COLUMN IF EXISTS encashment_frequency,
          DROP COLUMN IF EXISTS encashment_calculation_basis;
        """
    )
