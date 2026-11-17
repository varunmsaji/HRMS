# Attendance → payroll integrity check and historical anomaly report (16 Nov 2026)

## Read-only check
`apps/api/scripts/sql/attendance_integrity_report.sql` — SELECT only. Run against each environment:

```bash
psql "$DATABASE_URL" -f apps/api/scripts/sql/attendance_integrity_report.sql
```

| # | Finds | Finding |
|---|---|---|
| 1 | `ot_minutes_approved > ot_minutes_detected` on a day | AC-01 |
| 2 | day class / policy version / approved minutes differ from the paid overtime record | AC-01 |
| 3 | comp-off or approval above what the punches detected | AC-01 |
| 4 | `INCOMPLETE` days carrying approved overtime | AC-04 |
| 5 | locked days resolved as absent (`lop_fraction ≥ 1`) that still carry approved overtime | AC-04 |
| 6 | more than one overtime record per day | integrity |

Leave drift (AC-03) cannot be expressed in SQL: use
`LeaveCalendarReconciliationService.find_discrepancies` (read-only) or the period `validate` call.

## Result on the development database, 16 Nov 2026
4,203 attendance days (3,923 locked), 2 overtime records, 24 approved leave applications — all mock
data (see memory note: no real attendance or pay data exists yet).

* Checks 1–6: **0 rows each.**
* Leave drift: **5 discrepancies**, listed in `ATTENDANCE_LEAVE_CALENDAR_RECONCILIATION.md`.

Production and staging were **not** queried. This is not evidence that they are clean.

## Controlled correction for locked or finalized periods
Nothing here rewrites a locked day, a finalized period or payroll history. If a check returns rows
on a locked day:

1. Export the rows and the affected employees' payroll run status.
2. If the period is not payroll-finalized: reopen it (existing, audited, refused after payroll
   finalization), let the open-day recalculation re-derive the overtime under the new rules, and
   finalize again.
3. If payroll is finalized: do **not** reopen. Compute the difference per employee
   (`approved − supported` minutes at the paid multiplier; LOP vs overtime on a day resolved absent)
   and apply it as a signed adjustment in the next open payroll run, with the audit reference to
   the discrepancy row. Owner sign-off per employee.
4. Re-run the report and keep its output with the adjustment record.

## Period-close safeguards (what is enforced now)
| Safeguard | State |
|---|---|
| Approved overtime above detected blocks finalize | **new** — `OVERTIME_INTEGRITY` |
| Day row disagrees with its overtime record (minutes, class, policy version) blocks finalize | **new** — `OVERTIME_INTEGRITY` |
| Unresolved incomplete attendance per lock policy | existing (`INCOMPLETE_ATTENDANCE`) + held overtime resolved at lock (**new**) |
| Unresolved work-on-leave flags | existing (`WORK_ON_LEAVE_UNRESOLVED`); now also raised for work inside a half-day-leave half (**new**) |
| Leave disagrees with the calendar | **new** — `LEAVE_CALENDAR_MISMATCH` |
| Leave balance shortfall after a calendar change (P-E) | **new** — `LEAVE_BALANCE_SHORTFALL` |
| Locked rows never silently recalculated; payroll-finalized period never reopened | existing, unchanged |
| Open recalculation requests processed before finalize | finalize recalculates every unlocked day itself (R-09); queue requests are **not** separately awaited — see risks |
| Finalize idempotent | unchanged |
