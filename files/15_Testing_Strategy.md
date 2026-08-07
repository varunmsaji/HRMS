# Document 15 — Testing Strategy

**Version:** 2.0 — full replacement of Document 13 v1.0 ("QA Strategy & Test Plan"). The testing
**philosophy** — what matters most, the golden-dataset payroll approach, the security suites — is
entirely unchanged; it was correct independent of implementation language. What changed is tooling
(Jest/Supertest → pytest/httpx) and, materially, the operating model: this document assumes one
developer running these suites, not a QA team, which changes what "coverage" has to mean in
practice (§0).

---

## 0. Why This Still Has to Be Rigorous With One Developer

A QA team catches what a developer's own testing misses through a second set of eyes and different
assumptions. A solo developer has neither. The response is not to relax the bar — it's to make the
automated suites carry more of the weight that manual QA and code review used to carry, and to be
honest that **exploratory manual testing coverage will be thinner** than a staffed QA team would
provide (Document 25, Document 26 §Bus Factor Risk). Concretely: the payroll golden-dataset suite,
the four blocking security suites (§6), and the coverage gates (§2) are **not negotiable and are not
where time gets cut when the schedule is tight** — if something has to give under schedule pressure,
it is manual exploratory testing breadth or non-critical-module test depth, never these.

---

## 1. Quality Objectives — Unchanged

An HRMS has three failure classes with very different consequences:

| Class | Example | Consequence | Tolerance |
|---|---|---|---|
| **Money errors** | Wrong net pay, wrong PF, wrong LOP | Legal liability, employee harm, customer loss | **Zero** |
| **Data leakage** | One tenant sees another's employees; a manager sees salaries | Breach notification, contract termination | **Zero** |
| **Functional defects** | A filter doesn't work, a report column is misaligned | Annoyance, support ticket | Managed |

Test effort is allocated accordingly: payroll, attendance, leave and RBAC receive disproportionate
investment.

---

## 2. Test Levels, Coverage Targets, and Tooling

| Level | Tool | Target | Runs |
|---|---|---|---|
| Unit | `pytest` | 80% overall; **95% payroll calculation, leave accrual, attendance resolution, RBAC/tenancy, tax** (Document 05 §4) | Every commit |
| Integration (API) | `pytest` + `httpx.AsyncClient` (in-process ASGI) + `Testcontainers` (Python, real Postgres + Redis) | Every endpoint, happy + error paths | Every PR |
| Contract | Schema validation against the committed OpenAPI snapshot (Document 09 §8) | Web/mobile ↔ API schema compatibility | Every PR |
| End-to-end | Playwright (unchanged — this is a frontend-driving tool, backend-language-agnostic) | 60 critical user journeys | Nightly + pre-release |
| Manual exploratory | Developer | Each new module + regression areas — narrower than a staffed QA team's coverage; prioritised toward payroll, RBAC, and whatever changed most recently | Per release, not per sprint (Document 25's block-based schedule) |
| Performance | `k6` | 5 load scenarios (Document 23 §1) | Nightly (light), pre-release (full) |
| Security | Semgrep (SAST) + OWASP ZAP (DAST) + `pip-audit`/Safety every build; pentest pre-launch and annually | Continuous + annual |
| Accessibility | axe-core in Playwright CI | Per release |
| UAT | Client + pilots | Full business scenarios with real data | Pre-launch |

`pytest-asyncio` runs the async test suite natively — every `service.py`/`repository.py` method is
`async def` (Document 07 §1), so the test suite is async throughout, using `pytest.mark.asyncio` (or
the `asyncio_mode = "auto"` pytest-asyncio configuration to avoid marking every test function
individually).

### 2.1 Test Organisation

Mirrors `src/hrms/` 1:1 (Document 06 §4). A CI check flags any `service.py`/`router.py`/
`repository.py` with no corresponding test file — this is the mechanical substitute for a reviewer
noticing "there's no test for this" (Document 05 §4).

### 2.2 Fixture & Factory Strategy

