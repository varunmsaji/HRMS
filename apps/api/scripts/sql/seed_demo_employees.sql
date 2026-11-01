-- Demo workforce for the company that varunmsaji01@gmail.com belongs to: 20 new employees with
-- employment, assignment, leave balances, leave applications, 30 days of attendance and
-- attendance-regularization requests, in a realistic status mix.
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_demo_employees.sql
--
-- Idempotent and additive: every employee is tagged custom_fields {"demo_seed": "demo-20-employees"}
-- with code DEMO-001..DEMO-020, and every row hanging off them is removed first on a re-run. Existing
-- employees are never touched. Dates are relative to current_date so the data always looks recent.
-- Names, emails and reasons are invented; the emails use the reserved example.com domain.

BEGIN;

-- ---- context ---------------------------------------------------------------------------------
CREATE TEMP TABLE _ctx ON COMMIT DROP AS
SELECT uc.company_id, u.id AS admin_user_id, coalesce(c.timezone, 'Asia/Kolkata') AS tz,
       (SELECT id FROM legal_entity le WHERE le.company_id = uc.company_id ORDER BY created_at LIMIT 1) AS legal_entity_id
FROM "user" u
JOIN user_company uc ON uc.user_id = u.id
JOIN company c ON c.id = uc.company_id
WHERE lower(u.email) = 'varunmsaji01@gmail.com'
ORDER BY uc.company_id
LIMIT 1;

DO $$ BEGIN
  IF (SELECT count(*) FROM _ctx) <> 1 OR (SELECT legal_entity_id FROM _ctx) IS NULL THEN
    RAISE EXCEPTION 'company or legal entity for varunmsaji01@gmail.com not found';
  END IF;
END $$;

-- Calendar / policy versions the attendance engine stamped on this company's existing days.
CREATE TEMP TABLE _pol ON COMMIT DROP AS
SELECT work_calendar_id, attendance_policy_version_id, overtime_policy_version_id, regularization_policy_version_id
FROM attendance_day
WHERE company_id = (SELECT company_id FROM _ctx)
  AND work_calendar_id IS NOT NULL AND attendance_policy_version_id IS NOT NULL
  AND regularization_policy_version_id IS NOT NULL
ORDER BY attendance_date DESC
LIMIT 1;

DO $$ BEGIN
  IF (SELECT count(*) FROM _pol) <> 1 THEN
    RAISE EXCEPTION 'no existing attendance day to copy calendar/policy versions from';
  END IF;
END $$;

-- ---- clean previous run ----------------------------------------------------------------------
CREATE TEMP TABLE _old ON COMMIT DROP AS
SELECT id FROM employee
WHERE company_id = (SELECT company_id FROM _ctx) AND custom_fields->>'demo_seed' = 'demo-20-employees';

DELETE FROM attendance_regularization_requested_punch WHERE request_id IN
  (SELECT id FROM attendance_regularization_request WHERE employee_id IN (SELECT id FROM _old));
DELETE FROM attendance_regularization_action WHERE request_id IN
  (SELECT id FROM attendance_regularization_request WHERE employee_id IN (SELECT id FROM _old));
UPDATE attendance_day SET is_regularized = false WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM attendance_regularization_request WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM leave_day_projection WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM leave_application_action WHERE leave_application_id IN
  (SELECT id FROM leave_application WHERE employee_id IN (SELECT id FROM _old));
DELETE FROM leave_application_day WHERE leave_application_id IN
  (SELECT id FROM leave_application WHERE employee_id IN (SELECT id FROM _old));
DELETE FROM leave_application WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM leave_ledger WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM attendance_day WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM punch WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM employee_assignment WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM employment WHERE employee_id IN (SELECT id FROM _old);
DELETE FROM employee WHERE id IN (SELECT id FROM _old);

