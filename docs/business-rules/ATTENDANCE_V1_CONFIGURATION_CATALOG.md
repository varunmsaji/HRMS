# Attendance V1 — Configuration Control Panel

**Read this if:** you're setting up the system and want to know exactly what can be configured, who is allowed to configure it, and — critically — whether the system actually uses that setting or just stores it.

See [`README.md`](./README.md) for the meaning of each tag. **A setting appearing here does not guarantee it changes behaviour** — check the "Currently consumed?" column every time. Settings marked "No" are detailed further in the [Gaps document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md).

Who can configure: people holding attendance policy-management, shift-management, roster-management, or period lock/unlock permissions — typically HR/Admin roles, with managers sometimes granted roster access. Exact role assignment is a separate access-control decision, not covered here.

---

## 1. Work Calendar

| Setting | Example | Scope | Who configures | Versioned? | Currently consumed? | Overrides | Overridden by |
|---|---|---|---|---|---|---|---|
| Calendar name/identity | "India — Standard Calendar" | Company | HR/Admin | Yes (change history) | Yes | — | — |
| Weekly-off pattern link | Attach "Mon–Fri" pattern | Calendar | HR/Admin | No | Yes | — | A separately-assigned Weekly-Off policy can replace this |
| "Optional holidays are hard holidays" flag | On/Off | Calendar | HR/Admin | No | Yes | Soft holiday default | — |
| Holiday calendar composition (ordered list) | ["India Public Holidays", "Maharashtra State Holidays"] | Calendar | HR/Admin | Replace-on-change | Yes | — | Calendar Exceptions |
| Calendar Exception (dated override) | Shutdown / Special Working / Substitute Holiday / Cancel Holiday | Calendar + specific date | HR/Admin | Deactivate + re-insert | Yes | Holiday, Weekly-Off | Nothing — highest priority |

## 2. Holiday

| Setting | Example | Scope | Who configures | Currently consumed? |
|---|---|---|---|---|
| Holiday Calendar (named set) | "Kerala Holidays 2026" | Company | HR/Admin | Yes |
| Individual holiday date + name | "26 Jan — Republic Day" | Holiday Calendar | HR/Admin | Yes |
| Holiday type | Public / Company / Optional / Restricted / Working-Holiday | Holiday entry | HR/Admin | Yes |

## 3. Weekly Off

| Setting | Example | Scope | Who configures | Currently consumed? |
|---|---|---|---|---|
| Weekly-Off Pattern (named) | "Standard Mon–Fri" | Company | HR/Admin | Yes |
| Weekday rule | Sunday only | Pattern | HR/Admin | Yes |
| Nth-weekday-in-month rule | 1st and 3rd Saturday | Pattern | HR/Admin | Yes |
| Last-weekday-in-month rule | Last Saturday | Pattern | HR/Admin | Yes |
| Alternate-week rule | Every other Saturday, starting from a chosen date | Pattern | HR/Admin | Yes |
| Off-fraction | Partial day off (e.g. 0.5) | Rule | HR/Admin | **Partial** — the day is still fully classified as Weekly Off; the fraction itself does not currently change the paid/unpaid calculation |

## 4. Shift

| Setting | Example | Scope | Who configures | Currently consumed? |
|---|---|---|---|---|
| Shift identity (name/code) | "General Shift" | Company | HR/Admin | Yes (for assignment/roster reference) |
| Shift type | Fixed / Flexible / Split | Shift version | HR/Admin | Yes |
| Timing (start/end, or window, or duty blocks) | 09:00–18:00 | Shift version | HR/Admin | Yes |
| Required minutes | 480 min | Shift version | HR/Admin | Yes (Flexible/Split baseline, and OT baseline) |
| Cross-midnight flag | On for night shifts | Shift version | HR/Admin | Yes |
| OT-eligible flag | On/Off | Shift version | HR/Admin | Yes (when OT eligibility is set to "shift decides") |
| Operates-on-holiday / Operates-on-weekly-off flags | On/Off | Shift version | HR/Admin | Yes |
| "Is night shift" flag | On/Off | Shift version | HR/Admin | **No** — overtime night-classification actually checks the cross-midnight flag instead; this flag is stored only |
| Timezone | IANA timezone name | Shift version (optional) | HR/Admin | Yes — highest priority timezone source |
| Core hours (start/end) | 11:00–16:00 | Shift version | HR/Admin | **No** — stored only |
| Break definitions | See §5 | Shift version | HR/Admin | Yes (partial — see §5) |
| Publish (Draft → Published) | — | Shift version | HR/Admin | Yes — only Published versions are used in calculation |

