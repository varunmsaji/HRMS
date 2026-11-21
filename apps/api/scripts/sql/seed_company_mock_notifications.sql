-- Mock notification inbox for the company behind varunmsaji@gmail.com (Varun Company), LOCAL DEV ONLY.
-- Every row is derived from a request or pay run that really exists, in the words the app itself
-- uses (`notification/approvals.py`), so an inbox item always opens something real:
--   * leave, attendance-correction and overtime requests still waiting -> the reviewer is told;
--   * those already decided -> the employee is told the outcome;
--   * the last two paid pay runs -> each employee's "payslip available".
--
-- Run as the schema owner (RLS is bypassed by `hrms`, never by `hrms_app`):
--   psql "$MIGRATIONS_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/sql/seed_company_mock_notifications.sql
--
-- Idempotent: deterministic ids and the app's own `dedupe_key`s; it never changes or removes a
-- notification it did not write. Items older than three days are marked read, newer ones unread.

BEGIN;

CREATE TEMP TABLE _co ON COMMIT DROP AS
SELECT DISTINCT uc.company_id, u.id AS admin_user_id
FROM "user" u JOIN user_company uc ON uc.user_id = u.id
WHERE u.email = 'varunmsaji@gmail.com';

DO $$ BEGIN
  IF (SELECT count(*) FROM _co) <> 1 THEN
    RAISE EXCEPTION 'varunmsaji@gmail.com is not linked to exactly one company';
  END IF;
END $$;

-- One flat list of requests: kind, id, who it is about, what it says, and where it stands.
CREATE TEMP TABLE _req ON COMMIT DROP AS
SELECT 'LEAVE' AS kind, a.id, a.company_id, a.employee_id, a.status, a.resolved_approver_manager_id AS approver,
       CASE WHEN a.start_date = a.end_date
            THEN trim(to_char(a.total_days, 'FM990.9')) || CASE WHEN a.total_days = 1 THEN ' day' ELSE ' days' END
                 || ' of leave on ' || to_char(a.start_date, 'DD Mon YYYY')
            ELSE trim(to_char(a.total_days, 'FM990.9')) || ' days of leave, ' || to_char(a.start_date, 'DD Mon YYYY')
                 || ' to ' || to_char(a.end_date, 'DD Mon YYYY') END AS summary,
       a.created_at, COALESCE(a.reviewed_at, a.updated_at) AS decided_at
FROM leave_application a JOIN _co ON _co.company_id = a.company_id
UNION ALL
SELECT 'REGULARIZATION', r.id, r.company_id, r.employee_id, r.status, r.resolved_approver_manager_id,
       'Attendance correction for ' || to_char(r.attendance_date, 'DD Mon YYYY'),
       r.created_at, COALESCE(r.reviewed_at, r.updated_at)
FROM attendance_regularization_request r JOIN _co ON _co.company_id = r.company_id
UNION ALL
SELECT 'OVERTIME', o.id, o.company_id, o.employee_id, o.status, o.resolved_approver_manager_id,
       (o.minutes_detected / 60) || 'h ' || (o.minutes_detected % 60) || 'm of overtime on '
         || to_char(o.attendance_date, 'DD Mon YYYY'),
       o.created_at, COALESCE(o.reviewed_at, o.updated_at)
FROM overtime_record o JOIN _co ON _co.company_id = o.company_id;

CREATE TEMP TABLE _meta ON COMMIT DROP AS
SELECT * FROM (VALUES
  ('LEAVE', 'LEAVE', 'leave request', '/app/leave-applications', 'LEAVE_APPROVAL_REQUESTED', 'LEAVE_DECIDED', 'LEAVE'),
  ('REGULARIZATION', 'ATTENDANCE', 'attendance correction', '/app/regularizations',
     'REGULARIZATION_APPROVAL_REQUESTED', 'REGULARIZATION_DECIDED', 'attendance_regularization_request'),
  ('OVERTIME', 'OVERTIME', 'overtime', '/app/overtime', 'OVERTIME_APPROVAL_REQUESTED', 'OVERTIME_DECIDED', 'overtime_record')
) AS m(kind, category, noun, path, pending_code, decided_code, entity_type);

-- ---- reviewer is told a request is waiting ----------------------------------------------------
INSERT INTO notification (id, company_id, recipient_user_id, type, category, priority, title, body,
                          entity_type, entity_id, action_url, action_label, metadata, dedupe_key,
                          read_at, created_at, updated_at)
