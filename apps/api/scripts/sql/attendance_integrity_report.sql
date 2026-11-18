-- Attendance / overtime historical integrity report (AC-01, AC-03, AC-04). READ ONLY: SELECT only.
-- Run per environment:  psql "$DATABASE_URL" -f scripts/sql/attendance_integrity_report.sql
-- Every query lists records for review; none changes data. Locked rows are reported, never fixed
-- here - a locked or payroll-finalised period needs a controlled correction (see
-- docs/audits/ATTENDANCE_PAYROLL_INTEGRITY_CHECK.md).

\echo '== 1. Approved overtime greater than detected (AC-01)'
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked, d.locked_period_id,
       d.ot_minutes_detected, d.ot_minutes_approved
FROM attendance_day d
WHERE d.ot_minutes_approved > d.ot_minutes_detected
ORDER BY d.company_id, d.attendance_date;

\echo '== 2. Day class or policy version differs from the paid overtime record (AC-01)'
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked,
       d.ot_day_class AS day_class, r.day_class AS record_class,
       d.overtime_policy_version_id = r.overtime_policy_version_id AS same_policy_version,
       d.ot_minutes_approved AS day_approved, r.minutes_approved AS record_approved, r.status
FROM attendance_day d
JOIN overtime_record r ON r.attendance_day_id = d.id
WHERE r.status IN ('APPROVED', 'AUTO_APPROVED')
  AND d.attendance_status NOT IN ('ON_DUTY')
  AND NOT (d.attendance_status = 'LEAVE' AND d.leave_fraction >= 1)
  AND (d.ot_minutes_approved <> r.minutes_approved
       OR (r.minutes_approved > 0 AND (d.ot_day_class IS DISTINCT FROM r.day_class
           OR d.overtime_policy_version_id IS DISTINCT FROM r.overtime_policy_version_id)))
ORDER BY d.company_id, d.attendance_date;

\echo '== 3. Comp-off credited beyond what the punches support (AC-01)'
SELECT r.company_id, r.employee_id, r.attendance_date, d.is_locked, r.status,
       r.comp_off_minutes, r.minutes_approved, d.ot_minutes_detected
FROM overtime_record r
JOIN attendance_day d ON d.id = r.attendance_day_id
WHERE r.status IN ('APPROVED', 'AUTO_APPROVED')
  AND r.comp_off_minutes > 0
  AND (r.comp_off_minutes > d.ot_minutes_detected OR r.minutes_approved > d.ot_minutes_detected)
ORDER BY r.company_id, r.attendance_date;

\echo '== 4. Incomplete days that still carry payable overtime (AC-04)'
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked,
       d.paid_day_fraction, d.lop_fraction, d.ot_minutes_approved, r.status
FROM attendance_day d
LEFT JOIN overtime_record r ON r.attendance_day_id = d.id
WHERE d.attendance_status = 'INCOMPLETE'
  AND (d.ot_minutes_approved > 0 OR r.status IN ('APPROVED', 'AUTO_APPROVED'))
ORDER BY d.company_id, d.attendance_date;

\echo '== 5. Locked days resolved as absent that still carry approved overtime (AC-04)'
SELECT d.company_id, d.employee_id, d.attendance_date, d.locked_period_id,
       d.lop_fraction, d.ot_minutes_approved
FROM attendance_day d
WHERE d.is_locked AND d.attendance_status = 'INCOMPLETE'
  AND d.lop_fraction >= 1 AND d.ot_minutes_approved > 0;

\echo '== 6. Overtime record rows per day (must be 1) and orphaned records'
SELECT attendance_day_id, count(*) FROM overtime_record GROUP BY 1 HAVING count(*) > 1;

\echo '== 7. Approved leave with no day rows at all (R-1: every day was released before the fix)'
\echo '--    Its half-day marker, if it had one, was lost with the rows; the half is unknown for these.'
SELECT a.company_id, a.employee_id, a.id AS leave_application_id, a.start_date, a.end_date,
       a.total_days, a.half_day
FROM leave_application a
WHERE a.status = 'APPROVED'
  AND NOT EXISTS (SELECT 1 FROM leave_application_day d WHERE d.leave_application_id = a.id)
ORDER BY a.company_id, a.start_date;

\echo '== Summary counts'
SELECT
  (SELECT count(*) FROM attendance_day) AS attendance_days,
  (SELECT count(*) FROM attendance_day WHERE is_locked) AS locked_days,
  (SELECT count(*) FROM overtime_record) AS overtime_records,
  (SELECT count(*) FROM leave_application WHERE status = 'APPROVED') AS approved_leave;
