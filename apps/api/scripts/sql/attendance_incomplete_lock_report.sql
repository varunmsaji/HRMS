-- H-02 / H-07 - what the zero-punch rule changes. READ ONLY: SELECT only.
-- Run per environment BEFORE the engine change reaches recalculation, as the schema owner:
--   psql "$MIGRATIONS_DATABASE_URL" -f scripts/sql/attendance_incomplete_lock_report.sql
--
-- H-02: a day with NO punches at all (an expected working day with no leave, on-duty or
-- regularization) is absent at period lock whatever `incomplete_at_lock_behaviour` says - TREAT_PRESENT
-- never pays a no-show. A day with at least one punch (an IN-only day included) follows the policy.
-- H-07: a half-day-leave day with no punch keeps its worked half pending until the lock (it used to be
-- lost at once), then absent; KEEP_INCOMPLETE blocks the close until HR resolves it.
-- Locked periods never change: they are reported so HR can decide on a separate, audited correction.
-- "No punches" = the day's snapshot owns no punch ids (rows that predate it: no recorded IN or OUT).

\echo '== 1. LOCKED days a TREAT_PRESENT policy paid although the employee never punched (historical)'
SELECT d.company_id, d.employee_id, d.attendance_date, d.attendance_status, d.paid_day_fraction,
       d.lop_fraction, d.leave_fraction, v.incomplete_at_lock_behaviour
FROM attendance_day d
JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
WHERE d.is_locked AND d.attendance_status = 'INCOMPLETE'
  AND d.paid_day_fraction > COALESCE(d.leave_fraction, 0)
  AND (
        COALESCE(d.computation_snapshot -> 'inputs' -> 'punch_ids', '[]'::jsonb) = '[]'::jsonb
        AND d.actual_first_in IS NULL AND d.actual_last_out IS NULL
      )
ORDER BY d.company_id, d.attendance_date, d.employee_id;

\echo '== 2. Same, per company'
SELECT d.company_id, count(*) AS locked_no_show_days_paid,
       sum(d.paid_day_fraction - COALESCE(d.leave_fraction, 0)) AS paid_day_fractions_to_review
FROM attendance_day d
WHERE d.is_locked AND d.attendance_status = 'INCOMPLETE'
  AND d.paid_day_fraction > COALESCE(d.leave_fraction, 0)
  AND COALESCE(d.computation_snapshot -> 'inputs' -> 'punch_ids', '[]'::jsonb) = '[]'::jsonb
  AND d.actual_first_in IS NULL AND d.actual_last_out IS NULL
GROUP BY d.company_id ORDER BY d.company_id;

\echo '== 3. UNLOCKED INCOMPLETE days that will now be absent at lock, by the policy setting'
SELECT d.company_id, v.incomplete_at_lock_behaviour AS configured,
       count(*) FILTER (WHERE COALESCE(d.computation_snapshot -> 'inputs' -> 'punch_ids', '[]'::jsonb) = '[]'::jsonb
                          AND d.actual_first_in IS NULL AND d.actual_last_out IS NULL) AS no_punch_days_absent_at_lock,
       count(*) FILTER (WHERE NOT (COALESCE(d.computation_snapshot -> 'inputs' -> 'punch_ids', '[]'::jsonb) = '[]'::jsonb
                          AND d.actual_first_in IS NULL AND d.actual_last_out IS NULL)) AS days_with_a_punch_follow_the_policy
FROM attendance_day d
JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
WHERE NOT d.is_locked AND d.attendance_status = 'INCOMPLETE'
GROUP BY d.company_id, v.incomplete_at_lock_behaviour
ORDER BY d.company_id, configured;

\echo '== 4. UNLOCKED half-day-leave days with no punch: now PENDING until the lock (were loss of pay at once)'
SELECT d.company_id, d.employee_id, d.attendance_date, d.attendance_status, d.paid_day_fraction,
       d.lop_fraction, d.leave_fraction
FROM attendance_day d
WHERE NOT d.is_locked AND d.leave_fraction > 0 AND d.leave_fraction < 1
  AND d.worked_minutes = 0 AND d.actual_first_in IS NULL AND d.actual_last_out IS NULL
  AND d.attendance_status <> 'INCOMPLETE'
ORDER BY d.company_id, d.attendance_date, d.employee_id;

\echo '== 5. KEEP_INCOMPLETE versions with incomplete days: these block the period close until resolved'
SELECT d.company_id, count(*) AS blocking_incomplete_days
FROM attendance_day d
JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
WHERE NOT d.is_locked AND d.attendance_status = 'INCOMPLETE'
  AND v.incomplete_at_lock_behaviour = 'KEEP_INCOMPLETE'
GROUP BY d.company_id ORDER BY d.company_id;
