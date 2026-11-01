"""Company face-enrollment policy: `require_enrollment_on_onboarding`.

Revision ID: 20261104090000
Revises: 20261103090000

A new, purely additive singleton-per-company table. It holds only the company's *policy* (whether
face enrollment is a required onboarding step); it is not a second enrollment record - the one
source of truth for an employee's enrollment stays `employee_face_profile` and
`face_enrollment_window`. No existing table, row or biometric data is touched, and a company with
no row here behaves exactly as before (not required).
"""

from alembic import op

revision = "20261104090000"
down_revision = "20261103090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS company_face_policy (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "require_enrollment_on_onboarding" BOOLEAN NOT NULL DEFAULT FALSE,
            "updated_by_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT "company_face_policy_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "company_face_policy_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "company_face_policy_user_fkey" FOREIGN KEY ("updated_by_user_id")
              REFERENCES "user"("id") ON DELETE SET NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS company_face_policy_company_id_idx
          ON company_face_policy (company_id);

        ALTER TABLE company_face_policy ENABLE ROW LEVEL SECURITY;
        ALTER TABLE company_face_policy FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON company_face_policy;
        CREATE POLICY tenant_isolation ON company_face_policy
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS company_face_policy;")
