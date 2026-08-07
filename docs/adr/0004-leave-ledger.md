# ADR-0004: Leave Balance as an Append-Only Ledger, Never a Stored Counter

**Status:** Accepted

## Context

Leave balance is one of the most frequently disputed numbers in any HRMS — employees check it
constantly and escalate immediately when it looks wrong. A single mutable `balance` column updated
in place on every accrual, application, approval, cancellation, encashment and year-end carry-
forward accumulates rounding drift and, worse, gives support staff no way to answer "why is my
balance 12.5 and not 14?" without git-archaeology through application logs.

## Decision

`leave_ledger` (Doc 04 §7.3) is **append-only**: every accrual, deduction, adjustment, encashment
and carry-forward is its own immutable row with a type, amount, reference and timestamp. The
displayed "balance" is a derived sum over the ledger for that employee and leave type, never a
column that gets decremented or incremented in place.

## Consequences

- **Positive:** any balance is explainable and reconstructable — "why is my balance X" is a filter
  on the ledger, not a mystery. This directly serves Doc 03 principle 4 (every state change is
  audited) for the specific number employees dispute most.
- **Positive:** correcting an error is an adjustment entry, consistent with how payroll corrections
  work (ADR-0005) — never an edit of a past entry.
- **Negative:** computing "current balance" requires summing the ledger rather than reading one
  column — mitigated with an indexed, possibly materialised, per-employee/leave-type running total
  refreshed on write, since balances must never be served from a stale cache (Doc 03 §7, "never
  cache: leave balances").
- **Negative:** more storage and more rows than a counter model; acceptable given leave volume is
  orders of magnitude below attendance punches.

## Alternatives Considered

- **Mutable balance column, updated transactionally on each event.** Rejected: loses the audit
  trail that makes disputes resolvable, and any missed or double-applied update silently corrupts
  the single source of truth with no way to detect it after the fact.
- **Mutable balance column + a separate event log for audit purposes only.** Rejected: two sources
  of truth that can drift apart is worse than one authoritative ledger; if the log is authoritative
  enough to explain the balance, it should simply be the balance.
