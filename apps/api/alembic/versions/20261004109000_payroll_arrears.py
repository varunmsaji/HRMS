"""Payroll Phase 5.5 — arrears (`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`,
FR-PAY-010, AC-PAY-023.1, decision 15 / D7).

- `pay_adjustment` — a correction to a finalised month's paid days (D7: the finalised attendance
  period stays closed; the correction is paid as arrears by the entity's next pay run). `PENDING`
  until the run that pays it is finalised, then `APPLIED` with that run's id.
- `pay_run_arrear` — which month, and which earlier finalised run, each arrears amount in a run
  belongs to, per component. What has already been paid for a month is that month's run plus the
  arrears rows of finalised runs for it — so arrears are never paid twice.

Revision ID: 20261004109000
Revises: 20261004108000
"""

from alembic import op

revision = "20261004109000"
down_revision = "20261004108000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pay_adjustment (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            legal_entity_id UUID NOT NULL REFERENCES legal_entity (id) ON DELETE RESTRICT,
            employee_id UUID NOT NULL REFERENCES employee (id) ON DELETE RESTRICT,
            for_month DATE NOT NULL CHECK (EXTRACT(DAY FROM for_month) = 1),
            source_pay_run_id UUID NOT NULL REFERENCES pay_run (id) ON DELETE RESTRICT,
            paid_days_delta NUMERIC(6, 2) NOT NULL CHECK (paid_days_delta <> 0),
            reason TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
              CHECK (status IN ('PENDING', 'APPLIED')),
            applied_pay_run_id UUID REFERENCES pay_run (id) ON DELETE RESTRICT,
            created_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT pay_adjustment_applied_check CHECK (
              (status = 'APPLIED') = (applied_pay_run_id IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS pay_adjustment_lookup_idx
          ON pay_adjustment (company_id, legal_entity_id, status);

        CREATE TABLE IF NOT EXISTS pay_run_arrear (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            pay_run_id UUID NOT NULL REFERENCES pay_run (id) ON DELETE CASCADE,
            employee_id UUID NOT NULL REFERENCES employee (id) ON DELETE RESTRICT,
            for_month DATE NOT NULL,
            source_pay_run_id UUID NOT NULL REFERENCES pay_run (id) ON DELETE RESTRICT,
            component_code VARCHAR(30) NOT NULL,
            line_type VARCHAR(25) NOT NULL,
            amount_minor BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS pay_run_arrear_lookup_idx
          ON pay_run_arrear (company_id, employee_id, for_month);
        CREATE INDEX IF NOT EXISTS pay_run_arrear_run_idx ON pay_run_arrear (pay_run_id);
        """
    )
    for table in ("pay_adjustment", "pay_run_arrear"):
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            DROP POLICY IF EXISTS tenant_isolation ON {table};
            CREATE POLICY tenant_isolation ON {table}
              USING (company_id = current_setting('app.company_id', true)::uuid);
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pay_run_arrear; DROP TABLE IF EXISTS pay_adjustment;")
