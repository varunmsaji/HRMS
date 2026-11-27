# DevOps verification checklist

Audit date: 2026-11-25. Use this list to confirm the audit's claims and, later, to accept each implementation task. Items marked **verified in this audit** were observed on 2026-11-25. Items marked **open** are the acceptance tests for the plan.

## Repository was not changed except for this package

- [x] Start of audit: branch `test`, HEAD `de832746ea48606dd83fd141bc81f8bfc31804c8`, clean tree.
- [x] No edits to application code, workflows, Compose, systemd units, or server files during evidence gathering.
- [x] End of audit: `git status` shows only untracked `docs/audits/devops-audit-2026-11-25/`. HEAD is still `de832746ea48606dd83fd141bc81f8bfc31804c8`.

## Workflow and GitHub

- [x] CI workflow and auto-merge workflow read.
- [x] Latest CI run `45608524544` succeeded for all six jobs on `de83274`.
- [x] PR #81 open, CI green, auto-merge comment names the Alembic file.
- [x] Branch protection absent on `main` and `test`.
- [x] No GitHub environments. No releases. Actions permissions read. SHA pinning not required.
- [ ] **P1-01** Direct push to `main` is rejected by GitHub.
- [ ] **P1-02** The six job names are required checks.
- [ ] **P1-03** Actions and Gitleaks are pinned. Repo requires SHA pinning.
- [ ] **P1-04** ESLint either fails the job or the summary no longer implies that it does.
- [ ] **P1-05** Every job has `timeout-minutes`. No test step uses `continue-on-error`.

## Production, read-only, already observed

- [x] Hostname `srv1592287`, Ubuntu 24.04.4, kernel 6.8.0-147.
- [x] UFW active, allow 22/80/443 only.
- [x] SSH passwords off, root login by key only.
- [x] HRMS containers up about three weeks, restart count 0, healthy except Beat which has no health check.
- [x] API, worker, Beat user `hrms`. Web user `node`.
- [x] API published on `127.0.0.1:8001`, web on `127.0.0.1:3001`, MinIO on `127.0.0.1:9100`.
- [x] Postgres 16.15, `archive_mode` off, databases `hrms_demo` (129 MB, Alembic `20261108090000`) and `hrms_prod` (15 MB, `20261105090000`).
- [x] API database target is `postgres:5432/hrms_demo`.
- [x] Redis AOF on, maxmemory 0, about 10.5 MB used.
- [x] Images created 2026-11-04. `/opt/hrms` is not a git repo.
- [x] No Prometheus, Grafana, or Alertmanager container.
- [x] Backup timer enabled. Daily SUCCESS 2026-11-25 00:23 UTC. Hourly SUCCESS through 12:21 UTC.
- [x] Monitor timer enabled. Last exit 0.
- [x] Public `https://www.krewoxa.com/` 200, `/health/live` 200, `/health/ready` 200, storage 403.
- [x] Certificate notAfter 2027-01-30. certbot timer active.
- [x] fail2ban active. unattended-upgrades enabled. 61 packages upgradable.
- [x] Hirico identified and not modified. Its uvicorn on `0.0.0.0:8000` was not probed from the internet.

## Open acceptance tests from the plan

- [ ] **P0-01** Baseline image tags exist and no container was recreated to create them.
- [ ] **P2-01** CI builds both images and does not push on a pull request.
- [ ] **P2-02** Postgres and Redis digests in Compose match the running images.
- [ ] **P2-03** A `main` commit has a GHCR tag equal to its SHA. Package visibility is what the owner chose.
- [ ] **P3-01** Deploy script dry-run on the VPS restarts nothing and refuses any name outside the HRMS service list.
- [ ] **P3-02** Spare database upgraded from `20261108090000` to the image head before production.
- [ ] **P4-01** Forced health-check failure restores the previous digest. A real deploy logs a 200 and matching image IDs for api, worker, and beat.
- [ ] **P5-01** Prometheus target `hrms-api` is UP. Port 9090 is not public.
- [ ] **P5-02** One test email received.
- [ ] **P5-03** Certificate-expiry check fails a fixture inside 21 days and passes on the live certificate.
- [ ] **P6-02** Off-server restore matches `manifest.txt`. Private key was not copied to the VPS.
- [ ] **P6-03** MinIO window is either hourly or explicitly accepted as 24 hours.
- [ ] **P7-02** A deploy works as `deploy`. Root login is disabled only after a console session is confirmed.
- [ ] **P7-03** Security updates applied or listed, both products healthy.
- [ ] **P8-01** Spare VM bootstrapped. Production not used as the test.
- [ ] **P9-01** Worker memory explained and a limit above the steady state applied without a restart loop.
- [ ] **P9-02** Redis `maxmemory` is 256mb and the app is healthy.
- [ ] **P10-01** `docs/operations/README.md` links resolve, and the old disaster-recovery page points at the script that actually runs.

## Cross-reference check

| Recommendation | Finding | Task | Acceptance |
|---|---|---|---|
| Protect branches | `R-01`, current-state audit section 1 | `P1-01`, `P1-02` | Push rejected, checks required |
| Do not deploy the tree blindly | `R-02`, inventory section 3 | `P0-01`, `P3-02`, `P4-01` | Spare upgrade, then health-gated deploy |
| Registry and digests | CI audit section 4 | `P2-01`, `P2-03` | Image built in CI, tag equals SHA |
| Start Prometheus | Observability audit section 1 | `P5-01` | Target UP, port not public |
| Prove mail | `R-05` | `P5-02` | Message received |
| Restore drill | Backup audit section 2 | `P6-02` | Manifest match off-server |
| Pin actions before any deploy secret | `R-06` | `P1-03` | SHA pinning required |
| Worker limit after measurement | Reliability audit section 1 | `P9-01` | Limit above steady state, no crash loop |
| One operations index | Current-state audit section 6 | `P10-01` | Links resolve |

## Commands that stay forbidden during verification

Do not run `docker compose down`, `docker system prune`, `docker volume rm`, a database restore onto `hrms_demo`, or an upgrade on the production database as part of checking this list. The spare-database and spare-VM tasks are the place for destructive tests.
