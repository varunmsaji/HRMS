# Document 12 — Project Plan, Estimation, Team & Delivery Model

---

## 1. Delivery Model

**Scrum with two-week sprints**, a hardening sprint every fourth sprint, and a demo to the client at
the end of every sprint. Definition of Done is enforced (§6) — "done" means shippable, not
"works on my machine".

**Why not fixed-price waterfall:** the client blueprint is one page. Fixing price against a
one-page scope guarantees either a padded quote or a fight in month four. Recommended contract
shape: **fixed-price for Phase 1 against this signed SRS**, then time-and-material or a fresh
fixed-price per subsequent phase. Any change to the signed SRS goes through the change-control
process (Doc 15).

---

## 2. Phase Plan

| Phase | Duration | Content | Outcome |
|---|---|---|---|
| **Sprint 0** | 3 weeks | Requirements sign-off, architecture, environment setup, design system, CI/CD, seed data | Team can build |
| **Phase 1 — MVP** | 28 weeks (14 sprints) | Auth, RBAC, Org, Employee, Recruitment, Attendance, Leave, Payroll, ESS, Onboarding, Exit, Reports, Mobile, Notifications, Workflow, basic AI | Pilot-ready product |
| **Pilot & UAT** | 6 weeks | Two pilot customers, real data, parallel payroll run, defect fixing | Production-ready |
| **Go-live & stabilisation** | 4 weeks | Launch, hypercare, monitoring | Live product |
| **Phase 2** | 20 weeks | Performance, Expense, Asset, Helpdesk, Task, Communication, advanced Reports, ERP integration, advanced AI | Full-featured |
| **Phase 3** | 20 weeks | Learning, Experience, Visitor, Workforce planning, Timesheets, roster optimiser, public API | Enterprise-ready |

**Total to a stable, live Phase 1 product: ~41 weeks (≈9.5 months).**
**Total to Phase 3 completion: ~81 weeks (≈19 months).**

> If the client expects Phase 1 in 4–5 months with this scope, the honest answer is that it is not
> achievable at acceptable quality with a single team. The options are: cut scope (see §8), add a
> second team (with the coordination cost that entails), or extend the timeline. Payroll and
> attendance in particular do not compress — they are correctness-critical and integration-heavy.

---

## 3. Sprint-by-Sprint Plan (Phase 1)

