"""Payroll input correctness, step 1b — `employment.pay_basis` (BUS-001,
`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 1) and `attendance_day.unpaid_off_fraction`.

- `employment.pay_basis`: `MONTHLY` (default — every existing employment, matching the
  behaviour so far) or `DAILY_WAGE`.
- `attendance_day.unpaid_off_fraction`: the share of a day that is an **unpaid** off day — a
  weekly off / company holiday / shutdown for a daily-wage employee, or any holiday marked
  `is_paid = false`. Neither paid nor loss of pay. With it every employed day satisfies
  `paid + lop + unpaid_off = 1.00`. Existing rows default to `0.00` (before this revision every
  off day was computed as paid).

Revision ID: 20261004093000
Revises: 20261004092000
"""

from alembic import op

revision = "20261004093000"
down_revision = "20261004092000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employment
          ADD COLUMN IF NOT EXISTS pay_basis VARCHAR(20) NOT NULL DEFAULT 'MONTHLY';

        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'employment_pay_basis_check'
          ) THEN
            ALTER TABLE employment
              ADD CONSTRAINT employment_pay_basis_check
              CHECK (pay_basis IN ('MONTHLY', 'DAILY_WAGE'));
          END IF;
        END $$;

        ALTER TABLE attendance_day
          ADD COLUMN IF NOT EXISTS unpaid_off_fraction NUMERIC(3, 2) NOT NULL DEFAULT 0;

        ALTER TABLE attendance_period_summary
          ADD COLUMN IF NOT EXISTS unpaid_off_days NUMERIC(6, 2);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_period_summary DROP COLUMN IF EXISTS unpaid_off_days;
        ALTER TABLE attendance_day DROP COLUMN IF EXISTS unpaid_off_fraction;
        ALTER TABLE employment
          DROP CONSTRAINT IF EXISTS employment_pay_basis_check,
          DROP COLUMN IF EXISTS pay_basis;
        """
    )
