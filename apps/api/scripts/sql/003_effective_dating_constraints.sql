-- Doc 04 §1.2: overlapping effective-dated periods must be structurally impossible, not a code
-- convention. Requires the btree_gist extension (see infra/docker/postgres/init/001_extensions.sql).
-- NULL effective_to means "current" — treated as unbounded (infinity) for overlap purposes.

ALTER TABLE employee_assignment
  ADD CONSTRAINT employee_assignment_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );

ALTER TABLE employee_compensation
  ADD CONSTRAINT employee_compensation_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );

-- Add one block here for every future effective-dated table (employee_statutory, employee_bank,
-- salary_structure assignment, etc. — Doc 04 §5.5/5.6 and the payroll domain) as those land.
