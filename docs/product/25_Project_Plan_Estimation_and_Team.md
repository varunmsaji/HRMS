# Document 25 — Project Plan, Estimation & Team

*(Renumbered and updated from Document 11/12 for the Python/FastAPI backend architecture and single-developer/AI-assisted delivery model — see Document 00 for the full document map.)*

---

## 1. Delivery Model

**Solo, AI-assisted sprints.** Two-week sprints for personal rhythm and accountability, a hardening
block reserved after every major module group, and a working demo at the end of every block —
to the developer's own checklist, and to any pilot or design-partner customer once one is engaged.
Definition of Done is enforced (§6) exactly as strictly as the original team plan, arguably more
strictly: "done" still means shippable, not "works on my machine" — and with no second engineer to
catch what slips through, the Definition of Done is the only backstop left.

This project has no external commissioning client funding the build against a fixed-price contract.
It is a self-directed, bootstrapped build of a multi-tenant SaaS product (Document 01 §1), with one
or two pilot/design-partner customers brought in for real-world validation during Pilot & UAT
(§2). The estimation formats below — person-days, milestones, contingency percentages — are kept
because they are still the right planning tools for a project this size, even solo; what changes is
that "client sign-off" becomes "developer sign-off against the SRS" (Documents 17–18), and "client
payment schedule" becomes an internal progress checkpoint (§7). If a paying design partner,
investor, or contract client is engaged at some point, revisit §7 to reintroduce a formal
payment/acceptance schedule against the same milestones.

**Why not fixed-price waterfall:** unchanged reasoning from the original plan — fixing a price
against a one-page-scope blueprint guarantees either a padded number or a fight later. The
practical equivalent for a solo build is to fix Phase 1 scope against the signed SRS (Documents
17–18) and hold that line through change control (Document 26), because uncontrolled scope drift is
now the single biggest threat to the timeline — there is no spare engineering capacity anywhere in
the plan to absorb it, and it is easier for a solo developer to quietly scope-creep their own product
than it ever was for a client to demand it.

---

## 2. Phase Plan

| Phase | Duration | Content | Outcome |
|---|---|---|---|
| **Foundation (Block 0)** | 6 weeks | Architecture & ADRs, environment/CI-CD setup on managed cloud services, design tokens (Document 24), seed data, AI coding agent workflow (Claude Code or equivalent) configured for the project | Developer can build |
| **Phase 1 — MVP (Blocks 1–13)** | ≈101 weeks (≈23 months) | Auth, RBAC, Org, Employee, Workflow, Notifications + Shifts, Attendance, Leave, Payroll, Recruitment, Onboarding, Exit, ESS + Mobile, Reports, Hardening — same module scope as the original plan (§3) | Pilot-ready product |
| **Pilot & UAT** | 10 weeks | One or two pilot/design-partner customers, real data, parallel payroll run, defect fixing | Production-ready |
| **Go-live & stabilisation** | 6 weeks | Launch, hypercare, monitoring | Live product |
| **Phase 2** | ≈48 weeks (≈11 months) | Performance, Expense, Asset, Helpdesk, Task, Communication, advanced Reports, ERP integration, advanced AI | Full-featured |
| **Phase 3** | ≈48 weeks (≈11 months) | Learning, Experience, Visitor, Workforce planning, Timesheets, roster optimiser, public API | Enterprise-ready |

**Total to a stable, live Phase 1 product: ≈123 weeks (≈2.4 years).**
**Total to Phase 3 completion: ≈219 weeks (≈4.2 years).**

Phase 2 and 3 are assumed to compress somewhat better relative to a hypothetical team estimate than
Phase 1 does, because by then the codebase, the AI-agent workflow, and the developer's own patterns
for this specific system are already established. That assumption is reasonable but unverified —
re-check it once Phase 1 has actually shipped, not before.

