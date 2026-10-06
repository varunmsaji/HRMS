"""`leave_application_day.half` could not store `SECOND_HALF`.

The API vocabulary is `FIRST_HALF` / `SECOND_HALF` (the latter is 11 characters) but the column was
created as `VARCHAR(10)`, so every second-half-day leave application failed on insert (surfaced as
a generic "value out of range" error). Widening a varchar is metadata-only and loses nothing.

Revision ID: 20261009091000
Revises: 20261009090000
"""

from alembic import op

revision = "20261009091000"
down_revision = "20261009090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE leave_application_day ALTER COLUMN half TYPE VARCHAR(20)")


def downgrade() -> None:
    # Narrowing would fail for any stored SECOND_HALF row, so it is deliberately a no-op.
    pass
