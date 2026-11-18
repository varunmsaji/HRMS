-- R-2 (owner decision D-01b) - late / early mark credit: impact report, SQL part. READ ONLY.
-- Run per environment BEFORE any historical recalculation, as the schema owner (cross-tenant):
--   psql "$MIGRATIONS_DATABASE_URL" -f scripts/sql/late_mark_band_impact_report.sql
-- The per-day before/after comparison (what the corrected engine WOULD give) is the companion
-- script `scripts/attendance_mark_credit_dry_run.py`; this file lists the policies and the
-- candidate days, from stored columns only. Nothing here or there writes, recalculates or edits a
-- policy version, and locked days are never listed as changing.
--
-- The rule (engine 16, `calculation.grace_band_credit_detail`), per day and policy version:
--   plain grace  = min(raw_late, grace_in) + min(raw_early, grace_out)        (separate, added)
--   qualifying_x = minutes beyond the grace at end x, when a mark band (NONE / LATE /
--                  EARLY_DEPARTURE) judges them
--   beyond-grace credit = min(qualifying_late + qualifying_early, mark_credit_ceiling_minutes)
-- The ceiling is a setting of the policy version (default 59, 0-120; 0 = no beyond-grace credit).
-- Stored attendance_day.late_minutes / early_departure_minutes ARE the minutes beyond the grace.
-- Requires the schema of migration 20261116120000 (the ceiling column).

\echo '== 1. Policy versions with a BROAD mark band: wider than the version ceiling, or open-ended'
\echo '--    (a band covers stored late/early minutes, i.e. minutes beyond the grace)'
WITH broad AS (
  SELECT b.policy_version_id, 'LATE' AS side, b.min_minutes, b.max_minutes, b.classification
  FROM attendance_policy_late_band b
  JOIN attendance_policy_version v ON v.id = b.policy_version_id
  WHERE b.classification IN ('NONE', 'LATE')
    AND (b.max_minutes IS NULL OR b.max_minutes > v.mark_credit_ceiling_minutes)
  UNION ALL
  SELECT b.policy_version_id, 'EARLY', b.min_minutes, b.max_minutes, b.classification
  FROM attendance_policy_early_departure_band b
  JOIN attendance_policy_version v ON v.id = b.policy_version_id
  WHERE b.classification IN ('NONE', 'EARLY_DEPARTURE')
    AND (b.max_minutes IS NULL OR b.max_minutes > v.mark_credit_ceiling_minutes)
)
SELECT v.company_id, p.name AS policy, v.id AS policy_version_id, v.version, v.status,
       v.effective_from, v.effective_to, v.grace_in_minutes, v.grace_out_minutes,
       v.mark_credit_ceiling_minutes AS ceiling,
       br.side, br.classification, br.min_minutes, br.max_minutes
FROM broad br
JOIN attendance_policy_version v ON v.id = br.policy_version_id AND v.deleted_at IS NULL
JOIN attendance_policy p ON p.id = v.policy_id
ORDER BY v.company_id, p.name, v.version, br.side, br.min_minutes;

\echo '== 2. COMPANIES WITH BROAD LATE/EARLY MARK BANDS (list 1 summarised; the separate company list)'
WITH broad_versions AS (
  SELECT DISTINCT b.policy_version_id
  FROM attendance_policy_late_band b
  JOIN attendance_policy_version v ON v.id = b.policy_version_id
  WHERE b.classification IN ('NONE', 'LATE')
    AND (b.max_minutes IS NULL OR b.max_minutes > v.mark_credit_ceiling_minutes)
  UNION
  SELECT DISTINCT b.policy_version_id
  FROM attendance_policy_early_departure_band b
  JOIN attendance_policy_version v ON v.id = b.policy_version_id
  WHERE b.classification IN ('NONE', 'EARLY_DEPARTURE')
    AND (b.max_minutes IS NULL OR b.max_minutes > v.mark_credit_ceiling_minutes)
)
SELECT v.company_id,
       count(DISTINCT v.id) AS broad_policy_versions,
       count(DISTINCT v.id) FILTER (WHERE v.status = 'PUBLISHED') AS published_versions,
       count(d.id) FILTER (WHERE NOT d.is_locked) AS unlocked_days_on_them,
       count(d.id) FILTER (WHERE d.is_locked) AS locked_days_on_them
