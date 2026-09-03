"""Employee bulk import — batch tracking + per-row error reporting.

New tenant-scoped tables backing the CSV bulk-employee-import feature: one row per upload in
`employee_import_batch` (status/progress counters), one row per failed CSV row in
`employee_import_row_error` (so a client can see exactly which rows failed and why without
re-parsing their own file). RLS enabled inline, per the pattern established in
`20260807180000_company_feature_flag.py`.

Revision ID: 20260907090000
Revises: 20260906090000
"""

from alembic import op

revision = "20260907090000"
down_revision = "20260906090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_import_batch (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL
              REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE,
            status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
            original_filename VARCHAR(255) NOT NULL,
            s3_key TEXT NOT NULL,
            total_rows INTEGER NOT NULL DEFAULT 0,
            processed_rows INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            created_by UUID REFERENCES "user"(id) ON DELETE SET NULL,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            version INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS employee_import_batch_company_id_idx
          ON employee_import_batch (company_id);
        CREATE INDEX IF NOT EXISTS employee_import_batch_status_idx
          ON employee_import_batch (status);

        ALTER TABLE employee_import_batch ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_import_batch FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_import_batch;
        CREATE POLICY tenant_isolation ON employee_import_batch
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS employee_import_row_error (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL
              REFERENCES employee_import_batch(id) ON DELETE CASCADE,
            company_id UUID NOT NULL
              REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE,
            row_number INTEGER NOT NULL,
            raw_row JSONB NOT NULL,
            error_code VARCHAR(60) NOT NULL,
            error_message TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS employee_import_row_error_batch_id_idx
          ON employee_import_row_error (batch_id);

        ALTER TABLE employee_import_row_error ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_import_row_error FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_import_row_error;
        CREATE POLICY tenant_isolation ON employee_import_row_error
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS employee_import_row_error;
        DROP TABLE IF EXISTS employee_import_batch;
        """
    )
