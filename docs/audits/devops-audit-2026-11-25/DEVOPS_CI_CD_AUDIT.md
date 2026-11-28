# CI/CD audit

Audit date: 2026-11-25. Workflows read: `.github/workflows/ci.yml`, `.github/workflows/auto-merge.yml`. Latest CI evidence: GitHub Actions run `45608524544` on commit `de832746ea48606dd83fd141bc81f8bfc31804c8`, event `pull_request`, conclusion success, duration 51m21s. All six jobs succeeded. An earlier run the same day, `45607300779`, failed and a later run went green, which is the expected fail-then-fix behaviour.

No deploy workflow exists.

## 1. Workflow catalogue

### CI

| Field | Value |
|---|---|
| Name | CI |
| Trigger | `pull_request` targeting `main` only. No push trigger, no schedule, no `workflow_dispatch` |
| Why no push on `main` | Comment in the file: merges arrive through a PR, so a second run would repeat the same checks. A direct push to `main` would not run this workflow at all |
| Permissions block | Absent. Repository default workflow token is `read` (`actions/permissions/workflow`) |
| Concurrency limit | None |
| Job timeouts | None (`timeout-minutes` absent). GitHub default is 360 minutes |
| Secrets used | None. Database and MinIO credentials are the repository-visible development values |
| Runner | `ubuntu-latest` for every job |
| Artifact retention | 14 days requested. Upload steps are `continue-on-error: true` because the account artifact quota is exhausted |

Jobs, in parallel (no `needs:`):

| Job | What it runs | Services | Failure behaviour |
|---|---|---|---|
| `api` | Contract fixture freshness, ruff, ruff format, mypy, import-linter, Postgres init scripts, `alembic upgrade head`, `hrms_app` role assertion, RLS harness tests, unit tests, disposable MinIO, integration and security tests | `postgres:16-alpine` on 5433, `redis:7-alpine` on 6380, MinIO via `docker run` of `pgsty/silo@sha256:635197cb9f36…` | Any step except artifact upload fails the job. MinIO is removed with `if: always()` |
| `migrations` | `tests/integration/migrations/test_attendance_r2_migrations.py` and `tests/unit/core/test_migration_test_guards.py` with `HRMS_QA_STRICT=1` and `HRMS_REQUIRE_MIGRATION_TESTS=1` | Separate Postgres on `127.0.0.1:15432`, Redis on `127.0.0.1:16379` | A skip fails the job. A leftover scratch database fails the job |
| `web` | `npm ci`, ESLint, `next typegen`, `tsc --noEmit`, Vitest JUnit, `next build --webpack` | None | ESLint does not fail the job. Typecheck, tests, and build do |
| `mobile` | `flutter pub get`, `flutter analyze`, `flutter test` at Flutter 3.29.2 | None | Analyze or test failure fails the job. Live tests skip without their env |
| `security-scan` | `docker run zricethezav/gitleaks:latest detect --no-git --redact --config=/repo/.gitleaks.toml` | None | A finding fails the job |
| `dependency-scan` | `uv export` plus `uvx pip-audit`, then `npm ci` and `npm audit --omit=dev --audit-level=high` | None | A production advisory at high or critical fails the job |

Caching: `setup-uv` caches `apps/api/uv.lock`. `setup-node` caches `apps/web/package-lock.json`. `flutter-action` has `cache: true`.

Test reporting: JUnit XML is written for API unit, API integration, migrations, and Vitest. Upload is best-effort and currently expected to fail open. The job summary is a static sentence, not a parsed count.

Coverage: not collected and not gated.

Flaky tests: the MinIO client setup retries 10 times because of a startup race recorded on 2026-09-28 (run `36368896052`). That is a documented race with a retry, not an ignored failure. No other quarantine list was found.

### Auto-merge

| Field | Value |
|---|---|
| Name | Auto-merge |
| Trigger | `workflow_run` of CI completed |
| Token scope at workflow level | `permissions: {}` |
| Job permission | `contents: write`, `pull-requests: write`, and only when CI succeeded, the event was `pull_request`, the head branch is `test`, and the head repository is this repository |
| Checkout of PR code | None |
| Sensitive paths | `.github/`, `.gitleaks.toml`, `AGENTS.md`, `CLAUDE.md`, `apps/api/alembic/` cause a comment and exit 0 |
| Merge | `gh pr merge --merge --match-head-commit` of the tested SHA |
| Follow-up | Fast-forward `test` to the merge commit. Failure becomes a warning |

Recent evidence: several auto-merge runs on 2026-11-25 completed in 6 to 14 seconds. PR #81 remains open with a bot comment naming the Alembic file. That is the workflow working as written, not a stuck deploy.

## 2. Are the three platforms tested?

Yes, on every pull request into `main`.

| Platform | Gate | Gap |
|---|---|---|
| API | Lint, types, boundaries, unit, integration, security, migrations | No image build. No coverage floor. Celery is tested as code (unit and some integration tests exist under `apps/api/tests`) but CI does not start a worker process and assert a scheduled task runs |
| Web | Types, Vitest, webpack production build | ESLint does not fail CI. No Playwright or browser pass in CI |
| Mobile | Analyzer and `flutter test` | No device or emulator run. Contract fixtures are checked from the API job by regenerating them and failing if `apps/mobile/test/fixtures/contract` changes |

Integration paths that are covered: HTTP tests against the app with a real database, Redis, and S3-compatible storage; RLS with the unprivileged role; Alembic upgrade from empty; a focused migration suite that is allowed to create and drop databases on a throwaway server.

Integration paths that are not covered in CI: the production Compose file booting, host nginx config, backup scripts, the monitor script against a real stack, Celery Beat firing, FCM, and the live mobile suite.

