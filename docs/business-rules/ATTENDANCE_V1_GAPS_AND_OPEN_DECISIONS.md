# Attendance V1 — Gaps, Stored-But-Unused Settings & Open Decisions

**Read this if:** you want the honest, complete list of what's not finished, what looks configurable but isn't active, and every decision that needs a client answer before it can be built or hidden.

See [`README.md`](./README.md) for tag meanings.

---

## Part 1 — Settings that exist but currently do nothing

For each: what HR might reasonably expect it to do, what actually happens today, why it matters, and the recommended path forward. **None of these have been changed — this is an inventory, not a fix list.**

### Attendance Policy fields

| Field | What HR might expect | What happens today | Why it matters | Recommended path |
|---|---|---|---|---|
| Punch rounding / rounding minutes | Punch times round to the nearest 5/10/15 minutes before evaluation | No rounding is applied — the exact punch timestamp is used | Common expectation, especially for biometric devices with slight drift | Implement if a client confirms it's a real requirement; otherwise hide the setting |
| Half-day split method + boundary minutes | A specific minute threshold decides Half-Day | The general hour bands (§Attendance Policy) already do something similar; this specific setting is unused | Risk of HR configuring this and expecting a different threshold to take effect | Consolidate into the hour-bands mechanism, or hide |
| Core-hours breach behaviour / early-out-uses-core-end | A flexible shift's "core hours" (mandatory presence window) is enforced with a specific consequence when breached | Core hours are stored on the shift but never checked at all | Flexible-shift clients often expect this | High-priority candidate for implementation if flexible shifts are widely used |
| Excess-break behaviour | A specific consequence (flag / reduce pay / etc.) when someone exceeds max break time | The excess is recorded as a number, but no automatic consequence happens | HR may assume "flag" already triggers a review step | Implement the chosen consequence, or hide until decided |
| Auto-close-after-minutes / auto-close-uses-shift-end | The system automatically inserts a clock-out for someone who forgot, some time after shift end | Nothing is auto-inserted — the day just falls through to the normal missing-punch handling | The setting's name strongly implies working behaviour — this is the most likely to cause false confidence | Rename/relabel in the UI immediately to avoid confusion, regardless of whether it's later implemented |
| Split-shift block mandatory / allow-hours-compensation | Missing one duty block in a split shift can be compensated by extra hours in another block | Not evaluated — the configured missed-block behaviour (ignore/half-day/absent/require-correction) is the only thing applied | Relevant for field/security staff with irregular block coverage | Needs a product decision on whether cross-block compensation should exist at all |
| WFH-requires-punch / On-duty-requires-punch / WFH-uses-shift-hours | These fields imply a working WFH/On-Duty attendance mode | No day is ever evaluated with a WFH or On-Duty status by the engine (see below) | Tied to the larger WFH/On-Duty gap | See ND-06 below |
| Late-count-window / lates-to-half-day-count | "3 late arrivals within 30 days automatically becomes a half-day deduction" | No such automatic conversion happens; each late day is judged independently | Common Indian HR expectation | Needs explicit design — see ND-01 |
| Early-departure-requires-approval | Leaving early without a pre-approval is blocked or flagged differently | No distinct enforcement — early departure is judged the same way regardless of approval | Lower priority | Hide or implement based on demand |
| Band "counts toward cap" flag (on late/early bands) | Feeds the late-count feature above | Unused, same reason | Tied to late-count feature | Same as above |

### Shift / Break fields

| Field | What HR might expect | What happens today | Why it matters | Recommended path |
|---|---|---|---|---|
| "Is night shift" flag on the shift | Marks a shift as eligible for night-OT treatment | Overtime's night classification actually checks whether the shift **crosses midnight**, not this flag | Confusing duplication — two settings that sound like the same thing, only one is used | Remove the unused flag, or wire it into the night-OT check for clarity |
| Core hours (start/end) on Flexible shifts | A mandatory presence window within the flexible window | Never checked | Same as the Attendance Policy row above | Same recommendation |
| Break "mandatory" flag / minimum-duration | A mandatory break is deducted even if the employee doesn't punch a gap for it | The system only deducts a break if a matching punch gap exists — it never auto-inserts an unpunched mandatory break | Employees who skip lunch without punching out would currently be credited for the full time as worked | Needs a product decision — auto-deducting an unpunched mandatory break changes payroll outcomes and should be explicit |
| Legacy Shift-record grace/threshold fields | Old-style shift settings for late/absence | Not read by the current calculation engine at all — only the current-generation Attendance Policy settings are used | Leftover from an earlier design iteration | Should be cleaned up/removed from the UI to avoid confusion |

