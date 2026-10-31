-- Demo data behind the employee mobile Home screen, for varunmsaji01@gmail.com (EMP-VARUN01).
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_employee_home_demo.sql
--
-- Idempotent: every row it writes is tagged (reason / reference 'demo-home-seed') and removed
-- first. Relative to current_date so Home always has a recent month of history:
--   * attendance: punches + day rows for the last 30 days (Mon-Fri working, one missing punch)
--   * leave: opening balances, past approved leave, one approved upcoming, one awaiting approval
--   * corrections: one missing-punch request awaiting approval

BEGIN;

CREATE TEMP TABLE _ctx ON COMMIT DROP AS
SELECT e.id AS employee_id, e.company_id, u.id AS user_id,
       a.shift_id, sv.id AS shift_version_id, sv.start_time, sv.end_time,
       'Asia/Kolkata'::text AS tz
FROM "user" u
JOIN employee e ON e.user_id = u.id
JOIN employee_assignment a ON a.employee_id = e.id AND a.effective_to IS NULL
JOIN shift_version sv ON sv.shift_id = a.shift_id
WHERE u.email = 'varunmsaji01@gmail.com' AND e.employee_code = 'EMP-VARUN01'
ORDER BY sv.version DESC
LIMIT 1;

DO $$ BEGIN
  IF (SELECT count(*) FROM _ctx) <> 1 THEN
    RAISE EXCEPTION 'EMP-VARUN01 for varunmsaji01@gmail.com with an assigned shift not found';
  END IF;
END $$;

-- ---- clean previous run -------------------------------------------------------------------
DELETE FROM attendance_regularization_requested_punch WHERE request_id IN
  (SELECT id FROM attendance_regularization_request WHERE reason = 'demo-home-seed' AND employee_id = (SELECT employee_id FROM _ctx));
DELETE FROM attendance_regularization_request WHERE reason = 'demo-home-seed' AND employee_id = (SELECT employee_id FROM _ctx);
DELETE FROM leave_ledger WHERE employee_id = (SELECT employee_id FROM _ctx) AND reason LIKE 'demo-home-seed%';
DELETE FROM leave_day_projection WHERE leave_application_id IN
  (SELECT id FROM leave_application WHERE reason = 'demo-home-seed' AND employee_id = (SELECT employee_id FROM _ctx));
DELETE FROM leave_application_day WHERE leave_application_id IN
  (SELECT id FROM leave_application WHERE reason = 'demo-home-seed' AND employee_id = (SELECT employee_id FROM _ctx));
DELETE FROM leave_application WHERE reason = 'demo-home-seed' AND employee_id = (SELECT employee_id FROM _ctx);
DELETE FROM attendance_day WHERE employee_id = (SELECT employee_id FROM _ctx) AND computation_snapshot @> '{"demo_home_seed": true}';
DELETE FROM punch WHERE employee_id = (SELECT employee_id FROM _ctx) AND reference = 'demo-home-seed';

-- ---- attendance: last 30 days --------------------------------------------------------------
-- Deterministic per-day variation: arrival 09:05-09:40 local, leave 18:30-19:10.
CREATE TEMP TABLE _days ON COMMIT DROP AS
SELECT d::date AS day,
       extract(isodow FROM d) >= 6 AS weekend,
       (extract(doy FROM d)::int % 7) AS k
FROM generate_series(current_date - 30, current_date - 1, interval '1 day') AS d;

-- The day 8 days back (a weekday if possible) is the "missing punch" the correction refers to.
CREATE TEMP TABLE _missing ON COMMIT DROP AS
SELECT max(day) AS day FROM _days WHERE NOT weekend AND day <= current_date - 7;

CREATE TEMP TABLE _p ON COMMIT DROP AS
SELECT c.employee_id, c.company_id, d.day,
       ((d.day + c.start_time) AT TIME ZONE c.tz) + make_interval(mins => d.k * 6 - 25) AS t_in,
       ((d.day + c.end_time)   AT TIME ZONE c.tz) + make_interval(mins => (d.k % 4) * 10) AS t_out,
       (d.day = m.day) AS missing
FROM _days d CROSS JOIN _ctx c CROSS JOIN _missing m
WHERE NOT d.weekend;

