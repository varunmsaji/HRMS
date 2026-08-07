# Document 02 — Product Requirements Document (PRD)

**Version:** 2.0 — migrated from Document 01 (Business Requirements Document, v1.0) §2–§11.
The vision statement that opened the original BRD is now [Document 01 — Product Vision](01_Product_Vision.md).
Detailed functional requirements per module live in [Document 17](17_SRS_Phase1_Core_Modules.md)
(Phase 1) and [Document 18](18_SRS_Phase2_Phase3_Modules.md) (Phase 2/3). This document is
**business-requirements content and is stack-independent** — nothing here changed because of the
FastAPI backend decision; it is renumbered and cross-referenced to fit the new document map
(Document 00).

---

## 1. Business Objectives & Success Metrics

| Obj | Objective | Measurable Target | Measured How |
|-----|-----------|-------------------|--------------|
| O1 | Automate routine HR transactions | ≥75% of leave, attendance-regularisation, payroll and onboarding transactions complete with **zero HR touches** | Event log: count transactions with `hr_intervention = false` ÷ total |
| O2 | Cut payroll processing time | From industry-typical 3–5 days to **< 4 hours** for a 500-employee run | Timestamp from `pay_run.started_at` to `finalised_at` |
| O3 | Cut time-to-hire | 20% reduction vs client baseline | Median days from `job_opening.published_at` to `offer.accepted_at` |
| O4 | Reduce payroll disputes | < 0.5% of payslips raise a helpdesk ticket | Tickets tagged `payroll_dispute` ÷ payslips issued |
| O5 | Employee self-service adoption | ≥80% monthly active employees on ESS/mobile | Distinct employee logins ÷ active headcount |
| O6 | Statutory accuracy | 100% on-time, zero-defect PF/ESI/TDS return files | Return rejection count = 0 |
| O7 | Platform reliability | 99.9% uptime; payroll never fails silently | Uptime monitor + failed-job alerts |

**Baseline capture requirement:** before go-live, the client must supply current-state values
for O2–O5. Without a baseline, "20% reduction" is unverifiable and the objective is unenforceable.

---

## 2. Target Customers & Segmentation

| Segment | Headcount | Buying Trigger | Modules They Actually Pay For |
|---------|-----------|----------------|-------------------------------|
| Small SME | 20–100 | Payroll errors, attendance disputes | Attendance, Leave, Payroll, ESS |
| Mid SME | 100–500 | Growth, compliance risk, manual chaos | + Recruitment, Onboarding, Reports, Workflow |
| Large SME / Small Enterprise | 500–2,000 | Multi-location, audit pressure | + Multi-company, Performance, Asset, Helpdesk |
| Enterprise | 2,000+ | Consolidation of point tools | + Integrations, SSO, AI analytics, custom SLA |

---

## 3. Industry-Specific Requirements

This is the section most HRMS projects get wrong. The eight named industries have **materially
different attendance, wage and compliance behaviour**. The platform serves them through
configuration templates, not code branches — this remains true regardless of backend language and
is, if anything, easier to defend now: Python's ecosystem (Pydantic, SQLAlchemy) makes rich,
validated, tenant-scoped configuration schemas straightforward to build and maintain in one place
(Document 07 §4, Document 08 §4).

### 3.1 IT / Software Services
- Flexible/no shift, core-hours policy, work-from-home and hybrid tracking
- Monthly salaried, high CTC complexity: variable pay, bonus, ESOP notes, NPS
- Project/client-wise timesheet and billable-hours tracking → integration to invoicing
- High recruitment volume, referral programme, notice-period buyouts
- **Special need:** timesheet module, client-billability reporting

### 3.2 Manufacturing
- Rotational shifts (typically 3×8h), shift rotation calendars, weekly-off rotation
- **Overtime is central**: statutory OT at 2× ordinary wages under Factories Act
- Contract labour (CLRA) — contractor-wise headcount, licence and compliance tracking
- Piece-rate / production-incentive wage components
- Safety training compliance, PPE issuance (Asset module), accident register
- **Special need:** OT engine, contractor management, shift rotation automation

### 3.3 Retail
- Store-wise rosters, split shifts, part-time and hourly staff
- High attrition → fast onboarding, bulk hiring, quick full-and-final
- Sales-linked incentives, store-target-based variable pay
- Geo-fenced mobile attendance for store staff without biometric hardware
- **Special need:** roster/scheduling engine, incentive calculation

### 3.4 Hotels & Cafes
- 24×7 operations, split shifts, on-call, night-shift allowance
- Tips/service-charge distribution, meal deductions, staff accommodation deductions
- Very high casual/temporary staff churn
- **Special need:** split-shift attendance, service-charge pooling, duty roster

