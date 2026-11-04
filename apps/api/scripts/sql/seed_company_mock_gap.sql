-- Mock attendance + leave data for the company behind varunmsaji@gmail.com, from 2026-10-27 up to
-- and including today, so the company dashboards/reports are not empty for the recent days.
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_company_mock_gap.sql
--
-- Idempotent and re-runnable (run it again on a later day to extend the window to that day):
--   * every row it writes is tagged ('MOCK-SEED-GAP' punches, {"mock_gap_seed": true} snapshots,
--     'mock-gap-seed' reasons) and removed first;
--   * it never touches or replaces an employee-day that already has an attendance row.
--
-- Shape of the data (deterministic per employee + date, so a re-run reproduces it):
--   * working days: ~85% present (some late, some leave early), a few half days, a few absent,
--     a few with a missing OUT punch; weekly offs follow each employee's pattern of the week before;
--   * today: only what has happened by the time the script runs - people checked in and still
--     working, the rest not yet checked in (the overview reads these as PRESENT / NOT_CHECKED_IN);
--   * leave: approved leave covering today and recent days, upcoming approved leave, pending
--     requests to approve, one rejected; ledger debits + day projections so balances line up;
--   * corrections: a few missing-punch requests awaiting approval for yesterday's open days.

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

-- ---- clean previous run ---------------------------------------------------------------------
DELETE FROM attendance_regularization_requested_punch WHERE request_id IN
  (SELECT id FROM attendance_regularization_request
   WHERE reason = 'mock-gap-seed' AND company_id = (SELECT company_id FROM _co));
DELETE FROM attendance_regularization_request
  WHERE reason = 'mock-gap-seed' AND company_id = (SELECT company_id FROM _co);
DELETE FROM leave_ledger
  WHERE company_id = (SELECT company_id FROM _co) AND reason LIKE 'mock-gap-seed%';
DELETE FROM leave_application_day WHERE leave_application_id IN
  (SELECT id FROM leave_application WHERE reason = 'mock-gap-seed' AND company_id = (SELECT company_id FROM _co));
DELETE FROM leave_day_projection WHERE leave_application_id IN
  (SELECT id FROM leave_application WHERE reason = 'mock-gap-seed' AND company_id = (SELECT company_id FROM _co));
DELETE FROM leave_application
  WHERE reason = 'mock-gap-seed' AND company_id = (SELECT company_id FROM _co);
DELETE FROM attendance_day
  WHERE company_id = (SELECT company_id FROM _co) AND computation_snapshot @> '{"mock_gap_seed": true}';
DELETE FROM punch
  WHERE company_id = (SELECT company_id FROM _co) AND reference = 'MOCK-SEED-GAP';

-- ---- who and when ---------------------------------------------------------------------------
CREATE TEMP TABLE _emp ON COMMIT DROP AS
SELECT e.id AS employee_id, e.company_id, e.user_id, e.employee_code,
       a.shift_id, sv.id AS shift_version_id, sv.start_time, sv.end_time,
       (sv.end_time < sv.start_time) AS crosses_midnight,
       ref.work_calendar_id, ref.attendance_policy_version_id,
       ref.overtime_policy_version_id, ref.regularization_policy_version_id,
       'Asia/Kolkata'::text AS tz,
       NOT EXISTS (SELECT 1 FROM attendance_day x WHERE x.employee_id = e.id
                   AND x.attendance_date BETWEEN DATE '2026-10-27' AND current_date) AS fresh
FROM employee e
JOIN _co ON _co.company_id = e.company_id
JOIN employee_assignment a ON a.employee_id = e.id AND a.effective_to IS NULL
JOIN LATERAL (SELECT * FROM shift_version v WHERE v.shift_id = a.shift_id AND v.status = 'PUBLISHED'
              ORDER BY v.version DESC LIMIT 1) sv ON true
