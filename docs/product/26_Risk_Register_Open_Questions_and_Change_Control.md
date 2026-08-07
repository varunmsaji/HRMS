# Document 26 — Risk Register, Open Questions & Change Control

*(Renumbered and updated from Document 15 for the Python/FastAPI backend architecture and single-developer/AI-assisted delivery model — see Document 00 for the full document map.)*

**Version:** 2.0
**Audience:** Project Manager, Client Sponsor, Developer
**Sign-off required from:** Client

---

## 0. How to Use This Document

This is the only document in the set that is expected to change every week. It holds the three
things that determine whether the project lands on time:

1. **§1–§2 Risk register** — what could go wrong, who owns it, what we do about it.
2. **§3 Open questions Q1–Q10** — decisions only the client can make, with the date each is needed.
3. **§4 Assumption log A1–A13** — what we have assumed in the absence of those decisions, for
   explicit client acceptance or rejection.
4. **§5–§7 Change control** — how scope changes are requested, priced and approved after sign-off.

**Standing rule:** an unanswered question does not stop the project — it converts into an
assumption, and the assumption is built. Reversing a built assumption later is a change request
with cost. §3 gives the "required by" date for each question precisely so that this trade is
visible in advance rather than argued about afterwards.

**Note on delivery model:** this project is built by a single developer with AI-assisted tooling
(Claude Code) across the whole stack, not a multi-role engineering team. Where earlier plans
divided effort across specialists and could compress calendar time by working in parallel, this
plan cannot — there is one person, so "dev-weeks of effort" and "calendar weeks elapsed" are close
to the same number, offset in one direction by AI-assisted velocity on mechanical work (R-24) and
in the other by the complete absence of a second reviewer for correctness-critical code (R-07,
R-25). Both are treated honestly below rather than by simply dividing old team estimates by
headcount.

Review cadence: risk register reviewed in every sprint review; open questions reviewed in every
weekly client call until closed.

---

## 1. Risk Scoring Method

| Likelihood | Meaning |
|---|---|
| L1 Rare | < 10% chance over the project |
| L2 Possible | 10–35% |
| L3 Likely | 35–70% |
| L4 Near-certain | > 70% |

| Impact | Meaning |
|---|---|
| I1 Minor | < 1 week slip or < 2% cost; no customer impact |
| I2 Moderate | 1–3 week slip, or a workaround degrades a feature |
| I3 Major | 3–8 week slip, or a Phase 1 module is materially reduced |
| I4 Severe | Launch cannot proceed; legal, financial or reputational exposure |

**Severity = Likelihood × Impact.** Anything scoring L3×I3 or above requires a named mitigation
owner and a written contingency, not just an intention.

| | I1 | I2 | I3 | I4 |
|---|---|---|---|---|
| **L4** | Medium | High | **Critical** | **Critical** |
| **L3** | Low | Medium | **High** | **Critical** |
| **L2** | Low | Low | Medium | **High** |
| **L1** | Low | Low | Low | Medium |

---

## 2. Risk Register

### 2.1 Critical & High Risks

---

**R-01 — Payroll statutory calculations are wrong in production**
*Category:* Product correctness · *Likelihood:* L3 · *Impact:* I4 · **Severity: Critical**
*Owner:* Payroll/Compliance Consultant (accountable) + Developer (delivery)

Indian payroll has more edge cases than any other part of this system: PF wage ceiling and the
₹15,000 threshold with voluntary contribution, ESI eligibility crossing mid-cycle and the
continuation-until-contribution-period-end rule, state-wise PT slabs, both income-tax regimes with
declaration and proof windows, LWF frequency by state, gratuity's 4-years-240-days rule, bonus
eligibility limits. A single wrong figure is a legal exposure for the customer and an existential
credibility problem for the product. This risk is entirely independent of language or team size —
it is a domain-correctness problem, not a technology one — and remains Critical after the migration
to Python/FastAPI and to a single-developer model.

*Triggers to watch:* golden dataset failures clustering in one statutory area; the compliance
consultant not yet engaged by Sprint 2; parallel run mismatches above 0%.

*Mitigation:*
- Compliance consultant engaged from **Sprint 1**, not at UAT (Doc 23 §6)
- Golden dataset of ≥200 employee-months, expected values signed by the client's payroll team, not
  by the developer (Doc 24 §3)
- Statutory rates stored as effective-dated data, never hard-coded (Doc 15 §7.3)
- Two clean parallel payroll cycles required before go-live — non-negotiable (Doc 24 §10)
- Calculation trace on every payslip line so any figure can be defended to an auditor
- This is the same golden-dataset/parallel-run safety net that catches AI-generated defects, not
  just hand-written ones — see R-25