### 3.5 Healthcare
- 24×7 rosters, nurse-to-patient ratio compliance, duty doctors, on-call allowance
- Credential & licence expiry tracking (medical registration, BLS/ACLS certification)
- Mandatory training compliance with audit trail (NABH/JCI)
- **Special need:** credential expiry alerts, competency matrix, roster compliance

### 3.6 Construction
- Site-wise workforce, daily-wage and muster-roll workers
- Mobile/offline attendance at sites with poor connectivity — **offline-first is mandatory here**
- BOCW cess and welfare board registration, contractor/sub-contractor labour
- Frequent inter-site transfer, travel and site allowances
- **Special need:** offline mobile attendance sync, site-wise labour reporting, contractor compliance

### 3.7 Logistics
- Driver/field staff — GPS attendance, trip-based tracking, distance allowance
- Statutory driving-hour limits, licence expiry tracking
- Hub-wise shift, night operations
- **Special need:** GPS-first attendance, trip/route allowance, licence compliance

### 3.8 Education
- Academic-year calendar, term breaks, vacation leave rules distinct from corporate leave
- Teaching vs non-teaching staff with different rules, workload/period allocation
- Substitution/relief tracking, sabbatical, probation confirmation cycles
- **Special need:** academic calendar, period-wise workload, vacation leave type

**Engineering implication:** the Attendance, Leave, Payroll and Onboarding modules must expose
enough configuration surface to satisfy all eight without code changes. Document 17 §5–§7 specifies
that surface. If it cannot be configured, the sales promise of "8 industries" is false.

---

## 4. User Personas

| Persona | Role in Hierarchy | Primary Jobs-to-be-Done | Devices | Success Feels Like |
|---------|-------------------|-------------------------|---------|--------------------|
| **Priya — HR Manager** | HR Manager | Run payroll, approve exceptions, stay compliant, answer employee queries | Web (primary) | "Payroll closed in one afternoon and nobody complained." |
| **Rahul — HR Executive** | HR Executive | Onboard joiners, chase documents, maintain records | Web | "I stopped chasing people; the system chases them." |
| **Sneha — Recruiter** | Recruiter | Fill open roles fast, manage pipeline, schedule interviews | Web + Mobile | "I never lose a candidate in my inbox again." |
| **Arun — Reporting Manager** | Reporting Manager | Approve leave/attendance, review team performance | Mobile (primary) | "I approve from my phone in 30 seconds." |
| **Meera — Employee (white-collar)** | Employee | Apply leave, view payslip, update details, raise queries | Mobile + Web | "I don't have to email HR for anything." |
| **Suresh — Employee (blue-collar)** | Employee | Punch in/out, check attendance, see salary | Shared kiosk / biometric / feature phone via SMS-WhatsApp | "My hours and my pay are correct." |
| **Vikram — Company Admin** | Company Admin | Configure the org, control access, see the big picture | Web | "I can see the whole company on one screen." |
| **Deepa — Finance** | External/Finance | Get accurate payroll JV, statutory dues, cost reports | Web | "Numbers reconcile with my books without a spreadsheet." |
| **Mr. Nair — Auditor** | External/Auditor | Read-only evidence with a trail | Web | "I found every record and its history without asking HR." |
| **Platform Ops — Super Admin** | Super Admin | Onboard tenants, monitor health, support | Web + Ops tooling | "I can diagnose any tenant issue without touching their data." |

**Persona-driven design rule:** Arun and Meera are the highest-volume users. If manager approval
and employee leave application are not each achievable in **≤3 taps**, the ESS adoption target (O5)
will fail regardless of feature completeness.

---

## 5. Scope

### 5.1 In Scope — Phase 1 (MVP)
Authentication & RBAC · Company/Org Setup · Employee Management · Recruitment (ATS) ·
Attendance · Leave · Payroll (India statutory) · ESS · Onboarding · Exit & F&F ·
Dashboards · Reports · Mobile App (employee + manager) · Notification Engine ·
Workflow/Approval Engine (as MVP enabler) · Basic AI (resume parsing & screening) ·
Biometric + GPS attendance integration · Excel import/export.

> **Note:** The client's Phase 1 list omits the Workflow Engine and Role & Permission as separate
> items, but Leave/Attendance/Onboarding/Exit cannot function without an approval engine and
> RBAC. They are therefore promoted into Phase 1 as foundation components. This is a
> **clarification, not a scope increase** — it was implicit.

### 5.2 In Scope — Phase 2
Performance Management · Expense Management · Asset Management · HR Helpdesk ·
Task & Checklist · Communication (announcements, WhatsApp) · Advanced Reports & Analytics ·
Multi-Company consolidation · Accounting/ERP integration · Advanced AI (attrition prediction,
attendance anomaly, payroll validation).

