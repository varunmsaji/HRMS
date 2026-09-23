# Payroll Input Readiness Matrix

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Commit | `e33fcdb` |
| Parent document | [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) |

Everything Payroll will consume from the completed modules, with a verified readiness verdict for each.

**Readiness key**

| Badge | Meaning |
|---|---|
| 🟢 READY | Authoritative, auditable, historically safe. Payroll may depend on it as-is. |
| 🟡 CONDITIONAL | Usable once a named condition is met. |
| 🔴 NOT READY | Must be fixed before Payroll consumes it. |

---

## 1. Identity and employment inputs

| Payroll input | Source module | Source of truth (table.column) | Finalized? | Auditable? | Historical safe? | Ready? |
|---|---|---|---|---|---|---|
| Employee id | employee | `employee.id` | n/a | ✅ `audit_log` | ✅ | 🟢 |
| Employee code | employee | `employee.employee_code` (sequence-backed) | n/a | ✅ | ✅ | 🟢 |
| Employment status | employee | `employment.status` — `ACTIVE`/`TERMINATED`, DB CHECK | n/a | ✅ | ✅ | 🟢 |
| Lifecycle status | employee | `employee.status` — `PROBATION`/`ACTIVE`/… | n/a | ✅ | ⚠️ **current value only** — not effective-dated | 🟡 Payroll must not ask "was this employee on probation in March" |
| Joining date | employee | `employment.joining_date` | n/a | ✅ | ✅ GiST `employment_no_overlap` | 🟢 |
| Exit date | employee | `employment.last_working_day` | n/a | ✅ | ✅ CHECK: set *iff* `status='TERMINATED'` | 🟢 |
| Rehire linkage | employee | `employment.previous_employment_id` | n/a | ✅ | ✅ new spell, never a mutation | 🟢 |
| Probation end | employee | `employment.probation_end_date` | n/a | ✅ | ✅ | 🟢 Informational only |
| Legal entity | employee | `employment.legal_entity_id` | n/a | ✅ | ✅ | 🟢 |

**Evidence.** `apps/api/src/hrms/modules/employee/models.py:71-112`; `EmploymentService.get_employment_as_of`
(`employee/service.py:1028`) and `get_latest_employment_on_or_before` (`:1043`) are the cross-module
as-of contract Attendance already consumes.

---

## 2. Organisational placement

| Payroll input | Source | Source of truth | Effective-dated? | Ready? |
|---|---|---|---|---|
| Branch | employee | `employee_assignment.branch_id` | ✅ `get_assignment_as_of` | 🟢 |
| Department | employee | `employee_assignment.department_id` | ✅ | 🟢 |
| Designation | employee | `employee_assignment.designation_id` | ✅ | 🟢 |
| Grade | employee | `employee_assignment.grade_id` | ✅ | 🟢 |
| Reporting manager | employee | `employee_assignment.reporting_manager_id` | ✅ | 🟢 |
| Cost centre / work location | employee | `employee_assignment.*` | ✅ | 🟢 |
| Shift | employee + attendance | `shift_roster` (PUBLISHED) **>** `employee_assignment.shift_id` | ✅ | 🟢 |

**Evidence.** `EmployeeAssignmentService.get_assignment_as_of`; roster precedence at
`attendance/service.py:2772-2776`.

---

## 3. Compensation and statutory

| Payroll input | Source | Source of truth | Type safety | Ready? |
|---|---|---|---|---|
| **Annual CTC** | employee | `employee_compensation.annual_ctc_minor` | ✅ `BigInteger` minor units (ADR-0006) | 🔴 **NOT READY — never created for employees activated through onboarding (PAY-014).** The bulk-import path creates it; the onboarding wizard does not. |
| Currency | employee | `employee_compensation.currency` | ✅ | 🟢 |
| Compensation effective range | employee | `effective_from` / `effective_to` | ✅ | 🟢 |
| PF / ESI / UAN / PAN / Aadhaar | employee | `employee_statutory.*` | ✅ | 🟡 stored in plaintext — no column-level encryption |
| VPF amount | employee | `employee_statutory.vpf_amount` (`BigInteger`) | ✅ | 🟢 |
| VPF percentage | employee | `employee_statutory.vpf_percentage` (`Numeric(9,4)`) | ⚠️ annotated `float` in Python (DAT-007) | 🟡 Fix the annotation before any arithmetic |
| Bank details | employee | `employee_bank.*` | ✅ | 🟡 plaintext |
| Salary structure / components | — | **Does not exist** | — | 🔴 Payroll must build it |

