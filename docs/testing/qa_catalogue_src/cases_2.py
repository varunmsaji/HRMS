from qa_lib import C, defaults

SYN = "Synthetic only: emails *@example.com, company 'QA-<tag>-<rand>'"
PS = "PRIVATE_STACK"
V1 = "docs/business-rules/ATTENDANCE_V1_COMPLETE.md"
STALE = ("ATTENDANCE_V1_* docs pre-date PAYROLL_BUSINESS_DECISIONS (2026-09-23/24): they still list night-OT mode, inert settings, "
         "leave module and legal-entity period grain as open/future. Treat PAYROLL_BUSINESS_DECISIONS + code as newer; confirm.")

# ------------------------------------------------------------------ ATTENDANCE: PUNCH
defaults(module="Attendance", src=V1 + " Stage 9; docs/modules/attendance/00_W4_ATTENDANCE_CORE_REPORT.md; ATTENDANCE_TIMEZONE_FINAL_PRE_IMPLEMENTATION_SPEC.md",
         pri="P0", role="EMPLOYEE (self) / HR_ADMIN (on behalf) T1", data=SYN + "; employee with Mon-Fri 09:00-18:00 shift, UTC company tz unless stated",
         env=PS, auto="AUTOMATED+LIVE_SCRIPT", pre="Employee with employment, shift, calendar, attendance policy assigned (org_setup-style fixture)")
C("ATT-PUNCH-001", "Self punch", "Employee punches IN/OUT via /me; server time is authoritative; bound to caller.",
  "201; punch.employee_id = caller; timestamp within 30 s of server now; client timestamp ignored/422; bad direction 422.",
  "1) POST /attendance/punches/me IN 2) with client timestamp 3) with direction=SIDEWAYS", live=["ATT-01", "ATT-05", "ATT-06"],
  tests=["integration/modules/attendance/test_attendance_day.py", "integration/modules/attendance/test_employee_default_role_attendance"],
  neg="Employee cannot punch as another employee.")
C("ATT-PUNCH-002", "Punch idempotency", "Same idempotency_key returns same punch; no duplicate rows; 10 parallel same-key requests create one row.",
  "1 punch row per (employee,key).", "1) replay 2) 10 parallel", live=["ATT-02", "ATT-03", "ATT-13", "ATT-14"],
  tests=["integration/modules/attendance/test_attendance_concurrency"], type="CONCURRENCY",
  inv="count(punch where employee_id=? and idempotency_key=?) == 1")
C("ATT-PUNCH-003", "Duplicate-punch window", "Two IN taps inside the policy duplicate window (e.g., 60 s) count as one for calculation.",
  "Worked minutes/pairs computed as if one IN; both raw punches retained (immutability).", "1) IN at t 2) IN with new key at t+5 s 3) OUT 4) calculate day",
  src=V1 + " §8 'Duplicate punch handling'", amb="Live script ran this probe (ATT-04) as INFO print only; result was NEVER recorded in register.csv (ID gap ATT-04). Expected value must come from the configured window.",
  tests=["unit/modules/attendance/test_calculation"], live=[])
C("ATT-PUNCH-004", "On-behalf punch (admin)", "Admins may record backdated punches for an employee; employees may not; future-dated and unknown-employee rejected.",
  "Employee 403; backdated 201; future 422/409; unknown 404/422.", "1) EMPLOYEE calls on-behalf 2) HR backdated 3) HR future 4) HR unknown id",
  live=["ATT-07", "ATT-08", "ATT-09", "ATT-10"], tests=["integration/modules/attendance/test_attendance_edge_cases", "integration/modules/attendance/test_attendance_security"])
C("ATT-PUNCH-005", "Punch cross-tenant", "T2 admin cannot punch for or read T1 punches.", "404/403; no rows.", "1) T2 calls", live=["ATT-11", "ATT-12"],
  tests=["integration/modules/attendance/test_attendance_security"], type="SECURITY")
