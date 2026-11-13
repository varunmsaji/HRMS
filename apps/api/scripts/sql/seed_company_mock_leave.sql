-- Mock leave around today for the company behind varunmsaji@gmail.com (Varun Company), on top of the
-- DEMO-001..DEMO-020 workforce from seed_demo_employees.sql and the attendance from
-- seed_company_mock_gap.sql:
--   * approved leave covering recent days and today (feeds "on leave today"),
--   * approved leave coming up, pending requests to approve, one rejected, one withdrawn,
--   * ledger debits, application days, day projections and timeline actions so balances,
--     calendars and the request history line up.
-- Then every mock attendance day (seed_company_mock_gap.sql rows) that falls on a full day of
-- APPROVED leave - from this script or any earlier one - is turned into a LEAVE day and its mock
-- punches / missing-punch requests are removed, so nobody is "present" while on approved leave.
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`), after the gap seed:
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_company_mock_leave.sql
--
-- Idempotent: every application it writes has reason prefixed 'mock-leave-seed' in the ledger and
-- a [mock-leave-seed] tag in leave_application.reason; they are removed first on a re-run. A planned
-- request that would overlap someone's existing submitted/approved leave is skipped. Dates are
-- relative to current_date. Local development only; names and reasons are invented.

BEGIN;

CREATE TEMP TABLE _ctx ON COMMIT DROP AS
SELECT uc.company_id, u.id AS admin_user_id
FROM "user" u JOIN user_company uc ON uc.user_id = u.id
WHERE lower(u.email) = 'varunmsaji@gmail.com';

DO $$ BEGIN
  IF (SELECT count(*) FROM _ctx) <> 1 THEN
    RAISE EXCEPTION 'varunmsaji@gmail.com is not linked to exactly one company';
  END IF;
END $$;

-- ---- clean previous run ---------------------------------------------------------------------
CREATE TEMP TABLE _old ON COMMIT DROP AS
SELECT id FROM leave_application
WHERE company_id = (SELECT company_id FROM _ctx) AND reason LIKE '%[mock-leave-seed]';

DELETE FROM leave_application_action WHERE leave_application_id IN (SELECT id FROM _old);
DELETE FROM leave_application_day WHERE leave_application_id IN (SELECT id FROM _old);
DELETE FROM leave_day_projection WHERE leave_application_id IN (SELECT id FROM _old);
DELETE FROM leave_ledger WHERE company_id = (SELECT company_id FROM _ctx) AND reason LIKE 'mock-leave-seed%';
DELETE FROM leave_application WHERE id IN (SELECT id FROM _old);

-- ---- leave plan -----------------------------------------------------------------------------
-- (employee code, type, start/end offset from today, status, reason, reviewer comment)
CREATE TEMP TABLE _plan0 ON COMMIT DROP AS
SELECT * FROM (VALUES
  -- approved: recent days and today
  ('DEMO-003', 'SL', -2, -2, 'APPROVED',  'Migraine',                 NULL),
  ('DEMO-020', 'SL', -1,  0, 'APPROVED',  'Viral fever',              'Get well soon'),
  ('DEMO-015', 'CL',  0,  0, 'APPROVED',  'Personal errand',          NULL),
  ('DEMO-012', 'EL',  0,  1, 'APPROVED',  'Sister''s graduation',     NULL),
  -- approved: coming up
  ('DEMO-011', 'CL',  5,  5, 'APPROVED',  'Bank work',                NULL),
  ('DEMO-013', 'CL',  6,  6, 'APPROVED',  'Personal work',            NULL),
  ('DEMO-002', 'EL', 11, 15, 'APPROVED',  'Family vacation',          'Enjoy the break'),
  -- waiting for approval
  ('DEMO-006', 'CL',  1,  1, 'SUBMITTED', 'Parent-teacher meeting',   NULL),
  ('DEMO-010', 'SL',  1,  1, 'SUBMITTED', 'Dentist follow-up',        NULL),
  ('DEMO-014', 'EL',  4,  6, 'SUBMITTED', 'Trip home',                NULL),
  -- declined and withdrawn
  ('DEMO-005', 'CL',  1,  1, 'REJECTED',  'Short trip',               'Month-end closing, please pick another day'),
  ('DEMO-010', 'CL',  7,  8, 'CANCELLED', 'Plans changed',            'Plans changed')
) AS t(code, lt_code, s_off, e_off, status, reason, comment);

CREATE TEMP TABLE _lt ON COMMIT DROP AS
SELECT lt.id AS leave_type_id, lt.code, v.id AS policy_version_id
FROM leave_type lt
JOIN leave_policy lp ON lp.leave_type_id = lt.id AND lp.company_id = lt.company_id
JOIN leave_policy_version v ON v.policy_id = lp.id AND v.effective_to IS NULL
WHERE lt.company_id = (SELECT company_id FROM _ctx) AND lt.code IN ('CL', 'SL', 'EL');

CREATE TEMP TABLE _plan ON COMMIT DROP AS
SELECT gen_random_uuid() AS id, p.*, e.id AS employee_id, e.user_id, l.leave_type_id, l.policy_version_id,
       current_date + p.s_off AS s, current_date + p.e_off AS e,
       (SELECT count(*) FROM generate_series(current_date + p.s_off, current_date + p.e_off, interval '1 day') d
        WHERE extract(isodow FROM d) < 6) AS days
FROM _plan0 p
JOIN employee e ON e.company_id = (SELECT company_id FROM _ctx) AND e.employee_code = p.code AND e.deleted_at IS NULL
JOIN _lt l ON l.code = p.lt_code;

-- Weekend-only ranges count nothing; overlaps with someone's live leave would be refused by the app.
DELETE FROM _plan WHERE days = 0;
DELETE FROM _plan p WHERE EXISTS (
  SELECT 1 FROM leave_application a
  WHERE a.employee_id = p.employee_id AND a.status IN ('SUBMITTED', 'APPROVED')
    AND a.start_date <= p.e AND a.end_date >= p.s);

INSERT INTO leave_application (
  id, company_id, employee_id, leave_type_id, leave_policy_version_id, start_date, end_date, total_days, reason,
  status, approval_chain, approval_stage, submitted_by_user_id, submitted_at, reviewed_by_user_id, reviewed_at,
  reviewer_comment, rejection_reason, cancelled_at, cancelled_by_user_id, cancellation_reason)
SELECT p.id, (SELECT company_id FROM _ctx), p.employee_id, p.leave_type_id, p.policy_version_id, p.s, p.e, p.days,
       p.reason || ' [mock-leave-seed]', p.status, 'HR', CASE WHEN p.status = 'SUBMITTED' THEN 'HR' END,
       coalesce(p.user_id, (SELECT admin_user_id FROM _ctx)),
       -- sick leave is filed on the day; planned leave a few days ahead; pending ones in the last day or two
       CASE WHEN p.status = 'SUBMITTED' THEN now() - make_interval(hours => 6 + (abs(hashtext(p.code)) % 30))
            WHEN p.lt_code = 'SL' THEN least(now() - interval '3 hours', p.s::timestamptz + interval '3 hours')
            ELSE least(now() - interval '4 hours', (p.s - 4)::timestamptz + interval '10 hours') END,
       CASE WHEN p.status IN ('APPROVED', 'REJECTED') THEN (SELECT admin_user_id FROM _ctx) END,
       CASE WHEN p.status IN ('APPROVED', 'REJECTED') THEN
            CASE WHEN p.lt_code = 'SL' THEN least(now() - interval '1 hour', p.s::timestamptz + interval '5 hours')
                 ELSE least(now() - interval '2 hours', (p.s - 3)::timestamptz + interval '11 hours') END END,
       CASE WHEN p.status = 'APPROVED' THEN coalesce(p.comment, 'Approved') END,
       CASE WHEN p.status = 'REJECTED' THEN p.comment END,
       CASE WHEN p.status = 'CANCELLED' THEN now() - interval '5 hours' END,
       CASE WHEN p.status = 'CANCELLED' THEN coalesce(p.user_id, (SELECT admin_user_id FROM _ctx)) END,
       CASE WHEN p.status = 'CANCELLED' THEN p.comment END
FROM _plan p;

-- Approved leave is debited from the ledger; a submitted request only reserves (derived by the API).
INSERT INTO leave_ledger (company_id, employee_id, leave_type_id, entry_type, amount, effective_date, reference_id, reason, created_by_user_id)
SELECT (SELECT company_id FROM _ctx), p.employee_id, p.leave_type_id, 'APPLICATION', -p.days, p.s, p.id,
       'mock-leave-seed: leave application ' || p.s || ' to ' || p.e, (SELECT admin_user_id FROM _ctx)
FROM _plan p WHERE p.status = 'APPROVED';

INSERT INTO leave_day_projection (company_id, employee_id, attendance_date, leave_application_id, leave_type_id,
                                  leave_type_code, fraction, is_paid, status)
SELECT (SELECT company_id FROM _ctx), p.employee_id, d::date, p.id, p.leave_type_id, p.lt_code, 1, true, 'APPROVED'
FROM _plan p CROSS JOIN LATERAL generate_series(p.s, p.e, interval '1 day') AS d
WHERE p.status = 'APPROVED' AND extract(isodow FROM d) < 6;

INSERT INTO leave_application_day (company_id, leave_application_id, calendar_date, fraction, leave_day_projection_id)
SELECT (SELECT company_id FROM _ctx), p.id, d::date, 1,
       (SELECT pr.id FROM leave_day_projection pr WHERE pr.leave_application_id = p.id AND pr.attendance_date = d::date)
FROM _plan p CROSS JOIN LATERAL generate_series(p.s, p.e, interval '1 day') AS d
WHERE extract(isodow FROM d) < 6;

-- Timeline entries (submitted, then the decision).
INSERT INTO leave_application_action (company_id, leave_application_id, action, actor_user_id, stage, comment, created_at)
SELECT company_id, id, 'SUBMITTED', submitted_by_user_id, NULL, reason, submitted_at
FROM leave_application WHERE id IN (SELECT id FROM _plan);

INSERT INTO leave_application_action (company_id, leave_application_id, action, actor_user_id, stage, comment, created_at)
SELECT company_id, id, status, coalesce(reviewed_by_user_id, cancelled_by_user_id),
       CASE WHEN status IN ('APPROVED', 'REJECTED') THEN 'HR' END,
       coalesce(reviewer_comment, rejection_reason, cancellation_reason), coalesce(reviewed_at, cancelled_at)
FROM leave_application WHERE id IN (SELECT id FROM _plan) AND status IN ('APPROVED', 'REJECTED', 'CANCELLED');

-- ---- mock attendance days that fall on approved leave become LEAVE days ---------------------
CREATE TEMP TABLE _conv ON COMMIT DROP AS
SELECT ad.id, ad.employee_id, ad.attendance_date, ad.timezone
FROM attendance_day ad
WHERE ad.company_id = (SELECT company_id FROM _ctx)
  AND ad.computation_snapshot @> '{"mock_gap_seed": true}'
  AND ad.calendar_day_type = 'WORKING'
  AND ad.attendance_status <> 'LEAVE'
  AND EXISTS (SELECT 1 FROM leave_day_projection pr
              WHERE pr.employee_id = ad.employee_id AND pr.attendance_date = ad.attendance_date
                AND pr.status = 'APPROVED' AND pr.fraction >= 1);

DELETE FROM attendance_regularization_requested_punch WHERE request_id IN
  (SELECT id FROM attendance_regularization_request WHERE reason = 'mock-gap-seed'
   AND attendance_day_id IN (SELECT id FROM _conv));
DELETE FROM attendance_regularization_request
  WHERE reason = 'mock-gap-seed' AND attendance_day_id IN (SELECT id FROM _conv);
DELETE FROM punch p USING _conv c
  WHERE p.reference = 'MOCK-SEED-GAP' AND p.employee_id = c.employee_id
    AND (p.punch_time AT TIME ZONE c.timezone)::date = c.attendance_date;

UPDATE attendance_day ad SET
  attendance_status = 'LEAVE', actual_first_in = NULL, actual_last_out = NULL, worked_minutes = 0,
  late_minutes = 0, is_late = false, early_departure_minutes = 0, is_early_out = false, missing_punch = false,
  paid_day_fraction = 1, lop_fraction = 0, leave_fraction = 1, calculated_at = now(),
  computation_snapshot = ad.computation_snapshot || '{"mock_leave_seed": true}'::jsonb
FROM _conv c WHERE ad.id = c.id;

COMMIT;

-- Summary.
SELECT e.employee_code, lt.code, a.start_date, a.end_date, a.total_days, a.status
FROM leave_application a
JOIN employee e ON e.id = a.employee_id JOIN leave_type lt ON lt.id = a.leave_type_id
WHERE a.reason LIKE '%[mock-leave-seed]'
  AND a.company_id = (SELECT uc.company_id FROM "user" u JOIN user_company uc ON uc.user_id = u.id
                      WHERE lower(u.email) = 'varunmsaji@gmail.com')
ORDER BY a.start_date, e.employee_code;
