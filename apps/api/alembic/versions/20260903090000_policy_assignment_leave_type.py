"""LD-11 — add `leave_type_id` dimension to `policy_assignment` for `LEAVE_POLICY`.

Found while building Leave L3's employee->policy resolution: `policy_assignment_no_overlap`
excludes on `(company_id, policy_kind, scope_type, scope_id, daterange)`, which is correct for
every other `policy_kind` (exactly one policy governs a scope at a time) but wrong for
`LEAVE_POLICY` — a company needs multiple simultaneous leave policies at the same scope, one per
leave type. Adds `leave_type_id` (FK -> leave_type.id, real FK unlike the polymorphic `policy_id`),
NULL for every existing kind, required iff `policy_kind = 'LEAVE_POLICY'`, and widens the
exclusion constraint to partition on it (same NULL-sentinel trick already used for `scope_id`).

`policy_assignment` has 0 rows in every environment — a clean add, no backfill.

Revision ID: 20260903090000
Revises: 20260902090000
"""

from alembic import op

revision = "20260903090000"
down_revision = "20260902090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE policy_assignment
          ADD COLUMN "leave_type_id" UUID;

        ALTER TABLE policy_assignment
          ADD CONSTRAINT "policy_assignment_leave_type_id_fkey" FOREIGN KEY ("leave_type_id")
            REFERENCES "leave_type"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

        ALTER TABLE policy_assignment
          ADD CONSTRAINT "policy_assignment_leave_type_id_null_iff_leave_policy_check"
          CHECK ((policy_kind = 'LEAVE_POLICY') = (leave_type_id IS NOT NULL));

        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_no_overlap;
        ALTER TABLE policy_assignment
          ADD CONSTRAINT policy_assignment_no_overlap
          EXCLUDE USING gist (
            company_id WITH =,
            policy_kind WITH =,
            COALESCE(leave_type_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
            scope_type WITH =,
            COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (deleted_at IS NULL);

        CREATE INDEX IF NOT EXISTS policy_assignment_leave_type_id_idx
          ON policy_assignment (leave_type_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS policy_assignment_leave_type_id_idx;

        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_no_overlap;
        ALTER TABLE policy_assignment
          ADD CONSTRAINT policy_assignment_no_overlap
          EXCLUDE USING gist (
            company_id WITH =,
            policy_kind WITH =,
            scope_type WITH =,
            COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =,
            daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
          )
          WHERE (deleted_at IS NULL);

        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_leave_type_id_null_iff_leave_policy_check;
        ALTER TABLE policy_assignment
          DROP CONSTRAINT IF EXISTS policy_assignment_leave_type_id_fkey;
        ALTER TABLE policy_assignment DROP COLUMN IF EXISTS leave_type_id;
        """
    )
