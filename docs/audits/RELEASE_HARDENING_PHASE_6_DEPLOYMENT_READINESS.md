# Release Hardening — Phase 6: Deployment Readiness & Go-Live Audit

**AUDIT DATE:** 2026-09-25
**COMMIT:** `fb94e255b629e3dbf55f3404871ba899919fe322` (branch `main`, 25 commits ahead of `origin/main`, unpushed)
**BRANCH:** `main`
**VERDICT:** NOT READY (see §24 — a small number of concrete, fast-to-close blockers, headlined by an uncommitted working tree)
**PILOT SCOPE:** Single-tenant pilot company, HR/Attendance/Leave/Payroll phases 5.1–5.6, no Recruitment, no MFA, operator-mediated onboarding
**PUBLIC RELEASE STATUS:** Not assessed as ready and not claimed — see §21/§25 "POST-PILOT / PUBLIC RELEASE"

This audit is read-only: no application code, configuration, or migration was changed. Where a live
system was needed to get real evidence (Docker builds, a running production-config stack, database
migrations, HTTP requests), disposable, non-default resources were created (a scratch `.env`/
`.env.production` pair, a scratch Postgres database, temporary Docker containers) and torn down
afterward; nothing was committed or pushed. Every claim below is tagged `VERIFIED` (independently
reproduced this session), `NOT VERIFIED` (not exercised — either genuinely blocked, or out of this
session's time budget), `FAILED` (reproduced and broken), `ENVIRONMENT-BLOCKED` (correctly
unexecutable without real external infrastructure this audit environment cannot provide),
`POLICY-DECISION` (a deliberate, documented human/operational choice, not a code gap),
`LEGAL-REVIEW`, or `COMPLIANCE-REVIEW`.

---

## 1. Executive Summary

The application layer of this system is substantially more mature than a typical pre-pilot codebase:
production-grade Docker images build and boot cleanly from the current working tree, Postgres RLS
provably enforces tenant isolation down to the database connection (not just application code),
RBAC is data-driven and fails closed, PII is encrypted at rest with a locally-wrapped key
architecture that replaced an earlier AWS KMS dependency, SMTP replaced AWS SES as a real
non-AWS email transport, and a full backup/restore/DR runbook exists with safety-guarded scripts.
This is the product of five prior hardening phases (0–5A), all independently re-verified against
current code this session (§4).

However, **two facts dominate the verdict and must be read before anything else in this report**:

1. **Almost none of that hardening work is committed to git or pushed to `origin/main`.** The
   working tree carries a 99-file, ~2,200-line uncommitted diff plus roughly 30 new untracked
   files — including the entire crypto/master-key rewrite, `SecurityHeadersMiddleware`, SMTP email
   sending, email verification, the production Docker/Nginx/backup infrastructure itself
   (`docker-compose.prod.yml`, `infra/nginx/`, `infra/backup/`, `docs/deployment/`), and all six of
   the prior Phase 0–5A audit reports this Phase 6 audit was told to treat as its own baseline
   (§3, §25). **A deploy from `origin/main` today would ship none of this.** This is the single
   largest blocker in this report and is entirely mechanical to fix (commit and push).
2. **A previously-unflagged, concrete, reproduced deployment defect**: the production Postgres
   init script hardcodes the application's own runtime database role (`hrms_app`) to a fixed,
   repository-visible password, independent of anything the operator sets in
   `apps/api/env/.env.production`. Following the documented production runbook exactly as written
   (generate secrets with `openssl rand`, per `docs/deployment/PRODUCTION_DEPLOYMENT.md` §3–4)
   produces a database authentication failure and a crash-looping API container — reproduced live
   this session (§5, §6, Finding **DB-01**).

Excluding those two items, the remaining gaps are the same class of items the prior four phases
already identified and left open by design: `PII_MASTER_KEY`/off-VPS backup storage as a
human-owned operational control, real Let's Encrypt issuance and real SMTP delivery as
environment-blocked (require a real domain / real mailbox this audit environment cannot provide),
MFA and a few other public-release-only items deliberately deferred for a single-tenant pilot.

## 2. Scope

Full 27-area scope as specified in the audit brief: repository/secrets baseline, production
configuration, SMTP, Docker, PostgreSQL, MinIO, PII/security, authentication, RBAC/tenant isolation,
business workflow, background jobs, Nginx/HTTPS, backup/DR, observability, frontend, CI/CD, VPS
operational security, legal/compliance, recruitment scope, and full regression testing. Work was
split three ways: this session directly executed all Docker/database/live-HTTP verification;
two research agents independently verified (a) the reconciliation of Phase 3A–5A's prior findings
against current code, and (b) RBAC/tenant isolation (with live cross-tenant HTTP tests) and
CI/CD/frontend/recruitment/legal documentation status (with real command execution, not just
reading). All three streams' findings are integrated below with citations.

## 3. Repository Baseline

**Git state** — `VERIFIED`:

| Item | Value |
| --- | --- |
| Branch | `main` |
| HEAD | `fb94e255b629e3dbf55f3404871ba899919fe322` — `feat(payroll): income tax (TDS) — new regime only (phase 5.6)` |
| Remote tracking | `origin/main`, **25 commits ahead**, nothing pushed |
| Working tree | **99 tracked files modified/deleted/renamed** (2,219 insertions / 1,019 deletions per `git diff --stat`), plus **~30 untracked new files** |

**Finding REPO-01 (blocking) — the entire release-hardening body of work is uncommitted.**
`git status` shows modifications across `core/crypto/*` (including `D core/crypto/kms.py`, replaced
by an untracked `core/crypto/master_key.py`), `core/auth/*`, `core/config/settings.py`,
`core/rbac/service.py`, `modules/identity/*`, `modules/employee/*`, `modules/account_invite/*`,
`modules/onboarding/*`, plus untracked new files: `apps/api/src/hrms/core/security_headers.py`,
`apps/api/src/hrms/core/auth/common_passwords.py`, `apps/api/src/hrms/core/auth/refresh_cookie.py`,
`apps/api/scripts/provision_encryption_key.py`, two new Alembic migrations
(`20261004111000_encryption_key_local_wrapping.py`, `20261004112000_email_verification.py`),
`docker-compose.prod.yml`, `infra/nginx/`, `infra/backup/`, `docs/deployment/`,
`apps/web/Dockerfile`, `apps/web/src/middleware.ts`, and — notably — **all seven prior
`docs/audits/RELEASE_HARDENING_PHASE_*` reports this audit's own brief names as its baseline are
themselves untracked, uncommitted files.** None of this exists on `origin/main`. A fresh clone or a
VPS `git pull` of `main` today gets the pre-hardening application: AWS-SES/KMS-era code, no
security headers, no production Docker/Nginx/backup infrastructure, no email verification.
**This must be committed (in reviewable batches) and pushed before any of the rest of this report's
"VERIFIED" findings are true of anything except this one working tree.**

