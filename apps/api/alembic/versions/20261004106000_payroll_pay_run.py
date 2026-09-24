"""Payroll Phase 5.2 — the pay run (`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`).

- `payroll_setting` — one row per company: the variance threshold (D10, default 15 %).
- `pay_run` — one per (legal entity, calendar month) (decisions 14/18, FR-PAY-025), lifecycle
  `DRAFT → INPUTS_LOCKED → COMPUTED → APPROVED → FINALISED → PAID`.
- `pay_run_employee` — the per-employee input snapshot (ADR-0005) and computed totals, validation
  issues and the variance against the previous finalised run (FR-PAY-014/015).
- `pay_run_line` — one row per employee per component with its calculation trace (FR-PAY-024).
- A finalised run never changes (decision 15, ADR-0005). Enforced in `PayRunRepository` — every
  write is conditioned on the run not being `FINALISED`/`PAID` (other than `FINALISED → PAID`),
  the same code-level posture as the append-only `leave_ledger`.
- New permissions `PAYROLL.RUN_VIEW`, `PAYROLL.RUN_PROCESS` (COMPANY_ADMIN + HR_ADMIN) and
  `PAYROLL.RUN_APPROVE` (COMPANY_ADMIN) at `COMPANY` scope (D9 — the approver must not be the
  user who computed the run, enforced in the service).

Revision ID: 20261004106000
Revises: 20261004105000
"""

from alembic import op

revision = "20261004106000"
down_revision = "20261004105000"
branch_labels = None
depends_on = None

_TABLES = ("pay_run_line", "pay_run_employee", "pay_run", "payroll_setting")

_PERMISSIONS = (
    ("PAYROLL.RUN_VIEW", "View pay runs and their employee pay", ("COMPANY_ADMIN", "HR_ADMIN")),
    (
        "PAYROLL.RUN_PROCESS",
        "Create pay runs, lock inputs, compute, acknowledge variances and roll back",
        ("COMPANY_ADMIN", "HR_ADMIN"),
    ),
    ("PAYROLL.RUN_APPROVE", "Approve, finalise and mark pay runs paid", ("COMPANY_ADMIN",)),
)


