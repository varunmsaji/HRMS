-- Mock employee profile details for the company behind varunmsaji@gmail.com (Varun Company), LOCAL DEV
-- ONLY: dependents (PF / gratuity nominees), education, previous employment and the branches an
-- employee may punch from, so the employee profile tabs are not empty.
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_company_mock_profiles.sql
--
-- Idempotent: every row has a deterministic id derived from the employee, so a re-run inserts
-- nothing twice, and it never touches a row it did not write. Employee documents are NOT seeded:
-- each needs a stored file, and a row without one would give a broken download.
--
-- Shape (deterministic per employee): a spouse for about two in three people, up to two children
-- (minors, with the employee as guardian), sometimes a parent; the first dependent is the PF and
-- gratuity nominee at 100%; one to three qualifications; up to three earlier employers that end
-- before the joining date; authorization for the assignment's branch.

BEGIN;

CREATE TEMP TABLE _co ON COMMIT DROP AS
SELECT DISTINCT uc.company_id
FROM "user" u JOIN user_company uc ON uc.user_id = u.id
WHERE u.email = 'varunmsaji@gmail.com';

DO $$ BEGIN
  IF (SELECT count(*) FROM _co) <> 1 THEN
    RAISE EXCEPTION 'varunmsaji@gmail.com is not linked to exactly one company';
  END IF;
END $$;

CREATE TEMP TABLE _emp ON COMMIT DROP AS
SELECT e.id, e.company_id, e.first_name, e.last_name, e.date_of_birth, e.gender,
       (row_number() OVER (ORDER BY e.employee_code))::int AS n,
       (SELECT min(em.joining_date) FROM employment em WHERE em.employee_id = e.id) AS joined
FROM employee e JOIN _co ON _co.company_id = e.company_id
WHERE e.deleted_at IS NULL;

-- ---- dependents ------------------------------------------------------------------------------
-- slot 1 spouse (n mod 3 <> 0), slot 2 and 3 children (n mod 2 = 0 / n mod 5 = 0), slot 4 parent.
WITH slots AS (
  SELECT e.*, s.slot FROM _emp e CROSS JOIN (VALUES (1),(2),(3),(4)) AS s(slot)
  WHERE (s.slot = 1 AND e.n % 3 <> 0) OR (s.slot = 2 AND e.n % 2 = 0)
     OR (s.slot = 3 AND e.n % 5 = 0) OR (s.slot = 4 AND e.n % 4 = 1)
), shaped AS (
  SELECT s.*,
    CASE slot WHEN 1 THEN 'SPOUSE' WHEN 4 THEN 'PARENT' ELSE 'CHILD' END AS rel,
    (ARRAY['Anita','Kavya','Divya','Pooja','Neha','Swati','Rekha','Lakshmi'])[1 + (n + slot) % 8] AS f_name,
    (ARRAY['Rohan','Aarav','Vihaan','Kabir','Ishaan','Arnav','Vivaan','Reyansh'])[1 + (n + slot) % 8] AS m_name
  FROM slots s
)
INSERT INTO employee_dependent (
  id, company_id, employee_id, full_name, relationship, date_of_birth, gender, is_minor,
  guardian_name, guardian_relationship, is_pf_nominee, pf_nominee_share_percentage,
  is_gratuity_nominee, gratuity_nominee_share_percentage, is_esi_dependent,
  created_at, updated_at, version)
SELECT
  md5('mock-profile:dep:' || id || ':' || slot)::uuid, company_id, id,
  CASE rel
    WHEN 'SPOUSE' THEN CASE WHEN gender = 'Male' THEN f_name ELSE m_name END || ' ' || last_name
    WHEN 'PARENT' THEN CASE WHEN n % 2 = 0 THEN 'Suresh' ELSE 'Savitri' END || ' ' || last_name
    ELSE CASE WHEN slot = 2 THEN m_name ELSE f_name END || ' ' || last_name END,
  rel,
  CASE rel
    WHEN 'SPOUSE' THEN date_of_birth + ((n % 5) - 2) * 300
    WHEN 'PARENT' THEN date_of_birth - (9000 + n * 40)
    ELSE DATE '2026-11-21' - (900 + slot * 700 + n * 31) END,
  CASE rel WHEN 'SPOUSE' THEN CASE WHEN gender = 'Male' THEN 'Female' ELSE 'Male' END
           WHEN 'PARENT' THEN CASE WHEN n % 2 = 0 THEN 'Male' ELSE 'Female' END
           ELSE CASE WHEN slot = 2 THEN 'Male' ELSE 'Female' END END,
  rel = 'CHILD',
  CASE WHEN rel = 'CHILD' THEN first_name || ' ' || last_name END,
  CASE WHEN rel = 'CHILD' THEN 'Parent' END,
  -- the first dependent a person has is the PF and gratuity nominee at 100%
  slot = (SELECT min(s2.slot) FROM slots s2 WHERE s2.id = shaped.id),
  CASE WHEN slot = (SELECT min(s2.slot) FROM slots s2 WHERE s2.id = shaped.id) THEN 100 END,
  slot = (SELECT min(s2.slot) FROM slots s2 WHERE s2.id = shaped.id),
  CASE WHEN slot = (SELECT min(s2.slot) FROM slots s2 WHERE s2.id = shaped.id) THEN 100 END,
  rel IN ('SPOUSE', 'CHILD') AND n % 4 = 0,
  now(), now(), 1
