"""Payroll input correctness, step 1b — work-on-leave resolution (BUS-012,
`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 5).

A full-day approved leave now always wins over punches (paid once, as leave) and flags the day;
period finalize is blocked (`WORK_ON_LEAVE_UNRESOLVED`) until HR cancels the leave or records
`KEEP_LEAVE` here.

Existing unlocked rows computed under the former `PRESENT_CANCEL_LEAVE_HINT` mode (paid as
present while the leave stayed debited) keep their old figures until recomputed; they are
already flagged, so the new finalize gate stops them reaching a frozen summary unresolved.

Revision ID: 20261004092000
Revises: 20261004091000
"""

from alembic import op

revision = "20261004092000"
down_revision = "20261004091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day
          ADD COLUMN IF NOT EXISTS work_on_leave_resolution VARCHAR(20),
          ADD COLUMN IF NOT EXISTS work_on_leave_resolution_reason TEXT,
          ADD COLUMN IF NOT EXISTS work_on_leave_resolved_by UUID,
          ADD COLUMN IF NOT EXISTS work_on_leave_resolved_at TIMESTAMPTZ;

        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'attendance_day_work_on_leave_resolved_by_fkey'
          ) THEN
            ALTER TABLE attendance_day
              ADD CONSTRAINT attendance_day_work_on_leave_resolved_by_fkey
              FOREIGN KEY (work_on_leave_resolved_by) REFERENCES "user"(id) ON DELETE SET NULL;
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'attendance_day_work_on_leave_resolution_check'
          ) THEN
            ALTER TABLE attendance_day
              ADD CONSTRAINT attendance_day_work_on_leave_resolution_check
              CHECK (work_on_leave_resolution IS NULL OR work_on_leave_resolution = 'KEEP_LEAVE');
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day
          DROP CONSTRAINT IF EXISTS attendance_day_work_on_leave_resolution_check,
          DROP CONSTRAINT IF EXISTS attendance_day_work_on_leave_resolved_by_fkey,
          DROP COLUMN IF EXISTS work_on_leave_resolved_at,
          DROP COLUMN IF EXISTS work_on_leave_resolved_by,
          DROP COLUMN IF EXISTS work_on_leave_resolution_reason,
          DROP COLUMN IF EXISTS work_on_leave_resolution;
        """
    )
