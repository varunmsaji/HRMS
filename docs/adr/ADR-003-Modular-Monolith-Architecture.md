# ADR-003: Modular Monolith Architecture

**Status:** Accepted  
**Date:** 2026-08-03  
**Detailed ADR:** [0001-modular-monolith.md](0001-modular-monolith.md)

## Context

Phase 1 scope spans 20+ HR domains with tight transactional coupling (leave → attendance → payroll). A solo developer cannot operate a microservices fleet. Team may grow later.

## Decision

Build a **modular monolith**:

- One deployable Python package (`hrms`)
- Modules under `src/hrms/modules/` with strict import boundaries
- Four process entrypoints (api, ingestion, worker, beat) — not four separate codebases
- Domain events for async cross-module effects (outbox for money/compliance)

## Consequences

- **Positive:** ACID across modules; simpler debugging; one CI pipeline.
- **Positive:** Module boundaries preparatory for future service extraction if needed.
- **Negative:** Discipline required — boundaries enforced by import-linter, not framework.
- **Negative:** Single binary scales vertically first; horizontal scaling is whole-app.

## Alternatives rejected

- Microservices for Phase 1
- Serverless core API for payroll workloads
