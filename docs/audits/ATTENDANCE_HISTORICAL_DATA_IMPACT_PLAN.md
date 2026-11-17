# Attendance — Historical Data Impact Plan — 16 November 2026

**Status:** plan and draft read-only SQL. **Nothing in this document has been run.** The queries were
written from the SQLAlchemy models (column names checked against `attendance/models.py`,
`leave/models.py`, `core/audit/models.py`) and must be syntax-checked on a scratch database before
use. They contain only `SELECT`. No data was read, changed or deleted by this pass.

**Standing facts**
- As of 5 November 2026 the system holds test data only, and the dev database is four migrations
  behind (verification section 1). The first run of every report is on dev, then on any pilot
  database, **before** the matching fix is released.
- Existing read-only scripts already cover: approved > detected overtime, day-vs-record class
  mismatch, comp-off beyond detected minutes, incomplete days carrying overtime, locked absent days
  with overtime, record-per-day and orphan records, leave with no day rows
  (`apps/api/scripts/sql/attendance_integrity_report.sql`); broad mark bands, uncapped-credit
  candidates, policies with no mark bands (`late_mark_band_impact_report.sql`); a pre-recalculation
  snapshot (`attendance_pre_recalc_snapshot.sql`). The audit is right that none of them covers
  MA-03 (ledger against record) or MA-27.

---

## 1. Who and what each finding can touch

"Locked" = `attendance_day.is_locked = true` (period closed). "Open" = not locked. Payroll reads only
closed periods, so a wrong **locked** value is a wrong payslip input; a wrong **open** value is
corrected by recalculation.

| Finding | Policies or configurations exposed | Employees | Date range | Locked rows? | Correction type |
|---|---|---|---|---|---|
| MA-01 | Published attendance policy versions whose hour bands do not start at 0 or have a gap | All assigned to such a version | `effective_from` to `effective_to` of the version | Possible | Version republish + controlled recalc (open); locked days: approved correction |
| MA-02 | Versions with `incomplete_at_lock_behaviour = TREAT_PRESENT` | Those on the version | Any locked period | **Yes, the harm is at lock** | Approved correction (pay reduces) |
| MA-03 | Overtime policies with comp-off instead of pay | Employees with `COMP_OFF_CREDIT` entries | Any | Ledger is append-only: balances only | Reversing entries, approved |
| MA-04 | Shift-scoped work calendar, attendance or overtime policy assignment | Employees on a shift with a roster week-off row | Roster off dates | `CONFIG_ERROR` days cannot lock, so open only; overtime lost on locked days possible | Recalc after fix |
| MA-05 | Any policy whose full-day band exceeds a shift's net minutes | Part-time, short-shift staff | Any | Possible | Decision P-05, then approved correction |
| MA-06 | Any | Anyone who punched after close | After a period's `locked_at` | **Yes** (the day is locked; the punch is lost) | Reopen or HR queue |
| MA-07, MA-29, MA-30 | Roster, regularization, break-override changes | Affected employee and neighbouring dates | Changed date ±2 days | Neighbour may be locked | Recalc open days; locked ones listed |
| MA-08 | Half-day leave and a calendar or roster change after approval | Employees with half-day leave | Leave dates | Blocked at close by `LEAVE_CALENDAR_MISMATCH`, so open | Reconcile, then recalc |
| MA-09, MA-13 | Policies with grace, band edges | Anyone near a band edge | Any | Possible | Decision, then approved correction |
| MA-10 | Employment pay-basis or legal-entity edits | Edited employees | From joining date | Legal entity: **yes** | Approved correction |
| MA-20 | FIXED shifts, early arrivals | Early starters | Any | Possible | Decision P-04 |
| MA-27 | Cancelled leave after a shortfall | Employee with the leave | Shortfall date | Period blocked, so open | Fix and close the row |
| MA-34 / NF-1 | Records at manager stage with a departed manager | Their reports | Any | Period blocked | Reassign after fix |

---

## 2. Read-only reports (drafts)

Run each as `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f <file>` inside
`BEGIN READ ONLY; … ROLLBACK;` so a typo cannot write. Row-level security applies: run as a role
that can see the company, or set `app.company_id` per company. Every report prints
`company_id, employee_id, attendance_date, is_locked, locked_period_id` where relevant so the
locked rows can be separated.

**R1 — MA-01 / NF-2 published hour-band sets with a gap or non-zero start**

