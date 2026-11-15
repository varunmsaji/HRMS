# Shift scenario map: what happens to attendance and pay — 15 November 2026

Read-only analysis of branch `test` (engine version 13, after the shift remediation commits). No code was changed. Companion spreadsheet: `SHIFT_SCENARIO_MAP_2026-11-15.xlsx` (same rows, filterable).

**166 scenarios** in 17 groups. Checked how: **103 ran through the real calculation engine**, 50 read from the source, 13 taken from the earlier shift audit. Verdicts: 126 OK, 5 fixed since the first draft, 25 need an owner decision, 6 are gaps, 4 are new findings.

**Update, same day:** N-02 and N-03 were fixed in engine version 14 (local `test` branch, not pushed). Rows marked FIXED show the new behaviour; the old behaviour is named in the row.

## 1. Findings that matter most

Seven things not in the earlier audit or remediation plan. Two were high (N-02, N-03) and are now fixed.

| ID | Severity | Finding | Scenarios |
|---|---|---|---|
| N-01 | Medium | **Roster rest day on a working calendar day pays NORMAL overtime, not WEEKLY_OFF.** A roster week-off row on a day the calendar calls working makes every worked minute overtime, but the day class is NORMAL because the engine only looks at the calendar type. The same work on a calendar weekly off pays the weekly-off multiplier. | ROS-02 |
| N-02 | High | **FIXED (engine 14) - Grace did not protect the hour band; the 'Standard office' template made a 5-minute delay a half day.** Grace forgives lateness but adds no worked minutes. With the template's 480-minute full-day band and an 8 h net shift, IN 09:05 on 09:00-18:00 with an unpaid hour (475 min), IN 09:08 on 09:00-17:00 (472 min) or OUT 17:55 gives HALF_DAY, LOP 0.50. This is P-07 made concrete: owner chose 'grace does not protect bands' without this consequence on the table. | BRK-08, BRK-09, NGT-03 |
| N-03 | High | **FIXED (engine 14) - A forgotten OUT followed by a next-morning OUT became one 24 h day with about 15 h of overtime.** Pairs are never split and have no maximum length. The punch-order rule only blocks an IN while the last punch (an IN) is under 18 h old, so the app steers the employee to OUT. Day 1 gets 1440 worked minutes, day 2 has no IN. | PUN-06, PUN-08, OT-13 |
| N-04 | Medium | **Daily-wage off-day work is made unpaid when overtime is detected, not when it is approved.** `_off_day_work_pay` zeroes the day wage whenever overtime was earned. If that overtime is later rejected, nothing pays the hours. | PB-05 |
| N-05 | Low | **A HALF_DAY late/early band overrides a harsher ABSENT hour band.** Hour band ABSENT (under 4 h) is replaced by HALF_DAY when a late or early band also says HALF_DAY, so a short day is paid half. | DAY-11 |
| N-06 | Medium | **Night-overtime WINDOW mode classes the whole day's overtime as NIGHT.** One classification per day: any overlap with the window sets NIGHT for all overtime that day. | OT-07 |
| N-07 | Low | **Overtime hourly rate always divides by 8 hours a day.** Basic / (days in month x 8) is used for every shift length, so a 12 h or 6 h shift gets the same hourly rate for the same monthly Basic. | OT-11 |

What each needs is in section 8. Everything else in the catalogue behaves as the code intends; where that intent is an open owner choice it is marked DECIDE and linked to the existing P-xx number.

## 2. Baseline used for every scenario

Unless a row says otherwise:

- Time zone Asia/Kolkata. Calendar day: working day (Tuesday 10 November 2026).
- Shift: FIXED 09:00-18:00 (540 minutes), no break rule.
- Attendance policy = the web app's **Standard office** template: grace-in 10, grace-out 10, full day 480 minutes, half day 240-479, under 240 absent. Late bands: 1-59 minutes no action, 60+ half day. Early-departure bands the same. (The two band sets are my test setting; the template ships them empty.)
- Missing punch: INCOMPLETE. At period close: TREAT_ABSENT. Multi-punch mode: pair all.
- Overtime policy: shift must be flagged overtime-eligible; minimum 30 minutes; needs post-approval; one multiplier per day class (NORMAL, WEEKLY_OFF, HOLIDAY, NIGHT).
- Pay figures are in **days** (paid, loss of pay, unpaid-off). Section 5 turns days into rupees with an example.

## 3. How one day is decided

Before the engine runs, three things are resolved (all in `attendance/`):

1. **Which shift.** Published roster row for the date, else the assignment's shift, else none (`work_schedule.py`). A roster row with no shift means a day off; it does not fall back to the assignment.
2. **Which punches belong to the day.** Each IN/OUT session is owned by exactly one day, by overlap with that day's shift, inside a window of 240 minutes before and 720 minutes after the shift (`punch_ownership.py`). Unclaimed punches are orphans and block period close.
3. **Calendar, policies, leave, on-duty and roster overrides** for that employee and date.

Then `evaluate_day` (`calculation.py`) works in this order. The first rule that matches ends the day.

| Step | Rule | Result |
|---|---|---|
| 1 | Employee not employed on the date | NOT_JOINED or EXITED (paid 0, LOP 0) |
| 2 | Time zone unusable, no calendar, no attendance policy | CONFIG_ERROR (blocks close) |
| 3 | Roster week-off and no punches | NOT_EXPECTED |
| 4 | No shift | Day off with no punches: NOT_EXPECTED. Working day with no punches: INCOMPLETE or ABSENT per policy. Punches: hour bands only, no late/early/overtime |
| 5 | Work expected? | Not expected on a holiday, weekly off or shutdown **unless the shift operates there or the roster says working**, and never on a roster week-off |
| 6 | Clean the punches | Same-direction punches within 120 s collapse; an extra punch within 30 minutes of the same direction is a stray; the rest pair IN to OUT; leftovers are orphans (missing punch) |
| 7 | Not expected and no punches | NOT_EXPECTED |
| 8 | Worked time | Pair minutes, minus unpaid breaks. Time before a FIXED shift starts is not credited |
| 9 | Late and early | Late = minutes after start (flexible: after the start window) minus grace-in; early = minutes before end minus grace-out. Looked up in the late/early bands. Split shifts never compute them |
| 10 | Status | Worked minutes into the hour bands; then any late/early/core-hours/cumulative HALF_DAY or ABSENT override; missing punch overrides to INCOMPLETE or ABSENT |
| 11 | Overtime | Worked minus scheduled (net of unpaid breaks), if eligible, over the minimum, rounded, capped by day, week and month; classed NORMAL, WEEKLY_OFF, HOLIDAY or NIGHT |
| 12 | Overlays | Unpaid off-day, half-day weekly off, ON_DUTY, then **approved leave wins** (full-day leave beats everything punched) |

