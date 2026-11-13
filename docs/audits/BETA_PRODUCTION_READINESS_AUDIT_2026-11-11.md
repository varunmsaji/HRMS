# Beta production-readiness audit — database, backend, frontend

**Date:** 11 Nov 2026 · **Branch audited:** `test` at `95dfff7` (13 commits ahead of `origin/main`) · **Mode:** read-only, no code or data changed

## 1. Verdict

**Not ready for a beta with real employee data yet. Ready for a closed, test-data pilot.**

The engineering base is unusually strong for this stage: tenant isolation is enforced in the database, secrets are guarded at boot, PII is encrypted, the checks are green. What stands between the product and a real beta is mostly **operational and release work, not a rewrite**:

- 7 blockers (section 3). Four are operations/release tasks, one is a code fix (an authorization gap that also breaks CI), two are owner decisions (legal notices, policy rules).
- 10 high-priority items that should land before or in the first week of beta.
- A list of medium/low items that can follow.

Rough effort to clear the blockers: about one to two focused weeks, most of it outside the code.

## 2. Scope, method and limits

| Area | What I did | What I did not do |
|---|---|---|
| Database | Read all schema facts from the local `hrms_dev` Postgres 16 (at migration head `20261111090000`): RLS, policies, roles, privileges, indexes, constraints, triggers. Read the init scripts and `alembic/env.py`. | Did not connect to the VPS database. Live-server statements below come from the 10 Nov audit notes and are marked **(not re-verified)**. |
| Backend | Read core (settings, auth, JWT, cookies, tenancy, RBAC, sessions, rate limiting, Celery, security headers), app factory, all routers' auth dependencies, Dockerfile, compose, nginx, CI. Ran ruff, mypy, unit tests, pip-audit. | Did not read every line of the ~104k-line backend. Did not run the integration/security suites (need a disposable DB, ~25 min). |
| Web | Read middleware/CSP, API client, token storage, config, Dockerfile. Ran `tsc`, ESLint, Vitest, `npm audit`. | Did not run Playwright e2e or click through the app. |
| Mobile | Read API client, token storage, Android build/manifest, iOS plist, dependencies. | Flutter is not installed on this machine: `flutter analyze` / `flutter test` not run. No device test. |

### Check results (this session)

| Check | Result |
|---|---|
| API ruff | Pass |
| API mypy (278 files) | Pass |
| API unit tests | 1941 passed, **1 real failure** (B-2 below). 5 failures + 9 errors were caused by my throwaway DB credentials, not by the code. |
| API pip-audit (locked prod deps) | No known vulnerabilities |
| Web `tsc --noEmit` | Pass |
| Web Vitest | 1024 passed / 147 files |
| Web `npm audit --omit=dev` | 0 vulnerabilities |
| Web ESLint | **119 errors**, 1 warning (non-blocking in CI) |

## 3. Blockers — fix before real users

### B-1. Beta must start on a clean production database, not the demo one
- **Evidence:** 10 Nov audit: the live app runs on `hrms_demo`, restored from a laptop dump; `hrms_prod` is empty **(not re-verified)**. `docs/development/DEMO_SEED_CREDENTIALS.md` publishes the seed admin email and password in the repo. `apps/api/scripts/seed.py` has no environment check and will seed any database it is pointed at.
- **Risk:** if the demo data contains the seed users, anyone who has seen the repo can log in as a company administrator on the live server.
- **Fix:** bring up `hrms_prod` from migrations only, run `provision_encryption_key.py` and `create_platform_admin.py`, switch the app to it, and confirm `admin@example.com` / `viewer@example.com` do not exist. Add a guard so `seed.py` refuses to run when `ENVIRONMENT != development`.

### B-2. Salary setup ignores the caller's data scope (and fails CI)
- **Evidence:** `apps/api/src/hrms/modules/payroll/router.py:448` — `POST /employees/{employee_id}/salary/setup` requires `PAYROLL.SETUP_MANAGE` and `EMPLOYEE.UPDATE_COMPENSATION` but never applies the resolved scope to `employee_id`. The repo's own guard catches it: `tests/unit/core/test_scope_enforcement_guard.py::test_every_scope_ignoring_route_is_a_reviewed_exception` fails on `test`.
- **Risk:** a user granted those permissions at TEAM/BRANCH/DEPARTMENT scope can set the CTC and structure of any employee in the company. Also, the next PR to `main` will fail CI on this test.
- **Fix:** enforce the scope in `save_setup` (and check the preview route at line ~437 the same way), as the other per-employee payroll routes do.

