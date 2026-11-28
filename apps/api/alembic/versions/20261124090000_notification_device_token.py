"""Push notification device tokens: `device_token`.

Revision ID: 20261124090000
Revises: 20261122090000

One row per (company, FCM registration token). The mobile app registers its token after sign-in
and removes it on sign-out; the notification worker reads a recipient's tokens to push a new
in-app notification to their phones. Additive: nothing reads the table until `PUSH_PROVIDER=fcm`.

The token is unique per company, so a phone that a second person signs in on moves to that person
instead of keeping two owners. FORCE row-level security with the usual `tenant_isolation` policy.
Downgrade drops the table (registered tokens are lost; apps re-register on next sign-in).
"""

from alembic import op

revision = "20261124090000"
down_revision = "20261122090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        SET LOCAL lock_timeout = '5s';

        CREATE TABLE IF NOT EXISTS device_token (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "user_id" UUID NOT NULL,
            "token" VARCHAR(4096) NOT NULL,
            "platform" VARCHAR(16) NOT NULL,
            "app_version" VARCHAR(32),
            "last_seen_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT "device_token_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "device_token_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "device_token_user_id_fkey" FOREIGN KEY ("user_id")
              REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "device_token_platform_check" CHECK ("platform" IN ('android', 'ios')),
            CONSTRAINT "device_token_company_token_key" UNIQUE ("company_id", "token")
        );
        CREATE INDEX IF NOT EXISTS device_token_user_idx ON device_token (company_id, user_id);

        ALTER TABLE device_token ENABLE ROW LEVEL SECURITY;
        ALTER TABLE device_token FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON device_token;
        CREATE POLICY tenant_isolation ON device_token
          USING (company_id = current_setting('app.company_id', true)::uuid);

        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON device_token TO hrms_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS device_token;")
