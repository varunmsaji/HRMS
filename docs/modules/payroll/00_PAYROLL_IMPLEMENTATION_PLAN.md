# Payroll — Implementation Plan (payroll readiness step 5)

| Field | Value |
|---|---|
| Status | **APPROVED 2026-09-23** — D1–D6 accepted as recommended (product owner: varun); D7–D11 still open, needed by the end of Phase 5.2 |
| Date | 2026-09-23 |
| Scope source | `docs/product/17_SRS_Phase1_Core_Modules.md` §7 (FR-PAY-001…025), `docs/product/VERSION_1_ROADMAP.md` rows 16, 37–44 |
| Binding rules | `docs/audits/PAYROLL_BUSINESS_DECISIONS.md` (decisions 1–18, PD-2), `docs/adr/0005-payroll-snapshot-immutability.md`, `docs/audits/PAYROLL_FOUNDATION_CONTRACT.md` Part C (C1–C10) |

---

## 1. What this plan is for

The SRS describes the whole of Payroll — 25 requirements covering salary structures, a formula
builder, statutory deductions, income tax, loans, reimbursements, bonus, payslips, bank files,
statutory returns, accounting vouchers and full & final settlement. That is several months of work
and cannot be one slice.

This plan splits it into **seven phases**, each shippable and testable on its own, ordered so
that the first usable result — a correct, locked monthly pay run with payslips — arrives as early
as possible, and every later phase adds to it without reworking it.

## 2. What already exists (verified 2026-09-23)

| Input Payroll needs | Where it is | State |
|---|---|---|
| Legal entity + PF/ESI codes, TAN, PAN | `organisation.LegalEntity` | Ready |
| Employment spells, pay basis (MONTHLY / DAILY_WAGE) | `employee.Employment` | Ready (decision 1) |
| Annual CTC, effective-dated | `employee.EmployeeCompensation` (`annual_ctc_minor`, INR minor units) | Ready — **no component breakup** (deferred to Payroll by design) |
| PF/ESI/PT/LWF applicability, VPF, tax regime | `employee.EmployeeStatutory` | Ready |
| UAN, PAN | `employee.Employee` | Ready (PAN encrypted) |
| Bank account | `employee.EmployeeBank` | Ready (encrypted) |
| Paid days, LOP days, not-employed days, OT minutes per class | `attendance.AttendancePeriodSummary` — frozen per **legal-entity** period at close | Ready (steps 1–3) |
| OT multipliers per day class | `attendance.OvertimePolicyRateRow.multiplier_decimal` | Stored, reference only today |
| Leave encashment owed | `leave` ledger `ENCASHMENT` entries with a `reference_id` (decision 11) | Ready — payroll must pick them up |
| Attendance engine version per day | `attendance_day.engine_version` | Ready (PAY-008) |
| Salary components, structures, statutory rates, pay runs, payslips | — | **Nothing exists** |

## 3. Fixed design rules (from signed-off decisions — not open)

1. **One pay run per legal entity per calendar month** (decisions 14, 18; FR-PAY-025).
2. **A pay run reads only a `CLOSED` attendance period** of the same legal entity covering exactly
   that month, and only its frozen summary rows — never live `attendance_day` rows (PD-2, C1, C2).
3. **Proration = calendar days**: monthly amount × paid days ÷ days in the month (decision 17).
   Not-employed days are neither paid nor LOP (decision 2).
4. **Snapshot then compute** (ADR-0005): every input is copied into the run before computation;
   computation is a pure function of the snapshot; every line stores its calculation trace
   (FR-PAY-024).
5. **A finalised run never changes.** Corrections flow as arrears in a later run (decision 15,
   FR-PAY-023). Once a month's run is finalised, the attendance period for it can no longer be
   reopened (decision 15).
6. **Money is integer minor units (paise) and `Decimal`**, never `float` (C7).
7. **Variance gate** before finalise: flagged changes must each be acknowledged with a reason
   (FR-PAY-014).
8. Permissions via `core/rbac` and `DataScope` (C8); an audit row for every run transition (C10).
9. Statutory rates are **effective-dated data, never hard-coded**, and need compliance sign-off
   before go-live (FR-PAY-005).

## 4. Phases

### Phase 5.1 — Salary structure (setup)

*FR-PAY-001, 003, 004 (simplified). No formula builder yet.*

- `salary_component` master per company: code, name, type (`EARNING` / `DEDUCTION` /
  `EMPLOYER_CONTRIBUTION`), calculation (`FIXED` / `PERCENTAGE_OF_CTC` / `PERCENTAGE_OF` another
  component / `BALANCING` — the remainder that makes the total equal CTC), flags: taxable, PF
  wage, ESI wage, prorated by paid days, show on payslip. System components seeded: Basic, HRA,
  Special Allowance (balancing), Employer PF, Employer ESI.
- `salary_structure` template: ordered components with values, effective-dated versions
  (draft → publish, same pattern as attendance policies).
- `employee_salary` assignment: employee → structure version, effective-dated, **driven by the
  existing `EmployeeCompensation` CTC** (no second place to store CTC). A breakup preview API
  returns monthly and annual amounts per component.
