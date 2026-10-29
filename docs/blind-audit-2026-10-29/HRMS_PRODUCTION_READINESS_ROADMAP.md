# HRMS Production Readiness Roadmap

Findings referenced by ID; full evidence in the companion reports. **Nothing here has been implemented.** Effort: S ≤ 1 day, M ≤ 1 week, L ≤ 2 weeks, XL > 2 weeks.

## 1. Prioritised findings
| ID | Sev | Conf. | Title | Effort | Depends on |
|---|---|---|---|---|---|
| — | P0 | — | **None confirmed** within covered scope | | |
| F-01 | P1 | confirmed design / probable impact | Test suite bypasses RLS; runtime-role coverage limited to 4 tests | M–L | – (do first) |
| F-02 | P1 | probable | `employee_import` request-path commit drops RLS GUC before RLS-table update; class audit of ~20 commit sites (F-30) | S + M | F-01 (to prove) |
| F-03 | P1 | confirmed schema | Only 4 composite tenant FKs; cross-tenant parent links not DB-prevented | L (staged) | F-01 |
| F-19 | P1-process | confirmed | Dirty tree; head migration untracked | S | – |
| F-05 | P2 | confirmed | RLS GUC set from unverified header before auth | S | F-01 |
| F-06 | P2 | needs live check | ~10 tenant-keyed tables without RLS | S (verify) / M | live DB |
| F-08a-d | P2 | confirmed/probable | Early-ack tasks; beat state in `/tmp`; no catch-up; single schedule TZ | M | – |
| F-09 | P2 | confirmed | Redis without auth | S | – |
| F-10 | P2 | confirmed | Append-only only on 3 tables | S | – |
| F-11 | P2 | confirmed | ORM has no constraints; no drift check | M | – |
| F-12 | P2 | confirmed | S3 delete before DB delete | S | – |
| F-07 | P2 | needs validation | ≥6 DB round trips/request before business logic | M | profiling |
| F-13a | P2 | confirmed | Access token in `localStorage` | M | – |
| F-14/F-31/F-32 | P2 | confirmed | Testability, CI gaps (drift, audit, restore) | M | – |
| F-15 | P2 | confirmed | 3.5–6.9k-line services; weak import contracts | XL (incremental) | tests |
| F-20/21/22 | P2 | unverified | Migration rollback/restore rehearsals; `ALTER TYPE` on populated tables | M | – |
| F-23/F-28/F-29/F-25 | P2 | mixed | Silent GUC no-op; unverified rate limits; export size caps; tenant timezone source | S–M | – |
| F-04/F-16/F-17/F-18/F-24/F-26/F-27 | P3 | confirmed | f-string SQL (constants), floating tags, repo clutter, dump file, dev password, vestigial route, stale API docs | S each | – |

## 2. Remediation order and phases
**Phase 0 — Establish truth (≈1 week; no behaviour change)**
1. Commit/clean tree (F-19). 2. Bring up a *disposable* stack, run the full suite as today, record baseline. 3. Run the suite with the app engine connected as `hrms_app` and a separate admin engine for fixtures (F-01); triage every failure — each is either a latent RLS bug (like F-02) or a fixture issue. 4. On the migrated disposable DB, query `pg_class`, `pg_roles`, `pg_constraint`, `pg_indexes`; diff against this audit's inventory (F-06, F-11).

**Phase 1 — Pilot blockers (≈1–2 weeks)**
F-02 fix + sweep of commit sites (F-30); F-05; Redis auth (F-09); restore drill + pre-migration backup step (F-22/F-32); decide F-06 per table; `acks_late` for idempotent tasks and beat watermark/catch-up (F-08).

**Phase 2 — Integrity hardening (before general availability)**
Composite `(company_id, id)` FKs, staged `NOT VALID` → `VALIDATE` (F-03), starting with payroll/leave/punch; extend append-only revokes (F-10); ORM↔DB drift test and `alembic check` in CI (F-11); S3 post-commit deletion (F-12); CI dependency/image audit and pinned images (F-16/F-31).

**Phase 3 — Scale & maintainability**
Measure p95 and reduce per-request auth queries (F-07); split large services under `import-linter` independence contracts (F-15); tenant-timezone policy (F-25); front-end token handling (F-13a); remove clutter and stale docs (F-17/F-26/F-27).

## 3. Fix dependencies
F-01 → (F-02, F-03, F-05) because those fixes need the runtime-role suite to prove them. F-03 depends on a live duplicate/orphan scan (a cross-tenant mismatch found at `VALIDATE` time must be investigated, not auto-fixed). F-08 beat catch-up needs per-task idempotency confirmation first. F-15 needs the test net from F-01.

## 4. Required regression tests
Whole-suite-as-`hrms_app`; per-write-endpoint "foreign tenant id → 404, zero writes"; commit-then-query GUC test per commit site; ORM-vs-catalog drift; concurrent finalise vs attendance reopen; duplicate punch/accrual/pay-run attempts; missed-beat catch-up; restore-from-backup smoke test.

## 5. Migration-safety considerations
Use `ADD CONSTRAINT … NOT VALID` then `VALIDATE CONSTRAINT` (no long exclusive lock); create indexes `CONCURRENTLY` outside the transaction; set `lock_timeout`; take a backup immediately before `migrate`; treat downgrade as unsupported for data migrations and rely on restore; never deploy from an uncommitted migration.

## 6. Criteria to approve production readiness
1. Full backend suite passes as `hrms_app` on a clean disposable stack, in CI.
2. Live schema check shows RLS ENABLE+FORCE on all intended tenant tables; runtime role is NOSUPERUSER/NOBYPASSRLS; every exception is documented.
3. No unresolved P0/P1; every P2 either fixed or accepted in writing.
4. Composite tenant FKs on payroll, leave, attendance, employee children; zero cross-tenant mismatches at validation.
5. Restore from a production-style backup demonstrated, with RTO/RPO recorded.
6. Redis authenticated; images pinned; dependency audit green; secrets guard verified in the prod environment.
7. Payroll engine and attendance calculation independently reviewed against client-signed rules (**this audit did not do that**).
8. Deployed artifact == tagged commit (clean tree).

## 7. Recommended implementation order (summary)
F-19 → Phase-0 baseline → F-01 → F-02/F-30 → F-05 → F-09 → F-22/F-32 → F-06 → F-08 → F-03 → F-10/F-11/F-12 → CI hardening → F-07/F-15/F-25.
