# Document 17 — Software Requirements Specification: Phase 1 Core Modules

*(Renumbered and updated from Document 02A for the Python/FastAPI backend architecture — see Document 00 for the full document map.)*

**Requirement ID format:** `FR-<MODULE>-<nnn>`
**Priority:** M = Must (MVP), S = Should, C = Could
Every requirement has at least one acceptance criterion (AC). QA writes test cases directly from AC.

---

# 1. Authentication, Identity & Session (AUTH) — Priority P1

## 1.1 Functional Requirements

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-AUTH-001 | Users authenticate with email + password, or mobile + OTP. Employee identity is resolved via `user_id → employee_id` within the selected company context. | M |
| FR-AUTH-002 | A single User may belong to multiple Companies (consultant/multi-entity). After login, if >1 company, present a company selector; the chosen `company_id` scopes the entire session. | M |
| FR-AUTH-003 | Password policy: min 10 chars, 1 upper, 1 digit, 1 symbol, not in the top-10k breached list, no reuse of last 5, forced rotation configurable per tenant (default: never — rotation harms security when combined with complexity). | M |
| FR-AUTH-004 | Account lockout after 5 failed attempts in 15 min; exponential backoff; unlock via email link or admin action. Lockout must not reveal whether the account exists. | M |
| FR-AUTH-005 | MFA via TOTP (authenticator app) and SMS OTP. Mandatory for Super Admin and Company Admin; optional-per-tenant for others. | M |
| FR-AUTH-006 | JWT access token (15 min) + rotating refresh token (30 days, HttpOnly Secure SameSite=Strict cookie for web; secure storage for mobile). Refresh-token reuse detection revokes the whole family. | M |
| FR-AUTH-007 | Session management screen: list active sessions (device, IP, location, last active), revoke individually or all. | S |
| FR-AUTH-008 | Forgot password: single-use token, 30-min expiry, invalidated on use, rate-limited to 3/hour/account. Response is identical whether or not the account exists. | M |
| FR-AUTH-009 | First-login forced password change for admin-created accounts; invitation links expire in 7 days. | M |
| FR-AUTH-010 | SSO via SAML 2.0 and OIDC (Google Workspace, Microsoft Entra ID), configurable per tenant, with optional JIT user provisioning mapped to a default role. | S (Phase 2) |
| FR-AUTH-011 | Impersonation: Super Admin may impersonate a tenant user **only** with a recorded reason, a time limit (max 60 min), a banner visible in UI, full audit, and never for actions marked `NO_IMPERSONATION` (payroll finalise, salary view, delete). | M |
| FR-AUTH-012 | Device binding for mobile attendance: an employee's punch device is registered; changing device requires HR approval (prevents buddy punching). | M |
| FR-AUTH-013 | API access for integrations uses scoped API keys / OAuth2 client-credentials, per tenant, with rotation and revocation. | S |

## 1.2 Acceptance Criteria (sample)
- **AC-AUTH-002.1** Given a user linked to 3 companies, when they log in, then a company chooser lists exactly those 3 and no data is queryable before selection.
- **AC-AUTH-002.2** Given company A is selected, when the API receives a request for a resource in company B, then it returns 404 (not 403 — do not confirm existence).
- **AC-AUTH-006.1** Given a refresh token is used twice, then all tokens in that family are revoked and the user is forced to re-authenticate, and a security alert is emailed.
- **AC-AUTH-011.1** Given Super Admin impersonation is active, when they attempt to finalise a pay run, then the action is blocked with `IMPERSONATION_FORBIDDEN`.

## 1.3 Negative / Edge Cases
- Deactivated employee's user account must be disabled within 60 seconds of exit finalisation.
- A user whose only employee record is exited but who has pending F&F must retain **restricted ex-employee access** (payslips, Form 16, tax docs) for 12 months — this is a distinct role, `EX_EMPLOYEE`.
- Concurrent login from a new country/IP triggers a notification, not a block.

---

# 2. Role-Based Access Control (RBAC) — Priority P1

## 2.1 Model
Three-layer model. Do not simplify this — HRMS access control failures are the #1 cause of
customer churn and legal exposure.

1. **Permission** — an atomic capability, e.g. `EMPLOYEE.VIEW`, `PAYROLL.RUN.FINALISE`.
2. **Role** — a named bundle of permissions. System roles are seeded; tenants may clone and edit.
3. **Data Scope** — the set of records a role instance may touch: `SELF | REPORTEES | REPORTEE_TREE | DEPARTMENT | BRANCH | LEGAL_ENTITY | COMPANY | ALL_COMPANIES`.

**Effective access = Permission ∧ Data Scope ∧ Field-level mask ∧ Module entitlement (subscription plan).**

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-RBAC-001 | Seed 10 system roles matching the client hierarchy: Super Admin, Company Admin, HR Manager, HR Executive, Recruiter, Reporting Manager, Team Leader, Employee, Finance, Auditor. Plus `EX_EMPLOYEE` and `CANDIDATE` (external portal). | M |
| FR-RBAC-002 | Tenants can create custom roles by cloning a system role; system roles themselves are read-only. | M |
| FR-RBAC-003 | A user may hold multiple roles; effective permissions are the **union**, effective data scope is the **widest**. Explicit DENY overrides any ALLOW. | M |
| FR-RBAC-004 | Field-level security: mark fields as `PUBLIC | INTERNAL | SENSITIVE | RESTRICTED`. Salary, bank account, PAN, Aadhaar, medical, disciplinary and background-check data are `RESTRICTED` by default. | M |
| FR-RBAC-005 | Data scope is evaluated at query time in the persistence layer, never in the controller, and never by filtering after fetch. | M |
| FR-RBAC-006 | Permission changes take effect within 60 seconds (cache TTL) or immediately via cache invalidation on write. | M |
| FR-RBAC-007 | An access-review report lists every user, role, scope and last-login, exportable for audit. | S |
| FR-RBAC-008 | Temporary role grants with an expiry date (e.g. HR cover during leave) auto-revoke. | S |
| FR-RBAC-009 | Every permission check failure is logged with actor, resource, permission and outcome. | M |

