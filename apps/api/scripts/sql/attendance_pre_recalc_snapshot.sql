-- Pre-recalculation snapshot (independent review, section 8: "no real preview"). READ ONLY.
-- Run BEFORE any historical recalculation, and again AFTER; diff the two files per company and
-- explain every difference against the change table in
-- docs/audits/ATTENDANCE_RULES_REMEDIATION_2026-11-16.md section 6.
--
--   psql "$MIGRATIONS_DATABASE_URL" -v company_id=<uuid> -v date_from=2026-11-01 \
--        -v date_to=2026-11-30 -f scripts/sql/attendance_pre_recalc_snapshot.sql > before.tsv
--
-- Unlocked days only: locked days are never recalculated. One row per employee-date.
\pset format unaligned
\pset fieldsep '\t'
\pset footer off
SELECT d.employee_id, d.attendance_date, d.attendance_status, d.paid_day_fraction,
       d.lop_fraction, d.ot_minutes_detected, d.ot_minutes_approved, d.ot_pending,
       d.late_minutes, d.early_departure_minutes, d.engine_version
FROM attendance_day d
WHERE d.company_id = :'company_id'::uuid
  AND NOT d.is_locked
  AND d.attendance_date BETWEEN :'date_from'::date AND :'date_to'::date
ORDER BY d.employee_id, d.attendance_date;