| Sprint | Weeks | Focus | Key Deliverables | Demo-able |
|---|---|---|---|---|
| **S0** | 1–3 | Foundation | Signed SRS, ADRs, repo, CI/CD, dev/QA envs, DB schema v1, design tokens + component library, seed data (permissions, statutory master, industry templates) | Architecture walkthrough |
| **S1** | 4–5 | Auth & tenancy | Registration, login, MFA, JWT/refresh, company switching, tenant context + RLS, cross-tenant leakage test suite | Login, multi-company switch |
| **S2** | 6–7 | RBAC & org setup | Permission catalogue, roles, data scope resolver, field masking, company/entity/branch/department/designation/grade, holiday calendar | Set up a company end to end |
| **S3** | 8–9 | Employee core | Employee CRUD, effective-dated assignment/compensation, documents, custom fields, directory, org chart, audit log | Add and manage employees |
| **S4** | 10–11 | Employee lifecycle + import | Transfer, promotion, confirmation, letters, bulk import with validation, demo-tenant generator, employee 360° | Bulk-load 500 employees |
| **S5** | 12–13 | Workflow engine | Definitions, versions, node types, approver resolution, SLA/escalation/delegation, approval inbox, workflow builder UI | Configure and run an approval |
| **S6** | 14–15 | Notification engine + shifts | Channels (in-app, email, push), templates, event catalogue, preferences, delivery log; shift master, roster | Notifications firing on events |
| **S7** | 16–17 | Attendance capture | Punch API, mobile/web/kiosk punch, geofence, offline sync, ingestion service, device integration (ZKTeco/eSSL push) | Punch from a real device |
| **S8** | 18–19 | Attendance processing | Status resolution engine, attendance day, matrix UI, regularisation, OT, exceptions, lock | Full month of attendance |
| **S9** | 20–21 | Leave | Leave types, policies, ledger, application with day-count preview, accrual job, balance statement, team calendar, year-end | Apply → approve → balance updates |
| **S10** | 22–23 | Payroll setup | Components, formula builder, structures, CTC builder, statutory master, employee statutory profile | Configure a salary structure |
| **S11** | 24–25 | Payroll engine | Pay run lifecycle, input snapshot, computation engine, pay days, LOP, arrears, statutory computation, calculation trace | Compute a real payroll |
| **S12** | 26–27 | Payroll outputs & tax | Validation, variance gate, payslips + PDF, bank files, ECR/ESI/PT/24Q, JV, TDS engine, declarations, loans | Complete payroll to bank file |
| **S13** | 28–29 | Recruitment | Requisition, opening, careers page, candidate, resume parsing (AI), pipeline, interviews, feedback, offer, convert to employee | Hire someone end to end |
| **S14** | 30–31 | Onboarding, exit, F&F | Templates, task packs, pre-boarding portal, resignation, clearance, exit docs, F&F settlement | Onboard and offboard |
| **S15** | 32–33 | ESS & mobile | Employee dashboard, mobile app complete (punch, leave, approvals, payslip, directory), push, offline | Ship the mobile app to TestFlight/Play beta |
| **S16** | 34–35 | Reports & dashboards | 60 standard reports, export pipeline, role dashboards, compliance calendar, report builder | Full reporting suite |
| **S17** | 36–37 | Hardening | Performance tuning, load testing, security fixes, accessibility, defect burn-down, documentation | Load test results, pentest fixes |
| **UAT** | 38–43 | Pilot | Two pilot customers, data migration, **parallel payroll for 2 cycles**, training, defect fixing | Signed UAT |
| **Go-live** | 44–47 | Launch + hypercare | Production launch, monitoring, daily standups with the client, rapid fixes | Live customers |

**Parallel payroll is non-negotiable.** Run two full months where the customer computes payroll in
their old system and in ours, and reconcile every rupee for every employee. Do not go live on
payroll without two clean parallel cycles. This is the single most important quality gate in the
project.

---

## 4. Effort Estimation

### 4.1 By Module (Phase 1)

| Module | Backend (d) | Frontend (d) | Mobile (d) | QA (d) | Total (d) |
|---|---:|---:|---:|---:|---:|
| Auth & tenancy | 25 | 12 | 8 | 12 | 57 |
| RBAC | 22 | 14 | 3 | 14 | 53 |
| Organisation setup | 20 | 22 | 2 | 10 | 54 |
| Employee management | 40 | 38 | 8 | 22 | 108 |
| Workflow engine | 35 | 22 | 6 | 16 | 79 |
| Notification engine | 25 | 12 | 8 | 12 | 57 |
| Attendance | 55 | 42 | 25 | 30 | 152 |
| Leave | 38 | 30 | 12 | 22 | 102 |
| Payroll | 75 | 45 | 6 | 40 | 166 |
| Recruitment | 45 | 45 | 5 | 24 | 119 |
| Onboarding | 20 | 20 | 5 | 10 | 55 |
| Exit & F&F | 22 | 20 | 4 | 12 | 58 |
| ESS | 15 | 25 | 30 | 16 | 86 |
| Reports & dashboards | 35 | 35 | 6 | 18 | 94 |
| AI (parsing, matching, assistant) | 35 | 12 | 2 | 12 | 61 |
| Integrations (Doc 09 §12) | 90 | 15 | 5 | 25 | 135 |
| Platform admin & billing | 20 | 18 | — | 10 | 48 |
| **Subtotal** | **617** | **427** | **135** | **305** | **1,484** |

### 4.2 Additional Effort

| Item | Days |
|---|---:|
| Architecture, setup, DevOps, CI/CD | 60 |
| Design (UX + UI, 185 screens) | 130 |
| Seed data & industry templates | 30 |
| Documentation (technical + user + training) | 45 |
| Data migration tooling | 25 |
| Performance & load testing | 25 |
| Security hardening & pentest remediation | 30 |
| Project management (12% of build) | 180 |
| UAT support & defect fixing | 80 |
| **Subtotal** | **605** |

