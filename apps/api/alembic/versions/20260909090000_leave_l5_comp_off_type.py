"""L5 (1/1 schema) — `is_comp_off` flag on `leave_type`.

Per `docs/architecture/LEAVE_DECISION_LOG.md` LD-14: `OvertimeRecord` (attendance module) has no
`leave_type_id` of its own, so crediting comp-off needs a way to name which `LeaveType` row is
"the" comp-off balance for a company. Mirrors the existing `is_paid_default`/`requires_balance`
flag convention on `leave_type` rather than adding a new settings concept — a company creates one
ordinary `LeaveType` row (e.g. code=`COMP_OFF`) and marks it `is_comp_off=true`.

The partial unique index enforces at most one active, non-deleted `is_comp_off=true` row per
company — `leave_type` already has real rows in some environments (unlike the 0-row tables LD-10/
LD-11 could freely re-shape), so this is additive-only: `false` by default, no backfill needed,
and the credit engine simply skips crediting for any company that hasn't designated one yet
(same "not configured yet is a valid, non-error state" posture the accrual engine already uses).

Revision ID: 20260909090000
Revises: 20260908090000
"""

from alembic import op

revision = "20260909090000"
down_revision = "20260908090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_type
          ADD COLUMN IF NOT EXISTS is_comp_off BOOLEAN NOT NULL DEFAULT false;

        CREATE UNIQUE INDEX IF NOT EXISTS leave_type_company_comp_off_idx
          ON leave_type (company_id)
          WHERE is_comp_off AND is_active AND deleted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS leave_type_company_comp_off_idx;
        ALTER TABLE leave_type
          DROP COLUMN IF EXISTS is_comp_off;
        """
    )
