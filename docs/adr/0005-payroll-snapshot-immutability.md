# ADR-0005: Payroll Inputs Snapshotted; Finalised Runs Immutable

**Status:** Accepted

## Context

Payroll is the one place in this product where correctness beats every other concern (Doc 03 §6).
A pay run reads compensation, attendance summary, leave, arrears, loans and statutory master data
that all continue changing after the run computes — a master-data edit made an hour after
computation must never silently alter figures a run already produced. Once a payslip is issued,
government filings and bank transfers reference it as a fact; editing history after the fact is
not a valid way to fix a mistake in a system whose outputs are legally and financially binding.

## Decision

Payroll execution is a **checkpointed, resumable pipeline** (Doc 03 §6):

1. **Create run** — lock the period, snapshot the employee list.
2. **Snapshot inputs** — copy compensation, attendance, leave, arrears, loans and statutory master
   versions into an immutable `payrun_input_snapshot`.
3. **Compute** — a pure function of the snapshot, parallelised across employee batches, no shared
   mutable state; each result stores a calculation trace.
4. **Validate / Variance** — automated checks and comparison against the previous run.
5. **Review** — a human approval gate that cannot be skipped.
6. **Finalise** — write payslips, mark the run immutable, emit `PayRunFinalised`.

Once finalised, a run's results are frozen. Any subsequent error is corrected with an
arrears/adjustment component in a **later** run — never by editing a finalised run's records.

## Consequences

- **Positive:** a later change to a master record cannot retroactively alter a computed run — the
  snapshot is what computation actually read, and it's preserved.
- **Positive:** computation is deterministic and unit-testable against a golden dataset of real
  payroll cases (Doc 13 §3), because it is a pure function of an immutable input.
- **Positive:** a crash mid-run resumes from the last checkpoint; a partially computed run is never
  visible to anyone, so there is no window where an incomplete payroll could be mistaken for final.
- **Negative:** corrections always flow forward as arrears, which is less intuitive to a new HR
  admin than "just editing the number" — this must be explicit in training and UI copy.
- **Negative:** snapshotting doubles storage for every run's inputs; acceptable given payroll runs
  monthly, not per-transaction.

## Alternatives Considered

- **Compute directly against live master data, no snapshot.** Rejected: a compensation correction
  made mid-computation (a realistic race in a live system) would produce an inconsistent run with
  no way to know which employees read old vs. new data.
- **Allow editing a finalised run directly for "obvious" fixes.** Rejected: there is no such thing
  as an obvious fix once a payslip has been issued and a bank file generated — the arrears/
  adjustment path is the only version of "fix" that doesn't rewrite a legally relevant record.
