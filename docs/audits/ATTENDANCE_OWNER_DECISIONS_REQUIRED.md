# Attendance — Owner Decisions Required — 16 November 2026

**For:** the product owner. **Status:** every decision below is **pending**. The "recommended" lines
are engineering suggestions to make the choice easier; **none is approved**, and nothing in
`ATTENDANCE_REMEDIATION_PRIORITY_PLAN.md` that depends on a decision will be built until the owner
records a choice in the last line of its block.

**Source:** the whole of `ATTENDANCE_POLICY_DECISION_REGISTER.md` (H-, D-, P-, O-, L-, C-, V- rows
and sections 7–8), checked against the verification. Money language: "one day of loss of pay"
means one day's pay is withheld, whatever the payroll divisor is (a payroll decision, not this
document's).

---

## 1. How the register splits

| Group | Rows | Count |
|---|---|---|
| **A. Must be decided before code can be written** | H-01, H-02, H-03, H-04, P-05, P-04, H-05, D-01a, D-01b, R-2, H-07, H-08, H-29, H-30, O-19 (+ regularization twin NF-1), L-09, L-06 | 17 |
| **B. Change pay, loss of pay or leave balances (of which A is part)** | A, plus H-06, H-11, H-16, H-18, H-19, H-20, H-22, H-26, O-06, O-12, O-14, O-15, L-04, L-10, L-12, PD-CAL-1, PD-CAL-2, C-10, LV-01..03 | about 40 (approximate, not counted row by row) |
| **C. Defaults built without owner approval** (register says "Approved: No" or "Default") | H-05, H-06, H-07, H-08, H-10, H-12, H-13, H-16, H-18, H-19, H-20, H-21, H-25..H-30, O-01..O-06, O-08, O-11..O-15, O-19..O-21, L-02, L-04, L-06, L-07, L-09, L-10, L-12, L-13, C-02, C-03, C-04, C-10..C-17; plus P-A, P-B, P-C, AC-04 `TREAT_PRESENT`, AC-05 threshold, AR-06, AR-11, AR-12, D-09/AR-14, R-2, R-3 | about 60 (approximate) |
| **D. Already decided and built** | H-09, H-14, H-15, H-17, H-23, H-24, O-07, O-09, O-10, O-16, O-17, O-18, L-01, L-03, L-05, L-11, C-06..C-09, P-02, P-06, P-13, D-1, BUS-001/002/003/011/012, D-01..D-04, P-E (choices inside it excepted) | — |

Group C is the real risk: about 60 rules change what employees are paid or what leave they hold
and nobody has signed them. Section 4 asks for them in batches.

---

## 2. Decisions needed before implementation (Group A)

Format: **Question** · **Today** · **Recommended** · **Alternatives** · **Money and operations** ·
**Implementation implication** · **Owner decision**.

### H-01 — A day with minutes no hour band covers
- **Today:** `PRESENT`, paid in full. Verified (probes 1 and 3). 30 minutes worked = a full day.
- **Recommended:** refuse such bands at publish (must start at 0, no gaps); treat "no band" as
  `CONFIG_ERROR`.
- **Alternatives:** (b) keep `PRESENT` but warn; (c) treat uncovered minutes as the band below.
- **Money/operations:** (recommended) existing hand-built policies with gaps stop paying full days
  for short work; they must be republished or their days become `CONFIG_ERROR` and block close.
  Templates are not affected (they start at 0).
- **Implementation:** publish validation (no migration), engine `CONFIG_ERROR`, impact report
  first. Two PRs.
- **Owner decision:** ☐ pending

### H-02 — A person who never punched: incomplete or absent?
- **Today:** `INCOMPLETE` by default; at lock `TREAT_PRESENT` pays it in full (verified in code),
  `TREAT_ABSENT` makes it a full day of loss of pay, `KEEP_INCOMPLETE` blocks close.
- **Recommended:** zero punches on an expected day is a no-show: `ABSENT` after the day's punch
  window has closed; `TREAT_PRESENT` applies only where at least one punch exists.
- **Alternatives:** (b) leave as is but remove `TREAT_PRESENT` from the screens; (c) keep and add a
  close blocker for zero-punch days under `TREAT_PRESENT`.
- **Money/operations:** (recommended) days a missing employee used to be paid for become loss of
  pay: a direct reduction in payroll for tenants using `TREAT_PRESENT`. (b)/(c) keep behaviour but
  stop it being silent.
