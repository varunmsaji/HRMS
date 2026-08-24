# Attendance V1 — Precedence & "What Overrides What"

**Read this if:** two rules could apply to the same day and you need to know which one actually wins.

See [`README.md`](./README.md) for the meaning of each tag (**CURRENTLY WORKING**, **CONFIGURABLE AND WORKING**, **STORED BUT NOT USED**, **OPEN PRODUCT DECISION**, **FUTURE MODULE**, **KNOWN LIMITATION**).

---

## 1. Policy specificity order

Work calendars, weekly-off patterns, and the three policy families (Attendance, Overtime, Regularization) can each be assigned at eight levels. **The most specific level with an assignment wins**, checked in this order:

```
EMPLOYEE  →  SHIFT  →  DESIGNATION  →  GRADE  →  DEPARTMENT  →  BRANCH  →  LEGAL ENTITY  →  COMPANY
```

Each of the following is resolved **independently** — having an Employee-level Attendance Policy says nothing about which level of Overtime Policy applies:

| What's being resolved | Uses this 8-level walk? |
|---|---|
| Work Calendar (holidays + weekly-off) | Yes |
| Weekly-Off pattern (can override the calendar's own pattern) | Yes |
| Attendance Policy | Yes |
| Overtime Policy | Yes |
| Regularization Policy | Yes |
| Shift identity itself | No — comes from Employee Assignment or Roster (§3) |
| Roster entries | No — set directly per employee/date |
| Leave projections | No — set directly per employee/date |
| Period lock | No — applies to the whole company for a date range |

**If no level has an assignment at all:** the system does not fall back to any default — the day cannot be evaluated and becomes a **Configuration Error**, which blocks period close. This is intentional (see [Client Flow §4](./ATTENDANCE_V1_CLIENT_FLOW.md#4-what-kind-of-day-is-it--the-calendar-decision)) — **CURRENTLY WORKING**.

---

## 2. Ten worked precedence examples

| # | Scenario | Winner | Why |
|---|---|---|---|
| 1 | Company Grace-In = 15 min; nothing more specific set | Company (15 min) | Only level with an assignment |
| 2 | Company = 15 min; Department "Sales" = 10 min | Department (10 min) for Sales; Company (15 min) for everyone else | Department is more specific than Company |
| 3 | Company = 15 min; Department = 10 min; Employee = 5 min (employee is in that department) | Employee (5 min) | Employee is the most specific level |
| 4 | Grade "Manager" has a Half-Day-at-30-min rule; no Employee/Shift/Designation override | Grade rule applies to all Manager-grade employees | Grade is the only level set |
| 5 | Shift "Night A" has its own Overtime Policy; Department "Security" has a different one | Shift-level policy | Shift outranks Department |
| 6 | Branch "Mumbai" has a Work Calendar; Legal Entity "ABC Pvt Ltd" also has one | Branch's calendar, for Mumbai employees | Branch outranks Legal Entity |
| 7 | No policy assigned at any level | Configuration Error | No silent default — fail closed |
| 8 | Employee transferred from Dept A (Reg Policy X) to Dept B (Reg Policy Y) mid-month | Requests before the transfer use X; after, Y | Policy resolution is always as-of the relevant date |
| 9 | Designation "Team Lead" has an Attendance Policy; Grade "L3" (held by most Team Leads) has a different one | Designation-level policy | Designation outranks Grade |
| 10 | Employee has no Shift-level policy, but their Shift itself does, and their Department also has one | Shift-level policy | Shift outranks Department even though it's the shift's setting, not the employee's |

---

## 3. Schedule precedence (which shift applies)

| Priority | Source | Effect |
|---|---|---|
| 1 (highest) | A **published** roster entry for that employee/date | Overrides the schedule for that date |
| 2 | The employee's assigned default shift | Used when no roster entry exists |
| — | Neither present | Governed by the "missing shift" rule in the Attendance Policy |

A **draft** (unpublished) roster entry has **zero** effect on calculation — it is completely ignored, as if it didn't exist — and it blocks period close until published or removed. **CURRENTLY WORKING.**

**Roster flags** change whether presence is *expected*, but never rewrite the calendar's day-type:

| Roster flag | Effect |
|---|---|
| "Treat as week-off" | Employee is not expected to work that date, even if the calendar says Working Day |
| "Treat as working" (holiday/week-off override) | Employee is expected to work despite the calendar showing a holiday/weekly-off |

---

## 4. Calendar precedence

| Priority | Rule | Result |
|---|---|---|
| 1 (highest) | A date-specific exception (Shutdown, Special Working Day, Substitute Holiday, Cancel Holiday) | Exception's day-type wins outright |
| 2 | A listed holiday (first matching holiday calendar in the assigned order) | Holiday / Working-Holiday / soft-holiday name |
| 3 | Weekly-off pattern match | Weekly Off |
| 4 (lowest) | Nothing else matched | Working Day |

### Special calendar cases

| Situation | Result | Why |
|---|---|---|
| Hard holiday falls on a weekly-off day | Stays **Weekly Off**, flagged "holiday coincided with weekly off" | Documented rule — no automatic substitute (see [Client Flow §4](./ATTENDANCE_V1_CLIENT_FLOW.md#4-what-kind-of-day-is-it--the-calendar-decision)); **OPEN PRODUCT DECISION** on whether this should auto-substitute |
| Holiday explicitly cancelled + day is a weekly-off | Weekly Off | Holiday stripped, weekly-off underneath still applies |
| Holiday explicitly cancelled + day is not a weekly-off | Working Day | Nothing left to classify it as a holiday |
| Special Working Day declared on a weekly-off/holiday | Special Working Day (expected working day) | Exception always wins |
| Shutdown declared on any date | Shutdown | Exception always wins |
| Optional/Restricted holiday, company setting OFF (default) | Working Day (holiday name still shown for reference) | Soft holiday default |
| Optional/Restricted holiday, company setting ON | Treated as a hard holiday | Company-level flag |

---

## 5. Attendance status precedence (inside the day calculation)

Checked in this order — the first one that applies decides the outcome, subject to the leave overlay always running last:

1. **Employment gate** — Not Joined / Exited always wins, absolute, no exceptions
2. **Configuration Error** — missing calendar or missing Attendance Policy
3. **Roster week-off with no punches** → Not Expected
4. **Missing shift** → follows the missing-shift rule
5. **Not-expected day (holiday/week-off/shutdown, nobody forced work) with no punches** → Not Expected
6. **Punch-based evaluation** → Present / Half-Day / Absent / Incomplete, including late/early classification
7. **Leave overlay** (runs last, can still change the outcome — see §7)

A "late → Half-Day" or "late → Absent" classification from step 6 overrides what the hour-based bands alone would have said.

---

## 6. Overtime precedence

| Topic | Rule |
|---|---|
| Eligibility | Policy eligibility setting, plus a shift-level flag check only when eligibility is set to "shift decides" |
| Minute calculation order | Minimum threshold → rounding → daily cap → remaining weekly cap → remaining monthly cap |
| Day classification | Holiday (if worked on a holiday) → else Weekly-Off (if worked on a weekly-off) → else Night (only if the shift crosses midnight **and** the night-classification setting is turned to a mode that actually checks it — the default setting never produces Night, see [Gaps document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md)) → else Normal |
| Approval | Auto-chain, or "no approval required" setting → auto-approved. Otherwise pending until a human decides |
| Once decided | Approved/Rejected overtime is frozen — a later recalculation of the same day will not silently revise it |
| vs. Attendance status | Overtime **never** changes Present/Absent/Half-Day — always a separate, parallel fact |
| vs. Period lock | Approve/reject actions are blocked once the period is locked |

---

## 7. Leave precedence

| Topic | Rule |
|---|---|
| vs. Calendar | Leave never changes the calendar's day-type (a holiday stays a holiday even with leave applied on top) |
| vs. Not-Expected days | A full-day leave can still turn an otherwise Not-Expected day (e.g. a day with no punches) into a Leave day |
| vs. Punches, "leave wins" mode (default) | Leave status wins outright; punch-based late/early flags are cleared |
| vs. Punches, "flag work-on-leave" mode | Punch-based status is kept; the day is flagged so HR can see the employee worked despite being on leave |
| vs. Overtime | **Known limitation:** in "leave wins" mode, overtime numbers calculated from punches are not automatically cleared — see [Gaps document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md) (ND-04) |
| vs. Period lock | Any leave sync/cancellation is refused once the period is locked |

---

## 8. Regularization precedence

| Topic | Rule |
|---|---|
| Allowed at all | Governed by policy: who may request (employee/manager/HR), correction types allowed, backdating window, monthly request limit |
| vs. original punches | Corrections are **always additive** — new punches are added, original punches are never edited or deleted |
| vs. roster | Approval can also update the roster's assigned shift for that date |
| vs. day result | Triggers a full recalculation of the day using the normal rules — never a direct status overwrite |
| vs. lock | Submitting a new request is blocked once the period is locked (unless policy explicitly allows it) |
| vs. finalize | Any request still awaiting a decision blocks period close |

---

## 9. Period lock precedence

**Lock outranks every other mutating action** for dates inside the locked range: punches, recalculation, roster changes, regularization submission, overtime approval/rejection, and leave sync/cancellation are all refused. Configuration masters (calendars, policies, shifts) outside the locked date range remain editable as normal. Reopening a period restores mutability but does **not** automatically recalculate anything.

---

## 10. Master "what overrides what" table

| Scenario | Rule A | Rule B | Winner | Why | Configurable? |
|---|---|---|---|---|---|
| Employee-specific policy vs. Company-wide policy | Employee assignment | Company assignment | **Employee** | Most-specific-wins order | Yes — set the assignment level |
| Shift-level policy vs. Department-level policy | Shift assignment | Department assignment | **Shift** | Shift outranks Department | Yes |
| Roster shift vs. Assignment shift | Published roster | Employee's default assignment | **Roster** (for schedule) | Roster is the most specific override for that date | Yes — publish/clear the roster |
| Roster shift vs. Shift-scoped **policy** | Roster changes the schedule | Policy is still keyed to the original assignment shift | **Policy stays on the original shift** — this is a documented mismatch | Code resolves shift-scoped policy from the assignment, not the roster | Only indirectly — change the assignment itself, or the policy assigned to that shift; flagged as **OPEN PRODUCT DECISION** |
| Calendar exception vs. holiday | Date-specific exception | Listed holiday | **Exception** | Exceptions are checked first | Yes — HR creates/removes exceptions |
| Special Working Day vs. Weekly Off | Exception | Weekly-off pattern | **Special Working Day** | Exception always wins | Yes |
| Holiday vs. Weekly Off | Holiday | Weekly-off pattern | **Weekly Off** (with a flag noting the coincidence) | Documented carve-out — see §4 | Only via a manual Substitute Holiday exception |
| Optional/Restricted holiday vs. Working Day | Soft holiday | Default behaviour | **Working Day**, unless the company-wide flag is turned on | PD-CAL-1 | Yes — one company-wide flag |
| Leave vs. Absence | Approved full-day leave | No punches recorded | **Leave** | Leave overlay runs after punch evaluation | Set via leave sync (not an end-user Leave UI yet) |
| Leave vs. Holiday day-type | Leave applied on a holiday | Calendar says Holiday | **Both apply** — status becomes Leave, calendar stays Holiday | Leave never rewrites calendar | — |
| Punch vs. Leave | Employee actually punched in | Approved leave exists for that day | **Conditional** — only under "flag work-on-leave" mode does the punch-based status survive; otherwise Leave wins | Policy setting | Yes |
| Regularization vs. original punch | New corrective punch | Original punch | **Both are kept**; pairing logic considers all of them | Punches are never deleted | — |
| Overtime vs. Attendance status | Detected/approved OT minutes | Present/Absent/Half-Day status | **Neither overrides the other — parallel facts** | Documented design | — |
| Pending overtime vs. Period finalize | Unapproved OT record | Attempt to close the period | **Finalize is blocked** | Validation blocker | Approve or reject first |
| Lock vs. any mutation | Period closed | Punch, correction, roster change, OT decision, leave sync attempt | **Lock wins — action refused** | Documented design | Reopen the period first |
| Draft roster vs. Published roster | Draft entry | Published entry | **Published wins; draft is ignored** by calculation, and blocks finalize if left unresolved | Documented design | Publish or remove the draft |

---

## 11. Quick answers — "Can X override Y?"

| Question | Answer |
|---|---|
| Can an Employee-specific policy override the Company policy? | **Yes** |
| Can a Shift-specific policy override a Department policy? | **Yes** |
| Can a Roster entry override the employee's assigned shift? | **Yes**, for scheduling purposes |
| Does a Roster entry also change which Shift-scoped policy applies? | **No** — documented mismatch, see §10 |
| Can a Calendar Exception override a Holiday? | **Yes** |
| Can a Special Working Day override a Weekly Off? | **Yes** |
| Can a Holiday override a Weekly Off? | **No** — the day stays Weekly Off, with a flag |
| Can Leave override an Absence or a Not-Expected day? | **Yes**, for the day's status |
| Can Leave override a Holiday's day-type? | **No** — the calendar is never changed by leave |
| Can a Punch override Leave? | **Only conditionally** — only in "flag work-on-leave" mode, and even then it doesn't cancel the leave itself |
| Can Regularization override an original Punch? | **Only by adding new punches** — it can never delete or edit an original punch |
| Can Overtime override the Attendance status? | **No** — always a separate, parallel fact |
| Can a Period Lock override all mutating actions? | **Yes** |
| Can a Draft roster override the live schedule? | **No** — only Published entries count |
| Can a soft (optional/restricted) holiday override a Working Day? | **Only conditionally** — only if the company-wide "treat as hard holiday" setting is on |