**AC-RBAC-003.1** Given a user is both Reporting Manager (scope REPORTEE_TREE) and HR Executive
(scope BRANCH), when they list employees, they see the union of both sets, with no duplicates.
**AC-RBAC-004.1** Given a Reporting Manager without `PAYROLL.VIEW_SENSITIVE`, when they open a
reportee's profile, the CTC and bank fields are absent from the **API response**, not merely
hidden in the UI.

Full permission catalogue and role×permission matrix: **Document 19**.

---

# 3. Company & Organisation Setup (ORG) — Priority P2

## 3.1 Hierarchy
```
Company (tenant)
 └── Legal Entity (registered employer; PF/ESI/TAN/PAN/GST)
      └── Branch / Location (address, state → PT & holiday calendar, geo-fence)
           └── Department
                └── Sub-department (optional, max 5 levels)
Cross-cutting: Designation · Grade/Band · Cost Centre · Employment Type · Business Unit
```

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-ORG-001 | Company registration: name, industry (drives template seeding), country, currency, timezone, financial year start, logo, subdomain. | M |
| FR-ORG-002 | On company creation, seed industry-specific defaults: leave types, shift patterns, salary structure template, holiday calendar, workflow templates, letter templates, designation list. | M |
| FR-ORG-003 | Legal Entity: registered name, address, PAN, TAN, CIN, GSTIN, PF establishment code, ESI code, PT registration per state, LWF registration, signatory name/designation/signature image. | M |
| FR-ORG-004 | Branch: name, code, address, state (drives PT slab and state holidays), timezone, geo-coordinates + geofence radius (metres), week-off pattern, associated legal entity. | M |
| FR-ORG-005 | Department: name, code, head (employee), parent department, cost centre. Hierarchy must reject cycles. | M |
| FR-ORG-006 | Designation: title, grade/band, department (optional), job description reference, career-path next designation. | M |
| FR-ORG-007 | Grade/Band: code, level, min/max CTC, leave entitlement override, notice period override, probation override, approval-limit override. | M |
| FR-ORG-008 | Holiday calendar: per branch/state and per year; supports fixed, floating/optional (employee picks N of M) and restricted holidays. | M |
| FR-ORG-009 | Financial-year and payroll-cycle setup: FY start month, salary cycle (calendar month / 26th–25th / custom), payroll cut-off day, pay date rule (last working day / fixed day + holiday shift rule). | M |
| FR-ORG-010 | Employment types: Permanent, Probation, Contract, Intern, Consultant, Part-time, Temporary, Apprentice, Daily-wage — each with its own statutory applicability flags. | M |
| FR-ORG-011 | Numbering series configurator: employee code, candidate ID, offer ID, asset ID, ticket ID — prefix + separator + running number + reset rule (never/yearly). Must be gap-free and race-safe. | M |
| FR-ORG-012 | Custom fields: tenant defines extra fields on Employee/Candidate/Asset — type (text, number, date, dropdown, multi-select, file, boolean), required flag, visibility by role, section placement, up to 40 per entity. | M |
| FR-ORG-013 | Org chart auto-generated from reporting relationships, with drill-down, search, export to PNG/PDF, and detection of orphans and cycles. | S |
| FR-ORG-014 | Deactivating an org unit (branch/department/designation) is allowed only if no active employee is assigned; otherwise show the blocking list. Never hard-delete. | M |

**AC-ORG-011.1** Given 50 concurrent employee creations, when codes are generated, then all 50 are
unique and sequential with no gaps and no duplicates (test with parallel transactions).
**AC-ORG-008.1** Given a branch in Kerala and one in Karnataka, when the holiday calendar for 2027
is generated, each branch shows its own state holidays and the common national ones.

---

# 4. Employee Management (EMP) — Priority P3

## 4.1 The Central Design Decision: Time-Versioned Records

An employee is **not** a flat row. It is a core identity plus a set of effective-dated histories.

```
employee (identity: code, name, DOB, gender, blood group, personal contacts)
 ├── employment[]     (entity, joining date, exit date, employment type, probation, confirmation)
 ├── assignment[]     (effective_from/to → department, designation, grade, manager, branch, shift, cost centre)
 ├── compensation[]   (effective_from/to → CTC, structure, components, revision reason)
 ├── statutory[]      (effective_from/to → PF applicability & UAN, ESI applicability & IP no., PT state, tax regime)
 ├── bank[]           (effective_from/to → account, IFSC, payment mode)
 ├── document[]       (type, number, issue/expiry, file, verification status)
 ├── dependent[]      (relation, name, DOB, for insurance/nominee/gratuity)
 ├── education[] / experience[] / skill[] / certification[]
 ├── address (permanent + current, emergency contact)
 └── audit trail (every change, who/when/before/after)
```

