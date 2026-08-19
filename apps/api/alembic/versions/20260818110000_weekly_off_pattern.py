"""Workforce Calendar W1 (3/5) — new `weekly_off_pattern` + `weekly_off_rule` tables.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §8.1 and WD-14 ("Weekly-off is
typed rules, not arbitrary JSON" — rejects `pattern JSONB` from
`08_Database_Architecture.md` §5). `week_off_pattern` never existed at any point in this
codebase (confirmed by direct search) — this is a genuine foundational `CREATE TABLE`, not an
expansion of a stub.

`weekly_off_pattern`: identity + `pattern_kind` (`FIXED_WEEKDAYS` / `NTH_WEEKDAY` /
`ALTERNATE` / `CUSTOM`) — the Organisation master shape (Shift/Grade precedent).

`weekly_off_rule`: child rows. Carries its own `company_id` + RLS rather than relying on a
join through `pattern_id` — this codebase's dominant convention for "child" tables
post-`001_init_schema.sql` (`employee_assignment`, `employee_bank`, etc. all carry their own
`company_id`+RLS despite having an obvious parent), not the retired join-away pattern that
only ever existed for tables with no `company_id` column at all.

Columns exactly as architecture §8.1: `weekday` (0-6), `nth_in_month` (nullable, `-1` = last
occurrence in month), `cycle_start_date` (nullable, for `ALTERNATE`'s week-A/week-B parity),
`off_fraction` (`1.00` full day off / `0.50` half day off), `week_parity` (nullable
`EVEN`/`ODD`).

Revision ID: 20260818110000
Revises: 20260818100000
"""

from alembic import op

revision = "20260818110000"
down_revision = "20260818100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_off_pattern (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "name" VARCHAR(150) NOT NULL,
            "code" VARCHAR(30),
            "pattern_kind" VARCHAR(20) NOT NULL,
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "weekly_off_pattern_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "weekly_off_pattern_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "weekly_off_pattern_kind_check"
              CHECK (pattern_kind IN ('FIXED_WEEKDAYS', 'NTH_WEEKDAY', 'ALTERNATE', 'CUSTOM'))
        );

        CREATE INDEX IF NOT EXISTS weekly_off_pattern_company_id_idx
          ON weekly_off_pattern (company_id);
        CREATE UNIQUE INDEX IF NOT EXISTS weekly_off_pattern_company_id_code_idx
          ON weekly_off_pattern (company_id, code)
          WHERE code IS NOT NULL AND deleted_at IS NULL;

        ALTER TABLE weekly_off_pattern ENABLE ROW LEVEL SECURITY;
        ALTER TABLE weekly_off_pattern FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON weekly_off_pattern;
        CREATE POLICY tenant_isolation ON weekly_off_pattern
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS weekly_off_rule (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "pattern_id" UUID NOT NULL,
            "weekday" SMALLINT NOT NULL,
            "nth_in_month" SMALLINT,
            "cycle_start_date" DATE,
            "off_fraction" NUMERIC(3, 2) NOT NULL DEFAULT 1.00,
            "week_parity" VARCHAR(4),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "weekly_off_rule_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "weekly_off_rule_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "weekly_off_rule_pattern_id_fkey" FOREIGN KEY ("pattern_id")
              REFERENCES "weekly_off_pattern"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "weekly_off_rule_weekday_check" CHECK (weekday BETWEEN 0 AND 6),
            CONSTRAINT "weekly_off_rule_nth_in_month_check"
              CHECK (nth_in_month IS NULL OR nth_in_month IN (-1, 1, 2, 3, 4, 5)),
            CONSTRAINT "weekly_off_rule_off_fraction_check"
              CHECK (off_fraction IN (0.50, 1.00)),
            CONSTRAINT "weekly_off_rule_week_parity_check"
              CHECK (week_parity IS NULL OR week_parity IN ('EVEN', 'ODD'))
        );

        CREATE INDEX IF NOT EXISTS weekly_off_rule_company_id_idx
          ON weekly_off_rule (company_id);
        CREATE INDEX IF NOT EXISTS weekly_off_rule_pattern_id_idx
          ON weekly_off_rule (pattern_id);

        ALTER TABLE weekly_off_rule ENABLE ROW LEVEL SECURITY;
        ALTER TABLE weekly_off_rule FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON weekly_off_rule;
        CREATE POLICY tenant_isolation ON weekly_off_rule
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS weekly_off_rule;
        DROP TABLE IF EXISTS weekly_off_pattern;
        """
    )
