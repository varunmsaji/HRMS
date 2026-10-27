from qa_lib import C, defaults

SYN = "Synthetic only: emails *@example.com, company 'QA-<tag>-<rand>'"
PS = "PRIVATE_STACK"
PBD = "docs/audits/PAYROLL_BUSINESS_DECISIONS.md"
PLAN = "docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md"

# ------------------------------------------------------------------ LEAVE
defaults(module="Leave", src="docs/audits/PAYROLL_BUSINESS_DECISIONS.md (BUS-004..006,013); docs/testing/LEAVE_MODULE_AUDIT.md; docs/business-rules/policies/LEAVE_POLICY_PRECEDENCE.md",
         pri="P0", role="EMPLOYEE applicant; HR_ADMIN approver T1", data=SYN + "; leave type EL, opening balance 20.00 via ledger adjustment, Sunday weekly off",
         env=PS, auto="AUTOMATED+LIVE_SCRIPT", pre="Leave policy version published and assigned; calendar assigned; employment started 2024-01-01")
C("LEAVE-APPLY-001", "Apply (AUTO chain) debits balance", "A 1-day application under an AUTO approval chain is APPROVED immediately and debits exactly 1.00.", "Balance 20.00 -> 19.00; ledger has one DEBIT row.",
  "1) ledger adjustment +20 2) POST /leave-applications 1 day (Idempotency-Key)", live=["LV-01", "LV-02", "LV-03"], tests=["integration/modules/leave/test_leave_application.py"],
  inv="sum(leave_ledger.amount) == GET /leave-balances", neg="No second debit on re-read.")
C("LEAVE-APPLY-002", "Application idempotency", "Replayed Idempotency-Key returns the same application and never debits twice.", "Balance unchanged by replay.", "1) apply 2) replay same key",
  live=["LV-04", "LV-05"], tests=["integration/modules/leave/test_leave_idempotency"])
C("LEAVE-APPLY-003", "Overlap and over-balance rejection", "Overlapping dates and requests exceeding balance (negative balance off) are refused with unchanged balance.", "422/409 and balance unchanged.",
  "1) overlap with different key 2) request > balance", live=["LV-06", "LV-07", "LV-08", "LV-09"], tests=["integration/modules/leave/test_leave_balance_safety", "integration/modules/leave/test_leave_reserved_balance"],
  src=PBD + " BUS-005 (negative balance not allowed by default)")
C("LEAVE-APPLY-004", "Date validation & weekly-off handling", "End before start -> 422; application on weekly off consumes no balance (or is rejected) - never silently charged.", "No debit for non-working day.",
  "1) end<start 2) Sunday-only application", live=["LV-10", "LV-11"], tests=["integration/modules/leave/test_leave_application.py", "integration/modules/leave/test_leave_request_limits"],
  amb="LV-11 accepts 'rejected OR 0-day' - the exact expected behaviour (and the sandwich rule on adjacent working days) must be fixed by the product owner.")
C("LEAVE-APPLY-005", "Leave rules: probation, statutory minimum, maternity, combination, type semantics", "Policy-level constraints enforced.", "Violations refused with stable codes.",
  "1) apply under each constraint", tests=["integration/modules/leave/test_leave_probation_rules", "integration/modules/leave/test_leave_statutory_minimum", "integration/modules/leave/test_leave_maternity_fields",
  "integration/modules/leave/test_leave_combination_rule", "integration/modules/leave/test_leave_type_semantics", "integration/modules/leave/test_leave_employment_validity"], auto="AUTOMATED", pri="P1",
  amb="Statutory minimums (maternity etc.) are legal inputs - compliance sign-off, not engineering, defines expected values.")
C("LEAVE-APPR-001", "HR-chain approval", "Employee self-submit is PENDING under HR chain; HR approves -> debit exact days; double approve refused with no double debit; stale If-Match refused.", "Balance 10 -> 8 for 2 days; second approve 409.",
  "1) employee applies 2) HR approves 3) approve again 4) stale If-Match", live=["LV-27", "LV-28", "LV-32", "LV-33", "LV-34", "LV-35", "LV-36"], tests=["integration/modules/leave/test_leave_application.py", "integration/modules/leave/test_leave_approval_hod"],
  amb="LV-28 is VACUOUS (`... or True`): pending-state no-debit invariant is not actually asserted. Needs a real assertion (balance unchanged = 10.00 while PENDING; reserved balance semantics per test_leave_reserved_balance).")
C("LEAVE-APPR-002", "Authorization of decisions", "Employee cannot approve/reject (own) application; manager cannot cancel after approval (BUS-004); cross-tenant read denied.", "403/404.",
  "1) EMPLOYEE approve/reject 2) manager cancel approved", live=["LV-29", "LV-30", "LV-31", "LV-41"], tests=["integration/modules/leave/test_leave_rbac_matrix", "integration/modules/leave/test_leave_cancel_authorization"],
  src=PBD + " BUS-004", type="SECURITY")
C("LEAVE-APPR-003", "Reject pending", "HR rejects pending application; balance unchanged; terminal state.", "Balance stays 8.", "1) reject", live=["LV-37", "LV-38"], tests=["integration/modules/leave/test_leave_application.py"])
C("LEAVE-APPR-004", "Approval overdraw -> shortfall to LOP", "BUS-006: approval that would overdraw is rejected, or approved with excess days converted to LOP; never silently negative; re-checked under row lock.", "Whole-day split; partial-day balance unused (documented limitation).",
  "1) two applications racing for the same balance 2) approve both", src=PBD + " BUS-006/PAY-010", tests=["integration/modules/leave/test_leave_balance_races", "integration/modules/leave/test_leave_balance_safety"],
  amb="Whole-day-only LOP split leaves 0.5 balance unused - confirm acceptable (follow-up in decisions doc).")
