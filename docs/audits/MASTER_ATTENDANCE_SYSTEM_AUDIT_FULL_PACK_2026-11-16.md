# Master Attendance System Audit — Full Pack (16 November 2026)

**Purpose of this file:** single concatenated pack of the six audit deliverables, for independent
verification by a reviewer or another AI. It is a verbatim assembly of the named source documents
below; it does not add findings beyond those sources.

**Audit constraints that applied when these documents were written:**
- Read-only. No application code, tests, migrations, policy configs or employee/attendance data
  were changed. Nothing was committed or pushed.
- Evidence classes used: REPRODUCED, CODE-CONFIRMED, PLAUSIBLE RISK, VERIFIED PASS, NOT VERIFIED,
  POLICY DECISION REQUIRED.
- Verdict in Part A: **NOT VERIFIED — IMPORTANT ISSUES REMAIN.**

**How to verify:** treat Part A as the primary report; Parts B–F are companions. Prefer checking
findings against the working tree on branch `test` (engine 16 uncommitted) rather than against
HEAD alone. Do not treat PLAUSIBLE RISK as a confirmed defect.

**Source documents (also present individually in this folder):**
1. `MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md` → Part A
2. `ATTENDANCE_POLICY_DECISION_REGISTER.md` → Part B
3. `ATTENDANCE_MODULE_DEPENDENCY_MATRIX.md` → Part C
4. `ATTENDANCE_CROSS_MODULE_SCENARIO_MATRIX.md` → Part D
5. `ATTENDANCE_RECALCULATION_TRIGGER_AUDIT.md` → Part E
6. `ATTENDANCE_REMAINING_ISSUES_AND_RISKS.md` → Part F

---

# Part A — Master report

# Master Attendance System Audit — 16 November 2026

**Written for:** product owner, technical architect, independent code reviewer, engineering team.
**Audit type:** read-only. No application code, test, migration, policy or data was changed. Nothing
was committed or pushed. The only files added are the six documents listed in section 15.

**Revision.** This report was first drafted by one audit session and then independently verified and
revised by a second session on the same day. The second pass re-ran every probe in fresh isolated
databases, re-ran the test suites, read the code behind every finding again, and added findings
MA-27 to MA-36. MA-03 is now reproduced. Where the two passes differed, this text follows what the
second pass observed.

**Companion documents (same folder):**
`ATTENDANCE_POLICY_DECISION_REGISTER.md`, `ATTENDANCE_MODULE_DEPENDENCY_MATRIX.md`,
`ATTENDANCE_CROSS_MODULE_SCENARIO_MATRIX.md`, `ATTENDANCE_RECALCULATION_TRIGGER_AUDIT.md`,
`ATTENDANCE_REMAINING_ISSUES_AND_RISKS.md`.

---

## 1. Executive summary

**Verdict: NOT VERIFIED — IMPORTANT ISSUES REMAIN.**

The calculation engine (version 16, uncommitted) is internally consistent and its results do not
depend on the server's timezone. Most of the earlier findings AC-01…AC-09, AR-01…AR-14 and R-1…R-8 have code
in the working tree that matches their stated fixes; the exceptions are listed in section 13. But
the system cannot yet be trusted to produce one correct result for every employee-date, for six
reasons:

1. **Configuration can silently pay for work that was not done.** Two were reproduced through the
   API: hour bands that do not start at zero pay a full day for 30 minutes of work (MA-01), and
   under "treat incomplete as present" an employee who never came in is paid in full at period
   lock (MA-02). Both settings are accepted by the API today; the second is offered in web and
   mobile.
2. **Comp-off credit does not follow overtime corrections** (MA-03, reproduced). Once credited,
   it stays when the overtime is later reduced, reopened, withdrawn at lock, or deleted and
   detected again, which credits a second time. In the probe, 180 minutes credited 0.38 day; the
   overtime was removed and the credit stayed; 30 minutes were detected again and 0.06 more was
   credited, leaving 0.44 day for 30 minutes of overtime.
3. **Some valid configurations produce a blocking error or wrong results.** A work calendar or
   attendance policy assigned by shift does not resolve on a roster week-off, so the day is
   `CONFIG_ERROR` and blocks period close (MA-04, reproduced). A part-time shift judged by full-day
   hour bands is a half day every day (MA-05, reproduced; decision P-05 still open).
4. **Results are stale between a change and period close in several cases** (MA-06, MA-07, MA-10,
   reproduced or code-confirmed): a checkout recorded after a period closed is counted nowhere and
   reported nowhere; a roster change recalculates only its own date while a neighbouring day keeps
   punches it no longer owns; a pay-basis change queues nothing.
5. **Period close can be blocked with no remedy in the product.** A leave shortfall stays open
   after its leave is cancelled, and the reconciliation operation then reports nothing to apply
   (MA-27, reproduced). Overtime waiting for a manager who has left can only be decided by that
   manager (MA-34). The calendar screens tell HR to "run leave reconciliation", which has no
   screen in web or mobile (MA-36).
6. **About 30 business rules are decided by code with no owner approval on record**
   (`ATTENDANCE_POLICY_DECISION_REGISTER.md`). Several change paid-day fractions. One newly
   found: deactivating a holiday calendar, work calendar or weekly-off pattern has no effect on
   any date (MA-28, reproduced).

Nothing in this audit found locked days being rewritten, tenant isolation failing, or ledger
entries being edited. Period close recalculates every unlocked day of the period first, which is
the main safety net: most stale states converge at close. The findings above are the cases where
close does not help, or where the result is wrong by rule rather than by staleness.

**What could not be verified:** the Flutter app (Flutter is not installed on this machine), any
behaviour at production data volumes, and concurrency beyond the existing tests.

### Findings at a glance

| ID | Severity | Evidence | One line |
|---|---|---|---|
| MA-01 | High | Reproduced (API, engine) | Hour bands with a gap: uncovered minutes default to `PRESENT`, full pay |
| MA-02 | High | Reproduced (API) | A no-show is `INCOMPLETE`; `TREAT_PRESENT` pays it in full at lock |
| MA-03 | High | Reproduced (API) | Comp-off credit is never reduced, reversed or deduplicated when overtime changes |
| MA-04 | High | Reproduced (API) | Shift-scoped calendar or policy does not resolve on a roster week-off: `CONFIG_ERROR` |
| MA-05 | High (part-time staff) | Reproduced (engine) | Short shift: full attendance is `HALF_DAY`, 0.50 loss of pay (P-05 open) |
| MA-06 | Medium | Reproduced (API) | Punch accepted after close and owned by a locked day: not counted, not reported |
| MA-07 | Medium | Reproduced (API) | Schedule change recalculates only its own date; neighbour keeps punches it no longer owns |
| MA-08 | Medium | Reproduced (API, engine) | Half-day leave on a day that became a day off shows 0.50 loss of pay until HR reconciles |
| MA-09 | Medium | Reproduced (engine) | A "late mark" of 50–59 minutes still costs half a day; template text says it does not |
| MA-10 | Medium | Code-confirmed; queue checked | Pay-basis and legal-entity edits queue no recalculation; legal-entity edit has no closed-period guard |
| MA-11 | Medium | Code-confirmed | Monthly accrual does not resolve an open leave shortfall; only an HR credit does |
| MA-12 | Medium | Code-confirmed; observed | Recalculation queue: no deduplication, abandoned requests are only logged |
| MA-13 | Medium | Reproduced (engine) | Grace lowers every hour-band threshold, even when the employee missed hours |
| MA-14 | Low–Medium | Reproduced (engine) | Weekly-off overtime is net of breaks; roster week-off overtime is gross |
| MA-15 | Low | Reproduced (engine) | Holiday falling on a weekly off pays the weekly-off overtime class |
| MA-16 | Low | Reproduced (engine) | No-shift day: a forgotten checkout pairs with the next day's, one 33-hour session |
| MA-17 | Low | Reproduced (API) | A future date can be calculated; the row is `INCOMPLETE` and the queue ignores it |
| MA-18 | Low | Code-confirmed (init script, migration) | `punch` and `overtime_action` are not append-only at database level |
| MA-19 | Low | Reproduced | Status label and paid fraction disagree on several day kinds |
| MA-20 | Medium | Reproduced (API) | FIXED shift: work wholly before shift start counts zero minutes, day is `ABSENT` (P-04) |
| MA-21 | Low | Code-confirmed | Termination or joining dated inside a closed period is accepted; locked days stay |
| MA-22 | Low | Plausible risk | Punch, regularization and overtime approval do not take the period-close lock |
| MA-23 | Low | Code-confirmed | Excess-break exceptions that need approval do not block period close |
| MA-24 | Low | Code-confirmed | Three server-date fallbacks (`date.today()`) remain |
| MA-25 | Operational | Verified | Dev database is four migrations behind; engine 16 is uncommitted; no reconciliation screen |
| MA-26 | Medium | Code-confirmed, not measured | Cascades and close-time checks scale poorly (section 12) |
| MA-27 | Medium–High | Reproduced (API) | Leave shortfall stays open after its leave is cancelled; blocks close; reconciliation shows nothing to apply |
| MA-28 | Medium | Reproduced (API) | Deactivated holiday calendar, work calendar or pattern still applies to every date and to leave counting |
| MA-29 | Medium | Code-confirmed | Regularization punches may fall a day either side; approval recalculates only its own date |
| MA-30 | Low–Medium | Code-confirmed | Break-override revocation recalculates from today only; revocation applies to past open days |
| MA-31 | Low | Reproduced (API) | Second ON_DUTY (or early-departure approval) for one date accepted at submit; approve fails with HTTP 500 |
| MA-32 | Low | Code-confirmed | Overtime withdrawn at lock does not hand its cap budget to later days |
| MA-33 | Low–Medium | Code-confirmed | Every recalculation rewrites a `PENDING` overtime record and raises its version; approvers hit stale-version errors |
| MA-34 | Medium | Code-confirmed | Manager-stage overtime: only the snapshotted manager can act; no reassignment or HR override; blocks close if the manager leaves |
| MA-35 | Low | Code-confirmed (web) | Web period screen has no labels for five blocker codes |
| MA-36 | Medium (operational) | Code-confirmed | No reconciliation or orphan-punch screen, yet calendar screens instruct HR to run reconciliation |

---

## 2. Repository state (Phase Zero)

| Item | State at audit time |
|---|---|
| Branch / HEAD | `test` at `dd71571`, level with `origin/test`; `main` is 9 commits behind `test` |
| Staged | nothing |
| Modified, tracked | 33 files, +2,424 / −246 (API, web, mobile, tests) |
| Untracked | 3 migrations, 3 SQL reports, `leave/reconciliation.py`, 13 test files, 10 mobile contract fixtures, 13 audit documents, `MOBILE_UX_NEXT_STEPS.md` |
| Engine version | `ENGINE_VERSION = 16` in the working tree; `14` at HEAD. Engine 15 was never committed |
| Migration head (code) | `20261116110000` (linear chain, one head) |
| Dev database (`hrms_dev`) | at `20261114090000`: **four migrations pending** (`20261115090000` shift remediation, `20261116090000`, `20261116100000`, `20261116110000`). Read with one `SELECT`; not written |
| Code/schema compatibility | The working-tree code needs head. On an older schema the first overtime supersede and period validation fail (reviewed in `ATTENDANCE_ENGINE_16_PRE_COMMIT_REVIEW`). A fresh database migrates to head cleanly (done twice in this audit) |
| Other sessions | Other Claude Code processes were running against this working tree. The newest file change before this audit was 15:12 IST. The tracked/untracked file list was identical before and after the audit (checksum of `git status --short`). The second pass confirmed the same branch, HEAD, modified-file list and migration head, and that the first session had stopped |

Everything below describes the **working tree**, not HEAD. None of the engine 16 work is committed.

---

## 3. Architecture overview

- **API:** FastAPI, SQLAlchemy async, PostgreSQL 16 with forced row-level security (107 of 127
  tables; the other 20 are platform and identity tables), Celery with Redis. Modules:
  `attendance`, `leave`, `organisation`, `employee`, `payroll`, `notification`, others.
- **Engine:** `attendance/calculation.py` (3,499 lines) is pure: no database access, no clock.
  `attendance/service.py` (8,970 lines) loads inputs, calls `evaluate_day`, and writes
  `attendance_day`, `attendance_break`, `overtime_record`.
- **Schedule:** `attendance/work_schedule.py` is the single resolution of the shift for a date.
- **Punch ownership:** `attendance/punch_ownership.py` (pure) and `ownership_service.py`.
- **Calendar:** `organisation/calendar_resolution.py` (pure classifier plus resolver).
- **Policy resolution:** `attendance/resolution.py`, using the calendar module's 8-level walk.
- **Recalculation queue:** `attendance/recalc.py`, table `attendance_recalc_request`, Celery task
  `attendance.process_recalc_requests_company`, Beat safety net every 5 minutes.
- **Leave:** `leave/service.py` (applications, ledger, accrual, comp-off), `leave/reconciliation.py`
  (P-E), projections written through `attendance.service.LeaveProjectionService`.
- **Period:** `AttendancePeriodService` in `attendance/service.py` (validate, finalize, reopen).
- **Clients:** Next.js web (`apps/web`) and Flutter mobile (`apps/mobile`). Both show a day's
  punches from `computation_snapshot.inputs.punch_ids`; neither recomputes status or pay.

### Scheduled jobs that affect attendance (Celery Beat, timezone `Asia/Kolkata`)

| Job | When | Effect |
|---|---|---|
| `attendance.run_daily_calculation` | 09:30 | Calculates today and the two days before, for every active employee |
| `attendance.run_recalc_requests` | every 5 min | Processes queued recalculation requests |
| `attendance.run_incomplete_reminders` | 10:00 | E-mails about `INCOMPLETE` days |
| `leave.run_monthly_accrual` | 01:00 | Monthly accrual (company business date) |
| `leave.run_comp_off_credit_sweep` | hourly | Comp-off credit from overtime records |
| `leave.run_comp_off_expiry_sweep` | 01:30 | Comp-off expiry |
| `leave.run_year_end_sweep` | 02:00 | Carry-forward, lapse, encashment |
| `employee.run_termination_access_sweep` | hourly at :15 | Revokes login after the last working day |

---

## 4. Module dependency map

```
employment (joining, last working day, pay basis, legal entity)
        |  population gate, period ownership, off-day pay
assignment (branch, department, designation, grade, shift)      roster (published rows)
        |  scope for policy + calendar, branch timezone              |  shift of the date,
        +-------------------------+----------------------------------+  week-off, holiday-working
                                  v
                    work schedule (one shift per date)
                                  |
   work calendar + holiday calendars + weekly-off pattern + exceptions --> day type
   attendance policy version (bands, grace, limits) ----------------------> rules
   overtime policy version (eligibility, caps, approval chain) -----------> overtime
   break overrides -------------------------------------------------------> breaks
   punches + dismissals --> ownership (this date and two neighbours each side)
   leave projections (approved leave) -------------------------------------> overlay
   approved regularizations (ON_DUTY, early-departure approval; corrections are punches)
   sibling days (month late / excess-break counts; week and month overtime already counted)
                                  |
                                  v
                         evaluate_day (pure)
                                  |
              attendance_day + attendance_break + overtime_record
                                  |
          period validate -> finalize (recalculate, resolve INCOMPLETE, freeze summary, lock)
                                  |
                 payroll reads only a CLOSED period's summary and payable overtime
```

The full mutation list is in `ATTENDANCE_MODULE_DEPENDENCY_MATRIX.md`.

---

## 5. How one employee-date is calculated

Source: `AttendanceDayService._calculate`, `_build_calculation_input`, `calculation.evaluate_day`.

1. **Guards.** The date must not be in a closed period of the employee's legal entity, and the
   existing row must not be locked. The row is locked `FOR UPDATE`.
2. **Employment.** No employment covering the date: `NOT_JOINED` or `EXITED` (0 paid, 0 loss of pay).
3. **Schedule.** Published roster row, else the assignment's shift, else none. A roster row with no
   shift never falls back to the assignment.
4. **Timezone.** Shift version zone, else branch zone, else company zone.
5. **Calendar.** Exception > holiday (first linked calendar wins) > weekly-off pattern > working.
   Not resolvable: `CONFIG_ERROR`.
6. **Policies.** Most specific assignment wins: employee, shift, designation, grade, department,
   branch, legal entity, company. The version is the published one effective on the date. No
   attendance policy: `CONFIG_ERROR`.
7. **Punches.** The punches this date owns after comparing its claim with two days each side.
8. **Sibling inputs.** Late and excess-break days earlier in the month; overtime already counted
   earlier in the week and month.