*Contingency:* if the parallel run does not clear, go live with attendance/leave/ESS and run
payroll in parallel for a third cycle. Never launch payroll on a partial match.

---

**R-02 — Biometric device integration takes far longer than estimated**
*Category:* Integration · *Likelihood:* L4 · *Impact:* I3 · **Severity: Critical**
*Owner:* Developer

Device SDKs are poorly documented, vendor firmware varies within the same model line, and the
on-prem agent must survive customer networks we do not control. Doc 20 §2 flags this as the
highest-risk integration in the project; the ~110 dev-day Phase 1 integration estimate is most
likely to be wrong here, and for a solo developer a wrong estimate here is not absorbed by
reassigning a second engineer — see R-24.

*Triggers:* no physical devices in hand by Sprint 3; a device brand appearing in a sales
conversation that is not on the Day-1 list; agent installation requiring customer IT escalation in
pilot.

*Mitigation:*
- **Buy physical devices of the target brands in Sprint 0** — no integration work against
  documentation alone
- Ship the file-import fallback (CSV/Excel punch upload) in the same sprint as the first device
  adapter, so attendance is never blocked on hardware
- Limit Day-1 support to the brands named in Q5; everything else is a paid adapter
- The on-prem agent is a single binary with a local buffer, auto-update and a health beacon
  (Doc 20 §2.4)

*Contingency:* mobile GPS punch + web punch + CSV import cover every attendance use case without a
device. A tenant can go live on Day 1 without biometric and add it later.

---

**R-03 — Scope expands because "22 modules" was read as a Phase 1 commitment**
*Category:* Scope · *Likelihood:* L4 · *Impact:* I3 · **Severity: Critical**
*Owner:* Project Manager + Client Sponsor

The blueprint lists 22 modules and 10 AI features on one page. The reading effort is identical for
all of them; the build effort is not. Phase 1 is 14 items (A11). Every module added to Phase 1
without removing another moves the date — and with one developer building sequentially (R-24),
there is no team capacity to quietly absorb the extra scope the way a larger team might.

*Triggers:* feature requests arriving through demo feedback rather than the change process; the
phrase "just a small addition"; sprint scope growing mid-sprint.

*Mitigation:*
- Signed SRS as the fixed-price baseline (Doc 23 §2)
- OOTB / Configurable / Custom classification table in BRD §10 — the answer to most requests is
  "that is configuration, here is how"
- Change control process in §5 below applied without exception, including for small items
- Demo every sprint so the client sees progress and does not compensate for uncertainty by
  requesting more

*Contingency:* the scope reduction menu in Doc 23 §8, ordered least-to-most damaging, with an
explicit never-cut list.

---

**R-04 — Cross-tenant data leakage**
*Category:* Security · *Likelihood:* L2 · *Impact:* I4 · **Severity: High**
*Owner:* Developer

One tenant seeing another's employee or salary data ends the product commercially. Multi-tenancy is
enforced at four layers (RLS, repository predicate, CI lint, automated tests) precisely because any
single layer will eventually be bypassed by a developer in a hurry — including a hurry induced by
an AI assistant producing a plausible-looking but tenant-unsafe query (see R-25).

*Triggers:* any raw SQL bypassing the repository layer; a new endpoint added without the isolation
test auto-generating; RLS disabled in any environment for debugging.

*Mitigation:*
- PostgreSQL RLS as the last line of defence — it holds even when application code is wrong
- Cross-tenant isolation suite auto-generated from the OpenAPI spec — FastAPI generates this schema
  natively from the Pydantic models, so there is no separate schema-authoring step to fall out of
  sync with the endpoints — so new endpoints are covered by default (Doc 24 §6)
- 404 rather than 403 on cross-tenant access, so existence is not disclosed
- Penetration test with remediation before go-live — a hard gate (Doc 21 §9)

*Contingency:* incident runbook 4 (Doc 25 §9), DPDP breach notification readiness, customer
communication template pre-drafted.

---

**R-05 — Key statutory or messaging lead times block launch**
*Category:* External dependency · *Likelihood:* L3 · *Impact:* I3 · **Severity: High**
*Owner:* Project Manager

DLT registration for SMS and Meta template approval for WhatsApp each take 1–3 weeks and depend on
client entity documents we do not hold. Both are outside engineering's control and both are on the
critical path for notifications (Doc 20 §4).

*Triggers:* client dependency D-list items still open at Sprint 4.

