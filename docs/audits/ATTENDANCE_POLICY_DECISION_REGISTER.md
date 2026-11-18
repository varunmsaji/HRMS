# Attendance Policy Decision Register — 16 November 2026

**Written for:** the product owner (decisions), and the engineers who will implement them.
Part of `MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`. Describes the uncommitted working tree
(engine 16).

Every row is a business rule the application applies today. "Approved" means an owner decision is
recorded in an audit document. "Default" means engineers built the audit's recommendation and it
still awaits confirmation. "Hidden" means the code decides and no document records a decision.
Probe ids (G1, IP2 …) refer to `ATTENDANCE_CROSS_MODULE_SCENARIO_MATRIX.md`.

**Revision.** A second, independent pass on the same day re-ran the probes behind this register.
Every row tied to a finding or probe was confirmed against the code; the remaining rows were
spot-checked and none was contradicted. It added H-29, H-30,
O-19 to O-21, L-14, C-14 to C-17, V-06 and V-07, and corrected O-15 (the comp-off choice is not
re-taken on republish).

**Columns:** Changes = what the rule can change: status (S), paid-day or loss-of-pay fraction (P),
leave balance (L), overtime (O). Cfg = configurable per policy today.

---

## 1. Decisions that block a payroll audit

These change pay and have no approved rule. Decide these first.

| ID | Question | What the code does today | Where | Changes | Cfg | Recommended | Decision needed |
|---|---|---|---|---|---|---|---|
| H-01 | What is a day worth when no hour band covers the minutes worked? | `PRESENT`, full pay. Bands may start above 0 or have gaps; publish accepts them (IP1: 30 minutes = full day) | `calculation._resolve_primary_status`; `service._validate_bands` | S, P | No | Refuse such bands at publish; treat "no band" as a configuration error | Confirm. Then list existing published versions with gaps |
| H-02 | Is an employee who never punched "incomplete" or "absent"? | `INCOMPLETE` unless `missing_punch_behaviour = ABSENT`. At lock, `TREAT_PRESENT` pays it in full (IP2); `TREAT_ABSENT` makes it loss of pay; `KEEP_INCOMPLETE` blocks | `_resolve_primary_status`; `_apply_incomplete_lock_resolution` | S, P | Partly | Zero punches on an expected day is absent once the day is over; `TREAT_PRESENT` only where at least one punch exists | Choose; decide whether `TREAT_PRESENT` stays on offer |
| P-05 | Hour bands for short and long shifts | Fixed minutes on the policy. A 4-hour shift worked in full is `HALF_DAY`, 0.50 loss of pay (O20) | `lookup_band` use in `_evaluate_fixed_or_flex` | S, P | Only by a separate policy per shift | Bands as a share of the shift's net minutes, or enforce one policy per shift length | Choose |
| H-03 | When does comp-off become usable, and what happens when the overtime behind it changes? | Credited by the hourly sweep as soon as a record is approved; never reduced or reversed on correction; a re-detected record earns a second credit. Reproduced (IP10): 180 minutes credited 0.38; overtime removed, credit kept; 30 minutes re-detected, 0.06 more; balance 0.44 | `LeaveCompOffService.credit_company` | L | No | Credit follows the record on every sweep; or credit at period close only | Choose |
| H-04 | On a rostered day off, which shift's calendar and policies apply? | None by shift scope: the day has no shift, so a shift-scoped calendar or policy does not resolve and the day is `CONFIG_ERROR` (IP3); a shift-scoped overtime policy gives no overtime | `_scope_candidates`; `evaluate_day` order | S, O | No | The shift on the employee's assignment for that date | Confirm |
| D-01a | Is the late-mark ceiling 59 minutes after shift start, or 59 minutes after grace? | After shift start. With grace 10 a `LATE` mark of 50–59 minutes is a half day; with grace 30, from 30 minutes (G1) | `grace_band_credit_detail` | S, P | No (constant) | Measure beyond grace, so the template text is true; or change the text | Choose. Extends the unconfirmed R-2 |
| D-01b | May a late mark and an early mark together excuse about two hours? | Yes. 59 minutes at each end: 362 minutes worked of 480 is `PRESENT` (G1) | same | S, P | No | One combined ceiling per day | Choose |
| P-04 | Is work before a FIXED shift's start ever counted? | Never. A whole session before the start counts zero minutes: worked 04:30–08:30 on a 09:00 shift is `ABSENT` (IP7c). FLEXIBLE shifts count it | `clamp_pairs_to_start` | S, P, O | No | Count it toward the day (not overtime) when the employee did not also work the shift; needs a rule | Choose |
| H-05 | Does grace also lower the half-day and absent thresholds? | Yes, by up to `grace_in + grace_out`, even when the employee missed hours (H3: 239 minutes is `HALF_DAY` under an "absent under 240" band) | `grace_band_credit_detail` | S, P | Through the grace values only | Credit grace only when the miss at that end is within grace | Choose |
| R-2 | How much may a late or early mark credit? | 59 minutes per end, or the grace if larger | `MARK_CREDIT_CEILING_MINUTES` | S, P | No | — | Still awaiting confirmation (59, none, or per policy) |
| H-06 | Policies with no late/early bands | One minute past grace on a shift whose length equals the full-day band is a half day (G2) | engine | S, P | By adding bands | Warn at publish; offer a one-click "add mark band" | Confirm that existing policies stay as they are |