- Web: component list, structure editor with live CTC breakup preview, salary tab on the employee.

**Status: done 2026-09-24** (migration `20261004105000`). As built:

- Tables `salary_component`, `salary_structure`, `salary_structure_version`,
  `salary_structure_line`, `employee_salary` (RLS `tenant_isolation`; `employee_salary` has a GiST
  no-overlap per employee and a CHECK that exactly one of structure / daily rate is set).
- Calculation types: `FIXED`, `PERCENTAGE_OF_CTC`, `PERCENTAGE_OF_GROSS`,
  `PERCENTAGE_OF_COMPONENT`, `BALANCING`; optional monthly cap; `applies_when`
  (`ALWAYS` / `PF_APPLICABLE` / `ESI_APPLICABLE`). The pure solver (`payroll/breakup.py`) finds
  gross by bisection so `gross + employer contributions = monthly CTC` exactly (D2); computed
  lines round to the rupee, the balancing line absorbs the rest.
- Seeded per company on first use: system components `BASIC`, `HRA`, `SPECIAL_ALLOWANCE`,
  `EMPLOYER_PF`, `EMPLOYER_ESI`; while a company has no structure, `STANDARD` (Basic 50 % of
  gross, HRA 40 % of Basic, Special Allowance balancing, employer PF 12 % of Basic capped at
  ₹1,800, PF-applicable only) and `STANDARD_METRO` (HRA 50 %), published from 2000-01-01.
  Employer ESI is not in the defaults — it arrives with the statutory master (5.3).
- API: `/v1/payroll/salary-components`, `/v1/payroll/salary-structures` (+ versions: create
  draft, `PUT …/lines`, `…/publish`, `DELETE` draft, `…/preview`),
  `/v1/employees/{id}/salary` (history, assign), `/v1/employees/{id}/salary/breakup?as_of=`,
  `/v1/payroll/salary-assignments/bulk`. Setup is gated by the new `PAYROLL.SETUP_MANAGE`
  (COMPANY_ADMIN + HR_ADMIN); salary reads reuse `EMPLOYEE.VIEW_COMPENSATION` with its DataScope.
- An assignment is refused unless, on its first day, the employee is employed, has a CTC
  (monthly-paid), and the structure has a published version that fits that CTC. Daily-wage
  employees get a daily rate instead (D5).
- `SalaryStructureService.breakup_as_of` is the seam the pay-run engine (5.2) will call.
- Web: Settings → Payroll → Salary Components / Salary Structures (draft editor, publish, CTC
  preview, bulk assign), and a Salary tab on the employee.

### Phase 5.2 — Pay run core (the first usable result)

*FR-PAY-007, 008, 009, 014, 015, 023, 024, 025.*

