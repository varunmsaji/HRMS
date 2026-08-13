"""Grade field expansion + RLS + Designation↔Grade link — Sprint 3
(docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md Feature 3.3 Task 3.3.1,
docs/product/08_Database_Architecture.md §4).

The `grade` table already exists (`scripts/sql/001_init_schema.sql`) with a minimal stub
shape (`id, company_id, code, name, rank, created_at, updated_at, deleted_at`) and an
existing `UNIQUE (company_id, code)` constraint, which is preserved as-is. This migration:

- Renames `rank` to `level` (the spec's own field name) — a clean rename via
  `ALTER TABLE ... RENAME COLUMN`, not a parallel column, per the Sprint plan's own note that
  `rank` has no real data yet.
- Adds `min_ctc`/`max_ctc`/`approval_limit` as `BIGINT` minor units (ADR-0006), and
  `notice_period_days`/`probation_days` as nullable `INTEGER` — all optional, matching
  FR-ORG-007's override-chain fields.
- Adds `is_active`/`version` — the same soft-deactivate + optimistic-concurrency pattern
  every other organisation-module resource uses.
- Does NOT add `leave_policy_id` — the Sprint doc's own Feature 4.3 text explicitly retracts
  this column in favor of `leave_policy_assignment` as the real mechanism; see
  docs/modules/grade/00_GRADE_AUDIT.md §2.4.

Also adds `designation.grade_id` (nullable FK to `grade`) — FR-ORG-006/Database Architecture
both document Designation as owning a `grade_id` field; it was deliberately excluded from the
prior Designation slice only because Grade did not exist yet
(docs/modules/designation/00_DESIGNATION_AUDIT.md §5.7). See
docs/modules/grade/00_GRADE_AUDIT.md §3 for the full relationship analysis.

RLS is re-asserted idempotently, following the same pattern as every prior migration in this
series — the standalone `scripts/sql/002_row_level_security.sql` file is never invoked by
Alembic and is not the live RLS registry.

Revision ID: 20260813160000
Revises: 20260813150000
"""

from alembic import op

revision = "20260813160000"
down_revision = "20260813150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE grade RENAME COLUMN rank TO level;

        ALTER TABLE grade
          ADD COLUMN IF NOT EXISTS min_ctc BIGINT,
          ADD COLUMN IF NOT EXISTS max_ctc BIGINT,
          ADD COLUMN IF NOT EXISTS notice_period_days INTEGER,
          ADD COLUMN IF NOT EXISTS probation_days INTEGER,
          ADD COLUMN IF NOT EXISTS approval_limit BIGINT,
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

        CREATE INDEX IF NOT EXISTS grade_company_active_idx
          ON grade (company_id, is_active) WHERE deleted_at IS NULL;

        ALTER TABLE designation ADD COLUMN IF NOT EXISTS grade_id UUID;

        ALTER TABLE designation
          ADD CONSTRAINT designation_grade_id_fkey
            FOREIGN KEY (grade_id) REFERENCES grade(id)
            ON DELETE SET NULL ON UPDATE CASCADE;

        CREATE INDEX IF NOT EXISTS designation_grade_id_idx ON designation (grade_id);

        ALTER TABLE grade ENABLE ROW LEVEL SECURITY;
        ALTER TABLE grade FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON grade;
        CREATE POLICY tenant_isolation ON grade
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE grade DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON grade;

        DROP INDEX IF EXISTS designation_grade_id_idx;
        ALTER TABLE designation DROP CONSTRAINT IF EXISTS designation_grade_id_fkey;
        ALTER TABLE designation DROP COLUMN IF EXISTS grade_id;

        DROP INDEX IF EXISTS grade_company_active_idx;

        ALTER TABLE grade
          DROP COLUMN IF EXISTS version,
          DROP COLUMN IF EXISTS is_active,
          DROP COLUMN IF EXISTS approval_limit,
          DROP COLUMN IF EXISTS probation_days,
          DROP COLUMN IF EXISTS notice_period_days,
          DROP COLUMN IF EXISTS max_ctc,
          DROP COLUMN IF EXISTS min_ctc;

        ALTER TABLE grade RENAME COLUMN level TO rank;
        """
    )
