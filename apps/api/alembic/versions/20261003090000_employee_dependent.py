"""Employee dependents — market-parity onboarding-data pass, part 6 (the hardest remaining
gap in the table: PF/Gratuity nominee declaration and ESI family details, per EPF Form 2,
Gratuity Form F, and ESI Form 1/Form 2).

Same "plain list" shape as `employee_experience`/`employee_education` — an employee may declare
several nominees/dependents, all concurrently valid, so this is a plain `employee_id` FK with no
effective-dating and no GiST exclusion constraint.

Unlike Experience/Education, this table carries two things neither of those do:
- `aadhaar_number_enc` — DATA-01-encrypted (same pattern as `employee.aadhaar_number_enc`/
  `employee_bank.account_number_enc`), since a nominee's own Aadhaar is PAN/Aadhaar-grade PII,
  not the lighter tier `employee_experience`/`employee_education` carry.
- `is_pf_nominee`/`pf_nominee_share_percentage` and `is_gratuity_nominee`/
  `gratuity_nominee_share_percentage` — a dependent may be declared a nominee under either or
  both statutory schemes independently, each with its own share percentage; application-layer
  validation (not a DB constraint) keeps each scheme's percentages summing to <=100 per employee.
`is_esi_dependent` has no percentage — ESI family coverage is not proportioned.

Revision ID: 20261003090000
Revises: 20261002091000
"""

from alembic import op

revision = "20261003090000"
down_revision = "20261002091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_dependent (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "full_name" VARCHAR(150) NOT NULL,
            "relationship" VARCHAR(50) NOT NULL,
            "date_of_birth" DATE,
            "gender" VARCHAR(20),
            "is_minor" BOOLEAN NOT NULL DEFAULT false,
            "guardian_name" VARCHAR(150),
            "guardian_relationship" VARCHAR(50),
            "aadhaar_number_enc" TEXT,
            "is_pf_nominee" BOOLEAN NOT NULL DEFAULT false,
            "pf_nominee_share_percentage" NUMERIC(5, 2),
            "is_gratuity_nominee" BOOLEAN NOT NULL DEFAULT false,
            "gratuity_nominee_share_percentage" NUMERIC(5, 2),
            "is_esi_dependent" BOOLEAN NOT NULL DEFAULT false,
            "document_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,
            "version" INTEGER NOT NULL DEFAULT 1,

            CONSTRAINT "employee_dependent_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "employee_dependent_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_dependent_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS employee_dependent_company_id_idx
          ON employee_dependent (company_id);
        CREATE INDEX IF NOT EXISTS employee_dependent_employee_id_idx
          ON employee_dependent (employee_id);

        ALTER TABLE employee_dependent ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_dependent FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_dependent;
        CREATE POLICY tenant_isolation ON employee_dependent
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS employee_dependent;
        """
    )
