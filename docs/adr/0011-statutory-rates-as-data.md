# ADR-0011: Statutory Rates as Effective-Dated Data, Never Code

**Status:** Accepted

## Context

Indian statutory payroll components — EPF, ESI, Professional Tax (state-specific), TDS slabs,
Gratuity, Bonus, LWF (Doc 03 A1) — change rates and thresholds periodically, sometimes with
retroactive effective dates announced by the government. If these values are hardcoded (even as
named constants) in the payroll computation code, every rate change requires a code change, a
review, a deploy, and — worse — makes historical payroll runs impossible to reproduce correctly
once the code has moved on to the new rate. Doc 03 principle 3 ("configuration over code") applies
directly, and the specific failure mode here is severe: an incorrect statutory computation is a
compliance violation, not just a bug.

## Decision

Statutory rates live in a `statutory_master` table (Doc 04 §2 ERD), itself effective-dated per
ADR-0003's pattern, keyed by jurisdiction (e.g. PT by state) and effective period. Payroll
computation reads the rate row effective for the pay period being computed — via the input
snapshot (ADR-0005) — never a code constant. A rate change is a data update (with the correct
effective date, potentially backdated per government notification), reviewed and applied without a
code deploy.

## Consequences

- **Positive:** a statutory rate change is a data operation with its own review process (Doc 14
  §9, runbook 14: "Statutory rate change requiring an urgent update"), decoupled from the code
  release cadence and the payroll blackout window (Doc 14 §10).
- **Positive:** historical payroll runs remain reproducible and explainable — the snapshot
  (ADR-0005) captured the statutory master version in effect at computation time, so re-deriving
  "why was March's PT this amount" never depends on reading old, since-changed code.
- **Negative:** requires a real UI/workflow for managing statutory master data (Doc 02A §7.2) with
  its own validation — a rate entered with the wrong effective date is a live compliance bug, so
  this data needs the same scrutiny a code change would get, just through a different mechanism.
- **Negative:** the compliance/payroll consultant (Doc 12 §5.2) must be involved in maintaining
  this data accurately over time — it is an ongoing operational responsibility, not a one-time
  setup task.

## Alternatives Considered

- **Hardcoded rate constants in the payroll engine, updated via code deploy per change.** Rejected:
  couples a compliance-critical, frequently-changing input to the software release process, and
  makes historical reproducibility depend on git archaeology instead of a queryable data row.
- **External statutory-rate service/API.** Considered for the future if a reliable, authoritative
  feed becomes available; not adopted for Phase 1 because no such feed is confirmed reliable enough
  to be a dependency for a compliance-critical input — internally managed data with the compliance
  consultant's review is the safer Phase 1 choice.
