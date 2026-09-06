"""Leave combination rules — new `leave_combination_rule` table.

Per `docs/architecture/LEAVE_DECISION_LOG.md` LD-16: client spec §7 wants configurable pairwise
exclusivity between leave types (e.g. "CL + SL = Not Allowed", "AL + CL = Allowed"). Each row
names an unordered pair of `leave_type_id`s and whether that pair may be applied for on
overlapping dates — absence of a row for a pair means allowed (matches today's behavior, where
nothing blocks any combination).

The pair is genuinely unordered (CL+SL and SL+CL are the same rule), so the unique index is an
expression index over `LEAST`/`GREATEST` of the two ids rather than the raw columns — this is
the one place in this schema a pair's storage order doesn't matter, unlike every FK pair
elsewhere in this codebase.

Revision ID: 20260911090000
Revises: 20260910090000
"""

from alembic import op

revision = "20260911090000"
down_revision = "20260910090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_combination_rule (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "leave_type_id_a" UUID NOT NULL,
            "leave_type_id_b" UUID NOT NULL,
            "allowed" BOOLEAN NOT NULL,
            "reason" TEXT,
            "created_by_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "leave_combination_rule_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_combination_rule_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_combination_rule_leave_type_id_a_fkey" FOREIGN KEY ("leave_type_id_a")
              REFERENCES "leave_type"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_combination_rule_leave_type_id_b_fkey" FOREIGN KEY ("leave_type_id_b")
              REFERENCES "leave_type"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "leave_combination_rule_created_by_user_id_fkey"
              FOREIGN KEY ("created_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "leave_combination_rule_distinct_types_check"
              CHECK (leave_type_id_a <> leave_type_id_b)
        );

        CREATE INDEX IF NOT EXISTS leave_combination_rule_company_id_idx
          ON leave_combination_rule (company_id);

        -- Unordered-pair uniqueness: a rule for (A, B) conflicts with one for (B, A).
        CREATE UNIQUE INDEX IF NOT EXISTS leave_combination_rule_pair_idx
          ON leave_combination_rule (
            company_id,
            LEAST(leave_type_id_a, leave_type_id_b),
            GREATEST(leave_type_id_a, leave_type_id_b)
          );

        ALTER TABLE leave_combination_rule ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_combination_rule FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_combination_rule;
        CREATE POLICY tenant_isolation ON leave_combination_rule
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leave_combination_rule;")