## 4.2 Requirements

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-EMP-001 | Create employee via: manual form, candidate→employee conversion from ATS, bulk Excel import, or API. | M |
| FR-EMP-002 | Mandatory-at-creation fields: employee code (auto), first name, joining date, legal entity, branch, department, designation, employment type, reporting manager (nullable for CEO). All other fields completable later with a profile-completeness indicator. | M |
| FR-EMP-003 | Every assignment change (transfer, promotion, manager change, shift change) creates a **new effective-dated row**; the previous row is closed the day before. Overlaps must be impossible (DB exclusion constraint). | M |
| FR-EMP-004 | Backdated changes are permitted only if the effective date is after the last finalised payroll period, unless the user holds `PAYROLL.BACKDATE_OVERRIDE`, in which case arrears are auto-generated. | M |
| FR-EMP-005 | Future-dated changes are supported and activate automatically on the effective date via a scheduled job. | M |
| FR-EMP-006 | Bulk import: downloadable template, dry-run validation with row-level errors, partial-commit prohibited (all-or-nothing per file), import log retained. Max 5,000 rows/file. | M |
| FR-EMP-007 | Document management: type-wise upload (Aadhaar, PAN, passport, education, experience, offer, contract), expiry tracking with 30/15/7-day alerts, verification status workflow, virus scan, encrypted at rest. | M |
| FR-EMP-008 | Employee directory: search by name/code/email/phone/skill, filter by department/branch/designation/status, card & table views, export subject to permission. | M |
| FR-EMP-009 | Profile change requests: employee edits go to HR approval for controlled fields (name, DOB, bank, PAN, address); uncontrolled fields (photo, emergency contact, personal email) update directly. Field controllability is configurable. | M |
| FR-EMP-010 | Probation & confirmation: probation end date auto-computed; T-30/T-15/T-0 reminders; confirmation workflow with manager recommendation; auto-extend or auto-confirm on rule; confirmation letter generation. | M |
| FR-EMP-011 | Transfer (inter-branch, inter-department, inter-entity): workflow with effective date; inter-entity transfer closes one employment and opens another, carrying leave balance per policy and handling PF transfer/settlement. | M |
| FR-EMP-012 | Promotion: new designation + grade + optional compensation revision, in a single workflow, generating a promotion letter. | M |
| FR-EMP-013 | Reporting manager change with reassignment of pending approvals to the new manager. | M |
| FR-EMP-014 | Employee statuses: `PRE_JOINING`, `PROBATION`, `ACTIVE`, `ON_NOTICE`, `SUSPENDED`, `ON_LONG_LEAVE`, `EXITED`, `ABSCONDING`, `RETIRED`, `DECEASED`. State-machine transitions only. | M |
| FR-EMP-015 | Rehire: on re-creating an employee with a matching PAN/Aadhaar/email, warn and offer to link to the prior record, preserving history and prior UAN. | S |
| FR-EMP-016 | Letters: 12 seeded templates (offer, appointment, confirmation, promotion, transfer, increment, warning, experience, relieving, NOC, address proof, salary certificate) with merge fields, digital signature image, PDF generation, watermark option, issue log. | M |
| FR-EMP-017 | 360° employee view: single screen with tabs — Profile, Job, Compensation (permission-gated), Attendance, Leave, Documents, Assets, Performance, Training, Timeline of all events. | M |
| FR-EMP-018 | Notice period, probation duration, leave entitlement and shift resolve through the override chain: Employee → Grade → Designation → Department → Branch → Company (most specific wins). | M |

**AC-EMP-003.1** Given an employee is promoted effective 01-Jul, when I view their designation as
of 30-Jun, the old designation is returned; as of 01-Jul, the new one.
**AC-EMP-004.1** Given June payroll is finalised, when HR backdates a salary revision to 01-Jun,
then the system blocks it unless the user has the override permission, and if overridden, creates
an arrears line in the July run equal to the June differential.
**AC-EMP-006.1** Given an import file with 3 invalid rows out of 500, then nothing is committed and
a report names row numbers, columns and reasons.

---

# 5. Attendance (ATT) — Priority P5

Attendance is the highest-volume, highest-complexity, most industry-variable module. Get the
model wrong and payroll is wrong forever.

## 5.1 Core Model
- **Punch** (raw, immutable): source, timestamp, device/geo, direction (IN/OUT/AUTO), employee.
- **Attendance Day** (derived, recomputable): one row per employee per date, holding first-in,
  last-out, worked hours, break hours, OT hours, late/early minutes, resolved status, source of truth.
- **Recomputation** is idempotent: given the same punches + policies + leaves + holidays, the day
  always resolves the same way. Every recompute logs its inputs.

## 5.2 Capture Sources
| Source | Notes |
|---|---|
| Biometric device (push/pull) | ZKTeco/eSSL push protocol; ADMS; poller fallback; device heartbeat monitoring |
| Face recognition | Liveness detection required; device-side or server-side matching |
| Mobile app GPS | Geo-fence validation, mock-location detection, device binding |
| Mobile app selfie punch | Face match against profile photo; stored with punch |
| Web punch | IP allow-list restricted |
| Kiosk / shared tablet | Employee code + PIN or face |
| QR code at site | Rotating QR to prevent screenshot sharing |
| Manual entry by HR | Always flagged as manual with reason + audit |
| Bulk import | For legacy/muster roll |
| RFID / access-control system | Via integration |

## 5.3 Requirements

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-ATT-001 | Shift master: name, start/end time, break windows (paid/unpaid), grace-in/grace-out minutes, half-day threshold, min hours for full day, night-shift flag, cross-midnight handling, weekly-off pattern, OT eligibility. | M |
| FR-ATT-002 | Shift assignment: default per employee, override per date via roster; rotating shift patterns (e.g. 6 days A → 1 off → 6 days B) auto-generated for N weeks ahead. | M |
| FR-ATT-003 | Flexible shift: no fixed start; full day = min N worked hours within a window. Required for IT. | M |
| FR-ATT-004 | Split shift: two duty blocks in one day with an unpaid gap. Required for hotels/retail. | M |
| FR-ATT-005 | Cross-midnight shifts attribute the whole duty to the **shift start date**, not the calendar date of each punch. | M |
| FR-ATT-006 | Status resolution engine produces exactly one status per day from: `PRESENT`, `ABSENT`, `HALF_DAY`, `WEEKLY_OFF`, `HOLIDAY`, `ON_LEAVE` (type), `ON_DUTY`, `WFH`, `COMP_OFF`, `NOT_JOINED`, `EXITED`. Precedence order is configurable but defaults to: Not joined/Exited > Approved leave > Holiday > Weekly off > Punch-derived. | M |
| FR-ATT-007 | Late-in/early-out policy: grace minutes, then rules such as "3 lates = 1 half-day per month", configurable, with automatic deduction posting to payroll. | M |
| FR-ATT-008 | Overtime: eligibility by employment type/grade, pre-approval required flag, min OT threshold, max OT cap per day/week/month, rate multipliers per day-type (weekday/weekly-off/holiday/night), and statutory 2× default for factory workers. OT must not be auto-paid without an approval record. | M |
| FR-ATT-009 | Compensatory off: earned for approved work on weekly-off/holiday, credited to a comp-off ledger with an expiry (default 90 days), usable as leave. | M |
| FR-ATT-010 | Regularisation: employee raises a request for missing punch / wrong punch / on-duty / WFH with reason and optional attachment; manager approves; the attendance day recomputes; monthly limit configurable. | M |
| FR-ATT-011 | Geo-fencing: punch accepted only within radius R of an assigned branch/site; multiple sites per employee; out-of-fence punch either blocked or accepted-with-flag for manager approval (configurable). | M |
| FR-ATT-012 | Offline mobile punch: stored locally with device timestamp + GPS, synced when connectivity returns, marked `OFFLINE_SYNCED`, with clock-tamper detection (device time vs server time delta > 5 min → flag). **Mandatory for construction/logistics.** | M |
| FR-ATT-013 | Attendance calendar view (employee) and matrix view (manager/HR: employees × dates grid with colour codes, inline edit for permitted roles). | M |
| FR-ATT-014 | Muster roll / daily-wage mode: mark present/absent in bulk for a site or contractor, with headcount reconciliation. | M (Construction) |
| FR-ATT-015 | Attendance lock: HR locks a period after payroll input freeze; locked days reject edits without `ATTENDANCE.UNLOCK`. | M |
| FR-ATT-016 | Device management: register device, map to branch, monitor heartbeat, alert when a device is silent > 2 hours, replay missed punches on reconnect, deduplicate. | M |
| FR-ATT-017 | Duplicate/bounce punch suppression: repeat punches within N seconds (default 60) collapse to one. | M |
| FR-ATT-018 | Attendance summary per employee per month: present, absent, leave, holiday, week-off, half-days, LOP days, OT hours, late count — the **single input contract to payroll**. | M |
| FR-ATT-019 | Recompute-on-change: approving a leave, changing a shift, adding a holiday or regularising must re-derive affected attendance days automatically and notify if payroll for that period is already locked. | M |
| FR-ATT-020 | Timesheet (project/task hours) with daily/weekly entry, project & activity codes, approval, and billable flag. | S (IT — Phase 2) |

