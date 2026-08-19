"""W3 (4/4) — new `regularization_policy`, `regularization_policy_version`,
`regularization_policy_allowed_type` tables.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §13 and WD-03: defines who may
request a correction, windows/caps, and the approval chain — the *contract* a future
regularization workflow will read (WD-08 — V1 does not build that workflow). `allowed_types` is a
typed child table (WD-20: no arrays/JSON for multi-valued rule shapes), not a Postgres array
column.

Revision ID: 20260819120000
Revises: 20260819110000
"""

from alembic import op

revision = "20260819120000"
down_revision = "20260819110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS regularization_policy (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "name" VARCHAR(150) NOT NULL,
            "code" VARCHAR(30),
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "regularization_policy_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "regularization_policy_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS regularization_policy_company_id_idx
          ON regularization_policy (company_id);
        CREATE UNIQUE INDEX IF NOT EXISTS regularization_policy_company_code_idx
          ON regularization_policy (company_id, code)
          WHERE code IS NOT NULL AND deleted_at IS NULL;

        ALTER TABLE regularization_policy ENABLE ROW LEVEL SECURITY;
        ALTER TABLE regularization_policy FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON regularization_policy;
        CREATE POLICY tenant_isolation ON regularization_policy
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS regularization_policy_version (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_id" UUID NOT NULL,
            "status" VARCHAR(20) NOT NULL,
            "version" INTEGER NOT NULL DEFAULT 1,
            "effective_from" DATE,
            "effective_to" DATE,

            "allow_employee_request" BOOLEAN NOT NULL DEFAULT true,
            "allow_manager_request" BOOLEAN NOT NULL DEFAULT true,
            "allow_hr_request" BOOLEAN NOT NULL DEFAULT true,
            "max_backdated_days" INTEGER,
            "max_requests_per_month" INTEGER,
            "reason_required" BOOLEAN NOT NULL DEFAULT true,
            "attachment_required" BOOLEAN NOT NULL DEFAULT false,
            "approval_chain" VARCHAR(20) NOT NULL DEFAULT 'MANAGER',
            "auto_approve_within_minutes" INTEGER,
            "blocked_when_locked" BOOLEAN NOT NULL DEFAULT true,

            "publish_reason" TEXT,
            "published_at" TIMESTAMPTZ,
            "published_by" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "regularization_policy_version_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "regularization_policy_version_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "regularization_policy_version_policy_id_fkey" FOREIGN KEY ("policy_id")
              REFERENCES "regularization_policy"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "regularization_policy_version_published_by_fkey" FOREIGN KEY ("published_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "regularization_policy_version_status_check"
              CHECK (status IN ('DRAFT', 'PUBLISHED')),
            CONSTRAINT "regularization_policy_version_date_range_check"
              CHECK (effective_to IS NULL OR effective_to >= effective_from),
            CONSTRAINT "regularization_policy_version_published_required_check"
              CHECK (status = 'DRAFT' OR effective_from IS NOT NULL)
        );

        CREATE INDEX IF NOT EXISTS regularization_policy_version_company_id_idx
          ON regularization_policy_version (company_id);
        CREATE INDEX IF NOT EXISTS regularization_policy_version_policy_id_idx
          ON regularization_policy_version (policy_id);

        CREATE UNIQUE INDEX IF NOT EXISTS regularization_policy_version_one_open_draft_idx
          ON regularization_policy_version (policy_id)
          WHERE status = 'DRAFT' AND deleted_at IS NULL;

        ALTER TABLE regularization_policy_version
          DROP CONSTRAINT IF EXISTS regularization_policy_version_no_overlap;
        ALTER TABLE regularization_policy_version
          ADD CONSTRAINT regularization_policy_version_no_overlap
          EXCLUDE USING gist (
            policy_id WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (status = 'PUBLISHED' AND deleted_at IS NULL);

        ALTER TABLE regularization_policy_version ENABLE ROW LEVEL SECURITY;
        ALTER TABLE regularization_policy_version FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON regularization_policy_version;
        CREATE POLICY tenant_isolation ON regularization_policy_version
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS regularization_policy_allowed_type (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_version_id" UUID NOT NULL,
            "regularization_type" VARCHAR(30) NOT NULL,
            "sort_order" INTEGER NOT NULL DEFAULT 0,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "regularization_policy_allowed_type_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "regularization_policy_allowed_type_company_id_fkey"
              FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "regularization_policy_allowed_type_version_id_fkey"
              FOREIGN KEY ("policy_version_id")
              REFERENCES "regularization_policy_version"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "regularization_policy_allowed_type_check"
              CHECK (regularization_type IN (
                'MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS', 'WFH',
                'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY'
              )),
            CONSTRAINT "regularization_policy_allowed_type_version_type_key"
              UNIQUE ("policy_version_id", "regularization_type")
        );

        CREATE INDEX IF NOT EXISTS regularization_policy_allowed_type_version_id_idx
          ON regularization_policy_allowed_type (policy_version_id, sort_order);
        CREATE INDEX IF NOT EXISTS regularization_policy_allowed_type_company_id_idx
          ON regularization_policy_allowed_type (company_id);

        ALTER TABLE regularization_policy_allowed_type ENABLE ROW LEVEL SECURITY;
        ALTER TABLE regularization_policy_allowed_type FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON regularization_policy_allowed_type;
        CREATE POLICY tenant_isolation ON regularization_policy_allowed_type
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS regularization_policy_allowed_type;
        DROP TABLE IF EXISTS regularization_policy_version;
        DROP TABLE IF EXISTS regularization_policy;
        """
    )
