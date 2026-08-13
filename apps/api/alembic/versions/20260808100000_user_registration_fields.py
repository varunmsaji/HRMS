"""User name fields — Task C-08 (docs/modules/company/04_API_Design.md §2).

`POST /v1/companies/register` requires `admin_first_name`/`admin_last_name`, but neither
column exists on `user` in the deployed schema or the ORM model (confirmed absent from both
`scripts/sql/001_init_schema.sql` and `hrms/core/db/models/identity.py::User`). Anticipated
explicitly by `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`'s registration task note: "no
`full_name` field exists on `User` yet; add `first_name`/`last_name VARCHAR(100)` nullable
columns to `user` in this task's migration." Nullable — additive, no backfill needed for
existing seeded users.

Revision ID: 20260808100000
Revises: 20260807180000
"""

from alembic import op

revision = "20260808100000"
down_revision = "20260807180000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE "user"
          ADD COLUMN IF NOT EXISTS first_name VARCHAR(100),
          ADD COLUMN IF NOT EXISTS last_name VARCHAR(100);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE "user"
          DROP COLUMN IF EXISTS last_name,
          DROP COLUMN IF EXISTS first_name;
        """
    )