LEFT JOIN LATERAL (SELECT d.work_calendar_id, d.attendance_policy_version_id,
                          d.overtime_policy_version_id, d.regularization_policy_version_id
                   FROM attendance_day d
                   WHERE d.employee_id = e.id AND d.attendance_policy_version_id IS NOT NULL
                   ORDER BY d.attendance_date DESC LIMIT 1) ref ON true
WHERE e.deleted_at IS NULL AND e.status IN ('ACTIVE', 'PROBATION', 'ON_NOTICE');

-- Rank among employees with nothing yet in the window - leave is only planned for these, so the
-- leave never contradicts an existing attendance row.
CREATE TEMP TABLE _fresh ON COMMIT DROP AS
SELECT employee_id, row_number() OVER (ORDER BY employee_code) AS rn FROM _emp WHERE fresh;

-- ---- leave plan -----------------------------------------------------------------------------
CREATE TEMP TABLE _plan ON COMMIT DROP AS
SELECT gen_random_uuid() AS id, f.employee_id, t.code, t.s, t.e, t.status, t.decided_hours_ago
FROM (VALUES
  (3,  'CL', current_date,      current_date,      'APPROVED',  5),
  (6,  'CL', current_date,      current_date,      'APPROVED',  20),
  (9,  'SL', current_date - 1,  current_date,      'APPROVED',  30),
  (12, 'SL', current_date - 1,  current_date - 1, 'APPROVED',  28),
  (15, 'EL', current_date - 5,  current_date - 4,  'APPROVED',  24 * 9),
  (18, 'EL', current_date + 2,  current_date + 3,  'APPROVED',  26),
  (21, 'CL', current_date + 7,  current_date + 7,  'APPROVED',  3),
  (24, 'CL', current_date + 6,  current_date + 7,  'SUBMITTED', NULL),
  (27, 'SL', current_date + 1,  current_date + 1,  'SUBMITTED', NULL),
  (30, 'EL', current_date + 9,  current_date + 13, 'SUBMITTED', NULL),
  (33, 'CL', current_date + 4,  current_date + 4,  'SUBMITTED', NULL),
  (36, 'CL', current_date - 8,  current_date - 8,  'REJECTED',  24 * 8)
) AS t(rn, code, s, e, status, decided_hours_ago)
JOIN _fresh f ON f.rn = t.rn;

CREATE TEMP TABLE _lt ON COMMIT DROP AS
SELECT lt.id AS leave_type_id, lt.code, v.id AS policy_version_id
FROM leave_type lt
JOIN leave_policy lp ON lp.leave_type_id = lt.id AND lp.company_id = lt.company_id
JOIN leave_policy_version v ON v.policy_id = lp.id AND v.effective_to IS NULL
WHERE lt.company_id = (SELECT company_id FROM _co) AND lt.code IN ('CL', 'SL', 'EL');

-- Opening balance for any (employee, type) the plan touches that has no ledger entry yet.
INSERT INTO leave_ledger (company_id, employee_id, leave_type_id, entry_type, amount, effective_date, reason)
SELECT DISTINCT (SELECT company_id FROM _co), p.employee_id, l.leave_type_id, 'ADJUSTMENT',
       CASE l.code WHEN 'CL' THEN 7 WHEN 'SL' THEN 10 ELSE 18 END,
       date_trunc('year', current_date)::date, 'mock-gap-seed: opening balance'
FROM _plan p JOIN _lt l ON l.code = p.code
WHERE NOT EXISTS (SELECT 1 FROM leave_ledger g WHERE g.employee_id = p.employee_id AND g.leave_type_id = l.leave_type_id);

-- One row per weekday of each application (the days that actually count as leave).
CREATE TEMP TABLE _plan_days ON COMMIT DROP AS
SELECT p.id AS application_id, p.employee_id, p.code, p.status, d::date AS day
FROM _plan p CROSS JOIN LATERAL generate_series(p.s, p.e, interval '1 day') AS d
WHERE extract(isodow FROM d) < 6;

INSERT INTO leave_application (
  id, company_id, employee_id, leave_type_id, leave_policy_version_id, start_date, end_date, total_days,
  reason, status, approval_chain, approval_stage, submitted_by_user_id, submitted_at,
  reviewed_by_user_id, reviewed_at, reviewer_comment, rejection_reason)
