# HRMS Policy Decisions — Client Review & Sign-Off

**Audience:** HR leadership, client product owner, implementation consultants. No technical background assumed.
**Purpose:** Explain, in plain language, how Attendance and Leave decide "which rule wins" today, where the two modules connect, and which decisions still need your answer before we lock this behaviour in as confirmed policy.
**What this is not:** This document does not change how the system behaves. It describes what it does today and flags every place where "today's behaviour" is a default we chose, not something you've explicitly approved.

---

## 1. Executive Summary

Your HRMS now has two working modules — **Attendance** (tracking who worked when, and how) and **Leave** (tracking who's away, and why) — and they talk to each other through one narrow, well-defined connection point. We reviewed every rule in both modules, every place they could conflict, and every place a business decision is being made silently by code rather than by an explicit choice you've signed off on.

**The headline finding:** the system is more consistent than most HR software at this stage — both modules use the identical "most specific rule wins" logic for figuring out which policy applies to which employee, and both treat a locked payroll period as untouchable. But there are **9 high-or-critical decisions** that are currently resolved by an unstated default, not a decision you've made, and **1 of those (leave vs. overtime pay) is the single most financially significant open question** in the whole system.

## 2. How Attendance and Leave Connect

Picture it like two departments that share exactly one filing cabinet. **Leave decides** whether someone is approved to be away, for how much of the day, and whether it's paid. **Attendance owns the calendar** — it takes that "away" decision and reflects it onto the actual day, alongside punches, holidays, and shifts. Leave never touches Attendance's records directly, and Attendance never touches Leave's balance ledger directly — they only exchange information through this one filing cabinet (technically: a "leave day projection").

The practical consequence: if the attendance record for a date is already locked (because payroll has been run for that period), **Leave cannot record a new approved-leave day on it, and cannot cancel one either** — the whole action is refused, with no partial state. There is currently no in-between fix — the only remedy is fully reopening that pay period, which we flag below as a decision point (§5).

## 3. Major Policy Hierarchy

### Attendance — "which rule wins for a given day"

1. Is the person even employed on this date? (Not-yet-joined / active / exited) — if not, nothing else matters.
2. Is the configuration for this day fully set up? (If not, the system deliberately refuses to guess, rather than silently marking someone present or absent.)
3. Has HR specifically rostered this person off today? That wins even if the calendar says it's a working day.
4. What does the calendar say? (Holiday / weekly off / working day)
5. What do the actual punches say, combined with grace periods, late/early rules, and break rules?
6. **Is there approved leave for this day?** If so, by default, leave wins outright — even over a "day off" from the calendar.
7. Is there an approved "on duty" (e.g., client visit, official travel) record? This can be overridden by leave if both apply to the same day.

### Leave — "which rule wins for an application"

1. Which company policy applies to this specific employee, based on their shift, grade, department, branch, etc.? (Most specific always wins — an employee-specific rule beats a department rule, which beats a company-wide rule.)
2. Is the employee still on probation, and does this leave type allow leave during probation?
3. Does the requested range make sense (half-day only for single dates, reason provided if required, not too far in the past)?
4. Do the dates actually consume leave balance? (Weekly offs and holidays inside a leave range don't count against balance — unless they're "sandwiched" between two leave days, in which case they do.)
5. Is there enough balance? (Balance can never go negative — there is no "advance leave" today.)
6. Who needs to approve, and in what order? (Manager, then possibly department head, then possibly HR — whoever the system can't identify is skipped, never used as an excuse to block the request.)

## 4. Major Override Rules

- **A locked payroll period beats everything.** Once a period is closed, no punch, no regularization, no leave approval, and no leave cancellation can touch a date inside it. The only way back in is a full reopen, which is a deliberately separate, higher-permission action from closing a period.
- **Nobody can approve their own request.** This is true for regularizations, overtime, and leave, with no configuration setting able to turn it off.
- **A rejection at any approval stage is final.** There's no "send it back" — if HR rejects something a manager already approved, it's rejected, full stop.
- **Approved facts are never silently rewritten.** If a policy (like grace period minutes, or a leave carry-forward cap) changes later, everything already calculated or approved under the old policy stays exactly as it was — a change never reaches backward in time unless someone deliberately and explicitly asks for a backdated recalculation.

## 5. Cross-Module Interactions — What We Found

| Situation | What happens today |
|---|---|
| Employee has approved leave and also punched in/out that day | Leave wins by default — the day shows as a leave day, not a worked day (configurable to the opposite, but not recommended without discussion) |
| Employee has half-day leave and works the other half | The day is split cleanly — half paid as worked, half as leave |
| Employee's leave falls on a holiday or a weekly off | Doesn't use up their leave balance, unless it's sandwiched between two leave days on either side |
| Leave is approved, but the pay period for that date is already closed | The approval is blocked entirely — the system will not let it through partially |
| Leave is cancelled after approval, but the pay period is already closed | Same — blocked entirely, no partial undo |
| Employee has approved leave and also worked enough hours to earn overtime that day | **⚠️ Currently, both are simply recorded as true at the same time — nobody has decided whether overtime should still count on a day someone was also on leave.** This is the single most important open decision in this review. |

## 6. Open Client Decisions

These are the decisions we cannot make on your behalf. Each one currently has a default behaviour, but that default was a technical judgment call, not a business decision you've approved.

| # | Decision | What's the question? | Priority |
|---|---|---|---|
| 1 | **Leave vs. Overtime** | If someone is on approved leave, should any overtime they also logged that day still be paid/credited, or should leave cancel it out? | 🔴 Critical |
| 2 | **Fixing a mistake after payroll closes** | Right now, the only way to correct a leave or attendance record after a pay period is closed is to fully reopen that entire period. Do you want a narrower "fix just this one record" option instead? | 🔴 High |
| 3 | **Rostering vs. shift-based rules** | When HR temporarily moves someone to a different shift for a day, some of that shift's specific rules (like grace period) currently still use the person's *usual* shift instead of the one they're actually rostered to. Is that acceptable? | 🔴 High |
| 4 | **Backdated leave for closed periods** | An employee can currently submit a leave request for a date whose payroll period is already closed — it just fails much later, when someone tries to approve it. Should this be blocked immediately at submission instead? | 🔴 High |
| 5 | **Two leave requests, same type, overlapping dates** | Today, nothing stops an employee from submitting two overlapping requests for the *same* leave type (only different types are checked). Should that be blocked? | 🔴 High |
| 6 | **Night-shift overtime pay rate** | Overtime worked overnight is only classified as "night" if the whole shift is a designated overnight shift — not based on the actual clock time worked. Is this acceptable, or should any hours worked during night-time windows get night-rate treatment regardless of shift type? | 🔴 High |
| 7 | **Holiday landing on a weekly off** | If a public holiday falls on someone's regular day off, they currently do not get a substitute day off. Is that the intended policy? | 🟡 Medium |
| 8 | **Sandwich rule scope** | The "sandwich" rule (which pulls a weekend/holiday into paid leave count if it's surrounded by leave days) only looks within one leave request. Should it also apply across two separate back-to-back requests? | 🟡 Medium |
| 9 | **Advance/negative leave balance** | Employees currently cannot go into negative leave balance under any circumstance. Should advance leave ever be allowed? | 🟢 Low |
| 10 | **Approval delegation** | There is currently no way for a manager to delegate their approval authority while on leave/unavailable. Is this needed? | 🟡 Medium |

## 7. What Changes Are Required Before Sign-Off

- A written answer to each of the 10 decisions above (or explicit deferral, with a target date).
- A decision on whether the existing Attendance documentation set (written before Leave existed) should be updated now that Leave is live and actively feeds Attendance — several older documents still describe Leave as "a future module."
- Confirmation that the "locked period beats everything, no exceptions" rule is acceptable as a permanent design principle, or a request to scope a narrower correction mechanism (Decision #2 above).

## 8. Approval Section

| Role | Name | Decision | Date |
|---|---|---|---|
| Client Product Owner | | ☐ Approved as-is ☐ Approved with noted exceptions ☐ Not approved | |
| HR Lead | | ☐ Reviewed ☐ Reviewed with comments | |
| Implementation Lead | | ☐ Confirmed technically accurate | |

**Comments / exceptions:**

---

---

---

*This document accompanies the full technical audit set in `docs/business-rules/policies/`. For the underlying rule-by-rule detail, precedence tables, and code references behind every statement above, see `MASTER_POLICY_INVENTORY.md`, `MASTER_POLICY_PRECEDENCE_MATRIX.md`, `ATTENDANCE_LEAVE_INTERACTION_MATRIX.md`, and `MASTER_POLICY_DECISION_REGISTER.md` in the same folder.*
