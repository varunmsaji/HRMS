"""Branch field expansion + RLS — Sprint 3 (docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md
Task 3.1.1, docs/product/08_Database_Architecture.md §4).

The `branch` table already exists (`scripts/sql/001_init_schema.sql`) with a minimal stub
shape (`id, company_id, legal_entity_id, name, state, timezone, created_at, updated_at,
deleted_at`). This migration adds the remaining columns the Branch vertical slice
requires and enables RLS inline, following the same pattern as
`20260813120000_legal_entity_fields.py` — the standalone `scripts/sql/
002_row_level_security.sql` file is never invoked by Alembic and is not the live RLS
registry, so RLS is re-asserted here even though `branch` is nominally covered by the
`001_init_schema.sql` RLS loop.

The free-text `state` column is dropped and replaced by a validated `state_code`
(ISO 3166-2:IN) — safe pre-launch, only seed/test data exists (docs/sprints/
SPRINT_3_COMPANY_FOUNDATION.md:419).

`holiday_calendar_id` and `week_off_pattern_id` are intentionally NOT added here — deferred
to Feature 4.1 and Task 3.1.3 respectively, per the sprint doc's own forward-reference
sequencing.

Revision ID: 20260813130000
Revises: 20260813120000
"""

from alembic import op

revision = "20260813130000"
down_revision = "20260813120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE branch
          DROP COLUMN IF EXISTS state,
          ADD COLUMN IF NOT EXISTS code VARCHAR(30),
          ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(200),
          ADD COLUMN IF NOT EXISTS address_line2 VARCHAR(200),
          ADD COLUMN IF NOT EXISTS city VARCHAR(100),
          ADD COLUMN IF NOT EXISTS state_code VARCHAR(10),
          ADD COLUMN IF NOT EXISTS pincode VARCHAR(10),
          ADD COLUMN IF NOT EXISTS latitude NUMERIC(9,6),
          ADD COLUMN IF NOT EXISTS longitude NUMERIC(9,6),
          ADD COLUMN IF NOT EXISTS geofence_radius_m INTEGER,
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

        CREATE INDEX IF NOT EXISTS branch_company_active_idx
          ON branch (company_id, is_active) WHERE deleted_at IS NULL;

        ALTER TABLE branch ENABLE ROW LEVEL SECURITY;
        ALTER TABLE branch FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON branch;
        CREATE POLICY tenant_isolation ON branch
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE branch DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON branch;

        DROP INDEX IF EXISTS branch_company_active_idx;

        ALTER TABLE branch
          DROP COLUMN IF EXISTS version,
          DROP COLUMN IF EXISTS is_active,
          DROP COLUMN IF EXISTS geofence_radius_m,
          DROP COLUMN IF EXISTS longitude,
          DROP COLUMN IF EXISTS latitude,
          DROP COLUMN IF EXISTS pincode,
          DROP COLUMN IF EXISTS state_code,
          DROP COLUMN IF EXISTS city,
          DROP COLUMN IF EXISTS address_line2,
          DROP COLUMN IF EXISTS address_line1,
          DROP COLUMN IF EXISTS code,
          ADD COLUMN IF NOT EXISTS state VARCHAR(60);
        """
    )