> This is dramatically longer than the original team-based plan's 41 weeks (≈9.5 months) to a
> stable Phase 1 — roughly **3× the calendar time**, despite going from ~11.5 FTE to ~1–1.3 FTE
> (an ~8–10× headcount reduction). That gap is the honest answer, not a rounding artefact: AI
> assistance and the removal of team coordination overhead are real, substantial productivity
> gains for one generalist developer (§4.3), but they do not multiply one person's calendar
> throughput by 8–10×, and this document should not pretend otherwise. If a stakeholder — an
> investor, a design partner, or the developer's own runway — needs Phase 1 sooner than ~2.4 years,
> the available levers are: cut scope (§8), engage the part-time frontend/mobile contractor earlier
> or for more hours (§5), or accept a smaller initial slice of Phase 1 goes live first (see the
> sequencing note under §3). There is no "add a second team" option for a codebase whose
> correctness-critical logic — payroll, statutory compliance, RBAC/tenant isolation — is owned by
> one person's judgment; payroll and attendance still do not compress, regardless of who or what
> writes the code.

---

## 3. Sprint / Build-Block Plan (Phase 1)

The original plan's 18 two-week sprints assumed 8–14 people working different modules in parallel.
A solo developer cannot parallelise module work the same way, so the plan below groups the same
scope into fewer, wider **build blocks** rather than presenting fake weekly granularity. Two-week
sprints still happen *inside* each block for personal cadence and progress tracking; the block
boundaries are what actually matters for planning.

| Block | Weeks | Focus | Key Deliverables | Demo-able |
|---|---|---|---|---|
| **B0** | 1–6 | Foundation | ADRs, repo, CI/CD, dev/QA envs, DB schema v1, design tokens + component library adopted from an existing kit, seed data (permissions, statutory master, industry templates), AI agent workflow tuned to the codebase | Architecture walkthrough |
| **B1** | 7–12 | Auth & tenancy | Registration, login, MFA, JWT/refresh, company switching, tenant context + RLS, cross-tenant leakage test suite | Login, multi-company switch |
| **B2** | 13–19 | RBAC & org setup | Permission catalogue, roles, data scope resolver, field masking, company/entity/branch/department/designation/grade, holiday calendar | Set up a company end to end |
| **B3** | 20–29 | Employee core, lifecycle & import | Employee CRUD, effective-dated assignment/compensation, documents, custom fields, directory, org chart, audit log, transfer, promotion, confirmation, letters, bulk import, employee 360° | Bulk-load 500 employees |
| **B4** | 30–36 | Workflow engine | Definitions, versions, node types, approver resolution, SLA/escalation/delegation, approval inbox, workflow builder UI | Configure and run an approval |
| **B5** | 37–42 | Notification engine + shifts | Channels (in-app, email, push), templates, event catalogue, preferences, delivery log; shift master, roster | Notifications firing on events |
| **B6** | 43–54 | Attendance (capture + processing) | Punch API, mobile/web/kiosk punch, geofence, offline sync, device integration (ZKTeco/eSSL push), status resolution engine, matrix UI, regularisation, OT, exceptions, lock | Punch from a real device; full month of attendance |
| **B7** | 55–61 | Leave | Leave types, policies, ledger, application with day-count preview, accrual job, balance statement, team calendar, year-end | Apply → approve → balance updates |
| **B8** | 62–78 | Payroll (setup + engine + outputs + tax) | Components, formula builder, structures, CTC builder, statutory master, pay run lifecycle, computation engine, LOP/arrears, statutory computation, calculation trace, validation, variance gate, payslips + PDF, bank files, ECR/ESI/PT/24Q, JV, TDS engine, declarations, loans | Compute a real payroll end to end to bank file |
| **B9** | 79–86 | Recruitment | Requisition, opening, careers page, candidate, resume parsing (native Python module, no cross-service boundary), pipeline, interviews, feedback, offer, convert to employee | Hire someone end to end |
| **B10** | 87–92 | Onboarding, exit, F&F | Templates, task packs, pre-boarding portal, resignation, clearance, exit docs, F&F settlement | Onboard and offboard |
| **B11** | 93–97 | ESS & mobile completion | Employee dashboard, mobile app complete (punch, leave, approvals, payslip, directory), push, offline | Ship the mobile app to TestFlight/Play beta |
| **B12** | 98–102 | Reports & dashboards | Standard reports (scope per §8), export pipeline, role dashboards, compliance calendar, report builder | Full reporting suite |
| **B13** | 103–107 | Hardening | Performance tuning, load testing, security fixes (with the security consultant, §5.2), accessibility, defect burn-down, documentation | Load test results, pentest fixes |
| **UAT** | 108–117 | Pilot | One or two pilot/design-partner customers, data migration, **parallel payroll for 2 cycles**, training, defect fixing | Signed-off pilot |
| **Go-live** | 118–123 | Launch + hypercare | Production launch, monitoring, rapid fixes | Live customers |

