# HRMS Master Product Test Plan & Module Map

**Status:** Planning phase only — discovery, mapping, classification. No test execution has occurred as a result of this document. No application code, database schema, migrations, tests, or configuration were modified to produce it.

**Date:** 2026-10-08
**Author:** Lead QA Architect / Product Validation pass (Claude Code, read-only codebase inventory)
**Method:** Direct inspection of `apps/api`, `apps/web`, `apps/mobile`, `alembic/versions`, `docker-compose*.yml`, `.github/workflows`. Documentation under `docs/` was treated as *secondary* and untrusted; where a doc claim conflicted with code, the conflict is recorded in §6 rather than silently resolved.

---

## 0. Why this document exists

This is the answer to: *what exactly exists in this HRMS, what should be tested, who uses it, how modules connect, and what complete user journeys must be validated?*

It intentionally does not fix, test, or implement anything. It is the map that a subsequent execution phase (writing/running new tests) would work from.

It also carries forward, unchanged, the pre-existing production-readiness state from prior audits (per project memory and the brief this was commissioned under):

- **Pre-Payroll surface**: READY FOR PRODUCTION (2,361 backend tests / 505 frontend tests passing, 0 vulnerabilities, `hrms_app` role verified NOSUPERUSER/NOBYPASSRLS at CI time).
- **Payroll**: READY FOR CONTROLLED PILOT, NOT LIVE PAYROLL.
- **Explicitly accepted/unverified, not to be treated as done**: mobile device testing, real Face++ /Luxand liveness validation, large-scale load testing, full disaster-recovery drill, production deployment smoke testing, deferred P2/P3 items.

Nothing in this inventory pass re-verified or overturned those statuses — they're restated here as inputs, not re-derived.

---

## 1. Master Module Tree (verified against code)