---

## 2. Hidden rules — attendance status and pay

| ID | Rule in force | Where | Changes | Cfg | Documented | Approved | Recommended | Decision |
|---|---|---|---|---|---|---|---|---|
| H-07 | Half-day leave and no punches: the other half is loss of pay immediately (`LEAVE`, 0.50/0.50), not `INCOMPLETE` (L11) | `_apply_leave_overlay` | S, P | No | Docstring only | No | Treat like any no-show (H-02) | Choose |
| H-08 | Half-day leave on a day that is (now) a day off: 0.50 loss of pay until reconciled (L1–L3, IP8) | `_apply_leave_overlay` | P | No | No | No | Nothing to lose on a day off | Confirm fix |
| H-09 | Work on a paid day off the shift does not operate never changes pay; all minutes are overtime | `_off_day_work_pay`, D-1 | O | No | Yes | Yes (D-1) | — | — |
| H-10 | A day off with only an IN punch stays `NOT_EXPECTED` and paid; the punch is flagged `missing_punch` (O6, O7) | `_resolve_primary_status` | S | No | No | No | Keep; show it for review | Confirm |
| H-11 | Half-day weekly off: the off half is always paid; the worked half is judged by full-day bands; under 240 minutes is 0.50 loss of pay with status `ABSENT` (O10) | `_apply_half_weekly_off` | S, P | No | Yes (PAY-012) | Yes | Rename the status shown | Minor |
| H-12 | Two same-direction punches within 30 minutes: the extra one is dropped silently (earliest IN, latest OUT stand) | `STRAY_PUNCH_WINDOW_MINUTES = 30` | S | No | Code comment | No | Make it a policy value or confirm 30 | Confirm |
| H-13 | Duplicate punches for ownership are folded within 60 seconds, whatever the policy's own duplicate window says | `OWNERSHIP_DUPLICATE_WINDOW_SECONDS = 60` | — | No | Code comment | No | Keep | Confirm |
| H-14 | A punch may belong to a shift from 240 minutes before its start to 720 minutes after its end, when no policy resolves | `DEFAULT_MAX_EARLY/LATE_PUNCH_MINUTES` | S | Yes, on the policy | Yes (P-13) | Yes | — | — |
| H-15 | A lone IN more than `max_early` before the shift is an orphan; it blocks close until regularized or dismissed (T10) | `owner_of` | S | Through the limit | Yes | Yes (P-13) | — | — |
| H-16 | No shift on a working day: hours go through the bands; no lateness, no overtime; a forgotten checkout can pair with the next day's (T8) | `_evaluate_no_schedule`, `_outruns_owner` | S, P | No | P-06 | Yes, except the pairing | Split over-long pairs on no-shift days too | Confirm |
| H-17 | No shift, working day, no punches: `INCOMPLETE` or `ABSENT` by `missing_shift_behaviour` | engine | S, P | Yes | Yes | Yes | — | — |
| H-18 | SPLIT shift: no lateness or early departure; a block counts as worked if any punch pair overlaps it; hours decide the rest (S2, S3) | `_evaluate_split` | S, P | Partly | Yes (P-11) | No | — | P-11 |
| H-19 | FLEXIBLE shift: lateness runs from the end of the start window; early departure is never measured; core-hours breach by policy (F2, F3) | `_evaluate_fixed_or_flex` | S | Partly | Yes (P-10) | No | — | P-10 |
| H-20 | Overnight shift: the start date's day type governs the whole shift (N4) | engine | S, O | No | Yes (P-01) | No | — | P-01 |
| H-21 | Status precedence: not employed > configuration error > full leave > ON_DUTY > half-leave result > day off > incomplete > harshest band verdict | `evaluate_day`, `_apply_overlays` | S, P | No | Partly | Partly | Publish it as the rule | Confirm |
| H-22 | Every Nth late day in a **calendar month** is a half day; any late minute beyond grace counts, including a "mark" (O21) | `lates_to_half_day_count`, `count_flagged_days_in_window` | S, P | Count only | Yes | Yes (D-10) | Say "calendar month" on the screen | Minor |
| H-23 | Early departure that needs approval and has none is forced to the harshest configured early band | `_harshest_band_classification` | S, P | Yes | Yes (WD-32) | Yes | — | — |
| H-24 | A daily-wage employee is paid on a day off only for `PUBLIC` and `SUBSTITUTE` holidays | `_off_day_is_paid` | P | No | Yes (BUS-001) | Yes | — | — |
| H-25 | Optional and restricted holidays are working days unless the calendar flag makes them holidays | `classify_work_calendar_date` | S, L | Per calendar | Yes | No (PD-CAL-1 open) | — | PD-CAL-1 |
| H-26 | A holiday on a weekly off stays a weekly off; no substitute day; overtime at the weekly-off class (O4) | same, `classify_ot_day` | O | No | Yes | No (PD-CAL-2 open) | Pay the higher of the two classes | PD-CAL-2 |
| H-27 | Alternate-week weekly off with no parity set: the cycle-start week is the off week | `_rule_matches` | S | Yes | Code comment | No | Require parity | Confirm |
| H-28 | Two weekly-off rules matching one date: the larger off fraction wins | `evaluate_weekly_off` | S | — | Code comment | No | Keep | Confirm |
| H-29 | Half-day leave plus lateness in the worked half, on a policy with no late bands: the lateness cliff applies to the worked half and costs a quarter day (L7: in 14:11, 0.75 paid, 0.25 loss of pay). With late bands: 1.00 paid (L8) | `_apply_leave_overlay` with the worked-half verdict | S, P | Through bands | No | No | Judge the worked half by hours only, or apply the same mark rules as a full day | Choose |
| H-30 | Deactivating a holiday calendar, work calendar or weekly-off pattern changes nothing: its holidays and off days still apply to every date and to leave counting (MA-28, C1-INACTIVE-HOLIDAY-CAL). Linking an inactive calendar is refused, but deactivating a linked one is allowed | `calendar_overlay` (docstring says `is_active` is deliberately ignored); `HolidayCalendarRepository.list_by_ids`; `calendar_setup._validate_references` | S, P, L | No | Docstring only | No | Either refuse deactivation while linked, or make deactivation take effect from a date | Choose. The screen must say which |

