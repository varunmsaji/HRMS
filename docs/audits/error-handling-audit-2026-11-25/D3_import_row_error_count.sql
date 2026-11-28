-- D3 (read-only): how many bulk-import row errors stored raw exception text?
--
-- Before the Phase 1 fix (commit 37748aa), an unexpected exception in an import row was saved as
-- str(exc) in employee_import_row_error.error_message with error_code = 'IMPORT_ROW_FAILED', and
-- GET /v1/employee-imports/{id}/errors returned it. Rows written after the fix all carry the fixed
-- text below, so they are excluded.
--
-- The table has FORCE ROW LEVEL SECURITY (policy: company_id = app.company_id). Run this as a role
-- that bypasses RLS (the database owner / a superuser), otherwise it returns 0 rows. Nothing here
-- writes: every statement is a SELECT.

-- 1. How many, per company, and the date range.
SELECT company_id,
       count(*)                AS affected_rows,
       count(DISTINCT batch_id) AS batches,
       min(created_at)         AS oldest,
       max(created_at)         AS newest
FROM   employee_import_row_error
WHERE  error_code = 'IMPORT_ROW_FAILED'
  AND  error_message <> 'This row could not be imported because of an unexpected problem.'
GROUP  BY company_id
ORDER  BY affected_rows DESC;

-- 2. Of those, how many look like they carry technical detail (SQL, driver or schema text).
--    Rows matching nothing here are probably plain Python messages (e.g. a KeyError name):
--    still worth clearing, but lower risk.
SELECT count(*) FILTER (WHERE error_message ~* '\[SQL:|SELECT |INSERT |UPDATE |violates|constraint|relation "|column "|sqlalchemy|asyncpg|psycopg|Traceback|\.py') AS looks_technical,
       count(*)                                                                                                                                       AS total
FROM   employee_import_row_error
WHERE  error_code = 'IMPORT_ROW_FAILED'
  AND  error_message <> 'This row could not be imported because of an unexpected problem.';

-- 3. A few examples to eyeball (message only, first 160 chars; no raw_row, which holds the
--    uploaded person's data).
SELECT id, company_id, created_at, left(error_message, 160) AS message_start
FROM   employee_import_row_error
WHERE  error_code = 'IMPORT_ROW_FAILED'
  AND  error_message <> 'This row could not be imported because of an unexpected problem.'
ORDER  BY created_at DESC
LIMIT  20;

-- If you later decide to clean up (NOT done here, needs your approval), the change would be:
--   UPDATE employee_import_row_error
--      SET error_message = 'This row could not be imported because of an unexpected problem.'
--    WHERE error_code = 'IMPORT_ROW_FAILED'
--      AND error_message <> 'This row could not be imported because of an unexpected problem.';
