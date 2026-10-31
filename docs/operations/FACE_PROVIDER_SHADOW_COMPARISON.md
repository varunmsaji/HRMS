# Face provider shadow comparison

Test-only facility to run a second face-identity provider beside the official one and compare.
**The shadow provider never affects attendance.** Off by default; with it off, no shadow code runs.

## 1. Architecture

Existing (unchanged): `FacePunchService.punch_self` (`attendance/face_service.py`) → replay/geofence/
attempt-limit → liveness (RetinaFace + MiniFASNet, untouched) → `provider.verify()` on every frame
(`FaceVerificationProvider` protocol, `attendance/face_verification.py`; `opensource` = YuNet+SFace,
`facepp` = Face++) → all frames must match → `record_punch_outcome` → `face_verification_attempt`.

Added:

```
 frames (in memory) ──► liveness ──► ┬─► PRIMARY  verify ×N ──► official decision ──► punch / reject
                                     │                               │
                                     └─► SHADOW (asyncio task)       │ (decision already fixed)
                                         own timeout, swallows all   ▼
                                         errors, own DB transaction  finish_comparison()
                                                  └────────────────► face_verification_comparison
```

* `attendance/face_comparison.py` – `start_shadow` (returns `None` unless enabled → nothing runs),
  `finish_comparison` (returns `None`, never raises), normalized `ProviderObservation`.
* The shadow task is started after liveness passes (so only frames that reached identity checking are
  compared), runs concurrently with the primary, and is awaited only **after** the official outcome is
  fixed and **before** the request transaction resumes (no DB connection held). Worst-case extra
  latency is bounded by `FACE_PROVIDER_SHADOW_TIMEOUT_SECONDS` minus the time the primary already took.
* Liveness rejections never reach identity, so they produce no comparison row.
* Shadow results are not written to `face_verification_attempt`, are not counted by the
  failed-attempt limit, and cannot change status codes. Primary failures behave exactly as before
  (e.g. 502) and are recorded as `primary_error`.

### Privacy
Frames are used from memory only during the request and are not kept (no new biometric retention —
this is why in-request execution was chosen over a background worker, which would need frames
persisted). The tables hold decisions, scores, thresholds, latencies and error **codes** only: no
images, embeddings, provider bodies, credentials. Logs carry the same fields. **Operational caveat:**
with Face++ as primary or shadow, participants' frames are sent to a third party — only for
consenting test participants. Shadow enrollment requires an explicit `consent_confirmed`.

## 2. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `FACE_VERIFICATION_PROVIDER` | `disabled` | Official provider: `opensource` \| `facepp` \| `disabled` |
| `FACE_VERIFICATION_SHADOW_PROVIDER` | `disabled` | Observed provider, same values |
| `FACE_PROVIDER_COMPARISON_ENABLED` | `false` | Master switch for shadow execution |
| `FACE_PROVIDER_SHADOW_TIMEOUT_SECONDS` | `8` | Wall-clock ceiling for all shadow work on one punch (0–60) |

Validation (boot fails with a clear message): comparison on requires a primary, a shadow ≠ `disabled`,
shadow ≠ primary, and the shadow's own prerequisites (`FACEPP_API_KEY/SECRET`, or `FACE_OS_ENABLED` +
`FACE_OS_MODEL_DIR`). With comparison off the shadow setting is ignored.

| Test | PROVIDER | SHADOW_PROVIDER | COMPARISON_ENABLED |
|---|---|---|---|
| A open-source only | opensource | disabled | false |
| B Face++ only | facepp | disabled | false |
| C | opensource | facepp | true |
| D | facepp | opensource | true |

## 3. Migration `20261101090000_face_provider_comparison` (additive)
* `face_shadow_enrollment` – (company, employee, provider) → shadow person id + consent time. Separate
  from `employee_face_profile` (one profile per employee is assumed all over production code).
  Participants must be enrolled with the shadow provider here; otherwise the row records
  `NOT_ENROLLED`.
