# HRMS Audit — Executive Summary & Remediation Roadmap

Read-only audit, 2026-10-27. Repository working tree + read-only catalog queries on an **empty** dev database (4 migrations behind). No production database was available; nothing was changed. Companion documents: `HRMS_ARCHITECTURE_INVENTORY.md`, `HRMS_DATABASE_SCHEMA_AUDIT.md`, `HRMS_TENANT_ISOLATION_MATRIX.md`, `HRMS_DATABASE_PERFORMANCE_AUDIT.md`, `HRMS_MIGRATION_SAFETY_AUDIT.md`, and `docs/deployment/*`.

## 1. Executive summary

**Is the database design production-ready?** The *design* is notably strong: 94 tables with FORCE row-level security fail-closed on an unset tenant, a non-bypass runtime role asserted in CI, integer-minor-unit money (no floats), `timestamptz` everywhere, effective-dating exclusion constraints, ledger-based leave balances with idempotency indexes, append-only audit/ledger grants, immutability triggers on finalised payroll, documented advisory-lock ordering, argon2 passwords, AES-GCM PII. I found **no confirmed cross-tenant data exposure and no P0 defect**. The *operation* is not production-ready: backups are local, unencrypted, untested and without PITR; the runtime containers hold the schema-owner credential that bypasses RLS; there is no DB connection/timeout budget; tenant integrity beyond RLS rests on application code; and there is no load-test or restore evidence.

**Most serious integrity / isolation risks**
1. F-01 owner credential (`MIGRATIONS_DATABASE_URL`) injected into API/worker/beat → one RCE defeats RLS.
2. F-03 zero composite tenant FKs → a service bug can link records across companies and the database will accept it (RLS is read/own-row only).
3. F-04/F-05/F-06 tenant-bearing tables outside RLS, transaction-local GUC lost after mid-request commits, GUC first set from unverified header — all currently fail-closed or mitigated, but unproven by per-table tests (no catalog-driven isolation test exists).
4. F-02 backups: single point of failure on the VPS; `PII_MASTER_KEY` loss is unrecoverable.
5. F-08 raw `punch` evidence is mutable by the app role and key-less duplicate punches are accepted.

**Recommended initial Hostinger configuration**: KVM 4 (4 vCPU / 16 GB / 200 GB NVMe) single host with the existing Compose stack, Postgres 16 tuned and given ≈5 GB, documents in an external private S3 bucket, off-server encrypted pgBackRest PITR, KVM 2 as staging. KVM 8 or a DB split only when the triggers in the scaling plan fire.

