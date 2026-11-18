# Master Attendance Audit — Independent Verification (16 November 2026)

**Type:** read-only verification and planning. No application code, test, migration, database row
or policy was changed. Nothing was committed or pushed. The only files created are the five
documents named in section 10.
**Subject:** `MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md` (MA-01 to MA-36), its decision register,
trigger audit, scenario matrix and remaining-issues list, checked against the working tree of
branch `test` (engine 16, uncommitted).

---

## 1. Method and what "verified" means here

Three evidence tiers are used. They are not interchangeable.

| Tier | Meaning | What I did |
|---|---|---|
| **R** Reproduced here | I ran the pure engine (`calculation.evaluate_day`) with inputs I built myself, in this session, and saw the stated outcome | Probe script kept outside the repo; engine 16; read-only |
| **C** Code-confirmed here | I read the cited lines in the working tree and the claim follows from them | File and line named in the row |
| **A** Carried from the audit | The audit reports an API-level or integration reproduction. I did **not** re-run it: that needs a disposable database and Redis, and this pass was not allowed to create or write one. Where I could, I read the code path (tier C) | Marked "A (+C)" when both |
| **N** Not reproduced | My attempt did not give the audit's result | Stated with the reason |

I did **not** run: the integration and security suites, the web suite, Flutter, or any API probe.
I did run the pure unit suites for attendance and leave (below), because they need no database.

**State of the tree (matches the audit).** Branch `test`, HEAD `dd71571`, 33 modified tracked
files (+2,424/−246), 3 untracked migrations (`20261116090000`, `…100000`, `…110000`),
3 untracked SQL reports, `ENGINE_VERSION = 16` (HEAD has 14), working tree untouched by me.
The repo is mounted at `/media/varun/varun27/…` today (the `varun20` path is an empty stub).

**Tests run by me.**

