# Attendance V1 — A Day (and a Month) in the Life

**Read this if:** you want to see the rules in action rather than as a table. This document follows one employee through a representative month — a late morning, an early departure, a forgotten punch, a leave day, a shift on a weekly off — and shows exactly what the system determines at each step, and why.

**Read this after:** [`ATTENDANCE_V1_CLIENT_FLOW.md`](./ATTENDANCE_V1_CLIENT_FLOW.md) (the rulebook) for the reasoning behind every decision. This document is a worked-example companion to that document, using the same rules applied to concrete situations.

---

## Employee setup used in this walkthrough

The scenarios below follow a single employee for illustration. The configuration is representative of a standard office shift:

| Setting | Value |
|---|---|
| Shift | General Shift, 09:00–18:00 (9 hours) |
| Lunch break | 13:00–14:00, unpaid, 1 hour |
| Required work | 480 minutes (8 hours), net of lunch |
| Grace period (late arrival) | 15 minutes — a punch-in by 09:15 is treated as on time |
| Grace period (early departure) | 10 minutes — a punch-out from 17:50 onward is treated as on time |
| Late band | Arrival 30+ minutes late (i.e., past 09:45) forces Half-Day, regardless of hours subsequently worked |
| Hours band | 8+ hours worked → Present · 4–8 hours → Half-Day · under 4 hours → Absent |
| Weekly off | Sunday |
| Overtime | Requires manager approval before it counts; minimum 30 minutes to qualify |

None of these figures are fixed in the software — HR configures each of them, and different teams can be assigned different grace periods, bands, or shift timings (see the [Configuration Catalog](./ATTENDANCE_V1_CONFIGURATION_CATALOG.md)). The figures here are chosen only to make the walkthrough concrete.

---

## Monday — a standard day

The employee punches **IN at 08:57**, takes the lunch break, and punches **OUT at 18:03**.

- On time, full day worked, nothing to flag.
- **Result:** Present.
- **Payroll fact:** 1.00 paid day.

No configuration or approval is involved here — this is the default case that resolves silently for most of the workforce on most days.

---

## Tuesday — late arrival within grace

The employee punches **IN at 09:10**.

That is 10 minutes after the 09:00 start time, but the grace period is 15 minutes. The system does not register this as late — 09:10 is treated identically to 09:00.

- **Result:** Present. Not flagged as late.
- **Payroll fact:** 1.00 paid day.
- **Employee view:** no exception shown on the attendance record.
- **HR view:** no exception shown — lateness within the grace period is never surfaced for review.

This is the purpose of a grace period: it absorbs ordinary variation in arrival time without requiring anyone to notice, flag, or approve anything.

---

## Wednesday — late arrival beyond grace, no status impact

The employee punches **IN at 09:25**.

- Raw lateness: 25 minutes. Minus the 15-minute grace period → 10 minutes of chargeable lateness.
- 10 minutes does not cross the 30-minute Half-Day late band, so the day's status is unaffected.
- The employee punches out normally at 18:00, so hours worked also indicate Present.
- **Result:** Present, flagged "late" on the record (10 minutes).
- **Payroll fact:** 1.00 paid day — the flag is informational and has no effect on pay by itself.
- **HR view:** a "late" tag against Wednesday, useful for identifying a pattern of lateness over time, but with no automatic effect on status or pay.

---

## Thursday — lateness overriding hours worked

The employee punches **IN at 09:50** — 50 minutes after the 09:00 start time — and, to make up the time, stays back and punches **OUT at 18:45**.

This scenario illustrates a rule worth explaining to the client directly, since it is not intuitive on first read:

- Chargeable lateness: 50 − 15 (grace) = 35 minutes, which crosses the 30-minute late band.
- Hours worked for the day, excluding lunch, exceed 8 hours — on hours alone, this would be a Present day.
- The system evaluates the late band first. Once lateness crosses 30 minutes, the day is forced to Half-Day, irrespective of hours subsequently worked.

