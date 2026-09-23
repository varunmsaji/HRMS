# Attendance Policy Precedence

**Status:** Audit document. Policy IDs per [`MASTER_POLICY_INVENTORY.md`](./MASTER_POLICY_INVENTORY.md).

## 1. Policy inputs (what determines whether an attendance policy applies)

| Policy | Applies To | Conditions | Effective From | Effective Until |
|---|---|---|---|---|
| Attendance Policy Version (grace, bands, missing-punch, etc.) | Resolved scope (EMPLOYEE→SHIFT→DESIGNATION→GRADE→DEPARTMENT→BRANCH→LEGAL_ENTITY→COMPANY) via `PolicyAssignment` | `policy_kind='ATTENDANCE_POLICY'`; date must fall in assignment's effective range | `PolicyAssignment.effective_from` | `PolicyAssignment.effective_to` (NULL = open-ended) |
| Overtime Policy Version | Same 8-level scope, `policy_kind='OVERTIME_POLICY'` | Same | Same | Same |
| Regularization Policy Version | Same 8-level scope, `policy_kind='REGULARIZATION_POLICY'` | Same | Same | Same |
| Shift Version | Employee's `EmployeeAssignment.shift_id` (or roster override for the day's actual schedule) | Date within `ShiftVersion.effective_from/effective_to` | `effective_from` | `effective_to` |
| Roster (`ShiftRoster`) | Specific employee + specific date | Row must be `status=PUBLISHED` | Row's `date` | Same day only (single-date row) |
| Work Calendar / Holiday Calendar | Branch/Company (calendar assignment, not the 8-level policy walk) | Date falls in the calendar's holiday list or weekly-off pattern | Holiday/pattern-specific | Holiday/pattern-specific |
| Weekly-Off Pattern | Calendar it's attached to | `weekday`/`nth_in_month`/`cycle_start_date` match the date | N/A (pattern is evaluated per-date) | N/A |
| Employment population gate | Employee | `Employment.joining_date <= date <= (last_working_day or open)` | `joining_date` | `last_working_day` |

## 2. Master precedence hierarchy — attendance day evaluation order

Directly transcribed from the calculation engine (`calculation.py`, `evaluate_day`), highest wins:

```
1. Employment population gate (NOT_JOINED / EXITED)          — terminal, no overlays applied
2. CONFIG_ERROR (calendar unresolved, then policy unresolved) — fail-closed, WD-21
3. Roster week-off override                                   — schedule fact, wins even over calendar WORKING
4. Missing-shift handling                                      — ABSENT/INCOMPLETE per policy, or presence-only if punches exist
5. Calendar NOT_EXPECTED (HOLIDAY/WEEKLY_OFF/SHUTDOWN)         — unless shift/roster explicitly operates that day
6. Punch-derived status (hour bands, late/early bands,
   core-hours breach, cumulative-day overrides)                — no mutual suppression; any one can force worse status
7. Leave overlay                                                — full-day leave wins outright, even over calendar NOT_EXPECTED
8. On-duty overlay                                               — loses to leave if both cover the same date
   (Regularization is not a status branch — approved corrections re-enter as new punches + full recompute, not a precedence tier)
```

This is the one authoritative source for "which attendance rule wins" — see `MASTER_POLICY_MAP.md` for the same information as a diagram.

## 3. Attendance-specific conflicts investigated

All items below are drawn from Section 1 of [`MASTER_POLICY_PRECEDENCE_MATRIX.md`](./MASTER_POLICY_PRECEDENCE_MATRIX.md); this table restates only the pure-Attendance ones with the required investigation columns.

| Conflict ID | Policy A | Policy B | Current Winner | Intended Winner | Reason | Status |
|---|---|---|---|---|---|---|
| CONF-001 | Holiday | Weekly Off | Weekly Off | Weekly Off | WD-05 | 🟢 Confirmed |
| CONF-002 | Holiday/WO | Shift (operates flag) | Shift | Shift | Explicit override flag | 🟢 Confirmed |
| CONF-003 | Weekly Off (calendar) | Roster | Roster | Roster | Schedule fact beats calendar default | 🟢 Confirmed |
| CONF-004 | Roster (schedule) | Employee Shift Assignment (policy scope) | Roster wins for schedule; base assignment still wins for SHIFT-scoped *policy resolution* | Architecture text implies roster should also drive policy scope | Named divergence | 🟠 DOC/IMPL CONFLICT |
| CONF-005/006/007 | Employee/Branch/Shift-scoped policy | Broader-scope policy | More specific scope | Same | 8-level walk | 🟢 Confirmed |
| CONF-008 | Approved regularization | Original punches | Both persist (additive) | Same | Immutable punch ledger | 🟢 Confirmed |
| CONF-009 | Leave | Overtime | No rule — independent facts | Undecided | No interaction coded | ⚠️ DECISION REQUIRED |
| CONF-010/011 | Holiday/WO | Overtime day-class | Classification only | Same | `classify_ot_day` | 🟢 Confirmed |
| CONF-012 | Night OT | Normal OT | No real distinction (window never checked) | Should classify by actual clock time | Gap | 🔵 GAP |
| CONF-013 | OT cap | OT eligibility | Sequential, no conflict | Same | Eligibility gates detection, cap clamps result | 🟢 Confirmed |
| CONF-014 | Period lock | Regularization | Lock wins unconditionally | Same | `_ensure_date_open` | 🟢 Confirmed |
| CONF-016 | Historical record | New policy | Historical record stands | Same | Version-by-date resolution + lock | 🟢 Confirmed |
| CONF-017 | Two overlapping same-scope PolicyAssignments | — | Undefined | Should be prevented or deterministic | Not defended against | ⚠️ DECISION REQUIRED |

## 4. Attendance override authority (summary — full table in `POLICY_OVERRIDE_MATRIX.md`)

| Action | Who | Approval Required? | Can Override Locked Period? |
|---|---|---|---|
| Submit regularization | Employee (self), Manager/HR (on-behalf, if policy allows) | N/A (submission) | No — period-closed check is unconditional |
| Approve regularization (MANAGER stage) | The specific resolved manager (identity match, not just REPORTEES scope) | N/A | No |
| Approve regularization (HR stage) | Any user with COMPANY-scoped `ATTENDANCE.REGULARIZATION_APPROVE` | N/A | No |
| Approve/reject overtime | Same manager/HR pattern as regularization | N/A | No |
| Publish attendance/OT/regularization policy version | `ATTENDANCE.POLICY_MANAGE` (company-scoped) | N/A | N/A (policy publish is independent of period lock) |
| Recompute a day | `ATTENDANCE.RECOMPUTE` | N/A | No — blocked if day/period locked |
| Lock (finalize) a period | `ATTENDANCE.LOCK` | Validation must return READY | N/A |
| Reopen a locked period | `ATTENDANCE.UNLOCK` (deliberately separate, higher-risk permission) | Requires `reason` | N/A (this *is* the unlock action) |
| Sync/cancel a leave projection | `ATTENDANCE.LEAVE_PROJECTION_SYNC` (internal seam, used by Leave module) | N/A | No — refused if period CLOSED |

Self-approval is blocked unconditionally for both regularization and overtime, with no policy field able to re-enable it (`service.py:3891-3892`, `4344-4345`).
