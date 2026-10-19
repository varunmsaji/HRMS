# Face attendance — base release runbook

Written for: the release owner and on-call engineer deploying and operating the first, limited
release of face attendance.

Date: 2026-10-18. Companion documents: `docs/audits/FACE_ATTENDANCE_SECURITY_HARDENING_REPORT.md`
(Part E: what changed and what was verified), `docs/operations/FACE_ATTENDANCE_STAGING_SECURITY_CHECKLIST.md`
(what must still be run), `docs/operations/FACE_LIVENESS_DOCKER_DEPLOYMENT.md` (image and model assets).

**Nothing in this runbook has been executed against staging or production.** It is the procedure to
follow; the checks marked *staging* are still open.

---

## 1. What this release is — and is not

**Release mode: A — face verification is OPTIONAL.**

- An employee with an approved face profile *can* punch with their face. They can equally punch with
  the ordinary endpoint (`POST /attendance/punches/me`), which is unchanged. Nothing server-side
  makes a face punch mandatory for any company, and no per-company policy for it exists in the
  data model (`attendance_policy` has no such field). **This release does not change any company's
  policy.**
- Face punches are stored with `source = FACE`; ordinary punches have a different source. That is
  how reports and monitoring can tell them apart.
- Therefore: **face attendance in this release is supplementary evidence. It does not prevent
  buddy punching.** Product copy, training material and the UI must not say that all punches are
  face-verified or that proxy punching is prevented.
- **Mode B (mandatory face attendance) is NOT implemented** and is a product decision (§10). It
  would need a per-company setting enforced server-side on every punch path (self, on-behalf,
  bulk/import, regularisation) with a documented recovery procedure for employees who cannot use
  the camera. Do not promise it.
- Not fraud-proof: passive single-frame liveness, thresholds not calibrated on real devices or real
  attacks, no device attestation, no virtual-camera/injected-frame detection.

## 2. Prerequisites (all required before production)

| # | Prerequisite | Status |
| --- | --- | --- |
| 1 | Release owner's written approval to ship **optional** face verification with the limitations in §1 | open |
| 2 | Verified, restorable database backup taken immediately before migrating (§4) | open |
| 3 | Migrations applied and exercised on **staging** first (§4, §7) | open |
| 4 | Staging checklist rows run with the real Face++ test account (checklist §9–§14) | open |
| 5 | Face++ account limits confirmed with the vendor (§9) | open |
| 6 | Legal/privacy/HR decisions in §10 recorded (or the release explicitly scoped to exclude them) | open |
| 7 | Alert delivery tested end to end (§8) | open |

## 3. Required configuration

All in `apps/api/.env.example`; production values are set in the environment, never committed.

| Setting | Required value / note |
| --- | --- |
| `FACE_VERIFICATION_PROVIDER` | `facepp` plus `FACEPP_API_KEY` / `FACEPP_API_SECRET` (the API refuses to boot without both) |
| `FACE_LIVENESS_ENGINE` | `minifasnet` + `FACE_LIVENESS_MODEL_DIR=/app/models/liveness/minifasnet-v1`. With `disabled` (the default) face punching and enrollment are unavailable — that is the safe off switch |
| `FACE_ENROLLMENT_PROVIDER_BUDGET_SECONDS` / `FACE_ENROLLMENT_LEASE_SECONDS` | defaults 120 / 240. Lease **must exceed** budget (boot validation) |
| `FACE_PROVIDER_MAX_CONCURRENCY`, `FACE_PROVIDER_TIMEOUT_SECONDS`, `FACE_PROVIDER_CONNECT_TIMEOUT_SECONDS` | defaults 4 / 15 / 5. These are *our* bounds, not Face++ quotas. Set concurrency from the vendor's confirmed limit (§9) |
| `FACE_*_REQUESTS_PER_MINUTE_PER_IP` | defaults 600 / 60 / 120. Flood ceilings per (tenant, IP), deliberately generous |
| `TRUSTED_PROXY_HOSTS` | **Must list the reverse proxy** or every request appears to come from the proxy's address and shares one bucket. Left empty, forwarded headers are ignored (safe, but then the per-IP limit is per proxy) |
| `FACE_*_RETENTION_DAYS`, `FACE_CLEANUP_DRY_RUN` | leave **unset / true**. No retention period is decided (§10). Do not turn destructive cleanup on |
| Celery Beat + worker | `attendance-run-face-deletions` (every 2 minutes) must be running — see §5 |

Model assets: four SHA-256-pinned files in `models/liveness/minifasnet-v1/`. The image build runs
`scripts/liveness/verify_assets.py` and fails on any mismatch; the API verifies them again at boot
and refuses to start with a bad asset. Confirm with
`docker run --rm <image> python scripts/liveness/verify_assets.py models/liveness/minifasnet-v1`.

