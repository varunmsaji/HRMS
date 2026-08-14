"""Shift Rules — shift master table (Sprint 3 Feature 4.2 Task 4.2.1, Decision D5;
docs/product/17_SRS_Phase1_Core_Modules.md FR-ATT-001).

Brand-new table — unlike every prior organisation-module slice (Legal Entity/Branch/
Department/Designation/Grade), `shift` has no Prisma-era DB stub to expand; this is a
`CREATE TABLE`, following the pattern established in
`alembic/versions/20260807180000_company_feature_flag.py`.

Scoped to the shift *master* definition only — name, timings, breaks, grace minutes,
half-day/full-day hour thresholds, night/cross-midnight/OT-eligibility flags. No shift
assignment, roster, or rotation-pattern table (explicitly Sprint 7 per D5). No
`week_off_pattern_id` — `week_off_pattern` itself was never built (deferred by the Branch
slice's own Task 3.1.3, never picked up since); see
docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md §2.4. No uniqueness constraint on `code` —
no document specifies one, unlike Grade's pre-existing DB-level constraint.

RLS enabled inline in this migration, per the same pattern every prior slice used — the
standalone `scripts/sql/002_row_level_security.sql` is not invoked by any migration and is
not the live RLS registry.

Revision ID: 20260813170000
Revises: 20260813160000
"""

from alembic import op

revision = "20260813170000"
down_revision = "20260813160000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shift (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL
              REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE,
            name VARCHAR(100) NOT NULL,
            code VARCHAR(30),
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            break_minutes_paid INTEGER NOT NULL DEFAULT 0,
            break_minutes_unpaid INTEGER NOT NULL DEFAULT 0,
            grace_in_minutes INTEGER NOT NULL DEFAULT 0,
            grace_out_minutes INTEGER NOT NULL DEFAULT 0,
            half_day_threshold_hours NUMERIC(4,2),
            min_hours_full_day NUMERIC(4,2),
            is_night_shift BOOLEAN NOT NULL DEFAULT false,
            is_cross_midnight BOOLEAN NOT NULL DEFAULT false,
            is_ot_eligible BOOLEAN NOT NULL DEFAULT false,
            is_active BOOLEAN NOT NULL DEFAULT true,
            deleted_at TIMESTAMPTZ,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS shift_company_id_idx ON shift (company_id);
        CREATE INDEX IF NOT EXISTS shift_company_active_idx
          ON shift (company_id, is_active) WHERE deleted_at IS NULL;

        ALTER TABLE shift ENABLE ROW LEVEL SECURITY;
        ALTER TABLE shift FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON shift;
        CREATE POLICY tenant_isolation ON shift
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shift;")
