"""W5 — `shift_roster` table.

Per `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §4.2/§9.7/§17 and decision log
WD-27: a per-employee-per-date schedule override. A `PUBLISHED` row for `(employee_id,
roster_date)` outranks `EmployeeAssignment.shift_id` in the calculation engine's shift
resolution (§9.7); `DRAFT` rows are invisible to calculation. `shift_id` is nullable — a pure
week-off or holiday-working override needs no shift. No GiST exclusion is needed: `roster_date`
is a single date, not a range (§17 — "the roster_date is the effective date"), so a plain
partial unique index on `(company_id, employee_id, roster_date)` already prevents the
"overlapping active roster" case.

Revision ID: 20260821090000
Revises: 20260820100000
"""

from alembic import op

revision = "20260821090000"
down_revision = "20260820100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shift_roster (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "roster_date" DATE NOT NULL,
            "shift_id" UUID,

            "is_week_off_override" BOOLEAN NOT NULL DEFAULT false,
            "is_holiday_working_override" BOOLEAN NOT NULL DEFAULT false,

            "status" VARCHAR(10) NOT NULL DEFAULT 'DRAFT',
            "reason" TEXT,
            "version" INTEGER NOT NULL DEFAULT 1,
            "deleted_at" TIMESTAMPTZ,

            "created_by" UUID,
            "updated_by" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT "shift_roster_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "shift_roster_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "shift_roster_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "shift_roster_shift_id_fkey" FOREIGN KEY ("shift_id")
              REFERENCES "shift"("id") ON DELETE SET NULL,
            CONSTRAINT "shift_roster_created_by_fkey" FOREIGN KEY ("created_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "shift_roster_updated_by_fkey" FOREIGN KEY ("updated_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            CONSTRAINT "shift_roster_status_check" CHECK (status IN ('DRAFT', 'PUBLISHED')),
            CONSTRAINT "shift_roster_override_exclusive_check" CHECK (
              NOT (is_week_off_override AND is_holiday_working_override)
            )
        );

        CREATE UNIQUE INDEX IF NOT EXISTS shift_roster_unique_idx
          ON shift_roster (company_id, employee_id, roster_date) WHERE deleted_at IS NULL;

        CREATE INDEX IF NOT EXISTS shift_roster_company_id_idx ON shift_roster (company_id);
        CREATE INDEX IF NOT EXISTS shift_roster_company_date_idx
          ON shift_roster (company_id, roster_date);
        CREATE INDEX IF NOT EXISTS shift_roster_employee_date_idx
          ON shift_roster (company_id, employee_id, roster_date DESC);

        ALTER TABLE shift_roster ENABLE ROW LEVEL SECURITY;
        ALTER TABLE shift_roster FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON shift_roster;
        CREATE POLICY tenant_isolation ON shift_roster
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shift_roster;")