-- ---- the 20 people ---------------------------------------------------------------------------
-- (n, first, last, gender, department, designation, branch, shift, joined, status)
CREATE TEMP TABLE _people ON COMMIT DROP AS
SELECT gen_random_uuid() AS id, v.*
FROM (VALUES
  (1,  'Arjun',    'Nair',      'Male',   'Engineering',      'Engineering Manager',      'Bengaluru HQ',   'General Shift', DATE '2020-06-01', 'ACTIVE'),
  (2,  'Meera',    'Pillai',    'Female', 'Human Resources',  'HR Manager',               'Bengaluru HQ',   'General Shift', DATE '2019-03-11', 'ACTIVE'),
  (3,  'Karthik',  'Reddy',     'Male',   'Finance',          'Finance Manager',          'Mumbai Office',  'General Shift', DATE '2021-01-18', 'ACTIVE'),
  (4,  'Sanjana',  'Kapoor',    'Female', 'Sales',            'Sales Manager',            'Mumbai Office',  'General Shift', DATE '2020-09-07', 'ACTIVE'),
  (5,  'Vikram',   'Rao',       'Male',   'Operations',       'Operations Manager',       'Chennai Office', 'Morning Shift', DATE '2018-11-05', 'ACTIVE'),
  (6,  'Divya',    'Menon',     'Female', 'Customer Support', 'Support Lead',             'Chennai Office', 'General Shift', DATE '2021-07-12', 'ACTIVE'),
  (7,  'Rahul',    'Verma',     'Male',   'Engineering',      'Senior Software Engineer', 'Bengaluru HQ',   'General Shift', DATE '2021-10-04', 'ACTIVE'),
  (8,  'Ananya',   'Iyer',      'Female', 'Engineering',      'Software Engineer',        'Bengaluru HQ',   'General Shift', DATE '2023-02-13', 'ACTIVE'),
  (9,  'Rohit',    'Joshi',     'Male',   'Engineering',      'Software Engineer',        'Bengaluru HQ',   'General Shift', DATE '2024-05-20', 'ACTIVE'),
  (10, 'Pooja',    'Desai',     'Female', 'Engineering',      'Software Engineer',        'Bengaluru HQ',   'General Shift', current_date - 50,  'PROBATION'),
  (11, 'Nisha',    'Agarwal',   'Female', 'Human Resources',  'HR Executive',             'Bengaluru HQ',   'General Shift', DATE '2022-04-25', 'ACTIVE'),
  (12, 'Suresh',   'Babu',      'Male',   'Finance',          'Accountant',               'Mumbai Office',  'General Shift', DATE '2022-08-01', 'ACTIVE'),
  (13, 'Kavya',    'Shetty',    'Female', 'Sales',            'Senior Sales Executive',   'Mumbai Office',  'General Shift', DATE '2022-01-10', 'ACTIVE'),
  (14, 'Imran',    'Sheikh',    'Male',   'Sales',            'Sales Executive',          'Mumbai Office',  'General Shift', DATE '2024-02-05', 'ACTIVE'),
  (15, 'Lakshmi',  'Narayan',   'Female', 'Sales',            'Sales Executive',          'Mumbai Office',  'General Shift', current_date - 35,  'PROBATION'),
  (16, 'Manoj',    'Kumar',     'Male',   'Operations',       'Operations Lead',          'Chennai Office', 'Morning Shift', DATE '2020-12-14', 'ACTIVE'),
  (17, 'Farah',    'Khan',      'Female', 'Operations',       'Operations Executive',     'Chennai Office', 'Night Shift',   DATE '2023-06-19', 'ACTIVE'),
  (18, 'Deepak',   'Singh',     'Male',   'Operations',       'Operations Executive',     'Chennai Office', 'Morning Shift', DATE '2024-09-02', 'ON_NOTICE'),
  (19, 'Tara',     'Bose',      'Female', 'Customer Support', 'Support Associate',        'Chennai Office', 'General Shift', DATE '2023-11-27', 'ACTIVE'),
  (20, 'Naveen',   'Chandra',   'Male',   'Customer Support', 'Support Associate',        'Bengaluru HQ',   'General Shift', DATE '2025-03-17', 'ACTIVE')
) AS v(n, first_name, last_name, gender, dept, title, branch, shift, joined, status);

CREATE TEMP TABLE _emp ON COMMIT DROP AS
SELECT p.*, 'DEMO-' || lpad(p.n::text, 3, '0') AS code,
       d.id AS department_id, g.id AS designation_id, b.id AS branch_id, s.id AS shift_id,
       sv.id AS shift_version_id, sv.start_time, sv.end_time
FROM _people p
JOIN department d ON d.company_id = (SELECT company_id FROM _ctx) AND d.name = p.dept
JOIN designation g ON g.company_id = (SELECT company_id FROM _ctx) AND g.title = p.title
JOIN branch b ON b.company_id = (SELECT company_id FROM _ctx) AND b.name = p.branch
JOIN shift s ON s.company_id = (SELECT company_id FROM _ctx) AND s.name = p.shift
JOIN LATERAL (SELECT id, start_time, end_time FROM shift_version WHERE shift_id = s.id
              ORDER BY version DESC LIMIT 1) sv ON true;

DO $$ BEGIN
  IF (SELECT count(*) FROM _emp) <> 20 THEN
    RAISE EXCEPTION 'expected 20 people to resolve against departments/designations/branches/shifts, got %',
      (SELECT count(*) FROM _emp);
  END IF;
END $$;

