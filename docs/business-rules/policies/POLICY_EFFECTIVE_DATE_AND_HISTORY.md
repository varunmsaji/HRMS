# Policy Effective-Date & History Analysis

**Status:** Audit document. Primary source: `docs/adr/0003-effective-dated-modelling.md`, `docs/adr/0004-leave-ledger.md`, and direct code reading of every `*Version`/`*Assignment` model in Attendance, Leave, and Organisation.

## 1. The uniform pattern (SHARED-POL-003)

ADR-0003: *"Any employee attribute that changes over time lives in its own child table with `effective_from DATE NOT NULL` and `effective_to DATE` (`NULL` = current) — never as a mutable column... A change is always an insert of a new row, never an edit of an existing one's core values."* Overlapping periods are made structurally impossible via a Postgres GiST exclusion constraint.

Models following this pattern, verified in code: `AttendancePolicyVersion`, `OvertimePolicyVersion`, `RegularizationPolicyVersion`, `LeavePolicyVersion`, `ShiftVersion`, `PolicyAssignment`, `EmployeeAssignment`, `EmployeeCompensation`, `EmployeeStatutory`. All follow identical **insert-new/close-previous** semantics — publishing a new version requires `effective_from` strictly after the current version's `effective_from`, and closes the old row by setting only its `effective_to` (never touching its other fields).

Documented exception: `EmployeeBank` is **deliberately not** closed on employee exit — kept open for full-and-final settlement payout after termination (`employee/models.py:249-253`). This is a locked, intentional deviation, not an oversight.

Not effective-dated at all: `Branch`, `Department`, `Grade`, `Designation` — plain mutable identity rows with only `is_active`/`deleted_at`/optimistic-lock `version`. The effective-dating for "which policy applies to this branch/department" lives entirely in `PolicyAssignment` (the scope link), not in these organisation tables themselves.

`LeaveLedgerEntry` is a distinct, stricter pattern: **append-only**, single `effective_date` (not a range), no update/delete/soft-delete ever (ADR-0004) — every accrual, deduction, adjustment, encashment, and carry-forward is its own immutable row; a correction is a new offsetting entry, never an edit.

## 2. Per-policy effective-dating table

| Policy | Effective Dating Supported? | Versioning? | Historical Protection? | Recalculation Behaviour |
|---|---|---|---|---|
| ATT-POL-001…020 (Attendance Policy Version fields) | Yes (`effective_from`/`effective_to` on `AttendancePolicyVersion`) | Yes — insert-new/close-previous, immutable once published | Yes — locked `AttendanceDay` rows never recompute; unlocked days re-resolve the version covering their date | Recompute re-resolves by date; a backdated publish (`effective_from` in the past) is a privileged act that *can* change unlocked historical days |
| ATT-POL-021…028 (Overtime Policy Version fields) | Yes | Yes, same pattern | Same | Terminal `OvertimeRecord`s (APPROVED/AUTO_APPROVED/REJECTED) are frozen and never revised by any recompute, even if a new OT policy publishes (WD-29 decision 2) |
| ATT-POL-029…035 (Regularization Policy Version fields) | Yes | Yes, same pattern | Same | Same recompute-by-date rule; approved regularizations are permanent (new punches), not tied to policy version after the fact |
| ATT-POL-045 Shift Version | Yes | Yes | Same | Same — recompute re-resolves the shift version covering the date |
| ATT-POL-036 Period lock state | Not effective-dated (a state, `OPEN`/`CLOSED`) | No — binary state per period | This **is** the historical-protection mechanism for everything else | Locking is what prevents recalculation; reopening removes protection but triggers no automatic recompute |
| ATT-POL-049 Policy Assignment (scope link) | Yes | Yes, insert-new/close-previous | Same | Changing which policy applies to a scope is itself an effective-dated event; historical resolution always uses "as of the attendance date," never "as of today" |
| LEAVE-POL-001…030 (Leave Policy Version fields) | Yes (`effective_from`/`effective_to` on `LeavePolicyVersion`) | Yes, same insert-new/close-previous pattern, immutable once published | Yes — `LeaveApplication.leave_policy_version_id` is **snapshotted at submit time**, so a later policy edit cannot retroactively change how an in-flight or already-decided application is reviewed | A policy version change never rewrites past ledger entries (ledger is append-only); each accrual/carry-forward cycle evaluates against whichever version was effective as of that cycle's date |
| LEAVE-POL-007 Leave balance | N/A — not a versioned "policy," a live derived value | N/A | Yes, absolute — `SUM(ledger.amount)`, and the ledger itself is immutable/append-only (ADR-0004) | Balance always reflects full ledger history; nothing is ever "recalculated" in the sense of rewriting old entries — only new offsetting entries are added |
| LEAVE-POL-009 Leave Year Setting | No effective-dating found — appears to be a single current-value setting per company, not itself versioned | 🔵 GAP — no historical record of *when* a leave-year setting changed, unlike every other policy in this system | Not established — no test or code found addressing what happens to an in-progress leave year if the setting changes mid-year | Undetermined — ⚠️ POLICY DECISION REQUIRED |
| LEAVE-POL-006 Leave Combination Rule | No effective-dating found on the rule row itself | No versioning — plain CRUD (create/delete) | Not established | A rule change takes effect immediately for all future submissions; no record of what rule applied when a past decision was made |
| LEAVE-POL-014 Statutory Leave Minimum | No effective-dating found | No versioning — plain CRUD | Not established (only enforced at publish time of a *different* object, the Leave Policy Version) | N/A |