C("ATT-PUNCH-006", "Punch immutability (K-1)", "`punch` is never UPDATEd or DELETEd; corrections are new rows (WD-11; Punch model docstring).",
  "As hrms_app: UPDATE and DELETE on punch are denied (permission error) and 0 rows change; TRUNCATE is denied (expected already denied - the grants test says the runtime role truncates nothing).",
  "1) connect as hrms_app with tenant context 2) UPDATE punch SET direction=... (inside a rolled-back txn) 3) DELETE 4) check has_table_privilege",
  live=["ATT-15"], tests=["integration/core/test_runtime_role_grants"], type="DB-INVARIANT", defect="K-1", status="NOT_RUN",
  amb="Product/security decision required to migrate (REVOKE UPDATE,DELETE,TRUNCATE for punch, attendance_regularization_action, attendance_period_action). NAMING COLLISION: 'D11' means 'pay date' in 00_PAYROLL_IMPLEMENTATION_PLAN.md and 'immutable history' in OBSERVABILITY_ARCHITECTURE.md §15 / test docstring.",
  risk="Run ONLY on a private disposable DB inside a ROLLED BACK transaction: the QA script ATT-15 executed an UNSCOPED `update punch set direction='IN'` that would have committed on success.",
  pri="P0")
C("ATT-PUNCH-007", "Business-date & timezone of a punch", "A punch is assigned to the employee's local business date from the resolved IANA zone (DEC-TZ), not the host clock.",
  "Punch at 23:30 local / next-day UTC lands on the local date; DST/zone-change boundaries behave per spec.", "1) company tz Asia/Kolkata 2) punch at UTC 19:00 3) read attendance date",
  src="docs/audits/ATTENDANCE_TIMEZONE_FINAL_PRE_IMPLEMENTATION_SPEC.md", tests=["unit/shared/test_timezone", "unit/shared/test_business_time", "integration/modules/attendance/test_break_cross_midnight"],
  type="BOUNDARY", amb="CI pins TZ=UTC; live QA ran TZ=UTC so host-timezone regressions are NOT exercised by the live pass.")
C("ATT-PUNCH-008", "Punch after last working day / outside employment", "Punches outside the employment period are refused or inert per DEC-TZ-05.",
  "Refused or stored-inert per spec; no calculation on non-employed dates.", "1) terminate employee 2) punch after last working day",
  tests=["integration/modules/attendance/test_punch_after_last_working_day", "integration/modules/attendance/test_regularization_employment_period"], pri="P1", auto="AUTOMATED")

# ------------------------------------------------------------------ ATTENDANCE: DAILY CALC
defaults(module="Attendance calc", src=V1 + " Stage 10, §8; ATTENDANCE_PAYROLL decisions", pri="P0",
         role="HR_ADMIN T1 (system calculation)", data=SYN + "; policy fixture grace_in=15, grace_out=10, bands per V1 §8 example", env=PS,
         auto="AUTOMATED", pre="Policy/shift/calendar assigned; punches inserted via on-behalf API")
C("ATT-DAY-001", "Punch to daily summary: normal present day", "IN 09:00 / OUT 18:00 on a working day yields PRESENT with worked minutes = 540 minus unpunched-break rules, 0 late/early.",
  "attendance_day.status=PRESENT; worked_minutes, late=0, early=0; engine_version stored.", "1) insert IN/OUT 2) POST /attendance/days/calculate 3) GET /attendance/days",
  tests=["unit/modules/attendance/test_calculation", "integration/modules/attendance/test_attendance_day.py", "unit/modules/attendance/test_evaluation_summary"],
  amb="NO live check asserts any attendance_day result: ATT live script printed calc/days responses as INFO and discarded them. Break-minute deduction expected value requires the fixture's break rule.")
C("ATT-DAY-002", "Late arrival grace and bands", "Arrival within grace_in is not late; beyond grace counts minutes after grace; late bands can force HALF_DAY/ABSENT.",
  "09:14 -> not late; 09:20 -> 5 min late; 45 min late with band '30+ => HALF_DAY' -> HALF_DAY.", "1) punch at each time 2) calculate",
  type="BOUNDARY", tests=["unit/modules/attendance/test_calculation", "integration/modules/attendance/test_policy_resolution"],
  amb="Inclusive/exclusive boundary at exactly grace minute (09:15:00 vs 09:15:59) must be confirmed from the engine; V1 doc does not state it.")