## 4. From status to pay

Every employed day carries three fractions that always add to 1.00: **paid**, **loss of pay (LOP)**, **unpaid-off** (a day off that is not paid).

| Status | Paid | LOP | Notes |
|---|---|---|---|
| PRESENT | 1.00 | 0.00 | |
| HALF_DAY | 0.50 | 0.50 | From hour band, late/early band, core-hours breach, cumulative rule or missed split block |
| ABSENT | 0.00 | 1.00 | |
| NOT_EXPECTED | 1.00 | 0.00 | 0.00 paid and 1.00 unpaid-off when the off day is unpaid (daily-wage weekly off, unpaid holiday) |
| LEAVE | per leave | per leave | Paid leave 1.00; unpaid leave LOP 1.00; half-day leave splits |
| ON_DUTY | 1.00 | 0.00 | No overtime |
| INCOMPLETE | 0.00 | 0.00 | Resolved at period close by the policy: TREAT_ABSENT, TREAT_PRESENT, or KEEP_INCOMPLETE (blocks close) |
| NOT_JOINED / EXITED | 0.00 | 0.00 | Outside employment; payroll prorates on employed days |
| CONFIG_ERROR | 0.00 | 0.00 | Blocks close until the configuration is fixed |

Off-day exceptions: a daily-wage employee is paid only for PUBLIC and SUBSTITUTE holidays; a holiday with `is_paid = false` is unpaid for everyone; a holiday on a weekly off follows the holiday rule.

## 5. From attendance to the payslip

1. HR validates and **closes** the attendance period. Close is refused while any of these exist: unresolved work-on-leave, paid/LOP mismatch, KEEP_INCOMPLETE rows, pending regularizations, pending overtime approvals, draft roster rows, orphan punches, CONFIG_ERROR days, or employed days with no attendance row.
2. Close resolves INCOMPLETE rows, freezes each day (never recalculated again) and writes one summary per employee: paid days, LOP days, unpaid-off days, payable days, overtime minutes by class, comp-off earned, late count.
3. Payroll reads **only closed periods**. For each salary segment: monthly amount x paid days / days in the month (prorated components); other components in full. Daily wage: daily rate x paid days. Payroll refuses paid days above employed days or above payable days.
4. Overtime: approved minutes not converted to comp-off, per day class: `minutes / 60 x Basic / (days in month x 8) x multiplier` (daily wage: `daily rate / 8`). A class with no multiplier stops the run.

**Illustration only**, not your salary data: Basic Rs 30,000, a 30-day month, so a day is Rs 1,000 and an hour Rs 125. Multipliers assumed: NORMAL 1.5, WEEKLY_OFF 2.0, HOLIDAY 2.0, NIGHT 1.5.

| Case | Scenario | Effect on pay |
|---|---|---|
| Half day | DAY-10 | LOP 0.50: Rs 500 off prorated pay |
| Grace trap (fixed in engine 14) | BRK-08, three times in a month | Was 3 half days: Rs 1,500 off, for arrivals inside grace. Now nothing |
| Overtime | OT-01, 90 minutes NORMAL | 1.5 h x Rs 125 x 1.5 = Rs 281.25 |
| Weekly off worked | OFF-02, 5 h | Day stays paid, plus 5 h x Rs 125 x 2.0 = Rs 1,250 |
| Forgotten OUT (fixed in engine 14) | PUN-06, 900 minutes NORMAL | Was 15 h x Rs 125 x 1.5 = Rs 2,812.50 if approved, plus day 2 LOP Rs 1,000. Now no overtime; both days INCOMPLETE until corrected |
| Daily wage on a weekly off | PB-04, 9 h at Rs 1,000 a day | Day wage 0; overtime 9 h x Rs 125 x 2.0 = Rs 2,250 |
| Month length | one LOP day | Rs 1,071 in a 28-day month, Rs 968 in a 31-day month |

## 6. Scenario catalogue

Check: **PROBE** ran the engine on 15 Nov 2026 (case IDs refer to the probe script), **CODE** read from source, **AUDIT** from `SHIFT_MANAGEMENT_AUDIT_2026-11-15.md`. Verdict: OK, FIXED (changed in engine 14), DECIDE (open owner choice), GAP (wrong or risky), NEW (not in earlier documents).

### 1. Ordinary fixed-shift day (09:00-18:00)

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| DAY-01 | On time: IN 09:00, OUT 18:00. | PRESENT. Worked 540, scheduled 540, late 0, early 0. | Paid 1.00, LOP 0.00. No overtime. | PROBE | OK | A01 |
| DAY-02 | IN 09:10, exactly the 10-minute grace. | PRESENT. Late 0 (raw 10 - grace 10). Worked 530. | Paid 1.00. Late counter not incremented. | PROBE | OK | A02 |
| DAY-03 | IN 09:11, one minute past grace. | PRESENT. Late 1 minute. Worked 529. Counts as a late day for the cumulative rule (CUM group). | Paid 1.00 unless a late band or cumulative rule fires. | PROBE | OK | A03 |
| DAY-04 | IN 09:40. | PRESENT. Late 30 (raw 40 minus grace 10). Worked 500, still above the 480 full-day band. | Paid 1.00 (a 1-59 minute late band is 'no action' in the test config). | PROBE | OK | A04, P-07 |
| DAY-05 | IN 10:10 (60 minutes late after grace, late band 60+ = HALF_DAY). | HALF_DAY. Late 60. | Paid 0.50, LOP 0.50. | PROBE | OK | A06 |
| DAY-06 | IN 09:40, OUT 19:00 (stays late to make up the time). | PRESENT. Worked 560 against 540 scheduled: excess 20, below the 30-minute overtime minimum. | No overtime. Late time must be made up before any overtime counts. | PROBE | DECIDE | A05, P-07 |
| DAY-07 | OUT 17:30, 30 minutes early. | PRESENT. Early departure 20 (30 minus grace-out 10). Worked 510. | Paid 1.00 unless an early band applies. | PROBE | OK | A07 |
| DAY-08 | OUT 17:50, inside grace-out. | PRESENT. Early 0. Worked 530. | Paid 1.00. | PROBE | OK | A08 |
| DAY-09 | OUT 17:00 with 'early departure needs approval' switched on and no approved request. | Early 50 is forced to the harshest configured early band: HALF_DAY. | Paid 0.50, LOP 0.50. With an approved EARLY_DEPARTURE_APPROVAL request: PRESENT, paid 1.00. | PROBE | OK | E04, E05 |
| DAY-10 | Works 09:00-13:00 only (4 h). | HALF_DAY by hour band (240-479). Early 290. | Paid 0.50, LOP 0.50. | PROBE | OK | A18 |
| DAY-11 | Works 3 h 59 m (leaves about 5 h early), with an early band 60+ minutes = HALF_DAY. | Hour band says ABSENT (under 240) but the early band HALF_DAY wins: HALF_DAY. | Paid 0.50 instead of 0.00. A HALF_DAY late/early band always overrides a harsher ABSENT hour band. | PROBE | NEW | A19, N-05 |
| DAY-12 | Duplicate IN within 120 seconds (double tap). | Collapsed to one punch. PRESENT, worked 540. | Paid 1.00. | PROBE | OK | A22 |
| DAY-13 | Second IN 20 minutes after the first. | Treated as a stray; earliest IN stands. PRESENT, worked 540. | Paid 1.00. | PROBE | OK | A23 |
| DAY-14 | IN 09:00, IN 14:00, OUT 18:00 (first IN real, second IN a mistake or a missed OUT). | INCOMPLETE. The first IN is an orphan; worked counts only 14:00-18:00 (240). Missing punch flagged. | Nothing paid or LOP yet. At close: TREAT_ABSENT gives LOP 1.00 although the person was there all day. Needs a regularization. | PROBE | DECIDE | A24 |
| DAY-15 | IN 08:00 (early), OUT 18:00. | PRESENT. Worked 540: time before 09:00 is recorded but not credited. | Paid 1.00. No overtime for arriving early. | PROBE | DECIDE | A11, P-04 |
| DAY-16 | IN 08:00, OUT 19:00. | PRESENT. Worked 600, overtime 60 (only the time after the shift counts). | Overtime 60 minutes, NORMAL class, pending approval. | PROBE | DECIDE | A12, P-04 |
| DAY-17 | Self-service IN earlier than the early-in allowance before shift start. | Refused at the punch (TOO_EARLY). Late punches and OUTs are always accepted; a punch after shift end plus grace-out is only logged. | None directly. The employee has no IN and ends up INCOMPLETE if they cannot punch. | CODE | OK | shift_window.py |

