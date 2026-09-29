# CI/CD & DevOps Implementation Plan — Staff Spectrum HRMS

**Status:** PLAN ONLY — Phase A. Nothing in this document has been implemented. No files other than this one were created or modified while producing it.
**Date:** 2026-09-27
**Scope:** Build a DevOps layer around the existing architecture. Docker Compose, PostgreSQL, Redis, MinIO, and the current CI workflow are kept as-is unless a specific finding below justifies a change.

---

## 1. Executive Summary

The application is further along than the CI/CD around it. Backend and frontend code are strictly typed and linted, Postgres RLS is real (DB-enforced, not just app-level filtering), the production Docker Compose stack is well-designed (non-root images, two-network isolation, a dedicated one-off `migrate` service, fail-closed secret validation), and backup/restore scripts exist and have been manually verified once. Five internal audit phases (0, 1, 2, 3A, 3B, 4, 5A, 6, 6A) already did real hardening work.

But the DevOps *process* around that code has three problems more urgent than anything on the user's original 35-point list:

1. **CI is not actually running.** `origin/main` is 27 commits behind local `main`. GitHub Actions has executed exactly twice in this repo's history (2026-08-25, 2026-09-03), both runs failed, and nothing has triggered it since — because nothing has been pushed. Every payroll phase (5.1–5.6), the TDS implementation, and the entire release-hardening effort (phases 0–6A) exists only on the developer's machine. CI has validated none of it.
2. **CI never touches Docker or Compose.** This is documented in the repo's own audit trail as finding **CI-02**, and it is not theoretical: it is the confirmed root cause that let **DB-01** (a hardcoded Postgres password in a production init script, independent of the operator's own secret) ship undetected through five hardening phases. It was only caught by a human manually booting the stack.
3. **Branch protection is unavailable on this repo as configured.** `GET /branches/main/protection` returns 403: "Upgrade to GitHub Pro or make this repository public." On a private repo under the current plan, nothing can technically force a PR, a review, or a green CI run before a merge to `main` — which is consistent with finding #1 (there is no PR history to speak of; commits land on `main` directly).

Everything else in this plan — Docker CI, registry, deployment, backups, monitoring — is real and worth building, but it would be building a second floor on a foundation that currently has no working ground floor. **Section 24 ("Open Decisions") leads with the prerequisite decision: what to do about the 27 unpushed commits before any of this pipeline can mean anything.**

The good news: closing all three gaps costs close to nothing. The registry, monitoring, and scanning tools recommended below are free-tier for a repo and workload this size. The only cash costs are optional: GitHub Pro (~$4/mo, for branch protection) and a second small VPS for staging (~$5–6/mo, only if approved).

---

## 2. Current Architecture (as verified, not assumed)

**Backend** — `apps/api`, FastAPI, Python 3.12, dependency management via `uv` with a committed `uv.lock`. SQLAlchemy 2.0 async (asyncpg + psycopg for sync Alembic), Alembic migrations, Pydantic Settings. Auth via PyJWT (migrated off `python-jose` in Phase 3A) + argon2. PII fields encrypted with a self-hosted AES-256-GCM application master key (`hrms.core.crypto`) — deliberately not AWS KMS, after Phase 3A found KMS had become a hard boot-time dependency that contradicted the no-AWS mandate. Celery + Redis for worker/beat. `aioboto3` used solely as a MinIO S3 client (SES support was removed in Phase 5A in favor of `aiosmtplib`/SMTP). Structured logging via `structlog`.

