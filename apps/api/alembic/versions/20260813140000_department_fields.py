"""Department field expansion + RLS — Sprint 3 (docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md
Feature 3.2, docs/product/08_Database_Architecture.md §4).

The `department` table already exists (`scripts/sql/001_init_schema.sql`) with a minimal
stub shape (`id, company_id, branch_id, name, code, parent_id, created_at, updated_at,
deleted_at`). This migration adds `is_active`/`version` (the same soft-deactivate +
optimistic-concurrency pattern Branch/Legal Entity use), a proper self-referential FK on
`parent_id` (previously undeclared), and `head_employee_id` as a passive nullable FK column
per Sprint 3's binding Scope Decision D10 ("built as a nullable FK column but has no UI
control this sprint... so a later sprint doesn't need a migration to add it") — `employee`
already exists as a DB stub. `head_employee_id` is not exposed by any schema/service/UI this
slice; see docs/modules/department/00_DEPARTMENT_AUDIT.md §9.1.

`cost_centre_id` is intentionally NOT added — Cost Centre is a separate, not-yet-built table
(Sprint 3 Task 3.2.2), out of scope for this slice.

RLS is re-asserted idempotently, following the same pattern as
`20260813120000_legal_entity_fields.py` and `20260813130000_branch_fields.py` — the
standalone `scripts/sql/002_row_level_security.sql` file is never invoked by Alembic and is
not the live RLS registry.

Revision ID: 20260813140000
Revises: 20260813130000
"""

from alembic import op

revision = "20260813140000"
down_revision = "20260813130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE department
          ADD COLUMN IF NOT EXISTS head_employee_id UUID,
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

        ALTER TABLE department
          ADD CONSTRAINT department_parent_id_fkey
            FOREIGN KEY (parent_id) REFERENCES department(id)
            ON DELETE SET NULL ON UPDATE CASCADE;

        ALTER TABLE department
          ADD CONSTRAINT department_head_employee_id_fkey
            FOREIGN KEY (head_employee_id) REFERENCES employee(id)
            ON DELETE SET NULL ON UPDATE CASCADE;

        CREATE INDEX IF NOT EXISTS department_company_active_idx
          ON department (company_id, is_active) WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS department_parent_id_idx
          ON department (company_id, parent_id);
        CREATE INDEX IF NOT EXISTS department_branch_id_idx
          ON department (branch_id);

        ALTER TABLE department ENABLE ROW LEVEL SECURITY;
        ALTER TABLE department FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON department;
        CREATE POLICY tenant_isolation ON department
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE department DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON department;

        DROP INDEX IF EXISTS department_branch_id_idx;
        DROP INDEX IF EXISTS department_parent_id_idx;
        DROP INDEX IF EXISTS department_company_active_idx;

        ALTER TABLE department DROP CONSTRAINT IF EXISTS department_head_employee_id_fkey;
        ALTER TABLE department DROP CONSTRAINT IF EXISTS department_parent_id_fkey;

        ALTER TABLE department
          DROP COLUMN IF EXISTS version,
          DROP COLUMN IF EXISTS is_active,
          DROP COLUMN IF EXISTS head_employee_id;
        """
    )
