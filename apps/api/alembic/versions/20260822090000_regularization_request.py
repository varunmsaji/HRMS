"""W6 — `attendance_regularization_request` + `_requested_punch` + `_action`.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §13 and decision log WD-28: an
employee/manager/HR request to correct one employee's attendance for one date, applied only
through the two mechanisms that already exist (synthetic `punch` rows and, for `WRONG_SHIFT`, a
`PUBLISHED` `shift_roster` row) followed by the existing calculation engine. `_requested_punch`
is the typed correction payload (WD-12/WD-20 — not JSON); `_action` is the append-only per-stage
timeline architecture §13.2/§33.4 names explicitly.

Also widens `punch_source_check` to accept `'REGULARIZATION'` (ALTER in place, DEC-021/WD-25
precedent) — an approved request's correction is applied as an ordinary immutable `punch` row
with that source, never a mutation of an existing punch.

Revision ID: 20260822090000
Revises: 20260821090000
"""

from alembic import op

revision = "20260822090000"
down_revision = "20260821090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE punch DROP CONSTRAINT punch_source_check;
        ALTER TABLE punch ADD CONSTRAINT punch_source_check
          CHECK (source IN ('WEB', 'MOBILE', 'DEVICE', 'IMPORT', 'ADMIN', 'API', 'REGULARIZATION'));

        CREATE TABLE IF NOT EXISTS attendance_regularization_request (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "attendance_day_id" UUID,
            "attendance_date" DATE NOT NULL,

            "request_type" VARCHAR(30) NOT NULL,
            "reason" TEXT,
            "requested_shift_id" UUID,
            "attachment_reference" VARCHAR(500),

            "status" VARCHAR(20) NOT NULL DEFAULT 'SUBMITTED',
            "approval_chain" VARCHAR(20) NOT NULL,
            "approval_stage" VARCHAR(10),
            "regularization_policy_version_id" UUID NOT NULL,
            "resolved_approver_manager_id" UUID,

            "submitted_by_user_id" UUID,
            "submitted_at" TIMESTAMPTZ NOT NULL,

            "reviewed_by_user_id" UUID,
            "reviewed_at" TIMESTAMPTZ,
            "reviewer_comment" TEXT,
            "rejection_reason" TEXT,

            "applied_at" TIMESTAMPTZ,
            "cancelled_at" TIMESTAMPTZ,
            "cancelled_by_user_id" UUID,

            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_regularization_request_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_regularization_request_company_id_fkey"
              FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_regularization_request_employee_id_fkey"
              FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_regularization_request_attendance_day_id_fkey"
              FOREIGN KEY ("attendance_day_id")
              REFERENCES "attendance_day"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_regularization_request_requested_shift_id_fkey"
              FOREIGN KEY ("requested_shift_id") REFERENCES "shift"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_regularization_request_policy_version_id_fkey"
              FOREIGN KEY ("regularization_policy_version_id")
              REFERENCES "regularization_policy_version"("id") ON DELETE RESTRICT,
            CONSTRAINT "attendance_regularization_request_approver_manager_id_fkey"
              FOREIGN KEY ("resolved_approver_manager_id")
              REFERENCES "employee"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_regularization_request_submitted_by_user_id_fkey"
              FOREIGN KEY ("submitted_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_regularization_request_reviewed_by_user_id_fkey"
              FOREIGN KEY ("reviewed_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_regularization_request_cancelled_by_user_id_fkey"
              FOREIGN KEY ("cancelled_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_regularization_request_status_check" CHECK (
              status IN ('SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED')
            ),
            CONSTRAINT "attendance_regularization_request_approval_chain_check" CHECK (
              approval_chain IN ('AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'HR')
            ),
            CONSTRAINT "attendance_regularization_request_approval_stage_check" CHECK (
              approval_stage IS NULL OR approval_stage IN ('MANAGER', 'HR')
            ),
            CONSTRAINT "attendance_regularization_request_request_type_check" CHECK (
              request_type IN (
                'MISSING_PUNCH', 'WRONG_PUNCH', 'WRONG_SHIFT', 'WRONG_STATUS',
                'WFH', 'ON_DUTY', 'EXCESS_BREAK', 'FULL_DAY'
              )
            )
        );

        CREATE UNIQUE INDEX IF NOT EXISTS attendance_regularization_request_active_unique_idx
          ON attendance_regularization_request (company_id, employee_id, attendance_date)
          WHERE status = 'SUBMITTED';

        CREATE INDEX IF NOT EXISTS attendance_regularization_request_company_id_idx
          ON attendance_regularization_request (company_id);
        CREATE INDEX IF NOT EXISTS attendance_regularization_request_employee_date_idx
          ON attendance_regularization_request (company_id, employee_id, attendance_date DESC);
        CREATE INDEX IF NOT EXISTS attendance_regularization_request_status_idx
          ON attendance_regularization_request (company_id, status);

        ALTER TABLE attendance_regularization_request ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_regularization_request FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_regularization_request;
        CREATE POLICY tenant_isolation ON attendance_regularization_request
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_regularization_requested_punch (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "request_id" UUID NOT NULL,
            "direction" VARCHAR(10) NOT NULL,
            "requested_time" TIMESTAMPTZ NOT NULL,
            "sort_order" INTEGER NOT NULL DEFAULT 0,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_regularization_requested_punch_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_regularization_requested_punch_company_id_fkey"
              FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_regularization_requested_punch_request_id_fkey"
              FOREIGN KEY ("request_id") REFERENCES "attendance_regularization_request"("id")
              ON DELETE CASCADE,
            CONSTRAINT "attendance_regularization_requested_punch_direction_check"
              CHECK (direction IN ('IN', 'OUT'))
        );

        CREATE INDEX IF NOT EXISTS attendance_regularization_requested_punch_request_idx
          ON attendance_regularization_requested_punch (company_id, request_id);

        ALTER TABLE attendance_regularization_requested_punch ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_regularization_requested_punch FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_regularization_requested_punch;
        CREATE POLICY tenant_isolation ON attendance_regularization_requested_punch
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_regularization_action (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "request_id" UUID NOT NULL,
            "action" VARCHAR(30) NOT NULL,
            "actor_user_id" UUID,
            "actor_employee_id" UUID,
            "stage" VARCHAR(10),
            "comment" TEXT,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_regularization_action_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_regularization_action_company_id_fkey"
              FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_regularization_action_request_id_fkey"
              FOREIGN KEY ("request_id") REFERENCES "attendance_regularization_request"("id")
              ON DELETE CASCADE,
            CONSTRAINT "attendance_regularization_action_actor_user_id_fkey"
              FOREIGN KEY ("actor_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_regularization_action_actor_employee_id_fkey"
              FOREIGN KEY ("actor_employee_id") REFERENCES "employee"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_regularization_action_action_check" CHECK (
              action IN (
                'SUBMITTED', 'APPROVER_UNRESOLVED', 'STAGE_APPROVED', 'APPROVED',
                'REJECTED', 'CANCELLED', 'APPLIED'
              )
            ),
            CONSTRAINT "attendance_regularization_action_stage_check"
              CHECK (stage IS NULL OR stage IN ('MANAGER', 'HR'))
        );

        CREATE INDEX IF NOT EXISTS attendance_regularization_action_request_idx
          ON attendance_regularization_action (company_id, request_id, created_at);

        ALTER TABLE attendance_regularization_action ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_regularization_action FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_regularization_action;
        CREATE POLICY tenant_isolation ON attendance_regularization_action
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS attendance_regularization_action;
        DROP TABLE IF EXISTS attendance_regularization_requested_punch;
        DROP TABLE IF EXISTS attendance_regularization_request;

        ALTER TABLE punch DROP CONSTRAINT punch_source_check;
        ALTER TABLE punch ADD CONSTRAINT punch_source_check
          CHECK (source IN ('WEB', 'MOBILE', 'DEVICE', 'IMPORT', 'ADMIN', 'API'));
        """
    )