- **Implementation:** engine and lock resolution; `incomplete_at_lock_behaviour` semantics change;
  UI text for the setting; impact report of locked days.
- **Owner decision:** ☐ pending

### H-03 — Comp-off: when usable, and what follows overtime corrections
- **Today:** credited by the hourly sweep once a record is approved; never reduced; a re-detected
  record credits again (0.38 + 0.06 = 0.44 for 30 minutes).
- **Recommended:** credit follows the record: reduce or reverse on cap, reopen, withdrawal or
  deletion; one credit per source record.
- **Alternatives:** credit only at period close; or allow negative balance after a reversal; or
  freeze credit once any leave has been taken against it.
- **Money/operations:** existing balances may exceed overtime (impact report). Reversing below
  zero when comp-off was already taken needs a rule.
- **Implementation:** `LeaveCompOffService`, `_comp_off_facts`, ledger entry for reversals,
  integrity report, balance notice.
- **Owner decision:** ☐ pending (including the below-zero rule)

### H-04 — Which shift governs a rostered day off
- **Today:** none: a shift-scoped calendar or policy does not resolve, and the day is
  `CONFIG_ERROR`.
- **Recommended:** the shift on the employee's assignment for that date.
- **Alternatives:** (b) the previous working day's shift; (c) company-scope policy only for off days.
- **Money/operations:** removes close blockers for employees with shift-scoped policies; overtime
  worked on a roster off day starts being counted.
- **Implementation:** `_scope_candidates` and engine order.
- **Owner decision:** ☐ pending

### P-05 — Hour bands for short and long shifts
- **Today:** fixed minutes. A 4-hour shift worked exactly is a half day (probe 6).
- **Recommended:** bands as a share of the shift's net minutes.
- **Alternatives:** (b) one policy per shift length, enforced at assignment; (c) leave fixed and
  document.
- **Money/operations:** part-time staff on a standard policy lose half a day's pay per day today;
  (a) corrects it; (b) leaves the work to HR.
- **Implementation:** (a) changes the band schema (percent bands) and engine; (b) is validation only.
- **Owner decision:** ☐ pending

### D-01a / D-01b / R-2 — The "mark" ceiling
- **Today:** a late or early mark credits up to 59 minutes per end, measured from shift start (grace
  included). 50–59 minutes late costs half a day on the standard template; two marks together
  excuse up to 118 minutes. Template text says marks are "not deducted".
- **Recommended:** measure beyond grace; one combined ceiling per day.
- **Alternatives:** keep and change the template text; ceiling per policy.
- **Money/operations:** (recommended) fewer half-days for arrivals up to 59 minutes after grace;
  (keep) more half-days than the screen promises.
- **Implementation:** `grace_band_credit_detail`; template text web and mobile; maybe a policy field.
- **Owner decision:** ☐ pending

### P-04 — Work before a FIXED shift's start
- **Today:** counts nothing; a whole session before the start is `ABSENT`.
- **Recommended:** count it toward the day (not as overtime) when the employee worked no part of the shift.
- **Alternatives:** keep and refuse such punches; make it per policy.
- **Money/operations:** removes a full day of loss of pay for early starters.
- **Implementation:** `clamp_pairs_to_start`, overtime interaction.
- **Owner decision:** ☐ pending

### H-05 — Does grace also lower band thresholds?
- **Today:** yes, by up to `grace_in + grace_out`. On the standard template a person who worked 230
  minutes is `HALF_DAY` under an "absent below 240" band.
- **Recommended:** credit grace only where the miss at that end is within grace.
- **Alternatives:** keep (documented); per-policy switch.
- **Money/operations:** (recommended) up to 20 minutes' difference at each band edge, standard
  template; 60 on the flexible template.
- **Implementation:** `grace_band_credit_detail`.
- **Owner decision:** ☐ pending

### H-06 — Policies with no late/early bands
- **Today:** one minute past grace on an 8-hour shift with an 8-hour full-day band is a half day.
- **Recommended:** warn at publish and offer a one-click "add mark band"; existing policies unchanged.
- **Alternatives:** automatic mark band; do nothing.
- **Money/operations:** warning only; no immediate pay change.
- **Implementation:** publish response warnings, template.
- **Owner decision:** ☐ pending

### H-07 / H-08 — Half-day leave and the other half
- **Today:** half-day leave and no punches: the other half is loss of pay at once (a full no-show
  waits as `INCOMPLETE`). Half-day leave on a day that is, or has become, a day off: 0.50 loss of pay.
