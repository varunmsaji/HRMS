"""Employee experience (previous employment / PF continuity) — market-parity onboarding-data
pass, part 4.

Models EPF Form 11's continuity block (previous UAN, PF account number, employer, dates) plus
Form 12B's salary-continuity fields, using the `employee_experience` shape already pre-named in
`docs/modules/employee/02_EMPLOYEE_DATA_MODEL.md` §2 (`company_name, designation, from/to date,
last_ctc, reason_for_leaving, document_id`) — confirmed via that doc's own §3 note that DDL for
this table was deferred to the implementation slice that builds it, i.e. this one.

Unlike `employee_statutory`/`employee_bank`, this is a genuine one-to-many list (a candidate may
have multiple past employers, all concurrently valid), not "one current value over time" —
plain FK + indexes + RLS, no GiST exclusion constraint, no effective-dating.

Revision ID: 20261001090000
Revises: 20260930090000
"""

from alembic import op

revision = "20261001090000"
down_revision = "20260930090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_experience (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "company_name" VARCHAR(200) NOT NULL,
            "designation" VARCHAR(150),
            "from_date" DATE NOT NULL,
            "to_date" DATE,
            "last_ctc_minor" BIGINT,
            "reason_for_leaving" TEXT,
            "had_prior_pf_membership" BOOLEAN NOT NULL DEFAULT false,
            "previous_uan" VARCHAR(20),
            "previous_pf_account_number" VARCHAR(30),
            "previous_esi_ip_number" VARCHAR(30),
            "document_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,
            "version" INTEGER NOT NULL DEFAULT 1,

            CONSTRAINT "employee_experience_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "employee_experience_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_experience_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS employee_experience_company_id_idx
          ON employee_experience (company_id);
        CREATE INDEX IF NOT EXISTS employee_experience_employee_id_idx
          ON employee_experience (employee_id);

        ALTER TABLE employee_experience ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_experience FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_experience;
        CREATE POLICY tenant_isolation ON employee_experience
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS employee_experience;
        """
    )
