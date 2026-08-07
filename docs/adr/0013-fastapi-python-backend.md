# ADR-0013: Python 3.12 / FastAPI Backend, Replacing NestJS/Node.js

**Status:** Accepted

## Context

The platform was originally specified (Doc 03 v1.0, ADR-0001) with a NestJS/Node.js/TypeScript core
API and a separate Python/FastAPI AI service. That specification assumed a team of 8–14 engineers
with separate frontend, backend and ML specialists (Doc 12 v1.0 §5).

The actual delivery context is different: this is a **single-developer project**, using AI-assisted
development tooling (Claude Code and similar), where the developer's strongest production expertise
is Python/FastAPI rather than NestJS. The AI/ML modules (resume parsing, candidate matching,
attrition scoring, LLM orchestration) were always going to be Python regardless of the core API's
language, per the original AI service design (Doc 08 v1.0 §3).

Running two backend languages makes sense when different specialists own each side. It has no
offsetting benefit for one person, who instead pays a permanent tax: two type systems, two test
frameworks, two dependency managers, two sets of idioms, and a service boundary between the core API
and the AI service that exists for language-isolation reasons alone, not for any genuine scaling or
domain reason.

## Decision

Rebuild the backend entirely on **Python 3.12+ and FastAPI** — the Core API, the Worker/Beat
processes, the Device Ingestion service, and the AI/ML modules all run from **one Python codebase**
(Doc 06). SQLAlchemy 2.x (async) + Alembic replace Prisma (ADR-0015). Celery + Redis replace BullMQ
(ADR-0014).

This is an implementation-language decision, not a product or architecture-pattern decision:

- The **modular monolith** pattern from ADR-0001 is retained unchanged — only its implementation
  language changes. ADR-0001's decision and consequences stand; its supporting text has been
  lightly amended to remove NestJS-specific phrasing.
- The **data model** (Doc 08), **API contracts** (Doc 09), and **RBAC design** (Doc 19) are
  confirmed stack-independent through this very migration — none of the three needed to change in
  substance, only in their implementation-detail sections. This is direct evidence that those
  documents were correctly designed as stack-independent from the start.
- Every other ADR in this directory (0002–0012) — RLS multi-tenancy, effective dating, the leave
  ledger, payroll immutability, money-as-integer, the separate ingestion service, the generic
  workflow engine, AI non-blocking design, UTC storage, statutory-rates-as-data, and the outbox
  pattern — is **business/architecture reasoning independent of backend language** and remains
  fully in force, unedited in substance.

## Consequences

- **Positive:** one dependency manager (`uv`), one linter/formatter (`Ruff`), one type checker
  (`mypy`), one test framework (`pytest`), one migration tool (`Alembic`), one background-job system
  (`Celery`) — a meaningfully smaller set of tools and idioms for one person to hold in their head
  across 500+ APIs and 100+ tables.
- **Positive:** the AI/ML modules can share SQLAlchemy models, the DB session, and the auth/tenancy
  context directly with the rest of the backend (Doc 12 §1, §6), rather than crossing a service
  boundary that existed only because the two sides were written in different languages.
- **Positive:** the developer's deepest production expertise is applied to the highest-risk code
  (payroll, statutory compliance, RBAC/tenancy) rather than to a framework being learned on the job.
- **Negative:** Python's async ecosystem for this exact combination (FastAPI + SQLAlchemy 2.x async
  + Celery, which is not itself async-native — Doc 04 §3) is less battle-tested at this system's
  scale than the Node/NestJS/Prisma/BullMQ combination it replaces. The async-ORM session lifecycle
  foot-gun documented in Doc 08 §15 (`DetachedInstanceError`) is a new class of bug this migration
  introduces that did not exist under Prisma's generated-client model.
- **Negative:** losing the NestJS ecosystem's opinionated structure (which "forced" the module
  boundaries this design depends on, per the original ADR-0001 rationale) means module-boundary
  discipline must be actively re-created with `import-linter` (Doc 07 §3) rather than inherited from
  the framework — this is done, but it is a decision this ADR makes explicit rather than gets for
  free.
- **Negative — schedule:** re-baselined project plan (Doc 25) shows the full migration and resulting
  solo delivery model taking roughly 3x the calendar time of the original team-based estimate,
  despite an 8-10x headcount reduction. This is disclosed here because it is a direct consequence of
  this decision, not a separate risk to discover later.

## Alternatives Considered

- **Django + Django REST Framework.** The "Python shop" fallback named in the original Doc 03 v1.0
  §2.2. Rejected in favour of FastAPI: DRF's async support is bolted-on rather than foundational,
  and FastAPI's Pydantic-based, contract-first validation is a better match for a 500+ endpoint API
  surface generated from type hints rather than hand-annotated. See Doc 04 §2 for the full
  comparison.
- **Keep NestJS, drop the separate Python AI service (rewrite AI in TypeScript).** Rejected: it
  would keep the two-tool-chain tax for the primary language while giving up Python's AI/ML
  ecosystem maturity (scikit-learn, XGBoost, Sentence Transformers, OCR tooling) for no benefit —
  strictly worse than either staying on the original two-language split or moving fully to Python.
- **Keep the two-language split as originally designed.** Rejected per the Context above — sound
  for a multi-engineer team, net-negative for one developer.

## Related

- Amends: ADR-0001 (modular monolith — pattern retained, NestJS-specific text removed)
- Enables: ADR-0014 (Celery + Redis), ADR-0015 (SQLAlchemy + Alembic)
- See: Document 01 §2, Document 04 (full stack table and rejected alternatives), Document 25
  (schedule impact), Document 26 (risk-register updates: bus-factor risk, AI-generated-code review
  risk, retired Node↔Python integration-friction risk)
