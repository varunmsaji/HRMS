-- H-01 (owner decision) - hour bands that do not cover every minute count. READ ONLY: SELECT only.
-- Run per environment BEFORE the stricter engine behaviour reaches recalculation, as the schema owner
-- (cross-tenant):
--   psql "$MIGRATIONS_DATABASE_URL" -f scripts/sql/attendance_hour_band_gap_report.sql
--
-- The rule: hour bands start at minute 0, follow each other with no gap and no overlap, and the last
-- band is open-ended. Publication now refuses anything else, and the engine returns CONFIG_ERROR
-- (never PRESENT) for worked minutes no band covers. Versions published BEFORE the rule are never
-- edited; HR corrects them by publishing a new version. An unlocked day on such a version becomes
-- CONFIG_ERROR when recalculated, and a CONFIG_ERROR day blocks period close until it is fixed.
-- Locked days are listed for information only: they never change.
--
-- Late-mark and early-departure bands are NOT checked: a gap there means "no mark".

\echo '== 1. Policy versions whose hour bands do not cover every minute count'
WITH b AS (
  SELECT policy_version_id, min_minutes, max_minutes,
         lag(max_minutes) OVER w AS prev_max,
         row_number() OVER w AS rn,
         count(*) OVER (PARTITION BY policy_version_id) AS n
  FROM attendance_policy_hour_band
  WINDOW w AS (PARTITION BY policy_version_id ORDER BY min_minutes)
), problems AS (
  SELECT policy_version_id, 'first band does not start at 0 (starts at ' || min_minutes || ')' AS problem
  FROM b WHERE rn = 1 AND min_minutes <> 0
  UNION ALL
  SELECT policy_version_id,
         'gap: minutes ' || (prev_max + 1) || ' to ' || (min_minutes - 1) || ' are not covered'
  FROM b WHERE rn > 1 AND prev_max IS NOT NULL AND min_minutes > prev_max + 1
  UNION ALL
  SELECT policy_version_id,
         'overlap: band starting at ' || min_minutes || ' begins at or before minute ' || prev_max
  FROM b WHERE rn > 1 AND prev_max IS NOT NULL AND min_minutes <= prev_max
  UNION ALL
  SELECT policy_version_id,
         'open-ended band is followed by another band starting at ' || min_minutes
  FROM b WHERE rn > 1 AND prev_max IS NULL
  UNION ALL
  SELECT policy_version_id, 'last band is bounded (ends at ' || max_minutes || ')'
  FROM b WHERE rn = n AND max_minutes IS NOT NULL
)
SELECT v.company_id, p.name AS policy, v.id AS policy_version_id, v.version, v.status,
       v.effective_from, v.effective_to, pr.problem
FROM problems pr
JOIN attendance_policy_version v ON v.id = pr.policy_version_id AND v.deleted_at IS NULL
JOIN attendance_policy p ON p.id = v.policy_id
ORDER BY v.company_id, p.name, v.version, pr.problem;

\echo '== 2. Same, per company, with the days that sit on those PUBLISHED versions'
WITH b AS (
  SELECT policy_version_id, min_minutes, max_minutes,
         lag(max_minutes) OVER w AS prev_max,
         row_number() OVER w AS rn,
         count(*) OVER (PARTITION BY policy_version_id) AS n
  FROM attendance_policy_hour_band
  WINDOW w AS (PARTITION BY policy_version_id ORDER BY min_minutes)
), bad AS (
  SELECT DISTINCT policy_version_id FROM b
  WHERE (rn = 1 AND min_minutes <> 0)
     OR (rn > 1 AND (prev_max IS NULL OR min_minutes <> prev_max + 1))
     OR (rn = n AND max_minutes IS NOT NULL)
)
SELECT v.company_id,
       count(DISTINCT v.id) AS invalid_versions,
       count(DISTINCT v.id) FILTER (WHERE v.status = 'PUBLISHED') AS published_invalid_versions,
       count(d.id) FILTER (WHERE NOT d.is_locked) AS unlocked_days_on_them,
       count(d.id) FILTER (WHERE d.is_locked) AS locked_days_on_them
FROM bad
JOIN attendance_policy_version v ON v.id = bad.policy_version_id AND v.deleted_at IS NULL
LEFT JOIN attendance_day d ON d.attendance_policy_version_id = v.id
GROUP BY v.company_id
ORDER BY v.company_id;

\echo '== 3. Unlocked days a recalculation would turn into CONFIG_ERROR (candidates)'
\echo '--    worked_minutes is a close proxy: the engine looks bands up on worked minutes plus any'
\echo '--    grace or mark credit, so a day within a few minutes of a gap edge may differ.'
SELECT d.company_id, d.employee_id, d.attendance_date, d.attendance_status, d.paid_day_fraction,
       d.worked_minutes, d.attendance_policy_version_id, d.engine_version
FROM attendance_day d
JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
WHERE NOT d.is_locked AND d.worked_minutes > 0
  AND NOT EXISTS (
    SELECT 1 FROM attendance_policy_hour_band hb
    WHERE hb.policy_version_id = v.id
      AND hb.min_minutes <= d.worked_minutes
      AND (hb.max_minutes IS NULL OR d.worked_minutes <= hb.max_minutes)
  )
ORDER BY d.company_id, d.attendance_date, d.employee_id;

\echo '== 4. Locked days with worked minutes no band covers (for information; they never change)'
SELECT d.company_id, count(*) AS locked_days_with_uncovered_minutes
FROM attendance_day d
JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
WHERE d.is_locked AND d.worked_minutes > 0
  AND NOT EXISTS (
    SELECT 1 FROM attendance_policy_hour_band hb
    WHERE hb.policy_version_id = v.id
      AND hb.min_minutes <= d.worked_minutes
      AND (hb.max_minutes IS NULL OR d.worked_minutes <= hb.max_minutes)
  )
GROUP BY d.company_id
ORDER BY d.company_id;