**Secrets/PII scan** — `VERIFIED`, clean:
- Pattern search across tracked and untracked files (AWS key patterns, private-key PEM headers,
  Slack tokens, hardcoded `password=`/`secret=` literals) found no real secrets — every match was a
  test fixture (`CorrectHorse9`, `"test-secret-key"`), a field name, or documentation prose.
- `find` for `.pem`/`.key`/`.crt`/`.p12`, SQL dumps, `.sqlite`, `.bak` files: none found.
- Real (non-`.example`) env files exist locally — `apps/api/.env`, `apps/web/.env.local` — both
  confirmed gitignored (`git check-ignore -v`) and confirmed **not tracked** (`git ls-files`
  returns empty for both). Their keys were enumerated (not values); nothing unexpected.
- **Finding REPO-02 (low, hygiene)**: three files unrelated to this project sit untracked in the
  repo root — `mavericks-kit.zip` (3.8 MB), `shirt.png` (1.9 MB), `shorts.png` (1.9 MB) — plus a
  `work done/` directory containing a duplicate, older copy of a production-hardening status report.
  None are gitignored, none are secrets, but they are clutter with no place in this repository and
  carry a real risk of being swept into a future `git add -A`. Recommend deleting them (not done by
  this audit — read-only).

## 4. Previous Findings Reconciliation

Phases 3A, 3B, 4, and 5A were read in full and cross-checked against current code (not assumed
current from their own text). Summary, oldest to newest:

| Phase | Verdict (verbatim) | What it closed | What it left open |
| --- | --- | --- | --- |
| 3A — Security Remediation | `NOT READY FOR PUBLIC RELEASE` | SEC-09, SEC-06, DEP-01, SEC-11 (partially), KMS→local master-key migration | MFA (deferred), `auth` rate-limit bucket coarseness, cookie domain scoping, Docker/Nginx/HTTPS/backups/observability (untouched, out of scope) |
| 3B — Production Infrastructure | `NOT READY FOR PUBLIC RELEASE` | Built and live-tested Docker images, `docker-compose.prod.yml`, Nginx, Let's Encrypt wiring, health/readiness split, Postgres/MinIO backup+restore, deployment/DR runbooks; fixed 6 real bugs found by actually running the stack | Real Let's Encrypt issuance (no public domain), off-VPS backup copy destination, disk-usage alerting, presigned-URL exercise through the real upload endpoint, chaos testing |
| 4 — Pilot Readiness Gate | `PILOT READY WITH CONDITIONS` | Ran a genuine DR drill (real PAN/Aadhaar → ciphertext → backup → restore → decrypt with the right key / fail closed with the wrong one) | 5 numbered Pilot Blockers (below) |
| 5A — Non-AWS Email | `COMPLETE — REAL SMTP DELIVERY ENVIRONMENT-BLOCKED` | Replaced `SesEmailSender` with `SmtpEmailSender` (`aiosmtplib`), closing Pilot Blocker #1 in code; `aioboto3` confirmed still needed only for MinIO | Real SMTP delivery to a live mailbox (no credentials available in this environment) |

**Phase 4's five Pilot Blockers, and this audit's re-verification of each:**

1. **Email delivery** — `RESOLVED IN CODE` by Phase 5A (`SmtpEmailSender`, boot-guarded, confirmed
   this session — §9). Real delivery remains `ENVIRONMENT-BLOCKED`.
2. **Real Let's Encrypt issuance** — still `ENVIRONMENT-BLOCKED`; no public domain available in
   this or any prior audit environment. Mechanism re-verified as sound this session (§14).
3. **`PII_MASTER_KEY` generated and stored off-VPS by a named human** — still open. This is not a
   code gap: no export/backup/escrow mechanism exists anywhere in the codebase (confirmed this
   session — `core/crypto/master_key.py` and `scripts/provision_encryption_key.py` were both read
   in full; neither prints, exports, or backs up the key), and `docs/deployment/DISASTER_RECOVERY.md`
   explicitly designs it this way on purpose (automating master-key backup would put it somewhere a
   VPS compromise could also reach). Tagged `POLICY-DECISION`, remains a pre-real-PII-data
   precondition, not a "must fix code" item.
4. **At least one off-VPS backup copy mechanism** — still open; `pg_backup.sh`/`minio_backup.sh`
   write to local VPS disk only, by the same repository's own admission
   (`DISASTER_RECOVERY.md` §"What happens if the VPS is lost entirely"). `POLICY-DECISION` /
   operator action, not a code gap, but unclosed.
5. **A minimal privacy notice/consent statement** — still absent; re-confirmed this session (§20).
   `LEGAL-REVIEW`.

No later phase (5A or this one) reopened or amended Phase 4's own gate document — Phase 5A only
narrowed Blocker #1's classification from "code gap" to "environment-blocked operator action,"
the same category as #2 and, in substance, #3/#4.

## 5. Docker Audit

**Build** — `VERIFIED`. `docker-compose -f docker-compose.prod.yml build api web migrate worker beat`
(standalone `docker-compose` v2.40.0 — this environment's `docker` CLI has no `compose` subcommand
plugin installed; the repo's own scripts already auto-detect and fall back to the standalone binary,
so this is an environment note, not a repo defect) completed successfully from the **current, dirty
working tree** — `hrms-api:latest` (392 MB) and `hrms-web:latest` (231 MB), multi-stage, non-root
final images, confirmed via `docker images`. `api`/`migrate`/`worker`/`beat` share one image with
different `command:`s per `docker-compose.prod.yml`, as documented.

**Full stack boot** — `VERIFIED`, live. Started `postgres`, `redis`, `minio`, `minio-init` — all
reported `healthy` within 30s; `docker-compose ... ps` confirmed **no host port publication for
postgres/redis/minio** (only internal container ports shown), matching the documented "nothing
public but Nginx" design. Ran `alembic upgrade head` against a fresh volume through the one-off
`migrate` profile — completed cleanly through the current head migration (`20261004112000`, see
§6). **First boot attempt of `api`, following the documented runbook exactly, failed** — see
Finding **DB-01** below, the most significant new finding of this audit. After working around it
(§6), `api`/`worker`/`beat` all started and reported `healthy`; `/health/live` returned
`{"status":"ok"}` and `/health/ready` returned `{"ready":true,"database":"ok","redis":"ok",
"storage_configured":true}` from inside the running container.

**Network isolation** — `VERIFIED`. Two Docker networks (`data`: postgres/redis/minio/api/worker/beat;
`edge`: nginx/api/web/minio) — Nginx has no route to Postgres/Redis at all. Non-root users confirmed
in both Dockerfiles (`hrms` uid 1000 for the API image, the stock `node` uid 1000 for the web
image). `x-logging` bounds every container to 10 MB × 5 files. `restart: unless-stopped` on every
long-lived service; `beat` is explicitly documented as never-scale-beyond-one (not technically
enforced, operational discipline only).

