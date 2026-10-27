# HRMS Database Performance & Concurrency Audit

Evidence: [REPO] code, [DEV-DB] catalog of an **empty** dev database. Because the dev DB has no rows, **no recommendation below is validated by a query plan**; every index proposal is marked *needs EXPLAIN (ANALYZE, BUFFERS) on representative data* (see §6 for the data-generation approach).

## 1. Index inventory summary [DEV-DB]

* 382 indexes, 23 MB total on empty tables (all empty), so size/bloat is unknown.
* Pattern: nearly every tenant table has **both** a standalone `*_company_id_idx (company_id)` and one or more composites that start with `company_id` (e.g. `attendance_day_company_id_idx` + `attendance_day_employee_date_idx (company_id, employee_id, attendance_date DESC)` + `attendance_day_company_date_status_idx`). The standalone index is redundant for reads (prefix of the composites) and adds write amplification and WAL.
* Exact duplicate: `attendance_day_unique (company_id, employee_id, attendance_date)` and `attendance_day_employee_date_idx (company_id, employee_id, attendance_date DESC)` – btree can scan either direction, so one is redundant (keep the UNIQUE one). [catalog query over `pg_index` found this as the only exact duplicate]
* Good partial indexes: `employee_company_status_idx … WHERE deleted_at IS NULL`, regularization "one SUBMITTED per day", ledger idempotency indexes, `punch_company_idempotency_key_idx`.
* GIN on `employee.custom_fields` (JSONB) – verify it is actually queried; otherwise drop (write cost on every employee update).

## 2. Findings

| ID | Pri | Type | Finding / evidence | Recommendation | Validate |
|---|---|---|---|---|---|
| P-01 | P2 | C | ~100 redundant single-column `company_id` indexes (e.g. `leave_ledger_company_id_idx`, `punch_company_id_idx`, `employment_company_id_idx`) | Drop where a composite leads with `company_id`. Use `DROP INDEX CONCURRENTLY` in a non-transactional migration | `pg_stat_user_indexes.idx_scan` = 0 after a representative week on staging |
| P-02 | P2 | C | `attendance_day_employee_date_idx` duplicates `attendance_day_unique` | Drop the non-unique one | – |
| P-03 | P2 | R | `leave_application` has only `(company_id)` and `(company_id, employee_id)`. The approver inbox (status filter), date-overlap checks and calendars have no supporting index | Candidate `(company_id, status, created_at DESC)` and `(company_id, employee_id, start_date, end_date)` – check actual predicates in `leave/repository.py` first | EXPLAIN on 1M-row staging set |
| P-04 | P2 | R | `session` / `refresh_token` have only `user_id` and token-hash indexes; no index on expiry/revoked columns and no pruning job was found | Add scheduled purge of expired/revoked rows (Celery beat) and, if purged by date, an index on `expires_at` | table growth projection (60 logins/employee/yr) |
| P-05 | P2 | C | Unbounded lists: 128 `.all()` result fetches vs 32 `.limit(` uses in `modules/*/repository.py`. Recent commit `463b00d` added "bounded lists" for attendance/account_invite (`test_bounded_list_pagination.py`), others unaudited | Inventory every list endpoint; enforce server-side max page size (≤200) and keyset pagination for `punch`, `attendance_day`, `audit_log`, `pay_run_line` | grep + per-endpoint test with 10k rows |
| P-06 | P2 | R | Offset pagination on growth tables (`audit_log`, `punch`) degrades linearly | Keyset on `(company_id, occurred_at DESC, id)` — index already exists for audit_log | EXPLAIN |
| P-07 | P2 | R | N+1 risk: services such as `attendance/service.py` (6.8k lines), `employee/service.py` (3.8k), `payroll/service.py` (3.9k) iterate employees and call repositories per employee. Not proven; payroll compute is batched per run (`payroll/engine.py`) | Enable `sqlalchemy` query-count assertions in integration tests (fail >N queries per endpoint); `db_metrics.py` already counts queries | request-level query histogram on staging |
| P-08 | P3 | R | `pay_run_employee.snapshot` / `payslip_details` JSONB per employee per month: 50k employees ≈ 600k rows/yr × ~10–30 KB ⇒ 6–18 GB/yr TOAST; `pay_run_line` ≈ 15 rows/employee-month ⇒ 9M rows/yr at growth tier | Partition `pay_run_line` / `punch` by month or archive after 24 months (only at Growth tier) | storage projection §5 |
| P-09 | P2 | C | No role- or DB-level `statement_timeout` / `idle_in_transaction_session_timeout` (dev default 0). Timeouts are applied per operation only in attendance (`core/db/timeouts.py`, `attendance_statement_timeout_ms=30000`) | Set on role: `ALTER ROLE hrms_app SET statement_timeout='30s'; … idle_in_transaction_session_timeout='60s'; lock_timeout='10s'` (raise per-job for import/payroll via `SET LOCAL`) | CI test: long query is cancelled |
| P-10 | P1 | C | Connection budget is implicit: SQLAlchemy defaults (pool 5 + overflow 10 = 15 per process, `pool_pre_ping=True`; no `pool_size` set, `core/db/session.py:25-36`), gunicorn 2 workers, Celery concurrency 2, beat 1, plus Alembic. Postgres `max_connections` not configured in compose (default 100) | Set `pool_size`/`max_overflow` explicitly via settings and a budget (§3 of `HOSTINGER_SELF_HOSTING_ARCHITECTURE.md`); add `pool_timeout` | `test_db_wait_timeouts.py` exists – extend with saturation test |
| P-11 | P2 | R | `run_task` disposes the engine at the end of every Celery task (`session.py:~120`): each task pays connection setup; fan-out tasks that loop over many companies in a single task reuse one pool but per-company `session_scope` opens a new transaction (fine) | Acceptable at ≤1k companies; monitor task duration | task metrics |
| P-12 | P3 | R | Hourly `employee.run_termination_access_sweep`, `leave.run_comp_off_credit_sweep` and 2-minute `attendance.run_face_deletions` scan all ACTIVE/TRIAL companies each run | Add per-run duration metric; make sweeps query only companies with pending work | task metrics |
| P-13 | P2 | R | Postgres tuning is absent: no `postgresql.conf`/command flags in `docker-compose.prod.yml` ⇒ `shared_buffers=128MB`, `work_mem=4MB`, no `pg_stat_statements`, no `log_min_duration_statement`, no autovacuum tuning | See config in `HOSTINGER_SELF_HOSTING_ARCHITECTURE.md §4` | – |
| P-14 | P3 | R | `btree_gist` EXCLUDE indexes on `employment`, `employee_compensation`, `employee_assignment` are heavier to maintain; fine at this size | none | – |

