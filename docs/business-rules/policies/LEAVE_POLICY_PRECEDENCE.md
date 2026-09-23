# Leave Policy Precedence

**Status:** Audit document. Policy IDs per [`MASTER_POLICY_INVENTORY.md`](./MASTER_POLICY_INVENTORY.md).

## 1. Policy inputs (what determines whether a leave policy applies)

| Policy | Applies To | Conditions | Effective From | Effective Until |
|---|---|---|---|---|
| Leave Policy Version | Resolved scope (EMPLOYEE→SHIFT→DESIGNATION→GRADE→DEPARTMENT→BRANCH→LEGAL_ENTITY→COMPANY) per leave type, via shared `PolicyAssignment` engine | `policy_kind='LEAVE_POLICY'`, matching `leave_type_id`; date within assignment range | `PolicyAssignment.effective_from` | `PolicyAssignment.effective_to` |
| Leave Type | Company | `is_active=True`; `requires_balance` gates whether ledger logic runs at all | Row-level `is_active` toggle, not effective-dated | N/A |
| Leave Year Setting | Company | `CALENDAR`/`FINANCIAL`/`CUSTOM`/`ANNIVERSARY` — for `ANNIVERSARY`, employee's own `Employment.joining_date` | Applies from whenever configured (no historical versioning found) | N/A |
| Leave Combination Rule | A pair of leave types, company-wide | `allowed=True/False` between the two types | N/A (no effective dating found on the rule itself) | N/A |
| Statutory Leave Minimum | `statutory_category` + optional state/establishment scoping | Checked only at **policy publish** time, using the strictest (max) configured minimum | N/A | N/A |
| Probation eligibility (`allowed_during_probation`, `accrue_during_probation`) | Field on the resolved `LeavePolicyVersion` | Employee's live `Employee.status == 'PROBATION'` at the moment of the check | Tied to policy version's own effective dating | Same |

## 2. Master precedence hierarchy — leave application evaluation order

Directly transcribed from `LeaveApplicationService.submit()` (`service.py:1932-2024`), in code order:

```
1. Resolve LeavePolicyVersion for (employee, leave_type, date) via 8-level scope walk
   → fail closed (LeaveApplicationPolicyNotResolvedError) if none resolves
2. Resolve work calendar for every date in range
   → fail closed (LeaveApplicationCalendarNotResolvedError) if any date unresolved
3. On-behalf permission gate (allow_employee_request / allow_manager_request_on_behalf / allow_hr_request_on_behalf)
4. Probation restriction (allowed_during_probation vs Employee.status)
5. Half-day validity (single-date only, half_day_allowed)
6. Reason required / attachment required
7. Backdating window (max_backdated_days) — no future-date restriction
8. Monthly request cap (max_requests_per_month, excludes CANCELLED)
9. Day-breakdown computation (WORKING/SPECIAL_WORKING consume; WEEKLY_OFF/HOLIDAY/SHUTDOWN don't, unless sandwiched)
   → fail if resulting total is zero consuming days (LeaveApplicationDateRangeInvalidError)
10. Leave combination rule check (blocks overlap with a specific other type only if an explicit allowed=False rule exists)
11. Balance sufficiency check (optionally net of reserved/pending balance if reserve_balance_on_submission)
    → hard block if insufficient; negative balance never permitted
12. Approval-chain resolution (manager/HOD identity resolved as of submission; unresolved stages dropped; all-unresolved falls back to single HR stage)
13. Self-approval block (always active, cannot be disabled by policy)
```

Approval-time sequence (`_approve_internal`, `service.py:2296-2399`):
```
Stage approval (non-final) → advance approval_stage, no ledger/attendance effect yet
Final-stage approval        → ledger debit (APPLICATION entry, unless requires_balance=False)
                             → sync LeaveDayProjection into Attendance (same DB transaction)
                             → whole transaction rolls back if the attendance period is CLOSED (LD-12)
```

## 3. Leave-specific conflicts investigated

| Conflict ID | Policy A | Policy B | Current Winner | Intended Winner | Reason | Status |
|---|---|---|---|---|---|---|
| CONF-018 | Employee-specific leave policy | Organization-level leave policy | Employee (most specific) | Same | Shared 8-level engine | 🟢 Confirmed |
| CONF-019 | Leave-type policy version | "Global" leave policy | N/A — no global layer exists | N/A | Not a real conflict in this model | 🟢 Confirmed (no such layer) |
| CONF-020 | Eligibility restriction | Available balance | Eligibility checks run before balance check in code, but this ordering isn't documented as an intentional rule | Undetermined | Implementation order, not stated business rule | ⚠️ DECISION REQUIRED |
| CONF-021 | Probation restriction | Leave entitlement already granted | If accrual is also blocked during probation, balance stays literally zero — restriction and non-accrual compound | Same | `accrue_during_probation` | 🟢 Confirmed |
| CONF-022 | Negative-balance permission | Balance limit | Balance limit always wins; negative balance never allowed regardless of the dormant `allow_negative_balance` field | Advance-leave support is an open future-feature question | LD-06 | 🟢 Confirmed current behaviour; ⚠️ advance-leave feature open |
| CONF-023 | Carry-forward policy | Expiry/lapse policy | Same mechanism — carry-forward cap enforcement *is* the expiry mechanism; no separate expiry concept | Same | `service.py:1506-1509` | 🟢 Confirmed |
| CONF-024 | Carry-forward cap | Existing balance | Cap wins, excess forfeited | Same | Year-end sweep | 🟢 Confirmed |
| CONF-025 | Leave overlap (same type) | Multiple leave requests | Not blocked at all | Undetermined | Gap — only cross-type combination rule exists | ⚠️ DECISION REQUIRED / 🔵 GAP |
| CONF-026 | Leave cancellation | Attendance already processed | Blocked entirely if attendance period is CLOSED; no partial/arrears path | Same | LD-13 + attendance lock | 🟢 Confirmed (see cross-module matrix) |

## 4. Leave override authority (summary — full table in `POLICY_OVERRIDE_MATRIX.md`)

| Action | Who | Approval Required? | Notes |
|---|---|---|---|
| Submit leave application | Employee (self); Manager/HR on-behalf if policy allows | N/A | Probation/balance/combination/backdating gates apply regardless of submitter identity |
| Approve — MANAGER stage | Snapshotted `resolved_approver_manager_id` (identity match) | N/A | Resolved as of submission date, not "current" manager |
| Approve — HOD stage | Snapshotted `resolved_department_head_id` | N/A | Self-head loop guarded — never routes to the applicant |
| Approve — HR stage | Any COMPANY-scoped `LEAVE.APPLICATION_APPROVE` holder | N/A | No specific identity required |
| Reject | Whoever holds the current stage's approval authority | N/A | Terminal — no send-back-to-previous-stage path |
| Cancel | **Only the original submitter** | N/A | No manager/HR override path in `cancel()` |
| Delegate approval authority | — | — | 🔵 **Not implemented** — no delegate/out-of-office mechanism exists anywhere in the module |
| Encash leave | HR with `LEAVE.BALANCE_ADJUST` | N/A | Subject to `encashment_allowed`, `max_encashment_days`, `min_balance_after_encashment` — no override path around these caps |
| Publish leave policy version | HR (policy-management permission) | Blocked below statutory minimum, no override | — |

Self-approval is blocked unconditionally, with no policy field able to re-enable it (`service.py:2190-2192`) — identical posture to Attendance regularization/OT.