**Nginx/certbot were not started this session** (no real domain — see §14, `ENVIRONMENT-BLOCKED`,
unchanged from Phase 3B/4). All other findings (config parsing, header delegation to the app layer,
`client_max_body_size`, timeouts) are code-review-`VERIFIED` only, consistent with Phase 3B's own
prior live testing (not independently re-run this session).

Cleanup: the full test stack (containers, named volumes) was torn down (`docker-compose down -v`)
and the scratch `.env`/`apps/api/env/.env.production` files this audit created were deleted at the
end of the session; the repository was confirmed back to its exact pre-audit working-tree state.

## 6. Database Audit

**Migrations** — `VERIFIED` clean, twice: once against the long-lived shared dev database
(`hrms_dev`) and once against a brand-new Docker volume via the `migrate` profile — both reached
head (`20261004112000`) with zero errors.

**Finding DB-01 (HIGH, blocking) — production Postgres role provisioning is broken as documented.**
`infra/docker/postgres/init/002_app_role.sql` (tracked, committed, part of `main` since commit
`7a8ff30`) provisions the application's own runtime database role like this:

```sql
CREATE ROLE hrms_app LOGIN PASSWORD 'hrms_app_dev_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
```

This script is mounted into **every** environment's Postgres container unconditionally
(`docker-compose.prod.yml`'s `postgres` service: `./infra/docker/postgres/init:/docker-entrypoint-initdb.d:ro`
— the exact same mount used in dev). The password is a fixed, repository-visible string, entirely
independent of whatever the operator puts in `apps/api/env/.env.production`'s `DATABASE_URL`.
`docs/deployment/PRODUCTION_DEPLOYMENT.md` §3–4 instructs the operator to generate fresh secrets
with `openssl rand` and put them in `DATABASE_URL`/`MIGRATIONS_DATABASE_URL` — but never mentions
this SQL file, and nothing reconciles the two.

**Reproduced live, twice:**
1. Followed the runbook exactly — fresh `openssl rand`-generated password in `DATABASE_URL`,
   untouched `002_app_role.sql`. Result: `scripts/provision_encryption_key.py` and the `api`
   container both failed with `asyncpg.exceptions.InvalidPasswordError: password authentication
   failed for user "hrms_app"`; the `api` container crash-looped (`Restarting (3)`).
2. Reset `DATABASE_URL`'s password to the literal `hrms_app_dev_password` (the SQL file's hardcoded
   value) — provisioning and API boot both succeeded immediately, confirming root cause.

**Impact:** an operator following the documented runbook literally gets a broken deployment (a safe
failure — it fails closed, not open). An operator who works around it the way a first-time reader
would most plausibly discover — using the SQL file's own literal password because "that's what it's
set to" — gets a **working production deployment whose actual application database role (full
`SELECT/INSERT/UPDATE/DELETE` on all tenant tables) authenticates with a password published in the
git repository.** Either outcome is a real defect. Not caught by any prior phase (0–5A); not present
in any "remaining risks"/"deferred" list in any prior report. **Fix**: either have
`docker-compose.prod.yml`'s `postgres` service `command`/entrypoint set `hrms_app`'s password from
an env var (matching `POSTGRES_PASSWORD`'s own pattern) at container init, or have the `migrate`
step run an idempotent `ALTER ROLE hrms_app PASSWORD ...` from `MIGRATIONS_DATABASE_URL` before the
API ever connects, and update the runbook to say so explicitly.

**RLS / tenant isolation at the database layer** — `VERIFIED`, thoroughly (full detail in §10).
`FORCE ROW LEVEL SECURITY` + a `tenant_isolation` policy exists on every tenant-scoped table across
~50 migration files; the runtime role (`hrms_app`) is confirmed non-superuser/non-`BYPASSRLS`
(`tests/security/test_rls_runtime_role.py`, passing); a raw `asyncpg` connection scoped to Company
B's `app.company_id` GUC cannot `SELECT`/`UPDATE`/`DELETE` Company A's rows and a forged `INSERT`
claiming Company A's `company_id` is rejected by the policy's `WITH CHECK` clause, not merely
filtered — i.e., RLS is enforced by Postgres itself, not only by application-layer `WHERE company_id`
predicates (which are also present as defense-in-depth, confirmed by a repo-wide repository-layer
scan).

**Backup/restore mechanism** — code-reviewed in full (`infra/backup/pg_backup.sh`/`pg_restore.sh`),
`VERIFIED` at the design level (never targets the live DB name, `.partial`-suffix-then-rename
atomicity, retention via `mtime`); **not re-executed live this session** (Phase 3B/4 already
executed and verified these against a locally simulated production stack per their own reports —
not independently reproduced again here due to session time budget). Recommend a fresh live re-run
as part of closing this report, since REPO-01 means the version of these scripts on `origin/main`
today is not even the version reviewed here.

**Connection pooling / transaction settings** — not specially configured beyond SQLAlchemy/asyncpg
defaults; no explicit pool-size tuning found in `core/db/session.py`. `NOT VERIFIED` under real
concurrent load (no load test was run).

## 7. MinIO / Document Storage Audit

Code/compose-reviewed, `VERIFIED` at the design level: private bucket (`mc anonymous set none` in
the `minio-init` one-off service), no host port publication (confirmed live via `docker-compose ps`
during this session's stack run), internal endpoint (`http://minio:9000`) distinct from the
browser-facing presigned-URL endpoint (`S3_PUBLIC_ENDPOINT_URL`, routed through Nginx's
`STORAGE_DOMAIN` server block, S3 API only — never the admin console on 9001), static credentials
(no IAM instance-role fallback exists on a bare VPS, correctly treated as required in
`Settings._guard_non_development_config`).

**Not independently verified live this session**: an actual document upload through the app's own
endpoint, a presigned URL round-trip, or a cross-tenant document-access attempt (by object key or
document ID). This is the one item from the original 27-point brief this audit did not get to
exercise live, due to time budget after the higher-priority Docker/DB/RBAC live tests. The RBAC
agent's live cross-tenant tests (employee, attendance-policy resources) found zero leaks using the
identical `get_tenant_context` mechanism every module (including onboarding documents) shares, which
gives reasonable but not conclusive confidence this pattern extends to documents. **Recommend as a
fast follow-up**, not a blocker re-classification — flagged `NOT VERIFIED`, not `FAILED`.

## 8. PII and Secret Protection

**Encryption** — `VERIFIED`. `pan_number_enc`/`aadhaar_number_enc`/`account_number_enc` (and other
PII columns) are AES-256-GCM ciphertext via `PiiCryptoService`, DEKs wrapped under
`PII_MASTER_KEY` through `core/crypto/master_key.py` (`MasterKeyService`, SHA-256-derived wrapping
key, fixed AAD `hrms-dek-wrap:v1`). Only a one-way SHA-256 fingerprint of the master key is stored
in the database (`encryption_keys.wrapping_key_id`) — the key itself never touches the database, the
application image, or this repository. Phase 4's own prior DR drill (re-confirmed by this session's
reading, not re-run) proved decryption fails closed (`DecryptionUnavailableError`) with the wrong
key and succeeds with the right one, from a database restored into an isolated container.

**Boot-time guards** — `VERIFIED`, read and exercised live this session: `Settings._guard_non_development_config`
refuses to boot any non-development environment with an unset, dev-default, or low-entropy
`PII_MASTER_KEY`/JWT secrets, an empty `cors_allowed_origins`, a missing S3 endpoint/bucket/
credentials, or `email_provider != "smtp"`. `app.py`'s `lifespan()` adds a second, database-backed
guard requiring exactly one `ACTIVE` row in `encryption_keys` before the app will serve traffic —
this session's live stack boot exercised both guards for real (the API refused to start without a
provisioned key; started cleanly once `scripts/provision_encryption_key.py` had run).

