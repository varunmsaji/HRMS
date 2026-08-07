# ADR-0006: Money as Integer Minor Units + Decimal Library, Never Floats

**Status:** Accepted

## Context

IEEE-754 floating point cannot represent most decimal fractions exactly. Payroll sums thousands of
small components (basic, HRA, allowances, deductions, statutory contributions) per employee per
run; float rounding error compounds across that many additions and multiplications, and a
one-paise discrepancy in a bank file or a statutory filing is not a cosmetic bug — it's a
compliance and trust problem in a domain where users reconcile "every rupee for every employee"
(Doc 12 §3, the parallel payroll gate).

## Decision

Money is stored as an **integer in minor units** (paise for INR) — `BIGINT` in Postgres — with an
explicit `currency CHAR(3)` column alongside it (Doc 04 header, A10). All payroll and financial
arithmetic uses a decimal-safe library server-side, with explicit, documented rounding rules
defined per salary/statutory component. Client-side salary computation of any kind is disallowed
(Doc 03 §2.3) — all money math happens on the server, against the integer representation.

## Consequences

- **Positive:** addition and subtraction of minor units is always exact; no floating-point drift
  across thousands of components per run.
- **Positive:** a single, explicit rounding rule per component (not implicit float rounding)
  makes payroll output auditable and explainable per Doc 03 §6 ("every payslip line stores
  `{formula, inputs, intermediate, result}`").
- **Negative:** every layer that touches money (API DTOs, ORM types, frontend display) must
  consistently treat it as an integer + currency pair rather than a plain number — a stray
  `parseFloat` or a naive JSON serialisation of a large `BigInt` is a real footgun the codebase
  must guard against (see `Money` value object in `apps/api/src/shared/value-objects/money.ts`).
- **Negative:** display formatting (dividing by 100, adding currency symbols/locale grouping) is
  an extra step at every UI boundary instead of "just render the number."

## Alternatives Considered

- **JavaScript `number` / float columns.** Rejected outright — this is the exact failure mode the
  decision exists to prevent.
- **Arbitrary-precision decimal type in Postgres (`NUMERIC`) instead of integer minor units.**
  Considered viable, but integer minor units are simpler to reason about across language
  boundaries (JS `BigInt`, JSON, wire formats) and avoid ambiguity about how many decimal places a
  `NUMERIC` column silently allows; `NUMERIC` is used elsewhere in this schema for percentages
  (Doc 04 header) where fractional precision, not exactness of whole-paise sums, is the goal.