```sql
WITH b AS (
  SELECT policy_version_id, min_minutes, max_minutes,
         ROW_NUMBER() OVER w AS rn,
         LAG(max_minutes) OVER w AS prev_max
  FROM attendance_policy_hour_band
  WINDOW w AS (PARTITION BY policy_version_id ORDER BY min_minutes)
)
SELECT v.company_id, v.policy_id, v.id AS version_id, v.version, v.status,
       v.effective_from, v.effective_to,
       count(*) FILTER (WHERE b.rn = 1 AND b.min_minutes > 0)               AS starts_above_zero,
       count(*) FILTER (WHERE b.rn > 1 AND b.min_minutes <> b.prev_max + 1) AS gaps
FROM b JOIN attendance_policy_version v ON v.id = b.policy_version_id
WHERE v.status = 'PUBLISHED'
GROUP BY v.company_id, v.policy_id, v.id, v.version, v.status, v.effective_from, v.effective_to
HAVING count(*) FILTER (WHERE (b.rn = 1 AND b.min_minutes > 0)
                           OR (b.rn > 1 AND b.min_minutes <> b.prev_max + 1)) > 0;
```

**R1b — days whose worked minutes no band of their version covers (candidates)**

```sql
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked, d.locked_period_id,
       d.worked_minutes, d.attendance_status, d.paid_day_fraction, d.lop_fraction
FROM attendance_day d
WHERE d.worked_minutes > 0
  AND d.attendance_policy_version_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM attendance_policy_hour_band h
                  WHERE h.policy_version_id = d.attendance_policy_version_id
                    AND d.worked_minutes >= h.min_minutes
                    AND (h.max_minutes IS NULL OR d.worked_minutes <= h.max_minutes))
ORDER BY d.company_id, d.attendance_date;
```
(Candidate list only: the engine looks bands up on worked minutes plus grace credit.)

**R2 — MA-02 locked or open days paid in full with no punch**

```sql
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked, d.locked_period_id,
       d.attendance_status, d.worked_minutes, d.paid_day_fraction, d.lop_fraction,
       v.incomplete_at_lock_behaviour
FROM attendance_day d
JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
WHERE d.attendance_status = 'INCOMPLETE' AND d.is_locked
  AND d.actual_first_in IS NULL AND d.paid_day_fraction > 0
  AND v.incomplete_at_lock_behaviour = 'TREAT_PRESENT';
```
Also list the exposed versions: `SELECT … FROM attendance_policy_version WHERE
incomplete_at_lock_behaviour = 'TREAT_PRESENT' AND status = 'PUBLISHED'`.

**R3 — MA-03 comp-off credits that no longer match their overtime record**

```sql
WITH credit AS (
  SELECT l.company_id, l.employee_id, l.leave_type_id, l.reference_id,
         sum(l.amount) AS net_credit, min(l.effective_date) AS first_credit_date
  FROM leave_ledger l
  WHERE l.entry_type = 'COMP_OFF_CREDIT' AND l.reference_id IS NOT NULL
    -- a credit already reversed by the leave-day path has an ADJUSTMENT row pointing at it
    AND NOT EXISTS (SELECT 1 FROM leave_ledger a
                    WHERE a.entry_type = 'ADJUSTMENT' AND a.reference_id = l.id)
  GROUP BY 1,2,3,4
)
SELECT c.company_id, c.employee_id, c.reference_id AS overtime_record_id, c.net_credit,
       r.status, r.comp_off_minutes, r.attendance_date,
       CASE WHEN r.id IS NULL THEN 'RECORD_GONE'
            WHEN r.status NOT IN ('APPROVED','AUTO_APPROVED') THEN 'NOT_APPROVED'
            WHEN r.comp_off_minutes = 0 THEN 'NO_COMP_OFF_MINUTES'
            ELSE 'AMOUNT_CHECK' END AS reason
FROM credit c
LEFT JOIN overtime_record r ON r.id = c.reference_id
WHERE c.net_credit > 0
  AND (r.id IS NULL OR r.status NOT IN ('APPROVED','AUTO_APPROVED') OR r.comp_off_minutes = 0);

-- double credit: one employee-date credited through more than one record id
SELECT l.company_id, l.employee_id, r.attendance_date,
       count(DISTINCT l.reference_id) AS records_credited, sum(l.amount) AS total
FROM leave_ledger l JOIN overtime_record r ON r.id = l.reference_id
WHERE l.entry_type = 'COMP_OFF_CREDIT'
GROUP BY 1,2,3 HAVING count(DISTINCT l.reference_id) > 1;
```
Records that were deleted leave a ledger row pointing at nothing, so `RECORD_GONE` is expected to be
the main hit. The amount check (credit days against `comp_off_minutes / day length`) needs the
policy's day length (O-18, scheduled minutes of the shift) and is not drafted here; do it by
hand for each `AMOUNT_CHECK` once the zero-cases are cleared.

