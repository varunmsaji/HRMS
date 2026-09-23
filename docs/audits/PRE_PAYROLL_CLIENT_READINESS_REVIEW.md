<div align="center">

# HRMS Platform

## Pre-Payroll Readiness Review

### Independent Assessment of the Attendance & Leave Foundation

---

**Prepared for:** Client Stakeholders — HR, Finance & Operations
**Prepared by:** Engineering Review Board
**Review date:** 10 September 2026
**Classification:** Client Confidential

---

### Overall readiness

# 🟠 NOT READY — FOUNDATION FIXES REQUIRED

**Estimated time to Payroll-ready: 3–4 weeks**

*Payroll design work can begin immediately and in parallel.*

</div>

---

## Document control

| Field | Detail |
|---|---|
| Document | Pre-Payroll Readiness Review |
| Version | 1.0 |
| Status | Issued for client review |
| Date | 10 September 2026 |
| Scope | All HRMS modules completed prior to Payroll development |
| Basis of review | Direct inspection of every completed module, plus execution of the full back-end and front-end test suites |
| Constraint | Review only. No changes were made to the system during this assessment. |
| Companion documents | Nine technical reports (engineering audience) |

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-09-10 | Engineering Review Board | Initial issue |

---

## Table of contents

| § | Section | Page |
|---|---|---|
| 1 | Executive summary | 3 |
| 2 | What has been completed | 4 |
| 3 | How the system behaves today | 5 |
| 4 | What Payroll will consume | 7 |
| 5 | Attendance readiness | 8 |
| 6 | Leave readiness | 10 |
| 7 | Which records become final and locked | 11 |
| 8 | Safeguards in place | 12 |
| 9 | Data readiness (incl. §9.4 onboarding & time-zone gaps) | 13 |
| 10 | Security readiness | 14 |
| 11 | Auditability | 15 |
| 12 | Key risks identified | 16 |
| 13 | Business decisions required from you | 18 |
| 14 | Technical issues to be fixed | 20 |
| 15 | Recommendation before Payroll begins | 21 |
| 16 | Sign-off | 22 |

---
<div align="center">— Page 3 —</div>

## 1. Executive summary

### 1.1 What we assessed

Your HRMS has reached the point immediately before Payroll development. Because Payroll converts
attendance and leave records into money, we conducted a full independent review to answer one question:

> **Is this foundation reliable enough for Payroll to be built on top of it?**

We inspected the delivered system directly rather than relying on its documentation, and we ran its
complete automated test suite.

### 1.2 What we found

**The foundation is well built.** The parts that are most expensive to correct later — keeping each
client's data separate, controlling who can see and do what, keeping historical records from silently
changing, and handling numbers safely — are all done properly. Several are done better than we typically
see at this stage. **None of this needs to be rebuilt.**

**However, the specific hand-off to Payroll is not ready.** In plain terms:

> Payroll needs a finalised, locked monthly statement of *how many days each employee should be paid
> for*. That statement can only be produced by closing an attendance month. Today, closing a month
> requires processing every employee for every day individually — around 3 000 separate operations for a
> 100-person company — and the statement it produces does not contain the paid-days figure, counts some
> days twice, and misses others entirely.

There are also three specific calculation errors that would produce incorrect pay, and around fifteen
policy settings that appear in your configuration screens but do not actually affect any calculation.

A second, dedicated review of the areas outside the attendance path found two further issues that also
affect Payroll: **employees hired through digital onboarding are never given a salary record**, and
**changing a company's time zone can silently alter past attendance**. Both are covered in §9.4.

### 1.3 Our verdict

| | |
|---|---|
| **Status** | 🟠 **NOT READY — FOUNDATION FIXES REQUIRED** |
| **Nature of the problem** | Missing capability and specific defects — **not** poor engineering |
| **Rebuild required?** | **No.** Every issue is a targeted fix. |
| **Time to ready** | 3–4 weeks of focused work |
| **Can Payroll design start now?** | **Yes** — and it should |

### 1.4 At a glance

| Measure | Result |
|---|---|
| Issues identified | 71 |
| Blocking issues | 5 |
| Critical issues | 14 |
| Business decisions needed from you | **15** |
| Automated tests, and whether they pass | **1 145 back-end + 342 front-end — all passing** |
| Modules reviewed | **All 28 completed areas** — a second pass deepened onboarding, bulk import, company settings and the web application |
| Areas confirmed production-grade | Data separation · Access control · Record locking · Audit trail · Number handling |

---
<div align="center">— Page 4 —</div>

## 2. What has been completed

Twenty-eight functional areas have been delivered.

