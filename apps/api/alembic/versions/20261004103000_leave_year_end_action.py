"""Leave balance safety, step 2 — year-end rule per leave type
(`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 11).

- `leave_policy_version.year_end_action` — what happens to the balance at leave-year start:
  `CARRY_FORWARD` (default; today's behaviour — carried up to `max_carry_forward_days`, the excess
  lapses), `LAPSE` (the whole positive balance lapses — e.g. casual leave), or `ENCASH_EXCESS`
  (carried up to the cap, the excess written as an `ENCASHMENT` entry that payroll pays — e.g.
  earned leave). Every existing version keeps `CARRY_FORWARD`, so nothing changes until HR opts in.
- DAT-001 for the new system-written `ENCASHMENT`: one per employee, leave type and leave-year
  start. Only rows with a `reference_id` (the policy version) — HR's manual encashments have none
  and stay unrestricted.

Revision ID: 20261004103000
Revises: 20261004102000
"""

from alembic import op

revision = "20261004103000"
down_revision = "20261004102000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
          ADD COLUMN IF NOT EXISTS year_end_action VARCHAR(20) NOT NULL DEFAULT 'CARRY_FORWARD';

        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'leave_policy_version_year_end_action_check'
          ) THEN
            ALTER TABLE leave_policy_version
              ADD CONSTRAINT leave_policy_version_year_end_action_check
              CHECK (year_end_action IN ('CARRY_FORWARD', 'LAPSE', 'ENCASH_EXCESS'));
          END IF;
        END $$;

        CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_ledger_year_end_encashment
          ON leave_ledger (company_id, employee_id, leave_type_id, effective_date)
          WHERE entry_type = 'ENCASHMENT' AND reference_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_leave_ledger_year_end_encashment;
        ALTER TABLE leave_policy_version
          DROP CONSTRAINT IF EXISTS leave_policy_version_year_end_action_check,
          DROP COLUMN IF EXISTS year_end_action;
        """
    )
