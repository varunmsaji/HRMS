"""Workforce Calendar W1 (4/5) — new `work_calendar`, `work_calendar_holiday_calendar`,
`calendar_exception` tables.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §6 and WD-01 ("WorkCalendar and
HolidayCalendar are separate concepts" — WorkCalendar is the assignment-facing composition of
holiday calendars + a weekly-off pattern + dated exceptions; employees are assigned a
WorkCalendar, never a raw HolidayCalendar).

`work_calendar`: identity + optional `weekly_off_pattern_id` default +
`restricted_holidays_are_off_by_default` (§7.2's named escape hatch for the open product
decision PD-CAL-1 — "are restricted/optional holidays off-by-default or working-until-
applied?" — default `false` per the architecture's documented default; this flag is the only
sanctioned per-company override, nothing more).

`work_calendar_holiday_calendar`: ordered composition join table (§6.3 — "union of holiday
dates... first HolidayCalendar in the ordered list supplies the display name if types
otherwise tie"), own `company_id`+RLS (see the rationale already recorded in
`20260818110000_weekly_off_pattern.py`'s docstring for why child tables get their own RLS in
this codebase rather than relying on a join).

`calendar_exception`: one-off dated overrides (§7.3) — `SPECIAL_WORKING` / `SHUTDOWN` /
`SUBSTITUTE_HOLIDAY` / `CANCEL_HOLIDAY`. A partial unique index enforces at most one *active*
exception per `(work_calendar_id, exception_date)` — correcting an exception is
deactivate-then-insert, never an in-place rewrite of `exception_date`/`exception_type`
(consistent with §2.3 constraint #1: "insert-new, never PATCH of historical core values").

Revision ID: 20260818120000
Revises: 20260818110000
"""

from alembic import op

revision = "20260818120000"
down_revision = "20260818110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS work_calendar (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "name" VARCHAR(150) NOT NULL,
            "code" VARCHAR(30),
            "description" TEXT,
            "weekly_off_pattern_id" UUID,
            "restricted_holidays_are_off_by_default" BOOLEAN NOT NULL DEFAULT false,
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "work_calendar_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "work_calendar_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "work_calendar_weekly_off_pattern_id_fkey"
              FOREIGN KEY ("weekly_off_pattern_id")
              REFERENCES "weekly_off_pattern"("id") ON DELETE RESTRICT ON UPDATE CASCADE
        );

        CREATE INDEX IF NOT EXISTS work_calendar_company_id_idx ON work_calendar (company_id);
        CREATE UNIQUE INDEX IF NOT EXISTS work_calendar_company_id_code_idx
          ON work_calendar (company_id, code)
          WHERE code IS NOT NULL AND deleted_at IS NULL;

        ALTER TABLE work_calendar ENABLE ROW LEVEL SECURITY;
        ALTER TABLE work_calendar FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON work_calendar;
        CREATE POLICY tenant_isolation ON work_calendar
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS work_calendar_holiday_calendar (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "work_calendar_id" UUID NOT NULL,
            "holiday_calendar_id" UUID NOT NULL,
            "sort_order" INTEGER NOT NULL DEFAULT 0,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "work_calendar_holiday_calendar_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "work_calendar_holiday_calendar_company_id_fkey"
              FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "work_calendar_holiday_calendar_work_calendar_id_fkey"
              FOREIGN KEY ("work_calendar_id")
              REFERENCES "work_calendar"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "work_calendar_holiday_calendar_holiday_calendar_id_fkey"
              FOREIGN KEY ("holiday_calendar_id")
              REFERENCES "holiday_calendar"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "work_calendar_holiday_calendar_unique"
              UNIQUE ("work_calendar_id", "holiday_calendar_id")
        );

        CREATE INDEX IF NOT EXISTS work_calendar_holiday_calendar_company_id_idx
          ON work_calendar_holiday_calendar (company_id);
        CREATE INDEX IF NOT EXISTS work_calendar_holiday_calendar_work_calendar_id_idx
          ON work_calendar_holiday_calendar (work_calendar_id, sort_order);

        ALTER TABLE work_calendar_holiday_calendar ENABLE ROW LEVEL SECURITY;
        ALTER TABLE work_calendar_holiday_calendar FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON work_calendar_holiday_calendar;
        CREATE POLICY tenant_isolation ON work_calendar_holiday_calendar
          USING (company_id = current_setting('app.company_id', true)::uuid);

        CREATE TABLE IF NOT EXISTS calendar_exception (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "work_calendar_id" UUID NOT NULL,
            "exception_date" DATE NOT NULL,
            "exception_type" VARCHAR(20) NOT NULL,
            "name" VARCHAR(150),
            "reason" TEXT,
            "is_paid" BOOLEAN,
            "is_active" BOOLEAN NOT NULL DEFAULT true,
            "version" INTEGER NOT NULL DEFAULT 1,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,

            CONSTRAINT "calendar_exception_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "calendar_exception_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "calendar_exception_work_calendar_id_fkey" FOREIGN KEY ("work_calendar_id")
              REFERENCES "work_calendar"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "calendar_exception_type_check" CHECK (
              exception_type IN (
                'SPECIAL_WORKING', 'SHUTDOWN', 'SUBSTITUTE_HOLIDAY', 'CANCEL_HOLIDAY'
              )
            )
        );

        CREATE INDEX IF NOT EXISTS calendar_exception_company_id_idx
          ON calendar_exception (company_id);
        CREATE INDEX IF NOT EXISTS calendar_exception_work_calendar_id_date_idx
          ON calendar_exception (work_calendar_id, exception_date);

        DROP INDEX IF EXISTS calendar_exception_work_calendar_id_date_active_idx;
        CREATE UNIQUE INDEX calendar_exception_work_calendar_id_date_active_idx
          ON calendar_exception (work_calendar_id, exception_date)
          WHERE is_active AND deleted_at IS NULL;

        ALTER TABLE calendar_exception ENABLE ROW LEVEL SECURITY;
        ALTER TABLE calendar_exception FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON calendar_exception;
        CREATE POLICY tenant_isolation ON calendar_exception
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS calendar_exception;
        DROP TABLE IF EXISTS work_calendar_holiday_calendar;
        DROP TABLE IF EXISTS work_calendar;
        """
    )