### Overtime Policy fields

| Field | What HR might expect | What happens today | Why it matters | Recommended path |
|---|---|---|---|---|
| Requires-pre-approval | Employee must get approval **before** working overtime, not just after | Not enforced — only post-approval (after the fact) is implemented | Some industries require pre-approval by law/policy | Needs a product decision on whether pre-approval workflow is in scope |
| Night OT window start/end | Only count overtime as "Night" if it actually falls within specific clock hours | Not used at all — night classification (when active) only checks the cross-midnight flag | Manufacturing/security clients with strict night-shift pay differentials will notice this | See ND-03 below |
| "By grade" OT eligibility | Only employees at certain grades are OT-eligible | Currently behaves exactly like "Always eligible" — no grade check happens | Could result in OT being detected/approved for employees who shouldn't be eligible | See ND-07 below — high priority to resolve before go-live if grade-based eligibility is a real requirement |

### Regularization Policy fields

| Field | What HR might expect | What happens today | Why it matters | Recommended path |
|---|---|---|---|---|
| Auto-approve-within-minutes | Small corrections (e.g., under 15 minutes) get approved automatically without a human | Not used — the configured approval chain (Auto/Manager/HR/Manager-then-HR) is a separate, all-or-nothing setting per request type, not a minutes-based auto-approval | Could reduce approver workload if implemented | Low priority unless requested |

### Day-status values that are never produced

| Status | What HR might expect | What happens today |
|---|---|---|
| Work-From-Home (WFH) | A day explicitly marked as WFH, separate from Present | Never produced by the calculation engine — even a WFH-typed regularization request only helps if it results in ordinary punches or a shift change |
| On-Duty | A day explicitly marked as field/outdoor work | Same as above |

### Period fields

| Field | What HR might expect | What happens today |
|---|---|---|
| Legal-entity-level lock grain | Locking a specific legal entity's period independently of the rest of the company | Locking currently applies at the whole-company level; a legal-entity field exists on the period record but is not used |
| A "Closing" (in-progress) period state | A visible in-between state while a lock is being processed | Only two states exist: Open and Closed — there is no persisted in-between state |

---

## Part 2 — Open product decisions (existing, from architecture sign-off)

| ID | Topic | Current default behaviour | Needs a decision on |
|---|---|---|---|
| PD-CAL-1 | Optional/Restricted holidays | Working day by default; a company-wide flag can harden them into real holidays | Whether this default is right for your client base, or should be leave-driven instead |
| PD-CAL-2 | Auto-substitute a holiday that falls on a weekly-off | No automatic substitute — manual exception only | Whether automatic substitution should be built |
| PD-APR-1 | Which date's manager approves a request | The manager assigned to the employee **as of the attendance date**, not today's manager | Confirm this matches expectation for transferred/promoted employees |
| PD-POL-1 | Whether HR should be able to reorder the 8-level precedence walk | Fixed order, not configurable | Confirm the fixed order is acceptable (recommended: keep fixed) |
| PD-POL-2 | Whether grace periods should also live on the Shift | Grace lives only on the Attendance Policy | Confirm Attendance-Policy-only grace matches expectation |
| PD-SHIFT-1 | Changing an employee's shift mid-day | Not supported — one schedule per attendance date | Confirm this is acceptable (recommended: keep as-is; mid-day shift changes are rare and complex) |
| PD-LOCK-1 | Locking grain — whole company vs. legal entity | Whole company | Confirm whether multi-legal-entity clients need independent locking |
| PD-WFH-1 | Automatic WFH status from an employee's assigned work-location | Not implemented — placement data exists but doesn't drive attendance status | See ND-06 |
| PD-OT-1 | Whether overtime should default to requiring approval | Yes, post-approval required, Manager chain | Confirm this is the desired default |
| PD-BR14-SHIFT | Automatic default-shift cascade (branch → company) when an employee has no shift assigned | Not implemented — no shift is a valid, deliberate state | Confirm whether a fallback default shift should exist |

---

## Part 3 — New decisions surfaced by this review

Each entry: the problem, the choices, the recommendation, and why.

### ND-01 — What to do about all the stored-but-unused fields
**Problem:** Many settings are visible and editable in configuration screens but don't affect calculation, which risks HR configuring something and assuming it's active.
**Choices:** (1) Build the missing behaviour, (2) Hide/disable the setting in the UI until it's built, (3) Remove the field entirely.
**Recommended:** Hide the unused settings from configuration screens in the near term, with a backlog to build the ones that come up as genuine client requirements (rounding, late-count, WFH, core hours).
**Why:** Prevents false confidence without committing to build everything at once.