| Run | Result |
|---|---|
| `pytest tests/unit/modules/attendance tests/unit/modules/leave` against a non-existent scratch DB URL and Redis index 14 (the suite's own guard refuses the shared dev stack; I did not override it) | **973 passed, 12 skipped, 0 failed** (29.6 s) |
| Engine probes, about 40 scenarios, engine 16 | Results in section 3 |

---

## 2. Verdict summary

| Verdict | Findings |
|---|---|
| **Confirmed, open, reproduced by me (R)** | MA-01, MA-04 (engine order), MA-05, MA-08, MA-09, MA-13, MA-16, MA-20, and the one-minute cliff (G2) |
| **Confirmed, open, code-confirmed by me (C)** | MA-02, MA-03, MA-06, MA-07, MA-10, MA-11, MA-12, MA-17, MA-23, MA-24, MA-27, MA-28, MA-30, MA-31, MA-32, MA-33, MA-34, MA-35, MA-36 |
| **Confirmed from the audit's evidence, mechanism read but not independently exercised** | MA-14 (see N below), MA-15, MA-18, MA-19, MA-21, MA-22, MA-25, MA-26, MA-29 |
| **Not reproduced (N)** | **MA-14**: my probe gave 480/480 (with lunch punches) and 540/540 (continuous punches), not 480 vs 540. Needs the audit's exact configuration (automatic break deduction) before it is accepted |
| **False positives** | None found. No finding was refuted |
| **Findings whose size is wrong in the audit** | MA-13 (boundary is 230, not 239), MA-09 (depends on net shift length), MA-27 (the blocker text is worse than reported), MA-05 (even exact attendance fails) |
| **New findings** | NF-1, NF-2 (section 5) |

No finding is downgraded. Three are **upgraded in impact** (MA-05, MA-13, MA-27), none in severity
class without an owner decision.

---

## 3. Engine probes run in this session

Engine 16. Shift 09:00–17:00 IST unless stated. Standard bands: `ABSENT 0–239`, `HALF_DAY 240–479`,
`PRESENT 480+`. Grace 10 in and out. `TZ` does not enter the pure engine.

| # | Scenario | Result | Finding |
|---|---|---|---|
| 1 | Bands `HALF_DAY 240–479`, `PRESENT 480+`; 30 minutes worked | `PRESENT`, paid 1.00, LOP 0.00 | MA-01 |
| 2 | Same punches, standard bands (control) | `ABSENT`, paid 0.00, LOP 1.00 | MA-01 |
| 3 | Bands `ABSENT 0–239`, `PRESENT 300+` (gap in the **middle**); 270 minutes worked | `PRESENT`, paid 1.00 | MA-01 (wider than reported, NF-2) |
| 4 | Working day, no punches, default policy | `INCOMPLETE`, paid 0.00, LOP 0.00 | MA-02 (first half) |
| 5 | 4-hour shift, worked 6 h | `HALF_DAY`, 0.50 / 0.50 | MA-05 |
| 6 | 4-hour shift, worked exactly the 4 hours | `HALF_DAY`, 0.50 / 0.50 | MA-05 (worse than reported) |
| 7 | Late band `LATE 1–59`; arrive 10:09 (69 min after start, 59 past grace) | `HALF_DAY`, 0.50 / 0.50 | MA-09 |
| 8 | Same band; arrive 09:59 | `PRESENT`, 1.00 | MA-09 |
| 9 | Late and early marks, arrive 09:59 and leave 16:59+ | `PRESENT`, 1.00 | MA-09 (two marks, one day) |
| 10 | Worked 229 / 230 / 231 minutes (leave early), "absent under 240" | `ABSENT` / `HALF_DAY` / `HALF_DAY` | MA-13: boundary is **230**, i.e. 240 − grace_out |
| 11 | Work 04:30–08:30 on a 09:00 FIXED shift | `ABSENT`, worked 0, LOP 1.00 | MA-20 |
| 12 | No late bands; arrive 09:10 / 09:11 | `PRESENT` / `HALF_DAY` | G2 (cliff) |
| 13 | Half-day leave, holiday / roster week-off / calendar weekly off, no punches | `LEAVE`, paid 0.50, LOP 0.50 in all three | MA-08 |
| 14 | Half-day leave, ordinary working day, no punches | `LEAVE`, 0.50 / 0.50 (a full no-show is `INCOMPLETE`) | MA-08 / H-07 (L11) |
| 15 | `calendar_day_type = None` (no calendar resolved) and a roster week-off, no punches | `CONFIG_ERROR` | MA-04 (order of checks) |
| 16 | No shift, IN on day 10, OUT on day 11 | `PRESENT`, 1,980 worked minutes | MA-16 |
| 17 | Weekly off with lunch **punches** 13:00/14:00 vs roster week-off, shift break defined | 480 / 480 | MA-14: not reproduced |
| 18 | Same, continuous 09:00–18:00 punches, `SHIFT_BREAK_MODES_ENABLED=true` | 540 / 540 | MA-14: not reproduced |

Probe 6 matters: a part-time employee who works the whole shift gets half a day's loss of pay. The
audit's wording ("6 hours worked") hid that the failure does not depend on overtime or extra
hours.

Probe 10 corrects MA-13. The audit says 239 minutes becomes `HALF_DAY`. True, but the real
boundary is 230 minutes on this template (grace_out = 10 gives credit of 10). On the flexible
template (grace 30) it is 210. Every employee who leaves early with a time shortfall between the
boundary and 240 is moved up a band.

---

## 4. Per-finding verification, MA-01 to MA-36

Columns follow the seven questions: **(1)** still exists, **(2)** root cause accurate, **(3)**
reproduced, **(4)** a test genuinely protects, **(5)** what it affects (A attendance status, P paid
fraction, LOP, L leave balance, O overtime, F period finalization), **(6)** already addressed
elsewhere, **(7)** migration, data correction or operational action.

### 4.1 High

| ID | 1 | 2 | 3 (tier) | 4 Test protection | 5 Affects | 6 Other fix | 7 Needs |
|---|---|---|---|---|---|---|---|
| **MA-01** | Yes | Yes. `_resolve_primary_status` (`calculation.py` ~3471) maps "no band matched" to `PRESENT`; `_validate_bands` (`service.py:267`) checks order and overlap only. **Wider than reported**: a gap in the middle pays the same (probe 3) | R (engine); API IP1 carried (A) | **None.** `test_policy_validation.py` has no gap or zero-start test, and `test_calculation._base_input` uses a single band `240+`, so the default is exercised and endorsed by tests | A, P, LOP, F (no blocker) | No | Validation (no migration). Read-only report of published versions with gaps or non-zero start. Owner confirmation H-01 |
| **MA-02** | Yes | Yes. `_apply_incomplete_lock_resolution` (`service.py` ~8247) takes **every** `INCOMPLETE` row, with no punch test; `TREAT_PRESENT` then gives 1.00 paid (line ~8287). Engine gives zero-punch day `INCOMPLETE` by default (probe 4) | C + R(first half); API IP2 carried (A) | **Partial and misleading.** `test_half_day_leave_close.py` covers `TREAT_PRESENT` only for an IN-only half-day-leave day. No test of a zero-punch day. `test_period_summary.py:141` hard-codes a `TREAT_PRESENT` row as 1.00 paid | A, P, LOP, F | AC-04 added lock withdrawal; did not touch this | Fix + decision H-02. Report of locked days with `TREAT_PRESENT`, no punches, 1.00 paid |
| **MA-03** | Yes | Yes. `_comp_off_facts` (`repository.py` ~2200) selects only `AUTO_APPROVED`/`APPROVED` records with `comp_off_minutes > 0`, so a record that is capped, pending, rejected or deleted simply stops being a fact; the credit already written is never touched. Reversal exists only for leave and ON_DUTY days (`_reverse_credit_for_leave`) | C; API IP10 carried (A) | **None for corrections.** `test_leave_comp_off_safety.py` covers fractional credits, version change, expiry boundary and concurrent sweeps | L, O. Not LOP | AC-01 (overtime decisions) is the cause of the exposed side effect, not a fix | Fix + decision H-03. Read-only ledger-vs-record report. Reversal as an `ADJUSTMENT` entry referencing the credit (the ledger CHECK has no reversal kind; no new type expected) |
| **MA-04** | Yes | Yes. `evaluate_day` returns `CONFIG_ERROR` at `calculation.py:1859`/`1863` **before** the roster week-off test at `1871` (probe 15). The upstream cause (no `SHIFT` candidate on a roster off day) is in `CalendarResolutionService._scope_candidates`, not re-read by me | R (order); API IP3 carried (A) | **None** for shift scope on a roster week-off | A, O, F (blocks close) | AR-01 fixed the company-scope case only | Fix + decision H-04. Report of employees with shift-scoped calendar or policy and any roster week-off row |
| **MA-05** | Yes | Yes, and decision P-05 is still open | R | None (and none possible until P-05 is decided) | A, P, LOP, O | AR-12 keeps the overtime; not the day | Decision P-05 first. Report of shifts shorter than the policy's full-day band |

### 4.2 Medium

| ID | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| **MA-06** | Yes | Yes. `_ensure_punch_date_open` (`service.py:2443`) accepts a punch unless its local date **and** the previous date are both closed; its docstring promises "at worst an orphan row" which does not happen when a locked day owns it | C; API IP9b carried (A) | None | A, P, LOP, F | None | Fix. Report of punches owned by a locked day but absent from that day's `computation_snapshot.inputs.punch_ids` |
| **MA-07** | Yes | Yes. `ShiftRosterService._queue_recalc` (`service.py:2831`) queues `[roster_date, roster_date]` | C; API IP7c carried (A) | `test_recalc_queue.py` and roster tests check the own date, not neighbours | A, P, O | Invariant C added the trigger, not the width | Fix. Re-queue of dates next to roster changes (operational, after fix) |
| **MA-08** | Yes | Yes. `_apply_leave_overlay` half-day branch; `weekly_off_fraction` is 0 on `NOT_EXPECTED` | R (three day kinds) | Suite asserts half-day leave on working days; none on a day that became a day off | P, LOP, L, F | P-E reconciles dated changes only | Fix + decision H-08. Report of leave projections of 0.50 on non-working days |
| **MA-09** | Yes | Yes, with a caveat: the effect needs a shift whose **net** length equals the full-day band (here 8 h). On a 9 h net shift the same arrival stays `PRESENT` (my first probe). So exposure is "shifts exactly at the band", which is the standard template | R | Unit tests encode the ceiling (`test_grace_band_credit.py`); none says the ceiling should be measured beyond grace | A, P, LOP | R-2 (the ceiling) is the cause | Decision D-01a/b, R-2. Template text must change or the rule must |
| **MA-10** | Yes | Yes. `update_employment` (`employee/service.py:1325–1402`) has no `request_recalc` and no closed-period test; `create_employment`, `terminate_employment` and `create_assignment` have | C | None | A, P, F | AR-09 covered the other three | Fix. Operational: none unless a legal-entity change has already happened (report) |
| **MA-11** | Yes | Yes. `LeaveCalendarReconciliationService.reconcile` is called from `create_adjustment` only (`leave/service.py:1455`) | C | None | L, F | None | Fix or document; decision L-09 |
| **MA-12** | Yes | Yes. `request_recalc` has no coalescing (`recalc.py`); `MAX_ATTEMPTS = 5` at line 43, abandoned only logged | C | Queue tests cover retry, not coalescing or surfacing | A (delay), performance | None | Fix; operational report of abandoned rows (`attendance_recalc_request` with `attempts >= 5 and last_error is not null`) |
| **MA-13** | Yes | Yes | R, **with a different number** (boundary 230, not 239) | N-02 unit tests assert the credit; none asserts it should not cross a band | A, P, LOP | N-02 introduced it | Decision H-05. Report of locked days within `grace` minutes under a band edge |
| **MA-20** | Yes | Yes (`clamp_pairs_to_start`) | R (engine); API IP7c carried (A) | `test_early_punch_credit.py` encodes the FIXED clamp | A, P, LOP | P-04 | Decision P-04 |
| **MA-26** | Plausible | Code only | Not measured | None | Performance | None | Measure before change (acceptance criteria) |
| **MA-27** | Yes | Yes. `apply_reviewed` calls `reconcile` only when the preview is actionable (`reconciliation.py:904–906`); `_close_obsolete_shortfalls` (line 1065, whose own docstring says it covers "the leave was cancelled") is therefore never reached; `list_open_shortfalls` has no application-status filter; `LeaveApplicationService.cancel` has no shortfall step | C; API carried (A) | None for cancel-after-shortfall | F, L | None | Fix. Report of open shortfalls whose application is not `APPROVED`. **See 6.3: the blocker text tells HR to "cancel the leave", which does not clear it** |
| **MA-28** | Yes | Yes (`calendar_overlay.py` ignores `is_active` by design) | C; API carried (A) | None | A, L | None | Decision H-30 |
| **MA-29** | Yes | Yes by reading approval | Carried | None | A, P | None | Fix |
| **MA-33** | Yes | Yes. `replace_for_day` (`repository.py` ~1985) raises `version` unconditionally; I saw no equality guard | C | None | O (operational) | None | Fix |
| **MA-34** | Yes | Yes. `OvertimeRecordService._get_reviewable` (`service.py:6946`) lets only `resolved_approver_manager_id` act at stage `MANAGER`; leave has a reassign endpoint (`leave/router.py:893`), overtime and regularization do not | C | None | O, F | None | Decision O-19. **Same defect in regularization: NF-1** |

### 4.3 Low and operational

| ID | Verdict | Evidence by me | Test protection | Affects | Needs |
|---|---|---|---|---|---|
| MA-14 | **Not reproduced (N)** | Probes 17–18: both paths gave identical overtime. The audit's repro needs a break configured for **automatic deduction**; I did not build one. Break modes are gated by `shift_break_modes_enabled` (`break_router.py:103`). Treat as plausible until reproduced | none | O | Reproduce first; decision O-06 |
| MA-15 | Open (mechanism read) | `classify_ot_day` takes `is_holiday`; `_off_day_is_paid` says a holiday on a weekly off "follows the holiday rule" for pay, so pay and overtime class are not aligned | none | O | Decision PD-CAL-2 |
| MA-16 | Open, **R** | Probe 16 | none | A, P | Decision H-16 |
| MA-17 | **Partially wrong location.** `calculate-range` refuses future dates (`service.py:4577`) and regularization refuses them (5933); the single-day path at ~4123 defaults to today and was reported by the audit to accept a future date (API IP6, carried) | — | none | A (rows), F (none: dates outside period) | Fix |
| MA-18 | Open, carried | Grants not re-queried | `test_runtime_role_grants.py` covers six tables only | integrity | Migration (Phase 4) |
| MA-19 | Open, mechanism visible in probes 13–14 | — | none | reports | Decision (label vs fraction) |
| MA-21 | Open, carried; `terminate_employment` has no closed-period read | — | none | A, F | Fix |
| MA-22 | Plausible, not examined | — | none | concurrency | Probe needed (Phase 4) |
| MA-23 | Open, C: `has_excess_break_exception` is stored (line 4855) and no blocker reads it | — | none | F | Decision C-12 |
| MA-24 | Open, C: `leave/decision_center.py:114`, `organisation/dashboard_insights.py:155`, `employee/schemas.py:100,367` | — | none | cosmetic/validation | Fix |
| MA-25 | Operational, carried | — | — | — | Commit and migrate |
| MA-30 | Open, C: revoke queues `max(effective_from, today)` (`break_override_service.py:260`) | — | none | A, P | Fix |
| MA-31 | Open, carried; `get_approved_for_date_and_type` uses `scalar_one_or_none` (`repository.py:1756`) | — | none | A, P (500 on approve) | Fix |
| MA-32 | Open, C: `reallocate_caps_after_decision` called only at `service.py:7178` and `7277` (approve, reject) | — | none | O | Decision O-20 |
| MA-35 | Open, **C**: web map has 8 labels (`attendance-period/types.ts` 65–74); the five missing are real blocker codes. Mobile not read | — | web tests do not check completeness | F (UX) | Fix |
| MA-36 | Open, carried | — | — | F | Build screens or change text |

---

## 5. New findings from this verification

| ID | Severity | Evidence | Finding |
|---|---|---|---|
| **NF-1** | Medium | C. `RegularizationRequestService._get_reviewable` (`service.py:6362–6391`) has the same identity-only rule at the `MANAGER` stage as overtime. `PENDING_REGULARIZATION` blocks close. No reassign or HR override exists. A departed manager stalls the period for regularizations as well as overtime | Widen O-19 to both. Fix them together |
| **NF-2** | High (widens MA-01) | R. Probe 3. A gap **inside** the hour bands (e.g. 240–299 uncovered) pays `PRESENT`, not only a non-zero start. The validation fix must check continuity, not just the first band |

Nothing in the audit was contradicted by anything else I read.

---

## 6. Corrections to the audit's own description

1. **MA-13 number.** 230, not 239 (probe 10).
2. **MA-09 exposure.** Needs net shift length equal to the full-day band. A 9-hour shift with no
   breaks (my first probe) shows `PRESENT`.
3. **MA-27 text.** The `LEAVE_BALANCE_SHORTFALL` blocker message says "resolve it in Leave before
   finalizing", and the code comment at `service.py:7836` says HR resolves it by "grant balance, or
   cancel the leave". Cancelling does not clear it (section 4.2). HR following the product's own
   instruction stays blocked.
4. **MA-14.** Not reproduced.
5. **MA-17.** The statement "a future date can be calculated" is true for the single-day
   endpoint only. Range and regularization already refuse it. The fix is one call site.
6. **Counts.** The audit states 2,301 unit tests passed overall; I confirm only the 973 in
   attendance and leave.

---

## 7. Earlier findings

Spot-verified by me are marked **V**. The rest are carried from the audit (**A**).

| ID | State today | Basis |
|---|---|---|
| AC-01 | Fixed; exposes MA-03 | A |
| AC-02 | Fixed | A |
| AC-03 / P-E | **Partially fixed**: dated changes reconcile; MA-08, MA-11, MA-27 remain | V (reconciliation read) |
| AC-04 | Fixed for lock withdrawal; `TREAT_PRESENT` side is MA-02 | V |
| AC-05, AC-06, AC-08, AC-09 | Fixed | A |
| AC-07 | Fixed: attendance policy publish calls `request_policy_version_recalc` (`service.py:984`, `1511`). The audit's "no dedicated test" for attendance publish is a test gap, not a code gap | V |
| AR-01 | Partial (MA-04) | A |
| AR-02 | Partial (MA-09, G2, decision R-2) | V (probes 7–12) |
| AR-03..AR-08, AR-11..AR-14, AR-16 | Fixed | A |
| AR-09 | **Partial**: `update_employment` still queues nothing (MA-10) | V |
| AR-10 | Partial (blocker, no auto-fix) | A |
| AR-15 | **Not fixed**: `work_on_leave_behaviour` still in `attendance/schemas.py:396, 436, 481` | V |
| AR-17 | Not fixed by design | A |
| R-1, R-4..R-8 | Fixed | A |
| R-2 | Open decision | V |
| R-3 | Operational gap (no screen) | A |
| P-01, P-04, P-05, P-10, P-11, P-12, P-14 | Open decisions | A |
| LV-01..03, LV-05..13 | Not fixed, **not re-reproduced by anyone since the leave audit**. Treated as unverified | A |
| LV-04 | Fixed | A |

---

## 8. Cross-check of the affected quantities

| Quantity | Findings that can make it wrong at lock with no blocker |
|---|---|
| Attendance status | MA-01, MA-02, MA-05, MA-09, MA-13, MA-16, MA-19, MA-20 |
| Paid-day fraction / LOP | MA-01, MA-02, MA-05, MA-08, MA-09, MA-13, MA-20 |
| Leave balance | MA-03 (comp-off), MA-11, MA-27, MA-28; LV-01..03 |
| Overtime | MA-03, MA-04, MA-14?, MA-15, MA-32, MA-33 |
| Period finalization blocked wrongly | MA-04, MA-27, MA-34, NF-1, MA-36 |
| Stale or lost data | MA-06, MA-07, MA-10, MA-29, MA-30 |

---

## 9. What this verification could not do

- It did not re-run any of the audit's API probes (IP1–IP10, C1-*). Where the audit's finding rests
  only on those, the tier is **A**. Phase 0 of the plan re-runs them against a disposable database
  as the first failing tests.
- No load, timing or two-session concurrency test.
- Flutter was not run (not installed); Dart code was not read by me.
- No real data exists (see memory note: test data only as of 5 November), so the historical-impact
  queries in `ATTENDANCE_HISTORICAL_DATA_IMPACT_PLAN.md` have not been run against anything.

## 10. Companion deliverables

`ATTENDANCE_REMEDIATION_PRIORITY_PLAN.md`, `ATTENDANCE_OWNER_DECISIONS_REQUIRED.md`,
`ATTENDANCE_HISTORICAL_DATA_IMPACT_PLAN.md`, `ATTENDANCE_RELEASE_ACCEPTANCE_CRITERIA.md`.
