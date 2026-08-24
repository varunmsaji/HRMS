# HRMS Attendance
## Business Rules & Scenario Specification

### Client Review & Business Sign-Off

| Document Information | Value |
|---|---|
| Document Version | 1.0 |
| Status | **CLIENT REVIEW** |
| Prepared Date | 22-Aug-2026 |
| Client Review Date | |
| Approved Date | |
| Prepared By | |
| Client Organization | |
| Approved By | |

**Covers:** Attendance module slices W1–W9 (work calendar, holidays, weekly-off, shifts, rosters, breaks, attendance policy, punches, leave overlay, regularization, overtime, period lock).

**Source material:** This document is a synthesis, not a new analysis. It draws entirely from the existing audit set (`docs/modules/attendance/ATTENDANCE_*_AUDIT*.md`, `ATTENDANCE_MASTER_RULE_MATRIX.md`, `ATTENDANCE_OVERRIDE_MATRIX.md`, `ATTENDANCE_SCENARIO_MATRIX.md`, `ATTENDANCE_CONFIGURATION_AUDIT.md`, `ATTENDANCE_DOCUMENTATION_GAPS.md`) and the existing client-facing set (`docs/business-rules/ATTENDANCE_V1_*.md`, `docs/business-rules/attendance/01–08_*.md`). No new code was read to produce this document, and nothing here should be treated as more current than the audits it summarizes (2026-08-20/21).

> This document defines the agreed business behaviour of the HRMS Attendance module. It is intended for client review and approval and will serve as the baseline for implementation, testing, UAT, payroll integration and future change requests.

### Document Status

☐ Draft **☑ Client Review** ☐ Changes Requested ☐ Pending Final Decisions ☐ Approved ☐ Superseded

> **Current status is CLIENT REVIEW.** No section of this document should be treated as approved until it is signed off in **Section 33 — Final Client Sign-Off**.

**This document does not invent business rules, does not assume what the client wants, and does not silently resolve contradictions.** Where the existing documentation or code does not establish a definitive intended behaviour, the item is marked plainly:

> ⚠️ **CLIENT DECISION REQUIRED**

That marking is the point of this document — it exists to surface exactly those decisions, not to hide them behind a plausible-sounding default.

---

## Table of Contents

