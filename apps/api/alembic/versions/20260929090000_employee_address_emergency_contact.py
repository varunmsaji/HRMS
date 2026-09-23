"""Employee address (present + permanent) and emergency contact — market-parity onboarding-data
pass, part 2.

Closes an existing gap: `OnboardingCase.address_info`/`.emergency_contact` have been collected
from candidates since O1, but `OnboardingActivationService.activate_case` never had an
Employee-side column to write them to (`onboarding/schemas.py`'s own module docstring flagged
this explicitly as "a known gap, not a silent one"). Flat columns, not a child table — these are
single current-value facts, same shape as `gender`/`blood_group`, not history.

Additive only (`ADD COLUMN IF NOT EXISTS`), same style as `20260813180000_employee_foundation.py`
— no RLS/constraint changes needed, `employee` is already RLS-protected.

Revision ID: 20260929090000
Revises: 20260928091000
"""

from alembic import op

revision = "20260929090000"
down_revision = "20260928091000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee
          ADD COLUMN IF NOT EXISTS present_address_line1 VARCHAR(200),
          ADD COLUMN IF NOT EXISTS present_address_line2 VARCHAR(200),
          ADD COLUMN IF NOT EXISTS present_city VARCHAR(100),
          ADD COLUMN IF NOT EXISTS present_state_code VARCHAR(10),
          ADD COLUMN IF NOT EXISTS present_pincode VARCHAR(10),
          ADD COLUMN IF NOT EXISTS present_country_code VARCHAR(2),
          ADD COLUMN IF NOT EXISTS permanent_address_line1 VARCHAR(200),
          ADD COLUMN IF NOT EXISTS permanent_address_line2 VARCHAR(200),
          ADD COLUMN IF NOT EXISTS permanent_city VARCHAR(100),
          ADD COLUMN IF NOT EXISTS permanent_state_code VARCHAR(10),
          ADD COLUMN IF NOT EXISTS permanent_pincode VARCHAR(10),
          ADD COLUMN IF NOT EXISTS permanent_country_code VARCHAR(2),
          ADD COLUMN IF NOT EXISTS permanent_same_as_present BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS emergency_contact_name VARCHAR(150),
          ADD COLUMN IF NOT EXISTS emergency_contact_relationship VARCHAR(50),
          ADD COLUMN IF NOT EXISTS emergency_contact_phone VARCHAR(20);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE employee
          DROP COLUMN IF EXISTS present_address_line1,
          DROP COLUMN IF EXISTS present_address_line2,
          DROP COLUMN IF EXISTS present_city,
          DROP COLUMN IF EXISTS present_state_code,
          DROP COLUMN IF EXISTS present_pincode,
          DROP COLUMN IF EXISTS present_country_code,
          DROP COLUMN IF EXISTS permanent_address_line1,
          DROP COLUMN IF EXISTS permanent_address_line2,
          DROP COLUMN IF EXISTS permanent_city,
          DROP COLUMN IF EXISTS permanent_state_code,
          DROP COLUMN IF EXISTS permanent_pincode,
          DROP COLUMN IF EXISTS permanent_country_code,
          DROP COLUMN IF EXISTS permanent_same_as_present,
          DROP COLUMN IF EXISTS emergency_contact_name,
          DROP COLUMN IF EXISTS emergency_contact_relationship,
          DROP COLUMN IF EXISTS emergency_contact_phone;
        """
    )