**R4 — MA-04 days blocked or short-changed by shift-scoped resolution**

```sql
SELECT d.company_id, d.employee_id, d.attendance_date, d.attendance_status, d.is_locked,
       r.is_week_off_override, r.status AS roster_status
FROM attendance_day d
JOIN shift_roster r ON r.company_id = d.company_id AND r.employee_id = d.employee_id
                   AND r.roster_date = d.attendance_date AND r.deleted_at IS NULL
WHERE r.is_week_off_override AND r.status = 'PUBLISHED'
  AND (d.attendance_status = 'CONFIG_ERROR' OR d.calendar_day_type IS NULL);
```
(Roster status literal `PUBLISHED` assumed from the `DRAFT` blocker; confirm.)

**R5 — MA-05 days whose shift is shorter than the full-day band**

```sql
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked,
       d.scheduled_minutes, d.worked_minutes, d.attendance_status, d.lop_fraction,
       full_day.min_minutes AS full_day_band_minutes
FROM attendance_day d
JOIN LATERAL (SELECT min(h.min_minutes) AS min_minutes
              FROM attendance_policy_hour_band h
              WHERE h.policy_version_id = d.attendance_policy_version_id
                AND h.result_status = 'PRESENT') full_day ON true
WHERE d.scheduled_minutes IS NOT NULL
  AND d.scheduled_minutes < full_day.min_minutes
  AND d.attendance_status IN ('HALF_DAY','ABSENT');
```

**R6 — MA-06 punches recorded after their day was locked and not in its snapshot**

```sql
SELECT p.company_id, p.employee_id, p.id AS punch_id, p.punch_time, p.created_at,
       d.attendance_date, d.locked_period_id, d.locked_at
FROM punch p
JOIN attendance_day d
  ON d.company_id = p.company_id AND d.employee_id = p.employee_id AND d.is_locked
 AND (p.punch_time AT TIME ZONE d.timezone)::date = d.attendance_date
WHERE p.created_at > d.locked_at
  AND NOT (d.computation_snapshot::jsonb -> 'inputs' -> 'punch_ids') ? p.id::text;
```
This heuristic finds the same-date case. The audit's own case (checkout dated after midnight, owned
by the previous day) needs the ownership neighbourhood; add the previous date as a second join leg.

**R7 — MA-07 / MA-29 / MA-06 symptom: one punch listed on two days**

```sql
SELECT d.company_id, d.employee_id, pid AS punch_id,
       array_agg(d.attendance_date ORDER BY d.attendance_date) AS dates,
       bool_or(d.is_locked) AS any_locked
FROM attendance_day d,
     jsonb_array_elements_text(d.computation_snapshot::jsonb -> 'inputs' -> 'punch_ids') AS pid
GROUP BY d.company_id, d.employee_id, pid
HAVING count(*) > 1;
```
Two days that both claim a punch means ownership changed after one of them was calculated. Both
open: recalculate. One locked: list for HR.

**R8 — MA-08 half-day leave paid as loss of pay on a day off**

```sql
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked, d.calendar_day_type,
       d.attendance_status, d.leave_fraction, d.paid_day_fraction, d.lop_fraction
FROM attendance_day d
WHERE d.attendance_status = 'LEAVE' AND d.leave_fraction = 0.50
  AND d.lop_fraction > 0 AND d.calendar_day_type IN ('HOLIDAY','WEEKLY_OFF','SHUTDOWN');
```
(Roster week-offs are not in `calendar_day_type`; join `shift_roster` as in R4.)

**R9 — MA-13 grace at a band edge (candidate)**