C("ATT-DAY-003", "Hour-based bands", ">=480 min present, 240-479 half-day, <240 absent (example policy).",
  "Status by worked minutes incl. boundary 239/240/479/480.", "1) punches yielding each worked-minute total", type="BOUNDARY",
  tests=["unit/modules/attendance/test_calculation", "unit/modules/attendance/test_policy_validation"])
C("ATT-DAY-004", "Missing punch handling", "Missing IN/OUT -> INCOMPLETE (default), or ABSENT/require-correction per policy.", "Per policy setting; never silently PRESENT.",
  "1) only IN 2) calculate 3) switch policy to ABSENT 4) recalc", tests=["unit/modules/attendance/test_calculation", "integration/modules/attendance/test_attendance_edge_cases",
  "integration/modules/attendance/test_incomplete_reminders"], amb="'Auto-close' is hidden/inert (PD-1); verify it is not selectable and has no effect.")
C("ATT-DAY-005", "Day types: holiday, weekly off, special working day", "Day type decided by exception > holiday > weekly off > working; hard holiday on weekly off keeps WEEKLY_OFF label.",
  "Not expected with no punches; present+flag when worked.", "1) configure calendar 2) calculate holiday/weekly-off/holiday-on-weekly-off/special working day",
  src=V1 + " §4", tests=["unit/modules/organisation/test_calendar_resolution", "integration/modules/organisation/test_workforce_calendar", "integration/modules/attendance/test_policy_resolution"],
  amb="PD-CAL-2 / BUS-010: no auto substitute holiday (approved: HR adds SUBSTITUTE_HOLIDAY manually).")
C("ATT-DAY-006", "Night / cross-midnight shift", "A shift crossing midnight assigns the whole shift to the start date; breaks crossing midnight handled; night OT classified per night_ot_mode.",
  "Single attendance_day; worked minutes continuous; OT day_class NIGHT per mode.", "1) 22:00-06:00 shift 2) punch 22:05 / 06:10 next day 3) calculate",
  tests=["integration/modules/attendance/test_break_cross_midnight", "unit/modules/attendance/test_night_ot"], amb=STALE)
C("ATT-DAY-007", "Recalculation idempotence & engine version", "Recalculating an unchanged day yields the same result; engine_version recorded; locked days refuse recalculation.",
  "Identical rows; locked -> refused with period-lock error.", "1) calculate twice 2) lock period 3) calculate", tests=["unit/modules/attendance/test_engine_version",
  "integration/modules/attendance/test_attendance_range_calculate", "unit/modules/attendance/test_range_calculation_enqueue", "integration/modules/attendance/test_sweep_concurrency"], type="REGRESSION+CONCURRENCY")
C("ATT-DAY-008", "Leave overlay on the day", "Approved leave sets status LEAVE (leave-wins default) with leave_fraction; half-day leave + worked time -> HALF_DAY; leave arriving later triggers recalculation; leave on locked date refused.",
  "Per V1 §11 table.", "1) calculate with punches 2) approve leave for the date 3) observe recalculation",
  src=V1 + " §11; PAYROLL_BUSINESS_DECISIONS BUS-012", tests=["integration/modules/attendance/test_leave_projection", "integration/modules/attendance/test_leave_projection_integrity"],
  amb="ND-04: Leave day retaining overtime/worked minutes (payroll-facing) is an open product decision. BUS-011 (OT on full-day leave not payable) is approved - verify suppression.")
C("ATT-DAY-009", "Employment boundary days", "Days before joining / after exit are NOT_JOINED/EXITED: paid 0, LOP 0, not_employed bucket (BUS-002).",
  "paid_day_fraction=0, lop=0, not_employed_days incremented.", "1) employee joins mid-month 2) calculate whole month", src="docs/audits/PAYROLL_BUSINESS_DECISIONS.md BUS-002",
  tests=["unit/modules/attendance/test_pay_basis", "unit/modules/attendance/test_period_summary"], pri="P0")
