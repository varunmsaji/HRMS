# Face attendance — staging security checklist

For a **separately authorised** staging run. Nothing below has been executed. Rows marked **(new, 2026-10-17)**
were added by the integrity-hardening pass (`docs/audits/FACE_ATTENDANCE_SECURITY_HARDENING_REPORT.md`
Part B); all earlier rows are unchanged. A unit or integration
test that resembles a scenario does **not** make it `PASS`; only a recorded staging run does.

Statuses: `NOT RUN`, `PASS`, `FAIL`, `BLOCKED`, `NOT APPLICABLE`. Fill in tester, date, build and
evidence reference per row. Never attach face images or video to tickets; record scores and decisions only.

## 0. Prerequisites (all must hold before any row is run)

| # | Prerequisite | Status |
| --- | --- | --- |
| P1 | Staging is isolated: its own database, Redis, object storage, email sink; no production credentials | NOT RUN |
| P2 | Migrations `20261015090000`, **`20261017090000` and `20261018090000`** applied by the environment owner (staging only); `alembic current` recorded. `20261017090000` irreversibly erases stored Face++ search bodies — confirm that is acceptable first. `20261018090000` (enrollment reservation + deletion outbox, 2026-10-18) is reversible — see the base-release runbook §4 | NOT RUN |
| P3 | Image built from the reviewed tree with the model assets (4 hashes verified: `docker run … verify_assets.py`) | NOT RUN |
| P4 | `FACE_LIVENESS_ENGINE=minifasnet`, `FACE_LIVENESS_MODEL_DIR=/app/models/liveness/minifasnet-v1`; API boots | NOT RUN |
| P5 | Face++ **test** credentials, quota agreed, named test employees only | NOT RUN |
| P6 | Written consent from every participant; retention of capture sets agreed (delete after evaluation) | BLOCKED (needs HR/legal) |
| P7 | Two enrolment reviewers exist (an enrollee cannot approve themselves, since this phase) | NOT RUN |
| P8 | Mobile build matching the API release installed on the device matrix | NOT RUN |
| P9 **(new)** | Face++ plan allows the call volume of 3 verifications per punch (≈6 requests) and 5 enrollment liveness checks; QPS/concurrency limit known | NOT RUN |
| P11 **(new)** | Before applying `20261017090000` anywhere that matters: database backup taken (the migration irreversibly erases stored Face++ bodies; the downgrade cannot restore them) | NOT RUN |
| P10 **(new)** | Retention periods decided by HR/legal/privacy (report §B5). Until then leave `FACE_*_RETENTION_DAYS` unset | BLOCKED (needs approval) |

Device matrix (record model, OS, camera): ≥2 Android (low + mid tier), ≥1 iOS.

## 1. Genuine captures (BPCER)

10 attempts per participant per device per condition. Measure with
`scripts/liveness/evaluate_captures.py` on exported frames, and via the app for end-to-end rates.

| ID | Scenario | Status | Result (n / accepted / inconclusive / rejected) |
| --- | --- | --- | --- |
| G1 | Bright indoor | NOT RUN | |
| G2 | Dim indoor | NOT RUN | |
| G3 | Backlit window | NOT RUN | |
| G4 | Outdoor daylight | NOT RUN | |
| G5 | Glasses / no glasses | NOT RUN | |
| G6 | Cap or head covering | NOT RUN | |
| G7 | Appearance change (beard) | NOT RUN | |
| G8 | Low-end camera, low light | NOT RUN | |
| G9 **(new)** | Enrollment of genuine users: per-angle (front/left/right/up/down) server liveness pass rate per device. Turned/tilted heads are outside what the model was shown in the upstream samples; a high false-reject rate here means the angle liveness threshold or policy needs a decision before rollout (5 rejected submissions lock an enrollment window) | NOT RUN | |
| G10 **(new)** | Genuine punches with a second person or poster visible behind the employee: record how often Face++ `detect` reports >1 face (we reject as `AMBIGUOUS_FACE`) | NOT RUN | |

## 2. Presentation attacks (APCER) — own test employees only

| ID | Scenario | Status | Result (n / accepted as live) |
| --- | --- | --- | --- |
| A1 | Printed photo, matte, A4 | NOT RUN | |
| A2 | Printed photo, glossy / wallet size / curved / cut-out | NOT RUN | |
| A3 | Photo shown on another phone | NOT RUN | |
| A4 | Photo shown on a laptop / monitor | NOT RUN | |
| A5 | Prerecorded video on a phone | NOT RUN | |
| A6 | Prerecorded video on a monitor | NOT RUN | |
| A7 | Another enrolled colleague's real face (identity mismatch) | NOT RUN | |
| A8 **(new)** | Frame 1 is the employee, frames 2–3 are a colleague (swap during the 3-frame capture, e.g. two people trading places) | NOT RUN | |
| A9 **(new)** | Enrollment with a printed/on-screen photo as only a *turned* angle (left/right/up/down), real front | NOT RUN | |

Acceptance (APCER/BPCER targets) is a product/security/HR decision, not set here. If no threshold
meets both, do not enable.

## 3. Protocol and tampering (authorised test environment only)

