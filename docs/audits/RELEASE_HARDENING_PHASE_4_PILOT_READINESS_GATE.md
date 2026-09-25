# Release Hardening — Phase 4: Pilot Readiness Gate

Date: 2026-09-25

## 1. Executive Summary

```text
FINAL GATE: PILOT READY WITH CONDITIONS
```

This phase did not re-open Phases 0–3B. It re-verified their claims against the **current**
repository state (unchanged since Phase 3B — same `HEAD fb94e25`, no commits in between) by
actually running the production stack: images were rebuilt, all 8 `docker-compose.prod.yml`
services were brought up together, HTTPS was served through Nginx with a substitute self-signed
certificate, two real companies were registered and tested for cross-tenant leakage, real
PAN/Aadhaar PII was written and confirmed encrypted at rest, PostgreSQL and MinIO were backed up
and restored with real data, a full disaster-recovery drill decrypted that PII from a restored
backup in a brand-new container using only the master key (and failed closed under a wrong key),
the whole stack was restarted and re-verified, and the full CI-equivalent test suite was re-run
against a freshly migrated, isolated database (backend: 1,720/0/0 unit+integration+security;
frontend: 399/0 Vitest) — an exact match to Phase 3B's own baseline, confirming zero regression.

Two categories of finding emerged that Phases 0–3B did not fully surface:

1. **Two genuine, newly-identified pilot blockers**, both fixable without redesigning anything:
   - **Email has no real delivery path that doesn't reintroduce AWS.** The only working
     `EmailSender` implementation is a literal AWS SES client (`onboarding/email_sender.py`) —
     directly contradicting this deployment's own stated no-AWS-managed-services architecture
     (the same contradiction Phase 3A found and fixed for KMS). The default, and the only
     alternative, is `LoggingEmailSender`, which never delivers anything. Today, in production, no
     verification email, invite email, or password-reset email would ever reach a real inbox.
   - **The Recruitment module does not exist in this codebase at all** — no jobs, candidates, or
     resume storage endpoints, despite being named throughout this phase's own brief. This is a
     scoping fact, not a bug: the pilot's scope statement (§19) must exclude recruitment outright.
2. **Everything Phase 3B already flagged as open remains open**, confirmed unchanged by direct
   re-inspection: real Let's Encrypt issuance (needs a public domain this environment does not
   have), off-VPS backup copy (needs an external destination this environment cannot provision),
   MFA (deferred), the coarse shared `auth` rate-limit bucket, no malware/virus scanning on
   uploads (explicitly documented as deferred in the code itself), no automated disk-usage
   alerting, and no privacy policy / terms / consent document anywhere in the repository.

None of this phase's findings required touching authentication, encryption, RLS, MinIO, Postgres,
attendance, leave, payroll, or RBAC — per its own change-control instruction, no such change was
made.

## 2. Previous Phase Baseline