INSERT INTO punch (company_id, employee_id, punch_time, direction, source, reference)
SELECT company_id, employee_id, t_in, 'IN', 'MOBILE', 'demo-home-seed' FROM _p
UNION ALL
SELECT company_id, employee_id, t_out, 'OUT', 'MOBILE', 'demo-home-seed' FROM _p WHERE NOT missing;

INSERT INTO attendance_day (
  company_id, employee_id, attendance_date, timezone, shift_id, shift_version_id, work_calendar_id,
  attendance_policy_version_id, overtime_policy_version_id, regularization_policy_version_id,
  calendar_day_type, scheduled_start, scheduled_end, scheduled_minutes,
  actual_first_in, actual_last_out, worked_minutes, attendance_status,
  late_minutes, is_late, missing_punch, paid_day_fraction, lop_fraction,
  calculation_version, engine_version, calculated_at, computation_snapshot)
SELECT c.company_id, c.employee_id, p.day, c.tz, c.shift_id, c.shift_version_id,
       'd52a23e4-f694-4e04-bb91-ba41924b97fc', '4da18185-b598-467f-af24-23d26afb88f5',
       '4f8f1daa-9d6a-4b7f-9887-66b474643185', '59a378db-3efb-45c5-81b8-d8c06b055910',
       'WORKING', (p.day + c.start_time) AT TIME ZONE c.tz, (p.day + c.end_time) AT TIME ZONE c.tz,
       extract(epoch FROM (c.end_time - c.start_time))::int / 60,
       p.t_in, CASE WHEN p.missing THEN NULL ELSE p.t_out END,
       CASE WHEN p.missing THEN 0 ELSE (extract(epoch FROM (p.t_out - p.t_in)) / 60)::int END,
       CASE WHEN p.missing THEN 'INCOMPLETE' ELSE 'PRESENT' END,
       greatest(0, (extract(epoch FROM (p.t_in - ((p.day + c.start_time) AT TIME ZONE c.tz))) / 60)::int - 15),
       (extract(epoch FROM (p.t_in - ((p.day + c.start_time) AT TIME ZONE c.tz))) / 60) > 15,
       p.missing, CASE WHEN p.missing THEN 0 ELSE 1 END, 0,
       1, 2, now(), '{"demo_home_seed": true}'::jsonb
FROM _p p CROSS JOIN _ctx c
ON CONFLICT DO NOTHING;

INSERT INTO attendance_day (
  company_id, employee_id, attendance_date, timezone, shift_id, shift_version_id, work_calendar_id,
  calendar_day_type, attendance_status, weekly_off_fraction, calculation_version, engine_version,
  calculated_at, computation_snapshot)
SELECT c.company_id, c.employee_id, d.day, c.tz, c.shift_id, c.shift_version_id,
       'd52a23e4-f694-4e04-bb91-ba41924b97fc', 'WEEKLY_OFF', 'NOT_EXPECTED', 1, 1, 2, now(),
       '{"demo_home_seed": true}'::jsonb
FROM _days d CROSS JOIN _ctx c WHERE d.weekend
ON CONFLICT DO NOTHING;

-- ---- leave ----------------------------------------------------------------------------------
-- Opening balances for the leave year (Casual 7, Sick 10, Earned 18), then what was taken.
CREATE TEMP TABLE _lt ON COMMIT DROP AS
SELECT lt.id AS leave_type_id, lt.code, v.id AS policy_version_id
FROM leave_type lt
JOIN leave_policy lp ON lp.leave_type_id = lt.id AND lp.company_id = lt.company_id
JOIN leave_policy_version v ON v.policy_id = lp.id AND v.effective_to IS NULL
WHERE lt.company_id = (SELECT company_id FROM _ctx) AND lt.code IN ('CL', 'SL', 'EL');

INSERT INTO leave_ledger (company_id, employee_id, leave_type_id, entry_type, amount, effective_date, reason, created_by_user_id)
SELECT c.company_id, c.employee_id, l.leave_type_id, 'ADJUSTMENT',
       CASE l.code WHEN 'CL' THEN 7 WHEN 'SL' THEN 10 ELSE 18 END,
       date_trunc('year', current_date)::date, 'demo-home-seed: opening balance', c.user_id
