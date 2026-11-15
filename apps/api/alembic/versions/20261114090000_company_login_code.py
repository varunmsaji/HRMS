"""Company login code + employee-ID login lookup.

Employees can now sign in with their company code and employee ID (e.g. `ACME` + `EMP-0007`)
instead of their email. Employee codes come from a per-company number series, so `EMP-0001`
exists in every company: the company code is what makes the pair unique on the one shared login
page.

1. `company.login_code` — short, uppercase, globally unique. A `BEFORE INSERT` trigger fills it
   from the company name when the inserting code leaves it empty, so every path that creates a
   company (registration, seed data, test fixtures) gets one without having to know about it.
   Existing companies are backfilled the same way, oldest first.

2. `login_lookup_employee_user(company_code, employee_code)` — same shape and hardening as
   `login_lookup_user_companies` (migration 20260828090000): `employee` is under RLS and login
   runs before any tenant context exists, so the lookup goes through a narrow `SECURITY DEFINER`
   function, `EXECUTE` granted to `hrms_app` only, `search_path` pinned. It returns only the
   linked `user_id` and its `company_id` for one exact (company code, employee code) pair, and
   only for employees who already have a login — it cannot list a company's employees.

Revision ID: 20261114090000
Revises: 20261111090000
"""

from alembic import op

revision = "20261114090000"
down_revision = "20261111090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE company ADD COLUMN login_code VARCHAR(12);
        ALTER TABLE company ADD CONSTRAINT company_login_code_format
            CHECK (login_code ~ '^[A-Z0-9]{2,12}$');
        CREATE UNIQUE INDEX company_login_code_key ON company (login_code);

        -- The first free code for a company name: up to 6 letters/digits of the name, then a
        -- counter (ACME, ACME2, ACME3, ...) when that is taken.
        CREATE OR REPLACE FUNCTION company_next_login_code(p_name TEXT)
        RETURNS TEXT
        LANGUAGE plpgsql
        AS $$
        DECLARE
            base TEXT;
            candidate TEXT;
            n INT := 1;
        BEGIN
            base := left(upper(regexp_replace(coalesce(p_name, ''), '[^A-Za-z0-9]', '', 'g')), 6);
            IF length(base) < 2 THEN
                base := 'CO' || base;
            END IF;
            candidate := base;
            WHILE EXISTS (SELECT 1 FROM company WHERE login_code = candidate) LOOP
                n := n + 1;
                candidate := base || n::TEXT;
            END LOOP;
            RETURN candidate;
        END;
        $$;

        CREATE OR REPLACE FUNCTION company_assign_login_code()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.login_code IS NULL THEN
                NEW.login_code := company_next_login_code(NEW.name);
            ELSE
                NEW.login_code := upper(btrim(NEW.login_code));
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER company_assign_login_code
            BEFORE INSERT ON company
            FOR EACH ROW EXECUTE FUNCTION company_assign_login_code();

        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN SELECT id, name FROM company WHERE login_code IS NULL ORDER BY created_at, id
            LOOP
                UPDATE company SET login_code = company_next_login_code(r.name) WHERE id = r.id;
            END LOOP;
        END;
        $$;

        CREATE OR REPLACE FUNCTION login_lookup_employee_user(
            p_company_code TEXT, p_employee_code TEXT
        )
        RETURNS TABLE (user_id UUID, company_id UUID)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT e.user_id, e.company_id
            FROM employee e
            JOIN company c ON c.id = e.company_id
            WHERE c.login_code = upper(btrim(p_company_code))
              AND c.deleted_at IS NULL
              AND upper(e.employee_code) = upper(btrim(p_employee_code))
              AND e.deleted_at IS NULL
              AND e.user_id IS NOT NULL
            ORDER BY (e.employee_code = btrim(p_employee_code)) DESC
            LIMIT 1;
        $$;

        REVOKE ALL ON FUNCTION login_lookup_employee_user(TEXT, TEXT) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION login_lookup_employee_user(TEXT, TEXT) TO hrms_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS login_lookup_employee_user(TEXT, TEXT);
        DROP TRIGGER IF EXISTS company_assign_login_code ON company;
        DROP FUNCTION IF EXISTS company_assign_login_code();
        DROP FUNCTION IF EXISTS company_next_login_code(TEXT);
        DROP INDEX IF EXISTS company_login_code_key;
        ALTER TABLE company DROP CONSTRAINT IF EXISTS company_login_code_format;
        ALTER TABLE company DROP COLUMN IF EXISTS login_code;
        """
    )
