"""Workforce Calendar W1 (2/5) — expand `holiday` stub in place; first RLS on this table.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §7.2 and DEC-021. `holiday` has
existed since `001_init_schema.sql` with only `id`/`calendar_id`/`date`/`name`/`is_optional` —
no `company_id`, no timestamps, no `version`, no RLS of its own (it relied on the legacy
"joins-away" pattern documented in `001_init_schema.sql:485-487`, which only ever existed
because the table had no `company_id` column to filter on).

§7.2 explicitly calls for `company_id` "denormalised for RLS (FACT pattern on every tenant
table)" — this migration adds it (backfilled from the parent `holiday_calendar.company_id`,
since every existing row, if any, must belong to some calendar), then gives `holiday` full
`ENABLE`/`FORCE ROW LEVEL SECURITY` + `tenant_isolation` for the first time, bringing it in
line with every table added since (`employee_bank`, `employee_assignment`, ...) rather than
the retired join-away pattern.

Also brings `holiday` up to the standard Organisation-master trio it never had
(`created_at`/`updated_at`/`deleted_at`/`version`/`is_active`), plus §7.2's typed columns:
`holiday_type` (`PUBLIC`/`COMPANY`/`OPTIONAL`/`RESTRICTED`/`WORKING_HOLIDAY`), `is_paid`,
`is_working`, `region_note`, `replaced_holiday_id` (substitution link, self-FK). The legacy
`is_optional` boolean is kept as a deprecated shadow of `holiday_type='OPTIONAL'`
(§7.2: "keep both briefly; stop writing `is_optional` once the type column is live") —
service-layer code sets both in lockstep on write; `holiday_type` is canonical for reads.

Revision ID: 20260818100000
Revises: 20260818090000
"""

from alembic import op

revision = "20260818100000"
down_revision = "20260818090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE holiday
          ADD COLUMN IF NOT EXISTS "company_id" UUID,
          ADD COLUMN IF NOT EXISTS "holiday_type" VARCHAR(20) NOT NULL DEFAULT 'PUBLIC',
          ADD COLUMN IF NOT EXISTS "is_paid" BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS "is_working" BOOLEAN NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS "region_note" VARCHAR(200),
          ADD COLUMN IF NOT EXISTS "replaced_holiday_id" UUID,
          ADD COLUMN IF NOT EXISTS "is_active" BOOLEAN NOT NULL DEFAULT true,
          ADD COLUMN IF NOT EXISTS "version" INTEGER NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
          ADD COLUMN IF NOT EXISTS "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
          ADD COLUMN IF NOT EXISTS "deleted_at" TIMESTAMPTZ;

        UPDATE holiday h
          SET company_id = hc.company_id
          FROM holiday_calendar hc
          WHERE hc.id = h.calendar_id AND h.company_id IS NULL;

        ALTER TABLE holiday ALTER COLUMN company_id SET NOT NULL;

        ALTER TABLE holiday
          DROP CONSTRAINT IF EXISTS holiday_company_id_fkey;
        ALTER TABLE holiday
          ADD CONSTRAINT holiday_company_id_fkey FOREIGN KEY (company_id)
          REFERENCES company(id) ON DELETE RESTRICT ON UPDATE CASCADE;

        ALTER TABLE holiday
          DROP CONSTRAINT IF EXISTS holiday_replaced_holiday_id_fkey;
        ALTER TABLE holiday
          ADD CONSTRAINT holiday_replaced_holiday_id_fkey FOREIGN KEY (replaced_holiday_id)
          REFERENCES holiday(id) ON DELETE RESTRICT ON UPDATE CASCADE;

        ALTER TABLE holiday
          DROP CONSTRAINT IF EXISTS holiday_type_check;
        ALTER TABLE holiday
          ADD CONSTRAINT holiday_type_check
          CHECK (holiday_type IN (
            'PUBLIC', 'COMPANY', 'OPTIONAL', 'RESTRICTED', 'WORKING_HOLIDAY'
          ));

        CREATE INDEX IF NOT EXISTS holiday_company_id_idx ON holiday (company_id);
        CREATE INDEX IF NOT EXISTS holiday_calendar_id_date_idx ON holiday (calendar_id, date);

        DROP INDEX IF EXISTS holiday_calendar_id_date_active_idx;
        CREATE UNIQUE INDEX holiday_calendar_id_date_active_idx
          ON holiday (calendar_id, date)
          WHERE deleted_at IS NULL AND is_active;

        ALTER TABLE holiday ENABLE ROW LEVEL SECURITY;
        ALTER TABLE holiday FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON holiday;
        CREATE POLICY tenant_isolation ON holiday
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE holiday DISABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON holiday;

        DROP INDEX IF EXISTS holiday_calendar_id_date_active_idx;
        DROP INDEX IF EXISTS holiday_calendar_id_date_idx;
        DROP INDEX IF EXISTS holiday_company_id_idx;

        ALTER TABLE holiday
          DROP CONSTRAINT IF EXISTS holiday_type_check;
        ALTER TABLE holiday
          DROP CONSTRAINT IF EXISTS holiday_replaced_holiday_id_fkey;
        ALTER TABLE holiday
          DROP CONSTRAINT IF EXISTS holiday_company_id_fkey;

        ALTER TABLE holiday
          DROP COLUMN IF EXISTS "company_id",
          DROP COLUMN IF EXISTS "holiday_type",
          DROP COLUMN IF EXISTS "is_paid",
          DROP COLUMN IF EXISTS "is_working",
          DROP COLUMN IF EXISTS "region_note",
          DROP COLUMN IF EXISTS "replaced_holiday_id",
          DROP COLUMN IF EXISTS "is_active",
          DROP COLUMN IF EXISTS "version",
          DROP COLUMN IF EXISTS "created_at",
          DROP COLUMN IF EXISTS "updated_at",
          DROP COLUMN IF EXISTS "deleted_at";
        """
    )
