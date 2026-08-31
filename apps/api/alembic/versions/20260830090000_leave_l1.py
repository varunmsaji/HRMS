"""L1 — new `leave_type`, `leave_policy`, `leave_policy_version` tables.

Per docs/architecture/LEAVE_DECISION_LOG.md LD-02/LD-04/LD-09 (slice L1): mirrors
`attendance_policy`/`attendance_policy_version`'s identity+immutable-version shape exactly
(migration 20260819100000_attendance_policy.py) — `leave_policy` is a mutable identity
(name/code/active, never evaluation fields), `leave_policy_version` is the immutable,
effective-dated body (DRAFT -> PUBLISHED, one open draft per policy, GiST no-overlap of
published rows per `policy_id`). `leave_type` is a standalone identity table (code/name/
paid-default/balance-requirement), no versioning of its own — its rules are resolved via
`PolicyAssignment` like every other policy (LD-04 widens `policy_kind` to include
"LEAVE_POLICY" — both the Pydantic allow-list in `organisation/schemas.py` *and* the DB-level
`policy_assignment_policy_kind_check` CHECK constraint below, mirroring
`20260819090000_widen_policy_assignment_kinds.py`'s exact "ALTER in place" widening for
ATTENDANCE_POLICY/OVERTIME_POLICY/REGULARIZATION_POLICY — the GiST exclusion constraint
`policy_assignment_no_overlap` already includes `policy_kind WITH =`, so LEAVE_POLICY
automatically participates in the same per-scope no-overlap semantics with zero additional
migration work beyond the CHECK).

This slice defines the contract only — no accrual job (L3), application workflow (L4), ledger
(L2), or comp-off redemption (L5) reads these tables yet.

Revision ID: 20260830090000
Revises: 20260828090000
"""

from alembic import op

revision = "20260830090000"
down_revision = "20260828090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_type (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "code" VARCHAR(30) NOT NULL,
            "name" VARCHAR(150) NOT NULL,
            "is_paid_default" BOOLEAN NOT NULL DEFAULT true,
            "requires_balance" BOOLEAN NOT NULL DEFAULT true,
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "leave_type_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_type_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS leave_type_company_id_idx ON leave_type (company_id);
        CREATE UNIQUE INDEX IF NOT EXISTS leave_type_company_code_idx
          ON leave_type (company_id, code)
          WHERE deleted_at IS NULL;

        ALTER TABLE leave_type ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_type FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_type;
        CREATE POLICY tenant_isolation ON leave_type
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS leave_policy (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "name" VARCHAR(150) NOT NULL,
            "code" VARCHAR(30),
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "leave_policy_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_policy_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS leave_policy_company_id_idx ON leave_policy (company_id);
        CREATE UNIQUE INDEX IF NOT EXISTS leave_policy_company_code_idx
          ON leave_policy (company_id, code)
          WHERE code IS NOT NULL AND deleted_at IS NULL;

        ALTER TABLE leave_policy ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_policy FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_policy;
        CREATE POLICY tenant_isolation ON leave_policy
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS leave_policy_version (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "policy_id" UUID NOT NULL,
            "status" VARCHAR(20) NOT NULL,
            "version" INTEGER NOT NULL DEFAULT 1,
            "effective_from" DATE,
            "effective_to" DATE,

            "allow_employee_request" BOOLEAN NOT NULL DEFAULT true,
            "allow_manager_request_on_behalf" BOOLEAN NOT NULL DEFAULT true,
            "allow_hr_request_on_behalf" BOOLEAN NOT NULL DEFAULT true,
            "max_backdated_days" INTEGER,
            "max_requests_per_month" INTEGER,
            "reason_required" BOOLEAN NOT NULL DEFAULT true,
            "attachment_required" BOOLEAN NOT NULL DEFAULT false,
            "approval_chain" VARCHAR(20) NOT NULL DEFAULT 'MANAGER',
            "half_day_allowed" BOOLEAN NOT NULL DEFAULT true,

            "accrual_frequency" VARCHAR(20) NOT NULL DEFAULT 'NONE',
            "accrual_rate_per_cycle" NUMERIC(5, 2),
            "max_carry_forward_days" NUMERIC(5, 2),
            "encashment_allowed" BOOLEAN NOT NULL DEFAULT false,
            "allow_negative_balance" BOOLEAN NOT NULL DEFAULT false,
            "sandwich_rule_enabled" BOOLEAN NOT NULL DEFAULT false,

            "publish_reason" TEXT,
            "published_at" TIMESTAMPTZ,
            "published_by" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "leave_policy_version_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_policy_version_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_policy_version_policy_id_fkey" FOREIGN KEY ("policy_id")
              REFERENCES "leave_policy"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_policy_version_published_by_fkey" FOREIGN KEY ("published_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_policy_version_status_check"
              CHECK (status IN ('DRAFT', 'PUBLISHED')),
            CONSTRAINT "leave_policy_version_approval_chain_check"
              CHECK (approval_chain IN ('AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'HR')),
            CONSTRAINT "leave_policy_version_accrual_frequency_check"
              CHECK (accrual_frequency IN ('NONE', 'MONTHLY', 'YEARLY')),
            CONSTRAINT "leave_policy_version_date_range_check"
              CHECK (effective_to IS NULL OR effective_to >= effective_from),
            CONSTRAINT "leave_policy_version_published_required_check"
              CHECK (status = 'DRAFT' OR effective_from IS NOT NULL)
        );

        CREATE INDEX IF NOT EXISTS leave_policy_version_company_id_idx
          ON leave_policy_version (company_id);
        CREATE INDEX IF NOT EXISTS leave_policy_version_policy_id_idx
          ON leave_policy_version (policy_id);

        CREATE UNIQUE INDEX IF NOT EXISTS leave_policy_version_one_open_draft_idx
          ON leave_policy_version (policy_id)
          WHERE status = 'DRAFT' AND deleted_at IS NULL;

        ALTER TABLE leave_policy_version
          DROP CONSTRAINT IF EXISTS leave_policy_version_no_overlap;
        ALTER TABLE leave_policy_version
          ADD CONSTRAINT leave_policy_version_no_overlap
          EXCLUDE USING gist (
            policy_id WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (status = 'PUBLISHED' AND deleted_at IS NULL);

        ALTER TABLE leave_policy_version ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_policy_version FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_policy_version;
        CREATE POLICY tenant_isolation ON leave_policy_version
          USING (company_id = current_setting('app.company_id', true)::uuid);

        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_policy_kind_check;
        ALTER TABLE policy_assignment
          ADD CONSTRAINT policy_assignment_policy_kind_check
          CHECK (policy_kind IN (
            'WORK_CALENDAR', 'WEEKLY_OFF', 'ATTENDANCE_POLICY', 'OVERTIME_POLICY',
            'REGULARIZATION_POLICY', 'LEAVE_POLICY'
          ));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_policy_kind_check;
        ALTER TABLE policy_assignment
          ADD CONSTRAINT policy_assignment_policy_kind_check
          CHECK (policy_kind IN (
            'WORK_CALENDAR', 'WEEKLY_OFF', 'ATTENDANCE_POLICY', 'OVERTIME_POLICY',
            'REGULARIZATION_POLICY'
          ));

        DROP TABLE IF EXISTS leave_policy_version;
        DROP TABLE IF EXISTS leave_policy;
        DROP TABLE IF EXISTS leave_type;
        """
    )