| ID | Scenario | Expected | Status |
| --- | --- | --- | --- |
| T1 | Replay a captured request with its old challenge | 409 `FACE_LIVENESS_CHALLENGE_USED` | NOT RUN |
| T2 | Replay the same frames with a fresh challenge | 422 `FACE_CAPTURE_REPLAYED` | NOT RUN |
| T3 | Use an expired challenge | 409 `FACE_LIVENESS_CHALLENGE_EXPIRED` | NOT RUN |
| T4 | Challenge from another employee / tenant / direction | 422 `FACE_LIVENESS_CHALLENGE_INVALID` | NOT RUN |
| T5 | Send `is_live=true` / `liveness_score` in the request | ignored, outcome unchanged | NOT RUN |
| T6 | Send pre-captured **real** frames of the employee with a fresh challenge (injected / virtual camera) | **Known not detectable by the protocol**; record the model's decision. Expect possible acceptance | NOT RUN |
| T7 | Enrollee approves or rejects own enrolment | 403 `FACE_ENROLLMENT_SELF_APPROVAL_NOT_ALLOWED` | NOT RUN |
| T8 | Re-enrol while ENROLLED / PENDING | 409, no overwrite | NOT RUN |
| T9 | Repeated failures from one employee | 429 `FACE_ATTEMPTS_EXCEEDED` after the configured limit | NOT RUN |
| T10 **(new)** | Real colleague's face in frame 2 or 3 | 422 `FACE_NOT_MATCHED`, attempt row `IDENTITY_INCONSISTENT`, no punch, challenge stays burned | NOT RUN |
| T11 **(new)** | Two faces in a frame | 422 `FACE_MULTIPLE_FACES` (liveness or `AMBIGUOUS_FACE`), no punch | NOT RUN |
| T12 **(new)** | 5 rejected enrollment submissions in one window, then a 6th | 6th: 429 `FACE_ENROLLMENT_ATTEMPTS_EXCEEDED`, no Face++ call; HR opens a new window → submission works | NOT RUN |
| T13 **(new)** | Enrollment rejected by liveness/angle: inspect `face_enrollment_attempt` | one row per rejection: decision + angle only, no image/score | NOT RUN |
| T14 **(new)** | Face++ down during enrollment ×7 | 502 each time, rows `PROVIDER_ERROR`, employee **not** locked out afterwards | NOT RUN |

## 4. Concurrency, retries, failures

| ID | Scenario | Expected | Status |
| --- | --- | --- | --- |
| C1 | Same idempotency key sent concurrently ×5 | exactly one punch | NOT RUN |
| C2 | Retry after client timeout (same key, new challenge) | original result, no second punch | NOT RUN |
| C3 | Same key, other direction | 409 `DUPLICATE_PUNCH_IDEMPOTENCY_KEY` | NOT RUN |
| C4 | Same challenge submitted twice concurrently | one punch | NOT RUN |
| C5 | Kill the network after upload, before the response | retry resolves to the one punch | NOT RUN |
| C6 | Face++ timeout / 5xx | 502, no punch, key reusable | NOT RUN |
| C7 | Remove / corrupt a model file, restart API | API refuses to boot (explicit error) | NOT RUN |
| C8 | `FACE_LIVENESS_ENGINE=disabled` | face punch 503, other punch types work | NOT RUN |
| C9 | Database unavailable mid-punch | no punch, no half state | NOT RUN |
| C12 **(new)** | Face++ times out on the 2nd or 3rd frame's verification | 502, no punch, same key reusable, attempt row `PROVIDER_ERROR` — which does **not** count towards the employee lockout (2026-10-18) | NOT RUN |
| C13 **(new)** | Punch end-to-end latency with 3 verifications: p50/p95 on the device matrix over real mobile networks; no `CONCURRENCY_LIMIT_EXCEEDED` from Face++ at peak shift-start load | NOT RUN |
| C10 | App backgrounded / camera permission revoked during capture | nothing sent | NOT RUN |
| C11 | Outage fallback: HR regularisation for a legitimate employee | `REGULARIZATION` punch, not `FACE`, audit row, self-approval blocked | NOT RUN |

## 5. Privacy and observability

| ID | Check | Status |
| --- | --- | --- |
| L1 | Grep API, worker and proxy logs for the test window: no image bytes, tokens, Face++ keys | NOT RUN |
| L2 | `security.face_punch.rejected` and `security.face_enrollment.rejected` appear for each rejection with a fixed `reason` and no scores | NOT RUN |
| L3 | A spike of rejections is visible to the existing monitoring; alert delivery tested end to end | BLOCKED (needs a real `HRMS_ALERT_COMMAND` destination — see runbook §1.1) |
| L3a **(new)** | With the real destination set, inject >10 rejections (or >3 `SPOOF_SUSPECTED`) in 5 min on staging: `face_rejections` / `face_spoof_signals` fail in `hrms_monitor.sh` output and `{"alert_delivery":"sent"}` is logged and **received by a named person** | BLOCKED (needs destination) |
| L4 | Dropped-log counters visible | NOT RUN |
| L5 | `face_liveness_session` rows hold digests only; attempt rows hold scores, no images | NOT RUN |
| L7 **(new)** | `face_verification_attempt.provider_response` of new punches contains only `liveness` and `identity` (index/decision/similarity/request_id); `SELECT count(*) … WHERE provider_response::text ~ 'face_token|face_rectangle'` = 0, including pre-existing rows after the migration | NOT RUN |
| L8 **(new)** | Face++ error responses are logged as `error_code` only (no echoed tokens/keys) — provoke one (invalid faceset) and grep the API log for the key, secret and any `fs_`/`ft_` value | NOT RUN |
| L6 | Review photo deleted after approve/reject; no temp files left on test phones | NOT RUN |

## 6. Cleanup and rollback

- Delete test employees' Face++ persons (`DELETE /attendance/face-profiles/{id}`) and any exported captures.
- Staging liveness-session, attempt and enrollment-attempt rows: use the retention tool in report/runbook §B5 — first `python -m hrms.modules.attendance.face_cleanup` (report only), then `--apply` only on staging with agreed test periods. Record the counts.
- Rollback: `FACE_LIVENESS_ENGINE=disabled` + API restart; schema rollback `alembic downgrade 20261015090000` (this pass) then, if required, `20261014091000`. The downgrade of `20261017090000` drops `face_enrollment_attempt` and re-maps the two new decisions to `NO_MATCH`; it **cannot restore** the Face++ search bodies erased by the upgrade.
- Sign-off needs recorded numbers from sections 1–2 and a decision on T6.