### 5.3 In Scope — Phase 3
Learning & Development (LMS) · Employee Experience (surveys, engagement, recognition) ·
Visitor Management · Workforce planning AI · Timesheets & project costing ·
Shift roster optimiser · Multi-country payroll framework · Public API & marketplace ·
On-premise deployment option.

### 5.4 Explicitly OUT of Scope (v2.0, unchanged from v1.0)
- Full accounting/GL system (integration only)
- Applicant sourcing job-board *purchase* (posting integrations only)
- Background verification execution (vendor integration only)
- Statutory return **e-filing submission** to government portals (file generation only —
  actual submission remains a human act on the government portal)
- Insurance/benefits brokerage
- Native desktop applications
- Data migration from legacy systems (separately quotable)

---

## 6. Automation Definition — What "70–80% Automated" Concretely Means

For the target to be testable, each transaction type gets an automation definition:

| Transaction | Manual today | Automated behaviour | Counts toward target when |
|---|---|---|---|
| Attendance capture | HR compiles registers | Device/GPS/app push → auto-marked | No HR edit on the day record |
| Absence detection | HR notices later | Auto-flag + notify employee & manager same day | Flag raised without HR action |
| Leave application | Email → HR → register | Employee applies → balance auto-checked → routed → auto-posted to attendance & payroll | Zero HR touch end-to-end |
| Attendance regularisation | Email chain | Employee request → manager approves → attendance day recomputed | Zero HR touch |
| Payroll input collection | HR chases everyone | Attendance, leave, OT, arrears, expenses auto-flow into the pay run | No manual input rows added |
| Payroll computation | Excel formulas | Rules engine computes gross, deductions, statutory, net | Run completes with 0 manual overrides |
| Payslip distribution | HR emails PDFs | Auto-published to ESS + email/WhatsApp | Zero manual send |
| Offer letter | Word template | Generated from offer data + template, e-signed | No manual document editing |
| Onboarding tasks | HR checklist in Excel | Task pack auto-assigned to IT/Admin/HR/manager with due dates + escalation | All tasks auto-created |
| Confirmation / probation | HR calendar reminder | Auto-triggered review workflow at T-15 days | Triggered by system |
| Exit clearance | Email chase | Auto clearance checklist per department + F&F auto-computed | No manual chase |
| Statutory filing data | Manual compilation | ECR/ESI/PT/TDS files auto-generated from finalised run | File generated with no edit |

**Reported metric:** `automation_rate = automated_transactions / total_transactions`, computed
monthly per tenant and shown on the Company Admin dashboard. This becomes a **sales proof point**
and should be built as a first-class feature, not a report afterthought.

---

## 7. Business Rules — Cross-Cutting (Master List)

These rules apply across modules and are the source of truth for SRS acceptance criteria
(Document 17, Document 18).

| BR ID | Rule |
|-------|------|
| BR-01 | An employee's data belongs to exactly one Company; cross-company visibility requires an explicit Multi-Company grant. |
| BR-02 | No user may approve their own request at any level. If the approver resolves to the requester, escalate to the next level. |
| BR-03 | If an approver is on leave, requests auto-route to their configured delegate; if no delegate, to their manager after the SLA breach. |
| BR-04 | Attendance for a date cannot be modified after the payroll for that period is finalised, except via a formal arrears adjustment. |
| BR-05 | A finalised pay run is immutable. Corrections happen in a later period as arrears or recovery. |
| BR-06 | Leave balance is computed, never stored as a single mutable number — it is derived from an append-only ledger of accruals, usages, encashments, lapses and adjustments. |
| BR-07 | Salary revision is always effective-dated; retrospective revisions auto-generate arrears in the next run. |
| BR-08 | An employee cannot be deleted, only deactivated/exited. Records are retained per the retention policy. |
| BR-09 | Every document upload is virus-scanned before it becomes accessible. |
| BR-10 | Statutory rates (PF %, ESI %, PT slabs, TDS slabs, wage ceilings) are versioned master data with effective dates — never hardcoded. |
| BR-11 | An employee sees only their own data; a manager sees their reporting tree; HR sees their assigned scope (branch/department/entity). |
| BR-12 | Salary/CTC of any employee is visible only to roles holding the explicit `PAYROLL_VIEW_SENSITIVE` permission — including hiding it from reporting managers by default. |
| BR-13 | All monetary rounding rules are declared per salary component (round to nearest rupee / floor / ceiling) and are auditable. |
| BR-14 | Notice period, probation period, leave entitlement and shift default at Company level, are overridable at Branch → Department → Grade → Employee level; the most specific setting wins. |
| BR-15 | Any bulk operation (>25 records) requires a preview/dry-run with a validation report before commit. |

