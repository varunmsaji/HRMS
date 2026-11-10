# HRMS Rules, Policies & Attendance Logic — Production Audit

| Field | Value |
|---|---|
| Date | 2026-11-05 |
| Branch / commit | `claude/tender-gauss-5xrf9z` at `1268367` (code identical to `f7272cf`; the only later commit is a doc) |
| Mode | Audit only. No production code, test, migration or configuration was changed. |
| Builds on | `docs/audits/ATTENDANCE_LEAVE_POLICY_OVERTIME_INTERACTION_AUDIT_2026-11-04.md` (findings F1–F11, 84 test cases). Those findings are re-confirmed against the same code and are referenced here, not repeated in full. |
| Scope added by this audit | Sandwich leave, leave accrual and year-end, leave lifecycle, punch intake and pairing, grace/late/early boundaries, breaks, overtime rounding, cumulative counters, regularization corrections, recalculation and staleness, timezone/date boundaries, concurrency, web/mobile parity. |

## How findings were verified

Every finding carries one of four evidence labels.

| Label | Meaning |
|---|---|
| **CONFIRMED-RUN** | Reproduced by executing the real code: the pure engine (`evaluate_day`) or the real HTTP app against PostgreSQL 16 with all migrations applied. |
| **CONFIRMED-CODE** | Proven by tracing the execution path; no ambiguity in the code. |
| **HIGH-RISK** | The code allows it; triggering it needs a realistic but timing- or operator-dependent sequence. |
| **DECISION** | The code does what it says; the behaviour is a product choice that needs an owner. |

Probe harnesses used (deleted after the run, reproducible from this report):

* Engine probe: `tests/unit/modules/attendance/test_calculation.py::_base_input` with a 09:00–18:00 IST FIXED shift, grace 15/15, hour bands `[0,239] ABSENT · [240,419] HALF_DAY · [420,∞) PRESENT`, late and early bands `[1,60] · [61,180] HALF_DAY · [181,∞) ABSENT`.
* Integration probes: helpers from `tests/integration/modules/leave/test_leave_application.py` and `test_leave_accrual.py`, run against a local migrated `hrms_test` database.

Baseline: `tests/unit/modules/attendance` + `tests/unit/modules/leave` → 353 passed, 5 skipped, 1 failed (`test_liveness.py::test_boot_refuses_enabled_liveness_with_missing_assets`, a face-model asset check unrelated to rules).

---

## 1. Executive summary

### Scores

| Area | Score | Why |
|---|---|---|
| **Overall rules correctness** | **5/10** | Strong engine design and concurrency controls, but several money-moving rules are wrong in the most common configurations. |
| Attendance logic | 6/10 | Boundaries and overnight shifts are correct. A duplicate punch, or a "wrong punch" correction, turns a worked day into INCOMPLETE and then full LOP at close. |
| Shift logic | 7.5/10 | Versioned, immutable once published, effective-dated. FLEXIBLE lateness is measured from the wrong end of the window (F1). |
| Grace periods | 8/10 | No off-by-one errors. Grace is deducted from late minutes and seconds are truncated; both are consistent and documented in the UI. |
| Overtime | 6/10 | Net-of-break arithmetic is right. Frozen OT survives a later leave (F2), off-day OT is only "beyond shift" (F8), NEAREST rounding is inconsistent. |
| Leave policy | 6/10 | Lifecycle, balance locks and reversal are solid. Maternity windows and encashment frequency are stored but not enforced; no partial cancellation. |
| Leave accrual | 6.5/10 | Idempotent by unique index. A missed run window is unrecoverable, probation is judged at run time, and accrual/year-end ordering can leak balance past a lapse. |
| Sandwich leave | 2.5/10 | Does not sandwich a two-day weekend at all, and is bypassed by splitting a request in two. |
| Cross-module consistency | 5/10 | Half-day leave, ON_DUTY, OT and lock interactions (F2–F7) plus no staleness detection at period close. |

### Answer to the audit question

**Yes.** An employee can today receive an incorrect leave deduction, an incorrect half-day or absent mark, incorrect overtime, and an incorrect leave balance through logic bugs and sequence effects, without anyone doing anything unusual. The most impactful confirmed cases are:

1. **Friday-to-Monday leave over a Saturday-plus-Sunday weekend deducts 2 days with the sandwich rule on**, not 4 (R-01).
2. **"Late days before a half-day = 3" makes the 3rd and every later late day a half day.** The web form promises only the third (R-03).
3. **A second IN punch, or an approved "wrong punch" correction, leaves a full worked day INCOMPLETE**, which the default lock behaviour turns into a full day of LOP (R-05, R-06).
4. **Overtime approved before a backdated full-day leave is still paid** on the leave day (F2).
5. **A FLEXIBLE-shift employee arriving inside their allowed window is marked late** (F1).

Final decision: **🔴 NO-GO** for payroll-affecting production use until Phase 0 is fixed (Section 9).

---

## 2. Architecture and source of truth

### 2.1 Components

