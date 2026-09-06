"""Employee confirmation — minimal unblock for Leave's probation flags (LD-18).

`employee.status` has never had a DB-level enum lock (unlike `employment.status`, which already
does) because nothing ever wrote to it beyond the hardcoded `PRE_JOINING` default at creation.
This migration adds the CHECK constraint now, since this feature is the first real write path to
the column (`EmploymentService.create_employment`'s new PRE_JOINING -> PROBATION transition,
`EmployeeService.confirm_employee`'s new PROBATION -> ACTIVE transition).

Also adds `employment.probation_end_date` — purely informational (mirrors LD-17's maternity
fields posture), sits next to the existing `joining_date`/`last_working_day` pair. Nothing reads
or auto-computes it; HR sets/corrects it via the existing `EmploymentCreate`/`EmploymentUpdate`
paths.

Revision ID: 20260919090000
Revises: 20260918090000
"""

from alembic import op

revision = "20260919090000"
down_revision = "20260918090000"
branch_labels = None
depends_on = None

_EMPLOYEE_STATUSES = (
    "'PRE_JOINING', 'PROBATION', 'ACTIVE', 'ON_NOTICE', 'SUSPENDED', 'ON_LONG_LEAVE', "
    "'EXITED', 'ABSCONDING', 'RETIRED', 'DECEASED'"
)


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE employment
          ADD COLUMN IF NOT EXISTS probation_end_date DATE;

        ALTER TABLE employee
          ADD CONSTRAINT employee_status_check
            CHECK (status IN ({_EMPLOYEE_STATUSES}));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee
          DROP CONSTRAINT IF EXISTS employee_status_check;

        ALTER TABLE employment
          DROP COLUMN IF EXISTS probation_end_date;
        """
    )
