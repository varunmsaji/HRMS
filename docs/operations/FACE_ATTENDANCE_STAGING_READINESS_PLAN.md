# Face attendance — staging readiness and evaluation plan

Prepared 2026-10-17. **Nothing in this document has been executed against a staging environment.**
It is a plan, a protocol and a set of approval worksheets. Companions:
`docs/audits/FACE_ATTENDANCE_SECURITY_HARDENING_REPORT.md` (findings, Part D = this pass) and
`docs/operations/FACE_ATTENDANCE_STAGING_SECURITY_CHECKLIST.md` (the scenario register where results are recorded).

**Verdict: staging execution is `BLOCKED`** — the repository defines no staging environment (no staging
compose project, no `.env.staging.example`, no hosts or credentials), there is no Face++ test account on
record, and no alert destination exists. Everything that can be prepared without those is prepared here.
This is not production readiness and not a claim of fraud-proof behaviour.

Roles used below are *roles*, not people; each must be assigned a named person before the run
(`NOT ASSIGNED` today): **STG** staging owner/DevOps · **DBA** database owner · **SEC** security owner ·
**PRD** product owner · **HR** HR owner · **DPO** privacy/data-protection owner · **LEGAL** · **QA** test lead ·
**MOB** mobile developer · **API** backend developer.

---

## A. Handover matrix

"Verified this session" means I read the artefact or ran the command in this pass. Test counts from
earlier passes are *reported*, not re-run.

| Item | Status | Basis |
| --- | --- | --- |
| Settings defaults: no retention period, `face_cleanup_dry_run=True`, hold list empty, enrollment limit 5, punch limit 5/10 min, engine and provider `disabled`, similarity 0.90, angle 0.80, live 0.90 / spoof 0.50, 3 frames, 120 s challenge | **Verified locally** | resolved from `Settings` this session |
| Cleanup is non-destructive when unset and report-only by default; holds, bounds, idempotence, punches untouched | **Verified locally** | 36 DB-backed tests (`test_face_cleanup.py`, `test_face_integrity_hardening.py`) re-run on disposable DB `hrms_final_verify2` (Redis 14, Celery 15): 36 passed; 5 scheduling/CLI unit tests passed |
| Monitor checks fire/stay quiet as designed | **Verified locally** | `tests/unit/ops/test_host_monitor.py` re-run this session: 39 passed |
| Evaluation summariser (new this pass) | **Verified locally** | `test_evaluation_summary.py` 16 passed; `test_face_cleanup_scheduling.py` 5 passed |
| Migration preflight/post-check SQL in §B5 | **Verified locally** | run read-only against disposable `hrms_final_verify2` |
| ruff format, ruff check, mypy | **Verified locally** | format clean (591 files); ruff 4 pre-existing E501 (`20261007090000` ×2, `20261008090000` ×2), none new; mypy 196 files clean |
| Model asset hashes (4) match `_PINNED_SHA256` and the deployment doc | **Verified by reading** | §B3 |
| `apps/api/models/` is entirely untracked in git (`git ls-files` = 0 files) → a clean-checkout image build fails at `COPY models` | **Verified by reading** | Dockerfile lines 27–32 |
| No staging environment definition / template exists; `apps/api/env/` holds only a README | **Verified by reading** | `ls apps/api/env` |
| `HRMS_ALERT_COMMAND` is set nowhere in the repository | **Verified by reading** | grep |
| Full backend suite 2,852 passed (disposable `hrms_final_verify2`) | Reported, **not re-run** | engineering handover; no code under test changed this pass except new tooling |
| Flutter face tests 39 passed, `flutter analyze` clean | Reported, **not re-run** | mobile code not touched |
| Migration `20261017090000` upgrade → downgrade → re-upgrade on disposable DBs | Reported, **not re-run** | handover; the SQL in §B5 was exercised against the already-migrated disposable DB only |
| Staging deployment, migration, Face++ sandbox calls, device matrix, attacks, latency/quota, calibration/holdout | **Requires staging infrastructure / real devices / real provider** | none available |
| Alert destination, owner, delivery and acknowledgement | **Requires staging infrastructure + SEC/STG decision** | none configured |
| Retention periods, legal-hold process, termination clean-up, consent/notice wording, model training-data acceptance, APCER/BPCER targets, `hrms_dev` cleanup | **Requires approval** | §E, §F |

---

## B. Staging deployment and evaluation plan

### B1. Principles

