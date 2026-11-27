# Reliability and capacity audit

Audit date: 2026-11-25. One `docker stats` sample and one public health sample. They are observations, not a load test.

## 1. Capacity snapshot

| Resource | Observation | Reading |
|---|---|---|
| RAM | 7.8 GiB, about 5.1 GiB available, swap 544 MiB of 4 GiB used | The box is not out of memory. Available memory includes cache |
| Worker container | 2.16 GiB (27.9% of host RAM), 0.07% CPU, 0 restarts, not OOM-killed | Largest HRMS process. Stable enough to run for three weeks. Too large to ignore on a shared 8 GB host |
| API | 270 MiB, 23.6% CPU in this sample | The sample was taken while the audit ran `docker exec` and health commands. Do not treat 24% as the idle baseline |
| Web | 88 MiB | Fine |
| Beat | 80 MiB | Fine |
| Postgres | 161 MiB, database 129 MB on `hrms_demo` | Fine for the current data size. `shared_buffers` 128 MB is the image default |
| Redis | 13 MiB container, 10.5 MB used by Redis | Fine. Uncapped |
| MinIO | 98 MiB | Fine |
| Hirico | Postgres 61 MiB, Redis 4 MiB, plus a host uvicorn whose RSS was not measured | Shares the same RAM and disk |
| Disk | 24 GiB of 96 GiB, 25% | Comfortable. Growth rate was not measured |
| Public latency | `/health/live` 5.6 s once, `/health/ready` 0.7 s once | Ready is the meaningful dependency check and it was fast. The slow live sample needs a second look before anyone calls the API slow. One sample can be a cold TLS path or a pause |

No request-rate, p99, or connection-count history exists, because Prometheus is not running. `docs/deployment/HRMS_CAPACITY_AND_SCALING_PLAN.md` discusses a larger plan and a KVM 4 shape. The current host has 8 GB, which matches a small KVM class. The plan's thresholds cannot be evaluated without metrics.

## 2. When to scale

| Trigger | Action that fits this system |
|---|---|
| Worker stays above 2.5 GiB or the host starts swapping hard | Measure which child holds the memory (`P9-01`) before buying RAM. Face models loaded in the worker are a likely resident cost, not yet proven |
| Available memory under 1 GiB for a day | Add RAM on the same VPS, or move Hirico. Do not add a second HRMS stack on this box |
| Postgres data past a few tens of GB, or `shared_buffers` and cache fighting the worker | A separate database VPS is then justified. At 129 MB it is not |
| API CPU sustained near one core with a real traffic baseline | Raise `GUNICORN_WORKERS` only after connections are counted. Default pool is SQLAlchemy's default (5 plus 10 overflow) per process, and `max_connections` is 100 |
| Queue depth unknown | Turn on Prometheus (`P5-01`) before adding workers |
| A second company with a hard isolation requirement | A second VPS, not Kubernetes |

Vertical scaling is the next step if memory pressure appears. A separate worker host is the step after that, and only if the API and the worker contend. A separate database host is not justified by today's size.

## 3. Background work

Source of truth: `apps/api/src/hrms/core/celery_app.py` and the running worker and Beat containers.

| Topic | State |
|---|---|
| Broker | Redis, same URL as the app cache |
| Queues | `default` and `reports_exports`. Worker command does not pass `-Q`, so it consumes the declared queues. This was a real bug once (comment PRA-04) and the code now declares both |
| Beat schedule | Leave accrual 01:00, comp-off credit hourly, comp-off expiry 01:30, year-end 02:00, attendance calculation 09:30, recalc every 5 minutes, termination sweep hourly, reminders 10:00, digests weekdays, face cleanup 03:15, face deletions every 2 minutes, email outbox every 60 seconds, scheduler heartbeat every 60 seconds |
| Time limits | Company tasks soft 1500 s / hard 1800 s. Fan-out soft 120 / hard 180 |
| Acknowledgement | `acks_late` and `reject_on_worker_lost` only for tasks listed as idempotent. Others must be listed in `NO_RETRY_TASKS` or a test fails. That test is in the repo. Whether every new task on `test` is classified was not re-run here. The running image is the November image, so it has the policy as of that build |
| Retries | Database connection errors, exponential backoff, max 3, for idempotent tasks |
| Duplicate Beat | One container. A second replica would double-fire. Compose does not set `deploy.replicas: 1` as a hard constraint. It is operational discipline |
| Schedule file | `/tmp/celerybeat-schedule`. Lost on recreate. Worst case is one extra idempotent run |
| Dead letter | No dead-letter queue. Failed tasks increment metrics and logs. They are not parked for replay |
| Idempotency | Claimed per task in comments and enforced by a registry test in the current tree. Side-effect tasks are excluded from auto-retry on purpose |
| Worker loss | Idempotent tasks are redelivered. Others can be lost if the worker dies after the broker acknowledged them |
| Missed schedules | Heartbeat plus the host monitor. Prometheus missed-job rules are not loaded |
| RQ | Not used |

