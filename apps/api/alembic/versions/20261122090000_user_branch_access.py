"""Admin-assigned branch access for HR and branch managers: `user_branch_access`.

Revision ID: 20261122090000
Revises: 20261117090000

Until now an HR_ADMIN was company-wide and a BRANCH_MANAGER's single branch was derived from their
own job placement (`employee_assignment.branch_id`). This adds the explicit list the company admin
edits: which branches a user covers. One user may cover several branches and one branch may be
covered by several users. This migration is storage and data only; the application starts reading
the list in a later change, so applying it alone changes no one's access.

What it adds:

* `user_branch_access` (id, company_id, user_id, branch_id, created_by, created_at, updated_at,
  deleted_at). Rows are soft-deleted; a partial unique index allows one live row per
  (company, user, branch). Foreign keys to `company`, `user` and `branch`; the branch must belong to
  the SAME company as the row, enforced by a composite FK to `branch (company_id, id)` (the same
  backstop `20261031090000_shift_tenant_fk` adds for shifts), so a company cannot point at another
  company's branch. Users and branches are soft-deleted in normal operation; if one is ever
  hard-deleted its access rows go with it (ON DELETE CASCADE), so cleanup never trips on them. The parent key `branch_company_id_id_key` already exists
  (`20261030090000_attendance_geofencing`); this migration relies on it and never drops it. FORCE row-level security with the usual `tenant_isolation` policy.
* `account_invite.branch_ids UUID[] NOT NULL DEFAULT '{}'`: the branches an invited HR / branch
  manager will get when they accept, so such a user is never created with no access.
* Backfill, so nobody's reach changes when the application starts reading the list:
  - a user who holds HR_ADMIN in a company and does NOT hold COMPANY_ADMIN there receives one live
    row for every active, non-deleted branch of that company (HR was company-wide);
  - a user who holds BRANCH_MANAGER (and not COMPANY_ADMIN) receives one row for the branch of
    their own current assignment only, the branch their scope resolved to before: the earliest
    employee linked to the user, assignment with `effective_to IS NULL`, branch active and not
    deleted. A branch manager with no linked employee, no current branch, or an inactive branch
    gets no row (they saw no one before and still see no one until an admin assigns branches);
  - a user holding both roles gets every branch (HR's reach);
  - COMPANY_ADMIN ignores the list and gets no rows.
  Re-running adds nothing (ON CONFLICT DO NOTHING).

The backfill runs BEFORE row-level security is switched on for the new table, and the migration
refuses to run as a role that is itself subject to row-level security (it would read no roles and
silently backfill nothing); run it as the schema owner (`MIGRATIONS_DATABASE_URL`).

Downgrade drops the invite column and the table (the assigned lists are lost). It changes no other
row and leaves `branch_company_id_id_key` in place, which other tables depend on.
"""

# ruff: noqa: E501 - long SQL strings

from alembic import op