### B-3. Close the backup, alerting and key-escrow loop
- **Evidence (10 Nov notes, not re-verified):** hourly encrypted backups to Google Drive are running and one restore test passed. Still open: email alerts wait for the SMTP app password; `hrms-monitor.timer` is not enabled; the Drive OAuth token was printed into a session transcript and should be revoked and re-authorised.
- **Key escrow:** PAN, Aadhaar, bank account numbers and face embeddings are encrypted under `PII_MASTER_KEY`. A database backup is useless for those fields without that key. I found no record that the key is stored anywhere other than the server's env file.
- **Fix:** enable alerts and the monitor timer; rotate the Drive token; store `PII_MASTER_KEY`, both JWT secrets and the age private key in two offline places; run one full restore drill onto a blank machine (database **and** MinIO files) and time it.

### B-4. The mobile app cannot be released as built
- **Evidence:** `apps/mobile/android/app/build.gradle.kts` signs the release build with the debug key. `lib/core/api/api_client.dart:22` defaults `API_BASE_URL` to `http://localhost:8000` with no check in release mode. `pubspec.yaml` still says "A new Flutter project.", version `0.1.0`. No crash reporting, no minimum-version / force-update check.
- **Fix:** create a release keystore (kept outside the repo, backed up), fail the build or app start when a release build has a non-https base URL, set real metadata, and add a server-driven minimum-version check before the first external install, because you cannot recall an installed beta build.

### B-5. No privacy notice, terms or data-rights path
- **Evidence:** the web app has no privacy or terms page (`apps/web/src/app` has none; no such text in `src`). The product stores Aadhaar, PAN, bank details, face biometrics and punch locations. The backend has face-consent handling, but there is no export or erasure workflow, and face retention is unset (`face_*_retention_days = None`, `FACE_CLEANUP_DRY_RUN=true`).
- **Risk:** legal exposure under India's DPDP Act as soon as real employees are onboarded. This is an owner/legal decision, not only code.
- **Fix:** privacy notice and terms linked from registration, login and onboarding; a data-processing agreement for each beta company; decide retention periods and switch cleanup out of dry-run; a documented manual process for erasure requests is enough for beta.

### B-6. Open policy decisions C-01..C-20
- **Evidence:** `docs/audits/POLICY_DECISION_MAP_2026-11-09.md` lists 20 blocking decisions for attendance, leave, shift, overtime and payroll that still await the owner.
- **Risk:** beta companies will get pay-affecting results from rules nobody has signed off.
- **Fix:** decide them, or ship beta as **attendance + leave only** with payroll hidden behind the plan/feature flag until they are settled.

### B-7. What is on `test` has not been exercised end to end
- **Evidence:** 13 commits on `test` are not on `main`, including migration `20261111090000` (needs a person to merge). The Settings rework e2e has not been run; the CompreFace provider has never run live; Playwright has only 2 feature specs and is not in CI; CI does not run the mobile app on a device.
- **Fix:** one scripted manual pass on a staging copy covering register → verify → onboard employee → punch (web + mobile, face + geofence) → regularise → leave apply/approve → period lock → pay run, on a clean database, before inviting anyone.

## 4. High priority — before or in the first week of beta