## 4. Migrations

Two revisions are new since the last release train; apply in order, on staging first:

| Revision | Effect | Reversible? |
| --- | --- | --- |
| `20261015090000` | `face_liveness_session` table, new attempt decisions | yes |
| `20261017090000` | `face_enrollment_attempt` table, new decisions, indexes, **rewrites historical `face_verification_attempt.provider_response`** | **schema yes; data NO** |
| `20261018090000` | window reservation columns, `face_external_deletion` outbox | yes (drops the outbox rows) |

### `20261017090000` — irreversible redaction

It replaces the raw Face++ search body stored under `provider_response -> 'verify'` (face tokens,
rectangles, thresholds) with `{"identity": {"legacy_redacted": true, "request_id": …}}`. The
original bodies are **discarded by the UPDATE**. The downgrade restores the *schema* (constraints,
tables, indexes) but cannot restore the bodies. Therefore:

1. **Take and verify a backup first** (restore it somewhere and check row counts). It is the only
   way back to the old bodies.
2. Treat this revision as **forward-only for recovery**: if the release must be backed out, the
   code can be rolled back and the *schema left in place* (older code ignores the extra table and
   the wider CHECK constraint); do not run `alembic downgrade` expecting the data to return.
3. Confirm with the privacy owner that erasing those bodies is acceptable (it is a data
   minimisation, but it is irreversible).

*Demonstrated (final gate, 2026-10-18):* on a fresh database a row holding a raw Face++ search body (face token, results, thresholds) was migrated
through `20261017090000` using the built image, then downgraded: the body was replaced by the minimal `{"identity": {"legacy_redacted": true, …}}` form
on upgrade and was **not** restored by the downgrade. See the hardening report, Part F7.

### `20261018090000` — reversible, with one caveat

Downgrading drops `face_external_deletion`. Any rows still `PENDING` in it are Face++ FaceSets /
photos that were meant to be deleted and then never will be by this system. Before downgrading,
export them (`SELECT kind, resource_ref, reason FROM face_external_deletion WHERE status='PENDING'`)
and delete those resources by hand or let the worker finish first (§5).

### Procedure

1. Backup + restore test. 2. `alembic current` recorded. 3. Apply on **staging**. 4. `alembic
current` shows `20261018090000`. 5. Run the post-migration checks below. 6. Only then plan the
production window. The migrations run as the schema owner (`MIGRATIONS_DATABASE_URL`), never as
the application role. **No migration was run against any shared or production database while
preparing this release.**

Post-migration checks: tables `face_liveness_session`, `face_enrollment_attempt`,
`face_external_deletion` exist with row-level security enabled and forced; the application role can
read/write them; `SELECT count(*) FROM face_external_deletion` works under a tenant context;
`/health` is green.

## 5. Deleting external resources (how it works, how to recover)

**Rule: nothing outside PostgreSQL is deleted before the transaction that authorises it has
committed.** PostgreSQL and Face++ cannot commit together; this system does not claim they can.

- *Approve* → the review photo is queued for deletion. *Reject* → the Face++ FaceSet **and** the
  photo are queued. *Revoke* → the FaceSet is queued. The queue row (`face_external_deletion`) is
  written in the **same transaction** as the status change. If that transaction fails, neither the
  status nor the queue row exists and nothing external has been touched.
- A revoked or rejected profile stops being usable **at commit** (its status is no longer
  `ENROLLED`); the provider-side deletion happens afterwards, normally within ~2 minutes.
- The worker `attendance.run_face_deletions` (Beat, every 2 minutes) claims due rows, deletes them
  outside any transaction, and marks them `DONE`. A failure records a short error code and backs
  off 2, 4, 8 … up to 60 minutes. Deletion is idempotent (Face++ "already gone" counts as success;
  so does a missing object).
- **Reassignment safety:** FaceSet tokens and photo keys are unique and never reused, and the
  worker re-checks at deletion time that no `PENDING_APPROVAL`/`ENROLLED` profile still points at
  the resource; if one does, the row is `SKIPPED` (and logged) instead of deleted. A later
  reject/revoke of that profile re-arms the row.
- **Crash orphans:** during enrollment, as soon as a FaceSet is created a *guard* row is queued,
  due only after the reservation lease has lapsed. If the process dies before the profile is
  written, the worker deletes the orphan; if the profile was written, the guard is `SKIPPED`.
- Failed compensation inside a request (e.g. Face++ is down when an enrollment is aborted) queues
  the deletion instead of only logging it.

### Operator procedures