* `face_verification_comparison` – one row per punch attempt that reached identity checking. Columns:
  both providers' `*_result` (attempt vocabulary + `NOT_ENROLLED`/`ERROR`/`TIMEOUT`), `*_matched`,
  `*_score`, `*_threshold` (each in its **own** scale — never compared), `*_latency_ms`, `*_error`
  (code), `shadow_timed_out`, `results_agree` (binary matched/not-matched; NULL when either side has
  no verdict), `liveness_session_id` (join key to the attempt row; no FK by design — written in its
  own transaction), `ground_truth` (admin label). RLS per tenant like every face table.
* Retention: no retention job exists for these tables (no images, but they are personal data): purge
  manually after the trial. Downgrade drops both tables.

## 4. API (all need `ATTENDANCE.FACE_ENROLLMENT_MANAGE`; employees get 403)
* `GET  /v1/attendance/face-verification-comparisons` – paged rows. Filters: `date_from`, `date_to`,
  `employee_id`, `primary_provider`, `shadow_provider`, `agreement=agree|disagree`, `errors_only`.
* `GET  /v1/attendance/face-verification-comparisons/summary` – same filters. Totals; both matched /
  both rejected / primary-only / shadow-only; agreement % (over rows where both gave a verdict);
  per-provider latency (n, avg, p50, p95, p99), error + timeout counts and rate; labelled FAR/FRR.
* `PATCH /v1/attendance/face-verification-comparisons/{id}/ground-truth` `{ground_truth: GENUINE|IMPOSTOR|null}`.
* `POST/GET/DELETE /v1/attendance/face-shadow-enrollments[/{employee_id}]` – multipart `photos` (1–8) +
  `consent_confirmed`. 409 if already enrolled; delete removes the provider-side person first.

## 5. Testing protocol
Identity (consenting participants only): enroll with both providers (production flow for the primary,
shadow endpoint for the shadow). **Genuine:** each participant punches repeatedly across lighting,
distance, slight pose, time of day, glasses/no glasses, phones. **Impostor:** participant A punches
while signed in as B (and B as C, …) — then label those rows `IMPOSTOR` and genuine rows `GENUINE`
via the PATCH endpoint (unlabelled rows are excluded from FAR/FRR). Liveness/spoof testing is a
separate exercise on the existing pipeline (`scripts/liveness/`): printed photo, phone-screen photo,
video replay, varied quality/lighting; no claim beyond what is measured.

Definitions (per provider, over labelled rows where that provider gave a verdict): TA = genuine
accepted; FR = genuine rejected; TR = impostor rejected; FA = impostor accepted. **FAR = FA /
impostor attempts; FRR = FR / genuine attempts.** Counts are returned with the rates; with small
samples the rates carry wide uncertainty and must not be read as precise. Neither provider is
claimed more accurate until real labelled data exists. Provider agreement is *not* accuracy.

## 6. Tests added / run
* `tests/unit/modules/attendance/test_face_comparison.py` (37 incl. gate tests): config valid/invalid/
  disabled/duplicate; shadow match/reject/below-threshold/error/unexpected/timeout/not-enrolled;
  disabled starts nothing; agreement on binary outcome; `finish_comparison` never raises and returns
  None under shadow match/reject/error/timeout × persistence failure.
* `tests/integration/modules/attendance/test_face_shadow_comparison.py` (13): through the real app/DB —
  shadow REJECT cannot change primary MATCH; shadow MATCH cannot change primary REJECT (attempt log
  has exactly the primary's single NO_MATCH row); shadow ERROR/exception/TIMEOUT cannot fail or alter
  a punch (timeout bounded); primary failure unchanged (502, PROVIDER_ERROR); not-enrolled; comparison
  off never constructs the shadow; report filters/aggregates/FAR-FRR; employees get 403; shadow
  enrollment lifecycle leaves the production profile untouched.
* Regression results and known limitations: see §8.

## 7. Performance
`scripts/face/provider_benchmark.py` (`opensource` | `facepp` | `simulate`). Real engine measurement
needs OpenCV+numpy (`uv sync --extra liveness`) and, for Face++, billable calls with consented images.
Key fact from the code: open-source inference is capped at `FACE_OS_MAX_CONCURRENCY` (default **1**
per process) and a punch does one inference per frame (3 frames) — see the queueing simulation in §8.
Run the real benchmark and the 10/25/50/100-concurrent punch test on the target hardware before
trusting any scaling claim; if the open-source engine is the shadow it competes with the primary's
inference for the same cap.
