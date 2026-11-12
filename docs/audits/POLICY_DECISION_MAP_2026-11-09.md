# Attendance, Leave, Shift, Overtime & Payroll — Policy Decision Map

**Date:** 9 Nov 2026 · **Branch read:** `test` (8 local commits ahead of `origin/test`) · **Mode:** read-only discovery. No code, schema, policy or configuration was changed.

**How this was produced.** Every rule below was read from the code at the location given, not taken from earlier documents. Earlier documents (`PAYROLL_BUSINESS_DECISIONS.md`, `MASTER_POLICY_DECISION_REGISTER.md` of Sep 2026, `RULES_FIX_HANDOFF.md`, the settings guide) were used only to label a rule as *signed off* and to find conflicts. Boundary behaviour was worked out by tracing the code by hand. **No tests were run and nothing was executed against a database**, so every boundary result in section G should be confirmed with a unit test before anyone relies on it.

**Main engine files** (line numbers as of this date):

| Area | File |
|---|---|
| Day calculation (pure) | `apps/api/src/hrms/modules/attendance/calculation.py` (`ENGINE_VERSION = 10`) |
| Day inputs, OT records, regularisation, periods, lock | `apps/api/src/hrms/modules/attendance/service.py` |
| Punch acceptance window | `apps/api/src/hrms/modules/attendance/shift_window.py` |
| Calendar day type, scope precedence | `apps/api/src/hrms/modules/organisation/calendar_resolution.py` |
| Leave rules, accrual, year end, comp-off | `apps/api/src/hrms/modules/leave/service.py`, `leave/year.py` |
| Pay computation (pure) | `apps/api/src/hrms/modules/payroll/engine.py` |
| Pay run inputs, arrears, adjustments | `apps/api/src/hrms/modules/payroll/service.py` |
| Settings / env | `apps/api/src/hrms/core/config/settings.py` |
| Scheduled jobs | `apps/api/src/hrms/core/celery_app.py` |
| Web templates and forms | `apps/web/src/lib/*/templates.ts`, `apps/web/src/components/*-policy/` |
| Mobile policy editor | `apps/mobile/lib/features/attendance/domain/policy_resources.dart`, `attendance_setup_configs.dart` |

## Legend

**Basis** (where the rule comes from):
- **SIGNED** — a signed-off owner decision exists and the code matches it (reference given).
- **CONFIG** — an admin sets it per policy version; the code default is noted.
- **IMPLICIT** — decided only by code; no signed decision found. *Needs owner confirmation.*
- **DORMANT** — a stored setting that has **no effect** on any calculation.
- **CONFLICT** — two parts of the system disagree (see section D).

**Status:** ✅ settled · ⚠️ needs confirmation · ⛔ **BLOCKING** (must be decided before payroll relies on it).

**Payroll impact:** 💰 direct (changes paid days, OT pay or net pay) · ◐ indirect (changes status or a counter that later changes pay) · — none.

---

# A. Master Policy Decision Register

## A1. Punches and presence

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| ATT-01 | Which clock decides a punch's time | Self-service punches use the server clock; HR "on behalf" punches carry a supplied time that is validated, not trusted | `service.py` `record_punch` (DEC-TZ-01) | No | SIGNED (DEC-TZ-01) | ◐ | ✅ |
| ATT-02 | Which day a punch belongs to | Punches are **not** assigned to a date. Each day loads every punch inside a time window: FIXED = shift ±2 h, SPLIT = first block −2 h to last block +2 h, FLEXIBLE = start window −2 h to window end **+12 h**, no shift = local midnight to midnight | `calculation.py` `resolve_schedule_window`, `punch_window_utc` (`lookback_hours=2`, `lookahead_hours=2`) | No (hardcoded) | IMPLICIT | 💰 | ⛔ see C-01 |
| ATT-03 | Longest post-shift stay that can be recorded | On a FIXED shift an OUT punch 2 h or more after shift end is **outside the window and not loaded**. The IN becomes an orphan and the day goes INCOMPLETE (unpaid, then LOP at lock). 09:00–18:00 shift: OUT at 19:59 counts, OUT at 20:00 does not | `punch_window_utc`; repository query uses `< window_end` | No | IMPLICIT | 💰 | ⛔ C-01 |
| ATT-04 | Same punch counted on two days | Windows of consecutive days can overlap (night shift D loads to 08:00 D+1; a 06:00 shift on D+1 loads from 04:00). A punch in the overlap is evaluated on both days | same | No | IMPLICIT | 💰 | ⛔ C-01 |
| ATT-05 | Early punch-in limit | A self-service IN earlier than `early_in_allowance_minutes` before shift start is refused (`TOO_EARLY`). NULL = no limit. Overnight shifts check yesterday's shift too. HR punches are never checked | `shift_window.py` `evaluate_shift_window` | Yes, default NULL | CONFIG | — | ✅ |
| ATT-06 | Is time before shift start credited | **No** (FIXED shifts on working days). Credited presence is clamped to scheduled start; the real punch time is still stored and shown | `calculation.py` `clamp_pairs_to_start` | No | IMPLICIT (engine comment calls it a design rule) | 💰 | ⚠️ |
| ATT-07 | Is time after shift end credited | **Yes**, in full (until the 2 h load limit, ATT-03) | `evaluate_presence_and_breaks` | No | IMPLICIT | 💰 | ⚠️ |
| ATT-08 | Minimum gap between self-service punches | 120 s; a punch sooner is refused (`PunchTooSoonError`) | `settings.attendance_punch_min_gap_seconds` | Env only | IMPLICIT | — | ⚠️ |
| ATT-09 | Same direction twice in a row (self-service) | Refused if the previous punch in the last **18 h** has the same direction. A night worker who forgot to punch out at 06:00 cannot punch in at 22:00 (16 h later) | `settings.attendance_punch_order_lookback_hours=18`, `attendance_punch_order_check_enabled=True`; `_ensure_punch_sequence_and_gap` | Env only | IMPLICIT | ◐ | ⚠️ |
| ATT-10 | Duplicate punches | Same-direction punches within `duplicate_punch_window_seconds` (default 60) of the previous kept punch are dropped | `collapse_duplicate_punches` | Yes, default 60 | CONFIG | ◐ | ✅ |
| ATT-11 | Stray same-direction punches | A second same-direction punch within **30 min** is a stray: earliest IN / latest OUT is kept. Further apart, the day stays INCOMPLETE | `STRAY_PUNCH_WINDOW_MINUTES = 30` | No | IMPLICIT (engine v8) | ◐ | ⚠️ |
| ATT-12 | Pairing | IN then OUT. Two INs: the earlier is an orphan. OUT with no IN: orphan. OUT and IN at the same instant: OUT first | `pair_punches`, `punches_in_order` | No | IMPLICIT (engine v10) | ◐ | ✅ |
| ATT-13 | Multiple IN/OUT pairs | `PAIR_ALL` (default): sum of pairs; gaps are candidate breaks. `FIRST_IN_LAST_OUT`: whole span, unpaid gaps subtracted | `presence_span`, `worked_minutes_from_gross` | Yes | CONFIG | 💰 | ✅ |
| ATT-14 | Seconds and minute truncation | Every interval is floored to whole minutes. Under `PAIR_ALL` each pair is floored separately, so several short pairs can lose up to a minute each | `presence_span` (`// 60`) | No | IMPLICIT | 💰 (small) | ⚠️ |
| ATT-15 | Punch rounding | `punch_rounding` / `rounding_minutes` are stored and passed to the engine but **never applied**. `apply_rounding` is never called | `calculation.py` `apply_rounding` (unused) | Shown on mobile only | DORMANT · CONFLICT D-03 | — | ⛔ C-07 |
| ATT-16 | Missing punch (open IN, or no punches on a working day) | Default `INCOMPLETE` (0 paid, 0 LOP, resolved at lock). `ABSENT` = LOP immediately. `REQUIRE_REGULARIZATION` behaves exactly like INCOMPLETE. `AUTO_CLOSE` does **not** close anything: the orphan is ignored and the day is judged on its other pairs; `auto_close_after_minutes` and `auto_close_uses_shift_end` are unused | `_resolve_primary_status` | Yes | CONFIG; AUTO_CLOSE is DORMANT | 💰 | ⛔ C-07 |
| ATT-17 | Day with no shift resolved | No punches: `missing_shift_behaviour` (INCOMPLETE default, or ABSENT). With punches: **any worked minute = PRESENT, full day paid**; no late, early, bands or OT | `_evaluate_no_schedule` | Partly | IMPLICIT | 💰 | ⛔ C-08 |
| ATT-18 | Hour bands (worked minutes → day result) | First matching band wins, bounds inclusive. **Worked minutes in a gap between bands, or with no matching band, count as PRESENT** | `lookup_band`, `_resolve_primary_status` | Yes (≥1 band to publish) | IMPLICIT fallback | 💰 | ⚠️ C-09 |
| ATT-19 | Template hour bands | Standard: <240 ABSENT, 240–479 HALF_DAY, ≥480 PRESENT. Flexible template: same at 360 | `web/src/lib/attendance-policy/templates.ts`; mobile mirror | Template | CONFIG | 💰 | ⚠️ |
| ATT-20 | Which outcome wins | ABSENT (late/early/core band) > HALF_DAY (late/early/core band, cumulative counter) > hour band. An unresolved break forces INCOMPLETE | `_resolve_primary_status` | No | IMPLICIT, documented in engine | 💰 | ✅ |
| ATT-21 | Paid/LOP split per status | PRESENT 1/0 · HALF_DAY 0.5/0.5 · ABSENT 0/1 · NOT_EXPECTED 1/0 · INCOMPLETE and CONFIG_ERROR 0/0 | `_paid_lop_fraction` | No | SIGNED (PAY-002/003) | 💰 | ✅ |
| ATT-22 | Half-day "split" setting | `half_day_split` and `half_day_boundary_minutes` are stored but unused. Half-day leave always splits at the shift midpoint, moved to a fixed break if the midpoint falls inside one | `_half_day_split` | Shown on mobile | DORMANT | ◐ | ⛔ C-07 |
| ATT-23 | Work-from-home | `wfh_requires_punch`, `wfh_uses_shift_hours` unused. A WFH regularisation only adds punches; there is no WFH status | engine; `_apply_correction` | Shown on mobile | DORMANT | ◐ | ⚠️ |

