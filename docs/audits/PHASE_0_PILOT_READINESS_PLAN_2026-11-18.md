# Phase 0 — Make it safe to pilot (detailed plan) — 18 Nov 2026

Read-only planning. No code, data or server was changed. Source: the 11 Nov beta readiness audit (B-1..B-7, H-1..H-10, R-1..R-5), the 16 Nov attendance owner-decision register, the 9 Nov policy decision map, and a status check of the code on `test` made today. The VPS was not inspected.

**Goal.** One small real company (target: 10–50 employees) can use attendance and leave with real data, with backups, alerts, privacy notices and signed-off rules in place. Payroll goes live only if its decisions are settled; otherwise it is hidden.

**Rule for this phase.** No new product features. Only fixes, hardening, decisions and rehearsal.

## 0. Where things stand today (checked 18 Nov)

| Item | Status | Evidence |
|---|---|---|
| Working tree on `test` | Clean (only the two new plan docs untracked). The "uncommitted work" I listed in the first plan has since been committed. | `git status` |
| `test` vs `main` | 6 commits ahead of `origin/main` | `git rev-list` |
| B-2 salary-setup scope gap | Fixed, merged in PR #55 (3cf857d) | memory, 12 Nov |
| B-1 clean production database | **Unknown.** Needs a server check. Seed script still has no environment guard. | `scripts/seed.py` has no ENVIRONMENT check |
| B-3 backups, alerts, key escrow | Drive re-auth, email alerts and monitor timer reported live 12 Nov. Key escrow and restore drill not evidenced. | memory, `GOOGLE_DRIVE_BACKUP_DETAILS_2026-11-10.md` |
| B-4 mobile release build | **Open.** Release still signed with the debug key, `API_BASE_URL` still defaults to `http://localhost:8000`, pubspec says "A new Flutter project", version 0.1.0, no min-version check. | `build.gradle.kts:36-37`, `api_client.dart`, `pubspec.yaml` |
| B-5 privacy, terms, data rights | **Open.** No privacy or terms page in the web app. | no matching files under `apps/web/src/app` |
| B-6 policy decisions | **Open.** 17 attendance decisions (Group A) plus C-01..C-20 plus payroll items. | decision registers |
| B-7 end-to-end pass | **Open** | no record |
| H-1 per-IP auth limits | Open (still 10/min per IP for login, refresh, password) | `identity/router.py:36-57` |
| H-2 MFA / platform console | Open (no TOTP anywhere) | grep |
| H-3 change password | Open (no route) | grep |
| H-4 container limits, Postgres tuning | Open (no limits in `docker-compose.vps.yml`) | grep |
| H-5 liveness default | Open, verify prod env | audit |
| H-6 error tracking | Open (no Sentry or Crashlytics dependency) | grep |
| H-7 purge job | Open (only face cleanup is scheduled) | `celery_app.py` |
| H-8 ESLint blocking | Open (step still "non-blocking") | `ci.yml:448` |
| H-9 Node 22 | Open (`node:20-alpine`) | `apps/web/Dockerfile` |
| H-10 SHA-tagged deploys, rollback | Open | audit |

## 1. Workstreams

Owner key: **You** = a decision or action only you can take. **Me** = code or document work I can do on `test`. **Ops** = done on the VPS, by you or with me watching.

### WS1 — Release hygiene and CI (Me, then You merge) — about 2 days
1. Confirm CI is green on `test` and open the PR `test` → `main`. It contains a migration, so **you** merge it (`gh pr merge --merge`), then fast-forward `test` as AGENTS.md describes.
2. H-8: make ESLint blocking. Downgrade `react-hooks/set-state-in-effect` to a warning, fix the remaining ~25 errors, flip the CI step.
3. H-9: web image and CI to Node 22. Rebuild and run the Vitest and production build.
4. R-3: remove tracked junk (`mavericks-kit.zip`, `shirt.png`, `shorts.png`, `landing-page-code.md`, `pending task.md`, `work done/`) in a cleanup PR.
5. Seed guard: `seed.py` refuses to run unless `ENVIRONMENT=development`; delete the published demo credentials file `docs/development/DEMO_SEED_CREDENTIALS.md` from the repo.

