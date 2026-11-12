"""Face attendance - CompreFace provider value.

`COMPREFACE` becomes a valid `provider` on `employee_face_profile` and `face_verification_attempt`
(same widening as 20261107090000 did for AZURE), and on `face_shadow_enrollment` so CompreFace can
also run as the shadow-comparison provider. Existing rows are unchanged.

Revision ID: 20261110090000
Revises: 20261109090000
"""

from alembic import op

revision = "20261110090000"
down_revision = "20261109090000"
branch_labels = None
depends_on = None


def _set(values: str) -> str:
    return f"""
        ALTER TABLE employee_face_profile DROP CONSTRAINT employee_face_profile_provider_check;
        ALTER TABLE employee_face_profile ADD CONSTRAINT employee_face_profile_provider_check
          CHECK (provider IN ({values}));
        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_provider_check;
        ALTER TABLE face_verification_attempt
          ADD CONSTRAINT face_verification_attempt_provider_check
          CHECK (provider IN ({values}));
    """


def _shadow_set(values: str) -> str:
    return f"""
        ALTER TABLE face_shadow_enrollment DROP CONSTRAINT face_shadow_enrollment_provider_check;
        ALTER TABLE face_shadow_enrollment ADD CONSTRAINT face_shadow_enrollment_provider_check
          CHECK (provider IN ({values}));
    """


def upgrade() -> None:
    op.execute(_set("'LUXAND', 'FACEPP', 'OPENSOURCE', 'AZURE', 'COMPREFACE'"))
    op.execute(_shadow_set("'FACEPP', 'OPENSOURCE', 'COMPREFACE'"))


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM employee_face_profile WHERE provider = 'COMPREFACE')
               OR EXISTS (SELECT 1 FROM face_verification_attempt WHERE provider = 'COMPREFACE')
               OR EXISTS (SELECT 1 FROM face_shadow_enrollment WHERE provider = 'COMPREFACE') THEN
                RAISE EXCEPTION 'COMPREFACE face data exists; revoke and purge it before downgrading';
            END IF;
        END $$;
        """
    )
    op.execute(_shadow_set("'FACEPP', 'OPENSOURCE'"))
    op.execute(_set("'LUXAND', 'FACEPP', 'OPENSOURCE', 'AZURE'"))