### 4.3 Total

| | Days |
|---|---:|
| Build + supporting | 2,089 |
| Contingency @ 20% | 418 |
| **Total Phase 1** | **≈2,507 person-days** |

At ~20 productive days/person-month → **≈125 person-months**.
Over 11 months → an average team of **~11.5 FTE**.

**Phase 2 estimate:** ≈1,100 person-days. **Phase 3 estimate:** ≈1,000 person-days.

> These are engineering estimates from a specification, not a quotation. They assume the assumptions
> in Doc 00 hold, the client dependencies (BRD §10) are met on time, and scope is controlled. The
> 20% contingency is realistic, not padding — integration work and payroll edge cases consistently
> exceed first estimates.

---

## 5. Team Structure

### 5.1 Phase 1 Core Team (12 FTE)

| Role | Count | Responsibility |
|---|---:|---|
| Engineering Manager / Tech Lead | 1 | Architecture, code quality, technical decisions, unblocking |
| Product Manager / BA | 1 | Requirements, client liaison, backlog, acceptance |
| Backend Engineer (Senior) | 2 | Payroll, attendance, workflow — the correctness-critical core |
| Backend Engineer (Mid) | 2 | Employee, recruitment, org, reports |
| Frontend Engineer (Senior) | 1 | Architecture, design system, complex screens (matrix, pay run) |
| Frontend Engineer (Mid) | 2 | Module screens |
| Mobile Engineer | 1 | React Native app |
| QA Engineer | 2 | 1 manual/exploratory + 1 automation |
| DevOps Engineer | 0.5 | Infrastructure, CI/CD, monitoring (shared) |
| UI/UX Designer | 1 | Design system, screens, prototypes, usability testing |
| AI/ML Engineer | 0.5 | Resume parsing, matching, assistant (ramps up S13) |

### 5.2 Specialist Support (fractional)
| Role | Engagement |
|---|---|
| Payroll/Compliance Consultant | 15 days across S10–S12 and UAT — **mandatory**, not optional |
| Security Consultant / Pentester | 10 days pre-launch + annual |
| Technical Writer | 20 days for user documentation and help content |

### 5.3 Ramp Plan
- Sprint 0: Tech Lead, PM, Designer, 1 Backend, DevOps (5 people)
- Sprint 1–4: add backend and frontend engineers, QA (10 people)
- Sprint 7: add Mobile engineer (11)
- Sprint 10: add AI engineer, Payroll consultant (12)
- UAT: add a second QA and a support engineer temporarily

**Do not staff the full team on day one.** A team of 12 with no architecture, no design system and
no clear requirements produces expensive rework.

---

## 6. Definition of Ready / Definition of Done

### Definition of Ready (a story may enter a sprint)
- [ ] Acceptance criteria written and testable
- [ ] Designs available (or explicitly not needed)
- [ ] API contract agreed where it crosses backend/frontend
- [ ] Dependencies identified and unblocked
- [ ] Estimated by the team
- [ ] Edge cases and error states specified

### Definition of Done (a story may be called complete)
- [ ] Code complete, reviewed and merged
- [ ] Unit tests written; coverage thresholds met (95% for payroll/leave/attendance/RBAC)
- [ ] Integration tests for API endpoints
- [ ] RBAC test added for any new permission
- [ ] Cross-tenant isolation verified for any new table or endpoint
- [ ] Audit logging added for any state change
- [ ] Error and empty states implemented
- [ ] Accessibility checked (keyboard, contrast, labels)
- [ ] Responsive at all breakpoints
- [ ] OpenAPI updated
- [ ] Deployed to QA and verified by QA
- [ ] Demo-able without a developer present
- [ ] Documentation updated (user-facing and technical)
- [ ] No new critical or high defects

**A story that fails DoD is not "done with follow-ups". It is not done.** This discipline is what
prevents month nine from being a defect-clearing exercise.

---

## 7. Milestones & Payment Schedule (suggested)

