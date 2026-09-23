# HRMS Attendance & Timezone — Client Approval

**Prepared:** 2026-09-15
**For:** HRMS Client / Product Decision-Maker
**Purpose:** Confirm the business decisions required before attendance-timezone development begins
**Reading time:** approximately 10–15 minutes
**Companion technical document (for the engineering team only):**
[`ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md`](./ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md)

---

## 1. Executive Summary

We have completed a detailed technical audit of how HRMS handles attendance timing and timezones.
That audit found several places where the software's behaviour depends on a **business decision**,
not a technical one — decisions only you, as the product owner, can properly make.

This document exists to get those decisions confirmed, in plain language, before development starts.
It does not require you to read or understand any engineering material. Wherever an engineering
recommendation already exists, we have restated it here in business terms.

**Why this matters.** The exact interpretation of date and time touches almost every part of the
system:

| Attendance records | Late / early calculations | Night shifts | Leave |
|---|---|---|---|
| Overtime | Payroll | Historical attendance | Payroll period locking |

A punch recorded at the wrong moment, or attributed to the wrong date, can silently change a
late-arrival mark, an overtime entry, or a payroll figure — and if it happens quietly, nobody notices
until an employee or an auditor asks why a number doesn't match. Confirming these decisions now, before
a single line of code changes, is what prevents that.

**What we need from you.** Read the decisions below, tick a box for each, and sign at the end. Nine
items are listed; most already have a strong, low-risk recommendation, and several need no action at
all unless you want something different from the default.

---

## 2. The India V1 Timezone Rule

### Recommended

> **HRMS V1 uses India Standard Time (`Asia/Kolkata`) as the official business timezone.**
> **All attendance calculations use India time, not the employee's device or browser time.**

Concretely:

- An employee's phone clock, computer clock, browser timezone setting, or travel location must
  **never** change the official outcome of an attendance calculation.
- The company's operations, shifts, and payroll all run on Indian time for V1.

**Example.** An employee is physically working in India, but their laptop happens to be set to
New York time (by accident, or because they forgot to change it back from a trip). When they punch in,
HRMS records and calculates their attendance using **India time**, exactly as if the laptop were set
correctly — because the official time comes from HRMS's own server, not from the employee's device.

**One clarification, so nothing is over-promised:** this does not mean every internal setting in the
software is hard-locked to say "Asia/Kolkata." The software keeps its underlying ability to work with
other timezones (this is what lets us prove, with automated tests, that the calculation logic itself
is correct and trustworthy — the same way a scale is tested with reference weights). What is locked
down for V1 is the **business outcome**: no matter what an employee's device says, and no matter what
technical flexibility exists under the hood, the number that ends up on an attendance record or a
payslip is always computed on Indian time.

---

## 3. Decision — Authoritative Attendance Clock

### The question

When an employee punches attendance, whose clock should be treated as official — the employee's own
device, or HRMS's server?

### Recommended answer

**HRMS's own server clock is authoritative for every ordinary employee punch.**

- The employee's phone or browser clock is **never** read, stored, or trusted for a normal punch.
- **HR administrators keep the ability to enter a specific past time on an employee's behalf** — for
  example, correcting a missed punch — provided they give a reason, and it is fully logged.

### Why this is recommended

- Device clocks can be manually changed, are sometimes simply wrong, and different employees' phones
  can disagree with each other.
- Using the server as the single source of time gives the whole organization one consistent, trusted
  clock — essential for anything that feeds payroll.
- This is standard practice for any centralized attendance system.

### Business impact

- **If approved:** Every employee "Punch In"/"Punch Out" is timestamped the instant HRMS receives it.
  HR's existing "enter a missed punch" workflow is unaffected, other than gaining a mandatory reason
  field and a visible audit trail.
- **If rejected:** The alternative — trusting whatever time an employee's device reports — is exactly
  the situation a device (or a dishonest employee) could exploit to log an earlier arrival than
  actually happened. We do not recommend this for any payroll-linked attendance system.

**Client decision:** ☐ APPROVED ☐ CHANGES REQUIRED

