"""Idempotency keys (LM-03) - retry-safe leave adjustments, encashments and applications.

`idempotency_key` holds one row per (company, operation, client `Idempotency-Key`). It is written in
the same transaction as the mutation it guards, so a committed row always carries the stored
response and a rolled-back attempt leaves nothing behind. The unique constraint is what makes two
concurrent requests with the same key execute the mutation once. Only a SHA-256 request fingerprint
and the response are stored, never the raw request body.

RLS-enforced like every tenant table. The runtime role may insert, read and complete (update) a row,
never delete it.

The company FK cascades: the rows are retry bookkeeping owned by the company, not business
records, so they must not block a company's removal.

Additive only; no existing data is touched.

Revision ID: 20261011090000
Revises: 20261010091000
"""

from alembic import op

revision = "20261011090000"
down_revision = "20261010091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_key (
            id UUID NOT NULL,
            company_id UUID NOT NULL,
            operation VARCHAR(100) NOT NULL,
            idempotency_key VARCHAR(255) NOT NULL,
            request_fingerprint VARCHAR(64) NOT NULL,
            response_status INTEGER,
            response_body JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            CONSTRAINT idempotency_key_pkey PRIMARY KEY (id),
            CONSTRAINT idempotency_key_company_id_fkey FOREIGN KEY (company_id)
                REFERENCES company (id) ON DELETE CASCADE,
            CONSTRAINT uq_idempotency_key UNIQUE (company_id, operation, idempotency_key)
        );

        ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY;
        ALTER TABLE idempotency_key FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON idempotency_key;
        CREATE POLICY tenant_isolation ON idempotency_key
          USING (company_id = current_setting('app.company_id', true)::uuid);

        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
                GRANT SELECT, INSERT, UPDATE ON idempotency_key TO hrms_app;
                REVOKE DELETE, TRUNCATE ON idempotency_key FROM hrms_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_key;")
