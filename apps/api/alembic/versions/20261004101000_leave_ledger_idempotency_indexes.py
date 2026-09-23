"""Leave balance safety, step 2 — DAT-001: database-enforced idempotency for system-written
leave ledger entries.

`run_for_company` / `run_year_end_for_company` / `credit_company` each check "already written?"
and then insert, with nothing stopping two concurrent runs (Celery Beat has no leader election,
OPS-006) from both inserting. These partial unique indexes make the second insert a no-op
(`INSERT … ON CONFLICT DO NOTHING` in `LeaveLedgerRepository.insert_if_absent`):

- one `ACCRUAL` / `CARRY_FORWARD` entry per employee, leave type and cycle date;
- one `COMP_OFF_CREDIT` per source overtime record (`reference_id`).

Fails loudly if duplicates already exist — they are double credits and need a human decision.

Revision ID: 20261004101000
Revises: 20261004100000
"""

from alembic import op

revision = "20261004101000"
down_revision = "20261004100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_ledger_cycle_entry
          ON leave_ledger (company_id, employee_id, leave_type_id, entry_type, effective_date)
          WHERE entry_type IN ('ACCRUAL', 'CARRY_FORWARD');

        CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_ledger_comp_off_credit
          ON leave_ledger (company_id, reference_id)
          WHERE entry_type = 'COMP_OFF_CREDIT';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_leave_ledger_comp_off_credit;
        DROP INDEX IF EXISTS uq_leave_ledger_cycle_entry;
        """
    )
