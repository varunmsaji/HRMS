"""Employee Document — post-onboarding document management.

Creates `employee_document`, an employee's ongoing document store, independent of the existing
`onboarding_document` table (which stays unchanged, scoped to a case's lifetime only). Mirrors
`onboarding_document`'s exact shape (`20260905090000_onboarding_o1.py`) with the parent FK
swapped from `onboarding_case_id` to `employee_id`, plus one new column,
`source_onboarding_document_id` — a plain, unconstrained UUID (no FK) set only on rows created
by `OnboardingActivationService.activate_case`'s document-migration step, for traceability only.

RLS: `ENABLE`/`FORCE ROW LEVEL SECURITY` + a single `tenant_isolation` policy on `company_id`,
same convention as every other tenant table.

Revision ID: 20261014090000
Revises: 20261013090000
"""

from alembic import op

revision = "20261014090000"
down_revision = "20261013090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_document (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "document_type" VARCHAR(40) NOT NULL,
            "s3_key" VARCHAR(512) NOT NULL,
            "original_filename" VARCHAR(255) NOT NULL,
            "content_type" VARCHAR(100) NOT NULL,
            "size_bytes" BIGINT NOT NULL,
            "status" VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            "verified_by_user_id" UUID,
            "verified_at" TIMESTAMPTZ,
            "rejection_reason" TEXT,
            "uploaded_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "source_onboarding_document_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "employee_document_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "employee_document_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_document_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_document_verified_by_user_id_fkey"
              FOREIGN KEY ("verified_by_user_id")
              REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS employee_document_company_id_idx
          ON employee_document (company_id);
        CREATE INDEX IF NOT EXISTS employee_document_employee_id_idx
          ON employee_document (employee_id);

        ALTER TABLE employee_document ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_document FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_document;
        CREATE POLICY tenant_isolation ON employee_document
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS employee_document;
        """
    )