9. **Engine.** Order of decisions: employment gate → timezone check → calendar and policy present →
   roster week-off with no punches → no shift → not expected with no punches → pair punches →
   breaks → late / early → hour band (with grace and mark credit) → harshest verdict → overtime →
   overlays in this order: unpaid off-day, half-day weekly off, ON_DUTY, leave (leave wins).
10. **Overtime decision.** `_resolve_ot_decision` merges the fresh detection with any earlier
    decision (pending replaced; automatic re-derived; human kept, capped or reopened).
11. **Write.** Day row replaced, breaks replaced, overtime record synced, audit row written.
12. **Cascade.** If the day's late flag, excess-break flag or cap contribution changed, later
    unlocked days of the month (and week) are recalculated in date order in the same transaction.

Status precedence, highest first: `NOT_JOINED`/`EXITED` > `CONFIG_ERROR` > full-day `LEAVE` >
`ON_DUTY` > half-day leave result > `NOT_EXPECTED` > `INCOMPLETE` > harshest of hour band, late
band, early band, core hours, cumulative rule.

---

## 6. Critical and high-risk findings

Each finding follows the evidence standard of the audit brief. "Affects" lists attendance (A),
leave (L), overtime (O), paid-day fractions (P).

### MA-01 — Hour bands with a gap pay a full day (High · REPRODUCED, API and engine)

- **Module:** attendance policy, engine. **Affects:** A, P. Can cause incorrect attendance credit.
- **Where:** `calculation._resolve_primary_status` (lines 3471–3474: any worked minutes with no
  matching hour band become `PRESENT`); `service._validate_bands` (line 267: checks order and
  overlap only, not coverage from 0, not gaps).
- **Who:** every employee on a policy whose hour bands do not cover every minute count from 0.
- **Reproduction:** probe IP1. Publish a policy version with hour bands `HALF_DAY 240–479` and
  `PRESENT 480+` (accepted, HTTP 200). Punch 09:00–09:30 on a 09:00–18:00 shift. Calculate.
- **Expected:** not a full paid day; or the policy refused at publish.
- **Actual:** `PRESENT`, `paid_day_fraction 1.00`, `worked_minutes 30`. Engine probes H1 and H2
  give the same with a 500-minute early departure and no early band.
- **Root cause:** "no band matched" is treated as "nothing wrong". The repository's own test
  fixture (`tests/unit/modules/attendance/test_calculation.py::_base_input`) uses exactly such a
  one-band policy, so the default is exercised by tests without being noticed.
- **Historical data:** any unlocked or locked day on such a policy. The shipped templates cover
  from 0, so only hand-built policies are exposed. `late_mark_band_impact_report.sql` does not
  check for this.
- **Correction:** refuse to publish hour bands that do not start at 0 or leave a gap; treat
  "no band" as `CONFIG_ERROR` in the engine instead of `PRESENT`. Add a read-only report of
  published versions with gaps.
- **Decision needed:** none for the validation; owner to confirm `CONFIG_ERROR` over a default.
- **Regression test:** publish refused for gap and non-zero start; engine test for uncovered minutes.

### MA-02 — A no-show is paid in full under `TREAT_PRESENT` (High · REPRODUCED, API)

- **Module:** engine, period close. **Affects:** A, P. Can cause incorrect attendance credit.
- **Where:** `calculation._resolve_primary_status` (zero punches on an expected day is
  `INCOMPLETE` unless `missing_punch_behaviour = ABSENT`);
  `AttendancePeriodService._apply_incomplete_lock_resolution` (`TREAT_PRESENT` sets 1.00 paid for
  every `INCOMPLETE` row).
- **Reproduction:** probe IP2. Policy version with `incomplete_at_lock_behaviour = TREAT_PRESENT`.
  Employee does not punch at all. Calculate, create a one-day period, finalize (HTTP 200).
- **Actual:** locked row `attendance_status INCOMPLETE`, `paid_day_fraction 1.00`,
  `worked_minutes 0`; frozen summary `present_days 1.00`, `payable_days 1.00`.
- **Root cause:** "forgot to punch out" and "did not come" are the same status. The lock rule was
  written for the first and is applied to the second.
- **Who:** every employee on a policy with `TREAT_PRESENT` and the default
  `missing_punch_behaviour`. Web and mobile both offer `TREAT_PRESENT`.
- **Correction:** apply `TREAT_PRESENT` only to days with at least one punch, or make zero punches
  on an expected day `ABSENT` after the day's ownership window has closed.
- **Decision needed:** yes (register item H-02).
- **Regression test:** API test as IP2 with the corrected outcome; a second with an IN-only day.

### MA-03 — Comp-off credit does not follow overtime corrections (High · REPRODUCED, API)

- **Module:** leave (comp-off), overtime. **Affects:** L, O. Affects leave balance; no LOP effect.
- **Where:** `LeaveCompOffService.credit_company` (`leave/service.py` 2230–2300) writes one
  `COMP_OFF_CREDIT` per overtime record id and never revisits the amount.
  `_reverse_credit_for_leave` runs only for days that are now full-day leave or ON_DUTY
  (`AttendanceRepository._comp_off_facts`, `on_unpayable_day`).
- **Paths with no adjustment:**
  1. approved minutes capped by a correction (`_resolve_ot_decision`, kind `cap`): credit keeps the
     old amount;
  2. human decision reopened as `PENDING`: credit stays while nothing is approved;
  3. overtime withdrawn at lock (`_withdraw_overtime_at_lock`): record `REJECTED`, credit stays;
  4. automatic approval whose overtime disappears: `delete_for_day` deletes the record, the ledger
     row remains with a dangling reference; if overtime is detected again a new record id earns a
     **second** credit.
- **Also:** the hourly sweep credits before the period closes, so comp-off can be taken against
  overtime that is still open to correction.
- **Reproduction (API probe IP10, second pass):** overtime policy with comp-off instead of pay,
  automatic approval, comp-off leave type assigned.
  1. Punches give 180 minutes of overtime. The record is `AUTO_APPROVED` with 180 comp-off
     minutes. The comp-off credit sweep writes `COMP_OFF_CREDIT 0.38` against that record.
  2. A correction removes the overtime. The record is deleted (`delete_for_day`); the day is
     recalculated. **The balance stays 0.38**; no reversal is written.
  3. A further correction gives 30 minutes. A new record id is created and the sweep credits
     **0.06 more**. Balance 0.44 day for 30 minutes of overtime.
- **Expected:** balance 0.06 (or nothing until the period closes, if credit waits for close).
- **Correction:** reconcile credit to `overtime_record.comp_off_minutes` on every sweep (reverse
  the difference; reverse fully when the record is gone, rejected or pending), or credit only
  from locked days.
- **Decision needed:** when comp-off becomes usable (at approval, or at period close).
- **Historical data:** existing comp-off balances may already exceed the overtime behind them.
  A read-only query comparing `COMP_OFF_CREDIT` ledger entries with the current
  `overtime_record.comp_off_minutes` (and records that no longer exist) finds them.
- **Regression tests:** cap after credit; reopen after credit; lock withdrawal after credit;
  delete and re-detect (the IP10 sequence).

### MA-04 — Shift-scoped calendar or policy fails on a roster week-off (High · REPRODUCED, API)

- **Module:** policy resolution, roster, engine. **Affects:** A, O, period close.
- **Where:** `CalendarResolutionService._scope_candidates` adds the `SHIFT` candidate from
  `shift_id_for(assignment, roster_entry)`; a roster week-off row has no shift, so no `SHIFT`
  candidate exists that day. `evaluate_day` returns `CONFIG_ERROR` for an unresolved calendar or
  policy **before** it looks at the roster week-off.
- **Reproduction:** probe IP3. Work calendar and attendance policy assigned with scope `SHIFT`.
  Normal day: `PRESENT`. Publish a roster week-off for another day and calculate it.
- **Actual:** `CONFIG_ERROR`, `calendar_day_type null`. Engine probe O8 shows the same order.
- **Impact:** every rostered day off for such employees blocks period close (`CONFIG_ERROR` has no
  lock-time resolution). With only the overtime policy shift-scoped, work on a roster week-off
  earns no overtime (no policy resolves), which defeats AR-01.
- **Correction:** on a roster row without a shift, use the assignment's shift for the `SHIFT`
  scope (as AR-01 already does for the overtime-eligibility flag), or evaluate the roster week-off
  before the calendar check when there are no punches.
- **Decision needed:** which shift's policy governs a rostered day off.
- **Regression test:** IP3 with the corrected outcome, with and without punches.

### MA-05 — Short shifts: full attendance is a half day (High for part-time · REPRODUCED, engine)

- **Where:** hour bands are fixed minutes on the attendance policy, not a share of the shift
  (`_evaluate_fixed_or_flex`, `lookup_band`). Decision P-05 is still open.
- **Reproduction:** engine probe O20. Shift 09:00–13:00, standard 8-hour bands, worked 09:00–15:00.
- **Actual:** `HALF_DAY`, 0.50 paid, 0.50 loss of pay, 120 minutes overtime (AR-12 keeps the
  overtime). The employee loses half a day's pay every day they work their full shift.
- **Correction:** needs P-05 (bands as a share of the scheduled minutes, or a policy per shift
  length enforced at assignment).
- **Operational workaround today:** a separate attendance policy assigned by shift. Note MA-04.

---

## 7. Medium-risk findings

### MA-06 — A punch accepted after close and owned by a locked day is lost (REPRODUCED, API)

- **Where:** `_ensure_punch_date_open` accepts a punch unless its local date **and** the previous
  date are both closed. `PunchService._try_immediate_calculate` then fails on the locked day
  (log event `attendance_immediate_calculate_failed`), and the queued retry skips locked days.
  `list_orphaned_punches` reports only punches **no** day owns.
- **Reproduction:** probe IP9b. IN at 09:00, period closed (day locks as `INCOMPLETE`, 1.00 loss
  of pay). A checkout dated 01:00 the next morning is then recorded: HTTP 201.
- **Actual:** locked day unchanged (`worked_minutes 0`, loss of pay 1.00); orphan report returns 0;
  the next period has no blocker. Because both clients list a day's punches from the snapshot, the
  punch is also not shown on the day.
- **Note:** the docstring of `_ensure_punch_date_open` says such a punch "becomes, at worst, an
  orphan row for the Phase 8 report to surface". It does not.
- **Correction:** report punches owned by a locked day that are not in that day's snapshot
  (a new blocker on the next period, or an HR list), so HR can reopen or dismiss.
- **Regression test:** IP9b asserting the punch is reported.

### MA-07 — A schedule change recalculates only its own date (REPRODUCED, API)

- **Where:** `ShiftRosterService._queue_recalc` queues `[roster_date, roster_date]`;
  `create_assignment` queues from `effective_from`; neither includes the day before or after,
  although ownership compares two neighbours on each side.
- **Reproduction:** probe IP7c. Monday and Tuesday on a 09:00–18:00 shift; Tuesday holds a
  04:30–08:30 session. A roster row gives Monday a 20:00–04:00 shift.
- **Actual:** the queue held one request (`ROSTER_CHANGED` for Monday). After processing, Monday's
  snapshot lists 4 punches including Tuesday's session; Tuesday's stored row is untouched
  (calculation version unchanged, still lists the same 2 punches). A manual recalculation of
  Tuesday gives `INCOMPLETE` with 0 punches. The two rows disagree until the daily sweep
  (3 days back only), a punch, or period close.
- **Why it matters:** inside one period, close repairs it. If the neighbour is already locked in
  an earlier period it is never repaired. Until then both days show the same punches.
- **Correction:** widen every schedule-change request by the ownership neighbourhood (two days
  each side), or queue the dates whose owned punch set changed.
- **Regression test:** IP7c asserting Tuesday is recalculated.

### MA-08 — Half-day leave on a day that is off (REPRODUCED, engine and API)

- **Where:** `_apply_leave_overlay`, half-day branch: `remaining = 1 − leave − weekly_off`. On a
  `NOT_EXPECTED` result `weekly_off_fraction` is 0, so the unworked "other half" becomes loss of pay.
- **Reproduction:** engine L1–L3 (holiday, roster week-off, weekly off): `LEAVE`, 0.50 paid,
  0.50 loss of pay. API probe IP8: half-day leave approved, then a roster week-off published for
  the date. Row after: `LEAVE`, 0.50 paid, 0.50 loss of pay; leave balance still 19.50;
  `LEAVE_CALENDAR_MISMATCH` blocks close.
- **Impact:** wrong loss of pay is visible until HR runs the reconciliation operation (API only,
  no screen). It cannot be locked, because the blocker holds the period.
- **Second effect (L11):** on an ordinary day with half-day leave and no punches, the worked half
  is loss of pay at once, while a full no-show waits as `INCOMPLETE`. The two rules disagree.
- **Correction:** on a not-expected day a half-day leave should leave nothing to lose
  (`remaining = 0`); decide L11 (register item H-07).

### MA-09 — The late-mark ceiling is measured with grace included (REPRODUCED, engine)

- **Where:** `grace_band_credit_detail`: `raw` is minutes after shift start; the limit is
  `max(59, grace)`. The band is looked up on `late_minutes = raw − grace`.
- **Reproduction:** engine G1, grace 10, late band `LATE 1–59`. Arrive 10:09 (69 minutes after
  start, 59 beyond grace, classified `LATE`): `HALF_DAY`, 0.50 loss of pay. Arrive 09:59: `PRESENT`.
- **Consequence:** with the "Standard office" template a mark costs half a day from 50 minutes
  beyond grace; with "Flexible hours" (grace 30) from 30 minutes beyond grace. Both templates say
  "Late or early by under an hour is marked, not deducted" (web `templates.ts`, mobile
  `attendance_setup_configs.dart`). The record shows classification `LATE` and status `HALF_DAY`.
- **Other side:** the ceiling is per end. Arrive 09:59 and leave 17:01: 362 minutes worked of 480,
  two marks, `PRESENT`, full pay (reproduced).
- **Decision needed:** R-2 is still unconfirmed; this adds two questions (register D-01a, D-01b).

### MA-10 — Employment edits that queue nothing (CODE-CONFIRMED; queue checked)

- **Where:** `EmploymentService.update_employment` has no `request_recalc`. It can change
  `pay_basis` and `legal_entity_id`.
- **Evidence:** probe IP5: after `PATCH pay_basis = DAILY_WAGE` the queue was empty.
- **Effect of pay basis:** off-day pay (`_off_day_is_paid`) changes for every unlocked day; rows
  stay stale until the sweep, a punch or close. Close repairs it.
- **Effect of legal entity:** period ownership is derived from the employment's legal entity for
  the whole spell (`_owning_legal_entity`). Changing it moves every date of the spell, including
  dates locked under the old entity's closed periods, to the new entity. There is no check for
  closed periods. Not reproduced; the outcome for the new entity's open period is untested.
- **Correction:** queue from the joining date on a pay-basis change; refuse a legal-entity change
  when any closed period owns a date of the spell (or model it as a new employment).

### MA-11 — Accrual does not resolve a leave shortfall (CODE-CONFIRMED)

- **Where:** only `LeaveLedgerService.create_adjustment` (positive amount) calls
  `LeaveCalendarReconciliationService.reconcile` for open shortfalls. `LeaveAccrualService`,
  carry-forward and comp-off credit do not.
- **Effect:** after a holiday is removed and the balance is short, the shortfall stays open when
  the next accrual would cover it. Period close stays blocked until HR credits balance or runs the
  reconciliation operation.
- **Correction:** run the shortfall pass after any credit entry, or document the HR step.

### MA-12 — Recalculation queue: duplicates and silent abandonment (CODE-CONFIRMED; observed)

- **No deduplication.** `request_recalc` always inserts. Probe IP4: wiring one employee queued
  five overlapping requests from 1 January to today; processing them recalculated the same three
  rows five times (15 calculations).
- **Abandonment.** After 5 failed attempts a request is closed with an error and one `error` log
  line (`attendance_recalc_request_abandoned`). There is no screen, no notification and no close
  blocker. Period close recalculates the period's own days, so the effect is delay, except for
  days outside any period being closed.
- **Only existing rows.** The queue never creates a row. Dates without a row rely on the sweep
  (3 days), a punch, or `calculate-range`; `EMPLOYEES_WITHOUT_ATTENDANCE` catches them at close.
- **Correction:** coalesce pending requests with the same target and overlapping range; expose
  abandoned requests to HR or add a blocker.

### MA-13 — Grace lowers every hour-band threshold (REPRODUCED, engine)

- **Where:** `grace_band_credit_detail` credits `min(raw, grace)` at each end whenever the
  employee missed time at that end, however much.
- **Reproduction:** engine H3. Standard bands (`ABSENT` under 240). Worked 09:00–12:59, 239
  minutes, left 5 hours early: `HALF_DAY`, 0.50 paid. The 10-minute grace was credited.