- **Is anything stuck?** `SELECT kind, reason, attempts, last_error_code, next_attempt_at FROM
  face_external_deletion WHERE status='PENDING' ORDER BY created_at;` (set `app.company_id` for
  the tenant, or run as the owner). The monitor raises `face_deletion_stuck` when a row has passed
  `FACE_DELETION_ALERT_AFTER_ATTEMPTS` attempts (log event `face_deletion_failed`, level `error`).
- **Run the worker now:** `python -m hrms.modules.attendance.face_deletion [--company-id <uuid>]`.
- `last_error_code = PROVIDER_NOT_CONFIGURED` → the provider is disabled/misconfigured; rows wait
  (they are not lost). Fix configuration and they proceed.
- `PROVIDER_ERROR` for a long time → check Face++ status, credentials and the account's limits.
- **Manual deletion** of a FaceSet (vendor console/API) is safe; mark the row done afterwards or
  let the worker find it already gone.
- **A profile shows `ENROLLED` but punches fail with `FACE_PROVIDER_FAILED`:** its FaceSet may be
  missing at the provider. Revoke and re-enroll (HR opens a new window).
- Beat down → rows accumulate but nothing breaks; the existing `health-scheduler-heartbeat` /
  `job_health` alert covers Beat. Deletions resume when it is back.

## 6. Enrollment reservation (no DB locks across provider calls)

A self-enrollment submission commits a short *reservation* (lease) on the HR-opened window, then
does liveness and the ~18 sequential Face++ calls under one wall-clock budget with **no
transaction open**, then finalises in a second short transaction that re-locks the window and proves
the reservation is still its own.

- A second submission during the first returns **409 `FACE_ENROLLMENT_IN_PROGRESS`** (the app
  shows the server message; retry shortly).
- HR cancelling or reopening the window during the work makes the finalisation fail with
  `FACE_ENROLLMENT_NOT_OPEN` and the just-created FaceSet and photo are discarded.
- A crashed worker's reservation lapses after `FACE_ENROLLMENT_LEASE_SECONDS`; no manual step.
- If the budget is exceeded the submission fails with `FACE_PROVIDER_FAILED`, is recorded as
  `PROVIDER_ERROR` (not counted against the employee) and everything created is removed.
- The same release also stops the punch path holding a pooled connection and the idempotency-key
  advisory lock during liveness/provider calls. A duplicate request (same key and challenge) that
  arrives while the original is still at the provider waits — holding no connection — for the
  original's result and returns it (up to ~105 s by default); if the original was rejected, the
  duplicate fails as before (challenge already used).

## 7. Verification and rollout