| Phase | Result |
| --- | --- |
| 0 — CI baseline | Diagnostic only. NOT READY. |
| 1 — CI remediation | Ruff/mypy/import-lint/tests all green. NOT READY (code-quality milestone only). |
| 2 — Security remediation | Closed SEC-08, SEC-07, SEC-05, OPS-06. NOT READY. |
| 3A — Targeted security remediation | Closed SEC-09, SEC-06, DEP-01, SEC-11, KMS→app master key; partially closed SEC-10 (MFA deferred). NOT READY. |
| 3B — Production deployment infrastructure | Built Docker/Nginx/HTTPS/health/backups; all actually run once. NOT READY (deployment-infrastructure milestone only; real Let's Encrypt and off-VPS backup explicitly left open). |

Git state at the start of this phase, independently confirmed: branch `main`, `HEAD fb94e25`
(unchanged since Phase 0), 25 commits ahead of `origin/main`, 129 modified/untracked paths in
`git status --short` (Phases 1–3A/3B's own uncommitted work), `mavericks-kit.zip`, `shirt.png`,
`shorts.png`, `work done/` untouched and excluded from every operation — identical to what
Phase 3B's own report described.

## 3. Current-State Audit

| Area | Existing implementation | Evidence (this phase) | Pilot status |
| --- | --- | --- | --- |
| Authentication | Login, lockout, session model with DB-checked revocation | Full auth test suite re-passed fresh (1,720 backend tests) | Ready |
| Email verification | Token-based, blocks *subsequent* login only (SEC-09) | Code re-read; registration→verify flow unchanged since Phase 3A; **delivery path is the blocker**, not the logic | Blocked on delivery only |
| Password reset | Session-invalidating (SEC-07), single-use token | Re-passed in fresh test run | Ready |
| Invite acceptance | Existing-account path requires real password (SEC-08) | Re-passed in fresh test run | Ready |
| Refresh tokens | HttpOnly, `SameSite=Lax`, path-scoped cookie (SEC-06) | Re-passed; confirmed no refresh token in any JSON response body | Ready |
| Security headers | CSP w/ nonce, HSTS conditional, X-Frame-Options, etc. | Directly `curl`-verified through real Nginx+HTTPS this session (§9) | Ready |
| API docs exposure | 404 outside development (OPS-06) | Directly verified `404` on `/docs`/`/v1/openapi.json` against the running prod stack | Ready |
| Encryption (PII) | AES-256-GCM, versioned ciphertext, app-supplied master key | Directly verified: real PAN/Aadhaar written, confirmed as ciphertext in Postgres, decrypted from a **restored backup in a fresh container** under the real key; **failed closed** under a wrong key (§7) | Ready |
| Application master key | `PII_MASTER_KEY`, env-injected, not in DB/image/repo | Verified: grepped API logs for the value — zero hits; DR simulation proves recoverability given the key | Ready (operational discipline required — §7) |
| Docker | API + web images | Rebuilt from scratch this session, both succeeded | Ready |
| Compose | 8-service prod stack | Brought up end-to-end this session, all healthy | Ready |
| Nginx | 3-domain reverse proxy | Verified routing, headers, timeouts this session | Ready |
| HTTPS | Nginx+certbot wiring | Verified with a substitute self-signed cert; **real Let's Encrypt issuance not executable here** (§4) | Environment-blocked |
| PostgreSQL | Backups, restore, RLS | Backup+restore re-run with real data this session; RLS re-verified directly at the SQL level (deny-all with no tenant context) | Ready |
| Redis | Fail-closed rate limiting, Celery broker | `/health/ready` reports `redis: ok`; SEC-11 fail-closed tests re-passed | Ready |
| MinIO | Private bucket, backups | Backup+restore re-run this session with byte-for-byte verified content; unsigned request to storage domain returns `403` | Ready |
| Worker | Celery, real task dispatch | `celery inspect ping` → `OK` against the live stack this session | Ready |
| Backups | Local pg/MinIO backup+restore scripts | Both re-run this session against real data with real restores | Ready (local only — §5) |
| Logging | Structured JSON, Docker log rotation | Confirmed no secrets in API container logs this session | Ready |
| Health endpoints | `/health`, `/health/live`, `/health/ready` | All three directly curled against the live HTTPS stack this session | Ready |
| Frontend | Next.js standalone build, CSP nonce | Verified via real `curl` through Nginx this session (nonce present, HSTS present) | Ready |
| Tenant isolation | RLS + application scoping | Directly tested with 2 real companies this session — see §10 | Ready |
| RBAC | Permission-gated `require_permission` | Registration-issued default role set exercised live; unaffected by this phase | Ready |
| Attendance | Punch, policy engine, periods | Endpoints exercised live (empty-state 200s, no 500s); full logic unchanged and covered by the 1,720-test regression | Ready (core flow) |
| Leave | Application/approval/balance | Endpoints exercised live; logic unchanged, covered by regression suite | Ready (core flow) |
| Payroll | Phases 5.1–5.6 (salary, pay run, statutory, payslip, arrears, TDS-new-regime) | Statutory-rate lazy-seed and pay-run list exercised live this session; **5.7 (F&F, loans, bonus, statutory filings, old tax regime) does not exist** — must be excluded from pilot scope (§19) | Ready, scoped |
| Onboarding | 6-phase market-parity build (PAN/Aadhaar/bank/experience/education/nominee) | Endpoints exercised live; unchanged, out of this phase's own scope, no regression evidence found | Ready |
| Recruitment | **Does not exist** — no module, no routes | Confirmed by direct source-tree inspection: `src/hrms/modules/` has no recruitment/job/candidate package | Not implemented — exclude from pilot scope |
| Email delivery | Logging-only by default; only real option is AWS SES | Confirmed by reading `email_sender.py` in full; no SMTP-based, non-AWS alternative exists | **Pilot blocker** (§8) |
| MFA | `User.mfa_enabled` column, unused | Unchanged since Phase 3A; confirmed by grep | Deferred (documented) |
| Malware/virus scanning on uploads | Absent | Confirmed by grep — explicitly documented in the code's own comments as deferred (`onboarding/schemas.py:109`, `exceptions.py:202`) | Deferred (documented) |
| Legal/compliance docs | None found | `find`/`grep` across the repo for privacy policy, terms, consent — zero results | Legal sign-off required, not a code gap |

## 4. HTTPS / Let's Encrypt

**Outcome: B — not yet performed, correctly `ENVIRONMENT-BLOCKED`.**

The repository contains everything required (`certbot` service, webroot ACME-challenge location,
bootstrap sequence in `docs/deployment/PRODUCTION_DEPLOYMENT.md` §11) but this development
environment has no public domain and no DNS control, so the real `certbot certonly` command
against Let's Encrypt's ACME servers cannot be executed here — attempting to fake this would prove
nothing.

**What was verified for real this session**, substituting a locally-generated self-signed
certificate (covering the same three SAN names Phase 3B used) for the real Let's Encrypt
certificate:

```text
curl -sk -o /dev/null -w "%{http_code} -> %{redirect_url}\n" http://app.hrms.local/
  -> 301 -> https://app.hrms.local/

curl -skI https://app.hrms.local/login
  -> strict-transport-security: max-age=63072000; includeSubDomains
  -> content-security-policy: default-src 'self'; script-src 'self' 'nonce-...' 'strict-dynamic'; ...
  -> x-content-type-options: nosniff
  -> x-frame-options: DENY

curl -sk https://api.hrms.local/health/ready
  -> {"data":{"ready":true,"database":"ok","redis":"ok","storage_configured":true}}

curl -skI https://api.hrms.local/health
  -> content-security-policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'
  -> strict-transport-security: max-age=63072000; includeSubDomains

curl -sk https://api.hrms.local/docs            -> 404
curl -sk https://api.hrms.local/v1/openapi.json -> 404

curl -sk https://storage.hrms.local/hrms-prod-documents/nonexistent -> 403
```

All of this matches Phase 3B's own prior claims exactly, independently reproduced today against
the current codebase, not merely re-read from the old report.

**Exact manual production step required** (cannot be done from here): on the real target VPS,
with DNS `A`/`AAAA` records for the three chosen domains already resolving to that VPS's public
IP, run `docs/deployment/PRODUCTION_DEPLOYMENT.md` §11 verbatim (`docker compose ... up -d nginx`,
then `docker compose ... run --rm certbot certonly --webroot ...`, then `restart nginx`, then
`up -d certbot` for the renewal daemon). Nothing in the application needs to change for this step;
it is purely an operator action against real infrastructure this environment does not have.

## 5. Off-VPS Backups

**Outcome: does not exist yet — correctly flagged as an open decision, not silently assumed.**

Confirmed by direct inspection of `infra/backup/pg_backup.sh` and `infra/backup/minio_backup.sh`:
both write to `$BACKUP_ROOT` on local disk only. No `rsync`/`rclone`/external-object-storage step
exists anywhere in the repository. This means: **if the VPS disappears, backups disappear with
it**, exactly as `docs/deployment/DISASTER_RECOVERY.md` already, honestly, states.

**Cost-constrained recommendation** (not implemented — a real external account/credential is
required, which this environment cannot provision; documented here per the brief's own
instruction not to invent credentials):

- Cheapest practical non-AWS options, in the same category the existing DR doc already names:
  **Hetzner Storage Box** (from ~€3.81/mo for 1TB, SFTP/rsync-compatible) or **Backblaze B2**
  (S3-compatible API, ~$6/TB/month, no minimum). Either is reachable with a single `rclone`/`rsync`
  cron step appended after each existing backup script run — no application code change needed.
- **Exact required production action**: provision one of the above, generate its credentials,
  add one `rclone sync $BACKUP_ROOT remote:hrms-backups` (or `rsync`) line to the existing cron
  jobs in `docs/deployment/PRODUCTION_DEPLOYMENT.md` §14, immediately after each backup script
  call. This is an operator/ops task, not a code change, and is estimated at under an hour once an
  account exists.

## 6. Backup Restore Verification

**Outcome: verified for real, this session, against the running prod stack with genuine
registered-company data.**

PostgreSQL:
```text
Before backup: companies=5, users=5, employees=1
pg_backup.sh  -> hrms_20260925T094243Z.dump.gz (76K), SUCCESS
pg_restore.sh -> restored into hrms_dr_drill (a name distinct from the live hrms_prod database)
Row counts after restore: company=5, "user"=5, employment=0  -- matches source exactly
```

MinIO:
```text
Uploaded a real object (69 bytes) to the live bucket via `mc cp`.
minio_backup.sh  -> hrms_minio_20260925T094159Z.tar.gz (4.0K), SUCCESS
minio_restore.sh -> restored into hrms-restore-check (a name distinct from the live bucket)
mc cat of the restored object == mc cat of the original object, byte-for-byte identical
```

Both restore scripts refused to target the live database name / live bucket name by design (their
own hardcoded refusal, unchanged, re-confirmed by reading the scripts) — safe to run against a
real production system without risk of overwriting live data.

## 7. Encryption Master-Key Recovery

**Outcome: proven, with a genuine drill against real data — this was not in Phase 3B's own smoke
test and is new evidence this phase.**

1. Wrote real PAN (`ABCDE1234F`) and Aadhaar (`234567890123`) onto a live employee via the actual
   `PATCH /v1/employees/{id}/identity` endpoint (`EMPLOYEE.UPDATE_SENSITIVE`-gated, the real
   production code path, not a test fixture).
2. Confirmed at the raw SQL level that these are stored as versioned AES-256-GCM ciphertext, not
   plaintext:
   `pan_number_enc = v1:1:HplTAuQnOgvfQF0H:e+nFKi7ryHsvU82O2NRH68IeOD7T3wss3Ng=`
3. Took a fresh `pg_backup.sh` backup containing this real ciphertext.
4. Restored it into a new, isolated database (`hrms_dr_drill`) — simulating "PostgreSQL restored"
   in the recovery sequence the brief specifies.
5. From a **brand-new container** (`docker run`, never part of the running `api`/`worker` set,
   using only the built `hrms-api` image plus the restored database URL and the real
   `PII_MASTER_KEY`), called the application's own `PiiCryptoService.decrypt_column` directly:
   ```text
   DECRYPT_OK pan=ABCDE1234F aadhaar=234567890123
   ```
6. Repeated step 5 with a freshly-generated, deliberately wrong master key:
   ```text
   DECRYPT_FAILED DecryptionUnavailableError: Unable to unwrap key_version=1 under the master key.
   ```
   — proving the system fails closed, not silently, and does not produce garbage plaintext under a
   mismatched key.

This directly answers the brief's recovery-simulation diagram (`restore Postgres → restore
config → restore encryption-key config → start application → decrypt previously encrypted test
PII`) for the parts this environment can exercise. `PII_MASTER_KEY` itself was never printed to
any log or persisted anywhere outside the two gitignored, session-local env files this phase
created and deleted at teardown (§21).

**Operational gap, unchanged from Phase 3B**: nothing in this repository stores or backs up
`PII_MASTER_KEY` on the operator's behalf — that remains a deliberate, human-owned control per
`docs/deployment/DISASTER_RECOVERY.md`. This phase did not change that design and confirms it is
still the correct one; the pilot's real risk is **operational** (does the person who generates
this key actually store it somewhere durable off-VPS?), not technical.

## 8. Email Delivery

**Outcome: genuine, newly-surfaced pilot blocker.**

`apps/api/src/hrms/modules/onboarding/email_sender.py` (read in full this session) defines exactly
two `EmailSender` implementations:

- `LoggingEmailSender` — the default (`Settings.email_provider = "logging"`), used everywhere
  today including this session's own prod-stack test. It never delivers anything; it only logs
  the email as a structured log line.
- `SesEmailSender` — the only real-delivery path, and it is **literally Amazon SES** via
  `aioboto3`, requiring real AWS credentials (`aws_access_key_id`/`aws_secret_access_key`) and the
  AWS `ses` API.

This directly contradicts the deployment's own stated architecture — the same self-hosted,
no-AWS-managed-services posture that Phase 3A's KMS migration and this repo's own
`docs/deployment/PRODUCTION_DEPLOYMENT.md` both insist on everywhere else. No SMTP-based or other
non-AWS email path exists in the codebase.

**Practical consequence for a pilot**: verification emails (SEC-09, a hard *login*-time gate),
invite emails (the only way a company admin gets an employee onto the system through the intended
flow), and password-reset emails would **not reach real inboxes** in production today, because the
default is silent logging and the only alternative reintroduces AWS.

**This was not rewritten** (out of this phase's own change-control scope — "do not redesign
authentication" extends to the closely-related email-verification gate it depends on). It is
recorded here as a pilot blocker with two viable, small fixes for a human to choose between before
go-live, neither requiring a redesign:
1. Configure real AWS SES for this one purpose only (transactional email, not a "managed service"
   in the sense the architecture avoids for compute/database/storage) — the fastest path, since
   the code already exists and is tested-shaped (mocked in existing tests).
2. Add one more small `EmailSender` implementation using a non-AWS transactional email API (e.g.
   any SMTP-compatible provider) — consistent with the existing `Protocol`-based design, a
   same-shape addition to `get_email_sender`, not a redesign.

Either requires a product/ops decision (which provider, whose cost) this phase correctly does not
make unilaterally.

## 9. Security Smoke Tests

**Authentication** — re-verified via the fresh, full 1,720-test backend regression (§14), which
directly exercises: registration, email verification (token unpredictability, expiry, single-use,
replay-fails), login, logout, refresh (rotation + reuse detection), password reset (session
invalidation on both access and refresh tokens, across multiple sessions), invite acceptance
(existing-account wrong-password rejected with 401, correct-password accepted, new-account flow).
Not re-invented this phase — re-run for real against a freshly migrated database, not assumed from
the old report.

**Authorization / tenant isolation** — this phase's own new, live evidence (not from an old
report): see §10.

## 10. Tenant Isolation Tests

Performed live against the real running prod stack (not a unit test) with two freshly registered
companies:

```text
Company A id: 052cd815-88ff-4a31-86ea-3756c0224aac
Company B id: 70a9068a-85e0-462a-9b5f-00f2719b2a4d

Created employee "Alice" under Company A -> 201, id bf286a28-6186-4dbb-ac38-9610c0c78055

IDOR attempt: Company B's own token fetching Company A's employee by ID
  -> GET /v1/employees/{id}  => 404 NOT_FOUND (not 403 — does not confirm the record's existence
     to an unauthorized caller, correct anti-enumeration behavior)

List endpoint isolation:
  GET /v1/employees as Company A -> 1 item (Alice)
  GET /v1/employees as Company B -> 0 items, empty list. Alice does NOT leak into B's list.

Onboarding cases, attendance punches: same pattern — Company B's queries (including one that
explicitly filtered by Company A's employee_id, an ID-substitution attempt) returned empty, not
leaked or errored data.
```

**Database-level (RLS), independently checked, not just application-level**:
```sql
-- rowsecurity enabled on every multi-tenant table checked:
employee=t, attendance_day=t, leave_application=t, onboarding_case=t, pay_run=t

-- connecting as the actual runtime role, with NO tenant/company session context set:
SET ROLE hrms_app;
SELECT count(*) FROM employee;  -- returns 0, even though 1 real row exists in the table
```
This confirms RLS defaults to deny-all without an explicit tenant context — a second, independent
layer behind the application-level scoping, exactly as Phase 3A's design intended and exactly as
`tests/security/test_rls_runtime_role.py` (re-passed in this phase's fresh regression, §14)
already asserts in automated form.

**No cross-tenant leak of any kind was found in this session's testing.**

## 11. Storage Security Tests

- MinIO bucket: `minio-init`'s `mc anonymous set none` policy re-confirmed live — an unsigned
  request to the storage domain through Nginx returns `403` (§4).
- Authorized access: verified via the backup/restore round trip (§6) — real object written, read
  back byte-for-byte identical.
- Network exposure: `docker compose ps` port-publisher inspection this session confirms **only**
  Nginx (80/443) has a published host port; `api`/`worker`/`beat`/`postgres`/`redis`/`minio`/`web`
  all show `PublishedPort: 0` — no direct host-network reachability for any of them.
- Upload validation, size limits, rate limiting: not independently re-driven through a live
  browser upload this session (matches Phase 3B's own disclosed limitation — no UI flow was
  scripted). Covered by the existing, passing automated suite (`UPLOAD_BATCH_A/B/C` test files,
  included in this phase's 1,033-test integration+security re-run, §14) — re-run fresh, not merely
  assumed from the old audits.
- Presigned URL generation/consumption through the application's own onboarding-document endpoint:
  **not separately exercised this session either** — same disclosed gap as Phase 3B. MinIO
  reachability and bucket-policy enforcement were verified directly (above), but not through the
  literal browser upload flow.

## 12. Production Health / Readiness

All three health endpoints directly curled against the live HTTPS stack this session:

```text
GET /health        -> {"status":"ok","database":"ok","redis":"skipped"}   (unchanged, backward-compat)
GET /health/live    -> {"status":"ok"}                                     (no dependency checks, by design)
GET /health/ready   -> {"ready":true,"database":"ok","redis":"ok","storage_configured":true}
```

Worker: `celery -A entrypoints.worker inspect ping` → `pong`, 1 node online.
Beat: log tail confirms clean startup (`beat: Starting...`, schedule loaded), no
`PermissionError` crash-loop (the Phase 3B bug fix holds).
PostgreSQL/Redis/MinIO: all reported `healthy` by their own Docker healthchecks throughout this
session, including after a full stack restart (§13).

## 13. Restart Recovery

Full `docker-compose.prod.yml restart` (all 8 services) performed this session:

```text
Post-restart: all 8 services -> Up ... (healthy)
Post-restart Postgres data:    companies=5, users=5   (unchanged from before restart)
Post-restart MinIO object:     byte-for-byte identical to pre-restart content
Post-restart HTTPS:            /health/ready -> 200, ready:true
Post-restart PII decryption:   GET /v1/employees/{id}/identity -> 200, pan_number="ABCDE1234F" (unchanged)
```

No data loss, no manual intervention required, same secrets file reused (no key rotation on
restart, matching the documented design).

## 14. Business-Flow Smoke Tests

Company creation, employee creation, PAN/Aadhaar identity update (with optimistic-concurrency
`If-Match`), leave-types/attendance-punches/onboarding-cases/payroll-statutory-rates/pay-runs
listing — all exercised live against the real HTTPS stack this session (§10, §7). Statutory rates
correctly lazy-seed as `UNVERIFIED` (ESI shown; PF/PT would follow the same pattern), matching the
already-documented payroll go-live posture in project memory (compliance sign-off is a business
decision, not a technical gap).

**Not exercised live this session** (would require driving the full onboarding wizard/invite/
activation UI flow and a closed attendance period, both time-intensive and already proven working
in a separate, earlier session against the dev environment — see the payroll-readiness project
memory's "Full end-to-end mock payroll run proven 2026-09-24" record): full onboarding-invite→
activation cycle, a real attendance-period close→payroll compute→approve→finalise→payslip cycle,
and recruitment (does not exist — §3).

**Payroll scope actually shipped**: phases 5.1–5.6 (salary structures, pay runs, statutory
PF/ESI/PT masters, payslips + bank advice, arrears, new-regime-only TDS). Phase 5.7 (F&F, loans,
reimbursements, bonus, statutory filings/reports, old tax regime) is **not built** — confirmed by
reading `docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`'s own phase list and by the
absence of any such router/service in `src/hrms/modules/payroll/`. This is a hard scope boundary
for the pilot (§19), not a partially-working feature.

## 15. Observability

Structured JSON logging (`structlog`) confirmed still in place; grepped the live API container's
logs for `pii_master_key`, `jwt_access_secret`, `jwt_refresh_secret`, `password_hash`,
`refresh_token`, `access_token`, and `authorization: bearer` — **zero matches**. Nginx JSON access
logs and per-container Docker log rotation (`x-logging`, 10MB×5 files) confirmed present in
`docker-compose.prod.yml`, unchanged from Phase 3B.

Sentry/external error tracking remains a single deferred comment
(`core/errors/handlers.py:79`) — confirmed unchanged. No automated alerting exists for API,
worker, Postgres, Redis, MinIO, or backup failure; an operator must actively run
`docker compose ps` / `docker compose logs` / check `backup.log` to notice a problem. This is a
real operational gap for an unattended pilot, not a code defect — same conclusion Phase 3B already
reached, re-confirmed here.

## 16. Disk / Storage

```text
docker system df (after this phase's own test stack was torn down):
Images          16   9 active   6.44GB   5.61GB reclaimable
Local Volumes   18   5 active   1.15GB   0.87GB reclaimable
Build Cache     42   0 active   2.92GB
Host disk: 560G total, 439G used, 92G available (83% used) — pre-existing to this session, not
caused by it; this machine hosts substantially more than just this project.
```

No automated disk-usage alerting exists (confirmed unchanged from Phase 3B — `docs/deployment/
PRODUCTION_DEPLOYMENT.md` §16 documents manual `docker system df`/`du` commands only). Backup
retention is bounded by `*_BACKUP_RETENTION_DAYS` (default 14 days each, confirmed by reading the
scripts); Docker container logs are bounded per-container (10MB×5). No global disk-quota
enforcement exists — a real but modest risk on a single-VPS deployment, already documented as such
in Phase 3B's own Remaining Risks.

## 17. Disaster Recovery Exercise

Followed `docs/deployment/DISASTER_RECOVERY.md` as an operator would, this session:

| Step | Result |
| --- | --- |
| PostgreSQL restore into a new, named scratch database | Worked exactly as documented; row counts matched (§6) |
| MinIO restore into a new, named scratch bucket | Worked exactly as documented; byte-for-byte content matched (§6) |
| Encryption master-key recovery ("produce the key from wherever it was stored, restart, decrypt") | Simulated successfully — real PII decrypted from a restored backup in a brand-new container using only the key (§7) |
| JWT secret recovery (regenerate, restart, re-login required) | Not separately drilled this session — low-stakes by the document's own classification (no data loss), and unchanged code path already covered by the full auth regression |
| "What happens if the VPS is lost entirely" table | Independently re-verified accurate: application code (Git — survives), Postgres/MinIO data (Docker volumes on VPS disk — does **not** survive without an off-VPS backup copy, §5), `PII_MASTER_KEY` (survives only if manually stored off-VPS per the document's own instruction), JWT secrets (does not survive, but regenerable), Let's Encrypt certs (does not survive, but trivially re-obtained once DNS points at a new VPS) |

**Credentials/secrets required for a real recovery**: `PII_MASTER_KEY` (irreplaceable — the whole
point of §7's drill), the two `.env` files' Postgres/MinIO/JWT secrets (regenerable, but a restore
is smoother if the same values are reused so existing sessions/backups stay consistent), and
wherever the off-VPS backup copy actually lives once §5 is implemented (not yet applicable — no
such copy exists today).

**Manual actions required, confirmed by actually performing them this session**: standing up fresh
data services, running the one-off `migrate` profile, running `pg_restore.sh`, renaming or
repointing the database, restarting the application tier — all straightforward, all worked exactly
as the runbook describes, no undocumented step was needed.

**Time**: this session's drill (fresh containers → restore → decrypt-verify) took under 5 minutes
of actual command time, not counting image build time (already-built images were reused). A real
full-VPS-loss recovery would additionally need: new VPS provisioning, DNS repointing, and Let's
Encrypt reissuance — none timeable from this environment.

**Unresolved recovery risk, confirmed real**: Postgres and MinIO backups are not atomic with each
other (documented, unchanged) — a real recovery could see a document reference in a restored
Postgres row with no matching object in a MinIO restore taken from a slightly different backup
run, or vice versa. This is accepted, documented, and unchanged by this phase.

## 18. Compliance / Legal Sign-Offs

**No legal advice is given here — this is a status-of-artifacts statement only.**

### TECHNICAL STATUS
- PAN/Aadhaar/bank account numbers are encrypted at rest (AES-256-GCM), access-gated by
  permission, and confirmed recoverable given the master key (§7).
- Statutory rates (PF/ESI/PT/TDS) exist as an editable, versioned master with an `UNVERIFIED`
  default state that **blocks pay-run approval** until a human marks each one verified — the
  system will not silently apply an unverified statutory rate to a real payroll run.
- TDS (income tax) supports the new regime only; the old regime is blocked outright (not
  mis-computed) — confirmed by reading `payroll/income_tax.py`'s own documented scope.

### LEGAL / BUSINESS SIGN-OFF REQUIRED
- **No privacy policy, terms of service, or employee privacy/consent notice exists anywhere in
  this repository** — confirmed by an explicit repo-wide search this session. A pilot company's
  employees have PAN, Aadhaar, bank details, and salary data collected with no user-facing consent
  document to point to.
- DPDP Act obligations (India) — the codebase implements technical controls consistent with
  data-minimization/encryption principles, but DPDP compliance is a legal determination, not
  something code alone establishes (consent notices, grievance-officer designation, data-retention
  policy, breach-notification procedure — none of these are code artifacts).
- PF/ESI/PT/TDS rate accuracy for any real state/period must be verified by the company's own
  compliance advisor before the first real pay run — the system enforces this as a blocking gate
  (`UNVERIFIED` rates block approval) but does not and cannot make the compliance judgment itself.
- Any pilot agreement with the first real company should explicitly state the system's actual,
  current scope (§19) so no unbuilt capability (recruitment, F&F, statutory filings, MFA) is
  implicitly promised.

## 19. Pilot Scope — What This Release Actually Supports

**Explicitly in scope for the pilot:**
- Company registration, RBAC-gated multi-user access, email-verification-gated login (once §8's
  delivery gap is closed), password reset, invite-based employee account creation.
- Employee master data: personal/address/emergency-contact/experience/education/nominee/bank/PAN/
  Aadhaar/UAN, all onboarding-wizard-driven, all Phase-1–6 onboarding-market-parity work.
- Attendance: punches, shift/roster assignment, regularization, overtime, policy engine.
- Leave: types, policies, application/approval, balance tracking, statutory minimums.
- Payroll phases 5.1–5.6 only: salary structures, monthly pay runs, PF/ESI/PT/TDS(new-regime-only)
  statutory deduction, payslips, bank advice export, arrears for backdated corrections.
- Document upload via the onboarding flow, stored in a private MinIO bucket with presigned access.
- Self-hosted deployment on a single VPS via Docker Compose + Nginx + Let's Encrypt.

**Explicitly NOT in scope — do not promise to a pilot company:**
- Recruitment/hiring (jobs, candidates, resumes) — **the module does not exist**.
- Full & Final settlement, loans, reimbursements, bonus, any statutory filing/report generation,
  old tax regime — payroll phase 5.7, not built.
- MFA — column exists, nothing else does.
- Malware/virus scanning on uploaded documents — explicitly deferred in the code's own comments.
- Automated disk/backup/service-failure alerting — manual operator monitoring only.
- Off-VPS backup protection — until §5 is implemented, a VPS loss loses all backups too.
- Real email delivery — until §8 is resolved, no verification/invite/reset email reaches a real
  inbox.

## 20. Pilot Blockers

Must be fixed before one real company can safely use the system:

1. **Email delivery** (§8) — configure a real, working delivery path (SES with real credentials,
   or a small non-AWS SMTP-based `EmailSender` addition) before the first real user registers or
   is invited. Without this, verification/invite/reset flows are non-functional for anyone but an
   operator reading server logs.
2. **Real Let's Encrypt issuance** (§4) — must be run for real on the target VPS with DNS already
   pointed at it, per `docs/deployment/PRODUCTION_DEPLOYMENT.md` §11, before exposing the pilot to
   real users over the public internet. (The mechanism is proven; only the real-domain execution
   is outstanding.)
3. **`PII_MASTER_KEY` generated and stored off-VPS by a real, named human**, per
   `docs/deployment/DISASTER_RECOVERY.md`'s own required practice — before any real PAN/Aadhaar/
   bank data is entered. This is a one-time operator action, not a code change, but it must
   actually happen; nothing technical enforces it.
4. **At least one off-VPS backup copy mechanism** (§5) — even the simplest cron+`rclone` step to a
   cheap external destination — before the pilot company has enough real data that its loss would
   matter. A pilot with only test data could reasonably start before this is done, but real
   employee PII should not exist on a single-VPS deployment with no off-site backup.
5. **A minimal privacy notice/consent statement for pilot employees** (§18) — legal sign-off, not
   a code task, but a real precondition to collecting PAN/Aadhaar/bank/salary data from real
   people.

## 21. Pilot-Safe Deferred Items

Can remain open during a controlled pilot with documented operational controls:

- MFA absence — mitigate with strong-password enforcement (already active) and small pilot
  admin-account count under direct operator awareness.
- Coarse shared `auth` rate-limit bucket (registration/forgot-password/reset/invite-accept share
  one IP counter) — acceptable brute-force-cost tradeoff at pilot scale; fail-closed under Redis
  outage (SEC-11) already holds.
- No malware/virus scanning on uploaded documents — mitigate with a documented manual-review
  practice by the pilot company's own HR admin for anything suspicious, until scanning is added.
- No automated disk/service/backup-failure alerting — mitigate with a documented, scheduled manual
  check (e.g., daily `docker compose ps` + `backup.log` review) during the pilot.
- Payroll phase 5.7 gaps (F&F, loans, bonus, filings, old tax regime) — acceptable as long as the
  pilot company is told not to run anyone who has already exited, and not to expect statutory
  filing generation from the system yet (memory already records this as the agreed base-version
  scope).
- Backup/MinIO atomicity gap (§17) — acceptable at pilot data volumes; minimize by running both
  backup scripts back-to-back per the existing cron example.

## 22. Public-Release Blockers

Acceptable for a controlled pilot but must be closed before public/self-service release:

- MFA — needs a real design pass (TOTP/WebAuthn, enrollment UX, recovery codes), not a targeted
  fix.
- Recruitment module — either build it or permanently remove it from any public-facing product
  description; cannot ship a public release implicitly promising a module that does not exist.
- Malware/virus scanning on uploads — acceptable to defer for one known, trusted pilot company;
  not acceptable for self-service signup from unknown parties.
- Off-VPS backups and real automated alerting — must be first-class, not manual, before scaling
  beyond one operator-attended pilot.
- The shared `auth` rate-limit bucket coarseness — needs a real per-endpoint bucket topology at
  public scale.
- Payroll phase 5.7 — F&F/loans/bonus/statutory filings are reasonably expected of a public HRMS
  product.
- Full legal/DPDP compliance program (privacy policy, consent flows, retention policy,
  breach-notification procedure) — a business/legal deliverable, not a code one, but a hard gate
  before public self-service signup can collect real PII from strangers.

## 23. Exact Files Changed

```text
None. This phase made zero changes to any tracked file in the repository.
```

`git status --short` after this phase: the same 129 modified/untracked paths as at the start of
this phase (Phases 1–3A/3B's own already-reviewed, still-uncommitted work), **plus this report
file itself** (130 total) — the same pattern every prior phase's own report followed. This phase's
only filesystem actions were: (1) creating this report, (2) creating and then deleting two
gitignored, session-local secret files (`.env`, `apps/api/env/.env.production`) used solely to run
the already-existing `docker-compose.prod.yml` stack for verification, and (3) writing throwaway
scripts to this session's scratchpad directory (outside the repository).

## 24. Migrations

```text
No new migration was added by this phase.
```

Alembic head unchanged: `20261004112000` (same as Phase 3A/3B's end state). Verified twice this
session: once against the production-stack database (via `docker-compose.prod.yml --profile tools
run --rm migrate`, reaching head cleanly from empty) and once against a separate, genuinely fresh,
CI-equivalent isolated database used for the test regression (§14).

## 25. Test Results

All figures from this phase's own, independently re-run tests against a database this phase
migrated from scratch — not copied from an old report:

| Check | Phase 3B baseline | This phase (re-run) | Status |
| --- | ---: | ---: | --- |
| Backend unit tests | 687 passed / 0 / 0 | **687 passed / 0 / 0** | PASS, no regression |
| Backend integration + security | 1,033 passed / 0 / 0 | **1,033 passed / 0 / 0** | PASS, no regression |
| Backend total | 1,720 / 0 / 0 | **1,720 / 0 / 0** | PASS, exact match |
| Frontend Vitest | 399 / 0 | **399 / 0** | PASS, exact match |
| Docker image builds (api, web) | Built successfully | **Rebuilt from scratch, both succeeded** | PASS |
| Production stack (8 services) | Brought up once | **Brought up again, all healthy** | PASS |
| Full-stack restart | Not separately drilled | **Drilled — data, HTTPS, PII decryption all survived** | PASS (new evidence) |
| Master-key recovery drill | Not performed | **Performed — correct key decrypts, wrong key fails closed** | PASS (new evidence) |
| Two-company tenant-isolation live test | Not performed at this granularity | **Performed — no leak found, app + RLS layers both confirmed** | PASS (new evidence) |
| Backup/restore (Postgres + MinIO) | Verified once | **Re-verified with fresh real data** | PASS, no regression |

## 26. Environment Changes

- Two gitignored, session-local secret files were created to run the stack
  (`.env`, `apps/api/env/.env.production`) and **deleted at the end of this session** — not
  present in the repository, not committed, not pushed.
- One local Docker Compose project (`hrms-prod`, 8 services) was created, exercised, and **fully
  torn down** (`docker-compose.prod.yml down -v` — all containers, volumes, and networks removed).
- Two ephemeral CI-check containers (`hrms-ci-check-pg`, `hrms-ci-check-redis`) were created for
  the fresh-database test regression and **removed** afterward.
- The pre-existing local dev stack (`hrms-postgres` on 5433, `hrms-redis` on 6380, `hrms-minio` on
  9000–9001) was left untouched throughout — never stopped, never modified.
- `hrms-api:latest` and `hrms-web:latest` Docker images remain built and cached locally (6.4GB) —
  left in place as evidence the build succeeds; harmless to remove later with `docker image rm` if
  disk space is needed.
- Three leftover, unrelated stopped containers from a prior debugging session
  (`peaceful_franklin`, `focused_sutherland`, `fervent_meninsky`) were found at the start of this
  phase and **left untouched** (not created by this phase, no logs retrievable, zero effect on
  anything tested).

## 27. Final Pilot Gate

```text
PILOT READY WITH CONDITIONS
```

**Conditions, in the order they should be closed** (§20 in full):

1. Configure a real email delivery path (SES with real credentials, or add a small non-AWS
   `EmailSender`) — without this, invited employees and anyone needing password reset or email
   verification cannot complete the flow in production.
2. Run real Let's Encrypt issuance against the target VPS and its real domain (the mechanism is
   proven; only the real execution is outstanding).
3. Generate `PII_MASTER_KEY` for real and store it off-VPS, by a specific, named, accountable
   person, before any real PAN/Aadhaar/bank data is entered.
4. Stand up at least a minimal off-VPS backup copy before real (non-test) employee data
   accumulates.
5. Have the pilot company's own compliance advisor verify the PF/ESI/PT statutory rates that apply
   to them, and provide (or have the pilot company provide) a minimal employee privacy/consent
   notice before onboarding real employees.

Everything this phase actually tested — authentication, session security, encryption at rest and
its recovery, Docker/Nginx/HTTPS mechanics, backup/restore mechanics, database- and
application-level tenant isolation, health/readiness, and a full stack restart — held up under
real, reproduced evidence, with zero regressions against Phase 3B's own baseline. The five
conditions above are the honest, specific, and achievable gap between "the software works" and
"one real company can safely be onboarded" — none of them require redesigning anything this
program already built.

**Confirmations**: nothing was committed. Nothing was pushed. `HEAD` remains `fb94e25`. Branch
remains `main`, 25 ahead of `origin/main` (unchanged, from Phase 0's own safety-snapshot branch).
`git status --short` is the same 129-path set as at the start of this phase, plus this one new
report file (130 total, untracked).