- **Result:** Half-Day, despite a full (and extended) day of hours logged.
- **Payroll fact:** 0.50 paid, 0.50 unpaid.
- **Rationale:** the rule evaluates punctuality independently of total hours. Working extra hours later in the day does not offset a late arrival — the two are judged separately, and the less favorable outcome applies.
- **Correction path:** a regularization request. If there is a legitimate reason (client emergency, transport failure), the employee can submit one with a reason, and the manager can approve it, which adjusts the record and triggers a recalculation. Without an approved regularization, the Half-Day stands.

This is the scenario most likely to prompt questions from employees and is worth walking through explicitly during client review.

---

## Friday — early departure

The employee has a prior commitment and punches **OUT at 16:40** — 80 minutes before the 18:00 end time, well beyond the 10-minute early-departure grace.

- The IN punch was on time, so there is no lateness component.
- The early-departure band on this policy is set at "60+ minutes early = flag." At 80 minutes early (70 minutes past grace), this crosses that band.
- **Result:** flagged for early departure; depending on how far the departure crosses the configured bands, the outcome is either Present-with-a-flag or Half-Day — the same tiered logic as late arrival, applied to the end of the day.
- **Payroll fact:** matches whichever status the early-departure band resolves to.
- **Correction path:** the same regularization workflow as lateness, reviewed by the manager.

---

## Following Monday — a missed punch

The employee goes directly to a client site and forgets to punch IN, but does punch **OUT at 18:05**.

- The system records a single OUT punch with no matching IN, and cannot compute hours worked from an incomplete pair.
- The company's missing-punch policy is set to the default: Incomplete, not an automatic Absent. (A stricter policy could be configured to mark Absent instead; this company has not done so.)
- **Result:** Incomplete. Neither paid nor unpaid until resolved.
- **Resolution:** the employee submits a regularization request — for example, "Forgot to punch in; on-site with a client from approximately 09:00." This is within the company's 7-day backdating window and is accepted for review.
- The manager reviews and approves the request. The system adds the missing IN punch and recalculates the day, which typically resolves to Present given a normal remainder of the day.
- **Result after approval:** Present.
- **Payroll fact:** 1.00 paid day, once approved. If the request is not submitted before the period is locked, the correction is refused until HR explicitly reopens the period — which is why timely submission matters more as month-end approaches.

---

## Wednesday — half-day approved leave

The employee takes approved half-day leave for the morning, then punches **IN at 14:05** and **OUT at 18:10**.

- The Leave module has already approved 0.5 day of leave for this date and synced it to Attendance.
- Attendance combines the leave credit (0.5 day) with the hours actually worked in the afternoon.
- **Result:** Half-Day — but distinct in kind from Thursday's Half-Day. Thursday's outcome was a consequence of lateness; this one is a planned, approved outcome and requires no review.
- **Payroll fact:** approximately 1.00 paid day in total (0.50 from approved leave plus 0.50 from hours worked). The exact split depends on how the leave and worked-hours fractions are combined, but the intent is that approved half-day leave does not reduce pay the employee is entitled to.

---

## Thursday — full-day approved leave, no punches

The employee is on approved sick leave and does not come in or record any punches.

- Because Leave has already confirmed approved leave for this date, the system does not evaluate the absence of punches as a gap — the leave overlay takes precedence over an empty punch record.
- **Result:** Leave (not Absent, not Incomplete).
- **Payroll fact:** paid or unpaid according to the leave type's own configuration (e.g., paid sick leave → 1.00 paid; unpaid leave → 0 paid, 1.00 unpaid).
- **Note on timing:** if leave is approved a few days after this date's attendance was already calculated, the system automatically recalculates the day once the leave syncs in — no manual correction is required, provided the period is not yet locked.

---

## Sunday — work on a weekly off

The employee is normally off on Sundays, but is rostered in for this specific Sunday to handle a client shipment, punching **IN at 09:05** and **OUT at 15:30** (6 hours).