SELECT p.id, (SELECT company_id FROM _co), p.employee_id, l.leave_type_id, l.policy_version_id, p.s, p.e,
       (SELECT count(*) FROM _plan_days d WHERE d.application_id = p.id),
       'mock-gap-seed', p.status, 'HR', CASE WHEN p.status = 'SUBMITTED' THEN 'HR' END, em.user_id,
       now() - make_interval(hours => coalesce(p.decided_hours_ago, 0) + 30),
       CASE WHEN p.status <> 'SUBMITTED' THEN (SELECT user_id FROM _emp WHERE employee_id = p.employee_id) END,
       CASE WHEN p.status <> 'SUBMITTED' THEN now() - make_interval(hours => p.decided_hours_ago) END,
       CASE WHEN p.status = 'APPROVED' THEN 'Approved' END,
       CASE WHEN p.status = 'REJECTED' THEN 'Team is short-staffed that day' END
FROM _plan p JOIN _lt l ON l.code = p.code JOIN _emp em ON em.employee_id = p.employee_id;

INSERT INTO leave_ledger (company_id, employee_id, leave_type_id, entry_type, amount, effective_date, reference_id, reason)
SELECT (SELECT company_id FROM _co), p.employee_id, l.leave_type_id, 'APPLICATION',
       -(SELECT count(*) FROM _plan_days d WHERE d.application_id = p.id), p.s, p.id,
       'mock-gap-seed: leave application ' || p.s || ' to ' || p.e
FROM _plan p JOIN _lt l ON l.code = p.code WHERE p.status = 'APPROVED';

INSERT INTO leave_day_projection (
  company_id, employee_id, attendance_date, leave_application_id, leave_type_id, leave_type_code,
  fraction, is_paid, status, source_version, synced_at, created_by_user_id)
SELECT (SELECT company_id FROM _co), d.employee_id, d.day, d.application_id, l.leave_type_id, d.code,
       1, true, 'APPROVED', 1, now(), em.user_id
FROM _plan_days d JOIN _lt l ON l.code = d.code JOIN _emp em ON em.employee_id = d.employee_id
WHERE d.status = 'APPROVED';

INSERT INTO leave_application_day (company_id, leave_application_id, calendar_date, fraction, leave_day_projection_id)
SELECT (SELECT company_id FROM _co), d.application_id, d.day, 1,
       (SELECT pr.id FROM leave_day_projection pr
        WHERE pr.leave_application_id = d.application_id AND pr.attendance_date = d.day)
FROM _plan_days d;

-- ---- attendance: one decision per employee-day that has no row yet ---------------------------
CREATE TEMP TABLE _gen ON COMMIT DROP AS
WITH base AS (
  SELECT em.*, d::date AS day,
         abs(hashtext(em.employee_id::text || d::date::text)) % 100 AS r,
         CASE WHEN extract(isodow FROM d) >= 6
              THEN coalesce((SELECT x.calendar_day_type FROM attendance_day x
                             WHERE x.employee_id = em.employee_id AND x.attendance_date = d::date - 7),
                            'WEEKLY_OFF')
              ELSE 'WORKING' END AS day_type
  FROM _emp em
  CROSS JOIN generate_series(DATE '2026-10-27', current_date, interval '1 day') AS d
  WHERE NOT EXISTS (SELECT 1 FROM attendance_day x WHERE x.employee_id = em.employee_id AND x.attendance_date = d::date)
), sched AS (
  SELECT b.*,
         (b.day + b.start_time) AT TIME ZONE b.tz AS s_start,
         (b.day + CASE WHEN b.crosses_midnight THEN 1 ELSE 0 END + b.end_time) AT TIME ZONE b.tz AS s_end,
         EXISTS (SELECT 1 FROM _plan_days l WHERE l.employee_id = b.employee_id AND l.day = b.day
                 AND l.status = 'APPROVED') AS on_leave
  FROM base b
), planned AS (
  SELECT s.*,
         s_start + make_interval(mins => (s.r % 40) - 15) AS t_in,
         s_end   + make_interval(mins => (((s.r / 3) % 5) - 1) * 10) AS t_out,
         CASE
           WHEN s.day_type <> 'WORKING' THEN 'OFF'
           WHEN s.on_leave THEN 'LEAVE'
           WHEN s.day = current_date THEN
             CASE WHEN s.crosses_midnight OR s.r >= 93 OR s_start + make_interval(mins => (s.r % 40) - 15) > now()
                  THEN 'NOT_YET' ELSE 'WORKING_NOW' END
           WHEN s.r < 5  THEN 'ABSENT'
           WHEN s.r < 9  THEN 'NO_OUT'
           WHEN s.r < 12 THEN 'HALF'
           ELSE 'PRESENT' END AS kind
  FROM sched s
)
SELECT * FROM planned;

