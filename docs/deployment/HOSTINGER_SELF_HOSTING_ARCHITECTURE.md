# Hostinger Self-Hosting Architecture (plan only – nothing deployed)

Builds on what already exists: `docker-compose.prod.yml`, `infra/nginx`, `infra/backup`, `docs/deployment/PRODUCTION_DEPLOYMENT.md` and `DISASTER_RECOVERY.md`. This plan lists what to **keep** and what to **change**. Facts about the repo are [REPO]; sizing numbers are **hypotheses** until load-tested.

## 1. VPS options (pricing verified 2026-10-27 from third-party reviews of Hostinger's page – confirm on hostinger.com before purchase)

| Plan | Resources | Intro (24-mo term) | Renewal | Verdict |
|---|---|---|---|---|
| KVM 2 | 2 vCPU / 8 GB / 100 GB NVMe | ≈ $8.99/mo | ≈ $14.99/mo | Staging, or Pilot (≤10 companies) with monitoring stack off |
| **KVM 4** | 4 vCPU / 16 GB / 200 GB NVMe | ≈ $12.99/mo | ≈ $28.99/mo | **Recommended production start** |
| KVM 8 | 8 vCPU / 32 GB / 400 GB NVMe | ≈ $25.99/mo | ≈ $49.99/mo | When DB or workers saturate KVM 4 (see scaling triggers) |