*(Reference: `DEC-TZ-01` in the technical document.)*

---

## 4. Decision — Future-Dated Punches

### The question

If HR enters a punch on an employee's behalf, should the system simply refuse any time later than
right now — or should there be some small additional allowance, to account for minor differences
between systems?

### Recommended answer

**No additional allowance for V1.** A punch dated later than the current moment is refused outright,
with no grace window.

> **This exact numerical tolerance has not been formally set by any existing approved rule.** We are
> recommending "no tolerance" as the safe default, but this is explicitly open for your input if you
> want a specific allowance (for example, "5 minutes ahead").

### Why this matters

A future-dated punch can distort:

- attendance and late/early calculations for a day that hasn't happened yet
- overtime figures
- payroll totals
- and creates an opening for deliberate misuse (entering a convenient time in advance)

### Business impact

- **If approved (or left unanswered):** HR simply cannot enter a punch dated later than "now." This
  does not affect genuine corrections, since those are always about a time in the past.
- **If you want an allowance instead:** Tell us the number of minutes, and it will be implemented as
  a small, independent addition — it does not hold up any other part of this work.

**Client decision:** ☐ APPROVED (no allowance) ☐ SPECIFY AN ALLOWANCE: __________ minutes

*(Reference: `DEC-TZ-03` in the technical document, internally cross-referenced as `CD-7`.)*

---

## 5. Decision — Backdated Attendance

**Do not confuse this with Decision 4 above — that was about the future; this is about the past.**

### The question

How far back should HR be allowed to enter or correct an employee's attendance?

### Recommended answer

**No fixed number of days for V1.** HR may enter or correct a punch for any past date, **as long as
that date's payroll period is still open**. Once a payroll period is formally closed, no further entry
against it is possible through this workflow, regardless of how recently it closed.

> **This numeric limit has not been formally approved as a fixed policy.** The recommendation above is
> the default; if you would prefer a specific maximum (e.g., "no more than 60 days back"), that is
> your call to make.

### Why this matters

- **Operational consequence:** A generous backdating window means HR can always fix a genuinely
  missed punch without needing a separate, special process — as long as the relevant payroll period
  hasn't closed yet.
- **Payroll consequence:** Once a payroll period is closed, nothing entered against it can change a
  figure that has already been finalized and paid — this protection exists regardless of your answer
  to this question.

### Business impact

- **If approved (or left unanswered):** HR retains full flexibility to correct genuine mistakes within
  an open period, with a mandatory reason and a full record of who changed what.
- **If a specific limit is requested instead:** This becomes a small additional configuration option,
  scheduled as later, separate work — it does not block anything else described in this document.

**Client decision:** ☐ APPROVED (no fixed limit) ☐ SPECIFY A LIMIT: __________ days

*(Reference: `DEC-TZ-08` in the technical document, internally cross-referenced as `CD-5`.)*

---

## 6. Decision — Timezone Changes After Attendance Already Exists

**This is one of the more important decisions in this document.**

### The business scenario

Say your company has attendance records for **September 1–30**, already calculated and, in some
cases, already approved for payroll.

Later, an administrator edits the company's (or a branch's) attendance-timezone setting. If HRMS were
to silently recalculate September's already-finalized attendance using the *new* setting, the same
hours worked could suddenly be reinterpreted — what looked like an on-time arrival could now look
late, or vice versa — even though nothing the employee actually did has changed.

### The question

Should HRMS **block** this kind of configuration change outright once attendance already exists for
that company or branch, or should it instead **apply the new setting only to future attendance**,
leaving everything already recorded exactly as it was?

### Recommended answer

**Block the change.** Once any attendance has been recorded for a company or branch, its timezone
setting can no longer be changed through the ordinary settings screen — the system will refuse the
edit with a clear message. A brand-new company or branch that has **no** attendance recorded yet is
unaffected and can still be configured freely.

If a genuine correction is ever truly needed on a live account (expected to be extremely rare for an
India-only product), it would go through a deliberate, reviewed, one-off procedure — not a routine
settings change.

