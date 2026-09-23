"""Employee education history — market-parity onboarding-data pass, part 5.

Same "plain list" shape as `employee_experience` (`20261001090000_employee_experience.py`) —
a candidate may hold multiple qualifications, all concurrently valid, so this is a plain
`employee_id` FK with no effective-dating and no GiST exclusion constraint. Field shape
(`qualification, institution_name, year_of_passing, document_id`) matches
`docs/modules/employee/02_EMPLOYEE_DATA_MODEL.md` §2's own `employee_education` row.

Revision ID: 20261002090000
Revises: 20261001092000
"""

from alembic import op

revision = "20261002090000"
down_revision = "20261001092000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_education (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "qualification" VARCHAR(150) NOT NULL,
            "institution_name" VARCHAR(200),
            "year_of_passing" INTEGER,
            "document_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,
            "version" INTEGER NOT NULL DEFAULT 1,

            CONSTRAINT "employee_education_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "employee_education_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_education_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS employee_education_company_id_idx
          ON employee_education (company_id);
        CREATE INDEX IF NOT EXISTS employee_education_employee_id_idx
          ON employee_education (employee_id);

        ALTER TABLE employee_education ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_education FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_education;
        CREATE POLICY tenant_isolation ON employee_education
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS employee_education;
        """
    )