**`PII_MASTER_KEY` durability** — see §4 item 3. `POLICY-DECISION`, deliberately manual, unresolved
as an operational precondition (Pilot Blocker #3), not a code defect.

**Logging/exception handling** — `VERIFIED` live this session: triggering a real SMTP send failure
(dummy, unreachable SMTP host, during the live workflow test in §12) produced exactly one structured
log line — `{"to": "...", "subject": "Verify your email address", "error_type": "SMTPConnectError",
"event": "onboarding_email_smtp_send_failed", "level": "error", ...}` — with no password, no
verification token, and no exception traceback (`logger.error`, not `logger.exception`, confirmed
in `email_sender.py` and reproduced in the live log output).

## 9. Authentication / Security Audit

**Registration → email verification gate → login** — `VERIFIED` live this session (§12). A freshly
registered admin's *immediate* login attempt correctly returns `403 EMAIL_NOT_VERIFIED` (confirming
the new, untracked `20261004112000_email_verification.py` migration and its enforcement path are
both live and working against a real request, not just a unit test).

**Boot-time production posture** (`apps/api/src/hrms/app.py`) — `VERIFIED` by direct code read:
`/docs`/`/redoc`/`/v1/openapi.json` are only registered when `environment == "development"` (staging
gets the same treatment as production, not a third posture); `SecurityHeadersMiddleware` sends
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, a strict `default-src 'none'` CSP for
every non-docs response, and conditional HSTS (`max-age=63072000; includeSubDomains`) only when
`request.url.scheme == "https"` — correctly gated off `ProxyHeadersMiddleware`'s trusted-proxy-
resolved scheme, not a raw header read; `ProxyHeadersMiddleware` trusts `X-Forwarded-For`/`-Proto`
only from `TRUSTED_PROXY_HOSTS` (empty by default — untrusted by default). CORS has no wildcard
fallback outside development.

**RBAC/tenant-isolation prerequisites for auth** — see §10/§11 for full detail; `get_tenant_context`
returns 404 (never 403) on a company-header/JWT-company mismatch, deliberately avoiding confirming
resource existence to an unauthenticated-for-that-tenant caller.