**AC-ATT-005.1** Given a 22:00–06:00 shift on 10-Mar, punches at 21:55 and 06:10 (11-Mar) produce
one attendance day dated **10-Mar** with 8h5m worked, not two partial days.
**AC-ATT-008.1** Given an employee works 3 hours beyond shift with no approved OT request and the
policy requires pre-approval, then OT hours are recorded as `unapproved_ot` and are **excluded**
from payroll until approved.
**AC-ATT-012.1** Given a device is offline for 6 hours and 40 punches are queued, when sync occurs,
all 40 are ingested exactly once (idempotency key = device_id + employee_code + timestamp).
**AC-ATT-019.1** Given attendance for 12-Mar is `ABSENT` and a leave for 12-Mar is approved on
20-Mar, then 12-Mar becomes `ON_LEAVE` automatically and the March payroll LOP recalculates.

---

# 6. Leave Management (LEV) — Priority P5

## 6.1 Ledger Principle
Leave balance is **never a stored mutable number**. It is `SUM(credits) − SUM(debits)` over an
append-only `leave_ledger` table with entry types: `OPENING`, `ACCRUAL`, `APPLICATION_APPROVED`,
`APPLICATION_CANCELLED`, `ENCASHMENT`, `LAPSE`, `CARRY_FORWARD_IN/OUT`, `ADJUSTMENT`, `COMP_OFF_CREDIT`.
Every entry carries a reason and a source reference. This makes every balance explainable to an
employee and an auditor — which is exactly what HR spends its day doing.

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-LEV-001 | Leave type master: code, name, paid/unpaid, accrual method (monthly / quarterly / yearly / on-joining / none), accrual rate, pro-rata on joining & exit, max balance cap, carry-forward allowed + cap, encashable + rate basis, lapse rule, negative balance allowed + limit, applicable gender/marital/employment-type/grade, min & max days per application, notice days required, backdated application allowed + limit, requires document above N days, counts sandwich holidays, half-day allowed, hourly leave allowed. | M |
| FR-LEV-002 | Seeded Indian leave types: Casual (CL), Sick (SL), Earned/Privilege (EL/PL), Loss of Pay (LOP), Maternity (26 weeks), Paternity, Bereavement, Marriage, Comp-off, Restricted Holiday, Sabbatical, Vacation (education). | M |
| FR-LEV-003 | Accrual job runs on schedule (monthly on day N / on joining anniversary / on FY start), pro-rated for mid-period joiners & exits, idempotent (re-running never double-credits). | M |
| FR-LEV-004 | Sandwich rule: configurable whether intervening weekly-offs/holidays count as leave. Must support "count only if both adjacent days are leave". | M |
| FR-LEV-005 | Application: type, from/to, half-day (first/second half), reason, contact during leave, handover-to employee, attachment. Balance validated at application time **and again at approval time**. | M |
| FR-LEV-006 | Overlap prevention: no two approved leaves may overlap for the same employee; leave cannot overlap an existing approved on-duty/WFH. | M |
| FR-LEV-007 | Multi-level approval routed by the workflow engine (Document 20), default L1 = reporting manager, L2 = HR for >N days. | M |
| FR-LEV-008 | Cancellation & withdrawal: before start (auto-approve or manager approval), after start (partial cancellation with recalculation and ledger reversal), after payroll finalisation (blocked — creates an adjustment instead). | M |
| FR-LEV-009 | Team leave calendar with conflict view; policy option to block if >X% of a department is on leave on the same day. | S |
| FR-LEV-010 | Holiday & weekly-off aware day counting: `leave_days` computed excluding holidays/week-offs unless the sandwich rule says otherwise. Displayed to the employee before submission. | M |
| FR-LEV-011 | Encashment: eligibility rule, max encashable days, basis (Basic / Basic+DA / Gross), request workflow, posted to payroll as a component. | S |
| FR-LEV-012 | Year-end processing: carry-forward within cap, lapse the excess, optional auto-encash the excess, with a preview report before commit and full ledger entries. | M |
| FR-LEV-013 | Leave balance statement: opening, credits, debits, closing, per type, per period, downloadable — the single artefact that ends "my leave balance is wrong" disputes. | M |
| FR-LEV-014 | LOP: when leave is unpaid or balance is insufficient, LOP days flow into the payroll pay-days calculation automatically. | M |
| FR-LEV-015 | Compensatory-off ledger integrated with attendance (FR-ATT-009), FIFO consumption, expiry job. | M |
| FR-LEV-016 | Maternity leave: 26 weeks for first two children, 12 weeks thereafter (configurable), with expected-delivery-date-based planning and medical-certificate upload; job protection flag prevents exit workflows during the period. | M |

