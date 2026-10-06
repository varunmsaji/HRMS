"""Leave hardening - year-end processing marker and the maximum-consecutive-days policy field.

- `leave_year_end_run` (decision 16): one row per (company, employee, leave-year start) recording
  that the year-end operation has been done. The year-end sweep now has a catch-up window, so on
  any of its days it must know whether a given year start was already handled - otherwise a later
  run would re-evaluate the lapse / carry-forward cap against a balance that already includes the
  year's fresh accrual. The unique key makes concurrent catch-up runs idempotent. RLS-enforced like
  every leave table; the runtime role may only insert and read it (it is history, not state).
- `leave_policy_version.max_consecutive_days` (decision 15): the longest single leave application,
  in calendar days, a policy permits. Default 30 for every row, existing and new; HR raises it per
  policy. Bounded 1..90 because a single request can never span more than 90 days.

Additive only: no existing row is rewritten, and existing leave applications are untouched (the new
limit applies to applications submitted from now on).

Revision ID: 20261010091000
Revises: 20261010090000
"""

from alembic import op

revision = "20261010091000"
down_revision = "20261010090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_year_end_run (
            id UUID NOT NULL,
            company_id UUID NOT NULL,
            employee_id UUID NOT NULL,
            year_start DATE NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT leave_year_end_run_pkey PRIMARY KEY (id),
            CONSTRAINT leave_year_end_run_company_id_fkey FOREIGN KEY (company_id)
                REFERENCES company (id),
            CONSTRAINT leave_year_end_run_employee_id_fkey FOREIGN KEY (employee_id)
                REFERENCES employee (id),
            CONSTRAINT uq_leave_year_end_run UNIQUE (company_id, employee_id, year_start)
        );

        ALTER TABLE leave_year_end_run ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leave_year_end_run FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON leave_year_end_run;
        CREATE POLICY tenant_isolation ON leave_year_end_run
          USING (company_id = current_setting('app.company_id', true)::uuid);

        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
                GRANT SELECT, INSERT ON leave_year_end_run TO hrms_app;
                REVOKE UPDATE, DELETE, TRUNCATE ON leave_year_end_run FROM hrms_app;
            END IF;
        END $$;

        ALTER TABLE leave_policy_version
            ADD COLUMN IF NOT EXISTS max_consecutive_days INTEGER NOT NULL DEFAULT 30;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'leave_policy_version_max_consecutive_days_check'
            ) THEN
                ALTER TABLE leave_policy_version
                    ADD CONSTRAINT leave_policy_version_max_consecutive_days_check
                    CHECK (max_consecutive_days BETWEEN 1 AND 90);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE leave_policy_version
            DROP CONSTRAINT IF EXISTS leave_policy_version_max_consecutive_days_check;
        ALTER TABLE leave_policy_version DROP COLUMN IF EXISTS max_consecutive_days;
        DROP TABLE IF EXISTS leave_year_end_run;
        """
    )