revision = "20261122090000"
down_revision = "20261117090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        SET LOCAL lock_timeout = '5s';

        DO $$
        BEGIN
          IF NOT (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user) THEN
            RAISE EXCEPTION 'cannot backfill user_branch_access as role %: it is subject to row-level security'
              , current_user
              USING HINT = 'Run migrations as the schema-owner role (MIGRATIONS_DATABASE_URL).';
          END IF;
        END $$;

        CREATE TABLE IF NOT EXISTS user_branch_access (
            "id" UUID NOT NULL DEFAULT gen_random_uuid(),
            "company_id" UUID NOT NULL,
            "user_id" UUID NOT NULL,
            "branch_id" UUID NOT NULL,
            "created_by" UUID,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
            "deleted_at" TIMESTAMPTZ,
            CONSTRAINT "user_branch_access_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "user_branch_access_company_id_fkey" FOREIGN KEY ("company_id")
              REFERENCES "company"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
            CONSTRAINT "user_branch_access_user_id_fkey" FOREIGN KEY ("user_id")
              REFERENCES "user"("id") ON DELETE CASCADE ON UPDATE CASCADE,
            CONSTRAINT "user_branch_access_created_by_fkey" FOREIGN KEY ("created_by")
              REFERENCES "user"("id") ON DELETE SET NULL,
            -- The branch must belong to the same company as this row.
            CONSTRAINT "user_branch_access_branch_fkey" FOREIGN KEY ("company_id", "branch_id")
              REFERENCES "branch"("company_id", "id") ON DELETE CASCADE ON UPDATE CASCADE
        );

        -- One live row per (company, user, branch); soft-deleted rows are history.
        CREATE UNIQUE INDEX IF NOT EXISTS user_branch_access_live_key
          ON user_branch_access (company_id, user_id, branch_id)
          WHERE deleted_at IS NULL;
        -- "Which branches does this user cover" (every request of an HR / branch manager).
        CREATE INDEX IF NOT EXISTS user_branch_access_user_idx
          ON user_branch_access (company_id, user_id)
          WHERE deleted_at IS NULL;
        -- "Who covers this branch".
        CREATE INDEX IF NOT EXISTS user_branch_access_branch_idx
          ON user_branch_access (company_id, branch_id)
          WHERE deleted_at IS NULL;

        ALTER TABLE account_invite
          ADD COLUMN IF NOT EXISTS branch_ids UUID[] NOT NULL DEFAULT '{}';

        -- Existing access is preserved. HR was company-wide: every live branch. COMPANY_ADMIN (in
        -- the same company) ignores the list: no rows.
        INSERT INTO user_branch_access (company_id, user_id, branch_id)
        SELECT DISTINCT uc.company_id, uc.user_id, b.id
        FROM user_company uc
        JOIN user_role ur ON ur.user_company_id = uc.id
        JOIN role r ON r.id = ur.role_id
                   AND r.company_id = uc.company_id
                   AND r.code = 'HR_ADMIN'
                   AND r.deleted_at IS NULL
        JOIN branch b ON b.company_id = uc.company_id
                     AND b.deleted_at IS NULL
                     AND b.is_active
        WHERE NOT EXISTS (
          SELECT 1
          FROM user_role ur2
          JOIN role r2 ON r2.id = ur2.role_id
                      AND r2.company_id = uc.company_id
                      AND r2.code = 'COMPANY_ADMIN'
                      AND r2.deleted_at IS NULL
          WHERE ur2.user_company_id = uc.id
        )
        ON CONFLICT (company_id, user_id, branch_id) WHERE deleted_at IS NULL DO NOTHING;

        -- A branch manager's scope was their own current branch: keep exactly that, not every
        -- branch. The employee is the earliest one linked to the user, as the application resolves
        -- it; the assignment is the current one (effective_to IS NULL). A user who also holds
        -- HR_ADMIN already has every branch from the statement above.
        INSERT INTO user_branch_access (company_id, user_id, branch_id)
        SELECT DISTINCT uc.company_id, uc.user_id, b.id
        FROM user_company uc
        JOIN user_role ur ON ur.user_company_id = uc.id
        JOIN role r ON r.id = ur.role_id
                   AND r.company_id = uc.company_id
                   AND r.code = 'BRANCH_MANAGER'
                   AND r.deleted_at IS NULL
        JOIN LATERAL (
          SELECT e.id
          FROM employee e
          WHERE e.company_id = uc.company_id
            AND e.user_id = uc.user_id
            AND e.deleted_at IS NULL
          ORDER BY e.created_at, e.id
          LIMIT 1
        ) emp ON true
        JOIN employee_assignment ea ON ea.company_id = uc.company_id
                                   AND ea.employee_id = emp.id
                                   AND ea.deleted_at IS NULL
                                   AND ea.effective_to IS NULL
                                   AND ea.branch_id IS NOT NULL
        JOIN branch b ON b.id = ea.branch_id
                     AND b.company_id = uc.company_id
                     AND b.deleted_at IS NULL
                     AND b.is_active
        WHERE NOT EXISTS (
          SELECT 1
          FROM user_role ur2
          JOIN role r2 ON r2.id = ur2.role_id
                      AND r2.company_id = uc.company_id
                      AND r2.code = 'COMPANY_ADMIN'
                      AND r2.deleted_at IS NULL
          WHERE ur2.user_company_id = uc.id
        )
        ON CONFLICT (company_id, user_id, branch_id) WHERE deleted_at IS NULL DO NOTHING;

        -- Tenant isolation, switched on after the backfill (which has no tenant context).
        ALTER TABLE user_branch_access ENABLE ROW LEVEL SECURITY;
        ALTER TABLE user_branch_access FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON user_branch_access;
        CREATE POLICY tenant_isolation ON user_branch_access
          USING (company_id = current_setting('app.company_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE account_invite DROP COLUMN IF EXISTS branch_ids;
        DROP TABLE IF EXISTS user_branch_access;
        """
    )