---

## 4. Calendar and schedule

| Payroll input | Source | Source of truth | Ready? |
|---|---|---|---|
| Work calendar | organisation | `work_calendar` resolved via 8-level `PolicyAssignment` precedence | 🟢 |
| Holiday | organisation | `holiday` via `work_calendar_holiday_calendar` links; **first-list-wins** on duplicates | 🟢 |
| Holiday type semantics | organisation | `holiday.holiday_type` — `WORKING_HOLIDAY` stays WORKING; `OPTIONAL`/`RESTRICTED` governed by `restricted_holidays_are_off_by_default` | 🟢 Deterministic (PD-CAL-1 is a *business* question, not a code gap) |
| Calendar exception | organisation | `calendar_exception` — `SHUTDOWN`/`SPECIAL_WORKING`/`SUBSTITUTE_HOLIDAY`/`CANCEL_HOLIDAY`; **always wins** | 🟢 |
| Weekly off (binary) | organisation | `weekly_off_rule` — fixed / nth / last / alternate | 🟢 |
| **Weekly off (fraction)** | organisation | `weekly_off_rule.off_fraction` | 🔴 **Computed then discarded** (`calendar_resolution.py:140`). A half-day Saturday becomes a full weekly off. |
| Holiday on a weekly off | organisation | Stays `WEEKLY_OFF` + `holiday_on_weekly_off` flag; no substitution | 🟢 Deterministic (PD-CAL-2 is a business question) |
| Scheduled minutes | organisation | `shift_version` resolved as-of, snapshotted onto `attendance_day.shift_version_id` | 🟢 |
| Shift timezone | organisation | `shift_version.timezone` > `branch.timezone` > `company.timezone` | 🟢 |

---

## 5. Attendance — the critical block

| Payroll input | Source of truth | Finalized? | Auditable? | Historical safe? | Ready? |
|---|---|---|---|---|---|
| Attendance status | `attendance_day.attendance_status` | ✅ `is_locked` | ✅ snapshot + `audit_log` | 🟠 PAY-008 | 🟡 |
| **Paid day fraction** | `attendance_day.paid_day_fraction` | ✅ locked | ⚠️ lock-time rewrite unaudited (PAY-007) | 🟠 | 🔴 **NOT READY** — wrong for `NOT_JOINED` (PAY-004); zero for `INCOMPLETE` until lock (PAY-006); **absent from the frozen summary** (PAY-002) |
| **LOP fraction** | `attendance_day.lop_fraction` → `summary.lop_days` | ✅ | ⚠️ same | 🟠 | 🔴 **NOT READY** — wrong for `EXITED` (PAY-005) |
| Worked minutes | `attendance_day.worked_minutes` → `summary.worked_minutes_total` | ✅ | ✅ `snapshot.presence` | ✅ | 🟢 |
| Paid / unpaid break minutes | `attendance_day.paid_break_minutes` / `unpaid_break_minutes` | ✅ | ✅ `attendance_break` child rows | ✅ | 🟡 Scheduled-but-unpunched breaks are never deducted (ATT-008) |
| Late minutes / count | `attendance_day.late_minutes` → `summary.late_count` | ✅ | ✅ | ✅ | 🟢 Attendance never converts lateness to money |
| Early departure minutes | `attendance_day.early_departure_minutes` | ✅ | ✅ | ✅ | 🟢 |
| Present / absent / half / leave days | `attendance_period_summary.*` | ✅ frozen | ✅ | ✅ | 🔴 **NOT READY** — double-counted and under-covered (PAY-003) |
| Holiday / weekly-off days | `summary.holiday_days` / `weekly_off_days` | ✅ | ✅ | ✅ | 🔴 Counted **in addition to** the status bucket (PAY-003) |
| Worked-on-holiday flag | `attendance_day.worked_on_holiday` | ✅ | ✅ | ✅ | 🟢 |
| Worked-on-weekly-off flag | `attendance_day.worked_on_weekly_off` | ✅ | ✅ | ✅ | 🟢 |
| Regularization applied | Synthetic `punch` rows (`source='REGULARIZATION'`) + `attendance_regularization_action` | ✅ lock-guarded | ✅ full timeline | ✅ | 🟢 Excellent — corrections never mutate a fact |
| ON_DUTY | `attendance_day.on_duty` + `on_duty_regularization_id` | ✅ | ✅ | ✅ | 🟡 Falls into no summary bucket (PAY-003) |
| Core-hours breach | `attendance_day.is_core_hours_breach` | ✅ | ✅ | ✅ | 🟢 |
| Punches (raw) | `punch` — immutable, append-only, never updated or deleted | ✅ | ✅ | ✅ | 🟢 Excellent |