| # | Finding | Evidence | Fix |
|---|---|---|---|
| H-1 | **Per-IP auth limits will lock out offices.** Login, token refresh and the shared auth bucket are each 10 requests/minute per IP. Every employee in an office shares one public IP. With 15-minute access tokens, ~150 active users behind one NAT exceed the refresh limit in normal use; a 9 am login rush exceeds the login limit. | `identity/router.py:36-52`, `shared/rate_limit.py` | Raise the per-IP ceilings substantially (keep the per-email login bucket at 10), or key refresh on the session rather than the IP. |
| H-2 | **No MFA anywhere, including the platform console,** which can approve, suspend and terminate every tenant. Its token lives in `sessionStorage`. | `platform/router.py`, `web/src/lib/platform/api.ts` | TOTP for platform admins before beta; restrict `/platform` by IP at nginx as a stopgap. Company-admin MFA can follow. |
| H-3 | **No signed-in "change password"** endpoint; users can only use the forgot-password email. | Route scan: only `/password/forgot`, `/password/reset` | Add `POST /auth/password/change` (current + new, revoke other sessions). |
| H-4 | **Everything runs on one VPS with no resource limits:** Postgres, Redis, MinIO, API, worker, beat, web, optionally CompreFace (Java, 1.5 GB+ heap), plus another product. Postgres runs on stock settings. Recovery point is one hour (dumps, no WAL archiving). | `docker-compose.vps.yml` (no `mem_limit`/`deploy.resources`, no postgres config) | Set memory limits per container, tune `shared_buffers`/`work_mem`, keep CompreFace off this box, accept and document RPO 1 h / RTO for beta. |
| H-5 | **Face liveness is off by default** and not set in the production env template, so a photo of a photo can punch. Mock-location detection is client-side only. | `settings.py:313`, `env/.env.production.example` | Enable `FACE_LIVENESS_ENGINE=minifasnet` for any company using face punch; treat geofence as deterrent, not proof. |
| H-6 | **No error tracking** in API, web or mobile. Problems are only visible in log files, and alerting is not yet live (B-3). | No Sentry/Crashlytics dependency in any app | Add an error tracker to all three with PII scrubbing; beta feedback depends on it. |
| H-7 | **Nothing is ever purged:** `idempotency_key`, `refresh_token`, `session`, password-reset and email-verification tokens, `email_outbox`, `notification` have no cleanup job; `LOG_RETENTION_DAYS=0`. | No delete statements for these models; beat schedule has no retention task | One daily Celery task deleting expired/revoked rows older than N days. |
| H-8 | **ESLint is non-blocking with 119 errors** (94 are `react-hooks/set-state-in-effect`). New real hook bugs hide in the noise. | `ci.yml` step "ESLint (non-blocking)" | Downgrade that one rule to warning, fix the other 25, make the step blocking. |
| H-9 | **Web image uses Node 20,** which reached end of life in April 2026. | `apps/web/Dockerfile` | Move to Node 22 LTS (also in CI). |
| H-10 | **Manual, in-place deploys.** Images are built on the VPS and tagged `latest`; migrations are a manual step; no staging environment; no rollback image. | `docker-compose.vps.yml` | Tag images by git SHA, keep the previous tag, write the rollback steps, take a backup immediately before every migration. |

## 5. Database — detailed findings

### What is solid
- **Tenant isolation in the database.** 104 tables have `ENABLE` + `FORCE ROW LEVEL SECURITY` with a `company_id = current_setting('app.company_id', true)::uuid` policy. An unset variable yields no rows (fails closed). No RLS-enabled table lacks a policy.
- **Least-privilege runtime role.** `hrms_app` is `NOSUPERUSER NOBYPASSRLS`; CI asserts this. Migrations use a separate credential the app never loads.
- **Append-only by privilege and trigger.** `hrms_app` has no UPDATE/DELETE on `audit_log`, `leave_ledger`, `leave_application_action`, `leave_year_end_run`, `email_log`, `platform_audit_log`. Pay-run tables have immutability triggers.
- **Integrity.** 124 tables, all with primary keys; 347 foreign keys, 184 CHECK constraints, 15 exclusion constraints (effective-date overlap). All timestamps are `timestamptz`. No float or `money` columns (money is integer minor units).
- **Hot-path indexes are right:** `punch (company_id, employee_id, punch_time)`, `attendance_day (company_id, employee_id, attendance_date)`, partial indexes on the outbox and notifications, unique idempotency keys.

### Findings

