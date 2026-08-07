# Document 13 — QA Strategy & Test Plan

---

## 1. Quality Objectives

An HRMS has three failure classes with very different consequences:

| Class | Example | Consequence | Tolerance |
|---|---|---|---|
| **Money errors** | Wrong net pay, wrong PF, wrong LOP | Legal liability, employee harm, customer loss | **Zero** |
| **Data leakage** | One tenant sees another's employees; a manager sees salaries | Breach notification, contract termination | **Zero** |
| **Functional defects** | A filter doesn't work, a report column is misaligned | Annoyance, support ticket | Managed |

Test effort is allocated accordingly: payroll, attendance, leave and RBAC receive
disproportionate investment. A UI defect ships and gets fixed next sprint. A payroll defect does not.

---

## 2. Test Levels & Coverage Targets

| Level | Owner | Target | Runs |
|---|---|---|---|
| Unit | Developers | 80% overall; **95% payroll, leave accrual, attendance resolution, RBAC, tax** | Every commit |
| Integration (API) | Developers + QA | Every endpoint, happy + error paths | Every PR |
| Contract | QA | Web/mobile ↔ API schema compatibility | Every PR |
| End-to-end | QA automation | 60 critical user journeys | Nightly + pre-release |
| Manual exploratory | QA | Each new module + regression areas | Per sprint |
| Performance | QA + DevOps | 5 load scenarios (Doc 10 §1) | Nightly (light), pre-release (full) |
| Security | Security + QA | SAST/DAST/deps every build; pentest pre-launch and annually | Continuous + annual |
| Accessibility | QA | axe-core in CI; manual audit of the top 20 screens | Per sprint + pre-release |
| UAT | Client + pilots | Full business scenarios with real data | Pre-launch |

---

## 3. Payroll Testing — the Golden Dataset Approach

This is the most important section in this document.

### 3.1 Build a golden dataset (Sprint 10)
From the client's real, anonymised payroll data (BRD dependency D1), construct **at least 200
employee-months** covering:

| Scenario | Cases |
|---|---|
| Full month, no exceptions | Baseline |
| Mid-month joiner (1st, 15th, last day) | Pro-ration boundaries |
| Mid-month leaver | Pro-ration + F&F |
| LOP: 1 day, half day, 15 days, full month | Day-basis correctness |
| Salary revision mid-month | Split computation |
| Backdated revision → arrears | Arrears engine |
| PF at, below and above the wage ceiling | Ceiling logic |
| PF opt-out; international worker; higher-wage PF | Applicability variants |
| ESI crossing the ceiling mid-period | Contribution-period rules |
| Employee in each PT state | State slabs |
| Old regime vs new regime | Tax engine |
| Tax: declarations submitted, partially proved, unproved | Projection and true-up |
| Employee joining mid-financial-year with previous-employer income | Form 12B handling |
| OT at weekday, weekly-off, holiday rates | Multiplier logic |
| Loan EMI, part-prepayment, foreclosure on exit | Loan module |
| Gratuity at 4y11m vs 5y1m | Eligibility boundary |
| Bonus at, below and above the eligibility ceiling | Bonus Act |
| Leave encashment on exit | F&F |
| Zero-net-pay and negative-net-pay cases | Validation gates |
| Rounding boundaries (₹0.50 cases) | Rounding rules |
| Maternity leave spanning three months | Long-leave handling |

### 3.2 Test method
- Each case has **expected outputs verified by the client's payroll team or the compliance
  consultant**, not by the engineering team.
- The suite runs on every payroll-related commit. A single mismatched paisa fails the build.
- The suite is versioned; when a statutory rate changes, expected values are updated with the
  notification reference recorded.

### 3.3 Parallel run (UAT)
Two complete monthly cycles where the customer runs payroll in both systems.
**Acceptance:** 100% match on net pay, all statutory deductions and employer contributions for
every employee. Any variance must be explained and resolved — "close enough" is not an outcome.

---

## 4. Attendance & Leave Test Scenarios

### 4.1 Attendance
| Scenario | Expectation |
|---|---|
| Cross-midnight shift 22:00–06:00 | Single day attributed to the shift start date |
| Punch before shift start (early arrival) | Not counted as OT unless approved |
| Missing out-punch | Flagged; configurable auto-out or absent |
| Multiple punches (6 in a day) | Correct pairing; first-in/last-out |
| Duplicate punches within 60 s | Collapsed to one |
| Punch on a holiday | Comp-off eligibility triggered |
| Punch on a weekly off | Comp-off or OT per policy |
| Half-day threshold boundary (exactly 4h) | Deterministic, documented behaviour |
| Grace period boundary (exactly 10 min late) | Deterministic |
| 3 lates in a month | Half-day deduction posted |
| Offline punches synced 6 hours later | All ingested once; correct times |
| Device clock 20 minutes fast | Flagged; punch retained with skew recorded |
| Geofence boundary (exactly at radius) | Deterministic; documented |
| Employee with no shift assigned | Falls back to company default; warning raised |
| Leave approved after attendance marked absent | Attendance recomputes to on-leave |
| Attendance edited after payroll lock | Blocked with a clear message |
| Shift changed retrospectively | Affected days recompute; payroll flagged if finalised |
| Roster gap (no roster for a date) | Default shift applied; exception logged |
| DST / timezone edge (if multi-country) | Correct local-day attribution |