### ND-02 — Roster vs. Shift-scoped policy mismatch
**Problem:** Publishing a roster correctly changes an employee's working schedule, but a policy assigned "by shift" still resolves using the employee's original assigned shift, not the roster's shift.
**Choices:** (1) Make shift-scoped policy resolution follow the roster's shift for that date, (2) Keep current behaviour and document it clearly as intentional, (3) Disallow assigning policies at the Shift level at all.
**Recommended:** Option (1) — align policy resolution with the roster, since that matches what most HR teams would expect ("if I moved them to Night Shift, Night Shift's rules should apply").
**Why:** Avoids a silent mismatch when someone is temporarily reassigned.
**Impact:** Correct policy application for temporarily-reassigned staff; fewer HR support queries about "wrong grace period applied."

### ND-03 — Night overtime classification
**Problem:** With the default setting, overtime worked on a night/cross-midnight shift is never actually classified as "Night" — it's recorded as Normal overtime, and the specific night-time-window setting is never checked at all.
**Choices:** (1) Fix the default so a cross-midnight shift correctly produces Night classification, (2) Build proper support for the specific night-window setting, (3) Remove the Night classification option until it's properly designed.
**Recommended:** Do (1) as a quick correctness fix; treat (2) as a later enhancement. No pay/money is affected by this — only the classification label.
**Why:** Manufacturing/security/24x7 operations clients are the most likely to notice and care about this.

### ND-04 — Leave day retaining overtime/worked-minute numbers
**Problem:** When a day's status becomes "Leave" (in the default "leave wins" mode), any overtime or worked-minutes figures calculated from punches on that same day are not automatically cleared out.
**Choices:** (1) Zero out overtime/worked-minutes on a Leave day for payroll-facing purposes, (2) Keep as-is, treating it as a useful audit trail of "worked despite being on leave," (3) Only apply the "flag work-on-leave" behaviour (which keeps the punch-based status) whenever punches exist, instead of Leave always winning.
**Recommended:** Option (1) for the numbers that feed payroll, while still keeping the raw punch record visible separately for audit purposes.
**Why:** Avoids a payroll-facing report showing "Leave" alongside a non-zero overtime figure, which reads as a contradiction.

### ND-05 — "Auto-Close" naming
**Problem:** The setting name "Auto-Close" strongly implies the system inserts a missing clock-out automatically; it currently does not.
**Choices:** (1) Build the actual auto-close behaviour (insert a synthetic clock-out at shift-end or after N minutes), (2) Rename/relabel the option in the UI to avoid the false expectation, (3) Map it internally to "Incomplete" without exposing a separate name.
**Recommended:** Do (2) immediately regardless of the long-term plan, since it's a low-cost fix that prevents ongoing confusion. Consider (1) only if clients specifically request true auto-close behaviour, with explicit rules agreed first (which shift, how many minutes after, what time to close at).

