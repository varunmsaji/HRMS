"""Onboarding O1 — data model.

Per `docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md` §4/§11. Creates all four onboarding
tables up front (`onboarding_case`, `onboarding_token`, `onboarding_document`,
`onboarding_section_review`) even though O1's application code only reads/writes
`onboarding_case` — the shape is settled now so later phases (O2 token issuance, O5 documents,
O6 section review) add code only, not migrations (module docstring,
`hrms.modules.onboarding.models`).

`onboarding_case.employment_type_id` from the plan's own §4.1 table is replaced with
`legal_entity_id` here — there is no `employment_type` table anywhere in this codebase, and
`EmploymentCreate` (`hrms.modules.employee.schemas`) only ever needs `legal_entity_id` for
activation (O7) to eventually call it.

RLS: `ENABLE`/`FORCE ROW LEVEL SECURITY` + a single `tenant_isolation` policy on `company_id` on
every table, matching every other tenant table's convention exactly
(`docs/architecture/POSTGRES_RLS_ROLE_IMPLEMENTATION_REPORT.md`).

Revision ID: 20260905090000
Revises: 20260904090000
"""

from alembic import op

revision = "20260905090000"
down_revision = "20260904090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS onboarding_case (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "status" VARCHAR(25) NOT NULL DEFAULT 'DRAFT',
            "candidate_first_name" VARCHAR(100) NOT NULL,
            "candidate_last_name" VARCHAR(100),
            "personal_email" VARCHAR(255) NOT NULL,
            "personal_mobile" VARCHAR(20),
            "designation_id" UUID,
            "department_id" UUID,
            "branch_id" UUID,
            "legal_entity_id" UUID,
            "proposed_joining_date" DATE NOT NULL,
            "created_by_user_id" UUID NOT NULL,
            "personal_info" JSONB NOT NULL DEFAULT '{}'::jsonb,
            "address_info" JSONB NOT NULL DEFAULT '{}'::jsonb,
            "emergency_contact" JSONB NOT NULL DEFAULT '{}'::jsonb,
            "bank_info" JSONB NOT NULL DEFAULT '{}'::jsonb,
            "statutory_info" JSONB NOT NULL DEFAULT '{}'::jsonb,
            "policy_ack_at" TIMESTAMPTZ,
            "policy_ack_ip" VARCHAR(45),
            "employee_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,
            "version" INTEGER NOT NULL DEFAULT 1,

            CONSTRAINT "onboarding_case_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "onboarding_case_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_case_designation_id_fkey" FOREIGN KEY ("designation_id")
              REFERENCES "designation"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_case_department_id_fkey" FOREIGN KEY ("department_id")
              REFERENCES "department"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_case_branch_id_fkey" FOREIGN KEY ("branch_id")
              REFERENCES "branch"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_case_legal_entity_id_fkey" FOREIGN KEY ("legal_entity_id")
              REFERENCES "legal_entity"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_case_created_by_user_id_fkey" FOREIGN KEY ("created_by_user_id")
              REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_case_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS onboarding_case_company_id_idx
          ON onboarding_case (company_id);
        CREATE INDEX IF NOT EXISTS onboarding_case_personal_email_idx
          ON onboarding_case (personal_email);

        ALTER TABLE onboarding_case ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onboarding_case FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON onboarding_case;
        CREATE POLICY tenant_isolation ON onboarding_case
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS onboarding_token (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "onboarding_case_id" UUID NOT NULL,
            "token_hash" VARCHAR(64) NOT NULL,
            "expires_at" TIMESTAMPTZ NOT NULL,
            "used_first_at" TIMESTAMPTZ,
            "revoked_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "onboarding_token_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "onboarding_token_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_token_case_id_fkey" FOREIGN KEY ("onboarding_case_id")
              REFERENCES "onboarding_case"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_token_token_hash_key" UNIQUE ("token_hash")
        );

        CREATE INDEX IF NOT EXISTS onboarding_token_company_id_idx
          ON onboarding_token (company_id);
        CREATE INDEX IF NOT EXISTS onboarding_token_case_id_idx
          ON onboarding_token (onboarding_case_id);

        ALTER TABLE onboarding_token ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onboarding_token FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON onboarding_token;
        CREATE POLICY tenant_isolation ON onboarding_token
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS onboarding_document (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "onboarding_case_id" UUID NOT NULL,
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
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "onboarding_document_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "onboarding_document_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_document_case_id_fkey" FOREIGN KEY ("onboarding_case_id")
              REFERENCES "onboarding_case"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_document_verified_by_user_id_fkey"
              FOREIGN KEY ("verified_by_user_id")
              REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS onboarding_document_company_id_idx
          ON onboarding_document (company_id);
        CREATE INDEX IF NOT EXISTS onboarding_document_case_id_idx
          ON onboarding_document (onboarding_case_id);

        ALTER TABLE onboarding_document ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onboarding_document FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON onboarding_document;
        CREATE POLICY tenant_isolation ON onboarding_document
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS onboarding_section_review (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "onboarding_case_id" UUID NOT NULL,
            "section" VARCHAR(30) NOT NULL,
            "status" VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            "reviewed_by_user_id" UUID,
            "reviewed_at" TIMESTAMPTZ,
            "rejection_reason" TEXT,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "onboarding_section_review_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "onboarding_section_review_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_section_review_case_id_fkey" FOREIGN KEY ("onboarding_case_id")
              REFERENCES "onboarding_case"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "onboarding_section_review_reviewed_by_user_id_fkey"
              FOREIGN KEY ("reviewed_by_user_id")
              REFERENCES "user"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS onboarding_section_review_company_id_idx
          ON onboarding_section_review (company_id);
        CREATE INDEX IF NOT EXISTS onboarding_section_review_case_id_idx
          ON onboarding_section_review (onboarding_case_id);

        ALTER TABLE onboarding_section_review ENABLE ROW LEVEL SECURITY;
        ALTER TABLE onboarding_section_review FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON onboarding_section_review;
        CREATE POLICY tenant_isolation ON onboarding_section_review
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS onboarding_section_review;
        DROP TABLE IF EXISTS onboarding_document;
        DROP TABLE IF EXISTS onboarding_token;
        DROP TABLE IF EXISTS onboarding_case;
        """
    )