*Mitigation:* start registrations in **Sprint 1**; track as client dependencies D1–D7 in BRD §12
with named client owners and dates; email is the always-available fallback channel so no HR
operation depends on SMS or WhatsApp.

---

**R-06 — Attendance rules per industry are more varied than modelled**
*Category:* Product · *Likelihood:* L3 · *Impact:* I3 · **Severity: High**
*Owner:* Business Analyst + Developer

Manufacturing OT slabs, hotel split shifts, healthcare rotating rosters with credential rules,
retail weekly-off rotation, construction offline sites — the attendance engine must express all of
these as configuration (A5). If any industry needs code, the configuration model is wrong and the
cost multiplies across eight sectors.

*Mitigation:* validate the shift/roster configuration model against **real rosters from at least
three industries in Sprint 0**, before the engine is built. Pilot customers deliberately chosen
from two different industries (Doc 24 §10).

*Contingency:* narrow Phase 1 to the two pilot industries and treat the remaining six as
post-launch template work.

---

**R-07 — Bus factor: the developer is a single point of failure for all engineering knowledge**
*Category:* Resourcing / Key-person · *Likelihood:* L4 · *Impact:* I4 · **Severity: Critical**
*Owner:* Developer + Client Sponsor

With one developer, delivery risk is not merely "slower without a team" — it is a single point of
failure for every piece of engineering knowledge: payroll edge cases, RBAC design decisions, the
reasoning behind every architectural choice, and the undocumented judgment calls that never make it
into a ticket. If the developer is unavailable for an extended period (illness, attrition,
burnout), there is currently no one else who can operate, extend, or safely debug the system. In the
earlier team-based plan this was tracked narrowly as a payroll-engineer dependency; with no team at
all, it applies to the entire system and is elevated to Critical accordingly — it is now the
single highest structural risk in this register alongside R-01.

*Triggers to watch:* an architectural or payroll-logic decision made and merged with no written
rationale; a growing gap between what the code does and what any document says it does; the
developer unreachable for more than a few days during a payroll cycle or an incident.

*Mitigation:*
- Rigorous documentation as a delivery discipline, not an afterthought — every module keeps its
  data dictionary, API contract and RBAC matrix current as it is built, not retrofitted before UAT
- An Architecture Decision Record (ADR) for every non-trivial decision, including ones that would
  previously have been informal "hallway knowledge" in a team — the existing ADR set (`docs/adr/`)
  is the pattern to continue, not a one-time exercise
- No undocumented tribal knowledge: if a rule (a payroll edge case, an RBAC exception) exists only
  in the developer's head, it is written down the same day, not "when there's time"
- Comprehensive automated test coverage as the safety net that substitutes for a second reviewer —
  golden-dataset payroll tests, RBAC/tenant-isolation suites, and CI gates catch regressions a solo
  developer would otherwise only catch by luck (Doc 24)
- Consider a part-time second developer or a code-review contractor specifically for payroll and
  security-critical modules — not for velocity, but so a second qualified pair of eyes exists for
  the highest-consequence code even inside a single-developer team
- Calculation trace on every payslip line (R-01) and RBAC decision logging so behaviour can be
  reconstructed from evidence even if the person who wrote it is unavailable

*Contingency:* if the developer becomes unavailable mid-project, the client's fallback is (a) the
documentation and ADR trail above, and (b) engaging a new Python/FastAPI developer or contractor
against that trail. The honest recovery time depends entirely on how well the mitigations above
were actually followed — which is exactly why this risk is rated Critical rather than merely High.

---

**R-08 — Client-side decision latency**
*Category:* Governance · *Likelihood:* L4 · *Impact:* I2 · **Severity: High**
*Owner:* Client Sponsor

Ten blocking questions (§3) plus per-sprint approvals. If decisions take two weeks each, the
schedule absorbs it silently until it doesn't.

*Mitigation:* named client decision-maker with authority; weekly call with the open-question list
as a standing agenda item; the assumption-conversion rule at the top of this document so that
silence has a defined, agreed consequence rather than becoming a dispute.

---

**R-24 — Solo-developer schedule has no parallelism across modules**
*Category:* Resourcing / Schedule · *Likelihood:* L3 · *Impact:* I3 · **Severity: High**
*Owner:* Developer + Project Manager

A team could build payroll, attendance and mobile concurrently across engineers; a single developer
builds them sequentially. AI coding assistance (Claude Code) meaningfully accelerates individual
coding tasks — boilerplate, CRUD scaffolding, migrations, test generation — but it does not create
parallelism across unrelated modules, and correctness-critical modules (payroll, RBAC) still
require the developer's own careful review time, which AI cannot substitute for. Simply dividing
the old team-based effort estimates by team size understates the schedule; the honest model is:
total effort is similar or somewhat reduced by AI-assisted velocity on mechanical work, but calendar
time tracks total effort closely, because there is only one person to spread it across. The
offsetting factor is that there is no coordination overhead — no cross-team handoffs, no
sprint-planning ceremonies, no waiting on another engineer's PR review — so some of the padding a
team-based estimate carries for coordination genuinely does not apply here.