- **Effect:** every threshold is lower by up to `grace_in + grace_out` (20 minutes on the standard
  template, 60 on the flexible one). This is how N-02 was written, but the consequence at the
  absent / half-day boundary is not in any decision record.
- **Decision needed:** register item H-05.

### MA-20 — FIXED shift: work before the shift counts as nothing (REPRODUCED, API)

- **Where:** `clamp_pairs_to_start` in `evaluate_presence_and_breaks` (P-04).
- **Reproduction:** probe IP7c "before" state: worked 04:30–08:30 on a 09:00–18:00 shift.
- **Actual:** `worked_minutes 0`, `ABSENT`, 1.00 loss of pay.
- **Decision needed:** P-04 remains open; this is its sharpest consequence.

### MA-26 — Performance and scale (CODE-CONFIRMED, not measured)

See section 12.

### MA-27 — A leave shortfall outlives its cancelled leave (Medium–High · REPRODUCED, API)

- **Module:** leave reconciliation. **Affects:** C, L.
- **Where:** `leave/reconciliation.py`: `list_open_shortfalls` has no application-status filter;
  `_close_obsolete_shortfalls` runs only inside `reconcile`; `apply_reviewed` skips `reconcile`
  when nothing is actionable. `LeaveApplicationService.cancel` never touches shortfalls.
- **Reproduction (C1-SHORTFALL-CANCEL):** approved leave that uses the whole balance; a holiday
  inside it is removed, the balance cannot cover the restored day, so a shortfall opens (correct,
  as in the suite test). The leave is then cancelled. Result: the shortfall is still `OPEN`;
  `LEAVE_BALANCE_SHORTFALL` still blocks the period; the reconciliation preview and apply return
  no change (`noop: true`) and the shortfall stays open. From the code, only a positive HR credit
  for that employee or a further calendar edit runs the pass that closes it (not exercised in the
  probe).
- **Expected:** cancelling or withdrawing the leave closes its shortfalls.
- **Impact:** period close blocked with no supported remedy; the blocker text sends HR to the
  wrong action. A positive HR credit "fixes" it but changes the balance for no reason.
- **Historical data:** query open shortfalls whose application is not `APPROVED`.
- **Correction:** close shortfalls in `cancel` and `withdraw`; filter `list_open_shortfalls` by
  application status.
- **Regression test:** the probe sequence above, asserting the shortfall closes and the period
  validates.

### MA-28 — Deactivated calendars still apply (Medium · REPRODUCED, API)

- **Module:** organisation calendars, leave. **Affects:** A, L.
- **Where:** `calendar_overlay.py` (docstring: the resolver deliberately ignores `is_active` on
  patterns, work calendars and holiday calendars); `HolidayCalendarRepository.list_by_ids` and
  `HolidayRepository.list_for_calendars` have no `is_active` filter.
  `calendar_setup._validate_references` refuses to link an inactive calendar, but
  `update_holiday_calendar` allows deactivating one that is linked, and queues a recalculation
  that changes nothing.
- **Reproduction (C1-INACTIVE-HOLIDAY-CAL):** a holiday calendar linked to the work calendar has
  a holiday on a Wednesday. The calendar is deactivated. A leave from Tuesday to Thursday still
  counts 2.00 days; the Wednesday is still a holiday.
- **Expected:** undefined (register H-30). Either deactivation is refused while linked, or it
  takes effect.
- **Impact:** an administrator who deactivates a calendar to stop its holidays sees no effect.

### MA-29 — Cross-date regularization recalculates one date (Medium · CODE-CONFIRMED)

- **Where:** `RegularizationRequestService.submit` accepts requested punches within one day either
  side of the request date (`service.py` around line 5945). Approval (around lines 6612–6686)
  inserts the punches and calculates only `row.attendance_date`.
- **Effect:** when an added punch is owned by the neighbouring date (for example a night-shift
  checkout), the neighbour keeps its old result until the sweep (three days back), a punch or
  period close.
- **Correction:** calculate every date whose ownership the inserted punches can touch, oldest
  first, in the approval transaction.
- **Regression test:** night shift, regularize the missing checkout after midnight, assert both
  dates.

### MA-33 — Pending overtime records churn on every recalculation (Low–Medium · CODE-CONFIRMED)

- **Where:** `_resolve_ot_decision` returns a frozen result only for non-`PENDING` records. For a
  `PENDING` record `_sync_overtime_record` always calls `replace_for_day`, which raises `version`,
  then inserts a `DETECTED` action and writes an `OVERTIME_DETECTED` audit entry
  (`service.py` 5630–5690; `repository.py` around line 2005). A manager's step in a two-step chain
  is kept when minutes are unchanged (lines 5446–5454).
- **Effect:** an approver who loaded the record before any recalculation of the day (the 09:30
  sweep for three days, a queued run, a punch, a cascade) gets a stale-version error and must
  reload. The record timeline fills with identical `DETECTED` rows.
- **Correction:** skip the rewrite when the derived values equal the stored ones.

### MA-34 — Manager-stage overtime has no way out (Medium · CODE-CONFIRMED)

- **Where:** `OvertimeRecordService._get_reviewable`: at the `MANAGER` stage only
  `resolved_approver_manager_id` may act; HR with company scope is refused. `_resolve_ot_decision`
  keeps that id across recalculations while the chain is unchanged. No reassignment endpoint
  exists. Leave has one (`test_leave_reassign_approver.py`).
- **Effect:** if the manager leaves or is unavailable, the record stays `PENDING` and
  `PENDING_OVERTIME_APPROVAL` blocks period close. The only workaround is to change the overtime
  policy's approval chain and recalculate, which affects every employee on the policy.
- **Decision:** register O-19.

### MA-36 — Operations the product asks for but does not offer (Medium, operational · CODE-CONFIRMED)

- Leave reconciliation (preview and apply) and orphan-punch dismissal exist only as API endpoints.
- Both calendar setup screens say period close "stops until HR runs leave reconciliation" (web
  `app/work-calendars/setup/page.tsx:405`; mobile `work_calendar_setup_screen.dart:349`).
- **Effect:** `LEAVE_CALENDAR_MISMATCH` and, with MA-27, `LEAVE_BALANCE_SHORTFALL` can only be
  cleared by someone calling the API.

---

## 8. Low-risk findings

| ID | Finding | Where | Evidence |
|---|---|---|---|
| MA-14 | Work on a calendar weekly off: overtime 480 for 09:00–18:00 (lunch deducted). Same punches on a roster week-off: 540 (gross). | `_evaluate_fixed_or_flex` vs `_evaluate_no_schedule` | Engine O1, O2 |
| MA-15 | A holiday on a weekly off stays `WEEKLY_OFF`; overtime uses the weekly-off rate row, not the holiday row. | `classify_work_calendar_date` (WD-05), `classify_ot_day` | Engine O4 |
| MA-16 | With no shift, an IN on day 1 and an OUT on day 2 pair into one 33-hour session owned by day 1 (`PRESENT`); day 2 has nothing. The N-03 split applies to shift days only. | `punch_ownership._outruns_owner` | Engine T8 |
| MA-17 | `POST /attendance/days/calculate` accepts a future date and writes an `INCOMPLETE` row. Queue requests are clamped to today, so such rows wait for the sweep. | `_calculate`, `request_recalc` | API IP6 |
| MA-18 | The runtime role can `UPDATE`/`DELETE` `punch`, `overtime_action`, `punch_dismissal`, `attendance_period_action`. `leave_ledger`, `leave_application_action` and `audit_log` are insert-only. "Punches are never mutated" and "overtime history is append-only" are code rules only. No unique index stops a second `APPLICATION` ledger debit for one leave application. | grants, indexes | Read-only query |
| MA-19 | Label and pay disagree: half weekly off worked 239 minutes is `ABSENT` with 0.50 paid; a lock-resolved day stays `INCOMPLETE` with 1.00 paid or 1.00 loss of pay; half-day leave plus a worked half is `HALF_DAY` with 1.00 paid. Reports that count by status will not match paid days. | overlays, lock resolution | Engine O10, L6; API IP2 |
| MA-21 | `terminate_employment` and `create_employment` accept dates inside a closed period. Days after the last working day stay locked as they were; days before a later joining date stay locked too. | `employee/service.py` | Code |
| MA-22 | `finalize` takes an exclusive advisory lock that only leave changes share. A punch, regularization approval or overtime decision racing a finalize is protected only by row locks and the closed-period check, which reads committed state. MA-06 shows the resulting state is silent. | `core/db/locks.py`, callers | Plausible |
| MA-23 | A break whose excess needs approval sets `has_excess_break_exception`, but `_run_validation` has no blocker for it. Unresolved breaks do block (they make the day `INCOMPLETE`). | `_run_validation` | Code |
| MA-24 | `date.today()` fallbacks: `leave/decision_center.py:114`, `organisation/dashboard_insights.py:155`, `employee/schemas.py:100, 367` (date-of-birth and joining-date validation). On a UTC server these are yesterday between 00:00 and 05:30 IST. Harmless: `organisation/service.py:1431, 4476` (only when the company row is missing) and `organisation/repository.py:734` (`CURRENT_DATE` in an informational count). | grep | Code |
| MA-25 | Operational state, see section 2. The leave reconciliation operation has no web or mobile screen (MA-36). | — | Verified |
| MA-30 | `break_override_service.revoke` queues recalculation from `max(effective_from, today)`, but `list_in_force` drops a revoked override for every date. Past open days keep the override's effect until the sweep or close. | `break_override_service.py`, `break_repository.list_in_force` | Code |
| MA-31 | A second ON_DUTY request for a date that already has an approved one is accepted (201). Approving it raises `MultipleResultsFound` in `get_approved_for_date_and_type` (`scalar_one_or_none`): HTTP 500, rolled back. The only unique index covers `SUBMITTED` requests. The same pattern applies to early-departure approvals. The day stays calculable. | `repository.py` around line 1735 | API probe C1-DOUBLE-ON-DUTY |
| MA-32 | `finalize` runs `_apply_incomplete_lock_resolution` (which withdraws overtime on days resolved absent) after the recalculation, and never calls `reallocate_caps_after_decision` (called only from approve and reject, lines 7178 and 7277). A `PENDING` record reserved cap budget (O-02), so later days of the same week or month lock with less overtime than they would have had. | `service.py` `finalize`, `_withdraw_overtime_at_lock` | Code |
| MA-35 | `ATTENDANCE_PERIOD_BLOCKING_REASON_LABELS` (web) has 8 of the 13 blocker codes; `PENDING_LEAVE`, `OVERTIME_INTEGRITY`, `LEAVE_BALANCE_SHORTFALL`, `LEAVE_CALENDAR_MISMATCH`, `ORPHAN_PUNCHES` show without a label. Mobile was reported to have the same gap (not read in this pass). | `apps/web/src/lib/attendance-period/types.ts` 65–74 | Code |
| C-17 | Break-event recalculation (`BreakService._recalculate`) is best effort; a failure is logged and nothing is queued, unlike punches. | `break_service.py` 739–757 | Code |

---

## 9. Module-by-module assessment

### 9.1 Schedule resolution and shifts

- One shift per date, deterministically: roster, else assignment, else none. Overlapping
  assignments, shift versions, policy versions and employments are refused by exclusion
  constraints; one roster row per employee-date by a unique index. **Verified.**
- A roster may be published for a past date; it queues that date only (MA-07).
- Snapshots: the day row stores shift, shift version, calendar, policy version ids and a
  computation snapshot with punch ids. A policy **version** is immutable once published, so a past
  result can be explained. A work calendar, weekly-off pattern and holiday list are **not**
  versioned: a past day's calendar inputs cannot be reproduced after an edit (register V-03).
- Shift types: FIXED and overnight FIXED verified by probes (N1–N4). SPLIT judged by block overlap
  and hours (S1–S5); no lateness (P-11). FLEXIBLE: no early departure, no night support (P-10).
- Shift decisions: see section 13.

### 9.2 Calendar, holidays, weekly offs

- Precedence verified by reading and unit tests: exception > holiday > weekly off > working.
- Optional and restricted holidays are working days unless the calendar flag says otherwise
  (PD-CAL-1, open). Holiday on a weekly off stays a weekly off (PD-CAL-2, open; MA-15).
- Mutations: every calendar mutation queues recalculation (AC-02, AR-08). Only dated changes
  reconcile leave. See the trigger audit.
- The active flag on holiday calendars, work calendars and weekly-off patterns is ignored by the
  resolver (MA-28, reproduced; register H-30).

### 9.3 Punch processing and ownership

- Ownership is a pure function of punches and claims. Midnight, 00:01, 05:29, overnight and
  forgotten-checkout cases behave as designed (T1–T7, T10, T11). **Verified pass**, with MA-16.
- Duplicate requests: unique `(company_id, idempotency_key)`. Same-direction punches within the
  policy window collapse; a stray within 30 minutes is dropped (hardcoded, register H-12).
- Corrections are synthetic punches via regularization; raw punches are not edited by code.
- After close: MA-06.

### 9.4 Attendance classification

- Boundaries verified (G1/G2, H3/H4): grace, grace + 1, 59/60, 239/240.
- The four required properties from the brief:
  - *A late mark must not create a second penalty.* Holds inside the ceiling; fails for marks of
    50–59 minutes (MA-09).
  - *An early mark must not override a full day unless configured.* Holds.
  - *A short duration must not become PRESENT because of a broad band.* Holds since R-2 (ceiling),
    but two marks still lift 362 minutes to a full day (MA-09), and a band gap does (MA-01).
  - *An absent day must never become HALF_DAY because of a late/early band.* Holds for marks; the
    plain grace credit can lift `ABSENT` to `HALF_DAY` (MA-13).

### 9.5 Leave

- Lifecycle read end to end: submit (breakdown from calendar and roster), approve (balance cover,
  loss-of-pay days, projection per day, one ledger debit), cancel (reverse), reconciliation.
- P-E / R-1: the early return is gone; the half lives on `leave_application.half_day`.
- Remaining: MA-08, MA-11, MA-27 (shortfall after cancel), LV-01…LV-13 except LV-04
  (section 13), no reconciliation screen (MA-36).
- Verified sound by the suite: approve and cancel are idempotent under concurrency (version guard
  and advisory locks); two HR users applying one reconciliation preview change the leave once;
  accrual credits once per cycle (unique ledger key).
- Balance and projection can still diverge for undated changes (roster, pattern, shift) until HR
  runs the operation; the close blocker prevents locking it.

### 9.6 Grace and attendance policy

- Grace is applied once per end to lateness, and once per end to the hour-band lookup. It is not
  consumed (there is no daily or monthly grace allowance). The monthly rule is
  `lates_to_half_day_count` (every Nth late day), counted on the calendar month.
- One-minute cliff for policies without late/early bands: **still present** (G2: 09:11 is
  `HALF_DAY`). Nothing warns the administrator.
- Templates: web and mobile match line for line (read, not run on mobile).

### 9.7 Overtime

- Detection, caps in date order, P-C handling of human decisions, lock withdrawal and re-derivation
  read and match the remediation documents. Approved cannot exceed detected (validated at approval
  and by the `OVERTIME_INTEGRITY` blocker).
- Remaining: MA-03 (comp-off), MA-04 (shift-scoped overtime policy on roster week-off), MA-14,
  MA-15, P-D (probe O5: a full holiday worked earns nothing), week = Monday–Sunday hardcoded,
  capped minutes are dropped without a record (probe O18).
- Second pass: MA-32 (lock withdrawal keeps cap budget reserved), MA-33 (pending records churn),
  MA-34 (manager stage has no way out), O-15 (republish keeps the old comp-off choice). Approval
  is otherwise safe: optimistic version check, closed-date guard, approved minutes cannot exceed
  detected, the day lock is taken before the record.

### 9.8 Breaks

- Read: `compute_breaks`, legacy gap matching, automatic deduction, overrides. Break overrides
  queue recalculation (AR-09). Break modes are disabled in production
  (`SHIFT_BREAK_MODES_ENABLED = false`), so automatic deduction is not reachable from the product
  today; the engine paths are tested only with the flag on.
- Second pass (code): revoking an override recalculates from today only (MA-30); a break
  correction's recalculation failure queues nothing (C-17); an excess-break exception awaiting
  approval does not block close (MA-23). Not probed.

### 9.9 Roster

- Create, publish, update, delete queue the roster date. Draft rows block close
  (`UNPUBLISHED_ROSTER`). Leave is not reconciled on roster change (P-12).
- Findings: MA-04, MA-07, MA-08.

### 9.10 Employment

- Joining date and last working day are immutable after entry; termination is one-way. Create and
  terminate queue recalculation (verified by IP4: days after the last working day became `EXITED`,
  and their punches raised `ORPHAN_PUNCHES`). Rehire is a new employment.