---

## 3. Hidden rules — overtime

| ID | Rule in force | Where | Cfg | Approved | Decision |
|---|---|---|---|---|---|
| O-01 | The overtime week is Monday to Sunday; the month is the calendar month | `_build_calculation_input` | No | No | Confirm, or make the week start configurable |
| O-02 | A `PENDING` record on an earlier day reserves its detected minutes from the weekly and monthly caps | `sum_minutes_counted_for_cap` | No | Default (D-04) | Confirm |
| O-03 | Minutes beyond a cap are dropped. No record says how many were cut (O18) | `detect_overtime` | No | No | Record the capped minutes |
| O-04 | The minimum overtime is tested before rounding; rounding can then reduce it (O19: 59 minutes, minimum 30, round down to 30) | `detect_overtime` | Yes | No | Confirm order |
| O-05 | Night class is one decision per day: any overlap with the night window makes all the day's overtime `NIGHT`; with no night rate row the normal rate is used | `resolve_is_night_ot`, `detect_overtime` | Partly | Partly (ATT-005) | Confirm |
| O-06 | Roster week-off overtime uses gross minutes; calendar weekly-off overtime is net of the shift's breaks (O1, O2) | `_evaluate_no_schedule` | No | Default (D-03) | Choose one |
| O-07 | Roster week-off overtime always waits for a person, even under an `AUTO` chain | `_resolve_ot_decision` | No | Yes (D-03) | — |
| O-08 | Overtime beside an orphan punch always waits for a person | same | No | Default (AR-11) | Confirm |
| O-09 | `approval_chain = AUTO` approves immediately even when `requires_post_approval` is set | same | Yes | Yes (WD-29) | — |
| O-10 | With no manager on the date, a manager-chain record goes to HR | same | No | Yes | — |
| O-11 | P-A: on a half weekly off, overtime starts after the longer half | `_half_day_overtime_basis` | No | Default | Confirm |
| O-12 | P-B: a half-day or absent day by a penalty band pays no overtime (O12); a completed short shift keeps it (AR-12) | `_overtime_forfeited` | No | Default | Confirm |
| O-13 | P-C: a correction reopens a human approval when minutes grow or the class changes, caps it when they shrink; a human rejection reopens only on growth | `_resolve_ot_decision` | No | Default | Confirm |
| O-14 | P-D: under `SHIFT_FLAG` a non-eligible shift earns nothing for work on a day off (O5: a full holiday worked, no overtime, no comp-off, no extra pay) | `detect_overtime` | Yes | No | Confirm and show it on the policy screen |
| O-15 | A policy republish re-prices human-approved minutes at the new version's multiplier and policy version. The comp-off choice is not re-taken: `comp_off_minutes` stays non-zero when it was non-zero, even if the new version pays instead of giving comp-off | `_resolve_ot_decision` (`POLICY_VERSION_CHANGED`, around line 5372) | No | No (noted in R-7) | Decide whether an approval is of the minutes only, or of minutes and price; and which version decides comp-off versus pay |
| O-16 | Overtime is never payable on a full-day leave day or an ON_DUTY day without punches; the earlier decision is kept dormant | `_calculate` (`overtime_not_payable`) | Partly | Yes (BUS-011, D-5) | — |
| O-17 | Comp-off expires 60 days after the day when the policy sets nothing | `DEFAULT_COMP_OFF_EXPIRY_DAYS` | Yes | Yes (decision 13) | — |
| O-18 | One comp-off day equals the shift's scheduled minutes when the policy sets no length | `_comp_off_facts` | Yes | Yes (decision 13) | — |
| O-19 | A record at the manager stage can be decided only by the manager snapshotted when it was first detected. There is no reassignment and no HR override. If that manager leaves, the record stays `PENDING` and `PENDING_OVERTIME_APPROVAL` blocks close until HR changes the policy's approval chain and the day is recalculated (MA-34). Leave has a reassignment path (`test_leave_reassign_approver.py`) | `OvertimeRecordService._get_reviewable`; `_resolve_ot_decision` keeps `resolved_approver_manager_id` | No | No | Choose: HR may act at any stage, or reassign like leave |
| O-20 | Overtime withdrawn at period lock (the day resolved absent) does not hand its cap budget to later days of the week or month, unlike a human rejection (R-5) (MA-32) | `finalize` order; `_apply_incomplete_lock_resolution` | No | No | Confirm whether lock withdrawal should reallocate |
| O-21 | Every recalculation of a day with a `PENDING` record rewrites it, raises its version, and adds a `DETECTED` action and an `OVERTIME_DETECTED` audit entry, even when nothing changed (MA-33) | `_sync_overtime_record`; `OvertimeRecordRepository.replace_for_day` | No | No | Rewrite only when a value changed |