-- Punches. Half days leave 4h30 after arriving. A night shift's punches already happened for past days.
INSERT INTO punch (company_id, employee_id, punch_time, direction, source, idempotency_key, reference)
SELECT company_id, employee_id, t_in, 'IN', CASE WHEN r % 5 = 0 THEN 'WEB' ELSE 'MOBILE' END,
       'mock-gap-' || employee_id || '-' || day || '-IN', 'MOCK-SEED-GAP'
FROM _gen WHERE kind IN ('PRESENT', 'NO_OUT', 'HALF', 'WORKING_NOW')
UNION ALL
SELECT company_id, employee_id,
       CASE kind WHEN 'HALF' THEN t_in + interval '270 minutes' ELSE t_out END, 'OUT',
       CASE WHEN r % 5 = 0 THEN 'WEB' ELSE 'MOBILE' END,
       'mock-gap-' || employee_id || '-' || day || '-OUT', 'MOCK-SEED-GAP'
FROM _gen
WHERE kind IN ('PRESENT', 'HALF')
  AND CASE kind WHEN 'HALF' THEN t_in + interval '270 minutes' ELSE t_out END <= now();

INSERT INTO attendance_day (
  company_id, employee_id, attendance_date, timezone, shift_id, shift_version_id, work_calendar_id,
  attendance_policy_version_id, overtime_policy_version_id, regularization_policy_version_id,
  calendar_day_type, scheduled_start, scheduled_end, scheduled_minutes,
  actual_first_in, actual_last_out, worked_minutes, attendance_status,
  late_minutes, is_late, early_departure_minutes, is_early_out, missing_punch,
  paid_day_fraction, lop_fraction, leave_fraction, weekly_off_fraction,
  calculation_version, engine_version, calculated_at, computation_snapshot)
