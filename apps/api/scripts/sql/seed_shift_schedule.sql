-- Demo weekly shift schedule for the company that varunmsaji01@gmail.com belongs to:
--   * an Evening shift (14:00-22:30) with a published version,
--   * per-shift coverage targets (shift.min_staff), Night shift flagged as a night shift,
--   * published roster entries for every live employee from this week's Monday for 4 weeks
--     (General Mon-Fri, other shifts Mon-Sat, Sunday off; ~8 people rotated onto Evening;
--     one Morning-shift Saturday deliberately under target),
--   * two pending shift-swap requests.
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_shift_schedule.sql
--
-- Idempotent: roster rows it creates carry reason 'demo_seed:schedule' and are replaced on re-run;
-- existing roster entries (any other reason) are never touched. Local development only.

BEGIN;

CREATE TEMP TABLE _ctx ON COMMIT DROP AS
SELECT uc.company_id, u.id AS admin_user_id
FROM "user" u JOIN user_company uc ON uc.user_id = u.id
WHERE lower(u.email) = 'varunmsaji01@gmail.com'
ORDER BY uc.company_id LIMIT 1;

DO $$ BEGIN
  IF (SELECT count(*) FROM _ctx) <> 1 THEN RAISE EXCEPTION 'company for varunmsaji01@gmail.com not found'; END IF;
END $$;

-- ---- clean previous run -----------------------------------------------------------------------
DELETE FROM shift_swap_request
WHERE company_id = (SELECT company_id FROM _ctx) AND reference IN ('SW-208', 'SW-209');
DELETE FROM shift_roster WHERE company_id = (SELECT company_id FROM _ctx)
  AND (reason = 'demo_seed:schedule' OR reason IN ('Shift swap SW-208', 'Shift swap SW-209'));

-- ---- Evening shift ----------------------------------------------------------------------------
INSERT INTO shift (id, company_id, name, code, start_time, end_time, is_active)
SELECT gen_random_uuid(), company_id, 'Evening Shift', 'EVE', '14:00', '22:30', true FROM _ctx
WHERE NOT EXISTS (SELECT 1 FROM shift WHERE company_id = (SELECT company_id FROM _ctx) AND code = 'EVE' AND deleted_at IS NULL);

INSERT INTO shift_version (id, company_id, shift_id, status, version, effective_from, shift_type, timezone,
                           start_time, end_time, scheduled_minutes, is_night_shift, is_cross_midnight,
                           is_ot_eligible, publish_reason, published_at, published_by)
SELECT gen_random_uuid(), s.company_id, s.id, 'PUBLISHED', 1, date '2026-01-01', 'FIXED', 'Asia/Kolkata',
       '14:00', '22:30', 510, false, false, true, 'Initial (demo seed)', now(), (SELECT admin_user_id FROM _ctx)
FROM shift s
WHERE s.company_id = (SELECT company_id FROM _ctx) AND s.code = 'EVE' AND s.deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM shift_version v WHERE v.shift_id = s.id);

-- ---- coverage targets + night flag -------------------------------------------------------------
UPDATE shift SET min_staff = CASE code WHEN 'GEN' THEN 36 WHEN 'MOR' THEN 6 WHEN 'EVE' THEN 6 WHEN 'NGT' THEN 4 END,
                 is_night_shift = (code = 'NGT' OR is_night_shift)
WHERE company_id = (SELECT company_id FROM _ctx) AND code IN ('GEN', 'MOR', 'EVE', 'NGT');

-- ---- roster -------------------------------------------------------------------------------------
-- Each live employee's base shift = their current assignment shift; the 8 lowest-coded General-shift
-- employees are rotated onto Evening for the whole period.
CREATE TEMP TABLE _emp ON COMMIT DROP AS
WITH base AS (
  SELECT e.id AS employee_id, e.employee_code, ea.shift_id, s.code AS shift_code
  FROM employee e
  JOIN employee_assignment ea ON ea.employee_id = e.id AND ea.effective_to IS NULL AND ea.deleted_at IS NULL
  JOIN shift s ON s.id = ea.shift_id
  WHERE e.company_id = (SELECT company_id FROM _ctx) AND e.status IN ('ACTIVE', 'PROBATION', 'ON_NOTICE')
), ranked AS (
  SELECT *, row_number() OVER (PARTITION BY shift_code ORDER BY employee_code DESC) AS rn FROM base
)
SELECT employee_id, employee_code,
       CASE WHEN shift_code = 'GEN' AND rn <= 8
            THEN (SELECT id FROM shift WHERE company_id = (SELECT company_id FROM _ctx) AND code = 'EVE' AND deleted_at IS NULL)
            ELSE shift_id END AS shift_id,
       CASE WHEN shift_code = 'GEN' AND rn <= 8 THEN 'EVE' ELSE shift_code END AS shift_code,
       row_number() OVER (PARTITION BY (CASE WHEN shift_code = 'GEN' AND rn <= 8 THEN 'EVE' ELSE shift_code END)
                          ORDER BY employee_code) AS pos