C("LEAVE-CANCEL-001", "Cancel approved: restore once", "Cancel restores balance exactly once; second cancel refused; stale If-Match refused; employee may cancel before start, HR after start with reason (BUS-004).", "Balance back to 20.00 once.",
  "1) cancel 2) cancel again 3) cancel with stale version", live=["LV-12", "LV-13", "LV-14", "LV-15", "LV-16"], tests=["integration/modules/leave/test_leave_cancel_authorization"], src=PBD + " BUS-004")
C("LEAVE-CANCEL-002", "Cancel PENDING", "Employee cancels own PENDING application; ledger untouched.", "Balance unchanged.", "1) cancel pending", live=["LV-39", "LV-40"], tests=["integration/modules/leave/test_leave_application.py"])
C("LEAVE-CONC-001", "Concurrent applications", "6 parallel 4-day requests vs balance 20 -> balance never negative and == 20 - approved days; 6 identical-date requests -> exactly one accepted.", "5 of 6 approved, balance 0.",
  "1) fire parallel requests 2) read balance + ledger", live=["LV-17", "LV-18", "LV-19"], tests=["integration/modules/leave/test_leave_balance_races", "integration/modules/leave/test_leave_lock_timeouts"], type="CONCURRENCY",
  amb="Expected 'exactly 5 of 6' depends on request ordering only if each is 4 days (5x4=20); verify oracle is order-independent.")
C("LEAVE-LEDGER-001", "Ledger = balance invariant", "Balance == sum(leave_ledger) always; ledger is INSERT/SELECT-only for the runtime role; manual adjustments audited.", "Invariant holds after every scenario.",
  "1) after each leave scenario compare SQL sum with API", live=["LV-20", "LV-21"], tests=["integration/modules/leave/test_leave_ledger", "integration/modules/leave/test_leave_ledger_safety", "integration/modules/leave/test_leave_hardening"],
  type="DB-INVARIANT", inv="sum(amount) per (employee, leave_type) == balance", risk="LV-21 static grants check must be run on a private DB only.")
C("LEAVE-POL-001", "Leave policy versions & assignment", "Versions are effective-dated; publish requires If-Match; assignments resolve by scope.", "Resolution by date correct.",
  "1) create/publish 2) assign 3) resolve", tests=["integration/modules/leave/test_leave_policy", "unit/modules/leave/test_approval_chain", "integration/modules/leave/test_leave_reassign_approver"], auto="AUTOMATED", pri="P1",
  amb="reassign-approver endpoint has no UI in either client.")
C("LEAVE-YEAR-001", "Accrual and year-end", "Accrual per policy; year-end: CL lapses, SL/EL carry forward to cap, excess encashed or lapsed per policy (BUS-013); catch-up runs idempotent.", "Ledger entries ACCRUAL/CARRY/LAPSE/ENCASHMENT with exact amounts.",
  "1) set policy 2) run accrual/year-end for fixture year 3) re-run", tests=["integration/modules/leave/test_leave_accrual", "integration/modules/leave/test_leave_year", "unit/modules/leave/test_year", "integration/modules/leave/test_leave_year_end_catchup"],
  src=PBD + " BUS-013", type="BOUNDARY", auto="AUTOMATED", amb="Carry-forward cap numbers (30-45 EL days) are policy inputs per customer; oracle must come from fixture policy.")
C("LEAVE-ENC-001", "Encashment", "Encashment debits balance and creates ENCASHMENT entry picked up by payroll at Basic/days-in-month (D4).", "Debit exact; payroll line matches.", "1) request encashment (Idempotency-Key) 2) approve",
  tests=["integration/modules/leave/test_leave_encashment"], auto="AUTOMATED", pri="P0")
C("LEAVE-LOCK-001", "Leave vs closed attendance period", "PD-3: leave apply/approve/cancel for a closed date is refused; whole approval transaction rolls back.", "No ledger change on refusal.",
  "1) close period 2) approve leave in range", tests=["integration/modules/leave/test_leave_period_lock"], auto="AUTOMATED", src=PBD + " PD-3")
C("LEAVE-COMP-001", "Comp-off lifecycle", "Credit, expiry (60 days), redemption concurrency-safe under advisory lock.", "Single expiry per credit.", "1) credit 2) run expiry sweeps concurrently",
  tests=["integration/modules/leave/test_leave_comp_off", "integration/modules/leave/test_leave_comp_off_safety", "integration/modules/leave/test_comp_off_employee_lifecycle"], auto="AUTOMATED", type="CONCURRENCY")

# ------------------------------------------------------------------ PAYROLL
defaults(module="Payroll", src=PLAN + "; " + PBD + "; docs/audits/PAYROLL_FOUNDATION_CONTRACT.md", pri="P0",
         role="HR_ADMIN (maker) + COMPANY_ADMIN/PAYROLL.RUN_APPROVE (checker) T1", env=PS, auto="AUTOMATED",
         data=SYN + "; Oct-2026 (31 days) unless stated; legal entity LE-1; synthetic salary structure",
         pre="CLOSED attendance period for (legal entity, month); salary assigned; statutory rates present")
C("PAYROLL-FLOW-001", "Pay run state machine guards", "DRAFT run cannot compute/approve/finalise/mark-paid; duplicate (entity, month) -> 409; invalid month -> 422; unknown entity -> 404/422; refused transitions leave DRAFT.", "Per PAY-01..11.",
  "1) create 2) attempt each illegal transition", live=["PAY-01", "PAY-02", "PAY-03", "PAY-04", "PAY-05", "PAY-06", "PAY-07", "PAY-08", "PAY-10", "PAY-11", "PAY-24"], tests=["integration/modules/payroll/test_pay_run"], auto="AUTOMATED+LIVE_SCRIPT")