| # | Sev | Finding | Fix |
|---|---|---|---|
| D-1 | Med | 7 tables carry `company_id` but have no RLS: `session`, `refresh_token`, `account_invite`, `onboarding_token`, `email_log`, `email_outbox`, `platform_audit_log`. Most are read before a tenant is known, so this is probably deliberate, but they rely entirely on application filtering. | Record each as a reviewed exemption with a test, or add a policy that also admits the no-tenant case. |
| D-2 | Med | Missing indexes on columns used for lookups: `employee.user_id` (every login resolves the employee), `user_company.user_id` (company list at login; the existing unique index leads with `company_id`), `refresh_token.session_id`, and no entity index on `audit_log`. In total 176 FK columns have no leading index; most are `created_by`/`updated_by` and harmless now. | Add the four named indexes now; revisit the rest when a parent-row delete or a report gets slow. |
| D-3 | Med | No role-level safety timeouts. Dev server shows `statement_timeout=0`, `idle_in_transaction_session_timeout=0`, and no migration or init script sets them for `hrms_app` (some attendance/leave paths set their own). One stuck request can hold locks indefinitely. | `ALTER ROLE hrms_app SET statement_timeout='30s', idle_in_transaction_session_timeout='60s', lock_timeout='10s'`. |
| D-4 | Med | The RLS variable is transaction-local. Seven service files commit mid-request (`employee_import/service.py`, `onboarding/email_outbox.py`, `identity/service.py`, `platform/service.py`, `face_service.py`, `account_invite/service.py`, `email_sender.py`). Any tenant query after such a commit silently returns nothing unless the variable is set again. | Re-apply the variable in one shared "commit and continue" helper and use it at every mid-request commit. |
| D-5 | Med | The schema owner / migration role `hrms` is a superuser with `BYPASSRLS`. | Use a non-superuser owner for migrations in production; keep the superuser for administration only. |
| D-6 | Low | Connection pool is SQLAlchemy's default (5 + 10 overflow per process) and not configurable; no `pool_recycle`. Fine at 2 gunicorn workers + 2 Celery processes against `max_connections=100`; will need settings before scaling workers. | Expose pool size/recycle in `Settings`. |
| D-7 | Low | `init/002_app_role.sh` grants DML on **all** tables; the append-only REVOKEs live elsewhere. This is exactly how the 10 Nov demo restore undid them. | Put the REVOKEs in the same script (or a post-restore script) and add a monitor check that `hrms_app` cannot UPDATE `audit_log`. |
| D-8 | Low | `user.email` and `user.phone` are globally unique across tenants: one person, one login for all companies. Correct for the current model; worth knowing before a client asks for separate identities. | No action. |
| D-9 | Info | 140 migrations in a single linear history; local DB is at head. I did not test downgrade paths. | Before beta, rehearse `upgrade head` on a copy of the production backup. |

## 6. Backend — detailed findings

### What is solid
- **Boot guards.** Outside development the process refuses to start with default/weak JWT or PII secrets, empty CORS list, missing storage config, the logging-only email sender, a non-https web URL, or anything other than exactly one active encryption key.
- **Auth.** Argon2 hashes, common-password blocklist, 5-attempt lockout, 15-minute access tokens, rotating refresh tokens with replay detection, HttpOnly refresh cookie. Every request re-checks user, session, membership and company status, so suspension is immediate.
- **Tenancy.** The tenant comes only from the signed token; a mismatching `X-Company-Id` is rejected.
- **Route protection.** Of ~412 routes, the only unauthenticated ones are login/refresh/password/verify, registration, health, and the token-based invite and onboarding links, all rate-limited. `/metrics` is closed unless a token is set and nginx returns 404 for it. API docs are disabled outside development.
- **Uploads.** Size capped before parsing, type decided by magic bytes, private bucket, 5-minute presigned links.
- **Operations.** Structured JSON logs with redaction, request ids end to end, Prometheus metrics, time limits on every Celery task, a transactional email outbox, idempotency keys, non-root multi-stage image, liveness vs readiness probes.
- **Quality gates.** Ruff, mypy and import-boundary checks are clean; gitleaks, pip-audit and npm audit run in CI.

### Findings (beyond B-2 and H-1..H-7)