### 2. Missing, extra and odd punches

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| PUN-01 | Forgot to punch OUT (IN 09:00 only). | INCOMPLETE. Worked 0, missing punch. The IN is recorded as first-in so the overview shows the person present while the shift runs. | Nothing until close. At close: TREAT_ABSENT = LOP 1.00, TREAT_PRESENT = paid 1.00, KEEP_INCOMPLETE = blocks the close. | PROBE | OK | A13, PER-02 |
| PUN-02 | Forgot to punch IN (OUT 18:00 only). | INCOMPLETE. Worked 0. | Same as PUN-01. | PROBE | OK | A14 |
| PUN-03 | No punches on a working day, default policy. | INCOMPLETE (missing punch). Not ABSENT unless the policy says so. | Nothing until close, then as PUN-01. | PROBE | OK | A15 |
| PUN-04 | No punches, or IN only, with missing-punch behaviour = ABSENT. | ABSENT immediately. | LOP 1.00 at once, even while the shift is still running. | PROBE | DECIDE | A16, A17 |
| PUN-05 | Real OUT at 18:00, then a second OUT more than 30 minutes later. | The second OUT is not a 'stray' (window is 30 minutes) so it is an orphan: missing punch, INCOMPLETE even though the day was fully worked. | As PUN-01. Needs a regularization. | CODE | GAP | drop_stray_punches |
| PUN-06 | Forgot OUT on day 1. Next morning the app only offers OUT (last punch was an IN within 18 hours), so the employee punches OUT at 09:05. | FIXED in engine 14 (was one 24 h pair owned by day 1 with 900 minutes of overtime). The pair ends beyond day 1's punch window, so it is split: day 1 owns the IN (INCOMPLETE, worked 0, no overtime) and day 2 owns the OUT (lone OUT, INCOMPLETE). | No overtime and no paid 24-hour day. Each day follows the close behaviour (TREAT_ABSENT, TREAT_PRESENT or KEEP_INCOMPLETE) until HR or the employee regularizes. | PROBE | FIXED | S1, X17, N-03 |
| PUN-07 | Forgot OUT on day 1, punches IN next morning at 09:00. | Day 1: lone IN is an orphan, INCOMPLETE. Day 2 is normal. | Day 1 per close behaviour. Works only if the gap since the last IN is over 18 h; for night workers the app can refuse (R-07). | PROBE | OK | S2, R-07 |
| PUN-08 | Pair that starts inside the day's window but ends more than 12 h after shift end. | FIXED in engine 14: a pair ending at or after the owning day's window end is split into a lone IN and a lone OUT. An OUT that no day can take is an orphan (blocks close until corrected or dismissed). | No overtime from a stretched session. | PROBE | FIXED | S7, N-03 |
| PUN-09 | A lone punch outside every day's window (for example a lone IN at 03:00 for a 09:00 shift, window 240 min). | Orphan: owned by no day. Blocks period close until corrected by regularization or dismissed with a reason. | No pay effect until resolved, because the close is blocked. | CODE | OK | punch_ownership.py |
| PUN-10 | HR enters a manual punch or approves a MISSING_PUNCH regularization. | Synthetic punches are written and the day is recalculated like any other. | Pay follows the recalculated day. | CODE | OK | WD-28 |
| PUN-11 | Punch dated inside a closed attendance period. | Refused. | Locked days never change. | AUDIT | OK |  |
| PUN-12 | Same punch sent twice (network retry). | One punch (idempotency key plus 120-second collapse). | None. | AUDIT | OK |  |