SELECT md5('mock-notif:pending:' || q.id)::uuid, q.company_id,
       COALESCE((SELECT e2.user_id FROM employee e2 WHERE e2.id = q.approver), _co.admin_user_id),
       m.pending_code, m.category, 'HIGH',
       upper(left(m.noun, 1)) || substr(m.noun, 2) || ' awaiting your approval',
       e.first_name || ' ' || e.last_name || ': ' || q.summary || '.',
       CASE m.kind WHEN 'LEAVE' THEN 'leave_application' ELSE m.entity_type END, q.id,
       m.path || '/' || q.id, 'Review', '{"status": "SUBMITTED"}'::jsonb,
       m.pending_code || ':' || q.id || ':MANAGER',
       NULL, q.created_at, q.created_at
FROM _req q JOIN _meta m ON m.kind = q.kind JOIN _co ON _co.company_id = q.company_id
JOIN employee e ON e.id = q.employee_id
WHERE q.status IN ('SUBMITTED', 'PENDING')
  AND COALESCE((SELECT e2.user_id FROM employee e2 WHERE e2.id = q.approver), _co.admin_user_id)
      IS DISTINCT FROM e.user_id
ON CONFLICT (id) DO NOTHING;

-- ---- employee is told the outcome -------------------------------------------------------------
INSERT INTO notification (id, company_id, recipient_user_id, type, category, priority, title, body,
                          entity_type, entity_id, action_url, action_label, metadata, dedupe_key,
                          read_at, created_at, updated_at)
SELECT md5('mock-notif:decided:' || q.id || ':' || q.status)::uuid, q.company_id, e.user_id,
       m.decided_code, m.category, 'NORMAL',
       'Your ' || m.noun || ' was ' || CASE q.status WHEN 'APPROVED' THEN 'approved'
            WHEN 'REJECTED' THEN 'rejected' ELSE 'cancelled' END,
       q.summary || '.',
       CASE m.kind WHEN 'LEAVE' THEN 'leave_application' ELSE m.entity_type END, q.id,
       m.path || '/' || q.id, 'View', jsonb_build_object('status', q.status),
       m.decided_code || ':' || q.id || ':' || CASE q.status WHEN 'APPROVED' THEN 'approved'
            WHEN 'REJECTED' THEN 'rejected' ELSE 'cancelled' END,
       CASE WHEN q.decided_at < now() - interval '3 days' THEN q.decided_at + interval '2 hours' END,
       q.decided_at, q.decided_at
FROM _req q JOIN _meta m ON m.kind = q.kind JOIN employee e ON e.id = q.employee_id
WHERE q.status IN ('APPROVED', 'REJECTED', 'CANCELLED') AND e.user_id IS NOT NULL
ON CONFLICT (id) DO NOTHING;

-- ---- payslips of the last two paid pay runs ---------------------------------------------------
INSERT INTO notification (id, company_id, recipient_user_id, type, category, priority, title, body,
                          entity_type, entity_id, action_url, action_label, metadata, dedupe_key,
                          read_at, created_at, updated_at)
SELECT md5('mock-notif:payslip:' || pre.id)::uuid, pr.company_id, e.user_id,
       'PAYSLIP_AVAILABLE', 'PAYROLL', 'NORMAL',
       'Your payslip for ' || to_char(pr.period_month, 'FMMonth YYYY') || ' is available',
       'Your payslip for ' || to_char(pr.period_month, 'FMMonth YYYY') || ' is ready to view and download.',
       'pay_run', pr.id, '/app/me/payslips', 'View payslip',
       jsonb_build_object('period_month', pr.period_month),
       'PAYSLIP_AVAILABLE:' || pr.id || ':' || pre.employee_id,
       CASE WHEN COALESCE(pr.paid_at, pr.finalised_at, pr.updated_at) < now() - interval '3 days'
            THEN COALESCE(pr.paid_at, pr.finalised_at, pr.updated_at) + interval '1 day' END,
       COALESCE(pr.paid_at, pr.finalised_at, pr.updated_at), COALESCE(pr.paid_at, pr.finalised_at, pr.updated_at)
FROM pay_run pr JOIN _co ON _co.company_id = pr.company_id
JOIN pay_run_employee pre ON pre.pay_run_id = pr.id
JOIN employee e ON e.id = pre.employee_id
WHERE pr.status = 'PAID' AND e.user_id IS NOT NULL
  AND pr.id IN (SELECT id FROM pay_run WHERE company_id = _co.company_id AND status = 'PAID'
                ORDER BY period_month DESC LIMIT 2)
ON CONFLICT (id) DO NOTHING;

SELECT type, count(*) FILTER (WHERE read_at IS NULL) AS unread, count(*) AS total
FROM notification WHERE company_id = (SELECT company_id FROM _co) GROUP BY 1 ORDER BY 1;

COMMIT;