1. Staging is a **separate compose project on a separate host or at minimum a separate project name**
   (`COMPOSE_PROJECT_NAME=hrms-staging`) with its **own** Postgres, Redis and MinIO containers (the compose
   file already creates one of each per project) and its own env file. Nothing is shared with production
   or with `hrms_dev`.
2. Staging data are test employees and consented participants only. Never restore production data into it.
3. Face++ uses a **test/sandbox account** with its own key and secret and an agreed quota.
4. Email is `EMAIL_PROVIDER=logging` unless the STG owner approves a safe sink.
5. Nothing is deployed or migrated by anyone other than the STG/DBA owners.

### B2. Environment and secret inventory (names from `Settings` / compose; values never in the repo)

| Variable | Staging value / rule | Source of secret |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME`, `IMAGE_TAG` | `hrms-staging`, the reviewed build tag | STG |
| `POSTGRES_PASSWORD`, `HRMS_APP_PASSWORD` | unique to staging; `HRMS_APP_PASSWORD` must match `DATABASE_URL` | secrets manager |
| `DATABASE_URL`, `MIGRATIONS_DATABASE_URL` | staging DB only; app URL uses role `hrms_app`, migrations URL role `hrms` | STG/DBA |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | the **staging** Redis container; verify per §B6 | STG |
| `JWT_ACCESS_SECRET`, `JWT_REFRESH_SECRET`, `PII_MASTER_KEY` | **new** values, never production's (see `docs/deployment/DISASTER_RECOVERY.md`) | secrets manager |
| `EMAIL_PROVIDER` | `logging` | STG |
| `FACE_VERIFICATION_PROVIDER=facepp`, `FACEPP_API_KEY`, `FACEPP_API_SECRET`, `FACEPP_API_BASE_URL` | Face++ **test** credentials only | SEC/STG |
| `FACE_MATCH_MIN_SIMILARITY` (0.90), `FACE_ENROLLMENT_ANGLE_MIN_SIMILARITY` (0.80) | defaults until calibration (§C3) | — |
| `FACE_LIVENESS_ENGINE=minifasnet`, `FACE_LIVENESS_MODEL_DIR=/app/models/liveness/minifasnet-v1` | enable only after the image gate passes | STG |
| `FACE_LIVENESS_LIVE_THRESHOLD` (0.90), `FACE_LIVENESS_SPOOF_THRESHOLD` (0.50), `FACE_LIVENESS_FRAMES` (3), `FACE_LIVENESS_SESSION_TTL_SECONDS` (120) | defaults until calibration | — |
| `FACE_PUNCH_MAX_FAILED_ATTEMPTS` (5) / `FACE_PUNCH_ATTEMPT_WINDOW_MINUTES` (10), `FACE_ENROLLMENT_MAX_FAILED_ATTEMPTS` (5), `FACE_ENROLLMENT_WINDOW_HOURS` (48) | defaults | — |
| `FACE_*_RETENTION_DAYS` (3 vars) | **unset** (no approved period) — set only to agreed *test* periods for checklist R2–R7, then unset | DPO decision |
| `FACE_CLEANUP_DRY_RUN` | `true` except during R3/R4 | STG |
| `FACE_CLEANUP_HOLD_COMPANY_IDS` | the staging test company ids for R5 only | STG |
| `HRMS_ALERT_COMMAND`, `HRMS_COMPOSE_PROJECT=hrms-staging`, `HRMS_COMPOSE_CMD`, `HRMS_MAX_FACE_REJECTIONS`, `HRMS_MAX_FACE_SPOOF_SIGNALS` | **BLOCKED** until a destination exists (§D) | SEC |

`api`, `worker` and `beat` read the same `env_file` in `docker-compose.prod.yml`, so the cleanup settings reach the worker.
There is no staging env template: creating `apps/api/env/.env.staging.example` is a documentation task for STG once values are agreed.

### B3. Model assets and checksums

Source of truth: `_PINNED_SHA256` in `src/hrms/modules/attendance/liveness.py`. Verified this session to match
`docs/operations/FACE_LIVENESS_DOCKER_DEPLOYMENT.md`:

| File | SHA-256 |
| --- | --- |
| `minifasnet_v2_scale2.7_80x80.onnx` | `079399882d651cb9126de6444ca0fabce952db7d5792823ef6c4ae004132534f` |
| `minifasnet_v1se_scale4.0_80x80.onnx` | `828e4476ac4561c9185c092d173105f30c51f814d93fd71a892c1b67b41e5dd9` |
| `retinaface_deploy.prototxt` | `9fe2f141b4baee039ed9442da2833e216af40a6ff3e639e7b39258812bcda808` |
| `retinaface_widerface.caffemodel` | `d08338a2c207df16a9c566f767fea67fb43ba6fff76ce11e938fe3fabefb9402` |

Gate: the Docker build already runs `scripts/liveness/verify_assets.py` (build fails on mismatch); the STG owner
re-runs it inside the final image (`docker run … verify_assets.py models/liveness/minifasnet-v1`) and records the
four `OK` lines. **Never edit a pinned hash to make a file pass.**
**Blocker:** `apps/api/models/` is untracked; a CI/clean-checkout build cannot `COPY models`. The owner must decide to
commit the assets (the deployment doc already states that decision) before an image can be built from a clean tree.

### B4. Backup and restore requirements (before any migration)

1. Postgres: `infra/backup/pg_backup.sh`, then prove it restores: `infra/backup/pg_restore.sh` into a **new database name**
   (never over the live one), check the printed row counts, and record backup id, size, time and who verified
   (`docs/deployment/PRODUCTION_DEPLOYMENT.md` §14, `DISASTER_RECOVERY.md`).
2. MinIO (review photos are stored there until HR decides): `infra/backup/minio_backup.sh` and a restore check.
3. The backup is the **only** way to recover the Face++ response bodies that the migration erases (§B9). If staging data
   contains nothing worth keeping, the DBA may record "no value, accepted" explicitly instead.

### B5. Migration preflight and post-migration verification (execution `BLOCKED`)

Applies migrations `20261015090000` (if not yet applied) and `20261017090000` **to staging only, by the DBA/STG owner**:
`docker compose -f docker-compose.prod.yml -p hrms-staging --profile tools run --rm migrate`.

Preflight (read-only), expected outputs recorded in the checklist:

```sql
select version_num from alembic_version;                              -- PRE-1
select count(*) as attempts_total,
       count(*) filter (where provider_response ? 'verify') as bodies_to_erase