---

## 4. Hidden rules — leave

| ID | Rule in force | Where | Approved | Decision |
|---|---|---|---|---|
| L-01 | A day's leave share comes from the calendar; a published roster outranks it; a shift that operates on the off day makes it chargeable | `_working_shares` | Yes (F7, SH-03) | — |
| L-02 | Half-day leave exists only for single-day applications | `_compute_day_breakdown` | Not recorded | Confirm |
| L-03 | Sandwich rule: off days between two leave days inside one application are charged as full days; bridges across applications of the same type are added | `_compute_day_breakdown`, `_cross_application_bridges` | Yes (LD-06, R-02) | — |
| L-04 | The whole application is debited on its start date, including days in the next leave year (LV-03) | `_apply_approval` | No | LV-03 |
| L-05 | Holiday added inside approved leave: refund. Holiday removed: debit, or a shortfall exception; never automatic loss of pay | `leave/reconciliation.py` | Yes (P-E) | — |
| L-06 | Pattern, work-calendar, validity, roster and shift changes do not rewrite approved leave; HR reconciles | `request_calendar_recalc` | Open ("policy A") | Decide: automatic, or HR only |
| L-07 | A released loss-of-pay day that comes back is restored as a normal debit | reconciliation | Documented | Confirm |
| L-08 | A leave released completely before the R-1 fix restores as a full day (its half is unknown) | `_application_discrepancies` fallback | Documented | Accept |
| L-09 | A shortfall is cleared by an HR credit, not by accrual (MA-11) | `create_adjustment` | No | Choose |
| L-10 | ON_DUTY on a leave day: full leave wins and is still charged; half leave plus ON_DUTY pays the day and still charges the leave (L16, L17) | overlays | No (D-07) | D-07 |
| L-11 | Punches on a full leave day never change pay; HR must cancel the leave or confirm it | `_apply_leave_overlay` | Yes (BUS-012) | — |
| L-12 | Work in the leave half is a conflict only from half of that half; less is silently not credited | `_work_in_leave_half` | Default (AR-07) | Confirm |
| L-13 | `work_on_leave_behaviour` is stored and shown on mobile and has no effect | — | — | Remove the field |
| L-14 | A balance shortfall stays open after its leave is cancelled or withdrawn. It still blocks close; the reconciliation preview shows nothing to apply. It closes only on an HR credit for that employee or a calendar edit (MA-27, C1-SHORTFALL-CANCEL) | `leave/reconciliation.py` (`list_open_shortfalls` has no application-status filter; `_close_obsolete_shortfalls` runs only inside `reconcile`); `LeaveApplicationService.cancel` | No | Defect, not a choice: cancelling must close the shortfall |

