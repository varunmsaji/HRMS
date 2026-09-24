"""Payroll Phase 5.1 — salary components, salary structures and employee salary assignment
(`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`, decisions D1–D6).

- `salary_component`, `salary_structure`, `salary_structure_version`, `salary_structure_line`,
  `employee_salary` — every table tenant-scoped with the standard `tenant_isolation` RLS policy.
- `employee_salary` carries no CTC (that stays on `employee_compensation`): exactly one of a
  structure (monthly-paid) or a daily rate (daily-wage, D5); no overlapping rows per employee.
- New permission `PAYROLL.SETUP_MANAGE`, granted at `COMPANY` scope to `COMPANY_ADMIN` and
  `HR_ADMIN` in every existing company (`register_company` does the same for new ones).

Default components and structures are seeded per company by the service on first use, not here.

Revision ID: 20261004105000
Revises: 20261004104000
"""

from alembic import op

revision = "20261004105000"
down_revision = "20261004104000"
branch_labels = None
depends_on = None

_TABLES = (
    "employee_salary",
    "salary_structure_line",
    "salary_structure_version",
    "salary_structure",
    "salary_component",
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
        CREATE TABLE IF NOT EXISTS salary_component (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            code VARCHAR(30) NOT NULL,
            name VARCHAR(150) NOT NULL,
            component_type VARCHAR(25) NOT NULL
              CHECK (component_type IN ('EARNING', 'DEDUCTION', 'EMPLOYER_CONTRIBUTION')),
            is_system BOOLEAN NOT NULL DEFAULT false,
            is_taxable BOOLEAN NOT NULL DEFAULT true,
            is_pf_wage BOOLEAN NOT NULL DEFAULT false,
            is_esi_wage BOOLEAN NOT NULL DEFAULT false,
            is_prorated BOOLEAN NOT NULL DEFAULT true,
            show_on_payslip BOOLEAN NOT NULL DEFAULT true,
            display_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1
        );
        CREATE UNIQUE INDEX IF NOT EXISTS salary_component_company_code_idx
          ON salary_component (company_id, code) WHERE deleted_at IS NULL;

        CREATE TABLE IF NOT EXISTS salary_structure (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            code VARCHAR(30) NOT NULL,
            name VARCHAR(150) NOT NULL,
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1
        );
        CREATE UNIQUE INDEX IF NOT EXISTS salary_structure_company_code_idx
          ON salary_structure (company_id, code) WHERE deleted_at IS NULL;

        CREATE TABLE IF NOT EXISTS salary_structure_version (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            salary_structure_id UUID NOT NULL REFERENCES salary_structure (id) ON DELETE RESTRICT,
            version_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'PUBLISHED')),
            effective_from DATE,
            effective_to DATE,
            published_at TIMESTAMPTZ,
            published_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT salary_structure_version_number_uq
              UNIQUE (salary_structure_id, version_number),
            CONSTRAINT salary_structure_version_published_dates_check CHECK (
              status = 'DRAFT' OR effective_from IS NOT NULL
            ),
            CONSTRAINT salary_structure_version_range_check CHECK (
              effective_to IS NULL OR effective_to >= effective_from
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS salary_structure_version_one_draft_idx
          ON salary_structure_version (salary_structure_id) WHERE status = 'DRAFT';
        CREATE INDEX IF NOT EXISTS salary_structure_version_structure_idx
          ON salary_structure_version (salary_structure_id);

        CREATE TABLE IF NOT EXISTS salary_structure_line (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            salary_structure_version_id UUID NOT NULL
              REFERENCES salary_structure_version (id) ON DELETE CASCADE,
            salary_component_id UUID NOT NULL REFERENCES salary_component (id) ON DELETE RESTRICT,
            calculation_type VARCHAR(30) NOT NULL CHECK (calculation_type IN (
              'FIXED', 'PERCENTAGE_OF_CTC', 'PERCENTAGE_OF_GROSS', 'PERCENTAGE_OF_COMPONENT',
              'BALANCING'
            )),
            percentage NUMERIC(7, 4),
            amount_monthly_minor BIGINT,
            base_salary_component_id UUID REFERENCES salary_component (id) ON DELETE RESTRICT,
            max_monthly_minor BIGINT,
            applies_when VARCHAR(20) NOT NULL DEFAULT 'ALWAYS'
              CHECK (applies_when IN ('ALWAYS', 'PF_APPLICABLE', 'ESI_APPLICABLE')),
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT salary_structure_line_component_uq
              UNIQUE (salary_structure_version_id, salary_component_id)
        );
        CREATE INDEX IF NOT EXISTS salary_structure_line_version_idx
          ON salary_structure_line (salary_structure_version_id);

        CREATE TABLE IF NOT EXISTS employee_salary (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            employee_id UUID NOT NULL REFERENCES employee (id) ON DELETE RESTRICT,
            salary_structure_id UUID REFERENCES salary_structure (id) ON DELETE RESTRICT,
            daily_rate_minor BIGINT CHECK (daily_rate_minor IS NULL OR daily_rate_minor > 0),
            effective_from DATE NOT NULL,
            effective_to DATE,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT employee_salary_basis_check CHECK (
              (salary_structure_id IS NOT NULL) <> (daily_rate_minor IS NOT NULL)
            ),
            CONSTRAINT employee_salary_range_check CHECK (
              effective_to IS NULL OR effective_to >= effective_from
            ),
            CONSTRAINT employee_salary_no_overlap EXCLUDE USING gist (
              employee_id WITH =,
              daterange(effective_from, effective_to, '[]') WITH &&
            ) WHERE (deleted_at IS NULL)
        );
        CREATE INDEX IF NOT EXISTS employee_salary_employee_idx ON employee_salary (employee_id);
        """
    )
    op.execute("".join(_rls(table) for table in _TABLES))
    op.execute(
        """
        INSERT INTO permission (id, code, domain, description)
        VALUES (gen_random_uuid(), 'PAYROLL.SETUP_MANAGE', 'PAYROLL',
                'Manage salary components, salary structures and employee salary assignments')
        ON CONFLICT (code) DO NOTHING;

        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'COMPANY'
        FROM role r
        JOIN permission p ON p.code = 'PAYROLL.SETUP_MANAGE'
        WHERE r.code IN ('COMPANY_ADMIN', 'HR_ADMIN') AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE permission_id IN (SELECT id FROM permission WHERE code = 'PAYROLL.SETUP_MANAGE');
        DELETE FROM permission WHERE code = 'PAYROLL.SETUP_MANAGE';
        """
    )
    op.execute("".join(f"DROP TABLE IF EXISTS {table};" for table in _TABLES))