1. Cover / Title *(this page)*
2. [Document Control](#2-document-control)
3. [Executive Client Decision Summary](#3-executive-client-decision-summary)
4. [How to Review This Document](#4-how-to-review-this-document)
5. [Attendance Terminology](#5-attendance-terminology)
6. [Attendance Flow](#6-attendance-flow)
7. [Attendance Status Rules](#7-attendance-status-rules)
8. [Normal Working Day Scenarios](#8-normal-working-day-scenarios)
9. [Grace & Late Rules](#9-grace--late-rules)
10. [Early Departure](#10-early-departure)
11. [Break Rules](#11-break-rules)
12. [Shift Types](#12-shift-types)
13. [Roster Rules](#13-roster-rules)
14. [Holiday & Weekly Off](#14-holiday--weekly-off)
15. [Leave Interactions](#15-leave-interactions)
16. [Regularization](#16-regularization)
17. [Overtime](#17-overtime)
18. [Night Overtime](#18-night-overtime)
19. [OT Conflicts](#19-ot-conflicts)
20. [Attendance Period Lock](#20-attendance-period-lock)
21. [Employee Lifecycle](#21-employee-lifecycle)
22. [WFH & On-Duty](#22-wfh--on-duty)
23. [Timezone & DST](#23-timezone--dst)
24. [Indian HR Scenarios](#24-indian-hr-scenarios)
25. [Rule Precedence Matrix](#25-rule-precedence-matrix)
26. [Configuration Catalog](#26-configuration-catalog)
27. [Client Decision Register](#27-client-decision-register)
28. [Technical Verification Items](#28-technical-verification-items)
29. [Implementation Decisions](#29-implementation-decisions)
30. [Rule Traceability](#30-rule-traceability)
31. [Decision History](#31-decision-history)
32. [Change Control](#32-change-control)
33. [Final Client Sign-Off](#33-final-client-sign-off)

---

## 2. Document Control

### Document Purpose

This document defines how the HRMS Attendance module is expected to behave under normal, exceptional, and conflicting situations.

It is intended for **client review and approval**. The purpose is to establish a single, agreed business interpretation of attendance rules before final implementation is treated as complete.

Once approved, this document will serve as the reference for:

- Attendance implementation
- Testing
- User acceptance testing (UAT)
- Future changes
- Dispute resolution
- Payroll integration
- HR policy configuration

### Version History

| Version | Date | Status | Description | Approved By |
|---|---|---|---|---|
| 1.0 | 22-Aug-2026 | Client Review | Initial consolidated attendance business-rule document, restructured for formal client review and sign-off | |

*(Do not add future version rows speculatively — a new row is added only when a version is actually issued. See **Section 31 — Decision History** and **Section 32 — Change Control**.)*

---

## 3. Executive Client Decision Summary

> This section allows the client to review the most important attendance decisions before reviewing the detailed scenarios. Each item below is expanded in full, with options and current-behaviour detail, in its referenced section and in the full **Section 27 — Client Decision Register**.

| ID | Business Rule | Current Situation | Decision Options | Client Decision | Status |
|---|---|---|---|---|---|
| CD-001 | Night OT definition | Default config never classifies Night OT; enabling the "night window" mode still keys off shift crossing midnight, not actual clock time | (A) Any cross-midnight shift, (B) Actual clock-time window, (C) Explicit manual flag, (D) Other | | ⚠️ Open |
| CD-002 | Leave + OT | OT detected from punches is not cleared when the day becomes a full-day Leave; both facts can coexist | (A) Clear OT on a Leave day, (B) Allow OT to stand (current), (C) Require HR review, (D) Other | | ⚠️ Open |
| CD-003 | OT eligibility by grade | Setting exists but has no effect — behaves exactly like "Always eligible" | (A) Build a real grade check, (B) Remove this eligibility mode, (C) Document as alias for "Always eligible" | | ⚠️ Open |
| CD-004 | Holiday falling on Weekly Off | Day stays Weekly Off; no automatic substitute holiday is created | (A) Auto-substitute, (B) Weekly-off only, no substitute (current), (C) Treat as holiday instead, (D) Other | | ⚠️ Open |
| CD-005 | Post-lock corrections / arrears | Only mechanism is a full period reopen — no dedicated adjustment/arrears feature | (A) Build a dedicated adjustment feature, (B) Reopen + manual recompute only (current), (C) Handle entirely outside this system | | ⚠️ Open |
| CD-006 | Roster vs Shift-scoped policy | Shift-level policy resolves using the employee's originally-assigned shift, not the roster's shift for that date | (A) Policy follows roster's shift, (B) Keep current, (C) Disallow shift-level policy assignment | | ⚠️ Open |
| CD-007 | Work From Home | WFH regularization type exists but produces no distinct WFH status | (A) No distinct status (current), (B) Distinct WFH status in reports, (C) Manager-approved WFH without punches, (D) Other | | ⚠️ Open |
| CD-008 | On-Duty | On-Duty regularization type exists but produces no distinct status | (A) No distinct status (current), (B) Distinct On-Duty status, (C) Regularization-only (current partial), (D) Other | | ⚠️ Open |
| CD-009 | Flexible shift core hours | Core-hours window can be configured but is never enforced | (A) Build enforcement, (B) Hide the setting, (C) Accept as inactive | | ⚠️ Open |
| CD-010 | Mandatory break | Only deducted if punches show a matching gap; working through it is credited as worked time | (A) Auto-deduct even without a matching gap, (B) Keep current (punch-gap-only) | | ⚠️ Open |
| CD-011 | Excess break vs OT | No rule exists anywhere for whether excess break time offsets OT eligibility | No options established — genuinely open | | ⚠️ Open |
| CD-012 | Auto-Close naming/behaviour | Setting name implies auto clock-out insertion; it does nothing | (A) Build true auto-close, (B) Rename/relabel only (recommended minimum), (C) Leave as-is | | ⚠️ Open |
| CD-013 | Repeated lateness | Setting exists for a rolling-window half-day penalty; has zero effect today | (A) Build the rolling-window penalty, (B) Hide the setting, (C) Accept as inactive | | ⚠️ Open |
| CD-014 | Early-departure approval | "Requires approval" setting exists but is not enforced; classification is always after-the-fact | (A) Build a pre-approval gate, (B) After-the-fact classification only (current) | | ⚠️ Open |
| CD-015 | Half-day leave handling | Flat 0.50 credit applied regardless of "first half"/"second half" flag | (A) Evaluate only the specified half of the shift, (B) Keep flat 0.50 credit (current) | | ⚠️ Open |
| CD-016 | Reopen/recompute | Reopening a locked period does not auto-recompute | (A) Auto-recompute on reopen, (B) Manual recompute step (current), (C) Visible "stale" indicator instead | | ⚠️ Open |
| CD-017 | Split-shift rules | Block-mandatory / cross-block hours-compensation settings exist but their business meaning is unconfirmed | No options established — needs scoping | | ⚠️ Open |
| CD-018 | Punch rounding | Setting exists to round punch times before evaluation; currently has no effect | (A) Implement, (B) Hide, (C) Accept as inactive | | ⚠️ Open |

> Current system behaviour does **not** mean client-approved behaviour. Every row above is expanded with full context in its linked section, and consolidated with the remaining eight decision items (CD-019 to CD-026) in **Section 27 — Client Decision Register**.

---

## 4. How to Review This Document

### 4.1 How the Client Should Review This Document

For every rule and scenario in this document, please confirm:

1. **Is the scenario applicable to our organization?** (Some scenarios — e.g., split shifts, night shifts — may not apply to every client.)
2. **Is the expected result correct?**
3. **Is the rule interpretation correct?**
4. **If two rules conflict, is the stated precedence correct?**
5. **Is HR approval required for this outcome, or should it happen automatically?**
6. **Can HR modify the result after the fact, and how?**
7. **What should happen once the attendance period is locked (closed for payroll)?**

For each scenario, the client should answer the following four questions. Not every field applies to every scenario — for example, OT-related fields are omitted where overtime is not relevant to that scenario.

**Does this scenario apply to our organization?**

☐ Applicable ☐ Not Applicable ☐ Future Requirement

**Is the expected behaviour correct?**

☐ Approved ☐ Change Required

**If rules conflict, is the precedence correct?**

☐ Approved ☐ Change Required ☐ Decision Required

**Is approval required?**

☐ Automatic ☐ Manager ☐ HR ☐ Manager → HR ☐ Other

**Comments**

________________________________________

> **Current system behaviour does NOT mean client-approved behaviour.** Every "🔧 Current System Behaviour" statement in this document is a fact about the implementation as built today — not a statement that the client has approved it. Approval only exists once recorded in **Section 27 (Client Decision Register)** or **Section 33 (Final Client Sign-Off)**.

For every item marked **⚠️ CLIENT DECISION REQUIRED**, the client must provide an explicit decision before that rule is considered finalized. A consolidated register of every such item is in **Section 27**.

### 4.2 Status Labels Used in This Document

Every rule statement in this document is labelled with one of the following. Where current system behaviour and proposed business behaviour are the same, only one label is shown for brevity.

| Label | Meaning |
|---|---|
| 🔧 **CURRENT SYSTEM BEHAVIOUR** | What the system, as built today, actually does. This is a statement of fact about the implementation — not a statement that this is the approved business rule. |
| 📋 **PROPOSED / INTENDED BUSINESS BEHAVIOUR** | What the existing business documentation states the system *should* do, where that differs from, or adds detail beyond, current system behaviour. |
| ⚠️ **CLIENT DECISION REQUIRED** | No source document — code or business documentation — establishes a definitive answer. The client must decide. |
| 🟠 **DOCUMENTATION CONFLICT** | Existing source documents disagree and require clarification. Both statements are preserved; the contradiction is not resolved by this document. |
| 🔵 **IMPLEMENTATION GAP** | The intended business rule is known but the current system does not fully support it. |
| ⚪ **OUT OF SCOPE** | Explicitly outside this Attendance module (e.g., leave balances, statutory pay calculation). |

> No unresolved contradictions between the underlying source documents were identified while consolidating this document. If a reviewer identifies one during client review, it must be recorded using the 🟠 **DOCUMENTATION CONFLICT** label above — both original statements preserved side by side — rather than silently resolved in a document revision.

---

## 5. Attendance Terminology

Plain-language definitions, no code or database terms.

| Term | Meaning |
|---|---|
| **Attendance Day** | The single record representing one employee's attendance result for one calendar date. |
| **Working Day** | A date on which an employee is expected to be present, per the calendar (i.e., not a holiday, weekly off, or shutdown). |
| **Weekly Off** | An employee's designated rest day for the week (e.g., Sunday, or alternate Saturdays). |
| **Holiday** | A date on which the organization (or a subset of it) does not expect employees to work, drawn from a holiday calendar. |
| **Shift** | The work schedule for a day — start/end times (or a flexible window, or multiple blocks), plus break rules. |
| **Roster** | A schedule assigned to one specific employee for one specific date, which can differ from their normal default shift (used for rotating crews, temporary reassignment, etc.). |
| **Punch** | A single clock-in or clock-out event recorded for an employee, with a timestamp. |
| **IN Punch** | A punch recording the start of a period of presence. |
| **OUT Punch** | A punch recording the end of a period of presence. |
| **Worked Minutes** | The total time counted as "worked" for the day, after pairing IN/OUT punches and applying break deductions. |
| **Paid Day** | The fraction of a day (0.00–1.00) that counts as paid for payroll purposes. |
| **LOP (Loss of Pay)** | The fraction of a day (0.00–1.00) that counts as unpaid. Paid + LOP always total 1.00 for a given day. |
| **Late** | Arriving after the scheduled start time (beyond any configured grace period). |
| **Early Departure** | Leaving before the scheduled end time (beyond any configured grace period). |
| **Half Day** | A status representing partial attendance — half the day is treated as worked/paid, half as not. |
| **Absent** | No attendance recorded for an expected working day, or attendance below the minimum threshold, with no leave applied. |
| **Incomplete** | A day where punches exist but are insufficient to determine a clean result (e.g., a missing OUT punch) — pending resolution. |
| **Regularization** | The formal correction process an employee, manager, or HR uses to fix an attendance mistake (e.g., a forgotten punch). |
| **Overtime (OT)** | Time worked beyond the scheduled/required minutes for the day, subject to eligibility, minimums, and approval. |
| **Comp-Off** | Time off owed to an employee in lieu of overtime pay, as an alternative to being paid for the extra hours. |
| **Attendance Period** | A date range (typically a calendar month) that HR opens, manages, and eventually closes/locks as a single payroll cycle. |
| **Period Lock** | The state after an attendance period is finalized — attendance records for those dates become frozen and cannot be changed without formally reopening the period. |
| **Leave Projection** | A record mirrored into Attendance from wherever leave is approved, indicating an employee is on approved leave for a date (full or half day). This module does not manage leave applications, balances, or approvals itself. |

---

## 6. Attendance Flow

🔧 This reflects the order the system currently evaluates a day in, as reconstructed from the calculation engine. It is presented here as a business-readable flow — it is **not** independently confirmed as the client's intended conceptual model, only as what the system does.

```
Employee & Employment Status
        ↓
Employee Assignment (branch, department, shift, manager — as of the date)
        ↓
Calendar → Holiday / Weekly Off / Working Day
        ↓
Roster (may override the assigned shift, or override whether presence is expected)
        ↓
Assigned Shift (timing, breaks, duty blocks)
        ↓
Attendance Policy (grace, bands, missing-punch handling)
        ↓
Employee Punches
        ↓
Worked Time Calculation
        ↓
Late / Early / Break Evaluation
        ↓
Attendance Status (Present / Absent / Half-Day / Incomplete / Not Expected)
        ↓
Leave Overlay (may replace the status above)
        ↓
Overtime Detection (a separate, parallel fact — never changes the status above)
        ↓
Regularization (corrections re-enter this flow from the top, as new punches/roster entries)
        ↓
Approval (Overtime and/or Regularization, where required)
        ↓
Period Finalization / Lock (freezes the day for payroll)
```

**Plain-language explanation of each step:**

1. **Employment Status** — is the person even an employee on this date? (Before joining, or after exit, nothing else below applies.)
2. **Assignment** — where do they sit in the org, and what's their default shift, as of this specific date?
3. **Calendar** — is this a holiday, a weekly off, or an ordinary working day?
4. **Roster** — has HR/a manager scheduled this specific person differently for this specific date?
5. **Shift** — what are the actual timings and break rules?
6. **Attendance Policy** — what are the rules for judging lateness, absence, half-days?
7. **Punches** — what did the employee actually record?
8. **Worked Time / Late / Early / Break Evaluation** — the arithmetic.
9. **Attendance Status** — the day's headline result.
10. **Leave Overlay** — if approved leave exists for the date, does it change the result?
11. **Overtime** — was extra time worked, and does it qualify as recorded overtime?
12. **Regularization** — if something was wrong, how is it corrected?
13. **Approval** — who signs off on corrections and overtime?
14. **Period Lock** — once HR closes the payroll period, the day is frozen.

**Where the actual system order differs from a "natural" business reading of this flow:** Regularization is not a step that happens *after* everything else in a linear sense — approving a regularization request injects new punches (or a roster change) and re-runs the entire flow above from the top. There is no separate "correction" status; the corrected result always comes from the same calculation everyone else's attendance goes through.

---

## 7. Attendance Status Rules

🔧 These are the only statuses currently produced by the calculation engine.

| Status | When it occurs | Paid? | LOP? | Can HR modify? | Client confirmation |
|---|---|---|---|---|---|
| **PRESENT** | Worked minutes meet or exceed the "Present" hour-band threshold (and late/early bands don't force a lower status) | 1.00 (unless late/early band overrides) | 0.00 | Yes — via regularization (adds punches, day recalculates) | ☐ Approved / ☐ Change required |
| **ABSENT** | No punches (or below minimum threshold) on an expected working day, and missing-punch/hour-band policy says Absent; or a late/early band forces it | 0.00 | 1.00 | Yes — via regularization | ☐ Approved / ☐ Change required |
| **HALF_DAY** | Worked minutes fall in the "Half-Day" band, or a late/early band forces it | 0.50 | 0.50 | Yes — via regularization | ☐ Approved / ☐ Change required |
| **INCOMPLETE** | Punches exist but don't pair cleanly (e.g., missing OUT), and missing-punch policy defaults to Incomplete | 0.00 (until resolved) | 0.00 (until resolved) | Yes — via regularization; otherwise auto-resolved at period lock per policy | ☐ Approved / ☐ Change required |
| **NOT_EXPECTED** | Holiday / Weekly Off / Shutdown with no punches and nobody forced to work | 1.00 (paid rest day) | 0.00 | N/A — this is the calendar's own classification | ☐ Approved / ☐ Change required |
| **LEAVE** | An approved leave projection covers the day (full-day, or the leave-wins policy applies) | Per the leave's own paid/unpaid flag | Per the leave's own paid/unpaid flag | Only by changing the leave record elsewhere, or by policy set to "flag work-on-leave" instead | ☐ Approved / ☐ Change required |
| **NOT_JOINED** | Date is before the employee's employment start | 1.00 (not counted as absence) | 0.00 | No — derived purely from employment dates | ☐ Approved / ☐ Change required |
| **EXITED** | Date is after the employee's employment end | 0.00 | 1.00 | No — derived purely from employment dates | ☐ Approved / ☐ Change required |
| **CONFIG_ERROR** | No calendar or no attendance policy could be resolved for the employee on this date | Undefined — blocks period close until fixed | Undefined | HR must fix the underlying configuration (assign a calendar/policy), then recalculate | ☐ Approved / ☐ Change required |

🔵 **IMPLEMENTATION GAP — not currently produced by the system, despite existing as allowed values in the data model:** `WFH` (Work From Home) and `ON_DUTY`. See **Section 22**.

⚠️ **CLIENT DECISION REQUIRED — INCOMPLETE resolution at lock time.** The system can be configured to resolve a still-Incomplete day at period-lock time to either "treat as Absent" (default), "treat as Present," or "leave as Incomplete." The **status label itself stays "Incomplete"** for record-keeping even when the paid/LOP fraction is resolved — this label-vs-fraction split should be confirmed as acceptable for your payroll reporting, since a report reading "Incomplete" next to a paid/unpaid fraction may look unusual to a reviewer unfamiliar with this design.

---

## 8. Normal Working Day Scenarios

Default assumptions unless stated otherwise: shift 09:00–18:00 with a 60-minute unpaid lunch break (13:00–14:00), Grace-In/Out = 0, Present threshold ≥ 480 worked minutes, `missing_punch_behaviour = INCOMPLETE`.

Each scenario below uses the standard review structure: **Scenario**, **Example**, **Expected Result**, **Current System Behaviour**, and a **Client Review** block. OT-related fields are omitted from scenarios where overtime is not relevant.

### Scenario A01 — Full-Day Attendance

**Scenario:** Employee works the complete scheduled shift.

**Example:** Shift 09:00–18:00. Punches: 09:00 IN, 18:00 OUT.

**Expected Result:** Status = PRESENT · Worked time = 480 min (after break) · Paid = 1.00 · LOP = 0.00 · OT = 0.

🔧 **Current System Behaviour:** As above — this is the baseline, uncontested case.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A02 — Late Arrival

**Scenario:** Employee arrives after the scheduled start time, within grace or beyond it.

**Example:** Same shift, Grace-In = 15 min. Punches: 09:25 IN, 18:00 OUT.

**Expected Result:** Raw late = 25 min → after grace = 10 min late. If no late band forces a status change, status = PRESENT with `late_minutes = 10` recorded. If a configured late band (e.g., "30+ min late → Half-Day") is crossed, the band wins.

🔧 **Current System Behaviour:** As above — see **Section 9** for the full grace/band calculation.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A03 — Early Departure

**Scenario:** Employee leaves before the scheduled end time, within grace or beyond it.

**Example:** Same shift, Grace-Out = 10 min. Punches: 09:00 IN, 17:00 OUT.

**Expected Result:** Early = 60 min (after grace). Worked = 480 min minus the missing hour = 420 min. Status depends on early-departure bands and hour bands; may remain PRESENT with a flag, or drop to HALF_DAY.

🔧 **Current System Behaviour:** As above — see **Section 10**.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A04 — Late + Early on the Same Day

**Scenario:** Both a late arrival and an early departure occur on the same day.

**Example:** Same shift and grace. Punches: 09:20 IN, 17:30 OUT.

**Expected Result:** Both a late classification and an early-departure classification are computed independently; if either crosses a band that forces Half-Day/Absent, that outcome wins over what the raw worked-hours total alone would suggest.

🔧 **Current System Behaviour:** As above. ⚠️ See **Section 25** for the precedence rule governing this (late/early band outranks hour-band).

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required ☐ Decision Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A05 — Short Working Hours (below Half-Day threshold, above zero)

**Scenario:** Employee works only part of the day, below the Half-Day floor.

**Example:** Present ≥480, Half-Day 240–479, Absent <240 (example bands). Punches: 09:00 IN, 12:30 OUT (210 min worked).

**Expected Result:** Status = ABSENT (below the Half-Day floor), even though the employee was physically present for part of the day.

🔧 **Current System Behaviour:** As above.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A06 — Exactly at the Half-Day Threshold

**Scenario:** Worked minutes land exactly on the boundary of the Half-Day band.

**Example:** Half-Day band 240–479. Worked = 350 min.

**Expected Result:** Status = HALF_DAY. Paid = 0.50, LOP = 0.50.

🔧 **Current System Behaviour:** As above.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A07 — No Punches at All (Expected Working Day)

**Scenario:** Employee has no punches on an ordinary working day, with no leave applied.

**Example:** Ordinary working day, no leave applied. Punches: None.

**Expected Result:** Status = INCOMPLETE by default (not automatically Absent), unless the policy is configured with `missing_punch_behaviour = ABSENT`.

🔧 **Current System Behaviour:** As above — this default (Incomplete, not Absent) is a deliberate design choice.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | confirm this default matches expectation |
| Client Decision / Notes | ________________________________ |

### Scenario A08 — Missing IN Punch (orphan OUT)

**Scenario:** Employee has an OUT punch with no matching IN.

**Example:** Same shift. Punches: 18:00 OUT only, no IN.

**Expected Result:** Status = INCOMPLETE. Requires a regularization request to resolve.

🔧 **Current System Behaviour:** As above.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A09 — Missing OUT Punch (orphan IN)

**Scenario:** Employee has an IN punch with no matching OUT.

**Example:** Same shift. Punches: 09:00 IN only, no OUT.

**Expected Result:** Status = INCOMPLETE.

🔧 **Current System Behaviour:** As above.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A10 — Multiple Punches (extra IN/OUT pair)

**Scenario:** Employee steps out and back in during the day (not matching a defined break).

**Example:** Punches: 09:00 IN, 12:00 OUT, 12:30 IN, 18:00 OUT.

**Expected Result:** With the default "sum all pairs" multi-punch mode, both intervals are summed (the 12:00–12:30 gap is excluded as it's neither a punch-pair nor a matched break). With "first-in, last-out" mode instead, the whole 09:00–18:00 span counts, including the gap.

🔧 **Current System Behaviour:** As above — default mode is "sum all pairs."

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | confirm which multi-punch mode your organization needs |
| Client Decision / Notes | ________________________________ |

### Scenario A11 — Duplicate Punches

**Scenario:** The same punch direction is accidentally recorded twice in quick succession.

**Example:** Same shift, duplicate window = 60 seconds. Punches: 09:00:00 IN, 09:00:15 IN (accidental double-tap), 18:00 OUT.

**Expected Result:** The second IN is collapsed as a duplicate; treated as a single 09:00 IN.

🔧 **Current System Behaviour:** As above.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

### Scenario A12 — Orphan Punches Mixed with Valid Ones

**Scenario:** A valid punch pair exists alongside an unmatched orphan punch on the same day.

**Example:** Same shift. Punches: 09:00 IN, 13:00 OUT, 13:00 OUT (second OUT with no matching IN).

**Expected Result:** First pair (09:00–13:00) evaluates normally; the second OUT is an orphan and does not contribute worked time. Depending on missing-punch handling, this may still resolve the day or leave it flagged.

🔧 **Current System Behaviour:** As above.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |
| Client Decision / Notes | ________________________________ |

---

## 9. Grace & Late Rules

### How lateness is calculated (step by step)

1. **Raw late minutes** = actual IN time − scheduled start time (if positive).
2. **Grace adjustment** = raw late minutes − configured grace-in minutes (floor at zero).
3. **Final late minutes** = the grace-adjusted value; this is what's stored and reported.
4. **Applicable late band** = the configured range (e.g., "0–14 min: no action," "15–29 min: flag only," "30+ min: Half-Day") that the final late minutes fall into.
5. **Attendance status** = the band's mapped consequence, if any (Half-Day or Absent bands **override** the hour-based worked-minutes status — see below).
6. **Paid day / LOP** follow from whatever status results.
7. **Approval requirement** — 🔧 **currently, no late scenario requires pre-approval.** Late arrivals are judged automatically, never routed for manager sign-off before being recorded.

### Worked Example

**Shift:** 09:00–18:00. **Grace:** 15 minutes. **Punch:** 09:25 IN.

| Step | Value |
|---|---|
| 1. Raw late minutes | 25 |
| 2. Grace adjustment | 25 − 15 = 10 |
| 3. Final late minutes | 10 |
| 4. Applicable late band | Depends on configured bands (e.g., if the first band is "0–29 min: no consequence," this falls inside it) |
| 5. Attendance status | PRESENT (assuming no band consequence triggered) |
| 6. Paid / LOP | 1.00 / 0.00 |
| 7. Approval required? | No |

**Client confirmation:** ☐ Approved / ☐ Change required

### Repeated Lateness — (CD-013)

⚠️ **CLIENT DECISION REQUIRED.** A setting exists in configuration to convert repeated lateness (e.g., "3 late arrivals within 30 days") into an automatic half-day deduction, but **this has no effect today** — each day is judged completely independently, with no memory of prior lateness. If your organization has a policy like this, it needs to be scoped and built; it is not currently a working feature despite the setting being visible and editable. See **Decision Register CD-013**.

### Late + Half-Day Interaction, Late + Absent Interaction

📋 **Proposed/intended business behaviour, matching current system behaviour:** a late-band classification of Half-Day or Absent **overrides** whatever the hour-based worked-minutes bands alone would have produced. Concretely: an employee who worked a full 8 hours but arrived extremely late (crossing an "Absent" late-band threshold) is marked **ABSENT**, not Present, even though their total hours were sufficient.

**This precedence is real in the system today but is not written down anywhere as an explicit, named rule in prior business documentation** — it emerged from reading the calculation logic directly. Please confirm this is the behaviour you want: should severe lateness ever override a full day's worth of hours actually worked?

**Client confirmation:** ☐ Approved / ☐ Change required

---

## 10. Early Departure

| Aspect | Current behaviour |
|---|---|
| Grace | A configurable number of minutes of leeway before "early" starts counting, symmetric in concept to Grace-In. |
| Early departure calculation | Scheduled end time − actual OUT time (after grace), floored at zero. |
| Early bands | Same band structure as late bands — ranges of minutes mapped to no-action / flag / Half-Day / Absent. |
| Early departure approval | 🔵 A setting ("early-departure-requires-approval") exists in configuration but is **not enforced** — an employee can leave early and it is simply classified after the fact; no pre-approval gate exists today. |
| Early + Half-Day | Same override behaviour as late: an early-departure band mapped to Half-Day overrides the hour-based status. |
| Early + Absent | Same as above, for an Absent-mapped band. |
| Early + OT | Not applicable in the same day — early departure and overtime are evaluated from different ends of the shift and do not directly interact, though obviously an early departure reduces worked minutes and therefore reduces (or eliminates) any excess-hours OT calculation. |

⚠️ **CLIENT DECISION REQUIRED — (CD-014).** Should leaving early ever require pre-approval (blocking the punch or flagging it for manager sign-off before it's accepted), or is after-the-fact classification (the current behaviour) sufficient? See **Decision Register CD-014**.

**Client confirmation:** ☐ Approved / ☐ Change required

---

## 11. Break Rules

| Rule | Current behaviour |
|---|---|
| **Paid breaks** | 🔧 Matched break minutes are added back into worked time, so a paid break does not reduce the day's worked-minutes total. |
| **Unpaid breaks** | 🔧 Matched break minutes are subtracted from worked time. |
| **Required (mandatory) breaks** | 🔧 **A mandatory break is only deducted if the employee's punches actually show a matching gap.** If an employee works through a mandatory unpaid lunch without punching out for it, the system does **not** invent or auto-insert that deduction — the full span is counted as worked. |
| **Missed breaks** | Same as above — a break the employee never actually took (no punch gap) has no automatic consequence today. |
| **Excess breaks** | 🔧 A break longer than its configured maximum is detected and the excess minutes are recorded as a fact. **No automatic consequence** (flag escalation, pay deduction, approval requirement) is applied. |
| **Multiple breaks** | 🔧 Each detected punch-gap is matched against configured break windows on a first-match basis; only one break can be matched per gap. |
| **Breaks crossing shift boundaries** | ⚠️ Not specifically documented — treat as a **technical verification item** (see **Section 28**); this edge case has not been explicitly verified. |
| **Break + overtime** | ⚠️ **CLIENT DECISION REQUIRED** — see below (CD-011). |

### Worked Example

Shift 09:00–18:00 (540 min span), unpaid break 13:00–14:00 (60 min).

- Employee punches IN 09:00, OUT 18:00, with a matching 13:00–14:00 gap.
- Total span: 540 min. Unpaid break deducted: 60 min. **Worked minutes: 480.**
- Scheduled requirement: 480 min (540 − 60). Result: exact match, 0 overtime.
- If the employee instead works through lunch (no punch gap at 13:00–14:00): worked minutes = 540 (full span), because no break was matched to deduct.

**Client confirmation:** ☐ Approved / ☐ Change required

### ⚠️ CLIENT DECISION REQUIRED — Excess break vs. Overtime (CD-011)

No rule anywhere — not in code, not in documentation, not in any test — decides whether time spent in an excess (over-length) break should reduce eligible worked/overtime minutes beyond what the ordinary unpaid-break deduction already does, or whether excess break time itself should ever be treated as a negative adjustment against overtime. **Do not assume an answer here; this needs an explicit decision.**

**Client decision:** _______________________

### ⚠️ CLIENT DECISION REQUIRED — Mandatory break auto-deduction (CD-010)

Should a mandatory unpaid break be force-deducted from worked hours even when the employee's punches don't show a matching gap (i.e., they worked through it without punching out)? Current behaviour credits that time as worked. This has real payroll impact — please confirm this is the desired policy, or specify what should happen instead.

**Client decision:** _______________________

---

## 12. Shift Types

### Fixed Shift
🔧 **CURRENTLY WORKING.** Same start/end time every day. Lateness measured against the fixed start; early departure against the fixed end. Worked time = span between paired punches, minus unpaid breaks, plus paid breaks. OT = excess over scheduled minutes. Missing punches follow the standard missing-punch rule (**Section 7**).

### Flexible Shift
🔧 **PARTIALLY WORKING.** The employee can arrive/leave within a configured window, provided required hours are completed. Schedule window resolution exists and functions. **However:**
- 🔵 **Core hours enforcement does not exist.** A "core hours" window (e.g., everyone must be present 11:00–16:00) can be configured but is never checked by the system in any way. See **Section 26** and the dedicated decision below.
- ⚠️ **No dedicated test in the codebase confirms exactly how late/early/status is computed for a Flexible shift end-to-end** (see **Section 28**). Treat Flexible-shift outcomes as **lower confidence** than Fixed/Split, pending explicit verification, if this shift type is important to your organization.
- OT is computed against `required_minutes` as a fallback baseline when no fixed start/end resolves.

⚠️ **CLIENT DECISION REQUIRED — (CD-009).** If Flexible shifts (with a meaningfully enforced "core hours" requirement) are important to your organization, this needs to be built and verified before go-live — the setting exists today but does nothing.

**Client decision:** _______________________

### Split Shift
🔧 **CURRENTLY WORKING**, with a documented simplification. Two or more separate work blocks in one day (e.g., 06:00–10:00 and 14:00–18:00 for security/field staff). Each block needs its own complete punch pair. If a block is missed entirely, the configured "missed-block behaviour" applies (Ignore / Half-Day / Absent / Require Correction). **Lateness/early-departure are not calculated for split shifts** — only whether the required blocks/hours were met. **No partial credit** exists for a partially-worked block (e.g., working half of a 4-hour block does not credit 2 hours toward the total) — this is a known, documented simplification, not a bug. See **CD-017**.

### Cross-Midnight (Night) Shift
🔧 **CURRENTLY WORKING** for scheduling and date attribution. A shift starting at 22:00 and ending at 06:00 the next calendar day is attributed **entirely to the start date** — not split across two days, and not recorded on the following day at all.

⚠️ **See Section 18 (Night Overtime)** — while the shift itself schedules and evaluates correctly, the system's *overtime classification* for night shifts does not reliably distinguish a genuine overnight shift; this is a separate, high-priority open decision (CD-001).

### Rotational Shift
🔧 **CURRENTLY WORKING** via the roster mechanism (**Section 13**) — a per-employee, per-date roster entry can assign a different shift than the employee's default, which is how rotating crews (e.g., week 1 on Morning, week 2 on Night) are supported today. There is **no automatic rotation generator** — rosters must be entered (manually or via a bulk operation) for each date; automatic generation of a rotating pattern is a future capability, not built today.

### 24×7 Shift / Continuous Operations
🔧 **CURRENTLY WORKING**, via a combination of: shift-level flags that let a shift "operate" on a holiday or weekly-off without a special exception, and roster-level overrides that force expected presence on specific dates. These building blocks are individually tested. ⚠️ **No end-to-end scenario test combines them the way a real 3-shift rotating roster would operate** (see **Section 28**) — treat a genuine 24×7 rotating-crew deployment as functionally supported but not validated as a complete package.

---

## 13. Roster Rules

| Topic | Current behaviour |
|---|---|
| **Roster assignment** | A roster is a per-employee, per-date entry that can assign a specific shift for that date, and/or flag the date as "treat as week-off" or "treat as working" (overriding the calendar's default expectation). |
| **Roster override (schedule)** | A **published** roster entry always wins over the employee's default assigned shift for scheduling purposes. |
| **Weekly-off pattern vs. roster** | A roster's "treat as week-off" flag can make an otherwise-Working calendar day Not Expected for that one employee (e.g., a rotating crew member's day off this week). |
| **Rotational roster** | Supported by entering roster rows per date; no automatic generator (see **Section 12**). |
| **Roster vs. employee assignment** | Roster wins for *scheduling* purposes only when published. A **draft** (unpublished) roster row has **zero effect** — it is completely invisible to calculation, and it blocks period close if left unpublished. |
| **Roster changes** | Take effect for the specific date they're entered against; do not retroactively change past days. |
| **Roster changes during an open attendance period** | Take effect immediately upon publish — the next recalculation of that day picks up the new schedule. |
| **Roster changes after OT is already detected** | 🔧 No automatic re-evaluation exists specifically for "roster changed, therefore re-check this day's already-detected overtime." The next `calculate()` call (triggered by any other correction) does refresh the day's overtime figures **as long as the overtime record itself is still PENDING** — once an overtime decision is Approved/Rejected, it is frozen and will not be revised even if the underlying roster/shift changes. |

### ⚠️ CLIENT DECISION REQUIRED — Roster vs. Shift-scoped Policy (which rule wins?) (CD-006)

**This is a genuine, documented mismatch, not a hypothetical:** if an Attendance Policy (or Overtime/Regularization Policy) is assigned at the **Shift** level, and an employee is temporarily moved to a different shift via a published roster, the system still resolves that Shift-level policy using the employee's **originally assigned** shift — **not** the roster's shift for that date.

**Practical effect:** HR moves someone to Night Shift for one week via roster (which correctly changes their working hours). If that person's normal daytime shift has its own specific Attendance Policy (say, a stricter late-grace rule), that daytime policy is still what judges their attendance during the night-shift week — not any policy attached to Night Shift.

**Options:**
- **A.** Make Shift-scoped policy resolution follow the roster's shift for that date (so "if I moved them to Night Shift, Night Shift's rules should apply").
- **B.** Keep current behaviour (policy stays tied to the originally-assigned shift) and document it clearly as intentional.
- **C.** Disallow assigning policies at the Shift level entirely, to remove the ambiguity.

**Client decision:** _______________________

---

## 14. Holiday & Weekly Off

### Day-type precedence (current system behaviour)

1. A date-specific exception (Shutdown / Special Working Day / Substitute Holiday / Cancelled Holiday) — always wins first.
2. Otherwise, a listed holiday.
3. Otherwise, the weekly-off pattern.
4. Otherwise, an ordinary working day.

| Scenario | Result |
|---|---|
| Normal holiday, shift doesn't operate | NOT_EXPECTED |
| Working holiday (shift/roster forces presence) | Evaluated normally; `worked_on_holiday` recorded |
| Weekly off, no override | NOT_EXPECTED |
| Working weekly off (shift/roster forces presence) | Evaluated normally; `worked_on_weekly_off` recorded |
| Roster override — treat working day as week-off | NOT_EXPECTED, even though the calendar itself says Working |
| Special working day (exception) | Treated as an ordinary expected working day |
| Shutdown | NOT_EXPECTED unless specifically rostered |
| Holiday substitution | Manual only — see below |

### ⚠️ CLIENT DECISION REQUIRED — Holiday falling on a Weekly Off (CD-004)

**Current system behaviour:** if a public holiday lands on an employee's weekly-off day (e.g., a holiday falls on a Sunday, which is already the standing weekly off), **the day stays classified as Weekly Off.** The system records that a holiday coincided with it (visible to HR as a flag), but **no substitute day off is automatically created.**

**Example:** Independence Day falls on a Sunday, and Sunday is the standing weekly off. Result: the day is Weekly Off (flagged "holiday coincided"). Employee is not expected to work; day is fully paid, same as an ordinary weekly off. No extra day off is created anywhere else automatically.

**This is one of the most common expectations in Indian HR policy — many organizations expect an automatic substitute working day off elsewhere.** This is **not** built today. If a substitute is wanted, HR must manually create a "Substitute Holiday" exception on a different date — there is no automatic trigger.

**Please choose:**
- **A.** Provide an automatic substitute holiday when this happens (would need to be built).
- **B.** Treat it only as a weekly off, as today — no substitute (current default).
- **C.** Treat it as a holiday instead of weekly-off (overriding the current "weekly-off wins" carve-out).
- **D.** Another organization-specific rule.

**Client decision:** _______________________

### Optional / Restricted Holidays

📋 **Current system behaviour, matching proposed default:** Optional/Restricted holidays (e.g., regional festivals not everyone observes) are treated as **ordinary working days by default**. A company-wide setting can instead make them hard holidays for everyone.

**Example:** A regional festival is listed as "Optional." By default, employees work normally that day unless they separately apply for leave. If the company-wide switch is turned on, nobody is expected to work that day at all — it becomes a hard holiday.

**Client confirmation:** ☐ Approved / ☐ Change required

### Special Working Day / Shutdown / Holiday Substitution

- **Special Working Day:** an exception that forces a date that would otherwise be a holiday or weekly-off to be treated as an ordinary expected working day (e.g., "this Saturday is a working day this month to compensate for an extended break elsewhere"). 🔧 Currently working, supported.
- **Shutdown:** a declared closure — nobody expected to work unless explicitly rostered. 🔧 Currently working.
- **Holiday substitution:** supported, but **entirely manual** — HR must create the exception row by hand for each occurrence. There is no automatic "Sunday-holiday triggers Monday-substitute" rule (tied directly to the decision above).

---

## 15. Leave Interactions

**Important scope note, applying to this entire section:** ⚪ **OUT OF SCOPE** — this Attendance module does **not** contain a Leave application system. It receives a signal from wherever leave is approved elsewhere ("this employee has approved leave for this date, this fraction of the day, paid or unpaid") and reflects it on the attendance day. There is no leave balance tracking, accrual, or leave-application workflow inside this module — that is a **future module**, entirely out of scope for this document's sign-off. Confirm this scope boundary is acceptable:

**Client confirmation:** ☐ Approved (Attendance mirrors leave only; balances/accrual/applications are a separate future build) / ☐ Change required

| Situation | Current behaviour |
|---|---|
| Full-day leave, no punches | Status = LEAVE; day counted per the leave's own paid/unpaid flag |
| Half-day leave, no punches | 0.50 credited as leave; remaining 0.50 treated as LOP for the unworked half (unless punches exist — see below) |
| Multiple half-day leave entries on the same date | Their fractions sum, capped at 1.00 total — the system rejects a combination that would exceed a full day |
| Leave with no punches | As above |
| Leave with punches (full-day leave, default "leave wins" mode) | Status = LEAVE regardless of punches; late/early flags cleared |
| Leave with punches (alternate "flag work-on-leave" mode) | Punch-derived status is kept instead; day is flagged so HR can see the employee worked despite being on leave |
| Half-day leave + full-day punches | Status = HALF_DAY (0.50 leave credit + 0.50 from punch-derived work) |
| Leave + late | If leave wins the day, late/early classifications from punches are cleared along with the rest of the punch-derived outcome |
| Leave + early | Same as above |
| Leave + regularization | A regularization approval recalculates the day; the leave overlay is reapplied on top of the recalculated punch-derived result |
| Leave cancellation | Reverts the day to whatever the punch-derived outcome would be, on the next recalculation |
| Leave + locked period | Any leave sync or cancellation is **refused** once the period is locked — the period must be reopened first |

### ⚠️ CLIENT DECISION REQUIRED — Leave + Overtime (highest-priority open item in this section) (CD-002)

**No rule exists anywhere — not in code, not in any business document, not in any test — for what should happen when an employee has approved full-day leave for a date but also has punches on that same date that would independently generate overtime.**

**Current system behaviour (a side effect of execution order, not a deliberate design choice):** overtime is calculated from punches **before** the leave overlay runs. The leave overlay replaces the attendance status (e.g., to LEAVE) but does **not** clear `ot_minutes_detected` — so a day can show status = LEAVE while still carrying non-zero overtime minutes underneath, which would look contradictory on a payroll report.

**Options:**
- **A.** Ignore/clear any OT detected on a day that becomes a full-day Leave.
- **B.** Allow the OT to stand alongside the Leave status (current behaviour).
- **C.** Require HR approval/review specifically for this combination before it's finalized.
- **D.** Another organization-specific rule.

**Client decision:** _______________________

### Related decision — Half-day leave and "which half" (CD-015)

⚠️ **CLIENT DECISION REQUIRED (lower priority).** Half-day leave records whether it's the "first half" or "second half" of the day, but the system currently applies a **flat 0.50-day credit** regardless — it does not actually limit punch evaluation to the specified half of the shift. A "second half" leave doesn't currently exclude morning punches any differently than a "first half" leave would. Confirm whether this flat approach is acceptable, or whether true half-shift evaluation is required.

**Client decision:** _______________________

---

## 16. Regularization

**In plain language:** Regularization is the formal correction process an employee (or their manager, or HR) uses when an attendance record is wrong — most commonly a forgotten punch.

| Aspect | Current behaviour |
|---|---|
| **Who can submit it** | Configurable per policy — employee themselves, manager on the employee's behalf, and/or HR, independently switchable. |
| **Allowed types** | Missing Punch, Wrong Punch, Wrong Shift, Wrong Status, Work-From-Home, On-Duty, Excess Break, Full-Day correction — which of these are permitted is configured per policy. |
| **Missing punch correction** | Adds the missing punch; day is recalculated from scratch through the normal rules. |
| **Backdated correction** | Allowed up to a configurable maximum number of days in the past. |
| **Attachments** | Can be required or optional, per policy. |
| **Approval chain** | Auto (no human review) / Manager only / HR only / Manager-then-HR, configurable per policy, and can differ by correction type. |
| **Self-approval restriction** | Hard-coded, always blocked, **no policy setting can disable this** — an employee (or a manager) can never approve their own request. |
| **Rejection** | Leaves the attendance day completely unchanged; no punches or roster entries are written. |
| **Cancellation** | Available; symmetric to rejection in effect. |
| **Monthly limits** | A configurable cap on how many requests one employee can submit per month. |
| **Behaviour after period lock** | New requests for a locked date are **refused outright** — the period must be reopened first. |

**Important clarification, worth reading carefully:** regularization does **not** directly overwrite the final attendance status. Approving a "Missing Punch" request adds the missing punch (and/or updates the roster's assigned shift for that date), then the day is **recalculated from scratch** using the exact same rules every other day goes through. This is a deliberate audit-trail design — nothing is ever hand-edited to a specific status.

**Client confirmation:** ☐ Approved / ☐ Change required

### Scenario — Missing IN

**Scenario:** Employee forgot to punch in.

**Example:** Submits a Missing Punch request with the correct time and a reason. Manager approves. System inserts the IN punch (source = Regularization). Day recalculates using the normal rules — the corrected result depends on the same late/early/hour-band logic as any other punch would.

🔧 **Current System Behaviour:** As above — currently working.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |

### Scenario — Missing OUT

**Scenario:** Symmetric to Missing IN, for a forgotten OUT punch.

🔧 **Current System Behaviour:** Currently working, same mechanism as Missing IN.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |

### Scenario — Incorrect Punch

**Scenario:** Employee punched at the wrong time (e.g., device malfunction recorded 03:00 instead of 09:00).

**Example:** Regularization request corrects it by inserting the accurate punch alongside the original (original punches are never deleted or edited — corrections are always additive).

🔧 **Current System Behaviour:** As above.

**Client Review**

| Field | Response |
|---|---|
| Applicability | ☐ Applicable ☐ Not Applicable ☐ Future Requirement |
| Business Rule | ☐ Approved ☐ Change Required |
| Comments | ________________________________ |

### Scenario — WFH (Work From Home) request (CD-007)

⚠️ **CLIENT DECISION REQUIRED — this type is currently only partially functional.** Submitting and approving a "WFH"-typed regularization request is allowed by policy today, but **by itself it does not produce a WFH attendance status.** It only has any effect if the approval also adds punches or changes the roster's shift — in which case the resulting day is evaluated as an ordinary Present/Absent/etc. day, not as a distinct "WFH" record. See **Section 22** for the full discussion.

### Scenario — On-Duty request (CD-008)

⚠️ Same situation as WFH above — the type exists and can be submitted/approved, but produces no distinct "On-Duty" status. See **Section 22**.

### Other supported types

**Wrong Shift** — on approval, publishes/updates a roster entry with the correct shift for that date, then recalculates. **Currently working.**
**Wrong Status / Full-Day correction** — gate the submission as an allowed type, but ultimately resolve through the same punches/roster mechanism as the others — there is no separate direct "overwrite the status to X" path.

**Distinguishing supported vs. configuration-only:** the request-type list itself (including WFH/On-Duty) is fully functional as a *submission and approval gate* — HR can restrict which types are allowed, requests of a disallowed type are rejected at submission. What is **not** fully functional is any type-specific *outcome* beyond "insert punches and/or change the roster shift." WFH and On-Duty are the two types where this gap is most visible, because their names imply a distinct result that the system doesn't produce.

---

## 17. Overtime

| Aspect | Current behaviour |
|---|---|
| **When OT is detected** | Worked minutes exceed scheduled/required minutes for the day, and the excess is positive. |
| **Minimum OT** | A configurable minimum threshold — excess below this is discarded (treated as zero OT). |
| **Rounding** | The excess minutes (not the punch times themselves) can be rounded up/down/nearest to a configured interval. |
| **Daily cap** | A configurable maximum OT minutes per day; excess above the cap is clipped. |
| **Weekly cap** | A configurable maximum per ISO week, computed against the sum of OT already recorded on other days that week. |
| **Monthly cap** | Same idea, at calendar-month grain. |
| **Approval** | Required by default (Manager chain); can be configured to auto-approve instead. |
| **Auto approval** | If the policy sets "no approval required," or the approval chain is set to Auto, OT is recorded without any human review. |
| **Multi-stage approval** | Manager-then-HR chain supported; if no manager can be resolved for the employee on that date, the request routes straight to HR. |
| **Rejection** | Rejected OT is recorded as zero approved minutes for the day; frozen — a later recalculation will not silently revise a rejected decision. |
| **Approved OT** | Recorded as `ot_minutes_approved` on the day, separate from the raw detected minutes. |
| **Frozen OT** | Once Approved or Rejected, an overtime decision does not change even if the underlying day is later recalculated (e.g., via an unrelated regularization) — see the cross-reference in **Section 19**. |
| **Comp-off** | ⚪ If configured, approved OT can convert into comp-off minutes instead of being paid, with an optional expiry date. This produces a **fact only** — no comp-off balance, ledger, or redemption mechanism exists in this module; that belongs to a future Leave module (out of scope). |
| **Holiday OT** | Correctly classified and detected when worked minutes occur on a holiday. |
| **Weekly-off OT** | Same, for a weekly-off day. |
| **Night OT** | ⚠️ **See the dedicated Section 18 — this is not reliably supported today.** |

**One important structural point:** overtime **never changes** the day's Present/Absent/Half-Day status — the two are always separate, parallel facts. A day can be Present with 0 minutes of OT, or Present with 90 approved minutes of OT; approving or rejecting the OT never retroactively changes whether the day itself was Present.

**Client confirmation:** ☐ Approved / ☐ Change required

### ⚠️ CLIENT DECISION REQUIRED — OT eligibility "by grade" (CD-003)

A setting exists to restrict overtime eligibility to specific employee grades ("only non-managerial staff are OT-eligible," a common requirement in Indian manufacturing where OT eligibility is often tied to grade by policy or law). **Current behaviour: this setting has no actual effect — it behaves exactly like "Always eligible."** No employee grade, designation, or assignment field is consulted at all. If grade-based OT restriction is a genuine requirement, this must be built before go-live — this is flagged as one of the highest-risk gaps in the whole module, because it could result in overtime being detected and even auto-approved for employees who should never have been eligible.

**Client decision:** _______________________

---

## 18. Night Overtime

**This is a dedicated, high-priority decision.** It is the single sharpest contradiction found between the system's original design intent and what was actually built, and it directly affects payroll-facing figures for any organization with genuine overnight shifts (security, hospitals, manufacturing, 24×7 operations).

### The conflict, explained in plain language

The original design for this module explicitly called for "night shift" to be its own, independently-set flag — something HR marks on a shift deliberately, separate from whether the shift happens to cross midnight. The reasoning given at the time was that a shift crossing midnight by a few minutes (say, 23:55–00:05) is not necessarily what anyone would call a "genuine" night shift, while a shift that runs entirely in the evening (say, 20:00–23:30, never crossing midnight at all) might still deserve night-shift treatment depending on the organization's policy.

**What was actually built does the opposite of that stated intent:** whether overtime gets classified as "Night" is decided **purely by whether the shift's schedule crosses midnight** — there is no independent "is this a night shift" concept anywhere in the system. And even that cross-midnight check only takes effect if a separate mode setting is turned on; **with the default setting, night overtime is never classified as Night at all** — it always reads as ordinary ("Normal") overtime, regardless of how many hours were worked in the middle of the night.

There is also a "night time window" setting (e.g., 22:00–06:00) that looks like it should be the actual mechanism — but it is **never checked against anything.** Configuring it has zero effect.

### Net effect today

- A genuinely overnight security/hospital/manufacturing shift, using the system's default configuration, will **never** produce a single Night-classified overtime record — ever — regardless of how many overnight hours are worked.
- Turning on the "check the night window" mode does make Night classification possible, but it still only triggers based on whether the *shift* crosses midnight, not whether the actual worked minutes fall inside the configured night-time window.
- **No money is affected by this today** — this module never calculates OT pay, only classifies OT for reference/reporting. But if your organization (or a downstream payroll system) relies on the "Night" classification to apply a different pay rate, that classification will currently be silently missing or misleading.

### How should the organization define Night OT?

⚠️ **CLIENT DECISION REQUIRED — (CD-001).**

- **A.** Any cross-midnight shift automatically counts as producing Night OT (fixes the current "default never produces Night" gap with the simplest possible rule).
- **B.** OT should be classified as Night specifically when it falls within a configured night-time clock window (e.g., 22:00–06:00), independent of whether the shift crosses midnight — this is closer to the setting's current name and the "night window" fields that already exist but do nothing.
- **C.** A shift should be explicitly, manually marked "this is a night shift" by HR — independent of both the cross-midnight flag and any time window — matching the module's original design intent.
- **D.** Another organization-specific rule (e.g., a combination of B and C).

**Client decision:** _______________________

---

## 19. OT Conflicts

| Scenario | Rule A | Rule B | Which wins? | Current behaviour | Client decision |
|---|---|---|---|---|---|
| OT + Leave | Approved full-day leave | Punches generating OT | ⚠️ **Undecided (CD-002)** | OT is not cleared when leave overwrites the status — see **Section 15** | _______________ |
| OT + Regularization | An approved correction changes the day's punches | An already-Approved/Rejected overtime record for that day | **The existing OT decision wins — frozen** | The corrected punches feed into the day's *detected* OT figures, but a terminal (Approved/Rejected) OT record is never revised by the recalculation. Documented as deliberate, but leaves the two facts able to diverge with no reconciliation path short of a full period reopen. | ☐ Approved / ☐ Change required |
| OT + Roster change | A published roster changes the shift after OT was first detected | A still-PENDING overtime record | **The next recalculation refreshes the figures** | Works correctly only while the OT record is still PENDING — once decided, same freeze as above applies | ☐ Approved / ☐ Change required |
| OT + Shift change | A shift-version change (new timings) mid-period | Already-detected OT for prior days | Not specifically tested | No test found combining a mid-period shift-version change with existing OT records | ⚠️ **Needs verification (see Section 28)** |
| OT + Holiday | Worked minutes on a holiday | — | OT is detected and classified as Holiday-class | Correctly working | ☐ Approved / ☐ Change required |
| OT + Weekly Off | Worked minutes on a weekly off | — | OT is detected and classified as Weekly-Off-class | Correctly working | ☐ Approved / ☐ Change required |
| OT + Excess Break | Time spent in an over-length break | Overtime eligibility of the remaining time | ⚠️ **Undecided (CD-011)** | No rule exists — see **Section 11** | _______________ |
| OT + Attendance Period Lock | Pending OT approval | Attempt to close the period | **Lock is blocked — pending OT is a hard finalize blocker** | Correctly working; the period simply cannot close until every OT record is decided | ☐ Approved / ☐ Change required |

---

## 20. Attendance Period Lock

| Concept | Meaning |
|---|---|
| **Open period** | Attendance for the date range can be freely calculated, corrected, and recalculated. |
| **Finalization** | HR runs a formal close process: validate → fix blockers → finalize. |
| **Validation** | A pre-check that reports every reason the period cannot yet be closed. |
| **Lock** | The frozen state after finalize — no further changes are possible without reopening. |
| **What becomes frozen** | Every attendance day's final status, paid/LOP fraction, and approved OT minutes for the period; a per-employee summary is snapshotted for payroll handoff. |
| **What HR can/cannot change** | Nothing, for dates inside a locked period — no new punches, no recalculation, no roster changes, no new regularization requests, no OT approve/reject, no leave sync/cancel. Everything is refused until the period is reopened. |
| **Reopen** | A separately-permissioned action that unlocks the days again. |
| **Recalculation after reopen** | 🔧 **Does not happen automatically.** Reopening only removes the lock — any changes still need to be manually triggered to recompute. |

### Scenarios

**Complete period, ready to close:** all days have a resolved status, no pending requests, all rosters published. Validate returns no blockers. Finalize succeeds, days lock, summary snapshot is frozen.

**Incomplete attendance blocks finalize:** if the policy is configured to "keep Incomplete as Incomplete" (rather than auto-resolving it), any day still Incomplete blocks the close until resolved (either via regularization, or by changing the policy to auto-resolve at lock time).

**Missing punches / missing attendance records:** any employee-date in the period range with **no attendance record at all** blocks finalize — this is treated as a coverage gap, distinct from a resolved Incomplete/Absent day.

**Pending OT blocks finalize:** as in **Section 19**.

**Pending regularization blocks finalize:** any correction request still awaiting a decision blocks the close.

**Leave changes:** leave sync/cancellation is refused for any date inside a locked period — must reopen first.

**Mutation attempted after lock:** every one of the seven mutation types (punches, recompute, roster changes, regularization submission, OT approve/reject, leave sync, leave cancel) is refused for a locked date.

**Reopen:** requires a separate permission from ordinary lock/finalize. Unlocks the date range; does not recompute anything automatically.

**Client confirmation:** ☐ Approved / ☐ Change required for the six close-blockers, all-or-nothing (see below)

### ⚠️ CLIENT DECISION REQUIRED — Should every blocker be hard, or should some be waivable with a warning?

**Current behaviour:** all six validation blockers (Config Error, Incomplete attendance under "keep incomplete" policy, Pending Regularization, Pending Overtime Approval, Unpublished Roster, Employees Without Attendance) are **hard blockers** — nothing can be waived without resolving it first. Confirm this all-or-nothing approach matches your payroll process, or specify which (if any) should instead be allowed to pass with a warning.

*(This decision is not currently in the numbered Decision Register — it is a genuine open item surfaced during this consolidation and is listed as an additional business decision in Section 27, Category A.)*

**Client decision:** _______________________

### ⚠️ CLIENT DECISION REQUIRED — Post-lock corrections (CD-005)

There is currently **no dedicated "adjustment after lock" feature.** The only mechanism to fix something discovered after a period is already closed (and possibly already paid) is a **full reopen** of the entire period — a blunt instrument: it unlocks every day in the range, does not auto-recompute, and has no arrears-tracking for a payroll cycle that may have already been run externally.

**Choices:**
- **A.** Build a proper post-lock adjustment/arrears feature (recommended before the first fully-paid, closed payroll cycle, per the source audit).
- **B.** Rely on reopen + manual recompute as the only mechanism (current state).
- **C.** Treat post-lock corrections as strictly a manual, payroll-side process entirely outside this system.

**Client decision:** _______________________

### ⚠️ CLIENT DECISION REQUIRED — Automatic recompute on reopen? (CD-016)

**Current behaviour:** reopening does not auto-recompute (a deliberate payroll-safety choice, so numbers already reported externally don't silently change). Confirm this is the desired behaviour, or specify a preference for automatic recompute, or for a visible "stale — needs recompute" indicator on reopened days.

**Client decision:** _______________________

---

## 21. Employee Lifecycle

| Event | Current behaviour |
|---|---|
| **Joining date** | Before this date, every day is classified NOT_JOINED (fully paid, not counted as absence). |
| **Before joining date** | Same as above. |
| **Active employee** | Ordinary evaluation applies. |
| **Exit date** | After the recorded last working day, every day is classified EXITED (fully unpaid, LOP). |
| **After exit** | Same as above. |
| **Rehire after a gap** | A new employment record is created; days in the gap (no employment record covering them) fall into NOT_JOINED/EXITED logic depending on which side of the gap they're on. |
| **Department change** | Takes effect from the date recorded — earlier days keep the prior department's context (for calendar/policy resolution). |
| **Branch change** | Same — effective-dated, does not retroactively change past days. |
| **Manager change** | Same — effective-dated. Approval routing for a regularization/OT request uses the manager **as of the attendance date being corrected**, not today's manager. |
| **Shift change** | Same — effective-dated via the assignment/roster mechanism. |
| **Policy change** | A new policy version, once published, applies going forward; already-calculated days keep the policy version they were originally resolved with (their `computation_snapshot` records exactly which version was used) — they are **not** silently retroactively recalculated. |
| **Policy version change** | Same as above. |
| **Designation change** | Effective-dated, same pattern. |
| **Grade change** | Effective-dated, same pattern. |

### Does the new rule apply immediately or only from its effective date?

📋 **Proposed/confirmed pattern, consistent across the module:** every lookup (employment, assignment, calendar, policy) is always done **"as of" the specific date being evaluated** — never "as of today." A transfer or promotion recorded effective 15 August only affects attendance calculated for 15 August onward; days before that date continue to resolve against the prior department/policy/shift, even if recalculated later.

⚠️ **Not independently verified by a dedicated test for every combination (see Section 28):** while the *mechanism* (as-of-date lookups) is confirmed and used consistently, specific mid-period scenarios — an employee transferred mid-month, a policy republished mid-month, a shift-version changed mid-month, each followed by a recalculation of surrounding days — are **not covered by any dedicated test found in the codebase.** Treat the general "as-of-date" rule as reliable, but treat any *specific* mid-period edge case as unverified until tested.

**Client confirmation:** ☐ Approved (effective-dated changes only, never retroactive) / ☐ Change required

### ⚠️ CLIENT DECISION REQUIRED — Manager as-of-date for approvals (CD-020)

**Current behaviour:** the manager who approves a regularization or overtime request is the manager assigned to the employee **as of the attendance date being corrected**, not the employee's current manager. Example: an employee transfers from Manager A to Manager B on 1 September; a correction request submitted in October for an August date routes to Manager A (who managed them on that August date), not Manager B. Confirm this matches your expectation — the alternative would be routing every request to the *current* manager regardless of which date is being corrected.

**Client decision:** _______________________

---

## 22. WFH & On-Duty

**Do not assume these are implemented as distinct attendance outcomes — they are not.**

### Work From Home (CD-007)

🔵 **IMPLEMENTATION GAP.** The system's data model anticipates a distinct "WFH" attendance status, and a regularization request can be *typed* as "WFH." **Neither of these produces a WFH-labelled attendance day.** A WFH-typed correction request only has any effect if its approval results in ordinary punches being added or a roster shift being changed — in which case the resulting day is evaluated as an ordinary Present/Absent/Half-Day/Incomplete day, exactly as if the employee had been in the office. There is no visual or reporting distinction between "worked from the office" and "worked from home" anywhere downstream.

⚠️ **CLIENT DECISION REQUIRED.**

**How should WFH be recorded?**
- **A.** Normal attendance with punches — no distinct status, WFH is simply not tracked separately (closest to current behaviour).
- **B.** A special, distinct WFH status that appears in attendance reports and payroll-facing summaries separately from Present.
- **C.** Manager-approved WFH, functioning like a lightweight leave-adjacent approval, without necessarily requiring punches at all.
- **D.** Another organization-specific approach.

**Client decision:** _______________________

### On-Duty (CD-008)

🔵 **IMPLEMENTATION GAP.** Same situation as WFH: an "On-Duty" regularization type exists and can be submitted/approved, but produces no distinct attendance status. Field staff, sales staff on client visits, or outdoor duty are not distinguishable from ordinary office presence in any report today.

⚠️ **CLIENT DECISION REQUIRED.**

**How should on-duty attendance be recorded?**
- **A.** Normal attendance — no distinct tracking (closest to current behaviour).
- **B.** A special, distinct On-Duty status, separate from Present.
- **C.** Handled purely through the regularization workflow, with no dedicated status (current partial state).
- **D.** Another organization-specific approach.

**Client decision:** _______________________

**If neither WFH nor On-Duty as a distinct status is required by your organization,** the current behaviour (option A in both cases) requires no further work — but this should still be an explicit, recorded decision rather than an assumption, since the presence of these fields in configuration screens could otherwise create false confidence that they are active.

---

## 23. Timezone & DST

| Topic | Current behaviour |
|---|---|
| **Organization timezone** | Every company has a timezone, used as the lowest-priority fallback. |
| **Branch timezone** | Optional, per branch; outranks company timezone when set. |
| **Shift timezone** | Optional, per shift version; outranks both branch and company when set. **Precedence order: Shift > Branch > Company.** There is no employee-level timezone override — this is a deliberate 3-tier design, confirmed consistent between the code and the original architecture document. |
| **Cross-midnight attendance** | All internal storage is in UTC; local time (per the resolved timezone above) is used only for classification (late/early/day-boundary decisions). A shift crossing midnight is attributed entirely to its start date (see **Section 12**). |
| **DST transitions** | ⚠️ **Untested, not proven either way.** The system uses a standard timezone-aware library that is generally expected to handle daylight-saving transitions correctly for named timezones, but **no test in the codebase specifically exercises a spring-forward or fall-back transition date.** This has not been demonstrated to work correctly for the specific case of a shift that spans a clock-change moment. |

⚠️ **TECHNICAL VERIFICATION REQUIRED — (CD-025).** If your organization operates in a timezone that observes daylight saving time, and any shift could plausibly span a DST transition, this should be explicitly tested before go-live rather than assumed to work. This is flagged as a technical verification item rather than a business policy question (see **Section 28**), but it is included here because an unverified DST edge case could silently produce an incorrect worked-minutes calculation on the two days per year it applies.

**Client/technical decision:** _______________________

---

## 24. Indian HR Scenarios

Drawn from the existing Indian-HR-requirements audit. Each item is marked with its actual support level — please do not assume "Supported" means fully polished; check the linked caveat where one exists.

| Requirement | Applicable? | Current Support | Business Rule Confirmed? | Notes |
|---|---|---|---|---|
| Monday–Friday work week | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Fixed weekday weekly-off pattern covers any weekday set |
| Monday–Saturday work week (single weekly off) | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Same mechanism |
| Alternate Saturdays off | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Configured via a cycle-start date + parity; the default parity for an *unset* parity value is an implementation choice, not an explicitly spec'd default — confirm your expected default if you leave this field blank |
| 1st/3rd (or Nth) Saturday off | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | |
| Last Saturday off | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | |
| Rotational weekly offs (different day per employee/week) | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Via per-employee-date roster overrides — this was explicitly the motivating case for building roster overrides (e.g., night-shift workers with a Wednesday off instead of Sunday) |
| State/branch-specific holiday calendars (e.g., Kerala vs. Maharashtra) | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Multiple calendars can be assigned by branch or by employee |
| Optional/restricted holidays | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | See **Section 14** |
| Holiday landing on a weekly-off (Sunday) | ☐ Yes ☐ No ☐ Future | ⚠️ **Needs decision (CD-004)** | ☐ | See **Section 14** — no automatic substitute today |
| Compensatory (substitute) holiday | ☐ Yes ☐ No ☐ Future | ⚠️ Partial | ☐ | The mechanism exists but is entirely manual — no automatic trigger |
| Night shifts | ☐ Yes ☐ No ☐ Future | ⚠️ **Needs decision (CD-001)** | ☐ | Scheduling/date-attribution works correctly; Night OT classification does not — see **Section 18** |
| 24×7 operations | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Building blocks exist and are individually tested; no combined end-to-end test (see **Section 28**) |
| Security / hospital / manufacturing rotating shift patterns | ☐ Yes ☐ No ☐ Future | ⚠️ Partial | ☐ | The building blocks (cross-midnight, split shifts, roster overrides, 24×7 flags) all exist; the night-OT gap is most likely to affect this segment specifically |
| Split shifts | ☐ Yes ☐ No ☐ Future | ✅ Supported (with a documented simplification) | ☐ | No partial-hours credit for a partially-worked block |
| Flexible timings | ☐ Yes ☐ No ☐ Future | ⚠️ Partial — needs verification | ☐ | Core-hours enforcement doesn't exist (**Section 12**, CD-009); flexible-shift outcomes are lower-confidence generally |
| Work From Home | ☐ Yes ☐ No ☐ Future | ❌ **Not supported as a distinct status** | ☐ | See **Section 22**, CD-007 |
| Field / On-Duty work | ☐ Yes ☐ No ☐ Future | ❌ **Not supported as a distinct status** | ☐ | See **Section 22**, CD-008 |
| Half-day leave | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Including multiple half-days summing to a full day |
| Late-coming policy (grace + bands) | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | |
| Repeated-late penalties ("N lates = half day") | ☐ Yes ☐ No ☐ Future | ❌ **Not supported** | ☐ | Setting exists in configuration, has zero effect — see **Section 9**, CD-013 |
| OT on holiday / weekly-off | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Classification works; no money is calculated (see below) |
| Comp-off | ☐ Yes ☐ No ☐ Future | ⚠️ Fact only | ☐ | Earned-minutes fact is correctly recorded with an optional expiry date; **nothing enforces the expiry** (no code invalidates a comp-off once its date passes) and there is no redemption/balance mechanism — that belongs to a future Leave module |
| Statutory OT pay rates (e.g., legally mandated 2× pay) | ☐ Yes ☐ No ☐ Future | ⚪ **Explicitly out of scope** | ☐ | This module records a reference multiplier and a classification label only — it never calculates actual money. This is a deliberate design boundary (confirmed, not an oversight) |
| Monthly attendance closing | ☐ Yes ☐ No ☐ Future | ✅ Supported | ☐ | Comprehensive — see **Section 20** |

**Client confirmation on scope boundary:** ☐ Approved (statutory pay calculation is out of scope for this module; a future Payroll module owns it) / ☐ Change required

### ⚠️ CLIENT DECISION REQUIRED — Statutory holiday pack (CD-023)

Is it acceptable that this system has **no built-in statutory holiday pack** — HR loads every holiday date manually per calendar, per state/region — or is a pre-loaded statutory calendar (auto-updated year to year) expected?

**Client decision:** _______________________

---

## 25. Rule Precedence Matrix

### 25.1 How Conflicts Are Resolved

Attendance scenarios can involve multiple rules at the same time. For example, an employee may have leave, punches, overtime and a holiday on the same date. The system therefore needs an agreed precedence between rules.

```
Holiday
  +
Weekly Off
  ↓
Which rule wins?
```

```
Leave
  +
Overtime
  ↓
Which rule wins?
```

```
Roster
  +
Shift Policy
  ↓
Which rule wins?
```

The detailed, row-by-row answers the system currently gives to each of these — and which ones still require a client decision — are in the matrix below (**Section 25.2**).

### 25.2 Precedence Matrix

| Rule A | Rule B | Which wins? | Reason | Client Status |
|---|---|---|---|---|
| Employee-level policy | Company-level policy | **Employee** | Most-specific-of-8-levels wins (Employee > Shift > Designation > Grade > Department > Branch > Legal Entity > Company) | ☐ Approved |
| Shift-level policy | Department-level policy | **Shift** | Same 8-level order | ☐ Approved |
| Roster shift | Assignment (default) shift | **Roster**, if published | Most specific override for that date | ☐ Approved |
| Roster shift | Shift-scoped **policy** resolution | **Policy stays on the originally-assigned shift** | Documented mismatch — see **Section 13** | ⚠️ **CLIENT DECISION REQUIRED (CD-006)** |
| Calendar exception (Shutdown / Special Working / Substitute / Cancel) | Holiday | **Exception** | Exceptions are always checked first | ☐ Approved |
| Holiday | Weekly Off | **Weekly Off** (flagged) | Documented carve-out — no auto-substitute | ⚠️ **CLIENT DECISION REQUIRED (CD-004)** — see **Section 14** |
| Optional/Restricted holiday | Working Day default | **Working Day**, unless a company-wide flag hardens it | Confirmed default | ☐ Approved |
| Special Working Day | Weekly Off / Holiday | **Special Working Day** | Exception always wins | ☐ Approved |
| Full-day Leave | Punch-derived Absence | **Leave** | Leave overlay runs after punch evaluation, replaces the status | ☐ Approved |
| Full-day Leave | Calendar day-type (e.g., Holiday) | **Both apply independently** — status becomes Leave, calendar still reports Holiday | Leave never rewrites the calendar | ☐ Approved |
| Leave ("leave wins" mode) | Punch-derived status | **Leave** | Default policy setting | ☐ Approved |
| Leave ("flag work-on-leave" mode) | Punch-derived status | **Punch-derived status kept**, work-on-leave flag raised | Alternate policy setting | ☐ Approved |
| Leave | Overtime | ⚠️ **No rule exists** | Genuine open gap — see **Sections 15, 19** | ⚠️ **CLIENT DECISION REQUIRED (CD-002)** |
| Regularization (approved) | Original punches | **Both retained** — correction is additive, original punches never deleted/edited | Audit-trail design | ☐ Approved |
| Regularization (approved) | Attendance result | **Recalculated from scratch**, not directly overwritten | Audit-trail design | ☐ Approved |
| Regularization | An already-terminal Overtime decision for the same day | **The frozen OT decision wins — stays as-is** | Documented as deliberate, but can leave OT and attendance facts diverging with no reconciliation short of a full reopen | ⚠️ **CLIENT DECISION REQUIRED** — see **Section 19** |
| Overtime decision | Attendance status (Present/Absent/etc.) | **Neither overrides the other — always parallel, independent facts** | Deliberate design | ☐ Approved |
| Period Lock | Any mutation (punch, roster, regularization, OT decision, leave sync/cancel, recompute) | **Lock wins — action refused** | Fail-closed design | ☐ Approved |
| Draft Roster | Published Roster | **Published wins; draft is completely invisible to calculation** | Deliberate | ☐ Approved |
| Two overlapping policy assignments at the same scope tier (e.g., two Employee-level Attendance Policies with overlapping effective dates) | — | ⚠️ **Not defended against** | Neither the resolution logic nor any test confirms what happens if this occurs — treat as a data-integrity assumption, not a handled case | ⚠️ **TECHNICAL VERIFICATION REQUIRED (CD-026)** — see **Section 28** |

Never treat current implementation behaviour as automatically approved precedence — every row above requires an explicit client status, not a default assumption.

---

## 26. Configuration Catalog

The full field-by-field technical catalogue lives in the source audits; this table is the business-relevant summary — what each setting is *for*, and, critically, whether it currently does anything.

### 26.1 Working Configurations

Settings that currently affect system behaviour (safe to configure — they change behaviour as expected).

| Setting | What it means | Client decision |
|---|---|---|
| Grace-In / Grace-Out minutes | Leeway before lateness/early-departure starts counting | ☐ Confirm values per employee group |
| Late / Early bands | Minute-thresholds that escalate lateness/earliness to Half-Day or Absent | ☐ Confirm bands per employee group |
| Hour bands | Worked-minute thresholds for Present / Half-Day / Absent | ☐ Confirm thresholds |
| Missing-punch behaviour (Incomplete / Absent / Require-Correction) | What a day defaults to when punches don't pair cleanly | ☐ Confirm default (Client Confirmation item — **Section 27.2**) |
| Missing-shift behaviour | What happens when no shift is resolved at all | ☐ Confirm default |
| Multi-punch mode (sum all pairs / first-in-last-out) | How more than one IN/OUT pair in a day is totalled | ☐ Confirm mode (Client Confirmation item — **Section 27.2**) |
| Duplicate-punch window | Seconds within which repeated same-direction punches collapse to one | ☐ Confirm window |
| Split-shift missed-block behaviour | Outcome when a duty block is entirely missed | ☐ Confirm per shift type |
| Work-on-leave behaviour (leave wins / flag-and-keep) | Which status wins when leave and punches both exist | ☐ Confirm mode |
| Incomplete-at-lock behaviour | How an unresolved Incomplete day is auto-resolved at period close | ☐ Confirm default |
| OT minimum / rounding / daily-weekly-monthly caps | Overtime detection thresholds | ☐ Confirm values |
| OT requires-approval / approval chain | Whether OT needs sign-off, and by whom | ☐ Confirm chain |
| Comp-off instead of pay + expiry days | Whether OT converts to time-off, and how long it's valid (fact only, no enforcement — see **Section 17**) | ☐ Confirm policy |
| Regularization: who may request, backdating window, monthly limit, reason/attachment requirements, allowed types | Correction-request policy | ☐ Confirm per employee group |
| Regularization approval chain | Who signs off on corrections | ☐ Confirm chain |
| Roster week-off / holiday-working overrides | Per-employee-date schedule exceptions | ☐ Confirm usage pattern |

### 26.2 Configurations Present but Inactive

🔵 **IMPLEMENTATION GAP.** These appear in configuration screens, can be edited, but currently have **zero effect on calculation.** For each, the client should decide: build it, hide it, or explicitly accept it as inactive.

| Configuration | What HR Might Expect | What System Currently Does | Decision |
|---|---|---|---|
| Punch rounding (CD-018) | Round punch times to the nearest N minutes before evaluation | No effect — raw punch times are always used | ☐ Build / ☐ Hide / ☐ Accept inactive |
| Core hours (flexible shifts) + breach behaviour (CD-009) | Enforce a mandatory-presence window within a flexible shift | Never checked by the system — see **Section 12** | ☐ Build / ☐ Hide / ☐ Accept inactive |
| Half-day split method + boundary minutes | An alternate way of determining half-day (separate from hour bands, which already work) | Hour bands are used regardless; this setting has no effect | ☐ Build / ☐ Hide / ☐ Accept inactive |
| Excess-break behaviour (CD-011) | An automatic consequence for exceeding max break time | Excess is recorded as a fact only; no consequence applied — see **Section 11** | ☐ Build / ☐ Hide / ☐ Accept inactive |
| Auto-close-after-minutes / uses-shift-end (CD-012) | Automatically insert a clock-out for a forgotten punch | Does nothing — no clock-out is ever auto-inserted | ☐ Build / ☐ Rename to avoid confusion / ☐ Accept inactive — see below |
| Split-shift block-mandatory / hours-compensation (CD-017) | Making a duty block optional, or letting extra hours in one block compensate for a shortfall in another | Not enforced — business meaning needs scoping | ☐ Build / ☐ Hide / ☐ Accept inactive |
| WFH-requires-punch / On-Duty-requires-punch / WFH-uses-shift-hours (CD-007, CD-008) | Govern a working WFH/On-Duty mode | No distinct WFH/On-Duty outcome exists yet — see **Section 22** | ☐ See Section 22 decision |
| Late-count-window / lates-to-half-day-count (CD-013) | "N lates in a period = automatic half-day" | Each day judged independently; no memory of prior lateness | ☐ Build / ☐ Hide / ☐ Accept inactive |
| Early-departure-requires-approval (CD-014) | Pre-approval gate for leaving early | No pre-approval gate exists; classification is always after-the-fact | ☐ Build / ☐ Hide / ☐ Accept inactive |
| Band "counts toward cap" flag | Feeds the late-count feature above | No effect while the late-count feature itself is inactive | ☐ Tied to the CD-013 decision above |
| OT "by grade" eligibility (CD-003) | Restrict OT to specific employee grades | Behaves exactly like "Always eligible" — no grade/designation field consulted | ☐ **High priority** — see **Section 17** |
| OT night-window start/end (CD-001) | Classify OT as Night based on actual clock time | Never checked against anything | ☐ **High priority** — see **Section 18** |
| Regularization auto-approve-within-minutes (CD-024) | Auto-approve small/quick corrections without human review | No effect | ☐ Build / ☐ Hide / ☐ Accept inactive |
| Regularization blocked-when-locked | Looks like an escape hatch to allow regularization during a locked period — it is not; period lock is unconditional regardless of this setting | Misleading name; behaviour is unconditional lock | ☐ **Recommend: relabel to avoid false expectation** |
| Legal-entity-level lock grain (CD-019) | Lock a specific legal entity independently of the rest of the company | Locking is whole-company only | ☐ Build / ☐ Accept whole-company-only locking |

**On "Auto-Close" specifically:** the setting's name strongly implies the system will automatically insert a missing clock-out. **It does not.** This is flagged as the single most likely setting to cause false confidence, since a reasonable HR admin would assume turning it on changes behaviour. Recommend it be renamed or clearly labelled "not yet active" in the interface regardless of the eventual decision on whether to build it.

### 26.3 Business Rules Requiring Clarification

Settings whose intended business meaning cannot be finalized without a business decision (beyond a simple build/hide/accept choice).

| Setting | Why it needs clarification | Section |
|---|---|---|
| Holiday-on-weekly-off substitution | Genuinely different from "not built" — needs a decided business rule, not just an implementation | Section 14 (CD-004) |
| Leave vs. Overtime | No rule exists at all, in either direction | Sections 15, 19 (CD-002) |
| Roster vs. Shift-scoped policy | A real mismatch with two reasonable resolutions | Section 13 (CD-006) |
| Night OT definition | Three plausible definitions exist; none is confirmed | Section 18 (CD-001) |

---

## 27. Client Decision Register

This is the authoritative, consolidated record of every client business decision surfaced by this document. **No decision below is marked approved.** As each is resolved, the client (or their authorized representative) records the decision, approver, and date directly in this table.

### 27.1 Category A — Client Business Decisions

Rules where the client must choose the desired business behaviour — there is no "correct" system default, only a business policy choice.

| Decision ID | Rule | Priority | Decision Options | Client Decision | Comments | Approved By | Date |
|---|---|---|---|---|---|---|---|
| CD-001 | Night OT definition | High | A/B/C/D — Section 18 | | | | |
| CD-002 | Leave + Overtime precedence | High | A/B/C/D — Sections 15, 19 | | | | |
| CD-003 | OT eligibility "by grade" | High | Build / Remove / Document as alias — Section 17 | | | | |
| CD-004 | Holiday falling on a Weekly Off | High | A/B/C/D — Section 14 | | | | |
| CD-006 | Roster vs. Shift-scoped policy mismatch | Medium | A/B/C — Section 13 | | | | |
| CD-007 | Work From Home status | Medium | A/B/C/D — Section 22 | | | | |
| CD-008 | On-Duty status | Medium | A/B/C/D — Section 22 | | | | |
| CD-010 | Mandatory break auto-deduction | Medium | A/B — Section 11 | | | | |
| CD-011 | Excess break vs. Overtime | Medium | No options established — Sections 11, 19 | | | | |
| CD-015 | Half-day leave "first half / second half" enforcement | Medium | A/B — Section 15 | | | | |
| CD-016 | Reopen: automatic recompute or manual? | Medium | A/B/C — Section 20 | | | | |
| *(unnumbered)* | Period-lock blockers: hard vs. waivable-with-warning | Medium | Not established — Section 20 | | | | |

### 27.2 Category B — Client Confirmations

Rules where the system has a defined behaviour but the client needs to confirm it is acceptable. No artificial options are introduced here — these items only require a yes/no-style confirmation, not a choice among alternatives.

| Item | Rule | Current Behaviour | Client Confirmation | Comments | Approved By | Date |
|---|---|---|---|---|---|---|
| CD-020 | Manager-as-of-date for approval routing | Approvals route to the manager as of the attendance date, not today's manager — Section 21 | ☐ Approved ☐ Change required | | | |
| CD-022 | Optional/Restricted holiday default | Working day by default unless a company-wide flag hardens it — Section 14 | ☐ Approved ☐ Change required | | | |
| *(unnumbered)* | Missing-punch default (Incomplete, not Absent) | Section 8, Scenario A07 | ☐ Approved ☐ Change required | | | |
| *(unnumbered)* | Multi-punch mode default (sum all pairs) | Section 8, Scenario A10 | ☐ Approved ☐ Change required | | | |
| *(unnumbered)* | Alternate-Saturday default parity when left blank | Section 24 | ☐ Approved ☐ Change required | | | |
| *(unnumbered)* | Leave module scope boundary (Attendance mirrors leave only) | Section 15 | ☐ Approved ☐ Change required | | | |
| *(unnumbered)* | Statutory pay calculation scope boundary (out of scope) | Section 24 | ☐ Approved ☐ Change required | | | |
| *(unnumbered)* | Regularization overall workflow design (additive, recalculate-from-scratch) | Section 16 | ☐ Approved ☐ Change required | | | |

### 27.3 Full Register (All 26 Decision IDs)

Preserved for audit completeness. Every CD ID from the original consolidated audit appears here exactly once, cross-referenced to its category.

| Decision ID | Rule | Priority | Category | Decision Options | Client Decision | Comments | Approved By | Date |
|---|---|---|---|---|---|---|---|---|
| CD-001 | Night OT definition | High | A — Business Decision | A/B/C/D | | | | |
| CD-002 | Leave + Overtime precedence | High | A — Business Decision | A/B/C/D | | | | |
| CD-003 | OT eligibility "by grade" | High | A — Business Decision | Build/Remove/Alias | | | | |
| CD-004 | Holiday falling on a Weekly Off | High | A — Business Decision | A/B/C/D | | | | |
| CD-005 | Post-lock corrections / arrears | High | D — Implementation Decision | A/B/C | | | | |
| CD-006 | Roster vs. Shift-scoped policy mismatch | Medium | A — Business Decision | A/B/C | | | | |
| CD-007 | Work From Home status | Medium | A — Business Decision | A/B/C/D | | | | |
| CD-008 | On-Duty status | Medium | A — Business Decision | A/B/C/D | | | | |
| CD-009 | Core hours enforcement (Flexible shifts) | Medium | D — Implementation Decision | Build/Hide/Accept | | | | |
| CD-010 | Mandatory break auto-deduction | Medium | A — Business Decision | A/B | | | | |
| CD-011 | Excess break vs. Overtime | Medium | A — Business Decision | Not established | | | | |
| CD-012 | Auto-Close naming/behaviour | Medium | D — Implementation Decision | Build/Rename/Leave | | | | |
| CD-013 | Repeated-lateness → half-day penalty | Medium | D — Implementation Decision | Build/Hide/Accept | | | | |
| CD-014 | Early-departure pre-approval requirement | Medium | D — Implementation Decision | Build/After-the-fact | | | | |
| CD-015 | Half-day leave "first half / second half" enforcement | Medium | A — Business Decision | A/B | | | | |
| CD-016 | Reopen: automatic recompute or manual? | Medium | A — Business Decision | A/B/C | | | | |
| CD-017 | Split-shift block-mandatory / cross-block hours compensation | Medium | D — Implementation Decision | Not established | | | | |
| CD-018 | Punch rounding | Medium | D — Implementation Decision | Implement/Hide/Accept | | | | |
| CD-019 | Legal-entity-level lock grain | Low / Confirmatory | D — Implementation Decision | Build/Accept | | | | |
| CD-020 | Manager-as-of-date for approval routing | Low / Confirmatory | B — Client Confirmation | Confirm current | | | | |
| CD-021 | Default-shift cascade (branch → company) when no shift is assigned | Low / Confirmatory | D — Implementation Decision | A/B | | | | |
| CD-022 | Optional/Restricted holiday default | Low / Confirmatory | B — Client Confirmation | Confirm current | | | | |
| CD-023 | Statutory holiday pack vs. manual loading | Low / Confirmatory | D — Implementation Decision | A/B | | | | |
| CD-024 | Regularization auto-approve-within-minutes | Low / Confirmatory | D — Implementation Decision | Implement/Remove | | | | |
| CD-025 | DST-transition verification | Low / Confirmatory | C — Technical Verification | N/A — technical | | | | |
| CD-026 | Two overlapping policy assignments at the same scope tier | Low / Confirmatory | C — Technical Verification | N/A — technical | | | | |

---

## 28. Technical Verification Items

**These items do not require the client to define a business rule. They require technical verification before production/UAT.**

| Item | Description | Section |
|---|---|---|
| CD-025 — DST-transition verification | No test exercises a spring-forward/fall-back transition for a shift spanning the change. Confirm whether operating regions observe DST and whether explicit pre-go-live testing is required. | Section 23 |
| CD-026 — Overlapping policy assignments | Two policies at the same scope tier with overlapping effective dates are not defended against in code or tests — a data-integrity assumption, not a handled case. | Section 25 |
| Flexible shift end-to-end verification | No dedicated test confirms exactly how late/early/status is computed for a Flexible shift end-to-end. | Section 12 |
| 24×7 combined end-to-end test | Individual building blocks (holiday-operating flags, roster overrides) are tested; no test combines them as a full rotating 3-shift roster would operate. | Section 12 |
| Breaks crossing shift boundaries | Not specifically documented or tested as an edge case. | Section 11 |
| OT + Shift-version change mid-period | No test combines a mid-period shift-version change with already-detected OT records. | Section 19 |
| Mid-period lifecycle edge cases | The "as-of-date" lookup mechanism is confirmed and consistently used, but specific mid-period combinations (transfer + recalculation, policy republish + recalculation, shift-version change + recalculation) have no dedicated test coverage. | Section 21 |

---

## 29. Implementation Decisions

These should be handled after the client's business requirements (**Section 27.1**) and confirmations (**Section 27.2**) are confirmed. Each is fundamentally a build/hide/accept/rename choice about an inactive or partially-built configuration, not an open business-policy question.

| Decision ID | Item | Options | Section |
|---|---|---|---|
| CD-005 | Post-lock corrections / arrears feature | Build dedicated feature / Reopen+manual only (current) / Handle outside system | Section 20 |
| CD-009 | Core hours enforcement (Flexible shifts) | Build / Hide / Accept inactive | Section 12 |
| CD-012 | Auto-Close naming/behaviour | Build true auto-close / Rename-relabel (recommended minimum) / Leave as-is | Section 26 |
| CD-013 | Repeated-lateness → half-day penalty | Build the rolling-window penalty / Hide / Accept inactive | Section 9 |
| CD-014 | Early-departure pre-approval requirement | Build a pre-approval gate / After-the-fact classification only (current) | Section 10 |
| CD-017 | Split-shift block-mandatory / cross-block hours compensation | Needs scoping before build/hide decision is even possible | Section 12 |
| CD-018 | Punch rounding | Implement / Hide / Accept inactive | Section 26 |
| CD-019 | Legal-entity-level lock grain | Build / Accept whole-company-only locking | Section 26 |
| CD-021 | Default-shift cascade (branch → company) when no shift is assigned | Build a fallback cascade / No shift remains a valid, deliberate state (current) | Section 12 (referenced), source audit PD-BR14-SHIFT |
| CD-023 | Statutory holiday pack vs. manual loading | Build a pre-loaded statutory pack / HR loads all dates manually (current) | Section 24 |
| CD-024 | Regularization auto-approve-within-minutes | Implement / Remove-hide the setting | Section 26 |

---

## 30. Rule Traceability

This section links each business rule/decision through implementation, testing, and UAT to final approval. **No GitHub issue numbers are invented** — fields are left blank where no linked artifact currently exists.

Client Decision → GitHub Issue → Developer Implementation → Automated Test → UAT → Approval

| Business Rule / Decision | Scenario | GitHub Issue | Implementation | Test | UAT | Status |
|---|---|---|---|---|---|---|
| CD-001 — Night OT definition | Section 18 | | | | | ⚠️ Awaiting decision |
| CD-002 — Leave + Overtime | Section 15, 19 | | | | | ⚠️ Awaiting decision |
| CD-003 — OT eligibility by grade | Section 17 | | | | | ⚠️ Awaiting decision |
| CD-004 — Holiday on Weekly Off | Section 14 | | | | | ⚠️ Awaiting decision |
| CD-005 — Post-lock corrections | Section 20 | | | | | ⚠️ Awaiting decision |
| CD-006 — Roster vs. Shift policy | Section 13 | | | | | ⚠️ Awaiting decision |
| CD-007 — WFH status | Section 22 | | | | | ⚠️ Awaiting decision |
| CD-008 — On-Duty status | Section 22 | | | | | ⚠️ Awaiting decision |
| CD-009 — Core hours enforcement | Section 12 | | | | | ⚠️ Awaiting decision |
| CD-010 — Mandatory break deduction | Section 11 | | | | | ⚠️ Awaiting decision |
| CD-011 — Excess break vs OT | Section 11, 19 | | | | | ⚠️ Awaiting decision |
| CD-012 — Auto-Close naming | Section 26 | | | | | ⚠️ Awaiting decision |
| CD-013 — Repeated lateness | Section 9 | | | | | ⚠️ Awaiting decision |
| CD-014 — Early-departure approval | Section 10 | | | | | ⚠️ Awaiting decision |
| CD-015 — Half-day leave half | Section 15 | | | | | ⚠️ Awaiting decision |
| CD-016 — Reopen recompute | Section 20 | | | | | ⚠️ Awaiting decision |
| CD-017 — Split-shift compensation | Section 12 | | | | | ⚠️ Awaiting decision |
| CD-018 — Punch rounding | Section 26 | | | | | ⚠️ Awaiting decision |
| CD-019 — Legal-entity lock grain | Section 26 | | | | | ⚠️ Awaiting decision |
| CD-020 — Manager-as-of-date | Section 21 | | | | | ⚠️ Awaiting decision |
| CD-021 — Default-shift cascade | Section 12 | | | | | ⚠️ Awaiting decision |
| CD-022 — Optional holiday default | Section 14 | | | | | ⚠️ Awaiting decision |
| CD-023 — Statutory holiday pack | Section 24 | | | | | ⚠️ Awaiting decision |
| CD-024 — Regularization auto-approve | Section 26 | | | | | ⚠️ Awaiting decision |
| CD-025 — DST-transition verification | Section 23 | | | | | ⚠️ Awaiting verification |
| CD-026 — Overlapping policy assignments | Section 25 | | | | | ⚠️ Awaiting verification |

---

## 31. Decision History

| Version | Decision ID | Previous Rule | New Rule | Reason | Approved By | Date |
|---|---|---|---|---|---|---|
| | | | | | | |

> Once a decision is approved, future changes must not overwrite the original decision. They must be recorded as a new version/change. No history exists yet — this table will populate as decisions in **Section 27** are approved and, subsequently, changed.

---

## 32. Change Control

# Attendance Rule Change Control

After client sign-off, any change to an approved attendance business rule must be treated as a change request.

| Change ID | Existing Rule | Requested Change | Reason | Impact | Approved By | Date |
|---|---|---|---|---|---|---|
| | | | | | | |

> Developers must not modify an approved attendance rule based solely on a verbal request or implementation assumption. The corresponding business rule/change request must be recorded first.

---

## 33. Final Client Sign-Off

### Sign-off Summary

Once every item in **Section 27** has a recorded decision, and every scenario table in **Sections 8–24** has been marked "Approved" or annotated with a change, this document becomes the confirmed business-rule baseline for the Attendance module. Any decision that changes current system behaviour should be logged as a change request in **Section 32** and scoped separately before implementation begins — this document itself does not implement anything.

| Reviewed by | Role | Date | Sections confirmed |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

### Final Client Approval

The client confirms that:

1. Applicable attendance scenarios have been identified.
2. Business rules have been reviewed.
3. Rule precedence has been reviewed.
4. Open business decisions have been resolved.
5. Out-of-scope functionality has been identified.
6. Implementation gaps have been identified.
7. The approved rules represent the intended Attendance behaviour.

**Client Organization:**

_____________________________

**Authorized Representative:**

_____________________________

**Designation:**

_____________________________

**Signature / Approval Reference:**

_____________________________

**Date:**

_____________________________

**Document Version Approved:**

_____________________________

### Document Status

☐ Draft **☑ Client Review** ☐ Changes Requested ☐ Pending Final Decisions ☐ Approved ☐ Superseded

> Current status remains **CLIENT REVIEW** until the Final Client Approval block above is completed and signed.

---

*This document was compiled from the existing technical and client-facing attendance documentation set as of 2026-08-20/21. It introduces no new claims about system behaviour beyond what those source documents already established, and resolves no open question that those documents left open. Where this document appears to disagree with a source document, treat that as an error in this document to be corrected against the source, not as a new finding.*
