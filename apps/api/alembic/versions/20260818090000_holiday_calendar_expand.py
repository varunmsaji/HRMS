"""Workforce Calendar W1 (1/5) — expand `holiday_calendar` stub in place.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §7.1 and DEC-021 ("ALTER stubs
in place; never drop-and-recreate `holiday_calendar`/`holiday`/`shift`"). `holiday_calendar`
has existed since `001_init_schema.sql` (id/company_id/name/created_at/updated_at/deleted_at)
with RLS already enabled via that migration's tenant-table loop — no RLS change needed here,
only additive columns.

New columns, all named directly in §7.1's table:
- `code` — optional, unique per company when present.
- `kind` — `NATIONAL` / `REGIONAL` / `COMPANY` / `LOCATION`.
- `state_code` — nullable; regional calendars.
- `valid_from` / `valid_to` — replaces a single `year` so a calendar can span a fiscal year.
- `is_active` / `version` — Organisation master pattern (Shift/Grade/Branch precedent); §7.1
  doesn't literally name these two, but calls this "the Organisation master pattern," which is
  never built without them elsewhere in this codebase.

Revision ID: 20260818090000
Revises: 20260815140000
"""

from alembic import op

revision = "20260818090000"
down_revision = "20260815140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE holiday_calendar
          ADD COLUMN IF NOT EXISTS "code" VARCHAR(30),
          ADD COLUMN IF NOT EXISTS "kind" VARCHAR(20) NOT NULL DEFAULT 'COMPANY',
          ADD COLUMN IF NOT EXISTS "state_code" VARCHAR(10),
          ADD COLUMN IF NOT EXISTS "valid_from" DATE,
          ADD COLUMN IF NOT EXISTS "valid_to" DATE,
          ADD COLUMN IF NOT EXISTS "is_active" BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS "version" INTEGER NOT NULL DEFAULT 1;

        ALTER TABLE holiday_calendar
          DROP CONSTRAINT IF EXISTS holiday_calendar_kind_check;
        ALTER TABLE holiday_calendar
          ADD CONSTRAINT holiday_calendar_kind_check
          CHECK (kind IN ('NATIONAL', 'REGIONAL', 'COMPANY', 'LOCATION'));

        DROP INDEX IF EXISTS holiday_calendar_company_id_code_idx;
        CREATE UNIQUE INDEX holiday_calendar_company_id_code_idx
          ON holiday_calendar (company_id, code)
          WHERE code IS NOT NULL AND deleted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS holiday_calendar_company_id_code_idx;
        ALTER TABLE holiday_calendar
          DROP CONSTRAINT IF EXISTS holiday_calendar_kind_check;
        ALTER TABLE holiday_calendar
          DROP COLUMN IF EXISTS "code",
          DROP COLUMN IF EXISTS "kind",
          DROP COLUMN IF EXISTS "state_code",
          DROP COLUMN IF EXISTS "valid_from",
          DROP COLUMN IF EXISTS "valid_to",
          DROP COLUMN IF EXISTS "is_active",
          DROP COLUMN IF EXISTS "version";
        """
    )