C("PAYROLL-FLOW-002", "Lock inputs requires CLOSED period (PD-2)", "Payroll refuses any attendance period not CLOSED; reads per legal entity.", "409/422 PAY_RUN_PERIOD_NOT_CLOSED-style error.",
  "1) lock-inputs with open period 2) close 3) lock", live=["PAY-09"], tests=["integration/modules/payroll/test_pay_run"], src=PBD + " PD-2", auto="AUTOMATED+LIVE_SCRIPT")
C("PAYROLL-FLOW-003", "Full run to PAID (happy path)", "DRAFT -> inputs locked -> computed -> validated -> approved -> finalised (periods frozen, payslips published) -> PAID.", "Each transition audited; payslips visible to employees only after FINALISED.",
  "1) close period 2) lock 3) compute 4) resolve variance reasons 5) approve (different user) 6) finalise 7) mark paid", tests=["integration/modules/payroll/test_pay_run", "integration/modules/payroll/test_payslip"],
  amb="NOT exercised live (needs closed attendance periods). Only the project's own integration test covers it.", pri="P0", type="API-E2E")
C("PAYROLL-FLOW-004", "Maker-checker (D9)", "The user who prepared/computed a run cannot approve it.", "403/409 for same user; succeeds for different user with PAYROLL.RUN_APPROVE.", "1) same-user approve 2) other-user approve",
  tests=["integration/modules/payroll/test_pay_run"], type="SECURITY")
C("PAYROLL-FLOW-005", "Inputs changed after lock (PD-4)", "A payroll input changing after INPUTS_LOCKED blocks approval/finalisation with 409 PAY_RUN_INPUTS_CHANGED; never auto-converted to arrears.", "Run unchanged; rollback to draft required.",
  "1) lock inputs 2) change salary/attendance input 3) approve", tests=["integration/modules/payroll/test_p1_hardening", "integration/modules/payroll/test_pay_run"], src=PBD + " PD-4")
C("PAYROLL-FLOW-006", "Variance gate (D10)", "Net pay change >15% (company-configurable) vs previous finalised run needs a reason before approval.", "Approval blocked until reason recorded.",
  "1) two consecutive runs with >15% delta 2) approve", tests=["integration/modules/payroll/test_pay_run"], type="BOUNDARY", amb="Boundary exactly 15.00% inclusive/exclusive not stated.")
C("PAYROLL-FLOW-007", "Concurrency & atomicity of finalise", "Concurrent finalise/approve is serialised; session commits before response (B01); idempotent adjustments (B04).", "One finalise wins; no duplicate payslips/lines.",
  "1) parallel finalise 2) parallel adjustment posts with same key", live=["PAY-26"], tests=["integration/modules/payroll/test_b01_session_commit", "integration/modules/payroll/test_b04_adjustment_idempotency"], type="CONCURRENCY", inv="One payslip per employee per run.",
  auto="AUTOMATED+LIVE_SCRIPT")
C("PAYROLL-FLOW-008", "Finalised data immutability", "Finalised/PAID run lines & payslips cannot be modified (DB level).", "UPDATE/DELETE rejected for hrms_app.", "1) attempt as hrms_app", tests=["integration/modules/payroll/test_b05_db_immutability"], type="DB-INVARIANT")
C("PAYROLL-AUTHZ-001", "Payroll authorization & tenancy", "EMPLOYEE has no access to runs, components, statutory rates, settings; cannot create/approve; T2 cannot read/transition/create against T1.", "403/404.",
  "1) EMPLOYEE attempts 2) T2 attempts", live=["PAY-12", "PAY-13", "PAY-14", "PAY-15", "PAY-16", "PAY-17", "PAY-18", "PAY-19", "PAY-20", "PAY-21"], tests=["integration/modules/payroll/test_pay_run"], type="SECURITY", auto="AUTOMATED+LIVE_SCRIPT")
C("PAYROLL-SLIP-001", "Payslip visibility", "Employees list only own payslips from FINALISED/PAID runs; others 404; HR preview before finalise; PAN masked; Aadhaar never decrypted.", "Own-only; non-finalised -> 404.",
  "1) employee list before/after finalise 2) other employee's id", live=["PAY-22", "PAY-23"], tests=["integration/modules/payroll/test_payslip", "unit/modules/payroll/test_words"], auto="AUTOMATED+LIVE_SCRIPT")
C("PAYROLL-ADJ-001", "Payroll adjustments", "POST /payroll/adjustments requires Idempotency-Key and a valid run; unknown run 404/422.", "Without key 400/422; replay returns same row.", "1) post without key 2) with key twice",
  live=["PAY-25", "PAY-26"], tests=["integration/modules/payroll/test_b04_adjustment_idempotency"], auto="AUTOMATED+LIVE_SCRIPT")
C("PAYROLL-ARR-001", "Arrears", "Backdated salary changes and D7 day corrections to finalised months are paid as per-component arrears in the next run, month-wise breakup, never paid twice.", "Arrears line = difference; second run does not repeat.",
  "1) finalise month M 2) correct attendance/salary of M 3) run M+1 4) run M+2", tests=["integration/modules/payroll/test_arrears"], src=PBD + " BUS-008/D7")
C("PAYROLL-CALC-001", "Proration by calendar days (BUS-016) - independent oracle", "Monthly salary x paid_days / days_in_month. Example: Basic 15,000.00, Oct (31d), paid_days 26 -> 15000 x 26 / 31 = 12,580.645161...",
  "Engine earned amount equals oracle to the rounding rule once rounding is confirmed.", "1) build snapshot with paid_days=26 2) compute 3) compare with independently computed value (spreadsheet/python Decimal)",
  tests=["unit/modules/payroll/test_engine", "integration/modules/payroll/test_pay_run"], type="UNIT+ORACLE",
  amb="Rounding of earned (prorated) components: structure BREAKUP rounds to the rupee, net pay is NOT rounded (D8) - the rounding point for each prorated line (paise vs rupee) is not stated; product owner must confirm before an equality assertion is written.")