INSERT INTO employee (id, company_id, employee_code, first_name, last_name, display_name, gender, date_of_birth,
                      nationality, personal_email, personal_mobile, status, is_active, custom_fields,
                      created_at, updated_at, version)
SELECT e.id, (SELECT company_id FROM _ctx), e.code, e.first_name, e.last_name, e.first_name || ' ' || e.last_name,
       e.gender, DATE '1986-01-15' + (e.n * 211), 'Indian',
       lower(e.first_name || '.' || e.last_name) || '.demo@example.com',
       '+91 98' || lpad((45000000 + e.n * 137)::text, 8, '0'),
       e.status, true, '{"demo_seed": "demo-20-employees"}'::jsonb, now(), now(), 1
FROM _emp e;

INSERT INTO employment (company_id, employee_id, legal_entity_id, joining_date, status, pay_basis,
                        probation_end_date, created_at, updated_at, version)
SELECT (SELECT company_id FROM _ctx), e.id, (SELECT legal_entity_id FROM _ctx), e.joined, 'ACTIVE', 'MONTHLY',
       CASE WHEN e.status = 'PROBATION' THEN e.joined + 90 END, now(), now(), 1
FROM _emp e;

-- Department heads are n = 1..6 and report to nobody; everyone else reports to their head.
INSERT INTO employee_assignment (company_id, employee_id, department_id, designation_id, branch_id, shift_id,
                                 reporting_manager_id, effective_from, change_type, work_location_type,
                                 created_at, updated_at, version)
SELECT (SELECT company_id FROM _ctx), e.id, e.department_id, e.designation_id, e.branch_id, e.shift_id,
       CASE WHEN e.n <= 6 THEN NULL ELSE
         (SELECT h.id FROM _emp h WHERE h.n <= 6 AND h.dept = e.dept LIMIT 1) END,
       e.joined, 'INITIAL', 'OFFICE', now(), now(), 1
FROM _emp e;

-- ---- leave: opening balances ------------------------------------------------------------------
CREATE TEMP TABLE _lt ON COMMIT DROP AS
SELECT lt.id AS leave_type_id, lt.code, v.id AS policy_version_id
FROM leave_type lt
JOIN leave_policy lp ON lp.leave_type_id = lt.id AND lp.company_id = lt.company_id
JOIN leave_policy_version v ON v.policy_id = lp.id AND v.effective_to IS NULL
WHERE lt.company_id = (SELECT company_id FROM _ctx) AND lt.code IN ('CL', 'SL', 'EL');

DO $$ BEGIN
  IF (SELECT count(*) FROM _lt) <> 3 THEN
    RAISE EXCEPTION 'CL/SL/EL leave types with an open policy version not found';
  END IF;
END $$;

INSERT INTO leave_ledger (company_id, employee_id, leave_type_id, entry_type, amount, effective_date, reason, created_by_user_id)
SELECT (SELECT company_id FROM _ctx), e.id, l.leave_type_id, 'ADJUSTMENT',
       CASE l.code WHEN 'CL' THEN 12 WHEN 'SL' THEN 10 ELSE 18 END,
       date_trunc('year', current_date)::date, 'demo-seed: opening balance', (SELECT admin_user_id FROM _ctx)
FROM _emp e CROSS JOIN _lt l;

