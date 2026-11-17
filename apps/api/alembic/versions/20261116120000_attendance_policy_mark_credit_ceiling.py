"""R-2 (owner decision D-01b): `attendance_policy_version.mark_credit_ceiling_minutes`.

Revision ID: 20261116120000
Revises: 20261116110000

A late or early *mark* may credit minutes beyond the grace to the hour-band lookup, bounded by ONE
combined ceiling per day (late and early together). The ceiling is a setting of the policy version
(default 59, range 0-120, 0 = no beyond-grace mark credit). Plain grace is credited separately and
never uses the ceiling. Published versions stay immutable: a new value needs a new version.

Existing versions read 59, which is what the engine applied (as a per-end figure) before this
change; the engine's combined rule is the behaviour change, not the data. Additive; no row is
rewritten (a constant default on Postgres 16 is a catalogue-only change).

Downgrade refuses while any version holds a value other than 59: dropping the column would silently
discard a configured policy value.
"""

from alembic import op

revision = "20261116120000"
down_revision = "20261116110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_policy_version
          ADD COLUMN IF NOT EXISTS "mark_credit_ceiling_minutes" INTEGER NOT NULL DEFAULT 59;
        ALTER TABLE attendance_policy_version
          DROP CONSTRAINT IF EXISTS attendance_policy_version_mark_credit_ceiling_check;
        ALTER TABLE attendance_policy_version
          ADD CONSTRAINT attendance_policy_version_mark_credit_ceiling_check
          CHECK (mark_credit_ceiling_minutes BETWEEN 0 AND 120);
        """
    )


def downgrade() -> None:
    """Refuses while a configured (non-default) ceiling exists; nothing is changed then.
    `row_security = off` makes the check see every tenant's rows (it fails, never undercounts, if
    the migration role cannot bypass row security)."""
    op.execute(
        """
        SET LOCAL row_security = off;
        DO $$
        DECLARE
          n bigint;
        BEGIN
          SELECT count(*) INTO n FROM attendance_policy_version
           WHERE mark_credit_ceiling_minutes <> 59;
          IF n > 0 THEN
            RAISE EXCEPTION
              'Refusing to downgrade 20261116120000: % attendance policy version(s) hold a '
              'configured mark credit ceiling other than 59 that the column drop would discard. '
              'Restore from a pre-upgrade backup, or keep this revision.', n;
          END IF;
        END
        $$;
        ALTER TABLE attendance_policy_version
          DROP CONSTRAINT IF EXISTS attendance_policy_version_mark_credit_ceiling_check;
        ALTER TABLE attendance_policy_version DROP COLUMN IF EXISTS "mark_credit_ceiling_minutes";
        """
    )