Done when: `main` equals `test`, CI green with blocking ESLint, no demo credentials in the repo.

### WS2 — Production data, backups, secrets (Ops + You) — about 3 days
1. B-1: create `hrms_prod` from migrations only; run `provision_encryption_key.py` and `create_platform_admin.py`; point the app at it; confirm `admin@example.com` and `viewer@example.com` do not exist. Archive or drop `hrms_demo`.
2. B-3: confirm the alert email arrives (trigger a test failure) and the monitor timer's last run is recent. Store `PII_MASTER_KEY`, both JWT secrets and the age private key in **two** offline places. Run one full restore drill onto a blank machine (database **and** MinIO files) and write down the time it took.
3. H-4: add memory limits per container, tune Postgres (`shared_buffers`, `work_mem`), keep CompreFace off this VPS. Write down the recovery point (1 hour) and recovery time as accepted for beta.
4. H-10: tag images by git SHA, keep the previous tag, take a backup right before each migration, and write a one-page rollback.
5. R-1, R-2: encrypt or delete plaintext dumps in `backups/`; rotate or delete unused keys (Supabase file, unused Azure / Face++ keys).
6. Run the server verification list from audit section 10 and record each answer (TLS renewal, `/metrics` and `/docs` hidden, `ENVIRONMENT=production`, `TRUSTED_PROXY_HOSTS`, `EMAIL_PROVIDER` with SPF/DKIM, `hrms_app` lacks UPDATE/DELETE on append-only tables).

Done when: a written checklist with a result and date beside every line, and a restore drill time recorded.

### WS3 — Security hardening (Me) — about 3–4 days
1. H-1: raise per-IP ceilings for login and refresh (keep the per-email login limit at 10); or key refresh on the session. Add tests for an office of 100+ users behind one IP.
2. H-2: TOTP for platform admins, and restrict `/platform` by IP at nginx as the stopgap until TOTP ships.
3. H-3: `POST /auth/password/change` (current + new password, revoke other sessions) with web and mobile screens.
4. H-5: set `FACE_LIVENESS_ENGINE=minifasnet` in the production env template; document geofence as a deterrent, not proof.
5. H-6: add error tracking to API, web and mobile with PII scrubbing. **You** choose the service (Sentry cloud or self-hosted) and supply the DSN.
6. H-7: daily Celery task purging expired or revoked sessions, refresh tokens, reset and verification tokens, idempotency keys, sent `email_outbox` rows and old notifications; set `LOG_RETENTION_DAYS`.

Done when: each item has a test, and the audit's H-1..H-3, H-5..H-7 rows can be marked closed.

### WS4 — Mobile release (Me + You) — about 2–3 days
1. B-4: **You** create the release keystore and back it up outside the repo. **Me**: wire signing from a local properties file, fail the build or app start if a release build has a non-https base URL, set app name, description and version, and add a server-driven minimum-version check (API endpoint plus an app gate).
2. Decide the distribution path for the pilot: internal testing track, or APK sideload. iOS stays out of the pilot unless a Mac and Apple developer account are available.

Done when: a signed release APK installs on a real phone, points at the production host, and shows the force-update screen when the minimum version is raised.

### WS5 — Privacy and legal (You decide, Me drafts) — about 1 week elapsed
1. **You** decide, with a lawyer if possible: face and location retention periods, the data-processing agreement wording, and the grievance contact.
2. **Me**: privacy notice and terms pages linked from register, login and the onboarding wizard, plus a consent line on face enrolment. Set `face_*_retention_days` and turn `FACE_CLEANUP_DRY_RUN` off once you have chosen the periods.
3. A documented manual process for access and erasure requests (who, how fast, what is deleted) is enough for the pilot.

Done when: notices are live, retention is set, and each pilot company has a signed agreement.

### WS6 — Policy decisions (You) — this is the longest pole
**Attendance, Group A (17 items):** H-01, H-02, H-03, H-04, P-05, D-01a/b/R-2, P-04, H-05, H-06, H-07/H-08, H-29, H-30, O-19, L-06, L-09, plus the Group B items that touch pay or balances. The register lists them in the order to ask (its section 7).
**Policy decision map:** C-01..C-20 (payroll-blocking).
**Leave:** PD-01..PD-15 from the 16 Nov leave audit.

