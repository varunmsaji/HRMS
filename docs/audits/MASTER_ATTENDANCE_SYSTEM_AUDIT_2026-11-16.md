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