### ND-06 — Work-From-Home / On-Duty statuses
**Problem:** The system's data model anticipates WFH and On-Duty as distinct attendance outcomes, and lets a correction request be typed as either — but the calculation engine never actually produces those statuses.
**Choices:** (1) Build the actual WFH/On-Duty overlay logic, (2) Remove WFH/On-Duty from the list of allowed correction types until it's ready, (3) Keep the types available but document clearly (in the product, not just here) that they currently only work by producing ordinary punches/shift changes.
**Recommended:** Do (2) in client-facing product copy now (don't advertise it as working), and treat (1) as a scheduled future slice if hybrid/remote work tracking is a real requirement for your client base.
**Why:** Prevents managers/employees from submitting a WFH request expecting a WFH-labelled day and getting a generic Present/Incomplete result instead.

### ND-07 — "By grade" overtime eligibility
**Problem:** This eligibility mode is meant to restrict overtime to specific employee grades, but it currently has no grade check at all — it behaves exactly like "Always eligible."
**Choices:** (1) Implement an actual grade-based check, (2) Remove this eligibility mode until it's built, (3) Document it clearly as an alias for "Always eligible" for now.
**Recommended:** If grade-based OT eligibility is a genuine requirement (common in Indian manufacturing, where only certain grades are OT-eligible by policy/law), prioritize building (1) before go-live — this is one of the higher-risk gaps because it could result in unintended overtime approvals.

### ND-08 — What happens when a locked period is reopened
**Problem:** Reopening a locked period restores the ability to make changes, but does not automatically recalculate anything — so a reopened period can sit with stale numbers until someone manually triggers a recalculation.
**Choices:** (1) Force a full recompute automatically whenever a period is reopened, (2) Give HR an explicit checklist/action to run recompute after reopening, (3) Mark reopened-but-not-recomputed days with a visible "stale" indicator.
**Recommended:** Option (2) for now — an explicit, deliberate recompute step is safer than an automatic one that might silently overwrite figures HR didn't expect to change. Consider (1) as an optional, clearly-labelled bulk action.
**Why:** Payroll safety — an accidental silent recompute after reopening could change numbers that were already reported externally.

### ND-09 — Half-day leave "first half" vs. "second half"
**Problem:** Half-day leave records which half of the day (morning/afternoon) is being taken, but the system currently applies a flat 0.50-day credit regardless — it doesn't actually limit evaluation to just that half of the shift.
**Choices:** (1) Actually evaluate only the specified half of the shift for punch purposes, (2) Keep the current flat 0.50 approach, (3) Remove the first/second distinction until it's meaningful.
**Recommended:** Keep the current flat approach until the future Leave module defines exactly how half-day leave should interact with shift timing — trying to build this now, ahead of that design, risks having to redo it.

### ND-10 — Corrections after a period is locked
**Problem:** There is no dedicated "post-lock adjustment" capability — the only way to fix something after lock is a full reopen, which is a blunt instrument (unlocks everything for that date range, no automatic recompute, no arrears tracking for payroll that's already been run).
**Choices:** (1) Build a proper post-lock adjustment/arrears feature, (2) Rely on reopen + manual recompute as the only mechanism, (3) Treat post-lock corrections as strictly a manual/payroll-side process outside this system.
**Recommended:** Plan to build (1) before the first fully paid, closed payroll cycle goes live for a client — this is a common real-world need ("we found a mistake after payroll already ran") and the current tools aren't designed for it.

---

## Part 4 — Explicitly future / not-yet-built modules

These are not gaps in the current module — they are simply **owned by something that doesn't exist yet**:

| Capability | Owned by |
|---|---|
| Leave applications, approval workflow, balances, accrual, sandwich-leave rules | Future Leave module |
| Redeeming comp-off against actual leave | Future Leave module |
| Any payroll money calculation — pay rates, OT pay, LOP deduction amounts, payslips | Future Payroll module |
| Biometric/device connector pipeline (beyond manually-recorded or integrated punches) | Future Device module |
| A general-purpose, reusable approval-workflow engine (current approvals use simpler, purpose-built chains) | Future Workflow Engine |
| Post-lock adjustments / payroll arrears | Future slice — see ND-10 |
| Automatic shift-rotation pattern generation for rotating crews | Future slice (rosters can be entered manually today) |
| Statutory/state-specific overtime pay rules | Future Payroll/Statutory module — this system only classifies OT and stores an informational multiplier, never computes pay |

---

## Part 5 — Known edge cases worth being aware of

These are not necessarily wrong — they are simplifications worth knowing about:

1. A "soft" (optional/restricted) holiday with punches recorded, and no leave applied, is simply treated as a normal working day — nothing special is recorded beyond the holiday's name showing for reference.
2. Multiple overlapping leave projections on the same date are prevented from exceeding 1.00 total, but there's no dedicated screen for HR to review overlaps — this is enforced at the data level only.
3. A day's overtime can be recalculated and come out differently if a related day's overtime record changes (weekly/monthly caps are calculated relative to sibling days) — this is a documented simplification of how caps are tracked, not a bug.
4. Whether an attendance day's "is regularized" indicator is reliably visible across recalculations is inconsistent today — HR should rely on the regularization request history, not this flag, when auditing corrections.
5. Split shifts don't currently give partial credit for a partially-worked duty block — a block is either fully counted or handled via the missed-block rule.
6. Punch de-duplication logic and any concurrent roster update during a regularization approval have a narrow timing edge case that hasn't been stress-tested — low risk in normal usage patterns.
7. If configuration (calendars, policies) changes partway through an open period, only unlocked days recalculate on demand — there's no bulk "recalculate everyone affected by this change" action; each affected day needs to be recalculated individually or in a batch operation run by an administrator.

---

## Where to go next

- The full narrative flow → [`ATTENDANCE_V1_CLIENT_FLOW.md`](./ATTENDANCE_V1_CLIENT_FLOW.md)
- Precedence rules referenced above → [`ATTENDANCE_V1_PRECEDENCE_AND_OVERRIDE.md`](./ATTENDANCE_V1_PRECEDENCE_AND_OVERRIDE.md)
- The actual sign-off checklist to work through with the client → [`ATTENDANCE_V1_CLIENT_SIGNOFF.md`](./ATTENDANCE_V1_CLIENT_SIGNOFF.md)