**AC-LEV-003.1** Given the accrual job is executed twice for March, then the ledger contains exactly
one March accrual entry per employee.
**AC-LEV-005.1** Given an employee has 2.5 CL and applies for 3 days with negative balance disallowed,
then the application is rejected at submission with the balance shown.
**AC-LEV-008.1** Given an approved 5-day leave has started and the employee returns after 2 days,
when HR partially cancels the remaining 3 days, then 3 days are credited back and attendance for
those dates recomputes to present/absent by punches.

---

# 7. Payroll (PAY) — Priority P6

The module with the least tolerance for error. Design for **correctness and explainability first,
speed second**.

## 7.1 Architecture
```
Inputs                       Engine                        Outputs
─────────────────────────    ──────────────────────────    ─────────────────────────
Compensation structure   →   1. Snapshot inputs        →   Payslip (per employee)
Attendance summary       →   2. Compute pay days       →   Payment/bank advice file
Leave/LOP                →   3. Earnings               →   Statutory: ECR, ESI, PT, TDS
OT & incentives          →   4. Statutory deductions   →   Accounting journal voucher
Arrears & adjustments    →   5. Income tax (TDS)       →   Reimbursement register
Loans & advances         →   6. Other deductions       →   Variance vs last month report
Reimbursements/expenses  →   7. Net pay + rounding     →   Form 16 / Form 24Q data
Statutory master (dated) →   8. Freeze & lock          →   Audit trail of every formula
```

## 7.2 Requirements — Setup

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-PAY-001 | Salary component master: code, name, type (`EARNING | DEDUCTION | EMPLOYER_CONTRIBUTION | REIMBURSEMENT | INFORMATIONAL`), calculation type (`FIXED | PERCENTAGE_OF | FORMULA | SLAB | ATTENDANCE_BASED | MANUAL`), base component reference, taxable flag, PF-applicable flag, ESI-applicable flag, PT-applicable flag, LOP-applicable flag, arrears-applicable flag, pro-rata rule, rounding rule, display order, show-on-payslip flag. | M |
| FR-PAY-002 | Formula builder with a safe expression language (no arbitrary code execution): references to other components, employee attributes, attendance values, and functions `MIN/MAX/ROUND/IF/SLAB`. Validated for circular references at save time. | M |
| FR-PAY-003 | Salary structure/template: an ordered set of components with values or formulas, assignable per grade/designation/employee, with CTC-to-gross-to-net breakup preview. | M |
| FR-PAY-004 | CTC builder: enter CTC → auto-distribute across components per template → show monthly & annual breakup, employer contributions, and net take-home estimate. Reverse mode: enter desired net → derive CTC. | M |
| FR-PAY-005 | Statutory master (effective-dated, never hardcoded — BR-10): PF employee %, employer split (EPS/EPF), wage ceiling, admin & EDLI charges, VPF; ESI employee %, employer %, wage ceiling, contribution periods; PT slabs per state with frequency; LWF per state; TDS slabs for both regimes with surcharge & cess; gratuity formula & ceiling; bonus %, eligibility ceiling & calculation ceiling. **All values are seeded as data and require compliance sign-off (Document 02 D5) before go-live.** | M |
| FR-PAY-006 | Employee statutory profile: PF applicable + UAN + PF number + VPF amount/% + higher-wage-PF opt-in; ESI applicable + IP number; PT state; tax regime (old/new) with a once-per-FY switch rule; PAN; Aadhaar. | M |

## 7.3 Requirements — Processing

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-PAY-007 | Pay run lifecycle: `DRAFT → INPUTS_LOCKED → COMPUTED → UNDER_REVIEW → APPROVED → FINALISED → PAID`. Only `FINALISED` publishes payslips. Rollback allowed only before `FINALISED`. | M |
| FR-PAY-008 | Pay-days computation: `payable_days = total_days − LOP_days` (or working-days basis, configurable per company: calendar days / working days / fixed 26 / fixed 30). This single setting changes every salary in the system — it must be explicit, versioned and change-controlled. | M |
| FR-PAY-009 | Mid-month joiner/leaver pro-ration by the same day-basis rule; joining and exit dates inclusive. | M |
| FR-PAY-010 | Arrears engine: detects retrospective salary revisions, leave/attendance corrections and missed payments, computes the differential per component per affected month, and posts as a separate `ARREARS` line with a month-wise breakup on the payslip. | M |
| FR-PAY-011 | Income tax (TDS): annual projection = actual YTD + projected remaining months; declarations under Chapter VI-A (80C/80D/80E/80G/80TTA), HRA exemption with rent-paid & metro rule, LTA, standard deduction, professional tax deduction, previous-employer income (Form 12B); regime comparison; monthly TDS = (annual tax − TDS already deducted) ÷ remaining months; proof-submission window with HR verification and recomputation. | M |
| FR-PAY-012 | Loans & advances: request, approval, disbursement, EMI schedule, auto-deduction, part-prepayment, foreclosure on exit, interest (perquisite) handling, outstanding balance report. | M |
| FR-PAY-013 | Reimbursements: claim → approval → payment either through payroll or separately; tax-exempt categories with limits (fuel, telephone, books, uniform); balance tracking against annual entitlement. | S |
| FR-PAY-014 | Variance report (mandatory pre-finalise gate): for every employee, this month vs last month per component, with % change, flagging anything beyond a threshold. **The pay run cannot be finalised until every flagged variance is acknowledged with a reason.** This single control prevents most payroll disasters. | M |
| FR-PAY-015 | Payroll validation checks before finalise: negative net pay, net > gross, zero net for an active employee, missing bank details, missing PAN for TDS > threshold, PF/ESI applicability mismatch, employees present in attendance but absent from the run, duplicate bank accounts, salary below minimum wage for the state/skill category. | M |
| FR-PAY-016 | Off-cycle / supplementary pay run for bonus, incentive, arrears, final settlement — same engine, flagged separately, with correct TDS treatment. | M |
| FR-PAY-017 | Payslip: PDF per employee, company-branded, showing earnings, deductions, employer contributions (optional), YTD columns, leave balance, pay days, net in words, password protection (default: PAN + DOB pattern), bulk generation, publish-to-ESS, email/WhatsApp delivery. | M |
| FR-PAY-018 | Bank advice / payment file in NEFT/RTGS/IMPS formats for major banks (HDFC, ICICI, SBI, Axis, Kotak) plus a generic CSV; multiple banks in one run; encrypted download with an access log. | M |
| FR-PAY-019 | Statutory outputs: PF ECR text file, ESI contribution file, PT challan data per state, Form 24Q quarterly TDS data, Form 16 Part B generation, LWF statement, Gratuity provision report, Bonus register (Form C), Muster roll & wage register formats (Form 12/16/17 as applicable). | M |
| FR-PAY-020 | Accounting journal voucher: configurable mapping of components → GL codes and cost centres, with a balanced debit/credit output, exportable to Tally XML / Zoho / generic CSV. | M |
| FR-PAY-021 | Payroll register, salary sheet, component-wise summary, department/cost-centre-wise cost, CTC vs actual analysis, headcount reconciliation. | M |
| FR-PAY-022 | Full & final settlement: triggered by exit, computes salary till last working day, leave encashment, gratuity (if ≥5 years), bonus, notice-pay recovery or payment, loan recovery, asset-recovery deductions, and produces an F&F statement requiring employee acknowledgement. | M |
| FR-PAY-023 | Payroll locking & immutability: after finalisation, no input for that period may change. Any correction is an arrears/recovery in a later run (BR-05). | M |
| FR-PAY-024 | Every computed line stores its **calculation trace** (formula, inputs, intermediate values) so any figure can be explained without re-running. | M |
| FR-PAY-025 | Multi-entity payroll: one run per legal entity; a consolidated view across entities for the Company Admin. | M |