**Why not build a more flexible "apply going forward" mechanism instead?** That is technically
possible, and we describe it below as the alternative — but it is meaningfully more work to build and
test correctly, for a situation an India-only product is not expected to encounter in practice.

### Business impact

- **If approved (recommended):** Finalized historical attendance can never be silently altered by a
  later settings change. Any genuine correction becomes a deliberate, logged, assisted action rather
  than a routine edit — appropriate given how rarely this should ever be needed.
- **If rejected, in favour of "apply going forward":** The system instead keeps a version history for
  the timezone setting — similar to how shift schedules already work — so a change only affects
  attendance calculated *after* the change date, and everything before it keeps using the old setting.
  This is a larger, more complex piece of engineering work, and is only recommended if you specifically
  anticipate needing to correct a live company's timezone mid-operation.

**Client decision:** ☐ APPROVED — block the change (recommended) ☐ REJECTED — build "apply going forward" instead

*(Reference: `DEC-TZ-04` in the technical document, internally cross-referenced as `CD-8`.)*

---

## 7. Background — Attendance Date for Night Shifts

**This section is explanatory, not a decision in itself — the actual decision is Decision 8, next.**

Some shifts cross midnight. For example:

```text
Shift:  10:00 PM  →  6:00 AM
```

Consider an employee on this shift:

```text
Starts work:    10:00 PM — September 10
Still working:  12:30 AM — September 11   (after midnight)
Finishes work:   6:00 AM — September 11
```

**Which date does this attendance belong to — September 10, or September 11?**

**The answer HRMS uses: September 10 — the date the shift started.** This is deliberate and consistent
throughout the system: for a shift that crosses midnight, the entire shift — including every hour
worked after midnight — belongs to the day the shift *began*, not the day the clock happened to roll
over. **Passing midnight does not, by itself, create a new attendance record.**

This same date is then used consistently everywhere that matters: whether the day was a holiday,
whether it was the employee's scheduled day off, and how overtime for that shift is calculated. There
is no ambiguity here and **no decision required from you** — this is simply how the system correctly
recognizes a night shift as one continuous unit of work.

**What this background section does not cover** is a separate, genuinely open question about what
happens when a night-shift punch lands very close to a payroll cutoff — that is Decision 8, below.

---

## 8. Decision — Attendance Near a Payroll Period Cutoff (Night Shifts)

### The business scenario

Payroll periods eventually "close" — after which no further changes can normally be made against
them. For a night-shift employee, punches near midnight can fall right at the edge of that boundary.

Using the shift from the background section above (10:00 PM → 6:00 AM, starting September 10, with
September now closed and October open), here is exactly what happens to punches at different times,
under how the system works **today**:

| Employee's punch time | Belongs to which attendance date? | Which period is that? | Accepted today? |
|---|---|---|---|
| 12:30 AM (Sept 11) | September 10 | September — **closed** | ❌ Refused |
| 1:30 AM (Sept 11) | September 10 | September — closed | ❌ Refused |
| 3:00 AM (Sept 11) | September 10 | September — closed | ❌ Refused |
| 5:00 AM (Sept 11) | September 10 | September — closed | ❌ Refused |
| 5:29 AM (Sept 11) | September 10 | September — closed | ❌ Refused |
| 5:30 AM (Sept 11) | September 10 | September — closed | ⚠️ **Accepted today** — but harmlessly, since it can never actually rewrite September's already-closed figures |
| 6:00 AM (Sept 11) | September 10 | September — closed | ⚠️ **Accepted today** — same as above |

The technical audit found a related, more serious problem, using a **different** example (an
early-morning day shift instead of a night shift): under the current logic, a genuine, legitimate
punch can be **permanently refused and lost forever**, with no record anywhere that it ever happened —
simply because of which side of a technical midnight boundary it happened to fall on, unrelated to
which shift or which employee it was.

### The question

Should an employee's punch **ever be permanently refused and lost** because the payroll period has
already closed — or should the system **always record the physical fact** that a punch happened, and
let HR review and reconcile anything unusual afterwards?