*Triggers:* any module estimate that was produced simply as "team estimate ÷ headcount"; the
developer working two modules concurrently and both slipping as a result.

*Mitigation:*
- Sequence modules explicitly and build one to completion before starting the next, rather than
  context-switching (module plan in Doc 23)
- Treat AI-assisted velocity as a productivity multiplier on mechanical work, not as a stand-in for
  a second engineer — do not budget it as added headcount
- Protect review and verification time for correctness-critical modules (payroll, RBAC, security)
  as non-compressible, regardless of how quickly a first draft was produced
- Prefer deferring scope (Doc 23 §8 reduction menu) over compressing verification time when the
  schedule is tight

*Contingency:* the scope reduction menu (R-03) is the primary lever. A solo developer has no second
engineer to reassign work to, so schedule protection depends on scope discipline rather than
staffing flex.

---

**R-25 — Over-reliance on AI-generated code for correctness-critical logic**
*Category:* Development process / AI-assisted development · *Likelihood:* L3 · *Impact:* I4 ·
**Severity: Critical**
*Owner:* Developer

The developer uses AI coding assistants across the whole stack, including payroll calculations,
statutory compliance logic, and security/RBAC enforcement. AI-generated code can look plausible and
pass a superficial read while containing subtle correctness errors, especially in areas requiring
exact domain rules (PF ceiling, ESI eligibility windows, PT slabs, tax-regime rules) or
negative-case security logic (an RBAC check that fails open instead of closed, a tenant-isolation
predicate silently dropped during a refactor). With no second engineer routinely reviewing every
change, an AI-authored bug in these areas can reach production because the human-verification loop
a team's code review would normally provide is thinner by default.

*Triggers:* any payroll or RBAC/security change merged without the developer specifically reading
through the diff; golden-dataset or security tests skipped "because it looks right"; a growing
share of commits touching correctness-critical modules with no corresponding review-checklist entry.

*Mitigation:*
- Golden-dataset payroll testing (≥200 employee-months, expected values signed by the client's
  payroll team) applies identically regardless of whether the code was hand-written or AI-generated
  — it verifies outcomes, not authorship, which is exactly what is needed here (Doc 24 §3, R-01)
- Mandatory human review checklist for any change touching payroll calculation, statutory rates,
  RBAC/permission checks, or tenant-isolation logic — the developer reads and reasons through the
  diff line by line before merge, even when AI-generated and even though there is no second
  reviewer to catch a miss
- AI-generated code for these modules is treated as a first draft, not a finished artefact — the
  developer remains the accountable author of record for every line, consistent with the
  calculation-trace and ADR practices already required by R-01 and R-07
- Never let AI assistance shortcut the "two clean parallel payroll cycles before go-live" gate
  (R-01) — it is an outcome check, not a code review, and it is exactly the kind of check that
  catches an AI-introduced defect that looked correct on inspection

*Contingency:* if a defect traced to AI-generated logic reaches a golden-dataset or parallel-run
failure, treat it as a process failure, not just a bug — review whether the checklist was actually
followed for that change, not only fix the code.

---

### 2.2 Medium Risks

