"""W7 — `overtime_record` + `overtime_action`.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §12 and decision log WD-29: overtime
*detection* was already built in W3/W4 (`AttendanceDay.ot_minutes_detected`/`ot_pending`/etc.)
but had no approval workflow to act on it. `overtime_record` is a single
mutable-then-frozen row per `AttendanceDay` (`attendance_day_id` is `UNIQUE` — not an
accumulating history like `attendance_regularization_request`), carrying the approval-chain
snapshot, review fields, and the payroll-facing facts (`minutes_approved`, `comp_off_minutes`,
`comp_off_expiry_date`, `configured_multiplier`). `overtime_action` is the append-only per-stage
timeline, mirroring `attendance_regularization_action`.

Revision ID: 20260823090000
Revises: 20260822090000
"""

from alembic import op

revision = "20260823090000"
down_revision = "20260822090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS overtime_record (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "attendance_day_id" UUID NOT NULL,
            "attendance_date" DATE NOT NULL,
            "overtime_policy_version_id" UUID NOT NULL,

            "day_class" VARCHAR(20),
            "classification_code" VARCHAR(50),
            "configured_multiplier" NUMERIC(5,4),

            "minutes_detected" INTEGER NOT NULL DEFAULT 0,
            "minutes_approved" INTEGER NOT NULL DEFAULT 0,

            "status" VARCHAR(20) NOT NULL,
            "approval_chain" VARCHAR(20) NOT NULL,
            "approval_stage" VARCHAR(10),
            "resolved_approver_manager_id" UUID,

            "reviewed_by_user_id" UUID,
            "reviewed_at" TIMESTAMPTZ,
            "reviewer_comment" TEXT,
            "rejection_reason" TEXT,

            "comp_off_minutes" INTEGER NOT NULL DEFAULT 0,
            "comp_off_expiry_date" DATE,

            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "overtime_record_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "overtime_record_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "overtime_record_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "overtime_record_attendance_day_id_fkey" FOREIGN KEY ("attendance_day_id")
              REFERENCES "attendance_day"("id") ON DELETE CASCADE,
            CONSTRAINT "overtime_record_attendance_day_id_unique" UNIQUE ("attendance_day_id"),
            CONSTRAINT "overtime_record_policy_version_id_fkey"
              FOREIGN KEY ("overtime_policy_version_id")
              REFERENCES "overtime_policy_version"("id") ON DELETE RESTRICT,
            CONSTRAINT "overtime_record_approver_manager_id_fkey"
              FOREIGN KEY ("resolved_approver_manager_id") REFERENCES "employee"("id")
              ON DELETE SET NULL,
            CONSTRAINT "overtime_record_reviewed_by_user_id_fkey"
              FOREIGN KEY ("reviewed_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "overtime_record_status_check" CHECK (
              status IN ('PENDING', 'AUTO_APPROVED', 'APPROVED', 'REJECTED')
            ),
            CONSTRAINT "overtime_record_approval_chain_check" CHECK (
              approval_chain IN ('AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'HR')
            ),
            CONSTRAINT "overtime_record_approval_stage_check"
              CHECK (approval_stage IS NULL OR approval_stage IN ('MANAGER', 'HR')),
            CONSTRAINT "overtime_record_day_class_check"
              CHECK (
                day_class IS NULL OR day_class IN ('NORMAL', 'WEEKLY_OFF', 'HOLIDAY', 'NIGHT')
              ),
            CONSTRAINT "overtime_record_multiplier_check"
              CHECK (configured_multiplier IS NULL OR configured_multiplier > 0)
        );

        CREATE INDEX IF NOT EXISTS overtime_record_company_id_idx
          ON overtime_record (company_id);
        CREATE INDEX IF NOT EXISTS overtime_record_employee_date_idx
          ON overtime_record (company_id, employee_id, attendance_date DESC);
        CREATE INDEX IF NOT EXISTS overtime_record_status_idx
          ON overtime_record (company_id, status);

        ALTER TABLE overtime_record ENABLE ROW LEVEL SECURITY;
        ALTER TABLE overtime_record FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON overtime_record;
        CREATE POLICY tenant_isolation ON overtime_record
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS overtime_action (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "overtime_record_id" UUID NOT NULL,
            "action" VARCHAR(30) NOT NULL,
            "actor_user_id" UUID,
            "actor_employee_id" UUID,
            "stage" VARCHAR(10),
            "comment" TEXT,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "overtime_action_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "overtime_action_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "overtime_action_overtime_record_id_fkey"
              FOREIGN KEY ("overtime_record_id") REFERENCES "overtime_record"("id")
              ON DELETE CASCADE,
            CONSTRAINT "overtime_action_actor_user_id_fkey"
              FOREIGN KEY ("actor_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "overtime_action_actor_employee_id_fkey"
              FOREIGN KEY ("actor_employee_id") REFERENCES "employee"("id") ON DELETE SET NULL,
            CONSTRAINT "overtime_action_action_check" CHECK (
              action IN (
                'DETECTED', 'APPROVER_UNRESOLVED', 'AUTO_APPROVED', 'STAGE_APPROVED',
                'APPROVED', 'REJECTED'
              )
            ),
            CONSTRAINT "overtime_action_stage_check"
              CHECK (stage IS NULL OR stage IN ('MANAGER', 'HR'))
        );

        CREATE INDEX IF NOT EXISTS overtime_action_record_idx
          ON overtime_action (company_id, overtime_record_id, created_at);

        ALTER TABLE overtime_action ENABLE ROW LEVEL SECURITY;
        ALTER TABLE overtime_action FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON overtime_action;
        CREATE POLICY tenant_isolation ON overtime_action
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS overtime_action;
        DROP TABLE IF EXISTS overtime_record;
        """
    )
