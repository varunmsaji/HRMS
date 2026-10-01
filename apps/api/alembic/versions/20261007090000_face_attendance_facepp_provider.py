"""Face attendance (2/n) — allow 'FACEPP' as a face-provider value.

Widens both provider CHECK constraints from 20261005090000 to accept 'FACEPP' alongside the
existing 'LUXAND' (kept, not dropped, so the one pre-existing LUXAND-provider row stays valid).
The application only ever writes 'FACEPP' going forward — `face_verification.py`'s Luxand
adapter was removed, not kept as a selectable option.

Revision ID: 20261007090000
Revises: 20261006090000
"""

from alembic import op

revision = "20261007090000"
down_revision = "20261006090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee_face_profile DROP CONSTRAINT employee_face_profile_provider_check;
        ALTER TABLE employee_face_profile ADD CONSTRAINT employee_face_profile_provider_check
          CHECK (provider IN ('LUXAND', 'FACEPP'));

        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_provider_check;
        ALTER TABLE face_verification_attempt ADD CONSTRAINT face_verification_attempt_provider_check
          CHECK (provider IN ('LUXAND', 'FACEPP'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE face_verification_attempt
          DROP CONSTRAINT face_verification_attempt_provider_check;
        ALTER TABLE face_verification_attempt ADD CONSTRAINT face_verification_attempt_provider_check
          CHECK (provider IN ('LUXAND'));

        ALTER TABLE employee_face_profile DROP CONSTRAINT employee_face_profile_provider_check;
        ALTER TABLE employee_face_profile ADD CONSTRAINT employee_face_profile_provider_check
          CHECK (provider IN ('LUXAND'));
        """
    )
