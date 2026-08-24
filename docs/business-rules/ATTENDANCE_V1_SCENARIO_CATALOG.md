# Attendance V1 — Realistic HR Scenario Catalog

**Read this if:** you want to see, in plain terms, what the system actually does for real day-to-day HR situations — including common Indian HR patterns.

Every scenario shows: the situation, what day-type/shift/policy applies, what punches/leave/regularization/overtime are involved, the expected result and why, what it means for payroll, and whether HR can correct it (and whether that's still possible after the period is locked).

Results marked **FUTURE** or **GAP** are not supported today — see the [Gaps document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md) for the reasoning and recommended path.

---

## A. Everyday attendance patterns

| # | Scenario | Situation | Expected result | Reason | Payroll fact | HR correction (open) | After lock |
|---|---|---|---|---|---|---|---|
| 1 | Normal full day | 09:00–18:00 shift, punches 09:00/18:00, no issues | **Present** | Worked minutes meet the Present threshold | 1.00 paid day | N/A | N/A |
| 2 | Slightly late, within grace | Shift 09:00, grace 15 min, punch IN 09:10 | **Present**, not marked late | 10 min is within the 15-min grace window | 1.00 paid day | N/A | N/A |
| 3 | Late beyond grace, minor | Grace 15 min, punch IN 09:20 (5 min late after grace) | **Present**, flagged late (if no band pushes it further) | Late but not enough to change status | 1.00 paid day | Regularization if disputed | Refused |
| 4 | Late enough to trigger Half-Day band | Grace 15 min, late band "30+ min = Half-Day", punch IN 09:50 | **Half-Day** | Crosses the configured late-to-half-day band | 0.50 paid, 0.50 unpaid | Regularization request | Refused |
| 5 | Early departure | Grace-out 10 min, punch OUT 17:00 for an 18:00 end | Present + flagged early (or Half-Day if band forces it) | Depends on configured early-departure bands | Per resulting status | Regularization | Refused |
| 6 | Missing OUT punch | Punch IN only, missing-punch policy = Incomplete (default) | **Incomplete** | No pairing possible for the IN punch | 0 paid, 0 unpaid until period lock resolves it | Regularization (add OUT) | Locked days can't add punches — must reopen |
| 7 | Missing IN punch | Punch OUT only | **Incomplete** | Orphan punch with no IN to pair | Same as above | Regularization (add IN) | Same as above |
| 8 | Duplicate device punches | Two IN taps 5 seconds apart (duplicate window 60 sec) | Treated as **one punch** | Falls within the duplicate-collapse window | No effect | N/A | N/A |
| 9 | Multiple in/out cycles in a day | IN 09:00, OUT 13:00 (personal errand), IN 14:00, OUT 18:00 | **Present**, worked minutes = sum of both pairs (if "sum all pairs" mode) | Multi-punch mode set to sum-all-pairs | 1.00 paid, minus any gap treated as unpaid break if it matches a break window | N/A | N/A |
| 10 | Odd punch sequence: IN, IN, OUT | Second IN treated as the real start; first IN becomes an orphan | 1 valid pair + 1 orphan; may show **Incomplete** flag on the orphan | Pairing logic assigns IN→OUT to the closest valid pair | Depends on resulting status | Regularization to clarify | Refused |
| 11 | No punches at all on a working day | Employee simply didn't show up, no leave applied | **Absent** (if missing-punch policy = Absent) or **Incomplete** (if default) | Governed entirely by the missing-punch policy setting | 0 paid, 1.00 unpaid (if Absent) | Regularization or manual leave application | Refused |
| 12 | Worked exactly to the minute-boundary | Worked minutes exactly equal the Present threshold | **Present** | Threshold is inclusive | 1.00 paid | N/A | N/A |

## B. Calendar, holiday & weekly-off patterns

| # | Scenario | Situation | Expected result | Reason | Payroll fact | HR correction | After lock |
|---|---|---|---|---|---|---|---|
| 13 | Ordinary weekly off, no work | Calendar says Weekly Off, employee doesn't work | **Not Expected** | Weekly-off, nobody forced work | 1.00 paid | N/A | N/A |
| 14 | Public holiday, no work | Calendar says Holiday, nobody scheduled to work | **Not Expected** | Standard holiday | 1.00 paid | N/A | N/A |
| 15 | Holiday falls on the weekly-off day (e.g. festival on a Sunday) | Hard holiday + weekly-off coincide | **Weekly Off**, flagged "holiday coincided with weekly off" — **no automatic substitute day** | Documented rule — see [Client Flow](./ATTENDANCE_V1_CLIENT_FLOW.md#4-what-kind-of-day-is-it--the-calendar-decision) | 1.00 paid, same as any weekly off | HR can manually add a Substitute Holiday exception elsewhere | Calendar exceptions can't be added for locked dates |
| 16 | Holiday, but employee is required to work (e.g., factory/security) | Roster or shift marked "operates on holiday" | Evaluated normally — **Present** (or per punches) | Expectation overridden by roster/shift flag | 1.00 paid + possible Holiday-classified overtime | N/A | N/A |
| 17 | Weekly off, but employee comes in and works anyway (no override set) | No roster/shift override, but punches exist | Still **evaluated** (system doesn't ignore the punches) — typically Present | The system does not silently discard punches on a not-expected day | 1.00 paid + possible Weekly-Off-classified overtime | N/A | N/A |
| 18 | Optional/Restricted holiday, company setting off (default) | E.g., a regional festival marked "Optional" | **Working day** — treated normally, holiday name shown for reference | Soft-holiday default | Normal day rules apply | N/A | N/A |
| 19 | Optional/Restricted holiday, company setting turned on | Same, but the "treat as hard holiday" flag is enabled | Treated as a **hard holiday** — Not Expected | Company-wide flag hardens soft holidays | 1.00 paid | N/A | N/A |
| 20 | "Working Holiday" type | A day marked as a holiday for naming purposes but still a working day | **Working day**, holiday name shown for reference | By design | Normal day rules | N/A | N/A |
| 21 | Special Working Day declared on a normal weekly-off | HR declares a specific Sunday as a special working day | **Expected to work**, evaluated normally | Exception always wins over weekly-off | Per punches | N/A | N/A |
| 22 | Shutdown day (declared company closure) | Exception type = Shutdown | **Not Expected**, unless specifically rostered to work | Exception wins | 1.00 paid (per usual shutdown pay policy) | N/A | N/A |
| 23 | Holiday cancelled for this year | HR removes a holiday's holiday-status via a Cancel-Holiday exception | Reverts to **Weekly Off or Working Day**, whichever underlying rule applies | Exception strips the holiday | Per resulting day type | N/A | N/A |
| 24 | Alternate Saturdays off | Weekly-off pattern: Saturday + alternate-week rule | Correctly alternates **Weekly Off** week to week | Supported natively | 1.00 paid on off Saturdays | N/A | N/A |
| 25 | 1st/3rd Saturday off | Weekly-off pattern: Saturday + "1st and 3rd" rule | Correctly marks only 1st/3rd Saturdays as **Weekly Off** | Supported natively | Same as above | N/A | N/A |
| 26 | 2nd/4th Saturday off | Same pattern, different weeks selected | Correctly marks 2nd/4th Saturdays | Supported natively | Same as above | N/A | N/A |
| 27 | Last Saturday off | Weekly-off pattern: "last occurrence in month" | Correctly marks the final Saturday of the month | Supported natively | Same as above | N/A | N/A |
| 28 | Kerala-specific holiday calendar | A branch/employee assigned the Kerala holiday calendar instead of the national one | Correct regional holidays apply for that branch/employee | Calendar assignment can be scoped per branch/employee | Per resulting day type | N/A | N/A |
| 29 | State holiday differs by branch (e.g. Maharashtra vs. Karnataka) | Two branches, two different holiday calendars assigned | Each branch's employees follow their own branch's calendar | Calendar precedence resolves per employee's assignment | Per resulting day type | N/A | N/A |

## C. Shift types & schedules

| # | Scenario | Situation | Expected result | Reason | Payroll fact | HR correction | After lock |
|---|---|---|---|---|---|---|---|
| 30 | Night / cross-midnight shift, normal | 22:00–06:00, worked as scheduled | **Present** on the **start date**, not split across two dates | Shift-start-date ownership rule | 1.00 paid on the start date | N/A | N/A |
| 31 | Security staff, rotating night shift via roster | Roster assigns Night Shift for specific dates | Schedule uses the roster's shift for those dates | Roster overrides default assignment shift | Per punches | Roster edits while open | Refused once locked |
| 32 | Factory shift, fixed timing, high punctuality enforcement | Tight grace period (e.g. 5 min), strict late bands | Small lateness quickly triggers Half-Day/Absent | Bands are fully configurable per policy | Per resulting status | Regularization | Refused |
| 33 | Split shift (e.g., 06:00–10:00 and 14:00–18:00) | Both blocks fully punched | **Present**, late/early not computed for split shifts | Split-shift rule: lateness not evaluated, only completion | 1.00 paid | N/A | N/A |
| 34 | Split shift, one block missed entirely | Only the morning block punched; afternoon missed | Result depends on the "missed block" setting: Ignore / Half-Day / Absent / Require Correction | Configurable per policy | Per resulting status | Regularization if "require correction" | Refused |
| 35 | Flexible/IT-style shift, arrival within window | Window 08:00–11:00, required 8 hours, employee arrives 10:00 works till 18:00+break | Evaluated against required minutes met, not a fixed start time | Flexible-shift rule | Per resulting status | N/A | N/A |
| 36 | Flexible shift, "core hours" expectation | HR configured a mandatory 11:00–16:00 core window | **Not enforced today** — core hours are stored but never checked | **GAP** — see [Gaps document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md) | No consequence today regardless of core-hours compliance | — | — |
| 37 | Field employee with On-Duty regularization | Employee requests "On-Duty" type correction for a client-site visit day | Request is accepted by policy, but does **not** produce an On-Duty status — only helps if it results in punches/shift changes | **GAP** — see ND-06 | Depends on what the correction actually changes | Regularization | Refused |
| 38 | Work-From-Home day | Employee expected to be marked WFH | **Not currently produced as a distinct status** | **GAP/FUTURE** — see ND-06 | Falls back to punch-based evaluation if any punches exist, otherwise Incomplete/Absent | Regularization (limited effect) | Refused |

## D. Leave interactions

| # | Scenario | Situation | Expected result | Reason | Payroll fact | HR correction | After lock |
|---|---|---|---|---|---|---|---|
| 39 | Full-day paid leave, no punches | Approved paid leave synced onto the date | **Leave** | Full-day leave overlay | 1.00 paid | N/A (correct via leave source) | Leave sync refused once locked |
| 40 | Full-day unpaid leave | Approved unpaid leave synced | **Leave** | Same overlay, unpaid flag | 0 paid, 1.00 unpaid | N/A | Refused |
| 41 | Half-day leave, employee also works the other half | 0.50-day leave + punches showing worked time | **Half-Day** | Leave credit (0.50) combined with worked punches | ~1.00 paid (0.50 leave + 0.50 worked, depending on exact combination) | N/A | Refused |
| 42 | Leave + punches, "leave wins" mode (default) | Employee has approved leave but also punched in that day | **Leave** status; late/early cleared | Default overlay behaviour | Per leave's paid/unpaid setting | N/A | Refused |
| 43 | Leave + punches, "flag work-on-leave" mode | Same situation, policy set to hint mode instead | Punch-based status is **kept**, flagged "worked despite leave" | Alternate configured behaviour | Per punch-based status | N/A | Refused |
| 44 | Leave synced after attendance was already calculated | Leave approved a few days after the original calculation | Day is **automatically recalculated** to reflect the leave | Sync triggers recompute | Updated to reflect leave | N/A | N/A while open |
| 45 | Leave synced after the period was locked | Same situation, but period is already Closed | **Refused** — leave sync is blocked | Lock precedence | Unchanged | Reopen period first | N/A |
| 46 | Leave on a holiday date | Employee applies leave on a date that's already a holiday | Status becomes **Leave**; calendar day-type stays Holiday underneath | Leave never rewrites the calendar | Per leave's paid/unpaid setting | N/A | Refused |

## E. Regularization (corrections)

| # | Scenario | Situation | Expected result | Reason | Payroll fact | HR correction | After lock |
|---|---|---|---|---|---|---|---|
| 47 | Employee requests missing-punch correction | Forgot to punch OUT, submits request with reason | **SUBMITTED**, pending review | Standard workflow entry | Blocks period finalize until decided | Approve/reject | N/A |
| 48 | Manager approves the correction | Manager reviews and approves | System adds the missing punch → day **recalculated** → e.g. becomes Present | Additive-punch correction model | Updated per recalculated result | N/A | N/A |
| 49 | HR rejects a correction | HR reviews and rejects with a comment | Day **unchanged**; employee may resubmit depending on policy | Rejection has no side effects | Unchanged | Employee can resubmit if allowed | N/A |
| 50 | Correction requested for a date beyond the allowed backdating window | Policy allows max 7 days backdating; request is for 15 days ago | **Rejected at submission** | Policy enforcement | N/A | N/A | N/A |
| 51 | Correction requested for a locked period | Employee tries to submit a correction for an already-closed period | **Refused** (if policy blocks corrections when locked, which is the default) | Lock precedence | N/A | Reopen period first | N/A |

## F. Overtime

| # | Scenario | Situation | Expected result | Reason | Payroll fact | HR correction | After lock |
|---|---|---|---|---|---|---|---|
| 52 | Standard overtime, requires manager approval | Worked 90 min beyond scheduled, policy requires post-approval | Overtime record **PENDING** until decided | Default OT policy setting | Blocks period finalize | Approve/reject | N/A |
| 53 | Overtime auto-approved | Approval chain set to Auto | Overtime **AUTO_APPROVED** immediately | No human approval configured | Recorded OT minutes immediately | N/A | N/A |
| 54 | Overtime rejected | Manager rejects the OT request | OT record **REJECTED**, 0 minutes count | Rejection is terminal and frozen | 0 OT minutes | N/A | N/A |
| 55 | Overtime on a holiday | Worked extra minutes on a day classified Holiday | Overtime classified as **Holiday** overtime | Day-class detection | Fact recorded; no automatic pay multiplier applied | N/A | N/A |
| 56 | Overtime on a weekly off | Same, but on a Weekly-Off day | Overtime classified as **Weekly-Off** overtime | Same mechanism | Same as above | N/A | N/A |
| 57 | Overtime on a night shift | Worked extra minutes past a cross-midnight shift | With the default setting, classified as **Normal** overtime, not Night | **KNOWN LIMITATION** — see [Gaps document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md) (ND-03) | Recorded as Normal-classified OT | N/A | N/A |
| 58 | Weekly overtime cap reached | Detected OT would exceed the remaining weekly cap | Overtime is **clipped** to whatever remains under the cap | Cap enforcement | Reduced OT minutes recorded | N/A | N/A |
| 59 | Comp-off earned instead of pay | OT policy set to comp-off instead of pay | Comp-off minutes (+ optional expiry) recorded as a **fact** | OT policy setting | No money calculated; comp-off balance itself is tracked by the future Leave module | N/A | N/A |
| 60 | OT approval still pending at month-end | Employee's OT request not yet decided when HR tries to close the period | **Finalize is blocked** | Pending-OT validation blocker | N/A | Approve/reject first | N/A |

## G. Organisational changes

| # | Scenario | Situation | Expected result | Reason | Payroll fact | HR correction | After lock |
|---|---|---|---|---|---|---|---|
| 61 | Branch transfer mid-month | Employee moves to a new branch (different timezone/calendar) partway through | Days before the transfer use the old branch's calendar/timezone; days after use the new one | Assignment is always evaluated as-of the specific date | Split correctly across the transfer date | N/A | N/A |
| 62 | Department transfer mid-month | Same idea, different department (possibly different policy) | Policy resolution follows the department that was active on each specific date | As-of-date resolution | Split correctly | N/A | N/A |
| 63 | Manager change | Employee's reporting manager changes mid-month | Regularization/OT approvals already in the chain use the manager assigned **as of the attendance date**, not today's manager | Documented approver rule (PD-APR-1) | N/A | N/A | N/A |
| 64 | Employee-specific policy override | HR sets a custom Attendance Policy just for one employee (e.g., a senior exec with different grace rules) | That employee's policy overrides company/department/etc. defaults | Employee is the most specific level | Per the custom policy | N/A | N/A |
| 65 | Employee joins mid-month | Joining date falls in the middle of an open period | Days before joining show **Not Joined**, fully paid, no manual entry needed | Employment gate | 1.00 paid for pre-joining days (standard convention) | N/A | N/A |
| 66 | Employee's last working day is mid-month | Last working day recorded partway through the period | Days after the last working day show **Exited**, fully unpaid | Employment gate | 0 paid for post-exit days | N/A | N/A |
| 67 | Employee rehired after a gap | Employee left, then rejoined months later | The gap period shows Exited/Not Joined as applicable; the new spell is evaluated normally from the new joining date | Employment gate treats each employment record independently | Per each period's employment state | N/A | N/A |
| 68 | Policy version changes mid-period (e.g., grace period updated from 15 to 10 minutes, effective next month) | Two policy versions, each with their own effective dates | Each date uses whichever policy version was in effect **on that date** | Effective-dated versioning | Per the version in effect for each date | N/A | Locked days keep whatever version was used when calculated |
| 69 | Holiday calendar updated after attendance was already calculated | HR adds a holiday after some days were already calculated | If the period is still open, recalculating those days will pick up the new holiday | Recalculation reflects current configuration | Updated once recalculated | Manual recalculation trigger | Locked days stay as originally calculated until reopened |
| 70 | Shift schedule changes mid-period | A new shift version published partway through the month | Each date uses whichever shift version was in effect (published) on that date | Effective-dated versioning | Per version in effect | N/A | Same as above |

## H. Period lifecycle

| # | Scenario | Situation | Expected result | Reason | Payroll fact | HR correction | After lock |
|---|---|---|---|---|---|---|---|
| 71 | Period validated with no issues | HR runs Validate, nothing pending | Ready to finalize | No blockers found | N/A | N/A | N/A |
| 72 | Period validated with pending regularization | A correction request is still SUBMITTED | **Blocked** — cannot finalize | Validation blocker | N/A | Approve/reject first | N/A |
| 73 | Period validated with an unpublished (draft) roster | A roster entry inside the period is still Draft | **Blocked** — cannot finalize | Validation blocker | N/A | Publish or remove the draft roster | N/A |
| 74 | Period validated with employees missing attendance entirely | Some employee has no attendance record for a date in range | **Blocked** — flagged as coverage gap | Validation blocker | N/A | Trigger calculation for the missing employee/date | N/A |
| 75 | Period finalized successfully | All blockers resolved, HR runs Finalize | Period becomes **Closed**; incomplete days resolved to paid/unpaid per policy; summaries frozen | Standard close sequence | Final payroll-ready summary produced | N/A | N/A |
| 76 | Attempt to punch on a locked date | Employee tries to clock in for a date inside a closed period | **Refused** | Lock precedence | N/A | Reopen the period first | N/A |
| 77 | Period reopened by HR | HR with unlock permission reopens a closed period | Days become mutable again; **nothing recalculates automatically** | Documented design | Stale until manually recomputed | Manual recompute needed | N/A |

---

## I. Summary of unsupported / future scenarios found above

| Scenario # | Why it's not fully supported | Tracked as |
|---|---|---|
| 36 (Flex core hours) | Setting stored but not enforced | Gaps doc — Attendance Policy fields |
| 37 (On-Duty) | Status never produced by the engine | Gaps doc ND-06 |
| 38 (WFH) | Status never produced by the engine | Gaps doc ND-06 |
| 57 (Night OT) | Default setting never classifies Night | Gaps doc ND-03 |

None of these are silently broken — each has a documented current behaviour and a recommended path in the [Gaps & Open Decisions document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md).

---

## Where to go next

- Full narrative flow → [`ATTENDANCE_V1_CLIENT_FLOW.md`](./ATTENDANCE_V1_CLIENT_FLOW.md)
- Precedence rules referenced above → [`ATTENDANCE_V1_PRECEDENCE_AND_OVERRIDE.md`](./ATTENDANCE_V1_PRECEDENCE_AND_OVERRIDE.md)
- Every configurable setting → [`ATTENDANCE_V1_CONFIGURATION_CATALOG.md`](./ATTENDANCE_V1_CONFIGURATION_CATALOG.md)
- The sign-off checklist → [`ATTENDANCE_V1_CLIENT_SIGNOFF.md`](./ATTENDANCE_V1_CLIENT_SIGNOFF.md)