`shared/testing/` (Document 07 §6) provides:
- A root `conftest.py` fixture giving an `httpx.AsyncClient` wired to the FastAPI app with
  `app.dependency_overrides` pre-configured for a fake authenticated user/tenant (Document 07 §2.3)
  — most unit/integration tests use this rather than real JWTs.
- Factory functions (factory-boy-style, or plain functions returning populated Pydantic
  `Create` schemas) for every entity, used across module test suites for consistent, realistic test
  data — was: Prisma-based seed/factory helpers; the pattern is equivalent, the library is Python-
  native.
- A Testcontainers-backed fixture (`real_db_session`) that spins up an ephemeral PostgreSQL 16
  container with the current Alembic migrations applied, used by integration tests that must exercise
  actual RLS policies, exclusion constraints, or partitioning behaviour that a mocked session cannot
  verify (Document 08 §1.1).

---

## 3. Payroll Testing — The Golden Dataset Approach — Unchanged

This remains the most important section in this document; nothing about it changes with the
language migration.

### 3.1 Build a golden dataset
From the client's real, anonymised payroll data (Document 02 dependency D1), construct **at least
200 employee-months** covering:

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
  consultant**, not by the developer.
- The suite runs on every payroll-related commit as a `pytest` parametrized test reading the golden
  dataset fixtures. A single mismatched paisa fails the build.
- The suite is versioned; when a statutory rate changes, expected values are updated with the
  notification reference recorded.

### 3.3 Parallel run (UAT)
Two complete monthly cycles where the customer runs payroll in both systems. **Acceptance:** 100%
match on net pay, all statutory deductions and employer contributions for every employee. Any
variance must be explained and resolved — "close enough" is not an outcome.

---

## 4. Attendance & Leave Test Scenarios — Unchanged

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
| Accrual job run twice | Single credit (idempotency — Document 11 §2 rule 2) |
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

## 5. End-to-End Journeys (automated, 60 total — extract, unchanged)

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

## 6. Security & Isolation Test Suites (blocking) — Unchanged, Implementation Updated

These four suites must pass on **every** CI build. A failure blocks merge — no exceptions, and with
no second reviewer to overrule a red build, this gate is the actual backstop (Document 05 §7).

### 6.1 Cross-tenant isolation
Automated generator: for every list and detail endpoint discovered from the OpenAPI spec, create a
record in tenant A, authenticate as tenant B, assert `404` and zero rows. New endpoints are picked up
automatically via FastAPI's route introspection (`app.routes`) — a developer cannot forget to add
the test.

### 6.2 Permission matrix
Data-driven from Document 19 §4: for every (role × endpoint) pair, assert allow or deny. ~2,500
assertions, generated as `pytest.mark.parametrize` cases from the permission matrix table (parsed
from a machine-readable copy of Document 19 §4, not hand-transcribed — the transcription itself
would be a drift risk).

### 6.3 Data scope
Fixture: a 4-level reporting tree across 2 branches and 3 departments. For each scope type, assert
the exact returned employee set. Includes a deliberate cycle to verify depth capping (Document 19 §5).

### 6.4 Field masking
For each RESTRICTED field (Document 19 §6), assert absence from the **raw JSON** (`response.json()`,
inspected as a dict before any client-side model parsing) for roles without the permission, across
list, detail and export endpoints.

### 6.5 Additional security tests — Unchanged
- Privilege escalation attempts (self-grant, role elevation, scope widening)
- IDOR: iterate over UUIDs from another tenant on every `{id}` endpoint
- Mass assignment: post extra fields (`role_id`, `company_id`, `annual_ctc`) and assert they are
  ignored — verifies the Pydantic `extra="forbid"` contract (Document 09 §6) actually rejects them
  rather than silently dropping them (a `422` is the correct, tested outcome, not a silent no-op)