### 4.2 Leave
| Scenario | Expectation |
|---|---|
| Application spanning a holiday, sandwich rule on/off | Day count matches the rule |
| Application spanning a weekly off | Same |
| Half-day at start and end | 0.5 + 0.5 counted correctly |
| Balance exactly equal to the request | Allowed |
| Balance 0.5 short | Rejected with the exact numbers shown |
| Negative balance allowed up to the limit | Allowed to the limit, blocked beyond |
| Accrual job run twice | Single credit (idempotency) |
| Joiner on the 20th | Pro-rated accrual per rule |
| Leaver mid-month | Pro-rated; excess leave recovered |
| Carry-forward above cap | Excess lapsed or encashed per policy |
| Cancellation after the leave started | Partial credit; attendance recomputed |
| Cancellation after payroll finalised | Blocked; adjustment path used |
| Two overlapping applications | Second rejected |
| Backdated application beyond the limit | Rejected |
| Maternity leave 26 weeks across a year boundary | Correct ledger and attendance across years |
| Comp-off expiry | Auto-lapsed on the expiry date; FIFO consumption |

---

## 5. End-to-End Journeys (automated, 60 total — extract)

| # | Journey | Modules exercised |
|---|---|---|
| E1 | Register company → configure org → add 50 employees → set up payroll → run payroll | Full stack |
| E2 | Employee applies leave → manager approves → attendance updates → payroll reflects LOP | Leave, attendance, payroll, workflow, notification |
| E3 | Candidate applies → screened → interviewed → offered → accepted → onboarded → becomes employee | Recruitment, onboarding, employee |
| E4 | Punch in (mobile, geofenced) → punch out → attendance day resolves → appears in monthly summary | Attendance, mobile |
| E5 | Offline punch → app reconnects → syncs → attendance correct | Attendance, mobile, ingestion |
| E6 | Payroll: create → compute → validation exceptions → variance ack → approve → finalise → payslip published → employee views | Payroll, notification, ESS |
| E7 | Employee resigns → manager accepts → clearance → F&F computed → documents issued → access revoked | Exit, payroll, asset, auth |
| E8 | Salary revised backdated → arrears computed in the next run → payslip shows the breakup | Employee, payroll |
| E9 | Manager approves 20 requests on mobile in one session | Workflow, mobile |
| E10 | Tenant A user attempts to access tenant B data across 40 endpoints | Security |
| E11 | Employee raises a profile change → HR approves → audit trail correct | Employee, workflow, audit |
| E12 | Transfer employee between branches → PT state changes → next payroll uses the new state | Employee, payroll |

---

## 6. Security & Isolation Test Suites (blocking)

These four suites must pass on **every** CI build. A failure blocks merge.

### 6.1 Cross-tenant isolation
Automated generator: for every list and detail endpoint in the OpenAPI spec, create a record in
tenant A, authenticate as tenant B, assert `404` and zero rows. New endpoints are picked up
automatically — a developer cannot forget to add the test.

### 6.2 Permission matrix
Data-driven from Doc 06 §4: for every (role × endpoint) pair, assert allow or deny. ~2,500 assertions.

### 6.3 Data scope
Fixture: a 4-level reporting tree across 2 branches and 3 departments. For each scope type, assert
the exact returned employee set. Includes a deliberate cycle to verify depth capping.

### 6.4 Field masking
For each RESTRICTED field, assert absence from the **raw JSON** for roles without the permission,
across list, detail and export endpoints.

### 6.5 Additional security tests
- Privilege escalation attempts (self-grant, role elevation, scope widening)
- IDOR: iterate over UUIDs from another tenant on every `{id}` endpoint
- Mass assignment: post extra fields (`role_id`, `company_id`, `annual_ctc`) and assert they are ignored
- File upload: polyglot files, oversized files, executable content, path traversal in filenames
- Prompt injection in resumes, tickets and expense receipts reaching AI features
- Rate limit enforcement
- JWT tampering, expired tokens, refresh-token reuse
- Impersonation restrictions

---

## 7. Test Data Management