### 3. Breaks and the hour bands

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| BRK-01 | Shift with an unpaid 13:00-14:00 lunch (legacy break). Employee punches OUT 13:00 and IN 14:00. | Gap matched to the break, unpaid. Worked 480. | Paid 1.00. | PROBE | OK | B05 |
| BRK-02 | Same shift, lunch not punched. | Nothing deducted. Worked 540 - an hour more than a colleague who punches lunch. | Paid 1.00. Overtime threshold reached an hour sooner than for the colleague. | PROBE | DECIDE | B06, P-03 |
| BRK-03 | Punched gap that matches no break window (legacy break rules). | Unmatched gap is unpaid and deducted from worked time. | Can push worked time under 480 and cost a half day. | AUDIT | OK | SH-10 |
| BRK-04 | AUTO_DEDUCT unpaid lunch, nothing punched (feature hidden by default, SH-15). | Worked 480 (540 less the 60-minute window). | Paid 1.00. | PROBE | OK | B01 |
| BRK-05 | AUTO_DEDUCT lunch and the employee also punches 12:30-13:30. | Punched gap counts toward the deduction: worked 480, not 450 (SH-12). | Paid 1.00. | PROBE | OK | B02 |
| BRK-06 | AUTO_DEDUCT lunch, OUT 19:30. | Worked 570 against a net schedule of 480: overtime 90. | Overtime 90, NORMAL, pending approval. | PROBE | OK | B03 |
| BRK-07 | AUTO_DEDUCT paid lunch. | Nothing deducted. Worked 540. | Paid 1.00. | PROBE | OK | B07 |
| BRK-08 | Shift 09:00-18:00 with a 1 h unpaid lunch (net 8 h). IN 09:05, OUT 18:00, both inside grace. | FIXED in engine 14 (was HALF_DAY). Worked stays 475; the 5 forgiven minutes are credited to the hour-band lookup only (480): PRESENT. Late 0. | Paid 1.00, LOP 0.00 (was 0.50 / 0.50). | PROBE | FIXED | X1, X2, X18, N-02 |
| BRK-09 | Shift 09:00-17:00 (8 h, no break), IN 09:08, OUT 17:00. | FIXED in engine 14 (was HALF_DAY). Worked stays 472; credit 8 gives band minutes 480: PRESENT. Late 0. | Paid 1.00, LOP 0.00 (was 0.50 / 0.50). | PROBE | FIXED | X3, N-02 |
| BRK-13 | Same shifts, IN one minute past grace (09:11 on a 1 h-lunch shift, or 09:11 on 09:00-17:00). | Late 1 minute. Worked 469; only the 10 grace minutes are credited: 479, still under 480: HALF_DAY. The credit never covers more than the grace. | Paid 0.50, LOP 0.50. A one-minute cliff just past grace remains on a shift with no spare minutes. | PROBE | DECIDE | X18, N-02 |
| BRK-10 | 4-hour shift 09:00-13:00, worked in full, on a company-wide 480-minute full-day band. | HALF_DAY. Bands are fixed minutes, not a share of the shift. | Paid 0.50, LOP 0.50 every day unless the shift has its own policy. | PROBE | DECIDE | X5, P-05 |
| BRK-11 | Break rule with 'excess break' counting. | Excess minutes recorded. With a cumulative count set, every Nth excess-break day becomes HALF_DAY (CUM-02). | As the resulting status. | CODE | OK | compute_breaks |
| BRK-12 | Break START with no END on a closed day (break modes only). | INCOMPLETE. Presence after the START is not credited. | Needs correction before close. | CODE | OK | credit_cutoff_for |

### 4. Overtime

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| OT-01 | OUT 19:30 (90 minutes after shift end), overtime policy needs post-approval. | Overtime detected 90, class NORMAL, pending. | Not paid until approved. Pending overtime blocks period close (PENDING_OVERTIME_APPROVAL). | PROBE | OK | A09 |
| OT-02 | OUT 18:25. | Excess 25, under the 30-minute minimum: no overtime. | None. | PROBE | OK | A10 |
| OT-03 | 250 minutes over, rounding DOWN to 30, daily cap 120, weekly budget left 60. | Detected 60 (250, then 240, then 120, then 60). | 60 minutes approved and paid. | PROBE | OK | J01 |
| OT-04 | Policy auto-approves (no post-approval). | Detected minutes are approved immediately. | Paid in the next payroll with no human check. | PROBE | OK | J01, X12 |
| OT-05 | Comp-off instead of pay. | Minutes recorded as comp-off earned. Expiry default 60 days. | Excluded from payroll overtime (comp-off days are paid in leave, never also in money). | PROBE | OK | J02 |
| OT-06 | Shift not flagged overtime-eligible (eligibility = SHIFT_FLAG). | No overtime. | None. | PROBE | OK | J03 |
| OT-07 | Day shift, night-overtime mode WINDOW 22:00-06:00, stays until 23:00. | 300 minutes of overtime, all classed NIGHT, although only 60 minutes fall inside the window. | The whole day's overtime is paid at the NIGHT multiplier. | PROBE | NEW | J04, N-06 |
| OT-08 | Same, stays until 20:00. | 120 minutes, class NORMAL. | NORMAL multiplier. | PROBE | OK | J05 |
| OT-09 | Weekly or monthly overtime cap, and days recalculated in a different order. | A day's detected overtime depends on what sibling days already used. Recomputing the same punches can give a different figure. | Pay can change between two recalculations without any punch changing. | CODE | DECIDE | WD-29 |
| OT-10 | Overtime on a full-day leave or on-duty day. | Zeroed. | None. | PROBE | OK | D03, D10 |
| OT-11 | How overtime becomes money. | Approved minutes are grouped by day class. | Minutes / 60 x (Basic / (days in month x 8)) x multiplier. Daily wage: daily rate / 8. The 8 hours is fixed, whatever the shift length. | CODE | DECIDE | payroll/engine.py, N-07 |
| OT-12 | Approved overtime whose day class has no multiplier in the policy. | n/a | Payroll run raises OT_MULTIPLIER_MISSING (error); the run cannot be finalised until fixed. | CODE | OK | engine.py |
| OT-13 | No Basic component in the salary structure. | n/a | Overtime paid on gross, with a warning (BASIC_MISSING). | CODE | OK | engine.py |

