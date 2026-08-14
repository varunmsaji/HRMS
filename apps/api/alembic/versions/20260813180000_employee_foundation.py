"""Employee foundation (E-01) — identity field expansion + number_series allocator.

`docs/modules/employee/01_EMPLOYEE_FOUNDATION_AUDIT.md` §3. The `employee` table already
exists (`scripts/sql/001_init_schema.sql`) with a minimal 8-business-column stub shape and RLS
already live. This migration, additive only (`ADD COLUMN IF NOT EXISTS` throughout — no renames,
no drops; zero rows exist in `employee` at the time this was written, confirmed against the dev
database, so there is no data to transform or lose):

- Adds the twelve identity columns `02_EMPLOYEE_DATA_MODEL.md` §3 documents (`middle_name`
  through `status`). `personal_email` is `VARCHAR(255)` rather than that doc's proposed
  `CITEXT` — this codebase does not use the `citext` extension anywhere else (`user.email` is
  plain `VARCHAR(255)`, validated at the Pydantic layer) and that doc's own SQL is explicitly
  "proposed shapes for review, not applied DDL" — matching the existing convention instead of
  introducing a new extension dependency for one column.
- Adds `is_active BOOLEAN NOT NULL DEFAULT true` — `employee` was the only employee-domain table
  without it; `01_EMPLOYEE_MODULE_PLAN.md`'s own E-01 description calls for "the organisation
  module's soft-deactivate... pattern exactly," which is built on this flag everywhere else.
- Adds the two `docs/product/08_Database_Architecture.md` §12 target indexes that apply to
  columns this migration actually adds/uses (`(company_id, status)` partial, `custom_fields`
  GIN). The third target index over `(company_id, employee_code)` is already covered by the
  live `UNIQUE (company_id, employee_code)` index — not duplicated.
- Re-asserts RLS on `employee` idempotently, matching every prior migration in this series
  (already live and forced today; re-asserted for consistency, not because it was missing).
- Creates `number_series` (race-safe code allocator, scoped to `EMPLOYEE_CODE` for this slice)
  inside this migration rather than a follow-up to `organisation`'s own migration set — see the
  audit §1.6 for why this deviates from `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`'s original
  placement of this table.

Revision ID: 20260813180000
Revises: 20260813170000
"""

from alembic import op

revision = "20260813180000"
down_revision = "20260813170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee
          ADD COLUMN IF NOT EXISTS middle_name VARCHAR(100),
          ADD COLUMN IF NOT EXISTS display_name VARCHAR(200),
          ADD COLUMN IF NOT EXISTS blood_group VARCHAR(10),
          ADD COLUMN IF NOT EXISTS marital_status VARCHAR(20),
          ADD COLUMN IF NOT EXISTS nationality VARCHAR(80),
          ADD COLUMN IF NOT EXISTS personal_email VARCHAR(255),
          ADD COLUMN IF NOT EXISTS personal_mobile VARCHAR(20),
          ADD COLUMN IF NOT EXISTS photo_url TEXT,
          ADD COLUMN IF NOT EXISTS pan_number_enc TEXT,
          ADD COLUMN IF NOT EXISTS aadhaar_number_enc TEXT,
          ADD COLUMN IF NOT EXISTS uan_number VARCHAR(20),
          ADD COLUMN IF NOT EXISTS status VARCHAR(25) NOT NULL DEFAULT 'PRE_JOINING',
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

        CREATE INDEX IF NOT EXISTS employee_company_status_idx
          ON employee (company_id, status) WHERE deleted_at IS NULL;

        CREATE INDEX IF NOT EXISTS employee_custom_fields_idx
          ON employee USING gin (custom_fields);

        ALTER TABLE employee ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee;
        CREATE POLICY tenant_isolation ON employee
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS number_series (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "entity_type" VARCHAR(30) NOT NULL,
            "prefix" VARCHAR(10) NOT NULL,
            "separator" VARCHAR(3) NOT NULL DEFAULT '-',
            "current_number" INTEGER NOT NULL DEFAULT 0,
            "padding" INTEGER NOT NULL DEFAULT 4,
            "reset_rule" VARCHAR(10) NOT NULL DEFAULT 'NEVER',
            "last_reset_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

            CONSTRAINT "number_series_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "number_series_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS number_series_company_id_entity_type_key
          ON number_series (company_id, entity_type);

        ALTER TABLE number_series ENABLE ROW LEVEL SECURITY;
        ALTER TABLE number_series FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON number_series;
        CREATE POLICY tenant_isolation ON number_series
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE number_series DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON number_series;
        DROP TABLE IF EXISTS number_series;

        DROP INDEX IF EXISTS employee_custom_fields_idx;
        DROP INDEX IF EXISTS employee_company_status_idx;

        ALTER TABLE employee
          DROP COLUMN IF EXISTS is_active,
          DROP COLUMN IF EXISTS status,
          DROP COLUMN IF EXISTS uan_number,
          DROP COLUMN IF EXISTS aadhaar_number_enc,
          DROP COLUMN IF EXISTS pan_number_enc,
          DROP COLUMN IF EXISTS photo_url,
          DROP COLUMN IF EXISTS personal_mobile,
          DROP COLUMN IF EXISTS personal_email,
          DROP COLUMN IF EXISTS nationality,
          DROP COLUMN IF EXISTS marital_status,
          DROP COLUMN IF EXISTS blood_group,
          DROP COLUMN IF EXISTS display_name,
          DROP COLUMN IF EXISTS middle_name;
        """
    )
