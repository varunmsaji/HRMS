# HRMS Platform — Complete Development Documentation Set
**Version:** 1.0 (derived from Client Blueprint v1.0)
**Prepared for:** Engineering, QA, DevOps, Product & Client Sign-off
**Date:** August 2026

---

## 1. How to Use This Document Set

The client blueprint is a **one-page vision statement**. It names 22 modules but defines
zero fields, zero business rules, zero data models and zero acceptance criteria. This set
converts that vision into buildable engineering artefacts.

| # | Document | Primary Audience | Sign-off Needed From |
|---|----------|------------------|----------------------|
| 00 | This index + assumptions | Everyone | Client, PM |
| 01 | Business Requirements Document (BRD) | Client, Product, Sales | **Client** |
| 02 | Software Requirements Specification (SRS) | Devs, QA, Product | **Client + Tech Lead** |
| 03 | System Architecture & Tech Stack | Devs, DevOps, Architect | **CTO / Tech Lead** |
| 04 | Database Design & Data Dictionary | Backend, DBA | Tech Lead |
| 05 | API Specification & Contracts | Backend, Frontend, Mobile, Integrations | Tech Lead |
| 06 | RBAC & Permission Matrix | Backend, Security, Client | **Client** |
| 07 | Workflow, Approval & Notification Engine Spec | Backend | Tech Lead |
| 08 | AI & Automation Feature Spec | ML/AI Eng, Backend | Product |
| 09 | Integration Specification | Backend, DevOps, Partners | Tech Lead |
| 10 | Non-Functional Requirements, Security & Compliance | All + Legal | **Client + Legal** |
| 11 | UI/UX Screen Inventory & Design System | Design, Frontend, Mobile | Product |
| 12 | Project Plan, Sprints, Estimation & Team | PM, Client, Finance | **Client** |
| 13 | QA Strategy & Test Plan | QA | QA Lead |
| 14 | DevOps, Environments & Deployment Runbook | DevOps | DevOps Lead |
| 15 | Risk Register, Open Questions & Change Control | PM, Client | **Client** |

**Read order for a new developer joining:** 01 → 03 → 04 → 02 (your module only) → 05 → 06 → 14.

---

## 2. What the Client Blueprint Does NOT Yet Answer

These are **blocking questions**. Development of the affected module cannot start until answered.
The full list with impact analysis is in Document 15.

| ID | Question | Blocks |
|----|----------|--------|
| Q1 | Target countries for payroll statutory compliance? (Assumed: **India only** for Phase 1) | Payroll |
| Q2 | Deployment model — pure SaaS multi-tenant, or on-premise per enterprise client? | Architecture, DevOps |
| Q3 | Expected scale at 12 months: number of tenant companies and total employees? | Infra sizing, cost |
| Q4 | Is white-labelling required (client logo, custom domain, custom email sender)? | Multi-Company module |
| Q5 | Which biometric device brands must be supported on Day 1? | Attendance, Integrations |
| Q6 | Data residency requirement (India-only region)? | DevOps, Compliance |
| Q7 | Which accounting/ERP system for the Phase 1 integration (Tally / Zoho Books / SAP)? | Integrations |
| Q8 | Budget model: fixed-price scope-locked, or time & material with rolling backlog? | Contract, Plan |
| Q9 | Mobile: native (Kotlin/Swift), Flutter, or React Native? | Mobile team hiring |
| Q10 | Does "AI-powered" require in-house models, or is a third-party LLM API acceptable? | AI module, cost, privacy |

---

## 3. Working Assumptions (used throughout this document set)

Every assumption below is **replaceable**. Where an assumption drives significant cost, it is
flagged with **[COST]**. Client must confirm or reject each before Sprint 1 closes.

### 3.1 Business Assumptions
- **A1.** Primary market is **India**; payroll statutory engine implements Indian law (EPF, ESI,
  PT, TDS, Gratuity, Bonus, LWF). Multi-country is a Phase 3 architectural allowance, not a
  Phase 1 feature. **[COST]** Each additional country ≈ 6–10 developer-weeks.
- **A2.** Delivery model is **multi-tenant SaaS** on public cloud. On-premise deployment is
  offered only as an enterprise add-on from Phase 3.
