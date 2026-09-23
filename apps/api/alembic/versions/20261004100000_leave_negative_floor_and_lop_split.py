"""Leave balance safety, step 2a — PAY-010 / PAY-011 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`
decisions 8 and 9).

- `leave_policy_version.negative_balance_floor`: how far below zero the balance may go when
  `allow_negative_balance` is on (e.g. `3.00` = down to −3). Required to publish a version with
  `allow_negative_balance = true`; NULL is read as 0, so every existing version keeps the
  never-negative behaviour it had (the switch was stored but never enforced).
- `leave_application.lop_days` / `leave_application_day.is_lop`: when an approver approves an
  application the balance can no longer cover ("approve with excess as LOP"), the uncovered days
  are projected to attendance as unpaid leave and only the covered days are debited.

Revision ID: 20261004100000
Revises: 20261004095000
"""

from alembic import op

revision = "20261004100000"
down_revision = "20261004095000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          ADD COLUMN IF NOT EXISTS negative_balance_floor NUMERIC(5, 2);

        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'leave_policy_version_negative_floor_check'
          ) THEN
            ALTER TABLE leave_policy_version
              ADD CONSTRAINT leave_policy_version_negative_floor_check
              CHECK (negative_balance_floor IS NULL OR negative_balance_floor >= 0);
          END IF;
        END $$;

        ALTER TABLE leave_application
          ADD COLUMN IF NOT EXISTS lop_days NUMERIC(6, 2) NOT NULL DEFAULT 0;

        ALTER TABLE leave_application_day
          ADD COLUMN IF NOT EXISTS is_lop BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_application_day DROP COLUMN IF EXISTS is_lop;
        ALTER TABLE leave_application DROP COLUMN IF EXISTS lop_days;
        ALTER TABLE leave_policy_version
          DROP CONSTRAINT IF EXISTS leave_policy_version_negative_floor_check,
          DROP COLUMN IF EXISTS negative_balance_floor;
        """
    )