- Because the manager explicitly rostered the employee for this Sunday, the day is evaluated normally rather than treated as a weekly off.
- All hours worked on a weekly-off day are evaluated as overtime, not only hours beyond a normal shift end.
- The overtime is classified specifically as "Weekly-Off overtime," so it is reportable separately from overtime on an ordinary weekday.
- Because the overtime policy requires manager approval, the overtime is recorded as Pending until reviewed. It counts toward payroll only after approval.
- **Result:** Present for the day, plus Pending Overtime (6 hours, Weekly-Off classification).
- **Payroll fact:** 1.00 paid day for Sunday (weekly offs are paid by default, worked or not), plus overtime minutes once approved.
- **Period-close implication:** if this overtime approval is still Pending when HR attempts to close the month, period close is blocked until it is decided. The system neither drops the request nor allows it through automatically — approval requires an explicit decision.

---

## Month-end — locking a payroll-ready result

At the end of the month, HR opens the Period Finalization screen for the employee's team. Before the period can be locked:

1. Every pending regularization must be decided (approved or rejected).
2. Every pending overtime request must be decided.
3. Any day still marked Incomplete is resolved according to the "incomplete-at-lock" setting — by default, treated as Absent once the period closes, unless HR has configured it to default to Present or remain Incomplete for manual review.
4. Once all outstanding items are resolved, HR locks the period.

After the lock:

- No new punches, leave syncs, regularizations, or overtime requests can affect that period.
- Every day for every employee has a final, unambiguous paid fraction and unpaid (loss-of-pay) fraction — this is what is handed to payroll.
- If a correction is genuinely needed after lock, HR must explicitly reopen the period first — a deliberate, auditable action rather than an implicit one.

For this month, the resulting handoff to payroll looks approximately like:

| Day | Status | Paid | Unpaid |
|---|---|---|---|
| Mon | Present | 1.00 | 0.00 |
| Tue | Present (grace absorbed) | 1.00 | 0.00 |
| Wed | Present (late flagged, no cost) | 1.00 | 0.00 |
| Thu | Half-Day (late band, despite extra hours) | 0.50 | 0.50 |
| Fri | Present/Half-Day (early-departure band) | per band | per band |
| Mon (missed punch, regularized) | Present | 1.00 | 0.00 |
| Wed (half-day leave) | Half-Day (planned) | ~1.00 | ~0.00 |
| Thu (full leave) | Leave | per leave type | per leave type |
| Sun (worked, rostered) | Present + OT | 1.00 + OT | 0.00 |

This is the figure payroll actually consumes — every row traceable to a specific punch, leave record, or approval.

---

## Summary reference

| Situation | Governing rule | Typical result |
|---|---|---|
| Arrival within grace period | Grace-in minutes | Present, not flagged |
| Late arrival beyond grace, under the Half-Day late band | Late band (lower tier) | Present, flagged late |
| Late arrival crossing the Half-Day late band | Late band (upper tier) — overrides hours worked | Half-Day, regardless of hours subsequently worked |
| Early departure within grace | Grace-out minutes | Present, not flagged |
| Early departure beyond grace and beyond the early band | Early-departure band | Present-flagged or Half-Day, depending on severity |
| Missed punch | Missing-punch policy (default: Incomplete) | Incomplete, resolved via regularization |
| Half-day approved leave, worked the remaining half | Leave overlay combined with worked hours | Half-Day (planned, not a penalty) |
| Full-day approved leave, no punches | Leave overlay takes precedence over punches | Leave |
| Work on a weekly off or holiday | Roster plus overtime detection | Present, plus Overtime (Pending until approved) |
| Outstanding item at month-end (pending OT, pending regularization, Incomplete day) | Period finalization checks | Blocks lock until resolved |

For the complete rulebook behind each line above — including every configurable figure and scenarios not covered in this walkthrough — see the [Client Flow](./ATTENDANCE_V1_CLIENT_FLOW.md) and [Scenario Catalog](./ATTENDANCE_V1_SCENARIO_CATALOG.md) documents.