FROM ranked;

INSERT INTO shift_roster (id, company_id, employee_id, roster_date, shift_id, is_week_off_override,
                          is_holiday_working_override, status, reason, created_by, updated_by)
SELECT gen_random_uuid(), (SELECT company_id FROM _ctx), m.employee_id, d::date,
       CASE WHEN off THEN NULL ELSE m.shift_id END, off, false, 'PUBLISHED', 'demo_seed:schedule',
       (SELECT admin_user_id FROM _ctx), (SELECT admin_user_id FROM _ctx)
FROM _emp m
CROSS JOIN generate_series(date_trunc('week', current_date)::date, (date_trunc('week', current_date) + interval '27 days')::date, interval '1 day') d
CROSS JOIN LATERAL (SELECT
    CASE WHEN extract(isodow FROM d) = 7 THEN true                                   -- Sunday off for everyone
         WHEN extract(isodow FROM d) = 6 AND m.shift_code = 'GEN' THEN true         -- General: Saturday off too
         -- one Morning-shift Saturday under target: 3 of the 8 morning staff have the day off
         WHEN extract(isodow FROM d) = 6 AND m.shift_code = 'MOR' AND m.pos <= 3
              AND d::date = (date_trunc('week', current_date) + interval '12 days')::date THEN true
         ELSE false END AS off) o
WHERE NOT EXISTS (
  SELECT 1 FROM shift_roster r
  WHERE r.company_id = (SELECT company_id FROM _ctx) AND r.employee_id = m.employee_id
    AND r.roster_date = d::date AND r.deleted_at IS NULL
);

-- ---- pending shift swaps ------------------------------------------------------------------------
-- Two peer swaps on the first Wednesday/Thursday that has both people on different shifts.
WITH pairs AS (
  SELECT a.employee_id AS a_emp, b.employee_id AS b_emp, ra.roster_date, ra.shift_id AS a_shift, rb.shift_id AS b_shift,
         row_number() OVER (ORDER BY ra.roster_date, a.employee_code) AS n
  FROM _emp a
  JOIN _emp b ON b.shift_code = 'GEN' AND a.shift_code = 'EVE'
  JOIN shift_roster ra ON ra.employee_id = a.employee_id AND ra.deleted_at IS NULL AND ra.reason = 'demo_seed:schedule'
  JOIN shift_roster rb ON rb.employee_id = b.employee_id AND rb.roster_date = ra.roster_date
                      AND rb.deleted_at IS NULL AND rb.reason = 'demo_seed:schedule'
  WHERE ra.roster_date > current_date AND ra.shift_id IS NOT NULL AND rb.shift_id IS NOT NULL
    AND a.pos = 1 + (extract(isodow FROM ra.roster_date)::int % 3)
    AND b.pos = 1 + (extract(isodow FROM ra.roster_date)::int % 3)
    AND extract(isodow FROM ra.roster_date) IN (3, 4)
), picked AS (SELECT * FROM pairs WHERE n <= 2)
INSERT INTO shift_swap_request (company_id, reference, swap_date, requester_employee_id, counterpart_employee_id,
                                requester_shift_id, counterpart_shift_id, reason, status, counterpart_consented)
SELECT (SELECT company_id FROM _ctx), 'SW-' || (207 + n), roster_date, a_emp, b_emp, a_shift, b_shift,
       CASE n WHEN 1 THEN 'Family travel commitment; counterpart agreed to cover the evening queue.'
              ELSE 'Client release support scheduled early that morning.' END,
       'PENDING', n = 1
FROM picked
ON CONFLICT DO NOTHING;

COMMIT;
