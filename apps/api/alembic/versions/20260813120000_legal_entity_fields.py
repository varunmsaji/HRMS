"""Legal Entity field expansion + RLS — Sprint 3A (docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md
Feature 2.6, docs/product/08_Database_Architecture.md §4).

The `legal_entity` table already exists (`scripts/sql/001_init_schema.sql`) with a minimal
stub shape (`id, company_id, name, pan, gstin, created_at, updated_at, deleted_at`). This
migration adds the remaining columns the Legal Entity vertical slice requires and enables RLS
inline, following the pattern established in `20260803200000_b1_auth_audit.py` (`audit_log`)
and `20260807150000_company_setup_progress.py` — the standalone `scripts/sql/
002_row_level_security.sql` file is never invoked by Alembic and is not the live RLS registry.

Revision ID: 20260813120000
Revises: 20260808100000
"""

from alembic import op

revision = "20260813120000"
down_revision = "20260808100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE legal_entity
          ADD COLUMN IF NOT EXISTS registered_address TEXT,
          ADD COLUMN IF NOT EXISTS tan VARCHAR(20),
          ADD COLUMN IF NOT EXISTS cin VARCHAR(30),
          ADD COLUMN IF NOT EXISTS pf_code VARCHAR(30),
          ADD COLUMN IF NOT EXISTS esi_code VARCHAR(30),
          ADD COLUMN IF NOT EXISTS lwf_reg VARCHAR(30),
          ADD COLUMN IF NOT EXISTS signatory_name VARCHAR(150),
          ADD COLUMN IF NOT EXISTS signatory_designation VARCHAR(150),
          ADD COLUMN IF NOT EXISTS signature_image_url TEXT,
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

        CREATE INDEX IF NOT EXISTS legal_entity_company_active_idx
          ON legal_entity (company_id, is_active) WHERE deleted_at IS NULL;

        ALTER TABLE legal_entity ENABLE ROW LEVEL SECURITY;
        ALTER TABLE legal_entity FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON legal_entity;
        CREATE POLICY tenant_isolation ON legal_entity
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE legal_entity DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON legal_entity;

        DROP INDEX IF EXISTS legal_entity_company_active_idx;

        ALTER TABLE legal_entity
          DROP COLUMN IF EXISTS version,
          DROP COLUMN IF EXISTS is_active,
          DROP COLUMN IF EXISTS signature_image_url,
          DROP COLUMN IF EXISTS signatory_designation,
          DROP COLUMN IF EXISTS signatory_name,
          DROP COLUMN IF EXISTS lwf_reg,
          DROP COLUMN IF EXISTS esi_code,
          DROP COLUMN IF EXISTS pf_code,
          DROP COLUMN IF EXISTS cin,
          DROP COLUMN IF EXISTS tan,
          DROP COLUMN IF EXISTS registered_address;
        """
    )
