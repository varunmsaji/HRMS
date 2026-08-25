"""WD-32 — core-hours breach flag, ON_DUTY overlay columns, cumulative excess-break counter.

Per docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md WD-32 (five client sign-off change
requests, §D3/E2/F2/G1/L1): four of the five decisions reuse dormant fields that already existed
from earlier slices (`core_hours_breach_behaviour`, `ShiftVersion.core_start`/`core_end`,
`late_count_window`/`lates_to_half_day_count`, `early_departure_requires_approval`,
`on_duty_requires_punch`) — only decision 2 (cumulative excess-break-days) and decision 1/6's
derived reporting flags need new columns.

`attendance_policy_version`:
- `excess_break_count_window` / `excess_break_days_to_half_day_count` — mirrors the existing
  `late_count_window` / `lates_to_half_day_count` pair exactly (WD-32 decision 2).

`attendance_day`:
- `is_core_hours_breach` — derived, re-resolved every recompute (WD-32 decision 1).
- `on_duty` / `on_duty_regularization_id` — derived ON_DUTY overlay fact + provenance, re-resolved
  every recompute, mirrors `work_on_leave_flagged`'s own shape (WD-32 decision 6).

Revision ID: 20260826090000
Revises: 20260825090000
"""

from alembic import op

revision = "20260826090000"
down_revision = "20260825090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_policy_version
          ADD COLUMN IF NOT EXISTS "excess_break_count_window" VARCHAR(10) NOT NULL DEFAULT 'MONTH',
          ADD COLUMN IF NOT EXISTS "excess_break_days_to_half_day_count" INTEGER;

        ALTER TABLE attendance_day
          ADD COLUMN IF NOT EXISTS "is_core_hours_breach" BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS "on_duty" BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS "on_duty_regularization_id" UUID;

        ALTER TABLE attendance_day
          DROP CONSTRAINT IF EXISTS attendance_day_on_duty_regularization_id_fkey;
        ALTER TABLE attendance_day
          ADD CONSTRAINT attendance_day_on_duty_regularization_id_fkey
            FOREIGN KEY ("on_duty_regularization_id")
            REFERENCES "attendance_regularization_request"("id") ON DELETE SET NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day
          DROP CONSTRAINT IF EXISTS attendance_day_on_duty_regularization_id_fkey;
        ALTER TABLE attendance_day
          DROP COLUMN IF EXISTS "on_duty_regularization_id",
          DROP COLUMN IF EXISTS "on_duty",
          DROP COLUMN IF EXISTS "is_core_hours_breach";

        ALTER TABLE attendance_policy_version
          DROP COLUMN IF EXISTS "excess_break_days_to_half_day_count",
          DROP COLUMN IF EXISTS "excess_break_count_window";
        """
    )
