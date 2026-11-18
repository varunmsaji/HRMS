-- R11 (P-04) - work before a fixed shift's scheduled start. READ ONLY: SELECT only.
-- Run per environment BEFORE the P-04 engine change reaches recalculation, as the schema owner:
--   psql "$MIGRATIONS_DATABASE_URL" -f scripts/sql/attendance_pre_start_work_report.sql
--
-- P-04 (owner decision, option B): when an employee has NO credited work inside the scheduled shift
-- window but has worked one or more sessions wholly BEFORE the scheduled start, that time counts toward
-- the day's hour-band classification (capped at the shift's net scheduled minutes). It is never
-- overtime or comp-off, earns no lateness relief, and the day is flagged WORKED_OUTSIDE_SHIFT for HR.
-- Today such a day has zero credited minutes and is ABSENT (or INCOMPLETE). Locked days are listed
-- for information only and never change.
--
-- Stored columns only: a day whose first-in and last-out both fall at or before the scheduled start
-- and that credited no worked minutes. A day with an extra session inside the shift is not a candidate
-- (it already has credited work). The per-day before/after (what the corrected engine WOULD give) is the
-- companion script scripts/attendance_mark_credit_dry_run.py --all-unlocked-days.

\echo '== 1. Days with punches wholly before the scheduled start and no credited work'
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked, d.attendance_status,
       d.paid_day_fraction, d.worked_minutes, d.scheduled_start, d.actual_first_in, d.actual_last_out,
       d.engine_version
FROM attendance_day d
WHERE d.worked_minutes = 0
  AND d.actual_first_in IS NOT NULL AND d.actual_last_out IS NOT NULL
  AND d.scheduled_start IS NOT NULL
  AND d.actual_last_out <= d.scheduled_start
ORDER BY d.company_id, d.attendance_date, d.employee_id;

\echo '== 2. Per company: unlocked days P-04 can change, locked days that stay as they are'
SELECT d.company_id,
       count(*) FILTER (WHERE NOT d.is_locked) AS unlocked_days,
       count(*) FILTER (WHERE NOT d.is_locked AND d.attendance_status = 'ABSENT') AS unlocked_absent,
       count(*) FILTER (WHERE d.is_locked) AS locked_days,
       count(*) FILTER (WHERE d.is_locked AND d.attendance_status = 'ABSENT') AS locked_absent
FROM attendance_day d
WHERE d.worked_minutes = 0
  AND d.actual_first_in IS NOT NULL AND d.actual_last_out IS NOT NULL
  AND d.scheduled_start IS NOT NULL
  AND d.actual_last_out <= d.scheduled_start
GROUP BY d.company_id
ORDER BY d.company_id;

\echo '== 3. Days already carrying the WORKED_OUTSIDE_SHIFT flag (after the change; empty before it)'
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked, d.attendance_status,
       d.paid_day_fraction, d.computation_snapshot -> 'worked_outside_shift' AS detail
FROM attendance_day d
WHERE d.computation_snapshot ? 'worked_outside_shift'
ORDER BY d.company_id, d.attendance_date, d.employee_id;
