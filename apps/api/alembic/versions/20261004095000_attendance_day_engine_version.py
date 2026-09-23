"""Payroll input correctness — `attendance_day.engine_version` (PAY-008).

`calculation_version` is a per-row recompute counter, not an identifier of the algorithm. This
column stores `hrms.modules.attendance.calculation.ENGINE_VERSION` for every newly computed row.
Existing rows stay NULL: they were computed by an unversioned engine and there is no reliable
way to tell which one. The matching derived sibling-day inputs are recorded in
`computation_snapshot["derived_inputs"]` from now on (no column needed).

Revision ID: 20261004095000
Revises: 20261004094000
"""

from alembic import op

revision = "20261004095000"
down_revision = "20261004094000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE attendance_day ADD COLUMN IF NOT EXISTS engine_version INTEGER;")


def downgrade() -> None:
    op.execute("ALTER TABLE attendance_day DROP COLUMN IF EXISTS engine_version;")