Redis-dependent tests are included. The API job sets `REDIS_URL=redis://localhost:6380/0` and the service has a health check. Celery workers and Beat are not started as CI services.

Database migrations are tested against real PostgreSQL 16, twice: once as `alembic upgrade head` before the main suite, and once in the isolated migration job. They are not tested against a copy of production data.

## 3. Can CI report success incorrectly?

| Path | Effect |
|---|---|
| ESLint errors | Job stays green. Documented. A lint regression will not block a merge |
| Artifact upload failure | Job stays green. Tests have already run |
| Gitleaks `--no-git` | A secret that exists only in history and not in the tree will not fail the PR |
| Gitleaks allowlist | Named test files and one planning doc are excluded. A new test file is still scanned. The allowlist is narrow and commented |
| `gitleaks:latest` | A bad upstream tag could fail the job or, worse, change detection behaviour without a commit in this repo |
| Migration job scope | It runs two test modules, not every migration file. A new migration is applied by the API job's `alembic upgrade head`, which is a real gate, and is not automatically added to the strict migration suite |
| Direct push to `main` | CI does not run. Auto-merge does not run. The commit is on the release branch with no check |
| Fork pull request | CI runs with a read token and no production secrets. The workflow does not use `pull_request_target`. This is the safer default |

Tests run on the pull request head SHA. Auto-merge passes `--match-head-commit` of `workflow_run.head_sha` and re-reads the PR head. A newer push is left alone. The tested commit is the merged commit's parent, which is the right relationship. Production does not deploy that commit, so the guarantee stops at `main`.

## 4. Delivery and deployment

| Capability | Status |
|---|---|
| Automated image build | Missing in CI. Manual on the VPS (`docker compose build`) |
| Image tagging | `IMAGE_TAG` defaults to `latest` in both prod compose files. Server images are `hrms-api:latest` and `hrms-web:latest` |
| Registry | Missing |
| Artifact retention for images | Local Docker tags only. The web runbook tags `hrms-web:pre-web-<timestamp>` before a web rebuild. No retention policy |
| Staging | Missing |
| Production automation | Missing |
| Approval gate | The Alembic/GitHub hold on auto-merge is an approval before code reaches `main`. It is not an approval before code reaches the VPS |
| Health check after deploy | Manual curls in the web runbook. Container `HEALTHCHECK` instructions exist and the running web, API, and worker report healthy |
| Migration execution | Documented as `docker compose … --profile tools run --rm migrate`. Not observed during this audit. Live head shows migrations stopped at `20261108090000` |
| Restart orchestration | Manual. Web procedure restarts only `web`. A full release must restart `api`, `worker`, and `beat` on the same image or they will diverge. Nothing enforces that |
| Automatic rollback | Missing |
| Notifications | Missing |

Manual commands that remain: `ssh` as root, `scp` or `patch` into `/opt/hrms`, `docker compose -f docker-compose.vps.yml build`, `up -d`. The web document is explicit that API, worker, Beat, Postgres, Redis, and MinIO must not be restarted for a frontend-only change. That is a good constraint for a web-only patch and a dangerous one if someone uses that document for an API change.

## 5. CI security

| Control | Finding |
|---|---|
| Workflow token | Default read. Auto-merge elevates to contents and pull-request write only inside its job, and only for a same-repo `test` head |
| Production secrets in CI | Not referenced. A malicious PR cannot print `apps/api/env/.env.production` because that file is not in the repository and is not a GitHub secret |
| `pull_request_target` | Not used |
| Third-party actions | `actions/checkout@v4`, `astral-sh/setup-uv@v5`, `actions/setup-python@v5`, `actions/setup-node@v4`, `actions/upload-artifact@v4`, `subosito/flutter-action@v2`. All floating major tags. `sha_pinning_required` is false. `allowed_actions` is `all` |
| Gitleaks image | Floating `latest` |
| MinIO images in CI | Pinned by digest. Matches `docker-compose.prod.yml` and `docker-compose.vps.yml` |
| Environment protection | No environments, so no required reviewers |
| Fork access to credentials | No deploy credentials exist in GitHub to steal. The residual risk is a compromised action on a future workflow that does hold a deploy key |
| Provenance | Images are built on the VPS from whatever files are in `/opt/hrms`. There is no attestation |

The path from an untrusted pull request to production credentials is currently closed, because production credentials are not in GitHub. The path from an untrusted pull request to `main` is closed only if nobody merges by hand and nobody pushes `main`. The path from `main` to production is a person with the root SSH key. That key is the production credential, and it does not appear in CI.

## 6. Supply chain notes

- Python dependencies are locked (`uv.lock`) and audited.
- npm production dependencies are locked and audited at high severity.
- npm dev dependencies are explicitly not a gate (comment references P3-05).
- Container base images `python:3.12-slim` and `node:20-alpine` are not pinned by digest.
- `postgres:16-alpine`, `redis:7-alpine`, and `nginx:1.27-alpine` are minor-floating tags.
- `certbot/certbot:latest` and dev `pgsty/silo:latest` / `pgsty/mc:latest` are floating.
- No Trivy, Grype, or Docker Scout step.
- No SLSA provenance, no cosign.

## 7. What "CI passed" does not mean

CI passed on `de83274` means the API test suite, the migration job, the web build, the mobile tests, the secret scan, and the dependency scan succeeded on GitHub-hosted runners. It does not mean a container starts with `docker-compose.vps.yml`, it does not mean the live database can migrate from `20261108090000`, and it does not mean `www.krewoxa.com` is running that commit. It is not.
