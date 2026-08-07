# HRMS Platform — Complete Development Documentation Set

**Version:** 2.0 — restructured for the Python/FastAPI backend architecture decision (2026-08-03).
Supersedes the v1.0 document set (documents 00–15, NestJS/Node.js-based), archived unedited at
[`docs/archive/superseded-v1-nestjs/`](.superseded_v1/) for historical reference. **Do not build against the
archived documents — they describe a rejected architecture.**

---

## 1. Why This Document Set Was Restructured

The backend is now built entirely on **Python 3.12+ and FastAPI** — one language across the API,
background workers, device ingestion and AI/ML — instead of a NestJS/Node.js core with a separate
Python AI service. This is a single-developer, AI-assisted delivery model, not a multi-engineer
team. See [Document 01 — Product Vision](01_Product_Vision.md) §2 for the full reasoning.

Restructuring the documents was necessary, not cosmetic: the original 16-document set (BRD, two SRS
parts, one combined System Architecture & Tech Stack document, Database Design, API Spec, RBAC,
Workflow, AI Spec, Integration, one combined NFR/Security/Compliance document, UI/UX, Project Plan,
QA Strategy, DevOps, Risk Register) did not have room to specify a 500+ API / 100+ table / 20+
module FastAPI architecture in the depth an AI-assisted solo build needs to stay consistent
(Document 05 §1). Several documents were split so that architecture concerns (folder structure,
dependency injection, authentication mechanics, background job design, AI service design) each have
a document precise enough to brief an AI coding assistant from directly, without diluting the
original business/product/compliance documents that didn't need to change.

---

## 2. Document Map

| # | Document | Primary Purpose | Status vs. v1.0 |
|---|----------|------------------|------------------|
| 00 | This index | Map + reading order | Rewritten |
| 01 | [Product Vision](01_Product_Vision.md) | Vision statement, why the stack changed | New (extracted from old Doc 01 §1) |
| 02 | [PRD](02_PRD.md) | Business objectives, personas, scope, business rules, industry requirements | Migrated from old Doc 01 §2–§11, unchanged in substance |
| 03 | [System Architecture](03_System_Architecture.md) | Deployables, request lifecycle, tenancy, payroll/attendance execution paths | Rewritten for FastAPI; business/architecture substance unchanged |
| 04 | [Technology Stack](04_Technology_Stack.md) | The official stack, rejected alternatives, job-queue comparison | New (split from old Doc 03 §2) |
| 05 | [Development Standards](05_Development_Standards.md) | Coding standards, PR checklist, AI-assisted development guardrails | New (expanded from old Doc 10 §7) |
| 06 | [Folder Structure](06_Folder_Structure.md) | Full backend monorepo layout, module anatomy | New |
| 07 | [Backend Architecture](07_Backend_Architecture.md) | Layered architecture, DI, module boundary enforcement, events, tenancy mechanics | New |
| 08 | [Database Architecture](08_Database_Architecture.md) | Full data dictionary (100+ tables), SQLAlchemy/Alembic conventions | Migrated from old Doc 04; data model unchanged, tooling section new |
| 09 | [API Standards](09_API_Standards.md) | REST conventions, envelope, full endpoint catalogue, security | Migrated from old Doc 05; contract unchanged, FastAPI implementation notes added |
| 10 | [Authentication Architecture](10_Authentication_Architecture.md) | JWT/OAuth2/SAML/OIDC/MFA design and implementation | New (expanded from old Doc 05 §2 + Doc 10 §3.2) |
| 11 | [Background Job Architecture](11_Background_Job_Architecture.md) | Celery queue topology, task design rules, scheduled job catalogue | New (replaces BullMQ design implicit in old Doc 03/14) |
| 12 | [AI Architecture](12_AI_Architecture.md) | AI/ML service design, model registry, cost controls | New (split from old Doc 08 §3) |
| 13 | [DevOps Architecture](13_DevOps_Architecture.md) | Infra topology, CI/CD pipeline, observability stack | New (split from old Doc 14) |
| 14 | [Security Architecture](14_Security_Architecture.md) | Data protection, appsec, infra security, incident response | New (split from old Doc 10 §3, §3.5) |
| 15 | [Testing Strategy](15_Testing_Strategy.md) | Full QA strategy: pytest, golden-dataset payroll testing, security suites | Full replacement of old Doc 13 |
| 16 | [Deployment Strategy](16_Deployment_Strategy.md) | Environments, deployment checklist, release cadence, backup/DR, tenant ops | New (split from old Doc 14) |
| 17 | [SRS Phase 1 — Core Modules](17_SRS_Phase1_Core_Modules.md) | Detailed functional requirements, Phase 1 modules | Renumbered from old Doc 02A, unchanged in substance |
| 18 | [SRS Phase 2 & 3 — Extended Modules](18_SRS_Phase2_Phase3_Modules.md) | Detailed functional requirements, Phase 2/3 modules | Renumbered from old Doc 02B, unchanged in substance |
| 19 | [RBAC & Permission Matrix](19_RBAC_and_Permission_Matrix.md) | Permission catalogue, role matrix, data scope, field security | Renumbered from old Doc 06, unchanged in substance |
| 20 | [Workflow, Approval & Notification Engine](20_Workflow_Approval_Notification_Engine.md) | Workflow node types, condition language, notification catalogue | Renumbered from old Doc 07, unchanged in substance |
| 21 | [AI & Automation Feature Specification](21_AI_and_Automation_Feature_Specification.md) | AI governing principles, feature-by-feature spec, evaluation, ethics | Renumbered from old Doc 08 §1,2,4-7; §3 trimmed to point at Doc 12 |
| 22 | [Integration Specification](22_Integration_Specification.md) | Biometric devices, messaging, calendar, ERP, job boards, SSO | Renumbered from old Doc 09, unchanged in substance |
| 23 | [Non-Functional Requirements & Compliance](23_Non_Functional_Requirements_and_Compliance.md) | Performance, availability, usability, DPDP/labour-law compliance | New (split from old Doc 10 §1,2,4,5,6,9,10) |
| 24 | [UI/UX Screen Inventory & Design System](24_UIUX_Screen_Inventory_and_Design_System.md) | Frontend screen inventory and design system | Renumbered from old Doc 11, unchanged (frontend stack unaffected) |
| 25 | [Project Plan, Estimation & Team](25_Project_Plan_Estimation_and_Team.md) | Phase plan, effort estimation, team composition | Renumbered from old Doc 12, substantially reworked for solo/AI-assisted delivery |
| 26 | [Risk Register, Open Questions & Change Control](26_Risk_Register_Open_Questions_and_Change_Control.md) | Risks, open questions, change control process | Renumbered from old Doc 15, reworked for the new stack/team risk profile |
| 27 | [Architecture Migration Summary](27_Architecture_Migration_Summary.md) | NestJS→FastAPI audit closure: decisions, doc register, repo pending work | **New** — read after 04 if you are migrating code or onboarding from v1.0 docs |