C("ATT-DAY-010", "Orphan attendance report", "Attendance data without a valid employment/policy is reported, not silently dropped.", "Report lists orphans.",
  "1) create orphan 2) run report", tests=["integration/modules/attendance/test_attendance_orphan_report"], pri="P2")

# ------------------------------------------------------------------ REGULARIZATION
defaults(module="Attendance regularization", src=V1 + " §12; docs/modules/attendance-regularization/00_W6_REGULARIZATION_IMPLEMENTATION_REPORT.md",
         pri="P0", role="EMPLOYEE requester; HR_ADMIN approver T1", data=SYN, env=PS, auto="AUTOMATED+LIVE_SCRIPT")
C("REG-FLOW-001", "Request -> approve -> punches written once", "Pending request writes no punches; approval writes exactly the requested punches (source REGULARIZATION) once; day recalculated from scratch.",
  "2 new punches; attendance_day recalculated; second approval 409 and no duplicate punches.", "1) employee requests 2) HR approves 3) approve again 4) read punches + day",
  live=["REG-01", "REG-02", "REG-06", "REG-07", "REG-08", "REG-09"], tests=["integration/modules/attendance/test_regularization.py"],
  inv="punch rows with source=REGULARIZATION for the request == requested count.",
  amb="Live pass printed the post-approval calculate result as INFO only (j5_reg.py:35): recalculated day status NOT asserted.")
C("REG-FLOW-002", "Reject path", "Rejection writes no punches, leaves terminal state; approve-after-reject refused.", "State REJECTED; punches unchanged.",
  "1) reject 2) approve", live=["REG-10", "REG-11", "REG-12"], tests=["integration/modules/attendance/test_regularization.py"])
C("REG-VAL-001", "Request validation", "Unknown type, missing correction payload, future date rejected.", "422 each.", "1) submit invalid variants",
  live=["REG-03", "REG-04", "REG-13"], tests=["integration/modules/attendance/test_regularization.py"])
C("REG-AUTHZ-001", "Authorization", "Employee cannot approve own request or submit for another employee; cross-tenant read denied.", "403/404.",
  "1) attempts", live=["REG-05", "REG-14", "REG-15"], tests=["integration/modules/attendance/test_attendance_security"], type="SECURITY")
C("REG-POL-001", "Regularization policy limits", "Backdating window, monthly request limit, allowed correction types and approval chain (Auto/Manager/HR/Manager->HR) enforced.",
  "Over-limit or disallowed type refused; chain routes to correct approver; self-approval blocked.", "1) configure limits 2) exceed each 3) approve through chain",
  tests=["integration/modules/attendance/test_overtime_regularization_policy"], auto="AUTOMATED", amb="Auto-approve-within-minutes is inert (PD-1). WFH/On-Duty types never produce a WFH/On-Duty status (ND-06).")
C("REG-LOCK-001", "Regularization on locked period", "No new request or approval can affect dates in a CLOSED period.", "Refused with period-lock error.",
  "1) close period 2) submit/approve for date inside", tests=["integration/modules/attendance/test_attendance_period"], auto="AUTOMATED")

# ------------------------------------------------------------------ SHIFTS / ROSTERS
defaults(module="Shifts & rosters", src=V1 + " §6; docs/modules/shift-version/00_W2_SHIFT_VERSION_REPORT.md; docs/modules/employee/14_EMPLOYEE_SHIFT_ASSIGNMENT_MODULE.md",
         pri="P1", role="HR_ADMIN T1", data=SYN, env=PS, auto="AUTOMATED",
         pre="Live pass covered these only via SWP sweep (garbage-input / unauth) - no deep live checks")
C("SHIFT-DEF-001", "Shift definition & versioning", "Shifts (fixed, flexible, split, night) validate times/breaks; versions are effective-dated, published immutable, non-overlapping.",
  "Invalid times 422; overlapping versions rejected; published version immutable.", "1) create each type 2) publish 3) edit published 4) overlapping version",
  tests=["integration/modules/organisation/test_shift.py", "integration/modules/organisation/test_shift_version.py", "unit/modules/organisation/test_shift_service",
  "unit/modules/organisation/test_shift_version_validation"], pri="P1")
