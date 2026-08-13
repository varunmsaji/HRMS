"""Company feature flag table — Task C-07 (docs/modules/company/03_Database_Design.md §7).

New tenant-scoped table representing per-company feature state (independent of `plan`/
`plan_feature` from C-05 and `subscription` from C-06 — this table holds company-specific
overrides/state only, not entitlement calculation, which is out of scope for this task).
RLS enabled inline in this migration, per the pattern established in
`alembic/versions/20260803200000_b1_auth_audit.py` (`audit_log`) — the standalone RLS SQL
script is not invoked by any migration and must not be treated as the live RLS registry.

Revision ID: 20260807180000
Revises: 20260807170000
"""

from alembic import op

revision = "20260807180000"
down_revision = "20260807170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS company_feature_flag (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL
              REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE,
            feature_code VARCHAR(60) NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            overrides_plan BOOLEAN NOT NULL DEFAULT false,
            value JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_by UUID REFERENCES "user"(id) ON DELETE SET NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            updated_by UUID REFERENCES "user"(id) ON DELETE SET NULL,
            version INTEGER NOT NULL DEFAULT 1,
            UNIQUE (company_id, feature_code)
        );

        CREATE INDEX IF NOT EXISTS company_feature_flag_company_id_idx
          ON company_feature_flag (company_id);

        ALTER TABLE company_feature_flag ENABLE ROW LEVEL SECURITY;
        ALTER TABLE company_feature_flag FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON company_feature_flag;
        CREATE POLICY tenant_isolation ON company_feature_flag
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS company_feature_flag;")