Sources: [findstack](https://findstack.com/resources/hostinger-vps-for-ai-agents), [learnwithhasan](https://learnwithhasan.com/vps-providers/hostinger-vps/), [hostscore](https://hostscore.net/choose/hostinger-vps-alternatives/). These are affiliate/review sites, dated mid-2026; price is promotional and requires a long term. Reported sustained-CPU throttling (~25%/hour after ~180 min of high CPU) needs to be checked in Hostinger's fair-use terms because nightly attendance/payroll jobs are CPU bursts. Region availability and the backup add-on were **not** verified (Gap G4). Hostinger VPS snapshots/backups are in the same provider account; treat them as a convenience only, never as disaster recovery.

## 2. Target architecture (single KVM 4)

```
Internet ─ Cloudflare (DNS, proxy, WAF/rate limit; optional) ─ :443
                         │
                    ┌────▼─────── VPS (UFW: 22 restricted, 80, 443) ─────────────┐
                    │ nginx ── web (Next.js)                                       │
                    │   └────── api (gunicorn x uvicorn)  ──┐   edge net           │
                    │ certbot (renewal)                     │                      │
                    │ ─────────────────────── data net (internal, no host ports)──│
                    │ postgres 16 ◄── api, worker, beat, migrate(one-off)          │
                    │ redis 7  ◄── api, worker, beat                               │
                    │ worker (celery x2)   beat (exactly 1)                        │
                    │ minio (or external S3)  ◄── api, worker, nginx(presigned)    │
                    │ node-exporter / prometheus / grafana (optional, loopback)    │
                    └─────────┬──────────────────────────────────────────────────┘
                              │ encrypted push (pgBackRest or pg_dump+restic)
                      Off-server object storage (different provider/account)
```

Keep from the repo: two networks, no published DB/Redis ports, `migrate` as an explicit one-off, single `beat`, JSON log rotation, non-root image, `/metrics` blocked at Nginx, TLS 1.2+.

### Components: together now, separate later

| Component | Start (KVM 4) | Separate when |
|---|---|---|
| nginx, web, api | same host | API p95 CPU >70% sustained → add second API host behind a load balancer |
| postgres | same host (largest consumer) | DB CPU >60% or disk IOPS wait >20% sustained, or DB >60% of RAM needed → dedicated KVM 8 DB host (private firewall) |
| redis | same host | unlikely before Growth tier |
| worker/beat | same host | when Celery jobs (import, payroll, face) hurt API latency → dedicated worker host (beat stays 1) |
| object storage | **prefer external S3-compatible bucket** over self-hosted MinIO on the same disk (see §5) | – |
| monitoring | same host, Prometheus retention 15 d | Growth: external monitoring/SaaS so alerts survive a VPS outage |

No Kubernetes: workload is one modular monolith plus workers; Compose is sufficient through the Growth scenario.

## 3. Resource budget on KVM 4 (hypothesis)

| Service | RAM limit | CPU share | Notes |
|---|---|---|---|
| OS + Docker + sshd/fail2ban | 1.5 GB | – | measured baseline needed |
| PostgreSQL | 5 GB | up to 2 vCPU | `shared_buffers` 1.5 GB; remainder = OS page cache |
| API (gunicorn) | 3 GB | 1.5 vCPU | `GUNICORN_WORKERS=3`; liveness/face models (`opencv`, MiniFASNet) load per process – measure RSS before raising workers |
| Celery worker | 2 GB | 1 vCPU | `CELERY_CONCURRENCY=2` |
| Redis | 512 MB | – | `maxmemory 512mb`, `noeviction` (broker data must not be evicted) |
| MinIO (if kept) | 1 GB | – | prefer external |
| web (Next.js) | 512 MB | 0.5 | |
| beat + nginx + certbot | 256 MB | – | |
| Prometheus + Grafana | 1 GB | 0.3 | optional |
| **Sum** | ≈14.8 GB | | ≈1.2 GB headroom; **do not** give Postgres more than ~35% of RAM |

Disk (200 GB NVMe): OS+images 20 GB, Postgres data 10–30 GB (Early) , WAL 5–10 GB, local backup staging 2× the largest dump (≈10 GB), logs 5 GB (docker 10 MB×5 per container + `api_logs`), MinIO documents 20–60 GB if self-hosted. Alert at 70 %.

**Connection budget** (max_connections=100): API 3 workers × (pool 5 + overflow 5 = 10) = 30; Celery 2 × 10 = 20 (+ per-task engine disposal); beat 5; migrate/admin/backup 10; superuser reserve 3; monitoring exporter 3; headroom ≈ 29. This requires **setting `pool_size`/`max_overflow`/`pool_timeout` explicitly** (currently defaults, `core/db/session.py:25-36`) – finding P-10. PgBouncer is not needed at this size; revisit if workers > 6 total.

**Tuning rules**: raise API workers only when CPU idle <30 % *and* RSS leaves ≥2 GB free; raise `shared_buffers` only if cache hit ratio <99 % and RAM is free; raise `work_mem` only after `temp_files` growth is seen.

## 4. PostgreSQL production configuration (proposed; not applied)

Mount a `postgresql.conf` fragment (compose `command: postgres -c …` or `/etc/postgresql/conf.d`):

```
max_connections = 100
shared_buffers = 1536MB
effective_cache_size = 9GB
work_mem = 16MB                 # x concurrent sorts; raise per-session for payroll
maintenance_work_mem = 384MB
wal_level = replica
archive_mode = on
archive_command = 'pgbackrest --stanza=hrms archive-push %p'   # or wal-g; PITR
max_wal_size = 4GB
checkpoint_timeout = 15min
random_page_cost = 1.1
effective_io_concurrency = 200
log_min_duration_statement = 500
log_lock_waits = on
log_temp_files = 0
log_autovacuum_min_duration = 1s
shared_preload_libraries = 'pg_stat_statements,auto_explain'
idle_in_transaction_session_timeout = 60s    # also ALTER ROLE hrms_app SET … (P-09)
statement_timeout = 30s                      # role-level for hrms_app; SET LOCAL for jobs
password_encryption = scram-sha-256
ssl = off                                    # internal bridge only; enable if DB leaves the host
```

* Version: stay on **PostgreSQL 16** (CI and compose already use it); pin the minor (`postgres:16.x-alpine`, currently `16-alpine` floats) and upgrade minors in a maintenance window.
* Roles: keep `hrms` (owner, migrations only, not given to runtime containers – fix F-01), `hrms_app` (runtime). Add `hrms_backup` (`pg_read_all_data`/replication) and `hrms_monitor` (`pg_monitor`). No superuser network login.
* Volume: named volume `postgres_data` on NVMe; never bind-mount over network storage. Health: `pg_isready` already present; add a SQL liveness `SELECT 1` through `hrms_app`.
* PITR: pgBackRest (or WAL-G) with WAL archive to off-server S3; RPO ≈ 5 min. If PITR is judged unnecessary, minimum = hourly `pg_dump` (RPO 1 h). **Recommendation: PITR for production.**
* Monitoring: connections, `pg_stat_activity` idle-in-transaction, locks, slow queries, bloat, DB size, replication lag (if replica added), `pg_stat_statements`.

## 5. Storage strategy

| Data | Recommendation |
|---|---|
| Employee documents, onboarding uploads, payslip PDFs (if rendered), face review photos | **Private S3-compatible bucket outside the VPS** (e.g. Hostinger-independent provider) with versioning + SSE; app keeps server-built keys `employee/{company}/{employee}/{doc}/document.ext` [REPO]. Self-hosted MinIO on the same disk is acceptable for Pilot only, and then must be replicated off-server nightly (`infra/backup/minio_backup.sh` has no off-server step) |
| Access | Never public; downloads via short-lived presigned URL minted after an RLS-scoped DB lookup; confirm TTL ≤5 min and `Content-Disposition: attachment` (exists in `employee/document_validation.py:62`) |
| Upload validation | Present: magic-byte sniffing (`sniff_document_content_type`), server-chosen filename, 15 MB Nginx + app body cap (`core/uploads.py`). Add malware scanning (ClamAV) as P3 |
| Encryption/retention | SSE-S3/SSE-KMS at provider; bucket versioning with 90-day noncurrent retention; legal retention per policy (payroll 8 y India – confirm with counsel) |
| Backup | Object store replicated to a second bucket/account; restore tested alongside DB (same recovery runbook) |

## 6. Network & host security

* DNS: A/AAAA for `app.`, `api.`, `storage.` (the three names used by `hrms.conf.template`); low TTL during cutover; CAA record for Let's Encrypt.
* TLS: certbot webroot renewal already in compose (`certbot/certbot:latest` – **pin a version**); add alert at 14 days to expiry. Cloudflare proxy optional: then use Full (strict), restrict origin 80/443 to Cloudflare ranges, and trust `CF-Connecting-IP` (the proxy-aware rate limit is tested in `tests/integration/test_proxy_aware_rate_limiting.py`).
* Firewall (UFW + Hostinger firewall): allow 80, 443; SSH 22 only from admin IPs / or non-default port + key-only; deny all else. Docker bypasses UFW for published ports – only nginx publishes ports (already true in prod compose; **dev `docker-compose.yml` publishes 5433/6380/9000/9001 and must never be used on the VPS**).
* SSH: key-only, `PermitRootLogin no`, `PasswordAuthentication no`, fail2ban, unattended-upgrades for security patches, kernel reboot window.
* Secrets: `apps/api/env/.env.production` and root `.env` mode 0600 owned by deploy user, never in Git (check `.gitignore` covers them), separate `.env.migrate` (F-01). `PII_MASTER_KEY` escrowed offline per `DISASTER_RECOVERY.md`. Prefer Docker secrets or `sops/age` for at-rest encryption of env files.
* Rate limiting: app-level Redis limiter exists (`shared/rate_limit.py`, login/invite/face). Nginx has **no** `limit_req`; add per-IP `limit_req` zone for `/auth/*` and a global burst limit (P2).
* Admin access: platform console should be reachable only through Cloudflare Access / IP allow-list / VPN (P2); Grafana and Prometheus bound to `127.0.0.1` behind SSH tunnel.

## 7. CI/CD and release design

Existing CI covers lint, types, import boundaries, migrations from empty, unit/integration/security tests. Add:

1. `schema-snapshot` and "single alembic head" checks (M-04).
2. Previous-tag upgrade job with data (M-05).
3. Tenant-isolation generated test (T-01) as required check.
4. Dependency audit (`pip-audit`, `npm audit`) and container scan (Trivy).
5. Build and push **versioned images** `hrms-api:<git-sha>` / `hrms-web:<git-sha>` to GHCR; compose uses `IMAGE_TAG`.
6. Deploy job (manual approval) → staging → smoke tests (health, login, punch, leave apply/approve, payslip download) → production.
7. Production deploy steps exactly as in `HOSTINGER_DEPLOYMENT_RUNBOOK.md` (backup → migrate once → api/worker/beat → verify). API replicas never migrate; `beat` is single.

## 8. Cost (recurring, assumptions flagged)

| Item | Monthly | Basis |
|---|---|---|
| Hostinger KVM 4 | ≈ $13 (24-mo promo) → ≈ $29 at renewal | third-party-reported (see §1) |
| Staging KVM 2 (optional, can be powered on demand) | ≈ $9 → $15 | same |
| Off-server backup + document bucket (≈100 GB) | ≈ $1–10 | **assumption**: S3-compatible provider list prices; verify |
| Transactional e-mail (SMTP) | $0–20 | **assumption**, code supports SMTP (`aiosmtplib`) |
| Domain + DNS/Cloudflare free | ≈ $1–2 | assumption |
| Face++ API (if the commercial provider stays enabled) | usage based | not estimated; the repo also has an open-source engine (`20261022090000_face_opensource_engine`) |
| **Total (Early production)** | **≈ $20–60** | before taxes; ex-Face++ |