C("SHIFT-ASSIGN-001", "Employee shift assignment", "An employee has at most one effective schedule per date; no assignment is valid ('no shift' rule).", "Assignment history non-overlapping; missing-shift rule applied.",
  "1) assign 2) overlapping assign 3) calculate with none", tests=["integration/modules/employee/test_employee_assignment"],
  amb="PD-BR14-SHIFT: default-shift cascade (branch->company) not implemented; confirm.")
C("SHIFT-ROSTER-001", "Roster create/publish", "Roster entries override schedule for dates; draft rosters block period finalize; publishing changes the working schedule.",
  "Published roster reflected in calculation; draft blocks finalize.", "1) create entry 2) publish 3) calculate 4) try finalize with draft",
  tests=["integration/modules/attendance/test_shift_roster"], pri="P1", amb="ND-02: shift-scoped policy still resolves from the ORIGINAL assigned shift, not the roster shift (product decision pending).")
C("SHIFT-ROSTER-002", "Bulk roster", "POST /rosters/bulk creates many entries atomically.", "All-or-nothing; limit respected; tenant-scoped.",
  "1) bulk of N valid 2) bulk with one invalid", tests=[], auto="NOT_AUTOMATED", amb="Backend only; neither client has UI (report §8). Atomicity not asserted anywhere I could find.", pri="P2")
C("SHIFT-FLEX-001", "Flexible / split shift behaviours", "Flexible-shift core hours and split-shift compensation are inert today; split missed-block rule applied.",
  "Core-hours breach has NO effect (documented); missed block follows configured behaviour.", "1) flexible shift with core hours 2) breach 3) split shift missing block",
  src="ATTENDANCE_V1_GAPS_AND_OPEN_DECISIONS Part 1", tests=["unit/modules/attendance/test_calculation"], amb="Documented 'inert' behaviour: test should assert the documented no-op until product decides.")

# ------------------------------------------------------------------ POLICIES
defaults(module="Attendance policies", src=V1 + " §8-9; docs/business-rules/policies/MASTER_POLICY_PRECEDENCE_MATRIX.md", pri="P1",
         role="HR_ADMIN T1", data=SYN, env=PS, auto="AUTOMATED")
C("POL-RESOLVE-001", "8-level policy precedence", "Most specific assignment wins (fixed order); ties/overlaps rejected.", "Resolved policy matches the 10 worked examples.",
  "1) create assignments at company/legal entity/branch/dept/designation/grade/shift/employee 2) resolve", src=V1 + " §9 (ten worked examples)",
  tests=["integration/modules/attendance/test_policy_resolution", "integration/modules/attendance/test_attendance_policy", "unit/modules/attendance/test_policy_validation"],
  amb="PD-POL-1/2: order fixed, grace only on policy.")
C("POL-VERSION-001", "Effective-dated policy versions", "Policy versions publish with effective_from; history preserved; no retroactive silent change.", "Resolution by date uses version in force.",
  "1) v1 2) v2 effective later 3) resolve before/after", src="docs/business-rules/policies/POLICY_EFFECTIVE_DATE_AND_HISTORY.md", tests=["integration/modules/attendance/test_attendance_policy"])
C("POL-INERT-001", "Inert settings hidden", "PD-1: settings the engine does not apply are hidden in UI/rejected on create while stored values round-trip.", "UI hides; API round-trips existing values.",
  "1) open policy screen 2) PATCH existing inert value", tests=["web/src/lib/attendance"], type="UI-E2E+API", auto="PARTIAL", env="BROWSER")

# ------------------------------------------------------------------ PERIODS
defaults(module="Attendance periods", src=V1 + " §14; PAYROLL_BUSINESS_DECISIONS BUS-007/008/012/016, PD-2/PD-3", pri="P0",
         role="HR_ADMIN T1", data=SYN, env=PS, auto="AUTOMATED", pre="Live pass: not deep-tested (needed for pay run to PAID)")