from face_verification_attempt;                                       -- PRE-2: rows that will lose stored Face++ bodies
```

Post-migration (read-only; all exercised against a disposable migrated DB this session):

```sql
select version_num from alembic_version;                              -- POST-1: 20261017090000
select to_regclass('public.face_enrollment_attempt') is not null as table_exists,
       (select relforcerowsecurity from pg_class where relname='face_enrollment_attempt') as rls_forced,
       (select string_agg(policyname,',') from pg_policies where tablename='face_enrollment_attempt') as policy,
       has_table_privilege('hrms_app','face_enrollment_attempt','INSERT') as app_role_can_insert;
                                                                      -- POST-2: t / t / tenant_isolation / t
select count(*) from face_verification_attempt
 where provider_response::text ~ 'face_token|face_rectangle|faceset|landmark|thresholds'; -- POST-3: 0
select (pg_get_constraintdef(oid) like '%AMBIGUOUS_FACE%'
    and pg_get_constraintdef(oid) like '%IDENTITY_INCONSISTENT%') as new_decisions_allowed
from pg_constraint where conname='face_verification_attempt_decision_check';   -- POST-4: t
```

Then: API `/health/ready` OK; with `FACE_LIVENESS_ENGINE=disabled` a face punch answers 503 and other punch types work.
Locking: one transaction; non-concurrent index builds and a CHECK-constraint rewrite briefly block writes to two small
face tables — run it in a quiet window. **Release coupling:** migrate *before* the new API starts (new code needs the schema;
old code tolerates it).

### B6. Isolation of queues and resources (prove, do not assume)

- `CELERY_BROKER_URL` and `REDIS_URL` must resolve to the staging Redis container's service name. Record
  `printenv` (secrets masked) from the `api`, `worker`, `beat` containers; the host must not equal any production host.
- `celery -A entrypoints.worker inspect ping` from the staging project shows only staging nodes.
- Exactly one `beat` instance. A staging worker must never be started with a production env file.
- Redis DB0 of any shared instance is out of bounds; staging uses its own instance.

### B7. Health checks and safe failure

`/health/live`, `/health/ready`, `python -m hrms.ops.job_health` (heartbeat/queue age), container health. Expected failure behaviour,
already implemented and tested locally: bad or missing model asset with the engine enabled → the API refuses to boot;
engine/provider disabled or erroring → 503/502, no punch, nothing partial; Redis down → limiter fails closed (503).

### B8. Rollback and forward recovery

| Level | When | Action | Effect |
| --- | --- | --- | --- |
| 1. Feature off | any face problem | `FACE_LIVENESS_ENGINE=disabled`, restart API | face punches/self-enrollment answer 503; web/HR/other punches unaffected; **schema stays** (recommended) |
| 2. Code rollback | bad release | `IMAGE_TAG=<previous> docker compose … up -d api worker beat web` | old code runs on the new schema (new table and decisions unused) |
| 3. Schema downgrade | last resort | `alembic downgrade 20261015090000` | drops `face_enrollment_attempt` **and its rows**; maps `AMBIGUOUS_FACE`/`IDENTITY_INCONSISTENT` to `NO_MATCH`; **does not restore erased bodies**; export both first |
| 4. Restore | data loss | restore the verified backup into a new DB, re-point, re-run migrations | only way to recover erased bodies |

Forward recovery is the default: fix and redeploy; do not downgrade production-like data.

### B9. Irreversible data change

Migration `20261017090000` **permanently erases** stored Face++ search bodies in `face_verification_attempt.provider_response`
(`verify` → `identity.{legacy_redacted, request_id}`). The downgrade restores structure only; surviving rows keep
`legacy_redacted: true` so they never pose as the originals. Only a pre-migration backup can bring them back.
PRE-2 tells the DBA how many rows are affected before it runs.

### B10. Other staging dependencies to settle first

- Mobile: the app in the working tree contains the uncommitted liveness-capture screens; the staging mobile build and the
  API must be released together (old builds send `photo` and get `FACE_LIVENESS_CHALLENGE_REQUIRED`). No mobile change was needed
  by the 2026-10-17 hardening (client shows server messages and maps no error codes).
- `docs/operations/FACE_LIVENESS_DOCKER_DEPLOYMENT.md` and `STAGING_VALIDATION_CHECKLIST.md` B-21 list only migration
  `20261015090000`; the second migration is documented here and in the checklist (P2).

**Execution status of §B: `BLOCKED`** (no staging host, credentials, Face++ test account, or approved build).

---

## C. Evaluation protocol

### C1. Ethics, consent and data handling

- Only consented participants and designated test employees. Written consent names the purpose, what is captured, who can see it,
  how long it is kept and how to withdraw (wording from LEGAL/DPO — see §E).
- Evaluation uses **test accounts**; no real employee's enrollment or punches are used.
- Captured images/video (needed only for offline engine measurement with `evaluate_captures.py`) live **outside the repository** on an
  access-restricted store chosen by SEC, named access list, encrypted at rest, deleted at the end of the evaluation by a recorded step.
  The retention date is fixed *before* collection by DPO.
- End-to-end trial results are recorded as outcome rows only (§C6): pseudonymous participant id, device label, outcome code, timings, counts.
  No image, frame, embedding, face token or provider body goes in any ticket, spreadsheet, log excerpt or this repository.
- Attack materials (prints, screens) are made from consenting participants' own images, with their permission.

### C2. Participants, devices, scale

Recommended structure (the owners set the numbers, see §C7): at least 2 Android (low and mid tier) and 1 iOS device;
a spread of skin tones, ages, glasses/no glasses, head coverings, facial hair; attackers are separate test colleagues or the
same consenting person presenting their own artefacts. **Independence unit = participant**, not frame, not attempt.
Statistical note for planning: with zero accepted attacks in *n* presentations the 95% upper bound on the true acceptance rate is
about 3/n (n=30 → ~10%, n=100 → ~3%, n=300 → ~1%); small samples cannot support strong claims.

### C3. Calibration versus holdout

1. Before collecting anything, assign each **participant** (not attempt) to `calibration` or `holdout`, stratified by device; record the
   assignment. A participant is never in both (the summariser refuses such a file).
2. Calibration data may be used to choose `FACE_LIVENESS_LIVE_THRESHOLD`, `FACE_LIVENESS_SPOOF_THRESHOLD`, `FACE_MATCH_MIN_SIMILARITY`,
   `FACE_ENROLLMENT_ANGLE_MIN_SIMILARITY`, the retry policy, and the attempt limits.
3. **Freeze** the configuration and the build; record both (git revision, image tag, the env values) as the `--frozen-config` label.
4. Run the holdout once, on the frozen build. Report holdout as is. If anything changes afterwards, that holdout is spent: a new one
   with new participants is required. Never pick a threshold by looking at holdout results.

### C4. Scenario matrix

Scenarios are registered in the checklist §§9–18 with owners and sign-off. Coverage:

| Area | Cases (checklist IDs) |
| --- | --- |
| Genuine users | bright/dim/backlit/outdoor, glasses, head covering, appearance change, low-end camera (G1–G10; RD-1…RD-3) |
| Printed photo, photo on another device, replayed video | A1–A6; RD-4…RD-6 |
| Background faces / several faces | G10, T11; RD-7 |
| Different identity in some punch frames | A7, A8, T10; RD-8 |
| Poor frames, partial face, camera failure/permission loss | C10; RD-9 |
| Expired, replayed, duplicate challenge | T1–T4, C1–C5; RD-10 |
| Network interruption, provider timeout, rate limit | C5, C6, C12; LQ-4, LQ-5 |
| Enrollment angles; limit and lock-out behaviour | G9, A9, T12–T14; RD-11, RD-12 |
| Rejection visibility and investigation | L2, L3, L3a; AL-1…AL-6 |

### C5. Metric definitions

All rates carry `n` (attempts) **and** `participants`. "Rejected" includes every server rejection and `LIVENESS_INCONCLUSIVE`.

| Metric | Numerator | Denominator | Exclusions / rules | Independence |
| --- | --- | --- | --- | --- |
| Genuine false-rejection, per attempt | genuine attempts rejected | genuine attempts not excluded | provider/engine errors and aborted trials excluded (reported separately) | attempts of one person are correlated → also give per participant |
| Genuine false-rejection, per participant (mean) | Σ of each person's own rejection rate | participants with ≥1 scored attempt | same | participant; bootstrap CI resamples people |
| Genuine acceptance, first attempt | presentations accepted on attempt 1 | genuine presentations | excluded-error presentations dropped | participant |
| Genuine acceptance, eventually | presentations with any accepted attempt | genuine presentations | | participant |
| Attack acceptance (APCER), per attack type × device | attack presentations where **any** attempt was accepted (worst case) | valid attack presentations for that type × device | errors excluded and reported | attacker participant; Wilson 95% bound shown; low-sample flag |
| Inconclusive / failed evaluations | `LIVENESS_INCONCLUSIVE` + excluded errors (count and share) | all attempts in the cell | shown, never silently dropped | — |
| Punch latency | median and p95 (nearest rank) of client-measured request time | accepted attempts; rejected attempts reported separately | timeouts are `ABORTED`/`PROVIDER_ERROR` and listed | — |
| Face++ requests per punch | mean requests per accepted attempt and per rejected attempt | those attempts | from server logs/provider dashboard | — |
| Provider error rate | `PROVIDER_ERROR` attempts | all punch attempts | none | — |
| Quota consumption | requests used / quota in the window | provider dashboard | note QPS/concurrency errors | — |
| Enrollment failure | participants whose first submission was rejected; participants who exhausted attempts (`LOCKED`) | participants with ≥1 scored submission | provider errors excluded | participant |
| Rejection-event visibility | rejections seen in the log/monitor within the monitor window | rejections injected/caused in the run | per checklist AL rows | — |

`scripts/liveness/summarise_trials.py` computes the above from the outcome CSV and enforces the split rules (16 unit tests, run this session).
`scripts/liveness/evaluate_captures.py` separately measures the engine alone, frame by frame, on stored captures.

### C6. How to record a trial (no biometric data)

One CSV row per API attempt with the columns documented in `summarise_trials.py`: `trial_id, participant_id, phase, kind, attack_type,
device, condition, split, attempt_no, outcome, latency_ms, facepp_requests`. Outcome comes from the API response/`face_verification_attempt.decision`
(or `face_enrollment_attempt.decision`); latency from the test app; Face++ request count from the server logs or provider dashboard.
Keep `participant_id` a pseudonym; the key to real identities stays with HR/DPO, not with the analysts.

### C7. Targets — proposals for the owners to decide (none adopted)

The system does not define acceptable APCER/BPCER; SEC and PRD must. To start the discussion, a worksheet to fill in **before** data collection:

| Quantity | Owner | Proposal to react to (no data behind it) | Decision |
| --- | --- | --- | --- |
| Genuine acceptance within 3 attempts | PRD | very high (e.g. ≥ 99% of presentations) | `NOT DECIDED` |
| Genuine first-attempt acceptance | PRD | stated as a number the workforce can live with | `NOT DECIDED` |
| Attack acceptance per attack class (upper bound) | SEC | stricter for cheap attacks (prints, screens) than expensive ones | `NOT DECIDED` |
| Minimum presentations/participants per attack class and device | SEC | enough that the 95% upper bound can meet the target (see C2) | `NOT DECIDED` |
| Punch latency p95 | PRD/MOB | derived from user tolerance on real mobile networks | `NOT DECIDED` |
| Face++ requests per punch & monthly cost ceiling | PRD | 6 requests per successful punch today | `NOT DECIDED` |
| Enrollment lock-out rate tolerated | HR | low, with a fast support path (§E, §9 of the checklist) | `NOT DECIDED` |

If no threshold setting meets both genuine and attack targets, **do not enable** the feature (consistent with the existing checklist).

### C8. Limitations of the current approach (state these in every report)

- Passive: three still frames ~200 ms apart plus a single-model liveness score; **no challenge-response liveness** (no random blink/turn
  verified by the server).
- **Virtual-camera, emulator, injected-frame and modified-client attacks are not detected** (no device attestation; the server cannot tell
  that frames came from a camera). Checklist T6 only *records* the outcome.
- Per-frame identity proves each frame matches the enrolled employee; it does not prove the three frames are the same live subject at one moment.
- The liveness model is an upstream open-source model with undisclosed training data, unmaintained, and uncalibrated on our devices/attacks;
  turned/tilted-head enrollment liveness is unmeasured.
- Face++ similarity semantics and "several faces" behaviour are used as documented; real behaviour on background faces is unmeasured.
- The attack set covers prints, screens and replay only: not 3D masks, deepfakes, or professional presentation attacks.
- Unit and integration tests prove contracts and fail-closed ordering with mocks; they do not measure spoof resistance.

---

## D. Alerting and operational readiness

What exists (verified by reading `infra/monitoring/hrms_monitor.sh`, `ALERTS_AND_RUNBOOKS.md` and the tests):

| Question | Answer |
| --- | --- |
| Event | `security.face_punch.rejected` (fields: `reason` from a fixed vocabulary else `UNKNOWN`, `company_id`, `employee_id`, `liveness_session_id`) and `security.face_enrollment.rejected` (`reason`, `angle`, ids). No scores, images, tokens, provider data |
| `face_rejections` | counts both events in the window; fails above `HRMS_MAX_FACE_REJECTIONS` (default 10); severity medium |
| `face_spoof_signals` | counts those events whose `reason` ∈ {SPOOF_SUSPECTED, CAPTURE_REPLAYED, IDENTITY_INCONSISTENT, AMBIGUOUS_FACE, MULTIPLE_FACES}; fails above `HRMS_MAX_FACE_SPOOF_SIGNALS` (default 3); severity high |
| Frequency | The script is **stateless and run by cron, installed by the operator** (documented as every 5 min, window `HRMS_MONITOR_WINDOW` default 5m). The repository contains no cron entry, compose service or systemd unit that runs it |
| Invoked in staging? | **No** — nothing in the repo schedules it anywhere. STG must install it and set `HRMS_COMPOSE_PROJECT=hrms-staging` (default is `hrms-prod`) and `HRMS_COMPOSE_CMD` |
| Output | one JSON report on stdout (`ok`, `failing`, per-check values); exit 0 ok, 1 a check failed, 2 the monitor itself could not run; stderr gets `{"alert_delivery":"sent|failed|not_configured"}` |
| Consumer | **none configured.** With `HRMS_ALERT_COMMAND` unset a failure is written to the cron log and nobody is told (`not_configured`) |
| Known limits | stateless: an event can fall in two windows or none if cron drifts; totals only (no per-employee grouping — that is done by hand); depends on `docker logs` retention; cannot see events dropped when stdout is unwritable (`log_writes_dropped` is separately monitored) |
| Investigation workflow | `ALERTS_AND_RUNBOOKS.md` §3.9 (group by `employee_id` and `reason`; ordinary `NO_FACE`/`NO_MATCH` is baseline; many employees at once suggests a lighting/device/threshold problem; repeated `IDENTITY_INCONSISTENT` or `CAPTURE_REPLAYED` from one employee goes to HR/security). Scores come from the DB (`face_verification_attempt.decision, similarity, liveness_score`), never from logs |
| Log hygiene | log fields are ids, fixed codes and counts; Face++ errors log only `error_code`; tests assert no frames, digests, keys, face tokens or request ids leak (see the report, Part B §B4 and §B6) |

**Alerting is not operational.** It becomes operational only when a real alert has been delivered *and acknowledged by a named, authorised recipient*.

Requirements to close the gap (no service is provisioned by this plan):

1. **Destination** (owner SEC/STG decision): a chat webhook, mail relay or pager reachable from the staging host, wrapped in a script given as `HRMS_ALERT_COMMAND`.
2. **Credentials**: webhook URL/API token held in the host's secret store, readable only by the cron user; never in the repo or in the cron log.
3. **Owner and recipients**: named primary and secondary recipient and a working-hours/out-of-hours expectation per severity.
4. **Test procedure** (checklist AL-3, AL-4): cause >10 rejections or >3 `SPOOF_SUSPECTED` in a window on staging using test accounts → `face_rejections`/`face_spoof_signals` appear in the report → `{"alert_delivery":"sent"}` → the recipient **acknowledges receipt with a timestamp** → negative tests: revoke the webhook (`failed`), unset the command (`not_configured`).
5. **Escalation path** (template to fill): recipient → security owner → HR owner (employee contact) → DPO if biometric exposure is suspected → LEGAL if reportable.
6. Re-test after any change to the script, destination or credential and at least quarterly.

---

## E. Privacy and lifecycle approval worksheet

Nothing below is decided. Do not invent values; each row names the decision-maker and the evidence they need. "Status" is `NOT DECIDED` unless a record is attached.

| # | Decision | Decision-maker | Evidence needed | Current technical state | Blocks |
| --- | --- | --- | --- | --- | --- |
| E1 | Retention for `face_liveness_session` (challenge + frame digests) | DPO, SEC | the replay horizon the business wants (digests only catch repeats *within* retention), legal retention duties | tool exists, **unset**, report-only | prod |
| E2 | Retention for `face_verification_attempt` detail (per-frame scores, `provider_person_id`) | DPO, HR, LEGAL | how long attendance disputes can be raised; whether decision + scores (kept) suffice | detail-erase supported; rows never deleted | prod |
| E3 | Retention for `face_enrollment_attempt` | DPO, SEC | how long rejected-enrollment history is useful for abuse review | delete supported, **unset** | prod |
| E4 | Legal hold: who can place it, how it is recorded, release | LEGAL, DPO | policy text; granularity needed | company-level only via `FACE_CLEANUP_HOLD_COMPANY_IDS`; **per-employee hold not built** | prod |
| E5 | Access control and auditing for biometric information | SEC, DPO | role list allowed to see review photos, attempts, Face++ console; audit requirement | review photo behind `ATTENDANCE.FACE_ENROLLMENT_MANAGE`, data-scoped; approve/reject/revoke audited; Face++ console access is outside the app | staging+prod |
| E6 | Employee notice and consent wording (enrollment screen, policy, withdrawal) | LEGAL, DPO, HR | jurisdictional requirements; consent record format | `consent_recorded_at` mandatory at enrollment; wording not reviewed here | prod |
| E7 | Liveness model: training-data and licensing acceptance | LEGAL, SEC | upstream licence (Apache-2.0, text retained) and the undisclosed training data | model assets untracked in git; feature stays disabled until accepted | prod |
| E8 | **Employee termination**: remove face profile from HRMS **and** Face++ | HR, DPO, API | policy (when, who, grace period); proof of provider deletion | **no automatic revoke exists** (grep: nothing in the employee module); interim manual path: HR `DELETE /attendance/face-profiles/{employee_id}` (deletes the Face++ FaceSet first, then marks REVOKED); a profile still `PENDING_APPROVAL` is rejected via `/reject` instead. Automatic clean-up needs a change in the employee module | prod |
| E9 | Re-enrollment, disputes, recovery when a legitimate employee keeps failing | HR, PRD | support SLA; fallback rule | HR can record a punch by regularisation (`source=REGULARIZATION`, self-approval blocked); HR can revoke and open a new enrollment window; enrollment lock-out (5) resets only by HR opening a window | staging+prod |
| E10 | Irreversible deletion and backups: do backups keep what cleanup/revoke removed, for how long | DPO, DBA | backup retention schedule | cleanup/revoke act on live data only. **A restore resurrects erased rows and may reference deleted FaceSets** → a post-restore reconciliation (re-apply revocations/cleanup, delete orphan FaceSets) must be written | prod |
| E11 | Incident response if biometric data is exposed | SEC, DPO, LEGAL | breach procedure, regulator/employee notification rules | exposure surface listed below | prod |
| E12 | APCER/BPCER, latency, cost targets | SEC, PRD | §C7 | undecided | staging sign-off |
| E13 | Face++ data-processing terms, region/endpoint (`facepp_api_base_url`), their retention of submitted images | LEGAL, DPO | provider contract/DPA | not reviewed | prod |

**Exposure surface for E11** (what exists where): Face++ holds the enrolled faces (one FaceSet per employee) — the real biometric reference;
MinIO holds one review photo per pending enrollment until HR decides (deleted on approve/reject); Postgres holds SHA-256 frame digests, decisions,
similarity/liveness scores, provider person ids and consent timestamps (no images or embeddings); logs hold ids and fixed codes. Immediate steps if a
leak is suspected: contain (disable the engine/provider), preserve logs, identify affected FaceSets and MinIO keys, revoke/delete at Face++, rotate
`FACEPP_API_KEY/SECRET`, involve DPO/LEGAL for notification decisions. Provider-side deletion is the step that cannot be done from the database.

**Verified this pass:** unset retention is non-destructive and report-only by default (see §A).

---

## F. `hrms_dev` cleanup — decision record (NOT EXECUTED; do not execute as part of this work)

Background (read-only investigation, 2026-10-17): 83 candidate companies (`Acme <10 hex>`, TRIAL), 161 candidate users (83 `priya-<10 hex>@acme.example`
admins + 78 `scoped-*@example.com`), created 11:22–11:23 UTC on 2026-10-17; no activity afterwards; no rows outside the candidates reference them;
`hrms_dev` still at revision `20261015090000`. **No test-run identifier was recorded.** Seven older `Acme …` companies/admins from 2026-10-16 14:38 UTC are
the same kind of leftover but **explicitly out of scope** of this decision; `Demo Company A/B` are seed data and never candidates. The explicit id
manifests were exported to the session scratchpad
(`…/scratchpad/hrms_dev_candidate_company_ids.txt`, `…_user_ids.txt`); they may not exist in your workspace — if absent, regenerate them with the read-only
criteria above (company name pattern + window + admin email pattern + `scoped-` users linked only to candidate companies) and have the owner approve the *list*.

Required process — each step is a separate sign-off; a later step may not start before the earlier one is recorded:

1. **Owner confirmation.** The `hrms_dev` database owner confirms no legitimate registrations took place in the candidate window (11:22–11:24 UTC, 2026-10-17) and
   that nobody is using those tenants.
2. **ID and dependency review.** The explicit company and user id lists, plus the foreign-key dependents found read-only (`audit_log` 325 rows,
   `company_setup_progress` 83, `employee` 81, `face_enrollment_window` 77, `number_series` 80, `refresh_token` 83, `role` 493, `session` 161,
   `user_company` 161, `email_verification_token` 83, then `user` 161 and `company` 83; other company-scoped tables showed 0) are reviewed and the expected
   counts are written down. Re-run the counts immediately before execution; any difference stops the process.
3. **Fresh backup, verified.** A new backup is taken and restored into a differently named database; row counts compared. Record backup id and verifier.
4. **Deletion plan with assertions.** A reviewed script that deletes **by explicit id list only** (never by `scoped-%` or by time), in dependency order, inside one
   transaction, asserting the exact expected counts per table and rolling back on any mismatch; reviewed by a second person. The suite's own
   `_cleanup_scoped_users` deletes every `scoped-%` user and must not be the mechanism.
5. **Explicit authorisation.** The database owner records, in writing, "execute the plan with manifest hash `<sha256>` against `hrms_dev` at `<time>`".
6. **Separate execution and verification.** Run once, by the owner or a named delegate; then verify: candidate ids gone, the 7 older and 2 seed tenants and all
   other counts unchanged, `alembic_version` unchanged, application and a test login still work. Record the output.

| Field | Value |
| --- | --- |
| Database owner | `NOT ASSIGNED` |
| Step 1 confirmation (who/when) | `NOT DONE` |
| Manifest sha256 (companies / users) | `NOT RECORDED` |
| Backup id and restore verification | `NOT DONE` |
| Reviewer of deletion plan | `NOT ASSIGNED` |
| Authorisation | `NOT GIVEN` |
| Execution / post-verification | `NOT DONE` |

---

## G. Sign-off

Final staging sign-off is recorded in the checklist (§18). It requires every `BLOCKED`/`NOT RUN` row either `PASS` with evidence or an
explicit, signed risk acceptance, the approvals in §E, and the targets in §C7 decided *before* the data were collected.
Meeting it makes the feature eligible for a limited pilot decision. It does not make it fraud-proof.
