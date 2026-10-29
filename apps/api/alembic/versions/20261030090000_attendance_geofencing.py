"""Attendance geofencing: policy-version columns, authorised extra workplaces, attempt log.

Revision ID: 20261030090000
Revises: 20261029090000

Additive and backward compatible:

* `attendance_policy_version` gains `geofence_mode` (default 'DISABLED'), `geofence_max_accuracy_m`
  and `geofence_max_age_seconds`. Every existing row — published or draft — reads DISABLED, so no
  tenant's punch behaviour changes until an administrator publishes a version that says otherwise.
* `branch` gains `UNIQUE (company_id, id)` (trivially true: `id` is the primary key) so child
  tables can carry a composite tenant foreign key to it.
* `employee_workplace_authorization` — extra branches an employee may punch at. Composite FKs to
  `employee` and `branch` make a cross-company row impossible at the database level.
* `geofence_attempt` — append-only record of evaluated punch locations (coordinates rounded to
  4 dp). Composite FK to `employee`.

Both new tables get `ENABLE`/`FORCE ROW LEVEL SECURITY` with the standard `tenant_isolation`
policy. Downgrade drops the two tables, the branch constraint and the three columns.
"""

# ruff: noqa: E501 - long SQL

from alembic import op

revision = "20261030090000"
down_revision = "20261029090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE attendance_policy_version
          ADD COLUMN IF NOT EXISTS geofence_mode VARCHAR(10) NOT NULL DEFAULT 'DISABLED',
          ADD COLUMN IF NOT EXISTS geofence_max_accuracy_m INTEGER NOT NULL DEFAULT 100,
          ADD COLUMN IF NOT EXISTS geofence_max_age_seconds INTEGER NOT NULL DEFAULT 60;
        ALTER TABLE attendance_policy_version
          ADD CONSTRAINT attendance_policy_version_geofence_mode_check
            CHECK (geofence_mode IN ('DISABLED', 'OPTIONAL', 'REQUIRED')),
          ADD CONSTRAINT attendance_policy_version_geofence_accuracy_check
            CHECK (geofence_max_accuracy_m BETWEEN 5 AND 500),
          ADD CONSTRAINT attendance_policy_version_geofence_age_check
            CHECK (geofence_max_age_seconds BETWEEN 5 AND 300);

        ALTER TABLE branch ADD CONSTRAINT branch_company_id_id_key UNIQUE (company_id, id);

        CREATE TABLE employee_workplace_authorization (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL,
            employee_id UUID NOT NULL,
            branch_id UUID NOT NULL,
            created_by_user_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT employee_workplace_authorization_pkey PRIMARY KEY (id),
            CONSTRAINT employee_workplace_authorization_company_fkey
              FOREIGN KEY (company_id) REFERENCES company (id) ON DELETE RESTRICT,
            CONSTRAINT employee_workplace_authorization_employee_fkey
              FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id) ON DELETE RESTRICT,
            CONSTRAINT employee_workplace_authorization_branch_fkey
              FOREIGN KEY (company_id, branch_id) REFERENCES branch (company_id, id) ON DELETE RESTRICT,
            CONSTRAINT employee_workplace_authorization_user_fkey
              FOREIGN KEY (created_by_user_id) REFERENCES "user" (id) ON DELETE SET NULL,
            CONSTRAINT employee_workplace_authorization_unique
              UNIQUE (company_id, employee_id, branch_id)
        );
        CREATE INDEX employee_workplace_authorization_company_id_idx
          ON employee_workplace_authorization (company_id);
        CREATE INDEX employee_workplace_authorization_employee_id_idx
          ON employee_workplace_authorization (employee_id);
        CREATE INDEX employee_workplace_authorization_branch_idx
          ON employee_workplace_authorization (company_id, branch_id);

        CREATE TABLE geofence_attempt (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL,
            employee_id UUID NOT NULL,
            punch_id UUID,
            direction VARCHAR(10) NOT NULL,
            source VARCHAR(20) NOT NULL,
            mode VARCHAR(10) NOT NULL,
            outcome VARCHAR(40) NOT NULL,
            accepted BOOLEAN NOT NULL,
            branch_id UUID,
            distance_m NUMERIC(10, 2),
            radius_m NUMERIC(10, 2),
            accuracy_m NUMERIC(10, 2),
            latitude NUMERIC(7, 4),
            longitude NUMERIC(8, 4),
            captured_at TIMESTAMPTZ,
            client_error VARCHAR(30),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT geofence_attempt_pkey PRIMARY KEY (id),
            CONSTRAINT geofence_attempt_company_fkey
              FOREIGN KEY (company_id) REFERENCES company (id) ON DELETE RESTRICT,
            CONSTRAINT geofence_attempt_employee_fkey
              FOREIGN KEY (company_id, employee_id) REFERENCES employee (company_id, id) ON DELETE RESTRICT,
            CONSTRAINT geofence_attempt_punch_fkey
              FOREIGN KEY (punch_id) REFERENCES punch (id) ON DELETE SET NULL,
            CONSTRAINT geofence_attempt_mode_check CHECK (mode IN ('OPTIONAL', 'REQUIRED')),
            CONSTRAINT geofence_attempt_direction_check CHECK (direction IN ('IN', 'OUT'))
        );
        CREATE INDEX geofence_attempt_company_created_idx
          ON geofence_attempt (company_id, created_at DESC);
        CREATE INDEX geofence_attempt_employee_created_idx
          ON geofence_attempt (company_id, employee_id, created_at DESC);

        ALTER TABLE employee_workplace_authorization ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_workplace_authorization FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON employee_workplace_authorization
          USING (company_id = current_setting('app.company_id', true)::uuid)
          WITH CHECK (company_id = current_setting('app.company_id', true)::uuid);

        ALTER TABLE geofence_attempt ENABLE ROW LEVEL SECURITY;
        ALTER TABLE geofence_attempt FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON geofence_attempt
          USING (company_id = current_setting('app.company_id', true)::uuid)
          WITH CHECK (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS geofence_attempt;
        DROP TABLE IF EXISTS employee_workplace_authorization;
        ALTER TABLE branch DROP CONSTRAINT IF EXISTS branch_company_id_id_key;
        ALTER TABLE attendance_policy_version
          DROP CONSTRAINT IF EXISTS attendance_policy_version_geofence_mode_check,
          DROP CONSTRAINT IF EXISTS attendance_policy_version_geofence_accuracy_check,
          DROP CONSTRAINT IF EXISTS attendance_policy_version_geofence_age_check,
          DROP COLUMN IF EXISTS geofence_mode,
          DROP COLUMN IF EXISTS geofence_max_accuracy_m,
          DROP COLUMN IF EXISTS geofence_max_age_seconds;
        """
    )