| Area | What it does | Status |
|---|---|---|
| **Login & security** | Sign-in, session management, automatic lock-out after repeated failures | ✅ Complete |
| **Roles & permissions** | Fine-grained control of who can see and do what, including "own records only", "my team", "my whole reporting line", and "whole company" | ✅ Complete |
| **Company setup** | Company profile, legal entities, branches, departments, designations, grades | ⚠️ Time-zone changes are unguarded — see §9.4 |
| **Employee records** | Personal details, statutory identifiers, bank details, compensation | ✅ Complete |
| **Employment history** | Joining, exit, re-hire — with database-level protection against overlapping records | ✅ Complete |
| **Org placement** | Which branch, department, designation, grade, shift and manager an employee has *at any given date* | ✅ Complete |
| **Bulk employee import** | Spreadsheet upload with validation | ⚠️ A retried upload could create duplicate employees |
| **Digital onboarding** | Invite link → candidate wizard → document upload → HR review → activation into a live employee | ⚠️ **No salary record created on activation — see §9.4** |
| **Holiday calendars** | Multiple calendars, holiday types, special exceptions | ✅ Complete |
| **Weekly-off patterns** | Fixed days, "2nd and 4th Saturday", alternating weeks | ⚠️ Half-day weekly offs not carried through |
| **Work calendars** | Combining holidays and weekly-offs, assignable at any organisational level | ✅ Complete |
| **Shifts** | Fixed, flexible and split shifts; breaks; overnight shifts; per-shift time zones | ✅ Complete |
| **Rosters** | Per-employee, per-day schedule overrides, with a draft/published workflow | ✅ Complete |
| **Attendance rules** | Grace periods, late/early bands, hour bands, half-day rules, and more | ⚠️ **Several settings do not affect calculations** |
| **Attendance calculation** | Turns clock-in/out records into a daily attendance result | ⚠️ **See §5** |
| **Overtime** | Detection, caps, approval workflow, comp-off earning | ⚠️ Night overtime misclassified |
| **Attendance corrections** | Employee/manager/HR requests with a full approval trail | ✅ Complete |
| **Monthly close & lock** | Validate, finalise and lock a month; controlled re-opening | ⚠️ **See §7** |
| **Leave types & policies** | Configurable per leave type, assignable at any organisational level | ✅ Complete |
| **Leave balance ledger** | Every credit and debit as a permanent, unalterable record | ✅ Complete |
| **Leave accrual** | Monthly and annual, pro-rated for part-months | ⚠️ Can double-credit in rare cases |
| **Leave applications** | Submit, multi-level approval (Manager → Department Head → HR), cancel | ⚠️ **Balance not re-checked at approval** |
| **Carry-forward** | Annual cap enforcement at leave-year start | ✅ Complete |
| **Comp-off** | Earned from approved overtime, with expiry | ✅ Complete |
| **Leave encashment** | Policy-validated, recorded in the ledger | ✅ Complete (payout is Payroll's) |
| **Statutory leave floors** | Legal minimum enforcement when publishing a policy | ✅ Complete |
| **Audit trail** | Every change recorded with who, what, when, before and after | ⚠️ No screen to view it |
| **Notifications** | — | ❌ **Not built** |
| **Reports** | — | ❌ **Not built** |

---
<div align="center">— Page 5 —</div>

## 3. How the system behaves today

### 3.1 A day in the life of an attendance record

```
   Employee clocks in / out
             │
             ▼
   ┌─────────────────────┐
   │  Clock records      │   Permanent. Never edited, never deleted.
   │  stored             │   A correction adds a NEW record.
   └──────────┬──────────┘
              ▼
   ┌─────────────────────┐   Was this person employed on this date?
   │  Employment check   │   Not yet joined / Active / Already exited
   └──────────┬──────────┘
              ▼
   ┌─────────────────────┐   Working day? Holiday? Weekly off?
   │  Calendar lookup    │   Company shutdown? Special working day?
   └──────────┬──────────┘
              ▼
   ┌─────────────────────┐   Roster override first, then the
   │  Shift resolution   │   employee's standard assigned shift
   └──────────┬──────────┘
              ▼
   ┌─────────────────────┐   Most specific rule wins, checked in order:
   │  Policy resolution  │   Employee → Shift → Designation → Grade →
   │                     │   Department → Branch → Legal entity → Company
   └──────────┬──────────┘
              ▼
   ┌─────────────────────┐   Pair clock-ins with clock-outs, remove
   │  Calculation        │   duplicates, deduct breaks, measure lateness,
   │                     │   apply the hour bands, detect overtime
   └──────────┬──────────┘
              ▼
   ┌─────────────────────┐   Approved leave overrides the clocked result
   │  Leave overlay      │   (full-day leave wins outright)
   └──────────┬──────────┘
              ▼
   ┌─────────────────────┐   Present / Half day / Absent / Leave / On duty /
   │  DAILY RESULT       │   Not expected / Incomplete
   │                     │   + paid portion and unpaid portion of the day
   └─────────────────────┘
```

### 3.2 The principle that governs the whole system

**A recorded fact is never altered.**

| When this happens | The system does **not** | It does this instead |
|---|---|---|
| A clock-in was wrong | Edit the clock record | Add a correction record and recalculate |
| A leave balance was wrong | Change the balance figure | Add a correcting entry; the balance is always the running total |
| An attendance result was wrong | Overwrite it silently | Recalculate from the underlying records, keeping the full trail |
| Policy rules change | Apply them to past months | Create a new dated version; past months keep the version that was in force |

This is exactly the discipline Payroll requires, and it is applied consistently.

---
<div align="center">— Page 6 —</div>

### 3.3 Which rule wins when rules conflict

We traced 26 situations where two rules could disagree. **Every one of them resolves the same way every
time.** There is no ambiguity in the system's decision-making.

| Situation | What wins |
|---|---|
| Employee-level policy vs company-level policy | The employee-level policy (most specific wins) |
| A calendar exception vs a listed holiday | The exception |
| A holiday vs a weekly-off pattern | The holiday |
| A holiday landing on a weekly off | Stays a weekly off, flagged — **no compensatory day** |
| A published roster override vs the standard shift | The roster |
| A draft (unpublished) roster | Ignored entirely |
| Approved full-day leave vs clocked attendance | The leave |
| An employee not yet joined, or already exited | Overrides everything |
| Missing configuration | **Nothing is guessed** — the day is flagged and blocks month-close |
| **A closed and locked month vs any change** | **The lock wins, always** |

---
<div align="center">— Page 7 —</div>

## 4. What Payroll will consume

Payroll will read the following from the completed system.

| What Payroll needs | Where it comes from | Ready? |
|---|---|---|
| Who the employee is | Employee records | ✅ Ready |
| Joining and exit dates | Employment history | ✅ Ready |
| Branch, department, designation, grade, cost centre | Org placement, as at any date | ✅ Ready |
| **Annual CTC** | Compensation records | 🔴 **Not ready — missing for onboarded staff** (see §9.4) |
| PF / ESI / PAN / bank details | Statutory and bank records | ✅ Ready |
| Which shift applied, and its scheduled hours | Shift and roster records | ✅ Ready |
| Holidays and weekly offs | Work calendars | ✅ Ready |
| **Paid days for the month** | Monthly attendance statement | 🔴 **Not ready** |
| **Loss-of-pay days for the month** | Monthly attendance statement | 🔴 **Not ready** |
| Present / absent / leave / half-day counts | Monthly attendance statement | 🔴 **Not ready** |
| Approved overtime minutes | Overtime records | 🟡 Ready, with one classification issue |
| Overtime rate multiplier | Overtime records (as a reference figure only) | ✅ Ready |
| Comp-off earned | Overtime and leave ledger | ✅ Ready |
| Paid vs unpaid leave days | Leave records | ✅ Ready |
| Leave balance | Leave ledger | 🟡 Ready, but not frozen at month-end |
| Encashment amounts | Leave ledger records the days; **Payroll calculates the money** | ✅ Ready |

**Of 88 individual data points assessed: 58 ready · 24 ready with conditions · 6 not ready.**

**All six "not ready" items are in the paid-days and loss-of-pay chain** — which is precisely what
Payroll exists to use.

### 4.1 An important design decision, confirmed as correct

The system **never calculates money.** Overtime is measured in minutes. Attendance is measured in days
and fractions of days. Even the overtime rate multiplier is stored purely as a reference figure for
Payroll to interpret, and is never applied.

This is the right boundary, and it was deliberately drawn. Payroll will own every monetary calculation,
which keeps money logic in one place and makes it auditable.

---
<div align="center">— Page 8 —</div>

## 5. Attendance readiness

### 5.1 What works correctly

| Capability | Confirmed |
|---|---|
| Clock-in/out pairing, including multiple in/out pairs per day | ✅ |
| Duplicate clock-punch removal | ✅ |
| Overnight shifts attributed to the correct date | ✅ |
| Break deduction from punched gaps | ✅ |
| Late arrival and early departure with grace periods and severity bands | ✅ |
| Hours-worked bands driving Present / Half-day / Absent | ✅ |
| Flexible-shift core-hours checks | ✅ |
| Cumulative rules ("three lates in a month becomes a half day") | ✅ |
| Overtime detection with daily, weekly and monthly caps | ✅ |
| Overtime approval, with the decision frozen once made | ✅ |
| Attendance corrections applied only as new records, never edits | ✅ |
| Multiple time zones — shift, then branch, then company | ✅ |
| Missing configuration flagged rather than guessed | ✅ |

### 5.2 🔴 The blocking problem: a month cannot practically be closed

Payroll needs a finalised monthly statement. Producing one requires an attendance record for every
employee for every day of the month. **The system can only create these one employee-day at a time.**

| Company size | Operations needed to close one month |
|---|---|
| 100 employees | ~3 000 |
| 500 employees | ~15 000 |
| 1 000 employees | ~30 000 |

There is no bulk processing option and no overnight job.

**In practice this means the monthly close cannot be completed, so Payroll would have no input.**

**Fix:** add bulk processing and a scheduled overnight job. Estimated at one week.

### 5.3 🔴 Three calculation errors that would produce incorrect pay

| # | What happens | Consequence |
|---|---|---|
| 1 | A day **before** an employee's joining date is marked as a **fully paid day** | A mid-month joiner could be paid for the entire month |
| 2 | A day **after** an employee's exit date is marked as a **full loss-of-pay day** | A leaver's final settlement would be over-deducted |
| 3 | A day left **incomplete** (e.g. a missing clock-out) is counted as **neither paid nor unpaid** until the month is locked | Any mid-month preview understates both figures |

All three are small, well-understood corrections.

---
<div align="center">— Page 9 —</div>

### 5.4 🟠 Around fifteen policy settings do not affect any calculation

This is the finding we consider most important for you to be aware of, because it is **invisible from the
user interface**.

Certain rules can be configured on screen, saved successfully, and shown as active — while having **no
effect whatsoever** on any attendance result.

| Setting | What HR expects | What actually happens |
|---|---|---|
| **Punch rounding** ("round to the nearest 15 minutes") | Clock times rounded before calculation | Raw times are used. The setting is ignored. |
| **Auto-close a missing clock-out** | The day closes automatically at shift end | The day becomes Absent or Incomplete instead |
| **Half-day determination method** | Choose by hours, shift midpoint, or a fixed time | Only the hour bands ever apply |
| **Excess-break handling** | Flag, half-day, or absent | Recorded but has no effect |
| **Night overtime by time window** | Work between (say) 22:00–06:00 classed as night OT | Only overnight *shifts* are classed as night |
| **Allow negative leave balance** | Permit a balance to go below zero under approval | The setting is never consulted |
| **Half-day weekly off** | Alternate Saturdays as half days | Treated as a full weekly off |
| *(and several more)* | | |

**Why this matters for Payroll.** If Payroll is designed assuming punch rounding is applied, or that
night overtime is being classified by time window, it will be built on rules that do not exist. This must
be resolved before Payroll's design is finalised — either by implementing each rule, or by removing it
from the configuration screens so nobody can set something that does nothing.

**Our recommendation:** for each setting, decide *implement* or *remove*. Leaving a switch on screen that
changes nothing is worse than not offering it.

---
<div align="center">— Page 10 —</div>

## 6. Leave readiness

### 6.1 What works correctly

| Capability | Confirmed |
|---|---|
| Leave types with paid/unpaid defaults and balance requirements | ✅ |
| Leave policies assignable at any organisational level | ✅ |
| Permanent, unalterable balance ledger — the balance is always the running total | ✅ |
| Monthly accrual, pro-rated for part-months | ✅ |
| Annual accrual at the leave-year start (calendar, financial, joining anniversary, or custom) | ✅ |
| Carry-forward cap enforced at leave-year start | ✅ |
| Multi-level approval: Manager → Department Head → HR | ✅ |
| Approvers fixed at the time of application, so a later reporting change cannot redirect it | ✅ |
| Self-approval blocked, with no override | ✅ |
| Sandwich rule (a weekend between two leave days becomes leave) | ✅ |
| Incompatible leave-type combinations blocked | ✅ |
| Statutory legal minimums enforced when publishing a policy | ✅ |
| Comp-off earned from approved overtime, with expiry | ✅ |
| Cancelling an approved leave reverses both the balance and the attendance record | ✅ |
| **Leave cannot be approved or cancelled into a closed month** | ✅ **Correctly refused** |

### 6.2 🟠 Leave balance can go negative

The balance is checked when an employee **applies**, but not when a manager **approves**.

> **Example.** An employee has 5 days of leave. On Monday they submit two separate 5-day applications.
> Both pass the check, because each is compared against the 5 days available at that moment. On Tuesday
> their manager approves both. The employee now has a balance of **minus 5 days**, and Payroll would pay
> for 10 days of leave that was never earned.

The setting that is supposed to control whether negative balances are permitted is never consulted.

**Fix:** re-check the balance at the moment of approval. Estimated at two days.

### 6.3 🟠 Leave accrual can credit twice

Monthly accrual checks whether it has already run before writing. If two accrual runs happen at the same
moment — which the current scheduler configuration permits — both can pass the check and both can write.
Because the balance is a running total, the resulting over-credit is silent and permanent.

**Fix:** a database-level uniqueness rule. Estimated at one day.

### 6.4 🟡 Leave balances are not frozen at month-end

Attendance months can be closed and locked. Leave has no equivalent. A leave balance can therefore change
after the attendance month it relates to has been closed.

**This is a design question rather than a defect**, and it needs a decision (see §13).

---
<div align="center">— Page 11 —</div>

## 7. Which records become final and locked

### 7.1 The monthly close process

```
   OPEN MONTH
   Attendance is calculated and can be corrected freely
             │
             ▼
   ┌────────────────────────────────────────────────┐
   │  VALIDATE                                       │
   │  ✗ Employees missing attendance for any day     │
   │  ✗ Days with unresolved configuration errors    │
   │  ✗ Correction requests still awaiting a decision │
   │  ✗ Overtime still awaiting approval             │
   │  ✗ Roster entries still in draft                │
   │  Any single item blocks the close.               │
   └────────────────────┬───────────────────────────┘
                        ▼
   ┌────────────────────────────────────────────────┐
   │  FINALISE  (all-or-nothing)                     │
   │  1. Re-validate from scratch                    │
   │  2. Mark the month CLOSED                       │
   │  3. Resolve any remaining incomplete days       │
   │  4. Write the frozen monthly statement          │
   │  5. Lock every day in the month                 │
   │  If any step fails, nothing at all is changed.  │
   └────────────────────┬───────────────────────────┘
                        ▼
   CLOSED MONTH — LOCKED
```

### 7.2 What the lock actually prevents — verified

Once a month is closed, **every one of the following is refused**:

| Attempted change | Result |
|---|---|
| Recording a clock-in/out for a locked date | ❌ Refused |
| Adding or editing a roster entry | ❌ Refused |
| Submitting or approving an attendance correction | ❌ Refused |
| Approving or rejecting overtime | ❌ Refused |
| **Approving a leave application covering a locked date** | ❌ **Refused — the whole approval is cancelled** |
| **Cancelling an approved leave on a locked date** | ❌ **Refused** |
| Recalculating a locked day | ❌ Refused |

We consider this the strongest single guarantee in the system, and it is implemented correctly.

### 7.3 Re-opening a closed month

Re-opening is possible, and deliberately harder than closing:

- It requires a **separate, higher-level permission** than closing a month
- A **reason is mandatory** and is stored permanently
- It is recorded in both the month's own history and the system-wide audit trail
- Re-closing produces a **completely fresh** monthly statement, never a partially-updated one

**There is currently no arrears mechanism** — no way to say "August was already paid; make a correcting
adjustment in September". This needs a decision (see §13).

---
<div align="center">— Page 12 —</div>

## 8. Safeguards in place

| Safeguard | What it protects against | Status |
|---|---|---|
| **Client data separation** | One client ever seeing another client's data | ✅ Enforced at the database itself, not just in the application. 70 of 79 data tables are protected, and the application connects using an account that cannot bypass those protections. |
| **Permission checks on every action** | Users seeing or changing records outside their remit | ✅ Every request is checked, and crucially the check is against the **specific record**, not just "does this person have the permission at all". |
| **Records never altered** | Silent, untraceable changes | ✅ Clock records, balance entries, audit entries and approval histories can only be added to, never edited or deleted. |
| **Effective-dated history** | Yesterday's answer changing because today's configuration changed | ✅ Every rule, shift and assignment carries a date range. Past records use the version that was in force at the time. |
| **Locked months** | Paid figures changing after the fact | ✅ Confirmed across every route by which data could change. |
| **All-or-nothing operations** | Half-completed changes leaving inconsistent records | ✅ Verified on the most complex sequence in the system: leave approval → balance deduction → attendance update. If any step fails, none of it happens. |
| **Fail-safe on missing setup** | Guessing when configuration is absent | ✅ Missing configuration produces a flagged error that blocks the monthly close, rather than a silent assumption. |
| **Safe number handling** | Rounding drift and floating-point errors in money | ✅ No approximate arithmetic anywhere. Money is stored in whole paise; durations in whole minutes. |
| **Approval trails** | Disputes about who approved what | ✅ Every workflow keeps a permanent stage-by-stage history. |
| **Login protection** | Password guessing and stolen sessions | ✅ Account lock-out after repeated failures; a stolen session token invalidates the entire token family when replayed. |

---
<div align="center">— Page 13 —</div>

## 9. Data readiness

### 9.1 Can we reproduce a past result?

For Payroll, the ability to answer *"why did this employee receive this figure on this date?"* is
essential — for disputes, for audits, and for statutory inspection.

| Can we reconstruct... | Answer |
|---|---|
| Which employee, which date, which time zone | ✅ Yes |
| Which calendar, holiday and weekly-off pattern applied | ✅ Yes |
| Which shift and shift version applied | ✅ Yes |
| Which policy version applied | ✅ Yes |
| Which clock records were used, and how they were paired | ✅ Yes |
| Hours worked, breaks deducted, lateness measured | ✅ Yes |
| The final status and the paid/unpaid split | ✅ Yes |
| Who approved what, and when | ✅ Yes |
| **Which version of the calculation logic produced it** | ❌ **Not recorded** |
| **Certain running totals used at the time** (e.g. overtime already used that week) | ❌ **Not preserved** |

### 9.2 What this means

Recalculating a day that has not changed **can sometimes produce a different answer**, because certain
figures depend on the state of *other* days at the moment of calculation, and those figures are not
preserved.

Once a month is closed and locked, this cannot occur. The risk exists only between calculation and
month-close.

**Two consequences:**

1. Payroll should read **only closed and locked months** — and we recommend this be enforced by the
   system rather than left as a working convention.
2. The missing figures should be preserved, and a version stamp added to each record. Estimated at
   three days.

### 9.3 Could a past month change unexpectedly?

| Scenario | In a **closed** month | In an **open** month |
|---|---|---|
| Someone edits an attendance rule | ❌ Cannot affect it | ❌ Cannot affect it |
| Someone publishes a rule **back-dated** to that period | ❌ Cannot affect it | ⚠️ **Yes** — restricted to senior users and fully audited |
| Someone edits a roster entry | ❌ Cannot affect it | ⚠️ **Yes** — audited |
| Someone edits a holiday calendar | ❌ Cannot affect it | ⚠️ **Yes** — audited |
| A leave application is approved or cancelled | ❌ Refused | ⚠️ Yes, and attendance updates accordingly |

**The lock is what makes past months safe, and it works.** Everything before the lock is intentionally
mutable, which is correct — but it is why Payroll must read only closed months.

### 9.4 🟠 Two gaps found in a dedicated review of onboarding and company settings

Our first pass concentrated on the path from clock-in to payslip. A second, dedicated review of the
digital onboarding flow and company configuration screens found two further issues, both of which affect
Payroll and neither of which is visible from the attendance path.

---

> #### Employees hired through digital onboarding have no salary record
>
> When a candidate completes the onboarding wizard and HR activates them, the system creates their
> employee record, employment history, org placement, bank details and statutory details — **but not
> their salary.**
>
> The same employee loaded from a spreadsheet through bulk import *does* get a salary record.
>
> Nothing has ever flagged this, because salary has no consumer until Payroll exists. **The moment
> Payroll launches, every employee hired through onboarding would have no CTC and no indication that
> anything was missing.**
>
> **Fix:** collect salary during onboarding, or require it before a candidate can be activated.
> Estimated at two days.

---

> #### Changing a company or branch time zone can silently alter past attendance
>
> Time zone determines when a working day starts and ends, how lateness is measured, and how breaks are
> matched. Changing it re-interprets every one of those for any month that is not yet closed.
>
> A safeguard against this **was written into the system as a placeholder**, to be completed once
> Attendance existed. Attendance now exists; the safeguard is still an empty function. Branch time zone
> has no safeguard at all.
>
> **In practice:** correcting a company's time zone today would quietly change attendance results for
> every open month — including lateness, and potentially whether a day counts as present or half-day.
>
> **Fix:** complete the safeguard so a time zone cannot be changed once attendance has been calculated,
> or require explicit confirmation. Estimated at one day.

---

**Why we are drawing attention to these two specifically.** Neither is a mistake in the calculation
engine. Both are cases where a *connection between modules* was left for later and then not revisited
when the dependent module shipped. They are the kind of gap that only a deliberate cross-module review
finds — which is why we went back for one.

---
<div align="center">— Page 14 —</div>

## 10. Security readiness

### 10.1 Independent security assessment

We found **no vulnerability that would allow one client to access another client's data, one employee to
access another employee's records, or an attacker to bypass authentication.**

The three areas that most often fail in a multi-tenant HR system are all handled properly here.

| Security area | Assessment |
|---|---|
| Client data separation | ✅ **Strong** — enforced at the database layer with a restricted application account |
| Access control | ✅ **Strong** — checked per-request against the specific record |
| Password storage | ✅ **Strong** — modern hashing algorithm |
| Session security | ✅ **Strong** — a stolen session token invalidates the entire family when replayed |
| Account lock-out | ✅ Present — five failed attempts, fifteen-minute lock |
| Database attack resistance | ✅ **No injection vulnerabilities found** |
| Sensitive data in the codebase | ✅ **None found** — no passwords or keys are stored in the source repository |

### 10.2 Areas requiring attention before go-live

| Area | Finding | Urgency |
|---|---|---|
| **Web access configuration** | The current configuration would prevent the web application from communicating with the server once deployed. This would surface as a total outage on the first deployment. | 🟠 Before deployment |
| **Login throttling** | There is no limit on login attempt volume from a single source. Only per-account lock-out exists, so an attacker could try one password across many accounts unimpeded. | 🟠 Before go-live |
| **Browser security headers** | Standard protective headers are not applied. | 🟠 Before go-live |
| **Demo accounts** | The sample-data script has no safeguard preventing it from running against a live system, where it would create an administrator account with a publicly documented password. | 🟠 Before go-live |
| **Document uploads** | File type is not verified. A file could be uploaded with a misleading type. | 🟡 Before scale |
| **Sensitive identifiers** | PAN, Aadhaar, PF and bank details are stored without additional encryption beyond the database's own protections. | 🟡 Before scale |
| **Automated security scanning** | Third-party software components are not automatically checked for known vulnerabilities. | 🟡 Before go-live |

**None of these are defects in the system's logic.** They are protective layers that have not yet been
added.

---
<div align="center">— Page 15 —</div>

## 11. Auditability

### 11.1 What is recorded

Every change of consequence is recorded permanently, with:

**Who** made the change · **What** was changed · **When** · **The value before** · **The value after** ·
**The reason**, where one is required · **The device and network address** · **A reference number**
linking related changes

### 11.2 Coverage

| Event | Recorded? |
|---|---|
| Employee record changes | ✅ |
| Clock-in/out entries | ✅ |
| Attendance calculations and recalculations | ✅ |
| Attendance correction requests, approvals and rejections | ✅ with reason |
| Overtime approvals and rejections | ✅ with reason |
| Leave applications, approvals, rejections and cancellations | ✅ with reason |
| Leave balance adjustments and encashments | ✅ with reason |
| Policy publication | ✅ with a mandatory publication reason |
| Roster changes | ✅ with reason |
| Month close | ✅ |
| **Month re-opening** | ✅ **with a mandatory reason** |
| Login, logout and session refresh | ✅ |
| **The final adjustment made to incomplete days at month-close** | ❌ **Not recorded** |

### 11.3 Two gaps

1. **One important change is not recorded.** When a month is closed, any remaining incomplete days have
   their paid/unpaid split adjusted automatically. This is the last change made before the figures are
   frozen for Payroll — and it is the one change that leaves no trail.
2. **There is no screen to view the audit trail.** The information is captured completely, but it can
   currently only be retrieved by a technical team member querying the database directly. For a system
   handling payroll inputs, HR and compliance users will need direct access.

---
<div align="center">— Page 16 —</div>

## 12. Key risks identified

### 12.1 Risks that would produce incorrect pay

| # | Risk | Likelihood | Impact | Status |
|---|---|---|---|---|
| 1 | **The monthly statement cannot be produced at all** — closing a month requires thousands of individual operations | Certain | Payroll cannot run | 🔴 Blocking |
| 2 | **The monthly statement has no paid-days figure**, so Payroll's primary input is missing | Certain | Payroll cannot run | 🔴 Blocking |
| 3 | **The statement's day counts do not add up** — a worked holiday counts twice; six day-types count zero times | Certain | Incorrect pay | 🔴 Blocking |
| 4 | **Days before joining are paid in full** | High | Over-payment to new joiners | 🔴 Blocking |
| 5 | **Days after exit deduct full pay** | High | Over-deduction in final settlements | 🟠 Critical |
| 6 | **Leave balances can go negative** because the balance is not re-checked at approval | Medium | Payment for leave never earned | 🟠 Critical |
| 7 | **Configured policy rules are not applied** — around fifteen settings have no effect | Certain | Payroll built on rules that do not exist | 🟠 Critical |
| 8 | **Past results cannot be reproduced exactly** | Medium | A payslip cannot be defended in a dispute or inspection | 🟠 Critical |
| 9 | **Leave accrual can credit twice** under concurrent processing | Low | Silent, permanent balance inflation | 🟠 Critical |
| 10 | **Overtime worked at night is misclassified** unless the shift itself is overnight | Medium | Wrong overtime multiplier applied | 🟠 Critical |
| 11 | **Employees hired through digital onboarding have no salary record** | Certain, for every such hire | Payroll has no CTC to pay against | 🟠 Critical |
| 12 | **Changing a company or branch time zone silently alters past attendance** in any open month | Low but plausible | Lateness and day status change retroactively | 🟠 Critical |

### 12.2 Risks to operating the system in production

| # | Risk | Impact | Status |
|---|---|---|---|
| 13 | **No monitoring or alerting whatsoever.** If attendance processing failed, or leave accrual silently skipped 500 employees, nobody would find out until a user complained. | Undetected failure | 🔴 Blocking for go-live |
| 14 | **No backups and no tested restore procedure.** | Unrecoverable data loss | 🔴 Blocking for go-live |
| 15 | **No deployment process.** There is no automated way to release, and no rollback procedure. | Release risk | 🔴 Blocking for go-live |
| 16 | **Automated tests do not run before changes are accepted.** All 1 145 backend and 342 front-end tests pass when run by hand, but the automated gate runs only 362 of them, because it has no database available and no front-end step. | Regressions go undetected | 🔴 Blocking |
| 17 | **Performance has never been measured.** No load testing has been performed at any scale. | Unknown behaviour under real volume | 🟠 Critical |
| 18 | **Lists return every record.** A month's attendance for a large company returns tens of thousands of rows in a single response. | Slow and unstable at scale | 🟡 High |

---
<div align="center">— Page 17 —</div>

### 12.3 Risk profile

```
IMPACT
  ▲
  │  ┌──────────────────────┬──────────────────────┐
H │  │  Performance         │  Monthly statement   │
I │  │  unmeasured (17)     │  unavailable (1,2,3) │
G │  │  Past results not    │  Pre-joining days    │
H │  │  reproducible (8)    │  paid (4)            │
  │  │  Backups absent (14) │  Automated gate      │
  │  │  Monitoring absent   │  not running (16)    │
  │  │  (13)                │  Policy rules not    │
  │  │                      │  applied (7)         │
  │  ├──────────────────────┼──────────────────────┤
M │  │  Unpaginated         │  Negative leave      │
E │  │  lists (18)          │  balance (6)         │
D │  │  Accrual double-      │  Post-exit deduction │
  │  │  credit (9)          │  (5)                 │
  │  │                      │  Night OT (10)       │
  │  └──────────────────────┴──────────────────────┘
  │        LOWER                    HIGHER
  └────────────────────────────────────────────────► LIKELIHOOD
```

---
<div align="center">— Page 18 —</div>

## 13. Business decisions required from you

These are **not** technical faults. Each is a genuine business question the system cannot decide on your
behalf, and each changes what Payroll must calculate. **We recommend resolving these before Payroll's
design is finalised.**

---

> ### DECISION 1 — Are holidays and weekly offs paid days for everyone?
> **Today:** every holiday and weekly off is treated as a fully paid day, for all employees.
> **This is correct for monthly-salaried staff.** For daily-wage, contract or hourly workers it may
> represent over-payment.
> **We need:** confirmation, or the rule that should apply per employment type.

---

> ### DECISION 2 — How are days outside the employment period treated?
> **Today:** a day before joining is paid in full; a day after exit is a full loss-of-pay deduction.
> **Both are almost certainly wrong.** We propose: neither paid nor deducted — simply outside the
> employment window.
> **We need:** confirmation, and any rule for the joining and exit months specifically.

---

> ### DECISION 3 — Do you need half-day weekly offs?
> **Today:** the system can record "alternate Saturdays are half days", but treats them as full days off.
> **We need:** to know whether this is required. If not, we will remove the option so nobody configures
> something that has no effect.

---

> ### DECISION 4 — May HR cancel an employee's approved leave?
> **Today:** only the person who originally submitted the application can cancel it. If an employee has
> left the organisation, or is unavailable, their approved leave cannot be cancelled by anyone.
> **We need:** confirmation of who should hold this right.

---

> ### DECISION 5 — Is a negative leave balance ever permitted?
> **Today:** blocked at application, but not prevented at approval. A setting exists to allow negative
> balances, but it is never consulted.
> **We need:** a rule. *Never permitted* · *Permitted up to N days* · *Permitted with named approval*

---

> ### DECISION 6 — If an approval would overdraw the balance, block it or recover it?
> **Today:** neither. It silently goes negative.
> **We need:** *Block the approval* · *Allow it and recover through payroll* · *Allow with an exception
> approval*

---
<div align="center">— Page 19 —</div>

> ### DECISION 7 — Is the payroll period per company, per legal entity, or per pay cycle?
> **Today:** the month is closed for the whole company at once. The system has been built to support
> per-legal-entity closing, but that capability is not yet switched on.
> **This matters if:** you have multiple legal entities that need to close and pay independently.
> **We need:** the intended structure before Payroll's design is fixed.

---

> ### DECISION 8 — How are corrections handled after a month has been paid?
> **Today:** a closed month can be re-opened by a senior user, with a mandatory reason and a full audit
> record. But **there is no arrears mechanism** — no way to say "August was already paid; make a
> correcting adjustment in September's payroll".
> **We need:** *Re-open and re-run August* · *Leave August alone and adjust in September* · *Both,
> depending on circumstances*

---

> ### DECISION 9 — Restricted and optional holidays
> **Today:** treated as **working days** unless the calendar is explicitly configured otherwise.
> Employees who wish to take one apply for leave.
> **We need:** confirmation.

---

> ### DECISION 10 — A holiday falling on a weekly off
> **Today:** it remains a weekly off. **No compensatory day is granted.**
> **We need:** confirmation, or the compensatory rule that should apply.

---

> ### DECISION 11 — Overtime on a leave day
> **Today:** if an employee is on approved full-day leave but works overtime, the overtime is still
> detected and recorded.
> **We need:** should this be payable, blocked, or flagged for review?

---

> ### DECISION 12 — Working despite approved leave
> **Today:** under one available policy setting, the employee is paid as present **and** the leave day
> remains deducted from their balance until HR intervenes manually.
> **We need:** confirmation, or the intended handling.

---

> ### DECISION 13 — Should ordinary leave expire?
> **Today:** only comp-off expires. Ordinary leave never lapses beyond the annual carry-forward cap.
> **We need:** confirmation. Note that unlimited accrual creates a growing financial liability.

---

> ### DECISION 14 — Is advance leave required?
> **Today:** not available. An employee cannot borrow against future accrual.
> **We need:** confirmation of whether this is needed.

---

> ### DECISION 15 — Comp-off day length
> **Today:** each overtime policy must specify how many minutes constitute one comp-off day. **If it is
> left unset, no comp-off is ever credited** — silently.
> **We need:** the value to configure, and confirmation that this should fail loudly rather than
> silently.

---
<div align="center">— Page 20 —</div>

## 14. Technical issues to be fixed

For the engineering team. Detailed evidence appears in the companion technical reports.

### 14.1 Must be fixed before Payroll development — 3–4 weeks

| # | Item | Estimate |
|---|---|---|
| 1 | Make the automated test gate actually run all tests (add a database to the pipeline) | 1 day |
| 2 | Bulk attendance processing plus an overnight scheduled job | 1 week |
| 3 | Add paid-days and payable-days to the frozen monthly statement | 2 days |
| 4 | Correct the monthly statement's day counting | 3 days |
| 5 | Days before joining must not be paid | 1 day |
| 6 | Days after exit must not deduct | 1 day |
| 7 | Decide and implement the treatment of incomplete days before lock | 2 days |
| 8 | Make the month-close adjustment explicit, recorded and tested | 2 days |
| 9 | Preserve the figures needed to reproduce past results; add a version stamp | 3 days |
| 10 | Re-check the leave balance at approval | 2 days |
| 11 | Prevent duplicate leave accrual with a database rule | 1 day |
| 12 | Fix the web access configuration | 1 day |
| 13 | Create a salary record when an onboarded candidate is activated | 2 days |
| 14 | Guard time-zone changes once attendance has been calculated | 1 day |

### 14.2 Must be resolved before Payroll's design is finalised

- For each of the ~15 inactive policy settings: **implement or remove.**
- Confirm which record is the single source of truth for approved leave days.
- Add result limits to list screens and interfaces.
- Run the test suite under the same restricted database account used in production.

### 14.3 Must be in place before go-live

- Monitoring, error tracking and alerting
- Automated backups with a **rehearsed** restore
- An automated deployment process with a rollback path
- Login throttling and browser security headers
- A safeguard preventing sample data from reaching a live system
- Automated security scanning of third-party components
- Retry handling and failure alerts for scheduled jobs
- A screen for viewing the audit trail

### 14.4 Can be addressed alongside Payroll

Remaining calculation refinements, code organisation, performance tuning, accessibility improvements, and
documentation alignment. **None of these can cause incorrect pay.**

---
<div align="center">— Page 21 —</div>

## 15. Recommendation before Payroll begins

### 15.1 Our recommendation

> ## 🟠 NOT READY — FOUNDATION FIXES REQUIRED
>
> **Payroll design should begin immediately. Payroll implementation should begin in approximately four
> weeks, once fourteen specific fixes are complete.**

### 15.2 Why not "ready"

Payroll's purpose is to turn attendance and leave into money. Today it cannot, for four reasons:

1. **The monthly statement cannot be produced** — closing a month needs thousands of individual
   operations.
2. **The statement is incomplete** — it does not contain the paid-days figure.
3. **The statement does not add up** — some days count twice, others count not at all.
4. **Some figures are wrong** — days before joining are paid; days after exit deduct; leave balances can
   go negative.

And one reason that makes the other four dangerous: **the automated safety net is not running.** All
1 145 tests pass when run manually, but the automated gate only runs 362 of them.

### 15.3 Why this is not a serious concern

**Nothing here indicates poor engineering.** Every issue is a targeted, well-understood fix, and none
requires redesigning anything that already works.

The parts that are genuinely hard to get right — and expensive to correct later — have been done
properly:

- Client data separation is enforced at the database itself
- Access control is checked per-request against the specific record
- Records are never altered, only added to
- Historical results are protected from configuration changes
- Locked months genuinely cannot be modified, through any route we tested
- No approximate arithmetic touches money anywhere
- Every rule conflict we traced resolves the same way every time

**These are exactly the foundations Payroll needs, and they should not be touched.**

### 15.4 Recommended sequence

```
NOW ────────► Business decisions (§13) taken to you           [1 week, your input]
              Product decision on the ~15 inactive settings    [1 week]
              Payroll data model and design                    [starts now, in parallel]

WEEK 1 ─────► Fix the automated test gate first
              Quick corrections: joining/exit days, web access, accrual rule

WEEK 2 ─────► The monthly statement: add paid days, correct the counting
              Make the month-close adjustment explicit and recorded

WEEK 3 ─────► Bulk attendance processing and the overnight job
              Preserve reproducibility figures

WEEK 4 ─────► Leave balance check at approval
              Verification and re-assessment

WEEK 5 ─────► ✅ Payroll implementation begins

SEPARATE ───► Monitoring · backups · deployment · security hardening
  TRACK       (required before go-live, not before Payroll development)
```

### 15.5 Re-assessment

We recommend a short re-assessment once the fourteen fixes are complete, covering only the six readiness
gates that currently fail on Payroll-relevant grounds. Payroll implementation should begin when those six
pass.

---
<div align="center">— Page 22 —</div>

## 16. Sign-off

This review has been conducted independently. No changes were made to the system.

### Acknowledgement of findings

| Role | Name | Signature | Date |
|---|---|---|---|
| Client Sponsor | | | |
| HR Lead | | | |
| Finance Lead | | | |
| Engineering Lead | | | |
| Product Owner | | | |

### Business decisions — record of resolution

| # | Decision | Resolution | Decided by | Date |
|---|---|---|---|---|
| 1 | Holidays / weekly offs paid for all employment types | | | |
| 2 | Treatment of days outside the employment period | | | |
| 3 | Half-day weekly offs required | | | |
| 4 | Who may cancel approved leave | | | |
| 5 | Negative leave balance permitted | | | |
| 6 | Overdrawn approval — block or recover | | | |
| 7 | Payroll period structure | | | |
| 8 | Corrections after a month is paid | | | |
| 9 | Restricted / optional holidays | | | |
| 10 | Holiday on a weekly off | | | |
| 11 | Overtime on a leave day | | | |
| 12 | Working despite approved leave | | | |
| 13 | Leave expiry | | | |
| 14 | Advance leave | | | |
| 15 | Comp-off day length | | | |

### Approval to proceed

| Gate | Approved | Signature | Date |
|---|---|---|---|
| Business decisions resolved | ☐ | | |
| Fourteen pre-Payroll fixes complete | ☐ | | |
| Re-assessment passed | ☐ | | |
| **Payroll development authorised** | ☐ | | |

---

<div align="center">

*HRMS Platform — Pre-Payroll Readiness Review · Version 1.0 · 10 September 2026*

*Client Confidential*

*Companion technical reports are available to the engineering team in `docs/audits/`.*

</div>
