# Attendance V1 — Client Sign-Off Checklist

**Purpose:** This is the actual review document. Work through each question with the client/product owner. Every question shows the current proposed (default) behaviour and a concrete example — the client's job is to confirm it, or flag it for change.

This checklist covers **business rules**, not technical implementation. No database, API, or code terms are used.

**How to use this document:** for each question, record the client's decision in the "Client decision" line. Leave it blank until answered. Once answered, treat it as the confirmed business rule for the current release.

---

## A. Calendar rules

**Question:** When a public holiday falls on an employee's weekly-off day, should the employee automatically get a substitute day off elsewhere?
**Current proposed behaviour:** No — the day simply stays a weekly off (with a note that a holiday coincided with it). HR must manually add a substitute day if desired.
**Example:** Independence Day falls on a Sunday, which is already the weekly off. No extra day off is created automatically.
**Client decision:** _______________________

**Question:** Should there be a way to declare a specific working day as an exception (e.g., "this Saturday is a working day this month only")?
**Current proposed behaviour:** Yes — this is already supported via a date-specific exception.
**Example:** A company declares a specific Saturday a working day ahead of a long weekend elsewhere.
**Client decision:** _______________________

---

## B. Holiday rules

**Question:** Should "optional" or "restricted" holidays (e.g., regional festivals not everyone observes) count as working days by default, only becoming a holiday if an employee specifically applies leave for it?
**Current proposed behaviour:** Yes, working day by default. There is a company-wide switch that can instead make them hard holidays for everyone if that's preferred.
**Example:** A regional festival is listed as "Optional." By default, employees work normally unless they take leave. If the switch is turned on, nobody is expected to work that day at all.
**Client decision:** _______________________

**Question:** Do different branches/states need entirely separate holiday lists (e.g., Kerala vs. Maharashtra)?
**Current proposed behaviour:** Yes — supported today, via assigning different holiday calendars to different branches or employees.
**Client decision:** _______________________

---

## C. Weekly-off rules

**Question:** What weekly-off pattern(s) does the client need — fixed day, alternate Saturdays, 1st/3rd Saturday, 2nd/4th Saturday, last Saturday, or a custom mix by branch/department?
**Current proposed behaviour:** All of the above are supported today; the specific pattern per branch/department needs to be confirmed and configured.
**Client decision:** _______________________

---

## D. Shift rules

**Question:** Which shift types does the client need — fixed, flexible, split, night/cross-midnight — and for which employee groups?
**Current proposed behaviour:** All four types are supported. Client needs to confirm which groups use which type.
**Client decision:** _______________________

**Question:** For a night/cross-midnight shift, should the entire shift belong to the date it started, even though most of the hours may fall after midnight?
**Current proposed behaviour:** Yes — the whole shift is attributed to its start date.
**Example:** A 22:00–06:00 shift starting 20 Aug is entirely recorded as 20 Aug's attendance, not split or recorded on 21 Aug.
**Client decision:** _______________________

**Question:** For flexible shifts, does the client require a "core hours" window (a period everyone must be present for) to be actually enforced?
**Current proposed behaviour:** This setting exists in configuration but currently has **no effect** — it needs a decision on whether to build it.
**Client decision:** _______________________

---

## E. Break rules

**Question:** Should a "mandatory" unpaid break be deducted from worked hours automatically, even if the employee doesn't punch out/in around it?
**Current proposed behaviour:** No — a break is only deducted if the employee's punches show an actual matching gap. If they work through lunch without punching out, they are currently credited for that time as worked.
**Example:** Shift 09:00–18:00, mandatory unpaid lunch 13:00–14:00. Employee punches only IN at 09:00 and OUT at 18:00 with no gap punches. Today: full 9 hours counted as worked (break not deducted). If this is not the desired policy, it needs to be flagged for a change.
**Client decision:** _______________________

**Question:** Should exceeding the maximum allowed break time trigger any automatic consequence?
**Current proposed behaviour:** No automatic consequence today — the excess is recorded as a number only, for HR to review manually.
**Client decision:** _______________________

---

## F. Late rules

**Question:** What grace period (minutes of leeway before "late" starts counting) should apply, and does it vary by employee group?
**Current proposed behaviour:** Fully configurable per policy, and policies can be assigned at 8 different levels down to an individual employee.
**Client decision:** _______________________

