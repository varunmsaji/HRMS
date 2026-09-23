# Master Policy Inventory — Attendance + Leave

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
