"""W3 (1/4) — widen `policy_assignment.policy_kind` CHECK to admit the three new policy kinds.

Per WD-24 in `docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md`: the W1 migration
(`20260818130000_policy_assignment`) deliberately narrowed `policy_kind` to
`('WORK_CALENDAR', 'WEEKLY_OFF')` with an explicit comment that W3 would widen it via
`ALTER TABLE ... DROP/ADD CONSTRAINT` rather than replace the table — the same "ALTER in place"
posture DEC-021 established for `holiday_calendar`/`holiday`, applied here to a table that didn't
exist yet at W1 start.

No other change: the GiST exclusion constraint `policy_assignment_no_overlap` already includes
`policy_kind WITH =` in its column list (migration `20260818130000`), so the three new kinds
automatically participate in the same per-scope no-overlap semantics with zero additional
migration work — only the CHECK needed widening.

Revision ID: 20260819090000
Revises: 20260818140000
"""

from alembic import op

revision = "20260819090000"
down_revision = "20260818140000"
branch_labels = None
depends_on = None

_OLD_KINDS = "('WORK_CALENDAR', 'WEEKLY_OFF')"
_NEW_KINDS = (
    "('WORK_CALENDAR', 'WEEKLY_OFF', 'ATTENDANCE_POLICY', 'OVERTIME_POLICY', "
    "'REGULARIZATION_POLICY')"
)


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_policy_kind_check;
        ALTER TABLE policy_assignment
          ADD CONSTRAINT policy_assignment_policy_kind_check
          CHECK (policy_kind IN {_NEW_KINDS});
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_policy_kind_check;
        ALTER TABLE policy_assignment
          ADD CONSTRAINT policy_assignment_policy_kind_check
          CHECK (policy_kind IN {_OLD_KINDS});
        """
    )