SELECT g.company_id, g.employee_id, g.day, g.tz, g.shift_id, g.shift_version_id, g.work_calendar_id,
       g.attendance_policy_version_id, g.overtime_policy_version_id, g.regularization_policy_version_id,
       g.day_type,
       CASE WHEN g.day_type = 'WORKING' THEN g.s_start END,
       CASE WHEN g.day_type = 'WORKING' THEN g.s_end END,
       CASE WHEN g.day_type = 'WORKING' THEN (extract(epoch FROM (g.s_end - g.s_start)) / 60)::int END,
       CASE WHEN g.kind IN ('PRESENT', 'NO_OUT', 'HALF', 'WORKING_NOW') THEN g.t_in END,
       CASE g.kind
         WHEN 'PRESENT' THEN CASE WHEN g.t_out <= now() THEN g.t_out END
         WHEN 'HALF' THEN g.t_in + interval '270 minutes' END,
       CASE g.kind WHEN 'PRESENT' THEN CASE WHEN g.t_out <= now() THEN (extract(epoch FROM (g.t_out - g.t_in)) / 60)::int ELSE 0 END
                   WHEN 'HALF' THEN 270 ELSE 0 END,
       CASE g.kind WHEN 'OFF' THEN 'NOT_EXPECTED' WHEN 'LEAVE' THEN 'LEAVE'
                   WHEN 'PRESENT' THEN CASE WHEN g.t_out <= now() THEN 'PRESENT' ELSE 'INCOMPLETE' END
                   WHEN 'HALF' THEN 'HALF_DAY' WHEN 'NO_OUT' THEN 'INCOMPLETE'
                   WHEN 'WORKING_NOW' THEN 'INCOMPLETE' WHEN 'NOT_YET' THEN 'ABSENT' ELSE 'ABSENT' END,
       CASE WHEN g.kind IN ('PRESENT', 'NO_OUT', 'HALF', 'WORKING_NOW')
            THEN greatest(0, (extract(epoch FROM (g.t_in - g.s_start)) / 60)::int - 15) ELSE 0 END,
       g.kind IN ('PRESENT', 'NO_OUT', 'HALF', 'WORKING_NOW') AND (extract(epoch FROM (g.t_in - g.s_start)) / 60) > 15,
       CASE WHEN g.kind = 'HALF' THEN (extract(epoch FROM (g.s_end - (g.t_in + interval '270 minutes'))) / 60)::int
            WHEN g.kind = 'PRESENT' AND g.t_out < g.s_end AND g.t_out <= now()
                 THEN (extract(epoch FROM (g.s_end - g.t_out)) / 60)::int ELSE 0 END,
       g.kind = 'HALF' OR (g.kind = 'PRESENT' AND g.t_out < g.s_end AND g.t_out <= now()),
       g.kind = 'NO_OUT',
       CASE g.kind WHEN 'PRESENT' THEN 1 WHEN 'LEAVE' THEN 1 WHEN 'HALF' THEN 0.5 ELSE 0 END,
       CASE g.kind WHEN 'ABSENT' THEN 1 WHEN 'HALF' THEN 0.5 ELSE 0 END,
       CASE g.kind WHEN 'LEAVE' THEN 1 ELSE 0 END,
       CASE g.kind WHEN 'OFF' THEN 1 ELSE 0 END,
       1, 2, now(), '{"mock_gap_seed": true}'::jsonb
FROM _gen g;

-- ---- corrections awaiting approval for yesterday's open days ----------------------------------
WITH pick AS (
  SELECT ad.id AS day_id, ad.employee_id, ad.company_id, ad.attendance_date, ad.scheduled_end,
         ad.regularization_policy_version_id, em.user_id,
         row_number() OVER (ORDER BY ad.employee_id) AS n
  FROM attendance_day ad JOIN _emp em ON em.employee_id = ad.employee_id
  WHERE ad.computation_snapshot @> '{"mock_gap_seed": true}'
    AND ad.attendance_status = 'INCOMPLETE' AND ad.missing_punch
    AND ad.regularization_policy_version_id IS NOT NULL
), req AS (
  INSERT INTO attendance_regularization_request (
    company_id, employee_id, attendance_day_id, attendance_date, request_type, reason, status,
    approval_chain, approval_stage, regularization_policy_version_id, submitted_by_user_id, submitted_at)
  SELECT company_id, employee_id, day_id, attendance_date, 'MISSING_PUNCH', 'mock-gap-seed', 'SUBMITTED',
         'HR', 'HR', regularization_policy_version_id, user_id, now() - interval '3 hours'
  FROM pick WHERE n <= 6
  RETURNING id, company_id, attendance_day_id
)
INSERT INTO attendance_regularization_requested_punch (company_id, request_id, direction, requested_time)
SELECT r.company_id, r.id, 'OUT', ad.scheduled_end
FROM req r JOIN attendance_day ad ON ad.id = r.attendance_day_id;

COMMIT;

-- Summary of what is now in the window.
SELECT attendance_date, attendance_status, count(*)
FROM attendance_day
WHERE company_id = (SELECT DISTINCT uc.company_id FROM "user" u JOIN user_company uc ON uc.user_id = u.id
                    WHERE u.email = 'varunmsaji@gmail.com')
  AND attendance_date >= DATE '2026-10-27'
GROUP BY 1, 2 ORDER BY 1, 2;
