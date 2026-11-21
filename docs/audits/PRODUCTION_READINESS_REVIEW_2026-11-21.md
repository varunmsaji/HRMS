# Is the HRMS app ready as a base (initial test) version? Review of 21 Nov 2026

Read-only. No code, data, server or configuration was changed. The only file written is this one.
Branch `test` = `origin/test`; `origin/main` is at `8079b7e` (PR #74).

## 1. Verdict

**Ready for a closed test with test data, after a short list of must-dos (section 5). Not ready for real employee data.**

"Initial test version" can mean two things, so the answer has two parts:

| Meaning | Verdict |
|---|---|
| **A. Internal or friendly test.** Your team and a few trusted testers use it with made-up employees, to find problems. | **Yes, after the 6 must-dos in section 5** (about 1 to 3 days, most of it server work, not code). |
| **B. A pilot with a real company's real people** (Aadhaar, PAN, bank details, face photos, punch locations, pay). | **No.** Six of the earlier audit's seven blockers are still open or unproven (only B-2 is fixed), and privacy and policy sign-off are owner decisions, not code. |

The product itself is far along and unusually well built for this stage. What stands between it and a real
pilot is almost all **operations, release and decisions**, not missing features.

## 2. How I did this, and what I could not check

- **Checked today by reading the code and git history:** every blocker and high item from the 11 Nov audit
  (`BETA_PRODUCTION_READINESS_AUDIT_2026-11-11.md`) and the 18 Nov plan
  (`PHASE_0_PILOT_READINESS_PLAN_2026-11-18.md`), plus the recent commits (119 since 11 Nov) and CI history.
- **Taken from earlier audits and not repeated (marked "earlier audit"):** the database facts (row-level
  security on 104 tables, least-privilege runtime role, append-only tables), the boot guards, authentication
  design, upload handling, the CSP, and the dependency scans. I did not re-run those checks.
- **My own test runs:** mobile `flutter analyze` clean and 1,496 tests passing on 19 to 20 Nov, on this
  machine. I did **not** run the API integration or security suites (they need a disposable database, about
  25 minutes), the web suite, or any end-to-end test.
- **CI:** the last CI run on `test` (20 Nov) succeeded.
- **Not possible from here:** the live server. I could not see which database the running app uses, whether
  demo users exist, whether alerts and backups are working, TLS, or the real environment variables. Anything
  about the VPS is marked **unknown**.
- **Nothing was run in a browser or on a phone.** No click-through of the finished app exists in any audit I
  found.

## 3. What is in good shape

(Earlier audit, 11 Nov, unless marked otherwise.)

- **Tenant isolation is enforced in the database** (row-level security forced on 104 tables, fails closed),
  and the app connects as a non-bypass role. This is the biggest risk for a multi-company product and it is
  handled.
- **Login security:** Argon2, lockout, 15-minute access tokens, rotating refresh tokens with replay
  detection; every request re-checks user, session and company status.
- **The process refuses to start in production** with weak or default secrets, an empty CORS list, or the
  logging-only email sender.
- **Personal data:** PAN, Aadhaar, bank numbers and face data are encrypted at rest; uploads are checked by
  content, stored privately and shared by short-lived links.
- **Quality gates:** CI runs lint, typecheck, import boundaries, API unit and integration tests against a real
  Postgres, secret scanning, dependency scanning, web build and tests, and mobile analyze and tests. It runs on
  every pull request, and the branch process (`test` to pull request to `main`, with a human merge for
  migrations and CI files) is being followed.
- **Backups exist:** hourly encrypted dumps to Google Drive, with one restore test reported as passed
  (12 Nov notes; not re-verified).
- **Recent work is sound and tested:** the attendance engine, the single day-counting rule (R-B01 to R-B03,
  merged 20 Nov), the salary-setup scope fix (B-2, merged), and the mobile screens built in the last days.
- **Money is stored as integer minor units**, all timestamps are timezone-aware, and 347 foreign keys and 184
  check constraints protect the data (earlier audit).

## 4. What is not ready, checked against the code today

Status key: **Open** = I confirmed in the code that it is still not done. **Unknown** = needs the server.

### 4.1 Blockers (from the 11 Nov audit)

| ID | Item | Status today | Evidence |
|---|---|---|---|
| B-1 | Start on a clean production database, no demo users | **Unknown, and the guard is still missing** | `apps/api/scripts/seed.py` has no environment check; `docs/development/DEMO_SEED_CREDENTIALS.md` is still in the repo. Earlier notes said the live app ran on a restored demo database. |
| B-2 | Salary setup ignored the caller's data scope | **Fixed** | Commit "fix(payroll): salary setup save stays inside the compensation scope", merged. |
| B-3 | Backups, alerts, key escrow | **Unknown** | Alerts and monitor timer were reported live 12 Nov. No record of the secrets (`PII_MASTER_KEY`, both JWT secrets, backup key) being stored in two offline places, and no timed full restore drill of database plus files. |
| B-4 | Mobile release build | **Open** | `android/app/build.gradle.kts` still signs release with the debug key; `API_BASE_URL` still defaults to `http://localhost:8000` with no check; `pubspec.yaml` still says "A new Flutter project." at version 0.1.0; no minimum-version check anywhere. |
| B-5 | Privacy notice, terms, data-rights path | **Open** | No privacy or terms page in `apps/web/src/app`; no mention in the web source. The product stores Aadhaar, PAN, bank, face and location data. |
| B-6 | Policy decisions | **Open** | 17 attendance decisions (Group A), C-01 to C-20 and the leave PD-01 to PD-15 are listed as awaiting the owner. |
| B-7 | One end-to-end pass on a clean copy | **Open** | No record of one. Playwright has two feature specs and is not in CI. |

### 4.2 High-priority items (from the 11 Nov audit)

| ID | Item | Status today | Evidence |
|---|---|---|---|
| H-1 | Per-IP login and refresh limits will lock out an office | **Open** | Login, refresh and password routes are still 10 per minute per IP (`identity/router.py` lines 36 to 57). Everyone in one office shares one public IP. This is the most likely thing to hurt a real test on day one. |
| H-2 | No multi-factor sign-in, including the platform console | **Open** | No TOTP route found. (One model file mentions the term; I did not look further.) |
| H-3 | No signed-in "change password" | **Open** | No such route. Users can only use forgot-password. |
| H-4 | One VPS, no container memory limits, stock Postgres | **Open** | No limits in `docker-compose.vps.yml`. Recovery point is about one hour (dumps only). |
| H-5 | Face liveness off by default | **Open** | `face_liveness_engine` defaults to `disabled`. A photo of a photo could punch if a company uses face punch. |
| H-6 | No error tracking in any app | **Open** | No Sentry, Crashlytics or similar in the API, web or mobile dependencies. |
| H-7 | Nothing is ever purged | **Open** | The only scheduled cleanup is face records. Sessions, refresh tokens, idempotency keys, outbox and notifications grow forever. |
| H-8 | ESLint is non-blocking with about 120 errors | **Open** | `ci.yml` step is still `continue-on-error: true`. |
| H-9 | Web image on end-of-life Node 20 | **Open** | `apps/web/Dockerfile` and CI both use Node 20. |
| H-10 | In-place deploys, `latest` images, no rollback | **Open** (partly) | The compose file takes `IMAGE_TAG` but defaults to `latest`; no rollback procedure was found. |

### 4.3 Other items worth knowing (earlier audit, not re-checked unless noted)

- No role-level database timeouts (`statement_timeout` and others) were found in any migration or init script
  (checked today). A stuck request can hold locks.
- Four lookup indexes the earlier audit asked for (`employee.user_id`, `user_company.user_id` and others) were
  not found in the migrations by my search; treat as **probably still open** (weak check).
- No `limit_req` in the nginx config (checked today); no global per-user API limit.
- The tenant variable is transaction-local, and seven service files commit mid-request (D-4). A tenant query
  after such a commit could silently return nothing. Earlier audit; not re-checked.
- The mobile refresh token sits in a plain file in the app sandbox (M-2); no certificate pinning; no code
  shrinking on the Android release build.
- Plaintext database dumps and real API keys sit on the laptop drive (`backups/`, `apps/api/.env`). Git-ignored,
  so not in the repo, but a risk if the laptop is lost.
- Tracked files that do not belong in the repo: `mavericks-kit.zip`, `shirt.png`, `shorts.png`,
  `landing-page-code.md`, `pending task.md`, `work done/` (still present in the folder today).

## 5. Must-dos for an internal test version (meaning A)

These are the smallest set that makes a closed test safe and useful. None of them is a feature.

1. **Put the test on a clean database, with no demo users, and confirm it.** Create it from migrations only,
   add a platform admin, check that the seed admin and viewer logins do not exist, and retire any restored demo
   database. If the repo is shared with anyone, delete the published demo credentials file and add the seed
   environment guard. (Needs the server; about half a day.)
2. **Raise the per-IP login and refresh limits** (keep the per-email login limit). Without this, testers in one
   office will be locked out at the morning login. This is the one code change I would insist on.
3. **Build the mobile app against the real https address** (`--dart-define=API_BASE_URL=https://...`) and
   install it by sideload. Debug signing is acceptable for your own devices; do not give it to outsiders, and do
   not call it a release.
4. **Decide what to show testers about payroll.** The 16 Nov audit's verdict is "not payroll-ready"; a company
   feature-flag table exists but I did not confirm that menus and API routes obey it. For a first test, either
   tell testers payroll is out of scope or hide it.
5. **Write down the known limits for testers:** attendance and leave rules still await 17 attendance and 15
   leave decisions, so results that affect pay may change; only one time zone (`Asia/Kolkata`) and one legal
   entity per company are supported.
6. **Run one scripted pass yourself before inviting anyone, on a clean database:** register, verify email,
   create a company, onboard an employee, punch on web and on mobile (with geofence), regularise, apply and
   approve leave, overtime, lock a period. Nothing so far has been tried on a phone or in a browser, including
   all the mobile work from 19 to 20 Nov. Use the checklist in `MOBILE_HANDOFF_2026-11-20.md`.

Also strongly advised, but not blocking a closed test with made-up data: confirm the backup timer and alert email
work, and start the 'two offline copies' habit for the secrets so a lost server does not mean unreadable data.

## 6. What must be true before real employee data (meaning B)

All of section 4.1 and 4.2, in this order of effort:

1. **Owner and legal (the long pole):** privacy notice and terms linked from register, login and onboarding; a
   data-processing agreement per company; face and location retention periods set and cleanup turned out of
   dry-run; the attendance, leave and payroll policy decisions signed and dated, or payroll hidden.
2. **Operations:** clean production database; secrets escrowed twice; one timed restore drill of database and
   files; alerts proved by a real test email; container limits and Postgres tuning; images tagged by git commit
   with a written rollback; server checks (TLS renewal, `/metrics` and `/docs` hidden, `ENVIRONMENT=production`,
   `TRUSTED_PROXY_HOSTS`, email delivering with SPF and DKIM, the runtime role unable to update append-only
   tables).
3. **Release:** a real Android keystore (kept outside the repo and backed up), a build that refuses a non-https
   address, proper app name and version, and a server-driven minimum-version check, because an installed build
   cannot be recalled.
4. **Security and support:** change-password, multi-factor sign-in (or an IP restriction) for the platform
   console, liveness on for any company using face punch, error tracking in all three apps, a purge job, role
   timeouts and the missing indexes.
5. **Proof:** the scripted end-to-end pass on a staging copy, with a repeatable smoke spec in CI.

The 18 Nov plan already lays out this work in workstreams WS1 to WS7 with an estimated three weeks, paced by the
owner decisions. I agree with it; nothing I found today changes its order. The attendance display work done since
(20 Nov, R-B01 to R-B03) improves correctness but does not touch any item above.

## 7. Confidence

- **High:** every "Open" row in section 4 (each was confirmed in the code today) and the list of must-dos.
- **Medium:** the "good shape" list (taken from the 11 Nov audit and not re-run; the code has had 119 commits
  since, though none touched the areas listed in a way I saw).
- **Low or unknown:** everything about the live server, and whether the app works end to end in a browser or on a
  phone. A passing CI means the code and its tests agree, not that a person can complete the flows.