## A2. Breaks

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| BRK-01 | Legacy breaks (no mode) | Only punched gaps are matched. **A gap matching no configured break is unpaid** | `match_breaks` | No | IMPLICIT | 💰 | ⚠️ |
| BRK-02 | Break modes (V1) | MANDATORY_PUNCH, OPTIONAL_PUNCH, AUTO_DEDUCT; recorded START/END events; a recorded break replaces that rule's scheduled deduction; no minute is deducted twice | `compute_breaks` | Yes | CONFIG | 💰 | ✅ |
| BRK-03 | Mandatory break not recorded | Only noted in the snapshot (`mandatory_not_recorded`); **nothing is deducted** | `compute_breaks` | No | IMPLICIT | 💰 | ⚠️ |
| BRK-04 | Open break START | Nothing after it is credited; the day is INCOMPLETE until corrected | `credit_cutoff_for`, `clip_pairs_at` | No | IMPLICIT | 💰 | ✅ |
| BRK-05 | Excess break | Per-break `excess_outcome`, else policy `excess_break_behaviour` (FLAG default). Paid-break excess is deducted only under DEDUCT, never when approved | `compute_breaks` | Yes | CONFIG | 💰 | ✅ |
| BRK-06 | Do breaks reduce the OT threshold | **V1 unpaid breaks reduce the scheduled minutes OT is measured against; legacy breaks do not.** Same 1 h unpaid lunch on 09:00–18:00: V1 → OT after 8 h worked; legacy → OT after 9 h worked | `scheduled_unpaid_break_minutes` (skips `mode is None`) | No | IMPLICIT · CONFLICT D-10 | 💰 | ⛔ C-05 |
| BRK-07 | Shift-level `break_minutes_paid/unpaid`, `grace_in/out_minutes` on `Shift` | Always written as 0, never read | `organisation/service.py` ~2185 | No | DORMANT | — | ⚠️ (cleanup) |

## A3. Shifts, schedules and day ownership

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| SHF-01 | Shift types | FIXED, FLEXIBLE (start window + required minutes + optional core hours), SPLIT (duty blocks) | `ShiftVersion` | Yes | CONFIG | ◐ | ✅ |
| SHF-02 | Which shift applies on a date | Published roster row > employee assignment's shift. Draft roster rows are ignored | `_build_calculation_input` | Yes | SIGNED (WD-27) | ◐ | ✅ |
| SHF-03 | Which date owns an overnight shift | The shift's **start** date. An end time earlier than the start rolls to the next day even when `is_cross_midnight` is false | `scheduled_span_utc` | No | IMPLICIT (FR-ATT-005) | ◐ | ✅ |
| SHF-04 | Timezone | Shift version > branch > company. Only `Asia/Kolkata` is allowed (`allowed_company_timezones`) | `resolve_timezone`; settings | Env | SIGNED (ADR-0010) | ◐ | ✅ |
| SHF-05 | Two shifts on one date / intra-day shift change | Not supported — one schedule per employee-date | engine | No | IMPLICIT (PD-SHIFT-1 open since Sep) | ◐ | ⚠️ |
| SHF-06 | Unassigned employee | See ATT-17 | | | | 💰 | ⛔ C-08 |
| SHF-07 | Shift working on holidays / weekly offs | `operates_on_holiday` / `operates_on_weekly_off` (default false). If true, the off day is judged as a working day | `_shift_operates` | Yes | CONFIG | 💰 | ⚠️ C-04 |
| SHF-08 | SHIFT-scoped policy and calendar resolution | Uses the **assignment's** shift, not the rostered shift of the day. A roster swap to a night shift keeps the day-shift's SHIFT-scoped policy | `calendar_resolution.py` `_scope_candidates` | No | IMPLICIT (PD-XMOD-002 open since Sep) | 💰 | ⛔ C-10 |
| SHF-09 | Flexible shift lateness | Late counts from the **end** of the start window (+grace) | `_evaluate_fixed_or_flex` | No | SIGNED (engine v4) | ◐ | ✅ |
| SHF-10 | Flexible shift early departure | Measured against the end of the **start window**, not the end of the working day. Someone on an 08:00–11:00 window who leaves at 12:00 is never "early"; only hour bands catch the short day. `early_out_uses_core_end` is unused | same; DORMANT field | Partly | IMPLICIT · DORMANT | ◐ | ⛔ C-11 |
| SHF-11 | Split shift late/early | Never computed for SPLIT. A missed block → `split_shift_missed_block_behaviour` (HALF_DAY default). A partly worked block counts as fully worked. `split_shift_block_mandatory`, `split_shift_allow_hours_compensation` unused | `_evaluate_split` | Partly | IMPLICIT · DORMANT | 💰 | ⚠️ |
| SHF-12 | Shift effective dating / later change | Shift versions are effective-dated; a backdated change does not recalculate days until the trailing sweep (3 days) or period finalise | `tasks.py` `TRAILING_DAYS=3`; R-09 | No | SIGNED (R-09) | 💰 | ✅ |
| SHF-13 | Shift swaps | Implemented as roster rows; no separate swap rule in the calculation | roster | — | IMPLICIT | ◐ | ✅ |

## A4. Grace

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| GRC-01 | Is grace a threshold or forgiven minutes | **Forgiven minutes**: `late = raw − grace`. 10 min grace, arrival 09:25 → 15 min late, not 25. Late bands are therefore read on post-grace minutes | `_evaluate_fixed_or_flex` | Yes | CONFIG (guide matches) | ◐ | ✅ |
| GRC-02 | Grace boundary | Whole minutes, seconds floored. Grace 10: 09:10:59 → on time; 09:11:00 → 1 min late | same (`// 60`) | No | IMPLICIT | ◐ | ⚠️ |
| GRC-03 | Daily or monthly grace | Daily only. No monthly grace bank, no accumulation | — | No | IMPLICIT | ◐ | ⚠️ C-12 |
| GRC-04 | Grace per shift or per policy | Per attendance policy version (shift-level grace fields are dormant, BRK-07) | engine | Yes | IMPLICIT | ◐ | ✅ |
| GRC-05 | **Does grace protect the hour bands** | **No.** Grace removes the "late" mark only; the minutes missed still reduce worked time. Standard template + 09:00–18:00 shift + 1 h punched lunch: on time = 480 = PRESENT; **09:01 arrival (inside grace) = 479 = HALF_DAY** | GRC-01 + ATT-06 + ATT-19 | No | IMPLICIT · CONFLICT D-08 | 💰 | ⛔ C-02 |
| GRC-06 | Early-departure grace | Same model as late: `early = raw − grace_out` | same | Yes | CONFIG | ◐ | ✅ |
| GRC-07 | Grace and overtime | Independent. OT is total worked minus scheduled, so lateness inside grace delays OT minute for minute | `detect_overtime` | No | SIGNED (R-16, owner 6 Nov) | 💰 | ✅ |
| GRC-08 | Grace converting into a deduction | Only through the cumulative counter: every Nth late day (after grace) in a calendar month is HALF_DAY (`lates_to_half_day_count`). No per-minute deduction exists | `cumulative_status_override` | Yes | CONFIG | 💰 | ✅ |