FROM _ctx c CROSS JOIN _lt l;

-- (code, start, end, days, status, approval hours ago, decided-on note)
CREATE TEMP TABLE _apps ON COMMIT DROP AS
SELECT gen_random_uuid() AS id, * FROM (VALUES
  ('EL', current_date - 40, current_date - 38, 3, 'APPROVED',  24 * 41),
  ('SL', current_date - 20, current_date - 20, 1, 'APPROVED',  24 * 20),
  ('CL', current_date - 9,  current_date - 9,  0.5, 'APPROVED', 24 * 10),
  ('EL', current_date + 12, current_date + 14, 3, 'APPROVED',  18),       -- the banner
  ('CL', current_date + 21, current_date + 22, 2, 'SUBMITTED', NULL)      -- awaiting approval
) AS t(code, s, e, days, status, decided_hours_ago);

INSERT INTO leave_application (
  id, company_id, employee_id, leave_type_id, leave_policy_version_id, start_date, end_date, total_days,
  reason, status, approval_chain, approval_stage, submitted_by_user_id, submitted_at,
  reviewed_by_user_id, reviewed_at, reviewer_comment)
SELECT a.id, c.company_id, c.employee_id, l.leave_type_id, l.policy_version_id, a.s, a.e, a.days,
       'demo-home-seed', a.status, 'HR', CASE WHEN a.status = 'SUBMITTED' THEN 'HR' END, c.user_id,
       now() - make_interval(hours => coalesce(a.decided_hours_ago, 0) + 30),
       CASE WHEN a.status = 'APPROVED' THEN c.user_id END,
       CASE WHEN a.status = 'APPROVED' THEN now() - make_interval(hours => a.decided_hours_ago) END,
       CASE WHEN a.status = 'APPROVED' THEN 'Approved' END
FROM _apps a CROSS JOIN _ctx c JOIN _lt l ON l.code = a.code;

-- Approved leave is debited; a submitted request only reserves (the balance API derives that).
INSERT INTO leave_ledger (company_id, employee_id, leave_type_id, entry_type, amount, effective_date, reference_id, reason, created_by_user_id)
SELECT c.company_id, c.employee_id, l.leave_type_id, 'APPLICATION', -a.days, a.s, a.id,
       'demo-home-seed: leave application ' || a.s || ' to ' || a.e, c.user_id
FROM _apps a CROSS JOIN _ctx c JOIN _lt l ON l.code = a.code
WHERE a.status = 'APPROVED';

INSERT INTO leave_application_day (company_id, leave_application_id, calendar_date, fraction, half)
SELECT c.company_id, a.id, d::date, CASE WHEN a.days < 1 THEN a.days ELSE 1 END,
       CASE WHEN a.days < 1 THEN 'FIRST' END
FROM _apps a CROSS JOIN _ctx c
CROSS JOIN LATERAL generate_series(a.s, a.e, interval '1 day') AS d
WHERE extract(isodow FROM d) < 6;

-- ---- attendance correction awaiting approval ------------------------------------------------
WITH req AS (
  INSERT INTO attendance_regularization_request (
    company_id, employee_id, attendance_day_id, attendance_date, request_type, reason, status,
    approval_chain, approval_stage, regularization_policy_version_id, submitted_by_user_id, submitted_at)
  SELECT c.company_id, c.employee_id,
         (SELECT id FROM attendance_day ad WHERE ad.employee_id = c.employee_id AND ad.attendance_date = m.day),
         m.day, 'MISSING_PUNCH', 'demo-home-seed', 'SUBMITTED', 'HR', 'HR',
         '59a378db-3efb-45c5-81b8-d8c06b055910', c.user_id, now() - interval '6 hours'
  FROM _ctx c CROSS JOIN _missing m
  RETURNING id, company_id, attendance_date
)
INSERT INTO attendance_regularization_requested_punch (company_id, request_id, direction, requested_time)
SELECT r.company_id, r.id, 'OUT', ((r.attendance_date + c.end_time) AT TIME ZONE c.tz)
FROM req r CROSS JOIN _ctx c;

COMMIT;