## 7. Retention and cleanup **(new, 2026-10-17)**

| ID | Check | Status |
| --- | --- | --- |
| R1 | Defaults: no `FACE_*_RETENTION_DAYS` set; Beat `attendance.run_face_cleanup` returns 0 and deletes nothing | NOT RUN |
| R2 | With test periods set and `FACE_CLEANUP_DRY_RUN=true`, the report lists what would change; row counts unchanged | NOT RUN |
| R3 | `--apply` on staging: old sessions/enrollment attempts gone, attempt rows kept with `provider_response`/`provider_person_id` NULL; punches, attendance days, profiles unchanged (counts before/after) | NOT RUN |
| R4 | Second `--apply` is a no-op; `face_cleanup_finished` shows zeros | NOT RUN |
| R5 | A company in `FACE_CLEANUP_HOLD_COMPANY_IDS` is skipped (`face_cleanup_skipped_hold`) | NOT RUN |
| R6 | An in-flight punch (challenge issued, not yet consumed) is not disturbed by a concurrent `--apply` | NOT RUN |
| R7 | A retry of an old idempotent punch key after the scrub still returns the original punch | NOT RUN |

## 7a. Local engineering verification (not staging evidence) **(2026-10-17)**

Done on disposable local resources with mocks; **none of this changes any row above to PASS.**
Full backend suite 2852 passed; migration round trip verified on disposable DBs; Flutter face tests 39 passed;
monitor checks exercised against a fake docker harness. Details: report Part C. `hrms_dev` leftover test tenants
(83) are a read-only finding awaiting the owner's decision (report C4) — not a staging item.

## 8. Acceptance criteria for leaving staging

All of the following must be true and recorded; none is currently met.

1. P1–P10 satisfied (P6 and P10 need approvals).
2. Sections 1–2 measured with consented participants on the device matrix, with APCER/BPCER targets
   **set by the product/security/HR owners beforehand**, and thresholds chosen from the data.
   Enrollment angle liveness (G9) has a pass rate the owners accept.
3. T1–T14 and C1–C13 behave as expected; T6 (injected real frames) has an explicit accept/mitigate decision.
4. L1–L8 pass, and L3/L3a prove a named person receives an alert.
5. R1–R7 pass on staging; retention periods and the hold process are approved and written down.
6. Punch p95 latency and Face++ quota/QPS are acceptable (C13, P9).
7. Open decisions recorded as decided: device attestation, active challenge, termination clean-up of
   face data (report §B7), legal acceptance of the liveness model's training data.
8. A rollback rehearsal (`FACE_LIVENESS_ENGINE=disabled`, schema downgrade on a staging copy) was done.

Meeting these makes the feature eligible for a pilot. It does not make it fraud-proof.

---

# Staging readiness register (added 2026-10-17)

Sections 9–18 add the owner / prerequisites / procedure / expected / actual / evidence / sign-off record for each staging
activity. Sections 0–8 above are the original quick-reference rows and keep their IDs (G*, A*, T*, C*, L*, R*, P*); the new
rows below cross-reference them. Plan and protocol: `docs/operations/FACE_ATTENDANCE_STAGING_READINESS_PLAN.md`.

**Status rule.** `PASS` = executed, evidence attached at the recorded location. `FAIL` = executed, acceptance criterion not met.
`BLOCKED` = a prerequisite is missing (named in *Prerequisites*). `NOT RUN` = not attempted. **As of 2026-10-17 no row below has been
executed.** "Actual" is `—` until a run is recorded; never fill it from a unit test.

**Roles** (each needs a named person): STG staging owner · DBA · SEC security owner · PRD product owner · HR · DPO · LEGAL · QA test lead · MOB mobile dev · API backend dev.
**Evidence location:** `<evidence-store>/<run-id>/<row-id>/` — the store is chosen by SEC (`NOT ASSIGNED`). Outcome rows, command output (secrets masked),
screenshots of dashboards/logs. **Never store face images, video, frames, embeddings, face tokens or provider bodies there.**
**Standing prerequisite `ENVB`** = a staging environment that satisfies ENV-1…ENV-3 (none exists today).

## 9. Environment and deployment preflight

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ENV-1 | Staging is isolated from production and from `hrms_dev` | STG | host / compose project `hrms-staging`; own Postgres, Redis, MinIO | list containers and networks; show DB, Redis and MinIO hosts in each service env (secrets masked) | no hostname, volume or credential shared with production or dev | — | `…/ENV-1/` | STG + SEC | BLOCKED (no staging environment) |
| ENV-2 | Secrets inventory complete and distinct | STG, SEC | plan §B2 | compare each variable's presence/fingerprint against production's; confirm new `JWT_*`, `PII_MASTER_KEY`, DB passwords | every row of §B2 satisfied; none equals production | — | `…/ENV-2/` | STG + SEC | BLOCKED |
| ENV-3 | Image built from the reviewed tree contains verified model assets | STG, API | assets committed (currently untracked → clean build fails at `COPY models`) | build image; run `verify_assets.py models/liveness/minifasnet-v1` in it | build passes; 4 lines `OK` with the §B3 hashes; `engine loaded` | — | `…/ENV-3/` | STG + SEC | BLOCKED (assets untracked; no build target) |
| ENV-4 | Corrupted/missing asset stops boot (existing C7) | STG | ENV-3 | alter a copy of one asset in a throwaway container; start API with engine enabled | API refuses to boot with an explicit error; no face punch served | — | `…/ENV-4/` | STG | BLOCKED |
| ENV-5 | Queue and Redis isolation proven | STG | ENV-1 | `printenv` of api/worker/beat (masked); `celery inspect ping` shows only staging nodes; one beat | broker/Redis host is the staging Redis; no production queue reachable | — | `…/ENV-5/` | STG + SEC | BLOCKED |
| ENV-6 | Email cannot reach real people | STG | ENV-1 | `EMAIL_PROVIDER=logging`; trigger an invite | log line `email.logged_not_sent`; no SMTP/API call | — | `…/ENV-6/` | STG | BLOCKED |
| ENV-7 | Face++ test account and quota agreed | STG, SEC, PRD | Face++ sandbox account | record account type, key owner, QPS/concurrency and monthly quota; confirm key is not production's | written limits; credentials in the secret store only | — | `…/ENV-7/` | SEC + PRD | BLOCKED (no account on record) |
| ENV-8 | Health and safe-failure behaviour | STG | ENV-1…ENV-3 | `/health/live`, `/health/ready`, `job_health`; set `FACE_LIVENESS_ENGINE=disabled`, attempt a face punch and a web punch | health OK; face punch 503 `FACE_LIVENESS_UNAVAILABLE`; web punch succeeds | — | `…/ENV-8/` | STG | BLOCKED |
| ENV-9 | Level-1 rollback rehearsal (feature off, schema kept) | STG | ENV-8 | disable engine, restart API, re-enable | exact behaviour of plan §B8 level 1; no data change | — | `…/ENV-9/` | STG + SEC | BLOCKED |

