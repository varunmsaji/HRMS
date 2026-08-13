"""Designation field expansion + RLS — Sprint 3 (docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md
Feature 3.3, docs/product/08_Database_Architecture.md §4).

The `designation` table already exists (`scripts/sql/001_init_schema.sql`) with a minimal
stub shape (`id, company_id, department_id, title, created_at, updated_at, deleted_at`). This
migration adds `code`, `is_active`/`version` (the same soft-deactivate + optimistic-
concurrency pattern every other organisation-module resource uses), and `next_designation_id`
as a passive, self-referential nullable FK column per Sprint 3's binding Scope Decision D10
("built as a nullable FK column but has no UI control this sprint"). `next_designation_id` is
not exposed by any schema/service/UI this slice; see
docs/modules/designation/00_DESIGNATION_AUDIT.md §5.4.

`grade_id` is intentionally NOT added — this task's own instructions explicitly exclude
Grade, which directly conflicts with the Sprint 3 plan's D2 ("Grade built alongside
Designation, not deferred"); this task's explicit boundary wins. `jd_document_id` is also
intentionally NOT added — no document-management module exists to reference (stated
explicitly in the source doc itself). See docs/modules/designation/00_DESIGNATION_AUDIT.md
§5.7 for the full reasoning.

RLS is re-asserted idempotently, following the same pattern as
`20260813140000_department_fields.py` and its own predecessors — the standalone
`scripts/sql/002_row_level_security.sql` file is never invoked by Alembic and is not the
live RLS registry.

Revision ID: 20260813150000
Revises: 20260813140000
"""

from alembic import op

revision = "20260813150000"
down_revision = "20260813140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE designation
          ADD COLUMN IF NOT EXISTS code VARCHAR(30),
          ADD COLUMN IF NOT EXISTS next_designation_id UUID,
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

        ALTER TABLE designation
          ADD CONSTRAINT designation_next_designation_id_fkey
            FOREIGN KEY (next_designation_id) REFERENCES designation(id)
            ON DELETE SET NULL ON UPDATE CASCADE;

        CREATE INDEX IF NOT EXISTS designation_company_active_idx
          ON designation (company_id, is_active) WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS designation_department_id_idx
          ON designation (department_id);

        ALTER TABLE designation ENABLE ROW LEVEL SECURITY;
        ALTER TABLE designation FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON designation;
        CREATE POLICY tenant_isolation ON designation
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE designation DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON designation;

        DROP INDEX IF EXISTS designation_department_id_idx;
        DROP INDEX IF EXISTS designation_company_active_idx;

        ALTER TABLE designation DROP CONSTRAINT IF EXISTS designation_next_designation_id_fkey;

        ALTER TABLE designation
          DROP COLUMN IF EXISTS version,
          DROP COLUMN IF EXISTS is_active,
          DROP COLUMN IF EXISTS next_designation_id,
          DROP COLUMN IF EXISTS code;
        """
    )