| # | Sev | Finding | Fix |
|---|---|---|---|
| A-1 | Med | Redis is a single point for login. The limiter fails closed, so a Redis outage returns 503 on every auth route. Redis has no `maxmemory` policy and no password (network-internal only). | Acceptable for beta; add `maxmemory` + `noeviction` and include Redis in the monitor. |
| A-2 | Med | Only Leave tasks use `acks_late` / `reject_on_worker_lost`. A worker killed mid-task loses `employee_import.process_batch` (one-off, user-triggered; there is a reconcile script) and delays the others until the next beat tick. | Add the two options to the import task. |
| A-3 | Med | Nothing watches Celery beat automatically yet: its healthcheck is disabled by design and the heartbeat check depends on the monitor timer from B-3. If beat stops, attendance calculation, leave accrual and the termination-access sweep stop silently. | Enabling the monitor timer closes this. |
| A-4 | Med | JWTs are HS256 with one shared secret, no `kid`, `iss` or `aud`. Rotating the secret signs everyone out at once. | Fine for beta; plan key ids before GA. |
| A-5 | Med | No global per-user or per-tenant API rate limit; `rate_limit_max` / `rate_limit_window_ms` exist in settings but are unused. Nginx has no `limit_req`. | Add a coarse nginx `limit_req` per IP on the API host. |
| A-6 | Low | `web_app_base_url` and the cookie design assume web and API share a registrable domain (the refresh cookie is `SameSite=Lax`). On different sites, refresh silently fails. | State it in the deployment runbook. |
| A-7 | Low | CompreFace's database password defaults to empty in compose (`${COMPREFACE_POSTGRES_PASSWORD:-}`); MinIO runs a third-party fork image (`pgsty/silo`), pinned by digest. | Require the password; note the image provenance and watch it for updates. |
| A-8 | Low | Product limits hard-wired for now: only `Asia/Kolkata` is an allowed company timezone and one legal entity per company. | Tell beta companies up front. |
| A-9 | Info | Password rule is 8+ characters with a letter and a digit plus blocklist. Reasonable; consider 10+ for admins. | Optional. |

## 7. Frontend — detailed findings

### Web (Next.js)

**Solid:** strict nonce-based CSP with no `unsafe-inline`/`unsafe-eval` for scripts in production, plus a dedicated CSP e2e config; refresh token never reachable from JavaScript; cross-tab refresh serialised with Web Locks so two tabs do not trigger replay revocation; request timeouts and cancellation; error boundaries at route and global level; no `dangerouslySetInnerHTML`, no stray `console.log`; type-check clean; 1024 unit tests; zero audit findings; non-root standalone image.

| # | Sev | Finding | Fix |
|---|---|---|---|
| W-1 | High | ESLint backlog, non-blocking (H-8). | See H-8. |
| W-2 | High | Node 20 base image is end-of-life (H-9). | See H-9. |
| W-3 | High | End-to-end coverage is thin: 2 Playwright specs (policy followers, work calendar) plus CSP; none in CI. | Add 5–6 smoke flows (login, employee create, punch, leave, regularisation, pay run) and run them against staging before each release. |
| W-4 | Med | The access token and company list sit in `localStorage`. Exposure is limited to 15 minutes and mitigated by the CSP, but any script-injection bug becomes token theft. | Acceptable for beta; keep the CSP e2e mandatory. Longer term keep the access token in memory only. |
| W-5 | Med | No privacy/terms pages (B-5) and no in-app way to report a problem or see the build version. | Add footer links and show the build SHA in the user menu for support. |
| W-6 | Low | Every page is rendered per request so it can carry a CSP nonce, including the marketing landing page. This costs CPU on the shared VPS. | Fine for beta; later serve the landing page statically with a hash-based CSP. |
| W-7 | Low | Dependencies are current within their majors (Next 16.4.5 → 16.4.6 available). React is on 18 while Next 16 targets 19. | Take the patch bump; plan the React 19 move after beta. |
| W-8 | Low | Open known gaps from earlier work: employee Home and the Settings guide text are not updated. | Finish or hide before inviting users. |

### Mobile (Flutter)

**Solid:** access token in Keychain/Keystore via `flutter_secure_storage`; `allowBackup=false`; cleartext traffic allowed only in the debug manifest; clear camera and location purpose strings; timeouts on every request; idempotency keys on punches; a large test tree (817 files).

