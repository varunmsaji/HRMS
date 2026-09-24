"""Payroll Phase 5.3 — the statutory rate master (`docs/modules/payroll/
00_PAYROLL_IMPLEMENTATION_PLAN.md`, FR-PAY-005).

- `statutory_rate` — effective-dated rates per company: `PF` and `ESI` (national, `state_code`
  NULL), `PT` and `LWF` (per state). `parameters` holds the scheme's numbers (validated by the
  service per scheme); nothing statutory is hard-coded (BR-10). No two rows of the same
  `(company, scheme, state)` overlap in time (GiST exclusion).
- `verified_at`/`verified_by_user_id` — compliance sign-off. A pay run that uses an unverified
  rate cannot be approved. Editing a rate clears its verification.
- New permission `PAYROLL.STATUTORY_MANAGE` (COMPANY_ADMIN, HR_ADMIN at COMPANY scope).

Default rates are seeded per company by the service on first use, unverified.

Revision ID: 20261004107000
Revises: 20261004106000
"""

from alembic import op

revision = "20261004107000"
down_revision = "20261004106000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS statutory_rate (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company (id) ON DELETE RESTRICT,
            scheme VARCHAR(10) NOT NULL CHECK (scheme IN ('PF', 'ESI', 'PT', 'LWF')),
            state_code VARCHAR(10),
            effective_from DATE NOT NULL,
            effective_to DATE,
            parameters JSONB NOT NULL,
            notes TEXT,
            is_seeded BOOLEAN NOT NULL DEFAULT false,
            verified_at TIMESTAMPTZ,
            verified_by_user_id UUID REFERENCES "user" (id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            version INTEGER NOT NULL DEFAULT 1,
            CONSTRAINT statutory_rate_state_check CHECK (
              (scheme IN ('PF', 'ESI')) = (state_code IS NULL)
            ),
            CONSTRAINT statutory_rate_range_check CHECK (
              effective_to IS NULL OR effective_to >= effective_from
            ),
            CONSTRAINT statutory_rate_no_overlap EXCLUDE USING gist (
              company_id WITH =,
              scheme WITH =,
              (COALESCE(state_code, '')) WITH =,
              daterange(effective_from, effective_to, '[]') WITH &&
            )
        );
        CREATE INDEX IF NOT EXISTS statutory_rate_company_idx
          ON statutory_rate (company_id, scheme, state_code);

        ALTER TABLE statutory_rate ENABLE ROW LEVEL SECURITY;
        ALTER TABLE statutory_rate FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON statutory_rate;
        CREATE POLICY tenant_isolation ON statutory_rate
          USING (company_id = current_setting('app.company_id', true)::uuid);

        INSERT INTO permission (id, code, domain, description)
        VALUES (gen_random_uuid(), 'PAYROLL.STATUTORY_MANAGE', 'PAYROLL',
                'Manage and verify statutory rates (PF, ESI, professional tax, LWF)')
        ON CONFLICT (code) DO NOTHING;

        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'COMPANY'
        FROM role r
        JOIN permission p ON p.code = 'PAYROLL.STATUTORY_MANAGE'
        WHERE r.code IN ('COMPANY_ADMIN', 'HR_ADMIN') AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission
        WHERE permission_id IN (
          SELECT id FROM permission WHERE code = 'PAYROLL.STATUTORY_MANAGE'
        );
        DELETE FROM permission WHERE code = 'PAYROLL.STATUTORY_MANAGE';
        DROP TABLE IF EXISTS statutory_rate;
        """
    )