### 5. Holidays and weekly offs

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| OFF-01 | Weekly off, shift does not operate, no punch. | NOT_EXPECTED. | Monthly: paid 1.00. Not LOP. | PROBE | OK | C01 |
| OFF-02 | Weekly off, shift does not operate, worked 5 h. | PRESENT. All 300 minutes are overtime, class WEEKLY_OFF. | Day stays paid 1.00 plus 300 minutes at the weekly-off multiplier. | PROBE | OK | C02 |
| OFF-03 | Holiday, shift does not operate, worked 9 h. | PRESENT. All 540 minutes overtime, class HOLIDAY. | Paid 1.00 plus 540 minutes at the holiday multiplier. | PROBE | OK | C03 |
| OFF-04 | Holiday, shift does not operate, worked 20 minutes. | PRESENT. 20 minutes is under the 30-minute overtime minimum. | Paid 1.00, no overtime. Work under the minimum earns nothing extra. | PROBE | OK | C04 |
| OFF-05 | Holiday that the shift operates on, no punch. | Ordinary working day (P-02): INCOMPLETE. | At close LOP 1.00 under TREAT_ABSENT. Leave also charges this day. | PROBE | OK | C05, P-02 |
| OFF-06 | Same holiday, worked a normal 9 h. | PRESENT. No overtime (matches the schedule). | Paid 1.00 and no holiday premium. Owner decision P-02: the shift's day is an ordinary day. | PROBE | DECIDE | C06, P-02 |
| OFF-07 | Operated holiday, worked 11 h. | Overtime 120, class NORMAL. | NORMAL multiplier, not HOLIDAY. | PROBE | DECIDE | C07, P-02 |
| OFF-08 | Operated holiday, worked 2 h. | HALF_DAY by hour band. | Paid 0.50, LOP 0.50 (not worse than a no-show: that is 1.00 LOP). | PROBE | OK | C08 |
| OFF-09 | Weekly off that the shift operates on. | Same rules as OFF-05 to OFF-08. | As above. | CODE | OK | _shift_operates |
| OFF-10 | Half-day weekly off (calendar off fraction 0.50), no punch. | INCOMPLETE; the off half is already credited. | At close TREAT_ABSENT: paid 0.50, LOP 0.50. | PROBE | OK | C17, PER-02 |
| OFF-11 | Half-day weekly off, worked 4.5 h. | PRESENT (worked half plus off half). | Paid 1.00. | PROBE | OK | C18 |
| OFF-12 | Half-day weekly off, full day worked. | PRESENT. No overtime (the normal schedule applies). | Paid 1.00. | PROBE | OK | C19 |
| OFF-13 | Holiday that falls on a weekly off. | Follows the holiday rule. | Paid or unpaid by the holiday's own paid flag. | CODE | OK | _off_day_is_paid |
| OFF-14 | Unpaid holiday (is_paid = false), monthly employee, no punch. | NOT_EXPECTED. | Paid 0.00, LOP 0.00, unpaid-off 1.00. Salary is prorated down by the day. | PROBE | OK | C15 |
| OFF-15 | Shutdown day. | Treated like a holiday. | As a holiday. | CODE | OK | _OFF_DAY_TYPES |

### 6. Pay basis: monthly vs daily wage

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| PB-01 | Daily-wage employee, weekly off, no punch. | NOT_EXPECTED. | Paid 0.00, unpaid-off 1.00: no wage. | PROBE | OK | C12 |
| PB-02 | Daily wage, company holiday, no punch. | NOT_EXPECTED. | Unpaid-off 1.00. | PROBE | OK | C13 |
| PB-03 | Daily wage, PUBLIC holiday, no punch. | NOT_EXPECTED. | Paid 1.00. | PROBE | OK | C14 |
| PB-04 | Daily wage, weekly off, worked 9 h on an overtime-eligible shift. | PRESENT, overtime 540 WEEKLY_OFF. | Day paid 0.00 and unpaid-off 1.00; the hours are paid as overtime (9 h x daily rate / 8 x multiplier). | PROBE | OK | C16, X8 |
| PB-05 | Same, but the overtime is rejected at approval. | Day was classed 'unpaid-off' because overtime was detected, not because it was approved. | A rejected overtime leaves a worked day paid nothing at all. To confirm with a live case. | CODE | NEW | _off_day_work_pay, N-04 |
| PB-06 | Daily wage, weekly off, worked 20 minutes (under the overtime minimum). | No overtime. Hour band ABSENT. | Unpaid-off 1.00: the 20 minutes earn nothing. | CODE | OK | _off_day_work_pay |
| PB-07 | Daily-wage pay on a normal day. | PRESENT. | Daily rate x paid days. | CODE | OK | engine.py |
| PB-08 | Monthly employee, any off day, any paid/unpaid mix. | Paid, LOP and unpaid-off always add up to 1.00 per employed day. | Prorated lines: amount x paid days / days in month. A 28-day month costs more per LOP day than a 31-day month. | CODE | OK | engine.py |