-- ---- leave applications -----------------------------------------------------------------------
-- (n, type, start offset, end offset, status, fraction, reason, comment)
CREATE TEMP TABLE _apps0 ON COMMIT DROP AS
SELECT * FROM (VALUES
  -- awaiting approval (two in Engineering overlap, so the decision center shows a clash)
  (7,  'CL', 9,   10,  'SUBMITTED', 1.0, 'Family function',                  NULL),
  (8,  'CL', 9,   9,   'SUBMITTED', 1.0, 'Cousin''s engagement',             NULL),
  (9,  'EL', 14,  18,  'SUBMITTED', 1.0, 'Trip to Coorg',                    NULL),
  (13, 'SL', 1,   1,   'SUBMITTED', 1.0, 'Fever and cold',                   NULL),
  (17, 'EL', 21,  23,  'SUBMITTED', 1.0, 'Wedding in the family',            NULL),
  (19, 'CL', 7,   8,   'SUBMITTED', 1.0, 'Home visit',                       NULL),
  (4,  'EL', 30,  34,  'SUBMITTED', 1.0, 'Annual vacation',                  NULL),
  -- approved: earlier this year
  (1,  'EL', -50, -46, 'APPROVED',  1.0, 'Family vacation',                  'Enjoy the break'),
  (3,  'EL', -60, -56, 'APPROVED',  1.0, 'Pilgrimage',                       NULL),
  (7,  'EL', -45, -41, 'APPROVED',  1.0, 'Travel',                           NULL),
  (16, 'EL', -33, -30, 'APPROVED',  1.0, 'Brother''s wedding',               'Approved'),
  (2,  'CL', -25, -24, 'APPROVED',  1.0, 'Personal work',                    NULL),
  (12, 'CL', -20, -19, 'APPROVED',  1.0, 'House shifting',                   NULL),
  (6,  'SL', -18, -18, 'APPROVED',  1.0, 'Migraine',                         NULL),
  (20, 'CL', -15, -15, 'APPROVED',  1.0, 'Passport appointment',             NULL),
  (8,  'SL', -12, -11, 'APPROVED',  1.0, 'Viral fever',                      'Get well soon'),
  (5,  'CL', -9,  -8,  'APPROVED',  1.0, 'Family function',                  NULL),
  (11, 'CL', -6,  -6,  'APPROVED',  1.0, 'Bank work',                        NULL),
  (10, 'SL', -5,  -5,  'APPROVED',  1.0, 'Dental appointment',               NULL),
  (18, 'SL', -4,  -4,  'APPROVED',  0.5, 'Doctor visit (half day)',          NULL),
  (14, 'SL', -3,  -3,  'APPROVED',  1.0, 'Stomach infection',                NULL),
  -- approved: today and coming up (feeds "on leave today" and the next-7-days cards)
  (11, 'SL', 0,   0,   'APPROVED',  1.0, 'Not well',                         NULL),
  (19, 'CL', 0,   1,   'APPROVED',  1.0, 'Family event',                     NULL),
  (9,  'CL', 3,   4,   'APPROVED',  1.0, 'Long weekend trip',                NULL),
  (16, 'CL', 5,   6,   'APPROVED',  1.0, 'Festival',                         NULL),
  (1,  'CL', 12,  12,  'APPROVED',  1.0, 'Personal',                         NULL),
  -- declined and withdrawn
  (14, 'EL', -28, -26, 'REJECTED',  1.0, 'Short-notice trip',                'Peak sales period, please reschedule'),
  (20, 'CL', -35, -34, 'REJECTED',  1.0, 'Personal',                         'Team coverage not possible those days'),
  (17, 'CL', -10, -10, 'CANCELLED', 1.0, 'Plans changed',                    NULL)
) AS t(n, code, s_off, e_off, status, frac, reason, comment);

-- Only weekdays count; a request that covers none (e.g. a weekend-only range today) is dropped.
CREATE TEMP TABLE _apps ON COMMIT DROP AS
SELECT gen_random_uuid() AS id, a.*, e.id AS employee_id, l.leave_type_id, l.policy_version_id,
       current_date + a.s_off AS s, current_date + a.e_off AS e,
       (SELECT count(*) FROM generate_series(current_date + a.s_off, current_date + a.e_off, interval '1 day') d
         WHERE extract(isodow FROM d) < 6) * a.frac AS days
FROM _apps0 a
JOIN _emp e ON e.n = a.n
JOIN _lt l ON l.code = a.code;

DELETE FROM _apps WHERE days <= 0;

INSERT INTO leave_application (
  id, company_id, employee_id, leave_type_id, leave_policy_version_id, start_date, end_date, total_days, reason,
  status, approval_chain, approval_stage, submitted_by_user_id, submitted_at, reviewed_by_user_id, reviewed_at,
  reviewer_comment, rejection_reason, cancelled_at, cancelled_by_user_id, cancellation_reason)
SELECT a.id, (SELECT company_id FROM _ctx), a.employee_id, a.leave_type_id, a.policy_version_id, a.s, a.e, a.days,
       a.reason, a.status, 'HR', CASE WHEN a.status = 'SUBMITTED' THEN 'HR' END, (SELECT admin_user_id FROM _ctx),
       -- submitted a few days before it starts (pending ones: 1-3 days ago)
       CASE WHEN a.status = 'SUBMITTED' THEN now() - make_interval(hours => 20 + a.n * 5)
            ELSE least(now() - interval '2 hours', (a.s - 3)::timestamptz) END,
       CASE WHEN a.status IN ('APPROVED', 'REJECTED') THEN (SELECT admin_user_id FROM _ctx) END,
       CASE WHEN a.status IN ('APPROVED', 'REJECTED')
            THEN least(now() - interval '1 hour', (a.s - 2)::timestamptz) END,
       CASE WHEN a.status = 'APPROVED' THEN coalesce(a.comment, 'Approved') END,
       CASE WHEN a.status = 'REJECTED' THEN a.comment END,
       CASE WHEN a.status = 'CANCELLED' THEN least(now() - interval '1 hour', (a.s - 1)::timestamptz) END,
       CASE WHEN a.status = 'CANCELLED' THEN (SELECT admin_user_id FROM _ctx) END,
       CASE WHEN a.status = 'CANCELLED' THEN a.comment END