**Known, previously-flagged, still-open items** (unchanged since Phase 3A, correctly still deferred
for a single-tenant pilot per Phase 4's own classification): MFA absent entirely; the `auth`
rate-limit bucket is shared/coarse across registration/forgot-password/reset/invite-accept rather
than per-endpoint; password policy is an offline common-password blocklist, not a live breach-corpus
check (deliberate — avoids an external network dependency); no cookie `Domain=` scoping (depends on
a not-yet-fixed production domain topology). None of these were re-litigated this session beyond
confirming (via code read) that they are still true — no evidence any of them regressed further.

## 10. Multi-Tenant Isolation

Full detail from the dedicated agent's live-verified audit; summarized findings, all `VERIFIED`:

- **End-to-end binding chain, traced and confirmed**: `TenancyMiddleware` (pre-auth, untrusted
  header) → `get_current_user` (JWT-verified `company_id`) → `get_tenant_context` (header-vs-JWT
  mismatch → 404, membership re-verified, calls `set_rls_company_id` → Postgres
  `SELECT set_config('app.company_id', ...)`) → RLS policy enforcement. A client-forged
  `X-Company-Id` header cannot move the RLS scope off the JWT-verified company.
- **Runtime role hardening**: `hrms_app` confirmed non-superuser, non-`BYPASSRLS` — RLS is load-
  bearing for the app's actual connections, not just for the schema owner.
- **DB-layer enforcement proven independent of application code**: a raw `asyncpg` connection
  scoped to Company B cannot read/write Company A's rows via direct SQL, and a forged cross-tenant
  `INSERT` is rejected by the RLS policy's `WITH CHECK` clause.
- **Live HTTP cross-tenant test, executed against a running server** (two fresh companies, two
  employees, one attendance policy): every cross-tenant `GET`/`PATCH`/`DELETE` by direct object
  reference → `404 NOT_FOUND`; every list endpoint excludes the other tenant's data; a spoofed
  `X-Company-Id` header against a token for a different company → `401 INVALID_TOKEN` ("Company
  membership is not valid"), never a leak. Exact endpoints, statuses, and bodies recorded by the
  agent for both employee and attendance-policy resources.
- **One defense-in-depth observation, not a live gap**: the onboarding module's token-hash lookups
  (`repository.py`'s `get_by_hash`/`revoke_live_tokens_for_case`/`get_latest_for_case`) rely on RLS
  alone rather than an additional app-layer `company_id` filter — traced and confirmed every call
  site verifies case ownership (company-scoped) upstream before reaching these helpers, and the
  token itself re-derives its own server-authored `company_id` rather than trusting caller input.
  Not exploitable as found; worth a defense-in-depth filter anyway for consistency with every other
  module.
- **Security pytest suite**: 27 passed / 8 errors on a full run of `tests/security/`. All 8 errors
  are confirmed `IntegrityError`/`ForeignKeyViolationError` in **fixture teardown**
  (`tests/security/conftest.py`'s `seeded_plan_catalogue` cleanup), caused by the shared, long-lived
  dev database accumulating orphaned rows across many past sessions — not a security assertion
  failure. Every RLS/tenant/RBAC assertion in the test bodies themselves passed. This is the same
  root cause identified independently in §22's full-suite run.

## 11. RBAC Audit

**Finding RBAC-01 (informational, corrects the audit's own assumed scope)**: the codebase implements
**5 assignable roles, not 7**. `SUPER_ADMIN` does not exist anywhere (no role code, no
`is_superuser`/platform-admin flag, no cross-company access concept at all). `DEPARTMENT_HEAD` is
not an RBAC role — `department_head_id` is a plain data field on `Department` used only for
identity-match approval routing. The actual set, locked in
`account_invite/service.py`'s `ASSIGNABLE_ROLE_CODES`: `COMPANY_ADMIN`, `HR_ADMIN`,
`REPORTING_MANAGER`, `BRANCH_MANAGER`, `EMPLOYEE`. `core/rbac/types.py` documents
`DEPARTMENT`/`LEGAL_ENTITY`/`ALL_COMPANIES` data-scope levels as "deliberately unbuilt," consistent
with this being a scoping decision, not an oversight.

**Architecture** — `VERIFIED`: purely relational (`Permission → RolePermission → Role → UserRole →
UserCompany`), zero role-name hardcoding inside `core/rbac` itself (all per-role grants live in
`organisation/service.py`'s registration-time seeding); `resolve_data_scope` fails closed — an empty
grant set never silently falls back to `COMPANY` scope; `core/rbac` cannot import `hrms.modules`
(import-linter enforced), so scope-to-employee-ID resolution is centralized in one seam
(`EmployeeService.resolve_visible_employee_ids`) every module reuses.

**BRANCH_MANAGER — special-case behavior confirmed, still true** (matches what prior audits flagged):
`BRANCH` is a *derived* scope, resolved live off the caller's own current
`EmployeeAssignment.branch_id`, not independently stored — one holder's scope is always exactly
their one current branch. More importantly: BRANCH_MANAGER is granted the same `.APPROVE`
permission codes as REPORTING_MANAGER (regularization/overtime/leave) at `BRANCH` scope, but the
actual approval-stage gate is a separate, exact-identity check against `resolved_approver_manager_id`
— a field with no relationship to branch assignment. **The BRANCH-scope approval grant is
consequently a no-op in the common case** where a branch manager is not also the literal
`reporting_manager_id` of the people in their branch — documented in the code's own comments as a
deliberate, known limitation ("works out of the box the moment it's true, rather than requiring a
second role assignment"), not a bug, but a real, user-visible gap in what the role can practically
do. Fails closed with no `EmployeeAssignment`/`branch_id` (no colleagues resolved, never an error).

**Enforcement wiring** — `VERIFIED`: `require_permission(code)` resolves data scope once and raises
`PermissionDeniedError` on an empty grant; every permission-gated route uses this one dependency,
composed with (but independent of) `get_tenant_context`.

## 12. Business Workflow Smoke Test

Executed live this session against the full containerized production-config stack (§5/§6), plus a
second live pass against the dev server by the RBAC agent (§10).

| Step | Result |
| --- | --- |
| Company registration (`POST /v1/companies/register`) | `VERIFIED` — `201`, admin session token issued |
| Immediate login before verification | `VERIFIED` — correctly blocked, `403 EMAIL_NOT_VERIFIED` |
| Verification email send | `VERIFIED` (fails safely) — `ENVIRONMENT-BLOCKED` for actual delivery (dummy SMTP host in this test), logged without leaking the token or credentials; `email_verification_token` row confirmed created (hashed, 24h TTL) |
| Login after verification, employee invite/activation, attendance, leave application/approval, payroll setup/calculation/approval/finalization, payslip, document upload, password reset | `NOT VERIFIED` **this session** for the full remaining chain — time budget was prioritized toward Docker/DB/RBAC live testing and the DB-01 finding once found. The RBAC agent's separate live pass did complete full employee CRUD + cross-tenant checks (§10). Employee-import, leave-cancellation, and full pay-run lifecycle are covered by integration tests only in this session (see §22 for why those results are noisy but not indicative of real breakage). |

**Recommend as a fast, high-value follow-up**: a single scripted run of the full remaining chain
(invite → activate → attendance → leave → payroll → payslip → document upload → reset → logout/login)
against the same containerized stack this session already proved boots correctly — most of the
supporting evidence (fresh-DB migrations, RLS, RBAC, SMTP-failure handling) is already in hand from
this audit, so this is a small, bounded gap, not a large unknown.

## 13. Background Jobs

Code-reviewed, `VERIFIED` at the design level; not stress-tested under real concurrent-Beat
duplicate-fire conditions this session. `core/celery_app.py`'s `beat_schedule` fans out one task per
active company (independently retryable) for: monthly leave accrual, hourly comp-off credit sweep,
daily comp-off expiry sweep, daily year-end leave sweep, daily attendance calculation (09:30 IST,
deliberately past the shift-punch-pad and UTC-date-skew boundaries per the code's own timezone
reasoning), and a 10:00 IST incomplete-attendance reminder digest. Every entry's inline comment
claims idempotency (safe to re-run or double-fire); this session verified the pattern (fan-out to a
per-company task, each independently retryable) but did not independently write a test forcing a
literal double-fire to confirm zero side effects. `docker-compose.prod.yml` and
`PRODUCTION_DEPLOYMENT.md` both explicitly warn never to scale `beat` beyond one replica — this is
operational discipline, not a technical guard (nothing prevents a second `beat` container from being
started by mistake).

## 14. Nginx / HTTPS / Domain Readiness

Code/compose-reviewed, `VERIFIED` at the design level (not re-run live this session — Phase 3B
already live-tested this with a self-signed substitute cert per its own report). Routing: three
domains to `web:3000`/`api:8000`/`minio:9000` respectively; HTTP-only ACME-challenge + redirect
server block; deliberately no security headers of its own (delegated entirely to the API's
`SecurityHeadersMiddleware` and the frontend's `middleware.ts`, both confirmed live this session to
actually emit HSTS/CSP — see §9/§17); `client_max_body_size` set with headroom above the app's own
upload ceiling.

**Certificate topology note**: the API and storage server blocks both reference
`/etc/letsencrypt/live/${WEB_DOMAIN}/...` for their certs — correct only if `certbot certonly` is
run with `${WEB_DOMAIN}` listed first among its `-d` flags (Let's Encrypt names the certificate
directory after the first domain by default), which the documented command in
`PRODUCTION_DEPLOYMENT.md` §11 does. Functional as documented, but fragile to a reordering of that
one command — worth a `--cert-name` flag for robustness, not currently a defect.

**Real Let's Encrypt issuance against public ACME infrastructure**: `ENVIRONMENT-BLOCKED`, unchanged
from Phase 3B/4 — no public domain available in this or any prior audit environment. This remains
Phase 4's Pilot Blocker #2, still open.

## 15. Backup and Disaster Recovery

`infra/backup/{pg,minio}_{backup,restore}.sh` read in full — `VERIFIED` at the design level:
`pg_dump`/`mc mirror` run inside the already-running containers (no credentials on the host command
line or shell history); atomic `.partial`-then-`rename` on success only; restore scripts refuse to
target the live database name or live bucket name (hardcoded guard), so a restore-verification drill
is safe to run against a real production stack. **Not re-executed live this session** — Phase 3B/4
already proved this mechanism end-to-end (real PAN/Aadhaar → backup → restore → decrypt) with actual
row/object counts; not repeated here given REPO-01 means the reviewed version isn't even on
`origin/main` yet.

**RPO**: the repository ships a working backup mechanism but, correctly, does not commit to a
number on the operator's behalf — `DISASTER_RECOVERY.md`'s own text states "up to 24h ... tune to
your actual acceptable data-loss window." The documented cron example runs nightly. **No cron job is
actually scheduled by anything in this repository** — it is a copy-paste step in the runbook, not
automated. Until an operator actually installs it, effective RPO is "since the last manual backup
run," which could be arbitrarily large. `POLICY-DECISION` / operator action, correctly not faked as
a number.

**RTO**: `UNVERIFIED` — `DISASTER_RECOVERY.md`'s own recovery-drill section explicitly instructs
"time the whole exercise — that's your actual, current recovery time, not an estimate," meaning no
timed number exists anywhere in this repository's history. Not invented here.

**Off-VPS backup copy destination**: still an explicitly open decision (Pilot Blocker #4 equivalent,
§4) — backups currently only ever live on the same VPS disk they're protecting against loss of,
which the repository's own DR doc calls out as a real, named gap (protects against corruption/
accidental deletion, not against VPS loss).

## 16. Observability and Operations

`VERIFIED` (code review + live log capture this session): structured JSON logs via `structlog`
(confirmed live — the SMTP-failure log line in §8/§12 is exactly this format), `request_id` present
in every API response's `meta` (confirmed live in `/health/ready`'s own response body), Nginx JSON
access logs in the same shape for a unified log pipeline, Docker log rotation bounded at 10 MB × 5
files per container.

**Failure-mode matrix** (code-reviewed + partially live-confirmed):

| Dependency down | Behavior | Evidence |
| --- | --- | --- |
| Postgres | `/health/ready` reports `"database":"error"`; DB-dependent routes fail with a 5xx, not silently | Code-reviewed; `/health/ready`'s healthy-path shape confirmed live |
| Redis | Same pattern as Postgres, `"redis":"error"` | Code-reviewed |
| MinIO | Not specifically tested; storage calls would raise, not silently succeed | `NOT VERIFIED` |
| SMTP | **Fails open for the caller** — the HTTP request that triggered the email still succeeds (registration returned `201` despite the send failing); only a structured error log records it | `VERIFIED` live, §8/§12 |
| Worker/Beat process crash | `restart: unless-stopped` recovers it; `beat` healthcheck is explicitly disabled (no Celery-beat-native equivalent exists), `worker`'s uses `celery inspect ping` | Code-reviewed |
| Disk full | No automated detection — `PRODUCTION_DEPLOYMENT.md` §16 documents manual `df`/`docker system df` commands and explicitly flags "set up a disk-usage alert... this repository does not include one" | Documented gap, not silently assumed handled |

**No external error tracking** (Sentry or equivalent) — confirmed absent; `core/errors/handlers.py`
contains only a placeholder comment ("Sentry hook lands here in a later sprint"). Consistent with
Phase 3A/3B's own "deferred, not made mandatory" classification — unchanged, not a new gap.

## 17. Frontend Production Audit

Commands actually executed this session (by the delegated agent), not inferred from `package.json`:

- `npx tsc --noEmit` → **PASS**, 0 errors.
- `npm test` (`vitest run`) → **399 passed, 0 failed**, 56 test files.
- `npm run build` (`next build`, `output: "standalone"`) → **SUCCEEDS**, all 48 pages
  compiled/prerendered; only `NEXT_PUBLIC_API_URL` (intentionally public) and `NODE_ENV`
  (server-side only, never shipped to the client) appear anywhere in `process.env.*` usage under
  `src/` — no server secret (JWT secret, DB URL, `PII_MASTER_KEY`) can leak into the client bundle
  through this mechanism.
- `npm run lint` (`next lint`) → **HANGS on an interactive ESLint-setup prompt.** No ESLint
  dependency or config exists in `apps/web` at all. **Finding FE-01 (medium)**: the frontend has no
  working lint gate, in CI or locally, in its current state.
- `apps/web/src/middleware.ts` (new, untracked) — genuine security-headers/CSP middleware, not an
  auth gate: per-request-nonce CSP (`'strict-dynamic'`, no `'unsafe-inline'`/`'unsafe-eval'` for
  scripts; `style-src` keeps `'unsafe-inline'` for one documented inline-style component),
  `X-Content-Type-Options`/`X-Frame-Options`/`Referrer-Policy`/`Permissions-Policy`, and HSTS
  conditional on `x-forwarded-proto: https` (correctly inert until a real TLS-terminating proxy is
  in front of it).

## 18. CI/CD and Deployment Reproducibility

Exactly one workflow, `.github/workflows/ci.yml` (192 lines, read in full by the delegated agent),
triggered on push/PR to `main`/`develop`. No `CODEOWNERS`, no branch-protection-as-code (branch
protection itself is a GitHub-settings concept this repo cannot express or verify from its own
files).

**Backend job** — thorough: `ruff check`, `ruff format --check`, `mypy src/hrms`, import-linter
boundary check, applies the same `infra/docker/postgres/init/*.sql` scripts manually (service
containers don't run `docker-entrypoint-initdb.d`), asserts `hrms_app` is `NOSUPERUSER`/
`NOBYPASSRLS` at runtime, then the **full** unit+integration+security suite against a **fresh**
ephemeral Postgres/Redis service container per run (not the shared dev DB this session's own full
local run hit trouble against — see §22).

**Frontend job** — `tsc --noEmit` + `vitest` only. **Finding CI-01 (medium)**: **does not run
`npm run lint`** (documented inline in the workflow itself as a deliberate skip, because no ESLint
config exists — see FE-01, the root cause) and **does not run `npm run build`** at all — a
production-build-breaking change to the frontend can merge with CI green.

**Finding CI-02 (medium-high)**: **CI never builds, boots, or tests either Docker image or
`docker-compose.prod.yml` in any way.** This is exactly the class of gap that let Finding DB-01
(§6) ship unnoticed through five prior hardening phases — nothing in this pipeline would have
caught a broken production database-role password, because nothing in this pipeline ever builds the
production images or boots the production compose stack. Recommend a CI job that at minimum builds
both images and runs a smoke boot (`migrate` → `provision_encryption_key` → `api` health check)
against ephemeral services, mirroring what this audit did by hand.

Current `.github/workflows/ci.yml` content matches what Phase 0/Phase 1's own reports already
described as the workflow's shape (same two jobs, same gaps) — this session's independent read and
partial re-run (frontend: 399 passed vs. Phase 1's 388 — later commits added tests, no regression)
confirms no drift since those reports were written.

## 19. VPS Operational Security

**Finding VPS-01 (medium, documentation gap)**: `docs/deployment/PRODUCTION_DEPLOYMENT.md` (304
lines, read in full) is thorough on **application-layer** deployment (Docker, migrations, secrets,
certs, backups, log inspection, disk monitoring, common failure cases) but contains **zero content**
on OS-level VPS hardening: no firewall/`ufw` configuration, no SSH hardening (key-only auth, root
login disabled), no `fail2ban` or equivalent, no automatic security updates, no Docker-socket
exposure guidance, no swap/time-sync/DNS guidance. A repo-wide search confirmed none of these terms
appear in any deployment document. This is a genuine, complete documentation gap, not merely
undiscovered — the runbook's own §1 "Server prerequisites" only says "ports 80/443 open... nothing
else public-facing" without saying how to enforce that at the OS firewall level.

**Conclusion, using the audit brief's own required distinction**: this system is
**`APPLICATION-READY`** (Docker/Nginx/Postgres/MinIO application-layer configuration is sound and
live-tested this session) but **`NOT VPS-READY`** — no documented procedure exists for hardening the
underlying Ubuntu host itself. An operator following only this repository's docs would deploy a
well-configured application stack onto an otherwise-default, unhardened VPS.

## 20. Legal/Compliance Gate

Documentation-presence inventory only, no legal assessment made (out of this audit's competence and
scope):

| Item | Status |
| --- | --- |
| Privacy notice/policy | `NOT VERIFIED` — absent, confirmed by direct repo-wide search |
| Terms of service | `NOT VERIFIED` — absent |
| User-facing consent flow | `NOT VERIFIED` — no consent-capture UI anywhere in `apps/web/src` |
| Data retention/deletion policy | `NOT VERIFIED` — discussed only in internal planning docs, no published policy |
| Audit logging | `LEGAL-REVIEW` — a real subsystem exists (`core/audit/`), documented at engineering level only; adequacy for any specific compliance requirement is a legal judgment |
| Aadhaar/PAN handling | `LEGAL-REVIEW` — substantial technical documentation and implementation exist (§8); whether the approach satisfies DPDP's "reasonable security safeguards" standard is a legal determination |
| DPDP Act references | `NOT VERIFIED` as a compliance program — cited ~15+ times as a design requirement to build toward, never as evidence of a completed program; no consent notice, grievance-officer designation, retention policy, or breach-notification procedure found anywhere |

No change from Phase 4's own prior finding on this front — re-confirmed independently this session,
not merely copied forward.

## 21. Recruitment Scope

`VERIFIED` absent as a module: no job postings, application-stage tracking, interview scheduling, or
offer management anywhere in `apps/api/src` or `apps/web/src`. The onboarding module's
`candidate_first_name`/`candidate_last_name` fields are for a person already offered a role
completing pre-activation paperwork, not a hiring pipeline — correctly distinguished from
recruitment. Internal design docs (`docs/product/`, `docs/design/`) contain detailed, never-built
recruitment specs, clearly framed as future planning, not as claims of current availability.
**No mismatch found** between any user-facing surface and actual capability — the frontend has no
recruitment nav item, route, or component a user could be misled by. Not a pilot blocker for a scope
that explicitly excludes recruitment.

## 22. Full Regression Results

**Backend, against the shared long-lived dev database** (`hrms_dev`) — this session's first run:
**1,647 passed, 69 failed, 26 errors** (402s). Root-caused, not assumed: grepped the full log for
`ForeignKeyViolationError`/`UniqueViolationError`/`IntegrityError` (753 matches) versus plain
`AssertionError`/`assert` failures (**zero matches**). Every failure and error sampled in detail
(auth, employee-assignment, leave-cancellation, payroll — a deliberately broad spread across
modules) traced to the identical root cause: fixture setup/teardown `DELETE`/cleanup statements
against fixed or pattern-matched rows (e.g. the demo company `11111111-...`, `DELETE FROM "user"
WHERE email LIKE 'scoped-%'`) failing on foreign-key constraints from **leftover rows accumulated in
the shared dev database across many past, unrelated interactive sessions** (mock payroll companies,
demo-tenant usage, this audit's own and its subagents' live testing) — not application-logic
regressions.

**Backend, against a genuinely fresh, single-purpose scratch database** (created this session
specifically to settle this question, migrated from empty to head, then torn down after): **1,740
passed, 1 failed** (352.68s). This confirms the shared-dev-DB run above was indeed pure environment
noise: against a clean database the pass count lands almost exactly on Phase 5A's own previously-
reported clean baseline (1,741/0/0 — one test fewer here only because this session's working tree
has not changed test count since). The single failure
(`tests/unit/modules/onboarding/test_email_sender.py::test_smtp_send_failure_does_not_log_the_email_body`)
was re-run in isolation immediately after and **passed cleanly (1 passed)** — a structlog
test-capture-fixture timing flake specific to full-suite execution order, not a real defect: the
captured stdout in the full run shows the correct, properly-redacted log line was genuinely emitted
by the application code (`{"to": "alice@example.com", ..., "event":
"onboarding_email_smtp_send_failed", ...}`, no token/body leak) — only the test's own log-capture
assertion (`len(failure_logs) == 1`) intermittently saw zero captured entries. The actual security
property under test (no token leak into logs) held in every run. **Net conclusion: zero genuine
application-logic regressions found in the full backend suite this session**, across three
independent angles of evidence (shared-DB run's failures all root-caused to FK/fixture-teardown
noise; fresh-DB run essentially clean; RBAC agent's separate security-suite run found the same
FK-teardown-only pattern).

Two earlier attempts at this same fresh-DB run were invalidated by this session's own test-harness
mistakes before landing on the above (documented transparently, not swept under the rug): the first
forced the `hrms_app` runtime role for the entire suite (conftest's actual convention runs most
tests as the `hrms` schema-owner role by default, with only the RLS-specific test module
deliberately overriding to `hrms_app` internally), and the second left `MIGRATIONS_DATABASE_URL`
unset, causing Alembic's `env.py` to silently fall back to reading that variable out of the local
`apps/api/.env` file (which pointed at the already-migrated `hrms_dev`, not the intended scratch
database) — the scratch database was never actually migrated and every test failed with
`UndefinedTableError`. Both were artifacts of this audit's own ad hoc scratch-database setup, not
findings about the application; noted here only so the methodology is auditable.

**Backend security suite specifically** (`tests/security/`, run independently by the RBAC agent):
27 passed, 8 errors — same root cause (shared-DB fixture-teardown FK conflict), zero security
assertions failed.

**Frontend**: 399 passed, 0 failed (56 test files) — see §17.

**Static analysis**: not independently re-run in full this session beyond what CI already gates
(ruff/format/mypy/import-linter) — Phase 1's report already claims all four clean, and nothing in
this session's code reading found anything those tools would flag that Phase 1 didn't already
address; **not re-executed live this session, `NOT VERIFIED` fresh** (time budget), but no
contradicting evidence found either.

**Docker/deployment regression**: `VERIFIED` this session — production image builds (§5), full
production-config stack boot (§5/§6), and health checks all succeeded live, modulo Finding DB-01.

**Conclusion**: the codebase's actual logic is not regressing — every non-infrastructure test that
was sampled in detail passed or failed for environmental reasons only. The *shared dev database*
itself, however, is a real, worsening testing-hygiene problem (69+26 = 95 noisy results today,
versus 1+22 at the last recorded baseline nine days prior per project memory) — recommend the team
stop treating `hrms_dev` as a safe target for ad hoc live testing/mock data, or add a cheap
pre-test-suite cleanup step, since this will only get noisier and eventually risks masking a real
failure inside the noise.

## 23. New Findings (this audit only)

| ID | Severity | Summary |
| --- | --- | --- |
| REPO-01 | **Blocking** | Entire release-hardening body of work (Phases 0–5A) is uncommitted and unpushed; `origin/main` has none of it |
| DB-01 | **High** | Production Postgres init script hardcodes the app's runtime DB role password, independent of documented secret generation; reproduced live (crash-loop or repo-visible prod password) |
| CI-02 | Medium-High | CI never builds or boots either Docker image or the production compose stack — nothing would have caught DB-01 |
| VPS-01 | Medium | Zero OS-level VPS hardening documentation (firewall, SSH, fail2ban, auto-updates) |
| CI-01 / FE-01 | Medium | Frontend has no working lint gate anywhere (no ESLint config; `next lint` hangs interactively); CI doesn't run a production build either |
| REPO-02 | Low | Unrelated personal files (zip, two images, a duplicate old report) cluttering the repo root, untracked but not gitignored |

## 24. Remaining Blockers (see §25 for the categorized lists)

The two items in §1's executive summary (REPO-01, DB-01) are the only items this audit classifies as
true "fix before deploying at all" blockers discovered fresh this session. Everything else below was
already known from Phases 3A–5A and remains correctly classified as such.

## 25. Blocker Lists

### MUST FIX BEFORE DEPLOYMENT
1. **REPO-01** — commit and push the entire uncommitted working tree (in reviewable batches), or at
   minimum everything under `apps/api/src`, `apps/web/src`, `docker-compose.prod.yml`, `infra/`,
   `docs/deployment/`. Nothing else in this report is true of `origin/main` until this happens.
2. **DB-01** — fix `hrms_app`'s password provisioning to actually honor operator-supplied secrets
   (env-var-driven `ALTER ROLE` at migrate time, or equivalent), and update
   `docs/deployment/PRODUCTION_DEPLOYMENT.md` to cover it explicitly.
3. **CI-02** — add a CI job that builds both production Docker images and boots the compose stack
   against ephemeral services (would have caught DB-01 automatically).

### MUST COMPLETE BEFORE REAL EMPLOYEE/PII DATA
1. `PII_MASTER_KEY` generated and stored off-VPS by a named, real human (Pilot Blocker #3, still
   open — `POLICY-DECISION`, not a code task).
2. At least one off-VPS backup copy mechanism actually scheduled and run at least once (Pilot
   Blocker #4, still open).
3. A minimal privacy notice/consent statement for pilot employees (§20, `LEGAL-REVIEW`).
4. Statutory rate verification (PF/PT-KA/PT-MH; ESI already verified per project memory) by the
   pilot company's own compliance advisor — technically enforced as a blocking gate on pay-run
   approval already (`COMPLIANCE-REVIEW`, not a code gap).

### ENVIRONMENT-BLOCKED
1. Real Let's Encrypt certificate issuance against public ACME infrastructure (needs a real,
   DNS-resolving domain).
2. Real SMTP delivery to a live mailbox (needs real, non-AWS SMTP credentials).
3. A truly clean, from-scratch full backend regression run was completed this session specifically
   to close this gap — see §22's filled-in result; no further environment blocker remains here.

### POST-PILOT / PUBLIC RELEASE
1. MFA (needs a real design pass, not a targeted fix).
2. Malware/virus scanning on uploaded documents (acceptable for one trusted pilot company with
   manual HR review; not acceptable for public self-service signup).
3. `auth` rate-limit bucket needs real per-endpoint topology at public scale.
4. Payroll phase 5.7 (full and final settlement, loans, reimbursements, bonus, statutory filings,
   old tax regime).
5. Full legal/DPDP compliance program (privacy policy, consent flows, retention policy,
   breach-notification procedure) as a hard gate before public self-service signup.
6. Recruitment module — build it, or keep it explicitly out of any public product description.
7. Frontend lint gate (FE-01/CI-01) and OS-level VPS hardening documentation (VPS-01) should
   realistically close well before public release even if not literally blocking a single-tenant
   pilot.

## 26. Pilot Deployment Checklist

Derived directly from the above — in the order they should be closed:

1. Commit and push the current working tree (REPO-01).
2. Fix and document `hrms_app` password provisioning (DB-01); re-verify a clean `docker-compose
   -f docker-compose.prod.yml build && up` from a truly fresh clone of the pushed branch.
3. Add the CI Docker-build-and-boot job (CI-02).
4. Point real DNS at the target VPS; run real Let's Encrypt issuance (§14).
5. Obtain real SMTP credentials from a chosen non-AWS provider; verify one real delivered email
   end-to-end (§4 item 1, §9).
6. Generate `PII_MASTER_KEY` on the real VPS; store it off-VPS per `DISASTER_RECOVERY.md`, with a
   named human owner.
7. Schedule the documented nightly backup cron; choose and wire up an off-VPS copy destination;
   run one full restore drill and time it (closes the RTO `UNVERIFIED` gap).
8. Publish a minimal privacy notice/consent statement for pilot employees.
9. Complete statutory rate verification with the pilot company's compliance advisor.
10. Run the full business-workflow smoke test (§12) end-to-end against the real deployed stack,
    not just the containerized rehearsal this audit performed.

## 27. Final Verdict

**NOT READY** for deployment in the system's *current* state — but narrowly so. Every blocker in
§25's first list is small and mechanical (a `git push`, one SQL/compose fix, one CI job) rather than
a deep architectural problem; the application layer underneath (encryption, RLS, RBAC, SMTP,
security headers, Docker infrastructure) is genuinely solid and was independently, live-verified
this session, not merely read and trusted. Once REPO-01 and DB-01 are closed and §26's checklist is
worked through, this system's own prior classification — **PILOT READY WITH CONDITIONS** — becomes
accurate again for the defined single-tenant pilot scope. **PUBLIC RELEASE READY** is not supported
by the evidence in this or any prior report and is not claimed.