C("PAYROLL-CALC-002", "Month-length sensitivity", "Same paid fraction in a 28-day month gives different amount: 15000 x 26 / 28 = 13,928.571428...; 30-day: 13,000.00.", "Matches oracle for 28/29/30/31.",
  "1) compute for Feb 2026 (28), Feb 2028 (29), Apr (30), Oct (31)", tests=["unit/modules/payroll/test_engine"], type="BOUNDARY+ORACLE", amb="Same rounding ambiguity as PAYROLL-CALC-001.")
C("PAYROLL-CALC-003", "Joiner/leaver/segments", "Paid days apportioned across salary segments by employed days; days before joining / after exit neither paid nor LOP (BUS-002).", "Sum of segment paid days == paid_days; not_employed excluded.",
  "1) join 2026-10-11 2) salary change 2026-10-21 3) compute", tests=["unit/modules/payroll/test_engine", "unit/modules/attendance/test_period_summary"], type="UNIT+ORACLE", src=PBD + " BUS-002/BUS-016")
C("PAYROLL-CALC-004", "Overtime pay (D3)", "OT pay = Basic / (days_in_month x 8) x multiplier x OT hours; daily-wage: daily rate / 8. Example: 15000/(31x8)=60.483871/h; 3 h at 2.0x = 362.903226.", "Matches oracle; OT on full-day leave = 0 (BUS-011).",
  "1) snapshot with 180 approved OT minutes class HOLIDAY multiplier 2.0 2) compute", tests=["unit/modules/payroll/test_engine", "unit/modules/attendance/test_night_ot"], type="UNIT+ORACLE",
  amb="D3 says '(Basic + DA)'; DA component presence/definition not verified. Whether approved minutes taken as comp-off are excluded is stated in plan (yes).")
C("PAYROLL-CALC-005", "Leave encashment (D4)", "Per-day = Basic / days_in_month; 2 days in Oct = 2 x 15000/31 = 967.741935.", "Matches oracle.", "1) ENCASHMENT ledger entry of 2 days 2) compute", tests=["unit/modules/payroll/test_engine", "integration/modules/leave/test_leave_encashment"], type="UNIT+ORACLE")
C("PAYROLL-CALC-006", "Daily-wage employee (BUS-001/D5)", "Pay = daily_rate x paid_days; national/festival holidays paid, weekly offs unpaid. Example: 800 x 22 = 17,600.00.", "Matches oracle; salary-basis mismatch validation SALARY_BASIS_MISMATCH.",
  "1) DAILY_WAGE employee 2) compute", tests=["unit/modules/payroll/test_engine", "unit/modules/attendance/test_pay_basis"], type="UNIT+ORACLE", src=PBD + " BUS-001")
C("PAYROLL-CALC-007", "Salary structure breakup (D1/D2)", "Gross + employer contributions = monthly CTC exactly; Basic 50% of gross; HRA 40% (metro 50%) of Basic; special allowance balances; employer PF 12% of Basic capped 1,800.", "Sum identity holds to paise; lines round to rupee, balancing absorbs rest.",
  "1) CTC 600000 (monthly 50000) 2) solve breakup 3) check identity", tests=["unit/modules/payroll/test_breakup", "integration/modules/payroll/test_salary_structure", "integration/modules/payroll/test_b03_component_codes"], type="UNIT+ORACLE")
C("PAYROLL-STAT-001", "PF / ESI / PT / LWF engines", "PF 12% of PF wages capped at 15,000 ceiling (1,800), half-up to rupee; ESI 0.75% employee / 3.25% employer, ceiling 21,000, rounded up to next rupee; PT by state slab; LWF in rate months. Example ESI wages 20,000 -> employee 150, employer 650.",
  "Matches oracle for each boundary (ceiling-1, ceiling, ceiling+1).", "1) vary wages around ceilings 2) compute", tests=["unit/modules/payroll/test_statutory", "integration/modules/payroll/test_statutory_rate"], type="BOUNDARY+ORACLE",
  amb="Seeded rates are UNVERIFIED (verified_at null): approval must be blocked until compliance verifies (STATUTORY_UNVERIFIED). Real expected rates require compliance sign-off - engineers must not assert them as truth. Known limits: PF admin minimum Rs500 not applied; EPS eligibility age-only.")
C("PAYROLL-TDS-001", "Income tax (TDS), new regime", "Section 192 average-rate method using year-to-date pay; base version excludes declarations, previous-employer income, surcharge.", "Matches an externally computed TDS for FY slabs supplied by compliance.",
  "1) multi-month YTD fixture 2) compute month TDS", tests=["unit/modules/payroll/test_income_tax", "integration/modules/payroll/test_income_tax"], type="UNIT+ORACLE",
  amb="Tax slabs are legislation + product scope (declarations absent). Expected values must be supplied by a qualified payroll/compliance owner; do not derive here.")
C("PAYROLL-NET-001", "Net pay not rounded (D8); negative/zero net", "Net pay paid to the paisa; NEGATIVE_NET blocks approval; ZERO_NET warning.", "No rounding_minor; validation codes as listed.",
  "1) compute fixtures with deductions > earnings", tests=["unit/modules/payroll/test_engine", "integration/modules/payroll/test_b02_paid_days"], type="BOUNDARY", defect="")