## A5. Leave

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| LV-01 | Paid or unpaid | Per leave **type** (`is_paid_default`, default true). Not overridable per policy. Days approved beyond balance are unpaid (LOP) | `_resolve_backing_leave_day` | Yes (type) | SIGNED (PAY-010) | 💰 | ✅ |
| LV-02 | Balance-backed or not | `requires_balance` (default true). LOP-style types skip the balance check | `submit` | Yes | SIGNED (LD-02) | 💰 | ✅ |
| LV-03 | Which days consume leave | Working day 1.00; half-day weekly off 0.50; weekly off, holiday, shutdown 0. Roster overrides the calendar both ways. **The shift's `operates_on_weekly_off` / `operates_on_holiday` is not consulted** | `_compute_day_breakdown` | No | IMPLICIT · CONFLICT D-05 | 💰 | ⛔ C-04 |
| LV-04 | Sandwich rule | Default **on** for new policies (sick template turns it off). Off days between two consuming days of the **same application** count as full leave days. Holidays are sandwiched, not only weekends. No look across separate applications | `_compute_day_breakdown`; `sandwich_rule_enabled=True` | Yes | SIGNED (LD-06 d5); cross-application = owner decision R-02, not built | 💰 | ⚠️ |
| LV-05 | Sandwich on unpaid leave | A sandwiched weekend inside an unpaid-leave application becomes unpaid (LOP) | LV-01 + LV-04 | No | IMPLICIT | 💰 | ⛔ C-13 |
| LV-06 | Half-day leave | Allowed by default; only on a single-date application; FIRST_HALF/SECOND_HALF. No hourly leave | `_compute_day_breakdown` | Yes | CONFIG | 💰 | ✅ |
| LV-07 | Half-day leave + worked half | Worked half judged alone: late/early on that half; hour bands read **double** the worked minutes. PRESENT → HALF_DAY paid; HALF_DAY/ABSENT outcome → the worked half is LOP | `_apply_leave_overlay`, `_half_day_leave_half` | No | SIGNED (engine v5/v7) | 💰 | ✅ |
| LV-08 | Work on a full-day leave day | Leave wins: paid once as leave, OT zeroed, day flagged; period cannot close until HR cancels the leave or confirms it. `work_on_leave_behaviour` no longer changes anything | `_apply_leave_overlay` | No (field DORMANT) | SIGNED (BUS-011/012) | 💰 | ✅ (field still on mobile, D-03) |
| LV-09 | Negative balance | Off by default; allowed down to `negative_balance_floor`. No recovery at exit exists (no F&F module) | `_negative_floor` | Yes | SIGNED (BUS-005) except recovery | 💰 | ⛔ C-14 |
| LV-10 | Approval beyond balance | Re-checked under lock at final approval; approver may approve with excess as LOP. The **latest** days become LOP, whole days only | `_cover_from_balance` | No | SIGNED (BUS-006) | 💰 | ✅ |
| LV-11 | Monthly accrual timing | Credited after the month ends (effective the last day of the month), in the first 5 local days of the next month; catches up 3 months | `run_due_months`; `leave_accrual_run_window_days=5`; `ACCRUAL_CATCH_UP_MONTHS=3` | Env | IMPLICIT | 💰 | ⚠️ |
| LV-12 | Accrual proration (join/exit) | Rate × employed calendar days ÷ days in month, rounded half-up to 0.01 | `_prorate_accrual_days` | No | IMPLICIT | 💰 | ⚠️ |
| LV-13 | LOP days and accrual | LOP does **not** reduce accrual | `_accrue_employee_month` | No | SIGNED (decision 20) | 💰 | ✅ |
| LV-14 | Probation and monthly accrual | `accrue_during_probation=false`: a month in which the employee is still PROBATION at run time earns nothing and is never back-credited; the month of confirmation earns for days after `probation_end_date` | same | Yes | SIGNED (R-11) | 💰 | ✅ |
| LV-15 | Yearly accrual | Full rate credited on the leave-year start date. **No proration; a mid-year joiner gets nothing until the next year start. Probation is not checked** | `_year_end_for_employee` | No | IMPLICIT · CONFLICT D-11 | 💰 | ⛔ C-15 |
| LV-16 | Leave year | CALENDAR (1 Jan), FINANCIAL (1 Apr), ANNIVERSARY (joining date), CUSTOM. Feb 29 anchors clamp to Feb 28 | `leave/year.py` | Yes | SIGNED (LD-20) | 💰 | ✅ |
| LV-17 | Year end | LAPSE / CARRY_FORWARD (cap; no cap = keep all) / ENCASH_EXCESS (cap carried, excess encashed up to `max_encashment_days`, rest lapses). Negative balances untouched | `_year_end_split` | Yes | SIGNED (decision 11) | 💰 | ✅ |
| LV-18 | Encashment rate | Basic ÷ days in month per day (daily-wage: daily rate). Paid in the month of the ledger entry's date | `engine.py`; `list_encashments_between` | No | SIGNED (D4) | 💰 | ✅ |
| LV-19 | Leave application limits | Max 30 calendar days per application by default (`max_consecutive_days`), max 90 for any request (`MAX_LEAVE_REQUEST_DAYS`); backdating, monthly count, reason, attachment per policy | `submit` | Yes | CONFIG | — | ✅ |
| LV-20 | Leave during probation | Allowed unless the policy turns it off | `allowed_during_probation=True` | Yes | SIGNED (LD-18) | ◐ | ✅ |
| LV-21 | Cancellation | Pending: submitter/employee any time. Approved: employee before start; after start HR only with reason. Never inside a closed period | `cancel` | No | SIGNED (BUS-004, PD-3) | 💰 | ✅ |
| LV-22 | Leave and a closed attendance period | Submit, approve and cancel are all refused for dates in a closed period of the employee's legal entity | `_ensure_period_open` | No | SIGNED (PD-3) | 💰 | ✅ |
| LV-23 | Exit with leave after last working day | Termination is refused until that leave is cancelled; nothing is auto-cancelled | `_assert_no_leave_after` | No | IMPLICIT | ◐ | ✅ |
| LV-24 | Notice period | `Grade.notice_period_days` is informational; no leave or pay rule reads it | `organisation/models.py` | — | DORMANT | — | ⚠️ |
| LV-25 | Optional / restricted holidays | Treated as WORKING (unless the work calendar flag says off); the employee applies an ordinary leave. **The signed "annual cap, default 2" is not built** | `classify_work_calendar_date` | Partly | CONFLICT D-12 (BUS-009) | 💰 | ⚠️ |
| LV-26 | Same-type overlap | One type on one date cannot exceed 1.00 day; different types governed by combination rules (no rule = allowed) | `submit` | Yes | SIGNED (PRA-15, LD-16) | — | ✅ |
| LV-27 | Holiday added after leave approved | **Never rewrites the leave.** The day stays leave and the balance stays debited | `calendar_impact.py` docstring | No | IMPLICIT | 💰 | ⛔ C-16 |
| LV-28 | Cancelling into a closed leave year | Re-applies that year's rule: over-cap days lapse; ENCASH_EXCESS encashes now | `_apply_closed_year_rule` | No | SIGNED (R-12) | 💰 | ✅ |

