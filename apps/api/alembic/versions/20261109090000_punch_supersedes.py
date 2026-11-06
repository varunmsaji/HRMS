"""Punch: let an approved wrong-punch correction replace the punch it corrects.

Revision ID: 20261109090000
Revises: 20261108090000

Adds `punch.supersedes_punch_id`, a nullable self-reference. Punches stay immutable: a correction is
a new row pointing at the one it replaces, and calculation ignores any punch that something
supersedes. NULL on every existing row, so existing days calculate as they did before.
"""

from alembic import op

revision = "20261109090000"
down_revision = "20261108090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE punch
          ADD COLUMN IF NOT EXISTS supersedes_punch_id UUID REFERENCES punch (id);
        CREATE INDEX IF NOT EXISTS ix_punch_supersedes_punch_id
          ON punch (supersedes_punch_id)
          WHERE supersedes_punch_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_punch_supersedes_punch_id;
        ALTER TABLE punch DROP COLUMN IF EXISTS supersedes_punch_id;
        """
    )
