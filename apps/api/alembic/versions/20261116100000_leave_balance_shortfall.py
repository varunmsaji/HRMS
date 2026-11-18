"""Leave reconciliation (AC-03, P-E): `leave_balance_shortfall` exception table.

Revision ID: 20261116100000
Revises: 20261116090000

Owner decision P-E (16 Nov 2026). When a calendar change makes a date inside approved leave a
leave-consuming day and the balance cannot cover it (and the leave type does not allow a negative
balance), the day is neither debited nor turned into loss of pay: an exception row is opened for
HR, and attendance period close is blocked until it is resolved. One row per application-date;
a row is reopened if the same shortfall recurs. Purely additive. The downgrade refuses while any
shortfall row exists.

Tenant isolation: FORCE row-level security on `company_id`, like every tenant table.
"""

from alembic import op

revision = "20261116100000"
down_revision = "20261116090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_balance_shortfall (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "employee_id" UUID NOT NULL,
            "leave_application_id" UUID NOT NULL,
            "leave_type_id" UUID NOT NULL,
            "calendar_date" DATE NOT NULL,
            "required_fraction" NUMERIC(3, 2) NOT NULL,
            "available_balance" NUMERIC(8, 2) NOT NULL,
            "status" VARCHAR(20) NOT NULL DEFAULT 'OPEN',
            "resolution" VARCHAR(30),
            "resolved_at" TIMESTAMPTZ,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT "leave_balance_shortfall_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "leave_balance_shortfall_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE CASCADE,
            CONSTRAINT "leave_balance_shortfall_employee_id_fkey" FOREIGN KEY ("employee_id")
              REFERENCES "employee"("id") ON DELETE CASCADE,
            CONSTRAINT "leave_balance_shortfall_application_id_fkey"
              FOREIGN KEY ("leave_application_id") REFERENCES "leave_application"("id")
              ON DELETE CASCADE,
            CONSTRAINT "leave_balance_shortfall_leave_type_id_fkey" FOREIGN KEY ("leave_type_id")
              REFERENCES "leave_type"("id") ON DELETE CASCADE,
            CONSTRAINT "leave_balance_shortfall_application_date_unique"
              UNIQUE ("leave_application_id", "calendar_date"),
            CONSTRAINT "leave_balance_shortfall_status_check"
              CHECK (status IN ('OPEN', 'RESOLVED')),
            CONSTRAINT "leave_balance_shortfall_resolution_check" CHECK (
              resolution IS NULL OR resolution IN ('DEBITED', 'NO_LONGER_REQUIRED')
            )
        );

        CREATE INDEX IF NOT EXISTS leave_balance_shortfall_open_idx
          ON leave_balance_shortfall (company_id, calendar_date) WHERE status = 'OPEN';
        CREATE INDEX IF NOT EXISTS leave_balance_shortfall_employee_idx
          ON leave_balance_shortfall (company_id, employee_id);

        ALTER TABLE leave_balance_shortfall ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_balance_shortfall FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_balance_shortfall;
        CREATE POLICY tenant_isolation ON leave_balance_shortfall
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    """Refuses while any shortfall row exists (open or resolved): the table is HR's record of a
    leave day that could not be charged, and dropping it would delete that history. Nothing is
    changed then. `row_security = off` makes the check see every tenant's rows (it fails, never
    undercounts, if the migration role cannot bypass row security)."""
    op.execute(
        """
        SET LOCAL row_security = off;
        DO $$
        DECLARE
          n bigint;
        BEGIN
          IF to_regclass('leave_balance_shortfall') IS NOT NULL THEN
            SELECT count(*) INTO n FROM leave_balance_shortfall;
            IF n > 0 THEN
              RAISE EXCEPTION
                'Refusing to downgrade 20261116100000: % leave_balance_shortfall row(s) exist and '
                'dropping the table would delete shortfall history. Restore from a pre-upgrade '
                'backup, or keep this revision.', n;
            END IF;
          END IF;
        END
        $$;
        DROP TABLE IF EXISTS leave_balance_shortfall;
        """
    )
