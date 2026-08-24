"""W9 — `leave_day_projection` + `attendance_day.work_on_leave_flagged`.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §21 and decision log WD-31:
`leave_day_projection` is the attendance-owned mirror of architecture §21's `LeaveDayProjection`
read model — "a read model published by Leave (service method, not table sharing)". No Leave
module exists yet (architecture §30: "Leave projection adapter, mocked until Leave exists"), so
this table stands in for that service call. It is **not** the leave ledger (ADR-0004 untouched)
and is replaceable wholesale once a real Leave module ships.

`attendance_day.work_on_leave_flagged` is a small additive column consumed by the same slice:
set only when punches exist despite an approved full-day leave projection and policy
`work_on_leave_behaviour=PRESENT_CANCEL_LEAVE_HINT` (a column that shipped in W3, unused until
now) — Attendance flags the day for Leave to review, never cancels the leave itself.

Revision ID: 20260825090000
Revises: 20260824090000
"""

from alembic import op

revision = "20260825090000"
down_revision = "20260824090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day
          ADD COLUMN IF NOT EXISTS "work_on_leave_flagged" BOOLEAN NOT NULL DEFAULT false;

        CREATE TABLE IF NOT EXISTS leave_day_projection (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "attendance_date" DATE NOT NULL,

            "leave_application_id" UUID NOT NULL,
            "leave_type_id" UUID,
            "leave_type_code" VARCHAR(30),

            "fraction" NUMERIC(3,2) NOT NULL,
            "half" VARCHAR(10),
            "is_paid" BOOLEAN NOT NULL,

            "status" VARCHAR(20) NOT NULL DEFAULT 'APPROVED',
            "source_version" INTEGER NOT NULL DEFAULT 1,

            "synced_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "cancelled_at" TIMESTAMPTZ,
            "cancelled_reason" TEXT,

            "created_by_user_id" UUID,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "leave_day_projection_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_day_projection_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_day_projection_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT,
            CONSTRAINT "leave_day_projection_created_by_user_id_fkey"
              FOREIGN KEY ("created_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_day_projection_fraction_check"
              CHECK (fraction IN (0.50, 1.00)),
            CONSTRAINT "leave_day_projection_half_check"
              CHECK (half IS NULL OR half IN ('FIRST', 'SECOND')),
            CONSTRAINT "leave_day_projection_status_check"
              CHECK (status IN ('APPROVED', 'CANCELLED')),
            CONSTRAINT "leave_day_projection_natural_key"
              UNIQUE ("company_id", "employee_id", "attendance_date", "leave_application_id")
        );

        CREATE INDEX IF NOT EXISTS leave_day_projection_employee_date_idx
          ON leave_day_projection (company_id, employee_id, attendance_date);

        ALTER TABLE leave_day_projection ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_day_projection FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_day_projection;
        CREATE POLICY tenant_isolation ON leave_day_projection
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS leave_day_projection;
        ALTER TABLE attendance_day DROP COLUMN IF EXISTS "work_on_leave_flagged";
        """
    )