LV-01 to LV-13 (year end, cross-year leave, same half booked twice, comp-off expiry, accrual in
probation, missed accrual, on-behalf switches, leavers' accrual, encashment dating, dormant
settings, deactivated leave type) are unchanged from `LEAVE_MANAGEMENT_AUDIT_2026-11-16.md`
section 7, except LV-04, which is built.

---

## 5. Hidden rules — recalculation and period close

| ID | Rule in force | Where | Approved | Decision |
|---|---|---|---|---|
| C-01 | The queue repairs existing rows only; it never creates a row | `recalc.py` | Documented | — |
| C-02 | A request that fails five times is closed and logged | `MAX_ATTEMPTS` | No | Surface it |
| C-03 | A schedule change recalculates its own date only (MA-07) | `_queue_recalc` | No | Fix |
| C-04 | Pay-basis and legal-entity edits queue nothing (MA-10) | `update_employment` | Comment only | Fix |
| C-05 | A punch is accepted unless its local date and the day before are both closed; a punch owned by a locked day is ignored (MA-06) | `_ensure_punch_date_open` | Yes (DEC-TZ-05) for acceptance; the silence is not | Report such punches |
| C-06 | Finalize recalculates every unlocked day of the period, oldest first, without the per-day cascade | `recalculate_days_for_close` | Yes (R-09) | — |
| C-07 | Days of the same week in the next period are not recalculated at this period's close | same | Documented | Accept |
| C-08 | Reopen unlocks and recalculates nothing; the next finalize recalculates | `reopen` | Yes | — |
| C-09 | A period with finalized payroll never reopens | `reopen` | Yes (decision 15) | — |
| C-10 | A missing policy version at lock is treated as `TREAT_ABSENT` | `_apply_incomplete_lock_resolution` | No | Confirm (it should not occur) |
| C-11 | Termination or joining dated inside a closed period is accepted; locked days stay (MA-21) | `employee/service.py` | No | Refuse, or require a reopen |
| C-12 | An excess-break exception awaiting approval does not block close (MA-23) | `_run_validation` | No | Choose |
| C-13 | A future date may be calculated on request (MA-17) | `_calculate` | No | Refuse future dates |
| C-14 | An approved regularization cannot be revoked. A mistaken approval is corrected only by a second regularization | regularization service (no revoke endpoint) | No | Choose: revoke while the period is open, or accept |
| C-15 | A regularization may add punches up to one day either side of its date, but approval recalculates only its own date (MA-29) | `RegularizationRequestService.submit` (±1 day), approve (around line 6612) | No | Recalculate both dates (defect once ±1 day is accepted as a rule) |
| C-16 | More than one approved ON_DUTY (or early-departure approval) for one date is not refused at submit; approving the second fails with HTTP 500 (MA-31) | `get_approved_for_date_and_type` uses `scalar_one_or_none`; unique index covers `SUBMITTED` only | No | Choose: one per date (refuse at submit), or allow part-day requests |
| C-17 | Break-correction recalculation is best effort: a failure is logged and nothing is queued, unlike a punch, which leaves a durable request | `BreakService._recalculate` | No | Queue a request on failure, as punches do |

