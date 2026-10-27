# HRMS Production Readiness Checklist & Test Plan

Legend: ☐ open · P-level from the roadmap. "Evidence" = what must be attached before ticking.

## 1. Launch gates

| # | Gate | Pri | Evidence |
|---|---|---|---|
| 1 | Migration credential removed from runtime containers (R-01) | P1 | `docker compose exec api env` shows no `MIGRATIONS_DATABASE_URL`; compose diff |
| 2 | Off-server encrypted backups + WAL/PITR running (R-02) | P1 | bucket listing, `pgbackrest info` |
| 3 | Restore game day passed, RTO/RPO recorded (R-03) | P1 | filled table in DR doc |
| 4 | Generated tenant-isolation test across all RLS tables + allow-list for non-RLS tables (R-04) | P1 | CI run |
| 5 | Composite tenant FKs on core chains (R-05) | P1 | migration + tests |
| 6 | Explicit pool sizes, role-level `statement_timeout`, `idle_in_transaction_session_timeout`, Postgres config (R-06) | P1 | `SHOW` output on prod |
| 7 | Migration safety: lock_timeout, backup gate, schema snapshot test (R-07) | P1 | CI + runbook rehearsal |
| 8 | Release built from a tagged clean commit; 4 pending migrations applied on staging first | P1 | tag, staging log |
| 9 | Load tests L-1…L-6 pass on KVM-4-equivalent | P1 | report |
| 10 | Monitoring + alerts live and tested (§4) | P1 | fired test alert |
| 11 | `PII_MASTER_KEY` escrow verified by second custodian | P1 | signed check |
| 12 | Nginx rate limits, admin console network restriction, SSH/UFW hardened | P2 | config |
| 13 | Idempotent unique rule for key-less punches (F-08) | P2 | migration/test |
| 14 | Dependency & container scans clean of high/critical | P2 | reports |
| 15 | Legal: retention schedule, biometric (face) consent, third-party (Face++) data transfer | P1 | sign-off |

## 2. Automated test plan

| ID | Area | Test | Acceptance criterion | CI? |
|---|---|---|---|---|
| T-01 | Tenant isolation | For every table with `company_id` (catalog-driven): insert as tenant A under `hrms_app`, then select/update/delete as tenant B and with no GUC | 0 rows visible/affected; table not in allow-list ⇒ must have RLS FORCE | yes |
| T-02 | Tenant isolation (HTTP) | Replay every route in the authorization matrix with tenant B's token against tenant A's resource IDs, incl. documents/payslips/exports/search | 404/403 for 100 % | yes |
| T-03 | Header spoofing | Mismatched `X-Company-Id`, malformed UUID, missing header, on every route | 404, never a 500; no data | yes |
| T-04 | Concurrency | 50 parallel approvals of the same leave; 50 parallel punches same key; same-employee concurrent leave submits | exactly one effect; ledger balance consistent; no deadlock | yes (Postgres service) |
| T-05 | Concurrency | attendance period close vs leave approval | no frozen summary missing approved leave | yes |
| T-06 | Payroll | finalise twice / in parallel; change salary after finalise; adjustment after finalise | single run, identical output, finalised row immutable (trigger error) | yes |
| T-07 | Constraints | cross-tenant parent in child insert (after R-05) | FK violation | yes |
| T-08 | Schema | upgrade empty DB → single head; schema snapshot equals; `hrms_app` grants test | pass | yes |
| T-09 | Migration failure | inject failing revision | DB remains at previous revision | yes |
| T-10 | Connections | pool exhaustion test | clean 503 within timeout; recovery | yes |
| T-11 | Workers | kill worker mid-task (acks_late tasks, import); beat restart | no duplicate effects; import resumable or fails closed | nightly |
| T-12 | Mid-request commit | each service with `session.commit()` followed by reads | reads still tenant-scoped & non-empty (after_begin hook) | yes |
| T-13 | Security | ZAP baseline on staging, `pip-audit`, `npm audit`, Trivy | no high/critical open | CI weekly |
| T-14 | Backup | restore latest backup to scratch, run T-01 + smoke | pass | weekly cron |
| T-15 | Deployment | rehearse runbook §B including rollback | timings recorded | pre-launch |
| T-16 | Load/soak | L-1…L-6 | see capacity plan | pre-launch |

Never run destructive or load tests against production; use staging restored from anonymised data.

## 3. Security checks

* No secrets in Git (`git log -p -S` scan with gitleaks), images (`docker history`), frontend bundle (`NEXT_PUBLIC_*` review), or logs (redaction tests exist).
* `hrms_app` is NOSUPERUSER/NOBYPASSRLS in prod (`SELECT rolsuper, rolbypassrls`).
* Postgres/Redis/MinIO reachable only from the docker network: from outside `nmap -p 5432,6379,9000,9001 <ip>` shows closed.
* Presigned URL TTL and `attachment` disposition verified for a payslip and a document.

## 4. Monitoring & alert proposals (tune after 2 weeks of baseline)

| Signal | Warn | Page |
|---|---|---|
| CPU / load | > 70 % 15 min | > 90 % 10 min |
| RAM available / swap | < 15 % / any swap-in | OOM kill |
| Disk | 70 % | 85 % or < 7 days to full |
| Postgres up / connections | – / > 70 % | down / > 90 % |
| Slow queries (>500 ms) per min | > 20 | – (investigate) |
| Lock waits > 5 s, idle-in-tx > 60 s | any | > 10 in 5 min |
| API 5xx rate | > 1 % 5 min | > 5 % 5 min |
| API p95 latency | > 500 ms 10 min | > 2 s 5 min |
| Celery queue wait / failures | > 60 s / any failure | queue stalled 10 min |
| Beat heartbeat | – | no tick 15 min |
| TLS expiry | 21 d | 7 d |
| Backup success age / WAL lag | > 26 h / > 10 min | > 48 h / > 30 min |
| Container restarts | 2 in 1 h | 5 in 1 h |
Existing assets: Prometheus metrics (`core/observability`), `docker-compose.monitoring.yml`, `infra/monitoring/hrms_monitor.sh`, `/health/ready`.