**AC-PAY-008.1** Given company basis = "fixed 30 days" and an employee joins on 16-Apr, then payable
days = 15 and gross = monthly gross × 15/30 exactly, verified against a manual calculation.
**AC-PAY-014.1** Given an employee's net pay changed by 40% and the threshold is 15%, then finalise
is blocked until a reason is recorded against that employee.
**AC-PAY-023.1** Given March is finalised, when HR approves a leave for 10-Mar, then the leave is
accepted but March payroll is unchanged, and an arrears/LOP-reversal line appears in April.
**AC-PAY-011.1** Given an employee declares ₹1,50,000 under 80C and does not submit proof by the
cut-off, then the projection recomputes without it and the shortfall TDS is spread over the
remaining months (or recovered fully in March if none remain).

---

# 8. Recruitment / ATS (REC) — Priority P4

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-REC-001 | Manpower requisition: raised by a manager, specifying department, designation, positions, budget/CTC range, justification, replacement-or-new, target date; multi-level approval (manager → HOD → HR → Finance for budget). | M |
| FR-REC-002 | Job opening created from an approved requisition: title, description, responsibilities, skills (must/good), experience range, qualification, location, employment type, salary range (internal/external visibility), hiring team, pipeline stages, closing date. | M |
| FR-REC-003 | Publishing: careers page (tenant-branded, SEO-friendly), internal job posting for employees, shareable link, and integrations to LinkedIn/Naukri/Indeed where feasible (Phase 2). | M / S |
| FR-REC-004 | Candidate sources: careers-page application, manual entry, bulk resume upload (ZIP), email-inbox parsing (`careers@` mailbox), employee referral portal, agency portal with agency attribution and duplicate arbitration. | M |
| FR-REC-005 | Resume parsing extracts name, email, phone, total experience, current company/designation, skills, education, location, notice period; confidence scores shown; parsed values editable. Target ≥85% field accuracy on standard formats. | M |
| FR-REC-006 | Duplicate detection on email/phone/resume-hash across the tenant, with a merge flow preserving both application histories. | M |
| FR-REC-007 | Configurable pipeline: default stages `Applied → Screening → Shortlisted → Interview (n rounds) → Assessment → Offer → Offer Accepted → Joined`, plus `Rejected`, `On Hold`, `Withdrawn`, `Offer Declined`, `No Show`. Drag-and-drop kanban; stage-entry/exit rules; mandatory fields per stage. | M |
| FR-REC-008 | Interview scheduling: panel availability, calendar integration (Google/Outlook) with invite + video link, candidate confirmation, reschedule, no-show marking, automatic reminders to panel and candidate. | M |
| FR-REC-009 | Structured feedback forms per round: competency ratings, overall recommendation (`Strong Hire → Strong No Hire`), comments; feedback locked after submission; visible to hiring team only; consolidated scorecard. | M |
| FR-REC-010 | Assessment integration: send tests, capture scores (Phase 2 for third-party vendors); internal simple screening questionnaire with knockout questions in Phase 1. | S |
| FR-REC-011 | Offer management: offer approval workflow with CTC breakup, offer letter generation from template, e-sign, candidate accept/decline with reason, offer revision history, offer expiry, multi-offer comparison for the same position. | M |
| FR-REC-012 | Candidate portal: application status, interview schedule, document upload, offer view/accept — no login required for status (magic link), login for document submission. | M |
| FR-REC-013 | Communication: templated emails/SMS/WhatsApp at each stage, bulk rejection with a respectful template, full communication log on the candidate timeline. | M |
| FR-REC-014 | Talent pool: rejected/withdrawn candidates tagged and searchable for future openings, with consent tracking and a configurable retention period (DPDP compliance). | S |
| FR-REC-015 | Referral programme: employee submits a referral, tracks status, referral bonus rule (on joining + on completing N months), auto-posting the bonus to payroll. | S |
| FR-REC-016 | Recruitment analytics: time-to-hire, time-to-fill, source effectiveness, offer-acceptance rate, stage conversion funnel, interviewer load, cost-per-hire, requisition ageing. | M |
| FR-REC-017 | Candidate→Employee conversion carries all data, documents and the offer CTC into the employee record and triggers pre-onboarding. Zero re-typing is the acceptance bar. | M |
| FR-REC-018 | Background verification: initiate, track status per check type, store the report, and gate joining on the result (configurable). Vendor integration Phase 2. | S |

**AC-REC-017.1** Given an offer is accepted, when HR clicks "Convert to Employee", then a
`PRE_JOINING` employee record exists with name, contacts, documents, designation, department,
joining date and full compensation structure derived from the offer, with no manual re-entry.
**AC-REC-006.1** Given a candidate applies twice with the same email to two openings, then one
candidate profile exists with two applications.

---

