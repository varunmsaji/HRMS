# ADR-0001: Modular Monolith Over Microservices for Phase 1

**Status:** Accepted (amended 2026-08-03 — see note below)

> **Amendment note:** this ADR originally specified the modular monolith in NestJS/TypeScript
> terms. ADR-0013 replaced the backend language with Python/FastAPI; the modular-monolith **pattern**
> decided here is unaffected and remains in force. The text below has been lightly edited to
> describe the boundary-enforcement mechanism in stack-neutral terms (originally: ESLint
> `no-restricted-imports` + dependency-cruiser; now: `import-linter`, Doc 07 §3) and to update the
> "four services" list for the current deployable topology (Doc 03 §1.1). No decision or
> consequence stated here has changed in substance.

## Context

The platform has 22 modules and a team that ramps from 5 to ~12 engineers over Phase 1
(Doc 12 §5). Several of those modules — leave, attendance, payroll — have tight transactional and
temporal coupling: a leave approval must recompute attendance, which flags payroll as stale, all
for the same employee on the same date. The domain boundaries between modules are also not yet
proven; several will move as real usage surfaces edge cases (e.g. whether "onboarding" owns
pre-joining employee records or "employee" does).

Microservices would require distributed transactions across leave → attendance → payroll from day
one, before we know where the real boundaries are, with a team too small to operate the
associated infrastructure (service mesh, distributed tracing, saga orchestration) on top of
building the product itself.

## Decision

Build a **modular monolith**: one deployable Core API containing all business modules, with
strictly enforced internal module boundaries (Doc 07 §3) — each module exposes only a
`service.py` interface; cross-module DB access is banned and lint-enforced (`import-linter`
contracts, checked in CI).

Four deployables are built from one codebase from day one because their scaling and failure
profiles are already known to differ, not because their domain boundaries are uncertain (Doc 03
§1.1):

1. **Core API** — the monolith
2. **Worker (+ Beat)** — same codebase, different process (payroll runs, imports, reports, notifications, scheduled jobs)
3. **Device Ingestion service** — biometric push endpoints; must survive Core API deploys (ADR-0007)
4. **AI module** — internal by default (Doc 12 §1), now the same language and process family as the
   rest of the backend (ADR-0013), sharing models/session/auth context directly rather than crossing
   a service boundary; kept behind the same module-boundary discipline as every other module, with
   an explicit seam to extract into its own deployable later if GPU/latency isolation needs it

## Consequences

- **Positive:** one codebase, one deploy pipeline, one transaction boundary for the majority of
  cross-module workflows; enforced module boundaries mean extraction to a real service later is a
  refactor, not a rewrite, once we have scaling evidence.
- **Positive:** a small team can reason about the whole system; no distributed-systems tax before
  it's earned.
- **Negative:** the monolith becomes the single largest deploy unit — a bad deploy affects every
  module at once. Mitigated by blue-green deploys with automatic rollback (Doc 14 §3) and by the
  three services above already being independent of Core API's deploy cadence.
- **Negative:** module boundary discipline requires ongoing enforcement (lint rules, code review)
  or it erodes silently. This is treated as a CI gate, not a convention.

## Alternatives Considered

- **Full microservices per module.** Rejected: 22 services for a team of 8-14 is a well-documented
  way to fail (Doc 03 §1.1) — distributed transactions across leave/attendance/payroll, and domain
  boundaries not yet known well enough to draw service lines that will still be correct in a year.
- **Single service, no internal boundaries.** Rejected: without enforced module isolation, an
  HRMS of this size degenerates into a big ball of mud within a few sprints — cross-module queries
  are the single largest source of "can't extract this later" technical debt.

## Extraction Candidates for Phase 3

Payroll engine (CPU-bound bursts), Attendance ingestion (already separate), Reporting/analytics
(already on a read replica), Notification dispatcher — revisit once real traffic data exists.
