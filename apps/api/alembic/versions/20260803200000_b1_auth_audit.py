"""B1 auth foundation — audit_log, refresh token family, login lockout.

Revision ID: 20260803200000
Revises: 20260803124757
"""

from alembic import op

revision = "20260803200000"
down_revision = "20260803124757"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE "user"
          ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;

        ALTER TABLE refresh_token
          ADD COLUMN IF NOT EXISTS token_family_id UUID,
          ADD COLUMN IF NOT EXISTS session_id UUID REFERENCES session(id),
          ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES company(id),
          ADD COLUMN IF NOT EXISTS revoked_reason VARCHAR(40);

        CREATE TABLE IF NOT EXISTS audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES company(id),
            actor_user_id UUID REFERENCES "user"(id),
            action VARCHAR(60) NOT NULL,
            entity_type VARCHAR(60) NOT NULL,
            entity_id UUID,
            before_json JSONB,
            after_json JSONB,
            ip VARCHAR(45),
            user_agent TEXT,
            request_id VARCHAR(64),
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS audit_log_company_occurred_idx
          ON audit_log (company_id, occurred_at DESC);

        ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
        ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON audit_log;
        CREATE POLICY tenant_isolation ON audit_log
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS audit_log;
        ALTER TABLE refresh_token
          DROP COLUMN IF EXISTS revoked_reason,
          DROP COLUMN IF EXISTS company_id,
          DROP COLUMN IF EXISTS session_id,
          DROP COLUMN IF EXISTS token_family_id;
        ALTER TABLE "user"
          DROP COLUMN IF EXISTS locked_until,
          DROP COLUMN IF EXISTS failed_login_count;
        """
    )
