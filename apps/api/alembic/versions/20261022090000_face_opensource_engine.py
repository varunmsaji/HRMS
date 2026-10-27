"""Face attendance (6/n) - open-source engine: provider value + encrypted embedding store.

1. `OPENSOURCE` becomes a valid `provider` on `employee_face_profile` and
   `face_verification_attempt` (same widening as 20261007090000 did for FACEPP). Nothing about
   existing FACEPP rows changes; a profile always keeps the provider that created it.
2. `face_embedding` - one row per enrollment capture of an OPENSOURCE person: the face
   embedding, AES-256-GCM encrypted with the environment data key (`PiiCryptoService`, AAD bound to
   table/column/row id), the model version that produced it and an owner (`employee_id`).
   `person_ref` is the random id embedded in `employee_face_profile.provider_person_id`
   (`osf1.<company>.<person_ref>`); there is deliberately no FK to the profile, matching the
   Face++ model where the provider-side person is created before the profile row exists and is
   removed by the `face_external_deletion` outbox. Row-level security as every face table.
   No image is stored here or anywhere in this schema.

Revision ID: 20261022090000
Revises: 20261021090000
"""

from alembic import op

revision = "20261022090000"
down_revision = "20261021090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee_face_profile DROP CONSTRAINT employee_face_profile_provider_check;
        ALTER TABLE employee_face_profile ADD CONSTRAINT employee_face_profile_provider_check
          CHECK (provider IN ('LUXAND', 'FACEPP', 'OPENSOURCE'));
        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_provider_check;
        ALTER TABLE face_verification_attempt
          ADD CONSTRAINT face_verification_attempt_provider_check
          CHECK (provider IN ('LUXAND', 'FACEPP', 'OPENSOURCE'));

        CREATE TABLE IF NOT EXISTS face_embedding (
            "id" UUID NOT NULL,
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "person_ref" UUID NOT NULL,
            "sample_index" SMALLINT NOT NULL,
            "model_version" VARCHAR(40) NOT NULL,
            "embedding_enc" TEXT NOT NULL,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "face_embedding_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "face_embedding_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_embedding_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "face_embedding_sample_index_check" CHECK (sample_index >= 0),
            CONSTRAINT "face_embedding_person_sample_key" UNIQUE ("person_ref", "sample_index")
        );

        CREATE INDEX IF NOT EXISTS face_embedding_company_person_idx
          ON face_embedding (company_id, person_ref);

        ALTER TABLE face_embedding ENABLE ROW LEVEL SECURITY;
        ALTER TABLE face_embedding FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON face_embedding;
        CREATE POLICY tenant_isolation ON face_embedding
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM employee_face_profile WHERE provider = 'OPENSOURCE')
               OR EXISTS (SELECT 1 FROM face_verification_attempt WHERE provider = 'OPENSOURCE')
               OR EXISTS (SELECT 1 FROM face_embedding) THEN
                RAISE EXCEPTION
                  'OPENSOURCE face data exists; revoke and purge it before downgrading';
            END IF;
        END $$;

        DROP TABLE IF EXISTS face_embedding;
        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_provider_check;
        ALTER TABLE face_verification_attempt
          ADD CONSTRAINT face_verification_attempt_provider_check
          CHECK (provider IN ('LUXAND', 'FACEPP'));
        ALTER TABLE employee_face_profile DROP CONSTRAINT employee_face_profile_provider_check;
        ALTER TABLE employee_face_profile ADD CONSTRAINT employee_face_profile_provider_check
          CHECK (provider IN ('LUXAND', 'FACEPP'));
        """
    )