## 3. Concurrency & transactions (G)

| Operation | Mechanism found | Assessment |
|---|---|---|
| Attendance punch submit | Idempotency key unique index; per-request transaction; mobile retry safe if key sent | OK with key; **F-08**: without key duplicates possible. Recommend unique `(company_id, employee_id, punch_time, direction)` or dedupe window |
| Leave submit/approve/cancel | Per-employee advisory lock `leave-dates:{company}:{employee}`; ledger append-only with partial uniques; shared period-close lock | Strong. Needs automated concurrent-approval test (T-04) |
| Leave balance | Derived from ledger (no mutable counter) | No lost-update class |
| Attendance period close vs leave change | Exclusive vs shared advisory lock, bounded wait | Strong |
| Payroll finalise | `payroll-finalise` per legal entity + shared period-close lock; immutability triggers | Strong; test T-06 |
| Pay adjustment | Leaf lock `pay-adjustment` | OK |
| Onboarding case per e-mail | Leaf advisory lock `onboarding-case-email` + partial unique `20261027091000` | OK |
| Beat/scheduled jobs | Single `beat` (documented "never scale"); tasks idempotent; `leave/tasks.py:55-56` sets `acks_late` + `reject_on_worker_lost`; other task modules not confirmed (G5) | Add Redis-visibility-timeout config and a per-company advisory lock inside each sweep so a double beat or retried task cannot overlap (P2) |
| Employee import | `process_batch`, `time_limit=3600`, **no automatic retry**, multiple mid-task commits (`employee_import/service.py:177-619`) | A worker kill mid-batch leaves a partially imported batch; confirm resume/rollback semantics (U) |
| Multi-statement partial commit | Mid-request `session.commit()` calls listed in the tenant matrix caveat 1 mean those operations are **not atomic with the rest of their request** | Review each for intended semantics (P2) |
| Isolation level | Default READ COMMITTED; correctness relies on locks and unique constraints, not SERIALIZABLE | Appropriate; do not raise globally |

## 4. Query-pattern coverage vs required filters

| Filter | Supporting index [DEV-DB] | Verdict |
|---|---|---|
| tenant | all via composites | OK |
| employee + attendance date | `attendance_day_unique`, `punch_employee_punch_time_idx` | OK |
| attendance date range per company/status | `attendance_day_company_date_status_idx` | OK |
| leave status | none | P-03 |
| payroll period | `pay_run_entity_month_uq`; `pay_run_employee_uq` | OK |
| department/branch | `employee_assignment_current_idx`, `…_manager_idx`; branch/department filters via assignment join | Verify with EXPLAIN |
| email/login | `user_email_key`, `user_phone_key` | OK |
| subscription status | `subscription` indexes not examined | U |
| created/updated timestamps | `audit_log_company_occurred_idx` only | OK for audit; others unsorted |

## 5. Data-volume hypotheses (to be validated)

| Table | Pilot (200 emp) | Early (5k) | Growth (50k) | Basis |
|---|---|---|---|---|
| `punch` | 200×2×26×12 ≈ 125k/yr | 3.1M/yr | 31M/yr | 2 punches/day, 26 days |
| `attendance_day` | 62k/yr | 1.6M/yr | 15.6M/yr | 1 row/emp/day (~310 d) |
| `leave_ledger` | ~5k/yr | ~125k/yr | ~1.2M/yr | ~2 entries/emp/month |
| `pay_run_line` | 36k/yr | 0.9M/yr | 9M/yr | ~15 lines × 12 months |
| `audit_log` | ~100k/yr | ~2.5M/yr | ~25M/yr | ~40 writes/emp/yr (assumption) |

These are order-of-magnitude assumptions. Growth tier warrants monthly partitioning of `punch` and `audit_log`; Pilot and Early do not.

## 6. How to validate

1. Restore a staging DB; generate synthetic data with a seed script for the Early and Growth tiers (companies, employees, 12 months of punches/days/ledger/pay runs) using the existing `scripts/seed.py` as a base.
2. Enable `pg_stat_statements`, `auto_explain` (log_min_duration 200 ms), run the k6/Locust scenarios in the capacity plan.
3. For each candidate index: `EXPLAIN (ANALYZE, BUFFERS)` before/after; accept only if p95 improves and write overhead is acceptable.
4. After one week: `SELECT * FROM pg_stat_user_indexes WHERE idx_scan=0` to confirm redundant drops.