- Findings: MA-10, MA-21.

### 9.11 Regularization, ON_DUTY, comp-off

- Regularization: one open request per employee-date (unique index); approval inserts punches and
  recalculates; closed dates are refused by `_ensure_date_open`. Verified by the existing suite
  (AR-03 test path read). Approval recalculates only the request's date although punches may be
  a day either side (MA-29). An approved request cannot be revoked (register C-14).
- ON_DUTY: full-day only. "One approved request per date" is assumed by the code but not
  enforced: a second request is accepted and its approval fails with HTTP 500 (MA-31, reproduced).
  Overlay verified by probes L16–L20. Half-day ON_DUTY and multi-day requests do not exist. D-07
  is open.
- Comp-off: MA-03. Payable overtime and comp-off are kept apart by
  `comp_off_minutes_earned = 0` in the payroll query (read, not run).

### 9.12 Period validation and finalization

- Finalize recalculates every unlocked owned day, validates fresh, wins a version-guarded close,
  resolves `INCOMPLETE`, freezes the summary and locks. One transaction.
- Reopen unlocks without recalculating; a finalized payroll run forbids reopen.
- Blocker map: section 11.

---

## 10. Cross-module scenarios

All 35 required scenarios, with expected and actual results, are in
`ATTENDANCE_CROSS_MODULE_SCENARIO_MATRIX.md`. Summary after the second pass: 13 pass by probe or
by an existing test that ran, 14 expose a finding (a scenario that passes its main path but fails
a secondary one is counted here), 4 need a product decision, 1 is code-confirmed only, and 3 were
not executed (12 leave plus regularization, 15 shift change plus leave, 35 roster publication after
overtime approval). Eleven further scenarios found by this audit are listed at the end of that
document.

---

## 11. Period-close blockers

| Code | Created when | Cleared by | Supported remedy |
|---|---|---|---|
| `EMPLOYEES_WITHOUT_ATTENDANCE` | an employed date in the period has no row | calculating it | `calculate-range` |
| `CONFIG_ERROR` | a row is `CONFIG_ERROR` | fixing configuration and recalculating | yes, but see MA-04 |
| `WORK_ON_LEAVE_UNRESOLVED` | flagged row without resolution | cancel leave, or "keep leave" | "Keep leave" exists for full-day leave; for half-day leave the same endpoint is used |
| `PAID_LOP_MISMATCH` | paid + LOP + unpaid-off ≠ 1.00 | recalculation | recalculate |
| `INCOMPLETE_ATTENDANCE` | `INCOMPLETE` under `KEEP_INCOMPLETE` | regularization | yes |
| `PENDING_LEAVE` | a `SUBMITTED` application overlaps | decide or withdraw | yes |
| `PENDING_REGULARIZATION` | a `SUBMITTED` request in the period | decide | yes |
| `PENDING_OVERTIME_APPROVAL` | a `PENDING` record, unless the day will lock absent | decide | yes, except a manager-stage record whose manager has left (MA-34) |
| `OVERTIME_INTEGRITY` | approved > detected, or record ≠ day | recalculation | recalculate |
| `LEAVE_BALANCE_SHORTFALL` | open shortfall in the period | HR credit, or reconcile | API only; accrual does not clear it (MA-11); **cancelling the leave does not clear it either** (MA-27) |
| `LEAVE_CALENDAR_MISMATCH` | stored leave days ≠ current breakdown | reconciliation operation | **API only, no screen** |
| `UNPUBLISHED_ROSTER` | a `DRAFT` roster row in the period | publish or delete | yes |
| `ORPHAN_PUNCHES` | a punch no day owns | regularize or dismiss | yes |

Gaps: nothing blocks for a punch owned by a locked day (MA-06), an excess-break exception awaiting
approval (MA-23), an abandoned recalculation request (MA-12), or a no-show about to be paid under
`TREAT_PRESENT` (MA-02). Five of the thirteen codes have no label on the web period screen
(MA-35). Validation always reads rows recalculated in the same transaction by
`finalize`; the standalone `validate` endpoint reads stored rows and can therefore report `READY`
on stale rows. `finalize` does not trust it.

---

## 12. Security, data integrity and performance

**Tenant isolation.** 107 tables under forced row-level security with the tenant policy; the 20
without it are platform and identity tables. Every attendance, leave and organisation table
checked is forced. The security suite result is in section 14.

**Integrity constraints (read-only query on the audit database).** One `attendance_day` per
employee-date; one `overtime_record` per day; one projection per application-date; one
application-day per date; no overlapping assignments, employments, policy versions, shift versions
or attendance periods. Gaps: MA-18.

**Runtime role privileges (second pass).** The runtime role `hrms_app` gets
`SELECT, INSERT, UPDATE, DELETE` on every table from `infra/docker/postgres/init/002_app_role.sh`
(including default privileges for future tables). Migration `20261009090000` revokes `UPDATE`,
`DELETE` and `TRUNCATE` for `leave_ledger`, `leave_application_action` and `audit_log`;
migrations `20261019090000` and `20261021090000` do the same for `platform_audit_log` and
`email_log`, and `leave_year_end_run` is insert-only (`test_runtime_role_grants.py` checks these
six). Everything else, including `punch` and `overtime_action`, is writable by the runtime role
(MA-18). This is a known gap: the test's docstring records it as decision D11
(`docs/architecture/OBSERVABILITY_ARCHITECTURE.md` section 15), not yet approved. The same
docstring records that re-running the init script on a migrated database silently restores the
revoked rights; the test catches that.