C("PAYROLL-BANK-001", "Bank advice CSV", "COMPANY_ADMIN only, on demand, audited; masked account in snapshot; CSV injection-safe.", "Others 403; access logged; fields escaped.", "1) download as admin/HR/employee",
  tests=["integration/modules/payroll/test_payslip", "integration/modules/payroll/test_pay_run"], type="SECURITY", amb="CSV formula-injection (=, +, -, @ prefixes in names) not seen in any test name.")
C("PAYROLL-PIN-001", "Payroll vs attendance reconciliation", "paid_days + lop_days + unpaid_off_days = payable_days flows unchanged from frozen summary into the payroll snapshot.", "Snapshot equals summary.",
  "1) finalise period 2) lock payroll inputs 3) diff", tests=["integration/modules/payroll/test_b02_paid_days"], type="DB-INVARIANT")

# ------------------------------------------------------------------ PLATFORM CONSOLE
defaults(module="Platform console", src="docs/operations/PLATFORM_CONSOLE.md; docs/design/SUPER_ADMIN_PLATFORM_CONSOLE_PLAN.md", pri="P0",
         role="Platform super admin (type=platform token) vs tenant COMPANY_ADMIN", env=PS, auto="AUTOMATED",
         data=SYN + "; platform admin created via private-DB script only", pre="COMPANY_APPROVAL_REQUIRED=true (production default). The live pass ran with it FALSE, so approval flow was not exercised.")
C("PLAT-AUTHZ-001", "Token separation", "Tenant tokens rejected on /v1/platform; platform tokens rejected on every tenant route; platform token 30 min, not refreshable, revocable session.", "401/403 both ways.",
  "1) tenant token -> /v1/platform/* 2) platform token -> tenant routes (full OpenAPI sweep)", live=["RBAC-14"], tests=["integration/modules/platform/test_platform_console"], type="SECURITY",
  amb="Live RBAC-14 only checked 3 GET routes for a tenant admin; reverse direction and full route sweep not live-tested.", auto="AUTOMATED+LIVE_SCRIPT")
C("PLAT-LIFE-001", "Company lifecycle state machine", "PENDING_APPROVAL -approve-> TRIAL <-> ACTIVE; suspend/reactivate; reject/approve; terminate (typed company name, reason); illegal transitions refused.", "Matches diagram; reasons mandatory for reject/suspend/terminate.",
  "1) register with approval ON 2) walk every transition and every illegal one", tests=["integration/modules/platform/test_platform_console"], inv="company.status and platform_audit_log row per action.")
C("PLAT-ACCESS-001", "Status-based tenant access", "PENDING/SUSPENDED: read yes, write 403 (COMPANY_PENDING_APPROVAL/SUSPENDED); REJECTED/TERMINATED: no sign-in; effective on next request; auth writes (logout, refresh) still allowed; scheduled jobs skip non-TRIAL/ACTIVE.", "Per table in PLATFORM_CONSOLE.md.",
  "1) put tenant into each status 2) login/read/write/refresh", tests=["integration/modules/platform/test_platform_console", "unit/core/test_company_access"], type="SECURITY")
C("PLAT-AUDIT-001", "Platform audit log append-only", "Every platform action writes platform_audit_log; UPDATE/DELETE rejected by trigger for EVERY role and by missing grants; company audit_log gets COMPANY_STATUS_CHANGED_BY_PLATFORM.", "Mutation attempts fail.",
  "1) perform actions 2) attempt UPDATE/DELETE as owner and hrms_app", tests=["integration/modules/platform/test_platform_console", "integration/core/test_runtime_role_grants"], type="DB-INVARIANT")
C("PLAT-ADMIN-001", "Platform admin management guards", "Cannot disable self or last active admin; disabling/reset signs target out at once; username format; password policy gap.", "Guards enforced; sessions revoked.",
  "1) disable self 2) disable last admin 3) reset another admin's password and use old session", tests=["integration/modules/platform/test_platform_console"], amb="MFA not implemented (deferred); reverse-proxy allow-list is an operations control not testable in app tests.")
C("PLAT-SUB-001", "Plan / seat / trial operations", "Plan change, seat override, trial extension, unlock admin, resend verification obey rules (trial 14 days from APPROVAL; reactivate returns to TRIAL if not ended else ACTIVE).", "Dates and statuses exact.",
  "1) approve 2) extend trial 3) suspend/reactivate before and after trial end (clock control)", tests=["integration/modules/platform/test_platform_console"], type="BOUNDARY")
C("PLAT-LOG-001", "Log viewer", "Platform log viewer is platform-only, paginated, redacts secrets/PII, bounded file reads (no path traversal).", "Tenant access denied; no raw tokens in output.",
  "1) request logs as platform/tenant 2) traversal-shaped file names", tests=["integration/modules/platform/test_log_viewer"], type="SECURITY")
C("PLAT-UI-001", "Platform console web pages", "Dashboard, companies, detail actions, admins, audit log render and act correctly (web /platform).", "Matches API; destructive actions need confirmation.",
  "1) drive /platform in browser against private stack", tests=["web/src/lib/platform"], type="UI-E2E", auto="PARTIAL", env="BROWSER", amb="No browser run done; only vitest on lib layer.")

# ------------------------------------------------------------------ WEB / MOBILE
defaults(module="Web", src="apps/web; FUNCTIONAL_QA_REPORT §8", pri="P1", role="Per workflow", data=SYN, env="BROWSER+PRIVATE_STACK", auto="PARTIAL")
C("WEB-AUTH-001", "Register / verify / login UI", "User can register, verify email via token page, log in; error states shown.", "Redirect to app; errors inline.", "1) browser flow against private stack",
  tests=["web/src/app/login", "web/src/app/register", "web/src/app/verify-email", "web/src/lib/auth", "web/src/app/accept-invite"], type="UI-E2E", pri="P0", amb="Browser flow NOT run in the QA pass (no browser session); vitest unit only.")