- File upload: polyglot files, oversized files, executable content, path traversal in filenames
- Prompt injection in resumes, tickets and expense receipts reaching AI features (Document 21 §5)
- Rate limit enforcement
- JWT tampering, expired tokens, refresh-token reuse (Document 10 §1.1)
- Impersonation restrictions (Document 10 §7)

---

## 7. Test Data Management — Unchanged

| Dataset | Purpose | How generated |
|---|---|---|
| **Unit fixtures** | Fast, deterministic | Factory functions in code (§2.2) |
| **Demo tenant** | Demos, manual QA, onboarding a future second developer | Generator script (`scripts/generate_demo_tenant.py`, Document 08 §14): 250 employees, 6 months of attendance/leave/payroll history, full org, realistic Indian names and salary structures. Runs in < 5 min |
| **Golden payroll dataset** | Payroll correctness | Derived from anonymised client data, expected values verified by the compliance consultant |
| **Load-test dataset** | Performance | 50 tenants × up to 5,000 employees, 12 months of attendance |
| **Anonymised production copy** | UAT only | Irreversible anonymisation: names, contacts, PAN/Aadhaar, bank, **and salary** all synthesised |

**Rule:** no real personal data in dev or QA environments, ever.

---

## 8. Defect Management — Unchanged

| Severity | Definition | Response | Fix target |
|---|---|---|---|
| **S1 Critical** | Payroll incorrect, data leak, data loss, system down, security vulnerability | Immediate; stop-the-line | Same day |
| **S2 High** | Core function broken with no workaround (cannot approve leave, cannot punch) | Same day triage | Within the current build cycle |
| **S3 Medium** | Function broken with a workaround; incorrect non-financial data | Next cycle triage | Next build cycle |
| **S4 Low** | Cosmetic, minor usability | Backlog | Prioritised |

**Release gates:**
- Zero open S1 or S2
- No more than 5 open S3 in the released modules
- All payroll golden-dataset tests passing
- All security suites passing
- Load-test targets met
- Accessibility: zero critical axe violations

**Defect root-cause tagging** (requirement gap / design gap / coding error / test gap /
environment / third party / **AI-generated-code gap** — new category, Document 05 §8) reviewed
periodically. If "AI-generated-code gap" trends upward for payroll/RBAC/security code specifically,
that is a signal to slow down and increase manual tracing on those categories (Document 05 §8), not
to add more tests reflexively — the golden dataset and security suites already exist for exactly
this failure mode; a rising defect trend there means the *review discipline* is slipping, not that
coverage is insufficient.

---

## 9. Automation Strategy

| Layer | Tool | Coverage goal |
|---|---|---|
| Unit | `pytest` | Per §2 |
| API integration | `httpx.AsyncClient` + Testcontainers (real Postgres, real Redis) | 100% of endpoints |
| Contract | Schema validation against OpenAPI | 100% |
| E2E web | Playwright | 60 journeys |
| E2E mobile | Detox / Maestro (unchanged — mobile-side tooling, backend-language-agnostic) | 15 critical mobile flows |
| Load | k6 | 5 scenarios |
| Security | Semgrep (SAST), OWASP ZAP (DAST), pip-audit/Safety | Every build |
| Accessibility | axe-core in Playwright | Every screen in the E2E path |
| Visual regression | Playwright screenshots | Top 30 screens |

**Automation discipline, unchanged:** a flaky test is a broken test. Flaky tests are quarantined
within 24 hours and fixed within a week, or deleted.

---

## 10. UAT Plan — Unchanged

### 10.1 Participants
Two pilot customers from different industries (recommend one manufacturing and one IT), each
providing: an HR manager, a payroll operator, two reporting managers and ten employees.

### 10.2 UAT Scenarios (business-language)
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
1 week defect closure and sign-off — unchanged as a target, subject to Document 25's re-baselined
schedule for a solo developer.

---

## 11. Post-Launch Quality — Unchanged

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

**Hypercare:** for the first 30 days after go-live, a daily 15-minute check-in with each pilot
customer, the developer available during their payroll window, and a same-day fix commitment for
anything payroll-blocking.