---

## 6. Overtime

| Payroll input | Source of truth | Finalized? | Ready? |
|---|---|---|---|
| Detected OT minutes | `attendance_day.ot_minutes_detected` / `overtime_record.minutes_detected` | ✅ | 🟡 Depends on sibling-day budget state (PAY-008) |
| **Approved OT minutes** | `overtime_record.minutes_approved` → `summary.ot_minutes_*` | ✅ frozen at close; record frozen once terminal (WD-29 d2) | 🟢 |
| OT day class | `overtime_record.day_class` | ✅ snapshotted | 🟡 NIGHT is misclassified under `night_ot_mode=WINDOW` (ATT-005) |
| OT classification code | `overtime_record.classification_code` | ✅ | 🟡 same |
| **OT multiplier** | `overtime_record.configured_multiplier` (`Numeric(5,4)`) | ✅ snapshotted at decision time | 🟢 **Informational only** — Attendance never applies it as money (ADR-0006, WD-03 §12.1). Payroll owns rate application. |
| OT approval trail | `overtime_action` append-only timeline + `audit_log` | ✅ | 🟢 |
| Comp-off minutes earned | `overtime_record.comp_off_minutes` | ✅ | 🟢 |
| Comp-off expiry | `overtime_record.comp_off_expiry_date` | ✅ | 🟢 |
| OT caps applied | Daily / weekly / monthly, applied in `detect_overtime` | ✅ | 🟡 The remaining-budget input is not snapshotted (PAY-008) |

---

## 7. Leave

