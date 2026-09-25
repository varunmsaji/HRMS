"""W4 (2/2) — new `attendance_day` and `attendance_break` tables.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §19-22 and WD-10/WD-11:
`attendance_day` is the derived, fully-recomputed-not-patched calculation result, one row per
employee per attendance date (`UNIQUE (company_id, employee_id, attendance_date)`). Every
version FK actually used in the calculation is stored (reproducibility) alongside a
`computation_snapshot` JSONB trace. `attendance_break` is a no-independent-lifecycle child,
full-replaced on every recompute, mirroring `shift_break`.

Partitioning is deliberately not implemented here — see `20260820090000_punch.py`'s note and
decision log entry WD-26.

Revision ID: 20260820100000
Revises: 20260820090000
"""

from alembic import op

revision = "20260820100000"
down_revision = "20260820090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_day (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "attendance_date" DATE NOT NULL,
            "timezone" VARCHAR(64) NOT NULL,

            "shift_id" UUID,
            "shift_version_id" UUID,
            "work_calendar_id" UUID,
            "attendance_policy_version_id" UUID,
            "overtime_policy_version_id" UUID,
            "regularization_policy_version_id" UUID,

            "calendar_day_type" VARCHAR(20),
            "holiday_name" VARCHAR(150),
            "holiday_on_weekly_off" BOOLEAN NOT NULL DEFAULT false,

            "scheduled_start" TIMESTAMPTZ,
            "scheduled_end" TIMESTAMPTZ,
            "scheduled_minutes" INTEGER,

            "actual_first_in" TIMESTAMPTZ,
            "actual_last_out" TIMESTAMPTZ,
            "worked_minutes" INTEGER NOT NULL DEFAULT 0,
            "unpaid_break_minutes" INTEGER NOT NULL DEFAULT 0,
            "paid_break_minutes" INTEGER NOT NULL DEFAULT 0,
            "excess_break_minutes" INTEGER NOT NULL DEFAULT 0,

            "attendance_status" VARCHAR(20) NOT NULL,
            "late_minutes" INTEGER NOT NULL DEFAULT 0,
            "early_departure_minutes" INTEGER NOT NULL DEFAULT 0,
            "late_classification" VARCHAR(20),
            "early_departure_classification" VARCHAR(20),
            "missing_punch" BOOLEAN NOT NULL DEFAULT false,
            "auto_closed" BOOLEAN NOT NULL DEFAULT false,

            "is_late" BOOLEAN NOT NULL DEFAULT false,
            "is_early_out" BOOLEAN NOT NULL DEFAULT false,
            "is_overtime" BOOLEAN NOT NULL DEFAULT false,
            "is_regularized" BOOLEAN NOT NULL DEFAULT false,
            "is_pending_approval" BOOLEAN NOT NULL DEFAULT false,
            "worked_on_holiday" BOOLEAN NOT NULL DEFAULT false,
            "worked_on_weekly_off" BOOLEAN NOT NULL DEFAULT false,

            "paid_day_fraction" NUMERIC(3, 2) NOT NULL DEFAULT 0,
            "lop_fraction" NUMERIC(3, 2) NOT NULL DEFAULT 0,

            "ot_minutes_detected" INTEGER NOT NULL DEFAULT 0,
            "ot_minutes_approved" INTEGER NOT NULL DEFAULT 0,
            "ot_pending" BOOLEAN NOT NULL DEFAULT false,
            "ot_classification" VARCHAR(20),
            "comp_off_minutes_earned" INTEGER NOT NULL DEFAULT 0,

            "calculation_version" INTEGER NOT NULL DEFAULT 1,
            "computation_snapshot" JSONB,
            "calculated_at" TIMESTAMPTZ,

            "is_locked" BOOLEAN NOT NULL DEFAULT false,
            "locked_at" TIMESTAMPTZ,
            "locked_by" UUID,

            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_day_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_day_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_day_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_day_shift_id_fkey" FOREIGN KEY ("shift_id")
              REFERENCES "shift"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_day_shift_version_id_fkey" FOREIGN KEY ("shift_version_id")
              REFERENCES "shift_version"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_day_work_calendar_id_fkey" FOREIGN KEY ("work_calendar_id")
              REFERENCES "work_calendar"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_day_attendance_policy_version_id_fkey"
              FOREIGN KEY ("attendance_policy_version_id")
              REFERENCES "attendance_policy_version"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_day_overtime_policy_version_id_fkey"
              FOREIGN KEY ("overtime_policy_version_id")
              REFERENCES "overtime_policy_version"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_day_regularization_policy_version_id_fkey"
              FOREIGN KEY ("regularization_policy_version_id")
              REFERENCES "regularization_policy_version"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_day_locked_by_fkey" FOREIGN KEY ("locked_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "attendance_day_status_check" CHECK (attendance_status IN (
              'NOT_JOINED', 'EXITED', 'NOT_EXPECTED', 'PRESENT', 'HALF_DAY', 'ABSENT',
              'LEAVE', 'ON_DUTY', 'WFH', 'INCOMPLETE', 'CONFIG_ERROR'
            )),
            CONSTRAINT "attendance_day_unique"
              UNIQUE ("company_id", "employee_id", "attendance_date")
        );

        CREATE INDEX IF NOT EXISTS attendance_day_company_id_idx ON attendance_day (company_id);
        CREATE INDEX IF NOT EXISTS attendance_day_company_date_status_idx
          ON attendance_day (company_id, attendance_date, attendance_status);
        CREATE INDEX IF NOT EXISTS attendance_day_employee_date_idx
          ON attendance_day (company_id, employee_id, attendance_date DESC);

        ALTER TABLE attendance_day ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_day FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_day;
        CREATE POLICY tenant_isolation ON attendance_day
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS attendance_break (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "attendance_day_id" UUID NOT NULL,
            "shift_break_id" UUID,
            "break_start" TIMESTAMPTZ,
            "break_end" TIMESTAMPTZ,
            "minutes" INTEGER NOT NULL DEFAULT 0,
            "is_paid" BOOLEAN NOT NULL DEFAULT false,
            "is_excess" BOOLEAN NOT NULL DEFAULT false,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "attendance_break_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "attendance_break_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "attendance_break_attendance_day_id_fkey" FOREIGN KEY ("attendance_day_id")
              REFERENCES "attendance_day"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "attendance_break_shift_break_id_fkey" FOREIGN KEY ("shift_break_id")
              REFERENCES "shift_break"("id") ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS attendance_break_day_id_idx
          ON attendance_break (attendance_day_id);
        CREATE INDEX IF NOT EXISTS attendance_break_company_id_idx
          ON attendance_break (company_id);

        ALTER TABLE attendance_break ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_break FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON attendance_break;
        CREATE POLICY tenant_isolation ON attendance_break
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS attendance_break;
        DROP TABLE IF EXISTS attendance_day;
        """
    )