| ID | Risk | L | I | Owner | Mitigation summary |
|---|---|---|---|---|---|
| R-09 | AI *product* features fail their evaluation gates and cannot ship | L3 | I2 | Developer | Every AI feature has a manual fallback (P2, Doc 19); AI is additive, so a failed gate delays a feature, not the release |
| R-10 | LLM API cost exceeds the ≤8% of PEPM revenue target | L2 | I2 | Developer | Per-tenant quotas, caching, small models for classification, cost dashboard with anomaly alerting (Doc 25 §6.1) |
| R-11 | Performance degrades at scale on attendance and payroll | L2 | I3 | Developer | Partitioned punch table, separate ingestion path, load tests at 3× target from Sprint 8, performance budgets in CI |
| R-12 | Mobile offline sync produces duplicate or lost punches | L3 | I2 | Developer | Client-generated idempotency keys, server-side dedupe window, explicit offline UI state (Doc 22 §7), clock-skew test matrix |
| R-13 | Data import from customer spreadsheets is messier than the importer handles | L4 | I2 | BA | Dry-run with a validation report before commit (BR-15); assisted onboarding offered for mid-market; migration explicitly out of scope (A13) |
| R-14 | UAT reveals HR workflow mismatches late | L3 | I2 | Product | Usability-test the 6 core flows with real HR practitioners during design, not at UAT (Doc 22 §10) |
| R-15 | Third-party provider outage during payroll week | L2 | I2 | Developer | Multi-provider email, circuit breakers, degradable integrations (Doc 20 §1), payroll never depends on an external call |
| R-16 | Statutory rate change lands mid-project | L3 | I2 | Compliance | Rates are effective-dated data; a change is a data update plus a regression run, not a code change |
| R-17 | Design system work becomes a bottleneck for frontend | L2 | I2 | Developer | Component library delivered in Sprint 0–2 ahead of feature screens; screens specified before they are built (Doc 22 §6); AI-assisted component generation helps but does not remove the need for the library to exist first |
| R-18 | ~~Key-person dependency on the payroll engineer~~ — **RETIRED, superseded by R-07** | — | — | — | Bus-factor risk is now system-wide (the single developer holds all engineering knowledge, not just payroll), so it is tracked as a Critical risk in §2.1 rather than a medium, payroll-specific one. Row retained for traceability rather than deleted — see R-07. |
| R-19 | Pilot customers disengage during UAT | L2 | I3 | PM | Two pilots, not one; commercial incentive agreed up front; UAT scenarios written in business language with a fixed time commitment (Doc 24 §10) |
| R-20 | Fixed-price contract signed against an unsigned SRS | L2 | I4 | PM | Do not sign a fixed price without a signed SRS. This is a commercial control, not a technical one (Doc 23 §2) |

### 2.3 Accepted Risks (no mitigation planned)

| ID | Risk | Why accepted |
|---|---|---|
| R-21 | Multi-country payroll demand emerges in year 1 | Architecture allows it (A1); the cost is 6–10 dev-weeks per country and will be a funded change request, not absorbed |
| R-22 | An enterprise prospect demands on-premise deployment | Offered from Phase 3 as a priced add-on (A2); the modular monolith makes it feasible |
| R-23 | Competitor feature parity pressure | Product decision, not a delivery risk; handled through the roadmap |

### 2.4 Retired / Resolved Risks

Kept here rather than deleted, in line with §7's rule that a superseded baseline is archived, not
erased — so the reasoning is not lost if circumstances change again.

| ID | Risk | Why retired |
|---|---|---|
| R-26 | Node↔Python integration friction between the NestJS core backend and a separate Python/FastAPI AI service — handoff latency, duplicated request/response validation between two runtimes, versioning drift, cross-language debugging when a request crossed the service boundary | The backend is now a single Python/FastAPI codebase end to end, including the AI features that previously lived in a separate service (former assumption A6). There is no longer a language or runtime boundary for any feature to cross, so this risk class does not exist in the current architecture. If a future architectural change reintroduces a service boundary (e.g. splitting out a separate AI microservice for scaling reasons), re-open this entry rather than starting from a blank page. |

---

## 3. Open Questions — Impact Analysis & Required-By Dates

Dates are expressed relative to the sprint plan in Doc 23 §4. "Required by" is the date after which
the assumption is treated as final and reversal becomes a change request.

---

**Q1 — Which countries must payroll support for statutory compliance?**
*Blocks:* Payroll module design, statutory master data, compliance consultant scope
*Assumed:* India only (A1)
*Required by:* **End of Sprint 1**
*If India only:* proceed as documented. *If multi-country:* the statutory engine needs a
country-abstraction layer designed before the payroll data model is finalised — retrofitting it
after Sprint 8 is a rewrite of the payroll core, not an extension.
*Cost of late reversal:* 6–10 dev-weeks per country if designed in; 12–16 weeks if retrofitted.

---

**Q2 — Deployment model: pure multi-tenant SaaS, or on-premise per enterprise client?**
*Blocks:* Architecture, DevOps, licensing, support model
*Assumed:* Multi-tenant SaaS; on-premise as a Phase 3 enterprise add-on (A2)
*Required by:* **End of Sprint 0**
*If on-premise is required in Phase 1:* add installer packaging, offline licensing, customer-managed
upgrade paths, per-customer support, and a very different release cadence. Roughly +8 weeks and a
permanent increase in operating cost per customer — and for a solo developer, a permanent increase
in ongoing support load with no team to share on-call with.

---

