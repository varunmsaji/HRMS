# HRMS Blind Vibe-Coding Audit — Executive Summary

Audit date: 2026-10-29 · Branch `main` · Mode: **read-only** (no code, schema, migration or config changes).
Companion reports are in this directory (`HRMS_*.md`). Finding IDs (`F-xx`) are shared across all reports.

## 1. How to read this audit (limits first)

| Could do | Could **not** do |
|---|---|
| Static review of models, 127 Alembic revisions, routers, services, core tenancy/auth/RBAC, Celery, Docker/Nginx/CI, frontend structure | Query the live database (the only DB URL in the root `.env` points at a different server/role and fails authentication; I did not guess credentials or touch the shared dev stack) |
| AST-built inventory of all **354** HTTP routes and **442** repository query functions | Run the test suite (the repo's isolation guard refused to run against the shared dev stack; I did not override it) |
| Parse the migration graph (127 revisions, single head, no dangling parents) | Measure query plans, index usage, load, or backup/restore |
| | Read every line: ~88.5k lines of Python, of which payroll engine, attendance calculation, leave accrual math, face engine and upload validators were **not** reviewed line-by-line |

**Therefore every "RLS is enabled on table X" statement is derived from migrations, not from `pg_class`.**

## 2. Overall readiness score: **6.5 / 10** (provisional)

Method: weighted judgement across 8 areas, each scored 0–10 from evidence only, capped by what could not be verified.

| Area | Weight | Score | Note |
|---|---|---|---|
| DB schema & integrity design | 20% | 8 | Integer minor-unit money, GiST no-overlap constraints, immutability triggers, partial-unique idempotency indexes, advisory locks with a documented order |
| Tenant isolation | 20% | 6 | Strong design (RLS FORCE + app `company_id` filters), but **proven under the real runtime role for only a few modules** (F-01) |
| AuthN / AuthZ | 15% | 8 | argon2, per-request session/membership/company checks, fresh RBAC lookup, fail-closed rate limit, hardened cookie |
| Business-logic consistency | 10% | 6 | Unverified for payroll/attendance math; very large service files |
| Background jobs | 10% | 6 | Idempotency indexes exist; `acks_late` only on leave tasks; beat has no catch-up |
| Tests & CI | 10% | 6 | Large suite, but nearly all of it bypasses RLS; no dependency-vuln scan / drift check |
| Ops / deploy | 10% | 7 | Good prod compose + nginx; Redis unauthenticated, floating tags |
| Frontend (quick) | 5% | 7 | Refresh token is HttpOnly; access token in localStorage |

Limitation: a score cannot exceed what was verifiable. A live-DB check plus a runtime-role test run could move it up ~1 point or down ~1 point.

## 3. Direct answers

* **Is the database design safe for production?** The *design* is notably mature. It is **not yet demonstrated safe**: live schema unverified, cross-tenant FK consistency is DB-enforced for only 4 relationships (F-03), and RLS-dependent behaviour is untested for most modules (F-01, F-02).
* **Tenant isolation: demonstrated or unverified?** *Partially demonstrated.* App-level scoping is consistent (394 of 442 repository query functions reference `company_id`; the other 48 are global identity/platform/plan code, reviewed). RLS enforcement under `hrms_app` is proven only by 4 tests (`tests/security/test_rls_runtime_role.py`) plus geofence RLS. **Remaining modules: unverified.**
* **Confirmed P0 found?** **No.** No confirmed cross-tenant exposure, auth bypass, or data-loss defect in the covered scope.
* **Block production launch?** **Yes, conditionally:** block *general* launch until F-01/F-02/F-03 are resolved or explicitly accepted. A controlled pilot is reasonable once the pilot items below are done.

## 4. Five most serious risks

1. **F-01 (P1, probable)** — The integration suite runs as SUPERUSER/BYPASSRLS, so RLS-dependent bugs in payroll, leave, attendance, onboarding, organisation are invisible to tests.
2. **F-02 (P1, probable)** — `employee_import` enqueue-failure path queries an RLS table after a mid-request `commit()` without restoring `app.company_id`; the covering test runs as superuser and cannot catch it.
3. **F-03 (P1, confirmed schema gap)** — Only 4 composite tenant FKs exist; every other cross-table reference is single-column, so the DB itself permits a row to point at another company's parent.
4. **F-08 (P2)** — Most Celery tasks use early-ack; beat schedule file in `/tmp` and no missed-run catch-up; one global schedule timezone.
5. **F-10 (P2)** — Only 3 tables are append-only for the runtime role; other action/history tables are mutable.

## 5. Confirmed vs. unverified

* **Confirmed (from code/migrations):** F-03, F-05, F-09, F-10, F-11, F-12, F-13, F-16, F-19, and the *test design* underlying F-01.
* **Probable (needs a run to confirm):** F-01 impact, F-02, F-08, F-07.
* **Unverified (could not examine):** live schema/RLS flags, index usage, payroll/attendance/leave math correctness, timezone behaviour, upload validators, backup restore, mobile API behaviour.

## 6. Before a pilot (must)
1. Run the full suite once on a disposable stack **with the app connected as `hrms_app`** and triage failures (F-01).
2. Fix/verify F-02 and audit every other mid-request `commit()` (list in the Concurrency report).
3. Query the live (disposable, migrated) DB for `pg_class.relrowsecurity/relforcerowsecurity`, `rolsuper/rolbypassrls`, and compare to the 10 no-RLS candidates (F-06).
4. Commit the working tree (187 files uncommitted incl. head migration `20261030090000`) so the audited state is the deployable state (F-19).
5. Add Redis `requirepass` (F-09); confirm backup **restore** once.

## 7. Can wait
F-07 per-request query count, F-14/F-15 module size & import contracts, F-16 pin floating tags, F-17 repo-root clutter, composite-FK rollout beyond payroll/leave/attendance.

## 8. Next ten engineering tasks
1. Run suite as `hrms_app` (disposable stack) · 2. Fix F-02 + audit all `commit()` sites · 3. Live-schema RLS/role verification · 4. Composite `(company_id, id)` FKs for payroll, leave, onboarding, employee children (staged, `NOT VALID` → `VALIDATE`) · 5. Cross-tenant negative tests per write endpoint accepting foreign IDs · 6. Extend append-only revokes · 7. `acks_late` + `reject_on_worker_lost` for non-idempotent-safe tasks; beat catch-up policy · 8. CI: `alembic check` drift, `pip-audit`, `npm audit`, pinned images · 9. Redis auth + TLS-to-broker decision · 10. Break up 3–7k-line service files behind import-linter *independence* contracts.

**No code changes will be made without your explicit approval.**
