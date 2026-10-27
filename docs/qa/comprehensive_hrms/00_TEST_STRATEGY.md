# 00 — Test strategy

Status of this document: design only. No HRMS test run was started to produce it.

## Scope

Staff Spectrum HRMS as implemented in this repository on 2026-10-26:

- API: FastAPI modular monolith, PostgreSQL with row-level security, Redis, Celery, object storage.
- Web: Next.js routes under `apps/web/src/app`.
- Mobile: Flutter under `apps/mobile`. Flutter SDK was absent on the last QA host, so mobile execution is blocked until the SDK is present.
- Five system roles created by `OrganisationService.register_company`: `COMPANY_ADMIN`, `HR_ADMIN`, `REPORTING_MANAGER`, `BRANCH_MANAGER`, `EMPLOYEE`. There is no permission editor and no custom-role UI.

Out of scope until a product decision says otherwise: recruitment, ATS, AI resume processing, billing, Form 16/24Q, PF ECR, loans, reimbursements, full-and-final settlement, geofence, device punch import, in-app notifications.

## What “tested” means

A case passes only when the UI state, the API outcome, and the database invariants named in the case agree. HTTP 200 alone is not a pass. `BLOCKED` and `NOT_RUN` are not passes.

## Priority

| Priority | Meaning |
|---|---|
| P0 | Tenant isolation, authentication, leave balance integrity, payroll money movement, or a broken primary journey. |
| P1 | A daily HR or employee task that has no workaround. |
| P2 | Boundary, concurrency, or configuration variant of a P0/P1 rule. |
| P3 | Unused stored fields, copy, or a confirmed non-feature that only needs a regression guard. |

## Risk

| Level | Use |
|---|---|
| Critical | Cross-tenant write, double debit, double pay, privilege escalation. |
| High | Wrong balance, wrong approver, locked period bypass, leaked compensation. |
| Medium | Wrong message, missing audit row, stale UI with a correct database. |
| Low | Empty-state copy, unused policy field that the UI still shows. |

## Test levels

1. Smoke: health, login, one read per module.
2. Module functional: the catalogues in this folder.
3. Journey: `03_USER_JOURNEYS.md`, composed from module cases.
4. Permission and tenant: `02` and `08`.
5. Concurrency and idempotency: called out inside each catalogue.
6. Recovery: disposable environment only, after the batches in `TEST_EXECUTION_PLAN.md` are approved.
7. Scheduled jobs and performance: not in the first execution wave.

## Safety boundaries

- Design phase does not execute tests. Execution waits for review of `TEST_EXECUTION_PLAN.md`.
- Execution, when approved, uses a new disposable database, Redis DB, and bucket. Before each batch the runner prints `ISOLATION PROVED` only after those names are shown to be distinct from the shared development services.
- Free disk must be at least 3 GiB before a run and the run stops below 2 GiB. The 2026-10-25 QA report found the host root filesystem full; that failure mode is still a precondition, not a product defect.
- No production credentials, real email, SMS, payment, or webhook.
- No grant-script rerun, no shared container restart, no commit or deploy.
- Existing uncommitted work stays. This folder is additive.

## Sources of expected behaviour

Expected results cite code or a named decision record. Where those disagree, the case says so and `OPEN_BUSINESS_RULES.md` records the question. The functional gap register (`docs/product/STAFF_SPECTRUM_HRMS_FUNCTIONAL_GAPS.md`) is evidence of an earlier review, not automatically current behaviour. Example: that register says the Employee role has no attendance grants; `organisation/service.py` now grants `ATTENDANCE.PUNCH`, `ATTENDANCE.VIEW`, and `ATTENDANCE.REGULARIZATION_REQUEST` at `SELF`, with migration `20261020090000` named as the backfill. The catalogue tests the code, and asks for a decision only where the code itself is ambiguous.

## Existing evidence kept visible

Live register `docs/testing/qa_live_2026-10-25/register.csv`: 216 checks, 214 PASS, 1 INFO, 1 FAIL (`ATT-15` / K-1). Browser journeys were not driven in that pass. Those results are historical claims, not reruns.
