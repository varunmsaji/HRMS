"""Platform super-admin console (1/1) — company approval lifecycle + platform identity.

1. `company.status` gains `PENDING_APPROVAL` and `REJECTED` (a newly registered company waits for a
   platform admin; existing rows are untouched and stay `TRIAL`/`ACTIVE`). New nullable columns
   record why/when/by whom the status last changed and, for `TERMINATED`, until when its data is
   retained (`retention_until`).
2. `platform_admin` / `platform_session` — a separate identity from tenant `user`s: no
   `user_company` row, no company RBAC, own login by username. MFA is intentionally not part of
   this revision (deferred by decision).
3. `platform_audit_log` — append-only record of every platform action (a trigger rejects UPDATE
   and DELETE for every role; the runtime role is additionally denied them). It has no
   `company_id` FK so entries outlive the company they describe.

Reversible: the downgrade drops the new tables/columns and restores the original status CHECK
(it fails, deliberately, if rows with the new statuses exist — resolve them first).

Revision ID: 20261019090000
Revises: 20261018090000
"""

from alembic import op

revision = "20261019090000"
down_revision = "20261018090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE company DROP CONSTRAINT company_status_check;
        ALTER TABLE company ADD CONSTRAINT company_status_check CHECK (
          status IN ('PENDING_APPROVAL','TRIAL','ACTIVE','SUSPENDED','REJECTED','TERMINATED')
        );

        CREATE TABLE platform_admin (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          username VARCHAR(64) NOT NULL,
          password_hash TEXT NOT NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
            CHECK (status IN ('ACTIVE','DISABLED')),
          failed_login_count INTEGER NOT NULL DEFAULT 0,
          locked_until TIMESTAMPTZ,
          last_login_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          version INTEGER NOT NULL DEFAULT 1,
          CONSTRAINT platform_admin_username_format CHECK (username ~ '^[a-z0-9._-]{3,64}$')
        );
        CREATE UNIQUE INDEX platform_admin_username_key ON platform_admin (username);

        CREATE TABLE platform_session (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          platform_admin_id UUID NOT NULL REFERENCES platform_admin(id) ON DELETE CASCADE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          expires_at TIMESTAMPTZ NOT NULL,
          revoked_at TIMESTAMPTZ,
          ip VARCHAR(64),
          user_agent VARCHAR(255)
        );
        CREATE INDEX platform_session_admin_idx ON platform_session (platform_admin_id);

        ALTER TABLE company
          ADD COLUMN status_reason TEXT,
          ADD COLUMN status_changed_at TIMESTAMPTZ,
          ADD COLUMN status_changed_by_platform_admin_id UUID
            REFERENCES platform_admin(id) ON DELETE SET NULL,
          ADD COLUMN approved_at TIMESTAMPTZ,
          ADD COLUMN retention_until TIMESTAMPTZ;
        CREATE INDEX company_pending_approval_idx ON company (created_at)
          WHERE status = 'PENDING_APPROVAL' AND deleted_at IS NULL;

        CREATE TABLE platform_audit_log (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
          actor_platform_admin_id UUID,
          actor_username VARCHAR(64),
          action VARCHAR(60) NOT NULL,
          company_id UUID,
          reason TEXT,
          before_status VARCHAR(20),
          after_status VARCHAR(20),
          details JSONB,
          ip VARCHAR(64),
          user_agent VARCHAR(255),
          request_id VARCHAR(64)
        );
        CREATE INDEX platform_audit_log_company_idx ON platform_audit_log (company_id, created_at DESC);
        CREATE INDEX platform_audit_log_created_idx ON platform_audit_log (created_at DESC);

        CREATE FUNCTION platform_audit_log_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'platform_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER platform_audit_log_no_update_delete
          BEFORE UPDATE OR DELETE ON platform_audit_log
          FOR EACH ROW EXECUTE FUNCTION platform_audit_log_immutable();

        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
            REVOKE UPDATE, DELETE, TRUNCATE ON platform_audit_log FROM hrms_app;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE platform_audit_log;
        DROP FUNCTION platform_audit_log_immutable();
        DROP INDEX company_pending_approval_idx;
        ALTER TABLE company
          DROP COLUMN status_reason,
          DROP COLUMN status_changed_at,
          DROP COLUMN status_changed_by_platform_admin_id,
          DROP COLUMN approved_at,
          DROP COLUMN retention_until;
        DROP TABLE platform_session;
        DROP TABLE platform_admin;
        ALTER TABLE company DROP CONSTRAINT company_status_check;
        ALTER TABLE company ADD CONSTRAINT company_status_check CHECK (
          status IN ('TRIAL','ACTIVE','SUSPENDED','TERMINATED')
        );
        """
    )
