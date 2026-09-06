"""Legal compliance floor — `leave_type.statutory_category` + new `statutory_leave_minimum`
table (client spec §16, LEAVE_DECISION_LOG.md LD-22).

Client answers (2026-09-06): India-only scope, hard-block publishing a `LeavePolicyVersion` below
the applicable statutory minimum. No actual legal figures are hardcoded anywhere in this
migration or the application code — the same "engine reads whatever is configured" posture LD-06
already established for accrual — HR/compliance enters the minimums that apply to their states via
the new admin CRUD surface. `statutory_category` classifies a company's free-form `LeaveType` rows
(e.g. "Privilege Leave", "Casual Leave") against a small fixed statutory taxonomy so the
publish-time check can compare like against like; NULL means "not a statutorily-governed leave
type" (LOP, comp-off, bereavement, ...) and is never checked.

Revision ID: 20260916090000
Revises: 20260915090000
"""

from alembic import op

revision = "20260916090000"
down_revision = "20260915090000"
branch_labels = None
depends_on = None

_CATEGORIES = "'EARNED', 'SICK', 'CASUAL', 'MATERNITY', 'PATERNITY'"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE leave_type
          ADD COLUMN IF NOT EXISTS statutory_category VARCHAR(20);

        ALTER TABLE leave_type
          ADD CONSTRAINT leave_type_statutory_category_check
          CHECK (statutory_category IS NULL OR statutory_category IN ({_CATEGORIES}));

        CREATE TABLE IF NOT EXISTS statutory_leave_minimum (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "state_code" VARCHAR(10),
            "establishment_type" VARCHAR(30),
            "leave_category" VARCHAR(20) NOT NULL,
            "min_days_per_year" NUMERIC(5, 2) NOT NULL,
            "note" TEXT,
            "created_by_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "statutory_leave_minimum_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "statutory_leave_minimum_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "statutory_leave_minimum_created_by_user_id_fkey"
              FOREIGN KEY ("created_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "statutory_leave_minimum_category_check"
              CHECK (leave_category IN ({_CATEGORIES})),
            CONSTRAINT "statutory_leave_minimum_min_days_check" CHECK (min_days_per_year >= 0)
        );

        CREATE INDEX IF NOT EXISTS statutory_leave_minimum_company_id_idx
          ON statutory_leave_minimum (company_id);

        CREATE INDEX IF NOT EXISTS statutory_leave_minimum_lookup_idx
          ON statutory_leave_minimum (company_id, leave_category);

        ALTER TABLE statutory_leave_minimum ENABLE ROW LEVEL SECURITY;
        ALTER TABLE statutory_leave_minimum FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON statutory_leave_minimum;
        CREATE POLICY tenant_isolation ON statutory_leave_minimum
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS statutory_leave_minimum;
        ALTER TABLE leave_type DROP CONSTRAINT IF EXISTS leave_type_statutory_category_check;
        ALTER TABLE leave_type DROP COLUMN IF EXISTS statutory_category;
        """
    )