How to run it so it finishes:
- Hold three 45-minute sessions, about 6 decisions each, attendance first, then leave, then payroll.
- For each item I prepare a one-line recommendation and a worked example with real numbers, so you answer yes, no or change.
- Every answer is written into the decision register with a date. Any answer that changes the engine becomes a ticket, not an immediate change.

**Fallback if payroll decisions are not settled in time:** run the pilot on attendance and leave only, and hide payroll for the pilot companies. The older gaps doc says feature-flag gating is not implemented (verify), so hiding payroll needs a small change: a per-company flag plus menu and API guards. Budget about 1–2 days for that.

Done when: every Group A item has a dated answer, or payroll is hidden and the attendance and leave items are all answered.

### WS7 — End-to-end rehearsal (Me, You observe) — about 2 days after WS1–WS6
A scripted pass on a staging copy, on a clean database, written as a checklist with expected results:
register → verify email → set up company → onboard an employee (candidate link) → activate → web punch → mobile punch with geofence → mobile face punch → regularise → apply and approve leave → overtime → lock a period → (pay run, only if payroll is in scope).
Also: log in as each default role, confirm menus and 403s, trigger a deliberate error and see it in error tracking, restore a backup, test a rollback.
Add a Playwright smoke spec for register and punch so this is repeatable.

Done when: the checklist passes with no blocker, and every deviation is either fixed or written down as accepted.

## 2. Order and timeline (one person plus me)

| Week | Work |
|---|---|
| 1 | WS1 (merge, CI, junk, seed guard) · WS2 steps 1–3 (clean prod DB, alerts, escrow, limits) · WS3 items 1, 3, 4 · start WS6 session 1 (attendance) · start WS5 decisions |
| 2 | WS2 steps 4–6 and restore drill · WS3 items 2, 5, 6 · WS4 · WS5 pages · WS6 sessions 2–3 |
| 3 | Implement answers from WS6 as tickets · payroll flag if needed · WS7 rehearsal · fix what it finds |
| Gate | Pilot go/no-go review against the exit criteria below |

Realistic length: three weeks, with WS6 and WS5 setting the pace because they wait on you.

## 3. Dependencies

- WS7 needs WS1, WS2, WS4 and WS5 complete.
- Any engine change from WS6 reopens the attendance and payroll regression tests. Do not start it before the decision is dated.
- B-1 (clean production database) must precede inviting any real company.
- The migration PR needs your merge. Plan for it on day 1.
- Error tracking (WS3 item 5) needs your choice of service.

## 4. Risks

- **Decisions slip.** Mitigation: the three scheduled sessions, recommended defaults, and the attendance-and-leave-only fallback.
- **Engine changes after sign-off** break the rules you just approved. Mitigation: freeze the engine after WS6 except for tickets from the rehearsal.
- **Server drift.** The server was never inspected from this session. Mitigation: the WS2 step 6 checklist, run by you with me.
- **Real data lands before the privacy notices.** Mitigation: no real company is invited until WS5 is done.

## 5. Exit criteria (pilot go/no-go)

1. `main` equals `test`, CI green, ESLint blocking.
2. Production database clean, no demo users, secrets escrowed twice, restore drill timed.
3. Alerts delivered to a real inbox; error tracking receiving events from all three apps.
4. Signed release APK in use against the production host; force-update works.
5. Privacy notice, terms, agreement and retention periods in place.
6. All Group A decisions dated, or payroll hidden for pilot companies.
7. End-to-end checklist passed on a staging copy.
8. Rate limits tested for a 100-user office; platform console behind IP restriction or TOTP.

## 6. What I need from you to start

1. A yes to start WS1 and WS3 on `test` (I will not touch `main`; migrations and `.github/` changes wait for your merge).
2. Access or a session on the VPS for WS2, or run the commands yourself while I review the output.
3. Your pick of error-tracking service.
4. Dates for the three decision sessions.
5. Whether the pilot includes payroll, or attendance and leave only.
