"""Platform email log — one append-only row per outgoing email (sent, failed or dev-logged),
readable only through the platform console. Tenant-free (no RLS), like `platform_audit_log`.

Revision ID: 20261021090000
Revises: 20261020090000
"""

from alembic import op

revision = "20261021090000"
down_revision = "20261020090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE email_log (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          kind VARCHAR(80),
          provider VARCHAR(30) NOT NULL,
          status VARCHAR(20) NOT NULL CHECK (status IN ('ACCEPTED','FAILED','LOGGED_ONLY')),
          recipient VARCHAR(320) NOT NULL,
          sender VARCHAR(320),
          subject TEXT NOT NULL,
          text_body TEXT,
          html_body TEXT,
          company_id UUID,
          request_id VARCHAR(64),
          failure_class VARCHAR(40),
          error_type VARCHAR(80),
          status_code INTEGER,
          retryable BOOLEAN,
          duration_ms INTEGER
        );
        CREATE INDEX email_log_created_idx ON email_log (created_at DESC);
        CREATE INDEX email_log_company_idx ON email_log (company_id, created_at DESC);
        CREATE INDEX email_log_recipient_idx ON email_log (lower(recipient));

        CREATE FUNCTION email_log_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'email_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER email_log_no_update_delete
          BEFORE UPDATE OR DELETE ON email_log
          FOR EACH ROW EXECUTE FUNCTION email_log_immutable();

        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
            REVOKE UPDATE, DELETE, TRUNCATE ON email_log FROM hrms_app;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE email_log; DROP FUNCTION email_log_immutable();")
