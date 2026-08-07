-- Doc 03 §3.1: Row-Level Security is the backstop for tenant isolation, enabled on every table
-- carrying company_id. The application sets `SET LOCAL app.company_id` at the start of every
-- transaction (see src/core/tenancy) — this policy is what makes a forgotten WHERE clause return
-- zero rows instead of another tenant's data.
--
-- One block per tenant table. Add a new block here whenever a migration adds a table with a
-- company_id column — a CI check should eventually enforce "every new table has RLS enabled"
-- (Doc 03 §3.1) once the migration history exists to lint against.

ALTER TABLE company FORCE ROW LEVEL SECURITY;
-- company itself has no company_id (it IS the tenant root) — no policy needed, RLS not applicable.

DO $$
DECLARE
  tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'user_company', 'role', 'legal_entity', 'branch', 'department', 'designation', 'grade',
    'holiday_calendar', 'employee', 'employment', 'employee_assignment', 'employee_compensation'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (company_id = current_setting(''app.company_id'', true)::uuid)',
      tbl
    );
  END LOOP;
END $$;

-- Tables one join away from company_id (holiday, role_permission, user_role) rely on their parent's
-- RLS policy plus an application-layer join predicate; they are not given their own RLS policy
-- because they have no company_id column of their own to filter on.