- **Recommended:** H-08: nothing to lose on a day off. H-07: treat like any no-show (H-02).
- **Alternatives:** H-07 keep.
- **Money/operations:** H-08 removes a wrong 0.50 deduction. H-07 depends on H-02.
- **Implementation:** `_apply_leave_overlay`.
- **Owner decision:** ☐ pending

### H-29 — Lateness in the worked half of half-day leave
- **Today:** with no late bands the cliff costs a quarter day; with bands it is a mark.
- **Recommended:** judge the worked half by hours only, or apply the full-day mark rule.
- **Alternatives:** keep.
- **Implementation:** `_apply_leave_overlay` worked-half verdict.
- **Owner decision:** ☐ pending

### H-30 — Deactivating a calendar, work calendar or weekly-off pattern
- **Today:** has no effect on any date or on leave counting.
- **Recommended:** refuse deactivation while linked; deactivation takes effect only by an effective-dated unlink.
- **Alternatives:** make `is_active=false` effective from a given date.
- **Money/operations:** stops an administrator believing holidays are off when they still apply.
- **Implementation:** `calendar_setup`, `calendar_overlay`; reconciliation consequences.
- **Owner decision:** ☐ pending

### O-19 (+ NF-1) — A stalled manager-stage approval
- **Today:** only the snapshotted manager can act, for overtime and for regularization; no
  reassignment. If the manager leaves, the record blocks period close.
- **Recommended:** HR (company scope) may reassign (as leave does) and may also decide at any stage.
- **Alternatives:** HR may only reassign; auto-escalate after N days.
- **Money/operations:** removes a close blocker that today needs a policy change affecting everyone.
- **Implementation:** new endpoint or relaxed `_get_reviewable`, audit entry, tests.
- **Owner decision:** ☐ pending

### L-06 (policy A) — Roster, pattern, shift changes and approved leave
- **Today:** approved leave is not rewritten; HR reconciles; close is blocked until then.
- **Recommended:** keep (HR reconciles), but give HR the screen (MA-36).
- **Alternatives:** automatic reconciliation for dated changes only; automatic for all.
- **Money/operations:** automatic changes leave balances without a human; keep protects employees from surprises.
- **Implementation:** none if kept (screen only).
- **Owner decision:** ☐ pending

### L-09 — Does accrual clear a shortfall?
- **Today:** only an HR credit does.
- **Recommended:** any credit entry (accrual, carry-forward, comp-off, adjustment) runs the shortfall pass.
- **Alternatives:** HR-only, documented.
- **Implementation:** one call after each credit path in `leave/service.py`.
- **Owner decision:** ☐ pending

---

## 3. Other decisions affecting pay or balances (Group B, not blocking Phase 1)

| ID | Question | Today | Recommended | Consequence | Implication |
|---|---|---|---|---|---|
| H-11 | Half weekly-off with under 240 minutes worked | `ABSENT`, 0.50 pay | Rename status shown; keep pay | none to pay | label only |
| H-16 | No shift on a working day, forgotten checkout | pairs with next day (33 h) | Split over-long pairs as shift days do | prevents one session paying two days | engine |
| H-18 / H-19 / P-10 / P-11 | SPLIT: no lateness; FLEXIBLE: no early departure | as stated | Confirm or define | pay differs by shift type | engine, policy |
| H-20 / P-01 | Overnight shift takes the start date's day type | start date | Confirm; define split at midnight if needed | work after midnight on a holiday | engine, overtime |
| H-22 | Every Nth late day in a calendar month is a half day | as stated | Say "calendar month" on the screen | none | text |
| H-26 / PD-CAL-2 / MA-15 | Holiday on a weekly off | weekly off class | Pay the higher of the two classes | overtime rate | engine, rate rows |
| PD-CAL-1 / H-25 | Optional and restricted holidays | working days | Confirm | leave days charged | calendar |
| O-06 / MA-14 | Roster week-off overtime gross, weekly-off net | not reproduced | **Reproduce first** | minutes of overtime | engine |
| O-12 (P-B) | Half-day or absent by a penalty band pays no overtime | as stated | Confirm | overtime pay | engine |
| O-14 (P-D) | Non-eligible shift earns nothing for work on a day off | as stated | Confirm and show on policy screen | overtime pay | policy UI |
| O-15 | Republish re-prices approved overtime but keeps the old comp-off choice | as stated | Approval = minutes; price and comp-off follow the version in force on the day | pay vs comp-off mix | `_resolve_ot_decision` |
| O-20 / MA-32 | Lock withdrawal frees cap budget | no | Yes, like rejection | later days' overtime | `finalize` |
| L-04 / LV-03 | Cross-year leave debited on start date | as stated | Decide with LV-01..03 | balance by year | leave |
| L-10 / D-07 | ON_DUTY on leave day | leave wins, still charged | Confirm | balance | overlay |
| L-12 | Work in the leave half is a conflict only from half of it | as stated | Confirm | pay | overlay |
| C-10 | Missing policy version at lock treated as `TREAT_ABSENT` | as stated | Keep, but should not occur | loss of pay | none |
| LV-01..03, 05..13 | Year-end, cross-year, accrual, encashment, etc. | **not re-verified** | Re-audit leave first | balances | separate programme |