| # | Sev | Finding | Fix |
|---|---|---|---|
| M-1 | Blocker | Release signing, base-URL default, metadata, minimum-version check (B-4). | See B-4. |
| M-2 | Med | The 30-day refresh token is stored by `PersistCookieJar` as a plain file in the app's support directory, not in secure storage. Protected by the OS sandbox on a normal device, readable on a rooted one. | Back the cookie jar with secure storage, or shorten the refresh lifetime on mobile. |
| M-3 | Med | No crash or error reporting (H-6). | See H-6. |
| M-4 | Med | No certificate pinning and no root/jailbreak signal. For an attendance app the realistic abuse is a tampered client faking location or a face frame. | Server-side liveness (H-5) is the real control; pinning is optional for beta. |
| M-5 | Low | No code shrinking/obfuscation configured for the Android release build. | Enable R8 with the Flutter defaults. |
| M-6 | Info | Not verified here: `flutter analyze`, `flutter test`, iOS signing, store listing requirements (camera, location and biometric data declarations). | Run in CI and review store data-safety forms before submission. |

## 8. Repository and process hygiene

| # | Sev | Finding | Fix |
|---|---|---|---|
| R-1 | Med | Plaintext database dumps and VPS copies sit in `backups/` on the laptop drive (git-ignored, so not in the repo). They contain whatever personal data the databases held. | Encrypt or delete; never keep real beta data here. |
| R-2 | Med | `apps/api/.env` on the laptop holds real Azure and Face++ keys; root `.env` and `apps/.env` also exist (ignored). The latter holds live Supabase credentials for a project HRMS does not use. | Rotate anything not needed, delete the Supabase file. |
| R-3 | Low | Tracked files that do not belong in the product repo: `mavericks-kit.zip` (3.8 MB), `shirt.png`, `shorts.png`, `landing-page-code.md`, a stale `pending task.md`, `work done/`. | Remove in a cleanup PR. |
| R-4 | Low | The session working folder points at an old mount (`varun20`); the repo is at `varun21`. Tools and venv shebangs keep breaking on this. | Mount the drive by label/UUID at a fixed path. |
| R-5 | Info | The branch model (`test` → PR → `main`, auto-merge on green, human merge for migrations and CI files) is sound and is being followed. | Keep. |

## 9. Suggested order of work

**Week 1 — unblock**
1. Fix B-2 (scope on salary setup) so CI is green, merge `test` → `main` including the migration.
2. B-1: clean `hrms_prod`, seed guard, platform admin, key provisioning.
3. B-3: alerts on, monitor timer on, Drive token rotated, secrets escrowed, restore drill.
4. H-1: raise per-IP auth limits. D-3: role timeouts. D-2: four indexes.
5. B-4: release keystore, base-URL guard, minimum-version check.

**Week 2 — harden and rehearse**
6. H-2 (platform MFA or IP restriction), H-3 (change password), H-5 (liveness on), H-6 (error tracking), H-7 (purge job), H-9 (Node 22), H-8 (ESLint blocking).
7. B-5 and B-6 with the owner: notices, DPA, retention, policy decisions or payroll hidden.
8. B-7: full scripted pass on a staging copy; smoke e2e added.

**During beta**
9. Remaining medium/low items; resource limits and Postgres tuning (H-4); deploy tagging and rollback (H-10).

## 10. What I would want verified on the server before go-live

These could not be checked from the repository:
- Which database the running app uses, and whether seed/demo users exist in it.
- `hrms_app` still lacks UPDATE/DELETE on the six append-only tables.
- TLS certificate auto-renewal, HSTS present on the web and API hosts, `/metrics` and `/docs` return 404 from outside.
- `ENVIRONMENT=production`, `TRUSTED_PROXY_HOSTS` matches the real Docker subnet (otherwise every user shares one rate-limit bucket), `FACE_LIVENESS_ENGINE` value, `EMAIL_PROVIDER` delivering real mail with SPF/DKIM.
- Backup timer last-success time, alert email actually received, free disk and memory headroom.