| Concern | Where it lives | Notes |
|---|---|---|
| Day calculation engine | `apps/api/src/hrms/modules/attendance/calculation.py` (`evaluate_day`) | Pure function; no DB. |
| Input resolution, persistence, OT decision | `attendance/service.py` (`AttendanceDayService._build_calculation_input`, `_calculate`) | Full-row replacement per employee-date. |
| Punch intake | `attendance/service.py` (`PunchService.record_punch_outcome`, `enforce_shift_window`) | Self-service sources are `WEB`, `FACE`; HR uses `ADMIN`. |
| Breaks | `attendance/break_service.py`, `calculation.compute_breaks` | Advisory lock per employee-date. |
| Regularization | `attendance/service.py` (`AttendanceRegularizationRequestService`) | Approved punches are inserted additively. |
| Period validate / finalize / reopen | `attendance/service.py` 6467–7180 | Finalize does not recompute. |
| Shifts | `organisation/service.py` (shift versions, publish), `organisation/models.py:Shift/ShiftVersion` | Published versions immutable; effective-dated. |
| Work calendar, holidays, weekly offs | `organisation/calendar_resolution.py`, `calendar_impact.py` | Changes never rewrite attendance or leave. |
| Leave types, policies, applications, ledger | `leave/service.py`, `leave/repository.py` | Ledger is append-only; balance is a live sum. |
| Leave accrual and year-end | `leave/service.py:LeaveAccrualService`, `leave/tasks.py` | Celery beat in `core/celery_app.py`. |
| Leave → attendance hand-off | `LeaveProjectionService.sync/cancel` in `attendance/service.py` | Runs inside the approval transaction. |
| Payroll hand-off | `attendance/repository.py:list_payable_overtime_for_period`, `payroll/engine.py`, `leave/repository.py:list_encashments_between` | Payroll reads only CLOSED periods. |

### 2.2 Scheduled jobs (Asia/Kolkata beat timezone)

| Job | Schedule | Business date | Recovery |
|---|---|---|---|
| `leave.run_monthly_accrual` | daily 01:00 | `business_today(company.timezone)`; only acts on days 1–5 | None after day 5 (R-08) |
| `leave.run_year_end_sweep` | daily 02:00 | `business_today`; 5-day catch-up; operator task accepts `as_of` | Yes |
| `leave.run_comp_off_credit_sweep` | hourly | n/a; idempotent per OT record | Yes |
| `leave.run_comp_off_expiry_sweep` | daily 01:30 | `business_today` | Yes |
| `attendance.run_daily_calculation` | daily 09:30 | `business_today`; today + 2 trailing days | Range recompute endpoint |
| `attendance.run_incomplete_reminders` | daily 10:00 | | |

### 2.3 Rule source-of-truth matrix

| Rule | Source of truth | Backend enforcement | Web | Mobile |
|---|---|---|---|---|
| Grace in/out | `attendance_policy_version.grace_*` | Engine `calculation.py:2025-2034` | Form + "after grace" copy | Display only |
| Shift-level grace / half-day hours | Retired: `Shift.grace_*`, `half_day_threshold_hours`, `min_hours_full_day` forced to 0/NULL on create (`organisation/service.py:2173`) | Not read | Shift page copy still says "grace periods" | n/a |
| Late/early/hour bands | Policy version bands | Engine | Editor + client validation | Display |
| Lates-to-half-day | `lates_to_half_day_count` | Engine, every late from N onward | Copy says "the third late day" (mismatch, R-03) | Label "Lates that make a half day" |
| Early punch-in allowance | `early_in_allowance_minutes` | `enforce_shift_window`, WEB/FACE only | — | Renders server refusal |
| Punch order / min gap | Settings, defaults on | WEB/FACE only; ADMIN exempt | — | — |
| Duplicate punch collapse | `duplicate_punch_window_seconds` (60) | Engine, same direction only | — | — |
| Half-day leave single date | Schema validator `leave/schemas.py:602` | Yes | Server error shown | Client check + server |
| Leave day count / sandwich | `_compute_day_breakdown` | Yes | Shows server `total_days` | Shows server `total_days` |
| Leave balance check | Ledger sum | Submit (soft) + approval under advisory lock | Server errors | Server errors |
| Accrual | Policy version | Celery task | — | — |
| OT detection / caps / rounding | OT policy version | Engine | — | — |
| Period lock | `attendance_period` | All seven mutation surfaces + advisory lock | — | — |

No business rule was found that is enforced only on web or only on mobile. The backend is authoritative everywhere checked.

---

## 3. Complete findings register

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low. Paths are relative to `apps/api/src/hrms/modules/`.

### 3.1 New findings from this audit