## 10. Migration and backup verification

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MB-1 | Postgres and MinIO backups taken **and restored** | DBA, STG | ENV-1 | `pg_backup.sh`; `pg_restore.sh` into a new DB name; compare row counts; MinIO backup + restore check | restore succeeds; counts match; ids/sizes recorded | — | `…/MB-1/` | DBA | BLOCKED |
| MB-2 | Preflight queries | DBA | MB-1 | run PRE-1 and PRE-2 (plan §B5) | revision recorded; `bodies_to_erase` recorded | — | `…/MB-2/` | DBA | BLOCKED |
| MB-3 | Erasure acknowledged | DBA, DPO | MB-2 | DBA/DPO sign that `20261017090000` irreversibly erases stored Face++ bodies and that the MB-1 backup is the only recovery | signed acknowledgement referencing MB-1 ids | — | `…/MB-3/` | DBA + DPO | NOT RUN |
| MB-4 | Migration applied to **staging only** | DBA | MB-1…MB-3 | `migrate` service for `hrms-staging` | `alembic current` = `20261017090000`; no errors | — | `…/MB-4/` | DBA | BLOCKED |
| MB-5 | Post-migration checks | DBA | MB-4 | POST-1…POST-4 (plan §B5) | `20261017090000`; table/RLS forced/`tenant_isolation`/app role can insert = t; 0 token matches; new decisions allowed = t | — | `…/MB-5/` | DBA + SEC | BLOCKED |
| MB-6 | Cross-tenant isolation of the new table as the runtime role | SEC, API | MB-4 | as `hrms_app`, set tenant A and read `face_enrollment_attempt` rows of tenant B; try an insert for B | zero rows visible; insert refused by RLS | — | `…/MB-6/` | SEC | BLOCKED |
| MB-7 | Downgrade/up rehearsal on a **restored copy** (not live staging) | DBA | MB-1 | restore backup to a new DB; `alembic downgrade 20261015090000`; verify; `upgrade head` | matches plan §B8 level 3: table dropped, two decisions mapped to `NO_MATCH`, bodies not restored | — | `…/MB-7/` | DBA | BLOCKED |

## 11. Real-device and attack testing

All attacks use **test accounts and consenting people only**. Record every attempt as an outcome row (plan §C6). Device matrix: ≥2 Android
(low + mid), ≥1 iOS. These rows execute the original G*/A*/T* scenarios; results are filed here and the original rows updated to match.