FROM broad_versions bv
JOIN attendance_policy_version v ON v.id = bv.policy_version_id AND v.deleted_at IS NULL
LEFT JOIN attendance_day d ON d.attendance_policy_version_id = v.id
GROUP BY v.company_id
ORDER BY v.company_id;

\echo '== 3. Unlocked days whose marks the combined ceiling can change (candidates, from stored columns)'
\echo '--    qualifying = stored minutes beyond grace at an end that a mark band judges'
\echo '--    both_ends  = BOTH ends qualify: they now share ONE ceiling (the per-end rule gave each its own)'
\echo '--    over_ceiling = qualifying exceeds the version ceiling: the hours decide the rest'
WITH marked AS (
  SELECT d.company_id, d.employee_id, d.attendance_date, d.attendance_status, d.paid_day_fraction,
         d.worked_minutes, d.engine_version, d.attendance_policy_version_id,
         v.grace_in_minutes, v.grace_out_minutes, v.mark_credit_ceiling_minutes AS ceiling,
         CASE WHEN d.late_classification IN ('NONE', 'LATE') THEN d.late_minutes ELSE 0 END
           AS qualifying_late,
         CASE WHEN d.early_departure_classification IN ('NONE', 'EARLY_DEPARTURE')
              THEN d.early_departure_minutes ELSE 0 END AS qualifying_early
  FROM attendance_day d
  JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
  WHERE NOT d.is_locked AND d.worked_minutes > 0
)
SELECT company_id, employee_id, attendance_date, attendance_status, paid_day_fraction,
       worked_minutes, qualifying_late, qualifying_early,
       qualifying_late + qualifying_early AS qualifying_total, ceiling,
       LEAST(qualifying_late + qualifying_early, ceiling) AS beyond_grace_credit,
       (qualifying_late > 0 AND qualifying_early > 0) AS both_ends,
       (qualifying_late + qualifying_early > ceiling) AS over_ceiling, engine_version
FROM marked
WHERE qualifying_late + qualifying_early > 0
ORDER BY company_id, attendance_date, employee_id;

\echo '== 4. Same, per company: how many unlocked marked days, how many share the ceiling'
WITH marked AS (
  SELECT d.company_id,
         CASE WHEN d.late_classification IN ('NONE', 'LATE') THEN d.late_minutes ELSE 0 END AS q_l,
         CASE WHEN d.early_departure_classification IN ('NONE', 'EARLY_DEPARTURE')
              THEN d.early_departure_minutes ELSE 0 END AS q_e,
         v.mark_credit_ceiling_minutes AS ceiling
  FROM attendance_day d
  JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
  WHERE NOT d.is_locked AND d.worked_minutes > 0
)
SELECT company_id,
       count(*) FILTER (WHERE q_l + q_e > 0) AS unlocked_marked_days,
       count(*) FILTER (WHERE q_l > 0 AND q_e > 0) AS both_ends_days,
       count(*) FILTER (WHERE q_l + q_e > ceiling) AS over_ceiling_days
FROM marked
GROUP BY company_id
HAVING count(*) FILTER (WHERE q_l + q_e > 0) > 0
ORDER BY company_id;

\echo '== 5. Policies with NO late and NO early bands (the one-minute cliff of engine 14 remains)'
SELECT v.company_id, p.name AS policy, v.id AS policy_version_id, v.version, v.status
FROM attendance_policy_version v
JOIN attendance_policy p ON p.id = v.policy_id
WHERE v.deleted_at IS NULL AND v.status = 'PUBLISHED'
  AND NOT EXISTS (SELECT 1 FROM attendance_policy_late_band b WHERE b.policy_version_id = v.id)
  AND NOT EXISTS (SELECT 1 FROM attendance_policy_early_departure_band b
                  WHERE b.policy_version_id = v.id)
ORDER BY v.company_id, p.name, v.version;
