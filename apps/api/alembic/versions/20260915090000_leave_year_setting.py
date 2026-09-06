"""Leave year configuration — new `leave_year_setting` table (client spec §10,
LEAVE_DECISION_LOG.md LD-20).

Singleton per company (unique index on `company_id`) — client answer (2026-09-06): default is
`CALENDAR` (1 Jan – 31 Dec) for this client, but the mechanism supports the other three options
the spec lists (`FINANCIAL`, `ANNIVERSARY`, `CUSTOM`) since a future company may need one of
those. `start_month`/`start_day` are only meaningful for `CUSTOM` — `CALENDAR` and `FINANCIAL`
(client answer: India, so Apr 1) have their start dates hardcoded in application code, not
stored, since they're not configurable values; `ANNIVERSARY` has no company-wide start date at
all (each employee's own `Employment.joining_date` month/day is used instead).

Revision ID: 20260915090000
Revises: 20260914090000
"""

from alembic import op

revision = "20260915090000"
down_revision = "20260914090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_year_setting (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "leave_year_type" VARCHAR(20) NOT NULL DEFAULT 'CALENDAR',
            "start_month" INTEGER,
            "start_day" INTEGER,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "leave_year_setting_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_year_setting_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_year_setting_type_check"
              CHECK (leave_year_type IN ('CALENDAR', 'FINANCIAL', 'ANNIVERSARY', 'CUSTOM')),
            CONSTRAINT "leave_year_setting_custom_requires_start_check"
              CHECK (
                leave_year_type <> 'CUSTOM'
                OR (start_month IS NOT NULL AND start_day IS NOT NULL)
              ),
            CONSTRAINT "leave_year_setting_start_month_range_check"
              CHECK (start_month IS NULL OR (start_month BETWEEN 1 AND 12)),
            CONSTRAINT "leave_year_setting_start_day_range_check"
              CHECK (start_day IS NULL OR (start_day BETWEEN 1 AND 31))
        );

        CREATE UNIQUE INDEX IF NOT EXISTS leave_year_setting_company_id_idx
          ON leave_year_setting (company_id);

        ALTER TABLE leave_year_setting ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_year_setting FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_year_setting;
        CREATE POLICY tenant_isolation ON leave_year_setting
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leave_year_setting;")