C("PER-LIFE-001", "Open -> validate -> finalize -> CLOSED", "Validate lists blockers (config errors, pending regularizations/OT, draft rosters, employees w/o records); finalize freezes summaries.",
  "Blockers block; after fix, CLOSED with frozen attendance_period_summary.", "1) create period 2) add each blocker 3) validate 4) fix 5) finalize",
  tests=["integration/modules/attendance/test_attendance_period", "unit/modules/attendance/test_period_summary"])
C("PER-LE-001", "Per-legal-entity periods", "Periods are per (company, legal entity), no overlap; employee dates owned by the entity of employment (BUS-007).", "Overlap 409/422; transfer splits correctly.",
  "1) two entities 2) overlapping 3) mid-month transfer", tests=["integration/modules/attendance/test_attendance_period_legal_entity", "unit/modules/attendance/test_period_legal_entity"],
  pri="P0", amb="Before deploying migration 20261004104000 to real data, a pre-check is required (migration docstring).")
C("PER-RECON-001", "Summary reconciliation invariant", "Every calendar day in exactly one bucket; sum(buckets)=calendar days; paid_days+lop_days+unpaid_off_days=payable_days.", "Invariant holds for every employee-period incl. joiners/leavers/half-days.",
  "1) build mixed month 2) finalize 3) assert invariants in DB", type="DB-INVARIANT", tests=["unit/modules/attendance/test_period_summary", "integration/modules/attendance/test_attendance_period"],
  src="PAYROLL_BUSINESS_DECISIONS 'Derived rules'")
C("PER-LOCK-001", "Incomplete at close", "Unresolved INCOMPLETE -> absent/LOP at close (default TREAT_ABSENT); reminders before cutoff.", "Paid fraction 0; label preserved.",
  "1) leave a day incomplete 2) finalize", tests=["integration/modules/attendance/test_incomplete_reminders", "integration/modules/attendance/test_attendance_period"],
  src="PAYROLL_BUSINESS_DECISIONS PAY-006/decision 16")
C("PER-WOL-001", "Work on approved-leave day blocks close", "BUS-012: conflict must be resolved by HR before close (cancel leave or keep leave); never paid twice.", "finalize blocked until resolved.",
  "1) approve leave 2) add punches 3) finalize", tests=["integration/modules/attendance/test_attendance_period"], pri="P0", amb="Verify HR resolution action exists (decision lists it as implementation item).")
C("PER-REOPEN-001", "Reopen semantics", "Reopen allowed before payroll finalisation with reason; blocked once payroll for the period is finalised (BUS-008); no automatic recompute.", "Reopen after finalised payroll -> refused.",
  "1) close 2) reopen 3) run+finalise payroll 4) reopen", tests=["integration/modules/attendance/test_attendance_period"], pri="P0",
  amb="ND-08 (auto-recompute) open. Confirm block-after-payroll is implemented.")
C("PER-LOCKED-001", "Locked-date refusals", "Closed period refuses punches (per DEC-TZ-05 rule), recalculation, roster edit, regularization, OT decision, leave apply/approve/cancel (PD-3).", "Each refused with stable code; no row changes.",
  "1) close 2) attempt each", tests=["integration/modules/leave/test_leave_period_lock", "integration/modules/attendance/test_attendance_period"], type="NEGATIVE")

# ------------------------------------------------------------------ OVERTIME
defaults(module="Overtime", src=V1 + " §13; docs/modules/overtime/00_W7_OVERTIME_IMPLEMENTATION_REPORT.md", pri="P1", role="HR_ADMIN / Manager T1",
         data=SYN, env=PS, auto="AUTOMATED", pre="No deep live checks (sweep only)")
C("OT-DETECT-001", "Detection, threshold, rounding, caps", "OT = worked - scheduled (>0), subject to eligibility, min threshold, rounding, daily/weekly/monthly caps.",
  "Minutes per formula; caps applied; boundaries at threshold/cap.", "1) vary worked minutes 2) calculate", type="BOUNDARY", tests=["integration/modules/attendance/test_overtime_record"],
  amb="Weekly/monthly caps depend on sibling days (documented simplification) - recalculation order effect.")