| ID | Scenario (original IDs) | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RD-1 | Genuine users, normal light (G1, G8) | QA | ENVB; MB-4; consent (PV-1); participants assigned calibration/holdout (CH-1) | each participant, each device: 10 fresh-challenge punches IN/OUT | rates reported per plan §C5; accepted punches are `FACE`, server time | — | `…/RD-1/` | QA + SEC | BLOCKED |
| RD-2 | Genuine, challenging light: dim, backlit, outdoor (G2–G4) | QA | as RD-1 | as RD-1 per condition | rates per condition reported; inconclusive share reported | — | `…/RD-2/` | QA + SEC | BLOCKED |
| RD-3 | Genuine, appearance variation: glasses, head covering, beard (G5–G7) | QA | as RD-1 | as RD-1 per variation | rates reported per variation | — | `…/RD-3/` | QA + SEC | BLOCKED |
| RD-4 | Printed photo: matte, glossy, curved, cut-out (A1, A2) | QA, SEC | as RD-1; prints from participant's own consented image | ≥ agreed presentations per type × device; allow retries (worst case scored) | each presentation recorded; no `FACE` punch for a presentation unless it is counted as an accepted attack | — | `…/RD-4/` | SEC | BLOCKED |
| RD-5 | Photo shown on another phone / laptop (A3, A4) | QA, SEC | as RD-4 | as RD-4 | as RD-4 | — | `…/RD-5/` | SEC | BLOCKED |
| RD-6 | Replayed video on phone / monitor (A5, A6) | QA, SEC | as RD-4 | as RD-4 | as RD-4 | — | `…/RD-6/` | SEC | BLOCKED |
| RD-7 | Background faces, two faces in frame (G10, T11) | QA | as RD-1 | second person / poster behind the user; two people in frame | rejected `FACE_MULTIPLE_FACES` (`AMBIGUOUS_FACE` or liveness `MULTIPLE_FACES`); rate of **genuine** punches wrongly rejected by a background face reported | — | `…/RD-7/` | QA + PRD | BLOCKED |
| RD-8 | Different identity across frames (A7, A8, T10) | SEC, API | two enrolled **test** employees; an authorised test client (a person cannot swap within ~400 ms) | submit frames 1 from employee X and 2–3 from Y with X's challenge (staging, test accounts only) | 422 `FACE_NOT_MATCHED`; attempt `IDENTITY_INCONSISTENT`; no punch; challenge burned | — | `…/RD-8/` | SEC | BLOCKED |
| RD-9 | Poor frames, partial face, camera failure (C10) | QA, MOB | as RD-1 | cover half the face; very dark; revoke camera permission mid-capture; background the app | rejection with a clear message or nothing sent; no punch; no stuck state | — | `…/RD-9/` | QA + MOB | BLOCKED |
| RD-10 | Challenge abuse: expired, replayed, duplicate, cross-user (T1–T5, C1–C4) | SEC, API | ENVB | replay a captured request; fresh challenge + old frames; expired; other user's challenge; concurrent duplicates | per T/C rows (409/422 codes); exactly one punch for concurrent duplicates | — | `…/RD-10/` | SEC | BLOCKED |
| RD-11 | Enrollment with varied angles incl. genuine up/down/left/right (G9, A9) | QA | ENVB; HR opens window; second reviewer exists | enroll participants on each device; then a spoofed *turned* angle with a real front | genuine pass rate per angle/device reported; spoofed turned angle rejected with the angle recorded in `face_enrollment_attempt` | — | `…/RD-11/` | SEC + HR | BLOCKED |
| RD-12 | Enrollment limits and lock-out (T12–T14) | QA, API | RD-11 | 5 rejected submissions; 6th; HR reopens; provider outage ×7 | 6th = 429 `FACE_ENROLLMENT_ATTEMPTS_EXCEEDED` with no Face++ call; reopen resets; outage rows `PROVIDER_ERROR` and no lock-out | — | `…/RD-12/` | QA + HR | BLOCKED |
| RD-13 | Injected / virtual-camera frames (T6) | SEC | authorised test client | submit real pre-captured frames of a test employee with a fresh challenge | **recorded only** — acceptance is possible and known; SEC records an accept/mitigate decision | — | `…/RD-13/` | SEC + PRD | BLOCKED |

## 12. Threshold calibration and holdout evaluation

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CH-1 | Participant assignment to calibration/holdout **before** collection | QA, SEC | consented participant list | assign by participant, stratified by device; record the mapping (pseudonyms) | disjoint sets; mapping recorded and dated | — | `…/CH-1/` | SEC | NOT RUN |
| CH-2 | Targets pre-registered | SEC, PRD | plan §C7 worksheet | fill and sign the targets **before** any result is seen | signed worksheet dated before CH-3 | — | `…/CH-2/` | SEC + PRD | NOT RUN |
| CH-3 | Calibration run and threshold choice | QA, SEC | RD-1…RD-6, RD-11 on calibration participants | `summarise_trials.py trials.csv --report calibration`; `evaluate_captures.py` for engine-only curves | measurements reported; thresholds chosen from calibration only; no target met ⇒ do not enable | — | `…/CH-3/` | SEC | BLOCKED |
| CH-4 | Configuration frozen | STG, SEC | CH-3 | record git revision, image tag, env values, thresholds | one frozen-config label | — | `…/CH-4/` | STG + SEC | BLOCKED |
| CH-5 | Holdout run (once) | QA | CH-4; new/held-out participants | `summarise_trials.py trials.csv --report holdout --frozen-config "<label>"` | holdout reported unchanged; no tuning afterwards | — | `…/CH-5/` | SEC | BLOCKED |
| CH-6 | Result vs targets | SEC, PRD | CH-2, CH-5 | compare holdout to the pre-registered targets | PASS only if every target is met with the stated confidence bound; otherwise FAIL | — | `…/CH-6/` | SEC + PRD | BLOCKED |

## 13. Latency and Face++ quota / cost

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LQ-1 | Punch completion latency on real devices/networks (C13) | QA, MOB | ENVB; devices on Wi-Fi and mobile data | client-side timing, ≥ agreed attempts per device/network; median and p95 | reported per metric table §C5; compared with the PRD target | — | `…/LQ-1/` | PRD | BLOCKED |
| LQ-2 | Face++ requests per punch | STG, API | ENV-7 | count provider requests for N accepted and N rejected punches (logs + provider dashboard) | ≈ 6 per accepted punch (3 detect + 3 search); fewer on early rejection; matches dashboard | — | `…/LQ-2/` | PRD | BLOCKED |
| LQ-3 | Peak-load and concurrency limit | STG, PRD | ENV-7; agreed test window | burst of N simultaneous test punches (shift-start profile) within quota | no `CONCURRENCY_LIMIT_EXCEEDED` at expected peak, or the limit is quantified | — | `…/LQ-3/` | PRD | BLOCKED |
| LQ-4 | Provider timeout / 5xx (C6, C12) | STG, API | ENV-1 | block egress to the Face++ host from the staging api container, attempt punches, restore egress | 502 `FACE_PROVIDER_FAILED`; no punch; same idempotency key succeeds after restore; **note** `PROVIDER_ERROR` attempts count toward the 5-per-10-minute punch limit (existing behaviour), so a long outage can lock employees out briefly — record what users experience | — | `…/LQ-4/` | PRD + SEC | BLOCKED |
| LQ-5 | Provider rate limit / quota exhaustion | STG | ENV-7 | exceed the test quota in a controlled test | provider error handled as in LQ-4; logged as `error_code` only; cost/quota alarm path identified | — | `…/LQ-5/` | PRD | BLOCKED |