# 9. Onboarding (ONB) — Priority (Phase 1)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-ONB-001 | Pre-boarding portal for the accepted candidate before joining: welcome content, document checklist upload, personal/bank/statutory detail form, Form 11 & Form 2 (PF nomination), gratuity nomination, e-sign of policies. | M |
| FR-ONB-002 | Onboarding template per department/designation/location, containing task packs with owner (role or specific person), due date offset (relative to joining date, e.g. J-7, J-1, J+0, J+7), dependency, and mandatory flag. | M |
| FR-ONB-003 | Automatic task creation & assignment on joining-date confirmation, with reminders, escalation on overdue, and a completion dashboard per joiner. | M |
| FR-ONB-004 | Standard task packs: IT (email ID, laptop, software access, VPN), Admin (seat, ID card, access card), HR (documents, induction, policy sign-off, insurance enrolment), Finance (payroll setup, bank), Manager (buddy assignment, goals for first 90 days, introductions). | M |
| FR-ONB-005 | Day-1 checklist and induction schedule with content/videos and acknowledgement tracking. | M |
| FR-ONB-006 | Document verification workflow: HR marks each submitted document `Verified / Rejected (reason) / Pending`, with re-upload requests. | M |
| FR-ONB-007 | Auto-provisioning triggers to integrated systems (email, MDM, access control) via webhooks, with status tracking and retry. | S |
| FR-ONB-008 | Buddy/mentor assignment and a 30/60/90-day check-in workflow with feedback capture. | S |
| FR-ONB-009 | Onboarding status dashboard: joiners this week/month, completion %, blocked tasks, no-shows. | M |
| FR-ONB-010 | No-show handling: if the employee does not join by the joining date + grace, auto-flag, notify the recruiter, and offer to reopen the requisition. | M |

---

# 10. Exit & Offboarding (EXT) — Priority (Phase 1)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-EXT-001 | Exit initiation: employee resignation (with reason + proposed last day) or employer-initiated (termination, end-of-contract, retirement, abandonment, death). Distinct workflows and permissions per type. | M |
| FR-EXT-002 | Notice-period computation from the applicable policy (override chain BR-14); shortfall triggers notice-pay recovery; buyout/waiver requires approval; garden-leave option. | M |
| FR-EXT-003 | Resignation acceptance workflow: manager → HR, with the ability to negotiate the last working day and record retention attempts. Withdrawal of resignation supported before acceptance. | M |
| FR-EXT-004 | Clearance checklist auto-generated per department (IT, Admin, Finance, Library, Manager, HR) with items, owners, due dates and blocking flags; F&F cannot be finalised while blocking items are open. | M |
| FR-EXT-005 | Asset recovery integrated with Asset Management: list of assets held, return marking, damage/loss valuation → deduction to F&F. | M |
| FR-EXT-006 | Knowledge transfer: handover document, pending-task reassignment, replacement mapping. | S |
| FR-EXT-007 | Exit interview: configurable questionnaire, conducted online or by HR, with confidentiality controls and analytics on attrition reasons. | M |
| FR-EXT-008 | Full & final settlement per FR-PAY-022 with a statement, employee acknowledgement, dispute window, and payment tracking. | M |
| FR-EXT-009 | Exit document generation: acceptance letter, relieving letter, experience certificate, Form 16, PF withdrawal/transfer guidance, gratuity computation statement. Release gated on F&F completion. | M |
| FR-EXT-010 | Access revocation on last working day: system login disabled, integrations notified, mobile app deactivated, pending approvals reassigned. Automatic at 23:59 on the LWD. | M |
| FR-EXT-011 | Ex-employee portal: restricted access for 12 months to payslips, Form 16, experience letter and F&F statement. | S |
| FR-EXT-012 | Rehire eligibility flag with reason, visible in the ATS when a matching candidate applies. | S |
| FR-EXT-013 | Attrition analytics: voluntary vs involuntary, by department/manager/tenure/reason, monthly & rolling-12-month rates, regrettable-attrition flag. | M |

**AC-EXT-010.1** Given an employee's LWD is 31-Aug, then at 23:59 on 31-Aug their user account is
disabled, their pending approvals are reassigned to their manager, and their status becomes `EXITED`.

---

# 11. Employee Self-Service & Mobile (ESS) — Priority P7

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-ESS-001 | Employee dashboard: today's attendance state with a punch button, leave balances, pending requests, upcoming holidays, birthdays/anniversaries, announcements, quick actions. | M |
| FR-ESS-002 | Punch in/out with geo + selfie where policy requires; shows shift, hours worked today, and this month's summary. | M |
| FR-ESS-003 | Apply/cancel leave; view balance statement; team leave calendar (own team only). | M |
| FR-ESS-004 | Attendance regularisation request. | M |
| FR-ESS-005 | View & download payslips (last 24 months), tax declarations, proof submission, Form 16, salary certificate request. | M |
| FR-ESS-006 | Profile view & edit-with-approval; document upload; dependent & nominee management. | M |
| FR-ESS-007 | Manager view: pending approvals with one-tap approve/reject and bulk approve; team attendance today; team on leave; team profile access per scope. | M |
| FR-ESS-008 | Notifications: in-app inbox, push, email; per-category preferences. | M |
| FR-ESS-009 | Employee directory with search and click-to-call/email; org chart view. | M |
| FR-ESS-010 | Helpdesk ticket raise & track (Phase 2), policy document library (Phase 1). | M/S |
| FR-ESS-011 | Mobile app must function on Android 9+ and iOS 14+, work on 3G, cache the last-known dashboard offline, and queue punches offline. | M |
| FR-ESS-012 | Accessibility: WCAG 2.1 AA for web ESS; font scaling and screen-reader labels on mobile. | S |
| FR-ESS-013 | Multi-language UI: English + Hindi + Malayalam + Tamil in Phase 1 (string externalisation from day 1, translations by phase). | S |

**Design constraint (from Document 02 §5):** leave application ≤3 taps from app open; manager approval ≤3
taps from notification.

---