**This only affects night-shift and very-early-shift employees**, in a roughly 5½-hour window around
midnight/dawn, right at a month-end boundary. Every regular day-shift employee is unaffected either
way.

### Recommended answer

**Never permanently refuse a punch. Always record it, and let HR reconcile anything unusual.**

The reasoning: losing a genuine punch permanently is unrecoverable — there is no way to get that fact
back later. By contrast, occasionally accepting a punch that turns out to belong to an already-closed
period is harmless on its own (it can never actually change a number that has already been finalized)
and simply shows up on a review list for HR to glance at and confirm nothing is wrong.

### Business impact

- **If approved (recommended):** No night-shift or early-shift employee's punch is ever permanently
  lost at a payroll boundary. HR occasionally sees a small number of borderline punches in a review
  report — these never affect an already-finalized figure, they are there purely for visibility.
- **If rejected:** Some genuine punches from night-shift and early-shift employees will, on occasion,
  be **permanently and silently lost** at month boundaries, with no report and no way to recover them
  — support would need a fully manual process to even find out this happened.

**Client decision:** ☐ APPROVED (recommended) ☐ CHANGES REQUIRED

*(Reference: `DEC-TZ-05` in the technical document, internally cross-referenced as `CD-1` — the single
most important decision in this document.)*

---

## 9. Decision — Punch Rounding

### The scenario

An employee punches in at, for example, **09:02**. There are three broad ways this could be handled:

- Use the exact time punched (09:02, precisely).
- Round it to the nearest configured interval (e.g., the nearest 5 or 15 minutes).
- Apply some other company-specific rounding policy.

### Current status

**HRMS today uses the exact punch time, with no rounding applied at any step.** The audit found no
existing, approved company policy defining whether or how rounding should work, and — per our
instructions for this document — **we are not proposing a specific rounding interval, because no such
number has been approved anywhere in the technical record.**

### Recommended approach

**Leave rounding out of this piece of work.** Rounding is a distinct payroll-policy question,
unrelated to the timezone corrections described in this document, and deserves its own dedicated
decision once you are ready to specify exactly how it should behave. Bundling it into this release
risks changing pay figures as a side effect of an unrelated fix.

### Why this can matter, once a policy exists

Whatever rounding policy is eventually chosen can affect: late-arrival marks, early-departure marks,
overtime calculations, and payroll totals — which is exactly why it deserves its own careful decision
rather than an assumption made along the way.

### Recommended approach vs. final client decision

| | |
|---|---|
| **Recommended approach** | Leave punch rounding exactly as it is today (exact time, no rounding) for this release; treat it as a separate future decision |
| **Final client decision** | *(your call — see below)* |

**Client decision:** ☐ APPROVED — leave as-is for now (recommended) ☐ WE WANT TO DEFINE A ROUNDING POLICY NOW

*(Reference: flagged explicitly in the technical document's decision register, §19.1, as a named but
deliberately non-blocking item — it is not assigned a numbered `DEC-TZ-`/`CD-` ID because nothing in
the currently planned engineering work depends on its answer.)*

---

## 10. Decision — Night Overtime Policy

### Current status

HRMS has a setting for a "night overtime" premium, with a few configuration options. The audit found
that **two of those options currently do nothing** — an administrator could configure them and see no
effect on anyone's pay. This is a separate pay-policy question, unrelated to the timezone corrections
in this document.

### Recommended answer

**No decision is required as part of this timezone implementation.** We recommend deferring this
entirely — it will be documented internally as "not yet active" so nobody is misled by a setting that
currently has no effect, and it can be picked up as its own, separately scoped piece of work whenever
you're ready to define exactly which overtime hours should qualify for the night premium.

### Business impact

- **If you agree to defer (recommended):** Nothing changes now. The setting remains visible but is
  documented as inactive. No pay figures are affected by this release either way.
- **If you'd like this addressed now instead:** Let us know, and we will scope it as a separate,
  dedicated piece of work — it will not be folded into the timezone release, so that a pay-policy
  decision is never made as a side effect of a timezone fix.