**Estimated recurring cost** (Early production): ≈ $20–60/month — KVM 4 ≈ $13 promo (24-month term) rising to ≈ $29 at renewal per third-party reviews of Hostinger pricing (unverified on Hostinger's own page), plus assumed $1–10 backup/object storage, $0–20 email, ≈$1–2 domain. Face++ usage not estimated.

### Recommendation

**Can this HRMS safely launch on a single Hostinger KVM 4 VPS?** *Not yet; conditionally yes for a Pilot after the P1 items.* For ≤10 companies / ≈200 employees, KVM 4 is ample. Before any real customer data: complete R-01 through R-07 below (≈ 10–14 engineer-days), pass the restore game day and load tests L-1…L-6, and build from a clean tagged commit (the tree currently has 278 uncommitted changes). Early production (100 companies / 5,000 employees) on one KVM 4 is *plausible but unproven* until load-tested; Growth (1,000 / 50,000) requires a multi-host design.

### Next five implementation steps (priority order)
1. R-01 Split the migration credential out of runtime env (0.5 d).
2. R-02 + R-03 Off-server encrypted backups with WAL/PITR, then the restore game day (3–4 d).
3. R-04 Catalog-driven tenant-isolation test + RLS allow-list in CI; R-08 transaction-start GUC hook (2 d).
4. R-06 Postgres config, explicit pool sizes, role-level timeouts (1 d) and R-07 migration guard rails (2 d).
5. R-05 Composite tenant FKs for the core chains, then load tests (3–4 d + 2 d).

## 2. Findings register (confirmed defects separated from risks)

Type: **C** confirmed from code/catalog · **R** potential risk · **U** unverified. Effort in engineer-days. "Downtime" = needs an outage window.

| ID | Pri | Type | Finding | Evidence | Fix | Risk / compat | Tests | Effort | Depends | Downtime |
|---|---|---|---|---|---|---|---|---|---|---|
| R-01 / F-01 | P1 | C | Owner credential in runtime env | `docker-compose.prod.yml` `env_file` on api/worker/beat/migrate; `env/.env.production.example:33`; contradicts `alembic/env.py` comment | `.env.migrate` only for `migrate`; remove var from `.env.production` | none | env grep test | 0.5 | – | No |
| R-02 / F-02 | P1 | C | Backups local, unencrypted, no PITR, no scheduler | `infra/backup/pg_backup.sh` | pgBackRest/WAL-G to off-server S3, `age`-encrypted dumps, systemd timers, alerts | needs `wal_level`, `archive_mode` ⇒ one Postgres restart | T-14 | 3 | bucket account | Brief restart |
| R-03 | P1 | U | No restore ever proven | `DISASTER_RECOVERY.md` untested claims | Game day, record RTO/RPO | – | T-14/T-15 | 1 | R-02 | No |
| R-04 / F-04,F-05 | P1 | C | No generated per-table isolation test; non-RLS tenant tables untested | only `employee`/`audit_log` + module tests | catalog-driven T-01/T-02 + allow-list of 18 non-RLS tables | none | T-01,T-02,T-03 | 2 | – | No |
| R-05 / F-03 | P1 | C | 0 composite tenant FKs | catalog; `20261027092000` covers `attendance_day` only | `UNIQUE (id, company_id)` on parents; composite FKs `NOT VALID` → `VALIDATE` for employee-child chains, leave, payroll | long validation on big tables; do while small | T-07 | 4 | – | No |
| R-06 / P-09,P-10,P-13 | P1 | C | No pool budget, no role timeouts, default Postgres config | `core/db/session.py:25-36`; compose lacks conf; dev `statement_timeout=0` | settings for `pool_size/max_overflow/pool_timeout`; `ALTER ROLE hrms_app SET …`; conf fragment | `statement_timeout` may cancel long imports ⇒ `SET LOCAL` in jobs | T-10 | 1.5 | – | Restart |
| R-07 / M-01,M-02,M-04,M-05 | P1 | C | Migration guard rails missing | `alembic/env.py` | lock_timeout, backup gate, schema snapshot, previous-tag upgrade job, single-head check | – | T-08,T-09 | 3 | – | No |
| R-08 / F-05 | P2 | R | Mid-request commits lose GUC | list in tenant matrix | SQLAlchemy `after_begin` re-sets GUC from ContextVar | low | T-12 | 1 | – | No |
| R-09 / F-06 | P2 | U | GUC first set from raw header | `tenancy/middleware.py:23-26` | verify no RLS read before `get_tenant_context`; defer GUC until verified | low | T-03 | 0.5 | – | No |
| R-10 / F-08 | P2 | C | `punch` mutable; key-less duplicates | grants, indexes | revoke UPDATE/DELETE (or trigger), unique `(company_id, employee_id, punch_time, direction)` | existing duplicates block constraint — dedupe first | T-04 | 1.5 | – | No |
| R-11 / F-17 | P2 | C | App role has full DML on `encryption_keys` | grants | restrict to SELECT/INSERT, rotate via owner path | rotation tooling | grants test | 0.5 | – | No |
| R-12 / P-01,P-02 | P2 | C | ~100 redundant indexes | catalog | drop after 1-week `idx_scan` evidence; `CONCURRENTLY` | verify no ORM hint relies on them | EXPLAIN | 1 | staging data | No |
| R-13 / P-03,P-05,P-06 | P2 | R | Missing leave-status index; unbounded `.all()` lists (128 vs 32 limits) | repositories | list inventory, max page size, keyset, index after EXPLAIN | API contract change for unpaginated lists | T-16 | 3 | load data | No |
| R-14 / P-04 | P2 | R | No session/refresh-token pruning | schema | beat job | – | unit | 0.5 | – | No |
| R-15 | P2 | R | Task safety: `acks_late` only in leave tasks; import has no retry/resume | `leave/tasks.py:55-56`, `employee_import/tasks.py` | standardize task base class; per-company advisory lock in sweeps; import resume | – | T-11 | 2 | – | No |
| R-16 | P2 | R | Nginx has no rate limiting; admin console reachable publicly | `infra/nginx` | `limit_req`, Cloudflare Access/IP allow-list | – | smoke | 1 | – | No |
| R-17 / F-16 | P2 | U | Salary and face embeddings not field-encrypted | schema | decide; at minimum disk/backup encryption | – | – | decision | – | – |
| R-18 / F-11 | P1 | C | Release from uncommitted tree; dev DB behind | `git status`, `alembic_version` | tag clean commit; apply 4 pending revisions in staging | – | CI | 0.5 | – | No |
| R-19 | P3 | R | Floating images (`postgres:16-alpine`, `certbot:latest`, `pgsty/silo:latest` in dev) | compose | pin versions/digests | – | – | 0.5 | – | No |
| R-20 / P-08,P-14 | P3 | R | Growth-tier partitioning, PgBouncer, read replica, external monitoring | capacity plan | when triggers fire | – | – | 5+ | metrics | Possible |
| R-21 / F-14 | P3 | U | No erasure/anonymisation procedure | FK RESTRICT design | policy + tool | – | – | 3 | legal | No |
| R-22 | P3 | R | Per-currency support absent on `pay_run` | schema | only if non-INR needed | – | – | 1 | – | No |

## 3. Unverified assumptions (need live data or a human decision)
Query plans and index usefulness; table sizes/bloat; production Postgres/OS settings; Hostinger region, throttling policy, backup add-on and renewal terms on Hostinger's own page; presigned-URL TTL; behaviour of the 125 `downgrade()` bodies; whether `get_current_user` touches RLS tables early; import-batch crash semantics; legal retention periods and biometric consent.

## 4. Stop point
Per instructions, no schema, code, Docker or deployment file was modified; only Markdown under `docs/audit/` and `docs/deployment/` was added. **Awaiting your approval** before implementing any roadmap item. Suggested first batch on approval: R-01, R-06, R-04, R-08.
