# HRMS DevOps executive summary

Audit date: 2026-11-25. Read-only. No source, configuration, or server state was changed.

Evidence window:

- Repository: branch `test`, HEAD `de832746ea48606dd83fd141bc81f8bfc31804c8`, clean working tree, in sync with `origin/test`.
- GitHub: public repository `varunmsaji/HRMS`. Open pull request [#81](https://github.com/varunmsaji/HRMS/pull/81). Latest CI run `45608524544` succeeded on that commit.
- Production VPS hostname `srv1592287` (Ubuntu 24.04.4, kernel 6.8.0-147), inspected with read-only SSH. Public checks against `https://www.krewoxa.com`, `https://api.krewoxa.com/health/live`, and `https://api.krewoxa.com/health/ready`.

Companion documents in this directory are the evidence, the target design, the task plan, the maturity scores, the risk register, and the verification checklist. Task IDs such as `P1-01` are defined in `DEVOPS_DETAILED_IMPLEMENTATION_PLAN.md`. Risk IDs such as `R-01` are defined in `DEVOPS_RISK_REGISTER.md`.

## Overall maturity

**2.4 / 5.** The project has a real continuous-integration system and a real single-VPS production stack with encrypted off-site backups. It does not have continuous delivery, GitHub branch protection, a container registry, or a running metrics stack. Production, `main`, and `test` are three different versions.

| Area | Score |
|---|---|
| Source control | 3 |
| Continuous integration | 3 |
| Continuous delivery | 1 |
| Docker | 3 |
| Infrastructure management | 2 |
| Environment separation | 2 |
| Monitoring | 2 |
| Logging | 3 |
| Alerting | 2 |
| Security | 2 |
| Backups | 4 |
| Disaster recovery | 2 |
| Database operations | 3 |
| Release management | 1 |
| Reliability engineering | 2 |
| Documentation | 3 |

Score meanings and the evidence for each number are in `DEVOPS_MATURITY_ASSESSMENT.md`.

## What is actually in production

Inspected 2026-11-25 about 13:15 UTC. Containers have been up for about three weeks with zero restarts. Images were built on the server on 2026-11-04. `/opt/hrms` is not a git checkout.

| Service | Image | Notes |
|---|---|---|
| `hrms-prod-web-1` | `hrms-web:latest`, created 2026-11-04 10:42 UTC | Healthy. `127.0.0.1:3001` |
| `hrms-prod-api-1` | `hrms-api:latest`, created 2026-11-04 04:48 UTC | Healthy. `127.0.0.1:8001`. Runs as user `hrms` |
| `hrms-prod-worker-1` | same API image | Healthy. About 2.16 GiB container memory |
| `hrms-prod-beat-1` | same API image | Running. Health check disabled |
| `hrms-prod-postgres-1` | `postgres:16-alpine` (16.15) | Healthy. Not published to the host |
| `hrms-prod-redis-1` | `redis:7-alpine`, AOF on | Healthy. `maxmemory` is 0 |
| `hrms-prod-minio-1` | `pgsty/silo` digest `635197cb9f36` | Healthy. `127.0.0.1:9100` |

The API process uses database `hrms_demo` at Alembic revision `20261108090000` (committed 2026-11-03). A second database, `hrms_prod`, is at `20261105090000` and is 15 MB. The repository now contains migrations from `20261109090000` through `20261125090000` that are not applied on the live database.

Public results from this audit, each a single sample:

- `https://www.krewoxa.com/` returned 200.
- `https://api.krewoxa.com/health/live` returned 200 in 5.6 s.
- `https://api.krewoxa.com/health/ready` returned 200 in 0.7 s.
- `https://storage.krewoxa.com/` returned 403 (anonymous access closed).
- Let's Encrypt certificate for `www.krewoxa.com` is valid through 2027-01-30. `certbot.timer` is active.

Host nginx, not the Compose nginx service, terminates TLS. Compose file on the server is `docker-compose.vps.yml`. A second product, Hirico, runs on the same machine (`hirico-db`, `hirico-redis`, and a host `uvicorn` on `0.0.0.0:8000`). UFW allows only 22, 80, and 443. Port 8000 was not probed from the internet.

## Top ten capabilities that exist and were evidenced

1. Pull-request CI for API, web, and mobile, including a real PostgreSQL 16, Redis 7, and disposable MinIO, plus a separate migration-test job. Latest run on `de83274` succeeded (about 51 minutes).
2. Blocking secret scan (Gitleaks) and blocking production-dependency audit (`pip-audit`, `npm audit --omit=dev --audit-level=high`).
3. Auto-merge workflow that merges `test` into `main` only after CI success on that exact commit, and refuses when the pull request touches `.github/`, `.gitleaks.toml`, `AGENTS.md`, `CLAUDE.md`, or `apps/api/alembic/`. Pull request #81 is held for that reason.
4. A running production Compose stack with non-root API, worker, and web users, loopback port publishes, separate `data` and `edge` networks, and health checks on API, web, worker, Postgres, Redis, and MinIO.
5. Hourly encrypted backups. Today's daily run at 00:16 UTC succeeded, wrote an age archive, and the log records an off-site copy. Hourly successes continued through 12:21 UTC. `hrms-backup.timer` is enabled.
6. A host monitor every five minutes (`hrms-monitor.timer` enabled). The last completed run exited 0. An email notifier is wired in the unit file. A successful email send was not observed, because the last run did not fail.
7. Public TLS via host nginx and Let's Encrypt, with HSTS present in the krewoxa site file, and certificate renewal timer active.
8. SSH password authentication off, root login limited to public keys, UFW default deny, fail2ban active, unattended-upgrades enabled.
9. Application-level reliability work that is in the repository and in the November images that are running: structured logs, request IDs, `/health/live` and `/health/ready`, Celery queues `default` and `reports_exports`, idempotent-task acknowledgement policy, and a scheduler heartbeat task.
10. Row-level security exercised in CI against a non-superuser `hrms_app` role, with migration tests that fail the job if they skip.

## Top ten gaps

1. No continuous delivery. Production is a file copy into `/opt/hrms`, images are built on the server, and nothing publishes to a registry. See `R-02`.
2. GitHub branch protection is off on `main` and `test`. There are no rulesets and no environments. The pre-push hook exists only in this local clone. See `R-01`.
3. `origin/test` is 28 commits ahead of `origin/main`. Production images and the live schema are older than both. See `R-02`.
4. Prometheus, node exporter, Grafana, and Alertmanager are not running. Alert rules and dashboard JSON exist in the repo and are explicitly optional. See `R-05`.
5. No point-in-time recovery. `archive_mode` is off. Recovery granularity is the hourly dump. See `R-04`.
6. No resource limits on application containers. The worker container holds about 2.16 GiB on a 7.8 GiB host shared with another product. See `R-03`.
7. CI does not build the Docker images production runs, does not scan those images, and does not fail on ESLint (`continue-on-error: true`). Third-party actions and `gitleaks:latest` are not pinned by digest.
8. There is no staging environment. Example env files exist for staging. Only one VPS is in use, and the live database is named `hrms_demo`.
9. Release management is manual. One local tag exists (`backup/main-before-merge`). GitHub releases are empty. `IMAGE_TAG` defaults to `latest`.
10. Disaster recovery is documented in more than one place, and `docs/deployment/DISASTER_RECOVERY.md` still describes the older `pg_backup.sh` model. A full VPS rebuild has not been recorded as a drill.

## Most critical operational risks

| ID | Risk | Why it is critical now |
|---|---|---|
| R-01 | A collaborator can push straight to `main` on GitHub | Branch protection API returns 404. The refusing hook is local to one clone |
| R-02 | The next production deploy jumps about three weeks of schema and code | Live Alembic head `20261108090000`. Repository has later migrations through `20261125090000`. Images are `latest` from 2026-11-04 |
| R-03 | One VPS, shared with Hirico, no memory caps | Worker already uses about 28% of RAM. A restart storm or a second stack can exhaust the box |
| R-04 | Loss window of up to one hour, and an untested full rebuild | Backups are real and current. WAL archiving is off. This audit did not restore onto a new machine |
| R-05 | A quiet failure can sit until someone reads mail or SSH | Prometheus is not running. The host monitor is running and currently green. Alert delivery itself was not observed |

## Recommended target

Keep Docker Compose on one VPS. Do not add Kubernetes. Keep GitHub Actions as the only CI system. Add a container registry (GitHub Container Registry) and deploy by pulling an immutable tag, with API, worker, and Beat updated together and migrations run once before traffic. Turn on the Prometheus and node-exporter files that already exist, bind them to loopback, and keep the existing email monitor as the alert path until a drill proves mail delivery. Keep hourly age-encrypted backups. State the recovery objectives as one hour of data and a same-day rebuild, and run one restore drill on a spare machine before calling disaster recovery done. Add a staging VPS only after the production memory budget is understood. Ansible is justified only as a bootstrap for a replacement VPS, not as a new platform.

Detail is in `DEVOPS_TARGET_ARCHITECTURE.md`.

## Implementation order

| Phase | Intent | Start when |
|---|---|---|
| 0 | Write down the production baseline and stop treating `test` as what is live | Now. This audit is that record |
| 1 | GitHub branch protection and CI hardening | First code-side change. Independent of a deploy |
| 2 | Build and pin images in CI | After phase 1 so a bad image cannot be the only artifact |
| 3 | Deploy from a registry with a written migration step | After phase 2. Do not deploy the current 28-commit gap as an experiment |
| 4 | Health gate and one-command rollback of api, worker, and beat together | With phase 3 |
| 5 | Start the existing Prometheus stack and prove one email alert | Can start in parallel with phase 1 |
| 6 | Record RPO/RTO and run one full restore drill | After phase 5's alert path is proven, so a failed drill is visible |
| 7 | Pin actions, scan images, separate the SSH admin from root | After phase 2 images exist to scan |
| 8 | A bootstrap script for a replacement VPS | After phase 6, because the script is how the drill becomes repeatable |
| 9 | Measure the worker, then set memory and Redis limits | Needs a week of Prometheus data from phase 5 |
| 10 | One operations index. Mark superseded disaster-recovery text | Anytime after phase 0. Do it before the next person follows the old runbook |

Estimated effort for phases 1 through 4, which close the release gap, is about two to three focused weeks for one engineer who already knows this repo, plus a planned production window. Phases 5 through 10 are another three to five weeks if done carefully, and several of them can overlap. The plan in `DEVOPS_DETAILED_IMPLEMENTATION_PLAN.md` marks which tasks are sequential.

## Where to start

Start with phase 1 (`P1-01` branch protection) and phase 0's operational rule: do not copy the current tree to the VPS until the migration list from `20261109090000` onward has an explicit rollout and rollback. Phase 5 (`P5-01`) can start the same week because it only starts containers that the repository already defines and does not change application code.

## Confirmation

This audit created only the files in `docs/audits/devops-audit-2026-11-25/`. It did not modify application code, workflows, Compose files, server configuration, databases, or backups.