```sql
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked, d.worked_minutes,
       d.attendance_status, h.min_minutes AS band_min, h.result_status,
       v.grace_in_minutes + v.grace_out_minutes AS total_grace
FROM attendance_day d
JOIN attendance_policy_version v ON v.id = d.attendance_policy_version_id
JOIN attendance_policy_hour_band h ON h.policy_version_id = v.id
WHERE d.attendance_status = h.result_status
  AND h.min_minutes > d.worked_minutes
  AND h.min_minutes - d.worked_minutes <= v.grace_in_minutes + v.grace_out_minutes
  AND d.worked_minutes > 0;
```
For MA-09 reuse `late_mark_band_impact_report.sql` (queries 1–5) and add the "net shift minutes =
full-day band" filter that verification section 4.2 identified.

**R10 — MA-10 employment edits since go-live**

```sql
SELECT a.company_id, a.entity_id AS employment_id, a.occurred_at,
       a.before_json->>'pay_basis' AS pay_before, a.after_json->>'pay_basis' AS pay_after,
       a.before_json->>'legal_entity_id' AS entity_before, a.after_json->>'legal_entity_id' AS entity_after
FROM audit_log a
WHERE a.action = 'EMPLOYMENT_UPDATED'
  AND (a.before_json->>'pay_basis' IS DISTINCT FROM a.after_json->>'pay_basis'
    OR a.before_json->>'legal_entity_id' IS DISTINCT FROM a.after_json->>'legal_entity_id');
```

**R11 — MA-20 early work counted as nothing**

```sql
SELECT d.company_id, d.employee_id, d.attendance_date, d.is_locked,
       d.actual_first_in, d.actual_last_out, d.scheduled_start, d.worked_minutes, d.attendance_status
FROM attendance_day d
WHERE d.worked_minutes = 0 AND d.actual_first_in IS NOT NULL
  AND d.actual_last_out IS NOT NULL AND d.actual_last_out <= d.scheduled_start;
```

**R12 — MA-27 open shortfalls whose leave is no longer approved**

```sql
SELECT s.company_id, s.employee_id, s.leave_application_id, s.calendar_date,
       s.required_fraction, s.available_balance, a.status AS application_status
FROM leave_balance_shortfall s
JOIN leave_application a ON a.id = s.leave_application_id
WHERE s.status = 'OPEN' AND a.status <> 'APPROVED';
```

**R13 — MA-34 / NF-1 stalled approvals**

```sql
SELECT o.company_id, o.employee_id, o.attendance_date, o.approval_stage,
       o.resolved_approver_manager_id, e.status AS manager_employment_status
FROM overtime_record o
LEFT JOIN employee e ON e.id = o.resolved_approver_manager_id
WHERE o.status = 'PENDING' AND o.approval_stage = 'MANAGER'
  AND (e.id IS NULL OR e.status <> 'ACTIVE');
-- the same shape on attendance_regularization_request (resolved_approver_manager_id)
```
(`employee.status` assumed; confirm the column and value.)

**R14 — recalculation queue health (MA-12)**

```sql
SELECT company_id, reason, count(*) AS rows,
       count(*) FILTER (WHERE processed_at IS NULL) AS pending,
       count(*) FILTER (WHERE attempts >= 5 AND last_error IS NOT NULL) AS abandoned
FROM attendance_recalc_request GROUP BY company_id, reason ORDER BY abandoned DESC;
```

**R15 — MA-18 grants and duplicate ledger debits (pre-checks for Phase 4 indexes)**

```sql
SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants
WHERE grantee = 'hrms_app' AND table_name IN ('punch','overtime_action','punch_dismissal','attendance_period_action')
  AND privilege_type IN ('UPDATE','DELETE','TRUNCATE');

SELECT company_id, employee_id, reference_id, count(*) FROM leave_ledger
WHERE entry_type = 'APPLICATION' AND reference_id IS NOT NULL
GROUP BY 1,2,3 HAVING count(*) > 1;   -- must be empty before the unique index
```

---

## 3. Controlled recalculation

An engine change affects nothing until days are recalculated (AR-17). The release procedure:

1. **Freeze point.** Record `engine_version`, git SHA, migration head and the date.
2. **Before:** run `attendance_pre_recalc_snapshot.sql` for the company and date range: it writes
   nothing; save its output.
3. **Select dates:** unlocked days only, from the oldest open period start to yesterday, per
   company. Never include locked days.
4. **Recalculate in date order** per employee through the queue (one `attendance_recalc_request`
   per employee, range = open window), not by a loop of direct calls.
5. **After:** run the same snapshot; produce a diff of status, paid, LOP, overtime for every changed
   day, with the reason code (which fix changed it).
