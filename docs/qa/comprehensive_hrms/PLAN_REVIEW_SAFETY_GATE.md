# Plan review — safety gate

Date: 2026-10-26. Scope: `docs/qa/comprehensive_hrms/TEST_EXECUTION_PLAN.md` and the catalogues it names. No test was executed.

The plan is **not approved**.

## Risks

| # | Risk | Outcome |
|---|---|---|
| 1 | Isolation proof | **Fail on the previous plan, closed in the revision.** The previous plan printed `ISOLATION PROVED` after only a database name, a Redis index, and a bucket, compared loosely with "the compose project". It did not identify the API PID, the Celery worker, the runner, broker versus Redis, the email provider, or the settings fallback in `apps/api/.env`. Those defaults are `localhost:5433/hrms_dev`, Redis `localhost:6380/0`, and bucket `hrms-documents` on `hrms-minio`. That was ambiguous enough to mark the previous plan `BLOCKED`. The revision lists the forbidden names and ports, requires all eight checks, and allows `ISOLATION PROVED` only after every line matches. |
| 2 | Cross-tenant safety | **Fail on the previous plan, closed in the revision.** Tenant denial was batch 9, after leave, attendance, and payroll writes. The revision inserts batch S: anonymous access, missing company context, foreign company context, list reads, and GET-by-id, using markers `MARKER-FOUNDRY` and `MARKER-NORTHWIND` only. PATCH, punch posts, and worker jobs stay in later batches. Any cross-tenant write stops the programme. |
| 3 | Database and SQL | **Held.** Batch 10 is ATT-011 only: `UPDATE` of `public.punch.punch_time` by the runtime role, then `SELECT`. Expected protection is that the role cannot `UPDATE` or `DELETE` `punch`. Success of the `UPDATE` remains a FAIL for K-1. The statement was not run. Group approval cannot include this case. Schema changes, grant changes, and any database other than the proved `hrms_qa_*` name are prohibited. |
| 4 | Resource safety | **Partial on the previous plan, closed in the revision.** The 3 GiB start gate and the 2 GiB hard stop were already present. The revision states when disk is measured, adds a 60-second sample of disk and `MemAvailable` on long batches, stops only the recorded PIDs, and says an interrupted case is `INCONCLUSIVE`. Cleanup may touch only names printed on `ISOLATION PROVED`. |
| 5 | Leave | **Partial.** Day-count, overlap, half-day, reject, cancel, duplicate submit, and concurrent approval cases have one opening balance, one charge, one ledger movement, and one ending balance. Those figures are copied into the plan and were not changed in the catalogues. LEV-C12, LEV-C40, LEV-C41, and LEV-C42 stay out of group approval because BR-02, BR-03, and BR-10 do not pick a single outcome. LEV-C05 stays at 2.00 because that is the code; BR-01 is still open and must not replace the expected result. |
| 6 | Attendance and payroll | **Partial.** Batch 6 cases record owner, zoned timestamps, shift bounds, and the day row. ATT-005 is held for BR-04. Payroll maker-checker, one-line idempotency, period lock on finalise, and audit name are in the batch 7 cases. PAY-002 and PAY-009 do not yet contain a single net in paise, so they wait for a sheet written before the run. Salary data is the synthetic 30000.00 structure and account `999000111222`. |
| 7 | Evidence | **Partial on the previous plan, closed in the revision.** The old evidence line omitted environment id as a required field name, defect id, cleanup, and `INCONCLUSIVE`. The revision requires expected text copied before the run, actual text, status, timezone, environment id, and artefact paths. Harness errors stay `BLOCKED` or `INCONCLUSIVE`. Pass rate uses `PASS` over `PASS + FAIL` only. |
| 8 | UI and tooling | **Pass, unchanged.** Playwright is not added. UI cases are `BLOCKED` when no browser runner is already installed. Mobile stays `BLOCKED` until `flutter` is on `PATH`. Email is the logging provider. Payments and webhooks stay off. |

## Changes made to the plan

- Replaced the three-name isolation line with an eight-point proof and an explicit forbidden-target table.
- `ISOLATION PROVED` is now conditional on all eight points. Otherwise the run prints `ISOLATION BLOCKED`.
- Added batch S before mutation-heavy batches, and split worker, year-end, accrual, and failure injection into batch F.
- Documented ATT-011's table, statement type, role, protection, evidence, and restore rule. Removed it from any group that could be approved together.
- Added disk and memory sampling, PID-scoped stop, and interrupted-run cleanup.
- Copied the deterministic leave figures into the plan without editing catalogue expectations.
- Held every case whose expectation depends on an open product rule.
- Extended the evidence record and the pass-rate rule.

Catalogue files, application code, schemas, migrations, and grants were not edited.

## Safe to consider for a later approval

Only after a future run has printed `ISOLATION PROVED`, and only if that approval names the batches:

- Batch 0 and the two-tenant setup.
- Batch S.
- Batches 1, 2, 3, 4, and 6, excluding ATT-005.
- Batch 5, excluding LEV-C40, LEV-C41, and LEV-C42.
- Batch 7, excluding PAY-002 and PAY-009, and only with statutory off and a paise sheet written first.
- Batches 8 and 9, excluding failure injection.

## Individual approval required

ATT-011 (batch 10), including a compensating `UPDATE` if the first one succeeds. Also LEV-C12, LEV-C40, LEV-C41, LEV-C42, ATT-005, PAY-002, PAY-009, EMP-005, EMP-006, ONB-004, DOC-002, JRN-010, and SEC-005.

## Still unresolved

BR-01 through BR-14 in `OPEN_BUSINESS_RULES.md`. Isolation has not been proved on a live process, because this review did not start one. Historical October 25 results were not rerun.

## Confirmation

No pytest, Vitest, browser, Celery, or other test command was run. No container or database was created or started. Application code, schemas, migrations, grants, and catalogue expectations were not changed. Nothing was committed, pushed, reset, stashed, or discarded.

Git before this review: branch `main`, commit `436a2e5`, `git status --short` line count 256, `docs/qa/comprehensive_hrms/` untracked as one directory. Git after: same branch, same commit, same short-status line count 256, because the directory is still untracked. The catalogue now has 21 files. The only files this review wrote are `TEST_EXECUTION_PLAN.md` (replaced) and `PLAN_REVIEW_SAFETY_GATE.md` (new). No other path was staged or modified by this review.

## Status

AWAITING HUMAN APPROVAL