**Client decision:** ☐ DEFER (recommended — no action needed now) ☐ ADDRESS NOW AS SEPARATE WORK

*(Reference: `DEC-TZ-09` in the technical document, internally cross-referenced as `CD-6`. Blocks
nothing in this release either way.)*

---

## 11. Engineering Will Handle These Automatically

The technical audit identified a number of items that are purely technical corrections — they do not
change any business rule and do not require your approval. Each is one sentence:

- **Rejecting invalid timezone values** (such as an administrator accidentally typing "IST" instead of
  a proper timezone name) will be caught immediately with a clear error, instead of causing a hidden
  system error later.
- **A legacy timezone name** (`Asia/Calcutta`, an older alternate spelling of `Asia/Kolkata` that some
  browsers still send) will be automatically recognized as equivalent, wherever it appears.
- **Night-shift break handling** (for example, a meal break that itself spans midnight) will be
  corrected so it is paid or unpaid exactly as configured, regardless of which side of midnight it
  falls on — this is a straightforward bug fix with no business-policy content.
- **The automated leave-processing jobs** that currently, occasionally, use the wrong calendar date
  internally (due to a technical timezone mismatch) will be corrected to always use the correct
  Indian business date.
- **Server-side timestamping** for ordinary punches (Decision 3, above) will be implemented exactly as
  approved, with no further technical choices needed from you.
- **On-screen displays** of attendance times will consistently show Indian time, clearly labelled, so
  nobody misreads a time as being in their own browser's timezone.
- **Automated testing** will be expanded so that these corrections, once made, cannot be silently
  broken by a future change without an automatic warning.
- **Safe handling of simultaneous actions** (for example, two people editing the same record at
  once) will be added only where the audit found this could genuinely cause a problem.
