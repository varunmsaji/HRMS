"""Overtime remediation (AC-01): `SUPERSEDED_BY_RECALCULATION` overtime action.

Revision ID: 20261116090000
Revises: 20261115090000

`docs/audits/ATTENDANCE_CALENDAR_OVERTIME_AUDIT_2026-11-16.md` AC-01 / P-C. A recalculation that
changes what an earlier overtime decision was based on records that on the record's own timeline.
Purely additive: the action check constraint gains one value; no row is rewritten.
"""

from alembic import op

revision = "20261116090000"
down_revision = "20261115090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE overtime_action DROP CONSTRAINT IF EXISTS overtime_action_action_check;
        ALTER TABLE overtime_action ADD CONSTRAINT overtime_action_action_check CHECK (
          action IN (
            'DETECTED', 'APPROVER_UNRESOLVED', 'AUTO_APPROVED', 'STAGE_APPROVED',
            'APPROVED', 'REJECTED', 'SUPERSEDED_BY_RECALCULATION'
          )
        );
        """
    )


def downgrade() -> None:
    """Refuses while supersede history exists; it never deletes it.

    `overtime_action` is an audit timeline: rows are never deleted by a schema change. If any
    `SUPERSEDED_BY_RECALCULATION` row exists the downgrade stops, nothing is changed and the
    migration transaction rolls back. Recovery is a decision, not a side effect: restore from a
    backup taken before the upgrade, or leave the check constraint as it is (the extra allowed
    value is harmless to older code, which never writes it). `row_security = off` makes the check
    see every tenant's rows: if the migration role cannot bypass row security the statement
    fails instead of silently counting zero.
    """
    op.execute(
        """
        SET LOCAL row_security = off;
        DO $$
        DECLARE
          n bigint;
        BEGIN
          SELECT count(*) INTO n FROM overtime_action
           WHERE action = 'SUPERSEDED_BY_RECALCULATION';
          IF n > 0 THEN
            RAISE EXCEPTION
              'Refusing to downgrade 20261116090000: % overtime_action row(s) of type '
              'SUPERSEDED_BY_RECALCULATION would violate the narrower check constraint and '
              'deleting them would destroy audit history. Restore from a pre-upgrade backup, or '
              'keep this revision.', n;
          END IF;
        END
        $$;
        ALTER TABLE overtime_action DROP CONSTRAINT IF EXISTS overtime_action_action_check;
        ALTER TABLE overtime_action ADD CONSTRAINT overtime_action_action_check CHECK (
          action IN (
            'DETECTED', 'APPROVER_UNRESOLVED', 'AUTO_APPROVED', 'STAGE_APPROVED',
            'APPROVED', 'REJECTED'
          )
        );
        """
    )
