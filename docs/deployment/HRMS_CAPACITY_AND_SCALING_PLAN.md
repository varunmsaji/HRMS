# HRMS Capacity & Scaling Plan

**All numbers are hypotheses.** No load test or production telemetry exists. They exist to size a first test and to define triggers; replace them with measurements (see §4). Row-volume estimates are in `docs/audit/HRMS_DATABASE_PERFORMANCE_AUDIT.md §5`.

## 1. Workload assumptions

| Assumption | Value | Reason |
|---|---|---|
| Employees per company | 20 (Pilot) / 50 (Early) / 50 (Growth) | derived from the requested scenarios |
| Daily active users | 80 % of employees (punch), 10 % web portal | attendance app is the daily touchpoint |
| Punches per employee/day | 2 (in/out) concentrated in two 30-min windows (start/end of shift) | worst-case burst: 60 % of staff in 15 min |
| Mobile app API calls per active user per day | 15 | home, punch, history, leave |
| Web/HR admin calls | 300/day per HR user, 1 HR user per 50 employees | dashboards, approvals |
| Payroll | monthly, 1 run/company/month, run window of 2 days around month end; compute ≈ 0.05–0.2 s CPU per employee [guess] | |
| Documents | 8 documents/employee at 1 MB avg at onboarding + 1 payslip PDF/month 100 KB | |
| Face verification | optional; if on, 2 verifications/day/employee; CPU heavy | |

## 2. Scenarios

| | Pilot | Early production | Growth |
|---|---|---|---|
| Companies / employees | 10 / 200 | 100 / 5,000 | 1,000 / 50,000 |
| Daily active users | 160 | 4,000 | 40,000 |
| Daily API requests (≈15/user + admin) | ~3k | ~70k | ~700k |
| Peak punch burst | 120 in 15 min ⇒ 0.13 req/s | 3,000 in 15 min ⇒ 3.3 req/s | 30,000 in 15 min ⇒ **33 req/s** (+ 5× retry factor ⇒ ≈ 100 req/s) |
| Sustained peak API | < 1 req/s | ≈ 10 req/s | ≈ 100–150 req/s |
| Payroll month-end | trivial | 5k employees in minutes; DB write ≈ 80k `pay_run_line` rows | 50k employees ≈ 750k lines; run per company in parallel; ~30–90 min total if serialised [guess] |
| DB size after 1 yr | < 2 GB | 10–25 GB | 150–300 GB (partitioning, archive) |
| Documents after 1 yr | 2 GB | 40–60 GB | 400–600 GB |
| Redis | negligible | < 100 MB | < 500 MB |
| Suggested infrastructure | KVM 2 (or KVM 4 with headroom) | **KVM 4** single host | KVM 8 DB + separate 2×KVM 4 API/workers, external object storage, external monitoring, evaluate managed Postgres/read replica |
| Likely bottlenecks | none; single-host fragility, backups | punch-window bursts hitting 3 API workers × pool; Celery daily 09:30 calculation and hourly sweeps competing with API; shared host CPU throttling | DB write amplification (redundant indexes, audit_log), `punch`/`attendance_day` size, Face provider throughput, payroll compute, connection count (needs PgBouncer transaction mode), mobile retry storms |

Growth is **not** supportable on a single VPS; Early production on KVM 4 is plausible only if the load test passes (§4).

## 3. Scale-out triggers (sustained 15 min unless noted)

| Metric | Threshold | Action |
|---|---|---|
| API CPU | > 70 % | add API workers (if RAM) then a 2nd API host |
| Host load / CPU steal | > cores for 15 min, or Hostinger throttling observed | move to KVM 8 or split |
| Postgres CPU | > 60 % | dedicated DB host (KVM 8), tune indexes first |
| Postgres cache hit | < 99 % and RAM free | raise `shared_buffers` / bigger RAM |
| `pg_stat_activity` connections | > 70 of `max_connections` | reduce pool, add PgBouncer (transaction mode; GUC is transaction-local so compatible) |
| p95 API latency | > 500 ms read / > 1 s write | profile queries (`pg_stat_statements`), index, scale |
| Celery queue wait | > 60 s for `default`, > 10 min for `reports_exports` | add worker concurrency / dedicated worker host |
| Disk | > 70 % used or fill-in < 30 days | grow volume / archive / move documents |
| WAL archive lag | > 10 min | fix archive target before anything else |
| Swap in use / OOM kills | any OOM kill | lower limits or upgrade |
| Redis memory | > 70 % of maxmemory | increase / investigate backlog |

## 4. Load-test plan (before launch)

Tool: k6 or Locust against a staging stack that mirrors KVM 4 and a synthetic dataset (Early tier: 100 companies, 5,000 employees, 12 months history).

| Scenario | Profile | Pass criteria |
|---|---|---|
| L-1 punch burst | 3,000 punches in 15 min, 20 % retries with same idempotency key | 0 duplicate punches; p95 < 500 ms; error < 0.5 %; DB connections < 70 |
| L-2 mixed day | 10 req/s for 2 h (punch 40 %, history 30 %, leave 15 %, admin lists 15 %) | p95 < 500 ms, CPU < 70 % |
| L-3 month-end payroll | 50 companies × 100 employees finalise concurrently while L-2 runs | no deadlocks/lock timeouts; API p95 < 1 s; payroll idempotent on rerun |
| L-4 soak | 24 h at 50 % of L-2 with beat jobs | no memory growth > 10 %, no connection leak, disk growth as predicted |
| L-5 failure | kill worker mid-import; restart postgres; redis restart | jobs resume/idempotent, API recovers < 2 min |
| L-6 pool exhaustion | 200 concurrent slow requests | fast `503`, not hang; recovery after load |

Record results and update this document; promote hypotheses to measured numbers.