**Question:** Should repeated lateness (e.g., "3 late arrivals in a month") automatically convert into a half-day deduction?
**Current proposed behaviour:** **Not currently supported** — each day is judged independently; there's no cumulative late-count-to-half-day feature active today, even though a related setting exists in configuration.
**Client decision:** _______________________

---

## G. Early departure rules

**Question:** Should leaving early require pre-approval, or is it acceptable to simply flag/classify it after the fact?
**Current proposed behaviour:** Only after-the-fact flagging/classification is supported today; a pre-approval requirement setting exists but is not enforced.
**Client decision:** _______________________

---

## H. Missing punch rules

**Question:** When an employee forgets to punch in or out, should the day default to "Incomplete" (pending correction) or automatically become "Absent"?
**Current proposed behaviour:** Defaults to Incomplete — the employee/manager is expected to submit a correction. "Absent" can be configured as the default instead if preferred.
**Client decision:** _______________________

**Question:** Should the system automatically insert a clock-out for someone who forgot to punch out (e.g., at shift-end time, or some minutes after)?
**Current proposed behaviour:** **Not currently supported**, despite a setting named "Auto-Close" existing in configuration — that setting does not currently do this.
**Client decision:** _______________________

---

## I. Half-day rules

**Question:** What worked-hours thresholds should define Present vs. Half-Day vs. Absent?
**Current proposed behaviour:** Fully configurable (e.g., ≥480 min = Present, 240–479 = Half-Day, below 240 = Absent). Needs client-specific numbers confirmed.
**Client decision:** _______________________

**Question:** For half-day leave, should the system actually evaluate only that half of the shift (e.g., ignore morning punches for a "second half" leave), or is a flat half-day credit acceptable regardless of which half was taken?
**Current proposed behaviour:** Flat half-day credit only — the system does not currently limit evaluation to a specific half of the shift.
**Client decision:** _______________________

---

## J. Absent rules

**Question:** Should an employee with zero punches and no leave on an expected working day default to Incomplete (needs manual resolution) or automatically Absent?
**Current proposed behaviour:** Same as the missing-punch default above — Incomplete unless configured otherwise.
**Client decision:** _______________________

---

## K. WFH rules

**Question:** Does the client need a distinct "Work From Home" attendance status, separate from Present?
**Current proposed behaviour:** **Not currently supported.** The system has a placeholder for this status, and a correction-request type named "WFH," but no working day-result is produced yet. If this is required, it should be scoped as a dedicated future build.
**Client decision:** _______________________

---

## L. On-duty rules

**Question:** Does the client need a distinct "On-Duty" status for field/outdoor work, separate from Present?
**Current proposed behaviour:** **Not currently supported**, same situation as WFH above.
**Client decision:** _______________________

---

## M. Leave interaction

**Question:** When an employee has approved leave for a day but also has punches recorded, should the leave status always win, or should the actual punch-based status be kept (with a flag noting the employee worked despite being on leave)?
**Current proposed behaviour:** Leave wins by default; a "keep punch status + flag" mode is available as an alternate configuration.
**Client decision:** _______________________

**Question:** If a day ends up marked "Leave," should any overtime/worked-hours numbers from punches on that day be cleared for payroll purposes, or kept as an audit trail?
**Current proposed behaviour:** Currently kept as-is (not cleared) — flagged as an open decision, since a payroll report showing "Leave" with non-zero overtime could look contradictory.
**Client decision:** _______________________

**Question:** Is it acceptable that this system only mirrors leave decisions made elsewhere (no leave balance tracking, applications, or approvals happen inside Attendance)?
**Current proposed behaviour:** Yes, that is the current design — a full Leave module (balances, accrual, applications) is a separate future build.
**Client decision:** _______________________

---

## N. Regularization

**Question:** Who should be allowed to submit a correction request — the employee themselves, their manager on their behalf, or HR only?
**Current proposed behaviour:** All three are configurable independently per policy.
**Client decision:** _______________________

**Question:** How far back should an employee be allowed to request a correction (backdating window), and how many requests per month should be allowed?
**Current proposed behaviour:** Both fully configurable; needs client-specific numbers.
**Client decision:** _______________________

**Question:** What approval chain should corrections follow — automatic, manager only, HR only, or manager then HR?
**Current proposed behaviour:** All four options supported, configurable per policy (and can differ by correction type).
**Client decision:** _______________________

**Question:** Should corrections ever be allowed to directly overwrite the final attendance status, or should they always work by adding/adjusting punches and letting the system recalculate?
**Current proposed behaviour:** Always additive — corrections never directly overwrite status; they add punches and/or update the roster shift, then the day is recalculated through the normal rules. This is a deliberate audit-trail design.
**Client decision:** _______________________