**Tenant isolation** is real, DB-enforced Postgres Row-Level Security: tables carry `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + a `tenant_isolation` policy keyed on the `app.company_id` session GUC, which the app sets on every session (`hrms.core.db.session.set_rls_company_id`). Two DB roles exist: `hrms` (schema owner, runs migrations, effectively bypasses RLS) and `hrms_app` (runtime role, confirmed `NOSUPERUSER`/`NOBYPASSRLS` — CI checks this on every run). `tests/security/test_rls_runtime_role.py` proves cross-tenant access is blocked by Postgres itself, not by a WHERE clause.

**Static analysis (backend):** Ruff (`select = E,F,I,N,B,UP,BLE,TRY`, line-length 100), **mypy `strict = true`** on `src/hrms`, and `import-linter` enforcing one layered contract: `hrms.modules → hrms.shared → hrms.core` (downward-only dependencies). All three currently pass clean.

**Tests (backend):** 154 test files (54 unit, 95 integration, 5 security) under `apps/api/tests`. No mocking of Postgres, Redis, or MinIO — all three are real services in every test run. Latest recorded full run: 1,741 passed, 0 failed (Phase 5A).

**Frontend** — `apps/web`, Next.js 14.2.28, React 18.3.1, TypeScript 5.7.2 (`strict: true`), npm with a committed lockfile. Tests via Vitest + Testing Library, 56 test files, all unit/component level — **there is no e2e layer (no Playwright/Cypress) anywhere in the repo.** **There is no ESLint at all** — no config, no dependency installed. `next lint` exists as a script but would hang on an interactive setup prompt in a non-interactive shell; this is a known, already-documented gap, not something this plan is discovering.

**Local dev tooling:** `dev.sh` → `scripts/dev.sh` (or the newer `scripts/dev.py`) brings up Docker Compose (Postgres/Redis/MinIO) plus the API and web dev servers with health polling. `run_full_tests.py` (root) is a one-command orchestrator that mirrors CI's static/unit/integration/security/typecheck/vitest gates against an isolated `hrms_test` database, and additionally runs a full `next build` — which CI does not currently do. Both the local runner and CI share the same honest gap: **neither runs ESLint**, because there is nothing to run.

**Production infra** — `docker-compose.prod.yml`, project `hrms-prod`. Ten services: `postgres`, `redis`, `minio` + `minio-init` (one-shot bucket bootstrap), `api`, `migrate` (a dedicated one-off service, `profiles: ["tools"]`, deliberately excluded from `docker compose up` so migrations never race a starting API/worker), `worker`, `beat`, `web`, `nginx` (the *only* service publishing host ports — 80/443), `certbot`. Two networks: `data` (Postgres/Redis/MinIO/api/worker/beat — no route from the internet-facing side) and `edge` (nginx/api/web/minio, for presigned-URL proxying). Both application Dockerfiles are already reasonably hardened: non-root users, multi-stage builds, `HEALTHCHECK` directives. The compose file already parameterizes `${IMAGE_TAG:-latest}` — the plumbing for immutable image tags exists, it's just never been used for anything but `latest`.

**Secrets** are two separate env files: root `.env` (compose-level — Postgres/MinIO container credentials, domains, `IMAGE_TAG`) and `apps/api/env/.env.production` (the app's own `Settings` — DB URL, JWT secrets, PII master key, SMTP, S3 keys). Both are `${VAR:?required}`-style fail-closed at the compose layer, and a `pydantic` validator (`Settings._guard_non_development_config`) refuses to boot outside `development` if any secret still equals its dev default or fails an entropy floor. Nothing overlaps them automatically — the two files can drift, and that's exactly how DB-01 happened (an init script had its own hardcoded literal, independent of either file).

**Backups** — `infra/backup/{pg,minio}_backup.sh` and matching `*_restore.sh` exist, were manually run once end-to-end during Phase 3B (with a restore-into-different-name safety rail), and work. **They are not scheduled.** No crontab installs them; the cron lines in `PRODUCTION_DEPLOYMENT.md` are copy-paste documentation, not executed anywhere. There is no encryption of backup archives at rest and no off-VPS copy — both are named as open gaps in `DISASTER_RECOVERY.md` itself.

**Health endpoints:** `/health` (legacy, DB-only), `/health/live` (dependency-blind — what the container `HEALTHCHECK` polls, deliberately, to avoid restart storms on a transient Postgres/Redis blip), `/health/ready` (checks Postgres + Redis + S3 config, returns 503 if not ready — intended for an external load balancer/monitor, not the container healthcheck).

---

## 3. Current CI/CD State (ground truth, not the historical audit narrative)

`.github/workflows/ci.yml`, one workflow, two parallel jobs, triggered on `push`/`pull_request` to `main`/`develop` (no path filters, no `workflow_dispatch`, no schedule):

- **`api`** — real `postgres:16-alpine` + `redis:7-alpine` service containers (fresh every run), manually applies `infra/docker/postgres/init/*.sql`/`*.sh` (GH Actions service containers don't run `docker-entrypoint-initdb.d`), runs `alembic upgrade head` against the empty DB, asserts `hrms_app` is `NOSUPERUSER`/`NOBYPASSRLS`, then `pytest tests/unit` and `pytest tests/integration tests/security`. Ruff/Ruff-format/mypy/import-linter run first and gate the rest.
- **`web`** — `npx tsc --noEmit` + `npm test` (Vitest). `TZ=America/New_York` is set deliberately (non-IST) to catch host-timezone-fallback regressions. No `next build`, no lint (there is none to run).

**What is verifiably absent:** any Docker build or `docker compose` step; secret scanning; dependency vulnerability scanning (no `pip-audit`, no `npm audit`); container image scanning; SAST; a production frontend build gate. Caching is limited to `uv`'s own cache and npm's cache.

**What is verifiably broken as a process, independent of the workflow's content:** the workflow has run **twice, total**, both failures, nothing since 2026-09-03, and `origin/main` is 27 commits behind local `main`. As a gate on anything currently in the repository, this CI workflow has been inert for three weeks.

---

## 4. Current Gaps

Ranked by actual risk, not by the order they appear on a checklist:

| # | Gap | Evidence | Why it matters |
|---|---|---|---|
| G0 | 27 commits never pushed; CI hasn't run since 2026-09-03 | `git rev-list --left-right --count origin/main...main` = `0 27` | Every gate below is inert until code reaches GitHub. Nothing else in this plan has value until this is resolved. |
| G1 (**CI-02**, pre-existing finding) | CI never builds/boots Docker images or `docker-compose.prod.yml` | Confirmed absent in `ci.yml`; explicitly named in `RELEASE_HARDENING_PHASE_6_DEPLOYMENT_READINESS.md` as the reason DB-01 shipped 5 phases undetected | The single highest-value fix on this entire list — a compose-boot test is the class of check that catches the *next* DB-01, not just this one. |
| G2 | Branch protection unavailable (private repo, current plan tier) | `403` from GitHub API on the protection endpoint | Nothing can force PR review or a green CI run before merge to `main`, which is consistent with the fact that nothing currently goes through a PR. |
| G3 | Backups exist as scripts, not as a schedule | No crontab anywhere in the repo; cron lines in docs are illustrative only | Effective RPO today is "since whoever last ran the script by hand," which is worse than the DR doc's own stated (and already unverified) "up to 24h" assumption. |
| G4 | No off-VPS backup copy, no backup encryption at rest | Explicit open item in `DISASTER_RECOVERY.md` | A VPS-level disaster (disk failure, provider account loss, compromise) currently takes the only backup copy with it. |
| G5 | No frontend lint (FE-01) | No ESLint dependency or config anywhere in `apps/web` | A real, if narrow, quality gate is silently absent — not degraded, absent. |
| G6 | No VPS hardening documentation (VPS-01) | No firewall/SSH/fail2ban/auto-update guidance found in `docs/deployment/` | Deployment docs assume a VPS that is already secured, but nothing in the repo says how it got that way or how to reproduce it. |
| G7 | No dependency or secret scanning | Confirmed absent from `ci.yml` | Cheap to add; currently zero coverage for known-CVE dependencies or an accidentally committed credential. |
| G8 | PII_MASTER_KEY custody has no named human owner | `DISASTER_RECOVERY.md` flags this as open; no audit doc assigns it | If the key is lost, all PAN/Aadhaar/bank data becomes "permanently, mathematically unrecoverable" by design — this is not a technical gap, it's an unassigned operational responsibility for the single most consequential secret in the system. |
| G9 | No staging environment | Only `docker-compose.yml` (dev) and `docker-compose.prod.yml` (prod) exist | Every "prove it works" step currently either happens on a developer's laptop or directly on production. |
| G10 | Repo root has stray large/unrelated files | `mavericks-kit.zip` (3.9MB), `shirt.png`, `shorts.png`, `work done/` sitting untracked at repo root per `git status` | Not a security issue, but it bloats clone size and Docker build context; worth a `.gitignore` pass, not a blocker. |

---

## 5. Target Architecture

```
Developer → feature branch → PR → CI (existing api/web jobs + new: lint, build,
  dep/secret scan, Docker build, compose-boot validation) → review → merge to main
  → build+tag+push images to GHCR (tag = commit SHA) → manual deploy approval
  (GitHub Environment) → VPS: pull images → migrate (profile tools) → restart
  services → health checks → smoke test → done. Nightly/scheduled: backup,
  backup-restore verification, uptime/monitoring checks running independently
  of the deploy pipeline.
```

No Kubernetes, no Swarm, no blue/green, no Terraform, no AWS. Single VPS, Docker Compose, GitHub Actions, GHCR. This is a deliberate match to the existing architecture, not a downgrade from some default "production-grade" template — see Section 15 for the reasoning.

---

## 6. CI Pipeline (additions to the existing `ci.yml`, nothing removed)

Keep the `api` and `web` jobs exactly as they are — they are already doing the right things (fresh DB every run, real RLS verification, real integration tests with no mocking). Add:

- **`web` job:** an ESLint step (`eslint-config-next` + a minimal flat config), and a `next build` step with `NEXT_PUBLIC_API_URL` set — both currently only exist in `run_full_tests.py`, not in CI. Closes G5 and the CI/local-parity gap in the same move.
- **New `security-scan` job** (parallel to `api`/`web`, does not block them): `gitleaks` (secret scanning, catches an accidentally committed credential before it's in history for good), `pip-audit` against the `uv` environment, `npm audit --audit-level=high` for `apps/web`. Start non-blocking (report-only) for one iteration to see the baseline noise level, then promote to blocking. Closes G7.
- **Explicitly not adding yet:** CodeQL/SAST. GitHub Advanced Security's SAST features are free for public repos but require a paid tier for private ones — this is a cost/value call for a 1–2 person team, not an obvious yes. Listed in Open Decisions (Section 24), not silently added.

## 7. CD Pipeline

On merge to `main` (after CI is green): build `api` and `web` images, tag both `ghcr.io/<owner>/hrms-api:<sha>` / `hrms-web:<sha>` (plus a `latest` alias for convenience, never used for deployment itself), push to GHCR. Then a **GitHub Environment with a required reviewer** gates the actual deploy job — this is a real, currently-unused free feature of GitHub Environments and is independent of the branch-protection paywall in G2, so it's available today regardless of how G2 is resolved. The deploy job SSHes to the VPS (or the operator runs a thin `deploy.sh <sha>` locally against the VPS) and pulls the named tag rather than rebuilding on the VPS.

Recommendation: **hybrid, manual-gated** — automatic build+push, manual approval before the VPS actually changes. Reasoning: pre-pilot stage, no public users yet per the existing readiness audits, DB migrations are not automatically reversible, and real Let's Encrypt/SMTP delivery have never been exercised against a live domain. Revisit for closer-to-automatic staging deploys once a staging environment exists and a few manual production deploys have gone cleanly.

## 8. Docker Strategy

Two new CI jobs, both directly targeting **CI-02**:

- **`docker-build`**: `docker build` for `apps/api/Dockerfile` and `apps/web/Dockerfile` on every PR that touches those paths (or their dependency lockfiles). Add `hadolint` against both Dockerfiles — cheap, and both files already follow good practice (non-root, multi-stage), so this mostly guards against *regression*, not a current problem. Add a Trivy image scan against the built images, report-only initially (same reasoning as the dependency scan above — establish baseline noise before gating on it).
- **`compose-validate`**: the job that would have caught DB-01. Builds both images, generates a disposable `.env` (fake domains, generated random passwords — never real secrets), runs `docker compose -f docker-compose.prod.yml config` to validate parsing and that every `${VAR:?required}` is actually enforced, brings the stack up *without* `nginx`/`certbot` (no public domain or ACME needed in CI — hit `api`/`web` containers directly on their internal ports instead), runs `docker compose --profile tools run --rm migrate`, waits for every service's healthcheck to go green, curls `/health/live` and `/health/ready`, and runs one minimal smoke test (create a test company via the real API, confirm a second test company cannot read its data — a direct, automated version of the RLS tenant-isolation check). Tears everything down unconditionally.

Open decision (Section 24): run `compose-validate` on every PR (slower, catches infra regressions immediately) or only on PRs touching Docker/infra paths plus a nightly scheduled run (faster PRs, small detection lag). Given DB-01's actual blast radius, leaning toward "every PR that touches the relevant paths, plus nightly on everything" as the default recommendation — but this is the user's call on the cost/speed tradeoff.

## 9. Registry Strategy

**Recommend GitHub Container Registry (GHCR).** Free for a private repo at this scale, authenticates with the existing `GITHUB_TOKEN` (no new credential to create or rotate), keeps images co-located with the code and its Actions runs, and trivially supports immutable SHA tags — which `docker-compose.prod.yml` already anticipates via `${IMAGE_TAG:-latest}`.

| | GHCR | Docker Hub | Self-hosted | Build-on-VPS |
|---|---|---|---|---|
| Cost | Free (private) | Free tier rate-limited | VPS resources + a new attack surface | Free, but ties CI to VPS uptime |
| Auth | `GITHUB_TOKEN`, zero setup | Separate account/token | Self-managed TLS + auth | N/A |
| Rollback | Trivial — pull by SHA | Trivial — pull by SHA | Trivial | Requires keeping old build artifacts around |
| Extra surface | None | None | Yes — one more service to patch/secure on the same single VPS | None, but no build isolation from prod |

Self-hosting a registry on the same VPS that runs production buys nothing here and adds a service to secure for no benefit. Building directly on the VPS (currently effectively what happens, since there's no registry at all yet) works but means a deploy can fail mid-build on the box actually serving traffic. GHCR is the simplest option that's still strictly better than the status quo.

## 10. Deployment Strategy

See Section 7. Concretely, for one deploy:

```
git tag/merge → CI green → build+push ghcr.io/.../hrms-api:<sha>, hrms-web:<sha>
→ [manual approval, GitHub Environment] → operator/deploy-job on VPS:
  docker compose -f docker-compose.prod.yml pull
  docker compose -f docker-compose.prod.yml --profile tools run --rm migrate
  docker compose -f docker-compose.prod.yml up -d
  curl -f https://$API_DOMAIN/health/ready
  curl -f https://$WEB_DOMAIN/login
→ smoke test (scripted, safe: create+delete a throwaway test company)
→ record <sha> as "last known good" (a single file on the VPS or a GitHub
  Deployment status) → done
```

Not recommending full automatic deployment on every merge yet — see Section 7's reasoning. Not recommending deploying every commit without a distinct build/tag step either; `latest` as the only tag (today's actual state) makes it impossible to know what's actually running, which Section 11 fixes directly.

## 11. Migration Strategy

Already well-designed — keep it as-is, just make it participate in CI/CD rather than only being run by hand:

- `migrate` stays a dedicated, `profiles: ["tools"]` one-off service — never starts automatically, never races `api`/`worker` starting concurrently.
- CI's new `compose-validate` job (Section 8) proves migrations apply cleanly to a genuinely empty database on every relevant PR — this already happens in the `api` job today, but only against the GH Actions service-container Postgres, not against the actual `docker-compose.prod.yml` shape (real init scripts, real `migrate` service, real profile).
- Migration failure behavior: Alembic DDL is transactional in Postgres, so a failed migration rolls back cleanly — it does not leave a half-migrated schema. There is no automatic *rollback* of an already-succeeded migration if the application itself needs to roll back; that remains a documented manual decision (forward-fix vs. restore-from-backup), consistent with the existing `DISASTER_RECOVERY.md` philosophy. This plan does not change that — automatic schema rollback is not something to bolt on casually, and the existing docs are right not to promise it.
- New: run `migrate` *before* the `up -d` in the deploy sequence (Section 10), not as an implicit side effect of a container starting — this is already how the compose file is shaped; the gap was only that no pipeline exercised it end-to-end before Section 8's `compose-validate` job.

## 12. Secrets Strategy

Keep the existing two-file model (compose-level `.env`, app-level `apps/api/env/.env.production`) — it already fails closed via `${VAR:?required}` and `Settings._guard_non_development_config`. Add:

- **CI secrets** (GitHub Actions secrets, scoped to the repo or a GitHub Environment): a deploy SSH key (if the deploy job SSHes to the VPS), `GITHUB_TOKEN` for GHCR push (automatic, no setup needed). Nothing else needs to live in GitHub for CI/CD purposes — CI's own tests use synthetic, CI-only credentials already (visible in `ci.yml` today: `JWT_ACCESS_SECRET: ci-test-access-secret-min-16`), which is correct and should stay that way.
- **Production secrets** stay exactly where they are: on the VPS, in the two gitignored `.env` files, never in GitHub, never baked into an image (confirmed — neither Dockerfile `COPY`s an env file; both `.dockerignore`s explicitly exclude `.env*`).
- **No external secret manager recommended.** For a two-file, single-VPS, fail-closed-at-boot model with roughly a dozen secrets total, HashiCorp Vault or a cloud secrets manager would be pure overhead — it would add a new always-on service to run and secure for a problem this project doesn't have yet. Revisit only if the team grows past a size where "the ops person's password manager" stops being an adequate source of truth for who can see what.
- **PII_MASTER_KEY** stays exactly as documented (generated once, stored off-VPS in a password manager/vault, never exported by the app, no backup/escrow mechanism by design) — the one actual gap here is G8: nobody is named as the owner. That's a decision for the user, not something this plan can invent (Section 24).

## 13. Backup Strategy

Scripts already exist and work (`infra/backup/{pg,minio}_backup.sh` + restores). This plan adds the parts that turn "a script that works when you run it" into "a system":

1. Install a real crontab via the VPS provisioning script (Section 16) — nightly `pg_backup.sh`, `minio_backup.sh` 30 minutes later (matches the existing doc's own recommendation, keeps the two backups close enough in time to limit the documented Postgres/MinIO consistency gap).
2. Add encryption at rest for the backup archive itself (age or gpg, one extra pipeline step in each script) before anything leaves the VPS.
3. Add an off-VPS copy via `rclone`. Recommend **Backblaze B2** (S3-compatible, no AWS, ~$6/TB/month, free egress up to 3x stored volume/month) as the default suggestion — final choice is Section 24, not decided here.
4. Retention stays as currently configured (14 days default via `PG_BACKUP_RETENTION_DAYS`/`MINIO_BACKUP_RETENTION_DAYS`) unless the user wants it longer once off-VPS storage is cheap.

## 14. Monitoring Strategy

Deliberately small, matching "don't over-engineer a single VPS":

- **External uptime**: a free-tier external monitor (UptimeRobot or Better Stack free tier) polling `/health/ready` and the web login page from outside the VPS — the only way to detect "the whole VPS is unreachable," which nothing self-hosted can see.
- **Host/container metrics**: a single self-hosted Netdata container (zero-config, has its own free cloud dashboard) rather than standing up Prometheus+Grafana+node-exporter+cAdvisor as four more services to patch on the one box that's supposed to be simple.
- **Error tracking**: Sentry's free SaaS tier (5,000 events/month) rather than self-hosting Sentry, which is itself a multi-service stack heavier than the app it would monitor. Requires explicit configuration to scrub PII before anything is sent — flagged as a decision, not assumed acceptable (Section 24).
- **Backup freshness**: a dead-man's-switch style check (Healthchecks.io free tier — the backup cron pings it on success; silence past the expected window pages someone) — directly closes the "a backup job that says success but never actually ran" risk named in the user's original ask.
- **SSL expiry**: certbot already auto-renews; most free uptime monitors (including UptimeRobot) include certificate-expiry checks for free, so no separate tool needed.

## 15. Logging Strategy

`docker-compose.prod.yml` already has rotation configured for every service (`json-file`, `max-size: 10m`, `max-file: 5`, via a shared `x-logging` anchor) — this is sufficient at single-VPS scale and is not being replaced with ELK/Loki/etc., which would be new infrastructure to secure for a problem (log volume) this deployment doesn't have. The existing, tested guarantee that secrets/PII never appear in logs (verified today via targeted tests, e.g. the SMTP-password-never-logged test from Phase 5A) should be extended with one CI check: a grep-based scan of a sample test run's log output for known secret patterns, so a future regression is caught mechanically instead of relying on someone remembering to write another targeted test.

## 16. VPS Provisioning

**Recommend an idempotent shell script**, not Ansible. Reasoning: one VPS, a 1–2 person team, and the project's own existing convention is already plain shell (`infra/backup/*.sh`, `scripts/dev.sh`) — introducing a control-node/inventory/YAML-templating tool for a single target host adds a new thing to learn and maintain without a corresponding benefit. A versioned `infra/provision/bootstrap.sh`, idempotent (safe to re-run), covering: Ubuntu LTS baseline, `ufw` firewall (only 80/443/SSH open), SSH hardening (key-only, no root login), `fail2ban`, `unattended-upgrades`, Docker + Compose plugin install, a dedicated non-root deploy user, the app/secrets/backup directory layout `PRODUCTION_DEPLOYMENT.md` already assumes, and log rotation config. This directly closes **VPS-01**.

## 17. Infrastructure-as-Code Decision

No Terraform. There is no cloud-provider API surface to manage beyond, at most, DNS records for a single VPS — Terraform would be managing near-zero real resources while adding its own state file, backend, and drift-detection concerns to operate. The shell provisioning script in Section 16 is the right-sized tool for "one VPS, reproducibly configured."

## 18. Branching Strategy

Keep trunk-based development (`main` + short-lived feature branches) — no change to the model itself. The actual change is starting to *use* PRs: the current git history is linear with no merge commits, meaning everything has gone straight to `main` without review or a CI gate. Recommend: feature branch → PR → CI green → review → squash-merge → tag a release. This is the process prerequisite for Section 19's release flow to mean anything, and it's also the only way to eventually attach required-status-checks branch protection once Section 24's GitHub Pro decision is made.

## 19. Release Strategy

```
feature branch → PR → CI (api, web, security-scan, docker-build,
  compose-validate) → review → squash-merge to main → tag (vYYYY.MM.DD or
  semver) → build+push images tagged with commit SHA → manual deploy approval
  → VPS deploy → migrate → health checks → smoke test → monitor for the
  following hour before considering the release final
```

Release checklist (concrete, not generic): confirm CI green on the merge commit; confirm the previous production `IMAGE_TAG` is recorded somewhere retrievable (Section 10); confirm no pending Alembic migration is destructive/irreversible without a fresh backup taken first; confirm `apps/api/env/.env.production` and root `.env` haven't silently drifted (the two-file secrets model has no automatic consistency check today — worth a small script, not a big one).

## 20. Rollback Strategy

**Application rollback**: trivial by design, because `docker-compose.prod.yml` already parameterizes `IMAGE_TAG`. Re-run the deploy sequence with the previous known-good SHA; `docker compose up -d` recreates only the containers whose image actually changed.

**Database rollback**: explicitly **not** promised as automatic, matching the existing `DISASTER_RECOVERY.md` stance and Postgres' own DDL semantics — a failed migration rolls back cleanly (transactional), but a *successful* migration that the application then needs to walk back requires an operator decision: forward-fix with a new migration, or restore from the most recent backup and accept the resulting data loss window. This plan formalizes that decision tree in the deployment runbook rather than inventing an automatic schema-rollback mechanism the codebase doesn't have and that would be genuinely risky to bolt on for a system doing financial (payroll) calculations.

## 21. Disaster Recovery

Already substantially documented in `docs/deployment/DISASTER_RECOVERY.md` (full-VPS-loss survival table, Postgres/MinIO restore steps, PII_MASTER_KEY-loss consequences, a quarterly recovery-drill checklist). What this plan adds is making the DR doc's own recommendations actually happen on a schedule: real crontab (Section 13), automated restore verification (build a scheduled job — run *on the VPS itself*, not by pulling PII into a GitHub Actions runner — that restores the latest backup into a disposable local container, checks row counts, and decrypts one known PII field to prove `PII_MASTER_KEY` round-trips end to end), and finally *measuring* RTO/RPO once instead of leaving them as "UNVERIFIED," which is their current, explicitly-stated status.

## 22. Security Controls

Already strong at the application layer (see Section 2's RLS/auth/PII-encryption summary, and Phases 2/3A/5A's closed findings: SEC-05 through SEC-11 mostly closed, MFA and a couple of rate-limit coarseness items explicitly and knowingly deferred). This plan's additions are all at the pipeline layer, since that's the layer with zero current coverage: secret scanning (Gitleaks), dependency scanning (`pip-audit`, `npm audit`), container image scanning (Trivy), Dockerfile linting (Hadolint), and the compose-boot smoke test that exercises RLS/tenant isolation against the real production shape of the stack, not just the CI-container approximation of it.

## 23. Cost Estimate

Everything below is *incremental* to whatever the VPS itself already costs (unknown to this plan — not something visible in the repo):

| Item | Choice | Monthly cost |
|---|---|---|
| Container registry | GHCR (private) | $0 |
| CI minutes | GitHub Actions, current usage well under the free private-repo allowance | $0 (watch for overage if usage grows) |
| Uptime monitoring | UptimeRobot / Better Stack free tier | $0 |
| Host metrics | Self-hosted Netdata | $0 |
| Error tracking | Sentry free tier (5k events/mo) | $0 |
| Backup-freshness heartbeat | Healthchecks.io free tier | $0 |
| Off-VPS backup storage | Backblaze B2 (likely well under 1TB at this data size) | ~$1–3 |
| Domain (if not already owned) | any registrar | ~$1 (amortized) |
| **Optional:** GitHub Pro (branch protection) | — | ~$4 |
| **Optional:** staging VPS | e.g. Hetzner CX22-class | ~$5–6 |
| **Total (no optionals)** | | **≈ $2–4/mo** |
| **Total (with both optionals)** | | **≈ $11–15/mo** |

No AWS anywhere in this estimate, per the stated constraint. This is a genuinely cheap plan — the honest cost of closing G0–G10 is almost entirely *time*, not money.

## 24. Open Decisions Requiring Approval

In priority order:

1. **The 27 unpushed commits.** Before any CI gate can mean anything, does the user want to: (a) run the full local test suite (`python run_full_tests.py`) to confirm current `main` actually passes, then push everything to `origin/main` and let CI run for real for the first time in three weeks; or (b) something else? Nothing downstream of this plan has value until this is resolved.
2. **Branch protection**: upgrade to GitHub Pro (~$4/mo, unlocks required-status-checks branch protection on a private repo) vs. relying only on GitHub Environments' required-reviewer gate (available today, but gates *deploys*, not *merges*) vs. making the repo public (not recommended — no upside, and the codebase includes PII-handling logic) vs. accepting process discipline without technical enforcement for now.
3. **Container registry**: confirm GHCR (recommended) vs. Docker Hub vs. self-hosted vs. build-on-VPS.
4. **Deployment trigger**: confirm hybrid/manual-approval (recommended) vs. full-auto vs. auto-to-staging/manual-to-prod once staging exists.
5. **Off-VPS backup destination**: Backblaze B2 (recommended) vs. a second VPS vs. Hetzner Storage Box vs. other — and confirm no AWS S3, consistent with the stated architecture preference.
6. **Backup restore-verification location**: run on the VPS itself (recommended — keeps PII in existing custody) vs. pulling data into a GitHub Actions runner (faster to build, but moves PII off the VPS into a third party's compute for the duration of the check).
7. **Monitoring stack acceptance**, specifically Sentry SaaS: acceptable to send scrubbed error data to a third party, given the PII-handling stance elsewhere in the system? (Self-hosting Sentry is the alternative, at real operational cost.)
8. **Domain name and DNS**: has one actually been purchased/pointed at the VPS yet? Real Let's Encrypt/ACME issuance has never been exercised (Phase 3B tested only against a non-public setup) — this blocks any real TLS validation regardless of anything else in this plan.
9. **PII_MASTER_KEY custody**: who is the named human owner? This is currently unassigned in every audit doc that raises it (Phase 6/6A both flag it as open).
10. **Staging environment**: approve the recurring cost of a second VPS, or defer and continue validating against production directly (current state) or against a developer's laptop?
11. **SAST/CodeQL**: worth the GitHub Advanced Security cost for a private repo at this team size, or defer?
12. **Container/dependency scan severity gate**: report-only for an initial period vs. blocking merges on HIGH/CRITICAL findings from day one?
13. **`compose-validate` job scope**: run on every PR (slower CI, zero detection lag on infra regressions) vs. path-filtered + nightly (faster CI, small lag)?
14. **Repo root hygiene** (G10): confirm `mavericks-kit.zip`, `shirt.png`, `shorts.png`, `work done/` are fine to leave alone, or should they be removed/gitignored as a small housekeeping item alongside this work?

---

## 25. Implementation Phases

Each phase below lists Objective, Files affected, Infrastructure affected, Secrets required, GitHub configuration required, Commands, Tests, Verification, Rollback, Risk, and Expected output, as requested. Phases are ordered by dependency, not by the numbering in the original brainstorm — Phase 0 gates everything else.

### Phase 0 — Reality check (prerequisite, human-decision-gated)
- **Objective:** Confirm current `main` actually passes its own quality gates, then get it onto `origin/main` so CI can run for the first time in three weeks.
- **Files affected:** none (no code changes required — purely a push, pending Decision 1).
- **Infrastructure affected:** none.
- **Secrets required:** none beyond existing git push credentials.
- **GitHub configuration required:** none.
- **Commands:** `python run_full_tests.py` (full run); if green, `git push origin main` (only on explicit approval — this plan does not push anything itself).
- **Tests:** the full local suite, as the pre-push gate.
- **Verification:** GitHub Actions shows a new, green run against the pushed SHA.
- **Rollback:** none needed — pushing existing, already-committed history is not a destructive action, but it is still gated on explicit approval per this plan's own instructions.
- **Risk:** low technically; the only risk is discovering, three weeks late, that something in the unpushed work doesn't actually pass CI — better to find that now than later.
- **Expected output:** `origin/main` == local `main`; a green (or informatively red) CI run against real, current code.

### Phase A — CI foundation (frontend lint + build, dependency/secret scanning)
- **Objective:** Close G5 and G7; bring CI to parity with (and slightly beyond) what `run_full_tests.py` already does locally.
- **Files affected:** `.github/workflows/ci.yml`; new `apps/web/eslint.config.mjs` + `eslint-config-next` dependency in `apps/web/package.json`.
- **Infrastructure affected:** none.
- **Secrets required:** none.
- **GitHub configuration required:** none.
- **Commands:** `npm install eslint eslint-config-next --save-dev` (in `apps/web`); new CI steps `npx eslint .`, `npm run build`; new `security-scan` job running `gitleaks detect`, `uv run pip-audit`, `npm audit --audit-level=high`.
- **Tests:** the new steps are themselves the tests — a PR that introduces a lint error, a build break, or a scanned dependency CVE should fail exactly that step.
- **Verification:** open a throwaway PR with a deliberate lint violation to confirm the gate actually fires, then close it.
- **Rollback:** revert the `ci.yml` diff; no production impact either way, this is CI-only.
- **Risk:** low. Main risk is ESLint surfacing a real backlog of existing violations — budget time to fix or selectively disable rules rather than blocking merges on day one.
- **Expected output:** four CI checks where there were two; `security-scan` report-only for its first week.

### Phase B — Docker CI
- **Objective:** Build and lint both Dockerfiles on every relevant PR; close half of CI-02.
- **Files affected:** `.github/workflows/ci.yml` (new `docker-build` job).
- **Infrastructure affected:** none (build-only, no push yet).
- **Secrets required:** none.
- **GitHub configuration required:** none.
- **Commands:** `docker build -f apps/api/Dockerfile apps/api`, `docker build -f apps/web/Dockerfile apps/web`, `hadolint apps/api/Dockerfile apps/web/Dockerfile`, `trivy image <built-tag>` (report-only initially).
- **Tests:** the build itself; a deliberately broken Dockerfile in a test PR to confirm the gate fires.
- **Verification:** job appears green on the next real PR touching either Dockerfile or its lockfile.
- **Rollback:** revert the workflow diff.
- **Risk:** low; mainly CI-minutes cost (Docker builds are slower than the existing jobs — path-filter this job to only run when relevant files change).
- **Expected output:** every Dockerfile change is now build-tested before merge.

### Phase C — Compose validation (closes the other half of CI-02 — highest-value phase)
- **Objective:** A CI job that boots the real production compose shape (minus nginx/certbot) against disposable secrets, runs `migrate`, waits for every healthcheck, and smoke-tests tenant isolation — the exact class of check that would have caught DB-01.
- **Files affected:** `.github/workflows/ci.yml` (new `compose-validate` job); possibly a small `infra/ci/compose-validate.env.example` for the disposable/generated env.
- **Infrastructure affected:** none in production — entirely disposable, ephemeral GitHub Actions runner infrastructure.
- **Secrets required:** none real — generated random values per run.
- **GitHub configuration required:** none.
- **Commands:** `docker compose -f docker-compose.prod.yml config`; `docker compose -f docker-compose.prod.yml up -d postgres redis minio minio-init api worker beat web`; `docker compose -f docker-compose.prod.yml --profile tools run --rm migrate`; health-check polling loop; `curl -f .../health/ready`; a scripted smoke test hitting the real API to create two test companies and assert cross-tenant isolation; `docker compose -f docker-compose.prod.yml down -v`.
- **Tests:** the boot sequence and smoke test are the tests. Deliberately reintroduce a DB-01-shaped bug in a test branch first, to prove this job actually catches it, then revert.
- **Verification:** the reintroduced-bug test PR fails this job; a clean PR passes it.
- **Rollback:** revert the workflow diff; zero production risk either way.
- **Risk:** medium in effort (getting a nginx-less, ACME-less version of the stack to boot cleanly in CI takes some iteration), low in downside — it's fully disposable.
- **Expected output:** the job that directly answers "would this have caught DB-01" — expected answer, once built: yes.

### Phase D — Container registry + image tagging
- **Objective:** Push built images to GHCR on merge to `main`, tagged by commit SHA; stop relying on `latest`.
- **Files affected:** `.github/workflows/ci.yml` (new `build-and-push` job, triggered on `push` to `main` only); no change needed to `docker-compose.prod.yml` (`${IMAGE_TAG}` already exists).
- **Infrastructure affected:** GHCR (new, but zero-config beyond enabling package write on the existing token).
- **Secrets required:** none new — `GITHUB_TOKEN` already has the needed scope for GHCR when granted `packages: write` permission in the workflow.
- **GitHub configuration required:** confirm repo package visibility settings for GHCR (private, matching the repo).
- **Commands:** `docker buildx build --push -t ghcr.io/<owner>/hrms-api:${{ github.sha }} ...` (and the same for `hrms-web`).
- **Tests:** confirm the pushed image is pullable and matches what CI just built.
- **Verification:** `docker pull ghcr.io/<owner>/hrms-api:<sha>` succeeds from a separate machine with appropriate GHCR auth.
- **Rollback:** delete the pushed package version if needed; no production impact until Phase F actually deploys from it.
- **Risk:** low.
- **Expected output:** every merge to `main` now produces a permanently retrievable, SHA-tagged image pair.

### Phase E — VPS provisioning script
- **Objective:** Codify and make reproducible whatever manual VPS setup currently exists; close VPS-01.
- **Files affected:** new `infra/provision/bootstrap.sh` (and a short `infra/provision/README.md`).
- **Infrastructure affected:** the production VPS (or, ideally, a fresh disposable VPS first, to prove the script from zero before trusting it against the real box).
- **Secrets required:** SSH access to the target VPS (operator-held, not stored anywhere new).
- **GitHub configuration required:** none.
- **Commands:** the script itself — `ufw`, SSH config hardening, `fail2ban`, `unattended-upgrades`, Docker + Compose plugin install, deploy-user creation, directory scaffolding.
- **Tests:** run against a fresh, disposable VPS first; confirm idempotency by running it a second time with no unexpected changes.
- **Verification:** `ufw status`, `sshd_config` diff, `docker compose version`, directory layout all match expectations on the test VPS.
- **Rollback:** this only ever adds hardening to a fresh box; if run against the *existing* production VPS, review the diff of every change before applying (this is the one phase in this plan that touches a live, already-running production host directly, so it gets extra scrutiny, not less).
- **Risk:** medium if run against the live VPS without first validating on a throwaway one — mitigated by testing on a disposable VPS first, as stated above.
- **Expected output:** a documented, versioned, re-runnable path from "fresh Ubuntu VPS" to "ready for `docker-compose.prod.yml`."

### Phase F — CD: deployment pipeline
- **Objective:** Turn Section 10's sequence into an actual, repeatable, approval-gated pipeline.
- **Files affected:** `.github/workflows/deploy.yml` (new); `infra/deploy/deploy.sh` (new, the actual pull/migrate/up/health-check/smoke-test sequence, runnable by hand or by the workflow).
- **Infrastructure affected:** the production VPS, for real, on approval.
- **Secrets required:** a deploy SSH key (new GitHub Actions secret, scoped to a GitHub Environment, not the whole repo).
- **GitHub configuration required:** a GitHub Environment (e.g. `production`) with a required reviewer.
- **Commands:** as in Section 10.
- **Tests:** first several runs should be manually shadowed (operator watches every step) before trusting it unattended.
- **Verification:** post-deploy `/health/ready` and smoke test, as specified in Section 10.
- **Rollback:** re-run with the previous SHA (Section 20).
- **Risk:** medium — this is the first phase with real production blast radius. Mitigate by requiring the manual approval gate from day one (Decision 4) and by not enabling this phase until Phases C and D have both been exercised successfully at least once.
- **Expected output:** a named, reviewable, one-command deploy path, replacing whatever manual process exists today.

### Phase G — Backup automation
- **Objective:** Close G3/G4 — real schedule, encryption, off-VPS copy, automated restore verification.
- **Files affected:** `infra/backup/pg_backup.sh`, `minio_backup.sh` (add an encryption + `rclone` upload step each); new crontab entries added by the Phase E provisioning script; new `infra/backup/verify_restore.sh`.
- **Infrastructure affected:** the VPS (cron), plus the chosen off-VPS storage target (Decision 5).
- **Secrets required:** an encryption passphrase/key (separate from `PII_MASTER_KEY`) and `rclone` credentials for the off-VPS target — both VPS-resident, never in GitHub.
- **GitHub configuration required:** none.
- **Commands:** existing backup scripts, extended; `crontab` entries; a scheduled (`cron` on the VPS, not GitHub Actions — Decision 6) restore-verification run.
- **Tests:** manually trigger a full backup → encrypt → upload → download → decrypt → restore-into-disposable-container → integrity check cycle once, before trusting the schedule.
- **Verification:** Healthchecks.io shows a green heartbeat after the first scheduled run; the off-VPS storage target shows the expected new object.
- **Rollback:** backups are additive by nature — no rollback risk; worst case is disabling the new cron entries and reverting to the pre-existing manual-only process.
- **Risk:** low technically, but real if secrets for the off-VPS destination are mismanaged — treat the `rclone` credential with the same care as any other production secret.
- **Expected output:** nightly backups, encrypted, copied off-VPS, with a monthly automated proof that they actually restore.

### Phase H — Monitoring & alerting
- **Objective:** Close the "how would we know" gap across uptime, host metrics, errors, and backup freshness.
- **Files affected:** `docker-compose.prod.yml` (add a `netdata` service); no code changes for Sentry beyond SDK initialization already possible in `apps/api`/`apps/web` (small, but real, application-level change — flagged here rather than pretending it's zero-touch).
- **Infrastructure affected:** the VPS (one new container); external free-tier SaaS accounts (UptimeRobot/Better Stack, Sentry, Healthchecks.io).
- **Secrets required:** a Sentry DSN, a Healthchecks.io ping URL — both low-sensitivity, but still handled as secrets, not committed.
- **GitHub configuration required:** none.
- **Commands:** `docker compose -f docker-compose.prod.yml up -d netdata`; SDK init calls; external monitor configuration (done in each tool's own dashboard).
- **Tests:** deliberately trigger a test error to confirm it reaches Sentry scrubbed of PII; deliberately skip a backup run to confirm Healthchecks.io actually pages someone.
- **Verification:** dashboards populate; test alerts fire.
- **Rollback:** remove the `netdata` service / SDK calls; no production risk.
- **Risk:** low, contingent on Decision 7 (Sentry SaaS acceptability).
- **Expected output:** a real signal, for the first time, when something breaks — instead of finding out from a user.

### Phase I — Branching, process, and release discipline
- **Objective:** Actually start using PRs; add branch protection if Decision 2 approves it; adopt release tagging.
- **Files affected:** none in code — this is process, plus optional GitHub repository settings.
- **Infrastructure affected:** none.
- **Secrets required:** none.
- **GitHub configuration required:** branch protection rules (pending Decision 2), a release-tagging convention.
- **Commands:** `git tag vYYYY.MM.DD && git push --tags` at each release point.
- **Tests:** none (process, not code).
- **Verification:** the next several merges to `main` actually go through a PR with a green CI run attached.
- **Rollback:** n/a.
- **Risk:** low — the main risk is this phase being skipped in practice, which is exactly the current state.
- **Expected output:** a git history with merge commits and tags, instead of the current unbroken direct-to-`main` line.

### Phase J — Staging environment (optional, cost-gated on Decision 10)
- **Objective:** A place to validate a release before it touches production.
- **Files affected:** a `docker-compose.staging.yml` (likely a light variant of `docker-compose.prod.yml` with a different domain set and no certbot dependency, or self-signed certs).
- **Infrastructure affected:** a second, smaller VPS.
- **Secrets required:** a full, separate secret set (never shared with production values).
- **GitHub configuration required:** a `staging` GitHub Environment, possibly without a required reviewer (faster iteration than `production`).
- **Commands:** the same deploy sequence as Phase F, pointed at the staging host.
- **Tests:** the same smoke tests as production, run first here.
- **Verification:** staging deploy succeeds and passes health/smoke checks before any production deploy is attempted for the same release.
- **Rollback:** trivial — it's not production.
- **Risk:** low technically; the only real cost is the monthly VPS bill (Section 23).
- **Expected output:** a genuine pre-production proving ground, closing G9.

### Phase K — Final DevOps audit
- **Objective:** Close the loop — run every failure scenario in Section 26 for real (in staging, if it exists), measure actual RTO/RPO instead of leaving them "UNVERIFIED," and produce a sign-off doc in the same style as the existing `RELEASE_HARDENING_PHASE_*` reports.
- **Files affected:** new `docs/audits/DEVOPS_AUDIT_<date>.md`.
- **Infrastructure affected:** whichever environment the drills run against (staging strongly preferred).
- **Secrets required:** none beyond what earlier phases already use.
- **GitHub configuration required:** none.
- **Commands:** the actual failure-scenario drills (kill a container, fill a disk, expire a cert on purpose in staging, etc.).
- **Tests:** the drills themselves.
- **Verification:** each drill's detection→response→recovery→verification loop (Section 26) is observed to actually work, not just documented as a plan.
- **Rollback:** n/a (this phase is itself verification).
- **Risk:** low if run in staging; do not run destructive drills against production without a very deliberate, separately-approved maintenance window.
- **Expected output:** a real, timed answer to "how long would recovery actually take," replacing the current honest "UNVERIFIED."

---

## 26. Failure Scenarios

| Scenario | Detection | Response | Recovery | Verification |
|---|---|---|---|---|
| Deployment fails mid-way | Health check / smoke test fails in the deploy pipeline (Phase F) | Pipeline halts before marking the deploy complete | Redeploy previous SHA (Section 20) | `/health/ready` green, smoke test passes |
| Docker image fails to build | `docker-build`/`build-and-push` CI job fails | Merge/deploy blocked automatically | Fix Dockerfile, retry | CI job green |
| Migration fails | `migrate` one-off service exits non-zero | Deploy pipeline halts before `up -d` (services never see the new schema) | Transactional rollback is automatic; operator decides forward-fix vs. restore | Re-run `migrate` after fix; confirm `alembic current` matches expected head |
| PostgreSQL unavailable | `/health/ready` 503; container healthcheck failing | `restart: unless-stopped` retries; alert via uptime monitor | Investigate container/volume; restore from backup only if data-lost, not just down | `/health/ready` green again |
| Redis unavailable | `/health/ready` 503; rate limiters already fail closed (503, per Phase 2's SEC-11 fix) | Same as above | Same as above | Same |
| MinIO unavailable | `/health/ready` config-check fails; upload/download endpoints error | Alert; investigate container/volume | Restore from `minio_restore.sh` if data-lost | Presigned URL round-trip succeeds |
| SMTP unavailable | Email send exceptions (currently swallowed silently — a known, pre-existing gap, not introduced here) | Recommend: promote silent `except Exception: pass` call sites to at least a logged warning, as a small follow-up, not a new phase | Fix provider config; queued sends (if any) retried | A test send succeeds |
| VPS reboot | Uptime monitor alert; all containers show `restart: unless-stopped` | Containers restart automatically on Docker daemon start | Confirm `beat` (no healthcheck) actually resumed, since it can't self-report | Manual `docker compose ps` check after any reboot |
| Disk nearly full | Netdata threshold alert (Phase H) | Alert before it's critical | Prune old Docker images/logs; expand volume; check backup retention isn't over-accumulating | Disk usage back under threshold |
| Certificate expires | Uptime monitor's SSL-expiry check; certbot's own renewal should prevent this happening at all | Investigate why auto-renewal didn't fire | Manual `certbot renew` | HTTPS check green |
| Backup fails | Healthchecks.io heartbeat missed (Phase G) | Immediate alert (this is the scenario Section 4/G3 exists to prevent) | Re-run backup manually; investigate cron/script failure | Next heartbeat green |
| Backup restore fails | Automated monthly restore-verification job (Phase G/K) fails | Alert — this is a critical finding, treat as urgent | Investigate backup integrity immediately; do not wait for a real disaster to discover this | Manual restore succeeds |
| Worker dies | `celery inspect ping` healthcheck fails | `restart: unless-stopped` | Confirm queued jobs resume; investigate root cause if repeated | Healthcheck green, queue drains |
| Beat dies | No healthcheck exists for `beat` (documented limitation) — only `restart: unless-stopped` as a safety net | Recommend: a lightweight external check that scheduled jobs are actually firing on schedule, as a small Phase H addition | `restart: unless-stopped` should self-heal; confirm manually otherwise | Scheduled job runs on time again |
| Application crashes | Container healthcheck fails; uptime monitor | `restart: unless-stopped` | Investigate logs; rollback if caused by the last release | Healthcheck + uptime monitor green |
| Bad release deployed | Smoke test fails post-deploy, or user reports | Immediate rollback to previous SHA (Section 20) | Root-cause in a follow-up PR, not under pressure | Previous behavior confirmed restored |
| GitHub Actions unavailable | CI/CD pipeline simply doesn't run | No merges/deploys go through until it recovers — this is a GitHub outage, not a repo problem | Wait, or fall back to a manual, documented deploy procedure (Phase F's `deploy.sh` is runnable by hand, deliberately) | GitHub status page; next CI run succeeds |

---

## 27. Summary for approval

**Current state:** a technically strong application sitting behind an inert CI pipeline (CI hasn't run in 3 weeks; 27 commits are unpushed) with a known, named, un-remediated gap (CI-02) that already caused one real production-blocking bug (DB-01) to ship undetected.

**Proposed architecture:** no replacement of anything — Docker Compose, Postgres, Redis, MinIO, and the existing two CI jobs all stay. New: Docker/compose-boot CI validation (the direct fix for CI-02), dependency/secret/container scanning, GHCR for immutable image tags, a manual-approval deploy pipeline, a real backup schedule with off-VPS copy and automated restore verification, and a deliberately small monitoring stack — all chosen to stay within "no AWS, no Kubernetes, self-hosted/low-cost."

**Major gaps closed:** G0 (unpushed commits) through G10 (repo hygiene), Section 4.

**Implementation phases:** 0 (prerequisite) → A → B → C (highest-value) → D → E → F → G → H → I → J (optional) → K, Section 25.

**Estimated cost:** ≈ $2–4/month with no optional items, ≈ $11–15/month with GitHub Pro and a staging VPS both approved — Section 23.

**Decisions needed before implementation starts:** Section 24, fourteen items, led by what to do about the 27 unpushed commits.

This plan stops here, per Phase A instructions. No files besides this one were created; nothing was installed, committed, or pushed.
