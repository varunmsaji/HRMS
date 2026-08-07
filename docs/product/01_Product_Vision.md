# Document 01 — Product Vision

**Version:** 2.0 — rewritten for the Python/FastAPI backend architecture decision (2026-08-03).
Supersedes the vision section of the original Document 01 (Business Requirements Document, v1.0).
See [Document 00](00_README_Document_Index.md) for the full document map and
[Document 26 §Migration Notes](26_Risk_Register_Open_Questions_and_Change_Control.md) for why this
document set was restructured.

---

## 1. Vision Statement

A cloud-based, AI-assisted Human Resource Management System that lets a 50–5,000 employee
organisation run the complete employee lifecycle — hire to retire — with the HR team acting as
**exception handlers rather than data entry operators**.

**One-line positioning:** *"HR software that does the work, not just stores the records."*

This vision is unchanged by the technology pivot documented here. What changes is **how the vision
gets built**: a single Python/FastAPI codebase across the API, the background workers and the
AI/ML modules, instead of a two-language split between a NestJS core and a Python AI service.

---

## 2. Why This Document Set Was Rewritten

The original documentation set (v1.0) specified a NestJS/Node.js/TypeScript core API with a
separate Python/FastAPI AI service. That decision is **reversed**. The platform is now built
**entirely on Python 3.12+ and FastAPI** — API, background workers, device ingestion and AI/ML —
one language, one runtime family, one dependency ecosystem, one test framework.

| Driver | Explanation |
|---|---|
| **Single-developer delivery** | This is now explicitly a single-developer project using AI-assisted development (Claude Code and similar tools) rather than an 8–14 person engineering team. A two-language stack (TypeScript core + Python AI) makes sense for a team with separate frontend/backend/ML specialists; it is pure overhead for one person who has to context-switch between two type systems, two test frameworks, two dependency managers and two sets of idioms. |
| **Existing expertise** | The developer's strongest production expertise is Python/FastAPI, not NestJS. Building the highest-risk, highest-precision part of the system (payroll, statutory compliance, RBAC) in the language the developer knows best reduces defect risk more than any framework feature NestJS offers. |
| **AI/ML is already Python** | Resume parsing, candidate matching, attrition scoring and the LLM gateway (Document 08 / Document 12 / Document 21) were always going to be Python. Making the core API Python too means AI features can be implemented as **internal modules that share the same database session, the same auth context and the same domain models** as the rest of the platform, rather than talking to it over a service boundary. This directly simplifies the architecture described in Document 07 and Document 12. |
| **Reduced complexity** | One dependency manager (`uv`), one linter (`Ruff`), one type checker (`mypy`), one test framework (`pytest`), one migration tool (`Alembic`), one background-job system (`Celery`). Fewer moving parts is a feature, not a compromise, for a solo-maintained enterprise system. |
| **AI-assisted development works better in one language** | AI coding assistants are more effective, and their output is easier for a single human reviewer to verify, when the whole codebase shares one language, one style guide and one set of conventions. Context that the assistant builds up in the API layer transfers directly to the worker and AI layers. |

**What does not change:** the business vision, the target customers, the 8 industry verticals, the
data model, the API contract shape, the RBAC model, the workflow engine design, and the frontend
(Next.js 14/React 18) and mobile (React Native/Expo) stacks. This is a backend implementation
decision, not a product pivot. Document 02 (PRD) carries the full, unchanged business requirements
forward.

---

## 3. Product Pillars

| Pillar | What it means |
|---|---|
| **Automate, don't digitise** | Moving a paper process onto a screen is not automation. Every module is designed so routine transactions complete with zero HR manual data entry (Document 02 §7). |
| **Configuration over code** | Leave rules, shift rules, salary structures, approval chains and letter templates are tenant data, not code branches — this is what lets one Python codebase serve 8 different industries (Document 02 §4). |
| **Correctness where it's non-negotiable** | Payroll, statutory compliance and access control get disproportionate engineering rigour: immutable pay runs, effective-dated records, an append-only leave ledger, and a deny-by-default permission model (Document 07, Document 08, Document 19). |
| **AI that assists, never decides** | Every AI feature has a human decision-maker, a manual fallback, and an audit trail (Document 12 §1, Document 21 §1). |
| **One engineer, enterprise standards** | Small team size is not an excuse for weak engineering discipline — it's the reason for it. A solo-maintained system that will eventually carry 500+ APIs and 100+ tables survives only if module boundaries, testing discipline and documentation are enforced from day one, because there is no second engineer to catch what slips through (Document 05, Document 26 §Bus Factor Risk). |

---

## 4. Success Looks Like

Same measurable objectives as the original vision (full detail and measurement methodology in
Document 02 §2):

- ≥75% of routine HR transactions complete with zero HR manual touch
- Payroll for 500 employees closes in under 4 hours
- Payroll disputes stay under 0.5% of payslips issued
- ≥80% monthly active employees on ESS/mobile
- 100% on-time, zero-defect statutory filings
- 99.9% platform uptime, with payroll never failing silently

A ninth, stack-specific success measure is added for this rewrite:

- **Engineering sustainability:** a new contributor (a second developer, a contractor, or the
  original developer returning after time away) can become productive using the documentation set
  alone, without tribal knowledge — tested the same way Document 16 requires: watch where a new
  reader gets stuck, and fix that gap.