Notice **B8 (Payroll) is the longest single block at 17 weeks**, and **B6 (Attendance) the second
longest at 12 weeks** — that is deliberate, not an oversight. These are the two modules flagged
elsewhere in the document set as the highest-risk (payroll: correctness and money; attendance:
biometric device integration), and this plan does not let AI-assisted velocity on the rest of the
system pressure them into compressing.

**Sequencing option, not a scope change:** the phase/module boundaries above match the original
Phase 1/2/3 definitions in Documents 17–18 exactly — nothing has moved between phases. What a solo
developer can reasonably do differently from a team is *release incrementally within Phase 1*
rather than holding everything for one big-bang launch at week 123. Blocks B0–B8 (through Payroll)
cover the correctness-critical core that most differentiates the product; a design partner could
plausibly start using Auth/RBAC/Org/Employee/Attendance/Leave/Payroll/ESS around week 78–90, well
before Recruitment, Onboarding/Exit, and the full report suite are done. This is a release-sequencing
recommendation, not a change to what "Phase 1" formally contains.

**Parallel payroll is still non-negotiable.** Run two full months where a real customer computes
payroll in their old system and in this one, and reconcile every unit of currency for every
employee. Do not go live on payroll without two clean parallel cycles — this is unchanged by team
size and remains the single most important quality gate in the project.

---

## 4. Effort Estimation

### 4.1 By Module (Phase 1)

The columns below no longer split Backend/Frontend/Mobile/QA by role, since one developer (plus an
optional part-time contractor, §5) covers all of them for a given module rather than handing work
between specialists. The **AI-Adjusted Total** applies a different compression ratio per module,
reflecting where AI-assisted development genuinely accelerates work (CRUD scaffolding, boilerplate,
test-writing, well-specified screens) versus where it does not (correctness-critical logic,
external system quirks that no amount of code generation shortcuts).

| Module | Original Total (d)¹ | AI-Adjusted Total (d)² | Why |
|---|---:|---:|---|
| Auth & tenancy | 57 | 31 | Well-trodden auth patterns; AI drafts scaffolding fast |
| RBAC | 53 | 32 | Permission catalogue/data-scope design still needs careful human thought |
| Organisation setup | 54 | 27 | Highly CRUD, compresses the most |
| Employee management | 108 | 59 | Large but mostly CRUD + import/export; AI is strong here |
| Workflow engine | 79 | 55 | Genuinely complex state machine; only moderate compression |
| Notification engine | 57 | 29 | Templated, CRUD-heavy |
| Attendance | 152 | 129 | Device integration + status-resolution edge cases; barely compresses |
| Leave | 102 | 71 | Real rules complexity (sandwich rule, accrual); moderate compression |
| **Payroll** | 166 | **149** | Highest-risk module — correctness-critical, human review dominates; **smallest compression in this plan** |
| Recruitment | 119 | 71 | CRUD-heavy pipeline; AI drafts parsing/matching code fast, human still validates outputs |
| Onboarding | 55 | 33 | CRUD/workflow, compresses well |
| Exit & F&F | 58 | 35 | CRUD/workflow, compresses well |
| ESS | 86 | 52 | Mostly read views over existing data |
| Reports & dashboards | 94 | 47 | AI is very strong at report/query scaffolding |
| AI (parsing, matching, assistant) | 61 | 27 | No cross-language service boundary anymore — a native Python module sharing the same DB session, auth context and domain models as the rest of the platform (Document 01 §2) |
| Integrations (Document 22 §12) | 135 | 108 | External system quirks (banks, statutory portals, biometric devices) — not compressible by AI |
| Platform admin & billing | 48 | 29 | CRUD-heavy |
| **Subtotal** | **1,484** | **984** | |

