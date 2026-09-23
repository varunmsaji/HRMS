"""Payroll input correctness, step 1a — `attendance_day.leave_fraction` and the new
`attendance_period_summary` columns (PAY-002/PAY-003), plus the PAY-004/PAY-005 fraction fix for
already-computed unlocked rows.

See `docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decisions 2 and 16 and its "Derived rules for the
attendance period summary" section.

- `attendance_day.leave_fraction` — backfilled for **unlocked** rows only, from the APPROVED
  `leave_day_projection` rows that `_apply_leave_overlay` would have honoured (status
  `LEAVE`/`HALF_DAY`, not `work_on_leave_flagged`). Locked rows are frozen history and untouched.
- `NOT_JOINED`/`EXITED` unlocked rows are reset to `paid_day_fraction = lop_fraction = 0.00`
  (previously paid 1.00 / LOP 1.00 respectively). Locked rows are untouched.
- New summary columns are nullable: NULL marks a summary frozen before this revision, whose
  buckets used the old overlapping semantics. Frozen summaries are never regenerated.

Revision ID: 20261004090000
Revises: 20261003092000
"""

from alembic import op

revision = "20261004090000"
down_revision = "20261003092000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day
          ADD COLUMN IF NOT EXISTS leave_fraction NUMERIC(3, 2) NOT NULL DEFAULT 0;

        ALTER TABLE attendance_period_summary
          ADD COLUMN IF NOT EXISTS on_duty_days NUMERIC(6, 2),
          ADD COLUMN IF NOT EXISTS incomplete_days NUMERIC(6, 2),
          ADD COLUMN IF NOT EXISTS not_employed_days NUMERIC(6, 2),
          ADD COLUMN IF NOT EXISTS paid_days NUMERIC(6, 2),
          ADD COLUMN IF NOT EXISTS payable_days NUMERIC(6, 2);

        UPDATE attendance_day AS d
           SET leave_fraction = LEAST(1.00, p.total_fraction)
          FROM (
                SELECT company_id, employee_id, attendance_date, SUM(fraction) AS total_fraction
                  FROM leave_day_projection
                 WHERE status = 'APPROVED'
                 GROUP BY company_id, employee_id, attendance_date
               ) AS p
         WHERE d.company_id = p.company_id
           AND d.employee_id = p.employee_id
           AND d.attendance_date = p.attendance_date
           AND d.is_locked = false
           AND d.work_on_leave_flagged = false
           AND d.attendance_status IN ('LEAVE', 'HALF_DAY');

        UPDATE attendance_day
           SET paid_day_fraction = 0, lop_fraction = 0
         WHERE is_locked = false
           AND attendance_status IN ('NOT_JOINED', 'EXITED');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_period_summary
          DROP COLUMN IF EXISTS payable_days,
          DROP COLUMN IF EXISTS paid_days,
          DROP COLUMN IF EXISTS not_employed_days,
          DROP COLUMN IF EXISTS incomplete_days,
          DROP COLUMN IF EXISTS on_duty_days;

        ALTER TABLE attendance_day
          DROP COLUMN IF EXISTS leave_fraction;
        """
    )