| Payroll input | Source of truth | Finalized? | Ready? |
|---|---|---|---|
| Leave days consumed (Payroll-facing) | `leave_day_projection` — `status='APPROVED'`, per employee-date, with `fraction` and `is_paid` | ✅ lock-guarded on both sync and cancel | 🟡 Duplicates `leave_application_day` (ARC-003) — pick one, declared in the contract |
| Leave days consumed (Leave-owned) | `leave_application_day` | ✅ | 🟡 same |
| Paid vs unpaid leave | `leave_day_projection.is_paid` (from `leave_type.is_paid_default`) | ✅ | 🟢 |
| Half-day leave | `leave_day_projection.half` = `FIRST`/`SECOND` (translated from Leave's `FIRST_HALF`/`SECOND_HALF`) | ✅ | 🟢 |
| Sandwich-generated days | `leave_application_day.is_sandwich_generated` | ✅ | 🟢 Distinguishable, which Payroll will need |
| **Leave balance** | `SUM(leave_ledger.amount)` — never a stored column (ADR-0004) | ❌ **never frozen** | 🟡 Authoritative and auditable, but can move after an attendance period closes |
| Ledger entry types | `ACCRUAL` · `APPLICATION` · `ADJUSTMENT` · `ENCASHMENT` · `CARRY_FORWARD` · `COMP_OFF_CREDIT` | append-only | 🟢 |
| Encashment | `leave_ledger` `ENCASHMENT` debit, policy-validated | append-only | 🟢 Ledger side ready; **payout amount is Payroll's** |
| Carry-forward forfeiture | `leave_ledger` `CARRY_FORWARD` negative entry at leave-year start | append-only | 🟡 Concurrency-unsafe (DAT-001) |
| Leave-year boundary | `leave_year_setting` + `leave/year.py` — `CALENDAR`/`FINANCIAL`/`ANNIVERSARY`/`CUSTOM` | n/a | 🟢 Pure, unit-tested, leap-day safe |
| Comp-off balance | Same ledger, `leave_type.is_comp_off = true` | append-only | 🟡 Requires `comp_off_day_length_minutes` set, or nothing is ever credited |
| Statutory minimum floor | `statutory_leave_minimum` — enforced at policy publish against the **strictest** configured value | n/a | 🟢 Fail-safe by design (LD-22) |

---

## 8. Period and lock

| Payroll input | Source of truth | Ready? |
|---|---|---|
| Period definition | `attendance_period` — `[start, end]` inclusive, GiST non-overlap per company | 🟢 |
| Period status | `attendance_period.status` — `OPEN` / `CLOSED` | 🟢 |
| Day-level lock | `attendance_day.is_locked` / `locked_at` / `locked_by` | 🟢 |
| Lock enforcement | `_ensure_date_open` on punch, roster, regularization, OT decision, leave projection sync **and** cancel | 🟢 **The strongest guarantee in the system** |
| Validation verdict | `attendance_period.last_validation_status` + the six blocking-reason codes | 🟢 |
| Period timeline | `attendance_period_action` append-only | 🟢 |
| Reopen | `ATTENDANCE.UNLOCK`, reason mandatory, fully audited | 🟢 |
| **Frozen summary** | `attendance_period_summary` | 🔴 PAY-002, PAY-003 |
| **Period grain** | Company only — `legal_entity_id` reserved, always NULL | 🟡 PD-LOCK-1 open (BUS-007) |
| Leave period | **Does not exist** | 🟡 PD-3 open |

---

## 9. Cross-cutting

| Payroll input | Source of truth | Ready? |
|---|---|---|
| Company timezone | `company.timezone` (default `Asia/Kolkata`) | 🔴 **NOT READY — mutable with no guard; the guard hook is an empty function (PAY-013). A change silently alters unlocked historical attendance.** |
| Branch timezone | `branch.timezone` | 🔴 **NOT READY — no guard exists at all (PAY-013)** |
| Tenant scoping | `company_id` on every table + RLS on 70/79 tables + a non-superuser runtime role | 🟡 Designed well, verified weakly (TEN-002) |
| Audit trail | `audit_log` (who / what / when / before / after / ip / user_agent / request_id) | 🟡 No read API; lock-time rewrite unaudited |
| Permission model | `permission` + `role_permission.data_scope` + `DataScope` levels | 🟢 Payroll should reuse it directly |
| Money representation | Integer minor units + explicit currency (ADR-0006) | 🟢 |
| Duration representation | Integer minutes throughout; **no minutes→hours→money conversion exists anywhere** | 🟢 Exactly the right boundary |

---

## Readiness roll-up

| Category | 🟢 Ready | 🟡 Conditional | 🔴 Not ready |
|---|---|---|---|
| Identity & employment | 8 | 1 | 0 |
| Organisational placement | 7 | 0 | 0 |
| Compensation & statutory | 3 | 4 | 2 |
| Calendar & schedule | 8 | 0 | 1 |
| **Attendance** | **7** | **4** | **3** |
| Overtime | 5 | 4 | 0 |
| Leave | 8 | 6 | 0 |
| Period & lock | 7 | 2 | 1 |
| Cross-cutting | 2 | 3 | 2 |
| **Total** | **55** | **24** | **9** |

**Where the nine 🔴 items sit:**

- **Six are in the paid-days / LOP / summary chain** — precisely what Payroll exists to consume
  (PAY-001…006).
- **One is compensation itself** — employees onboarded through the wizard have no CTC at all (PAY-014).
  This was invisible from the attendance path and only surfaced on a dedicated onboarding review.
- **Two are timezone** — company and branch timezone are freely mutable, and the guard written for
  exactly this case is an empty function (PAY-013).

Everything else is either ready, or ready subject to a named and bounded condition.

---

## What Payroll should read, and from where

Once the P0 remediation lands, the recommended consumption pattern is:

```
Payroll run for (company, period)
  │
  ├─ REQUIRE attendance_period.status = 'CLOSED'          ← enforce in code, not convention
  │
  ├─ attendance_period_summary                            ← per-employee frozen roll-up
  │     paid_days · payable_days · lop_days                 (paid_days/payable_days = PAY-002 fix)
  │     present/absent/leave/half/holiday/weekly_off        (mutually exclusive = PAY-003 fix)
  │     ot_minutes_normal / weekly_off / holiday / night
  │     comp_off_minutes_earned · worked_minutes_total · late_count
  │
  ├─ employment (as-of period bounds)                     ← pro-rata window
  ├─ employee_assignment (as-of)                          ← cost centre, grade, entity
  ├─ employee_compensation (as-of)                        ← annual_ctc_minor
  ├─ employee_statutory / employee_bank                   ← PF/ESI/TDS, payout
  ├─ overtime_record.configured_multiplier                ← rate hint, Payroll applies it
  └─ leave_day_projection (declared Payroll-facing)       ← paid vs unpaid leave days
```

**Never** read `attendance_day` directly for money. Read the frozen summary. `attendance_day` is for
explanation and dispute resolution, not computation.

---

*No application code, schema, migration, test, or configuration was modified during this audit.*