**Q3 — Expected scale at 12 months (tenant companies and total employees)?**
*Blocks:* Infrastructure sizing, cost model, partitioning strategy, pricing viability
*Assumed:* ~500 tenants / ~150,000 employees (used in Doc 15 §11 volume estimates and Doc 25 §1.1
sizing)
*Required by:* **End of Sprint 2**
*If materially larger:* partitioning strategy and read-replica topology change; if materially
smaller, infrastructure cost can be cut roughly in half at launch. Either way the architecture
holds — this is a sizing and cost question, not a design question.

---

**Q4 — Is white-labelling required (client logo, custom domain, custom email sender)?**
*Blocks:* Multi-Company module, notification templates, DNS/certificate automation
*Assumed:* Logo and colour theming yes; custom domain and custom email sender no
*Required by:* **End of Sprint 3**
*If full white-label:* add per-tenant domain provisioning, ACM certificate automation, per-tenant
SES/DKIM sender verification, and tenant-branded mobile builds if requested. ≈3–4 dev-weeks for
web; tenant-branded mobile apps are a much larger commitment and should be resisted in Phase 1.

---

**Q5 — Which biometric device brands must be supported on Day 1?**
*Blocks:* Attendance integration, device procurement, on-prem agent scope (see R-02)
*Assumed:* ZKTeco and eSSL via ADMS push, plus CSV import fallback (Doc 20 §2)
*Required by:* **End of Sprint 1** — devices must be physically procured before the adapter work
starts in Sprint 5.
*Cost of each additional brand:* 5–15 dev-days depending on protocol quality. Cloud-API devices are
cheaper; serial/SDK-only devices are the expensive ones.

---

**Q6 — Is there a hard data-residency requirement?**
*Blocks:* Region selection, DR region, sub-processor list, DPA drafting
*Assumed:* India-only residency; all data in ap-south-1 with DR in another Indian region (A6, Doc 21
§6)
*Required by:* **End of Sprint 0**
*Note:* this also constrains AI provider selection — if data may not leave India, the hosted-LLM
assumption A8 is affected and Q10 must be answered consistently with it.

---

**Q7 — Which accounting/ERP system for the Phase 1 integration?**
*Blocks:* Integration scope and sequencing
*Assumed:* Generic CSV journal voucher plus bank payment files for five banks ship first; Tally XML
via the on-prem agent as the first named integration (Doc 20 §7)
*Required by:* **End of Sprint 4**
*If SAP or Oracle:* file-based exchange only in Phase 1; direct API integration is a separate
scoped item requiring customer-side ERP access that is rarely granted quickly.

---

**Q8 — Contract model: fixed-price scope-locked, or time & material?**
*Blocks:* Change control strictness, estimation buffer, milestone payment structure
*Assumed:* Fixed price for Phase 1 against a signed SRS; T&M for Phase 2 onward (Doc 23 §2)
*Required by:* **Before contract signature**
*Note:* this question determines how §5 operates. Under fixed price, every change is a priced CR.
Under T&M, changes are backlog re-prioritisation and the process can be lighter. Mixing the two —
fixed price with informal scope changes — is the single most common cause of project disputes and
is explicitly not on offer. With a single developer holding the whole build, fixed-price discipline
matters even more than it would with a team, because there is no spare capacity to absorb informal
scope creep quietly.

---

**Q9 — Mobile framework: React Native, Flutter, or native?**
*Blocks:* Mobile architecture, design tokens, offline architecture
*Assumed:* React Native (A6) — shares TypeScript with the web codebase, letting the same developer
work across web and mobile without a third language, using the same AI-assisted workflow
*Required by:* **End of Sprint 2** — mobile work starts Sprint 6.
*If native:* Swift/Kotlin add a second and third technology stack for one developer to hold, on top
of Python for the backend and TypeScript for the web frontend, and give up the code-sharing benefit
with the web layer entirely. Native gives better biometric and background-location behaviour, but
at a real increase in solo cognitive load — roughly +40% mobile effort. If the
construction/logistics offline-first requirement proves demanding in Sprint 0 validation, revisit
this trade-off explicitly rather than defaulting away from it.

---

**Q10 — Does "AI-powered" require in-house models, or is a third-party LLM API acceptable?**
*Blocks:* AI architecture, cost model, privacy posture, data residency (interacts with Q6)
*Assumed:* Hosted LLM API plus classical ML for scoring; no training from scratch in Phase 1 (A8)
*Required by:* **End of Sprint 3**
*If in-house models are mandated:* this adds ML engineering work — training data pipelines, GPU
infrastructure, model governance — that sits outside a single developer's Python/FastAPI
web-application skillset and cannot be absorbed by AI-assisted coding the way ordinary CRUD or API
work can. Realistically +12–16 weeks, and it is the one scenario in this document where staying
solo stops being credible without bringing in dedicated ML help. The honest recommendation is
unchanged from the original plan: hosted APIs for Phase 1 with a documented exit path, because the
AI features that matter here (parsing, matching, assistant) are not differentiated by owning the
model, and hosted APIs keep the whole system inside the single-developer, single-language operating
model assumed elsewhere in this document.