## 3. Ten-question checklist (per the audit's Phase 7 framework)

| # | Question | Attendance answer | Leave answer |
|---|---|---|---|
| 1 | Does it have an effective start date? | Yes, on every `*PolicyVersion`/`ShiftVersion`/`PolicyAssignment` | Yes, on `LeavePolicyVersion`/`PolicyAssignment`; **no** on Leave Year Setting or Combination Rule (🔵 gap) |
| 2 | Does it have an end date? | Yes (`effective_to`, NULL = current) | Same |
| 3 | Can policies overlap? | No — GiST exclusion constraint prevents overlap at the same scope+kind | Same constraint reused |
| 4 | Can a new policy replace an old policy? | Yes — insert-new/close-previous | Same |
| 5 | What happens to historical records? | Preserved untouched; locked days are immutable regardless of later policy changes | Preserved untouched; ledger is append-only, applications snapshot their policy version |
| 6 | Does recalculation use the new policy? | Only for **unlocked** days, and only if explicitly recomputed — never automatic on publish | N/A in the same sense — Leave doesn't "recompute" applications; each new accrual/carry-forward cycle naturally uses whatever version is effective on its date |
| 7 | Is the old policy version preserved? | Yes, always | Yes, always |
| 8 | Are existing approvals recalculated? | No — approved regularizations/OT records are permanent facts, not re-evaluated against new policy | No — `leave_policy_version_id` is fixed at submission; approved applications are never re-evaluated |
| 9 | Are balances recalculated? | N/A (Attendance has no balance concept beyond paid/LOP fraction, which is locked once the period finalizes) | No — ledger is append-only; a policy change never rewrites a past accrual/carry-forward entry, it only affects entries generated *after* the change under the new version |
| 10 | Are locked records protected? | Yes, absolutely — `AttendanceDay.is_locked` + `AttendancePeriod.status=CLOSED` block every mutation path checked in this audit | Indirectly, via Attendance's lock (LEAVE-POL-034) — Leave itself has no independent lock, so "protection" for a leave-affecting date is entirely borrowed from whether the attendance period covering that date is closed |

## 4. Policy Change Impact scenarios (Phase 8)

| Policy Change | Existing Records | Future Records | Recalculation | Manual Action Required |
|---|---|---|---|---|
| New Attendance Policy Version published mid-month, `effective_from` = today | Days before today: untouched (old version still covers them) | Days from today onward: new version applies on next calculate() | Automatic only on next `calculate()` call for affected dates; no bulk trigger | None required unless HR wants immediate recompute of already-calculated future-dated days |
| New Attendance Policy Version published with a **backdated** `effective_from` | Unlocked days in the backdated range: **will** change on next recompute, since version resolution is strictly by date | Same as above | Requires an explicit recompute call — not automatic | Yes — a human must trigger recompute; documented as "a privileged act requiring reason and `ATTENDANCE.RECOMPUTE`" |
| Attendance period locked mid-cycle, then a policy changes | No effect — locked days are immune regardless of any policy change | N/A (period is closed) | None until reopened | Reopen + manual recompute if correction is needed |
| Leave Policy Version published with new carry-forward cap | Past ledger entries: untouched (append-only) | Next year-end sweep uses new cap | Automatic only at the next scheduled year-end sweep for that leave type | None — sweep is a scheduled job |
| Leave Policy Version changes `allowed_during_probation` | In-flight/decided applications: unaffected (snapshotted `leave_policy_version_id`) | New submissions checked against new value | N/A — no retroactive check | None |
| Leave Year Setting changed mid-year | 🔵 Undetermined — no code path found that explicitly guards or handles an in-flight leave year when this setting changes | Same | Undetermined | ⚠️ POLICY DECISION REQUIRED |
| Attendance period reopened after policy already changed since the original lock | Days become mutable again, but are **not** auto-recomputed — they can silently reflect stale, pre-change values until someone explicitly recomputes them | N/A | Manual only | Yes — this is explicitly flagged as a process risk (ND-08/CD-016: "Reopen unlocks without recalc → stale days possible") |

## 5. Open decisions surfaced by this analysis

| ID | Topic | Status |
|---|---|---|
| PD-EFFDATE-1 | Should Leave Year Setting be effective-dated/versioned like every other policy in the system? | ⚠️ POLICY DECISION REQUIRED |
| PD-EFFDATE-2 | Should Leave Combination Rules be effective-dated (so a past decision can be explained by "the rule in force at the time")? | ⚠️ POLICY DECISION REQUIRED |
| PD-EFFDATE-3 | Should reopening a locked attendance period trigger an automatic recompute, or continue to require a manual step (with the associated stale-data risk)? | ⚠️ POLICY DECISION REQUIRED (carried over from ND-08/CD-016) |
