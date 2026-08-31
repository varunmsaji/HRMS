"""L2 — new `leave_ledger` table (append-only, ADR-0004/DEC-004).

Per docs/architecture/LEAVE_DECISION_LOG.md LD-02/LD-03/LD-09 (slice L2): balance for an
(employee, leave_type) pair is always `SUM(amount)` over this table — no column anywhere stores
a mutable balance. `entry_type` is CHECK-restricted to the six kinds LD-02 already locked the
shape of; this slice's application code only ever inserts `ADJUSTMENT` rows (manual HR
corrections) — `ACCRUAL` (L3), `APPLICATION`/`ENCASHMENT`/`CARRY_FORWARD` (L4), and
`COMP_OFF_CREDIT` (L5) are reserved values, not yet written by anything.

No GiST/uniqueness constraint on this table — unlike the identity/version tables in L1, a
ledger is intentionally append-only with no "current row" concept to deduplicate against; any
number of entries may share an (employee_id, leave_type_id) pair by design.

Revision ID: 20260901090000
Revises: 20260830090000
"""

from alembic import op

revision = "20260901090000"
down_revision = "20260830090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_ledger (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "leave_type_id" UUID NOT NULL,
            "entry_type" VARCHAR(20) NOT NULL,
            "amount" NUMERIC(6, 2) NOT NULL,
            "effective_date" DATE NOT NULL,
            "reference_id" UUID,
            "reason" TEXT,
            "created_by_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "leave_ledger_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_ledger_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_ledger_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_ledger_leave_type_id_fkey" FOREIGN KEY ("leave_type_id")
              REFERENCES "leave_type"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_ledger_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_ledger_entry_type_check"
              CHECK (entry_type IN (
                'ACCRUAL', 'APPLICATION', 'ADJUSTMENT', 'ENCASHMENT', 'CARRY_FORWARD',
                'COMP_OFF_CREDIT'
              )),
            CONSTRAINT "leave_ledger_amount_nonzero_check" CHECK (amount <> 0)
        );

        CREATE INDEX IF NOT EXISTS leave_ledger_company_id_idx ON leave_ledger (company_id);
        CREATE INDEX IF NOT EXISTS leave_ledger_balance_lookup_idx
          ON leave_ledger (company_id, employee_id, leave_type_id);

        ALTER TABLE leave_ledger ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_ledger FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_ledger;
        CREATE POLICY tenant_isolation ON leave_ledger
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leave_ledger;")