## A6. Holidays, weekly offs, calendar

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| HOL-01 | Day-type precedence | Calendar exception > holiday > weekly off > WORKING. No calendar = CONFIG_ERROR (blocks finalise) | `classify_work_calendar_date` | Yes | SIGNED (WD-21) | 💰 | ✅ |
| HOL-02 | Are holidays / weekly offs paid | MONTHLY: all paid unless the holiday is marked unpaid. DAILY_WAGE: only PUBLIC and SUBSTITUTE holidays paid | `_off_day_is_paid` | Partly | SIGNED (BUS-001) | 💰 | ✅ |
| HOL-03 | Holiday on a weekly off | Stays WEEKLY_OFF with a flag; no auto-substitute | same | No | SIGNED (BUS-010) | 💰 | ✅ |
| HOL-04 | Weekly-off patterns | Fixed weekday, nth weekday (−1 = last), alternate (parity from a cycle start; default EVEN = start week off), custom. Overlapping rules: largest off share wins | `_rule_matches`, `evaluate_weekly_off` | Yes | IMPLICIT defaults | 💰 | ⚠️ |
| HOL-05 | Half-day weekly off | Off half always paid (unpaid for daily wage); working half paid only if worked | `_apply_half_weekly_off` | Yes | SIGNED (BUS-003) | 💰 | ✅ |
| HOL-06 | Working on a non-operating off day | Status PRESENT; never late/early/LOP; **every worked minute is OT** (if OT-eligible); monthly-paid keep the paid off day as well | `_off_day_overtime_basis`, `_off_day_work_pay` | No | SIGNED (D-1, engine v6/v7) | 💰 | ✅ |
| HOL-07 | Daily-wage off-day work | Paid as OT if it earns OT; otherwise hour bands decide how much of the day's wage is paid | `_off_day_work_pay` | No | IMPLICIT | 💰 | ⚠️ |
| HOL-08 | Holiday work special pay | Only through the OT HOLIDAY rate row. No separate holiday allowance or double-day pay | engine, payroll | Yes | IMPLICIT | 💰 | ⚠️ |
| HOL-09 | Comp-off for holiday work | Only if the OT policy has `comp_off_instead_of_pay`; then **all** OT under that policy becomes comp-off, not just holiday OT | `evaluate_*` | Yes | IMPLICIT | 💰 | ⚠️ C-17 |
| HOL-10 | Holiday on a weekly off, worked | OT is classed WEEKLY_OFF, not HOLIDAY (day type stays WEEKLY_OFF) | `classify_ot_day` | No | IMPLICIT | 💰 | ⚠️ |
| HOL-11 | Regional / employee-specific holidays | Via work calendars assigned at any of 8 scopes (employee > shift > designation > grade > department > branch > legal entity > company) | `_PRECEDENCE_SCOPES` | Yes | SIGNED (WD-09) | 💰 | ✅ |

