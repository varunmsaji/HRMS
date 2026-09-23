# Policy Override Matrix

**Status:** Audit document. Policy IDs per [`MASTER_POLICY_INVENTORY.md`](./MASTER_POLICY_INVENTORY.md). "Override type" vocabulary: Automatic override (system-computed, no human involved) · Higher-priority policy override (scope-resolution wins) · Employee-specific override (a more specific `PolicyAssignment`) · Manager override · HR override · Admin override (COMPANY-scope permission) · Approved transaction override (an approval action changes an outcome) · System override (engine-internal precedence) · Locked-record override (none exists by design).

## A. Attendance policies

| Policy | Can Override? | Override Type | Who Can Override? | Approval Required? | Audit Trail? | Reversible? |
|---|---|---|---|---|---|---|
| ATT-POL-001 Grace minutes | Yes | Higher-priority policy assignment | HR (`ATTENDANCE.POLICY_MANAGE`), by publishing a more specific-scope version | No (publish is itself the change) | Yes — policy version history | Only forward (new version); old version preserved, never edited |
| ATT-POL-002/003 Late/Early bands | Yes | Higher-priority policy assignment | Same | No | Yes | Same |
| ATT-POL-004 Hour bands | Yes | Higher-priority policy assignment | Same | No | Yes | Same |
| ATT-POL-006 Missing-punch behaviour | Yes, per-scope | Higher-priority policy assignment | HR | No | Yes | Same |
| ATT-POL-013 Work-on-leave behaviour | Yes, per-scope | Higher-priority policy assignment | HR | No | Yes | Same |
| ATT-POL-021 OT eligibility | Yes, per-scope | Higher-priority policy assignment | HR | No | Yes | Same |
| ATT-POL-024 OT caps | Not overridable per-transaction | System override only (via policy republish) | HR (policy-level only) | No | Yes | Same — no per-request cap waiver exists |
| ATT-POL-029 Regularization who-may-request | Yes, per-scope | Higher-priority policy assignment | HR | No | Yes | Same |
| ATT-POL-033 Regularization approval chain | Approved transaction changes the *day*, not the chain itself | Approved transaction override | Manager (stage 1) / HR (final stage) per configured chain | Yes — matches configured chain | Yes — `SUBMITTED/APPROVER_UNRESOLVED/STAGE_APPROVED/APPROVED/REJECTED/CANCELLED/APPLIED` action log | Regularization itself cannot be un-applied except by a further, later regularization or a full recompute after reopen |
| ATT-POL-036 Period lock/finalize | Yes — this is itself the override mechanism for "is this range mutable" | Admin override | HR with `ATTENDANCE.LOCK` (close) / `ATTENDANCE.UNLOCK` (reopen) | Validation must be READY to finalize; `reason` required to reopen | Yes — `OPENED/VALIDATED/VALIDATION_FAILED/CLOSED/REOPENED` | Reopen is reversible (can re-lock), but reopening does **not** restore prior state — it only removes the lock |
| ATT-POL-037 Finalize validation blockers | No — cannot be bypassed | None — no override path found | N/A | N/A | Yes — blocker codes logged | N/A |
| ATT-POL-043 Holiday-vs-WO precedence | No per-transaction override; only a manual `CalendarException` row can change a specific date | Employee/date-specific override (calendar exception) | HR (`ORG.CALENDAR.MANAGE`) | No | Yes | Yes — exception rows can be edited/removed before the date is calculated; locked days unaffected |
| ATT-POL-044 Roster overrides | Yes, per employee-date | Employee-specific override | HR/Manager (`ATTENDANCE.ROSTER_MANAGE`) | No (draft) but only `PUBLISHED` rows take effect | Yes | Yes, while period unlocked |
| ATT-POL-035 `blocked_when_locked` | **No** — despite the name, this flag cannot actually re-enable submission on a locked day; the period-level check is unconditional | None (misleading label) | N/A | N/A | N/A | N/A |
| ATT-POL-051 Leave overlay | Approved transaction override | Approved transaction override | Leave module (via `ATTENDANCE.LEAVE_PROJECTION_SYNC`) | Governed by Leave's own approval chain, enforced before sync is even attempted | Yes — projection status APPROVED/CANCELLED | Yes — cancel reverses it, but only while the attendance period is open |
| ATT-POL-052 Employment population gate | No | System override (absolute, terminal) | N/A — no human action changes NOT_JOINED/EXITED classification directly; only editing the underlying `Employment` record does | N/A | Yes (via Employment audit) | N/A |
| ATT-POL-054 Fail-closed CONFIG_ERROR | No | None by design | Resolved only by fixing the missing config, not by an override action | N/A | N/A | N/A |

## B. Leave policies