C("WEB-ATT-001", "Attendance screens (punch, days, periods, policies, shifts)", "UI reflects API state, loading/empty/error states.", "Per component tests.", "1) browser walk-through",
  tests=["web/src/lib/attendance", "web/src/components/attendance", "web/src/components/attendance-period", "web/src/app/app/shifts", "web/src/lib/shift", "web/src/lib/shift-roster",
  "web/src/lib/regularization", "web/src/app/app/regularizations", "web/src/app/app/attendance", "web/src/app/app/overtime"], type="UI-E2E")
C("WEB-LEAVE-001", "Leave application UI", "Employee applies with Idempotency-Key; errors surfaced.", "Header sent; success state.", "1) apply via UI and inspect request",
  tests=["web/src/components/leave-application"], type="UI-E2E", pri="P0")
C("WEB-PAY-001", "Payroll UI", "Pay run list/detail/transitions/payslips; Idempotency-Key on adjustments.", "Per tests.", "1) walk pay run in UI", tests=["web/src/components/payroll", "web/src/lib/payroll", "web/src/app/app/payroll"], type="UI-E2E", pri="P0")
C("WEB-ORG-001", "Organisation & setup UIs", "Master data pages and setup wizard work.", "Per tests.", "1) walk each master page",
  tests=["web/src/lib/branch", "web/src/lib/department", "web/src/lib/designation", "web/src/lib/grade", "web/src/lib/legal-entity", "web/src/lib/company", "web/src/lib/holiday-calendar",
  "web/src/lib/work-calendar", "web/src/lib/weekly-off-pattern", "web/src/app/app/setup", "web/src/components/common", "web/src/lib/api", "web/src/app/app/branches", "web/src/app/app/company", "web/src/app/app/dashboard", "web/src/app/app/departments", "web/src/app/app/designations", "web/src/app/app/grades", "web/src/app/app/legal-entities", "web/src/app/app/layout"], type="UI-E2E", pri="P2")
C("WEB-CONTRACT-001", "Static web->API contract", "Every literal API call in web matches an OpenAPI operation.", "0 mismatches (220 distinct calls per report).", "1) run docs/testing/qa_live_2026-10-25/coverage.py with web/mobile source",
  type="STATIC", auto="LIVE_SCRIPT_ONLY", env="UNIT", pri="P1", amb="coverage.py takes a scratchpad path argument and reads relative 'web/' 'mobile/' dirs (not re-runnable as-is). Only literal call sites visible.")
C("WEB-BUILD-001", "Production build", "`next build --webpack` succeeds.", "Exit 0.", "1) npm ci 2) npx next build --webpack", type="BUILD", env="UNIT", auto="CI_ONLY", pri="P1", amb="Not run in QA pass.")
C("WEB-LINT-001", "ESLint backlog", "ESLint clean (CI step is non-blocking by design).", "0 errors target; current 110 (97x react-hooks/set-state-in-effect).", "1) npx eslint . (read-only)",
  type="STATIC", env="UNIT", auto="CI_ONLY", pri="P2", defect="TD-LINT-01")
C("WEB-A11Y-001", "Accessibility & responsive layout", "Key flows keyboard-operable; layouts usable at mobile widths.", "No blocking a11y issues.", "1) axe scan + keyboard walk", type="UI-E2E", auto="NOT_AUTOMATED", pri="P2", amb="No a11y requirement found in docs (NFR doc exists: 23_Non_Functional_Requirements) - confirm target level.")
C("WEB-IMPORT-001", "Employee import UI", "n/a - no UI exists.", "n/a", "n/a", status="NOT_APPLICABLE", type="UI-E2E", auto="N/A", pri="P2")

defaults(module="Mobile", src="apps/mobile; FUNCTIONAL_QA_REPORT §8", pri="P1", role="Per workflow", data=SYN, env="FLUTTER", auto="PARTIAL")
C("MOB-RUN-001", "Flutter analyze + unit/widget tests", "`flutter analyze` and `flutter test` pass on the pinned SDK (3.29.2 in CI).", "0 issues; all 278 test() cases pass (static count).", "1) install SDK in isolated env 2) flutter pub get 3) analyze 4) test",
  status="BLOCKED", actual="BLOCKED: Flutter/Dart not on PATH (verified this phase: `which flutter dart` empty). Prior report agrees.", type="BUILD", pri="P0", defect="ENV-BLK-FLUTTER")
C("MOB-AUTH-001", "Mobile auth & deep links", "Login, token storage, deep links (invite/verify/reset) work.", "Per tests.", "1) widget tests 2) device/emulator walk", tests=["mobile/test/deep_link_test", "mobile/test/core"], type="MOBILE-E2E", status="BLOCKED")
C("MOB-ATT-001", "Mobile attendance, regularization, rosters", "Punch, history, regularization, roster screens.", "Per tests.", "1) widget tests 2) device walk",
  tests=["mobile/test/attendance", "mobile/test/request_screens", "mobile/test/rosters", "mobile/test/time_test", "mobile/test/policy_resolution", "mobile/test/policy_assignments", "mobile/test/versioned_resources"], type="MOBILE-E2E", status="BLOCKED")
C("MOB-LEAVE-001", "Mobile leave + Idempotency-Key", "Leave apply sends Idempotency-Key; decimals parsed; If-Match headers sent.", "Headers present; parse exact.", "1) widget tests",
  tests=["mobile/test/leave_applications_test", "mobile/test/leave_decimal_parsing_test", "mobile/test/if_match_headers_test"], type="MOBILE-E2E", status="BLOCKED", pri="P0")
