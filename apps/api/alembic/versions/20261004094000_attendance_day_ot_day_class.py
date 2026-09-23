"""Payroll input correctness — `attendance_day.ot_day_class`.

The frozen period summary buckets approved OT into normal / weekly-off / holiday / night minutes.
It used to compare `attendance_day.ot_classification` — the overtime policy's **configurable rate
code** — against the literal day-class names, so a policy with codes such as `OT_NIGHT_2X` put all
its OT in `ot_minutes_normal`. The engine's day class (`NORMAL|WEEKLY_OFF|HOLIDAY|NIGHT`) is now
stored on the day row and the summary reads it instead.

Backfill: from `overtime_record.day_class` (recorded since W7) where the day has one, else from
`ot_classification` when it already is one of the four day-class names (the default policy codes).
Locked rows are backfilled too — this records a fact the engine already computed, it does not
change any paid/LOP figure.

Revision ID: 20261004094000
Revises: 20261004093000
"""

from alembic import op

revision = "20261004094000"
down_revision = "20261004093000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_day ADD COLUMN IF NOT EXISTS ot_day_class VARCHAR(20);

        UPDATE attendance_day d
           SET ot_day_class = r.day_class
          FROM overtime_record r
         WHERE r.attendance_day_id = d.id
           AND r.day_class IS NOT NULL
           AND d.ot_day_class IS NULL;

        UPDATE attendance_day
           SET ot_day_class = ot_classification
         WHERE ot_day_class IS NULL
           AND ot_classification IN ('NORMAL', 'WEEKLY_OFF', 'HOLIDAY', 'NIGHT');
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE attendance_day DROP COLUMN IF EXISTS ot_day_class;")