FROM _apps a;

-- Approved leave is debited from the ledger; a submitted request only reserves (derived by the API).
INSERT INTO leave_ledger (company_id, employee_id, leave_type_id, entry_type, amount, effective_date, reference_id, reason, created_by_user_id)
SELECT (SELECT company_id FROM _ctx), a.employee_id, a.leave_type_id, 'APPLICATION', -a.days, a.s, a.id,
       'demo-seed: leave application ' || a.s || ' to ' || a.e, (SELECT admin_user_id FROM _ctx)
FROM _apps a WHERE a.status = 'APPROVED';

INSERT INTO leave_application_day (company_id, leave_application_id, calendar_date, fraction, half)
SELECT (SELECT company_id FROM _ctx), a.id, d::date, a.frac, CASE WHEN a.frac < 1 THEN 'FIRST' END
FROM _apps a
CROSS JOIN LATERAL generate_series(a.s, a.e, interval '1 day') AS d
WHERE extract(isodow FROM d) < 6;

INSERT INTO leave_day_projection (company_id, employee_id, attendance_date, leave_application_id, leave_type_id,
                                  leave_type_code, fraction, half, is_paid, status)
SELECT (SELECT company_id FROM _ctx), a.employee_id, d::date, a.id, a.leave_type_id, a.code, a.frac,
       CASE WHEN a.frac < 1 THEN 'FIRST' END, true, 'APPROVED'
FROM _apps a
CROSS JOIN LATERAL generate_series(a.s, a.e, interval '1 day') AS d
WHERE a.status = 'APPROVED' AND extract(isodow FROM d) < 6;

-- Timeline entries (submitted, then the decision).
INSERT INTO leave_application_action (company_id, leave_application_id, action, actor_user_id, stage, comment, created_at)
SELECT (SELECT company_id FROM _ctx), l.id, 'SUBMITTED', l.submitted_by_user_id, NULL, l.reason, l.submitted_at
FROM leave_application l WHERE l.id IN (SELECT id FROM _apps);

INSERT INTO leave_application_action (company_id, leave_application_id, action, actor_user_id, stage, comment, created_at)
SELECT (SELECT company_id FROM _ctx), l.id, l.status, coalesce(l.reviewed_by_user_id, l.cancelled_by_user_id),
       CASE WHEN l.status IN ('APPROVED', 'REJECTED') THEN 'HR' END,
       coalesce(l.reviewer_comment, l.rejection_reason, l.cancellation_reason),
       coalesce(l.reviewed_at, l.cancelled_at)
FROM leave_application l WHERE l.id IN (SELECT id FROM _apps) AND l.status IN ('APPROVED', 'REJECTED', 'CANCELLED');

-- ---- regularization plan (decides how those particular days look) -------------------------------
-- (n, type, days back, status, reason, review comment). A day landing on a weekend moves to the
-- previous Friday; one that falls inside the person's approved leave is dropped.
CREATE TEMP TABLE _regs0 ON COMMIT DROP AS
SELECT gen_random_uuid() AS id, r.n, r.rtype, r.status, r.reason, r.comment, e.id AS employee_id,
       (current_date - r.back) - CASE extract(isodow FROM current_date - r.back) WHEN 6 THEN 1 WHEN 7 THEN 2 ELSE 0 END AS day
FROM (VALUES
  (7,  'MISSING_PUNCH', 2,  'SUBMITTED', 'Forgot to punch out after a late client call',   NULL),
  (9,  'WRONG_PUNCH',   3,  'SUBMITTED', 'Punched in from home by mistake',                NULL),
  (13, 'MISSING_PUNCH', 1,  'SUBMITTED', 'Biometric was offline when I left',              NULL),
  (17, 'MISSING_PUNCH', 4,  'SUBMITTED', 'Phone battery died before punching out',         NULL),
  (19, 'WRONG_PUNCH',   5,  'SUBMITTED', 'Punch recorded late because the app was stuck',  NULL),
  (11, 'MISSING_PUNCH', 7,  'SUBMITTED', 'Left for a bank visit and forgot to punch out',  NULL),
  (8,  'MISSING_PUNCH', 10, 'APPROVED',  'Forgot to punch out',                            'Verified with manager'),
  (12, 'MISSING_PUNCH', 14, 'APPROVED',  'Network issue while punching out',               'Approved'),
  (14, 'WRONG_PUNCH',   12, 'APPROVED',  'Punched in late by mistake, was on site early',  'Confirmed by team lead'),
  (16, 'MISSING_PUNCH', 16, 'APPROVED',  'Device did not register my exit',                'Approved'),
  (20, 'MISSING_PUNCH', 9,  'APPROVED',  'Forgot to punch out',                            'Approved'),
  (3,  'WRONG_PUNCH',   18, 'APPROVED',  'Wrong punch time at the gate',                   'Approved'),
  (15, 'MISSING_PUNCH', 8,  'REJECTED',  'Did not punch out',                              'No supporting evidence provided'),
  (18, 'WRONG_PUNCH',   20, 'REJECTED',  'Punch time looks wrong',                         'Time matches the device log'),
  (6,  'MISSING_PUNCH', 13, 'CANCELLED', 'Forgot to punch out',                            NULL)
) AS r(n, rtype, back, status, reason, comment)
JOIN _emp e ON e.n = r.n;