---

## 6. Versioning and precedence

| ID | Rule in force | Note |
|---|---|---|
| V-01 | Most specific assignment wins: employee, shift, designation, grade, department, branch, legal entity, company. No assignment at all: configuration error, never a default policy | Verified by reading; consistent for calendar, weekly off, attendance, overtime, regularization, leave policy |
| V-02 | A policy version applies from its `effective_from`; published versions cannot overlap (database constraint); publishing queues recalculation from that date | Verified |
| V-03 | Work calendars, holiday lists, weekly-off patterns, rosters and break overrides are not versioned. The day row stores the calendar id and the resulting day type, not the inputs | A past result cannot be re-derived after an edit; it can only be read from the stored row |
| V-04 | Timezone: shift version, else branch, else company. Only allow-listed zones (`Asia/Kolkata` in production) | Verified |
| V-05 | The engine version is stored on each row; raising it recalculates nothing | AR-17 |
| V-06 | A `READY` result from `validate` is not invalidated by later changes; `finalize` re-validates on freshly recalculated rows, so the close itself is safe | Decide whether the screen should warn that a validation is stale |
| V-07 | `is_active` on holiday calendars, work calendars and weekly-off patterns is ignored when resolving a date (H-30) | Decision H-30 |

---

## 7. Fields accepted and stored that the engine does not use

`work_on_leave_behaviour`, `punch_rounding` / `rounding_minutes`, `half_day_split` /
`half_day_boundary_minutes`, `early_out_uses_core_end`, `missing_punch_behaviour = AUTO_CLOSE`
(closes nothing; engine H8, H9) and `REQUIRE_REGULARIZATION` (same as `INCOMPLETE`). The shift
remediation made the API refuse non-default values for most of these (SH-14); existing rows may
still hold them. `work_on_leave_behaviour` is still accepted (AR-15).

---

## 8. Earlier decisions and their state

| ID | State |
|---|---|
| D-01, D-02, D-03, D-04, P-E | Approved 16 Nov 2026 and built. Choices inside them still to confirm: 1–59 template band, 100/50/0 % steps for the worked half, gross minutes on roster week-off, pending reserves budget, plus D-01a and D-01b above |
| P-A, P-B, P-C, AC-04 (`TREAT_PRESENT`), AC-05 / AR-07 threshold, AR-06 flexible, AR-11, AR-12, D-09 / AR-14, LV-04 | Built as defaults; awaiting confirmation |
| R-2, R-3 / "policy A" | Built as defaults; awaiting confirmation |
| P-01, P-04, P-05, P-10, P-11, P-12, P-14, P-D, D-07, PD-CAL-1, PD-CAL-2, LV-01…LV-13 except LV-04 | Not decided |
| P-02, P-06, P-13, D-1, BUS-001/002/003/011/012 | Decided and built |