```
HRMS
│
├── 1. Platform / Foundation
│   ├── 1.1 Configuration           core/config (Settings; boot-time guards reject unsafe SMTP/MinIO/DB config)
│   ├── 1.2 Database & Migrations   SQLAlchemy async + Alembic, 111 migration files, scripts/sql/001_init_schema.sql
│   ├── 1.3 Row-Level Security      ~80 tables, single `tenant_isolation` policy pattern, FORCE RLS
│   ├── 1.4 Runtime DB role         hrms_app (NOSUPERUSER/NOBYPASSRLS) vs hrms (migration/superuser owner)
│   ├── 1.5 Error handling          core/errors (envelope + exception handlers)
│   ├── 1.6 Observability           core/observability (structured logging only — no APM/metrics found)
│   ├── 1.7 Background jobs         core/celery_app.py — Celery + Beat
│   ├── 1.8 Object storage          core/storage.py — MinIO/S3-compatible (DocumentStorageService)
│   ├── 1.9 Field-level crypto      core/crypto — PII encryption, key registry/master key/provisioning
│   ├── 1.10 Idempotency            core/idempotency.py + idempotency_key table
│   └── 1.11 Shared primitives      shared/ — pagination, rate_limit, business_time, timezone, if-match (409 concurrency)
│
├── 2. Authentication & Account
│   ├── 2.1 Login                   Argon2 hashing, email-verified gate, lockout check
│   ├── 2.2 Logout                  revokes session + all refresh tokens
│   ├── 2.3 Password reset          revokes ALL sessions/tokens on reset (SEC-07)
│   ├── 2.4 Sessions                `session` table; re-validated (not just JWT-signature-checked) every request
│   ├── 2.5 Refresh tokens          rotation + reuse-detection (token_family_id), HttpOnly cookie (SEC-06)
│   ├── 2.6 Account lockout         5 failed attempts → 15 min lock
│   ├── 2.7 Email verification      blocks login until verified
│   ├── 2.8 OAuth                   NOT IMPLEMENTED — absent by design, not a gap unless roadmapped
│   └── 2.9 Account invite          separate module; token-based accept; intentionally NO RLS (pre-tenant-context)
│
├── 3. Organization
│   ├── 3.1 Company                 register/current/setup-progress/subscription/dashboard
│   ├── 3.2 Legal entities
│   ├── 3.3 Branches
│   ├── 3.4 Departments
│   ├── 3.5 Designations
│   ├── 3.6 Grades
│   ├── 3.7 Shifts                  + versions, breaks, duty blocks, publish workflow
│   ├── 3.8 Weekly-off patterns
│   ├── 3.9 Holiday calendars       + holidays
│   ├── 3.10 Work calendars         + exceptions
│   ├── 3.11 Policy assignment/resolution  cross-cutting policy→scope mapping + computed resolver
│   └── 3.12 Plans/Subscriptions/Feature flags  SaaS-tier catalog (plan/plan_feature are global, not tenant-scoped)
│
├── 4. Employee Management
│   ├── 4.1 Employee creation / profile
│   ├── 4.2 Employment record        (+legal_entity_id)
│   ├── 4.3 Assignment               department/branch/reporting-manager — the RBAC data-scope backbone
│   ├── 4.4 Compensation
│   ├── 4.5 Statutory
│   ├── 4.6 Bank details
│   ├── 4.7 Experience / Education
│   ├── 4.8 Dependents
│   ├── 4.9 Probation / Confirmation
│   ├── 4.10 Termination             + hourly Celery access-revocation sweep
│   ├── 4.11 Rehire                  mentioned in brief/memory as hardened (L11/L12) — module boundary not independently re-verified this pass; VERIFY
│   ├── 4.12 Bulk import             employee_import — async Celery, create-only (no auto-retry by design), documented RLS mid-batch-commit risk (service.py:549)
│   └── 4.13 Documents               no standalone "employee documents" domain found — flows through onboarding's document storage; VERIFY this is the intended single path
│
├── 5. RBAC / Permissions
│   ├── 5.1 Roles & Permissions schema   role / permission / role_permission(+data_scope) / user_role
│   ├── 5.2 Data scope levels        SELF, REPORTEES, REPORTEE_TREE, BRANCH, COMPANY (4 of a documented 8 — DEPARTMENT/LEGAL_ENTITY/ALL_COMPANIES explicitly out of scope)
│   ├── 5.3 Enforcement              require_permission() FastAPI dependency — fails closed, never defaults to COMPANY
│   ├── 5.4 Visible-employee resolution  reportee-tree (depth-capped 20) / branch-colleague resolution in employee/service.py
│   └── 5.5 Tenant isolation (RLS)   the hard backstop beneath RBAC — see 1.3
│
├── 6. Attendance
│   ├── 6.1 Punch                   self + admin, idempotency-key scoped per company
│   ├── 6.2 Face attendance         enrollment (admin-gated window, 5-pose mobile capture) + punch (camera→backend→Luxand.cloud server-side ONLY — no on-device liveness at punch time, no mobile Luxand code at all)
│   ├── 6.3 Manual/admin attendance entry
│   ├── 6.4 Regularization          request + approve/reject
│   ├── 6.5 Overtime                record + approve/reject → feeds comp-off credit
│   ├── 6.6 Comp-off                hourly credit sweep + daily expiry sweep
│   ├── 6.7 Attendance periods      validate/finalize/reopen — payroll-cutoff lifecycle
│   ├── 6.8 Attendance dashboard    KPI grid, trend/status charts, heatmap, who's-in, needs-attention, overtime panel, self-view
│   ├── 6.9 Reports                 6 tabs (daily/present-absent/late-early/hours/overtime/payroll) — client-side only, **NO EXPORT** (explicit in-code disclaimer)
│   ├── 6.10 Rosters                list/calendar, bulk-assign, publish
│   ├── 6.11 Policies               attendance/overtime/regularization, versioned, publish/resolve
│   ├── 6.12 Reminders              incomplete-punch daily digest (Beat 10:00 IST)
│   └── 6.13 Daily calculation job  Beat 09:30 IST (trailing 3 days) + on-demand range backfill (202 async)
│
├── 7. Leave
│   ├── 7.1 Leave types
│   ├── 7.2 Leave policies(+versions) + combination rules
│   ├── 7.3 Leave year settings + statutory minimums
│   ├── 7.4 Balances / ledger       adjustments + encashments (admin-only manipulation)
│   ├── 7.5 Applications            apply/approve/reject/cancel, multi-stage, approver reassignment
│   ├── 7.6 Accrual                 monthly, Beat day-1-gated but runs daily (self-repairing)
│   ├── 7.7 Year-end processing     carry-forward cap enforcement (Beat daily 02:00 IST) + manual operator call
│   └── 7.8 Employment-validity/rehire interaction  per memory, L11/L12 decisions implemented — confirm test coverage still matches current code
│
├── 8. Payroll  — PILOT-READY, NOT LIVE-READY (carried forward, not re-verified)
│   ├── 8.1 Salary components / structures (+versions/lines)
│   ├── 8.2 Salary assignment       incl. bulk assign
│   ├── 8.3 Pay run lifecycle       lock-inputs → compute → approve → finalise → mark-paid → rollback — fully SYNCHRONOUS, no Celery task at all
│   ├── 8.4 Attendance/Leave inputs into pay run compute
│   ├── 8.5 Statutory rates (+verify)
│   ├── 8.6 Arrears / Adjustments
│   ├── 8.7 Payslips                JSON-only via API; NO stored PDF; mobile renders PDF client-side
│   ├── 8.8 Bank advice             the ONE real export in the whole product (CSV)
│   ├── 8.9 Finalisation immutability  DB-level immutability migration + dedicated test
│   └── 8.10 Known residual risk areas (unchanged from prior audit — NOT re-verified here): salary/input race around finalisation, employment changes post-finalisation, payment lifecycle, month sequencing, taxable-component/TDS, separation of duties, compute performance, legal-entity migration validation, mobile verification, stale-409 UI, payment processing limitations
│
├── 9. Employee Self-Service (ESS)
│   ├── 9.1 Profile                 web /app/me, mobile profile_screen
│   ├── 9.2 Attendance self-view/self-punch/face-enrollment/face-punch
│   ├── 9.3 Leave apply + balance view
│   ├── 9.4 Payslips                web list/detail; mobile PDF render
│   ├── 9.5 Documents                via onboarding flows where applicable
│   └── 9.6 Mobile-only ESS gaps (confirmed absent, not assumed): no push notifications, no geofencing, no offline punch queueing
│
├── 10. Management / Admin
│   ├── 10.1 Dashboards             company/setup dashboard (web); team attendance (mobile)
│   ├── 10.2 Reports / exports      attendance = no export; payroll = bank-advice CSV only; no PDF export anywhere
│   ├── 10.3 Employee management    admin CRUD, data-scope filtered
│   ├── 10.4 Attendance management  periods, regularization/overtime approval, roster publish
│   ├── 10.5 Leave management       ledger adjustments, approvals, year-end
│   ├── 10.6 Payroll management     pay-run lifecycle, salary config
│   ├── 10.7 User management        /app/users, role assignment via account_invite
│   └── 10.8 Onboarding case review internal case list/detail + public token-based candidate wizard
│
├── 11. Notifications / Communication
│   ├── 11.1 Email                  ONLY channel; providers logging(dev)/smtp/mailtrap; per-module templates
│   ├── 11.2 In-app notifications   NOT IMPLEMENTED — no Notification model/inbox anywhere; roadmap-tracked "Not started"
│   ├── 11.3 Background notification jobs  attendance incomplete-reminders (Beat 10:00 IST)
│   └── 11.4 Failure/retry behavior email sends are explicitly best-effort (exceptions swallowed) BY DESIGN; no DLQ for any Celery task anywhere
│
├── 12. Files / Documents
│   ├── 12.1 Upload                 onboarding docs, employee-import CSVs, face-enrollment review photos
│   ├── 12.2 Download               presigned URLs (300s, forced attachment disposition) for onboarding docs; server-side-only fetch for face review photos (no presign)
│   ├── 12.3 Access control         permission-checked before URL issuance; bucket fully private, no anonymous access
│   └── 12.4 Deletion/retention     event-driven deletes only; NO scheduled retention/lifecycle sweep anywhere — VERIFY if this is acceptable for compliance
│
├── 13. Audit / Compliance
│   ├── 13.1 Audit log              company-scoped, RLS-protected, ~80+ distinct action codes across every domain
│   ├── 13.2 Immutability           UPDATE/DELETE/TRUNCATE revoked from hrms_app on audit_log + leave_ledger + leave_application_action (2026-10-09 migration)
│   ├── 13.3 Retention              NOT COVERED by any inventory pass — no archival/retention policy found — VERIFY
│   └── 13.4 Security events        login/logout/invite audited; dedicated tests/security/ suite exists
│
└── 14. Platform / Operations
    ├── 14.1 Docker                 dev compose = postgres/redis/minio only (api/web/worker run outside Docker); prod compose = full topology incl. nginx/certbot, two networks
    ├── 14.2 Migrations             Alembic, 111 versions; CI applies init scripts + alembic upgrade head + verifies hrms_app role flags
    ├── 14.3 CI/CD                  single ci.yml, 4 jobs (api/web/security-scan/dependency-scan); NO deploy workflow (manual runbook); NO mobile/Flutter job in CI AT ALL
    ├── 14.4 Health checks          /health, /health/live, /health/ready; all docker-compose services healthchecked except Beat (must stay single-instance — no leader election)
    ├── 14.5 Backups                NOT COVERED by any inventory pass — VERIFY
    ├── 14.6 Observability          structured logging only — no APM/metrics tooling found — VERIFY if intentional
    └── 14.7 Deployment             docs/deployment/PRODUCTION_DEPLOYMENT.md manual runbook — not independently verified against real infra this pass
```