FROM shaped
ON CONFLICT (id) DO NOTHING;

-- ---- education -------------------------------------------------------------------------------
INSERT INTO employee_education (
  id, company_id, employee_id, qualification, institution_name, year_of_passing,
  created_at, updated_at, version)
SELECT
  md5('mock-profile:edu:' || e.id || ':' || q.k)::uuid, e.company_id, e.id,
  (ARRAY['Higher Secondary (XII)','B.Com','B.Tech (Computer Science)','BBA','MBA (HR)',
         'B.Sc (Mathematics)','M.Com','MCA'])[1 + (e.n * 3 + q.k * 2) % 8],
  (ARRAY['Delhi Public School','St. Xavier''s College','Anna University','Osmania University',
         'Christ University','Symbiosis Institute','University of Mysore','Pune University'])[1 + (e.n + q.k * 3) % 8],
  extract(year FROM e.date_of_birth)::int + 18 + q.k * 3 + (e.n % 2),
  now(), now(), 1
FROM _emp e CROSS JOIN generate_series(1, 3) AS q(k)
WHERE q.k <= 1 + e.n % 3
ON CONFLICT (id) DO NOTHING;

-- ---- previous employment ---------------------------------------------------------------------
INSERT INTO employee_experience (
  id, company_id, employee_id, company_name, designation, from_date, to_date, last_ctc_minor,
  reason_for_leaving, had_prior_pf_membership, created_at, updated_at, version)
SELECT
  md5('mock-profile:exp:' || e.id || ':' || x.k)::uuid, e.company_id, e.id,
  (ARRAY['Infosys','Wipro','TCS','HCL Technologies','Tech Mahindra','Cognizant','Capgemini',
         'Mindtree','Zensar','Mphasis'])[1 + (e.n * 2 + x.k * 3) % 10],
  (ARRAY['Associate','Software Engineer','Analyst','Senior Associate','Executive',
         'Team Lead'])[1 + (e.n + x.k) % 6],
  (e.joined - ((x.k * 900) + 120 + e.n * 17))::date,
  (e.joined - (((x.k - 1) * 900) + 30 + e.n * 3))::date,
  (450000 + 250000 * (4 - x.k) + e.n * 20000)::bigint * 100,
  (ARRAY['Better opportunity','Career growth','Relocation','Higher studies','Role change'])[1 + (e.n + x.k) % 5],
  true, now(), now(), 1
FROM _emp e CROSS JOIN generate_series(1, 3) AS x(k)
WHERE x.k <= e.n % 4 AND e.joined IS NOT NULL
ON CONFLICT (id) DO NOTHING;

-- ---- branches an employee may punch from -----------------------------------------------------
INSERT INTO employee_workplace_authorization (id, company_id, employee_id, branch_id, created_at)
SELECT md5('mock-profile:wpa:' || a.employee_id || ':' || a.branch_id)::uuid, a.company_id,
       a.employee_id, a.branch_id, now()
FROM employee_assignment a JOIN _emp e ON e.id = a.employee_id
WHERE a.effective_to IS NULL AND a.branch_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM employee_workplace_authorization w
                  WHERE w.employee_id = a.employee_id AND w.branch_id = a.branch_id)
ON CONFLICT (id) DO NOTHING;

SELECT 'dependents' AS what, count(*) FROM employee_dependent WHERE company_id = (SELECT company_id FROM _co)
UNION ALL SELECT 'education', count(*) FROM employee_education WHERE company_id = (SELECT company_id FROM _co)
UNION ALL SELECT 'experience', count(*) FROM employee_experience WHERE company_id = (SELECT company_id FROM _co)
UNION ALL SELECT 'workplace authorizations', count(*) FROM employee_workplace_authorization WHERE company_id = (SELECT company_id FROM _co);

COMMIT;
