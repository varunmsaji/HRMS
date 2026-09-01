"""L4 — `leave_application`/`leave_application_day`/`leave_application_action` (LD-02, LD-05).

`leave_application` mirrors `attendance_regularization_request`'s shape (status/approval_chain/
approval_stage/resolved_approver_manager_id state machine, snapshotted policy version FK) —
mirrored, not shared code (LD-05). `leave_application_day` is new: one row per calendar date the
application covers (fraction/half/is_sandwich_generated), since a leave application spans a date
range with per-day fractions where Regularization is always single-date. `leave_day_projection_id`
on it is an opaque reference (no FK — `leave_day_projection` lives in `attendance`, cross-module,
mirrors `leave_ledger.reference_id`'s own "not joinable" posture) to the `LeaveDayProjection` row
`LeaveProjectionService.sync()` returns on approval, so a later cancellation
(`LeaveProjectionService.cancel()`, LD-13) can address it directly. `leave_application_action`
mirrors `attendance_regularization_action` exactly — append-only, no `updated_at`/`version`.

Revision ID: 20260904090000
Revises: 20260903090000
"""

from alembic import op

revision = "20260904090000"
down_revision = "20260903090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_application (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "leave_type_id" UUID NOT NULL,
            "leave_policy_version_id" UUID NOT NULL,

            "start_date" DATE NOT NULL,
            "end_date" DATE NOT NULL,
            "total_days" NUMERIC(6, 2) NOT NULL,
            "reason" TEXT,
            "attachment_reference" VARCHAR(500),

            "status" VARCHAR(20) NOT NULL DEFAULT 'SUBMITTED',
            "approval_chain" VARCHAR(20) NOT NULL,
            "approval_stage" VARCHAR(10),
            "resolved_approver_manager_id" UUID,

            "submitted_by_user_id" UUID,
            "submitted_at" TIMESTAMPTZ NOT NULL,

            "reviewed_by_user_id" UUID,
            "reviewed_at" TIMESTAMPTZ,
            "reviewer_comment" TEXT,
            "rejection_reason" TEXT,

            "cancelled_at" TIMESTAMPTZ,
            "cancelled_by_user_id" UUID,

            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "leave_application_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_application_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_application_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_application_leave_type_id_fkey" FOREIGN KEY ("leave_type_id")
              REFERENCES "leave_type"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_application_leave_policy_version_id_fkey"
              FOREIGN KEY ("leave_policy_version_id")
              REFERENCES "leave_policy_version"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_application_resolved_approver_manager_id_fkey"
              FOREIGN KEY ("resolved_approver_manager_id")
              REFERENCES "employee"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_application_submitted_by_user_id_fkey"
              FOREIGN KEY ("submitted_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_application_reviewed_by_user_id_fkey"
              FOREIGN KEY ("reviewed_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_application_cancelled_by_user_id_fkey"
              FOREIGN KEY ("cancelled_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_application_status_check"
              CHECK (status IN ('SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED')),
            CONSTRAINT "leave_application_approval_chain_check"
              CHECK (approval_chain IN ('AUTO', 'MANAGER', 'MANAGER_THEN_HR', 'HR')),
            CONSTRAINT "leave_application_approval_stage_check"
              CHECK (approval_stage IS NULL OR approval_stage IN ('MANAGER', 'HR')),
            CONSTRAINT "leave_application_date_range_check" CHECK (end_date >= start_date)
        );

        CREATE INDEX IF NOT EXISTS leave_application_company_id_idx
          ON leave_application (company_id);
        CREATE INDEX IF NOT EXISTS leave_application_employee_id_idx
          ON leave_application (company_id, employee_id);

        ALTER TABLE leave_application ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_application FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_application;
        CREATE POLICY tenant_isolation ON leave_application
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS leave_application_day (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "leave_application_id" UUID NOT NULL,
            "calendar_date" DATE NOT NULL,
            "fraction" NUMERIC(3, 2) NOT NULL,
            "half" VARCHAR(10),
            "is_sandwich_generated" BOOLEAN NOT NULL DEFAULT false,
            "leave_day_projection_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "leave_application_day_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_application_day_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_application_day_leave_application_id_fkey"
              FOREIGN KEY ("leave_application_id")
              REFERENCES "leave_application"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_application_day_fraction_check"
              CHECK (fraction > 0 AND fraction <= 1),
            CONSTRAINT "leave_application_day_unique_date"
              UNIQUE (leave_application_id, calendar_date)
        );

        CREATE INDEX IF NOT EXISTS leave_application_day_company_id_idx
          ON leave_application_day (company_id);
        CREATE INDEX IF NOT EXISTS leave_application_day_application_id_idx
          ON leave_application_day (leave_application_id);

        ALTER TABLE leave_application_day ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_application_day FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_application_day;
        CREATE POLICY tenant_isolation ON leave_application_day
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS leave_application_action (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "leave_application_id" UUID NOT NULL,
            "action" VARCHAR(30) NOT NULL,
            "actor_user_id" UUID,
            "actor_employee_id" UUID,
            "stage" VARCHAR(10),
            "comment" TEXT,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "leave_application_action_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_application_action_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_application_action_leave_application_id_fkey"
              FOREIGN KEY ("leave_application_id")
              REFERENCES "leave_application"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_application_action_actor_user_id_fkey"
              FOREIGN KEY ("actor_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_application_action_actor_employee_id_fkey"
              FOREIGN KEY ("actor_employee_id") REFERENCES "employee"("id") ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS leave_application_action_company_id_idx
          ON leave_application_action (company_id);
        CREATE INDEX IF NOT EXISTS leave_application_action_application_id_idx
          ON leave_application_action (leave_application_id);

        ALTER TABLE leave_application_action ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_application_action FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_application_action;
        CREATE POLICY tenant_isolation ON leave_application_action
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS leave_application_action;
        DROP TABLE IF EXISTS leave_application_day;
        DROP TABLE IF EXISTS leave_application;
        """
    )