## 14. Alert delivery and incident response

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AL-1 | Destination, owner and recipients defined | SEC, STG | decision | record destination type, script, secret location, primary/secondary recipients, severity expectations (plan §D) | written, named, approved | — | `…/AL-1/` | SEC | BLOCKED (no destination exists) |
| AL-2 | Monitor installed for staging and healthy baseline | STG | ENVB; AL-1 | cron entry with `HRMS_COMPOSE_PROJECT=hrms-staging`; run once on a healthy stack | exit 0; `ok: true`; stderr delivery line `not_configured` or `sent` as configured | — | `…/AL-2/` | STG | BLOCKED |
| AL-3 | Rejection spike is detected | QA, STG | AL-2 | cause >10 rejections, and separately >3 `SPOOF_SUSPECTED`, within the window using test accounts | `face_rejections` / `face_spoof_signals` listed in `failing`; exit 1 | — | `…/AL-3/` | SEC | BLOCKED |
| AL-4 | Alert is **delivered and acknowledged** by a named recipient | SEC, STG | AL-1, AL-3 | re-run AL-3 with `HRMS_ALERT_COMMAND` set | `{"alert_delivery":"sent"}` **and** the recipient confirms receipt with a timestamp (screenshot) | — | `…/AL-4/` | SEC | BLOCKED |
| AL-5 | Negative delivery tests | STG | AL-4 | revoke the destination credential; unset the command | `failed`; `not_configured`; both visible in the cron log | — | `…/AL-5/` | STG | BLOCKED |
| AL-6 | Investigation drill | SEC, HR | AL-3 | give an on-call person a synthetic spike; they follow `ALERTS_AND_RUNBOOKS.md` §3.9 to identify employee/reason and decide escalate/ignore, without touching images | correct finding recorded; time taken recorded; no biometric data copied out | — | `…/AL-6/` | SEC | BLOCKED |
| AL-7 | Log hygiene | SEC | ENVB; RD rows run | grep API/worker/proxy logs for the window for image bytes, base64 blobs, `face_token`, `fs_`/`ft_` values, Face++ key/secret, frame digests | no matches (L1, L8) | — | `…/AL-7/` | SEC | BLOCKED |
| AL-8 | Biometric-exposure incident tabletop | SEC, DPO, LEGAL | plan §E (E11) | walk the exposure scenarios through the written procedure | owners, contacts, provider-deletion step and notification decision points confirmed | — | `…/AL-8/` | SEC + DPO | NOT RUN |

## 15. Retention and termination lifecycle approval

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LC-1 | Retention periods decided (E1–E3) | DPO, HR, LEGAL | evidence in plan §E | written decision per record type | signed periods, or an explicit "keep indefinitely" with reason | — | `…/LC-1/` | DPO + LEGAL | BLOCKED (approval) |
| LC-2 | Defaults are non-destructive on staging (R1–R4) | STG, DBA | ENVB; MB-4 | see section 7 | unset ⇒ no change; dry-run reports only | — | `…/LC-2/` | STG | BLOCKED |
| LC-3 | Legal-hold process (E4) | LEGAL, DPO | decision | define who sets/releases a hold; test `FACE_CLEANUP_HOLD_COMPANY_IDS` (R5); decide whether per-employee holds are needed | process written; hold respected; gap for per-employee hold recorded | — | `…/LC-3/` | LEGAL | BLOCKED (approval) |
| LC-4 | Termination policy decided (E8) | HR, DPO | decision | choose automatic revoke, scheduled reconciliation, or documented manual step; if code is needed, raise a change for the employee module | signed policy | — | `…/LC-4/` | HR + DPO | BLOCKED (approval) |
| LC-5 | Manual termination drill | HR, STG | ENVB; an enrolled test employee | HR calls `DELETE /attendance/face-profiles/{employee_id}`; confirm in the Face++ account that the FaceSet no longer exists; confirm `status = REVOKED`, audit row, and that a punch is refused | provider FaceSet gone; profile REVOKED; audit `FACE_PROFILE_REVOKED`; face punch refused | — | `…/LC-5/` | HR + DPO | BLOCKED |
| LC-6 | Backup/restore reconciliation (E10) | DBA, DPO | MB-1 | write and rehearse the post-restore step that re-applies revocations/cleanup and removes orphan FaceSets | procedure written; rehearsal output recorded | — | `…/LC-6/` | DBA + DPO | NOT RUN |
| LC-7 | Access to biometric data reviewed (E5) | SEC, DPO | role list | list who holds `ATTENDANCE.FACE_ENROLLMENT_MANAGE`, who has Face++ console and MinIO access; confirm audit entries for approve/reject/revoke | access list approved; audit rows present | — | `…/LC-7/` | SEC + DPO | BLOCKED |

## 16. Privacy and model-provenance approval

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PV-1 | Evaluation consent form and notice wording (E6) | LEGAL, DPO, HR | draft | review and approve; collect signed forms | approved text; signed form per participant (pseudonymised index) | — | `…/PV-1/` | LEGAL + DPO | BLOCKED (approval) |
| PV-2 | Model training-data and licence acceptance (E7) | LEGAL, SEC | upstream licence text; the undisclosed training data statement | written acceptance or rejection | signed decision; if rejected the feature stays disabled | — | `…/PV-2/` | LEGAL | BLOCKED (approval) |
| PV-3 | Face++ terms, region and provider retention (E13) | LEGAL, DPO | provider contract/DPA | review where images are processed and how long Face++ keeps submitted images | written conclusion | — | `…/PV-3/` | LEGAL + DPO | BLOCKED |
| PV-4 | Privacy impact assessment where required | DPO | PV-1, PV-3 | DPO decides if one is required in the jurisdiction and completes it | assessment, or a recorded "not required" with reason | — | `…/PV-4/` | DPO | NOT RUN |
| PV-5 | Evaluation data handling and deletion | SEC, DPO | CH-1 | capture store has named access list and a fixed deletion date; deletion performed and verified at the end | access log; deletion record | — | `…/PV-5/` | DPO | BLOCKED |
| PV-6 | Incident-response plan approved (E11) | SEC, DPO, LEGAL | AL-8 | approve the written plan | signed plan | — | `…/PV-6/` | SEC + DPO | NOT RUN |