**Read order for a developer (or AI coding assistant) starting fresh:**
01 → 02 → 03 → 04 → 06 → 07 → 08 (your module's tables) → 17/18 (your module's requirements) →
09 → 19 → 05.

**Read order to understand *why* this document set looks the way it does:** 01 §2, then this
document, then Document 26's migration-related risk entries.

---

## 3. What the Client Blueprint Does NOT Yet Answer

Unchanged from v1.0 — these remain blocking questions for the affected modules. Full detail and
impact analysis in [Document 26](26_Risk_Register_Open_Questions_and_Change_Control.md).

| ID | Question | Blocks |
|----|----------|--------|
| Q1 | Target countries for payroll statutory compliance? (Assumed: **India only** for Phase 1) | Payroll |
| Q2 | Deployment model — pure SaaS multi-tenant, or on-premise per enterprise client? | Architecture, DevOps |
| Q3 | Expected scale at 12 months: number of tenant companies and total employees? | Infra sizing, cost |
| Q4 | Is white-labelling required (client logo, custom domain, custom email sender)? | Multi-Company module |
| Q5 | Which biometric device brands must be supported on Day 1? | Attendance, Integrations |
| Q6 | Data residency requirement (India-only region)? | DevOps, Compliance |
| Q7 | Which accounting/ERP system for the Phase 1 integration (Tally / Zoho Books / SAP)? | Integrations |
| Q8 | Delivery model: is this staying a solo/bootstrapped build, or will outside funding/a client engagement change the plan? | Document 25, contract terms |

---

## 4. Working Assumptions

### 4.1 Business Assumptions — Unchanged, see Document 02
Primary market India, multi-tenant SaaS delivery, PEPM pricing with feature entitlements,
70-80% automation target, 8 industries served via configuration.

### 4.2 Technical Assumptions — Updated for This Rewrite
- **A6 (superseded).** Stack: **PostgreSQL 16 + FastAPI (Python 3.12/asyncpg) + Next.js 14 (React
  18) + React Native + Redis 7 + Celery + Python for AI/ML (unified, no longer a separate service
  language)**, on AWS ap-south-1 (Mumbai). Full rationale in Document 04.
- **A7–A13** (tenant isolation, AI approach, timestamp handling, money handling, phase scope,
  mobile scope, data migration scope) are **unchanged** from v1.0 and are now stated in Document 03,
  Document 12, Document 08, and Document 02 respectively.

### 4.3 Delivery Assumption — New
- **A14.** Delivery is a **single developer using AI-assisted development** (Document 01 §2), not an
  8–14 person team. This assumption governs Document 25's schedule and Document 26's risk profile,
  and is the reason Document 05 exists as a standalone standard — a solo, AI-assisted build needs
  its conventions written down and mechanically enforced, not held as team tacit knowledge.

---

## 5. Terminology & Naming Standard

Moved to [Document 02 §11](02_PRD.md) — it is product terminology, not a document-index concern.
Code-level naming conventions (module names, class naming, permission codes) are in
[Document 06 §5](06_Folder_Structure.md).

---

## 6. Critical Engineering Principles for This Product — Unchanged

These five principles are not negotiable. Violating them is what turns HRMS projects into
unmaintainable rewrites in year two. They are stack-independent and were true under NestJS and
remain true under FastAPI.

1. **Everything about an employee is time-versioned.** (Document 08 §1.2, ADR-0003)
2. **Payroll outputs are immutable.** (Document 08 §8.4, ADR-0005)
3. **Configuration over code.** (Document 02 §3, Document 01 §3)
4. **Every state change is audited.** (Document 07 §9)
5. **Tenant context is enforced at the lowest possible layer.** (Document 03 §2, Document 07 §5)

---

## 7. Document Change Control

Any change to a signed-off document requires a Change Request (template in Document 26 §4) with
impact analysis on scope, schedule and cost. Version numbers follow `MAJOR.MINOR`: `MINOR` for
clarifications, `MAJOR` for scope changes. This entire document set moved from `1.x` to `2.0` in one
step because the backend architecture change is, by definition, a MAJOR change across every document
it touched.