---

## O. Overtime

**Question:** Should overtime require approval before it counts, or should it always auto-approve?
**Current proposed behaviour:** Requires approval by default (manager chain); can be configured to auto-approve instead.
**Client decision:** _______________________

**Question:** What daily/weekly/monthly overtime caps should apply?
**Current proposed behaviour:** Fully configurable; needs client-specific numbers.
**Client decision:** _______________________

**Question:** Should overtime eligibility depend on employee grade (e.g., only non-managerial staff are OT-eligible)?
**Current proposed behaviour:** A "by grade" eligibility option exists in configuration, but it currently has **no actual grade check** — it behaves the same as "always eligible." If grade-based restriction is a real requirement, this needs to be built before go-live.
**Client decision:** _______________________

**Question:** Should overtime worked during night-shift hours be classified and reported differently from daytime overtime?
**Current proposed behaviour:** With current defaults, night overtime is **not** classified separately — it's recorded as ordinary overtime. This is flagged as a fix candidate if night-shift differentiation matters to the client.
**Client decision:** _______________________

---

## P. Comp-off

**Question:** Should overtime be convertible into comp-off (time off in lieu) instead of being paid?
**Current proposed behaviour:** Yes, supported as a configurable choice per overtime policy, including an optional expiry period for the comp-off.
**Client decision:** _______________________

**Question:** Is it acceptable that redeeming (using) a comp-off balance against actual leave is not built yet — this system only records that comp-off minutes were earned?
**Current proposed behaviour:** Yes, that is the current scope — comp-off redemption belongs to the future Leave module.
**Client decision:** _______________________

---

## Q. Locking

**Question:** What should block a period from being closed — configuration errors, incomplete attendance, pending correction requests, pending overtime approvals, unpublished rosters, missing attendance records? Should all of these be blockers, or should some be allowed to pass with a warning instead?
**Current proposed behaviour:** All six are hard blockers today — nothing can be waived without resolving it first.
**Client decision:** _______________________

**Question:** When a locked period is reopened, should the system automatically recalculate everything, or should HR trigger recalculation manually as a deliberate step?
**Current proposed behaviour:** Manual — reopening does not auto-recalculate. Recommended to keep it this way for payroll safety, but flagged for confirmation.
**Client decision:** _______________________

**Question:** How should corrections be handled after a period has already been locked (and possibly already paid)?
**Current proposed behaviour:** **Not fully built** — today the only option is to reopen the whole period (a blunt instrument with no arrears tracking). A dedicated post-lock adjustment feature is recommended before the first fully paid, closed payroll cycle.
**Client decision:** _______________________

---

## R. Payroll handoff

**Question:** Is it acceptable that this system produces only *facts* (paid/unpaid days, overtime minutes, comp-off minutes) and does not calculate any actual pay amounts?
**Current proposed behaviour:** Yes, that is the confirmed design — no money, pay rates, or statutory deductions are calculated here. That is entirely a separate, future Payroll module's responsibility.
**Client decision:** _______________________

---

## S. Special Indian HR cases

**Question:** Are the supported weekly-off patterns (fixed day, alternate Saturdays, Nth Saturday, last Saturday) sufficient, or are there additional regional patterns to support?
**Client decision:** _______________________

**Question:** Are state-specific/regional holiday calendars (e.g., Kerala vs. Maharashtra) sufficient as "HR manually loads the list per state," or is a built-in statutory holiday pack expected?
**Current proposed behaviour:** No built-in statutory holiday pack exists — HR loads the dates manually per calendar.
**Client decision:** _______________________

**Question:** Is it acceptable that this system does not calculate statutory overtime pay rates (e.g., legally mandated 2x pay) as actual money — only records a reference multiplier and the classification (Holiday/Weekly-Off/Night/Normal)?
**Current proposed behaviour:** Yes — this is a deliberate design boundary; statutory pay calculation belongs to the future Payroll module.
**Client decision:** _______________________

---

## Sign-off summary

Once every section above has a recorded client decision, this document becomes the confirmed business-rule baseline for Attendance V1. Any question left unanswered, or any answer that differs from the "current proposed behaviour," should be logged as a change request against the [Gaps & Open Decisions document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md) before implementation begins.

| Reviewed by | Role | Date | Sections confirmed |
|---|---|---|---|
| | | | |
| | | | |
