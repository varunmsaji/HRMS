"""Company profile/settings gap-fill — Task C-03 (docs/modules/company/03_Database_Design.md).

Adds the Company Profile/Settings columns identified as schema drift against the approved
Company design (registration, contact, address, locale, working-hours), the two new CHECK
constraints on the pre-existing `fy_start_month`/`status` columns (added NOT VALID then
validated, per §8 step 2 — these columns are already populated), and the two new indexes
from §2.5. Additive only; no data migration (new columns are nullable or carry a DEFAULT).

Revision ID: 20260807140000
Revises: 20260803200000
"""

from alembic import op

revision = "20260807140000"
down_revision = "20260803200000"
branch_labels = None
depends_on = None

# Colons before `true`/`false` are escaped (`\:`) because op.execute() runs this string through
# SQLAlchemy's text() construct, which otherwise parses `:true`/`:false` as bind parameters.
_DEFAULT_WORKING_DAYS_PATTERN = (
    '\'[{"day":"MON","is_working"\\:true},{"day":"TUE","is_working"\\:true},'
    '{"day":"WED","is_working"\\:true},{"day":"THU","is_working"\\:true},'
    '{"day":"FRI","is_working"\\:true},{"day":"SAT","is_working"\\:false},'
    '{"day":"SUN","is_working"\\:false}]\''
)


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE company
          ADD COLUMN IF NOT EXISTS registration_number VARCHAR(64),
          ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255),
          ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(32),
          ADD COLUMN IF NOT EXISTS website VARCHAR(255),
          ADD COLUMN IF NOT EXISTS company_size VARCHAR(20)
            CHECK (company_size IN ('1-10','11-50','51-200','201-500','501-1000','1000+')),
          ADD COLUMN IF NOT EXISTS address_line1 VARCHAR(255),
          ADD COLUMN IF NOT EXISTS address_line2 VARCHAR(255),
          ADD COLUMN IF NOT EXISTS address_city VARCHAR(100),
          ADD COLUMN IF NOT EXISTS address_state VARCHAR(100),
          ADD COLUMN IF NOT EXISTS address_postal_code VARCHAR(20),
          ADD COLUMN IF NOT EXISTS address_country_code CHAR(2),
          ADD COLUMN IF NOT EXISTS locale_language_code VARCHAR(10) NOT NULL DEFAULT 'en-IN',
          ADD COLUMN IF NOT EXISTS date_format VARCHAR(20) NOT NULL DEFAULT 'DD/MM/YYYY',
          ADD COLUMN IF NOT EXISTS working_days_pattern JSONB NOT NULL
            DEFAULT {_DEFAULT_WORKING_DAYS_PATTERN},
          ADD COLUMN IF NOT EXISTS business_hours_start TIME,
          ADD COLUMN IF NOT EXISTS business_hours_end TIME
            CHECK (business_hours_end IS NULL OR business_hours_start IS NULL
                   OR business_hours_end > business_hours_start),
          ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES "user"(id) ON DELETE SET NULL,
          ADD COLUMN IF NOT EXISTS updated_by UUID REFERENCES "user"(id) ON DELETE SET NULL;

        ALTER TABLE company
          ADD CONSTRAINT company_fy_start_month_check
            CHECK (fy_start_month BETWEEN 1 AND 12) NOT VALID;
        ALTER TABLE company VALIDATE CONSTRAINT company_fy_start_month_check;

        ALTER TABLE company
          ADD CONSTRAINT company_status_check
            CHECK (status IN ('TRIAL','ACTIVE','SUSPENDED','TERMINATED')) NOT VALID;
        ALTER TABLE company VALIDATE CONSTRAINT company_status_check;

        CREATE INDEX IF NOT EXISTS company_status_idx
          ON company (status) WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS company_trial_ends_at_idx
          ON company (trial_ends_at) WHERE status = 'TRIAL';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS company_trial_ends_at_idx;
        DROP INDEX IF EXISTS company_status_idx;

        ALTER TABLE company DROP CONSTRAINT IF EXISTS company_status_check;
        ALTER TABLE company DROP CONSTRAINT IF EXISTS company_fy_start_month_check;

        ALTER TABLE company
          DROP COLUMN IF EXISTS updated_by,
          DROP COLUMN IF EXISTS created_by,
          DROP COLUMN IF EXISTS business_hours_end,
          DROP COLUMN IF EXISTS business_hours_start,
          DROP COLUMN IF EXISTS working_days_pattern,
          DROP COLUMN IF EXISTS date_format,
          DROP COLUMN IF EXISTS locale_language_code,
          DROP COLUMN IF EXISTS address_country_code,
          DROP COLUMN IF EXISTS address_postal_code,
          DROP COLUMN IF EXISTS address_state,
          DROP COLUMN IF EXISTS address_city,
          DROP COLUMN IF EXISTS address_line2,
          DROP COLUMN IF EXISTS address_line1,
          DROP COLUMN IF EXISTS company_size,
          DROP COLUMN IF EXISTS website,
          DROP COLUMN IF EXISTS contact_phone,
          DROP COLUMN IF EXISTS contact_email,
          DROP COLUMN IF EXISTS registration_number;
        """
    )