C("OT-CLASS-001", "Day classification", "Normal/Holiday/Weekly-off/Night classification; Night per night_ot_mode (SHIFT_FLAG|WINDOW|BOTH).", "Correct day_class per mode.",
  "1) OT on each day type", tests=["unit/modules/attendance/test_night_ot"], amb=STALE)
C("OT-APPR-001", "Approval chain & frozen decisions", "Approval per chain; self-approval blocked; decided records frozen against recalculation.", "Status transitions valid; frozen minutes unchanged.",
  "1) detect 2) approve 3) recalc", tests=["integration/modules/attendance/test_overtime_regularization_policy"])
C("OT-ELIG-001", "Eligibility 'by grade'", "BY_GRADE should restrict OT to eligible grades.", "CURRENT: behaves as ALWAYS (documented gap ND-07).",
  "1) configure BY_GRADE 2) ineligible-grade employee works OT", tests=[], amb="Requirement unclear: implement vs hide vs document. Do NOT record as FAIL until product owner decides.", pri="P1")
C("OT-LEAVE-001", "OT on full-day leave not payable", "BUS-011: OT suppressed on a full-day approved-leave day.", "ot minutes zero payroll-facing.", "1) leave day 2) punches beyond shift 3) calculate",
  src="PAYROLL_BUSINESS_DECISIONS BUS-011", tests=["integration/modules/attendance/test_leave_projection"], pri="P0")
C("OT-COMP-001", "Comp-off credit", "Approved OT may credit comp-off proportionally (minutes / day length, 2 dp); BUS-015 step rule NOT implemented.", "Credit = proportional; expiry 60 days default.",
  "1) approve OT with comp-off 2) read ledger", src="COMPOFF_POLICY_SAFETY_REVIEW.md", tests=["integration/modules/leave/test_leave_comp_off", "integration/modules/leave/test_leave_comp_off_safety",
  "integration/modules/leave/test_comp_off_employee_lifecycle"], amb="Decision 13 step rule (>=full shift=1, >=half=0.5) deliberately deferred: expected value for partial days is an OPEN decision.")

# ------------------------------------------------------------------ BACKGROUND TASKS
defaults(module="Background jobs", src="docs/operations/OBSERVABILITY_RUNBOOK.md; FUNCTIONAL_QA_REPORT §5/§9; core/celery_app.py", pri="P0",
         role="System (Celery worker + Beat)", data=SYN, env=PS, auto="AUTOMATED", pre="Private Redis DB for broker; PRIVATE worker; Beat NOT started against shared services")
C("JOB-LOOP-001", "DB tasks across event loops (DEF-02)", "Every DB-touching task runs correctly as the 2nd..Nth task in one worker process.", "No 'attached to a different loop' failure; consecutive tasks of different modules succeed.",
  "1) real worker concurrency=1 2) enqueue leave.accrue_company then attendance.calculate_company then import", tests=["integration/core/test_celery_task_event_loop", "unit/core/test_task_hardening",
  "integration/modules/attendance/test_attendance_tasks", "integration/modules/leave/test_leave_tasks_business_time", "unit/modules/leave/test_leave_task_hardening"],
  defect="DEF-02", inv="Task result persisted; no PENDING import batch left.")
C("JOB-BEAT-001", "Beat schedule maps to registered tasks", "All 10 Beat entries reference registered tasks on the correct queue; schedules sane.", "No unknown task names; queue routing per config.",
  "1) load schedule 2) compare with registry", tests=["unit/test_celery_queue_routing", "unit/test_termination_task_registration"], live=[],
  amb="Report states mapping verified; firing of Beat deliberately NOT run (no real accrual/payroll).")