6. **Sign-off:** HR reviews the diff for each company; the product owner approves large changes
   (rule: any employee with more than 1.0 days of change in a month, or any company with more than
   2% of days changed).
7. **Stop condition:** any locked row appears in the diff, or any status changes to `CONFIG_ERROR`
   without an expected cause: stop and restore nothing (rows are append-only history in the audit
   log); investigate.

## 4. Protecting locked and finalized periods

1. **Code never rewrites a locked day** (existing invariant; keep and add a test for every new
   recalculation entry point: a recalculation request spanning a locked date skips it and logs).
2. **A finalized payroll run forbids reopen** (decision 15): corrections for such periods go to the
   **next** period's payroll as an adjustment, never to the closed rows.
3. **Unlocked-after-reopen days** are recalculated only by an explicit, logged action after the
   reopen, not by the queue.
4. **Corrections to locked data are a separate operation** with its own approval:
   - A written request naming employee, date, old value, new value, reason, finding id.
   - Approval by someone other than the requester, with company scope.
   - Executed by a documented operation (an HR action that reopens the period, then corrects through
     a regularization or adjustment, then finalizes again), never by SQL.
   - Audit rows: who, when, before, after, finding id, approval id. The leave ledger gets **reversing
     entries**, never edits (`UPDATE` and `DELETE` are already revoked on it).
5. **No silent rewrite of attendance or ledger history.** The only permitted writes to historical
   attendance are new calculation results on **unlocked** rows (each with its audit entry) and new
   append-only ledger entries.

## 5. Approval and audit trail for historical corrections

| Step | Who | Record |
|---|---|---|
| Identify | Engineer runs the report | The report output, run date, git SHA, saved under `docs/audits/impact/` |
| Classify | HR lead | Each row: correct as is, correct by recalculation, correct by approved adjustment, accept |
| Approve | Product owner (and payroll owner for locked or finalized periods) | A named decision id and date |
| Execute | HR through the product | Normal audit log, with the finding id in the reason field |
| Verify | Engineer re-runs the report | Zero remaining or each remaining row has a written acceptance |

## 6. Required migrations and deployment order

| Order | Migration | Needed by | Rollback | Pre-check |
|---|---|---|---|---|
| Already in the working tree | `20261115090000` shift remediation, `20261116090000` overtime supersede action, `20261116100000` leave balance shortfall, `20261116110000` leave application half-day | Engine 16 | Their downgrades | Dev is four behind: migrate dev first |
| New 1 (if H-03 needs it) | **None expected for comp-off reversal.** `leave_ledger.entry_type` is CHECK-restricted to six kinds (no reversal kind), but the existing leave-day reversal writes an `ADJUSTMENT` entry whose `reference_id` is the credit row (`leave/service.py` ~2328–2340), and `amount <> 0` allows negatives. Reuse that pattern; confirm before choosing | Phase 1.6 | — | R3 |
| New 2 (if P-05 is "share of shift") | Policy-version column for percent bands | Phase 1.7 | Downgrade drops it | R5 |
| New 3 | Unique partial index: one `APPLICATION` ledger debit per application | Phase 4.2 | Drop index | R15 duplicates query empty |
| New 4 | Unique partial index: one approved ON_DUTY and one early-departure approval per employee-date | Phase 4.3, same release as 3.6 | Drop index | Duplicates query empty |
| New 5 | Revoke `UPDATE`, `DELETE`, `TRUNCATE` on `punch`, `overtime_action`, `punch_dismissal`, `attendance_period_action` for the runtime role | Phase 4.1, after 4.2 and 4.3 | Grant back | R15 grants; grep every write |
| Data (not schema) | Republish policy versions flagged by R1 | Before Phase 1.2 | n/a (new version, old one closed) | R1 empty |

Deployment order: engine 16 baseline (migrations) → Phase 1.1 (no schema) → data republish (R1) →
Phase 1 engine items → controlled recalculation → Phase 2/3 code → indexes (New 3, 4) → grants
(New 5). Never deploy engine code on a database that is behind head (verification section 1).

## 7. What cannot be said yet

- How many real rows are affected: none exist.
- Whether R4, R8 and R13 column literals (`PUBLISHED`, `employee.status`) are right: confirm on a
  scratch database.
- The exact comp-off amounts: needs day length per record; manual for the first run.
