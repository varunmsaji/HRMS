"""Face attendance (7/n) - shadow provider comparison: test telemetry + shadow enrollments.

Purely additive; no existing table is altered.

1. `face_shadow_enrollment` - a consenting test participant's person id with the SHADOW provider
   (`FACEPP` / `OPENSOURCE`), one per (company, employee, provider). Kept apart from
   `employee_face_profile` so the one-profile-per-employee production flow is untouched.
2. `face_verification_comparison` - one row per face punch attempt that reached identity
   verification while shadow comparison was enabled: both providers' decisions, scores,
   thresholds, latencies and error codes. No image, embedding, provider body or credential.
   `liveness_session_id` and `employee_id` carry no foreign key to the attempt/punch: the row is
   written in its own transaction and must never block or be blocked by the punch's.

Row-level security as every face table.

Revision ID: 20261101090000
Revises: 20261031090000
"""

from alembic import op

revision = "20261101090000"
down_revision = "20261031090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS face_shadow_enrollment (
            "id" UUID NOT NULL,
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "provider" VARCHAR(20) NOT NULL,
            "provider_person_id" VARCHAR(100) NOT NULL,
            "consent_recorded_at" TIMESTAMPTZ NOT NULL,
            "enrolled_by_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "face_shadow_enrollment_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "face_shadow_enrollment_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_shadow_enrollment_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_shadow_enrollment_enrolled_by_fkey" FOREIGN KEY ("enrolled_by_user_id")
              REFERENCES "user"("id") ON DELETE SET NULL ON UPDATE CASCADE,
            CONSTRAINT "face_shadow_enrollment_provider_check"
              CHECK (provider IN ('FACEPP', 'OPENSOURCE')),
            CONSTRAINT "face_shadow_enrollment_key" UNIQUE ("company_id", "employee_id", "provider")
        );

        CREATE TABLE IF NOT EXISTS face_verification_comparison (
            "id" UUID NOT NULL,
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "liveness_session_id" UUID,
            "primary_provider" VARCHAR(20) NOT NULL,
            "shadow_provider" VARCHAR(20) NOT NULL,
            "primary_result" VARCHAR(30) NOT NULL,
            "shadow_result" VARCHAR(30) NOT NULL,
            "primary_matched" BOOLEAN NOT NULL,
            "shadow_matched" BOOLEAN,
            "primary_score" NUMERIC(5,4),
            "shadow_score" NUMERIC(5,4),
            "primary_threshold" NUMERIC(5,4),
            "shadow_threshold" NUMERIC(5,4),
            "primary_latency_ms" INTEGER,
            "shadow_latency_ms" INTEGER,
            "results_agree" BOOLEAN,
            "primary_error" VARCHAR(40),
            "shadow_error" VARCHAR(40),
            "shadow_timed_out" BOOLEAN NOT NULL DEFAULT false,
            "frames_compared" SMALLINT NOT NULL,
            "liveness_score" NUMERIC(5,4),
            "ground_truth" VARCHAR(10),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "face_verification_comparison_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "face_verification_comparison_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_verification_comparison_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_verification_comparison_providers_check"
              CHECK (primary_provider <> shadow_provider),
            CONSTRAINT "face_verification_comparison_ground_truth_check"
              CHECK (ground_truth IS NULL OR ground_truth IN ('GENUINE', 'IMPOSTOR'))
        );

        CREATE INDEX IF NOT EXISTS face_verification_comparison_company_created_idx
          ON face_verification_comparison (company_id, created_at DESC);

        ALTER TABLE face_shadow_enrollment ENABLE ROW LEVEL SECURITY;
        ALTER TABLE face_shadow_enrollment FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON face_shadow_enrollment;
        CREATE POLICY tenant_isolation ON face_shadow_enrollment
          USING (company_id = current_setting('app.company_id', true)::uuid);

        ALTER TABLE face_verification_comparison ENABLE ROW LEVEL SECURITY;
        ALTER TABLE face_verification_comparison FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON face_verification_comparison;
        CREATE POLICY tenant_isolation ON face_verification_comparison
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS face_verification_comparison;
        DROP TABLE IF EXISTS face_shadow_enrollment;
        """
    )
