-- READ-ONLY. Impact of SC-01..SC-04 (docs/audits/SHIFT_CREATION_VALIDATION_AUDIT_2026-11-17.md) on
-- data that already exists. Changes nothing. Run as the schema owner (row-level security would hide
-- rows from any other role):
--   psql "$MIGRATIONS_DATABASE_URL" -f scripts/sql/shift_name_and_break_rules_impact_report.sql
--
-- 1. names: the two things migration 20261117090000 stops on (live shifts only).
-- 2. breaks: stored break configurations the new rules would refuse if they were saved again.
--    Nothing stored is rewritten or re-validated by the code change; these rows matter only when
--    someone edits and re-saves the breaks of a draft, or publishes a draft that holds them.

\echo '== 1a. live shifts with a blank name (migration stops on these)'
SELECT company_id, id AS shift_id, code, is_active, quote_literal(name) AS name
FROM shift WHERE deleted_at IS NULL AND name ~ '^[[:space:]]*$'
ORDER BY company_id, id;

\echo '== 1b. live shifts sharing a name, ignoring case and surrounding spaces (migration stops on these)'
SELECT company_id, lower(btrim(name)) AS normalised_name, count(*) AS shifts,
       string_agg(id::text || ' ' || coalesce(code, '-') || CASE WHEN is_active THEN '' ELSE ' (inactive)' END,
                  '; ' ORDER BY created_at, id) AS shifts_detail
FROM shift WHERE deleted_at IS NULL
GROUP BY company_id, lower(btrim(name)) HAVING count(*) > 1
ORDER BY company_id, normalised_name;

\echo '== 1c. info only: live shifts whose stored name has surrounding spaces (left unchanged, D-2)'
SELECT company_id, id AS shift_id, code, quote_literal(name) AS name
FROM shift WHERE deleted_at IS NULL AND name <> btrim(name) AND name !~ '^[[:space:]]*$'
ORDER BY company_id, id;

\echo '== 2. stored breaks that fail a duration rule (SC-04), by version status'
WITH b AS (
  SELECT sb.*, sv.status, sv.shift_id, sv.shift_type, sv.effective_from
  FROM shift_break sb
  JOIN shift_version sv ON sv.id = sb.shift_version_id AND sv.deleted_at IS NULL
),
w AS (
  SELECT b.*,
         CASE WHEN break_kind = 'FIXED_WINDOW' AND start_time IS NOT NULL AND end_time IS NOT NULL
              THEN ((extract(epoch FROM end_time - start_time) / 60)::int + 1440) % 1440 END AS fixed_span
  FROM b
)
SELECT company_id, shift_id, shift_version_id, status, name, break_kind,
       CASE
         WHEN max_minutes IS NOT NULL AND max_minutes < 1 THEN 'max_minutes < 1'
         WHEN min_minutes IS NOT NULL AND max_minutes IS NOT NULL AND min_minutes > max_minutes THEN 'min > max'
         WHEN scheduled_minutes IS NOT NULL AND max_minutes IS NOT NULL AND scheduled_minutes > max_minutes THEN 'scheduled > max'
         WHEN scheduled_minutes IS NOT NULL AND min_minutes IS NOT NULL AND scheduled_minutes < min_minutes THEN 'scheduled < min'
         WHEN scheduled_minutes > 0 AND fixed_span IS NOT NULL AND scheduled_minutes > CASE WHEN fixed_span = 0 THEN 1440 ELSE fixed_span END THEN 'scheduled > fixed window'
       END AS violated_rule
FROM w
WHERE (max_minutes IS NOT NULL AND max_minutes < 1)
   OR (min_minutes IS NOT NULL AND max_minutes IS NOT NULL AND min_minutes > max_minutes)
   OR (scheduled_minutes IS NOT NULL AND max_minutes IS NOT NULL AND scheduled_minutes > max_minutes)
   OR (scheduled_minutes IS NOT NULL AND min_minutes IS NOT NULL AND scheduled_minutes < min_minutes)
   OR (scheduled_minutes > 0 AND fixed_span IS NOT NULL
       AND scheduled_minutes > CASE WHEN fixed_span = 0 THEN 1440 ELSE fixed_span END)
ORDER BY status, company_id, shift_id;

\echo '== 3. stored flexible-duration breaks whose window is not wholly inside the shift window (SC-03)'
WITH f AS (
  SELECT sb.company_id, sv.shift_id, sv.id AS version_id, sv.status, sv.shift_type, sb.name,
         sb.window_start, sb.window_end,
         CASE sv.shift_type WHEN 'FIXED' THEN sv.start_time WHEN 'FLEXIBLE' THEN sv.window_start END AS o_start,
         CASE sv.shift_type
           WHEN 'FIXED' THEN sv.end_time
           WHEN 'FLEXIBLE' THEN sv.window_end + make_interval(mins => least(coalesce(sv.required_minutes, 0), 1439))
         END AS o_end
  FROM shift_break sb
  JOIN shift_version sv ON sv.id = sb.shift_version_id AND sv.deleted_at IS NULL
  WHERE sb.break_kind = 'FLEXIBLE_DURATION' AND sv.shift_type IN ('FIXED', 'FLEXIBLE')
),
m AS (
  SELECT f.*,
    CASE WHEN ((extract(epoch FROM o_end - o_start) / 60)::int % 1440 + 1440) % 1440 = 0 THEN 1440
         ELSE ((extract(epoch FROM o_end - o_start) / 60)::int % 1440 + 1440) % 1440 END AS outer_dur,
    ((extract(epoch FROM window_start - o_start) / 60)::int % 1440 + 1440) % 1440 AS inner_off,
    CASE WHEN ((extract(epoch FROM window_end - window_start) / 60)::int % 1440 + 1440) % 1440 = 0 THEN 1440
         ELSE ((extract(epoch FROM window_end - window_start) / 60)::int % 1440 + 1440) % 1440 END AS inner_dur
  FROM f WHERE o_start IS NOT NULL AND o_end IS NOT NULL AND window_start IS NOT NULL AND window_end IS NOT NULL
)
SELECT company_id, shift_id, version_id, status, shift_type, name, window_start, window_end, o_start AS shift_from, o_end AS shift_to
FROM m WHERE inner_off + inner_dur > outer_dur
ORDER BY status, company_id, shift_id;

\echo '== 4. context: shifts / versions / breaks counted'
SELECT (SELECT count(*) FROM shift WHERE deleted_at IS NULL) AS live_shifts,
       (SELECT count(*) FROM shift_version WHERE deleted_at IS NULL) AS versions,
       (SELECT count(*) FROM shift_version WHERE deleted_at IS NULL AND status = 'PUBLISHED') AS published_versions,
       (SELECT count(*) FROM shift_break) AS breaks,
       (SELECT count(*) FROM shift_break WHERE break_kind = 'FLEXIBLE_DURATION') AS flexible_breaks;