### 7. Roster, swaps and overrides

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| ROS-01 | Roster week-off row (no shift on the row) on a calendar working day, no punch. | NOT_EXPECTED, even though the calendar says working. | Paid 1.00. Leave on that day consumes nothing. | PROBE | OK | C09 |
| ROS-02 | Roster week-off row, shift on the row, employee works 6 h on a calendar working day. | PRESENT. All 360 minutes are overtime, but classed NORMAL (the day's calendar type is 'working'). | Paid at the NORMAL multiplier, not WEEKLY_OFF. A rostered rest day pays less than a calendar weekly off. | PROBE | NEW | C10, N-01 |
| ROS-03 | Roster week-off row with no shift, employee punches 6 h. | PRESENT. No overtime (no schedule to measure against). | Paid 1.00 only. The 6 hours earn nothing extra. | PROBE | GAP | X11, SH-08 |
| ROS-04 | Roster 'working this holiday' row, no punch. | Ordinary working day: INCOMPLETE. | LOP 1.00 at close. | PROBE | OK | C11 |
| ROS-05 | Roster row left DRAFT. | Ignored by calculation. | Blocks period close (UNPUBLISHED_ROSTER). | CODE | OK | _run_validation |
| ROS-06 | Roster puts the employee on a different shift for a day. | That shift's times, break rules, overtime flag and (now) SHIFT-scoped policy apply. | Follows the day's result. | CODE | OK | SH-07, work_schedule.py |
| ROS-07 | Roster published, changed or deleted after the day was calculated. | A recalculation request is queued in the same transaction; unlocked days are recalculated. | Days recalculated before close. Locked days untouched. | CODE | OK | recalc.py |
| ROS-08 | Shift swap approved. | Both rosters swapped under one lock; both days recalculated. Past dates refused; stale pending swaps expire. | Follows each person's new shift. | CODE | OK | SH-20 |
| ROS-09 | Roster changed after leave was approved for that day. | Leave not re-checked. | A leave day can end up on a rostered day off, or the reverse. | AUDIT | DECIDE | P-12 |
| ROS-10 | Roster row names a shift with no published version on the date. | Refused at write (SH-18). | None. | CODE | OK | SH-18 |
| ROS-11 | Shift version missing at calculation time (rare, config gap). | Treated as no shift (see NSH group). | Day paid by the no-shift rules. | CODE | OK | version_missing |

### 8. Leave and on-duty

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| LV-01 | Full-day paid leave, no punch. | LEAVE. | Paid 1.00. | PROBE | OK | D01 |
| LV-02 | Full-day unpaid leave. | LEAVE. | Paid 0.00, LOP 1.00. | PROBE | OK | D02 |
| LV-03 | Full-day leave and the employee punches in 9 h. | Stays LEAVE. Overtime and late/early zeroed. 'Work on leave' flag raised. | Paid as leave only. HR must cancel the leave or confirm it stands before close (WORK_ON_LEAVE_UNRESOLVED). | PROBE | OK | D03 |
| LV-04 | Half-day leave (first half), worked 13:30-18:00. | HALF_DAY. The worked half is judged alone: hours are doubled before the band (270 x 2). | Paid 1.00. | PROBE | OK | D04 |
| LV-05 | Half-day paid leave, no punch. | LEAVE; the other half is unworked. | Paid 0.50, LOP 0.50. | PROBE | OK | D05 |
| LV-06 | Half-day leave, worked half only 2 h. | Doubled 240 = HALF_DAY band, so the worked half is lost. | Paid 0.50 (leave), LOP 0.50. The worked half must reach 4 h to count. | PROBE | OK | D06 |
| LV-07 | Half-day leave (first half), arrives 14:00. | Lateness measured from the half-way point 13:30: late 20. | Paid 1.00. | PROBE | OK | D07 |
| LV-08 | Half-day unpaid leave (second half), worked 09:00-13:30. | HALF_DAY. | Paid 0.50, LOP 0.50. | PROBE | OK | D08 |
| LV-09 | Half-day leave (second half), OUT 13:00 / 12:00. | 13:00: HALF_DAY, early 20, paid 1.00. 12:00: worked half lost, paid 0.50, LOP 0.50. | As stated. | PROBE | OK | X9, X10 |
| LV-10 | Leave on a calendar weekly off or holiday. | Leave days are only charged on working days. A shift that operates on that day makes it a working day (SH-03). | No leave balance is used on a plain off day. | CODE | OK | _working_shares |
| LV-11 | Leave on a rostered day off / on a rostered working holiday. | Day off: no leave used. Working holiday: leave used. | As stated. | CODE | OK | F7 |
| LV-12 | Leave approved or cancelled after the day was calculated. | Recalculated at once. | Follows. | AUDIT | OK |  |
| LV-13 | Leave in an attendance period that is closed. | Refused (apply, approve and cancel). | None. | CODE | OK | PD-3 |
| LV-14 | ON_DUTY approved, no punch. | ON_DUTY. | Paid 1.00. | PROBE | OK | D09 |
| LV-15 | ON_DUTY approved and employee works 11 h. | ON_DUTY. Overtime zero. | Paid 1.00 only: the extra hours earn nothing. | PROBE | DECIDE | D10 |
| LV-16 | ON_DUTY with 'on duty requires punch', no punch. | INCOMPLETE. | Needs a punch or a regularization. | PROBE | OK | X7 |

### 9. Overnight shifts

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| NGT-01 | Night shift 22:00-06:00 on time (starts 10 Nov, ends 11 Nov). | PRESENT. The whole shift belongs to 10 Nov. Worked 480. | Paid 1.00 on 10 Nov. 11 Nov is independent. | PROBE | OK | F01 |
| NGT-02 | Same shift, OUT 07:00. | Overtime 60, class NIGHT (shift is flagged a night shift). | NIGHT multiplier. | PROBE | OK | F02 |
| NGT-03 | Same shift, IN 22:07 (inside grace) / IN 22:40 (30 minutes past grace). | 22:07: PRESENT since engine 14 (worked 473, band 480). 22:40: late 30, worked 440 + 10 credit = 450: HALF_DAY. | 22:07: paid 1.00. 22:40: paid 0.50, LOP 0.50 (a real shortfall beyond grace). | PROBE | FIXED | F03, N-02 |
| NGT-04 | Night shift starting on a weekly off the shift does not operate on. | All 480 minutes are overtime, class WEEKLY_OFF. | The whole shift is paid at the weekly-off multiplier because it started on that date. | PROBE | DECIDE | F04, P-01 |
| NGT-05 | Night shift starting on a holiday the shift does not operate on. | All 480 minutes overtime, HOLIDAY. | HOLIDAY multiplier for the whole shift. | PROBE | DECIDE | F05, P-01 |
| NGT-06 | Night shift starting on a working day and ending on a holiday morning. | Ordinary day: the start date decides. Overtime 0 (probe ran it as a plain working day). | No holiday treatment for the hours after midnight. | CODE | DECIDE | F06, P-01 |
| NGT-07 | Overnight shift on the employee's last working day. | Checkout after the last day is accepted (SH-09). | Final settlement uses the full shift. | CODE | OK | SH-09 |
| NGT-08 | Overnight shift crossing a month or year end. | Belongs entirely to the start date and its period. | Paid in the start date's month. | AUDIT | OK |  |
| NGT-09 | Night worker's rostered day off the next morning. | Morning punches of the previous night shift stay with that day; the off day is NOT_EXPECTED. | Paid 1.00. | CODE | OK | engine 11, punch_ownership.py |
| NGT-10 | Night shift then a day shift within four hours. | Punches go to the day whose shift they overlap most; no punch counts twice (SH-02). | Each day pays on its own punches. | CODE | OK | SH-02 |
| NGT-11 | Night worker forgot OUT at 06:00 and tries to punch IN at 22:00 the same day. | Refused when the last punch (an IN) is under 18 hours old. | Employee cannot clock in; HR must correct. | AUDIT | GAP | R-07 |

### 10. Split shifts

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| SPL-01 | Split shift 07:00-11:00 and 16:00-20:00, both blocks worked. | PRESENT. Worked 480, scheduled 480. | Paid 1.00. | PROBE | OK | G01 |
| SPL-02 | Only the morning block worked, behaviour IGNORE. | HALF_DAY by hour band (240). Missed blocks 1. | Paid 0.50, LOP 0.50. | PROBE | OK | G02 |
| SPL-03 | Same, behaviour HALF_DAY / ABSENT / REQUIRE_REGULARIZATION. | HALF_DAY / ABSENT / INCOMPLETE. | Paid 0.50 / LOP 1.00 / unresolved until corrected. | PROBE | OK | G03-G05 |
| SPL-04 | First block started at 07:45. | No late flag is ever computed for a split shift. Worked 435: HALF_DAY by band. | Paid 0.50, LOP 0.50. | PROBE | DECIDE | G06, P-11 |
| SPL-05 | Both blocks and one extra hour. | Overtime 60. | Overtime pending approval. | PROBE | OK | G07 |
| SPL-06 | Second block after midnight (20:00-23:00 then 01:00-04:00). | Blocks placed in sequence (SH-04). Worked 360 of 360 scheduled, but the 480 band makes it HALF_DAY. | Paid 0.50, LOP 0.50 for a full shift. | PROBE | DECIDE | G08, P-05 |
| SPL-07 | A block worked for only 30 minutes. | Any overlap counts as attended. Missed blocks 0. | Band alone decides pay. | PROBE | DECIDE | G09, P-11 |

### 11. Flexible shifts

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| FLX-01 | Flexible shift: start window 09:00-10:00, 8 h required, core 11:00-16:00. IN 09:30, OUT 17:30. | PRESENT. Worked 480. Late 0. | Paid 1.00. | PROBE | OK | H01 |
| FLX-02 | IN 10:30, OUT 18:30. | Late 20 (measured from the end of the window, less grace). Worked 480: PRESENT. | Paid 1.00 (a small late band does nothing). | PROBE | OK | H02 |
| FLX-03 | IN 10:30, OUT 16:00 (5.5 h). | HALF_DAY. | Paid 0.50, LOP 0.50. | PROBE | OK | H03 |
| FLX-04 | Leaves 15:00 (core hours 11-16 broken). | Core-hours breach flag. HALF_DAY by band. With behaviour ABSENT: ABSENT. | Paid 0.50 or LOP 1.00. | PROBE | OK | H04, H06 |
| FLX-05 | Works 9.5 h. | Overtime 90 (against the 8 h required). | Overtime pending approval. | PROBE | OK | H05 |
| FLX-06 | Works 7 h of 8 h required. | HALF_DAY by band. Early departure is never flagged on a flexible shift. | Paid 0.50, LOP 0.50. | PROBE | DECIDE | X16, P-10 |
| FLX-07 | Flexible shift at night. | Cannot be configured: flexible shifts cannot cross midnight. | n/a | AUDIT | DECIDE | P-10 |

### 12. No shift resolved

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| NSH-01 | No shift, working day, no punch. | INCOMPLETE (or ABSENT if missing-shift behaviour = ABSENT). | LOP 1.00 at close under TREAT_ABSENT or ABSENT. | PROBE | OK | I01, I07 |
| NSH-02 | No shift, weekly off or holiday, no punch. | NOT_EXPECTED (SH-08). | Paid 1.00. | PROBE | OK | I02 |
| NSH-03 | No shift, working day, worked 1 minute. | ABSENT by hour band. | LOP 1.00. | PROBE | OK | I03 |
| NSH-04 | No shift, worked 5 h / 9 h. | HALF_DAY / PRESENT. No late, early or overtime. | Paid 0.50 / 1.00. | PROBE | OK | I04, I05 |
| NSH-05 | No shift, worked 9 h on a weekly off or holiday. | PRESENT. No overtime, ever. | Paid 1.00. The 9 hours earn no premium. | PROBE | GAP | I06, SH-08 |
| NSH-06 | New joiner with an assignment but no shift yet. | Every working day INCOMPLETE until a shift is assigned. | LOP at close if never corrected. | AUDIT | GAP | R-01 |
| NSH-07 | Shift assigned but no published version covers the date. | Treated as no shift. | As NSH group. | CODE | OK | version_missing |

### 13. Cumulative rules (every Nth late)

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| CUM-01 | Policy: every 3rd late day in a month is a half day. Day with late 20. | 1st and 2nd late day: PRESENT. 3rd, 6th, 9th: HALF_DAY. | Paid 0.50, LOP 0.50 on every 3rd late day. | PROBE | OK | E01-E03 |
| CUM-02 | Same rule for excess-break days. | Counted per calendar month. Prior days come from other rows. | As CUM-01. | CODE | OK | WD-32 |
| CUM-03 | An earlier late day is regularized away. | Later days keep their old result until they are recalculated. | Pay of later days can change only after a recalculation. | CODE | DECIDE | WD-29 |

### 14. Assignment, shift-version and policy changes

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| ASN-01 | Shift changes from a future date. | Old shift until then, new shift after. | Neither affects pay directly. | AUDIT | OK |  |
| ASN-02 | Assignment or shift version backdated into an open past month. | Allowed. A recalculation request recalculates unlocked days. HR is not shown the impact first. | Days in the open month can change status and pay. | CODE | DECIDE | P-08, SH-13 |
| ASN-03 | Same, into a closed period. | Refused for shift versions and assignments. | None. | CODE | OK | assert_date_open |
| ASN-04 | Attendance-policy version published (new grace, bands, caps). | No recalculation is queued. Days keep the old figures until the next sweep or period close. | Open days can be paid on the old policy. | CODE | GAP | plan 8, P-09 |
| ASN-05 | Policy assignment created or ended. | Recalculation queued. | Follows. | CODE | OK | recalc.py |
| ASN-06 | Employee has no shift assigned and 'clear shift' is chosen. | Possible since SH-13. | NSH group. | CODE | OK | SH-13 |
| ASN-07 | Shift deleted or deactivated while assigned. | Refused. | None. | AUDIT | OK |  |
| ASN-08 | Branch change. | Branch timezone and policies resolve by date. | None. | AUDIT | OK |  |
| ASN-09 | Daily sweep and period close. | Sweep recalculates recent unlocked days; close recalculates every unlocked day. | Late shift edits land at close. | AUDIT | OK |  |

### 15. Joiners, leavers and configuration failures

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| EMP-01 | Day before the employee joined. | NOT_JOINED, even with punches. | Paid 0, LOP 0. Payroll prorates on employed days. | PROBE | OK | X13 |
| EMP-02 | Day after exit. | EXITED. | Paid 0, LOP 0. | PROBE | OK | X13 |
| EMP-03 | No calendar resolves for the date. | CONFIG_ERROR. | Not paid, not LOP; blocks the close (CONFIG_ERROR) until fixed. | PROBE | OK | X14 |
| EMP-04 | No attendance policy resolves. | CONFIG_ERROR. | As EMP-03. | PROBE | OK | X15 |
| EMP-05 | Unresolvable timezone on an old shift version. | CONFIG_ERROR on that day instead of an error. | As EMP-03. | CODE | OK | resolve_zoneinfo |
| EMP-06 | Paid days exceed the days employed in the legal entity. | n/a | Payroll raises PAID_DAYS_EXCEED_EMPLOYED; run refused until attendance is fixed. | CODE | OK | engine.py |

### 16. Regularization

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| REG-01 | Types: MISSING_PUNCH, WRONG_PUNCH, WRONG_SHIFT, WRONG_STATUS, WFH, ON_DUTY, EXCESS_BREAK, FULL_DAY, BREAK_CORRECTION, EARLY_DEPARTURE_APPROVAL. | Applied as synthetic punches or overlays, then the day is recalculated. | Pay follows the recalculated day. | CODE | OK | schemas.py |
| REG-02 | Pending regularization at close. | Blocks the close (PENDING_REGULARIZATION). | None until decided. | CODE | OK | _run_validation |
| REG-03 | EARLY_DEPARTURE_APPROVAL. | Forward-dated by design; once approved, removes the forced half day (DAY-09). | Avoids a half-day LOP. | PROBE | OK | E05 |
| REG-04 | WFH request. | The engine's WFH overlay is documented as a no-op; the status is not produced by the calculation. | Confirm with the owner what a WFH day should pay. | CODE | DECIDE | calculation.py _resolve_primary_status docstring |

### 17. Period close and the payroll hand-off

| ID | Scenario | Attendance | Pay | Check | Verdict | Refs |
|---|---|---|---|---|---|---|
| PER-01 | Close is blocked by any of: unresolved work-on-leave, paid/LOP mismatch, KEEP_INCOMPLETE rows, pending regularization, pending overtime, draft roster, orphan punches, CONFIG_ERROR days, employed days with no attendance row. | Period stays OPEN. | Payroll cannot read an open period. | CODE | OK | _run_validation |
| PER-02 | INCOMPLETE rows at close. | Resolved by the day's own policy: TREAT_ABSENT (default), TREAT_PRESENT, or KEEP_INCOMPLETE (blocks). | TREAT_ABSENT: paid = off share, LOP = rest. TREAT_PRESENT: paid 1.00. Half-day leave: only the worked half is decided. | CODE | OK | _apply_incomplete_lock_resolution |
| PER-03 | What payroll receives per employee. | Frozen summary: present, half, absent, leave, holiday, weekly-off, on-duty days, paid, LOP, unpaid-off, payable days, overtime minutes by class, comp-off, late count. | Invariant: paid + LOP + unpaid-off = payable days = employed days. | CODE | OK | _aggregate_day_rows |
| PER-04 | Overtime into payroll. | Approved minutes not converted to comp-off, grouped by day class and the multiplier of the policy version that applied that day. | Money per OT-11. | CODE | OK | list_payable_overtime_for_period |
| PER-05 | Period reopened after payroll inputs were locked. | Version changes. | Payroll re-checks the period state before approving or finalising, so the stale run is caught. | CODE | OK | period_state |
| PER-06 | Locked days after close. | Never recalculated; keep their stored engine version. | Frozen. | CODE | OK |  |
| PER-07 | Late count in the summary. | Reported only. | No money, unless a cumulative rule already changed the status. | CODE | OK |  |

## 7. Owner decisions the map depends on

| Ref | Question | Today | Scenarios |
|---|---|---|---|
| P-01 | Overnight shift crossing a holiday or weekly off: which date decides? | Start date decides everything. | NGT-04, NGT-05, NGT-06 |
| P-03 | Should an unpunched unpaid lunch be deducted automatically? | No, unless an automatic break mode is set (hidden). | BRK-02 |
| P-04 | Is early arrival ever overtime? | Never on fixed shifts. | DAY-15, DAY-16 |
| P-05 | Hour bands for short and long shifts: fixed minutes or a share? | Fixed minutes on the attendance policy. | BRK-10, SPL-06, N-02 |
| P-07 | Grace: forgiven minutes or threshold? Does grace protect the hour band? | Forgiven minutes, daily, does not protect the band. | DAY-04, DAY-06, BRK-08, BRK-09, NGT-03, N-02 |
| P-08 | May shift versions or assignments be backdated into an open past month, and should HR see the impact first? | Allowed; no preview. | ASN-02 |
| P-09 | Should every shift, roster, swap, assignment and policy change recalculate at once? | All but a policy-version publish. | ASN-04 |
| P-10 | Flexible shifts at night, and early departure on flexible shifts. | Not supported / never detected. | FLX-06, FLX-07 |
| P-11 | Split shifts: lateness, early departure, partly worked blocks. | Not computed; any overlap counts. | SPL-04, SPL-07 |
| P-12 | Roster changed after leave was approved. | Not re-checked. | ROS-09 |
| P-14 | Two shifts in one day, or a mid-day shift change. | Not supported. | none yet |
| D-01 | Overtime policy: auto-approve vs post-approval, daily cap, and what should happen to a 24-hour pair. | Set per policy; no length cap on a session. | OT-04, PUN-06 |
| D-02 | WFH regularization: what should a WFH day pay? | Engine overlay is a no-op. | REG-04 |
| D-03 | ON_DUTY day: should hours beyond the shift ever earn overtime? | No. | LV-15 |
| D-04 | Overtime divisor (8 hours) and day-class on a roster rest day. | 8 h fixed; NORMAL class. | OT-11, ROS-02 |
| D-05 | Overtime classing on a holiday the shift operates on. | Ordinary pay, no premium (P-02). | OFF-06, OFF-07 |

P-02, P-06 and P-13 were decided by the owner on 15 Nov 2026 (see the remediation plan) and are built in. The D-xx rows are new questions raised by this map.

## 8. What each new finding needs

| ID | Suggested fix or decision | Evidence |
|---|---|---|
| N-01 | Classify a roster week-off day as WEEKLY_OFF for overtime, or confirm NORMAL is intended. | Probe C10 |
| N-02 | Done: forgiven grace minutes credit the band lookup only (`grace_band_credit`). Open: a one-minute cliff just past grace on a shift with no spare minutes (BRK-13); bands as a share of the shift stays P-05. | Probes X1-X3, X18, F03 |
| N-03 | Done: a pair ending at or after its shift day's window end is split into a lone IN and a lone OUT (`assign_owners`). Open, separate change: stale-punch handling at the punch endpoint, after a dedicated audit with night shifts. | Probes S1, S7, X17 |
| N-04 | Base the unpaid-off decision on approved overtime, or recalculate when the overtime is decided. Confirm on a live case. | Code only |
| N-05 | Pick the harsher of the two or document the order. | Probe A19 |
| N-06 | Split overtime minutes by window, or confirm one class per day is intended. | Probe J04 |
| N-07 | Confirm that 8 hours is the company's standard divisor. | payroll/engine.py |

## 9. Method and limits

- The probes call `evaluate_day` and the punch-ownership functions directly (pure functions, no database), using `apps/api/.venv` Python. Inputs are exactly what the service layer would pass for the baseline in section 2. The probe script is not committed.
- Not run: the database path (loading punches, writing rows), the Celery recalculation queue, real payroll runs, the web and mobile screens. Those rows are marked CODE or AUDIT.
- Late and early bands, overtime multipliers and the 30-minute overtime minimum are my test values. Your policies may differ; the logic is the same, the thresholds move.
- Not covered: geofence and face verification (they refuse a punch, they do not change a day), leave balance and encashment mechanics, statutory deductions (PF, ESI, tax) on the changed earned wages, and any company with real pilot data (there is none yet).
- Repo state: local `test` branch at 6416420, not pushed; migration 20261115090000 still needs a person to merge.