- **The technical mechanism** for enforcing whichever decisions you approve above (Decisions 3, 4, 6,
  and the registration restriction referenced in Decision 6's timezone-locking) will be implemented by
  engineering once the underlying business decision is confirmed — you are approving the *rule*, not
  the *mechanism*.

---

## 12. What You Do Not Need to Decide

To be explicit, you are **not** being asked to decide any of the following — these are engineering
implementation details, not business questions:

- Database structure or indexes
- API/endpoint design
- Background job scheduling software
- Database transaction locking
- Programming language or function structure
- Testing framework or tools
- Continuous-integration (CI) pipeline configuration
- Database migration mechanics

If any of these terms appear anywhere, they belong entirely to the engineering team.

---

## 13. Business Impact At a Glance

| Area | Why timezone handling matters |
|---|---|
| Attendance | Determines when the employee actually worked |
| Late arrival | Determines scheduled time vs. actual time correctly |
| Early departure | Determines departure time against the correct local schedule |
| Night shift | Ensures a shift that crosses midnight is handled as one continuous record |
| Breaks | Determines whether a break is correctly matched as paid or unpaid |
| Leave | Determines the correct business date for leave processing |
| Overtime | Determines the correct local time an overtime period occurred in |
| Payroll | Uses attendance results directly — an attendance error becomes a pay error |
| Period lock | Determines which payroll period a given punch or correction affects |
| Reports | Prevents an employee's or manager's own browser timezone from displaying misleading times |

---

## 14. Recommended Overall Policy — One-Page Summary

```text
HRMS V1
India-only
   |
   v
Asia/Kolkata is the official business timezone
   |
   v
The HRMS server's own clock is authoritative for attendance — not the employee's device
   |
   v
Each attendance record has one clear, explicit business date
   |
   v
Night shifts that cross midnight are handled as one continuous record
   |
   v
Finalized historical attendance is protected from being silently changed later
   |
   v
An employee's browser or device timezone can never change what an attendance record means
   |
   v
Only valid, recognized timezone values are accepted anywhere in the system
```

**In plain English:** HRMS will run on India time, using its own server clock as the single source of
truth, with a clearly defined date for every attendance record — including night shifts — and strong
protection against historical figures changing after the fact. Nothing about an employee's own device
can affect what gets recorded or how it is interpreted.

---

## 15. Client Approval Table

**The table below lists every decision in this document. IDs are preserved exactly as used in the
technical execution gate — `DEC-TZ-XX` is the client-facing ID; the internal engineering
cross-reference (`CD-X`) is shown alongside it where one exists.**

| ID | Decision | Recommended answer | Client decision |
|---|---|---|---|
| `DEC-TZ-01` | Authoritative attendance clock | Server/backend time is official; device time is never trusted for a normal punch | ☐ Approve ☐ Changes required |
| `DEC-TZ-03` *(`CD-7`)* | Future-dated punch tolerance | No additional allowance beyond "not later than now" | ☐ Approve ☐ Specify: _____ minutes |
| `DEC-TZ-08` *(`CD-5`)* | Backdated attendance limit | No fixed number of days — bounded by the open payroll period only | ☐ Approve ☐ Specify: _____ days |
| `DEC-TZ-04` *(`CD-8`)* | Timezone change after attendance exists | Block the change outright once attendance exists (do not silently rewrite history) | ☐ Approve (block) ☐ Reject (build "apply going forward" instead) |
| `DEC-TZ-05` *(`CD-1`)* ⭐ | Attendance near a payroll cutoff (night shifts) | Never permanently refuse a punch; always record and reconcile | ☐ Approve ☐ Changes required |
| — *(not numbered — see §9 above)* | Punch rounding policy | Leave as exact time, no rounding, for this release; treat as separate future decision | ☐ Approve (leave as-is) ☐ Define a rounding policy now |
| `DEC-TZ-09` *(`CD-6`)* | Night overtime policy | Defer — not part of this release | ☐ Defer (recommended) ☐ Address now, separately |
| `DEC-TZ-02` *(`CD-2`)* | India-only registration & company timezone | Restrict company sign-up and profile timezone to `Asia/Kolkata` only | ☐ Approve ☐ Changes required |
| `DEC-TZ-06` *(`CD-3`)* | Amend the locked "display timezone" documentation rule | Approve — no visible change for India V1, keeps documentation consistent for the future | ☐ Approve ☐ Changes required |
| `DEC-TZ-07` *(`CD-4`)* | Automatic daily attendance calculation | Run daily at 09:30 India time, re-checking the last 3 days | ☐ Approve (09:30, 3 days) ☐ Specify: time _____ / window _____ days |

**Two rows above are also referenced in §2 and §11 but do not require a separate signature** —
`DEC-TZ-02` and `DEC-TZ-06` are included here for completeness since they are genuine business
decisions in the technical register, even though the main body of this document (§§3–10) focused on
the decisions with the clearest day-to-day operational impact.

---

## 16. Sign-Off

## CLIENT APPROVAL

I confirm that the attendance/timezone business rules described in this document are understood and
approved for HRMS V1.

Client / Product Owner: `____________________________`

Name: `____________________________`

Date: `____________________________`

Signature: `____________________________`

Comments / changes required:

`________________________________________________`

`________________________________________________`

`________________________________________________`

---

## 17. Implementation Condition

> Development of the timezone remediation will proceed according to the decisions approved in this
> document, and according to the corresponding engineering execution gate
> (`ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md`).

> If a decision is changed after this document is signed, the affected business rule, the
> implementation phase it belongs to, its tests, and its acceptance criteria must all be reviewed
> together before the change is implemented. This is to make sure a policy change is never introduced
> informally, partway through development, without everyone seeing its full effect.

---

## 18. Final Status

```text
CLIENT DECISION STATUS

☐ All required decisions approved
☐ Decisions require changes
☐ Approval pending
```

> Once the required decisions are approved, the engineering team can proceed with the implementation
> phases defined in the technical execution gate. No additional timezone audit is required unless a
> new business requirement is introduced.

---

*This document is a plain-language summary. In the event of any difference between this document and
the technical execution gate (`ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md`), the
technical execution gate is the authoritative source, and this document should be corrected to match
it rather than the other way around.*
