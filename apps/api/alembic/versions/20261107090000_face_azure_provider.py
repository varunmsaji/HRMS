"""Face attendance - Azure AI Face provider value.

`AZURE` becomes a valid `provider` on `employee_face_profile` and `face_verification_attempt`
(same widening as 20261022090000 did for OPENSOURCE). Existing rows are unchanged.

Revision ID: 20261107090000
Revises: 20261106090000
"""

from alembic import op

revision = "20261107090000"
down_revision = "20261106090000"
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


def upgrade() -> None:
    op.execute(_set("'LUXAND', 'FACEPP', 'OPENSOURCE', 'AZURE'"))


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM employee_face_profile WHERE provider = 'AZURE')
               OR EXISTS (SELECT 1 FROM face_verification_attempt WHERE provider = 'AZURE') THEN
                RAISE EXCEPTION 'AZURE face data exists; revoke and purge it before downgrading';
            END IF;
        END $$;
        """
    )
    op.execute(_set("'LUXAND', 'FACEPP', 'OPENSOURCE'"))