---

## 4. Defaults implemented without approval — ask in batches

Batch 1 (pay): P-A, P-B, P-C, AC-04 `TREAT_PRESENT`, AC-05 threshold, AR-06, AR-11, AR-12, D-09/AR-14.
Batch 2 (leave): L-02, L-04, L-06, L-07, L-09, L-10, L-12.
Batch 3 (operations): C-02..C-05, C-10..C-17, O-19..O-21.
Batch 4 (unlikely to change but unsigned): H-10, H-12, H-13, H-21, H-27, H-28, O-01..O-05, O-08.

For each batch the owner can answer "keep as built" per row; that is also a decision and gets
recorded. Without a recorded answer the row stays "Default".

---

## 5. Configurable per policy, or a global invariant?

| Per policy (varies by business) | Global product invariant (never configurable) |
|---|---|
| Grace in/out, late and early bands, hour bands, mark ceiling (if it stays configurable), `lates_to_half_day_count`, missing-punch behaviour, lock behaviour, overtime eligibility, caps, rounding, approval chain, comp-off instead of pay, comp-off expiry, break rules, core hours | A locked day is never rewritten by code; policy versions are immutable once published; every timezone-derived date is the company or branch business date; one `attendance_day` per employee-date; paid + LOP + unpaid-off = 1.00 per day; leave ledger and overtime history are append-only; an employee cannot approve their own overtime or regularization; no pay-affecting default hides in code (any threshold the engine applies must be a visible policy value or a documented constant) |

Today's constants that should become visible policy values or explicit invariants:
`MARK_CREDIT_CEILING_MINUTES = 59`, `STRAY_PUNCH_WINDOW_MINUTES = 30`,
`OWNERSHIP_DUPLICATE_WINDOW_SECONDS = 60`, week = Monday–Sunday (O-01),
`MAX_ATTEMPTS = 5` for recalculation, `DEFAULT_COMP_OFF_EXPIRY_DAYS = 60`.

---

## 6. What needs versioning and historical auditability

| Item | Today | Recommendation |
|---|---|---|
| Attendance, overtime, regularization policy versions | Versioned, immutable, effective-dated | Keep. The day row stores the version id |
| Work calendar, holiday list, weekly-off pattern, roster, break overrides | **Not versioned** (V-03). The row stores the calendar id and the resulting day type, not the inputs | Store the **resolved inputs** on the day row (day type, holiday id, pattern rule id, roster id), or version calendars. Needed to explain a past day after an edit |
| Engine | Version stored on each row; raising it recalculates nothing | Keep the stored version, add a recalculation run record (who, when, which dates, before/after) |
| Comp-off credit | Ledger append-only; no link to the version of the record it came from | Reversals as new entries referencing the original |
| Approvals | `overtime_action` and regularization actions are append-only by code, not by grant (MA-18) | Enforce at database level |
| Decisions themselves | Recorded in audit documents | Move the register to a dated, versioned decision log; each rule row cites the decision id; the engine docstring cites it |

---

## 7. Order in which to ask the owner

1. H-02, H-01, H-04, H-03 (they decide whether Phase 1 can start; 1.1 and 1.6 can start earlier).
2. P-05, D-01a/b, H-05, P-04 (policy shape; together, so engine 17 is one change).
3. H-07, H-08, H-29.
4. O-19 / NF-1, L-09, L-06, H-30, C-14, C-16.
5. Batches 1–4 of section 4.

Record each answer under the decision's id with date and approver; the plan's dependency column then unblocks.