| Dataset | Purpose | How generated |
|---|---|---|
| **Unit fixtures** | Fast, deterministic | Factory functions in code |
| **Demo tenant** | Demos, manual QA, onboarding new developers | Generator script: 250 employees, 6 months of attendance/leave/payroll history, full org, realistic Indian names and salary structures. Runs in < 5 min |
| **Golden payroll dataset** | Payroll correctness | Derived from anonymised client data, expected values verified by the compliance consultant |
| **Load-test dataset** | Performance | 50 tenants × up to 5,000 employees, 12 months of attendance |
| **Anonymised production copy** | UAT only | Irreversible anonymisation: names, contacts, PAN/Aadhaar, bank, **and salary** all synthesised |

**Rule:** no real personal data in dev or QA environments, ever. Salary data especially — it is the
most damaging leak and the one most often forgotten during anonymisation.

---

## 8. Defect Management

| Severity | Definition | Response | Fix target |
|---|---|---|---|
| **S1 Critical** | Payroll incorrect, data leak, data loss, system down, security vulnerability | Immediate; stop-the-line | Same day |
| **S2 High** | Core function broken with no workaround (cannot approve leave, cannot punch) | Same day triage | Within the sprint |
| **S3 Medium** | Function broken with a workaround; incorrect non-financial data | Sprint triage | Next sprint |
| **S4 Low** | Cosmetic, minor usability | Backlog | Prioritised |

**Release gates:**
- Zero open S1 or S2
- No more than 5 open S3 in the released modules
- All payroll golden-dataset tests passing
- All security suites passing
- Load-test targets met
- Accessibility: zero critical axe violations

**Defect root-cause tagging** (requirement gap / design gap / coding error / test gap /
environment / third party) reviewed monthly. If "requirement gap" dominates, the problem is
upstream of engineering and the process must change — this is common on projects that start from a
one-page brief, which is exactly why Documents 01–02 exist.

---

## 9. Automation Strategy

| Layer | Tool | Coverage goal |
|---|---|---|
| Unit | Jest / Vitest | Per §2 |
| API integration | Supertest + Testcontainers (real Postgres, real Redis) | 100% of endpoints |
| Contract | Schema validation against OpenAPI | 100% |
| E2E web | Playwright | 60 journeys |
| E2E mobile | Detox / Maestro | 15 critical mobile flows |
| Load | k6 | 5 scenarios |
| Security | Semgrep (SAST), OWASP ZAP (DAST), Snyk/Dependabot | Every build |
| Accessibility | axe-core in Playwright | Every screen in the E2E path |
| Visual regression | Playwright screenshots | Top 30 screens |

**Automation discipline:** a flaky test is a broken test. Flaky tests are quarantined within 24
hours and fixed within a week, or deleted. A test suite people ignore is worse than no suite.

---

## 10. UAT Plan

### 10.1 Participants
Two pilot customers from different industries (recommend one manufacturing and one IT — they stress
opposite parts of attendance and payroll), each providing: an HR manager, a payroll operator, two
reporting managers and ten employees.

### 10.2 UAT Scenarios (business-language, written by the PM with the client)
1. Set up our company from scratch
2. Import our existing 300 employees
3. Configure our actual leave policy and verify balances match our records
4. Configure our actual shifts and rosters
5. Run one month of attendance with our real devices
6. Run payroll for one month and reconcile against our existing system, employee by employee
7. Generate our PF ECR and ESI files and validate them on the government portal
8. Hire one real candidate end to end
9. Onboard one real joiner
10. Process one real exit with F&F
11. Managers approve a week of real requests on mobile
12. Employees use ESS for a full month

### 10.3 UAT Exit Criteria
- [ ] All 12 scenarios completed and signed off
- [ ] **Two parallel payroll cycles matching 100%**
- [ ] Statutory files accepted by the government portals
- [ ] Zero open S1/S2 defects
- [ ] Performance targets met with the pilot's real data volume
- [ ] Users trained; training material delivered
- [ ] Support process agreed and tested
- [ ] Client sign-off document executed

### 10.4 Duration
6 weeks: 1 week setup and training, 2 weeks scenario execution, 2 weeks parallel payroll,
1 week defect closure and sign-off.

---

## 11. Post-Launch Quality

| Activity | Frequency |
|---|---|
| Production error review (Sentry triage) | Daily during hypercare, then weekly |
| Payroll run success monitoring | Every run; alert on any failure |
| Customer-reported defect trend | Weekly |
| Performance regression check | Weekly |
| Security scan | Continuous; pentest annually |
| Backup restore test | Monthly |
| DR drill | Annually |
| Accessibility audit | Semi-annually |
| Statutory rate verification with the consultant | Quarterly and on every budget/notification |

**Hypercare:** for the first 30 days after go-live, a daily 15-minute call with each pilot customer,
an engineer on-call during their payroll window, and a same-day fix commitment for anything
payroll-blocking.
