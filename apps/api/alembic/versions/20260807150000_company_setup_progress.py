"""Company setup progress table — Task C-04 (docs/modules/company/03_Database_Design.md §3).

New table tracking which onboarding steps a company has completed, so the future Setup
Wizard can derive `steps_completed`/`status` from real row/field state rather than a
client-trusted flag. RLS enabled inline in this migration, per the pattern established in
`alembic/versions/20260803200000_b1_auth_audit.py` (`audit_log`) — the standalone RLS SQL
script is not invoked by any migration and must not be treated as the live RLS registry.

Revision ID: 20260807150000
Revises: 20260807140000
"""

from alembic import op

revision = "20260807150000"
down_revision = "20260807140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS company_setup_progress (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL UNIQUE
              REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE,
            steps_completed JSONB NOT NULL DEFAULT '[]',
            current_step VARCHAR(40),
            status VARCHAR(20) NOT NULL DEFAULT 'IN_PROGRESS'
              CHECK (status IN ('IN_PROGRESS','COMPLETE')),
            started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );

        ALTER TABLE company_setup_progress ENABLE ROW LEVEL SECURITY;
        ALTER TABLE company_setup_progress FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON company_setup_progress;
        CREATE POLICY tenant_isolation ON company_setup_progress
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS company_setup_progress;")