CREATE TEMP TABLE _regs ON COMMIT DROP AS
SELECT r.* FROM _regs0 r
WHERE NOT EXISTS (
  SELECT 1 FROM _apps a
  WHERE a.employee_id = r.employee_id AND a.status = 'APPROVED' AND r.day BETWEEN a.s AND a.e);

-- ---- attendance: the last 30 days for all 20 -----------------------------------------------------
-- Deterministic variation from a hash of (code, day): most days on time, ~15% late, ~1% absent.
CREATE TEMP TABLE _grid ON COMMIT DROP AS
SELECT e.id AS employee_id, e.code, e.shift_id, e.shift_version_id, e.start_time, e.end_time, e.joined,
       d::date AS day, extract(isodow FROM d) >= 6 AS weekend,
       abs(hashtext(e.code || d::date::text)) % 100 AS k,
       (e.end_time < e.start_time) AS overnight
FROM _emp e CROSS JOIN generate_series(current_date - 30, current_date - 1, interval '1 day') AS d
WHERE d::date >= e.joined;

CREATE TEMP TABLE _plan ON COMMIT DROP AS
SELECT g.*,
       (SELECT a.id FROM _apps a WHERE a.employee_id = g.employee_id AND a.status = 'APPROVED'
          AND g.day BETWEEN a.s AND a.e AND NOT g.weekend LIMIT 1) AS leave_app,
       (SELECT r.status FROM _regs r WHERE r.employee_id = g.employee_id AND r.day = g.day) AS reg_status,
       (SELECT r.rtype FROM _regs r WHERE r.employee_id = g.employee_id AND r.day = g.day) AS reg_type
FROM _grid g;

-- t_in / t_out as the device recorded them; shifts that end after midnight add a day to t_out.
CREATE TEMP TABLE _times ON COMMIT DROP AS
SELECT p.*,
       ((p.day + p.start_time) AT TIME ZONE (SELECT tz FROM _ctx)) AS sched_start,
       ((p.day + p.end_time) AT TIME ZONE (SELECT tz FROM _ctx)) + CASE WHEN p.overnight THEN interval '1 day' ELSE interval '0' END AS sched_end,
       CASE WHEN p.reg_type = 'WRONG_PUNCH' AND p.reg_status <> 'APPROVED' THEN 95
            WHEN p.k >= 85 THEN 20 + (p.k - 85) * 2
            ELSE (p.k % 12) - 6 END AS in_off_min,
       ((p.k % 4) * 8) - 5 AS out_off_min
FROM _plan p;

-- Working days that produce punches (not weekend, not leave, not an absence).
CREATE TEMP TABLE _punched ON COMMIT DROP AS
SELECT t.*,
       t.sched_start + make_interval(mins => t.in_off_min) AS t_in,
       t.sched_end + make_interval(mins => t.out_off_min) AS t_out,
       coalesce(t.reg_type = 'MISSING_PUNCH' AND t.reg_status <> 'APPROVED', false) AS missing_out
FROM _times t
WHERE NOT t.weekend AND t.leave_app IS NULL AND NOT (t.k = 1 AND t.reg_status IS NULL);

INSERT INTO punch (company_id, employee_id, punch_time, direction, source, reference)
SELECT (SELECT company_id FROM _ctx), employee_id, t_in, 'IN',
       CASE WHEN k % 3 = 0 THEN 'WEB' ELSE 'MOBILE' END, 'demo-seed'
FROM _punched
UNION ALL
SELECT (SELECT company_id FROM _ctx), employee_id, t_out, 'OUT',
       CASE WHEN reg_status = 'APPROVED' THEN 'REGULARIZATION' WHEN k % 3 = 0 THEN 'WEB' ELSE 'MOBILE' END, 'demo-seed'
FROM _punched WHERE NOT missing_out;