| Policy | Can Override? | Override Type | Who Can Override? | Approval Required? | Audit Trail? | Reversible? |
|---|---|---|---|---|---|---|
| LEAVE-POL-002 Probation restriction | Yes, per-scope | Higher-priority policy assignment | HR, by publishing a more specific `LeavePolicyVersion` with `allowed_during_probation=True` | No | Yes | Same as any policy version change |
| LEAVE-POL-005 Self-approval block | **No** | None — no policy field re-enables it | N/A | N/A | N/A | N/A |
| LEAVE-POL-006 Combination rule | Yes | Admin override (rule itself is HR-managed) | HR (CRUD on `LeaveCombinationRule`) | No | Yes (rule CRUD is audited) | Yes — rule can be deleted/changed |
| LEAVE-POL-010 Carry-forward cap | Yes, per-scope | Higher-priority policy assignment | HR | No | Yes | Same |
| LEAVE-POL-011 Encashment caps (`max_encashment_days`, `min_balance_after_encashment`) | **No per-transaction override** — every encashment request is checked against the currently resolved policy, no admin bypass found | None found | N/A | N/A | N/A | N/A |
| LEAVE-POL-014 Statutory minimum | **No** — blocks publish outright | None — no override path in code | N/A (only remedy: raise the accrual rate or adjust the `StatutoryLeaveMinimum` row itself, which is a different action, not an override) | N/A | Yes (publish attempt logged as blocked) | N/A |
| LEAVE-POL-015 Negative balance | **No** | None — hard business rule, `allow_negative_balance` field is dormant | N/A | N/A | N/A | N/A |
| LEAVE-POL-016 Reserved balance (`reserve_balance_on_submission`) | Yes, per-scope | Higher-priority policy assignment | HR | No | Yes | Same |
| LEAVE-POL-024 Cancellation | Yes, but **only by the original submitter** | Employee-specific action (not really an "override" — a first-class right) | Original submitter only — **no manager/HR override path exists in `cancel()`** | N/A | Yes | For an APPROVED cancellation: reverses ledger + projection; blocked if the attendance period is locked |
| LEAVE-POL-027 Approval chain | Approved transaction override (per stage) | Approved transaction override | Manager/HOD/HR per resolved chain | Yes — matches configured chain | Yes — action log entries per stage | Reject is terminal; approved applications can only be reversed via cancellation (LEAVE-POL-024), not by a later "un-approve" |
| LEAVE-POL-028 Approver resolution-failure fallback | Automatic — falls back to HR | Automatic (system) override | N/A — no human decision, always drops to the next resolvable stage or HR | N/A | Yes — `APPROVER_UNRESOLVED` logged | N/A |
| LEAVE-POL-030 Delegation | **Not implemented** | N/A | N/A | N/A | N/A | N/A |
| LEAVE-POL-033 Leave→Attendance projection sync | Attendance can refuse (period closed) | System override (Attendance side wins) | N/A — Leave has no override for a closed attendance period | N/A | Yes | The whole leave-side transaction rolls back; nothing to reverse because nothing was committed |
| LEAVE-POL-034 No leave-specific period lock | N/A — Leave borrows Attendance's lock entirely | N/A | Only Attendance's `ATTENDANCE.UNLOCK` holder can create room for a leave change on a previously-locked date (by reopening the whole attendance period) | Yes (reason required to reopen) | Yes | Yes, via Attendance reopen, but with no automatic reconciliation of Leave-side state |

## C. Shared / cross-cutting

| Policy | Can Override? | Override Type | Who Can Override? | Approval Required? | Audit Trail? | Reversible? |
|---|---|---|---|---|---|---|
| SHARED-POL-001 8-level resolution engine | Yes, structurally — this *is* the override mechanism (more specific scope always wins) | Higher-priority policy override | HR publishing an assignment at a more specific scope | No | Yes | Yes — assignment can be closed/replaced |
| SHARED-POL-002 PROBATION→ACTIVE confirmation | Yes — this is a one-way, one-time transition | Admin/HR action | `EmployeeService.confirm_employee` caller (HR) | No additional approval gate found beyond the permission check | Yes — `EMPLOYEE_CONFIRMED` audit action | **No** — no code path reverses ACTIVE back to PROBATION |
| SHARED-POL-003 Effective-dated modelling (insert-new/close-previous) | N/A — this is the mechanism itself, not a policy to override | — | — | — | Yes, by construction (every version preserved) | Yes — a new version can supersede, old one is never lost |

## D. Override-vs-override precedence (repeated from Master Precedence Matrix §3 for completeness)

See [`MASTER_POLICY_PRECEDENCE_MATRIX.md`](./MASTER_POLICY_PRECEDENCE_MATRIX.md) Section 3 for the full table (Employee-specific vs HR override, Approved regularization vs Manual correction, Manager approval vs HR rejection, Existing approval vs Policy change, Locked record vs New policy, Reopened record vs Historical snapshot). Every row there is either 🟢 Confirmed or flagged 🔵/⚠️ — none were silently resolved by this document.
