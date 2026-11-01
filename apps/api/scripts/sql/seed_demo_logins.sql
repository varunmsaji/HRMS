-- Logins for the 20 demo employees created by seed_demo_employees.sql (run that first).
--
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -v pwhash="$ARGON2_HASH" -f scripts/sql/seed_demo_logins.sql
--
-- `pwhash` is an argon2 hash made with hrms.core.auth.passwords.hash_password; the plain password is
-- never stored in this file. Each employee signs in with their personal_email
-- (first.last.demo@example.com). Roles: everyone gets "Employee"; the five department heads that
-- have reports (DEMO-001, 003, 004, 005, 006) also get "Reporting Manager"; DEMO-002 gets
-- "HR Administrator". Idempotent: earlier demo logins are removed and recreated.

BEGIN;

CREATE TEMP TABLE _demo ON COMMIT DROP AS
SELECT e.id AS employee_id, e.company_id, e.first_name, e.last_name, e.personal_email AS email,
       e.employee_code, replace(e.employee_code, 'DEMO-', '')::int AS n
FROM employee e
WHERE e.custom_fields->>'demo_seed' = 'demo-20-employees'
  AND e.company_id = (SELECT uc.company_id FROM "user" u JOIN user_company uc ON uc.user_id = u.id
                      WHERE lower(u.email) = 'varunmsaji01@gmail.com' ORDER BY uc.company_id LIMIT 1);

-- psql does not substitute variables inside a DO body, so the hash goes through a temp table.
CREATE TEMP TABLE _pw ON COMMIT DROP AS SELECT :'pwhash'::text AS hash;

DO $$ BEGIN
  IF (SELECT count(*) FROM _demo) <> 20 THEN
    RAISE EXCEPTION 'expected the 20 demo employees; run seed_demo_employees.sql first (found %)', (SELECT count(*) FROM _demo);
  END IF;
  IF (SELECT hash FROM _pw) !~ '^\$argon2' THEN
    RAISE EXCEPTION 'pwhash must be an argon2 hash';
  END IF;
END $$;

-- ---- remove earlier demo logins ------------------------------------------------------------------
CREATE TEMP TABLE _old_users ON COMMIT DROP AS
SELECT e.user_id AS id FROM employee e JOIN _demo d ON d.employee_id = e.id WHERE e.user_id IS NOT NULL;

UPDATE employee SET user_id = NULL WHERE id IN (SELECT employee_id FROM _demo);
DELETE FROM user_role WHERE user_company_id IN (SELECT id FROM user_company WHERE user_id IN (SELECT id FROM _old_users));
DELETE FROM user_company WHERE user_id IN (SELECT id FROM _old_users);
DELETE FROM "user" WHERE id IN (SELECT id FROM _old_users);

-- ---- create ----------------------------------------------------------------------------------------
CREATE TEMP TABLE _new ON COMMIT DROP AS
SELECT d.*, gen_random_uuid() AS user_id, gen_random_uuid() AS uc_id FROM _demo d;

INSERT INTO "user" (id, email, password_hash, first_name, last_name, status, email_verified_at, created_at, updated_at)
SELECT user_id, email, (SELECT hash FROM _pw), first_name, last_name, 'ACTIVE', now(), now(), now() FROM _new;

INSERT INTO user_company (id, company_id, user_id, is_primary, status, created_at, updated_at)
SELECT uc_id, company_id, user_id, true, 'ACTIVE', now(), now() FROM _new;

UPDATE employee e SET user_id = n.user_id FROM _new n WHERE e.id = n.employee_id;

INSERT INTO user_role (user_company_id, role_id)
SELECT n.uc_id, r.id FROM _new n JOIN role r ON r.company_id = n.company_id AND r.name = 'Employee';

INSERT INTO user_role (user_company_id, role_id)
SELECT n.uc_id, r.id FROM _new n JOIN role r ON r.company_id = n.company_id AND r.name = 'Reporting Manager'
WHERE n.n IN (1, 3, 4, 5, 6);

INSERT INTO user_role (user_company_id, role_id)
SELECT n.uc_id, r.id FROM _new n JOIN role r ON r.company_id = n.company_id AND r.name = 'HR Administrator'
WHERE n.n = 2;

SELECT n.employee_code, n.email,
       string_agg(r.name, ' + ' ORDER BY r.name) AS roles
FROM _new n
JOIN user_role ur ON ur.user_company_id = n.uc_id
JOIN role r ON r.id = ur.role_id
GROUP BY n.employee_code, n.email ORDER BY n.employee_code;

COMMIT;