The grants exist only in a database where the init script ran before the migrations. Default
privileges in Postgres are per database. A database created later, for example a new production
database migrated without the init script, gives `hrms_app` no table privileges at all, and the
application fails closed. CI applies the script first (`.github/workflows/ci.yml`, "Apply database
init scripts"). This audit's first integration run skipped that step by mistake; section 14
explains the effect.

**Integrity queries on test data.** The integrity report (`scripts/sql/attendance_integrity_report.sql`)
was not run against production-like data: none was available. Not verified. The report has no
query for MA-03 (comp-off credit above current overtime) or MA-27 (open shortfalls whose leave is
no longer approved); both would be worth adding.

**Performance (code-confirmed, not measured):**

1. `_recompute_later_days_of_month` recalculates up to two months of one employee's days inside
   the triggering request, holding a row lock on each until commit. A range recalculation calls
   it once per day whose counters or cap contribution changed: quadratic in days per employee.
2. A calendar-wide change (pattern, work calendar, holiday-calendar validity) queues from the
   oldest unlocked day to today for the whole company unless scoped to an employee or shift. Each
   employee-date is its own transaction, processed serially per company.
3. `request_recalc` does not coalesce (MA-12).
4. `_run_validation` loads every day row of the period, every overtime record, and calls
   `list_orphaned_punches`, which resolves five claims (each with a policy resolution) per
   employee per local date.
5. `_working_shares` and leave reconciliation resolve the calendar one date at a time.
6. One `calculate` issues roughly 40–60 queries (five claims, three policy resolutions with an
   8-level walk each, bands, counters, leave, regularization).

No load test was run. Lock order is ascending by date within an employee everywhere it was read,
which avoids deadlock cycles between calculations; timeouts are bounded and retried.

---

## 13. Historical finding verification

Status words follow the brief. "Suite" means the regression tests exist and ran in this audit's
own integration or unit run (section 14).

### AC-01 … AC-09

| ID | Status | Evidence |
|---|---|---|
| AC-01 | VERIFIED FIXED | `_resolve_ot_decision` read in full; suite. Open side effect: MA-03 (now reproduced, IP10) |
| AC-02 | VERIFIED FIXED | 11 `request_calendar_recalc` call sites read; suite |
| AC-03 / P-E | PARTIALLY FIXED | Dated changes reconcile. Undated changes: blocker plus API-only operation. MA-08, MA-11 |
| AC-04 | VERIFIED FIXED | `_withdraw_overtime_at_lock`; suite. `TREAT_PRESENT` path: MA-02 |
| AC-05 | VERIFIED FIXED | Engine L6–L15, F4–F6, S4–S5 |
| AC-06 | VERIFIED FIXED | Engine O2; AR-01 API test in suite |
| AC-07 | VERIFIED FIXED | `request_policy_version_recalc`; suite (overtime policy). Attendance policy publish has no dedicated test |
| AC-08 | VERIFIED FIXED (web) / NOT VERIFIED (mobile) | Web suite ran; Dart code read, not run |
| AC-09 | VERIFIED FIXED | `business_today(company.timezone)` |

### AR-01 … AR-17

| ID | Status | Evidence |
|---|---|---|
| AR-01 | PARTIALLY FIXED | Works with company-scoped policies (suite). Fails with shift-scoped overtime policy (MA-04). Gross minutes (MA-14) |
| AR-02 | PARTIALLY FIXED · POLICY DECISION REQUIRED | Mark credit and ceiling present (G1). Cliff remains without bands (G2). MA-09 |
| AR-03 | VERIFIED FIXED | Suite. Still recognised by reason text |
| AR-04 | VERIFIED FIXED | Suite (four orders, month boundary). Year boundary not tested |
| AR-05 | VERIFIED FIXED | `_resolve_primary_status`; unit suite |
| AR-06 | VERIFIED FIXED | Engine F4–F6, S4–S5. SPLIT with all blocks in one half: unchanged edge case |
| AR-07 | VERIFIED FIXED | Engine L10, L15 |
| AR-08 | VERIFIED FIXED | `model_fields_set`; suite |
| AR-09 | PARTIALLY FIXED | Create, terminate, break override covered (IP4). `update_employment` not (MA-10) |
| AR-10 | PARTIALLY FIXED | `PENDING_LEAVE` blocker present. Roster and shift drift: blocker only (P-12) |
| AR-11 | VERIFIED FIXED | Engine H9 plus `_resolve_ot_decision` hold |
| AR-12 | VERIFIED FIXED | Engine O20 (overtime kept). The half-day itself is MA-05 |
| AR-13 | VERIFIED FIXED | Engine O9–O11 |
| AR-14 | VERIFIED FIXED | `_evaluate_split`; unit suite |
| AR-15 | NOT FIXED | `work_on_leave_behaviour` is still accepted and stored and does nothing |
| AR-16 | VERIFIED FIXED | Paths corrected in the documents |
| AR-17 | NOT FIXED (by design) | Raising `ENGINE_VERSION` recalculates nothing |

### R-1 … R-8 (pre-commit review)

| ID | Status | Evidence |
|---|---|---|
| R-1 | VERIFIED FIXED | Early return removed; `half_day` column and backfill; suite. Rows fully released before the fix lost their half (none in dev) |
| R-2 | PARTIALLY FIXED · POLICY DECISION REQUIRED | 59-minute ceiling in the engine; unit suite. MA-09 |
| R-3 | PARTIALLY FIXED · OPERATIONAL GAP | Preview and apply endpoints exist; suite. No screen in web or mobile |
| R-4 | VERIFIED FIXED | Window logic read; suite |
| R-5 | VERIFIED FIXED | `reallocate_caps_after_decision` called from approve and reject; suite |
| R-6 | VERIFIED FIXED | `caps_configured` gate |
| R-7 | VERIFIED FIXED | Three outcome labels |
| R-8 | VERIFIED FIXED | `LEAVE_ADJUSTED_AUTOMATICALLY` / `LEAVE_NOT_RECALCULATED` |

### Shift-audit decisions

| ID | Status | What the code does today |
|---|---|---|
| P-01 | POLICY DECISION REQUIRED | The whole overnight shift takes the start date's day type (engine N4) |
| P-04 | POLICY DECISION REQUIRED | FIXED: early arrival not credited, even a whole early session (MA-20). FLEXIBLE: credited |
| P-05 | POLICY DECISION REQUIRED | Fixed-minute bands; MA-05 |
| P-10 | POLICY DECISION REQUIRED · NOT VERIFIED | Flexible: no early departure (F3); night flexible not tested |
| P-11 | POLICY DECISION REQUIRED | Split: no lateness or early departure; hours decide (S2) |
| P-12 | PARTIALLY IMPLEMENTED | Close blocker and API operation only |
| P-14 | NOT IMPLEMENTED | One roster row per employee-date; two shifts in a day are impossible |

### Leave-audit findings LV-01 … LV-13

`leave/service.py` differs from HEAD by 25 added lines (shortfall resolution on HR credit, storing
`half_day`). None of them touches these findings.

| ID | Status | Note |
|---|---|---|
| LV-01, LV-02, LV-03 | NOT FIXED | Year-end and cross-year logic unchanged; the debit is still dated at `start_date` |
| LV-04 | VERIFIED FIXED | `PENDING_LEAVE` blocker; suite |
| LV-05 … LV-13 | NOT FIXED | Unchanged code. Not re-reproduced in this audit: NOT VERIFIED individually, carried from the leave audit |

---

## 14. Test results

All runs used databases created only for this audit, migrated from empty to head. `hrms_dev` and
`hrms_test` were not used as write targets. `FACE_PROVIDER_COMPARISON_ENABLED=false` was set
because the local `.env` enables it.

| Check | Result |
|---|---|
| `alembic upgrade head` on an empty database | passed (first pass twice; second pass on `hrms_audit_c1`, `hrms_audit_c1_probe`, `hrms_audit_c1_rls`) |
| `pytest tests/unit` | **2,301 passed, 12 skipped, 1 failed** (`test_settings.py::test_development_has_no_explicit_origins_but_a_valid_fallback`, reads the local `.env` CORS setting; known). Same under `TZ=Asia/Kolkata` and `TZ=Pacific/Kiritimati` |
| `pytest tests/integration tests/security` | see below |
| Web `vitest run` (whole suite) | **151 files, 1,045 tests passed** |
| Web `tsc --noEmit` | passed |
| API `ruff check`, `ruff format --check`, `mypy src/hrms` | all passed (second pass) |
| Engine probe, 86 scenarios | identical output under `TZ=UTC`, `Asia/Kolkata`, `America/New_York` (second pass); first pass also matched under Los Angeles and Pacific/Kiritimati |
| API probes IP1–IP10 and C1-* | ran on isolated DBs; results in the scenario matrix. MA-03 upgraded to reproduced (IP10) |
| Flutter `analyze` / `test` | **not run**: Flutter is not installed on this machine |
| Web ESLint / `next build`, API `lint-imports` | not run in this audit |
| Load or timing tests | not run |

**Integration and security suite.**

- First pass (database `hrms_master_audit`, created without re-applying the Postgres init script):
  **2,595 passed, 40 skipped, 1 xfailed**, exit 0. Runtime-role grant tests were not exercised
  correctly on that database because `hrms_app` lacked DML (default privileges are per database;
  see section 12).
- Second pass (database `hrms_audit_c1_rls`, init scripts applied first exactly as CI does, then
  migrated to head): **2,595 passed, 40 skipped, 1 xfailed**, exit 0, 1,626 s. The 72 runtime-role
  and RLS tests that had failed on the mis-provisioned database all passed on this one.

Probe scripts lived only under `/tmp/audit_c1/` and were deleted after the report was written.
Audit databases are listed in section 15.

---

## 15. What this audit created

- Six documents under `docs/audits/` (this one and the five companions).
- Temporary databases on the local Postgres container, all dropped at the end of the audit:
  `hrms_master_audit`, `hrms_master_probe` (first pass), `hrms_audit_c1`, `hrms_audit_c1_probe`,
  `hrms_audit_c1_rls` (second pass). Temporary Redis indexes 9–15 and Celery DB indexes used for
  the same runs were left to expire; no durable Redis keys were written outside those indexes.
- Temporary probe scripts and logs under `/tmp/audit_c1/`, removed after writing this section.
- Nothing else in the repository. Application code, tests, migrations and data were not modified.
  The only audit deliverables are the six documents named in the header.

---

## 16. Readiness assessment

Scores are 0–10. A score does not offset a blocker in another row.

| # | Dimension | Score | Why |
|---|---|---|---|
| 1 | Attendance calculation correctness | 6 | Engine consistent and deterministic; MA-01, MA-02, MA-09, MA-13, MA-20 |
| 2 | Shift and schedule correctness | 6 | Single resolution, constraints hold; P-01, P-04, P-05, P-10, P-11, P-14 open; MA-05 |
| 3 | Leave calculation correctness | 4 | P-E works for dated changes; LV-01…03 and 05…13 open; MA-08, MA-11, MA-27 (reproduced), MA-28 (reproduced) |
| 4 | Grace and attendance policy correctness | 5 | Cliff remains without bands; ceiling semantics (MA-09); grace shifts thresholds (MA-13); H-29 |
| 5 | Overtime correctness | 5 | Decision handling sound and well tested; MA-03 now reproduced; MA-04, MA-14, MA-32, MA-33, MA-34, O-15, P-D |
| 6 | Calendar and weekly-off correctness | 6 | Precedence clear; calendar not versioned; active flag ignored (MA-28); PD-CAL-1/2 open |
| 7 | Roster correctness | 5 | MA-04, MA-07, P-12 |
| 8 | Punch ownership and processing | 7 | Deterministic and timezone-safe; MA-06, MA-16, MA-29 |
| 9 | Recalculation reliability | 5 | Broad trigger coverage; MA-07, MA-10, MA-12, MA-29, MA-30, C-17; relies on close |
| 10 | Policy versioning and precedence | 6 | Versions immutable and dated; MA-01, MA-04; calendars unversioned; O-15 |
| 11 | Period validation and finalization | 5 | Atomic, fail-closed; but blockers without a product remedy (MA-27, MA-34, MA-36); gaps in section 11; MA-02, MA-32 |
| 12 | Web / mobile / API consistency | 5 | Clients do not recompute; template values match; mobile not run; no reconciliation screen (MA-36); missing blocker labels (MA-35) |
| 13 | Database integrity | 7 | Strong uniqueness and overlap constraints; MA-18 |
| 14 | Security and tenant isolation | 8 | Forced RLS on every tenant table checked; security suite result in section 14 |
| 15 | Concurrency and idempotency | 6 | Row locks, ordered cascades, idempotency keys; MA-22; two-session races beyond the suite untested |
| 16 | Historical data protection | 7 | Locked days refused in every path read; MA-10 (legal entity), MA-21 |
| 17 | Test coverage | 6 | Large suite, all passing; several tests encode the MA-01 default; comp-off corrections, shift-scoped policies, post-close punches, cancel-after-shortfall and inactive calendars untested |
| 18 | Operational recovery | 4 | Queue retries and sweep; abandoned requests silent; no reconciliation or orphan-punch screen; no approver reassignment for overtime; no regularization revoke |

### Conclusion

**NOT VERIFIED — IMPORTANT ISSUES REMAIN.**

No finding shows locked payroll inputs being rewritten, tenant isolation failing, or ledger entries
being edited, so this is not "critical integrity". But MA-01 to MA-05 can each put a wrong
paid-day fraction or leave balance into a period that closes without any blocker; MA-27, MA-34
and MA-36 can stop a period from closing with no remedy in the product; and the decision register
lists about 30 rules that change pay or balances without owner approval. Attendance outputs are
not yet a stable input for a payroll audit.

The second, independent pass reached the same verdict. It found no reason to raise or lower it:
every reproduced finding of the first pass reproduced again, the code-confirmed ones were re-read
and still hold, MA-03 moved from code-confirmed to reproduced, none was refuted, and the new
findings (MA-27 to MA-36) are medium or low on their own.

### The final question

*Can the current HRMS reliably produce one deterministic, explainable, policy-compliant attendance
result for every employee and business date, whatever the shift type, roster, calendar, leave,
grace, overtime, breaks, regularization, employment changes, policy version, calculation order or
later corrections?*

**No.**

- **Deterministic:** yes for a given set of inputs, and independent of server timezone and of
  calculation order within a month. Not yet across a schedule change (MA-07), a punch after close
  (MA-06) or an employment edit (MA-10), where the stored result depends on what was recalculated.
- **Explainable:** mostly. Policy versions and punch ids are on the row. Calendar inputs are not
  versioned, and status labels disagree with pay on several day kinds (MA-19).
- **Policy-compliant:** not demonstrable. About 30 rules have no approved decision behind them,
  and five findings (MA-01 to MA-05) produce results no policy would intend.
- **After later corrections:** not reliably. Comp-off does not follow overtime corrections
  (MA-03); a revoked break override (MA-30) and a cross-date regularization (MA-29) leave stale
  days; a cancelled leave leaves its shortfall behind (MA-27).

**Before attendance can be trusted:** fix MA-01 to MA-04 and MA-27; decide P-05 (MA-05), O-19
(MA-34) and the items marked "blocks payroll audit" in the decision register; close MA-06, MA-07
and MA-10; build the reconciliation screen (MA-36); commit engine 16 with its migrations and run
the mobile suite in CI. The
ordered list is in `ATTENDANCE_REMAINING_ISSUES_AND_RISKS.md`.


---

# Part B — Policy decision register

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


---

# Part C — Module dependency matrix

# Attendance Module Dependency Matrix — 16 November 2026

**Written for:** architect and engineering team. Part of
`MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`. Describes the uncommitted working tree (engine 16).

Every module and operation that can change an attendance result, with what it should trigger and
what it triggers today. The mechanics of each trigger (transaction, queue, retry) are in
`ATTENDANCE_RECALCULATION_TRIGGER_AUDIT.md`.

**Status words:** OK = implemented and read in code (R = also exercised by a probe or a test that
ran in this audit). GAP = missing or incomplete, with the finding id. BY DESIGN = deliberately not
done, recorded as a decision.

**Column key:** Recalc = attendance recalculation of affected existing rows. Leave = approved
leave must be re-derived. OT = overtime decisions or caps may move. Close = what period close does
about it.

---

## 1. How each module feeds a day's result

| Module | Supplies | Read by | Stored on the day row |
|---|---|---|---|
| Employment | population gate, pay basis, legal entity (period ownership) | `_build_calculation_input`, `_PeriodScope` | status `NOT_JOINED`/`EXITED`; pay basis in snapshot |
| Employee assignment | shift, branch (timezone), department, designation, grade (policy scope), manager (overtime approver) | `WorkScheduleResolver`, `_scope_candidates`, `_resolve_ot_decision` | `shift_id`, `shift_version_id`, `timezone` |
| Shift and shift version | type, times, breaks, duty blocks, operates-on flags, overtime and night flags, timezone | `resolve_shift_schedule` | `shift_version_id`, scheduled start, end, minutes |
| Roster | shift of the date, week-off, working-this-holiday | `WorkScheduleResolver`, `_working_shares` | flags in snapshot |
| Shift swap | rewrites two roster rows on approval | `schedule_service` | through roster |
| Work calendar, holiday calendars, holidays, weekly-off pattern, exceptions | day type, holiday type and paid flag, weekly-off fraction | `CalendarResolutionService` | `work_calendar_id`, `calendar_day_type`, holiday name |
| Policy assignment | which calendar, weekly-off pattern, attendance, overtime, regularization, leave policy applies | `resolve_policy_assignment` | resolved version ids |
| Attendance policy version | grace, bands, punch limits, missing-punch and lock behaviour, cumulative rules | engine | `attendance_policy_version_id` |
| Overtime policy version | eligibility, minimum, rounding, caps, chain, comp-off, night mode, rate rows | engine, `_resolve_ot_decision` | `overtime_policy_version_id` |
| Regularization policy version | who may request and approve | regularization service | `regularization_policy_version_id` |
| Punches, dismissals | presence | `PunchOwnershipService` | punch ids in snapshot |
| Break events, break overrides | break figures | `break_service`, engine | `attendance_break` rows |
| Regularization | synthetic punches; ON_DUTY; early-departure approval | regularization service, engine inputs | `on_duty_regularization_id`, regularized flag |
| Leave | approved day projections (fraction, half, paid) | `LeaveProjectionService`, engine overlay | `leave_fraction` |
| Overtime decisions | approved minutes, comp-off | `OvertimeRecordService` | overtime columns |
| Sibling days | late and excess-break counts in the month; overtime counted earlier in week and month | repositories | `derived_inputs` in snapshot |
| Period | lock, lock-time resolution of `INCOMPLETE` | `AttendancePeriodService` | `is_locked`, period id, paid / LOP fractions |
| Notifications | none (output only) | — | — |
| Payroll | none (reads a closed period only; a finalized run forbids reopen) | — | — |

---

## 2. Mutation matrix

### Employment and employee

| Operation | People | Dates | Recalc | Leave | OT | Close | Status |
|---|---|---|---|---|---|---|---|
| Create employment (incl. rehire) | the employee | joining date → today | queued `EMPLOYMENT_CREATED` | — | — | recalculates in-period days | OK (R, IP4) |
| Terminate employment | the employee | day after last working day → today | queued `EMPLOYMENT_TERMINATED` | refused if leave exists after the date | records on exited days are re-derived | post-exit punches raise `ORPHAN_PUNCHES` | OK (R, IP4). No closed-period guard: GAP MA-21 |
| Edit employment: pay basis | the employee | whole spell | **none** | — | — | recalculates in-period days | GAP MA-10 (R, IP5) |
| Edit employment: legal entity | the employee | whole spell, including locked days | **none** | — | — | ownership of every date moves to another entity's periods | GAP MA-10 |
| Edit employment: probation end | the employee | — | not needed | accrual of later months | — | — | OK |
| Deactivate employee | the employee | — | none; the daily sweep skips inactive employees | — | — | missing rows raise `EMPLOYEES_WITHOUT_ATTENDANCE` | Plausible risk (reported by a code reading, not reproduced): a deactivated but still employed person blocks close until HR runs `calculate-range`; a terminated employee who stays `is_active` gets an `EXITED` row every day |
| New assignment (transfer, shift, grade, manager) | the employee | `effective_from` → end of the split range | queued `ASSIGNMENT_CREATED` | **none** (drift → blocker) | via recalculation | recalculates | OK for recalc; neighbour day GAP MA-07; leave BY DESIGN (P-12) |
| Manager change | the employee | — | none | pending approvals keep their approver; leave has a reassignment path | pending overtime keeps its approver; **no reassignment, no HR override at the manager stage** | a departed manager's records block `PENDING_OVERTIME_APPROVAL` | GAP MA-34 (code-confirmed) |

### Shift, roster, swap

| Operation | People | Dates | Recalc | Leave | OT | Close | Status |
|---|---|---|---|---|---|---|---|
| Publish shift version | days calculated on that shift | `effective_from` → today | queued `SHIFT_VERSION_PUBLISHED` (by `shift_id`) | none (blocker) | via recalculation | recalculates | OK; days that did not use the shift before are not matched; neighbour GAP MA-07 |
| Deactivate shift | — | — | none | — | — | — | Plausible risk (code reading, not reproduced): the engine does not read `Shift.is_active`, so assignments and roster rows keep resolving the shift; swaps do not check it |
| Roster create / update / publish / delete (published rows) | the employee | the roster date | queued `ROSTER_CHANGED` | none (blocker `LEAVE_CALENDAR_MISMATCH`) | via recalculation; P-C for human decisions | recalculates; draft rows block | OK (R); neighbour GAP MA-07 (R, IP7c); shift-scoped policy GAP MA-04 (R, IP3) |
| Shift swap approved | both employees | both dates | queued `SWAP_APPROVED` | none | via recalculation | recalculates | OK (read) |

### Calendar

| Operation | People | Dates | Recalc | Leave | OT | Close | Status |
|---|---|---|---|---|---|---|---|
| Holiday create / edit / deactivate | assignments of calendars linking it (company-wide if scoped wider than employee or shift) | old and new date | queued `HOLIDAY_CHANGED` | **reconciled in the same transaction** (refund, debit, shortfall) | via recalculation | recalculates; shortfall blocks | OK (R) |
| Calendar exception create / edit | the calendar's assignments | the date(s) | queued `CALENDAR_EXCEPTION_CHANGED` | reconciled | via recalculation | same | OK (R) |
| Holiday calendar validity / active | linked calendars | oldest unlocked day → today | queued `HOLIDAY_CALENDAR_CHANGED` | none (blocker) | via recalculation | recalculates | Validity: OK; leave BY DESIGN ("policy A", open). **Active flag: queued, but the resolver ignores it, so nothing changes** (MA-28, reproduced: C1-INACTIVE-HOLIDAY-CAL). The same holds for the work calendar and pattern active flags |
| Weekly-off pattern rules / active | calendars using it + `WEEKLY_OFF` assignments | oldest unlocked day → today | queued `WEEKLY_OFF_PATTERN_CHANGED` | none (blocker) | via recalculation | recalculates | OK (R); leave BY DESIGN |
| Work calendar pattern / links / restricted flag / active | its assignments | oldest unlocked day → today | queued `WORK_CALENDAR_CHANGED` | none (blocker) | via recalculation | recalculates | OK (R) |
| Policy assignment create / change / end (any kind) | the scope | from the assignment's start | queued `POLICY_ASSIGNMENT_CHANGED` | none (blocker) | via recalculation | recalculates | OK (read) |
| `CalendarImpactService.confirm` | as the method it calls | — | as above | as above | — | — | OK |

### Policies

| Operation | People | Dates | Recalc | OT | Status |
|---|---|---|---|---|---|
| Publish attendance policy version | the policy's assignments | `effective_from` → today | queued `POLICY_VERSION_PUBLISHED` | via recalculation | OK (read; no dedicated test) |
| Publish overtime policy version | the policy's assignments | `effective_from` → today | queued | human-approved minutes re-priced (O-15) | OK (R) |
| Publish regularization policy version | — | — | none | — | OK (does not affect results) |
| Publish leave policy version | — | — | none | — | OK; existing applications keep their version |
| Break override create | the employee | override start → today | queued `BREAK_OVERRIDE_CHANGED` | via recalculation | OK (R) |
| Break override revoke | the employee | **today onwards only** (`max(effective_from, today)`) | queued | via recalculation | GAP MA-30: revocation applies to past dates too, so open past days stay stale until the sweep or close |
| Grace change | is an attendance policy version | — | as above | — | OK |

### Punches, regularization, ON_DUTY

| Operation | Dates recalculated | How | OT | Close | Status |
|---|---|---|---|---|---|
| Punch created (self, on-behalf, face, manual day) | the punch's local date and its owning date | in-request, best effort; on failure queued `IMMEDIATE_CALCULATION_FAILED` | re-derived; caps cascade to later days | — | OK. A third day whose session changed owner: GAP (open since the shift audit). Punch owned by a locked day: GAP MA-06 (R, IP9b) |
| Orphan punch dismissed | none | — | — | clears `ORPHAN_PUNCHES` | OK (a dismissed punch was owned by no day) |
| Regularization approved (missing punch, correction, break correction) | the request's attendance date | in-request, required to succeed | re-derived; P-C | refused on a closed date | OK (R) for its own date. GAP MA-29 (code-confirmed): requested punches may be up to a day either side, and the other date is not recalculated. No revoke of an approved request (C-14) |
| Break correction applied | the date | in-request, best effort; on failure only logged | re-derived | — | GAP C-17: unlike a punch, a failure queues nothing |
| Regularization ON_DUTY / early-departure approval | the date | in-request | ON_DUTY zeroes overtime; decision kept dormant | — | OK (R). A second approved request of the same type for the date fails with HTTP 500 (MA-31, reproduced) |
| Regularization cancelled or rejected | — | nothing applied | — | pending ones block | OK |

### Leave

| Operation | Dates recalculated | Ledger | Projection | Close | Status |
|---|---|---|---|---|---|
| Leave approved (incl. AUTO chain at submit) | every leave day, in-request | one debit dated at start date | one per day | approval refused on a closed day; shares the close lock | OK (R) |
| Leave cancelled / reversed | every leave day, in-request | refund of what was debited | cancelled | refused on a closed day | OK (R) for days and ledger. GAP MA-27 (reproduced): an open shortfall for the leave stays open and keeps blocking close |
| Leave rejected / withdrawn | none | none | none | pending blocks | OK |
| HR balance credit | days of open shortfalls | adjustment; then debit of waiting days | added | clears `LEAVE_BALANCE_SHORTFALL` | OK (R) |
| Monthly accrual, carry-forward, comp-off credit | none | credit | none | open shortfalls stay open | GAP MA-11 |
| Reconciliation preview / apply | affected leave days | refund / debit / shortfall | synced | clears `LEAVE_CALENDAR_MISMATCH`; closed periods protected | OK (R); API only, no screen |
| Year-end sweep | none | carry-forward, lapse, encashment | — | — | LV-01…LV-03 open |

### Overtime and comp-off

| Operation | Effect on other days | Comp-off | Status |
|---|---|---|---|
| Approve in full | none | credit by hourly sweep | OK |
| Approve fewer minutes / reject | later days of the week and month re-allocated in the same transaction when a cap exists | — | OK (R) |
| Recalculation changes a decided record | supersede action; later days cascade | **credit not adjusted** | GAP MA-03 (reproduced, IP10) |
| Recalculation of a day with a `PENDING` record | record rewritten and version raised every time, even unchanged | — | GAP MA-33 |
| Withdrawn at lock | **freed cap budget not handed to later days** | **credit not reversed** | GAP MA-03, MA-32 |

### Period

| Operation | Effect | Status |
|---|---|---|
| Validate | reads stored rows; reports blockers | OK; can say `READY` on stale rows (finalize does not trust it) |
| Finalize | recalculates unlocked owned days, validates, resolves `INCOMPLETE`, freezes summary, locks | OK (R); `TREAT_PRESENT` GAP MA-02 |
| Reopen | unlocks; nothing recalculated until the next change or finalize | OK (R) |

---

## 3. Dependencies with no trigger at all

1. Employment pay-basis and legal-entity edits (MA-10).
2. A neighbouring day whose punches change owner after a schedule change (MA-07).
3. Accrual and other credits against an open leave shortfall (MA-11).
4. Comp-off credit against a changed overtime record (MA-03).
5. A punch owned by a locked day (MA-06).
6. Raising `ENGINE_VERSION` (by design; a range recalculation is the documented step).
7. Days with no row: the queue never creates one; the sweep covers three days back.
8. Past open days after a break override is revoked (MA-30).
9. The second date touched by a cross-date regularization (MA-29).
10. Later days of a capped week or month when overtime is withdrawn at lock (MA-32).
11. A leave shortfall after its leave is cancelled (MA-27).
12. Deactivating a holiday calendar, work calendar or weekly-off pattern: a recalculation is queued
    but resolves to the same result, because the active flag is ignored (MA-28).

Revised by a second, independent pass on the same day: items 8–12 and the rows that cite MA-27 to
MA-34 were added. Nothing this pass read contradicted the other rows.


---

# Part D — Cross-module scenario matrix

# Attendance Cross-Module Scenario Matrix — 16 November 2026

Companion to `MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`. Every scenario was run against the
**working tree** (engine 16, uncommitted) on databases created only for this audit. No development,
staging or production database was used.

## How to read this

**Result values**

| Result | Meaning |
|---|---|
| PASS | Ran in this audit and matched the expected result |
| FINDING | Ran in this audit; the result is wrong or incomplete. The finding id explains it |
| DECISION REQUIRED | Ran in this audit, but no approved product rule says what the result should be. The table shows what the code does; it does not call that right or wrong |
| CODE-CONFIRMED | Not run end to end; the outcome follows from code that was read |
| NOT EXECUTED | Neither run nor fully traced |

**Evidence sources**

- **Engine `<id>`:** the pure engine probe (`evaluate_day` with built inputs). 86 cases, run under
  server timezones UTC, Asia/Kolkata, America/New_York, America/Los_Angeles and Pacific/Kiritimati.
  The output was identical byte for byte in all of them.
- **API `IP<n>` / `C1-*`:** probe tests that call the HTTP API against an isolated database through
  the project's own test fixtures. They were kept outside the repository and deleted afterwards.
- **Suite `<file>::<test>`:** an existing repository test that ran and passed in this audit's
  integration run (section 14 of the master report).

**Common setup unless stated:** company in `Asia/Kolkata`; FIXED shift 09:00–18:00 with a 60-minute
unpaid lunch (480 expected minutes); grace 10 minutes at each end; standard hour bands (ABSENT under
240, HALF_DAY 240–479, PRESENT 480 and over); Monday–Friday work calendar; one active employment;
policies assigned at company scope.

## Summary

| Result | Count |
|---|---|
| PASS | 13 (3, 4, 5, 6, 17, 19, 20, 21, 24, 29, 30, 32, 33) |
| FINDING | 14 (1, 7, 8, 9, 10, 13, 16, 18, 23, 25, 26, 27, 28, 31) |
| DECISION REQUIRED | 4 (2, 11, 22, 34) |
| CODE-CONFIRMED | 1 (14) |
| NOT EXECUTED | 3 (12, 15, 35) |

A scenario that passes its main path but shows a defect on a secondary path is counted as FINDING.
Scenario 34 also shows a finding but is counted under its open decision.

---

## The 35 scenarios

### 1. Late arrival + grace + early departure — FINDING (MA-09) · DECISION REQUIRED (R-2)

- **Setup:** policy G1 has late and early "mark" bands for 1–59 minutes. Policy G2 has no late or
  early bands.
- **Punches and actual results (engine G1, G2):**

| Punches | G1 (mark bands) | G2 (no bands) |
|---|---|---|
| In 09:10 | PRESENT, 1.00 paid | PRESENT, 1.00 paid |
| In 09:11 | PRESENT, 1.00 paid, late 1 | HALF_DAY, 0.50 loss of pay |
| In 09:59, out 17:01 (both marks, 362 minutes worked) | PRESENT, 1.00 paid | HALF_DAY, 0.50 loss of pay |
| In 10:09 (late 59 after grace) | **HALF_DAY, 0.50 loss of pay** | HALF_DAY |

- **Expected:** no double penalty (met: two marks give one HALF_DAY, never ABSENT). A late
  arrival inside the "mark" band costs nothing.
- **Difference:** the band ceiling of 59 minutes is compared with lateness measured from shift
  start, including the grace, so arriving 50–59 minutes after grace ends still costs half a day
  (MA-09). In G2, one minute past grace costs half a day (the cliff, decision R-2).
- **Also:** in G1, 362 minutes worked is a full paid day, because mark   bands decide before hour
  bands. Whether this is intended is not on record (register D-01b).

### 2. Late arrival + half-day leave — DECISION REQUIRED

- **Setup:** half-day leave for the first half; the employee works the second half, arriving
  14:11 (grace + 1).
- **Actual:** with late bands (engine L8): HALF_DAY, 1.00 paid. Without late bands (engine L7):
  **HALF_DAY, 0.75 paid, 0.25 loss of pay.** The lateness cliff is applied to the worked half and
  costs a quarter day.
- **Expected:** undefined. The policy says nothing about lateness in the worked half of a half-day
  leave. Register item H-29.

### 3. Early departure + half-day leave — PASS (with bands)

- **Setup:** half-day leave for the second half; out at 12:49 (grace + 1); early bands configured.
- **Actual (engine L9):** HALF_DAY, 1.00 paid, early 1.
- **Not run:** the same without early bands. By symmetry with scenario 2 it costs a quarter day.

### 4. Half-day leave + flexible shift — PASS

- **Engine F4, F5, F6:** first-half leave plus 14:00–18:00 worked gives HALF_DAY, 1.00 paid.
  Second-half leave plus 360 worked gives 1.00 paid and 120 overtime. Leave plus 480 worked gives
  1.00 paid.
- **Note:** a flexible shift never measures early departure (engine F3, decision P-10).

### 5. Half-day leave + split shift — PASS

- **Engine S4, S5:** first-half leave plus block 2 worked gives 1.00 paid. Both blocks worked gives
  1.00 paid, with no double credit.

### 6. Half-day leave + overnight shift — PASS

- **Engine N2, N3:** 22:00–06:00 shift. First-half leave plus 02:00–06:00 worked gives 1.00 paid.
  Second-half leave plus 22:00–02:00 worked gives 1.00 paid.

### 7. Holiday + approved leave + holiday removal — FINDING (MA-27)

- **Suite:** `test_leave_calendar_reconciliation.py::test_a_holiday_removed_inside_approved_leave_debits_the_day`
  and `::test_a_holiday_added_inside_approved_leave_refunds_the_day` pass. When the balance is
  short, the shortfall is recorded as an exception, not loss of pay
  (`::test_a_shortfall_is_an_exception_not_loss_of_pay_and_hr_resolves_it_with_balance`).
- **Difference (API C1-SHORTFALL-CANCEL):** if the employee's leave is then **cancelled**, the
  shortfall stays `OPEN`. `LEAVE_BALANCE_SHORTFALL` keeps blocking period close, and the
  reconciliation operation reports nothing to apply. See MA-27.

### 8. Weekly off + approved leave + roster change — FINDING (MA-08)

- **Setup:** half-day leave approved on a working day. A roster row then makes that day a week-off.
- **Actual (API IP8):** the day shows `LEAVE` with **0.50 loss of pay**. The balance is unchanged
  at 19.50, and `LEAVE_CALENDAR_MISMATCH` blocks close until HR runs the API-only reconciliation.
- **Expected:** no loss of pay on a day off; half a day refunded, or the leave flagged without a
  pay effect.
- **Suite:** the full-day version is refunded by HR through reconciliation
  (`test_leave_reconciliation_operation.py::test_a_published_roster_day_off_after_approval_is_refunded_by_hr`).

### 9. Roster weekly off + punches + overtime — FINDING (MA-04, MA-14)

- **Suite:** `test_attendance_rules_remediation.py::test_roster_week_off_work_is_weekly_off_overtime_held_for_approval`
  passes: work on a roster week-off is weekly-off overtime held for approval.
- **Difference 1 (API IP3, engine O8):** if the work calendar or attendance policy is assigned to
  the shift, the roster week-off has no shift, nothing resolves, and the day is `CONFIG_ERROR`,
  which blocks close (MA-04).
- **Difference 2 (engine O1, O2):** the same 09:00–18:00 punches give 480 overtime minutes on a
  calendar weekly off (lunch deducted) and 540 on a roster week-off (no lunch deducted) (MA-14).

### 10. Holiday + punches + overtime — FINDING (MA-15) · DECISION REQUIRED (P-D)

- **Engine O3:** holiday, 09:00–18:00 gives PRESENT, 480 overtime, class HOLIDAY. Pass.
- **Engine O4:** a holiday on a weekly off is paid at the weekly-off rate, not the holiday rate
  (MA-15).
- **Engine O5:** the shift is not overtime-eligible, so holiday work earns nothing (decision P-D).
- **Engine O6:** holiday, IN punch only gives `NOT_EXPECTED`, 1.00 paid. The forgotten checkout
  is not flagged.

### 11. Leave + punches during leave — DECISION REQUIRED (AR-15)

- **Engine L13:** full-day leave with 09:00–20:00 punches gives LEAVE, 1.00 paid, no overtime.
  The day is flagged for HR (`WORK_ON_LEAVE_UNRESOLVED`).
- **Suite:** `test_leave_projection.py::test_full_day_leave_keep_leave_behaviour_overrides_punches`,
  `test_leave_overtime_interaction.py` (three tests) pass.
- **Undefined:** the policy field `work_on_leave_behaviour` is accepted and stored, but the engine
  ignores it (AR-15). Whether overtime is earned on a leave day is not decided.

### 12. Leave + regularization — NOT EXECUTED

- **From the code:** the leave overlay runs after punches are assembled, so a regularized punch on
  a full-day leave day produces `LEAVE` plus the work-on-leave flag, as in scenario 11.
  Regularization does not cancel leave. Not run end to end.

### 13. Leave cancellation after attendance calculation — FINDING (MA-27)

- **Attendance:** cancelling recalculates the days (suite: `test_leave_balance_races.py`,
  `test_leave_full_release_restoration.py`). Pass.
- **Difference:** an open balance shortfall for the cancelled leave is not closed (API
  C1-SHORTFALL-CANCEL). See scenario 7 and MA-27.

### 14. Leave balance shortfall + accrual — CODE-CONFIRMED (MA-11)

- `LeaveAccrualService` does not call the shortfall pass. Only a positive HR adjustment
  (`LeaveLedgerService.create_adjustment`) or a calendar edit resolves an open shortfall. The next
  monthly accrual leaves it open, and period close stays blocked.

### 15. Shift change + approved leave — NOT EXECUTED

- **From the code:** leave day counting uses the calendar and does not depend on the shift. It
  could change only when the work calendar is assigned by shift, in which case the leave goes
  through the same reconciliation as scenario 8. Not run.

### 16. Shift change + existing punches — FINDING (MA-07)

- **Setup (API IP7, IP7b, IP7c):** punches on Monday and Tuesday. A roster change moves Tuesday to
  a shift whose window claims Monday's late-night punches.
- **Actual:** only the changed date is recalculated. The neighbouring date keeps punches it no
  longer owns until something else recalculates it. In IP7c, Tuesday shows ABSENT, 0 worked, while
  Monday's later recalculation counts the punches (240 minutes).
- **Expected:** both dates whose punch ownership changes are recalculated together.

### 17. Roster change + overtime approval — PASS (mechanism)

- **Suite:** `test_overtime_recalculation.py::test_human_approved_overtime_is_capped_when_the_detection_shrinks`,
  `::test_human_approved_overtime_is_reopened_when_the_detection_grows`,
  `::test_rejected_overtime_stays_rejected_until_new_overtime_appears`,
  `::test_repeated_recalculation_changes_nothing` pass.
- **Not run:** a roster edit as the trigger. The supersede path is the same whatever caused the
  recalculation, so the mechanism is covered. The neighbour-date gap (MA-07) still applies.

### 18. Punch ownership transfer between dates — FINDING (MA-07, MA-29)

- **Roster or shift change:** see scenario 16.
- **Regularization:** a request may add punches up to one day either side of its date, but
  approval recalculates only the request's own date (`service.py`, approve, around line 6612).
  The other date keeps the old ownership until the next sweep or close (MA-29, code-confirmed).

### 19. Punch correction + weekly cap — PASS

- **Suite:** `test_attendance_rules_remediation.py::test_correcting_an_earlier_day_recalculates_the_later_days_of_the_week`,
  `::test_weekly_cap_goes_to_the_earliest_days_whatever_order_they_are_calculated_in`,
  `::test_a_locked_later_day_is_not_touched_by_an_earlier_correction`;
  `test_overtime_cap_reallocation.py` (R-5 partial approval, rejection, full approval).
- **Gap:** budget freed when overtime is withdrawn at period lock is not handed on (MA-32).

### 20. Punch correction + monthly cap — PASS

- **Suite:** `test_overtime_cap_reallocation.py::test_r4_a_correction_reallocates_a_week_that_spans_two_months_and_the_next_month`,
  `::test_r4_a_weekly_cap_alone_still_reaches_the_days_of_the_week_in_the_next_month`.

### 21. Overtime rejection + period reopening — PASS

- **Suite:** `test_attendance_rules_remediation.py::test_overtime_rejected_at_lock_returns_when_the_reopened_day_is_corrected`,
  `::test_a_human_rejection_is_still_not_reversed_by_a_recalculation`;
  `test_attendance_period.py::test_reopen_unlocks_days_and_refinalize_regenerates_summary`.

### 22. Overtime approval + later policy publication — DECISION REQUIRED

- **Suite:** `test_calendar_recalc_triggers.py::test_publishing_an_overtime_policy_version_queues_only_its_assignees`
  passes: only that policy's assignees are queued.
- **Undefined:** on recalculation, a human-approved record keeps its approved minutes, but its
  multiplier and policy version are taken from the new version (`_resolve_ot_decision`, outcome
  `POLICY_VERSION_CHANGED`). Its comp-off choice is **not** re-taken: `comp_off_minutes` stays
  non-zero if it was non-zero before, even when the new version no longer gives comp-off instead
  of pay (`service.py` around line 5372). Whether an approval stands for the minutes or for the price is not
  decided (register O-15).

### 23. Break override + overtime recalculation — FINDING (MA-30)

- **Suite:** `test_attendance_rules_remediation.py::test_a_backdated_break_override_recalculates_the_days_it_covers`
  passes.
- **Difference:** **revoking** an override queues recalculation from today
  (`break_override_service.revoke`). The revocation applies to every date
  (`list_in_force` drops revoked overrides), so past open days keep results computed with the
  override until the sweep or close (MA-30, code-confirmed).

### 24. Employment termination + overnight shift — PASS (main path) · NOT EXECUTED (overnight)

- **Suite:** `test_attendance_rules_remediation.py::test_a_backdated_termination_recalculates_the_days_after_the_last_working_day`;
  `test_leave_employment_validity.py` termination tests.
- **Not run:** an overnight shift starting on the last working day. By the ownership code the
  whole shift belongs to its start date, so it would count. Not executed.

### 25. Rejoining + historical attendance — PASS · FINDING (MA-21)

- **Suite:** `test_regularization_employment_period.py::test_regularization_respects_employment_gap_and_rehire`,
  `test_leave_employment_validity.py::test_balance_survives_termination_and_rehire_and_the_gap_accrues_nothing`,
  `test_comp_off_employee_lifecycle.py::test_comp_off_credit_survives_termination_and_rehire_and_expires_once`.
- **Difference:** a new employment or termination dated inside a closed period is accepted; locked
  days keep their old employment state (MA-21, code-confirmed).

### 26. ON_DUTY + leave overlap — PASS · FINDING (MA-31)

- **Engine L16, L17:** ON_DUTY plus half-day unpaid leave gives ON_DUTY, 0.50 paid, 0.50 loss of
  pay. ON_DUTY plus full paid leave gives LEAVE, 1.00 paid. Leave takes precedence.
- **Difference (API C1-DOUBLE-ON-DUTY):** a second ON_DUTY request for the same date is accepted.
  Approving it returns HTTP 500 and rolls back, leaving the first approval in place (MA-31).

### 27. Comp-off credit + overtime correction — FINDING (MA-03)

- **API IP10:** 180 minutes of auto-approved overtime credits 0.38 day of comp-off. A correction
  removes the overtime: the record is deleted and the credit stays at 0.38. A new correction gives
  30 minutes of overtime, which is credited again (0.06). The balance is 0.44 for 30 minutes of
  overtime.
- **Expected:** credit follows the current approved overtime, or is held until the period closes.

### 28. Holiday removal + leave shortfall — PASS · FINDING (MA-27, MA-11)

- **Suite:** `test_leave_calendar_reconciliation.py::test_a_shortfall_is_an_exception_not_loss_of_pay_and_hr_resolves_it_with_balance`,
  `::test_a_shortfall_closes_itself_when_the_holiday_comes_back`,
  `::test_a_negative_balance_is_used_only_where_the_policy_allows_it`.
- **Difference:** cancellation does not close the shortfall (MA-27); accrual does not resolve it
  (MA-11).

### 29. Calendar change + closed attendance period — PASS

- **Suite:** `test_leave_calendar_reconciliation.py::test_leave_in_a_closed_attendance_period_is_never_changed`;
  `test_calendar_recalc_triggers.py`. Locked days are not recalculated. Leave in the closed period
  is not changed.
- **Related:** deactivating a holiday calendar does not stop its holidays from applying (MA-28,
  API C1-INACTIVE-HOLIDAY-CAL).

### 30. Two simultaneous reconciliation requests — PASS

- **Suite:** `test_leave_reconciliation_operation.py::test_two_hr_users_applying_the_same_preview_change_the_leave_once`.

### 31. Two simultaneous attendance recalculations — PASS · FINDING (MA-12, MA-33)

- **Suite:** `test_attendance_rules_remediation.py::test_concurrent_calculation_of_days_sharing_a_cap_ends_in_the_same_allocation`.
- **Difference:** the queue does not deduplicate. API IP4 queued five overlapping requests for one
  employee (MA-12). Each recalculation of a day with pending overtime raises the record version
  (MA-33).

### 32. Earlier-date correction + week crossing a month boundary — PASS

- **Suite:** `test_overtime_cap_reallocation.py::test_r4_a_correction_reallocates_a_week_that_spans_two_months_and_the_next_month`.
- **Not tested:** a week crossing a year boundary.

### 33. Multiple policy versions with overlapping effective dates — PASS

- Overlap is refused by database exclusion constraints and the publish API.
- **Suite:** `test_attendance_policy.py::test_publish_second_version_insert_new_close_previous`,
  `::test_published_version_immutable`; the same for leave policy.

### 34. Regularization approval after attendance period validation — DECISION REQUIRED · FINDING (MA-29)

- `validate` reads stored rows; `finalize` recalculates every open day before validating, so an
  approval made after `validate` is still counted at close. Approval on a closed date is refused.
- **Undefined:** whether a `READY` validation result should become invalid when anything changes
  afterwards. Today it does not (register V-06).
- **Difference:** the neighbour-date gap of MA-29 applies.

### 35. Roster publication after punches and overtime approval — NOT EXECUTED

- **Components covered:** neighbour-date ownership (scenario 16) and approved-overtime supersede
  (scenario 17). The combined sequence was not run.

---

## Scenarios this audit added

| ID | Scenario | Result | Evidence |
|---|---|---|---|
| X1 | Hour bands not starting at zero, 30 minutes worked | FINDING (MA-01): PRESENT, 1.00 paid | API IP1, engine H1, H2 |
| X2 | No-show under `TREAT_PRESENT`, then lock | FINDING (MA-02): INCOMPLETE locked with 1.00 paid | API IP2 |
| X3 | Checkout after close, owned by a locked day | FINDING (MA-06): counted nowhere, no blocker | API IP5 |
| X4 | Future date calculated | FINDING (MA-17): INCOMPLETE row written | API IP6 |
| X5 | Part-time 4-hour shift with 8-hour bands | FINDING (MA-05): HALF_DAY, 0.50 loss of pay | Engine O20 |
| X6 | Work wholly before a FIXED shift | FINDING (MA-20): ABSENT, 0 worked | API IP7c |
| X7 | Holiday on a deactivated holiday calendar inside a leave range | FINDING (MA-28): still excluded from leave | API C1-INACTIVE-HOLIDAY-CAL |
| X8 | Server timezone UTC, IST, New York, Los Angeles, UTC+14 | PASS: identical engine output; unit suite identical under IST and UTC+14 | Engine digest; unit runs |
| X9 | Day shift, checkout 23:59 / 00:00 / 00:01 / 05:29 / 05:30 / 06:01 next day | PASS: owned by the shift day up to the +12-hour limit, then split | Engine T1–T4b |
| X10 | Night shift, IN 23:59 / OUT 00:01 | PASS: one 2-minute session on the start date | Engine T6 |
| X11 | No shift, IN day 1, OUT day 2 | FINDING (MA-16): one 33-hour session | Engine T8 |


---

# Part E — Recalculation trigger audit

# Attendance Recalculation Trigger Audit — 16 November 2026

**Written for:** architect and engineering team. Part of
`MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`. Describes the uncommitted working tree (engine 16).
It replaces nothing: `ATTENDANCE_RECALCULATION_TRIGGER_MATRIX.md` (the earlier remediation's
matrix) was checked against the code and is accurate for the rows it has; this document adds the
mechanics, the missing rows and the failure paths.

---

## 1. The three ways a day gets recalculated

| Path | Used by | Transaction | If it fails |
|---|---|---|---|
| **In-request, required** | leave approval and cancellation (`LeaveProjectionService.sync` / `cancel`), regularization approval, reconciliation, period finalize, HR overtime decision (cap re-allocation) | the caller's transaction; the change and the recalculation commit or roll back together | the whole request fails; nothing is half-written |
| **In-request, best effort** | punch creation (`PunchService._try_immediate_calculate`) | a savepoint inside the punch transaction; calculates the punch's local date and its owning date, oldest first | the punch is kept; a request `IMMEDIATE_CALCULATION_FAILED` is queued for the dates tried |
| **Queued** | every configuration change (`recalc.request_recalc`) | the request row is inserted in the caller's transaction; a Celery task is kicked after commit; Beat re-kicks every 5 minutes | the request stays pending and is retried, up to 5 attempts, then closed with an error |

Plus two sweeps: the daily calculation at 09:30 IST (today and two days back, every active
employee) and `finalize` (every unlocked day of the period, oldest first per employee).

### What the queue processor does (`recalc.process_company_requests`)

1. Reads up to 50 pending requests for the company, oldest first.
2. For each, selects **existing, unlocked** `attendance_day` rows in the date range, narrowed by
   `employee_id` and/or by `shift_id` (the shift the row was calculated against).
3. Calculates each employee's dates in date order, one transaction per employee-date
   (`tasks._calculate_employee_dates`). Locked days and closed periods are counted as skipped.
4. Marks the request processed when every day succeeded or was skipped; otherwise increments
   `attempts`.

Each `calculate` may cascade to later days of the month and week inside its own transaction when
the day's late flag, excess-break flag or cap contribution changed.

---

## 2. Mutation-to-recalculation matrix

Reason codes are the values written to `attendance_recalc_request.reason`.

| # | Mutation | Method | Path | Reason / call | Employees | Dates | Leave reconciled | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | Shift version published | `OrganisationService.publish_shift_version` | queued | `SHIFT_VERSION_PUBLISHED` | rows on that shift | `effective_from` → today | no | Correct, with gaps A and B |
| 2 | Shift created / draft edited | — | none | — | — | — | — | Correct (a draft changes nothing) |
| 3 | Shift deactivated | — | none | — | — | — | — | Plausible risk: the engine never reads `Shift.is_active`, so nothing would change if it did recalculate (code reading, not reproduced) |
| 4 | Assignment created (shift, branch, department, designation, grade) | `EmployeeAssignmentService.create_assignment` | queued | `ASSIGNMENT_CREATED` | the employee | `effective_from` → end of range | no | Correct, with gap A |
| 5 | Assignment deleted / edited | no such operation (assignments are closed by a new one or by termination) | — | — | — | — | — | — |
| 6 | Roster row created / edited / published / deleted | `ShiftRosterService._queue_recalc` | queued | `ROSTER_CHANGED` | the employee | the roster date only | no | **Incomplete**: gap A (reproduced, IP7c) |
| 7 | Shift swap approved | `schedule_service` | queued | `SWAP_APPROVED` | both employees | both dates | no | Correct, with gap A |
| 8 | Holiday created | `create_holiday` | queued | `HOLIDAY_CHANGED` | calendars linking the holiday calendar | the date | **yes, same transaction** | Correct |
| 9 | Holiday edited / deactivated | `update_holiday` | queued | `HOLIDAY_CHANGED` | same | old and new date | yes | Correct |
| 10 | Holiday calendar validity / active | `update_holiday_calendar` | queued | `HOLIDAY_CALENDAR_CHANGED` | linked calendars | oldest unlocked day → today | no (blocker) | Validity: correct; wide (section 5). Active flag: queued but has no effect, because the resolver ignores it (MA-28, reproduced) |
| 11 | Weekly-off pattern rules / active | `update_weekly_off_pattern` | queued | `WEEKLY_OFF_PATTERN_CHANGED` | calendars using it and `WEEKLY_OFF` assignments | oldest unlocked day → today | no (blocker) | Correct; wide |
| 12 | Work calendar pattern (including set to none), holiday links, restricted flag, active | `update_work_calendar` | queued | `WORK_CALENDAR_CHANGED` | its assignments | oldest unlocked day → today | no (blocker) | Correct; wide |
| 13 | Calendar exception created / edited | `create_calendar_exception`, `update_calendar_exception` | queued | `CALENDAR_EXCEPTION_CHANGED` | the calendar's assignments | the date(s) | yes | Correct |
| 14 | Policy assignment created / changed / ended | `_queue_policy_recalc` | queued | `POLICY_ASSIGNMENT_CHANGED` | the scope | assignment start → today | no | Correct; duplicates (section 4) |
| 15 | Attendance policy version published (grace, bands, limits) | `publish_attendance_policy_version` | queued | `POLICY_VERSION_PUBLISHED` | the policy's assignments | `effective_from` → today | — | Correct |
| 16 | Overtime policy version published | `publish_overtime_policy_version` | queued | `POLICY_VERSION_PUBLISHED` | the policy's assignments | `effective_from` → today | — | Correct |
| 17 | Leave / regularization policy version published | — | none | — | — | — | — | Correct (no effect on stored results) |
| 18a | Break override created | `break_override_service.create` | queued | `BREAK_OVERRIDE_CHANGED` | the employee | override start → today | — | Correct |
| 18b | Break override revoked | `break_override_service.revoke` | queued | `BREAK_OVERRIDE_CHANGED` | the employee | **`max(effective_from, today)` → today** | — | **Incomplete** (MA-30): `list_in_force` drops a revoked override for every date, so open past days keep the old result |
| 19 | Employment created | `create_employment` | queued | `EMPLOYMENT_CREATED` | the employee | joining date → today | — | Correct |
| 20 | Employment terminated | `terminate_employment` | queued | `EMPLOYMENT_TERMINATED` | the employee | last working day + 1 → today | — | Correct (reproduced, IP4) |
| 21 | Employment edited: pay basis | `update_employment` | **none** | — | — | — | — | **Missing** (MA-10; IP5) |
| 22 | Employment edited: legal entity | `update_employment` | **none** | — | — | — | — | **Missing**, and unguarded against closed periods (MA-10) |
| 23 | Punch created | `PunchService` | best effort, then queued | direct; `IMMEDIATE_CALCULATION_FAILED` | the employee | local date and owning date | — | Correct, with gaps A and C |
| 24 | Punch corrected | through regularization (a superseding punch) | required | direct | the employee | the request's attendance date | — | **Incomplete** (MA-29, code-confirmed): requested punches may fall a day either side (`submit`, around line 5945); only the request's date is recalculated |
| 25 | Punch deleted | no such operation in the product | — | — | — | — | — | — |
| 26 | Orphan punch dismissed | `dismiss_orphan_punch` | none | — | — | — | — | Correct (it was owned by no day) |
| 27 | Regularization approved | `_apply_correction`, `_apply_break_correction` | required | direct | the employee | the attendance date | — | Correct for its date; see row 24 |
| 27b | Break event corrected (break module) | `BreakService._recalculate` | best effort | direct; **on failure only a warning log** | the employee | the date | — | **Weaker than punches** (C-17): no durable request; repaired only by the 3-day sweep or close |
| 28 | ON_DUTY approved / cancelled | regularization service | required | direct | the employee | the date | — | Correct |
| 29 | Leave approved | `_apply_approval` → `sync` | required | direct | the employee | each leave day | ledger debit | Correct |
| 30 | Leave cancelled | `_reverse_approval` → `cancel` | required | direct | the employee | each leave day | refund | Correct for days and ledger; **an open shortfall is not closed** (MA-27, reproduced) |
| 31 | Leave edited | no such operation (cancel and re-apply) | — | — | — | — | — | — |
| 32 | Leave accrual / carry-forward / comp-off credit | Celery sweeps | none | — | — | — | open shortfalls not re-checked | **Missing** for shortfalls (MA-11) |
| 33 | HR balance adjustment (credit) | `create_adjustment` | required | reconcile for open shortfalls | the employee | shortfall dates | yes | Correct |
| 34 | Leave reconciliation apply | `apply_reviewed` | required | direct | affected employees | affected leave days | yes | Correct |
| 35 | Overtime approved in full | `OvertimeRecordService.approve` | none needed | day row updated directly | — | — | — | Correct |
| 36 | Overtime approved partly / rejected | `approve`, `reject` | required | `reallocate_caps_after_decision` | the employee | later days of week / month, when a cap exists | — | Correct |
| 37 | Comp-off credited / expired | Celery sweeps | none | — | — | — | — | Correct for attendance; credit does not follow corrections (MA-03) |
| 38 | Period finalized | `finalize` | required | `recalculate_days_for_close` | owned employees | every unlocked day of the period | blockers | Correct, except: overtime withdrawn by `_apply_incomplete_lock_resolution` runs after the recalculation and does not re-allocate cap budget to later days (MA-32, code-confirmed) |
| 39 | Period reopened | `reopen` | none | unlock only | — | — | — | Correct by design |
| 40 | Engine version raised | — | none | — | — | — | — | By design (AR-17) |

---

## 3. Missing or incomplete triggers

### Gap A — neighbouring days after a schedule change (MA-07, reproduced)

Ownership compares a date with two days on each side, so changing the shift of date D can change
which punches D−1 and D+1 own. Rows 1, 4, 6 and 7 queue only D (or D onward). Probe IP7c: after a
roster change on Monday, Monday's snapshot listed four punches including Tuesday's two; Tuesday's
row was not recalculated and still listed the same two.

It is repaired by: any later calculation of the neighbour (a punch, the sweep within three days,
period close). It is not repaired when the neighbour is already locked in an earlier period.

### Gap B — shift-scoped requests match only rows already on that shift

`_affected_days` filters `attendance_day.shift_id == request.shift_id`. A row calculated with no
shift (a roster week-off, or a day when the shift had no published version) is not selected when a
version is published for that shift, or when a shift-scoped policy changes. Code-confirmed, not
reproduced.

### Gap C — a punch that re-pairs another day's session

A new punch recalculates its own local date and its owner. If it changes how an older lone punch
pairs, and that older punch moves to or from a third date, the third date is not recalculated.
Open since the shift audit; unchanged.

### Missing: employment edits (MA-10), accrual against shortfalls (MA-11), comp-off against overtime (MA-03)

See the master report.

### Silent: a punch owned by a locked day (MA-06, reproduced)

The immediate calculation fails, a request is queued, the processor skips the locked day and
closes the request as done. Nothing reports the punch.

---

## 4. Duplicate and unnecessary triggers

- **No coalescing.** `request_recalc` inserts unconditionally. Probe IP4: creating one employee
  with an employment, a shift version, an assignment and two policy assignments queued five
  requests, four of them from 1 January to today. Processing recalculated the same three rows five
  times. A bulk import or a calendar setup session multiplies this.
- **Company-wide supersets.** A change scoped wider than one employee or one shift queues the whole
  company (`_targets_for_assignments`). This is safe and can be very large (section 5).
- **Unconditional calendar ranges.** A pattern or work-calendar edit queues from the oldest
  unlocked day to today even when the edit changes nothing in the past (for example a future-dated
  cycle start).
- **Policy publish with unchanged values** queues a full range.
- **Cascade inside a queued run.** The processor calls `calculate` with the cascade on. When a day's
  late flag or cap contribution changes, the rest of the month is recalculated in that
  transaction, and then again as the processor reaches each of those days.

None of these produces a wrong result: recalculation is idempotent (identical inputs give an
identical row; automatic overtime approvals with identical figures are left untouched). The cost is
time, lock duration and audit-log volume (one `ATTENDANCE_DAY_RECOMPUTED` audit row per run).

One exception to "untouched": a **`PENDING`** overtime record is rewritten on every recalculation of
its day, even with identical figures (`OvertimeRecordRepository.replace_for_day` raises `version`;
the service adds a `DETECTED` action and an `OVERTIME_DETECTED` audit entry each time). An approver
who opened the record before the 09:30 sweep, a queued run or a punch gets a stale-version error on
approve (MA-33, code-confirmed).

---

## 5. Date ranges and populations

| Check | Result |
|---|---|
| `date_to` is clamped to the company's business today | Correct. Future rows (MA-17) are never selected |
| Future-dated configuration (`date_from` > today) | No-op, correct: no row exists to repair |
| "Oldest unlocked day" for calendar-wide edits | Company-wide minimum. One old unlocked row (for example a never-closed month a year back) makes every calendar edit recalculate the whole span |
| Employee population for holiday changes | Calendars linking the holiday calendar → their assignments; company-wide when any assignment is wider than employee or shift. A superset, never a subset (verified by reading) |
| Policy publish population | The policy's own active assignments overlapping `effective_from`; none → nothing queued (correct) |
| Termination | From the day after the last working day. Correct |
| Roster | The roster date only: gap A |

---

## 6. Failure handling, retry and recovery

| Question | Answer |
|---|---|
| Can a request be lost? | No. It is a row committed with the change. The kick is at-most-once; Beat re-kicks every 5 minutes |
| What if the worker dies mid-request? | Days already calculated are committed one by one; the request stays pending and is run again from the start (idempotent) |
| What if a day keeps failing? | After 5 attempts the request is closed with `last_error` and one error log (`attendance_recalc_request_abandoned`). No screen, notification or blocker (MA-12) |
| What if the day is locked? | Skipped and counted; the request completes |
| Lock timeouts | `calculate` bounds lock and statement waits; a timeout counts as not done and is retried |
| Deadlocks | Not observed. Every path read takes row locks in ascending date order within one employee |
| Recalculation loops | None found. The cascade calls `_calculate` with the cascade switched off |
| Order within an employee | Ascending dates, which the cap allocation (D-04) and the cumulative counters need |
| Order across requests | Oldest request first; two requests for the same rows simply run twice |
| Concurrency of two processors for one company | Possible (kick plus Beat). Each `calculate` locks its row; the second waits or times out and retries. Not load-tested |
| Audit trail | Every recalculation writes an audit row with the full day; the request row keeps reason, source entity, requester, attempts, last error. There is no record of *which* days a request changed |

---

## 7. Previously reported R-1 to R-8, as triggers

| ID | Trigger aspect | State in the working tree |
|---|---|---|
| R-1 | Restoring a fully released leave after a holiday is removed | Re-derived from the application's own range and half; covered by the suite |
| R-3 | Undated calendar, roster and shift drift | No automatic trigger, by decision; HR runs preview and apply (API only) |
| R-4 | Cap cascade across a month boundary | The pass runs to the end of the second month when a monthly cap exists |
| R-5 | HR partial approval or rejection | Re-allocates later days in the reviewer's transaction |
| R-6 | Cascade without caps | Gated on a weekly or monthly cap being set |
| R-2, R-7, R-8 | Not trigger-related | See the master report |

---

## 8. Recommended changes, in order

1. Widen schedule-change requests by the ownership neighbourhood (gap A).
2. Queue on employment edits; guard the legal-entity edit (MA-10).
3. Report punches owned by a locked day (MA-06).
4. Coalesce pending requests per target and overlapping range; switch the cascade off inside the
   processor and rely on its date order (as `finalize` already does).
5. Surface abandoned requests to HR, or block period close while one overlaps the period.
6. Re-check open shortfalls after any credit entry (MA-11).
7. Make comp-off credit follow the overtime record (MA-03).
8. Drop the `shift_id` filter for rows with no shift, or queue by employee for shift changes (gap B).
9. Queue a break-override revocation from the override's own start date (MA-30).
10. Recalculate both dates of a cross-date regularization (MA-29).
11. Close a leave's open shortfalls when the leave is cancelled or withdrawn (MA-27).
12. Re-allocate cap budget after overtime is withdrawn at lock (MA-32).
13. Leave a `PENDING` overtime record untouched when nothing changed (MA-33).
14. Queue a durable request when a break-correction recalculation fails (C-17).

**Revision.** A second, independent pass on the same day added rows 18b and 27b, corrected rows 3,
10, 24, 30 and 38, and added items 9–14. The rest of this document was checked against `recalc.py`
(read in full) and the call sites it names.


---

# Part F — Remaining issues and risks

# Attendance Remaining Issues and Risks — 16 November 2026

Companion to `MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`, which holds the full write-up of every
finding (root cause, reproduction, correction, regression test). This document is the ordered work
list. It describes the **uncommitted working tree** (engine 16).

**Evidence words.** REPRODUCED: shown by a probe or test that ran in this audit. CODE-CONFIRMED:
the code path was read end to end and is unambiguous, but not executed. PLAUSIBLE RISK: reported by
a code reading and not confirmed by this audit; it may be wrong. DECISION: the product owner must
choose before anyone can call the behaviour right or wrong.

**Impact letters.** A = attendance status, P = paid-day or loss-of-pay fraction, L = leave balance,
O = overtime or comp-off, C = period close blocked or not blocked.

---

## 1. Before attendance can feed a payroll audit

These can put a wrong paid-day fraction, leave balance or overtime figure into a period that then
closes without any blocker, or stop a period from closing with no supported remedy.

| Order | ID | Issue | Evidence | Impact | Needs |
|---|---|---|---|---|---|
| 1 | MA-01 | Hour bands with a gap or not starting at zero: uncovered minutes are `PRESENT`, full pay. 30 minutes worked = full day | REPRODUCED (API IP1; engine H1, H2) | A, P | Fix (refuse at publish; no band = configuration error). Decision H-01. List published versions with gaps |
| 2 | MA-02 | Under `TREAT_PRESENT`, a no-show is paid in full at lock | REPRODUCED (API IP2) | A, P | Decision H-02, then fix |
| 3 | MA-03 | Comp-off credit never follows overtime corrections; a re-detected record earns a second credit (180 min credited 0.38, removed, 30 min re-detected: balance 0.44) | REPRODUCED (API IP10) | L, O | Decision H-03, then fix. Integrity query for existing credits |
| 4 | MA-04 | A shift-scoped work calendar or attendance policy does not resolve on a roster week-off: `CONFIG_ERROR`, blocks close | REPRODUCED (API IP3; engine O8) | A, C | Decision H-04, then fix |
| 5 | MA-05 | Part-time shifts judged by full-day bands: full attendance = `HALF_DAY`, 0.50 loss of pay | REPRODUCED (engine O20) | A, P | Decision P-05 |
| 6 | MA-27 | A leave shortfall stays open after its leave is cancelled; it keeps blocking close and the reconciliation operation shows nothing to apply | REPRODUCED (API C1-SHORTFALL-CANCEL) | C, L | Fix (close shortfalls on cancel and withdraw; filter by application status) |
| 7 | MA-34 | Overtime at the manager stage can only be decided by the snapshotted manager; no reassignment or HR override. A departed manager's records block close | CODE-CONFIRMED | C, O | Decision O-19, then fix |
| 8 | MA-06 | A punch accepted after close and owned by a locked day is counted nowhere and reported nowhere | REPRODUCED (API IP5, IP9b) | A, P | Fix (report it; blocker or HR queue) |
| 9 | MA-07 | A schedule change recalculates only its own date; the neighbour keeps punches it no longer owns | REPRODUCED (API IP7, IP7b, IP7c) | A, P, O | Fix (widen by the ownership neighbourhood) |
| 10 | MA-10 | Pay-basis and legal-entity edits queue no recalculation; the legal-entity edit has no closed-period guard | CODE-CONFIRMED | A, P, C | Fix |
| 11 | — | Commit engine 16 with its three migrations; migrate the dev database (four behind); run Flutter in CI | Verified state | all | Operational |

## 2. Wrong by rule, needing a decision first

| ID | Issue | Evidence | Impact | Decision |
|---|---|---|---|---|
| MA-08 | Half-day leave on a day that became a day off shows 0.50 loss of pay until HR reconciles | REPRODUCED (API IP8; engine L1–L3) | P | H-08 |
| MA-09 | Late-mark ceiling measured from shift start, grace included: a "mark" of 50–59 minutes costs half a day; template text says marks cost nothing | REPRODUCED (engine G1) | A, P | D-01a, R-2 |
| MA-13 | Grace lowers every hour-band threshold, even when hours were missed (239 minutes is `HALF_DAY` under "absent below 240") | REPRODUCED (engine H3) | A, P | H-05 |
| MA-20 | FIXED shift: work wholly before the shift counts zero minutes; day is `ABSENT` | REPRODUCED (API IP7c) | A, P | P-04 |
| MA-28 | Deactivating a holiday calendar, work calendar or weekly-off pattern changes nothing; its holidays still exclude leave days | REPRODUCED (API C1-INACTIVE-HOLIDAY-CAL) | A, L | H-30 |
| H-29 | Lateness in the worked half of a half-day leave, with no late bands, costs a quarter day | REPRODUCED (engine L7) | P | H-29 |
| O-15 | A policy republish re-prices approved overtime but keeps the old comp-off choice | CODE-CONFIRMED | O | O-15 |
| AR-15 | `work_on_leave_behaviour` is accepted, stored and ignored | CODE-CONFIRMED | — | L-13 |

## 3. Medium

| ID | Issue | Evidence | Impact | Correction |
|---|---|---|---|---|
| MA-11 | Accrual and other credits do not resolve an open leave shortfall; only an HR credit does | CODE-CONFIRMED | C, L | Run the shortfall pass after any credit, or document the HR step |
| MA-12 | Recalculation queue: no deduplication; requests abandoned after 5 attempts are only logged | CODE-CONFIRMED; duplication observed (IP4) | — | Coalesce; surface abandoned requests |
| MA-29 | Regularization may add punches a day either side, but approval recalculates only its own date | CODE-CONFIRMED | A, P | Recalculate both dates |
| MA-33 | A `PENDING` overtime record is rewritten on every recalculation (version raised, action and audit row added), so approvers hit stale-version errors after any sweep | CODE-CONFIRMED | O (operational) | Rewrite only on change |
| MA-26 | Cascades and close-time checks scale poorly (quadratic cascade, company-wide calendar ranges, per-date claim resolution at validation) | CODE-CONFIRMED; not measured | — | See master section 12 |
| MA-36 | No screen for leave reconciliation or orphan-punch handling, yet both calendar setup screens tell HR to "run leave reconciliation" (web `work-calendars/setup/page.tsx:405`, mobile `work_calendar_setup_screen.dart:349`) | CODE-CONFIRMED | C | Build the screen or change the text |
| MA-14 | Weekly-off overtime net of breaks; roster week-off overtime gross | REPRODUCED (engine O1, O2) | O | Decision O-06 |

## 4. Low

| ID | Issue | Evidence |
|---|---|---|
| MA-15 | Holiday on a weekly off pays the weekly-off overtime class | REPRODUCED (engine O4) |
| MA-16 | No-shift day: forgotten checkout pairs with the next day's (33-hour session) | REPRODUCED (engine T8) |
| MA-17 | A future date can be calculated | REPRODUCED (API IP6) |
| MA-18 | `punch`, `overtime_action`, `punch_dismissal`, `attendance_period_action` are not append-only for the runtime role. The init script grants UPDATE/DELETE on all tables; migration `20261009090000` revokes them only for `leave_ledger`, `leave_application_action`, `audit_log` | CODE-CONFIRMED (init script and migration read) |
| MA-19 | Status label and paid fraction disagree on several day kinds | REPRODUCED |
| MA-21 | Termination or joining dated inside a closed period accepted | CODE-CONFIRMED |
| MA-22 | Punch, regularization and overtime decisions do not take the period-close lock | PLAUSIBLE RISK |
| MA-23 | Excess-break exceptions awaiting approval do not block close | CODE-CONFIRMED |
| MA-24 | Server-date fallbacks that can be a day early between 00:00 and 05:30 IST on a UTC server: `leave/decision_center.py:114`, `organisation/dashboard_insights.py:155`, `employee/schemas.py:100, 367` (date-of-birth and joining-date validation). Harmless: `organisation/service.py:1431, 4476` (only when the company row is missing) and `organisation/repository.py:734` (`CURRENT_DATE` in an informational count of a shift's active employees) | CODE-CONFIRMED |
| MA-30 | Break-override revocation recalculates from today only; past open days stay stale | CODE-CONFIRMED |
| MA-31 | A second ON_DUTY or early-departure approval for one date is accepted at submit and fails with HTTP 500 on approve | REPRODUCED (API C1-DOUBLE-ON-DUTY) |
| MA-32 | Overtime withdrawn at lock does not hand its cap budget to later days | CODE-CONFIRMED |
| MA-35 | Web blocker labels miss five codes (`PENDING_LEAVE`, `OVERTIME_INTEGRITY`, `LEAVE_BALANCE_SHORTFALL`, `LEAVE_CALENDAR_MISMATCH`, `ORPHAN_PUNCHES`) in `attendance-period/types.ts`; mobile reported the same | CODE-CONFIRMED (web); mobile reported, not read |
| C-14 | No revoke for an approved regularization | CODE-CONFIRMED |
| C-17 | Break-correction recalculation failure is logged only; nothing queued | CODE-CONFIRMED |

## 5. Plausible risks not confirmed by this audit

Reported by code readings during the audit. Each needs a probe before it is treated as a defect.

| Risk | Where to look |
|---|---|
| A deactivated but still employed person blocks close (`EMPLOYEES_WITHOUT_ATTENDANCE`) because the sweep skips them | daily sweep, `_run_validation` |
| A terminated employee who stays `is_active` gets an `EXITED` row written every day | daily sweep |
| The daily sweep uses the company timezone, not the branch timezone | `tasks.py` sweep |
| The engine ignores `Shift.is_active`; deactivating a shift queues nothing; swaps do not check it | `resolve_shift_schedule`, `schedule_service` |
| An assignment expiring under a roster row drops shift-scoped policy resolution | `_scope_candidates` |
| `ShiftRosterUpdate` can store a week-off together with a `shift_id` | roster schemas |
| A legal-entity change through a branch move changes policy scope but not period ownership | `_PeriodScope` |
| A comp-off credit can coexist with paid overtime after `comp_off_instead_of_pay` is switched off (follows from O-15) | `_resolve_ot_decision`, day summary |
| Comp-off credits whose overtime record is gone never expire | comp-off expiry sweep |
| A failure in the cap cascade rolls back the original calculation | `_recompute_later_days_of_month` |
| `delete_for_day` removes a `PENDING` record and its action history without an audit entry | `OvertimeRecordRepository.delete_for_day` |
| Mobile offers a "present, cancel leave" hint that does nothing; mobile insights sum detected rather than approved overtime; clients show all punches when the snapshot is missing | mobile attendance features |
| Leave findings LV-01 to LV-03 and LV-05 to LV-13 | carried from `LEAVE_MANAGEMENT_AUDIT_2026-11-16.md`; code unchanged, not re-reproduced |

## 6. What was not verified at all

- **Flutter:** `flutter analyze` and `flutter test` were not run; Flutter is not installed. Dart code
  was read only.
- **Production-like volumes:** no load or timing test. Performance statements are from code.
- **Concurrency beyond the suite:** two-session races were not run except those in existing tests.
- **Integrity report on real data:** `scripts/sql/attendance_integrity_report.sql` was not run
  against any database holding real or production-like data; none was available to this audit.
- **Year boundary:** cap cascades and leave across 31 December were not tested.
- **Scenarios 12, 15 and 35** of the cross-module matrix were not executed.

## 7. Residual risk if released as is

- Configurations that the API accepts today (MA-01, MA-02, MA-04, MA-05) produce wrong pay with no
  warning. A tenant that uses any of them gets wrong paid-day inputs.
- Comp-off balances can exceed the overtime actually approved (MA-03) and nothing reports it.
- Period close can be blocked with no supported remedy in the product UI (MA-27, MA-34, MA-36).
- Stale results between a change and period close (MA-06, MA-07, MA-10, MA-29, MA-30). Close
  repairs most of them; MA-06 it does not.
- About 30 business rules apply without an owner decision on record
  (`ATTENDANCE_POLICY_DECISION_REGISTER.md`).