---

## 2. Testable End-to-End User Journeys

Grouped by actor. These are the journeys a future execution phase should validate end-to-end (crossing module boundaries), not unit-level checks.

### A. Public / unauthenticated
1. Candidate receives onboarding link → completes public token-based wizard (personal/address/bank/compensation/education/emergency-contact/nominee/previous-employment/documents/statutory) → submits → HR reviews/approves → case activates → user account provisioned.
2. New user receives account invite → accepts via token → sets password → logs in for the first time.
3. User forgets password → requests reset → resets → ALL prior sessions/tokens revoked → must log in again everywhere (including mobile).
4. User registers a new company (self-service signup) → email verification gate blocks login until verified.

### B. Employee (ESS — web + mobile parity)
5. Login → view profile → punch in/out (standard) on web and mobile; same action, confirm idempotency key prevents duplicate punches on retry/double-tap.
6. Face enrollment (one-time 5-pose guided capture, mobile only) → admin approves → employee performs a face-punch (mobile camera → backend → Luxand) → similarity score / enrollment-required error path.
7. Apply for leave → view updated balance → cancel before approval → balance reverts.
8. Regularize a missed/incorrect punch → manager approves/rejects → attendance day recalculates.
9. View payslip (web page vs mobile PDF render) — confirm both surfaces reflect the same finalised pay-run data.
10. Attempt an action outside permission (e.g., view another employee's payslip by guessing a URL/ID) → expect 403, not UI-only hiding (frontend's own `usePermissions` hook explicitly disclaims being the real gate — backend must be).