- `pay_run` per (legal entity, month) with lifecycle
  `DRAFT → INPUTS_LOCKED → COMPUTED → APPROVED → FINALISED → PAID`
  (the SRS's `UNDER_REVIEW` folds into `COMPUTED` + the variance gate). Rollback allowed only
  before `FINALISED`.
- **Lock inputs**: refuses unless the entity's attendance period for the month is `CLOSED`;
  snapshots per employee: frozen summary row, salary structure version + component amounts,
  pay basis, statutory profile, bank account reference, leave encashment entries, approved OT
  minutes per class with the multipliers.
- **Compute** (pure function over the snapshot): prorated earnings, LOP deduction, OT pay,
  leave encashment, gross, deductions (statutory ones arrive in 5.3 — until then zero, and a run
  cannot be finalised with statutory-applicable employees unless 5.3 is live — see D6), net,
  rounding to the rupee. One `pay_run_line` per employee per component with its trace.
- **Validation** (FR-PAY-015 subset): negative net, zero net for an employed employee, missing
  bank account, employee in the summary but not in the run and vice versa, missing salary.
- **Variance gate** vs the previous finalised run of the same entity; threshold configurable
  (default 15 %); finalise blocked until each flag has a reason.
- **Finalise**: immutable; blocks reopening that attendance period (new check in
  `AttendancePeriodService.reopen`).
- Web: pay run list per entity, run detail (employees, totals, validation, variance
  acknowledgement), per-employee breakdown with trace.

### Phase 5.3 — Statutory deductions

*FR-PAY-005, 006 (profile exists).*

- Effective-dated `statutory_rate` master: PF (employee 12 %, employer EPF/EPS split, wage ceiling
  ₹15,000, admin/EDLI charges, VPF), ESI (0.75 % / 3.25 %, ₹21,000 ceiling, contribution-period
  rule), PT slabs per state and frequency, LWF per state. Seeded values marked **unverified** until
  compliance sign-off.
- Engine: employee PF/ESI/PT/LWF deductions and employer contributions from the component flags.
- Validation: PF/ESI applicability mismatch, missing UAN/IP number.

### Phase 5.4 — Payslips and bank advice

*FR-PAY-017 (PDF, publish to ESS), FR-PAY-018 (generic CSV first).*

- Payslip PDF per employee from the finalised run (earnings, deductions, employer
  contributions, pay days, LOP, leave balance, net in words); published to employee self-service.
- Bank advice: generic CSV/NEFT file, encrypted download with access log. Bank-specific formats
  later.

### Phase 5.5 — Arrears

*FR-PAY-010, AC-PAY-023.1.*

- Detect after a month is finalised: retrospective CTC revisions, attendance/leave corrections
  (period reopened before finalise is fine; after finalise, corrections land in a later
  period — see D7), and missed employees.
- Compute the per-component, per-month differential and post it as `ARREARS` lines in the next
  run, with a month-wise breakup on the payslip.

### Phase 5.6 — Income tax (TDS)

*FR-PAY-011.* Both regimes, slabs/surcharge/cess as effective-dated data, annual projection,
declarations and proofs, previous-employer income, monthly TDS. The largest single phase.

### Phase 5.7 — Everything else

Statutory files (PF ECR, ESI, PT challan, Form 24Q / Form 16), accounting voucher, payroll reports
and register, full & final settlement (salary to last day, leave encashment, gratuity, notice pay,
negative leave recovery per decision 8), loans, reimbursements, bonus / off-cycle runs, formula
builder. Each is a separate slice once 5.1–5.6 are stable.

## 5. Suggested order and size

| Phase | Depends on | Rough size |
|---|---|---|
| 5.1 Salary structure | — | ~1 week |
| 5.2 Pay run core | 5.1 | ~2 weeks |
| 5.3 Statutory | 5.2 | ~1 week (+ compliance sign-off on rates) |
| 5.4 Payslips + bank advice | 5.2 (5.3 for complete payslips) | ~1 week |
| 5.5 Arrears | 5.2 | ~1 week |
| 5.6 TDS | 5.3 | ~2–3 weeks |
| 5.7 Remainder | 5.2–5.6 | separate slices |

5.1 → 5.2 → 5.3 → 5.4 gives a legally usable monthly payroll for companies whose employees are
below the TDS threshold or whose TDS is handled outside the system for the first months.

## 6. Module shape

`apps/api/src/hrms/modules/payroll/` following the Module Standard (models, repository,
service, schemas, router, permissions, exceptions, tasks). Cross-module reads only through
services: `EmployeeCompensationService.get_compensation_as_of`, `EmploymentService`,
`EmployeeStatutoryService`, `EmployeeBankService`, `AttendancePeriodService` (closed period +
frozen summary for an entity and month), `LeaveLedgerService` (encashment entries).

New permissions (proposal): `PAYROLL.SETUP_MANAGE`, `PAYROLL.RUN_VIEW`, `PAYROLL.RUN_PROCESS`,
`PAYROLL.RUN_APPROVE`, `PAYROLL.RUN_FINALISE`, `PAYROLL.PAYSLIP_VIEW_OWN`. Maker ≠ checker:
the user who computes a run cannot approve it.

## 7. Risks

- **Statutory values** are legal facts; wrong seed data pays people wrongly. Mitigation: rates as
  data with an "unverified" flag that blocks finalise until signed off.
- **TDS complexity** is the largest schedule risk; phasing it after 5.4 keeps it off the critical
  path for the first usable payroll.
- **Arrears correctness** depends on every input being snapshotted in 5.2 — the snapshot shape
  must be designed for 5.5 from day one.
- Existing employees have CTC but no salary structure — a bulk "assign structure" tool is needed
  in 5.1 or the first run cannot happen.

## 8. Decisions needed before Phase 5.1 / 5.2 starts

| # | Question | Recommendation |
|---|---|---|
| D1 | Default salary structure: which components and splits? | Basic 50 % of monthly gross, HRA 40 % of Basic (50 % metro), Special Allowance balancing; employer PF inside CTC |
| D2 | Is employer PF/ESI **inside** CTC (deducted from gross) or on top? | Inside CTC (most common in India) |
| D3 | OT pay base: hourly rate from Basic, from gross, or a fixed rate? | (Basic + DA) ÷ (days in month × 8 h) × multiplier — the Factories Act basis |
| D4 | Leave encashment rate base | Basic ÷ days in month per day (matches most EL policies) |
| D5 | Daily-wage employees: how is their rate stored? | Daily rate on the salary assignment; pay = daily rate × paid days |
| D6 | May a run be finalised before statutory deductions (5.3) exist? | No — 5.2 ships behind 5.3 for any entity with PF/ESI-applicable employees |
| D7 | After a month is finalised, where does a late attendance correction go? | It is made in the next open period as an arrears adjustment; the finalised period stays closed |
| D8 | Net pay rounding | Round to the nearest rupee; the difference shown as a rounding line |
| D9 | Who approves a pay run? | HR prepares, a separate user with `PAYROLL.RUN_APPROVE` (Finance / Company Admin) approves; same user cannot do both |
| D10 | Variance threshold | 15 % per employee net pay, configurable per company |
| D11 | Pay date | Configurable per legal entity; default the 1st working day of the next month |

**2026-09-23:** D1–D6 approved as recommended. D7–D11 are needed by the end of Phase 5.2.