¹ Carried forward unchanged from the original team-based estimate, as a reference point.
² Illustrative planning ratios, not measured data. Assumes one senior generalist developer using AI
coding agents for a large share of implementation and test-writing, with full human review retained
on **every** module — heaviest review load on payroll, attendance, RBAC and integrations. **Do not
treat these numbers as a quotation** — re-baseline against real observed velocity after Blocks
0–2 (§3), on this codebase, with this developer, using these tools.

### 4.2 Additional Effort

| Item | Original (d) | AI-Adjusted (d) | Why |
|---|---:|---:|---|
| Architecture, setup, DevOps, CI/CD | 60 | 39 | Managed cloud services + IaC templates + AI-assisted scripting; still real solo setup work |
| Design (component library + 185 screens) | 130 | 72 | Adapting an existing component library plus AI-assisted screen generation from Document 24's design tokens, rather than bespoke Figma-first design of every screen |
| Seed data & industry templates | 30 | 24 | |
| Documentation (technical + user + training) | 45 | 20 | AI drafts most of this from code/specs; human edits and verifies |
| Data migration tooling | 25 | 21 | Correctness-critical; modest compression only |
| Performance & load testing | 25 | 21 | |
| Security hardening & pentest remediation | 30 | 27 | An external pentest engagement is unavoidable regardless of team size |
| Self-management & planning (was "Project management," 12% of build) | 180 | 49 | No cross-team coordination to manage; retained at ≈5% of adjusted build for planning, tracking and consultant coordination |
| UAT support & defect fixing | 80 | 64 | |
| **Subtotal** | **605** | **337** | |

### 4.3 Total

| | Days |
|---|---:|
| Build + supporting (AI-adjusted) | 1,321 |
| Contingency @ 30%³ | 396 |
| **Total Phase 1 (AI-adjusted, solo)** | **≈1,717** |

³ Raised from the original plan's 20% — a solo build has no spare engineering capacity to absorb
surprises the way a team can reassign work; the contingency has to be larger precisely because the
bus factor is smaller (§9).

At ~20 productive days/person-month → **≈86 person-months**.

> **Reconciling this with §3's calendar plan.** The original team plan divided 125 person-months by
> 11.5 FTE to get ~11 months. Doing the equivalent mechanical division here — 86 person-months ÷
> ~1.3 effective FTE (primary developer + optional part-time contractor, §5) — suggests ~66 months
> (5.5 years), which is longer than the ~28-month (§2) timeline the block plan in §3 actually
> reasons through. Both numbers are legitimate, but they are not measuring the same thing: a large
> share of the original per-module person-day totals was **role-handoff and specialist-ramp
> overhead** — a backend engineer's context being re-learned by a frontend engineer, then again by a
> QA engineer — that a single developer with full context across the whole stack simply does not
> pay. §3's block plan reasons about calendar time directly, module by module, and is the primary
> planning tool; this section's person-day table is a useful cross-check and a way to compare
> against the original team estimate, not an independent source of truth. **Treat both as
> provisional and re-baseline them together** after Blocks 0–2, using this developer's actual
> observed throughput on this codebase with these AI tools — not the ratios assumed here.

**Phase 2 estimate:** original ≈1,100 person-days → AI-adjusted, illustratively, ≈650–700
person-days, using the same differentiated logic (CRUD-heavy modules like Expense/Asset/Helpdesk
compress well; the Performance module and ERP integration compress less).
**Phase 3 estimate:** original ≈1,000 person-days → AI-adjusted, illustratively, ≈600–650
person-days.

> These remain engineering estimates from a specification, not a quotation. The 30% contingency is
> realistic, not padding — payroll edge cases and integration work consistently exceed first
> estimates for teams of any size, and a solo build has less slack to absorb them.

---

## 5. Team Structure

### 5.1 Phase 1 Core Team (1–3 people)

