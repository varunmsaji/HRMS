-- Mock overtime for the company behind varunmsaji@gmail.com (Varun Company), LOCAL DEV ONLY: some
-- fully punched PRESENT days in November get a later last punch-out, so the attendance ENGINE finds
-- overtime past the shift end and writes the overtime records itself. Nothing here writes an
-- overtime record or a pay figure; `seed_mock_overtime_apply.py` recalculates the days and then
-- decides the older records through the API (approve in full, approve less, reject, leave pending).
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_company_mock_overtime.sql
--   .venv/bin/python scripts/seed_mock_overtime_apply.py        # API up
--
-- Only the last punch-out of a day written by a mock seed is moved, and its original time is kept in
-- `raw_payload.mock_overtime_seed.original_time`, so it can be put back. A moved punch is never
-- moved again (re-runs are no-ops), and locked days (closed periods) are never touched.
--
-- Shape: about one working day in five for an OT-eligible shift, 35 to 150 minutes past the
-- scheduled end; weekdays only (weekly-off and holiday work is a separate case).

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

CREATE TEMP TABLE _pick ON COMMIT DROP AS
SELECT d.id AS day_id, d.employee_id, d.scheduled_end,
       (SELECT p.id FROM punch p
         WHERE p.employee_id = d.employee_id AND p.direction = 'OUT'
           AND p.reference LIKE 'MOCK-SEED%'
           AND (p.punch_time AT TIME ZONE d.timezone)::date = d.attendance_date
         ORDER BY p.punch_time DESC LIMIT 1) AS punch_id,
       35 + abs(hashtext('ot' || d.id::text)) % 116 AS extra_min
FROM attendance_day d JOIN _co ON _co.company_id = d.company_id
WHERE d.attendance_status = 'PRESENT' AND NOT d.is_locked
  AND d.attendance_date BETWEEN DATE '2026-11-02' AND CURRENT_DATE - 1
  AND d.calendar_day_type = 'WORKING'
  AND d.scheduled_end IS NOT NULL AND d.actual_last_out IS NOT NULL
  AND d.overtime_policy_version_id IS NOT NULL
  AND abs(hashtext('otpick' || d.id::text)) % 5 = 0
  AND NOT EXISTS (SELECT 1 FROM overtime_record o WHERE o.attendance_day_id = d.id);

UPDATE punch p
SET punch_time = pk.scheduled_end + make_interval(mins => pk.extra_min),
    raw_payload = COALESCE(p.raw_payload, '{}'::jsonb) || jsonb_build_object(
      'mock_overtime_seed', jsonb_build_object('original_time', p.punch_time))
FROM _pick pk
WHERE p.id = pk.punch_id AND pk.punch_id IS NOT NULL
  AND NOT (COALESCE(p.raw_payload, '{}'::jsonb) ? 'mock_overtime_seed');

SELECT count(*) AS punches_moved, min(extra_min), max(extra_min)
FROM _pick WHERE punch_id IS NOT NULL;

COMMIT;
