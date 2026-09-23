# HRMS Policy Decision, Override & Precedence Audit — Complete Report

**Modules audited:** Attendance, Leave Management
**Audit date:** 2026-09-07
**Method:** Direct reading of source code (apps/api/src/hrms/modules/attendance, apps/api/src/hrms/modules/leave), existing business-rule documentation, architecture decision logs (WD-01..WD-33, LD-01..LD-23), and the full integration/unit test suites for both modules. No policy rule was invented; every unresolved item is explicitly marked.

---

## Table of Contents

1. [Master Policy Inventory](#1-master-policy-inventory)
2. [Master Policy Precedence Matrix](#2-master-policy-precedence-matrix)
3. [Attendance Policy Precedence](#3-attendance-policy-precedence)
4. [Leave Policy Precedence](#4-leave-policy-precedence)
5. [Attendance–Leave Interaction Matrix](#5-attendanceleave-interaction-matrix)
6. [Policy Override Matrix](#6-policy-override-matrix)
7. [Policy Effective-Date & History Analysis](#7-policy-effective-date--history-analysis)
8. [Hidden Policy Decisions Audit](#8-hidden-policy-decisions-audit)
9. [Master Policy Decision Register](#9-master-policy-decision-register)
10. [Master Policy Map](#10-master-policy-map)
11. [Policy Precedence Scenario Catalog](#11-policy-precedence-scenario-catalog)
12. [Client Policy Review & Sign-Off](#12-client-policy-review--sign-off)

---

## 1. Master Policy Inventory


**Status:** Audit document. Does not change system behaviour.
**Method:** Compiled from (a) existing business-rule docs in `docs/business-rules/attendance/` and `docs/business-rules/ATTENDANCE_V1_*`, (b) `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` + `WORKFORCE_ATTENDANCE_DECISION_LOG.md` (WD-01…WD-33), (c) `docs/architecture/LEAVE_DECISION_LOG.md` (LD-01…LD-23), (d) `docs/adr/0003` and `0004`, (e) direct reading of `apps/api/src/hrms/modules/attendance/*.py` and `apps/api/src/hrms/modules/leave/*.py`, (f) the integration/unit test suites for both modules.
**Tagging legend:** 🔧 Current implementation · 📋 Documented/intended policy · 🟢 Confirmed policy decision · ⚠️ Policy decision required · 🟠 Documentation/implementation conflict · 🔵 Implementation gap.

No policy in this inventory was invented. Every row traces to a named source file. IDs are stable across all 12 audit documents — use them for cross-referencing.

---

## A. ATTENDANCE POLICIES (ATT-POL-001…054)

| Policy ID | Policy Name | Purpose | Source | Current Status |
|---|---|---|---|---|
| ATT-POL-001 | Grace-in / grace-out minutes | Leeway before lateness/early-departure counts | `attendance/models.py:90-91`; `calculation.py:1148,1154` | 🔧 Functional, configurable |
| ATT-POL-002 | Late-arrival bands | Ordered minute ranges → flag/Half-Day/Absent | `01_ATTENDANCE_BUSINESS_RULES.md` §8; `calculation.py` `lookup_band` | 🔧 Functional |
| ATT-POL-003 | Early-departure bands | Mirror of late bands on `scheduled_end` | `01` §9; `calculation.py:1493-1505` | 🔧 Functional |
| ATT-POL-004 | Hour bands (Present/Half-Day/Absent) | Worked-minutes → base status | `AttendancePolicyHourBand`; `calculation.py:1488-1491` | 🔧 Functional |
| ATT-POL-005 | Half-day split method (`half_day_split`, `half_day_boundary_minutes`) | Alternate half-day determination | `models.py:104-105` | 🔵 STORED BUT NOT USED — actual half-day comes from hour bands, not this field |
| ATT-POL-006 | Missing-punch behaviour | INCOMPLETE / ABSENT / AUTO_CLOSE / REQUIRE_REGULARIZATION on unmatched punches | `models.py:98`; `calculation.py:1473-1486` | 🔧 Partially functional — `AUTO_CLOSE` never synthesizes an OUT punch (`calculation.py`, WD comment); `REQUIRE_REGULARIZATION` has no distinct branch, behaves as `INCOMPLETE` |
| ATT-POL-007 | Missing-shift behaviour | ABSENT/INCOMPLETE when no shift resolves | `models.py:101`; `calculation.py:797-812` | 🔧 Functional |
| ATT-POL-008 | Multi-punch pairing mode | `PAIR_ALL` vs `FIRST_IN_LAST_OUT` | `models.py:108`; `calculation.py:521-547` | 🔧 Functional |
| ATT-POL-009 | Duplicate-punch collapse window | Seconds within which same-direction punches merge | `models.py:109`; `calculation.py:468-483` | 🔧 Functional, default 60s |
| ATT-POL-010 | Punch rounding (`punch_rounding`, `rounding_minutes`) | Round punch instants pre-evaluation | `models.py:94-95` | 🔵 STORED BUT NOT USED |
| ATT-POL-011 | Split-shift missed-block behaviour | IGNORE/HALF_DAY/ABSENT/REQUIRE_REGULARIZATION | `models.py:117`; `calculation.py:1353-1371` | 🔧 Functional (block-level, not minute-level — documented simplification) |
| ATT-POL-012 | Split-shift block-mandatory / hours-compensation | Optional blocks / cross-block hour compensation | `models.py:117` area | 🔵 STORED BUT NOT USED |
| ATT-POL-013 | Work-on-leave behaviour | `KEEP_LEAVE` vs `PRESENT_CANCEL_LEAVE_HINT` | `models.py:126`; `calculation.py:878-935` | 🔧 Functional — see Attendance–Leave matrix |
| ATT-POL-014 | Incomplete-at-lock behaviour | TREAT_ABSENT / TREAT_PRESENT / KEEP_INCOMPLETE at finalize | `models.py:143`; `service.py:5016-5051`, `4781-4818` | 🔧 Functional; `KEEP_INCOMPLETE` blocks finalize |
| ATT-POL-015 | Core-hours (flex) + breach behaviour | Mandatory presence window in FLEXIBLE shift | `models.py:112`; `calculation.py:1174-1190` | 🔧 Functional (built per WD-32, 2026-08-25); block-level check, not minute-level |
| ATT-POL-016 | Excess-break behaviour + cumulative excess-break-days→Half-Day | Consequence of exceeding max break duration, single-day and cumulative | `models.py:129,140`; `calculation.py:1205-1211` | 🔧 Functional (cumulative variant built per WD-32) |
| ATT-POL-017 | Auto-close (`auto_close_after_minutes`, `auto_close_uses_shift_end`) | Auto-insert a clock-out for a forgotten punch | `models.py` (missing-punch area) | 🔵 STORED BUT NOT USED |
| ATT-POL-018 | Late-count window / lates-to-half-day cumulative trigger | "N lates in a period ⇒ Half-Day" | `models.py:132-133`; `calculation.py:1198-1204` | 🔧 Functional (built per WD-32); only `MONTH` window value supported |
| ATT-POL-019 | Early-departure-requires-approval | Pre-approval gate before leaving early | `models.py:134`; new `EARLY_DEPARTURE_APPROVAL` regularization type | 🔧 Functional (built per WD-32) |
| ATT-POL-020 | WFH / On-Duty punch rules | Govern WFH/On-Duty attendance mode | `models.py:121-123`; `schemas.py:1207-1219` | 🟠 CONFLICT — `ON_DUTY` fully wired (WD-32 decision 6); `WFH` is a declared enum value the engine never assigns (`calculation.py:1462`, "WFH remains a no-op") |
| ATT-POL-021 | OT eligibility mode | NEVER / SHIFT_FLAG / ALWAYS / GRADE_VIA_ASSIGNMENT | `models.py:251`; `calculation.py:696-739` | 🔵 GAP — only `NEVER`/`SHIFT_FLAG` are distinctly coded; `ALWAYS` and `GRADE_VIA_ASSIGNMENT` both fall through as "always eligible," no grade check exists |
| ATT-POL-022 | OT minimum minutes | Excess below threshold discarded | `models.py:252`; `calculation.py:716-718` | 🔧 Functional |
| ATT-POL-023 | OT rounding | Rounds excess minutes | `models.py:253-254`; `calculation.py:720-721` | 🔧 Functional |
| ATT-POL-024 | OT daily/weekly/monthly caps | Clamp detected OT | `models.py:257-259`; `calculation.py:723-728`; `service.py:3009-3038` | 🔧 Functional; weekly/monthly caps computed from sibling records → non-idempotent recompute (documented, WD-29 decision 3) |
| ATT-POL-025 | OT approval chain + pre/post-approval requirement | Whether/how OT needs human sign-off | `models.py:255-256,270` | 🔵 `requires_pre_approval` stored, never read anywhere in code — dormant field |
| ATT-POL-026 | Night-OT classification | Whether overnight OT is classified NIGHT | `models.py:267-269`; `calculation.py:679-693,1237,1388,1405` | 🔵 GAP — `night_ot_mode=WINDOW/BOTH` and `night_window_start/end` declared but never compared against actual clock time; "night" is always derived from `shift.is_cross_midnight` only |
| ATT-POL-027 | OT day-class + rate rows | Classification + informational multiplier | `models.py`; `schemas.py:61`; `calculation.py:679-693` | 🔧 Functional for classification; multiplier is informational only, never drives money (by design — Attendance owns no payroll) |
| ATT-POL-028 | Comp-off (instead of pay, expiry days, day-length minutes) | Converts OT into a time-off fact for Leave to consume | `models.py:260-266` | 🔧 Functional as a fact-emission contract; actual crediting/expiry logic lives in Leave (see LEAVE-POL-012/013) |
| ATT-POL-029 | Regularization: who may request | employee/manager/HR submission gates | `models.py:336-338`; `service.py:3536-3544` | 🔧 Functional |
| ATT-POL-030 | Regularization: max backdated days / max requests per month | Submission window and volume caps | `models.py:339-340`; `service.py:3546-3563` | 🔧 Functional |
| ATT-POL-031 | Regularization: reason/attachment required | Submission-content gates | `models.py:341-342`; `service.py:3551-3554` | 🔧 Functional |
| ATT-POL-032 | Regularization: allowed types | MISSING_PUNCH / WRONG_PUNCH / WRONG_SHIFT / WRONG_STATUS / WFH / ON_DUTY / EXCESS_BREAK / FULL_DAY / EARLY_DEPARTURE_APPROVAL | `schemas.py:63-75` | 🔧 Functional (WRONG_STATUS/EXCESS_BREAK-without-punch-change representability still an open decision — PD-REG-1) |
| ATT-POL-033 | Regularization approval chain | AUTO/MANAGER/MANAGER_THEN_HR/HR | `models.py:343`; `service.py:3606-3702` | 🔧 Functional |
| ATT-POL-034 | Regularization `auto_approve_within_minutes` | Small clock-error auto-approve window | `models.py:344` | 🔵 STORED BUT NOT USED — no read found in service.py |
| ATT-POL-035 | Regularization `blocked_when_locked` | Looks like an escape hatch for locked-period submission | `models.py:345`; `service.py:3580-3585` | 🟠 CONFLICT — label implies conditional lock bypass, but `_ensure_date_open` blocks submission unconditionally regardless of this flag's value (`service.py:3491-3496`); flagged for relabelling in `ATTENDANCE_CLIENT_RULES_AND_SCENARIOS.md` §26.2 |
| ATT-POL-036 | Period lock / finalize / reopen lifecycle | Freeze a payroll cycle; OPEN↔CLOSED | `models.py:846-853`; `service.py:5053-5220` | 🔧 Functional |
| ATT-POL-037 | Period finalize validation blockers | 6 typed blocking codes | `schemas.py:1767-1774`; `service.py:4712-4896` | 🔧 Functional; atomic rollback on any blocker |
| ATT-POL-038 | Work calendar / day-type resolution | WORKING/WEEKLY_OFF/HOLIDAY/SPECIAL_WORKING/SHUTDOWN | `01` §4; `ARCH` §6 | 🔧 Functional |
| ATT-POL-039 | Holiday types | PUBLIC/COMPANY/OPTIONAL/RESTRICTED/WORKING_HOLIDAY | `01` §4.4 | 🔧 Functional |
| ATT-POL-040 | Calendar exceptions | SHUTDOWN/SPECIAL_WORKING/SUBSTITUTE_HOLIDAY/CANCEL_HOLIDAY, checked first | `01` §4.3 | 🔧 Functional |
| ATT-POL-041 | `restricted_holidays_are_off_by_default` | Whether OPTIONAL/RESTRICTED holidays are hard holidays | `01` §4.1 | 🔧 Functional, default `False` |
| ATT-POL-042 | Weekly-off patterns | FIXED_WEEKDAYS/NTH_WEEKDAY/ALTERNATE/CUSTOM | `01` §4.5 | 🔧 Functional |
| ATT-POL-043 | Holiday-vs-weekly-off precedence | Hard holiday on WO stays WO + flag; no auto-substitute | `02` §2; WD-05 | 🟢 Confirmed (WD-05); PD-CAL-2 (auto-substitute) remains open |
| ATT-POL-044 | Roster (shift/week-off/holiday-working overrides) | Per-employee-date schedule override | `01` §12; WD-27 | 🔧 Functional; only `PUBLISHED` rows count |
| ATT-POL-045 | Shift versioning | DRAFT→PUBLISHED, effective-dated | `organisation/models.py:291-292` | 🔧 Functional |
| ATT-POL-046 | Shift types | FIXED/FLEXIBLE/SPLIT | `01` §5 | 🔧 Functional |
| ATT-POL-047 | Cross-midnight attribution | Whole duty attributed to shift-start date | `01` §5.3 | 🔧 Functional |
| ATT-POL-048 | Break rules | FIXED_WINDOW/FLEXIBLE_DURATION, paid/unpaid, mandatory, max duration | `01` §6 | 🔧 Partially functional — no auto-deduction for a mandatory break with zero punched gap (documented limitation, `calculation.py:23-28`) |
| ATT-POL-049 | Policy-assignment precedence (8-level scope chain) | EMPLOYEE>SHIFT>DESIGNATION>GRADE>DEPARTMENT>BRANCH>LEGAL_ENTITY>COMPANY | `organisation/calendar_resolution.py:48-57,251-315` | 🔧 Functional; shared engine also used by Leave |
| ATT-POL-050 | Timezone resolution precedence | ShiftVersion > Branch > Company | `01` §5.3; WD-06 | 🔧 Functional |
| ATT-POL-051 | Leave Day Projection mirror + overlay | Attendance-owned mirror of approved leave | `models.py:976-1032`; `calculation.py:861-935` | 🔧 Functional; now actively written by the real Leave module (see 📋/🟠 note in Section D) |
| ATT-POL-052 | Employment population gate | NOT_JOINED/ACTIVE/EXITED, derived from `Employment`, not `Employee.status` | `service.py:2724-2739`; `calculation.py:179` | 🔧 Functional |
| ATT-POL-053 | Paid/LOP fraction mapping | Status → payroll-facing paid/unpaid fraction | `01` §7.5 | 🔧 Functional |
| ATT-POL-054 | Fail-closed CONFIG_ERROR | No silent WORKING/PRESENT defaulting on missing config | `calculation.py:771-777`; WD-21 | 🟢 Confirmed design principle |

## B. LEAVE POLICIES (LEAVE-POL-001…037)

| Policy ID | Policy Name | Purpose | Source | Current Status |
|---|---|---|---|---|
| LEAVE-POL-001 | Leave type identity/config | `is_paid_default`, `requires_balance`, `is_comp_off`, `statutory_category` | `leave/models.py:37-66` | 🔧 Functional |
| LEAVE-POL-002 | Probation restriction on application | `allowed_during_probation` blocks submission if `Employee.status=PROBATION` | `models.py:162`; `service.py:1955-1960` | 🔧 Functional (LD-18) |
| LEAVE-POL-003 | Probation restriction on accrual | `accrue_during_probation` skips monthly accrual for PROBATION employees | `models.py:163`; `service.py:1397` | 🔧 Functional |
| LEAVE-POL-004 | On-behalf submission permissions | `allow_employee_request`/`allow_manager_request_on_behalf`/`allow_hr_request_on_behalf` | `models.py:128-130`; `service.py:1962-1973` | 🔧 Functional |
| LEAVE-POL-005 | Self-approval block | Unconditional, no policy escape hatch | `service.py:2190-2192` | 🟢 Confirmed (mirrors Attendance WD-28 decision 5) |
| LEAVE-POL-006 | Leave combination rule | Blocks overlap between two specific leave *types* when an explicit `allowed=False` rule exists | `service.py:1907-1927`; LD-16 | 🔧 Functional; absence of a rule = allowed |
| LEAVE-POL-007 | Balance = live ledger sum | No stored balance column; `SUM(leave_ledger.amount)` | `models.py:189-205`; ADR-0004 | 🟢 Confirmed architecture (ADR-0004) |
| LEAVE-POL-008 | Monthly accrual + proration | Prorated by worked days / total days in month | `service.py:1311-1437` | 🔧 Functional, idempotent |
| LEAVE-POL-009 | Yearly accrual (no proration) + leave-year setting | CALENDAR/FINANCIAL/CUSTOM/ANNIVERSARY | `models.py:413-430`; `year.py`; `service.py:1439-1569` | 🔧 Functional (LD-20/21); flat credit, no proration by design |
| LEAVE-POL-010 | Carry-forward cap | `max_carry_forward_days`; `NULL`=unlimited, `0`=use-it-or-lose-it | `service.py:1506-1509`; LD-06 decision 2 | 🟢 Confirmed |
| LEAVE-POL-011 | Encashment | `encashment_allowed`, `max_encashment_days`, `min_balance_after_encashment` | `service.py:1152-1245`; LD-19 | 🔧 Functional; `encashment_frequency`/`encashment_calculation_basis` stored but never enforced (🔵 GAP, no leave-year-linked frequency check, no Payroll module yet) |
| LEAVE-POL-012 | Comp-off credit | Converts `OvertimeRecord.comp_off_minutes` → leave days via `comp_off_day_length_minutes` | `service.py:1572-1652`; LD-07/LD-14 | 🔧 Functional; skips entirely (never guesses) if day-length unconfigured |
| LEAVE-POL-013 | Comp-off expiry | Balance-aware; never drives balance negative; no FIFO lot-tracking | `service.py:1643-1652`; LD-14 decision 3 | 🔧 Functional, documented simplification |
| LEAVE-POL-014 | Statutory minimum enforcement | Blocks *publishing* a policy version below the strictest configured floor | `service.py:899-932`; LD-22 | 🔧 Functional; enforced at publish time only, not at application/accrual time |
| LEAVE-POL-015 | Negative balance — never allowed | Hard-capped at current balance, no exceptions | `service.py:2022-2024`; LD-06 | 🟢 Confirmed; `allow_negative_balance` field exists but is dormant (🔵 GAP — never read anywhere) |
| LEAVE-POL-016 | Reserved/pending balance | `reserve_balance_on_submission` — optionally counts other SUBMITTED apps against balance at submit time | `models.py:149-152`; `service.py:2014-2024`; LD-15 | 🔧 Functional, default `False` |
| LEAVE-POL-017 | Overlap / multiple requests (same type) | No generic same-type overlap block found | grep of `service.py` | 🔵 GAP — only cross-type combination rule (LEAVE-POL-006) blocks overlap; two overlapping same-type requests are not structurally prevented |
| LEAVE-POL-018 | Half-day leave mechanics | Only valid for single-day applications; gated by `half_day_allowed` | `schemas.py:510-516`; `service.py:1975-1976` | 🔧 Functional |
| LEAVE-POL-019 | Holiday/weekly-off interaction + sandwich rule | WORKING/SPECIAL_WORKING consume leave; WEEKLY_OFF/HOLIDAY/SHUTDOWN don't, unless sandwiched | `service.py:1814-1878`; `sandwich_rule_enabled` default `True` | 🔧 Functional; sandwich look-back is same-application-only, no cross-application look-back |
| LEAVE-POL-020 | Backdated leave window | `max_backdated_days`; `NULL`=no limit | `service.py:1978-1981` | 🔧 Functional |
| LEAVE-POL-021 | Future leave | No restriction — forward-dated leave is the expected case | `service.py:1894-1896` | 🟢 Confirmed by design (explicit contrast with Regularization) |
| LEAVE-POL-022 | Monthly request cap | `max_requests_per_month`, excludes CANCELLED | `service.py:1989-1995` | 🔧 Functional |
| LEAVE-POL-023 | Reason/attachment required | `reason_required`/`attachment_required` | `service.py:1983-1986` | 🔧 Functional |
| LEAVE-POL-024 | Cancellation | Submitter-only; SUBMITTED→CANCELLED (no side effect) or APPROVED→CANCELLED (reverses ledger + projection) | `service.py:2488-2628`; LD-13 | 🔧 Functional |
| LEAVE-POL-025 | Rejection | Terminal at any stage; no ledger/balance effect | `service.py:2237-2294` | 🔧 Functional |
| LEAVE-POL-026 | Withdrawal / modification of an application | No separate withdraw verb; no amend/modify endpoint | grep of `router.py`/`service.py` | 🔵 GAP — cancellation is the only reversal mechanism; "extension" use case handled by submitting a new adjacent application (LD-17 decision 4) |
| LEAVE-POL-027 | Multi-level approval chain | AUTO / MANAGER / MANAGER_THEN_HR / MANAGER_THEN_HOD_THEN_HR / HR | `approval_chain.py:18-23`; LD-23 | 🔧 Functional |
| LEAVE-POL-028 | Approver resolution-failure fallback | Unresolved identity stage dropped; all-unresolved falls back to single HR stage | `approval_chain.py:44-46` | 🟢 Confirmed (mirrors Attendance's identical pattern) |
| LEAVE-POL-029 | HOD self-head loop guard | Applicant who is their own department head is treated as unresolved (never routed to self) | `service.py:2057-2061` | 🟢 Confirmed |
| LEAVE-POL-030 | Delegation of approval authority | No delegate/out-of-office/acting-manager mechanism | grep of `approval_chain.py`/`service.py`/`router.py`/`models.py` | 🔵 GAP — not present at all |
| LEAVE-POL-031 | Leave policy effective dating / versioning | `effective_from`/`effective_to`, insert-new/close-previous | `models.py:123-124`; `service.py:934-1028` | 🔧 Functional |
| LEAVE-POL-032 | Policy version snapshot at submission | `LeaveApplication.leave_policy_version_id` fixed at submit time | `models.py:248-250` | 🟢 Confirmed — later policy edits never retroactively affect an in-flight application |
| LEAVE-POL-033 | Leave→Attendance projection sync | `_apply_approval`/`_reverse_approval` call Attendance's `LeaveProjectionService.sync()`/`cancel()` in the same transaction | `service.py:2401-2482, 2569-2628`; LD-12/LD-13 | 🔧 Functional — see Attendance–Leave Interaction Matrix |
| LEAVE-POL-034 | No leave-specific period lock | Backdated/leave-after-lock handling entirely borrowed from Attendance's period-close guard | grep of leave module for lock/finalize | 🔵 GAP — no leave-side arrears/override path; only remedy is a full Attendance period reopen (PD-LOCK-2, still open) |
| LEAVE-POL-035 | Gender restriction on leave type | — | grep of `models.py`/`service.py` | 🔵 NOT IMPLEMENTED — no field or check exists anywhere; Maternity/Paternity distinguished only by `statutory_category` string, never by employee gender |
| LEAVE-POL-036 | Tenure (minimum service) restriction | — | grep of `models.py`/`service.py` | 🔵 NOT IMPLEMENTED — no minimum-service-days gate anywhere |
| LEAVE-POL-037 | Department/designation/grade/location eligibility | Not a distinct Leave-owned field — inherited entirely from which `LeavePolicyVersion` resolves via `PolicyAssignment` scope walk | `service.py:1932-1941` | 🔧 Functional only via the shared 8-level resolution engine (ATT-POL-049); no separate allow-list on `LeaveType`/`LeavePolicyVersion` itself |

## C. SHARED / CROSS-MODULE POLICIES (SHARED-POL-001…004)

| Policy ID | Policy Name | Purpose | Source | Current Status |
|---|---|---|---|---|
| SHARED-POL-001 | 8-level policy-assignment precedence engine | Generic "most specific wins" scope walk reused by Attendance and Leave policy resolution | `organisation/calendar_resolution.py:48-57, 251-315`; used at `attendance/resolution.py:38-118` and `leave/service.py:1374-1385,1936-1941` | 🟢 Confirmed shared architecture |
| SHARED-POL-002 | Employee lifecycle: PROBATION→ACTIVE confirmation | `EmployeeService.confirm_employee`; single explicit transition, no auto-confirm/reminder | `employee/service.py:428-498` | 🔧 Functional; read directly by Leave (LEAVE-POL-002/003); **not read at all by Attendance**, which derives its own `population_status` from `Employment` dates instead |
| SHARED-POL-003 | Effective-dated modelling pattern | Insert-new/close-previous, never mutate a published row's core fields | ADR-0003; used by `AttendancePolicyVersion`, `OvertimePolicyVersion`, `RegularizationPolicyVersion`, `LeavePolicyVersion`, `ShiftVersion`, `PolicyAssignment`, `EmployeeAssignment`, `EmployeeCompensation`, `EmployeeStatutory` | 🟢 Confirmed uniform architecture (one documented exception: `EmployeeBank`, deliberately not closed on exit) |
| SHARED-POL-004 | Joining date / last working day as accrual & population anchors | `Employment.joining_date`/`last_working_day` read by both modules for proration/anchoring | `attendance/service.py:4744-4746`; `leave/service.py:1365-1367,1471-1474`; `leave/year.py:43-76` | 🔧 Functional |

## D. Documentation-currency note (applies across this inventory)

🟠 **CONFLICT (documentation age, not code defect):** The entire `docs/business-rules/attendance/` and `docs/business-rules/ATTENDANCE_V1_*` set, plus most of `docs/modules/attendance*/`, describe Leave as **"not implemented" / a future module**, and describe `LeaveDayProjection` as Attendance's own temporary stand-in "until a real Leave module ships" (`models.py:977-984`, quoted verbatim in multiple docs). A real Leave module now exists and satisfies exactly the resolution path `WD-31`/`PD-LEAVE-1` left open: **Leave became the writer of the same mirror table** (LEAVE-POL-033), rather than replacing it. This is a **correct, already-anticipated outcome**, not a functional bug — but every attendance business-rule document that still says "Leave is a future module" is now stale and should be revised for accuracy before client sign-off. No document was found that records this resolution from the Attendance side (only from the Leave side, via `LEAVE_DECISION_LOG.md` LD-01).

---

## 2. Master Policy Precedence Matrix


**Status:** Audit document, current-state as of 2026-09-07. Cross-refs use IDs from [`MASTER_POLICY_INVENTORY.md`](./MASTER_POLICY_INVENTORY.md).

---

## 1. Policy vs Policy conflicts

| Conflict ID | Policy A | Policy B | Current Winner | Intended Winner | Reason | Status |
|---|---|---|---|---|---|---|
| CONF-001 | Holiday (ATT-POL-039) | Weekly Off (ATT-POL-042) | Weekly Off | Weekly Off | Hard holiday landing on a weekly-off day **stays classified as weekly-off**, with `holiday_on_weekly_off` flag raised — holiday cannot promote/override the WO classification | `02_ATTENDANCE_PRECEDENCE_MATRIX.md` §2; WD-05 | 🟢 Confirmed |
| CONF-002 | Holiday/Weekly-off (calendar) | Shift (`operates_on_holiday`/`operates_on_weekly_off`) | Shift, if flagged to operate | Shift, if flagged to operate | A shift explicitly marked to operate on a holiday/WO overrides the calendar's NOT_EXPECTED default | `calculation.py:814-827` | 🟢 Confirmed |
| CONF-003 | Weekly Off (calendar) | Roster (`is_week_off_override`) | Roster | Roster | A published roster week-off override wins even when the calendar says WORKING — "a schedule fact… must win even when the calendar itself says WORKING" | `calculation.py:779-794` | 🟢 Confirmed |
| CONF-004 | Roster shift assignment | Employee's base `EmployeeAssignment.shift_id` | Roster (for the actual worked schedule) but **not** for SHIFT-scoped policy resolution | Architecture text says roster should also apply to SHIFT-scoped policy | `02` §1,§3,§10 — explicitly named divergence; `ATTENDANCE_CLIENT_RULES_AND_SCENARIOS.md` CD-006 | Architecture doc: policy resolution should include roster shift. Code: `resolve_policy_assignment` SHIFT scope only reads `EmployeeAssignment.shift_id`, never the day's roster override | 🟠 **DOCUMENTATION/IMPLEMENTATION CONFLICT** — still open as of the newest decision log entries |
| CONF-005 | Employee-specific policy assignment | Organization/company-level policy assignment | Employee (most specific) | Employee (most specific) | 8-level precedence walk (SHARED-POL-001): EMPLOYEE beats every broader scope | `calendar_resolution.py:48-57` | 🟢 Confirmed |
| CONF-006 | Branch policy | Organization (company) policy | Branch (more specific) | Branch (more specific) | Same 8-level walk | `calendar_resolution.py:48-57` | 🟢 Confirmed |
| CONF-007 | Shift-scoped attendance policy | Attendance-policy at broader scope | Whichever resolves first in the 8-level order for that `policy_kind` | Same | Generic, `policy_kind`-parameterized resolution | `resolution.py:38-118` | 🟢 Confirmed |
| CONF-008 | Approved regularization (synthetic punches) | Original raw punches | Both persist; regularization **adds** new `Punch` rows (`source=REGULARIZATION`), original punches are never deleted/edited | Same | Punches are immutable/append-only (WD-11); a regularization is never a punch-edit | `models.py:428-445`; `service.py:4104-4133` | 🟢 Confirmed |
| CONF-009 | Leave (full-day, approved) | Overtime detected from punches | No rule — they coexist as independent facts | Undecided | `_apply_leave_overlay` does not clear `ot_minutes_detected`; leave and OT are computed on separate passes with no interaction rule | `calculation.py` overlay code note; `ATTENDANCE_OVERRIDE_MATRIX.md` item 1; `ATTENDANCE_CLIENT_RULES_AND_SCENARIOS.md` CD-002 | ⚠️ **POLICY DECISION REQUIRED** |
| CONF-010 | Holiday | Overtime eligibility/day-class | Holiday sets `day_class=HOLIDAY` for OT rate classification | Same | `classify_ot_day` (`calculation.py:679-693`) | 🟢 Confirmed (classification only, no automatic OT grant/denial tied to holiday) |
| CONF-011 | Weekly-off | Overtime eligibility/day-class | Weekly-off sets `day_class=WEEKLY_OFF` | Same | `classify_ot_day` | 🟢 Confirmed |
| CONF-012 | Night OT | Normal OT | No real distinction currently — "night" always derives from `shift.is_cross_midnight`, never a clock-time window check | Configured `night_window_start/end` should independently classify OT worked in a night window regardless of shift crossing midnight | `models.py:267-269` vs `calculation.py:1237,1388,1405` | 🔵 **IMPLEMENTATION GAP** |
| CONF-013 | OT cap (daily/weekly/monthly) | OT eligibility | Eligibility gates detection first; caps then clamp the detected amount — no conflict, sequential | Same | `calculation.py:696-739` then `:723-728`; `service.py:3009-3038` | 🟢 Confirmed |
| CONF-014 | Period lock | Regularization submission/approval | Period lock wins unconditionally | Same | `_ensure_date_open` blocks regardless of `blocked_when_locked` policy value | `service.py:3491-3496` | 🟢 Confirmed |
| CONF-015 | Period lock | Leave application approval (projection sync) | Period lock wins — approval transaction rolls back entirely | Same | `LeaveProjectionService.sync()` refuses a CLOSED period; failure rolls back the *whole* leave-approval transaction | `attendance/service.py:5252-5254`; `leave/service.py` LD-12 | 🟢 Confirmed — see Attendance–Leave Interaction Matrix |
| CONF-016 | Historical attendance record (already calculated) | New attendance/OT/regularization policy version published later | Old record stands until an explicit unlocked recompute re-resolves versions by date; **locked days never change** | Same | `models.py:480-484`; policy publish requires `effective_from` strictly after current version | 🟢 Confirmed |
| CONF-017 | Two overlapping `PolicyAssignment` rows at the same scope tier | — | Undefined — not defended against structurally | Should be structurally impossible or deterministically resolved | `ATTENDANCE_OVERRIDE_MATRIX.md` item 4; CD-026 | ⚠️ **POLICY DECISION REQUIRED** (also a 🔵 implementation gap — no DB constraint prevents it) |
| CONF-018 | Employee-specific leave policy assignment | Organization-level leave policy | Employee (most specific), same shared engine | Same | SHARED-POL-001, reused verbatim by Leave | 🟢 Confirmed |
| CONF-019 | Leave-type policy version | Company-wide default leave rules | There is no separate "global leave policy" layer distinct from `LeavePolicyVersion` — each leave type's policy is independently resolved per scope | N/A — no such conflict exists in the current model | `leave/models.py:99-181` | 🟢 Confirmed (not a real conflict — no global-vs-type-level policy layer exists to conflict) |
| CONF-020 | Eligibility restriction (e.g. probation block) | Available balance (sufficient funds) | Eligibility checked and can block **before** balance is even evaluated in some paths, but code order is: policy resolution → on-behalf/self-approval gates → probation check → half-day/reason/backdating/monthly-limit checks → combination-rule check → balance check (last) | Undetermined whether this ordering is an intentional business rule or incidental code structure | `service.py:1932-2024` (submit() ordering) | ⚠️ **POLICY DECISION REQUIRED** — the *order* of eligibility checks is implementation detail, not a documented business rule |
| CONF-021 | Probation restriction | Leave entitlement/accrual already granted | If `accrue_during_probation=False`, no ledger rows are written during probation — balance stays literally zero, not merely "restricted access to an existing balance" | Same | `service.py:1397` | 🟢 Confirmed |
| CONF-022 | Negative-balance permission | Balance limit / insufficient-balance check | Balance limit always wins — negative balance is unconditionally blocked; `allow_negative_balance` field is dormant (never read) | Undecided whether advance leave should ever be supported | `service.py:2022-2024`; LD-06 decision 4 | 🟢 Confirmed current behaviour; ⚠️ future-feature decision remains open |
| CONF-023 | Carry-forward policy | Expiry/lapse policy | Carry-forward cap enforced once, at year-end sweep; anything above `max_carry_forward_days` is forfeited (a `CARRY_FORWARD` ledger entry with negative amount) — no separate expiry concept exists beyond this cap | Same | `service.py:1506-1509` | 🟢 Confirmed — "carry-forward cap" and "expiry" are the same mechanism, not two competing policies |
| CONF-024 | Carry-forward cap | Existing balance at year-end | Cap wins — excess above cap is force-forfeited regardless of how the balance was accumulated | Same | `service.py:1506-1509` | 🟢 Confirmed |
| CONF-025 | Leave overlap (same type) | Multiple leave requests | No rule currently blocks two overlapping applications of the **same** leave type | Undetermined | grep of `service.py` — no same-type overlap check found | ⚠️ **POLICY DECISION REQUIRED** / 🔵 gap |
| CONF-026 | Leave cancellation (post-approval) | Attendance already processed for those dates | Cancellation succeeds only if the attendance period is still OPEN; if CLOSED, both the ledger reversal and the projection cancellation fail and the whole cancellation transaction rolls back | Same | `leave/service.py:2569-2628`; `attendance/service.py` period-closed guard | 🟢 Confirmed — see Attendance–Leave Interaction Matrix |
| CONF-027 | Approved leave | Attendance punches on the same date | `work_on_leave_behaviour` decides: default `KEEP_LEAVE` → leave wins; `PRESENT_CANCEL_LEAVE_HINT` → punches win for status, but leave application itself is never auto-cancelled, only flagged | Same | `calculation.py:878-935` | 🟢 Confirmed — see Attendance–Leave Interaction Matrix (PP-001) |
| CONF-028 | Holiday (calendar) | Leave | Approved full-day leave outranks calendar NOT_EXPECTED (i.e., leave "wins" the attendance-status slot even on a day the calendar would otherwise mark as holiday/WO-not-expected), but `calendar_day_type` itself is left untouched | Same | `calculation.py:869-876`; confirmed by `test_leave_overrides_roster_week_off_not_expected` | 🟢 Confirmed |
| CONF-029 | Weekly-off (calendar) | Leave | Same as CONF-028 — leave overlay outranks NOT_EXPECTED regardless of whether the NOT_EXPECTED came from holiday or weekly-off | Same | Same as above | 🟢 Confirmed |
| CONF-030 | Sandwich rule | Holiday/weekly-off exclusion (at leave-submission time) | Sandwich rule can pull an otherwise-excluded holiday/WO day back into consumption if bracketed by leave-consuming days within the same application | Same | `service.py:1826-1829,1847-1853` | 🟢 Confirmed; explicitly same-application-only, no cross-application look-back (⚠️ open question: should the sandwich look-back span multiple separately-submitted applications?) |

## 2. Policy vs Override conflicts

| Conflict ID | Policy | Override | Which wins | Reason | Status |
|---|---|---|---|---|---|
| CONF-031 | Attendance regularization policy (allowed types, approval chain) | Manager/HR approval action | Approval action executes what the policy already scoped — approver cannot approve a type outside the policy's `allowed_types`, cannot skip a configured chain stage | `service.py:3606-3702` | 🟢 Confirmed |
| CONF-032 | Overtime policy caps | HR/Manager OT approval | Approval only accepts/rejects the already-capped detected amount; approver cannot approve OT above the configured cap through this workflow | `calculation.py:723-728` (cap applied before the record reaches approval) | 🟢 Confirmed |
| CONF-033 | `incomplete_at_lock_behaviour=KEEP_INCOMPLETE` | HR finalize action | Policy wins — finalize is **blocked** entirely, HR cannot force-close over an unresolved INCOMPLETE day under this policy | `service.py:4781-4818` | 🟢 Confirmed |
| CONF-034 | Leave `allowed_during_probation=False` | Manager/HR on-behalf submission | Policy wins — the probation check applies regardless of who submits (self, manager-on-behalf, or HR-on-behalf) | `service.py:1955-1960` applies before the on-behalf branch resolves any different treatment | 🟢 Confirmed |
| CONF-035 | Leave statutory minimum | HR publishing a leave policy version | Policy (statutory floor) wins — publish is blocked below the strictest configured minimum; no override path exists in code | `service.py:899-932` | 🟢 Confirmed — no admin override exists; only remedy is raising the accrual rate or removing/adjusting the `StatutoryLeaveMinimum` row itself |
| CONF-036 | `blocked_when_locked` regularization policy flag | Manager/HR wanting to submit a correction on a locked day | Neither — the period-level lock (`_ensure_date_open`) makes this policy flag moot; it can never be "true" in a way that changes the unconditional lock behaviour | `service.py:3491-3496` (unconditional) vs `:3580-3585` (conditional, effectively dead) | 🟠 CONFLICT — the flag's existence implies a conditional override that doesn't actually function as one |

## 3. Override vs Override conflicts

| Override A | Override B | Which Wins? | Why? | Defined? |
|---|---|---|---|---|
| Employee-specific policy assignment | HR manual override (e.g. correcting a record) | HR manual actions (regularization approval, OT approval, manual roster/policy edits) operate independently of which policy scope resolved — they are transaction-level actions, not competing policy assignments | These are different kinds of "override" (policy-resolution vs transaction-action) and don't actually conflict in the current model | 🟢 Not a real conflict — no code path lets a policy assignment itself be "overridden" other than being superseded by a more specific scope or a later effective-dated version |
| Approved regularization | Manual attendance correction | No separate "manual correction" mechanism exists distinct from regularization — all corrections to punches/status flow through the regularization workflow (`_apply_correction`) | Regularization is the only correction path in code | 🔵 GAP relative to the audit's own framework — the spec's "Manual correction vs Automatic recalculation" scenario has no distinct manual-correction feature to test against |
| Approved leave | Attendance calculation | Governed entirely by `work_on_leave_behaviour` (CONF-027) — not a distinct override-vs-override case beyond the policy conflict already listed | See CONF-027 | 🟢 Confirmed |
| Approved leave cancellation | Period lock | Period lock wins — cancellation transaction rolls back if the attendance period is CLOSED (CONF-026) | Same | 🟢 Confirmed |
| Manager approval (regularization/leave) | HR rejection at a later stage | HR's later-stage decision is final for that request — a `MANAGER_THEN_HR` chain's manager approval only advances the stage, HR still independently approves/rejects; HR rejecting after manager approval **is a real, supported path** (rejection is terminal from any stage) | `regularization: service.py:3933-3946`; `leave: service.py:2237-2294` | 🟢 Confirmed |
| Existing approval (regularization/leave/OT) | Policy change after approval | Existing approvals are never retroactively affected — regularization/OT records reference the version resolved at the time; leave applications snapshot `leave_policy_version_id` at submission (LEAVE-POL-032) | `attendance/models.py:480-484`; `leave/models.py:248-250` | 🟢 Confirmed |
| Manual correction (via regularization) | Automatic recalculation (`calculate()`) | A regularization's approval *triggers* the automatic recalculation as its final step — they are sequential, not competing (`_apply_correction` → `calculate()` in the same transaction) | `service.py:4135-4142` | 🟢 Confirmed — not a real conflict |
| Locked record | New policy (published after lock) | Locked record wins — historical, locked `AttendanceDay` rows never recompute even if a new policy version publishes; only an explicit reopen + manual recompute can change them | `models.py:480-484`; period lock semantics | 🟢 Confirmed |
| Reopened record | Historical snapshot (`AttendancePeriodSummary`) | Reopening does **not** restore or recompute anything automatically — the old frozen summary stands until a fresh finalize regenerates it; in the interim, `AttendanceDay` rows are mutable again but may be inconsistent with the still-frozen summary | `service.py:5164-5169` ("a day made mutable again is only actually changed by a later, ordinary calculate()… call") | 🔵 IMPLEMENTATION GAP — no automatic reconciliation, no "reopen checklist" enforced by the system; ND-08/CD-016 flags this as a manual-process risk |

## 4. Cross-references

- Attendance-only precedence detail: [`ATTENDANCE_POLICY_PRECEDENCE.md`](./ATTENDANCE_POLICY_PRECEDENCE.md)
- Leave-only precedence detail: [`LEAVE_POLICY_PRECEDENCE.md`](./LEAVE_POLICY_PRECEDENCE.md)
- Attendance↔Leave specific scenarios: [`ATTENDANCE_LEAVE_INTERACTION_MATRIX.md`](./ATTENDANCE_LEAVE_INTERACTION_MATRIX.md)
- Full override authority table: [`POLICY_OVERRIDE_MATRIX.md`](./POLICY_OVERRIDE_MATRIX.md)
- Every open item above (⚠️/🟠/🔵) is repeated with a decision ID in [`MASTER_POLICY_DECISION_REGISTER.md`](./MASTER_POLICY_DECISION_REGISTER.md).

---

## 3. Attendance Policy Precedence


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

---

## 4. Leave Policy Precedence


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

---

## 5. Attendance–Leave Interaction Matrix


**Status:** Audit document. This is the single most load-bearing document in the audit — it answers "what wins when Attendance and Leave both have an opinion about the same day." All rows are backed by either source code or a passing integration test; no row was inferred without evidence.

**Primary evidence:** `attendance/calculation.py` `_apply_leave_overlay` (L861-935) and `_apply_on_duty_overlay`; `leave/service.py` `_apply_approval`/`_reverse_approval`; `attendance/tests/integration/modules/attendance/test_leave_projection.py` (the definitive cross-module test file).

## The integration mechanism (context for every row below)

Leave and Attendance are separate modules connected by exactly one seam: `LeaveDayProjection`, an **Attendance-owned** table. Leave never writes attendance tables directly and Attendance never writes leave tables directly (`WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §21: *"Attendance may not write leave tables. Leave may not write attendance tables."*). On final-stage approval of a leave application, `LeaveApplicationService._apply_approval` calls Attendance's `LeaveProjectionService.sync()` **inside the same database transaction** as the approval write; on post-approval cancellation, `_reverse_approval` calls `LeaveProjectionService.cancel()` the same way. If Attendance refuses the sync/cancel (e.g., period closed), the **entire leave-side transaction rolls back** — the leave application never ends up partially approved (LD-12).

## Attendance–Leave Interaction Matrix

| Scenario | Attendance Rule | Leave Rule | Current Behaviour | Intended Behaviour | Winner | Decision Status |
|---|---|---|---|---|---|---|
| **Leave vs. Attendance punches — full day** | `work_on_leave_behaviour` policy (default `KEEP_LEAVE`) | Approved full-day leave, `is_paid` per leave type | Default: `attendance_status` stays `LEAVE` regardless of a full day of punches; late/early are zeroed. Policy override `PRESENT_CANCEL_LEAVE_HINT`: `attendance_status` becomes `PRESENT` (punch-derived), and `work_on_leave_flagged=True` is raised for Leave to see — **Attendance never cancels the leave application itself** | Documented and matches architecture §19.3/19.4 exactly | **Leave (by default)** | 🟢 Confirmed — see also PP-001 in scenario catalog |
| **Leave vs. Absent (leave approved after attendance already computed the day as ABSENT)** | Day was previously computed as ABSENT from missing punches | Leave approval syncs a projection and triggers a recompute of that date | Recompute re-applies the leave overlay on top of whatever the punch-derived pass produces; `attendance_status` becomes `LEAVE` (or `HALF_DAY` for a half-day leave) | Same | **Leave** | 🟢 Confirmed by code path (overlay applies to the day regardless of what triggered the recompute) — no dedicated test found for the specific "was ABSENT, then leave approved" ordering, but the mechanism (full recompute) is generic and covers it |
| **Leave vs. Half-day attendance** | Punch-derived worked minutes | Half-day leave (`fraction=0.50`) | Half-day unpaid leave + full-day punches → `attendance_status=HALF_DAY`, `paid_day_fraction=0.50` (from work), `lop_fraction=0.50` (from unpaid leave half). Multiple half-day projections on the same date sum their fractions. Half-day leave with **no punches at all** → `attendance_status=LEAVE`, not `HALF_DAY` (`has_work=False`) | Matches architecture worked example | **Combined** — worked half stays paid/present-derived, leave half stays LOP/leave-derived | 🟢 Confirmed by `test_half_day_unpaid_leave_with_full_day_punches`, `test_multiple_half_day_projections_sum_to_full_day` |
| **Leave vs. Late Arrival** | Late-arrival bands | `KEEP_LEAVE` zeroes `late_minutes` when leave wins the day | Under default `KEEP_LEAVE`, late/early are explicitly zeroed once the day is classified LEAVE. Under `PRESENT_CANCEL_LEAVE_HINT`, punch-derived lateness is preserved since punches determine status | Same | **Leave overrides late (default policy)** | 🟢 Confirmed (`calculation.py:878-881, 905-920`) |
| **Leave vs. Early Departure** | Early-departure bands | Same `work_on_leave_behaviour` switch | Half-day leave does not have a distinct "early departure" override rule beyond the general half-day fraction mechanics above — early-departure bands only apply to the punch-derived portion of a mixed day | Not separately documented as its own rule | **Half-day leave does not specifically suppress early-departure classification on the worked portion** | 🔵 IMPLEMENTATION GAP / not explicitly tested — inferred only from the general overlay mechanics, no dedicated test found for "half-day leave AM + early departure PM" combination |
| **Leave vs. Overtime** | OT is detected from punches independent of the leave overlay pass | No leave-side OT rule | `_apply_leave_overlay` does **not** clear `ot_minutes_detected` — OT and leave are computed as two independent facts that can both be true for the same day | No rule exists anywhere in either module | **No rule — undefined interaction** | ⚠️ **POLICY DECISION REQUIRED** (also flagged as CONF-009 in the precedence matrix, and CD-002 in the pre-existing client decision register) |
| **Leave vs. Holiday** | Holiday sets calendar `day_type=HOLIDAY` (`calendar_day_type` field, untouched by leave) | Leave-submission-time: HOLIDAY days don't consume leave balance by default | At **application time**, a holiday inside the requested range is skipped (not deducted) unless the sandwich rule pulls it in. At **attendance-calculation time**, if leave is somehow active on a day the calendar marks HOLIDAY/NOT_EXPECTED, leave still wins the `attendance_status` slot, but `calendar_day_type` stays HOLIDAY (never overwritten) | Consistent with architecture | **Leave does not consume balance for a holiday date** (submission); **leave still wins attendance-status display** if a projection somehow exists on a holiday | 🟢 Confirmed — `test_leave_overrides_roster_week_off_not_expected` (same mechanism applies to holidays) |
| **Leave vs. Weekly Off** | Weekly-off sets calendar `day_type=WEEKLY_OFF` | Same non-consumption-by-default rule as holidays, same sandwich-rule exception | Same as Holiday row above | Same | Same as Holiday row | 🟢 Confirmed |
| **Leave vs. Sandwich rule** | N/A (Attendance has no sandwich concept) | `sandwich_rule_enabled` (default `True`) pulls a bracketed non-consuming day (weekly-off/holiday) into consumption if bracketed by leave-consuming days | Confirmed by test: Fri→Mon bracketing a Sunday → Sunday included, `is_sandwich_generated=True`, `total_days=4.00`; disabling the flag → Sunday excluded, `total_days=3.00` | Same, but scope is same-application-only | **Sandwich rule is Leave-owned, evaluated only within one application's date range** — no cross-application look-back | 🟢 Confirmed by `test_submit_sandwich_rule_generates_weekend_day` / `test_submit_without_sandwich_rule_skips_weekly_off`; ⚠️ whether sandwich look-back *should* span multiple separately-submitted applications is an open question |
| **Leave Approval vs. Attendance Period Lock** | `_ensure_date_open` refuses any mutation once `AttendancePeriod.status=CLOSED` | Final-stage approval calls `LeaveProjectionService.sync()` inside the same DB transaction as the approval write | If the attendance period for the leave date is CLOSED, `sync()` raises `ATTENDANCE_PERIOD_CLOSED`; because this happens **inside the same transaction as the leave approval**, the entire approval fails — the leave application is **not** left partially approved, it stays `SUBMITTED` | Documented as intentional (LD-12: "no partial approval, no partially-synced application") | **Attendance period lock wins — blocks leave approval outright** | 🟢 Confirmed by `test_sync_refused_when_period_closed`; 🔵 **IMPLEMENTATION GAP** — there is no arrears/override mechanism; the only remedy is a full attendance-period reopen (PD-LOCK-2, still open) |
| **Leave Cancellation vs. Attendance Finalization** | Same `_ensure_date_open` guard applies to `LeaveProjectionService.cancel()` | Post-approval cancellation calls `_reverse_approval`, which credits back the ledger and calls `cancel()` on the projection | If the period is CLOSED, cancellation is refused the same way as sync, and the whole cancellation transaction (ledger credit-back + projection cancel) rolls back — the leave application stays `APPROVED`, balance stays debited | Symmetric with the approval-side rule, explicitly documented in the test docstring ("§21 — Leave approved after payroll lock… default refuse") | **Attendance period lock wins — blocks leave cancellation too** | 🟢 Confirmed by `test_cancel_refused_when_period_closed` |
| **Leave projection cancellation (period still open) vs. attendance recompute** | Recompute re-evaluates the day from scratch each time | Cancelling an approved projection removes it from the "active" set `_apply_leave_overlay` reads | Cancelling a leave projection on a day with real punches **reverts** `attendance_status` back to the punch-derived outcome (e.g. `PRESENT`) — proves the overlay is dynamically recomputed each time, never baked in | Same | **Whichever facts are currently active win — dynamic, not cached** | 🟢 Confirmed by `test_cancel_projection_reverts_attendance_to_punch_derived_outcome` |
| **Re-syncing the same leave application** | N/A | Re-sync with the same `leave_application_id` | Updates the same projection row in place — no duplicate rows; flipping `is_paid` correctly flips `paid_day_fraction`/`lop_fraction` | Same | N/A — idempotent update | 🟢 Confirmed by `test_resync_same_leave_application_id_updates_in_place` |
| **Multiple leave projections overlapping on one date** | N/A | `LeaveProjectionService.sync()` validates that active fractions for one employee-date sum to ≤ 1.00 | Overlapping leave fractions that would exceed 1.00 on the same date → rejected with `LEAVE_PROJECTION_OVERLAP` (409) | Same | N/A — fail-closed | 🟢 Confirmed |
| **Comp-off (OT fact) vs. Leave balance** | Attendance emits `OvertimeRecord.comp_off_minutes`/`comp_off_expiry_date` as read-only facts once OT is approved with `comp_off_instead_of_pay=True` | Leave's `LeaveCompOffService` reads these facts (never writes Attendance tables) and converts minutes→days via `comp_off_day_length_minutes` | Functional automated sweep; skips crediting entirely (never guesses) if `comp_off_day_length_minutes` is unconfigured, or if no `LeaveType.is_comp_off=True` exists | Same, LD-07/LD-14 | **Attendance emits facts; Leave decides and owns the balance consequence** | 🟢 Confirmed — clean one-directional read seam, no conflict |
| **Employee lifecycle (PROBATION) vs. Attendance population status** | Attendance derives `population_status` (`NOT_JOINED`/`ACTIVE`/`EXITED`) purely from `Employment.joining_date`/`last_working_day` — **never reads `Employee.status`** | Leave reads `Employee.status` directly for probation eligibility (LEAVE-POL-002/003) | An employee in `PROBATION` is `population_status=ACTIVE` for Attendance purposes (fully subject to attendance calculation) while simultaneously restricted from leave application/accrual under Leave's own probation check | Not stated as intentional anywhere, but consistent with each module owning a narrower, purpose-specific status signal | **No conflict in practice — the two modules ask different questions of different fields** | 🟢 Confirmed, but 🟠 worth flagging as a **documentation gap**: no document states explicitly that Attendance and Leave use two independent, non-synchronized notions of "is this employee active" |
| **Backdated leave vs. Locked attendance period** | Period lock (`_ensure_date_open`) | `max_backdated_days` only limits how far in the past a leave *application* can start — it does not check attendance-period lock state at submission time | A backdated leave application can be **submitted** for a date whose attendance period is already closed (submission itself does not check attendance lock) — the lock is only enforced at **approval** time, when the projection sync is attempted | Undocumented whether submission should also fail closed | **Submission succeeds even for a locked date; approval fails at the lock check** | 🔵 IMPLEMENTATION GAP — this creates a confusing UX where an application can sit `SUBMITTED` indefinitely, only failing when someone finally tries to approve it; no test found that submission itself checks attendance-period state |

## Notable non-interactions (explicitly checked, no rule found)

- **Leave does not affect `calendar_day_type`.** The leave overlay changes `attendance_status` and paid/LOP fractions only — the underlying calendar classification (WORKING/HOLIDAY/WEEKLY_OFF) is never overwritten. Anyone reading `calendar_day_type` off an `AttendanceDay` row to infer "was this a holiday" will get the right answer even on a day that ended up `attendance_status=LEAVE`.
- **Overtime detection is entirely blind to leave.** No decision has been made about whether an employee should be allowed to earn OT on a day they were also on approved leave (see CONF-009 / ⚠️ open above).
- **No leave-specific period lock exists.** All locking behaviour Leave is subject to is Attendance's period lock, consumed through the projection-sync seam. There is no independent "leave period" concept to investigate separately.

## Summary of unresolved cross-module decisions

| ID | Topic | Status |
|---|---|---|
| PD-LEAVE-OT-1 | Should OT be blocked/reduced/allowed on a day with approved leave? | ⚠️ POLICY DECISION REQUIRED |
| PD-LEAVE-LOCK-1 | Should backdated leave submission be blocked outright if the target date's attendance period is already closed, rather than only failing at approval? | ⚠️ POLICY DECISION REQUIRED |
| PD-LEAVE-LOCK-2 | Should any arrears/exception mechanism exist for leave approved after a period lock, short of a full period reopen? | ⚠️ POLICY DECISION REQUIRED (carried over from Attendance's own PD-LOCK-2) |
| PD-LEAVE-SANDWICH-1 | Should the sandwich rule look across multiple separately-submitted applications, not just within one application's date range? | ⚠️ POLICY DECISION REQUIRED |
| PD-LEAVE-EARLY-1 | Does half-day leave interact with early-departure classification on the worked half of the day? | 🔵 GAP — untested, no explicit rule |

---

## 6. Policy Override Matrix


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

---

## 7. Policy Effective-Date & History Analysis


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

---

## 8. Hidden Policy Decisions Audit


**Status:** Audit document. This section identifies places in code where a business decision is being made implicitly — via an `if/else` default, a hard-coded threshold, a fallback, "first match wins," or silent conflict resolution — without a corresponding explicit, documented business rule. Classification per item: **Confirm** (the default is fine, just needs to be written down as policy) / **Document** (needs writing up, no change) / **Change** (the current default is probably wrong) / **Client decision required** (genuinely ambiguous, needs a business answer).

No code was modified to produce this document.

## Hidden Policy Decisions

| Hidden Decision | Current Code Behaviour | Business Documentation | Risk | Required Action |
|---|---|---|---|---|
| HD-001 — Default `missing_punch_behaviour` | `INCOMPLETE` (`models.py:98`) — a zero-punch expected working day never silently becomes ABSENT unless HR explicitly sets that | Documented in `01_ATTENDANCE_BUSINESS_RULES.md` §7.1 with explicit rationale ("ABSENT is harsh and must be an explicit policy choice") | Low — rationale is sound and written down | **Confirm** |
| HD-002 — `night_ot_mode` default `SHIFT_FLAG` never emits `NIGHT` day-class | Any shift not flagged `is_cross_midnight` never gets NIGHT OT classification, regardless of actual punch clock-time | Called "the sharpest contradiction found between the system's original design intent and what was actually built" in existing docs (`ATTENDANCE_CLIENT_RULES_AND_SCENARIOS.md` §18) | High — silently misclassifies genuinely-worked night hours for any shift not marked cross-midnight | **Client decision required** — carried forward as CD-001, still open |
| HD-003 — `eligibility=GRADE_VIA_ASSIGNMENT`/`ALWAYS` fall through as unconditionally eligible | No branch exists for these two enum values in `detect_overtime`; any value other than `NEVER`/`SHIFT_FLAG` is treated as eligible | Named as ND-07 in existing gap analysis; client sign-off doc confirms "as proposed" (i.e., client did not ask for a change) | Medium (label implies grade-based logic that doesn't exist) | **Confirm** (client already reviewed and accepted this shape) but rename/relabel recommended for clarity |
| HD-004 — `blocked_when_locked` regularization flag is inert | The unconditional period-lock check makes this flag's `False` value meaningless — it can never actually unblock a locked-day submission | Flagged in `ATTENDANCE_CLIENT_RULES_AND_SCENARIOS.md` §26.2 as needing relabelling | Medium — HR admins configuring this field get false expectations | **Change** (relabel or remove the field; do not leave a config surface that implies power it doesn't have) |
| HD-005 — `AUTO_CLOSE` missing-punch behaviour never actually auto-closes | Falls through to hour-band evaluation; `auto_closed` flag is always `false`; no synthetic OUT punch is ever created | Flagged as ND-05 in existing gap analysis | Medium — same false-customization risk as HD-004 | **Change** — relabel now per existing recommendation |
| HD-006 — `KEEP_LEAVE` does not zero `ot_minutes_detected` | Leave overlay only zeroes late/early minutes, not OT; a day can be simultaneously `attendance_status=LEAVE` and carry a nonzero OT record | No documented rule either way | High — directly affects payroll cost if unaddressed | **Client decision required** (= CD-002 / CONF-009 / PD-LEAVE-OT-1, repeated across documents because it's genuinely unresolved everywhere it appears) |
| HD-007 — SHIFT-scoped policy resolution ignores roster override | Policy resolution's SHIFT scope reads only `EmployeeAssignment.shift_id`, never the day's actual roster-assigned shift, even though architecture text says it should include roster | Named divergence in `02_ATTENDANCE_PRECEDENCE_MATRIX.md` §1 and CD-006 | High — an employee rostered onto a different shift still gets policy resolved against their *base* shift, which may have different grace/bands/etc. than the shift they're actually working that day | **Client decision required** (= CONF-004, still open per newest decision-log entries) |
| HD-008 — Two overlapping `PolicyAssignment` rows at the same scope tier are not defended against | No DB constraint or service-layer check prevents two active assignments of the same `policy_kind` at the same exact scope+scope_id | Named in `ATTENDANCE_OVERRIDE_MATRIX.md` item 4 / CD-026 | Medium — if it ever happens (e.g. a race condition or manual DB edit), which one resolves is whatever the query's implicit ordering returns — genuinely "first match wins" with no documented tie-break rule | **Client decision required** (also a **Change** — this should probably be a DB constraint, not just documentation) |
| HD-009 — Leave application eligibility-check ordering | `submit()` checks on-behalf permission → probation → half-day validity → reason/attachment → backdating window → monthly cap → day-breakdown → combination rule → balance (last) — this specific order is implementation structure, never stated as a business rule | No documentation found stating this order is intentional | Low-medium — could matter for which error message a user sees first, and for whether a probation-blocked employee even gets to see an "insufficient balance" message | **Document** (write down the intended check order, or confirm current order is acceptable) |
| HD-010 — Sandwich rule scope limited to a single application | The sandwich rule's look-back for a bracketed non-consuming day only considers dates within the *same* submitted application, never a previously-submitted adjacent application | No documentation found addressing multi-application sandwich scenarios | Medium — an employee could split one long leave into two adjacent applications specifically to dodge the sandwich rule | **Client decision required** |
| HD-011 — `reserve_balance_on_submission` default `False` | By default, multiple pending (SUBMITTED) applications for the same leave type are **not** jointly checked against balance — each is only checked individually at submission time | Documented as LD-15's explicit default, with rationale given | Low — documented and deliberate | **Confirm** |
| HD-012 — Comp-off expiry "never drives balance negative" | If balance was already spent below the original credit amount by the time expiry runs, the expiry offset is silently skipped rather than partially applied | Documented explicitly as LD-14 decision 3, "generous... at the cost of" edge-case correctness | Low-medium — a documented, deliberate simplification, but means comp-off expiry enforcement is not airtight | **Confirm** (already a conscious tradeoff) but worth noting as a known leak in strict FIFO accounting |
| HD-013 — Statutory minimum enforced only at policy **publish** time, using the strictest configured minimum across all states/establishment types | A policy is blocked from publishing if it's below the max of every configured `StatutoryLeaveMinimum` for its category, even ones that will never apply to any employee under that policy's actual scope | Documented rationale: "publish-time enforcement doesn't know final state/establishment assignment, so it uses the strictest bound" | Medium — could over-block a policy that would have been compliant for its actual assigned population, forcing HR to set a higher-than-legally-required accrual rate | **Client decision required** — is "always use the strictest" acceptable, or should enforcement instead check the minimum for the *specific* scope the policy is being assigned to? |
| HD-014 — No same-leave-type overlap check | Two overlapping applications of the *same* leave type are not blocked by any rule; only the cross-type combination rule exists | No documentation addresses this at all | Medium — could allow duplicate/double-booked leave for the same dates under the same type, consuming balance twice if both are separately approved | **Client decision required** |
| HD-015 — Backdated leave submission does not check attendance-period lock state | A leave application can be submitted for a date whose attendance period is already closed; the lock is only discovered at approval time | No documentation addresses this | Medium — confusing UX; an application can sit indefinitely `SUBMITTED`, failing silently-late at approval | **Change** (recommend checking at submission time, or at minimum surfacing a warning) |
| HD-016 — Employee lifecycle: Attendance and Leave read different "is this employee currently working" signals | Attendance derives population status from `Employment` dates only; Leave reads `Employee.status` (including PROBATION) directly | No document states these are deliberately independent | Low in practice (no observed conflict), but an unstated architectural assumption | **Document** — write down explicitly that these are intentionally separate signals for separate purposes |
| HD-017 — Leave Year Setting and Leave Combination Rule have no effective-dating | Unlike every other policy object in the system, these two have no `effective_from`/`effective_to` and no versioning | No documentation addresses this gap | Medium — a past leave decision cannot be explained by "the rule/year-setting in force at the time" if either has since changed | **Change** — bring these two into the same effective-dating pattern as everything else, or explicitly document why they're exempt |
| HD-018 — `RegularizationPolicyVersion.auto_approve_within_minutes` and `OvertimePolicyVersion.requires_pre_approval` are stored but never read | Both fields exist on the schema and can be set via the API/UI, but grep of `service.py`/`calculation.py` finds no code path that reads either | Named as part of the broader "false customization" pattern in `ATTENDANCE_CONFIGURATION_AUDIT.md` §9 | Medium — HR configuring these gets no actual effect, false confidence | **Change** — either wire them up or remove/hide them from configuration surfaces |
| HD-019 — `LeavePolicyVersion.allow_negative_balance` is stored but never read | Field exists, defaults `False`, but no code path checks it — negative balance is unconditionally blocked regardless of its value | Documented explicitly in LD-06 decision 4 as intentional for now ("the column remains in the schema... but nothing sets it True until a future client asks for advance leave") | Low — already documented as deliberate | **Confirm** |

## Summary counts

- **Confirm** (default is fine, just document it): HD-001, HD-003, HD-011, HD-012, HD-019 — 5 items
- **Document** (write it down, no behaviour change): HD-009, HD-016 — 2 items
- **Change** (current default likely needs adjustment): HD-004, HD-005, HD-008 (partially), HD-015, HD-017, HD-018 — 6 items
- **Client decision required** (genuinely ambiguous): HD-002, HD-006, HD-007, HD-008, HD-010, HD-013, HD-014 — 7 items

---

## 9. Master Policy Decision Register


**Status:** Audit document — consolidated register of every unresolved or explicitly-flagged decision surfaced across all other documents in this audit set, plus decisions already open in the pre-existing attendance business-rule documentation that remain unresolved as of 2026-09-07. No option was invented where the implementation/documentation doesn't already support one.

**Decision-type legend:**
- **Client Business Decision** — needs an answer from the client/business owner (e.g. "should X be allowed")
- **Product Decision** — needs an answer from the product owner about scope/priority
- **Technical Decision** — needs an engineering call about implementation approach, not business meaning
- **Implementation Verification** — needs someone to confirm current behaviour is/isn't intentional before it's signed off as policy

---

## Carried-forward decisions already open in existing Attendance documentation (pre-dating this audit)

| Decision ID | Module | Policy Area | Decision Required | Options | Priority | Status |
|---|---|---|---|---|---|---|
| PD-CAL-1 | Attendance | Optional/Restricted holiday default | Should optional/restricted holidays be off-by-default? | Working-until-Leave (current) / Off-by-default | Medium | ⚠️ Open |
| PD-CAL-2 | Attendance | Holiday-on-weekly-off | Should the system auto-substitute a holiday landing on a weekly-off day? | No auto-substitute (current) / Auto-substitute to next working day | Medium | ⚠️ Open |
| PD-POL-1 | Attendance | Engine precedence configurability | Should the fixed evaluation order in `calculation.py` ever be exposed as a reorderable UI setting? | Keep locked (current) / Expose reorder UI | Low | ⚠️ Open |
| PD-SHIFT-1 | Attendance | Intra-day shift change | Should an employee be able to have more than one schedule per attendance date? | Not supported (current) / Support intra-day change | Low | ⚠️ Open |
| PD-LOCK-1 | Attendance | Lock grain | Should period lock be scoped to legal entity instead of company? | Company-wide (current) / Legal-entity-scoped | Low | ⚠️ Open |
| PD-LOCK-2 | Attendance | Post-lock correction | Should a controlled post-lock correction/arrears mechanism exist, short of a full reopen? | No mechanism (current) / Build `AttendanceAdjustment`/arrears path | **High** | ⚠️ Open — flows directly into the Leave-side PD-LEAVE-LOCK-2 below |
| PD-WFH-1 | Attendance | WFH auto-detection | Should WFH auto-derive from assignment location? | No (current) | Low | ⚠️ Open |
| PD-OT-1 | Attendance | OT terminal-record revision | Should a terminal (approved/rejected) overtime record ever become revisable/voidable? | No revision path (current) / Add a supervised revision flow | Medium | ⚠️ Open |
| PD-OT-2 | Attendance | OT pre-approval enforcement | `requires_pre_approval` is stored but never enforced — should it be wired up? | Leave dormant (current) / Implement enforcement | Medium | ⚠️ Open (= HD-018 in Hidden Decisions Audit) |
| PD-SCOPE-1 | Attendance | Branch-HR RBAC scope | Should branch-level HR roles get BRANCH-level data scope instead of COMPANY? | COMPANY for HR roles (current) | Low | ⚠️ Open |
| PD-REG-1 | Attendance | WRONG_STATUS/EXCESS_BREAK representability | Should these regularization types be representable without a calculation-engine extension? | Not supported until scoped (current) | Medium | ⚠️ Open |

## New decisions surfaced by this cross-module audit

| Decision ID | Module | Policy Area | Decision Required | Options | Priority | Status | Type |
|---|---|---|---|---|---|---|---|
| PD-XMOD-001 | Cross-module | Leave vs. Overtime | Should approved leave suppress/reduce OT eligibility on the same day, or should the two remain fully independent? | (a) Leave zeroes OT entirely (b) Leave and OT coexist as independent facts (current) (c) Configurable per policy | **Critical** | ⚠️ Open | Client Business Decision |
| PD-XMOD-002 | Cross-module | Roster vs. SHIFT-scoped policy | Should policy resolution's SHIFT scope use the day's actual roster-assigned shift instead of the employee's base assignment shift? | (a) Keep base-assignment-only (current) (b) Align to roster, per original architecture intent | **High** | ⚠️ Open | Product Decision |
| PD-XMOD-003 | Cross-module | Leave submission vs. attendance lock | Should a leave application be blocked at **submission** time if its target date's attendance period is already closed, rather than only failing at approval? | (a) Keep current (fails late, at approval) (b) Block/warn at submission | **High** | ⚠️ Open | Product Decision |
| PD-XMOD-004 | Cross-module | Post-lock leave correction | Should any arrears/exception mechanism exist for leave approved after a period lock, short of a full attendance-period reopen? | (a) None (current — full reopen only) (b) Build a leave-specific arrears path | **High** | ⚠️ Open | Client Business Decision — tightly coupled to PD-LOCK-2 |
| PD-XMOD-005 | Cross-module | Sandwich rule scope | Should the sandwich rule look across multiple separately-submitted applications, or stay scoped to one application's date range (current)? | (a) Keep single-application scope (current) (b) Extend look-back across applications | Medium | ⚠️ Open | Client Business Decision |
| PD-XMOD-006 | Cross-module | Half-day leave vs. early departure | Does half-day leave interact with early-departure classification on the worked portion of the same day? | Undetermined — no rule exists either way | Medium | ⚠️ Open | Implementation Verification |
| PD-ATT-001 | Attendance | Two overlapping PolicyAssignments at the same scope | Should this be structurally prevented (DB constraint), or is a documented tie-break rule sufficient? | (a) Add DB constraint (b) Document first-match rule (c) Leave as-is | **High** | ⚠️ Open | Technical Decision |
| PD-ATT-002 | Attendance | Night OT classification | Should `night_ot_mode=WINDOW/BOTH` actually compare punch clock-time to `night_window_start/end`, instead of always deriving "night" from `shift.is_cross_midnight`? | (a) Implement real window check (b) Remove the unused enum values/fields | **High** | ⚠️ Open (= CD-001, HD-002) | Product Decision |
| PD-ATT-003 | Attendance | `blocked_when_locked` / `AUTO_CLOSE` mislabeled fields | Should these dormant/misleading fields be relabeled or removed? | (a) Relabel for clarity (b) Wire up real behaviour (c) Remove | Medium | ⚠️ Open (= HD-004, HD-005) | Technical Decision |
| PD-LEAVE-001 | Leave | Same-leave-type overlap | Should two overlapping applications of the *same* leave type be blocked, the way cross-type combination rules already block overlap between different types? | (a) No block (current) (b) Block same-type overlap by default | **High** | ⚠️ Open | Client Business Decision |
| PD-LEAVE-002 | Leave | Statutory minimum enforcement scope | Should publish-time enforcement use the strictest configured minimum across all states/establishment types (current), or only the minimum relevant to the policy's actual assigned scope? | (a) Strictest-always (current) (b) Scope-aware check | Medium | ⚠️ Open | Client Business Decision |
| PD-LEAVE-003 | Leave | Advance leave / negative balance | Should advance leave (negative balance) ever be supported, activating the currently-dormant `allow_negative_balance` field? | (a) Never (current) (b) Support under specific conditions | Low | ⚠️ Open | Client Business Decision |
| PD-LEAVE-004 | Leave | Approval delegation | Should a delegation/out-of-office/acting-approver mechanism be built? | (a) Not built (current) (b) Build delegation | Medium | ⚠️ Open | Product Decision |
| PD-LEAVE-005 | Leave | Leave Year Setting effective-dating | Should the Leave Year Setting be versioned/effective-dated like every other policy object, and what happens to an in-progress leave year if it changes mid-year? | Undetermined | Medium | ⚠️ Open | Technical Decision |
| PD-LEAVE-006 | Leave | Leave Combination Rule effective-dating | Should combination rules be effective-dated so past decisions can be explained by "the rule in force at the time"? | Undetermined | Low | ⚠️ Open | Technical Decision |
| PD-LEAVE-007 | Leave | Eligibility-check ordering | Is the current check order in `submit()` (on-behalf → probation → half-day → reason → backdating → monthly-cap → day-breakdown → combination → balance) an intentional business rule, or incidental code structure that could change? | Undetermined | Low | ⚠️ Open | Implementation Verification |
| PD-LEAVE-008 | Leave | Gender/tenure restriction | Neither gender-restricted nor minimum-tenure-restricted leave types exist today — is either required? | (a) Not required (current) (b) Add gender restriction (c) Add tenure restriction | Medium | ⚠️ Open | Client Business Decision |
| PD-LEAVE-009 | Leave | Withdrawal vs. cancellation distinction | The system has only "cancellation," no separate "withdrawal" concept, and no amend/modify-in-place for an existing application — is this sufficient? | (a) Current is sufficient (b) Add distinct withdrawal semantics (c) Add amend/modify | Low | ⚠️ Open | Product Decision |
| PD-DOC-001 | Attendance (docs only) | Documentation currency | Every attendance business-rule document still describes Leave as "a future module, not yet implemented" — should this entire document set be revised now that Leave exists and is the writer of `LeaveDayProjection`? | (a) Leave as-is (b) Revise attendance docs to reflect current Leave integration | **High** (client sign-off risk if left stale) | 🟠 Open | Technical Decision (documentation maintenance) |

## Priority summary

- **Critical:** 1 (PD-XMOD-001 — Leave vs. Overtime interaction)
- **High:** 8 (PD-LOCK-2, PD-XMOD-002, PD-XMOD-003, PD-XMOD-004, PD-ATT-001, PD-ATT-002, PD-LEAVE-001, PD-DOC-001)
- **Medium:** 12
- **Low:** 9
- **Total open decisions:** 30 (11 carried forward from pre-existing Attendance documentation + 19 newly surfaced by this audit)

## Decision-type breakdown

- **Client Business Decision:** PD-XMOD-001, PD-XMOD-004, PD-XMOD-005, PD-LEAVE-001, PD-LEAVE-002, PD-LEAVE-003, PD-LEAVE-008, plus carried-forward PD-CAL-1, PD-CAL-2
- **Product Decision:** PD-XMOD-002, PD-XMOD-003, PD-ATT-002, PD-LEAVE-004, PD-LEAVE-009, plus carried-forward PD-SHIFT-1, PD-WFH-1, PD-REG-1
- **Technical Decision:** PD-ATT-001, PD-ATT-003, PD-LEAVE-005, PD-LEAVE-006, PD-DOC-001, plus carried-forward PD-POL-1, PD-LOCK-1, PD-SCOPE-1
- **Implementation Verification:** PD-XMOD-006, PD-LEAVE-007, plus carried-forward PD-OT-1, PD-OT-2

---

## 10. Master Policy Map


**Status:** Audit document. Structure below is transcribed from actual evaluation order in code (`attendance/calculation.py::evaluate_day`, `leave/service.py::submit`/`_approve_internal`), not assumed.

## 1. Attendance Day — actual evaluation hierarchy

```
ATTENDANCE DAY EVALUATION (evaluate_day, highest wins)
│
├── 1. Employment Population Gate
│   └── NOT_JOINED / ACTIVE / EXITED  (from Employment.joining_date / last_working_day — NOT Employee.status)
│       └── if not ACTIVE: terminal, nothing below applies
│
├── 2. Config Resolution (fail-closed)
│   ├── Calendar unresolved → CONFIG_ERROR
│   └── Policy unresolved (8-level scope walk) → CONFIG_ERROR
│
├── 3. Roster Week-Off Override
│   └── published ShiftRoster.is_week_off_override → NOT_EXPECTED (wins even over calendar WORKING)
│
├── 4. Missing-Shift Handling
│   └── missing_shift_behaviour → ABSENT / INCOMPLETE (unless punches exist)
│
├── 5. Calendar Day-Type
│   ├── HOLIDAY / WEEKLY_OFF / SHUTDOWN → NOT_EXPECTED ...
│   └── ...unless shift.operates_on_holiday / operates_on_weekly_off / roster override says otherwise
│
├── 6. Punch-Derived Evaluation
│   ├── Worked minutes → Hour Bands → PRESENT / HALF_DAY / ABSENT (baseline)
│   ├── Late-Arrival Bands ────┐
│   ├── Early-Departure Bands ─┼── any one can force worse status (ABSENT beats HALF_DAY beats PRESENT); no mutual suppression
│   ├── Core-Hours Breach ─────┤
│   └── Cumulative Overrides ──┘   (lates-to-half-day, excess-break-days-to-half-day)
│
├── 7. Leave Overlay  (LEAVE_DAY_PROJECTION, owned by Attendance, written by Leave module)
│   └── Full-day approved leave WINS OUTRIGHT — even over step 5's NOT_EXPECTED
│       ├── work_on_leave_behaviour = KEEP_LEAVE (default) → status = LEAVE, late/early zeroed
│       └── work_on_leave_behaviour = PRESENT_CANCEL_LEAVE_HINT → keeps step 6's status, flags work_on_leave_flagged
│       (does NOT touch calendar_day_type; does NOT touch ot_minutes_detected — ⚠️ open decision)
│
└── 8. On-Duty Overlay
    └── Approved ON_DUTY regularization → status = ON_DUTY (loses to step 7 if leave also covers the date)

[Regularization is NOT a status branch — approved corrections re-enter as new immutable Punch rows
 (source=REGULARIZATION) + a full re-run of steps 1-8. Overtime is a SEPARATE, parallel computation
 (detect_overtime) that runs independent of this chain and is never overridden by it.]

[Period Lock sits outside this hierarchy entirely: once AttendancePeriod.status=CLOSED, NO step above
 can execute for dates in range — not punches, not roster, not regularization, not recompute, not
 leave-projection sync. It is the one rule that outranks everything else in the system.]
```

## 2. Leave Application — actual evaluation hierarchy

```
LEAVE APPLICATION SUBMISSION (submit(), code order)
│
├── 1. Policy Resolution (8-level scope walk, same engine as Attendance) → fail-closed if unresolved
├── 2. Calendar Resolution (per date in range) → fail-closed if unresolved
├── 3. On-Behalf Permission Gate (self / manager-on-behalf / hr-on-behalf)
├── 4. Probation Restriction (Employee.status == PROBATION vs allowed_during_probation)
├── 5. Half-Day Validity (single-date only, half_day_allowed)
├── 6. Reason / Attachment Required
├── 7. Backdating Window (max_backdated_days; no future-date limit)
├── 8. Monthly Request Cap (max_requests_per_month)
├── 9. Day-Breakdown Computation
│   ├── WORKING / SPECIAL_WORKING → consumes leave
│   ├── WEEKLY_OFF / HOLIDAY / SHUTDOWN → does not consume ...
│   └── ...UNLESS Sandwich Rule brackets it between two consuming days (same application only)
├── 10. Leave Combination Rule (blocks overlap with a DIFFERENT type only if an explicit deny rule exists)
└── 11. Balance Sufficiency (optionally net of reserved/pending balance) → hard block, negative balance NEVER allowed

LEAVE APPROVAL (multi-stage, chain-dependent)
│
AUTO ──────────────► immediately approved, no stage
MANAGER ───────────► resolved-manager approval → FINAL
MANAGER_THEN_HR ───► manager → HR → FINAL
MANAGER_THEN_HOD_THEN_HR ─► manager → HOD → HR → FINAL   (any unresolved identity stage is DROPPED;
HR ────────────────► HR approval → FINAL                  if ALL identity stages unresolved, falls back to single HR stage)
│
└── On FINAL approval only:
    ├── Ledger debit (APPLICATION entry, unless requires_balance=False)
    └── Sync LeaveDayProjection → Attendance (SAME transaction)
        └── Attendance period CLOSED for that date? → sync refused → ENTIRE approval transaction rolls back
            (application stays SUBMITTED, not partially approved)

Self-approval: BLOCKED UNCONDITIONALLY at every stage, no policy field can re-enable it.
```

## 3. Cross-Module Map

```
                        ┌─────────────────────────────┐
                        │   8-LEVEL POLICY RESOLUTION   │   (SHARED-POL-001)
                        │  EMPLOYEE > SHIFT > DESIGNATION│
                        │  > GRADE > DEPARTMENT > BRANCH │
                        │  > LEGAL_ENTITY > COMPANY      │
                        └──────────┬──────────┬─────────┘
                                   │          │
                     resolves     │          │     resolves
              AttendancePolicy/   │          │   LeavePolicyVersion
              OvertimePolicy/     │          │   (per leave_type)
              RegularizationPolicy│          │
                                   ▼          ▼
                        ┌──────────────┐  ┌──────────────┐
                        │  ATTENDANCE   │  │    LEAVE      │
                        │    MODULE     │  │    MODULE     │
                        └──────┬───────┘  └──────┬───────┘
                               │                  │
              owns:            │                  │  owns:
        LeaveDayProjection ◄───┼──── writes ──────┤   LeaveApplication
        (mirror table)         │   (sync/cancel,   │   LeaveLedgerEntry (append-only)
                               │    same txn as     │   LeavePolicyVersion
                               │    approval)        │
                               │                  │
        reads (facts only) ────┼──────────────────┤   reads (facts only, via
        OvertimeRecord             comp_off_minutes    list_comp_off_facts — read-only,
        .comp_off_minutes          / expiry_date         Leave never writes Attendance tables)
        .comp_off_expiry_date  ─────────────────────►
                               │
        AttendancePeriod       │
        lock state ────────────┼──── gates ───────►   Leave approval / cancellation
        (OPEN/CLOSED)             (CLOSED = refuse,      (transaction rolls back on refusal)
                                    no arrears path,
                                    PD-XMOD-004 open)

        Employment.joining_date/last_working_day
                │
                ├──► Attendance population_status (NOT_JOINED/ACTIVE/EXITED)
                └──► Leave accrual proration + ANNIVERSARY leave-year anchor

        Employee.status (PROBATION/ACTIVE)
                │
                └──► read ONLY by Leave (probation eligibility/accrual gate) — Attendance never reads this field
```

## 4. What this map deliberately does NOT show

- No "money"/payroll layer exists in either module — both stop at paid/LOP fractions or ledger day-counts; a Payroll module is out of scope for this audit (confirmed absent in both source trees).
- Overtime's interaction with Leave is drawn as absent on purpose — there genuinely is no rule connecting the two boxes for OT (PD-XMOD-001), which is why no arrow is drawn between Overtime and Leave above.

---

## 11. Policy Precedence Scenario Catalog


**Status:** Audit document. Every scenario below is backed by either a passing test (cited) or an explicit code path (cited); none are hypothetical extrapolations beyond what the cited evidence shows.

---

## PP-001 — Approved Full-Day Leave vs. Attendance Punches

**Conditions:** Full-day leave approved for an employee; the employee also has valid IN/OUT punches covering the full shift that day.
**Policies involved:** `work_on_leave_behaviour` (ATT-POL-013), Leave approval (LEAVE-POL-027).
**Current system behaviour:** Default policy (`KEEP_LEAVE`): `attendance_status` stays `LEAVE`; `late_minutes`/`early_minutes` are zeroed; `work_on_leave_flagged=False`. If policy is set to `PRESENT_CANCEL_LEAVE_HINT`: `attendance_status=PRESENT` (punch-derived), `work_on_leave_flagged=True`; the leave application itself is **not** auto-cancelled.
**Documented intended behaviour:** Matches architecture §19.3/19.4 exactly — no discrepancy.
**Winner:** Leave (by default policy); punches only win under an explicit non-default policy setting, and even then don't touch the leave application.
**Status:** 🟢 Confirmed. Evidence: `test_full_day_leave_keep_leave_behaviour_overrides_punches`, `test_full_day_leave_present_cancel_leave_hint_flags_and_keeps_punch_status`.
**Decision required:** None.

## PP-002 — Half-Day Unpaid Leave + Full-Day Punches

**Conditions:** Employee applies half-day unpaid leave; also punches a full working day.
**Policies involved:** Half-day leave mechanics (LEAVE-POL-018), hour bands (ATT-POL-004).
**Current system behaviour:** `attendance_status=HALF_DAY`; `paid_day_fraction=0.50` (worked half), `lop_fraction=0.50` (unpaid leave half).
**Documented intended behaviour:** Matches architecture worked example.
**Winner:** Combined — the day is split proportionally, neither side unilaterally wins.
**Status:** 🟢 Confirmed. Evidence: `test_half_day_unpaid_leave_with_full_day_punches`.
**Decision required:** None.

## PP-003 — Approved Leave vs. Roster Week-Off (NOT_EXPECTED)

**Conditions:** Employee has a published roster week-off override for a date, and also has approved full-day leave covering that same date.
**Policies involved:** Roster week-off override (ATT-POL-044), leave overlay (ATT-POL-051).
**Current system behaviour:** `attendance_status=LEAVE`, but `calendar_day_type` stays whatever the roster/calendar said (untouched).
**Documented intended behaviour:** Matches architecture §19.4's stated precedence (leave ranks above calendar NOT_EXPECTED).
**Winner:** Leave (for `attendance_status`); Roster/Calendar (for `calendar_day_type`, which leave never touches).
**Status:** 🟢 Confirmed. Evidence: `test_leave_overrides_roster_week_off_not_expected`.
**Decision required:** None.

## PP-004 — Approved Leave vs. Overtime Detected the Same Day

**Conditions:** Employee has approved leave for a day, and also has punches that would independently trigger OT detection (e.g., a partial workday with excess hours before the leave was applied, or comp-off scenario).
**Policies involved:** Leave overlay, OT detection (ATT-POL-021).
**Current system behaviour:** Both facts coexist — `attendance_status=LEAVE` (or HALF_DAY) and `ot_minutes_detected` remains whatever the punch-derived pass computed; the leave overlay never clears it.
**Documented intended behaviour:** None found in either module.
**Winner:** No rule — undefined interaction.
**Status:** ⚠️ **POLICY DECISION REQUIRED** (PD-XMOD-001).
**Decision required:** Yes — should approved leave suppress/zero OT for that day, or should the two remain independent facts as today?

## PP-005 — Regularization Approved After Attendance Already Locked

**Conditions:** A regularization request is `SUBMITTED` for a date; before it's approved, the attendance period covering that date is finalized/locked.
**Policies involved:** Period lock (ATT-POL-036), regularization approval (ATT-POL-033).
**Current system behaviour:** `_ensure_date_open` blocks the approval outright — `AttendancePeriodClosedError` — regardless of `blocked_when_locked`'s configured value. The whole approval transaction rolls back; request stays `SUBMITTED`.
**Documented intended behaviour:** Consistent — WD-30: "Lock outranks every other mutating action for dates inside the locked range."
**Winner:** Period lock.
**Status:** 🟢 Confirmed. Evidence: `test_attendance_period.py` lock-enforcement tests; `service.py:3491-3496`.
**Decision required:** None for this scenario itself, but see PD-LOCK-2 (should any exception/arrears path exist).

## PP-006 — Leave Approved After Attendance Period Locked

**Conditions:** A leave application reaches its final approval stage; the target date's attendance period is already `CLOSED`.
**Policies involved:** Period lock, leave approval/projection sync (LEAVE-POL-033).
**Current system behaviour:** `LeaveProjectionService.sync()` raises `ATTENDANCE_PERIOD_CLOSED`; because the sync call happens inside the same DB transaction as the leave approval write, the **entire leave approval fails** — the application is never left partially approved.
**Documented intended behaviour:** Explicit, LD-12: "no partial approval, no partially-synced application."
**Winner:** Period lock.
**Status:** 🟢 Confirmed. Evidence: `test_sync_refused_when_period_closed`.
**Decision required:** PD-XMOD-004 (should an arrears mechanism exist).

## PP-007 — Leave Cancellation After Attendance Finalization

**Conditions:** An `APPROVED` leave application (already synced into Attendance) is cancelled by the employee; the attendance period is now `CLOSED`.
**Policies involved:** Cancellation (LEAVE-POL-024), period lock.
**Current system behaviour:** `LeaveProjectionService.cancel()` is refused the same way as sync; the entire cancellation transaction (ledger credit-back + projection cancel) rolls back — the application stays `APPROVED`, balance stays debited.
**Documented intended behaviour:** Explicit test docstring: "§21 — Leave approved after payroll lock... default refuse," applying symmetrically to cancellation.
**Winner:** Period lock.
**Status:** 🟢 Confirmed. Evidence: `test_cancel_refused_when_period_closed`.
**Decision required:** Same as PP-006 (PD-XMOD-004) — the only remedy today is a full period reopen.

## PP-008 — Two Overlapping Leave Types on the Same Day (Combination Rule)

**Conditions:** Employee has a SUBMITTED/APPROVED application of Leave Type A covering a date; attempts to submit Leave Type B for an overlapping date, where an explicit `allowed=False` combination rule exists between A and B.
**Policies involved:** Leave combination rule (LEAVE-POL-006).
**Current system behaviour:** Second submission is blocked (422 `LEAVE_APPLICATION_COMBINATION_NOT_ALLOWED`), symmetric regardless of submission order. A `REJECTED` application no longer counts as "active" for this check.
**Documented intended behaviour:** LD-16, matches exactly.
**Winner:** The combination rule (blocks the second type).
**Status:** 🟢 Confirmed. Evidence: `test_explicit_not_allowed_rule_blocks_overlapping_submission`, `test_rejected_application_no_longer_blocks`.
**Decision required:** None for cross-type; see PP-009 for the same-type gap.

## PP-009 — Two Overlapping Applications of the SAME Leave Type

**Conditions:** Employee submits two separate applications of the same leave type with overlapping dates.
**Policies involved:** None found — the combination-rule mechanism only governs *different* types.
**Current system behaviour:** Not blocked by any code path found. Balance sufficiency is checked independently for each (unless `reserve_balance_on_submission=True`, in which case pending totals are netted).
**Documented intended behaviour:** None found.
**Winner:** Undefined — both submissions can succeed.
**Status:** 🔵 Implementation gap / ⚠️ **POLICY DECISION REQUIRED** (PD-LEAVE-001).
**Decision required:** Yes.

## PP-010 — Probation Employee Attempts to Apply for Leave

**Conditions:** New hire in `Employee.status=PROBATION`; applies for a leave type whose resolved policy has `allowed_during_probation=False`.
**Policies involved:** Probation restriction (LEAVE-POL-002).
**Current system behaviour:** Blocked, 422 `LEAVE_APPLICATION_NOT_ALLOWED_DURING_PROBATION`. Confirmed end-to-end: real `EmployeeService.create_employment` → PROBATION → blocked submission → `POST /employees/{id}/confirm` → ACTIVE → identical submission then succeeds.
**Documented intended behaviour:** LD-18, matches exactly.
**Winner:** Probation restriction (while PROBATION); Employee confirmation (SHARED-POL-002) is the only unblock path.
**Status:** 🟢 Confirmed. Evidence: `test_confirm_unblocks_probation_restricted_leave_type`.
**Decision required:** None.

## PP-011 — Holiday Landing on a Weekly-Off Day

**Conditions:** A configured public holiday falls on a date that is also a weekly-off day per the assigned pattern.
**Policies involved:** Holiday (ATT-POL-039), Weekly-off pattern (ATT-POL-042), precedence rule (ATT-POL-043).
**Current system behaviour:** Day is classified `WEEKLY_OFF`, with `holiday_on_weekly_off` flag raised — the holiday does not promote or substitute the day.
**Documented intended behaviour:** WD-05, matches.
**Winner:** Weekly Off.
**Status:** 🟢 Confirmed.
**Decision required:** PD-CAL-2 (should an auto-substitute-to-next-working-day mechanism exist) remains open.

## PP-012 — Employee's Base Shift Assignment vs. Roster Override for Policy Resolution

**Conditions:** Employee's base `EmployeeAssignment.shift_id` is Shift A; a published roster reassigns them to Shift B for a specific date; a `PolicyAssignment` exists scoped to Shift B with different grace/bands than the company default.
**Policies involved:** Roster (ATT-POL-044), 8-level policy resolution (SHARED-POL-001).
**Current system behaviour:** The employee **works** Shift B's schedule that day (roster wins for scheduling), but SHIFT-scoped **policy resolution** still resolves against Shift A (the base assignment) — the Shift-B-scoped policy is never picked up for that date.
**Documented intended behaviour:** Architecture text (§16) says SHIFT scope should include roster; code does not implement this.
**Winner:** Roster (schedule) / Base assignment (policy scope) — a genuine split, not a single consistent winner.
**Status:** 🟠 **DOCUMENTATION/IMPLEMENTATION CONFLICT** (= CONF-004, PD-XMOD-002).
**Decision required:** Yes.

## PP-013 — Backdated Leave Application for a Date Whose Attendance Period Is Already Closed

**Conditions:** Employee submits a leave application today for a date 20 days ago; that date's attendance period was finalized 15 days ago; the leave policy's `max_backdated_days` is 30 (so submission itself is within window).
**Policies involved:** Backdating window (LEAVE-POL-020), period lock (indirectly, at approval time only).
**Current system behaviour:** Submission succeeds (no lock check at submission). Approval later fails once someone attempts final-stage approval, because the sync is refused for the closed period.
**Documented intended behaviour:** None found addressing this specific ordering.
**Winner:** Submission is unguarded; approval is where the lock actually bites.
**Status:** 🔵 Implementation gap (= HD-015, PD-XMOD-003).
**Decision required:** Yes.

## PP-014 — Manager-Then-HR Regularization Chain, HR Rejects After Manager Approved

**Conditions:** `MANAGER_THEN_HR` chain; manager approves (stage advances to HR); HR then rejects.
**Policies involved:** Regularization approval chain (ATT-POL-033).
**Current system behaviour:** HR's rejection is terminal — `status=REJECTED` regardless of the manager's earlier stage-approval; no correction is applied; the day's attendance is left unchanged (as if never regularized).
**Documented intended behaviour:** Matches — rejection is terminal from any stage, in both Attendance and Leave.
**Winner:** The last decision-maker in the chain (HR, since it's the final stage) — a later-stage rejection always overrides an earlier-stage approval.
**Status:** 🟢 Confirmed. Evidence: `test_manager_then_hr_two_stage_chain` (regularization); analogous leave test `test_manager_then_hr_two_stage_approval`.
**Decision required:** None.

## PP-015 — Comp-Off Credit When Day-Length Basis Is Not Configured

**Conditions:** An approved `OvertimeRecord` has `comp_off_minutes > 0`; the resolved `OvertimePolicyVersion.comp_off_day_length_minutes` is `NULL`.
**Policies involved:** Comp-off credit (LEAVE-POL-012).
**Current system behaviour:** Credit sweep skips this record entirely — no ledger row is written, no guess is made about a conversion basis.
**Documented intended behaviour:** Explicit, matches: "never guesses a conversion basis."
**Winner:** Neither — the fact is simply not converted until HR configures the basis.
**Status:** 🟢 Confirmed. Evidence: `test_credit_skipped_when_day_length_not_configured`.
**Decision required:** None (fail-closed is the confirmed design).

## PP-016 — Statutory Minimum Blocks Publishing a Compliant-Enough Policy

**Conditions:** HR tries to publish a `LeavePolicyVersion` for a `SICK`-category leave type with an annual entitlement of 12 days; two `StatutoryLeaveMinimum` rows exist for `SICK` (10 days in one state, 15 in another).
**Policies involved:** Statutory minimum enforcement (LEAVE-POL-014).
**Current system behaviour:** Publish is blocked (12 < 15, the strictest configured minimum), even though the policy might only ever be assigned to employees in the 10-day state.
**Documented intended behaviour:** Explicit rationale given: "publish-time enforcement doesn't know final state/establishment assignment, so it uses the strictest bound."
**Winner:** The strictest configured minimum, always.
**Status:** 🟢 Confirmed current behaviour; ⚠️ **POLICY DECISION REQUIRED** on whether this is the right tradeoff (PD-LEAVE-002).
**Decision required:** Yes.

## PP-017 — Reopening a Locked Attendance Period After a Policy Changed

**Conditions:** Period P was locked in January under Policy v1. In February, Policy v2 publishes with different grace minutes. In March, HR reopens Period P to fix an unrelated missing-punch issue.
**Policies involved:** Period reopen (ATT-POL-036), policy versioning (SHARED-POL-003).
**Current system behaviour:** Reopen only removes the lock — it does not recompute anything. Any day HR doesn't manually recompute stays exactly as it was calculated under Policy v1, even though the day is now technically mutable and Policy v2 is current. If HR does trigger a recompute, that day now resolves against whichever version's effective range covers it by date — if v2's `effective_from` predates the day, the day would recompute under v2, potentially changing already-reported numbers.
**Documented intended behaviour:** Explicit, WD-30: "a deliberate payroll-safety choice, so numbers already reported externally don't silently change" — but this only holds if HR doesn't manually recompute; the system provides no warning either way.
**Winner:** Whichever action HR happens to take next — no system-enforced safeguard beyond "don't recompute."
**Status:** 🔵 Implementation gap (= ND-08/CD-016, PD-EFFDATE-3).
**Decision required:** Yes — should reopening surface a warning, require explicit confirmation before recompute, or auto-recompute?

---

## 12. Client Policy Review & Sign-Off


**Audience:** HR leadership, client product owner, implementation consultants. No technical background assumed.
**Purpose:** Explain, in plain language, how Attendance and Leave decide "which rule wins" today, where the two modules connect, and which decisions still need your answer before we lock this behaviour in as confirmed policy.
**What this is not:** This document does not change how the system behaves. It describes what it does today and flags every place where "today's behaviour" is a default we chose, not something you've explicitly approved.

---

## 1. Executive Summary

Your HRMS now has two working modules — **Attendance** (tracking who worked when, and how) and **Leave** (tracking who's away, and why) — and they talk to each other through one narrow, well-defined connection point. We reviewed every rule in both modules, every place they could conflict, and every place a business decision is being made silently by code rather than by an explicit choice you've signed off on.

**The headline finding:** the system is more consistent than most HR software at this stage — both modules use the identical "most specific rule wins" logic for figuring out which policy applies to which employee, and both treat a locked payroll period as untouchable. But there are **9 high-or-critical decisions** that are currently resolved by an unstated default, not a decision you've made, and **1 of those (leave vs. overtime pay) is the single most financially significant open question** in the whole system.

## 2. How Attendance and Leave Connect

Picture it like two departments that share exactly one filing cabinet. **Leave decides** whether someone is approved to be away, for how much of the day, and whether it's paid. **Attendance owns the calendar** — it takes that "away" decision and reflects it onto the actual day, alongside punches, holidays, and shifts. Leave never touches Attendance's records directly, and Attendance never touches Leave's balance ledger directly — they only exchange information through this one filing cabinet (technically: a "leave day projection").

The practical consequence: if the attendance record for a date is already locked (because payroll has been run for that period), **Leave cannot record a new approved-leave day on it, and cannot cancel one either** — the whole action is refused, with no partial state. There is currently no in-between fix — the only remedy is fully reopening that pay period, which we flag below as a decision point (§5).

## 3. Major Policy Hierarchy

### Attendance — "which rule wins for a given day"

1. Is the person even employed on this date? (Not-yet-joined / active / exited) — if not, nothing else matters.
2. Is the configuration for this day fully set up? (If not, the system deliberately refuses to guess, rather than silently marking someone present or absent.)
3. Has HR specifically rostered this person off today? That wins even if the calendar says it's a working day.
4. What does the calendar say? (Holiday / weekly off / working day)
5. What do the actual punches say, combined with grace periods, late/early rules, and break rules?
6. **Is there approved leave for this day?** If so, by default, leave wins outright — even over a "day off" from the calendar.
7. Is there an approved "on duty" (e.g., client visit, official travel) record? This can be overridden by leave if both apply to the same day.

### Leave — "which rule wins for an application"

1. Which company policy applies to this specific employee, based on their shift, grade, department, branch, etc.? (Most specific always wins — an employee-specific rule beats a department rule, which beats a company-wide rule.)
2. Is the employee still on probation, and does this leave type allow leave during probation?
3. Does the requested range make sense (half-day only for single dates, reason provided if required, not too far in the past)?
4. Do the dates actually consume leave balance? (Weekly offs and holidays inside a leave range don't count against balance — unless they're "sandwiched" between two leave days, in which case they do.)
5. Is there enough balance? (Balance can never go negative — there is no "advance leave" today.)
6. Who needs to approve, and in what order? (Manager, then possibly department head, then possibly HR — whoever the system can't identify is skipped, never used as an excuse to block the request.)

## 4. Major Override Rules

- **A locked payroll period beats everything.** Once a period is closed, no punch, no regularization, no leave approval, and no leave cancellation can touch a date inside it. The only way back in is a full reopen, which is a deliberately separate, higher-permission action from closing a period.
- **Nobody can approve their own request.** This is true for regularizations, overtime, and leave, with no configuration setting able to turn it off.
- **A rejection at any approval stage is final.** There's no "send it back" — if HR rejects something a manager already approved, it's rejected, full stop.
- **Approved facts are never silently rewritten.** If a policy (like grace period minutes, or a leave carry-forward cap) changes later, everything already calculated or approved under the old policy stays exactly as it was — a change never reaches backward in time unless someone deliberately and explicitly asks for a backdated recalculation.

## 5. Cross-Module Interactions — What We Found

| Situation | What happens today |
|---|---|
| Employee has approved leave and also punched in/out that day | Leave wins by default — the day shows as a leave day, not a worked day (configurable to the opposite, but not recommended without discussion) |
| Employee has half-day leave and works the other half | The day is split cleanly — half paid as worked, half as leave |
| Employee's leave falls on a holiday or a weekly off | Doesn't use up their leave balance, unless it's sandwiched between two leave days on either side |
| Leave is approved, but the pay period for that date is already closed | The approval is blocked entirely — the system will not let it through partially |
| Leave is cancelled after approval, but the pay period is already closed | Same — blocked entirely, no partial undo |
| Employee has approved leave and also worked enough hours to earn overtime that day | **⚠️ Currently, both are simply recorded as true at the same time — nobody has decided whether overtime should still count on a day someone was also on leave.** This is the single most important open decision in this review. |

## 6. Open Client Decisions

These are the decisions we cannot make on your behalf. Each one currently has a default behaviour, but that default was a technical judgment call, not a business decision you've approved.

| # | Decision | What's the question? | Priority |
|---|---|---|---|
| 1 | **Leave vs. Overtime** | If someone is on approved leave, should any overtime they also logged that day still be paid/credited, or should leave cancel it out? | 🔴 Critical |
| 2 | **Fixing a mistake after payroll closes** | Right now, the only way to correct a leave or attendance record after a pay period is closed is to fully reopen that entire period. Do you want a narrower "fix just this one record" option instead? | 🔴 High |
| 3 | **Rostering vs. shift-based rules** | When HR temporarily moves someone to a different shift for a day, some of that shift's specific rules (like grace period) currently still use the person's *usual* shift instead of the one they're actually rostered to. Is that acceptable? | 🔴 High |
| 4 | **Backdated leave for closed periods** | An employee can currently submit a leave request for a date whose payroll period is already closed — it just fails much later, when someone tries to approve it. Should this be blocked immediately at submission instead? | 🔴 High |
| 5 | **Two leave requests, same type, overlapping dates** | Today, nothing stops an employee from submitting two overlapping requests for the *same* leave type (only different types are checked). Should that be blocked? | 🔴 High |
| 6 | **Night-shift overtime pay rate** | Overtime worked overnight is only classified as "night" if the whole shift is a designated overnight shift — not based on the actual clock time worked. Is this acceptable, or should any hours worked during night-time windows get night-rate treatment regardless of shift type? | 🔴 High |
| 7 | **Holiday landing on a weekly off** | If a public holiday falls on someone's regular day off, they currently do not get a substitute day off. Is that the intended policy? | 🟡 Medium |
| 8 | **Sandwich rule scope** | The "sandwich" rule (which pulls a weekend/holiday into paid leave count if it's surrounded by leave days) only looks within one leave request. Should it also apply across two separate back-to-back requests? | 🟡 Medium |
| 9 | **Advance/negative leave balance** | Employees currently cannot go into negative leave balance under any circumstance. Should advance leave ever be allowed? | 🟢 Low |
| 10 | **Approval delegation** | There is currently no way for a manager to delegate their approval authority while on leave/unavailable. Is this needed? | 🟡 Medium |

## 7. What Changes Are Required Before Sign-Off

- A written answer to each of the 10 decisions above (or explicit deferral, with a target date).
- A decision on whether the existing Attendance documentation set (written before Leave existed) should be updated now that Leave is live and actively feeds Attendance — several older documents still describe Leave as "a future module."
- Confirmation that the "locked period beats everything, no exceptions" rule is acceptable as a permanent design principle, or a request to scope a narrower correction mechanism (Decision #2 above).

## 8. Approval Section

| Role | Name | Decision | Date |
|---|---|---|---|
| Client Product Owner | | ☐ Approved as-is ☐ Approved with noted exceptions ☐ Not approved | |
| HR Lead | | ☐ Reviewed ☐ Reviewed with comments | |
| Implementation Lead | | ☐ Confirmed technically accurate | |

**Comments / exceptions:**

---

---

---

*This document accompanies the full technical audit set in `docs/business-rules/policies/`. For the underlying rule-by-rule detail, precedence tables, and code references behind every statement above, see `MASTER_POLICY_INVENTORY.md`, `MASTER_POLICY_PRECEDENCE_MATRIX.md`, `ATTENDANCE_LEAVE_INTERACTION_MATRIX.md`, and `MASTER_POLICY_DECISION_REGISTER.md` in the same folder.*

---