| Role | Count | Responsibility |
|---|---:|---|
| Primary Developer | 1 (1.0 FTE) | Full-stack: FastAPI backend, SQLAlchemy/Alembic data layer, Celery workers, AI/ML modules (resume parsing, matching, assistant), architecture & ADRs, security, RBAC & tenant isolation, DevOps/CI-CD, orchestrating AI coding agents (Claude Code or equivalent) across the whole codebase, reviewing all AI-generated output line by line, and owning payroll & statutory logic end to end — this is **not delegated**, to the contractor or to AI, under any circumstance |
| Frontend/Mobile Contractor (optional, part-time) | 0–1 (0.3–0.5 FTE, engaged from roughly Block 3 onward) | Next.js/React screens and the React Native app, built against the primary developer's API contracts and Document 24's design tokens. Frees the primary developer to stay on backend/correctness-critical work. Optional — the primary developer can absorb this work solo with heavier AI assistance and a longer timeline if budget doesn't support a contractor |
| Fractional Designer (optional, bursty) | 0–0.1 FTE, ≈10–20 days total | Design token direction and polish passes on the two signature screens (attendance calendar, payslip breakdown — Document 24 §1.2). Most of the 185-screen build now leans on an adapted component library plus AI-assisted screen generation rather than a bespoke Figma file per screen (§4.2) |

**What this removes from the original plan:** a dedicated Engineering Manager/Tech Lead, Product
Manager/BA, split Senior/Mid Backend and Frontend roles, a dedicated Mobile Engineer, a dedicated
QA Engineer (manual + automation), and — most significantly — the **separately-staffed Python
AI/ML track that previously ramped in around Sprint 10** to build a service that talked to the
NestJS core over an API boundary. None of that exists now: AI/ML features are native Python modules
built by the same developer, in the same codebase, from whichever block actually needs them (mainly
B9, Recruitment), with no handoff, no service boundary, and no second team's ramp-up time to wait on.

### 5.2 Specialist Support (fractional)

| Role | Engagement |
|---|---|
| Payroll/Compliance Consultant | ≈20 days across B8 and UAT — **mandatory**, more so than in the original plan: with one engineer, there is no second reviewer to catch a statutory mistake before it reaches a payslip |
| Security Consultant / Pentester | 10 days pre-launch + annual — **mandatory**, unchanged. Solo-written codebases need external eyes more, not less, since there is no internal peer review from a second engineer |
| Technical Writer / Editor | 5–10 days reviewing and polishing AI-drafted documentation, down from 20 days of original authoring (§4.2) |

### 5.3 Engagement Plan

- **Block 0:** Primary developer only. Architecture decisions (Documents 03/04) made solo and
  recorded as ADRs — there is no second senior engineer to sanity-check them in real time, so the
  ADR discipline is the substitute.
- **Around Block 3 (Employee core, weeks 20–29):** evaluate engaging the part-time frontend/mobile
  contractor, once API contracts and design tokens are stable enough to hand off screens without
  constant rework.
- **Ahead of Block 8 (Payroll, from week ~58):** engage the payroll/compliance consultant. This is
  the one point in the plan where bringing outside expertise in *late* is expensive — statutory
  logic decisions made without their input in earlier blocks (RBAC, employee compensation fields)
  are exactly the kind that are costly to unwind later.
- **Ahead of go-live (B13/UAT, from week ~100):** engage the security consultant/pentester.
- **UAT:** contractor hours may increase temporarily to help burn down pilot defects.

**The inverse of the original team's caution applies here.** The original plan warned against
staffing a 12-person team on day one before there was architecture or requirements to organise
around. The equivalent solo risk is the opposite: trying to do *everything* — including the two
things that most benefit from a second set of eyes, payroll correctness and security — entirely
alone, all the way to launch, because bringing in the consultants feels like an avoidable cost.
It isn't. Budget for §5.2 from the start, even if the calendar dates shift.

---

## 6. Definition of Ready / Definition of Done

Unchanged in substance from the original team plan — a smaller team is exactly the wrong context to
relax quality gates, since there is no second reviewer to catch what slips through. Coverage
thresholds in particular stay where they were; if anything they matter more now.

### Definition of Ready (a story may enter a block/sprint)
- [ ] Acceptance criteria written and testable
- [ ] Designs available (or explicitly not needed)
- [ ] API contract agreed where it crosses backend/frontend (i.e., where the contractor is involved)
- [ ] Dependencies identified and unblocked
- [ ] Estimated by the developer
- [ ] Edge cases and error states specified

### Definition of Done (a story may be called complete)
- [ ] Code complete and reviewed line by line by the developer — including, and especially, code
      drafted by an AI coding agent