---

## 8. Constraints

| Type | Constraint |
|------|-----------|
| Legal | Indian labour law and Income-Tax rules; DPDP Act 2023 for personal data; POSH Act records confidentiality |
| Data | Payroll and statutory records retained 8 years; PF records 7 years post-exit; POSH records as per Act |
| Technical | Must operate on 3G-grade mobile connectivity for construction/logistics field staff |
| Operational | Payroll cut-off windows are unmovable — the system must never be down on month-end days 25–5 |
| Commercial | PEPM pricing means infra cost per employee must stay bounded; expensive AI calls must be rate-limited per plan |
| **Delivery** | **Single-developer, AI-assisted delivery model** (Document 01 §2, Document 25). Scope and phase sequencing must account for one person's realistic throughput even with AI-assisted coding — this constrains how aggressively Phase 2/3 features can be pulled forward. |

---

## 9. Assumptions & Dependencies on the Client

| Dep | The client must provide | Needed by |
|-----|-------------------------|-----------|
| D1 | Sample salary structures, payslip formats and 3 months of real (anonymised) payroll data for validation | Payroll build phase |
| D2 | Sample offer/appointment/relieving letter templates | Onboarding build phase |
| D3 | Biometric device models and network topology at customer sites | Attendance build phase |
| D4 | A named business owner available for ≥4 hours/week for clarifications and demo sign-off | Every phase |
| D5 | Statutory/compliance consultant sign-off on payroll calculations | Before payroll UAT |
| D6 | Brand assets, domain, email/SMS/WhatsApp sender accounts and payment gateway account | Before go-live |
| D7 | Two pilot customer companies for UAT with real data | UAT phase |

**Escalation rule:** if D4 is not met for two consecutive phases, the project moves to a formal
"blocked" status and schedule risk is transferred to the client.

---

## 10. Out-of-the-Box vs Configurable vs Custom

| Capability | OOTB | Tenant-Configurable | Requires Dev |
|---|:--:|:--:|:--:|
| Leave types & accrual rules | ✔ templates | ✔ | ✖ |
| Shift patterns & rotation | ✔ templates | ✔ | ✖ |
| Salary structure & components | ✔ templates | ✔ (formula builder) | ✖ |
| Approval chains | ✔ defaults | ✔ (visual builder) | ✖ |
| Letter templates | ✔ 12 templates | ✔ (rich editor + merge fields) | ✖ |
| Custom employee fields | — | ✔ (up to 40 per entity) | ✖ |
| Report columns & filters | ✔ 60 reports | ✔ (report builder) | ✖ |
| New statutory component (new country) | ✖ | ✖ | ✔ |
| New biometric device protocol | ✔ 3 protocols | ✖ | ✔ |
| New workflow node type | ✔ 8 types | ✖ | ✔ |

This table is the **anti-scope-creep contract**. Anything in the right column during Phase 1 is a
Change Request (Document 26 §Change Control).

---

## 11. Terminology & Naming Standard

Consistent naming prevents the single largest source of HRMS bugs — ambiguity between
*user*, *employee*, *candidate* and *person*. (Moved here from the original Document 00 §4 — it is
product terminology, not a document-index concern.)

| Term | Definition in this system |
|------|---------------------------|
| **Person** | Not modelled. Avoid the word. |
| **User** | An authenticatable identity. Has email/phone + password/OTP. May or may not be an Employee. |
| **Employee** | An employment record inside one Company. Has employee_code, joining date, CTC. An Employee **may exist without a User** (blue-collar staff with no login). |
| **Candidate** | An applicant record inside the ATS. Converts to Employee on onboarding. Never deleted on conversion — linked. |
| **Company / Tenant** | The paying customer. Top-level data isolation boundary. |
| **Branch / Location** | A physical or legal sub-unit of a Company. Drives compliance (PT state, shift, holidays). |
| **Legal Entity** | The registered company for statutory filing. One Company may own several Legal Entities. |
| **Employment** | A time-bounded relationship between an Employee and a Legal Entity. Supports rehire and inter-entity transfer. |
| **Assignment** | The current position: department, designation, grade, reporting manager, location, shift. **Time-versioned.** |
| **Attendance Day** | The atomic attendance unit: one employee, one calendar date, one resolved status. |
| **Pay Run** | An immutable payroll execution for a period + entity + employee group. |
| **Approval Request** | A generic instance of any workflow needing decisions. |

**Code conventions (updated for Python):** `snake_case` for DB columns, Python identifiers, and
JSON API fields; `PascalCase` for Python classes (SQLAlchemy models, Pydantic schemas); `kebab-case`
for URLs; `SCREAMING_SNAKE` for enums and permission keys. See Document 05 for the full coding
standard.