Note: an older, legacy "Shift" record type also stores grace-period and half-day settings from a previous design — these are **not read** by the current calculation engine. Only the newer versioned Shift schedule (start/end/breaks/duty-blocks) is used for scheduling.

## 5. Break

| Setting | Example | Currently consumed? |
|---|---|---|
| Break window (fixed start/end) | 13:00–14:00 | Yes |
| Break window (flexible, with min/max duration) | Any 30–60 min window between 12:00–15:00 | Yes for matching; min/max duration limits themselves — **No** |
| Paid / Unpaid | Unpaid lunch | Yes |
| Mandatory / Optional | Mandatory | **No** — a mandatory break with no matching punch gap is not auto-deducted |
| Maximum duration | 60 min | Yes — excess minutes are recorded |
| Action when exceeding maximum | Flag / other | **No** — excess is recorded as a fact only; no automatic consequence is applied |
| Split-compatible | On/Off | **Partial** — matching for split breaks is limited |

## 6. Attendance Policy

PD-1 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`, 2026-09-23): settings the engine does not apply are **hidden from the policy screens** (the database columns stay, and a stored value is kept unchanged when a version is edited). They are listed at the end of each table as "Hidden".

| Setting | Example | Currently consumed? |
|---|---|---|
| Grace-In minutes | 15 | Yes |
| Grace-Out minutes | 10 | Yes |
| Missing-punch behaviour | Incomplete (default) / Absent / Require Correction | Yes. **Auto-Close** is hidden (it does not synthesize a clock-out); shown only on a version that already uses it |
| Missing-shift behaviour | Absent / Incomplete | Yes |
| Multi-punch mode | Sum all pairs / First-in-last-out | Yes |
| Duplicate-punch window | 60 seconds | Yes |
| Core-hours breach behaviour | Ignore / Flag / Half-Day / Absent | Yes |
| Split-shift missed-block behaviour | Ignore / Half-Day / Absent / Require Correction | Yes |
| On-Duty requires punch | On/Off | Yes |
| Lates-to-half-day / excess-break-days-to-half-day count | 3 lates in a month = 1 half-day | Yes — counted per calendar month (the only window supported) |
| Early-departure requires approval | On/Off | Yes |
| Incomplete-at-lock behaviour | Treat as Absent (default) / Treat as Present / Keep as Incomplete | Yes — applied only at period finalize |
| Hour bands (worked minutes → status) | ≥480 = Present, 240–479 = Half-Day, <240 = Absent | Yes |
| Late bands (late minutes → classification) | 30+ min = Half-Day | Yes |
| Early-departure bands | 60+ min early = flag | Yes |
| Band "counts toward cap" flag | — | **Hidden** — never read |
| Punch rounding + rounding minutes | — | **Hidden** — never applied |
| Auto-close-after-minutes / uses-shift-end | — | **Hidden** |
| Half-day split method + boundary minutes | — | **Hidden** — half-day comes from hour bands only |
| Excess-break behaviour | — | **Hidden** |
| Early-out-uses-core-end | — | **Hidden** |
| Split-shift block mandatory / allow-hours-compensation | — | **Hidden** |
| WFH requires-punch / WFH-uses-shift-hours | — | **Hidden** |
| Work-on-leave behaviour | — | **Hidden** — since decision 5, approved full-day leave always wins and the day is flagged for HR, whatever this says |

## 7. Overtime Policy

| Setting | Example | Currently consumed? |
|---|---|---|
| Eligibility mode | Never / Shift decides / Always | Yes. **By-grade** is hidden (it behaves like Always — no grade check); shown only on a version that already uses it |
| Minimum OT minutes | 30 min | Yes |
| Rounding rule + minutes | Round up to nearest 30 min | Yes |
| Daily / weekly / monthly caps | 120 / 600 / 2400 min | Yes |
| Requires post-approval | On/Off | Yes |
| Approval chain | Auto / Manager / HR / Manager-then-HR | Yes |
| Comp-off instead of pay + expiry days | On, 60-day default expiry | Yes — credited to the comp-off leave balance |
| Rate rows (day-class → classification code + multiplier) | Holiday = 2x | Classification: Yes. Multiplier: reference only until the Payroll module exists |
| Night OT mode + night window | Shift flag / Window 22:00–06:00 / Both | Yes (ATT-005, fixed 2026-09-23) |
| Requires pre-approval | — | **Hidden** — never read |

## 8. Regularization Policy

| Setting | Example | Currently consumed? |
|---|---|---|
| Allow employee / manager / HR to request | On/Off per actor | Yes |
| Max backdated days | 7 days | Yes |
| Max requests per month | 3 | Yes |
| Reason required / attachment required | On/Off | Yes |
| Approval chain | Auto / Manager / HR / Manager-then-HR | Yes |
| Blocked when period is locked | On (default) | Yes |
| Allowed correction types | Missing Punch, Wrong Punch, Wrong Shift, Wrong Status, WFH, On-Duty, Full-Day | Yes — but note WFH/On-Duty types don't produce those specific statuses by themselves (see [Client Flow §12](./ATTENDANCE_V1_CLIENT_FLOW.md#12-regularization-flow)) |
| Auto-approve-within-minutes | — | **Hidden** — never read |

## 9. Policy Assignment

| Setting | Example | Currently consumed? |
|---|---|---|
| Policy kind | Work Calendar / Weekly-Off / Attendance / Overtime / Regularization | Yes |
| Scope level | Employee / Shift / Designation / Grade / Department / Branch / Legal Entity / Company | Yes |
| Effective from / to dates | 01 Apr 2026 – open-ended | Yes |
| Resolution preview | Shows which policy applies to which employee, for checking | Yes (read-only tool) |

## 10. Roster

| Setting | Example | Currently consumed? |
|---|---|---|
| Shift override for a date | Assign "Night Shift" to Employee X on 20 Aug | Yes, once Published |
| Treat-as-week-off override | On | Yes |
| Treat-as-holiday-working override | On | Yes |
| Status (Draft / Published) | — | Yes — only Published rows affect calculation; Draft rows block period close |

## 11. Leave Projection

| Setting/action | Example | Who can configure | Currently consumed? |
|---|---|---|---|
| Sync a leave projection onto a date | Fraction (0.50/1.00), half (first/second), paid flag, source reference | A system integration with leave-sync permission — **not a dedicated end-user screen today** | Yes |
| Cancel a leave projection | — | Same as above | Yes |

**Note:** this is a mirror of leave decided elsewhere, not a leave-application screen. There is no leave-request UI inside Attendance itself. **FUTURE MODULE** (full Leave application system).

## 12. Period Lock

| Setting/action | Example | Who configures | Currently consumed? |
|---|---|---|---|
| Create an Open period | A legal entity + a calendar month (default), or a custom range | HR/Admin | Yes |
| Validate | Pre-check for blockers | HR/Admin | Yes |
| Finalize (lock) | — | HR/Admin with lock permission | Yes |
| Reopen (unlock) | — | HR/Admin with unlock permission | Yes — unlocks days, does **not** auto-recompute |
| Legal-entity-level locking | Close "Acme India" for August while "Acme Services" stays open | HR/Admin | Yes — every period belongs to one legal entity (decision 14) |

---

## Operational defaults worth knowing

These are the out-of-the-box settings that most affect day-to-day results if nobody changes them:

| Setting | Default | Practical effect |
|---|---|---|
| Missing-punch behaviour | Incomplete | A forgotten punch does not silently become Absent |
| Incomplete-at-lock behaviour | Treat as Absent | Any Incomplete day still unresolved when the period closes becomes unpaid |
| Work-on-leave behaviour | Leave wins | Punching in on an approved-leave day does not cancel the leave |
| Overtime requires post-approval | On, Manager chain | OT is never silently auto-approved unless explicitly configured otherwise |
| Optional/Restricted holidays are hard holidays | Off | Soft holidays are working days by default |
| Duplicate-punch window | 60 seconds | Two taps within a minute count as one |
| Multi-punch mode | Sum all pairs | Multiple in/out cycles in a day are all added together |

---

## Reading this table correctly

A row marked **"No"** under "Currently consumed?" means: HR can open the settings screen, enter a value, save it successfully, and see it stored — but the day-to-day attendance calculation **ignores it**. This is not a bug report; it is an honest inventory so nobody assumes a saved setting is doing something it isn't. Every "No" item is discussed further, with a recommended path forward, in the [Gaps & Open Decisions document](./ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS.md).
