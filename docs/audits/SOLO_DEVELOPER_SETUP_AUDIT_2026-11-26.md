# Solo developer + AI setup audit

Audit date: 2026-11-26. Read-only audit of how safely one developer, working mostly through AI agents, can run this project. Server facts come from `docs/audits/devops-audit-2026-11-25/` (a read-only SSH inspection the day before); GitHub and repository facts were re-checked on 2026-11-26. Application code quality was not reviewed.

## Verdict

The repo is in better shape than most solo projects: real CI, a blocking secret scan, and hourly encrypted backups. The weak points are (1) nothing on GitHub protects `main` from a bad AI change, (2) there is no continuous delivery, and production runs code about three weeks older than `test`, and (3) nobody is told when production breaks.

## Already solid

- CI on every PR: ruff, mypy, import boundaries, unit/integration/RLS tests on real Postgres, Redis and MinIO, migration tests, web build and vitest, Flutter analyze and test, Gitleaks, pip-audit and npm audit.
- `auto-merge.yml` merges only on green CI for the exact commit, and refuses PRs touching `.github/`, `.gitleaks.toml`, `AGENTS.md`, `CLAUDE.md` or `apps/api/alembic/`.
- Hourly age-encrypted backups with off-site copy and a daily restore test on the same host.
- Production stack runs non-root, with health checks, loopback ports and a firewall.
- ADRs and a clear `AGENTS.md` git workflow.

## Gaps, most urgent first

### 1. Guardrails against AI mistakes
| Finding | Why it matters |
|---|---|
| No GitHub branch protection or rulesets on `main` (API returned 404). The only block on pushing to `main` is a pre-push hook in one local clone. | Another clone or a leaked token can push to `main`. |
| Local `.env` holds an uncommented live Razorpay key (`rzp_live…`). It is gitignored but readable by every AI agent in this folder. | Use test keys locally. Rotate the live key if it has been in an AI session. |
| `.claude/settings.local.json` has no deny rules for `.env*`, production `ssh`, `gh pr merge`, destructive deletes. | Nothing stops an agent reading secrets or touching production. |
| `CLAUDE.md` is one line; `AGENTS.md` has git rules only (no commands, code map, or "production is off-limits"). | Every AI session starts cold. |
| CI takes about 50 minutes and there is no local "check what I changed" command. | Slow feedback loop on every AI change. |
| Dependabot, secret scanning and push protection were disabled. Actions and `gitleaks:latest` are not pinned. | No vulnerability notices; supply-chain exposure grows once a deploy key exists. |
| ESLint is `continue-on-error`. | Lint is not a real gate. |

### 2. Release and deploy
- No CD. Production was built from a file copy on 2026-11-04. `/opt/hrms` is not a git checkout.
- Live Alembic revision is `20261108090000`; the repo has migrations through `20261125090000`. `test` is about 32 commits ahead of production-era `main`. The next deploy jumps all of it at once.
- No registry, no immutable tags, no rollback command, no release tags. `IMAGE_TAG` defaults to `latest`.
- Mobile: release builds are signed with the debug key; `applicationId` has a TODO; `google-services.json` is a per-machine file; no store pipeline or version policy.

### 3. Knowing when production breaks
- Prometheus, Grafana and Alertmanager are configured in the repo but not running.
- Alerts rely on a host script that emails; an arriving alert has never been observed.
- No external uptime check and no error tracker (no Sentry in API, web or mobile dependencies).
- Celery Beat has its health check disabled. Certificate expiry (2027-01-30) is not clearly monitored.

### 4. Backups and bus factor
- A full rebuild on a new VPS has never been drilled; RPO and RTO are not written down. Documents (MinIO) are backed up daily only, so up to 24 hours can be lost.
- Root SSH is the only login. The age private key and rclone token are single points of failure. Drive backups have no object lock. There is no sealed emergency note for a trusted person.
- `DISASTER_RECOVERY.md` still describes the old `pg_backup.sh`; the timer runs `hrms_backup.sh`.
- The live database is named `hrms_demo`; a stale `hrms_prod` also exists. Easy to restore the wrong one.
- The VPS is shared with another product. The worker uses about 2.2 GiB of 7.8 GiB with no memory caps.

### 5. Repo hygiene and AI context
- The repository is public and contains security audits, runbooks and infrastructure details. Decide whether that is intended.
- About 560 markdown files under `docs/`, 129 in `docs/audits/`, many contradicting each other. This wastes AI context and misleads agents.
- Root clutter: tracked `mavericks-kit.zip`; untracked `shirt.png`, `shorts.png`, `landing-page-code.md`, `pending task.md`, `run_full_tests.py`, logs, `stitch_hrms…`.
- `backups/` (3.8 GB of production database dumps) sits beside the code. Gitignored, but should live elsewhere and be encrypted.
- Stale `origin/claude/tender-gauss-5xrf9z` branch; `delete_branch_on_merge` is off.
- Work tracking is a markdown file. No changelog, PR template or issue list.

## Plan

**Phase 1: this week, hours each**
1. Branch protection on `main` (PR required, six CI checks required, no force-push, no deletion) and no force-push or deletion on `test`.
2. Enable Dependabot alerts, Dependabot security updates, secret scanning and push protection.
3. Replace the live Razorpay key in local `.env` with a test key. Add deny rules for `.env*`, production `ssh` and `gh pr merge` to Claude settings.
4. External uptime monitor on `/health/ready` with phone push; Sentry on API, web and mobile; send one test alert through the email path.
5. Move `backups/` out of the repo folder and encrypt it. Clean the root clutter.
6. `.github/dependabot.yml` (version updates). This touches `.github/`, so a person merges it.

**Phase 2: weeks 2–4, planned window**
7. Record the production baseline; tag running images `baseline-20261104`.
8. Build images in CI, push immutable tags to GHCR, write `deploy.sh` (migrate once, recreate api/worker/beat together, health gate, rollback). Rehearse on a staging copy, then do the catch-up deploy as one event.
9. Start the Prometheus and node-exporter stack already in the repo; set memory limits from measurements.
10. Restore drill on a spare VPS; record real RTO; write the sealed emergency note.
11. Expand `AGENTS.md`/`CLAUDE.md`: commands, code map, production off-limits, a "check changed apps only" script. Move stale audits to an archive and add one `OPERATIONS.md` index.

**Phase 3: later**
12. Android release signing and Play internal track; pin Actions to SHAs; staging environment; changelog and release tags.

## Decisions for the owner

- Should the repository stay public?
- Is `hrms_demo` the real client database? Rename it later, not during the first deploy.