C("MOB-PAY-001", "Mobile payroll screens", "Payslip/payroll screens render.", "Per tests.", "1) widget tests", tests=["mobile/test/payroll"], type="MOBILE-E2E", status="BLOCKED", pri="P0")
C("MOB-ORG-001", "Mobile profile/onboarding/org/setup", "Employee record, onboarding wizard, org resources, setup/bulk-assign.", "Per tests.", "1) widget tests",
  tests=["mobile/test/employee_record", "mobile/test/onboarding", "mobile/test/public_onboarding", "mobile/test/form_spec", "mobile/test/company_", "mobile/test/resource_screens", "mobile/test/setup_and_bulk_assign"], type="MOBILE-E2E", status="BLOCKED", pri="P2")
C("MOB-CONTRACT-001", "Mobile contract fixtures + live contract test", "Fixture parsing matches API; live test (HRMS_LIVE_API=1, read-only GETs + login) against a PRIVATE stack.", "No drift.", "1) contract_fixtures_test 2) HRMS_LIVE_API=1 flutter test test/live (private stack only)",
  tests=["mobile/test/contract_fixtures_test", "mobile/test/live"], type="CONTRACT", status="BLOCKED", risk="Live test targets http://localhost:8000 by default - the SHARED dev API port. Point to the private QA API (18000) only.")
C("MOB-CONTRACT-002", "Static mobile->API contract", "Every literal mobile API call matches OpenAPI.", "0 real mismatches (117 calls, 4 scanner artefacts hand-verified, per report).", "1) coverage.py", type="STATIC", auto="LIVE_SCRIPT_ONLY", env="UNIT")

# ------------------------------------------------------------------ ENVIRONMENT
defaults(module="Environment & tooling", src="FUNCTIONAL_QA_REPORT §2/§12; docs/testing/FULL_TEST_SUITE.md; .github/workflows/ci.yml", pri="P0", role="Operator", data="n/a", env="HOST", auto="NOT_AUTOMATED", type="INFRA")
C("ENV-DISK-001", "Root partition capacity", "Test and dev infra must have free space for Postgres/MinIO writes.", "Free space >= agreed headroom on `/` (and on the volume holding MinIO/Postgres).",
  "1) df -h / and the Docker data-root", status="FAIL", actual="VERIFIED 2026-10-25 this phase: `df -h /` -> /dev/nvme0n1p6 560G size, 526G used, 5.0G avail, 100%. Data root location of hrms-minio volume not inspected.", evidence="command output captured in QA_BASELINE_RESULTS.md",
  defect="ENV-BLK-DISK", pri="P0")
C("ENV-VENV-001", "Stale virtual-environment shebangs", ".venv console scripts (pytest, lint-imports, ...) execute.", "Shebang points to an existing interpreter.", "1) head -1 apps/api/.venv/bin/pytest apps/api/.venv/bin/lint-imports",
  status="FAIL", actual="VERIFIED: shebang is /media/varun/varun11/work/staff-spectrum/HRMS/apps/api/.venv/bin/python (repo now lives under .../varun12/...). `python -m pytest` unaffected.", evidence="QA_BASELINE_RESULTS.md",
  defect="ENV-BLK-SHEBANG", pri="P1")
C("ENV-ISOL-001", "Test suite default DB is the dev DB", "Running raw pytest must never target hrms_dev.", "Suite refuses to run unless DATABASE_URL names a disposable DB.", "1) read tests/conftest.py defaults",
  status="FAIL", actual="VERIFIED by code reading: tests/conftest.py os.environ.setdefault('DATABASE_URL', ...hrms_dev); FULL_TEST_SUITE.md confirms raw pytest 'truncates the developer's real dev data' (observed once). run_full_tests.py guards this only when used.",
  evidence="apps/api/tests/conftest.py:12-15; docs/testing/FULL_TEST_SUITE.md", defect="ENV-RISK-DEVDB", pri="P0")
C("ENV-ISOL-002", "Unit tier is not infrastructure-free", "Unit tests must not touch shared Redis.", "No network access in the unit tier, or an explicit private REDIS_URL.", "1) run `pytest tests/unit` with REDIS_URL pointing at a closed port",
  status="FAIL", actual="VERIFIED this phase: the root autouse fixture `_reset_credential_rate_limits` (tests/conftest.py:60-85) connects to REDIS_URL and SCAN-deletes `ratelimit:login:*`, `ratelimit:token_refresh:*`, `ratelimit:email_verification:*`, `ratelimit:auth:*` before AND after EVERY test, unit tests included. First run against a closed port errored on the very first unit test (redis ConnectionError). With default REDIS_URL (redis://localhost:6380/0) a raw run clears the shared dev Redis rate-limit keys.",
  evidence="apps/api/tests/conftest.py; run output in QA_BASELINE_RESULTS.md §2", defect="ENV-RISK-REDIS", pri="P1")
C("ENV-ISOL-003", "Security RLS test hard-coded the shared dev database", "Every test must follow DATABASE_URL; none may write to hrms_dev when pointed elsewhere.", "tests/security/test_rls_runtime_role.py connects only to the database named by DATABASE_URL.", "1) read tests/security/test_rls_runtime_role.py:63-64 2) run it with DATABASE_URL pointing at the disposable DB and confirm hrms_dev row counts unchanged",
  status="NOT_RUN", actual="VERIFIED by reading (Phase 3 preflight): ADMIN_ROLE_URL/RUNTIME_ROLE_URL were literals for localhost:5433/hrms_dev and the tests monkeypatch DATABASE_URL to them, so this module registered/cleaned synthetic tenants in the shared dev DB regardless of DATABASE_URL (and under run_full_tests.py). FIX APPLIED (uncommitted): URLs derive from DATABASE_URL (HRMS_APP_DATABASE_URL optional); derivation verified for three inputs (identical to the old constants with CI defaults). The test itself has not been run since the change.",
  evidence="apps/api/tests/security/test_rls_runtime_role.py", defect="ENV-RISK-HARDCODED-DEVDB", pri="P0", tests=["security/test_rls_runtime_role"])