## A7. Overtime

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| OT-01 | When overtime begins | Worked minutes beyond the day's scheduled minutes (FIXED: shift span less V1 unpaid breaks; FLEXIBLE: required minutes; SPLIT: required minutes less V1 breaks; off day: zero). A late arrival must make up the shift first | `detect_overtime` | No | SIGNED (R-16/D-11, owner 6 Nov) | 💰 | ✅ (but BRK-06) |
| OT-02 | Pre-shift OT | Not possible on FIXED working days (ATT-06) | `clamp_pairs_to_start` | No | IMPLICIT | 💰 | ⚠️ |
| OT-03 | Eligibility | SHIFT_FLAG (default; shift `is_ot_eligible` default **false**), ALWAYS, NEVER. **GRADE_VIA_ASSIGNMENT behaves as ALWAYS** | `detect_overtime` | Yes | IMPLICIT (web hides it, mobile offers it) | 💰 | ⚠️ D-03 |
| OT-04 | Minimum | Excess below `min_ot_minutes` → 0; at or above, **all** excess counts (not excess minus minimum) | same | Yes, default 0 | CONFIG (guide matches) | 💰 | ✅ |
| OT-05 | Order: threshold → rounding → caps | Minimum checked on unrounded minutes, then rounded, then daily cap, weekly remaining, monthly remaining | same | No | IMPLICIT | 💰 | ⚠️ |
| OT-06 | Rounding | NONE/NEAREST (midpoint up)/UP/DOWN on the OT duration | `round_minutes` | Yes | CONFIG | 💰 | ✅ |
| OT-07 | Caps | Daily; weekly = **Monday–Sunday**; monthly = calendar month. Caps count approved and pending OT of other days | `_build_calculation_input` | Yes | IMPLICIT boundaries | 💰 | ⚠️ |
| OT-08 | Approval | `requires_post_approval` true by default; chain AUTO / MANAGER / MANAGER_THEN_HR / HR. AUTO always auto-approves. No manager → goes to HR. Partial approval allowed | `_resolve_ot_decision` | Yes | SIGNED (WD-29) | 💰 | ✅ |
| OT-09 | Pre-approval | `requires_pre_approval` stored, never enforced | — | Mobile only | DORMANT · D-03 | 💰 | ⛔ C-07 |
| OT-10 | Approved/rejected OT after a punch correction | Frozen: a decided OT record never changes on recalculation, even if the hours change | `_resolve_ot_decision` (`frozen`) | No | SIGNED (WD-29 d2); PD-OT-1 open since Sep | 💰 | ⚠️ |
| OT-11 | Night OT | SHIFT_FLAG (shift `is_night_shift`), WINDOW (OT span overlaps the night window), BOTH. Holiday and weekly-off classes outrank NIGHT | `resolve_is_night_ot`, `classify_ot_day` | Yes | SIGNED (ATT-005) | 💰 | ⚠️ D-02 |
| OT-12 | OT on leave / on-duty days | Zero on full-day leave; zero on ON_DUTY days that need no punch | overlays | No | SIGNED (BUS-011, D-5) | 💰 | ✅ |
| OT-13 | Comp-off vs pay | Policy-wide switch. Comp-off days = approved minutes ÷ `comp_off_day_length_minutes` (unset → that day's scheduled minutes), 2 decimals; expiry 60 days from the OT date unless set. Comp-off OT is never paid as money | `DEFAULT_COMP_OFF_EXPIRY_DAYS=60`; `credit_company`; payroll filter `comp_off_minutes_earned == 0` | Yes | SIGNED (BUS-015) except step rule | 💰 | ⚠️ D-13 |
| OT-14 | OT pay rate | Hourly = full-month **Basic** ÷ (days in month × **8**) × multiplier. No Basic → gross with a warning. Daily wage: daily rate ÷ 8 | `engine.py` `_HOURS_PER_DAY = 8` | No | SIGNED (D3) but D3 says Basic **+ DA** | 💰 | ⛔ C-03 |
| OT-15 | Multiplier | Taken from the OT policy version's rate row for the day's class. **Missing → payroll error `OT_MULTIPLIER_MISSING`**, run blocked | `engine.py`; `list_payable_overtime_for_period` | Yes | CONFLICT D-01 | 💰 | ⛔ C-03 |

## A8. Regularisation, lock, recalculation

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| REG-01 | How a correction works | Only synthetic punches, or a roster row for WRONG_SHIFT. WRONG_PUNCH replaces the nearest punch of that direction. WFH, WRONG_STATUS, EXCESS_BREAK have no special effect | `_apply_correction` | No | SIGNED (WD-28) | 💰 | ⚠️ |
| REG-02 | Monthly request cap | Counts requests **created** since the 1st of the **UTC** month (leave uses the company's local month) | `submit` (`datetime(now.year, now.month, 1, tzinfo=UTC)`) | Yes | IMPLICIT · D-14 | — | ⚠️ |
| REG-03 | Auto-approve within N minutes | `auto_approve_within_minutes` stored, never used | — | Mobile only | DORMANT | ◐ | ⚠️ |
| REG-04 | Early-departure pre-approval | With `early_departure_requires_approval`, an unapproved early exit takes the **harshest configured early band**. With no early bands configured it has **no effect** — the "Strict" template sets the flag without bands | `_harshest_band_classification`; templates | Yes | CONFLICT D-07 | 💰 | ⛔ C-18 |
| REG-05 | On duty | Default: full paid day, no punches needed, no OT. With `on_duty_requires_punch`: punch result kept and flagged | `_apply_on_duty_overlay` | Yes | SIGNED (WD-32 d6, D-5) | 💰 | ✅ |
| LCK-01 | Period grain | Per legal entity; any date range may be created, calendar month is the default | `AttendancePeriodCreate` | Yes | SIGNED (decisions 14/18) | 💰 | ⚠️ D-06 |
| LCK-02 | What blocks finalise | Missing day rows, CONFIG_ERROR, unresolved work-on-leave, paid+LOP+unpaid-off ≠ 1, INCOMPLETE under KEEP_INCOMPLETE, pending regularisations, pending OT, draft roster. **Pending leave applications do not block** | `_run_validation` | No | IMPLICIT for pending leave | 💰 | ⛔ C-06 |
| LCK-03 | INCOMPLETE at lock | TREAT_ABSENT (default) → LOP; TREAT_PRESENT → paid; KEEP_INCOMPLETE → blocks. A day whose policy cannot be found defaults to TREAT_ABSENT | `_apply_incomplete_lock_resolution` | Yes | SIGNED (PAY-006) | 💰 | ✅ |
| LCK-04 | Recalculation before lock | Every unlocked day in the period is recalculated, oldest first per employee | `_recalculate_open_days` | No | SIGNED (R-09) | 💰 | ✅ |
| LCK-05 | Routine recalculation | On each punch (best effort, company-local date), nightly 09:30 for today and 3 days back; cumulative counters cascade to later days of the month | `tasks.py`; `_recompute_later_days_of_month` | No | SIGNED (CD-4, R-04) | 💰 | ✅ |
| LCK-06 | Reopen | Allowed with a reason until payroll for that period is finalised; then never | `reopen` | No | SIGNED (BUS-008) | 💰 | ✅ |

## A9. Payroll

| ID | Policy decision | Current behaviour | Source | Config? | Basis | Pay | Status |
|---|---|---|---|---|---|---|---|
| PAY-01 | Pay cycle | Calendar month per legal entity. Payroll reads an attendance period only if it covers **exactly** the 1st–last day and is CLOSED | `closed_period_for_month` | No | SIGNED (BUS-017, PD-2) | 💰 | ⚠️ D-06 |
| PAY-02 | Proration | Monthly amount × paid days ÷ calendar days in month. No separate LOP line | `engine.py` | Per component `is_prorated` (default true) | SIGNED (BUS-016) | 💰 | ✅ |
| PAY-03 | Non-prorated components | Paid in full (weighted by employed days only) whatever the attendance | same | Yes | CONFIG | 💰 | ⚠️ |
| PAY-04 | Mid-month salary change | Month split into segments; **paid days are spread over segments by employed days**, not by which days were actually worked. LOP before a raise is charged partly at the new rate | `compute_employee` (`weight`) | No | IMPLICIT | 💰 | ⚠️ C-19 |
| PAY-05 | Joiners / leavers | Days outside employment are neither paid nor LOP; proration still divides by the full calendar month | BUS-002 | No | SIGNED | 💰 | ✅ |
| PAY-06 | Daily wage | Daily rate × paid days (weekly offs unpaid, HOL-02) | `engine.py` | No | SIGNED (D5) | 💰 | ✅ |
| PAY-07 | Net rounding | None; each line rounded half-up to the paisa | `engine.py` | No | SIGNED (D8) | 💰 | ✅ |
| PAY-08 | Corrections after payroll | Only a manual **paid-days delta** (`PayAdjustment`), bounded 0..payable days, paid as arrears in the next run. OT, encashment and comp-off changes after a finalised month have no path. Salary inputs changed later are recomputed as arrears for up to 12 months | `PayAdjustmentService`; `ARREARS_LOOKBACK_MONTHS=12` | No | SIGNED (D7) for days; IMPLICIT for OT | 💰 | ⛔ C-20 |
| PAY-09 | Default salary structure | Basic 50 % of gross; HRA 40 % (metro 50 %) of Basic; Special Allowance balancing; employer PF 12 % of Basic capped at ₹1,800 | `DEFAULT_STRUCTURES` | Editable | SIGNED (D1) | 💰 | ✅ |
| PAY-10 | Pay date | First weekday after month end; holidays ignored; editable | `default_pay_date` | Yes | SIGNED (D11) | — | ✅ |
| PAY-11 | Variance check | Per-employee net change against the previous run; company threshold | `PayrollSetting.variance_threshold_percent` | Yes | SIGNED (D10) | — | ✅ |
| PAY-12 | Allowances tied to attendance (e.g. attendance bonus, shift/night allowance) | None exist | — | — | Missing | 💰 | ⚠️ |

---

# B. Policy Dependency Map

```
Employee ──► Employment (joining, last working day, pay basis, probation end)
   │            │
   │            ├─► population gate: NOT_JOINED / EXITED → 0 paid, 0 LOP (PAY-05)
   │            └─► pay basis → which off days are paid (HOL-02) → paid days
   │
   ├─► Assignment (branch, dept, grade, designation, manager, SHIFT)
   │      │
   │      ├─► scope chain (EMPLOYEE>SHIFT>…>COMPANY) ─► Work calendar, Attendance policy,
   │      │       OT policy, Regularisation policy, Leave policy      [SHIFT = assignment shift, SHF-08]
   │      └─► approver (manager) for leave / OT / regularisation
   │
   ├─► Roster (published) ─► shift of the day (SHF-02); week-off / holiday-working override
   │
   ▼
Calendar day type ──────────────┐            Leave application ──► day breakdown (LV-03/04)
(WORKING / WEEKLY_OFF / HOLIDAY  │                 │                 [calendar + roster only]
 / SHUTDOWN / SPECIAL_WORKING)   │                 ▼
   │                             │            approval → ledger debit (or LOP) → LeaveDayProjection
   ▼                             ▼                                                   │
Shift window ─► punch load window (±2 h)  ─► punches ─► pairs ─► breaks ─► worked minutes
   (ATT-02/03)                                                                      │
                                                                                    ▼
Attendance policy: grace → late/early minutes → late/early bands                     │
                   hour bands → PRESENT / HALF_DAY / ABSENT  ◄───────────────────────┘
                   cumulative counters (month) → HALF_DAY
                   missing punch → INCOMPLETE
   │
   ▼
Overlays in order: off-day pay → half weekly off → ON_DUTY → LEAVE (leave wins)
   │
   ▼
AttendanceDay: status, paid / LOP / unpaid-off fractions, OT detected
   │                                     │
   │                          OT policy: eligibility → minimum → rounding → caps
   │                                     → approval (OvertimeRecord) → approved minutes
   │                                     → comp-off (leave ledger)  OR  payable OT
   ▼
Attendance period (legal entity) ─ recalc all open days ─ validate ─ INCOMPLETE → LOP/paid ─ lock
   │                                                                     (pending leave NOT a blocker)
   ▼
Frozen summary: paid days, LOP days, payable days, OT minutes by day class
   │
   ▼
Pay run (calendar month, same entity): segments × paid days ÷ days in month
                                        + OT (Basic ÷ (days×8) × multiplier)
                                        + encashment (Basic ÷ days)
                                        − statutory (PF/ESI/PT/LWF on earned wages) − TDS
                                        + arrears (paid-days deltas, salary changes)
   ▼
Net pay (to the paisa)
```

**Places where one module silently changes another's meaning:**

| # | Trigger | What silently changes | Recalculated? |
|---|---|---|---|
| X-01 | Leave approved after a day was computed ABSENT/INCOMPLETE | Projection sync recalculates the day → LEAVE | Yes, immediately (unless the period is closed: refused) |
| X-02 | Leave still **pending** at period close | Day stays ABSENT/INCOMPLETE → LOP; the leave can no longer be approved | No — C-06 |
| X-03 | Shift or policy changed with a past effective date | Day figures | Only by the 3-day sweep or at finalise |
| X-04 | Holiday added for a past date | Attendance: recalculated at finalise. **Approved leave on that date: never refunded** | Partly — C-16 |
| X-05 | Roster swap to another shift | Day's shift changes, but SHIFT-scoped policies and calendar do not follow | No — C-10 |
| X-06 | Punch corrected after OT was approved/rejected | Worked minutes change, OT stays as decided | No (by design, OT-10) |
| X-07 | Correction to an earlier day in a month with a late counter | Later days' HALF_DAY counter results | Yes (R-04 cascade) |
| X-08 | Attendance changed after payroll finalised | Only via manual paid-days adjustment; OT/comp-off cannot be corrected | Partly — C-20 |
| X-09 | Leave cancelled after payroll | Refused if the period is closed | Blocked by design |
| X-10 | Employee joins or leaves mid-month | Prorated days; accrual prorated (monthly) but not yearly | LV-15 |
| X-11 | Shift `operates_on_weekly_off` on a calendar weekly off | Leave consumes nothing, attendance expects work → LOP | C-04 |

---

# C. Unresolved Policy Decisions — **BLOCKING**

Each item below is a place where the system currently makes a payroll-affecting choice with no explicit owner decision behind it, or where parts of the system disagree. **No implementation should assume an answer.** Options and a recommendation for each are in section F.

| ID | Decision needed | Why it blocks | Register refs |
|---|---|---|---|
| **C-01** | How punches are attributed to a day, and how long after shift end work can still be recorded | Long overtime days silently become INCOMPLETE → LOP; overlapping windows can count one punch on two days | ATT-02/03/04 |
| **C-02** | Should grace also protect the hour bands (minimum hours)? | A 1-minute late arrival inside grace can turn a full day into a half day under the shipped "Standard office" template | GRC-05 |
| **C-03** | Overtime pay rate: base (Basic vs Basic+DA vs gross), hours per day (fixed 8 vs shift length), and the multiplier's status | The web form and guide call the multiplier "information only", but payroll requires it and blocks the run without it; night OT with no NIGHT row blocks the run | OT-14, OT-15, D-01, D-02 |
| **C-04** | Leave on an off day that the employee's shift works | Leave consumes 0 days, attendance expects work → LOP | LV-03, SHF-07, X-11 |
| **C-05** | Do unpaid breaks reduce the OT threshold for every break type? | OT starts after 8 h or 9 h depending on how the same lunch was configured | BRK-06 |
| **C-06** | Should pending leave block period close? | Pending leave becomes LOP at lock with no way back except a paid-days adjustment after payroll | LCK-02 |
| **C-07** | What to do with dormant settings (punch rounding, auto-close, half-day split, WFH, split-shift compensation, OT pre-approval, regularisation auto-approve, counts-toward-cap, late/excess count window, work-on-leave) | Mobile lets admins set them; nothing happens | ATT-15/16/22/23, OT-09, REG-03 |
| **C-08** | Pay for punches on a day with no shift | Any worked minute pays a full day | ATT-17 |
| C-09 | Worked minutes that fall in a gap between hour bands | Default is PRESENT (full pay) | ATT-18 |
| **C-10** | SHIFT-scoped policy on a rostered day | Night-shift rules do not follow a roster swap | SHF-08 |
| C-11 | Early departure on flexible shifts | Never detected against the working day | SHF-10 |
| C-12 | Monthly grace bank | Not built; common in Indian HR policies | GRC-03 |
| **C-13** | Sandwich rule on unpaid leave | Weekends inside LOP leave become LOP | LV-05 |
| **C-14** | Negative leave balance at exit | No recovery exists, though the signed decision says "recovered in F&F" | LV-09 |
| **C-15** | Yearly accrual for joiners and probationers | Joiners wait up to a year; probation ignored | LV-15 |
| **C-16** | Holiday added after leave approved | Employee loses a leave day for a holiday | LV-27 |
| C-17 | Comp-off scope | Policy-wide, so all OT (not just holiday work) becomes comp-off | HOL-09 |
| **C-18** | "Leaving early needs approval" with no early bands | Shipped template sets a rule that does nothing | REG-04 |
| C-19 | LOP spread across a mid-month salary change | LOP before a raise is charged partly at the new rate | PAY-04 |
| **C-20** | Correcting OT, comp-off or encashment after payroll is finalised | No path exists | PAY-08 |

Also still open from the September register and confirmed still true in code: PD-SHIFT-1 (two shifts per day), PD-OT-1 (revising decided OT), PD-REG-1 (WRONG_STATUS / EXCESS_BREAK have no effect), PD-XMOD-002 (= C-10). Owner decision R-02 (sandwich across applications) is made but not built.

---

# D. Conflict Register

| ID | Kind | Side A | Side B | Effect |
|---|---|---|---|---|
| **D-01** | Code ≠ UI/docs | Payroll pays OT with `multiplier_decimal` and raises `OT_MULTIPLIER_MISSING` (ERROR) when it is blank (`engine.py`) | Web rate-row editor: "Multiplier (information only)… never becomes money here"; settings guide: "for information only. The system never turns it into money"; web OT templates leave it blank on purpose | Every company that uses a template has approved OT that **blocks its first pay run** |
| **D-02** | Module ≠ module | Engine: no NIGHT rate row → night OT uses the NORMAL row's classification code (`detect_overtime`); guide says the same | Payroll joins the rate row on `ot_day_class = 'NIGHT'` → no multiplier → ERROR | Night OT under a policy without a NIGHT row blocks payroll |
| **D-03** | Web ≠ mobile | Web hides dormant settings and `AUTO_CLOSE`, `GRADE_VIA_ASSIGNMENT` (labelled "behaves like ALWAYS") | Mobile `policy_resources.dart` exposes punch rounding, auto-close (2 fields), half-day split/boundary, core-end early-out, split-shift mandatory/compensation, WFH (2), work-on-leave, OT pre-approval, regularisation auto-approve, AUTO_CLOSE and GRADE_VIA_ASSIGNMENT | Admins on mobile can set rules that do nothing or behave differently from their label |
| D-04 | Signed decision ≠ code | D3: OT base = (Basic + **DA**) | Engine uses BASIC only; no DA component exists | OT underpaid wherever DA is part of wages |
| **D-05** | Module ≠ module | Attendance: a shift with `operates_on_weekly_off` makes a weekly off a working day | Leave day count reads calendar + roster only | Leave of 0 days on a day attendance marks absent |
| D-06 | Config ≠ runtime | Attendance periods accept any date range | Payroll reads only an exact calendar month | A 26th–25th period can be closed but can never be paid |
| **D-07** | Template ≠ behaviour | "Strict attendance" template (web and mobile): "leaving early needs approval" | The flag acts only on configured early bands; the template has none | The advertised rule does nothing |
| D-08 | Expectation ≠ behaviour | Guide: grace lets someone arrive within N minutes "without being counted late" | The lost minutes still reduce worked hours and can drop the day below the full-day band | Half days for on-time-by-grace arrivals |
| D-09 | Field label ≠ behaviour | `counts_toward_cap` is editable on late/early bands (web and mobile) | Never read | Misleading setting |
| D-10 | Same concept, two meanings | V1 unpaid breaks reduce the scheduled minutes for OT | Legacy (mode-less) unpaid breaks do not | Different OT for the same lunch hour |
| D-11 | Same field, two meanings | `accrue_during_probation` stops monthly accrual | It is ignored for yearly accrual | Probationers on yearly policies get the full credit |
| D-12 | Signed decision ≠ code | BUS-009: optional/restricted holidays capped per year (default 2) | No cap or holiday-linked leave type exists | Unlimited optional holidays if a leave type is used for them |
| D-13 | Signed decision ≠ code | BUS-015: ≥ full shift = 1 day, ≥ half shift = 0.5 day | Proportional minutes ÷ day length to 0.01 day (step rule recorded as deferred) | 3 h of OT on a 9 h shift earns 0.33 days instead of 0 |
| D-14 | Module ≠ module | Leave monthly request cap: company-local month | Regularisation monthly cap: UTC month, counted by creation time | Off by up to 5 h 30 min at month boundaries |
| D-15 | Docs ≠ code | Settings guide: classification code is what "Payroll uses to decide how that overtime is paid" | Payroll uses the day class and multiplier; the code is not read | Admins may set codes expecting a pay effect |

---

# E. Payroll Impact Matrix

Day-level figures are per working day on a MONTHLY employee unless stated. "Paid" = `paid_day_fraction`; pay = salary × Σ paid ÷ days in month.

| Event | Attendance result | Paid / LOP | Salary component | Immediate? | Period that pays it | Reversible after payroll? |
|---|---|---|---|---|---|---|
| On time, full hours | PRESENT | 1 / 0 | Prorated earnings | At close | Same month | — |
| Late within grace | PRESENT, not late | 1 / 0 — **unless worked minutes fall below the full-day band** (GRC-05) | same | At close | Same | Paid-days adjustment only |
| Late beyond grace, late band LATE | PRESENT, late counted | 1 / 0 | none directly; feeds counter | — | — | — |
| Late band HALF_DAY / ABSENT | HALF_DAY / ABSENT | 0.5/0.5 · 0/1 | Prorated earnings reduced | At close | Same | Adjustment |
| Nth late day in month (counter) | HALF_DAY | 0.5 / 0.5 | same | At close | Same | Adjustment |
| Early departure | as late (early bands) | as bands | same | | | |
| Short hours | Hour band | band | same | | | |
| Missing punch | INCOMPLETE → at lock TREAT_ABSENT | 0 / 1 (default) | same | At lock | Same | Adjustment |
| Punch-out ≥2 h after shift end | INCOMPLETE (C-01) | 0 / 1 at lock | same, **and OT lost** | At lock | Same | Adjustment for days only |
| Absent (no punches) | INCOMPLETE → ABSENT at lock (or ABSENT if policy) | 0 / 1 | same | At lock | Same | Adjustment |
| Paid leave, full day | LEAVE | 1 / 0 | none (balance debited) | On approval | Same | Cancel only while period open |
| Unpaid leave / excess-as-LOP | LEAVE | 0 / 1 | Prorated earnings reduced | On approval | Same | same |
| Half-day leave + worked half | HALF_DAY (or LEAVE if half lost) | 1/0 or 0.5/0.5 | same | | | |
| Sandwiched weekend in paid leave | LEAVE | 1 / 0, balance debited | balance only | | | |
| Sandwiched weekend in unpaid leave | LEAVE | **0 / 1** (C-13) | earnings reduced | | | |
| Holiday / weekly off (monthly) | NOT_EXPECTED | 1 / 0 | none | | | |
| Weekly off (daily wage) | NOT_EXPECTED | 0 paid, 0 LOP, 1 unpaid-off | no wage | | | |
| Work on holiday / weekly off | PRESENT | 1 / 0 (monthly) | **+ OT for all worked minutes** at HOLIDAY / WEEKLY_OFF multiplier (if eligible), or comp-off | OT after approval | Month of the day | No path (C-20) |
| Overtime on a working day | PRESENT | 1 / 0 | OT = minutes/60 × Basic/(days×8) × multiplier; ESI wage, not PF wage | After approval; pending OT blocks close | Same | No path |
| OT under comp-off policy | PRESENT | 1 / 0 | none; leave ledger credit, expires 60 days | Hourly credit sweep | — | — |
| Comp-off taken | LEAVE (comp-off type) | 1 / 0 | none | | | |
| Leave encashment (year end or HR) | — | — | + Basic ÷ days × days encashed | Month of ledger date | That month | No path |
| On duty (no punch needed) | ON_DUTY | 1 / 0, no OT | none | | | |
| Work on approved full-day leave | LEAVE, flagged; close blocked | 1 / 0, no OT | none | Needs HR | | |
| No shift resolved, any punches | PRESENT (C-08) | 1 / 0 | full day | | | |
| No calendar / no policy | CONFIG_ERROR | 0 / 0, close blocked | — | Must fix | | |
| Joiner / leaver days outside employment | NOT_JOINED / EXITED | 0 / 0 | prorated over full month | | | |
| Mid-month CTC change | — | — | segments; paid days spread by employed days (C-19) | | | |
| Salary input changed after payroll | — | — | arrears lines next run (≤12 months back) | Next run | Next run | Automatic |
| Day correction after payroll | — | delta | arrears via `PayAdjustment` | Next run | Next run | Manual only |

---

# F. Recommended Decision Framework

For each blocking item: the decision, options, trade-offs and a **recommendation that is only a recommendation** — none has been applied.

### C-01 · Punch attribution and the 2-hour window
**Decide:** how far after shift end a punch still belongs to the day, and how to stop one punch counting twice.
| Option | For | Against | Complexity |
|---|---|---|---|
| a. Keep ±2 h | No change | OT over 2 h is impossible and turns into LOP; overlap double count stays | None |
| b. Make look-back/look-ahead policy fields (e.g. default 2 h / 6 h) | Admin controls; small change | Overlap still possible with long windows | Low (migration, engine version bump) |
| c. Assign each punch to exactly one day at write time (nearest shift, ties to the earlier shift) | No double count; any OT length | Bigger change; backfill of existing punches | High |
| d. (b) plus "a punch already used by the previous day is excluded" | Fixes both with moderate effort | Ordering dependency between days | Medium |

Edge cases: back-to-back shifts, night shift followed by a morning shift, OT past midnight on a day shift. **Recommended: (d)** — configurable windows with the previous day's punches excluded. Impact on payroll: removes false LOP on long days.

### C-02 · Grace and hour bands
| Option | For | Against |
|---|---|---|
| a. Keep: grace only removes the late mark | Simple, consistent minutes | Surprising half days; contradicts what the guide implies |
| b. Credit grace minutes toward worked time (count from scheduled start when arrival ≤ grace) | Matches common Indian practice | Small pay for unworked minutes |
| c. Lower template full-day band to shift net hours − grace | No code change | Every policy must be set carefully |
Edge cases: exactly at grace; grace with OT (credited minutes must not create OT). **Recommended: (b)**, with credited grace excluded from OT. Complexity low (engine only, version bump).

### C-03 · OT rate and multiplier
**Decide:** (1) base: Basic, Basic+DA, or gross; (2) hours per day: fixed 8 or the employee's shift hours; (3) multiplier is required (payroll) — fix the UI/guide wording, or make a missing multiplier default to 1× / 2×; (4) NIGHT with no row: fall back to NORMAL multiplier, or require a row.
Statute note for the owner to verify with an advisor: the Factories Act uses twice the ordinary rate. **Recommended:** multiplier required and the UI/guide/templates corrected (templates prefilled with 2.0 for all classes as a visible, editable starting point); NIGHT falls back to the NORMAL row's multiplier in payroll as it already does for the label; base and hours per day decided explicitly by the owner (no recommendation on DA without knowing whether clients pay DA). Complexity low.

### C-04 · Leave on a day the shift works
| a. Leave counts the shift's operating days too | Consistent with attendance | Changes leave counts for 7-day operations |
| b. Attendance treats an off day as not expected unless rostered | Leave unchanged | Shift flag loses meaning |
**Recommended: (a)** — leave consumption follows the same "expected to work" rule attendance uses. Medium complexity (leave breakdown must resolve the shift).

### C-05 · Breaks and OT threshold
**Recommended:** every unpaid break, legacy or V1, reduces the scheduled minutes OT is measured against (i.e. OT starts after net shift hours). Changes OT for legacy-break companies; engine version bump; low complexity.

### C-06 · Pending leave at close
| a. Block close (new reason PENDING_LEAVE) | No surprise LOP | HR must chase approvers |
| b. Warn only | Never stops payroll | LOP stays |
| c. Auto-reject at close | Clean | Harsh |
**Recommended: (a)**, consistent with pending regularisation and pending OT already blocking. Low complexity.

### C-07 · Dormant settings
**Recommended:** hide every dormant field on mobile now (as web already does); then decide one by one whether to implement (punch rounding and OT pre-approval are the likeliest to be wanted) or remove. Removing columns needs a migration; hiding does not.

### C-08 · Punches with no shift
Options: full day (current), hour bands applied against no schedule, INCOMPLETE until a shift is set. **Recommended:** INCOMPLETE (or CONFIG_ERROR) so a missing assignment is fixed rather than paid by default.

### C-09 · Band gaps
**Recommended:** refuse to publish bands with gaps from 0 upwards (so every worked minute has an explicit result).

### C-10 · Roster and SHIFT-scoped policies
**Recommended:** resolve SHIFT scope from the shift of the day (roster first), matching the architecture's original intent. Medium: resolution needs the roster; every policy lookup touched.

### C-11 · Flexible early departure
Options: measure against first-in + required minutes; against core end; never. **Recommended:** first-in + required minutes (+ grace), which is what "flexible" usually means.

### C-12 · Monthly grace bank
Owner choice: not needed / N late arrivals per month forgiven / N minutes per month. No recommendation without the client's HR policy.

### C-13 · Sandwich on unpaid leave
**Recommended:** owner decides explicitly; many Indian companies do apply the sandwich rule to LOP. If kept, show it in the leave preview.

### C-14 · Negative balance at exit
Options: deduct days × day rate in the final pay run; block exit until resolved; write off. **Recommended:** deduct in the final pay run as a deduction line (needs a small F&F step).

### C-15 · Yearly accrual
**Recommended:** prorate the yearly credit for a joiner by remaining days in the leave year, credited on joining; apply `accrue_during_probation` the same way as monthly.

### C-16 · Holiday added after leave approved
Options: refund automatically; show in the calendar-impact preview and let HR refund; leave as is. **Recommended:** list affected leave in the existing impact preview and offer a refund on confirm.

### C-17 · Comp-off scope
**Recommended:** owner decides whether comp-off applies to all OT or only to holiday/weekly-off work (a per-day-class switch).

### C-18 · Early-departure approval without bands
**Recommended:** without early bands, treat an unapproved early exit as HALF_DAY, or refuse to publish the flag without bands; fix the "Strict" template either way.

### C-19 · LOP across a salary change
Options: spread (current); charge LOP at the rate of the segment the LOP day fell in. **Recommended:** charge by date — needs per-segment paid days from attendance; medium complexity.

### C-20 · Post-payroll OT / comp-off / encashment corrections
**Recommended:** extend `PayAdjustment` with an OT-minutes delta by day class (and an encashment delta), paid as arrears the same way paid days are.

---

# G. Boundary conditions (derived by reading code — confirm with tests)

| # | Case | Result in current code |
|---|---|---|
| G-01 | Grace 10, IN 09:10:59 | Not late (raw 10) |
| G-02 | Grace 10, IN 09:11:00 | 1 min late; band looked up at 1 |
| G-03 | Standard bands, 479 worked minutes | HALF_DAY (0.5 paid) |
| G-04 | 480 worked minutes | PRESENT |
| G-05 | 239 worked minutes | ABSENT |
| G-06 | 09:00–18:00, 1 h legacy lunch punched, IN 09:01 OUT 18:00 | 479 → HALF_DAY although within grace |
| G-07 | 09:00–18:00 FIXED, OUT at 19:59:59 | Loaded; OT counted (if eligible) |
| G-08 | Same, OUT at 20:00:00 | Not loaded → INCOMPLETE → LOP at lock |
| G-09 | IN 08:00 on a 09:00 shift | Credited from 09:00; no pre-shift OT |
| G-10 | `min_ot_minutes` 30, excess 29 / 30 | 0 / 30 |
| G-11 | NEAREST 15, excess 37 / 38 | 30 / 45 (midpoint 37.5 not reachable; 38 rounds up) |
| G-12 | Night 22:00–06:00, IN 21:55, OUT 06:05 | Owned by start date; credited 22:00–06:05 |
| G-13 | Night shift D and 06:00 shift D+1, punch at 05:00 D+1 | In both days' windows |
| G-14 | Late count 3: 3rd late day in the month | HALF_DAY; 4th and 5th not; 6th HALF_DAY |
| G-15 | Late day on 31 Jan, next late on 1 Feb | Counter resets (calendar month) |
| G-16 | Weekly OT cap, week Mon 29 Dec – Sun 4 Jan | One week across two months and two periods |
| G-17 | Leave Fri–Mon, sandwich on | 4 days |
| G-18 | Leave Fri, separate leave Mon, sandwich on | 2 days (no cross-application look) |
| G-19 | Half day leave on a half-day weekly off | Fraction 0.50 at most; worked half not judged |
| G-20 | Leave on a Sunday the shift operates on | 0 days consumed; day INCOMPLETE → LOP |
| G-21 | Joiner on 15 Jan, MONTHLY 1.5/month | 17/31 × 1.5 = 0.82 credited on 31 Jan (run in early Feb) |
| G-22 | Joiner on 15 Jan, YEARLY 12, calendar year | 0 until 1 Jan next year |
| G-23 | Balance 1.5, apply 2 days, approve with excess as LOP | Day 1 paid; day 2 LOP in full; 0.5 balance stays |
| G-24 | 3 h OT, comp-off, 9 h scheduled | 0.33 comp-off day |
| G-25 | Night OT, policy has NORMAL row only | Day labelled with NORMAL code; payroll ERROR (no NIGHT multiplier) |
| G-26 | Attendance period 26 Jan–25 Feb | Can be closed; payroll cannot read it |
| G-27 | Correction after payroll paid | Paid-days delta only; OT unchanged |
| G-28 | Two regularisations for the same date | Second refused while the first is active |
| G-29 | Policy changed mid-month | Each day uses the version effective that day; existing days recompute at the sweep or finalise |

---

# Appendix 1 — Hardcoded values that act as HR policy

| Value | Meaning | Where |
|---|---|---|
| 2 h | Punch window before/after FIXED and SPLIT shifts | `calculation.py` 422, 521–522 |
| 12 h | Punch window after a flexible start window | `calculation.py` 534 |
| 30 min | Stray same-direction punch window | `STRAY_PUNCH_WINDOW_MINUTES` |
| 60 s | Duplicate punch window (default; configurable) | model default |
| 120 s | Minimum gap between self-service punches | settings |
| 18 h | Look-back for "already punched in/out" | settings |
| 8 h | Hours per day in OT rate | `engine.py` `_HOURS_PER_DAY` |
| 60 days | Comp-off expiry default | `DEFAULT_COMP_OFF_EXPIRY_DAYS` |
| 30 days | Max consecutive leave days (default) | `max_consecutive_days` |
| 90 days | Max days in any leave request | `MAX_LEAVE_REQUEST_DAYS` |
| 5 days | Monthly accrual run window | settings |
| 3 months | Accrual catch-up | `ACCRUAL_CATCH_UP_MONTHS` |
| 5 days | Year-end catch-up | settings |
| 3 days | Nightly recalculation look-back | `TRAILING_DAYS` |
| 09:30 local | Nightly calculation time | `celery_app.py` |
| 3 days | Incomplete-attendance reminder lead | settings |
| 12 months | Arrears look-back | `ARREARS_LOOKBACK_MONTHS` |
| Mon–Sun | OT week | `_build_calculation_input` |
| Calendar month | Late/excess-break counter window, OT monthly cap, pay cycle | same; `_LATE_COUNT_WINDOWS = ("MONTH",)` |
| EVEN | Alternate weekly-off default parity | `_rule_matches` |
| PUBLIC, SUBSTITUTE | Holidays paid to daily-wage staff | `_DAILY_WAGE_PAID_HOLIDAY_TYPES` |
| Asia/Kolkata | Only allowed timezone | settings |
| 50 % / 40 % / 50 % / 12 % / ₹1,800 | Default salary structure | `DEFAULT_STRUCTURES` |
| TREAT_ABSENT | INCOMPLETE at lock, also when policy is missing | model default, `_apply_incomplete_lock_resolution` |

# Appendix 2 — Stored settings with no effect

`punch_rounding`, `rounding_minutes` (attendance), `auto_close_after_minutes`, `auto_close_uses_shift_end`, `missing_punch_behaviour = AUTO_CLOSE` (no closing), `half_day_split`, `half_day_boundary_minutes`, `early_out_uses_core_end`, `split_shift_block_mandatory`, `split_shift_allow_hours_compensation`, `wfh_requires_punch`, `wfh_uses_shift_hours`, `work_on_leave_behaviour`, `counts_toward_cap` (late and early bands), `late_count_window` / `excess_break_count_window` (only MONTH exists), `requires_pre_approval` (OT), `auto_approve_within_minutes` (regularisation), `pre_delivery_days` / `post_delivery_days`, `encashment_frequency`, `encashment_calculation_basis`, `Grade.notice_period_days`, `Shift.grace_in/out_minutes`, `Shift.break_minutes_paid/unpaid`, `eligibility = GRADE_VIA_ASSIGNMENT` (acts as ALWAYS).

# Appendix 3 — Scheduled jobs that change pay figures

| Job | When | Effect |
|---|---|---|
| `leave.run_monthly_accrual` | Daily 01:00 | Monthly accrual (acts in first 5 days) |
| `leave.run_comp_off_credit_sweep` | Hourly | Credits/reverses comp-off |
| `leave.run_comp_off_expiry_sweep` | Daily 01:30 | Expires comp-off |
| `leave.run_year_end_sweep` | Daily 02:00 | Lapse, carry-forward cap, encashment, yearly accrual |
| `attendance.run_daily_calculation` | Daily 09:30 | Recalculates today and 3 days back |
| `attendance.run_incomplete_reminders` | Daily 10:00 | Reminders only |
| `employee.run_termination_access_sweep` | Hourly | Ends login access after last working day |

Celery runs with `timezone = Asia/Kolkata`, `enable_utc = True`.
