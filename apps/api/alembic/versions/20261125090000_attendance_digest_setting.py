"""Per-company opt-out for the attendance digest emails: `attendance_digest_setting`.

Revision ID: 20261125090000
Revises: 20261124090000

One row per company, created the first time its settings are saved. No row means the defaults:
both digests on (they are still sent only where the deployment has switched the digests on at all,
`ATTENDANCE_DIGESTS_ENABLED`). `manager_daily_enabled` is the weekday note to managers,
`hr_weekly_enabled` the Monday summary to HR. Additive: nothing changes for a company that has never
saved a setting. FORCE row-level security with the usual `tenant_isolation` policy. Downgrade drops
the table (a company's opt-outs are lost, so its digests would resume once they are switched on).
"""

from alembic import op

revision = "20261125090000"
down_revision = "20261124090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        SET LOCAL lock_timeout = '5s';

        CREATE TABLE IF NOT EXISTS attendance_digest_setting (
            "company_id" UUID NOT NULL,
            "manager_daily_enabled" BOOLEAN NOT NULL DEFAULT true,
            "hr_weekly_enabled" BOOLEAN NOT NULL DEFAULT true,
            "updated_by_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT "attendance_digest_setting_pkey" PRIMARY KEY ("company_id"),
            CONSTRAINT "attendance_digest_setting_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_digest_setting_updated_by_user_id_fkey"
              FOREIGN KEY ("updated_by_user_id")
              REFERENCES "user"("id") ON DELETE SET NULL ON UPDATE CASCADE
        );

        ALTER TABLE attendance_digest_setting ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_digest_setting FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_digest_setting;
        CREATE POLICY tenant_isolation ON attendance_digest_setting
          USING (company_id = current_setting('app.company_id', true)::uuid);

        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
                GRANT SELECT, INSERT, UPDATE ON attendance_digest_setting TO hrms_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attendance_digest_setting;")