Payroll, attendance calculation, and leave sweeps are Celery tasks in this design. Their correctness is an application concern. Operationally, a missed day is visible only through the monitor's log scrape and `job_health`, not through a business report that says "accrual did not run for company X". The Prometheus rules would say that, if they were running. The gap is `R-05` and `R-07`.

Imports use the `reports_exports` queue. A stuck import shows up as queue depth inside `job_health`. The threshold in the monitor is the script default. It was not printed from the last JSON report because the last run exited 0 and the unit discards stdout (`StandardOutput=null`).

## 4. Process reliability

| Process | If it crashes | If it hangs |
|---|---|---|
| API | Docker restarts it. Gunicorn recycles workers on timeout 60 s | Liveness health check fails after retries, then Docker restarts it |
| Worker | Docker restarts it. Idempotent tasks redeliver | `inspect ping` fails, then Docker restarts it |
| Beat | Docker restarts it | Nothing restarts it. Heartbeat age grows. Monitor should mail. Mail was not observed |
| Postgres | Docker restarts it. API readiness fails while it is down. API is not restarted for that, by design | `pg_isready` fails, Docker restarts it |
| Redis | Same pattern. AOF recovers committed writes | Ping fails, Docker restarts it |
| MinIO | Docker restarts it. API calls fail until it is back | TCP health check |
| Host nginx | systemd restarts a failed unit. A hung nginx is a host problem | Not separately health-checked beyond public HTTPS |
| Backup | Next hour retries. `OnFailure` should mail | `TimeoutStartSec` 45 min |

Three weeks with zero container restarts is a good sign. It is also why hang detection for Beat has never had to prove itself.

## 5. Risks specific to jobs

| ID | Risk |
|---|---|
| R-07 | A missed accrual or attendance run is a business failure that can look like a quiet night if the monitor's log pattern does not match the new task name. The monitor greps structured events. New event names need to be added there or they are invisible |
| R-03 | Worker memory at 2.16 GiB leaves less room for a backup's throwaway Postgres, which runs during the daily job. The daily job is succeeding, so today's overlap fits. It will not fit after CompreFace is enabled on this host |
| R-02 | Deploying a new worker beside an old Beat, or the reverse, can schedule tasks the other process does not know. The recreate must be one image |

## 6. Connection pooling

`get_engine` in `apps/api/src/hrms/core/db/session.py` sets `pool_pre_ping=True` and does not set `pool_size` or `max_overflow`. SQLAlchemy defaults apply per process. Two Gunicorn workers plus a Celery concurrency of 2 is on the order of a few dozen connections, under the server's `max_connections` of 100. No PgBouncer. Not needed at this size. Revisit when `GUNICORN_WORKERS` or concurrency is raised.

There is no `statement_timeout` on the engine. One attendance setting has a 30 second statement timeout in application settings (`attendance_statement_timeout_ms`). A runaway query can still hold a connection. Slow-query logging was not enabled in the inspected `SHOW` list. `log_min_duration_statement` was not queried. Status: missing as an observed setting.

## 7. What not to buy

Do not add a metrics vendor, a log vendor, and a second region in the same quarter. Disk, CPU, and data size do not show a capacity emergency. The worker's memory is the one number that should be explained before the next feature that loads a model into the worker.
