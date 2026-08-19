"""W3 (3/4) — new `overtime_policy`, `overtime_policy_version`, `overtime_policy_rate_row`
tables.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §12 and WD-03: a separate versioned
policy identity from `attendance_policy` (eligibility/caps/approval differ from attendance
compliance, and often vary by grade/department/shift independently). `multiplier_decimal` on
`overtime_policy_rate_row` is informational configuration only (ADR-0006/WD-12) — never applied
as money here.

Revision ID: 20260819110000
Revises: 20260819100000
"""

from alembic import op

revision = "20260819110000"
down_revision = "20260819100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS overtime_policy (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "name" VARCHAR(150) NOT NULL,
            "code" VARCHAR(30),
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "overtime_policy_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "overtime_policy_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS overtime_policy_company_id_idx ON overtime_policy (company_id);
        CREATE UNIQUE INDEX IF NOT EXISTS overtime_policy_company_code_idx
          ON overtime_policy (company_id, code)
          WHERE code IS NOT NULL AND deleted_at IS NULL;

        ALTER TABLE overtime_policy ENABLE ROW LEVEL SECURITY;
        ALTER TABLE overtime_policy FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON overtime_policy;
        CREATE POLICY tenant_isolation ON overtime_policy
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS overtime_policy_version (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_id" UUID NOT NULL,
            "status" VARCHAR(20) NOT NULL,
            "version" INTEGER NOT NULL DEFAULT 1,
            "effective_from" DATE,
            "effective_to" DATE,

            "eligibility" VARCHAR(30) NOT NULL DEFAULT 'SHIFT_FLAG',
            "min_ot_minutes" INTEGER NOT NULL DEFAULT 0,
            "rounding_minutes" INTEGER,
            "rounding_mode" VARCHAR(10) NOT NULL DEFAULT 'NONE',
            "requires_pre_approval" BOOLEAN NOT NULL DEFAULT false,
            "requires_post_approval" BOOLEAN NOT NULL DEFAULT true,
            "daily_cap_minutes" INTEGER,
            "weekly_cap_minutes" INTEGER,
            "monthly_cap_minutes" INTEGER,
            "comp_off_instead_of_pay" BOOLEAN NOT NULL DEFAULT false,
            "comp_off_expiry_days" INTEGER,
            "night_ot_mode" VARCHAR(20) NOT NULL DEFAULT 'SHIFT_FLAG',
            "night_window_start" TIME,
            "night_window_end" TIME,
            "approval_chain" VARCHAR(20) NOT NULL DEFAULT 'MANAGER',

            "publish_reason" TEXT,
            "published_at" TIMESTAMPTZ,
            "published_by" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "overtime_policy_version_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "overtime_policy_version_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "overtime_policy_version_policy_id_fkey" FOREIGN KEY ("policy_id")
              REFERENCES "overtime_policy"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "overtime_policy_version_published_by_fkey" FOREIGN KEY ("published_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "overtime_policy_version_status_check"
              CHECK (status IN ('DRAFT', 'PUBLISHED')),
            CONSTRAINT "overtime_policy_version_date_range_check"
              CHECK (effective_to IS NULL OR effective_to >= effective_from),
            CONSTRAINT "overtime_policy_version_published_required_check"
              CHECK (status = 'DRAFT' OR effective_from IS NOT NULL),
            CONSTRAINT "overtime_policy_version_night_window_check"
              CHECK ((night_window_start IS NULL) = (night_window_end IS NULL))
        );

        CREATE INDEX IF NOT EXISTS overtime_policy_version_company_id_idx
          ON overtime_policy_version (company_id);
        CREATE INDEX IF NOT EXISTS overtime_policy_version_policy_id_idx
          ON overtime_policy_version (policy_id);

        CREATE UNIQUE INDEX IF NOT EXISTS overtime_policy_version_one_open_draft_idx
          ON overtime_policy_version (policy_id)
          WHERE status = 'DRAFT' AND deleted_at IS NULL;

        ALTER TABLE overtime_policy_version
          DROP CONSTRAINT IF EXISTS overtime_policy_version_no_overlap;
        ALTER TABLE overtime_policy_version
          ADD CONSTRAINT overtime_policy_version_no_overlap
          EXCLUDE USING gist (
            policy_id WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (status = 'PUBLISHED' AND deleted_at IS NULL);

        ALTER TABLE overtime_policy_version ENABLE ROW LEVEL SECURITY;
        ALTER TABLE overtime_policy_version FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON overtime_policy_version;
        CREATE POLICY tenant_isolation ON overtime_policy_version
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS overtime_policy_rate_row (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_version_id" UUID NOT NULL,
            "day_class" VARCHAR(20) NOT NULL,
            "classification_code" VARCHAR(50) NOT NULL,
            "multiplier_decimal" NUMERIC(5, 4),
            "sort_order" INTEGER NOT NULL DEFAULT 0,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "overtime_policy_rate_row_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "overtime_policy_rate_row_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "overtime_policy_rate_row_version_id_fkey" FOREIGN KEY ("policy_version_id")
              REFERENCES "overtime_policy_version"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "overtime_policy_rate_row_day_class_check"
              CHECK (day_class IN ('NORMAL', 'WEEKLY_OFF', 'HOLIDAY', 'NIGHT')),
            CONSTRAINT "overtime_policy_rate_row_multiplier_check"
              CHECK (multiplier_decimal IS NULL OR multiplier_decimal > 0),
            CONSTRAINT "overtime_policy_rate_row_version_day_class_key"
              UNIQUE ("policy_version_id", "day_class")
        );

        CREATE INDEX IF NOT EXISTS overtime_policy_rate_row_version_id_idx
          ON overtime_policy_rate_row (policy_version_id, sort_order);
        CREATE INDEX IF NOT EXISTS overtime_policy_rate_row_company_id_idx
          ON overtime_policy_rate_row (company_id);

        ALTER TABLE overtime_policy_rate_row ENABLE ROW LEVEL SECURITY;
        ALTER TABLE overtime_policy_rate_row FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON overtime_policy_rate_row;
        CREATE POLICY tenant_isolation ON overtime_policy_rate_row
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS overtime_policy_rate_row;
        DROP TABLE IF EXISTS overtime_policy_version;
        DROP TABLE IF EXISTS overtime_policy;
        """
    )
