"""W8 — `attendance_period` + `attendance_period_action` + `attendance_period_summary`.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §4.2/§22 and decision log WD-30:
`attendance_period` is the period lifecycle + lock entity architecture names `AttendanceLock`
(two persisted states, `OPEN`/`CLOSED` — `CLOSED` *is* locked, mirroring how the architecture
itself never describes a closed-but-unlocked state). `attendance_period_action` is the
append-only per-period timeline, mirroring `attendance_regularization_action`/`overtime_action`.
`attendance_period_summary` is the payroll-facing per-employee roll-up architecture §22.2 names
`AttendancePeriodSummary` — written exactly once, inside the same transaction that closes the
period; never regenerated afterwards.

`legal_entity_id` on `attendance_period` is reserved and unused in V1 (always `NULL`) — PD-LOCK-1
(architecture §32) is open between company/legal-entity/pay-cycle lock grain, and its own stated
default (legal-entity grain *only if* Payroll will be LE-scoped) cannot be evaluated because
Payroll does not exist yet; V1 ships the company-grain half of that same default with the column
reserved for a future slice, exactly like `AttendanceDay.is_locked` shipped in W4 ahead of this
table.

Revision ID: 20260824090000
Revises: 20260823090000
"""

from alembic import op

revision = "20260824090000"
down_revision = "20260823090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_period (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "legal_entity_id" UUID,

            "period_start" DATE NOT NULL,
            "period_end" DATE NOT NULL,
            "label" VARCHAR(100),

            "status" VARCHAR(20) NOT NULL DEFAULT 'OPEN',

            "opened_by_user_id" UUID,
            "opened_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            "last_validated_at" TIMESTAMPTZ,
            "last_validation_status" VARCHAR(20),

            "closed_by_user_id" UUID,
            "closed_at" TIMESTAMPTZ,

            "reopened_by_user_id" UUID,
            "reopened_at" TIMESTAMPTZ,
            "reopen_reason" TEXT,

            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_period_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_period_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_period_legal_entity_id_fkey" FOREIGN KEY ("legal_entity_id")
              REFERENCES "legal_entity"("id") ON DELETE RESTRICT,
            CONSTRAINT "attendance_period_opened_by_user_id_fkey"
              FOREIGN KEY ("opened_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_period_closed_by_user_id_fkey"
              FOREIGN KEY ("closed_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_period_reopened_by_user_id_fkey"
              FOREIGN KEY ("reopened_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_period_status_check"
              CHECK (status IN ('OPEN', 'CLOSED')),
            CONSTRAINT "attendance_period_last_validation_status_check"
              CHECK (
                last_validation_status IS NULL
                OR last_validation_status IN ('READY', 'BLOCKED')
              ),
            CONSTRAINT "attendance_period_date_range_check"
              CHECK (period_end >= period_start)
        );

        CREATE INDEX IF NOT EXISTS attendance_period_company_id_idx
          ON attendance_period (company_id);
        CREATE INDEX IF NOT EXISTS attendance_period_range_idx
          ON attendance_period (company_id, period_start, period_end);

        ALTER TABLE attendance_period
          DROP CONSTRAINT IF EXISTS attendance_period_no_overlap;
        ALTER TABLE attendance_period
          ADD CONSTRAINT attendance_period_no_overlap
          EXCLUDE USING gist (
            company_id WITH =,
            daterange(period_start, period_end, '[]') WITH &&
          );

        ALTER TABLE attendance_period ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_period FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_period;
        CREATE POLICY tenant_isolation ON attendance_period
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_period_action (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "attendance_period_id" UUID NOT NULL,
            "action" VARCHAR(30) NOT NULL,
            "actor_user_id" UUID,
            "comment" TEXT,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_period_action_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_period_action_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_period_action_period_id_fkey"
              FOREIGN KEY ("attendance_period_id") REFERENCES "attendance_period"("id")
              ON DELETE CASCADE,
            CONSTRAINT "attendance_period_action_actor_user_id_fkey"
              FOREIGN KEY ("actor_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_period_action_action_check" CHECK (
              action IN ('OPENED', 'VALIDATED', 'VALIDATION_FAILED', 'CLOSED', 'REOPENED')
            )
        );

        CREATE INDEX IF NOT EXISTS attendance_period_action_period_idx
          ON attendance_period_action (company_id, attendance_period_id, created_at);

        ALTER TABLE attendance_period_action ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_period_action FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_period_action;
        CREATE POLICY tenant_isolation ON attendance_period_action
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_period_summary (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "attendance_period_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,

            "present_days" NUMERIC(6,2) NOT NULL DEFAULT 0,
            "absent_days" NUMERIC(6,2) NOT NULL DEFAULT 0,
            "leave_days" NUMERIC(6,2) NOT NULL DEFAULT 0,
            "holiday_days" NUMERIC(6,2) NOT NULL DEFAULT 0,
            "weekly_off_days" NUMERIC(6,2) NOT NULL DEFAULT 0,
            "half_days" NUMERIC(6,2) NOT NULL DEFAULT 0,
            "lop_days" NUMERIC(6,2) NOT NULL DEFAULT 0,

            "ot_minutes_normal" INTEGER NOT NULL DEFAULT 0,
            "ot_minutes_weekly_off" INTEGER NOT NULL DEFAULT 0,
            "ot_minutes_holiday" INTEGER NOT NULL DEFAULT 0,
            "ot_minutes_night" INTEGER NOT NULL DEFAULT 0,
            "comp_off_minutes_earned" INTEGER NOT NULL DEFAULT 0,

            "late_count" INTEGER NOT NULL DEFAULT 0,
            "worked_minutes_total" INTEGER NOT NULL DEFAULT 0,

            "generated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_period_summary_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_period_summary_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_period_summary_period_id_fkey"
              FOREIGN KEY ("attendance_period_id") REFERENCES "attendance_period"("id")
              ON DELETE CASCADE,
            CONSTRAINT "attendance_period_summary_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT,
            CONSTRAINT "attendance_period_summary_unique"
              UNIQUE ("attendance_period_id", "employee_id")
        );

        CREATE INDEX IF NOT EXISTS attendance_period_summary_period_idx
          ON attendance_period_summary (company_id, attendance_period_id);

        ALTER TABLE attendance_period_summary ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_period_summary FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_period_summary;
        CREATE POLICY tenant_isolation ON attendance_period_summary
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS attendance_period_summary;
        DROP TABLE IF EXISTS attendance_period_action;
        DROP TABLE IF EXISTS attendance_period;
        """
    )