## 17. Employee recovery and support procedures

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SP-1 | Legitimate employee repeatedly rejected → fallback punch | HR, QA | ENVB | HR records a punch by regularisation for a test employee | `source = REGULARIZATION` (never `FACE`), audit row, self-approval refused | — | `…/SP-1/` | HR | BLOCKED |
| SP-2 | Re-enrollment | HR, QA | ENVB; two reviewers | revoke → open window → employee submits → a *different* reviewer approves | new profile ENROLLED; Face++ FaceSet replaced; the old one is deleted by the post-commit worker within minutes (not synchronously) | — | `…/SP-2/` | HR | BLOCKED |
| SP-3 | Enrollment lock-out recovery | HR | RD-12 | after `FACE_ENROLLMENT_ATTEMPTS_EXCEEDED`, HR opens a new window | count resets; employee can submit | — | `…/SP-3/` | HR | BLOCKED |
| SP-4 | Punch lock-out (`FACE_ATTEMPTS_EXCEEDED`) | HR, QA | ENVB | trigger 5 failures; observe message; wait for window or use SP-1 | message tells the employee to wait or ask HR; no punch forced | — | `…/SP-4/` | HR | BLOCKED |
| SP-5 | Second reviewer exists in every tenant that uses face attendance | HR | tenant list | confirm at least two people hold the enrollment-manage permission per tenant | enrollees can never be the only reviewer | — | `…/SP-5/` | HR + SEC | NOT RUN |
| SP-6 | Helpdesk script for error codes | HR, API | final codes | publish a table: `FACE_NOT_MATCHED`, `FACE_MULTIPLE_FACES`, `FACE_LIVENESS_INCONCLUSIVE`, `FACE_SPOOF_SUSPECTED`, `FACE_ATTEMPTS_EXCEEDED`, `FACE_ENROLLMENT_ATTEMPTS_EXCEEDED`, `FACE_PROVIDER_FAILED`, `FACE_LIVENESS_UNAVAILABLE`, `FACE_ENROLLMENT_IN_PROGRESS` (409, wait and retry), `RATE_LIMITED` (429 on the face endpoints) → what to tell the employee and when to escalate | helpdesk can resolve without seeing biometric data | — | `…/SP-6/` | HR | NOT RUN |

## 18. Final staging sign-off

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FS-1 | Every row in sections 0–17 is `PASS`, or has a signed risk acceptance | QA | all above | tabulate statuses | no `NOT RUN`/`BLOCKED`/`FAIL` without a signed acceptance | — | `…/FS-1/` | SEC + PRD | BLOCKED |
| FS-2 | Targets were pre-registered and met on holdout | SEC, PRD | CH-2, CH-6 | confirm dates and results | CH-2 dated before CH-3; CH-6 PASS | — | `…/FS-2/` | SEC + PRD | BLOCKED |
| FS-3 | Residual-risk register accepted | SEC, PRD, DPO | report Parts B–D | review: injected frames, passive liveness, uncalibrated model, termination gap, alert gap | each risk accepted, mitigated or blocking, in writing | — | `…/FS-3/` | SEC + PRD + DPO | NOT RUN |
| FS-4 | Pilot go / no-go decision record | PRD, SEC | FS-1…FS-3 | decision meeting | recorded decision with date and attendees; "go" means a limited pilot, **not** production readiness or fraud-proof behaviour | — | `…/FS-4/` | PRD + SEC | BLOCKED |

---

# Base-release rows (added 2026-10-18)

Added by the base-release critical-fix pass (`docs/audits/FACE_ATTENDANCE_SECURITY_HARDENING_REPORT.md` Part E;
procedure: `docs/operations/FACE_ATTENDANCE_BASE_RELEASE_RUNBOOK.md`). Each behaviour below is covered by automated
tests against **fake** Face++/engine/storage; **none of these rows has been run against real Face++, real devices,
staging or production**, and a passing unit/integration test does not make a row `PASS`.

**Release mode: A — face verification is optional.** Ordinary punching is unchanged. Mandatory face attendance (mode B)
is a product decision and is not implemented.

## 19. Base-release verification