| ID | Sev | Module | Rule | Scenario | Expected | Actual | Root cause | Risk | Fix | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| R-01 | 🔴 | Leave | Sandwich | Sat+Sun weekly off, sandwich on, leave Fri–Mon | 4.00 days (Fri, Sat, Sun, Mon) | **2.00 days**, Sat/Sun not counted | `leave/service.py:2381-2387` only marks an off day when **both immediate neighbours** consume leave. With two consecutive off days, neither has two consuming neighbours. Holiday + weekend runs fail the same way. | Systematic under-deduction for every 5-day-week company using the rule | Treat each maximal run of non-consuming days as one block: sandwich it when the days before and after the run are consuming. | CONFIRMED-RUN |
| R-02 | 🟠 | Leave | Sandwich | Leave Fri as one application, Mon as another | Weekend sandwiched (if that is the policy) | 1 + 1 days; weekend free | Breakdown looks only inside one application (docstring at 2357–2359) | Trivial self-service bypass | At submit, look at adjacent active applications of sandwich-enabled types and add the bracketed off days to the new application. Re-evaluate on cancel. | CONFIRMED-RUN |
| R-03 | 🟠 | Attendance | Lates-to-half-day | Count 3; employee late (beyond grace) on 5 days in a month | Web copy: "the third late day is a half-day" | Days 3, 4 and 5 are all HALF_DAY, each 0.50 LOP | `calculation.py:2077-2083` fires whenever `prior + 1 >= count` | Over-deduction of pay; employee-facing dispute | Decide the rule (D-10). If "every Nth", fire when `(prior + 1) % count == 0`. Align the web copy, the strict template text and mobile label. | CONFIRMED-RUN + UI copy at `web/src/components/attendance-policy/attendance-policy-version-form.tsx:121-122` |
| R-04 | 🟠 | Attendance | Cumulative counters | Day 3 later regularized to not late, after days 4–20 were computed | Later days recomputed against the new count | Later days keep their HALF_DAY; finalize locks them | Counter reads stored `is_late` of earlier days (`service.py:4413-4442`); nothing recomputes dependants; sweep covers only 3 days; finalize does not recompute | Stale penalties reach payroll; results depend on calculation order | After any change to a day's `is_late` or excess-break flag, enqueue recompute of later days of that month. Add a staleness check to period validation. | HIGH-RISK (CONFIRMED-CODE path) |
| R-05 | 🟠 | Attendance | Punch pairing | IN 09:00, IN 09:05, OUT 18:00 (or IN, OUT, OUT 18:05) | PRESENT, 540 worked (or ignore the stray punch) | **INCOMPLETE**, `missing_punch=True`; default `incomplete_at_lock_behaviour=TREAT_ABSENT` makes it full LOP at close | `pair_punches` (`calculation.py:585-611`) makes the earlier IN an orphan; `_resolve_primary_status` returns INCOMPLETE on any orphan | Full-day LOP for a worked day. Self-service is protected by the order check, but ADMIN on-behalf punches and approved regularizations are not | Treat a same-direction orphan bracketed by a valid pair as superseded (keep the earliest IN / latest OUT) and flag for review instead of INCOMPLETE. Apply the order check to ADMIN punches with an explicit override. | CONFIRMED-RUN |
| R-06 | 🟠 | Regularization | WRONG_PUNCH / WRONG_STATUS / WFH | Employee recorded IN at 10:30 by mistake; WRONG_PUNCH for IN 09:00 approved | Day re-evaluated from 09:00 | Punches become IN 09:00, IN 10:30, OUT 18:00 → INCOMPLETE (R-05). WRONG_STATUS and WFH approvals change nothing but mark the day regularized | `_apply_correction` inserts requested punches additively; punches have no supersede mechanism (only break events do); no handler for WRONG_PUNCH/WRONG_STATUS; WFH is a documented no-op | An approved correction makes the day worse, or shows as resolved while unchanged | Add `supersedes_punch_id` (like break events) and let WRONG_PUNCH void the named punch. Reject or hide WRONG_STATUS/WFH until they have defined effects. | CONFIRMED-CODE + engine run |
| R-07 | 🟠 | Leave accrual | Year-end ordering | LAPSE policy, 1.50/month; Dec accrual runs after the Jan 1 year-end (accrual failed at 01:00, repaired Jan 2 inside its window) | Balance 0.00 at year start | **1.50** survives the lapse | Year-end lapses the balance "as it stands" (`service.py:1904+`); the previous month's accrual, dated Dec 31, can be written later and nothing re-runs the lapse | Carry-forward caps and lapses silently exceeded | Year-end must refuse to run (or defer) until the previous month's accrual is written for that employee, or compute the lapse from entries dated before `year_start` and re-apply when a back-dated entry lands. | CONFIRMED-RUN (accrual-then-year-end 0.00, year-end-then-accrual 1.50) |
| R-08 | 🟡 | Leave accrual | Missed run | Worker or beat down on days 1–5 of a month | Accrual recovered when service resumes | Previous month's accrual never written; nothing alerts | `_accrue_company_async` returns 0 when `as_of.day > leave_accrual_run_window_days` (`leave/tasks.py`); `accrue_company` takes no `as_of`; `ops/job_health.py` does not watch leave jobs | Silent loss of a month's leave for a whole company | Make the run catch up every missing month since the last ACCRUAL cycle (it is idempotent already). Add an operator `as_of` path and a job-health check. | CONFIRMED-CODE |
| R-09 | 🟡 | Attendance | Recalculation | Holiday added for last week; shift version back-published; policy version published with past effective date | Affected unlocked days recalculated before payroll | Only today and 2 previous days are swept; validation and finalize do not detect stale days | `attendance/tasks.py:TRAILING_DAYS=3`; `_run_validation` has no staleness bucket; `calendar_impact.py` reports but never recomputes | Absent-on-a-holiday locked as LOP; old shift times used | Record a change watermark per employee-date range (calendar, shift, policy, assignment). Block finalize with `STALE_ATTENDANCE` until recomputed, or recompute inside finalize. | CONFIRMED-CODE |
| R-10 | 🟡 | Overtime | Rounding NEAREST | Rounding 30, excess 15 / 45 / 75 / 105 min | 30 / 60 / 90 / 120 (half-up) | **0 / 60 / 60 / 120** | `round_minutes` uses Python `round()` (banker's rounding), `calculation.py:1324` | Inconsistent OT pay at exact midpoints | Use `ROUND_HALF_UP` via `Decimal` or `(value + minutes // 2) // minutes * minutes`. | CONFIRMED-RUN |
| R-11 | 🟡 | Leave accrual | Probation | Confirmed on Sept 15; `accrue_during_probation=False` | Defined behaviour (prorate or skip probation days) | August skipped (still PROBATION on Sept 1); all of September accrued in full on Oct 1, including probation days | `_accrue_employee_month` reads current `employee.status`, not status during the period | Over- or under-accrual depending on run timing | Read probation dates (start/confirmation) and prorate the probation days out of the month. | CONFIRMED-CODE |
| R-12 | 🟡 | Leave | Cancel after year boundary | Leave in Dec approved, cancelled in Jan after year-end lapse | Credit returns to the year it was debited from, subject to that year's lapse | Full credit dated `business_today` in the new year; escapes the lapse/cap | `_reverse_approval` dates the ADJUSTMENT at today | Balance inflation via cancel | Date the reversal at the original debit date when that year is still open, otherwise apply the year-end rule to the restored amount. | CONFIRMED-CODE |
| R-13 | 🟡 | Leave | Partial cancel | Employee returns 3 days early from a 10-day leave | Cancel the remaining days | Only whole-application cancel; HR re-applying for taken days hits `max_backdated_days` (applied to on-behalf too) | No partial cancel API; backdate limit has no HR override | HR forced into manual ledger adjustments | Add "cancel from date" that cancels trailing day rows, projections and the matching ledger share. Exempt HR on-behalf from the backdate limit or give it an override permission. | CONFIRMED-CODE |
| R-14 | 🔵 | Leave | Stored-only fields | Maternity `pre_delivery_days`, `post_delivery_days`; `encashment_frequency`, `encashment_calculation_basis` | Enforced or hidden | Saved, never read. `max_encashment_days` is per request, so HR can encash repeatedly | No consumers outside create/schema | Policy appears enforced but is not | Enforce or hide; make the encashment cap per frequency window. | CONFIRMED-CODE |
| R-15 | 🔵 | Timezone | Server/UTC dates | 00:00–05:29 IST | Business date (IST) | UTC or server date used | `attendance/service.py:5105` regularization monthly cap (UTC month); `:3502` employment floor uses `punch_time.date()`; `schedule_service.py:553` and `schedule_router.py:56` `date.today()`; `break_override_service.py:227`; `geofence_service.py:96,466`; `organisation/calendar_setup.py:325` | Wrong month quota, refused on-behalf punch on joining night, swap date check off by a day | Replace with `business_today` / local-date conversion. | CONFIRMED-CODE |
| R-16 | 🔵 | Overtime | Late + OT | IN 10:00, OUT 19:30 | Decide | Late 45 (LATE) **and** OT 30 on the same day | OT = net worked − net schedule, independent of lateness | Policy conflict, not arithmetic error | Decide (D-11). | CONFIRMED-RUN / DECISION |
| R-17 | 🔵 | Grace | Grace semantics | Grace 15; IN 09:15:59; IN 09:16:00 | Documented | 09:15:59 → not late; 09:16 → `late_minutes = 1`, not 16 | Seconds floored; grace subtracted (`calculation.py:2025-2029`) | None if HR understands it; the UI says "after grace" | Keep; document in policy help that bands are post-grace and seconds are ignored. | CONFIRMED-RUN / DECISION |
| R-18 | 🔵 | Shift UI | Copy | Shifts page | Grace configured on the attendance policy | Page description says shifts hold "grace periods" | Legacy copy `web/src/app/app/shifts/page.tsx:186` | Admin confusion | Fix copy. | CONFIRMED-CODE |

### 3.2 Prior findings re-confirmed (2026-11-04 audit, same code)

| ID | Sev | Summary | This audit |
|---|---|---|---|
| F1 | 🟠 | FLEXIBLE lateness measured from `window_start`, so anyone arriving inside the window is late | Code unchanged; still no FLEX lateness test |
| F2 | 🟠 | OT approved before a backdated full-day leave is copied back onto the LEAVE day and paid at NORMAL; comp-off not reversed | Code unchanged |
| F3 | 🟠 | ON_DUTY on an unpaid off day gives paid 1.00 + unpaid-off 1.00, blocking period close | Code unchanged |
| F4 | 🟡 | Half-day leave discards penalties on the worked half and turns a missing punch into immediate 0.50 LOP | **Re-run:** 20 minutes worked + SECOND_HALF leave → paid 1.00; single IN + half-day leave → LEAVE, LOP 0.50 |
| F5 | 🟡 | FIRST_HALF leave marks the afternoon arrival late (feeds R-03/R-04 counters) | **Re-run:** IN 14:00 → `late_minutes=285`, `is_late=True` |
| F6 | 🟡 | Half-day leave + ON_DUTY → LEAVE, 0.50 LOP | Code unchanged |
| F7 | 🟡 | Leave ignores roster week-offs and later calendar changes | Code unchanged; same root as R-09 |
| F8 | 🟡 | Off-day OT is only minutes beyond the shift | **Re-run:** 9 h on a weekly off → OT 0; 11 h on a holiday → OT 120 |
| F9 | 🔵 | `GRADE_VIA_ASSIGNMENT` eligibility behaves as ALWAYS | Code unchanged |
| F10 | 🔵 | Forward-dated early-departure approval pre-creates a future day | Code unchanged |
| F11 | 🔵 | ON_DUTY + punched OT pays both | Code unchanged |

---

## 4. Policy conflict register

| ID | Rule A | Rule B | Conflict | Today | Recommended resolution |
|---|---|---|---|---|---|
| PC-1 | Sandwich rule | Weekly-off pattern with 2 off days | Rule cannot fire across a 2-day run | Under-deduction (R-01) | Run-based sandwich |
| PC-2 | Sandwich rule | Multiple applications | Rule depends on how the request is split | Bypass (R-02) | Cross-application check |
| PC-3 | Lates-to-half-day | Half-day leave | Leave half counted as a late (F5) | Inflated counter | Measure lateness from the worked half's start |
| PC-4 | Lates-to-half-day | Regularization | Earlier day corrected, later days stale (R-04) | Stale HALF_DAY | Dependent recompute |
| PC-5 | Overtime approval | Full-day leave | Approved OT outlives the leave (F2) | OT paid on leave day | Void OT on leave approval |
| PC-6 | Late arrival | Overtime | Same day is late and earns OT (R-16) | Both | Decision D-11 |
| PC-7 | Year-end lapse | Monthly accrual | Lapse runs before last month's accrual lands (R-07) | Balance leaks | Ordering guard |
| PC-8 | Leave cancellation | Year-end lapse | Credit lands after lapse (R-12) | Balance leaks | Date reversal to source year |
| PC-9 | Holiday/shift/policy change | Already calculated days | Old figures locked (R-09, F7) | Stale results | Staleness gate |
| PC-10 | ON_DUTY | Unpaid off day / half-day leave / OT | F3, F6, F11 | Close blocked / under-pay / double pay | Decisions D-4, D-5 |
| PC-11 | Regularization WRONG_PUNCH | Immutable punches | Correction cannot remove the wrong fact (R-06) | Day stays INCOMPLETE | Punch supersession |
| PC-12 | Holiday/weekly-off work | OT definition | Full off-day shift earns no OT or comp-off (F8) | 0 OT | Decision D-1 |

---

## 5. Edge case register

| # | Scenario | Expected | Actual | Handled? |
|---|---|---|---|---|
| E-1 | IN exactly 09:15 with grace 15 | Not late | Not late | ✅ |
| E-2 | IN 09:15:59 | Not late (minute resolution) | Not late | ✅ (seconds floored) |
| E-3 | IN 09:16 | Late | `late_minutes=1` (grace deducted) | ✅ by definition |
| E-4 | OUT 17:45 / 17:44, grace-out 15 | 17:45 not early; 17:44 early 1 | As expected | ✅ |
| E-5 | Late 60 vs 61 post-grace (10:15 vs 10:16) | Band edge LATE → HALF_DAY | LATE → HALF_DAY (paid 0.50) | ✅ |
| E-6 | Night shift 22:00–06:00, IN 22:16, OUT 06:00 next day | Late 1, date = shift start date | As expected | ✅ |
| E-7 | Night shift OUT 07:30 next day | OT 90 | OT 90 | ✅ |
| E-8 | IN 07:00 on 09:00 FIXED shift | Pre-shift not credited | Not credited, not OT | ✅ by design |
| E-9 | IN 07:00, OUT 08:30 (all before shift) | ABSENT | ABSENT | ✅ |
| E-10 | Duplicate IN within 60 s | Collapsed | Collapsed, PRESENT | ✅ |
| E-11 | Duplicate IN 5 minutes apart | PRESENT with review flag | INCOMPLETE | ❌ R-05 |
| E-12 | Extra OUT after OUT | PRESENT | INCOMPLETE | ❌ R-05 |
| E-13 | OUT only / IN only | INCOMPLETE | INCOMPLETE | ✅ |
| E-14 | Break longer than presence | Worked never negative | Worked 0, ABSENT | ✅ |
| E-15 | Two break STARTs before END | Prevented by service | Service refuses; engine would mark INCOMPLETE | ✅ (service lock + checks) |
| E-16 | Break START never ended on closed day | Needs review | INCOMPLETE | ✅ (harsh at lock; PAY-006 reminders) |
| E-17 | AUTO_DEDUCT lunch, 09:00–19:00 | OT 60 net of lunch | OT 60 | ✅ |
| E-18 | Fri–Mon leave, Sun-only weekly off, sandwich on | 4 days | 4 days (existing test) | ✅ |
| E-19 | Fri–Mon leave, Sat+Sun weekly off, sandwich on | 4 days | 2 days | ❌ R-01 |
| E-20 | Half-day on multi-day range | Rejected | Rejected by schema | ✅ |
| E-21 | Leave in closed period (approve/cancel) | Refused | Refused | ✅ |
| E-22 | Double approval / approve after cancel | Refused | Version check + status guard | ✅ |
| E-23 | Cancel twice / reverse twice | Once | Status guard + `already_reversed` guard | ✅ |
| E-24 | Accrual run twice same month | Once | Unique index `uq_leave_ledger_cycle_entry` | ✅ |
| E-25 | Accrual missed days 1–5 | Recovered | Lost | ❌ R-08 |
| E-26 | Feb 29 anniversary in non-leap year | Feb 28 | `_safe_date` clamps | ✅ |
| E-27 | Mid-month joiner accrual | Prorated by calendar days | Prorated, half-up to 0.01 | ✅ |
| E-28 | Accrual at 01:00 IST on the 1st | Previous IST month | `business_today` | ✅ |
| E-29 | Leave spanning year boundary | Split by year | One debit dated start date | ⚠ R-12 family |
| E-30 | Policy changes mid-range | Version per date | Version as of start date for whole range | ⚠ Low |

---

## 6. Test matrix (critical rules)

`Run` = executed in this audit. `Code` = traced. Status is today's result.

| ID | Rule | Input | Expected | Actual | Status |
|---|---|---|---|---|---|
| T-01 | Grace-in | 08:59 / 09:00 / 09:14 / 09:15 / 09:15:59 IN | Not late | Not late | PASS (Run) |
| T-02 | Grace-in | 09:16 IN | Late | Late 1 | PASS (Run) |
| T-03 | Late band edge | 10:15 / 10:16 IN | LATE / HALF_DAY | LATE / HALF_DAY | PASS (Run) |
| T-04 | Grace-out | 17:46 / 17:45 / 17:44 OUT | –/–/early 1 | As expected | PASS (Run) |
| T-05 | Early band edge | 16:45 / 16:44 OUT | EARLY / HALF_DAY | As expected | PASS (Run) |
| T-06 | Overnight late | 22:15 / 22:16 IN | –/late 1 | As expected | PASS (Run) |
| T-07 | Overnight OT | OUT 07:30 +1 | 90 | 90 | PASS (Run) |
| T-08 | Duplicate IN | IN, IN +5 min, OUT | PRESENT | INCOMPLETE | **FAIL** R-05 (Run) |
| T-09 | Extra OUT | IN, OUT, OUT +5 min | PRESENT | INCOMPLETE | **FAIL** R-05 (Run) |
| T-10 | Late + OT | 10:00–19:30 | Decide | late 45 + OT 30 | DECIDE (Run) |
| T-11 | OT rounding NEAREST/30 | +15/+45/+75/+105 | 30/60/90/120 | 0/60/60/120 | **FAIL** R-10 (Run) |
| T-12 | Weekly-off full shift | 09:00–18:00 Sunday | OT or comp-off (D-1) | 0 | **FAIL/DECIDE** F8 (Run) |
| T-13 | Lates-to-half-day = 3 | 3rd, 4th, 5th late | Per UI: only 3rd half-day | All half-day | **FAIL** R-03 (Run) |
| T-14 | Half-day leave lateness | FIRST_HALF leave, IN 14:00 | not late | late 285 | **FAIL** F5 (Run) |
| T-15 | Half-day leave penalties | SECOND_HALF leave, worked 20 min | 0.50 LOP (D-2) | paid 1.00 | **FAIL/DECIDE** F4 (Run) |
| T-16 | Full leave + OT punches | OT 0 | OT 0 | PASS (Run) |
| T-17 | Break > presence | worked ≥ 0 | 0 | PASS (Run) |
| T-18 | Sandwich, Sun-only off, Fri–Mon | 4 | 4 | PASS (existing test) |
| T-19 | Sandwich, Sat+Sun off, Fri–Mon | 4 | 2 | **FAIL** R-01 (Run) |
| T-20 | Sandwich, split Fri / Mon | 4 (if policy) | 2 | **FAIL** R-02 (Run) |
| T-21 | Year-end LAPSE then late accrual | 0.00 | 1.50 | **FAIL** R-07 (Run) |
| T-22 | Accrual then year-end LAPSE | 0.00 | 0.00 | PASS (Run) |
| T-23 | Accrual idempotent / concurrent | once | once | PASS (existing tests) |
| T-24 | Approval balance race | one debit wins | advisory lock | PASS (existing `test_leave_balance_races.py`) |
| T-25 | Approve/cancel in closed period | 409 | 409 | PASS (existing tests) |
| T-26 | WRONG_PUNCH approval | wrong punch replaced | added alongside | **FAIL** R-06 (Code) |
| T-27 | Holiday added for past week, then finalize | Day recalculated or close blocked | Locked stale | **FAIL** R-09 (Code) |
| T-28 | FLEX IN inside window | not late | late | **FAIL** F1 (Code, prior audit) |
| T-29 | OT approved, then backdated leave | OT voided | OT paid | **FAIL** F2 (Code, prior audit) |

The prior audit's 84 cases (`LV-*`, `LH-*`, `LO-*`, etc.) remain the regression list for F1–F11.

---

## 7. Data integrity risks

| Risk | Possible today? | Path | Guard present |
|---|---|---|---|
| Double leave deduction | No | Version-checked approval; one APPLICATION debit per approval | Optimistic version, per-employee leave-date lock, balance advisory lock |
| Double balance restoration | No | `already_reversed` guard on ADJUSTMENT by reference | Yes |
| Incorrect balance restoration | **Yes** | Credit dated today escapes lapse (R-12) | No |
| Duplicate accrual | No | Partial unique index on ACCRUAL/CARRY_FORWARD cycle | Yes |
| Skipped accrual | **Yes** | Run window (R-08) | No |
| Balance surviving lapse | **Yes** | Ordering (R-07) | No |
| Under-deducted leave | **Yes** | Sandwich (R-01, R-02) | No |
| Incorrect attendance records | **Yes** | R-05, R-06, F1, F4, F5 | No |
| Stale attendance locked | **Yes** | R-04, R-09 | Missing-row check only |
| Duplicate OT record | No | `overtime_record_attendance_day_id_unique` | Yes |
| OT paid on leave day | **Yes** | F2 | No |
| Duplicate day row | No | `attendance_day_unique (company, employee, date)` | Yes |
| Duplicate punch on retry | No | Idempotency key unique index; engine collapse within 60 s | Yes |
| Historical day changed by later policy edit | Only on explicit recompute | Versions are effective-dated and immutable after publish | Yes; recompute is the risk vector (R-09) |
| Locked day rewritten | No | Period lock on all mutation surfaces | Yes |
| Comp-off credit not reversed | **Yes** | F2 | No |

---

## 8. Recommended fixes (confirmed issues)

Each fix lists the code location, the change, side effects and the regression tests it needs.

**R-01 / R-02 Sandwich** — `leave/service.py:_compute_day_breakdown` (2344–2416).
* Change: replace the neighbour check with a run scan: for each maximal run of `working == 0` days, mark it consuming when the day before the run and the day after the run are consuming (inside the range, or covered by another active application of a sandwich-enabled type for R-02). Store which application "owns" a cross-application sandwich day so cancel can release it.
* Side effects: totals rise for existing patterns; balances of future-dated SUBMITTED applications must be re-checked at approval (already done under lock).
* Tests: Sat+Sun weekend; Fri holiday + weekend; leading/trailing off days not sandwiched; half-day weekly off Saturday; split applications; cancel of one side releases the sandwich days.

**R-03 / R-04 Lates counter** — `attendance/calculation.py:2077-2090`, `attendance/service.py:4408-4442`.
* Change: implement the decided rule (D-10). Exclude days whose `is_late` comes from a half-day leave (F5). After any recompute that flips `is_late` or excess-break state, enqueue recompute for later dates of that month.
* Side effects: more recompute load on regularization approval; acceptable (one employee, ≤ 30 days).
* Tests: 5 lates with count 3 under the chosen rule; regularize day 2 after day 10 computed; half-day leave not counted.

**R-05 / R-06 Pairing and corrections** — `calculation.py:pair_punches`, `_resolve_primary_status`; `service.py:_apply_correction`; punch model.
* Change: add `supersedes_punch_id` with a voiding correction; WRONG_PUNCH must name the punch it replaces. In pairing, when a same-direction punch is immediately followed by a valid pair, drop it and set a review flag instead of `missing_punch`. Apply punch-order checks to ADMIN with an explicit "allow out of order" flag.
* Side effects: snapshot shape changes; payroll unaffected except fewer false LOPs.
* Tests: IN-IN-OUT, IN-OUT-OUT, WRONG_PUNCH replacing a 10:30 IN with 09:00, MISSING_PUNCH that duplicates an existing IN.

**R-07 / R-08 / R-11 / R-12 Accrual and year-end** — `leave/tasks.py`, `leave/service.py:LeaveAccrualService`, `_reverse_approval`.
* Change: monthly run catches up every month since the last ACCRUAL cycle for each employee-type (bounded, idempotent). Year-end waits for the previous month's accrual, or recomputes the lapse when a back-dated credit lands before the leave-year start. Probation is prorated from employment dates. Reversals dated in a closed leave year are subjected to that year's rule.
* Side effects: first catch-up run after deploy may write historic rows; run a dry-run report first.
* Tests: missed window recovery; year-end before accrual; confirmation mid-month; cancel after year-end.

**R-09 Staleness** — `attendance/service.py:_run_validation`, organisation change services.
* Change: record `invalidated_from` per employee (or company) when calendar, shift version, policy version or assignment changes with a past effective date; validation adds a blocking `STALE_ATTENDANCE` bucket; offer "recompute affected" from the impact preview.
* Tests: holiday added for a past day → finalize blocked until recompute; recompute clears.

**R-10 Rounding** — `calculation.py:round_minutes`. Use half-up. Tests: midpoints at 15/45/75 for 30.

**R-13 Partial cancel**, **R-14 stored-only fields**, **R-15 timezone leftovers**, **R-18 copy** — as described in the register; each needs one targeted test.

For F1–F11 use the fix directions and tests in the 2026-11-04 audit, Sections 4–6.

---

## 9. Prioritized implementation plan

### Phase 0 — Critical data and payroll risks

* **Issues:** R-01, R-02, R-03, R-05, R-06, R-07, F1, F2.
* **Dependencies:** D-10 (lates rule) and D-8 (void OT on leave) must be answered first. R-06 needs a migration (`supersedes_punch_id`).
* **Order:** R-01 → R-02 (same function) → F2 → R-03 (after D-10) → F1 → R-05 → R-06 → R-07.
* **Regression:** full `tests/unit/modules/attendance`, `tests/integration/modules/leave`, `tests/integration/modules/attendance`, payroll run tests; prior audit cases LV-01…LV-18, LO-*.
* **Acceptance:** T-08, T-09, T-11, T-13, T-19, T-20, T-21, T-26, T-28, T-29 pass; no existing test regresses; one month of a pilot tenant recomputed with a diff report reviewed by HR.

### Phase 1 — Core policy logic bugs

* **Issues:** R-04, R-08, R-10, R-11, R-12, F3, F4, F5.
* **Dependencies:** D-2, D-3, D-4.
* **Order:** R-10 → R-08 → R-04 → F5 → F4 → F3 → R-11 → R-12.
* **Regression:** accrual and year-end suites; period finalize suites; half-day leave cases LH-01…LH-15.
* **Acceptance:** accrual recovers a simulated 10-day outage; recomputing an earlier day updates later counters; T-14, T-15 pass.

### Phase 2 — Cross-module rule conflicts

* **Issues:** R-09, F6, F7, F8, F11, R-16, PC-12.
* **Dependencies:** D-1, D-5, D-6, D-7, D-11.
* **Order:** R-09 (staleness gate) → F7 → F8 → F6 → F11 → R-16.
* **Regression:** calendar impact tests, roster tests, OT/comp-off tests.
* **Acceptance:** a holiday added for a past date blocks close until recompute; Sunday work earns the decided OT/comp-off.

### Phase 3 — Edge cases and boundaries

* **Issues:** R-13, R-15, F9, F10, E-29, E-30.
* **Order:** R-15 → R-13 → F9 → F10.
* **Acceptance:** each item has a passing boundary test at 23:59 / 00:00 / 00:01 IST where it applies.

### Phase 4 — Architecture and maintainability

* **Issues:** R-14, R-17 documentation, R-18, hidden-but-stored policy fields listed in the prior audit §3.3.
* **Work:** remove or enforce stored-only fields; one rules reference page generated from the engine's constants; job-health checks for every leave and attendance beat job.
* **Acceptance:** no policy field is accepted by the API without a consumer or an explicit "not yet enforced" flag.

---

## 10. Decisions needed

D-1 to D-9 from the 2026-11-04 audit stand. New:

| ID | Question | Recommended default |
|---|---|---|
| D-10 | "N late days = half day": every Nth late, or every late from the Nth? (R-03) | Every Nth late day (3rd, 6th, 9th), matching the web copy |
| D-11 | Can a day be both late and earn OT? (R-16) | Yes, but OT counts only minutes after `scheduled_end` when the employee arrived late |
| D-12 | Sandwich across separate applications? (R-02) | Yes, for the same sandwich-enabled leave type |
| D-13 | Probation accrual: skip, prorate, or credit retroactively on confirmation? (R-11) | Prorate out probation days; no retro credit unless the policy says so |
| D-14 | Missed accrual: auto catch-up or operator-only? (R-08) | Auto catch-up, with an alert |

---

## 11. What was verified correct

* Grace and band boundaries have no off-by-one-minute errors.
* Overnight shifts attribute to the start date; late/early/OT across midnight are right.
* Worked minutes never go negative; breaks are clipped to presence; auto-deducted lunch is excluded from the OT baseline.
* Pre-shift presence on FIXED shifts is neither credited nor OT, by design.
* Leave lifecycle: SUBMITTED → APPROVED/REJECTED/CANCELLED and APPROVED → CANCELLED only; double approval and double cancel are blocked by status and version checks.
* Balance check-then-debit is serialised by an advisory lock; approvals re-check under the lock; LOP excess is explicit.
* Accrual, carry-forward and comp-off credits are idempotent through partial unique indexes; year-end is claimed per employee.
* Accrual, year-end and comp-off expiry use the company's business date (IST), not UTC.
* All seven attendance mutation surfaces refuse closed periods; finalize holds an exclusive lock that leave approval shares.
* No business rule is enforced only in web or mobile; both display server-computed totals.

---

## 12. Final decision

## 🔴 NO-GO

Confirmed defects produce incorrect leave deductions (R-01, R-02), incorrect half-day LOP (R-03, F5), full-day LOP on worked days (R-05, R-06), overtime paid on leave days (F2), incorrect lateness for flexible shifts (F1) and leave balances that survive a lapse (R-07). These affect common Indian-HR configurations: a 5-day week, a "3 lates" rule, biometric or HR-entered punches, and backdated leave. After Phase 0 the system moves to **🟠 CONDITIONAL GO**, with Phase 1 required before multi-tenant payroll use.