---

## 4. Assumption Confirmation Log

Client to mark each **Confirmed** or **Rejected**. A rejected assumption immediately becomes an open
question with an impact analysis, and if it arrives after the corresponding Q-date, a change request.

| ID | Assumption | Doc ref | Cost flag | Client decision | Date | Notes |
|---|---|---|---|---|---|---|
| A1 | India-only payroll statutory for Phase 1 | 00 §3.1 | **[COST]** | ☐ Confirm ☐ Reject | | |
| A2 | Multi-tenant SaaS delivery; on-prem from Phase 3 | 00 §3.1 | | ☐ Confirm ☐ Reject | | |
| A3 | PEPM pricing with plan-based feature entitlements enforced in-product | 00 §3.1 | | ☐ Confirm ☐ Reject | | |
| A4 | "70–80% automation" = ≥75% of routine transactions with no HR data entry | 00 §3.1 | | ☐ Confirm ☐ Reject | | |
| A5 | 8 industries served by configuration and templates, not code forks | 00 §3.1 | | ☐ Confirm ☐ Reject | | |
| A6 | Stack: PostgreSQL / Python 3.12+ FastAPI (single backend for core and AI features) + SQLAlchemy / Next.js / React Native / Redis + Celery, on AWS ap-south-1 | 00 §3.2 | | ☐ Confirm ☐ Reject | | |
| A7 | Shared DB + `company_id` + PostgreSQL RLS for tenant isolation | 00 §3.2 | | ☐ Confirm ☐ Reject | | |
| A8 | Hosted LLM API + classical ML; no model training in Phase 1 | 00 §3.2 | **[COST]** | ☐ Confirm ☐ Reject | | |
| A9 | UTC storage; company-timezone boundaries for payroll and attendance | 00 §3.2 | | ☐ Confirm ☐ Reject | | |
| A10 | Money as integer minor units with explicit currency | 00 §3.2 | | ☐ Confirm ☐ Reject | | |
| A11 | Phase 1 = the client's 14 listed items; other 8 modules are Phase 2/3 | 00 §3.3 | **[COST]** | ☐ Confirm ☐ Reject | | |
| A12 | Mobile Phase 1 = employee + manager only; HR admin is web | 00 §3.3 | | ☐ Confirm ☐ Reject | | |
| A13 | Data migration out of scope; generic validated Excel importer in scope | 00 §3.3 | **[COST]** | ☐ Confirm ☐ Reject | | |

**Sign-off:**

| Role | Name | Signature | Date |
|---|---|---|---|
| Client Sponsor | | | |
| Project Manager | | | |
| Developer | | | |

---

## 5. Change Control Process

Applies from the date the SRS (Documents 17 and 18) is signed. Before that date, changes are free and expected —
that is what Sprint 0 and the requirements phase are for.

```
Request raised (any channel)
        │
        ▼
  Logged as CR-nnn by the PM within 1 working day
        │
        ▼
  Triage (PM + Developer) — 2 working days
        │
        ├─▶ Clarification (already in scope)      → answered, closed, no CR
        ├─▶ Configuration (achievable in-product) → documented as guidance, closed, no CR
        ├─▶ Defect (does not match signed SRS)    → moved to the defect process, no charge
        └─▶ Genuine scope change                  → impact analysis
                    │
                    ▼
      Impact analysis (Developer + BA) — 3–5 working days
      Scope · Schedule · Cost · Risk · Alternatives
                    │
                    ▼
      Client decision within 5 working days
                    │
        ┌───────────┼───────────┬──────────────┐
        ▼           ▼           ▼              ▼
     Approved   Rejected   Deferred to    Approved with
     as quoted             Phase 2        trade-off
        │                                  (something removed)
        ▼
  Baseline documents updated · version incremented · backlog updated
```

**The four triage outcomes matter more than the form.** In practice most requests are clarifications
or configuration, and treating everything as a CR makes the client defensive and slows the project.
Reserve the formal path for genuine scope change.

### Authority levels

| Impact | Approver | Turnaround target |
|---|---|---|
| No schedule or cost impact | Project Manager | 2 days |
| ≤ 5 person-days | PM + Client Project Lead | 5 days |
| 6–20 person-days | Client Sponsor | 10 days |
| > 20 person-days, or any scope removal | Client Sponsor + Steering review | 15 days |