INSERT INTO attendance_day (
  company_id, employee_id, attendance_date, timezone, shift_id, shift_version_id, work_calendar_id,
  attendance_policy_version_id, overtime_policy_version_id, regularization_policy_version_id,
  calendar_day_type, scheduled_start, scheduled_end, scheduled_minutes, actual_first_in, actual_last_out,
  worked_minutes, attendance_status, late_minutes, is_late, early_departure_minutes, is_early_out,
  missing_punch, is_regularized, paid_day_fraction, leave_fraction, lop_fraction, weekly_off_fraction,
  calculation_version, engine_version, calculated_at, computation_snapshot)
-- working days with punches
SELECT (SELECT company_id FROM _ctx), p.employee_id, p.day, (SELECT tz FROM _ctx), p.shift_id, p.shift_version_id,
       (SELECT work_calendar_id FROM _pol), (SELECT attendance_policy_version_id FROM _pol),
       (SELECT overtime_policy_version_id FROM _pol), (SELECT regularization_policy_version_id FROM _pol),
       'WORKING', p.sched_start, p.sched_end, (extract(epoch FROM (p.sched_end - p.sched_start)) / 60)::int,
       p.t_in, CASE WHEN p.missing_out THEN NULL ELSE p.t_out END,
       CASE WHEN p.missing_out THEN 0
            ELSE greatest(0, (extract(epoch FROM (p.t_out - p.t_in)) / 60)::int - 60) END,
       CASE WHEN p.missing_out THEN 'INCOMPLETE' ELSE 'PRESENT' END,
       greatest(0, (extract(epoch FROM (p.t_in - p.sched_start)) / 60)::int - 15),
       (extract(epoch FROM (p.t_in - p.sched_start)) / 60) > 15,
       CASE WHEN p.missing_out OR p.out_off_min >= 0 THEN 0 ELSE -p.out_off_min END,
       (NOT p.missing_out AND p.out_off_min < -3),
       p.missing_out, coalesce(p.reg_status = 'APPROVED', false),
       CASE WHEN p.missing_out THEN 0 ELSE 1 END, 0, 0, 0, 1, 2, now(),
       '{"demo_seed": true}'::jsonb
FROM _punched p
UNION ALL
-- approved leave
SELECT (SELECT company_id FROM _ctx), t.employee_id, t.day, (SELECT tz FROM _ctx), t.shift_id, t.shift_version_id,
       (SELECT work_calendar_id FROM _pol), (SELECT attendance_policy_version_id FROM _pol),
       (SELECT overtime_policy_version_id FROM _pol), (SELECT regularization_policy_version_id FROM _pol),
       'WORKING', t.sched_start, t.sched_end, (extract(epoch FROM (t.sched_end - t.sched_start)) / 60)::int,
       NULL, NULL, 0, 'LEAVE', 0, false, 0, false, false, false, 1, 1, 0, 0, 1, 2, now(), '{"demo_seed": true}'::jsonb
FROM _times t WHERE t.leave_app IS NOT NULL
UNION ALL
-- absent working days with no request
SELECT (SELECT company_id FROM _ctx), t.employee_id, t.day, (SELECT tz FROM _ctx), t.shift_id, t.shift_version_id,
       (SELECT work_calendar_id FROM _pol), (SELECT attendance_policy_version_id FROM _pol),
       (SELECT overtime_policy_version_id FROM _pol), (SELECT regularization_policy_version_id FROM _pol),
       'WORKING', t.sched_start, t.sched_end, (extract(epoch FROM (t.sched_end - t.sched_start)) / 60)::int,
       NULL, NULL, 0, 'ABSENT', 0, false, 0, false, false, false, 0, 0, 1, 0, 1, 2, now(), '{"demo_seed": true}'::jsonb
FROM _times t WHERE NOT t.weekend AND t.leave_app IS NULL AND t.k = 1 AND t.reg_status IS NULL
UNION ALL
-- weekends
SELECT (SELECT company_id FROM _ctx), t.employee_id, t.day, (SELECT tz FROM _ctx), t.shift_id, t.shift_version_id,
       (SELECT work_calendar_id FROM _pol), (SELECT attendance_policy_version_id FROM _pol),
       (SELECT overtime_policy_version_id FROM _pol), (SELECT regularization_policy_version_id FROM _pol),
       'WEEKLY_OFF', NULL, NULL, NULL, NULL, NULL, 0, 'NOT_EXPECTED', 0, false, 0, false, false, false, 0, 0, 0, 1, 1, 2, now(),
       '{"demo_seed": true}'::jsonb
FROM _times t WHERE t.weekend;

-- ---- regularization requests --------------------------------------------------------------------
INSERT INTO attendance_regularization_request (
  id, company_id, employee_id, attendance_day_id, attendance_date, request_type, reason, status, approval_chain,
  approval_stage, regularization_policy_version_id, submitted_by_user_id, submitted_at, reviewed_by_user_id,
  reviewed_at, reviewer_comment, rejection_reason, applied_at, cancelled_at, cancelled_by_user_id)
