-- Mock lunch-break punches for the company behind varunmsaji@gmail.com (Varun Company), LOCAL DEV ONLY,
-- so the day pages, break reports and excess-break flags have data. It writes break START / END
-- events only; the attendance ENGINE then turns them into `attendance_break` rows when the days are
-- recalculated (run `.venv/bin/python scripts/seed_mock_breaks_recalc.py`, API up, afterwards).
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_company_mock_breaks.sql
--
-- Idempotent: events carry a deterministic id and `meta = {"mock_breaks_seed": true}`; a re-run first
-- removes only its own events for unlocked days, then writes them again. Real events are untouched.
--
-- Shape: for about three in four fully punched PRESENT days from 2 Nov to yesterday, one lunch break
-- in the shift's own lunch window (General 13:00-14:00, Morning 10:00-10:30, Evening 18:00-18:30
-- local). Most are within the allowance; about one in eight runs 15-25 minutes over.

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

DELETE FROM attendance_break_event be
USING _co
WHERE be.company_id = _co.company_id
  AND be.meta ->> 'mock_breaks_seed' = 'true'
  AND NOT EXISTS (SELECT 1 FROM attendance_day d
                  WHERE d.id = be.attendance_day_id AND d.is_locked);

CREATE TEMP TABLE _plan ON COMMIT DROP AS
SELECT d.id AS day_id, d.company_id, d.employee_id, d.attendance_date, d.timezone,
       sb.id AS shift_break_id, sb.name AS break_name,
       (d.attendance_date + sb.start_time)::timestamp AS local_start,
       extract(epoch FROM (sb.end_time - sb.start_time)) / 60 AS allowance_min,
       abs(hashtext(d.id::text)) AS h
FROM attendance_day d
JOIN _co ON _co.company_id = d.company_id
JOIN shift_break sb ON sb.shift_version_id = d.shift_version_id AND sb.break_kind = 'FIXED_WINDOW' AND sb.is_enabled
WHERE d.attendance_status = 'PRESENT' AND NOT d.is_locked
  AND d.actual_first_in IS NOT NULL AND d.actual_last_out IS NOT NULL
  AND d.attendance_date BETWEEN DATE '2026-11-02' AND CURRENT_DATE - 1
  AND abs(hashtext(d.id::text)) % 4 <> 0;

INSERT INTO attendance_break_event (
  id, company_id, employee_id, attendance_date, attendance_day_id, shift_break_id, break_name,
  event_type, event_time, source, meta, created_at)
SELECT md5('mock-breaks:' || day_id || ':' || e.t)::uuid, company_id, employee_id, attendance_date,
       day_id, shift_break_id, break_name, e.t,
       ((local_start + make_interval(mins => CASE e.t
             WHEN 'START' THEN (h % 9)
             ELSE (h % 9) + allowance_min::int - 5 + CASE WHEN h % 8 = 0 THEN 20 ELSE (h / 7) % 6 END
         END)) AT TIME ZONE timezone),
       CASE WHEN h % 3 = 0 THEN 'MOBILE' ELSE 'WEB' END,
       '{"mock_breaks_seed": true}'::jsonb, now()
FROM _plan CROSS JOIN (VALUES ('START'), ('END')) AS e(t)
ON CONFLICT (id) DO NOTHING;

SELECT count(*) FILTER (WHERE event_type = 'START') AS lunch_breaks,
       count(DISTINCT employee_id) AS employees, min(attendance_date), max(attendance_date)
FROM attendance_break_event WHERE meta ->> 'mock_breaks_seed' = 'true';

COMMIT;
