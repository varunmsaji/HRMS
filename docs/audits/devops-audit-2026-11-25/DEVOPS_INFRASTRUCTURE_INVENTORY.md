# HRMS infrastructure inventory

Audit date: 2026-11-25. Read-only inspection of the repository and of the production VPS. Secret values were not printed and are not recorded here.

Classification key: implemented and verified, implemented but unverified, partially implemented, configured but inactive, manual process, missing, not applicable.

## 1. Repository baseline

| Item | Value |
|---|---|
| Path | `/media/varun/varun28/work/staff-spectrum/HRMS` |
| Branch at audit start | `test` |
| HEAD | `de832746ea48606dd83fd141bc81f8bfc31804c8` |
| Upstream | `origin/test` at the same commit |
| Working tree | Clean. No staged, unstaged, or untracked files at start |
| Local `main` | `ef932062` (behind `origin/main`) |
| `origin/main` | `76628d44` (2026-11-23, merge of pull request #80) |
| `origin/test` vs `origin/main` | 0 behind, 28 ahead |
| Remotes | `origin` = `https://github.com/varunmsaji/HRMS.git` |
| Other remote branches | `origin/claude/tender-gauss-5xrf9z` |
| Tags | One: `backup/main-before-merge` |
| GitHub releases | None |
| Visibility | Public |
| Default branch | `main` |

Ongoing work: pull request #81 is open, CI is green on `de83274`, and auto-merge left a comment because the pull request adds Alembic revisions. That pull request is the entire 28-commit gap. It was not merged or otherwise touched by this audit.

Existing audit and operations documents were left in place. This package is separate. Notable predecessors: `docs/devops/CI.md`, `docs/devops/PHASE_A_CI_IMPLEMENTATION.md`, `docs/deployment/PRODUCTION_DEPLOYMENT.md`, `docs/deployment/HOSTINGER_WEB_DEPLOY_FOR_AI.md`, `docs/deployment/BACKUPS_GOOGLE_DRIVE.md`, `docs/audits/RELEASE_HARDENING_PHASE_3B_PRODUCTION_INFRASTRUCTURE.md`.

## 2. Production host (verified)

| Item | Observed |
|---|---|
| Hostname | `srv1592287` |
| Provider | Hostinger VPS, as documented in `docs/deployment/HOSTINGER_WEB_DEPLOY_FOR_AI.md` |
| OS | Ubuntu 24.04.4 LTS |
| Kernel | 6.8.0-147-generic (same series as the auditor's workstation kernel; this is the server) |
| Uptime | 5 weeks, 4 days at inspection |
| CPU | Not enumerated as a core count. Load was not sampled over time. A single `docker stats` sample is in the capacity audit |
| RAM | 7.8 GiB total, about 5.1 GiB available, 603 MiB free, 5.0 GiB buff/cache |
| Swap | 4 GiB file, 544 MiB used |
| Disk | `/dev/sda1` ext4 96 GiB, 24 GiB used (25%), 73 GiB free. Inodes 3% used |
| Boot | `/boot` 15%, EFI 6% |
| Public listeners | 22, 80, 443 on IPv4 and IPv6 |
| Loopback listeners | 3001 (HRMS web), 8001 (HRMS API), 9100 (HRMS MinIO), 5432 (Hirico Postgres), 6379 (Hirico Redis), 53 (systemd-resolved) |
| Also listening | Host process `uvicorn` from `/root/hirico`, `0.0.0.0:8000`, started 2026-11-13, user root. Not an HRMS container. External reachability was not tested. UFW does not allow 8000 |
| Also listening | `monarx-agent` on `127.0.0.1:65529` (Hostinger agent, loopback only) |
| Firewall | UFW active. Default deny incoming, allow outgoing, deny routed. Allows 22, 80, 443 on IPv4 and IPv6 |
| SSH | Port 22. `permitrootlogin without-password`. Password and keyboard-interactive authentication off. Public-key authentication on. Max auth tries 6 |
| Admin accounts | `root` only (uid 0, shell bash). No second human account |
| fail2ban | Active |
| unattended-upgrades | Enabled |
| Upgradable packages | 61 (not split into security versus feature in this audit) |
| Docker | Enabled and active |
| Host nginx | Enabled and active. Sites enabled: `frontend`, `hirico`, `krewoxa` |
| Certificate | `/etc/letsencrypt/live/krewoxa.com` subject `CN=www.krewoxa.com`, notAfter 2027-01-30 09:52:57 GMT. `certbot.timer` active. Per-hostname live directories for `www`, `api`, and `storage` were absent; one certificate file is what the host uses |
| HSTS | The string `Strict-Transport` occurs in `/etc/nginx/sites-enabled/krewoxa` |

HRMS containers have `restart: unless-stopped`, memory limit 0, CPU limit 0, and restart count 0. Users: API, worker, and Beat `hrms`; web `node`; Postgres, Redis, and MinIO use the image default (empty `Config.User`).

No Prometheus, Grafana, Alertmanager, or node-exporter container is present.

`/opt/hrms` is not a git repository. Compose file mtime 2026-11-04 04:23 UTC. API Dockerfile mtime the same. Web Dockerfile mtime 2026-11-04 04:53 UTC.

## 3. Production data plane (verified)

| Item | Observed |
|---|---|
| API `DATABASE_URL` target | `postgres:5432/hrms_demo` (password not read) |
| Live Alembic head | `hrms_demo` = `20261108090000` |
| Other database | `hrms_prod` = `20261105090000`, size 15 MB |
| `hrms_demo` size | 129 MB |
| PostgreSQL | 16.15. `max_connections` 100. `shared_buffers` 128 MB. `wal_level` replica. `archive_mode` off. `archive_command` disabled. `max_wal_size` 1 GB |
| Redis | AOF yes. `used_memory_human` about 10.5 MB. `maxmemory` 0. Policy `noeviction` |
| Backup timer | `hrms-backup.timer` enabled and active. Schedule in the unit: hourly at :15 UTC |
| Last backup results | Daily success 2026-11-25 00:23 UTC for `hrms_20261125T001648Z_daily.tar.age` (11 MB) with off-site destination recorded by the script. Hourly successes at 07:23, 08:17, 09:19, 10:15, 11:17, and 12:21 UTC the same day. Matching daily MinIO archives exist for 2026-11-23, 24, and 25 |
| Monitor timer | `hrms-monitor.timer` enabled. Last `hrms-monitor.service` result success, exit status 0 |
| Log rotation | `logrotate.timer` active on the host. Container logs are also capped in Compose at 10 MB × 5 files |

The backup script's own success line is the evidence for the off-site copy. This audit did not list the Google Drive folder and did not decrypt an archive.

## 4. Repository service map

### Applications

| Component | Where it is defined | How it runs in production |
|---|---|---|
| FastAPI | `apps/api/Dockerfile`, `entrypoints/api.py` | Compose service `api`. Gunicorn with Uvicorn workers. Port 8000 inside the network, published to `127.0.0.1:8001` by `docker-compose.vps.yml` |
| Next.js web | `apps/web/Dockerfile` | Compose service `web`. `127.0.0.1:3001`. Standalone output, user `node` |
| Celery worker | Same API image, command override | Service `worker`. Concurrency default 2. Consumes queues declared in `apps/api/src/hrms/core/celery_app.py` |
| Celery Beat | Same API image | Service `beat`. Schedule file `/tmp/celerybeat-schedule`. Health check disabled. Must stay at one replica |
| Flutter mobile | `apps/mobile` | Not a server process. CI job `mobile` runs `flutter analyze` and `flutter test` |

### Data and edge

| Component | Compose | Production observation |
|---|---|---|
| PostgreSQL 16 | `postgres` service, init scripts in `infra/docker/postgres/init/` | Running. Not published by the HRMS compose file. Hirico publishes its own Postgres on `127.0.0.1:5432` |
| Redis 7 | `redis` with `--appendonly yes` in prod and vps files | Running. HRMS Redis is not published. Hirico Redis is on `127.0.0.1:6379` |
| Object storage | `pgsty/silo` pinned by digest in prod and vps files. Dev compose uses `pgsty/silo:latest` | Running, digest matches the pin in `docker-compose.vps.yml` |
| MinIO init | `pgsty/mc` one-shot, bucket create, anonymous off | Not left running, which is expected (`restart: "no"`) |
| Nginx in Compose | `docker-compose.prod.yml` only | Not used on this VPS. `docker-compose.vps.yml` has no nginx or certbot service |
| Host nginx | `infra/nginx/` is the Compose variant. The live site is `/etc/nginx/sites-enabled/krewoxa`, which is not in git | Verified running |
| Certbot in Compose | `certbot/certbot:latest` loop in `docker-compose.prod.yml` | Not the renewal path on this host. Host `certbot.timer` is |
| CompreFace | Profile `compreface` in dev compose and vps compose | Not running. No `compreface` container in `docker ps` |
| Monitoring | `docker-compose.monitoring.yml` | Not started |

### Supporting tooling in the repo

| Item | Status |
|---|---|
| Ansible | Missing. No playbooks |
| Terraform / OpenTofu | Missing |
| GitHub Actions | Two workflows: `.github/workflows/ci.yml`, `.github/workflows/auto-merge.yml` |
| Dependabot / Renovate | Missing |
| CODEOWNERS | Missing |
| CONTRIBUTING.md | Missing |
| Container registry config | Missing |
| Sentry SDK | Mentioned as a target in `docs/product/13_DevOps_Architecture.md`. No Sentry integration found in application code |
| RQ | Not used. Celery is the queue |

## 5. Environments that exist as files versus hosts

| Name | Files | Host |
|---|---|---|
| Local development | `docker-compose.yml`, `apps/api/.env.example`, `apps/api/env/.env.dev.example`, `apps/web/.env.local.example` | Developer machine. Dev ports 5433 and 6380 so they do not collide with a system Postgres or Redis |
| CI | Job services inside `ci.yml`. Dev passwords that are already in the repository | GitHub-hosted `ubuntu-latest`. Destroyed after the job |
| QA | `apps/api/env/.env.qa.example`, `docs/qa/comprehensive_hrms/runtime/` | No dedicated server found |
| Staging | `apps/api/env/.env.staging.example` | No host found |
| Production | `.env.prod.example`, `apps/api/env/.env.production.example`, `docker-compose.vps.yml` | `srv1592287`, code directory `/opt/hrms` |

Real env files exist on the developer workstation (`.env`, `apps/.env`, `apps/web/.env.local`, `apps/api/.env`). Their values were not read. They are gitignored from the audit narrative. Production env files on the server were not printed. The backup script is designed to include them, encrypted, in the daily archive, because they hold `PII_MASTER_KEY`.

## 6. Process and schedule inventory on the server

| Unit | State | Role |
|---|---|---|
| `docker.service` | enabled, active | Container runtime |
| `nginx.service` | enabled, active | Public TLS and reverse proxy |
| `hrms-backup.timer` | enabled, active | Hourly backup |
| `hrms-backup.service` | static, inactive between runs | Last result success |
| `hrms-monitor.timer` | enabled, active | Every 5 minutes |
| `hrms-monitor.service` | static | Last result success, exit 0 |
| `hrms-alert@.service` | defined in the repo and referenced as `OnFailure` | Fires when backup or monitor units fail. Not observed firing |
| `certbot.timer` | active | Host certificate renewal |
| `apt-daily.timer`, `apt-daily-upgrade.timer` | active | Unattended package updates |
| `logrotate.timer` | active | Host log rotation |
| `fail2ban` | active | SSH ban list. Jail list was not dumped |

Repo copies of the HRMS units live in `infra/backup/systemd/` and `infra/monitoring/systemd/`. Whether the installed unit text matches the repo byte for byte was not diffed. The timer names and the backup log format match the repo scripts.

## 7. Single points of failure

| SPOF | Evidence |
|---|---|
| One VPS | All HRMS containers, host nginx, certificates, and local backup staging live on `srv1592287` |
| One disk | Single ext4 root filesystem. No separate data volume observed |
| One operator path | SSH as root with one key. No second admin user |
| Shared fate with Hirico | Same kernel, same disk, same nginx, same Docker daemon |
| One Beat process | By design. If it stops, schedules stop until restart. Restart policy is `unless-stopped`, so a crash comes back. A hung process would not, because the health check is disabled |
| One Redis | Broker, result backend, and rate-limit state. AOF is on. No replica |
| Age private key | Documented as offline. This audit did not confirm the key can be found. Losing it makes every backup unreadable |
| Google Drive token | On the server in rclone's config (documented, not opened). Root can delete remote objects. Drive trash retains them for 30 days per `docs/deployment/BACKUPS_GOOGLE_DRIVE.md` |

## 8. What was not available

- No second environment to compare.
- No historical metrics. Prometheus is not installed, so CPU, latency, and queue depth over time are unknown.
- Google Drive object listing was not performed.
- The age private key was not located or tested.
- Hirico was not inspected beyond process and container names required to avoid confusing it with HRMS.
- Package updates were counted, not classified.
- A second `docker stats` sample was not taken, so the 2.16 GiB worker figure is one observation after three weeks of uptime, not a trend.