def _rls(table: str) -> str:
    return f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        CREATE POLICY tenant_isolation ON {table}
          USING (company_id = current_setting('app.company_id', true)::uuid);
    """


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_setting (
            company_id UUID PRIMARY KEY REFERENCES company (id) ON DELETE RESTRICT,
            variance_threshold_percent NUMERIC(5, 2) NOT NULL DEFAULT 15
              CHECK (variance_threshold_percent > 0 AND variance_threshold_percent <= 100),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            version INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS pay_run (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            legal_entity_id UUID NOT NULL REFERENCES legal_entity (id) ON DELETE RESTRICT,
            period_month DATE NOT NULL CHECK (EXTRACT(DAY FROM period_month) = 1),
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            days_in_month INTEGER NOT NULL CHECK (days_in_month BETWEEN 28 AND 31),
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
              'DRAFT', 'INPUTS_LOCKED', 'COMPUTED', 'APPROVED', 'FINALISED', 'PAID'
            )),
            pay_date DATE NOT NULL,
            attendance_period_id UUID REFERENCES attendance_period (id) ON DELETE RESTRICT,
            attendance_period_version INTEGER,
            variance_threshold_percent NUMERIC(5, 2),
            previous_pay_run_id UUID REFERENCES pay_run (id),
            employee_count INTEGER NOT NULL DEFAULT 0,
            gross_minor BIGINT NOT NULL DEFAULT 0,
            deductions_minor BIGINT NOT NULL DEFAULT 0,
            employer_contributions_minor BIGINT NOT NULL DEFAULT 0,
            net_minor BIGINT NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            variance_flag_count INTEGER NOT NULL DEFAULT 0,
            variance_open_count INTEGER NOT NULL DEFAULT 0,
            created_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            inputs_locked_at TIMESTAMPTZ,
            inputs_locked_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            computed_at TIMESTAMPTZ,
            computed_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            approved_at TIMESTAMPTZ,
            approved_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            finalised_at TIMESTAMPTZ,
            finalised_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            paid_at TIMESTAMPTZ,
            paid_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            last_rollback_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT pay_run_entity_month_uq UNIQUE (company_id, legal_entity_id, period_month)
        );
        CREATE INDEX IF NOT EXISTS pay_run_period_idx ON pay_run (attendance_period_id);

        CREATE TABLE IF NOT EXISTS pay_run_employee (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            pay_run_id UUID NOT NULL REFERENCES pay_run (id) ON DELETE CASCADE,
            employee_id UUID NOT NULL REFERENCES employee (id) ON DELETE RESTRICT,
            employee_code VARCHAR(50),
            employee_name VARCHAR(300),
            pay_basis VARCHAR(20),
            paid_days NUMERIC(6, 2),
            lop_days NUMERIC(6, 2),
            payable_days NUMERIC(6, 2),
            snapshot JSONB NOT NULL,
            is_computed BOOLEAN NOT NULL DEFAULT false,
            gross_minor BIGINT NOT NULL DEFAULT 0,
            deductions_minor BIGINT NOT NULL DEFAULT 0,
            employer_contributions_minor BIGINT NOT NULL DEFAULT 0,
            net_before_rounding_minor BIGINT NOT NULL DEFAULT 0,
            rounding_minor BIGINT NOT NULL DEFAULT 0,
            net_minor BIGINT NOT NULL DEFAULT 0,
            issues JSONB NOT NULL DEFAULT '[]'::jsonb,
            has_error BOOLEAN NOT NULL DEFAULT false,
            previous_net_minor BIGINT,
            variance_percent NUMERIC(9, 2),
            variance_flagged BOOLEAN NOT NULL DEFAULT false,
            variance_reason TEXT,
            variance_acknowledged_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            variance_acknowledged_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pay_run_employee_uq UNIQUE (pay_run_id, employee_id)
        );
        CREATE INDEX IF NOT EXISTS pay_run_employee_employee_idx
          ON pay_run_employee (employee_id);

        CREATE TABLE IF NOT EXISTS pay_run_line (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            pay_run_id UUID NOT NULL REFERENCES pay_run (id) ON DELETE CASCADE,
            pay_run_employee_id UUID NOT NULL REFERENCES pay_run_employee (id) ON DELETE CASCADE,
            employee_id UUID NOT NULL REFERENCES employee (id) ON DELETE RESTRICT,
            component_code VARCHAR(30) NOT NULL,
            component_name VARCHAR(150) NOT NULL,
            line_type VARCHAR(25) NOT NULL CHECK (line_type IN (
              'EARNING', 'DEDUCTION', 'EMPLOYER_CONTRIBUTION', 'ROUNDING'
            )),
            full_monthly_minor BIGINT,
            amount_minor BIGINT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            trace JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pay_run_line_uq UNIQUE (pay_run_employee_id, component_code)
        );
        CREATE INDEX IF NOT EXISTS pay_run_line_run_idx ON pay_run_line (pay_run_id);

        """
    )
    op.execute("".join(_rls(table) for table in _TABLES))
    for code, description, roles in _PERMISSIONS:
        role_list = ", ".join(f"'{role}'" for role in roles)
        op.execute(
            f"""
            INSERT INTO permission (id, code, domain, description)
            VALUES (gen_random_uuid(), '{code}', 'PAYROLL', '{description}')
            ON CONFLICT (code) DO NOTHING;

            INSERT INTO role_permission (role_id, permission_id, data_scope)
            SELECT r.id, p.id, 'COMPANY'
            FROM role r
            JOIN permission p ON p.code = '{code}'
            WHERE r.code IN ({role_list}) AND r.deleted_at IS NULL
            ON CONFLICT (role_id, permission_id) DO NOTHING;
            """
        )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _, _ in _PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM role_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code IN ({codes}));
        DELETE FROM permission WHERE code IN ({codes});
        """
    )
    op.execute("".join(f"DROP TABLE IF EXISTS {table};" for table in _TABLES))
