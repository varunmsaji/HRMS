"""LD-10 — bind `leave_policy` to exactly one `leave_type`.

Found while wiring HR-configurable accrual (LD-06): `leave_policy`/`leave_policy_version` (L1)
carry `accrual_rate_per_cycle`/`max_carry_forward_days`/etc, but nothing said *which* leave type
those settings apply to. Adds a required `leave_type_id` FK to the `leave_policy` identity row
(not the version table — the binding doesn't change across a policy's versions, same reasoning as
`code`/`name` living on the identity row). Not unique: multiple policies may target the same leave
type for different `PolicyAssignment` scopes.

`leave_policy` has 0 rows in every environment today (L1 shipped but nothing writes accrual
values through it yet) — a straight `NOT NULL` add, no backfill needed.

Revision ID: 20260902090000
Revises: 20260901090000
"""

from alembic import op

revision = "20260902090000"
down_revision = "20260901090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy
          ADD COLUMN "leave_type_id" UUID;

        ALTER TABLE leave_policy
          ADD CONSTRAINT "leave_policy_leave_type_id_fkey" FOREIGN KEY ("leave_type_id")
            REFERENCES "leave_type"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

        ALTER TABLE leave_policy
          ALTER COLUMN "leave_type_id" SET NOT NULL;

        CREATE INDEX IF NOT EXISTS leave_policy_leave_type_id_idx
          ON leave_policy (leave_type_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS leave_policy_leave_type_id_idx;
        ALTER TABLE leave_policy DROP CONSTRAINT IF EXISTS leave_policy_leave_type_id_fkey;
        ALTER TABLE leave_policy DROP COLUMN IF EXISTS leave_type_id;
        """
    )