### C. Manager (data-scope-bound)
11. Login as a manager → confirm visible employee list is limited to reportees/reportee-tree/branch per assigned data scope, not company-wide.
12. Approve/reject a direct report's leave application, overtime, or regularization request → confirm a non-manager of that employee gets 403 on the same action.
13. View team attendance dashboard (mobile `team_attendance_screen`) → cross-check figures against web attendance dashboard for the same team/date.

### D. HR Admin / Org Admin
14. Full org-structure setup from scratch: legal entity → branch → department → designation → grade → shift (version + publish) → holiday calendar → work calendar → weekly-off pattern → policy assignment → policy resolution returns the expected effective policy for a test employee.
15. Create an employee end-to-end (profile → employment → assignment → compensation → statutory → bank → dependents) → confirm it appears correctly in attendance, leave, and payroll modules without extra setup.
16. Bulk-import employees via CSV → inspect batch errors endpoint for intentionally-malformed rows → confirm **no partial duplicate creation** on a resubmitted batch (no auto-retry, but manual resubmission risk) and specifically probe the documented RLS mid-batch-commit risk (`employee_import/service.py:549`) for cross-tenant leakage under concurrent batches from two companies.
17. Terminate an employee with a future last-working-day → confirm access remains until that date → confirm the hourly sweep revokes access exactly once that date passes, not before/twice.
18. Run attendance period lifecycle: validate → finalize → (attempt to reopen) → confirm payroll pay-run cannot bypass a locked period, and attempting pay-run compute against an unfinalized period is rejected.
19. Run leave ledger adjustment/encashment as admin → confirm it's audit-logged and reflected in the employee's ESS balance view immediately.
20. Run a full pay-run lifecycle (lock-inputs → compute → approve → finalise → mark-paid) with a realistic mixed employee set (new joiner mid-month, employee with unpaid leave, employee with approved overtime) → download bank advice CSV → cross-check totals against payslip JSON for each employee.
21. Attempt to modify a finalised pay-run or an employee's compensation effective inside a finalised period → confirm immutability enforcement (DB-level, per `20261013090000_payroll_finalised_immutable.py`) actually blocks it end-to-end through the API, not just at the DB layer.
22. Invite a new user and assign a role with a specific permission/data-scope combination → confirm the UI surfaces exactly the right actions and the backend independently enforces the same boundary (don't trust frontend `usePermissions` gating alone — explicitly test backend-only).

### E. Cross-tenant / security
23. Two companies, same admin browser session pattern: confirm `X-Company-Id` cannot be swapped to view another company's data even with a technically-valid JWT for a different company membership (`get_tenant_context` re-verification path).
24. Attempt the account-invite / onboarding public-token endpoints with a guessed/incremented token → confirm failure (these intentionally have no RLS, relying on token-hash lookup only — the main residual exposure surface to probe).
25. Connect directly as `hrms_app` (not through the API) and attempt cross-tenant SELECT/INSERT/UPDATE/DELETE on a handful of representative tables — confirmatory re-run of what `test_rls_runtime_role.py` already covers, as a sanity check before trusting it in a broader plan.
26. Attempt to UPDATE/DELETE a row in `audit_log` or `leave_ledger` as `hrms_app` → confirm privilege revoke actually blocks it (not just RLS).

### F. System / background
27. Let the full Beat schedule run across a simulated multi-day window (accrual, comp-off credit/expiry, year-end, daily attendance calc, termination sweep, incomplete reminders) → confirm idempotency holds if a job is manually re-triggered for a date it already processed (Beat is explicitly single-instance with no leader election — a duplicate fire is a real operational scenario, not hypothetical).
28. Kill/restart the Celery worker mid-task for a long-running attendance range-backfill → confirm `acks_late`/retry behavior where configured (leave tasks) vs the no-retry-by-design paths (attendance, employee_import) behave as documented, not accidentally duplicating work.

---

## 3. Test Coverage Heat Map (current state, as found)

| Domain | Backend (integration+unit) | Frontend | Mobile | Assessment |
|---|---|---|---|---|
| Organisation | 282 integration + 143 unit | Good (branches/depts/designations/grades/shifts have page tests) | Generic `ResourceListScreen`, some tests | **Strong** |
| Employee | 278 integration + 129 unit | **Zero page tests** on core employee pages | Covered via employee_record/profile tests | **Backend strong, frontend gap** |
| Attendance | 219 integration + 157 unit | Good (dashboard charts, punch dialog, periods tested) | Good (face punch, pose tracker, periods) | **Strong overall**, but face-punch camera/Luxand round-trip untested anywhere (always faked) |
| Leave | 232 integration + only 20 unit | **Almost zero page tests** (only review-dialog component tested) | Covered (applications, decimal parsing) | **Integration strong, frontend gap, unit-level thin** |
| Payroll | 53 integration + 73 unit | Only pay-run detail page tested; salary-components/structures pages untested | Covered reasonably (pay runs, salary panel, statutory rates) | **Thin relative to business risk and state-machine complexity** |
| Onboarding | 93 integration + 57 unit | **Zero tests** — largest frontend page (643 lines) + all 9 wizard steps untested | Covered (case detail, form spec, public screen) | **Frontend gap on the single largest/riskiest page** |
| Account invite | 67 integration, **zero unit tests** | N/A (covered under users/settings, untested) | N/A | **Unit gap** |
| Employee import | 7 integration + 16 unit | N/A (admin-only, likely under employees page — untested) | N/A | **Thinnest backend module relative to blast radius (bulk mutation)** |
| Auth/Identity | 39 integration | login/register/verify/accept-invite/forgot-password tested | login tested | **Adequate** |
| RBAC/data-scope | Diffuse (no dedicated folder; spread across account_invite, organisation, leave, `test_route_authorization_matrix.py`) | `use-permissions.ts` itself untested | N/A | **Coverage exists but is not centrally verifiable — recommend a dedicated cross-module RBAC matrix test inventory** |
| Security (RLS, headers, tokens) | 30 dedicated tests incl. `test_rls_runtime_role.py` | N/A | N/A | **Strong, but background-task RLS coverage doc is stale (claims no task touches DB — false)** |
| `ingestion` router | **No test directory found at all** | N/A | N/A | **Unknown — verify before assuming untested** |
| E2E (browser-driven) | N/A | **None exist** (no Playwright/Cypress anywhere) | Dart `live` suite (dev-local, real backend, gated by env var, not in CI) | **No true cross-stack E2E layer exists for the web app** |
| CI coverage of all the above | `ci.yml` runs api+web+security-scan+dependency-scan | same | **Mobile tests do not run in CI at all** | **Mobile is a CI blind spot** |

---

## 4. Explicitly Unresolved / Accepted Risk Areas (carried forward — not re-verified this pass)

Per the standing production-readiness position, these remain **not done** regardless of automated test pass rates, and this inventory did not attempt to change that:

- Mobile device testing (real devices, not emulators)
- Real Face++/Luxand liveness validation (current coverage fakes the repository at the punch flow; no genuine round-trip test exists on either side as found in this pass)
- Large-scale load testing
- Full disaster-recovery drill
- Production deployment smoke testing
- Deferred P2/P3 items from prior audits
- Payroll's ten specific residual risk areas (§1, item 8.10) — still pilot-only, not live-ready

New candidates to add to this "not yet verified" list, surfaced by this pass specifically:
- Audit log / leave-ledger **retention** policy — no mechanism found (§13.3)
- Backup/restore procedure — not covered by any agent, status unknown (§14.5)
- APM/metrics/observability beyond structured logs — not found, status unknown (§14.6)
- `ingestion` router — test coverage status unknown (no obviously-named test directory)
- Mobile test suite — 0% of it runs in CI; its "live" contract suite in particular has never been automated

---

## 5. Docs-vs-Code Conflicts Found

| Doc claim | Code reality | Source |
|---|---|---|
| `docs/architecture/04_Background_Job_Architecture.md` lists "Outbox sweep" and "Attendance lock" as implemented background jobs | Neither exists as a Celery task; explicitly flagged as not-yet-built in `celery_app.py` comments | Backend agent |
| `docs/product/VERSION_1_ROADMAP.md` row 6 — "Notifications engine" | No such module exists; email is per-domain/ad-hoc via a shared sender protocol, by design as a stand-in | Backend + Jobs agents |
| `tests/security/test_rls_runtime_role.py` docstring — "the only existing background task (`health.ping`) touches no database at all; there is nothing to verify" | False as of now — leave/attendance/employee Celery tasks all touch RLS-protected tables via `session_scope(company_id=...)`, using the same GUC mechanism as the request path but with **no background-task-specific RLS test coverage renewed** | DB/RLS agent |
| `docs/security/` (Auth_Architecture.md, single file) | Likely stale relative to actual implementation (refresh-cookie SEC-06, lockout, reuse-detection) — not line-by-line diffed this pass | DB/RLS agent |
| Memory: "Stitch retheme... all 54 screens done... changes still uncommitted" | Not independently verified visually in this pass — flagged, not confirmed or denied | Frontend agent |
| Attendance frontend assumption (none stated, but worth guarding against in planning) | Attendance Reports panel has an explicit in-code comment disclaiming export capability entirely — any test plan assuming CSV/PDF export for attendance would be testing a feature that doesn't exist | Frontend agent |

---

## 6. Proposed Phased Execution Plan (not yet started)

This is sequencing guidance for *writing and running* new/expanded tests later — nothing below has been executed.

**Phase 0 — Foundation confirmation** (lowest risk, highest leverage if wrong)
- Re-run and extend `test_rls_runtime_role.py` to explicitly cover each Celery task's `session_scope` path per domain (closing the stale-docstring gap in §5).
- Add a direct test for the `employee_import` mid-batch-commit RLS reset risk (`service.py:549`).
- Confirm/establish test coverage for the `ingestion` router (currently unknown).

**Phase 1 — Auth / RBAC / cross-tenant boundary**
- Consolidate the diffuse RBAC coverage into one explicit cross-module permission × data-scope matrix (building on `test_route_authorization_matrix.py`) covering all 5 data-scope levels × every permission-gated route category found in §1 (sections 2–5).
- Journeys B.10, C.11–12, D.22, E.23–26 from §2.

**Phase 2 — Core record-keeping (Org structure + Employee)**
- Close the frontend page-test gap on Employees admin pages (zero coverage currently).
- Journeys D.14–15, D.17.

**Phase 3 — Attendance (largest single domain)**
- Add a real (not faked) integration test for at least the backend half of the face-punch round-trip against a Luxand sandbox/mock server, since current coverage fakes the repository entirely on both mobile and backend test suites.
- Journeys B.5–6, C.13, F.27–28.

**Phase 4 — Leave**
- Close the frontend page-test gap (almost nonexistent) and raise backend unit-test depth (currently thin at 20 vs. 232 integration tests).
- Journeys B.7–8, D.19.

**Phase 5 — Payroll** (highest business risk, lowest relative coverage)
- Treat the ten carried-forward residual risk areas (§1 item 8.10) as the literal test backlog for this phase — do not re-mark any as resolved without new evidence.
- Journeys D.20–21.

**Phase 6 — Onboarding** (largest untested frontend surface)
- Build frontend page/wizard-step tests for the entire onboarding flow (currently zero on both the internal case-review page and all 9 public wizard steps).
- Journey A.1.

**Phase 7 — Cross-cutting: Notifications / Files / Audit**
- Confirm email failure is genuinely non-blocking end-to-end (by design) rather than silently dropping required communications.
- Confirm audit immutability holds through the API, not just at the DB-privilege layer (journey E.26).
- Establish retention/backup verification as a named, tracked gap if it can't be closed in this phase (§4).

**Phase 8 — Platform / Ops / CI**
- Decide whether to bring mobile tests into CI (currently 100% local-only) before relying on them for release gating.
- Deployment smoke test and DR drill remain explicitly out of this document's scope per the standing accepted-risk list (§4) — flag for separate planning, don't fold into functional test phases.

---

## 7. Open Questions for the Product/QA Lead (this session's holder) Before Execution Begins

1. Is "Employee Documents" (brief §4, item O) meant to be its own domain, or is routing it entirely through onboarding's document storage (as found in code) the intended permanent design?
2. Is "Rehire" (brief §4, item K) implemented as a distinct flow, or folded into standard employee creation with a prior-employment lookup? Not independently confirmed this pass.
3. Is the complete absence of in-app notifications and push notifications (mobile) an accepted product decision for this release, or a gap that should gate further testing until built?
4. Is the complete absence of geofencing/location-based punch validation on mobile an accepted product decision, or a requirement that was assumed implemented?
5. Should mobile tests be wired into CI before the execution phase begins, given they currently provide zero automated regression signal on every PR?
6. Does payroll have its own audit-action-code coverage comparable to other domains? The grep used in this pass used a pattern that may have missed payroll's action-string construction style — worth a direct, narrow follow-up before assuming a gap.
7. What is the intended retention/backup policy for `audit_log`, `leave_ledger`, and uploaded documents? No mechanism was found in code for any of them.
