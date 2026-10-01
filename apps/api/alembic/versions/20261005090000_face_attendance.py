"""Face attendance (1/n) — face enrollment profile + verification attempt log.

Widens `punch_source_check` to accept `'FACE'` (same ALTER-in-place shape as the
`'REGULARIZATION'` widening in 20260822090000). A face-verified punch is still an ordinary
immutable `punch` row; the biometric evidence lives beside it, never inside `punch.raw_payload`,
so it can be audited and purged independently of the attendance record.

`employee_face_profile` — one row per employee: the provider's person id (no face images are
stored here or anywhere in this schema). `consent_recorded_at` is NOT NULL: enrollment cannot be
written without a recorded consent instant (biometric data is a special category under GDPR
Art. 9 / DPDP / BIPA-style laws). Mutable (re-enroll / revoke update in place).

`face_verification_attempt` — insert-only, like `punch`. Every attempt is logged, including
rejections (spoof/liveness failures are exactly what an auditor wants to see). `punch_id` is set
only for a MATCHED attempt that produced a punch.

Revision ID: 20261005090000
Revises: 20261004112000
"""

from alembic import op

revision = "20261005090000"
down_revision = "20261004112000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE punch DROP CONSTRAINT punch_source_check;
        ALTER TABLE punch ADD CONSTRAINT punch_source_check
          CHECK (source IN (
            'WEB', 'MOBILE', 'DEVICE', 'IMPORT', 'ADMIN', 'API', 'REGULARIZATION', 'FACE'
          ));

        CREATE TABLE IF NOT EXISTS employee_face_profile (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "provider" VARCHAR(20) NOT NULL,
            "provider_person_id" VARCHAR(100) NOT NULL,
            "status" VARCHAR(20) NOT NULL,
            "reference_photo_count" INTEGER NOT NULL DEFAULT 1,
            "consent_recorded_at" TIMESTAMPTZ NOT NULL,
            "enrolled_at" TIMESTAMPTZ NOT NULL,
            "enrolled_by_user_id" UUID,
            "revoked_at" TIMESTAMPTZ,
            "revoked_by_user_id" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "employee_face_profile_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "employee_face_profile_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_face_profile_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "employee_face_profile_enrolled_by_user_id_fkey"
              FOREIGN KEY ("enrolled_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "employee_face_profile_revoked_by_user_id_fkey"
              FOREIGN KEY ("revoked_by_user_id") REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "employee_face_profile_provider_check" CHECK (provider IN ('LUXAND')),
            CONSTRAINT "employee_face_profile_status_check"
              CHECK (status IN ('ENROLLED', 'REVOKED')),
            CONSTRAINT "employee_face_profile_revoked_consistency_check"
              CHECK ((status = 'REVOKED') = (revoked_at IS NOT NULL)),
            CONSTRAINT "employee_face_profile_photo_count_check"
              CHECK (reference_photo_count >= 1),
            CONSTRAINT "employee_face_profile_company_employee_key"
              UNIQUE ("company_id", "employee_id")
        );

        CREATE INDEX IF NOT EXISTS employee_face_profile_company_id_idx
          ON employee_face_profile (company_id);

        ALTER TABLE employee_face_profile ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_face_profile FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON employee_face_profile;
        CREATE POLICY tenant_isolation ON employee_face_profile
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS face_verification_attempt (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "punch_id" UUID,
            "provider" VARCHAR(20) NOT NULL,
            "provider_person_id" VARCHAR(100),
            "decision" VARCHAR(30) NOT NULL,
            "similarity" NUMERIC(5, 4),
            "liveness_score" NUMERIC(5, 4),
            "provider_response" JSONB,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "face_verification_attempt_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "face_verification_attempt_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_verification_attempt_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_verification_attempt_punch_id_fkey" FOREIGN KEY ("punch_id")
              REFERENCES "punch"("id") ON DELETE RESTRICT,
            CONSTRAINT "face_verification_attempt_punch_id_key" UNIQUE ("punch_id"),
            CONSTRAINT "face_verification_attempt_provider_check" CHECK (provider IN ('LUXAND')),
            CONSTRAINT "face_verification_attempt_decision_check"
              CHECK (decision IN (
                'MATCHED', 'NO_MATCH', 'NO_FACE', 'LIVENESS_FAILED', 'NOT_ENROLLED',
                'PROVIDER_ERROR'
              )),
            CONSTRAINT "face_verification_attempt_punch_only_on_match_check"
              CHECK (punch_id IS NULL OR decision = 'MATCHED'),
            CONSTRAINT "face_verification_attempt_similarity_range_check"
              CHECK (similarity IS NULL OR (similarity >= 0 AND similarity <= 1)),
            CONSTRAINT "face_verification_attempt_liveness_range_check"
              CHECK (liveness_score IS NULL OR (liveness_score >= 0 AND liveness_score <= 1))
        );

        CREATE INDEX IF NOT EXISTS face_verification_attempt_company_id_idx
          ON face_verification_attempt (company_id);
        -- Per-employee rate limiting looks back over recent attempts.
        CREATE INDEX IF NOT EXISTS face_verification_attempt_employee_created_idx
          ON face_verification_attempt (company_id, employee_id, created_at);

        ALTER TABLE face_verification_attempt ENABLE ROW LEVEL SECURITY;
        ALTER TABLE face_verification_attempt FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON face_verification_attempt;
        CREATE POLICY tenant_isolation ON face_verification_attempt
          USING (company_id = current_setting('app.company_id', true)::uuid);

        INSERT INTO permission (id, code, domain, description)
        VALUES (gen_random_uuid(), 'ATTENDANCE.FACE_ENROLLMENT_MANAGE', 'ATTENDANCE',
                'Enroll, add reference photos for, and revoke employee face profiles')
        ON CONFLICT (code) DO NOTHING;

        INSERT INTO role_permission (role_id, permission_id, data_scope)
        SELECT r.id, p.id, 'COMPANY'
        FROM role r
        JOIN permission p ON p.code = 'ATTENDANCE.FACE_ENROLLMENT_MANAGE'
        WHERE r.code IN ('COMPANY_ADMIN', 'HR_ADMIN') AND r.deleted_at IS NULL
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission WHERE permission_id IN
          (SELECT id FROM permission WHERE code = 'ATTENDANCE.FACE_ENROLLMENT_MANAGE');
        DELETE FROM permission WHERE code = 'ATTENDANCE.FACE_ENROLLMENT_MANAGE';

        DROP TABLE IF EXISTS face_verification_attempt;
        DROP TABLE IF EXISTS employee_face_profile;

        ALTER TABLE punch DROP CONSTRAINT punch_source_check;
        ALTER TABLE punch ADD CONSTRAINT punch_source_check
          CHECK (source IN ('WEB', 'MOBILE', 'DEVICE', 'IMPORT', 'ADMIN', 'API', 'REGULARIZATION'));
        """
    )