C("ENV-MINIO-001", "Destructive MinIO restart test is on by default", "`test_object_survives_a_minio_container_restart` runs `docker restart hrms-minio` (shared container).", "Opt-in env flag required.", "1) read tests/integration/core/test_storage.py:141-165",
  status="FAIL", actual="VERIFIED by code reading: only skipif when docker CLI/container absent; no opt-in flag. Report section 2 confirms it restarted the shared container once (hrms-minio 'Up 41 minutes' observed this phase vs postgres/redis 'Up 14 hours').",
  evidence="apps/api/tests/integration/core/test_storage.py", defect="ENV-RISK-RESTART", pri="P0")
C("ENV-GRANT-001", "init script re-run undoes append-only REVOKEs", "002_app_role.sh grants ALL DML on ALL TABLES to hrms_app; re-running on a migrated DB restores UPDATE/DELETE on append-only tables.", "Idempotent script must not widen privileges.", "1) read script; (private DB only) re-run and re-check privileges",
  status="NOT_RUN", actual="Script text VERIFIED (GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES). Behaviour 'reproduced 2026-10-25' is inherited from test docstring; not re-run (needs private DB).",
  defect="K-1-RELATED", pri="P0", risk="NEVER run against shared dev DB.")
C("ENV-MIG-001", "Clean-environment migration reproducibility", "alembic upgrade head from an empty private DB reaches single head 20261022090000; downgrade/upgrade cycle where supported; schema equals models.", "Single head; no errors; RLS enabled on tenant tables; hrms_app NOBYPASSRLS.",
  "1) create throwaway DB (name contains 'qa'/'test') 2) init scripts 3) alembic upgrade head 4) alembic heads 5) check RLS", env="PRIVATE_STACK", actual="Inherited: 121 revisions apply from empty to head (report §2); 121 files present (verified count). Not re-run.",
  amb="Verify single head with `alembic heads`; model-vs-migration drift check (alembic check) not documented anywhere.")
C("ENV-CI-001", "CI vs local dependency parity", "CI installs from uv.lock with Python 3.12; local .venv must match.", "`uv sync --frozen` produces same versions as .venv; Flutter pinned 3.29.2.", "1) compare uv.lock to pip freeze of .venv 2) record versions",
  actual="Partially verified: CI uses python 3.12 + `uv sync --all-groups`; local pycache shows both cpython-39 and cpython-312 -> mixed interpreters have been used here. Lock-vs-venv diff not done.", pri="P1")
C("ENV-FLUTTER-001", "Flutter toolchain", "Flutter 3.29.2 (CI pin) installed in isolation (e.g., fvm/container).", "flutter doctor OK for test-only.", "1) install into a dedicated directory", status="BLOCKED", actual="Flutter absent (verified).", defect="ENV-BLK-FLUTTER")
C("ENV-STACK-001", "Private test stack repeatability", "Private Postgres/Redis/MinIO provisioned by script, torn down cleanly, ports/paths not hard-coded.", "Re-runnable from a clean checkout.", "1) provision 2) run 3) teardown 4) repeat",
  actual="NOT repeatable today: qa_live scripts hard-code a previous session's scratchpad path (start_qa.sh, start_b.sh) and ports 5433/6380 etc.; qa.py reads api.log from its own dir; no teardown script.", defect="QA-EVID-01", pri="P1")
C("ENV-LOGS-001", "Dev log/disk growth", "Application logs and test result artifacts do not grow unbounded on `/`.", "Rotation configured; test-results ignored by git.", "1) inspect logs/ and test-results sizes", pri="P2")

# ------------------------------------------------------------------ EXCLUDED / NOT IMPLEMENTED
defaults(module="Excluded / not implemented", pri="P2", role="n/a", data="n/a", env="n/a", auto="N/A", type="N/A", status="NOT_APPLICABLE")
C("FACE-EXCL-001", "Face attendance (Face++/open-source, enrolment, liveness, punch)", "Excluded from this QA pass by instruction.", "Not executed.", "n/a",
  src="User instruction", tests=["face_", "opensource_face", "test_liveness", "test_face", "mobile/test/face_"], actual="EXCLUDED_BY_INSTRUCTION. Existing automated tests are mapped but must not be counted as QA-verified.",
  amb="Existing face tests (see QA_TEST_MAP.csv, filter 'face') run in CI and were inside the inherited regression total, i.e. executed but not assessed by this QA effort.")
C("REC-NI-001", "Recruitment, job postings, candidates", "No implementation present.", "n/a", "n/a", src="FUNCTIONAL_QA_REPORT §1", actual="NOT IMPLEMENTED - not a failed test. Check docs/product/02_PRD.md for whether a release commitment exists.")
C("AI-NI-001", "Resume processing / AI features", "No implementation present.", "n/a", "n/a", src="FUNCTIONAL_QA_REPORT §1; docs/product/21_AI_and_Automation_Feature_Specification.md", actual="NOT IMPLEMENTED - specification exists, no code.")
C("BILL-NI-001", "Subscription payment / usage billing", "No implementation (read-only plan summary only).", "n/a", "n/a", src="FUNCTIONAL_QA_REPORT §1", actual="NOT IMPLEMENTED.")
C("RPT-NI-001", "Reports/exports & rich notifications", "Only 1 dashboard endpoint; no export endpoints; only transactional email.", "n/a", "n/a", src="FUNCTIONAL_QA_REPORT §1", actual="NOT IMPLEMENTED.")