# 12. Dashboards & Reports (RPT) — Priority P8

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-RPT-001 | Role-specific dashboards: Company Admin (headcount, cost, attrition, automation rate), HR (today's attendance, pending approvals, joiners/leavers, compliance alerts), Manager (team attendance, leave, pending approvals, performance), Employee (per FR-ESS-001), Finance (payroll cost, statutory dues, cost centre). | M |
| FR-RPT-002 | Standard report library — minimum 60 reports across: employee master, headcount & movement, attendance register, muster roll, late/early, OT register, leave balance & ledger, payroll register, salary sheet, statutory (PF/ESI/PT/TDS/LWF/bonus/gratuity), recruitment funnel, onboarding status, exit & attrition, asset, compliance calendar. | M |
| FR-RPT-003 | Every report supports: date-range and org filters, column chooser, sort, group-by, subtotals, pagination, export to Excel/CSV/PDF, and permission-based row & column masking. | M |
| FR-RPT-004 | Report builder: users select an entity, fields, filters, grouping and chart type, then save the report as private or shared, with scheduled email delivery (daily/weekly/monthly) to a recipient list. | S |
| FR-RPT-005 | Large exports (>10k rows) are queued as background jobs with an email/download-link on completion; never block the request thread. | M |
| FR-RPT-006 | Compliance calendar: statutory due dates (PF 15th, ESI 15th, TDS 7th, PT per state, returns quarterly/annual) with owner assignment, reminders and completion marking. | M |
| FR-RPT-007 | Every export is logged (who, what, filters, row count) — this log is itself an auditable report. | M |
| FR-RPT-008 | Analytics warehouse: reporting queries run against a read replica or a nightly analytical store, never against the transactional primary during payroll windows. | M |

---

# 13. Notification Engine (NTF) — Priority P1 (foundation)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-NTF-001 | Channels: in-app, email, push (FCM/APNs), SMS, WhatsApp Business API. | M |
| FR-NTF-002 | Template management per event per channel per language, with merge variables, tenant-overridable, versioned, with a preview/test-send. | M |
| FR-NTF-003 | Event catalogue with ~120 named events (leave applied/approved/rejected, attendance missing, payslip published, offer released, document expiring, task overdue, birthday…), each mapped to recipients by role/relationship. | M |
| FR-NTF-004 | User preferences per category per channel, with mandatory categories (payslip, statutory, security) that cannot be disabled. | M |
| FR-NTF-005 | Delivery is asynchronous via a queue with retry (exponential backoff, max 5), dead-letter queue, and a delivery log with provider status callbacks. | M |
| FR-NTF-006 | Digest mode: batch low-priority notifications into a daily summary to avoid notification fatigue. | S |
| FR-NTF-007 | Quiet hours per tenant (no non-critical push/SMS between configured hours); critical security alerts bypass. | S |
| FR-NTF-008 | Rate limiting per tenant per channel to control cost; alert the tenant admin at 80% of the plan quota. | M |
| FR-NTF-009 | WhatsApp requires pre-approved templates and opt-in consent capture per employee; unsubscribe handling. | M |

---

# 14. Multi-Company, Subscription & Platform Administration (PLT)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-PLT-001 | Super Admin console: tenant list, tenant creation, plan assignment, usage (employees, storage, notifications, AI calls), health, support impersonation, suspend/reactivate. | M |
| FR-PLT-002 | Subscription plans define module entitlements, employee-count limits, storage limits, AI-call quotas and support SLA. Enforcement is server-side at the permission layer. | M |
| FR-PLT-003 | Employee-count breach behaviour: soft warning at 100%, grace of 10% or 15 days, then block new employee creation (never block payroll or attendance — never hold an employee's salary hostage to a billing dispute). | M |
| FR-PLT-004 | Billing: invoice generation, payment gateway (Razorpay/Stripe), dunning, plan upgrade/downgrade with proration. | S |
| FR-PLT-005 | Group companies: a parent tenant sees consolidated dashboards across child companies with an explicit grant; employee transfer between group companies preserves history. | S |
| FR-PLT-006 | White-labelling: logo, colour theme, custom domain (CNAME + managed TLS), custom email sender domain (SPF/DKIM). | S |
| FR-PLT-007 | Tenant data export (full JSON/CSV bundle) on request and on termination; tenant data deletion after the contractual retention window, with a certificate of deletion. | M |
| FR-PLT-008 | Feature flags per tenant for staged rollout and emergency kill-switch of any module. | M |

---

# 15. Workflow & Approval Engine (WFE) — Priority P1 (foundation)

Full specification in **Document 20**. Summary requirements:

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-WFE-001 | A generic engine serving all approval-bearing entities (leave, regularisation, OT, expense, requisition, offer, exit, profile change, asset request, transfer, promotion, loan). | M |
| FR-WFE-002 | Visual workflow builder: nodes = Start, Approval, Condition, Parallel, Notification, System Action, End. Conditions on any entity attribute (days, amount, department, grade). | M |
| FR-WFE-003 | Approver resolution: specific user, role, reporting manager (L1/L2/L3), department head, HR of the branch, dynamic by amount slab. | M |
| FR-WFE-004 | Delegation, auto-escalation on SLA breach, reminders, and skip-if-same-as-requester (BR-02, BR-03). | M |
| FR-WFE-005 | Actions: approve, reject with mandatory reason, request-more-info (returns to requester without cancelling), forward, withdraw. | M |
| FR-WFE-006 | Full audit of every transition with timestamp, actor, comment and duration at each stage; SLA reporting on approval turnaround. | M |
| FR-WFE-007 | Versioning: in-flight requests continue on the workflow version they started with. | M |

---

# 16. Audit, Logging & Data Governance (AUD)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-AUD-001 | Append-only audit log of every create/update/delete on business entities: actor, tenant, entity, entity id, action, before/after JSON diff, timestamp, IP, user agent, request id. | M |
| FR-AUD-002 | Audit log is queryable per entity ("show this employee's full change history") and per user ("everything this HR executive did in March"), exportable for auditors. | M |
| FR-AUD-003 | Sensitive-data access log: every read of salary, bank, PAN, Aadhaar and medical fields is recorded. | M |
| FR-AUD-004 | Login/logout, permission-denied, impersonation, export and bulk-operation events are logged with the same schema. | M |
| FR-AUD-005 | Logs are immutable and retained 8 years; no application role may delete them. | M |
| FR-AUD-006 | Data retention policy engine: per data category, define retention and post-retention action (anonymise/delete), executed by a scheduled job with a report. | S |
| FR-AUD-007 | DPDP compliance: consent capture, purpose declaration, employee data-access request fulfilment (export of all their data), correction requests, and a grievance officer contact. | M |