- [ ] Unit tests written; coverage thresholds met (95% for payroll/leave/attendance/RBAC — unchanged)
- [ ] Integration tests for API endpoints
- [ ] RBAC test added for any new permission
- [ ] Cross-tenant isolation verified for any new table or endpoint
- [ ] Audit logging added for any state change
- [ ] Error and empty states implemented
- [ ] Accessibility checked (keyboard, contrast, labels)
- [ ] Responsive at all breakpoints
- [ ] OpenAPI updated
- [ ] Deployed to a QA environment and verified
- [ ] Demo-able without narration
- [ ] Documentation updated (user-facing and technical)
- [ ] No new critical or high defects

**A story that fails DoD is not "done with follow-ups". It is not done.** This discipline is what
prevents the last few months before launch from becoming a defect-clearing exercise — a risk that
grows, not shrinks, with a smaller team.

---

## 7. Milestones & Progress Checkpoints

There is no external client payment schedule by default (§1). The table below tracks progress
against the block plan (§3) instead of a payment percentage; if a paying design partner, investor,
or contract client is engaged, reintroduce a payment-percentage column against these same
milestones.

| # | Milestone | Target Week | Cumulative Phase 1 Scope |
|---|---|---:|---:|
| M0 | Foundation complete: architecture, CI/CD, design tokens, seed data | 6 | 5% |
| M1 | Auth, RBAC, org setup, employee management complete | 29 | 20% |
| M2 | Attendance and leave complete | 61 | 45% |
| M3 | Payroll complete with statutory outputs | 78 | 60% |
| M4 | Recruitment, onboarding, exit complete | 92 | 72% |
| M5 | Mobile app, ESS and reports complete; feature-complete MVP | 102 | 82% |
| M6 | Pilot/UAT signed off with two clean parallel payroll cycles | 117 | 95% |
| M7 | Production go-live + 30 days stabilisation | 123 | 100% |

Acceptance criteria per milestone are still derived from the SRS (Documents 17–18) and should be
signed off by the developer against those criteria before moving on to the next block. Where a
design partner or pilot customer participates in Pilot & UAT, their sign-off replaces self
sign-off for M6.

---

## 8. Scope Reduction Options (if the timeline must compress)

This lever matters more now than it did in the original team plan: there is no "add a second team"
option (§2), so scope reduction and contractor hours are the primary ways to pull the ~2.4-year
Phase 1 timeline in. Presented in order of least to most damaging; the "saves" figures are scaled
directionally from the original team-based estimates to the new block plan and should be re-derived
once real velocity is known.

| Cut | Saves (illustrative) | Cost of cutting |
|---|---:|---|
| Report builder (keep ~25–30 standard reports at launch, add the builder in Phase 2) | ≈7 weeks | Design partners request custom reports as tickets in the interim |
| Recruitment module → Phase 2 | ≈12 weeks | ATS is a strong differentiator; HR can use spreadsheets short-term |
| Reduce standard reports from 60 to ~25 at launch (independent of cutting the builder) | ≈4 weeks | Fewer canned reports at day one; the highest-demand ones should be prioritised first |
| Web ESS (mobile-only for employees) | ≈5 weeks | Desk-based employees prefer web; acceptable for blue-collar-heavy customers |
| Multi-language (English only) | ≈4 weeks | Limits addressable market in Tier-2/3 India |
| Performance module (already Phase 2) | — | — |
| Reduce to 3 industry templates | ≈4 weeks | Narrows initial sales targeting |
| Offline mobile attendance | ≈5 weeks | **Blocks construction and logistics customers entirely.** Only cut if those segments are deferred |
| Engage the part-time contractor earlier / for more hours (§5) | Compresses B3, B9–B12 | Increases spend; the single biggest *timeline* lever that doesn't cut product scope |

**Never cut:** payroll parallel run, security testing, RBAC test suite, audit logging, backup
testing. These are not features; they are the reasons the product can be sold at all — unchanged
from the original plan, and if anything less negotiable with one engineer, not more.

Advanced AI features (matching quality tuning, the assistant) were a candidate cut in the original
plan; they are less attractive to cut now, since the AI module is one of the cheapest parts of the
new estimate to build at all (§4.1) — it shares the same database session, auth context and domain
models as everything else, with no separate service to stand up.