C("JOB-RETRY-001", "Retry, failure logging, lifecycle events", "Failed tasks log structured failure, retry per policy, never lose the message; poison messages bounded.", "Retry count honoured; final failure recorded.",
  "1) inject failure 2) observe retries", tests=["unit/core/test_celery_task_failure_logging", "unit/core/test_celery_task_lifecycle_logging", "unit/core/test_celery_metrics", "unit/core/test_worker_logging"],
  amb="No test proves a retried non-idempotent task cannot double-apply side effects (accrual, termination sweep).")
C("JOB-IDEM-001", "Task idempotency / exactly-once effects", "Accrual, year-end, termination sweep, comp-off expiry, attendance sweep are safe to run twice and concurrently.", "No double credit/debit; advisory locks respected.",
  "1) run each twice and in parallel on identical data", tests=["integration/modules/leave/test_leave_accrual", "integration/modules/leave/test_leave_year_end_catchup",
  "integration/modules/attendance/test_sweep_concurrency", "integration/modules/leave/test_leave_lock_timeouts"], type="CONCURRENCY", inv="sum(leave_ledger) unchanged by second run.")
C("JOB-HEALTH-001", "Job health & readiness", "Job health/backlog monitors and /health endpoints report truthfully.", "ready=503 when dependency down; live=200.",
  "1) normal 2) stop Redis (private)", tests=["integration/core/test_job_health_and_readiness", "unit/ops/test_job_health", "unit/modules/health/test_router", "unit/modules/health/test_service"],
  live=["DEP-04", "DEP-05"])

# ------------------------------------------------------------------ OBSERVABILITY / CONFIG / NFR
defaults(module="Observability & core", src="docs/architecture/OBSERVABILITY_ARCHITECTURE.md; docs/operations/LOGGING_GUIDE.md", pri="P2",
         role="System", data="n/a", env="UNIT_OR_PRIVATE_STACK", auto="AUTOMATED")
C("OBS-LOG-001", "Structured logging & request context", "Access events, request ids and error logs are structured, correlated and PII/token-redacted.", "Redaction rules hold; request_id propagated.",
  "1) issue requests with tokens in path/body 2) inspect log sink", tests=["integration/core/test_http_access_event", "integration/core/test_request_context_and_error_logging",
  "integration/core/test_token_path_redaction", "unit/core/test_log_redaction", "unit/core/test_audit_redact", "unit/core/test_trace_correlation", "unit/core/test_unhandled_exception_logging",
  "unit/core/test_resilient_log_sink", "unit/core/test_proxy_headers", "unit/core/test_error_contract"], type="UNIT+API", pri="P1")
C("OBS-FILE-001", "File sinks, rotation, metrics", "File logging safe under tests (temp dir); metrics multiprocess; host monitor.", "No writes to real logs/ dir.", "1) run with LOG_TO_FILES tmp",
  tests=["unit/core/test_file_logging", "unit/core/test_metrics", "unit/core/test_metrics_multiprocess", "unit/core/test_observability_config", "unit/ops/test_host_monitor", "integration/core/test_db_metrics",
  "integration/core/test_business_events"], risk="host_monitor/file_logging tests use subprocess; verify they never touch real services.")
C("OBS-AUDIT-001", "Audit trail & security events", "Mutations write audit_log; security events emitted; audit append-only.", "audit rows exist per mutation.",
  "1) mutate 2) read audit_log", live=["AUD-01"], tests=["integration/auth/test_request_id_audit", "integration/auth/test_security_events", "integration/modules/leave/test_leave_audit_privacy"], pri="P0",
  amb="AUD-01 only asserts >=1 row containing 'EMPLOYEE' - not that EVERY listed mutation is audited.")
C("CFG-SET-001", "Settings guards & DB resilience", "Boot-time guards reject unsafe config; DB wait timeouts and failure classification.", "Unsafe config refuses start.",
  "1) load Settings with unsafe values", tests=["unit/core/test_settings", "unit/core/test_db_error_handler", "unit/core/test_db_wait_timeout_handler", "integration/test_db_wait_timeouts",
  "integration/core/test_db_failure_classification", "unit/core/db/models/test_identity", "unit/core/test_passwords", "unit/core/test_face_feature_gates"], pri="P1")