- **A3.** Pricing is per-employee-per-month (PEPM) with module-based plan tiers. The platform
  must therefore enforce **feature entitlements per tenant subscription plan** — this is a real
  functional requirement, not an afterthought (see SRS §14).
- **A4.** "Automates 70–80% of HR operations" is interpreted as a measurable target:
  ≥75% of routine HR transactions (leave, attendance regularisation, payroll run, letter
  generation, onboarding tasks) complete without HR manual data entry. Metrics defined in BRD §7.
- **A5.** The 8 target industries are served through **configuration, not code forks** — industry
  templates seed different shift patterns, wage structures, compliance sets and field labels.

### 3.2 Technical Assumptions
- **A6.** Stack: **PostgreSQL 16 + NestJS (Node 20/TypeScript) + React 18 (Next.js) + React Native
  + Redis + BullMQ + Python FastAPI for AI services**, on AWS ap-south-1 (Mumbai).
  Alternatives table and rationale in Doc 03 §2. If the client's existing team is a PHP/Laravel or
  Java/Spring shop, swap the backend — the architecture, data model and API contracts stay valid.
- **A7.** Tenant isolation = **shared database, shared schema, `company_id` on every row, enforced
  by PostgreSQL Row-Level Security + application-layer tenant context**. Enterprise clients
  needing physical isolation get a dedicated database on the same codebase.
- **A8.** AI features Phase 1 use a **hosted LLM API (Claude/OpenAI) + classical ML (scikit-learn/
  XGBoost) for scoring models**. No model training from scratch in Phase 1.
- **A9.** All timestamps stored in **UTC**; rendered in the company's configured timezone.
  Payroll and attendance date boundaries use the **company timezone**, never UTC.
- **A10.** Money stored as **integer minor units** (paise) with an explicit `currency` column.
  Never floats. Payroll arithmetic uses a decimal library, rounding rules defined per component.

### 3.3 Scope Assumptions
- **A11.** Phase 1 (MVP) = the 14 items in the client's Phase 1 list. The remaining 8 modules
  (Asset, Learning, Expense, Helpdesk, Visitor, Employee Experience, Communication, advanced
  Performance) are Phase 2/3. See Doc 12 for phase mapping.
- **A12.** "Mobile App" in Phase 1 means an **employee + manager app** (ESS, attendance punch,
  leave, approvals, payslip, directory). Full HR admin functions remain web-only.
- **A13.** Data migration from the client's existing systems is **out of scope** unless separately
  scoped; a generic Excel importer with validation is in scope.

---

## 4. Terminology & Naming Standard

Consistent naming prevents the single largest source of HRMS bugs — ambiguity between
*user*, *employee*, *candidate* and *person*.

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

**Code conventions:** `snake_case` for DB columns and JSON API fields; `PascalCase` for classes;
`kebab-case` for URLs; `SCREAMING_SNAKE` for enums and permission keys.

---

## 5. Critical Engineering Principles for This Product

These five principles are not negotiable. Violating them is what turns HRMS projects into
unmaintainable rewrites in year two.

1. **Everything about an employee is time-versioned.** Salary, designation, manager, department,
   shift and location all change over time, and payroll for March must use March's values even if
   run in June. Never overwrite; always insert a new effective-dated row. (Doc 04 §3.)

2. **Payroll outputs are immutable.** Once a pay run is finalised, its results are frozen. Errors
   are fixed with an arrears/adjustment component in a later run, never by editing history.

3. **Configuration over code.** Leave rules, shift rules, salary structures, approval chains,
   letter templates, workflow states and field labels are **tenant data**, not `if` statements.
   The moment a customer request produces a `if (company.name === 'X')`, the design has failed.

4. **Every state change is audited.** Who, what, before, after, when, from which IP. HR data is
   litigable. The audit log is append-only and is itself a feature (see SRS §16).

5. **Tenant context is enforced at the lowest possible layer.** A missing `WHERE company_id = ?`
   must be impossible, not merely discouraged. Enforced by RLS + a repository base class +
   a CI lint rule + an automated cross-tenant leakage test suite.

---

## 6. Document Change Control

Any change to a signed-off document requires a Change Request (template in Doc 15 §4) with
impact analysis on scope, schedule and cost. Version numbers follow `MAJOR.MINOR`:
`MINOR` for clarifications, `MAJOR` for scope changes.