| # | Milestone | Week | % of Phase 1 value |
|---|---|---:|---:|
| M0 | Signed SRS, architecture and design system | 3 | 10% |
| M1 | Auth, RBAC, org setup, employee management live in QA | 11 | 15% |
| M2 | Attendance and leave complete | 21 | 15% |
| M3 | Payroll complete with statutory outputs | 27 | 20% |
| M4 | Recruitment, onboarding, exit complete | 31 | 10% |
| M5 | Mobile app and reports complete; feature-complete MVP | 35 | 10% |
| M6 | UAT signed off with two clean parallel payroll cycles | 43 | 15% |
| M7 | Production go-live + 30 days stabilisation | 47 | 5% |

Each milestone has explicit acceptance criteria derived from the SRS. Client sign-off is required
within 5 working days of demo, or the milestone is deemed accepted (to prevent schedule drift from
review delays).

---

## 8. Scope Reduction Options (if the timeline must compress)

Presented in order of least to most damaging. Use this list rather than the usual approach of
quietly cutting testing.

| Cut | Saves | Cost of cutting |
|---|---:|---|
| Report builder (keep 60 standard reports) | 3 weeks | Customers request custom reports as tickets |
| Recruitment module → Phase 2 | 5 weeks | ATS is a strong differentiator; HR can use spreadsheets short-term |
| AI features → Phase 2 | 3 weeks | Weakens the "AI-powered" positioning — a marketing decision |
| Web ESS (mobile-only for employees) | 2 weeks | Desk-based employees prefer web; acceptable for blue-collar-heavy customers |
| Multi-language (English only) | 1.5 weeks | Limits addressable market in Tier-2/3 India |
| Performance module (already Phase 2) | — | — |
| Reduce to 3 industry templates | 1.5 weeks | Narrows initial sales targeting |
| Offline mobile attendance | 2 weeks | **Blocks construction and logistics customers entirely.** Only cut if those segments are deferred |

**Never cut:** payroll parallel run, security testing, RBAC test suite, audit logging, backup
testing. These are not features; they are the reasons the product can be sold at all.

---

## 9. Risks to the Schedule

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Biometric device integration takes 3× the estimate | High | High | Acquire two real devices in Sprint 0; build the file-import fallback first |
| Statutory file formats rejected by government portals | High | High | Engage the compliance consultant early; test with real ECR/24Q submissions in UAT |
| Client unavailable for clarifications (BRD D4) | Medium | High | Weekly fixed slot; blocked-status escalation after two missed sprints |
| Payroll edge cases discovered late | High | High | Golden dataset of real payroll from Sprint 10; parallel run in UAT |
| Scope creep from "small" requests | High | Medium | Change control (Doc 15); the OOTB/Configurable/Custom table in BRD §11 |
| Key person dependency on payroll logic | Medium | High | Two engineers on payroll from S10; documented calculation specs |
| DLT/WhatsApp template approval delays | Medium | Medium | Start registration in Sprint 1, not Sprint 15 |
| Pilot customers withdraw | Medium | High | Secure three pilots, expect one to drop |
| Underestimated design effort for 185 screens | Medium | Medium | Design runs one sprint ahead; component library front-loaded |

Full risk register with owners and triggers: **Document 15**.

---

## 10. Communication Plan

| Ceremony | Frequency | Participants | Output |
|---|---|---|---|
| Daily standup | Daily, 15 min | Team | Blockers surfaced |
| Sprint planning | Bi-weekly, 3 h | Team + PM | Committed sprint backlog |
| Backlog refinement | Weekly, 1.5 h | Team + PM + BA | Ready stories |
| Sprint review/demo | Bi-weekly, 1 h | Team + **client** | Feedback, acceptance |
| Retrospective | Bi-weekly, 1 h | Team | Improvement actions |
| Client steering | Monthly, 1 h | PM, Tech Lead, client sponsor | Decisions, risk review, budget |
| Architecture review | Monthly | Tech Lead + seniors | ADRs |
| Release readiness | Per release | All + QA + DevOps | Go/no-go |

**Tooling:** Jira or Linear (backlog), Confluence or Notion (documentation), Slack (daily),
Figma (design), GitHub (code + PRs), Sentry + Grafana (production).
