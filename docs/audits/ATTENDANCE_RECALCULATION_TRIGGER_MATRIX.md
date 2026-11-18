# Attendance recalculation trigger matrix (after remediation, 16 Nov 2026)

All triggers use the existing `attendance_recalc_request` queue (`attendance/recalc.py`). The queue
only recalculates **existing, unlocked** `attendance_day` rows, is idempotent, and a request is
committed or rolled back with the change that caused it.

| Event | Dates | People | Reason code | Before | Now |
|---|---|---|---|---|---|
| Holiday created / edited / (de)activated | the holiday's date | work calendars linking its holiday calendar → their assignments | `HOLIDAY_CHANGED` | not queued | queued |
| Holiday calendar validity / active changed | oldest unlocked day → today | same | `HOLIDAY_CALENDAR_CHANGED` | not queued | queued |
| Weekly-off pattern kind / rules / active changed | oldest unlocked day → today | calendars using the pattern + `WEEKLY_OFF` assignments | `WEEKLY_OFF_PATTERN_CHANGED` | not queued | queued |
| Work calendar pattern / holiday links / restricted flag / active changed | oldest unlocked day → today | the calendar's assignments | `WORK_CALENDAR_CHANGED` | not queued | queued |
| Calendar exception created / edited | the exception's date | the calendar's assignments | `CALENDAR_EXCEPTION_CHANGED` | not queued | queued |
| Employment created | joining date onward | that employee | `EMPLOYMENT_CREATED` (AR-09) | not queued | queued |
| Employment terminated | the day after the last working day onward | that employee | `EMPLOYMENT_TERMINATED` (AR-09) | not queued | queued |
| Break override created / revoked | the override's start date onward | that employee | `BREAK_OVERRIDE_CHANGED` (AR-09) | not queued | queued |
| `CalendarImpactService.confirm` | as the method it calls | as above | (the service method's) | not queued | queued — it calls the same service methods |
| Attendance policy version published | `effective_from` → today | that policy's assignments | `POLICY_VERSION_PUBLISHED` | not queued | queued |
| Overtime policy version published | `effective_from` → today | that policy's assignments | `POLICY_VERSION_PUBLISHED` | not queued | queued |
| Immediate calculation after a punch fails | the dates it tried | that employee | `IMMEDIATE_CALCULATION_FAILED` | only the 3-day sweep | queued |
| Shift version, assignment, roster, swap, policy assignment | unchanged | unchanged | existing | queued | queued |

**Scoping rule.** An employee-scoped assignment queues that employee; a shift-scoped one queues
days calculated against that shift; any wider scope (company, legal entity, branch, department…) or
no assignment found queues the whole company — a superset, never a subset. Attendance and overtime
policy publication queue nothing when nobody is assigned the policy.

**Not yet covered (open):**
* A punch that moves *another* session to a different owner leaves the previous owner's day stale
  until the sweep or close (audit §9). Not changed.
* ~~Weekly / monthly overtime caps that depend on sibling days~~ - done (AR-04 / D-04, extended
  by review R-4 to cross a month boundary and by R-5 to HR approvals and rejections): when a day's
  counted overtime changes and the governing overtime policy has a weekly or monthly cap (R-6),
  the later unlocked days of the week and month are recalculated in date order in the same
  transaction. With a monthly cap and a week that spans two months the pass runs to the end of the
  second month.

**Approved leave (AC-03, P-E, review R-3).** Only *dated* changes - a holiday created or edited,
a calendar exception created or edited - reconcile approved leave automatically, in the same
transaction (refund, debit or shortfall exception). Holiday-calendar validity, weekly-off pattern,
work-calendar, assignment, roster and shift changes do **not**: Work Calendar policy A is not
retroactive. They are caught at period close by `LEAVE_CALENDAR_MISMATCH`, and HR resolves them with
the leave reconciliation operation (`POST /v1/leave-reconciliation/preview` then `/apply`).