| ID | Scenario | Owner | Prerequisites | Procedure | Expected | Actual | Evidence | Sign-off | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BR-1 | Face++ outage does not lock employees out | QA, API | ENVB, P5 | block egress to Face++ (staging firewall); 7+ face punches by one test employee; restore | each attempt `502 FACE_PROVIDER_FAILED`; attempts stored as `PROVIDER_ERROR`; **no** `FACE_ATTEMPTS_EXCEEDED`; next punch after restore succeeds | — | `…/BR-1/` | SEC | NOT RUN |
| BR-2 | Genuine mismatches still lock out | QA | ENVB | 5 punches with a different test person's face | 5×422 then `429 FACE_ATTEMPTS_EXCEEDED`; expires after the window | — | `…/BR-2/` | SEC | NOT RUN |
| BR-3 | Enrollment holds no DB lock/connection during provider calls | API, DBA | ENVB | while an enrollment runs with realistic Face++ latency, watch `pg_stat_activity` / `pg_locks` for `idle in transaction` and row locks on `face_enrollment_window` | none held; pool in-use count unaffected | — | `…/BR-3/` | DBA | NOT RUN |
| BR-4 | Enrollment end-to-end time against real Face++ | QA | P5 | time ≥20 enrollments; compare with `FACE_ENROLLMENT_PROVIDER_BUDGET_SECONDS` (120) and the lease (240) | p95 well inside the budget; no `PROVIDER_ERROR` caused by the budget | — | `…/BR-4/` | API | NOT RUN |
| BR-5 | Concurrent submission / cancel / reopen during enrollment | QA | ENVB | double-tap submit; HR cancels mid-submission; HR reopens mid-submission | second submit `409 FACE_ENROLLMENT_IN_PROGRESS`; cancelled/reopened ones end `FACE_ENROLLMENT_NOT_OPEN` and the FaceSet they created is deleted at Face++ | — | `…/BR-5/` | QA | NOT RUN |
| BR-6 | Reject / revoke / approve delete externally only after commit, and eventually do | QA, STG | ENVB, P5, Celery Beat running | reject a pending profile; revoke an enrolled one; approve another; check Face++ console and object store over ~5 minutes | FaceSets/photos gone within minutes; profile unusable immediately; outbox rows `DONE` | — | `…/BR-6/` | SEC | NOT RUN |
| BR-7 | Deletion retry and stuck alert | STG | BR-6 | make Face++ delete fail (egress block) for >5 worker passes, then restore | rows back off and stay `PENDING`; `face_deletion_stuck` alert fires after the attempt threshold; rows drain after restore | — | `…/BR-7/` | SEC | NOT RUN |
| BR-8 | Worker never deletes an in-use FaceSet | QA | BR-6 | queue a deletion row for an `ENROLLED` profile's person (staging SQL) and run the worker | row `SKIPPED`, FaceSet intact, punch still works | — | `…/BR-8/` | SEC | NOT RUN |
| BR-9 | Review-photo access is audited | SEC | ENVB | HR opens a pending enrollment's photo; refused/failed reads | one `FACE_REVIEW_PHOTO_VIEWED` audit row per served read (actor, profile, request id, no image content); none for refused reads | — | `…/BR-9/` | SEC | NOT RUN |
| BR-10 | Flood limits and proxy handling | API, STG | ENVB, `TRUSTED_PROXY_HOSTS` set | burst face requests from one address through the real proxy; send a forged `X-Forwarded-For` from outside the proxy | 429 `RATE_LIMITED` beyond the ceiling; forged header does not change the bucket; one tenant's burst does not affect another; a shift-start burst from a shared office NAT does **not** trip the default ceilings | — | `…/BR-10/` | SEC | NOT RUN |
| BR-11 | Shift-start load and DB pool behaviour | QA, DBA | P5, vendor limits | replay a realistic burst (N concurrent punches) against staging with real Face++ | no `db_pool_exhausted`, no vendor concurrency errors at the chosen `FACE_PROVIDER_MAX_CONCURRENCY`, acceptable p95 | — | `…/BR-11/` | API | BLOCKED (vendor limits unknown) |
| BR-12 | Migration `20261018090000` on a staging copy of production data | DBA | backup (P11) | upgrade, check RLS and app-role access, downgrade, upgrade | clean; `hrms_app` can read/write `face_external_deletion`; downgrade/upgrade repeatable | — | `…/BR-12/` | DBA | NOT RUN |
| BR-13 | Mode A wording | PRD | — | review UI strings, onboarding/training copy and the HR guide | nothing claims every punch is face-verified or that buddy punching is prevented | — | `…/BR-13/` | PRD | NOT RUN |
| BR-14 | Rollback switch | STG | ENVB | set `FACE_LIVENESS_ENGINE=disabled`, restart staging API | face enroll/punch unavailable, ordinary punch works, data intact, queued deletions keep draining | — | `…/BR-14/` | STG | NOT RUN |
| BR-15 | Celery worker and Beat availability for face jobs | STG | ENVB | on staging: `celery -A entrypoints.worker inspect registered` lists `attendance.run_face_deletions`, `attendance.process_face_deletions_company` (and `attendance.run_face_cleanup`); Beat log shows `attendance-run-face-deletions` firing every 2 minutes; stop Beat for 10 minutes, restart, confirm queued rows drain | tasks registered; schedule fires; backlog drains without manual action | — | `…/BR-15/` | STG | NOT RUN |
| BR-16 | Image and engine start-up drills on the staging image | STG, SEC | ENVB; image built by the staging pipeline | (a) `docker run --rm <image> python scripts/liveness/verify_assets.py models/liveness/minifasnet-v1` ⇒ 4×OK; (b) start the API with the engine enabled ⇒ boots, models loaded; (c) copy the model dir, alter one byte, point `FACE_LIVENESS_MODEL_DIR` at it ⇒ API refuses to boot; (d) delete one asset ⇒ refuses; (e) `FACE_LIVENESS_ENGINE=disabled` ⇒ boots, face endpoints unavailable, ordinary punch works; (f) no `.env`/secret file in the image filesystem | all as described | — | `…/BR-16/` | SEC | NOT RUN |
| BR-17 | Retention-cleanup batch bound on production-like data | DBA | ENVB; retention decision (RD) — until then dry-run only | with `FACE_CLEANUP_DRY_RUN=true`, run `python -m hrms.modules.attendance.face_cleanup` on a copy of production data after a bulk delete/vacuum; confirm reported counts respect `FACE_CLEANUP_BATCH_SIZE × FACE_CLEANUP_MAX_BATCHES` and `truncated` is reported | counts never exceed the bound; no destructive run until retention is approved | — | `…/BR-17/` | DBA | BLOCKED (retention undecided) |
| BR-18 | Reverse-proxy client-address handling end to end | STG, SEC | ENVB; `TRUSTED_PROXY_HOSTS` set to the proxy | from two real client networks through the proxy, then directly to the API port with a forged `X-Forwarded-For` | per-IP buckets follow the real client behind the proxy; the forged header is ignored on a direct connection | — | `…/BR-18/` | SEC | NOT RUN |