---

## 9. Risks to the Schedule

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Biometric device integration takes 3× the estimate | High | High | Unaffected by team size. Acquire two real devices in Block 0/1; build the file-import fallback first |
| Statutory file formats rejected by government portals | High | High | Engage the compliance consultant ahead of B8; test with real ECR/24Q submissions in UAT |
| Payroll edge cases discovered late | High | High | Golden dataset of real payroll before B8; parallel run in UAT. Payroll already carries the smallest AI-driven compression in this plan (§4.1) — do not compress it further under schedule pressure |
| **Sole-developer bus factor / burnout** | High | High | This risk barely existed in the original 11.5-FTE plan and is now the top schedule risk. Mitigate with ADRs and runbooks written as you go (not backfilled), realistic pacing with actual rest, treating B13 (Hardening) as real recovery time and not just tech debt, and a written incident/succession note — who could pick this up, and where the docs are — rather than assuming continuity is fine because "it's just me" |
| **AI-generated code passing review too easily** | Medium | High | AI coding agents produce plausible-looking code for payroll, statutory and security logic that can be subtly wrong. The smaller compression ratio assumed for those modules (§4.1) exists specifically because they still need line-by-line human review, not just AI-assisted authorship. Do not relax the 95% coverage threshold (§6) or the payroll-consultant review step because AI wrote the first draft |
| Part-time contractor availability / turnover | Medium | Medium | Keep API contracts and design tokens (Document 24) stable so a replacement contractor can ramp quickly without tribal knowledge |
| Scope creep from self-imposed feature additions | High | Medium | Change control (Document 26); the OOTB/Configurable/Custom table in Document 02 (PRD) §11. It is easier for a solo developer to quietly scope-creep their own product than it ever was for a client to demand it — hold the same discipline against yourself |
| **Key-person dependency on payroll logic — now total, not partial** | High | High | Documented calculation specs (Documents 17–18) and the compliance consultant as an independent check are the only mitigations available with one engineer; treat both as non-negotiable, not nice-to-haves |
| DLT/WhatsApp template approval delays | Medium | Medium | Start registration in Block 1, not late |
| Design partners / pilot customers withdraw | Medium | High | Secure more than two if possible; expect at least one to drop |
| Underestimated design effort for 185 screens | Medium | Medium | Mitigated more than in the original plan by adopting an existing component library rather than bespoke design (§4.2), but still track actual screen-build velocity from Block 0 onward and re-baseline |

Full risk register with owners and triggers: **Document 26**.

---

## 10. Communication Plan

Team ceremonies sized for 8–14 people don't apply solo. What replaces them is lighter but not
absent — the discipline moves from meetings to written artefacts, because there's no one else in
the room to talk it through with.

| Practice | Frequency | Participants | Output |
|---|---|---|---|
| Weekly self-review | Weekly, 30 min | Developer (+ contractor if engaged) | Progress vs. block plan (§3), blockers, velocity check against §4 |
| Build-block planning | Per block | Developer | Committed block scope |
| Contractor sync (if engaged) | Weekly, 30 min | Developer + contractor | Screen/API alignment |
| Design-partner / pilot check-in | Weekly during Pilot & UAT; monthly once a partner is engaged pre-UAT | Developer + partner contact | Feedback, defect list |
| Monthly self-retro | Monthly, 1 h | Developer | Improvement actions, re-baseline effort/velocity assumptions (§4) |
| Consultant review | Per engagement (payroll consultant, security consultant, §5.2) | Developer + consultant | Sign-off on their area |
| Architecture decisions | As needed | Developer | ADR written and committed to the repo — the substitute for an architecture-review meeting with a second senior engineer |
| Release readiness | Per release | Developer (+ consultant for security-relevant releases) | Go/no-go |

**Tooling:** GitHub (code, PRs, Issues/Projects for the backlog — no separate Jira/Confluence at
this scale), Markdown docs in-repo (this document set), Claude Code or an equivalent AI coding
agent (day-to-day implementation), Figma (design tokens and the two signature screens only, per
Document 24 §1.2), Sentry + Grafana (production monitoring — unchanged).