### Emergency changes
Statutory changes (a budget announcement altering PF/PT/TDS rules, for example) bypass the queue and
are implemented on a best-effort basis, with the CR raised retrospectively within 5 working days.
Compliance does not wait for paperwork.

---

## 6. Change Request Template

Copy this block for each CR. Keep them in a single register with the ID, title, status and decision
date visible at a glance.

```
CHANGE REQUEST

CR ID:              CR-nnn
Title:
Raised by:                              Date raised:
Requested for phase:                    Priority: Critical / High / Medium / Low

1. DESCRIPTION
   What is being asked for, in the requester's words.

2. BUSINESS JUSTIFICATION
   What problem this solves, who is affected, and what happens if it is not done.

3. CURRENT BEHAVIOUR (per signed baseline)
   Document and section reference:
   What the system does today / is specified to do:

4. PROPOSED BEHAVIOUR
   Specific, testable description. Include acceptance criteria.

5. TRIAGE CLASSIFICATION
   ☐ Clarification — already in scope, no CR needed
   ☐ Configuration — achievable in-product, guidance provided
   ☐ Defect — does not match signed SRS, no charge
   ☐ Scope change — proceed with impact analysis

6. IMPACT ANALYSIS                                   (completed by Developer + BA)
   Modules affected:
   Documents requiring update:
   Data model change required:      Yes / No    Migration required: Yes / No
   API contract change:             Yes / No    Breaking: Yes / No
   Effort — backend / frontend / mobile / QA / design:        ___ person-days
   Total effort including 20% contingency:                    ___ person-days
   Schedule impact:                 ___ weeks   Affects critical path: Yes / No
   Cost impact:                     ___
   New risks introduced:
   Testing impact:
   Alternatives considered (including "do nothing" and the configuration workaround):

7. TRADE-OFF OPTIONS
   Option A — Add to current phase, extend timeline by ___ weeks, cost ___
   Option B — Add to current phase, remove [item] of equivalent effort, no timeline change
   Option C — Defer to Phase 2, no impact on the current phase
   Recommended option and why:

8. DECISION
   ☐ Approved as quoted   ☐ Approved with trade-off (Option ___)
   ☐ Deferred to Phase ___   ☐ Rejected
   Approved by:                            Role:                    Date:
   Rationale:

9. IMPLEMENTATION
   Target sprint:              Assigned to:
   Baseline documents updated: ☐    New version numbers:
   Backlog items created:
   Completed and verified:                 Date:
```

---

## 7. Document Version Control

All documents in this set are versioned independently using `MAJOR.MINOR`.

| Change type | Version increment | Re-sign-off required |
|---|---|---|
| Typo, formatting, clarification with no behavioural change | MINOR | No |
| New detail added within an already-agreed requirement | MINOR | No |
| Requirement added, removed or materially altered | **MAJOR** | **Yes, from the document's sign-off owner (Doc 00 §1)** |
| Architecture or data model decision reversed | **MAJOR** | **Yes, Developer + affected owners** |
| Assumption confirmed or rejected in §4 | MINOR on Doc 00 and 26 | Client initials on the log |

Every document carries a change log at its end:

| Version | Date | Author | Change | Approved by |
|---|---|---|---|---|
| 1.0 | Aug 2026 | — | Initial baseline derived from Client Blueprint v1.0 (as Document 15) | Pending |
| 2.0 | Aug 2026 | — | Renumbered from Document 15 to Document 26; updated for the Python/FastAPI backend and the single-developer, AI-assisted delivery model — bus-factor risk elevated (R-07), AI-assisted development risk added (R-25), solo-developer schedule risk added (R-24), Node↔Python integration friction retired (R-26) | Pending |

**Rule:** the signed baseline is whatever version was signed, not the latest file. When a MAJOR
version is issued, the previous version is archived, not overwritten, and any CR referencing it
cites the version explicitly. Disputes about scope are almost always disputes about which version
someone was reading.

---

## 8. Standing Agenda — Weekly Client Call

Ten minutes, every week, in this order. It exists so that §2 and §3 never go stale.

1. Sprint progress against the plan (2 min)
2. **Open questions — any answered this week? Any Q-date approaching?** (3 min)
3. **New or escalated risks** (2 min)
4. Change requests awaiting client decision (2 min)
5. Client dependencies (BRD §12) — status of D1–D7 (1 min)

If a question has passed its required-by date, it is stated aloud that the assumption is now
baselined and reversal is a change request. Say it every time. The purpose is not process
enforcement — it is that no one is surprised in month seven.