1. **Staging build** from the reviewed tree; migrations (§4); `FACE_*` config (§3).
2. **API/mobile compatibility.** The API's request contracts are unchanged. New outcomes the
   mobile app has not been tuned for (it shows the server's message): `409 FACE_ENROLLMENT_IN_PROGRESS`
   and `429 RATE_LIMITED` on the face endpoints. Deploy API before or together with the mobile
   build that sends `liveness_session_id` + `frames` (older builds sending a single `photo` are
   refused by design). **The Flutter test suite was not run as part of this change set.**
3. **Functional verification on staging** (real Face++ test account, test employees only): enroll →
   approve → face punch IN/OUT; reject; revoke; confirm the FaceSet disappears at Face++ within a
   few minutes of reject/revoke and the photo disappears from storage after approve/reject.
4. **Failure drills:** make Face++ unreachable → punches return `FACE_PROVIDER_FAILED`, employees
   are *not* locked out, and recover when it returns; stop the worker → deletions queue and then
   drain.
5. **Health checks:** `/health`; Beat heartbeat; `SELECT count(*) FROM face_external_deletion WHERE
   status='PENDING' AND next_attempt_at < now() - interval '15 minutes'` is 0.
6. **Controlled rollout:** one company, a handful of enrolled employees, face engine on; watch the
   monitor for a full week of shifts before widening. Keep ordinary punching available throughout
   (mode A).
7. **Release-owner approval** is recorded before each widening step.

### Rollback versus forward recovery

- *Switch off:* `FACE_LIVENESS_ENGINE=disabled` (or `FACE_VERIFICATION_PROVIDER=disabled`) and
  restart the API: face enrollment/punch return "unavailable"; ordinary punching continues; data is
  kept. This is the first response to any face-specific incident.
- *Code rollback:* safe to the previous image; leave the schema as is (§4). Older code ignores the
  outbox, so queued deletions simply wait until the new code returns — export the pending rows
  first if the rollback will be long.
- *Data:* the redacted `provider_response` bodies cannot come back except from the backup.

## 8. Monitoring and alert delivery

`infra/monitoring/hrms_monitor.sh` watches, among others: `face_rejections`, `face_spoof_signals`
(spoof/replay/identity-inconsistent/ambiguous), `storage_and_orphan_failures`, and the new
`face_deletion_stuck`. Provider and liveness-engine outages appear as `PROVIDER_ERROR` /
`LIVENESS_ERROR` attempts and as `face_provider_request_failed` logs; they are **deliberately not**
part of the spoof signal and never lock employees out. **Alert delivery (email/webhook) has not
been exercised**; do so on staging by forcing each condition once.

## 9. Face++ limits that must be confirmed with the vendor (not assumed here)

A punch makes **one detect + one search per submitted frame** (default 3 frames ⇒ 6 requests); an
enrollment makes about 18 requests. The following are unknown for this account and must be obtained
in writing before sizing or load-testing:

- request rate (QPS) and concurrent-request limit per API key, and how excess is signalled;
- maximum number of FaceSets per API key (this design uses one FaceSet per enrolled employee);
- image size/dimension limits against the 1 MB frame cap and 5 MB enrollment cap;
- data residency of `api-us.faceplusplus.com`, retention at the provider, deletion guarantees;
- pricing at expected volume.

`FACE_PROVIDER_MAX_CONCURRENCY` is our own client-side bound and is not derived from any of these.
A load test (shift-start burst) against the real account has **not** been run.

## 10. Decisions still pending (not made in this change set)

- Optional vs **mandatory** face attendance per company (product) — and, if mandatory, the fallback
  for employees who cannot use the camera.
- Retention periods for liveness sessions, attempt details and enrollment attempts (legal/privacy).
- Deletion of an employee's face data (provider FaceSet and profile) when they leave.
- Consent wording and **notice versioning** (today only `consent_recorded_at` is stored).
- Cross-border processing of biometric data by the provider; DPA with the vendor.
- Liveness thresholds, APCER/BPCER targets, device/attack matrix (needs real data).
- Acceptance of the liveness model's undisclosed training data.

## 11. Known limitations (carried into the release)

- Passive liveness only; uncalibrated thresholds; no device attestation; no virtual-camera or
  injected-frame detection; a byte-different re-encoding of an old frame defeats the replay check.
- The ordinary punch endpoint bypasses face verification (mode A).
- The employee-level lockout counts only genuine negative outcomes; per-IP limits are flood
  ceilings, not identity controls.
- Provider-side deletion after reject/revoke is eventually consistent (minutes), not synchronous.
- Review-photo access is audited (`FACE_REVIEW_PHOTO_VIEWED`); no other biometric image is stored
  or served.

## 12. Pre-staging gate evidence and operator commands (2026-10-18)

Evidence that the **final working tree** passes local verification is in the hardening report, Part F (backend unit 1,165 and integration+security 1,759
passed under CI-equivalent database initialisation; RLS suite 4 passed; Flutter analyze clean and 503 tests passed; image built and checked). That is
*local engineering verification only*. It is not staging evidence and not production approval, and it does not show that face verification prevents
buddy-punching (it is optional; ordinary punching is unchanged).

Commands for the **authorised staging operator** (none was run against staging):

```sh
# Build (CI/staging pipeline normally does this)
docker build -t <registry>/hrms-api:<tag> apps/api
# Model assets and checksums inside the image (expect 4 x OK + "engine loaded")
docker run --rm --entrypoint python <image> scripts/liveness/verify_assets.py models/liveness/minifasnet-v1
# No env/secret files shipped (expect no output)
docker run --rm --entrypoint sh <image> -c 'find / -xdev \( -name ".env" -o -name ".env.*" \) -not -path "*/site-packages/*" 2>/dev/null'
# Migrations, only after a verified backup (runbook section 4), as the schema owner
docker run --rm --env-file <staging-migration.env> --entrypoint alembic <image> upgrade head
# Face job registration (expect the four attendance.*face* tasks)
docker run --rm --env-file <staging.env> --entrypoint python <image> -c "import entrypoints.worker; from hrms.core.celery_app import celery_app as c; print(sorted(t for t in c.tasks if 'face' in t))"
```

CI-equivalent local database initialisation (what the gate used): start `postgres:16-alpine` with `POSTGRES_USER=hrms POSTGRES_DB=hrms_dev`, apply
`infra/docker/postgres/init/*.sql` then `*.sh` (with `HRMS_APP_PASSWORD` set) **before** `alembic upgrade head`, so `hrms_app` receives default privileges.
A database made with a bare `CREATE DATABASE` lacks those grants and makes the runtime-role tests fail for a permissions reason.

Known items to fix upstream (not blockers for staging): four E501 errors in two committed migrations make `ruff check .` exit 1; the RLS runtime-role test
hard-codes `localhost:5433/hrms_dev`.