SELECT r.id, (SELECT company_id FROM _ctx), r.employee_id,
       (SELECT ad.id FROM attendance_day ad WHERE ad.employee_id = r.employee_id AND ad.attendance_date = r.day),
       r.day, r.rtype, r.reason, r.status, 'HR', CASE WHEN r.status = 'SUBMITTED' THEN 'HR' END,
       (SELECT regularization_policy_version_id FROM _pol), (SELECT admin_user_id FROM _ctx),
       (r.day + 1)::timestamptz + interval '10 hours' + make_interval(mins => r.n * 7),
       CASE WHEN r.status IN ('APPROVED', 'REJECTED') THEN (SELECT admin_user_id FROM _ctx) END,
       CASE WHEN r.status IN ('APPROVED', 'REJECTED') THEN (r.day + 2)::timestamptz + interval '11 hours' END,
       CASE WHEN r.status = 'APPROVED' THEN r.comment END,
       CASE WHEN r.status = 'REJECTED' THEN r.comment END,
       CASE WHEN r.status = 'APPROVED' THEN (r.day + 2)::timestamptz + interval '11 hours' END,
       CASE WHEN r.status = 'CANCELLED' THEN (r.day + 1)::timestamptz + interval '16 hours' END,
       CASE WHEN r.status = 'CANCELLED' THEN (SELECT admin_user_id FROM _ctx) END
FROM _regs r;

-- The punches the employee asked for.
INSERT INTO attendance_regularization_requested_punch (company_id, request_id, direction, requested_time, sort_order)
SELECT (SELECT company_id FROM _ctx), r.id, 'OUT', t.sched_end + interval '5 minutes', 0
FROM _regs r JOIN _times t ON t.employee_id = r.employee_id AND t.day = r.day
WHERE r.rtype = 'MISSING_PUNCH'
UNION ALL
SELECT (SELECT company_id FROM _ctx), r.id, 'IN', t.sched_start + interval '2 minutes', 0
FROM _regs r JOIN _times t ON t.employee_id = r.employee_id AND t.day = r.day
WHERE r.rtype = 'WRONG_PUNCH'
UNION ALL
SELECT (SELECT company_id FROM _ctx), r.id, 'OUT', t.sched_end + interval '5 minutes', 1
FROM _regs r JOIN _times t ON t.employee_id = r.employee_id AND t.day = r.day
WHERE r.rtype = 'WRONG_PUNCH';

INSERT INTO attendance_regularization_action (company_id, request_id, action, actor_user_id, stage, comment, created_at)
SELECT (SELECT company_id FROM _ctx), q.id, 'SUBMITTED', q.submitted_by_user_id, NULL, q.reason, q.submitted_at
FROM attendance_regularization_request q WHERE q.id IN (SELECT id FROM _regs);

INSERT INTO attendance_regularization_action (company_id, request_id, action, actor_user_id, stage, comment, created_at)
SELECT (SELECT company_id FROM _ctx), q.id, q.status, coalesce(q.reviewed_by_user_id, q.cancelled_by_user_id),
       CASE WHEN q.status IN ('APPROVED', 'REJECTED') THEN 'HR' END,
       coalesce(q.reviewer_comment, q.rejection_reason), coalesce(q.reviewed_at, q.cancelled_at)
FROM attendance_regularization_request q
WHERE q.id IN (SELECT id FROM _regs) AND q.status IN ('APPROVED', 'REJECTED', 'CANCELLED');

-- ---- summary ------------------------------------------------------------------------------------
SELECT 'employees' AS what, count(*) FROM employee WHERE id IN (SELECT id FROM _emp)
UNION ALL SELECT 'leave applications', count(*) FROM _apps
UNION ALL SELECT '  pending', count(*) FROM _apps WHERE status = 'SUBMITTED'
UNION ALL SELECT '  approved', count(*) FROM _apps WHERE status = 'APPROVED'
UNION ALL SELECT '  rejected/cancelled', count(*) FROM _apps WHERE status IN ('REJECTED', 'CANCELLED')
UNION ALL SELECT 'regularization requests', count(*) FROM _regs
UNION ALL SELECT '  pending', count(*) FROM _regs WHERE status = 'SUBMITTED'
UNION ALL SELECT 'attendance days', count(*) FROM attendance_day WHERE employee_id IN (SELECT id FROM _emp)
UNION ALL SELECT 'punches', count(*) FROM punch WHERE employee_id IN (SELECT id FROM _emp);

COMMIT;
