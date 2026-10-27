# Face attendance - two selectable engines

Written for: engineers extending or operating face attendance.

Date: 2026-10-25. Baseline and findings: `docs/audits/OPEN_SOURCE_FACE_ATTENDANCE_AUDIT.md`.

## 1. Shape

```
FacePunchService / FaceEnrollmentService      (unchanged business rules)
        |  FaceVerificationProvider (port)              LivenessEngine (shared, local MiniFASNet)
        +--> FaceppFaceVerificationProvider   provider_name = FACEPP       (Face++ over httpx)
        +--> OpenSourceFaceVerificationProvider provider_name = OPENSOURCE
                 |- SFaceEmbeddingService   YuNet detect + SFace embed (OpenCV DNN, ONNX, local)
                 |- DbEmbeddingStore        face_embedding rows, AES-256-GCM, RLS
                 `- similarity              pure cosine / thresholds
```

The attendance services only see the port and a normalised `FaceMatchResult`. Engine specifics stay
in their adapters; the services read two optional attributes (`match_threshold`,
`angle_threshold`) so each engine is judged on its own score scale.

## 2. Selection

`FACE_VERIFICATION_PROVIDER` = `disabled` (default) | `facepp` | `opensource`.
`opensource` additionally requires `FACE_OS_ENABLED=true` and `FACE_OS_MODEL_DIR` - settings
validation refuses to boot otherwise, and the app lifespan loads + checksums the models so a bad
deployment fails at boot. Selection is one process-wide value; **there is no fallback**: an engine
error is a `FaceProviderError` (HTTP error `FACE_PROVIDER_FAILED`, decision `PROVIDER_ERROR`),
never a retry on the other engine and never an accepted punch. Switching engines is a deliberate
config change plus per-employee re-enrollment.

## 3. Identity mapping

| Port concept | Face++ | Open-source |
|---|---|---|
| `person_id` (stored in `employee_face_profile.provider_person_id`) | FaceSet token | `osf1.<company uuid>.<person_ref uuid>` (<= 100 chars) |
| `enroll(label=employee_id)` | detect + faceset/create | embed front capture, store sample 0 |
| `add_reference_photo` | faceset/addface | embed, store another sample (cap `FACE_OS_MAX_SAMPLES_PER_PERSON`, default 8) |
| `verify` | faceset/search in this employee's FaceSet | embed probe, **best cosine against this person's samples** (1:1; no tenant-wide search exists) |
| `delete_person` | faceset/delete | delete this person's rows (idempotent) |
| similarity | 0..100 confidence / 100 | cosine clamped to 0..1, 4 dp |

Cross-engine safety (all tested): the punch path refuses a profile whose `provider` differs from the
selected engine (FE-01); the OS engine rejects any id that is not `osf1.` (a Face++ token is an
error, never a successful no-op delete); the person id's company must equal the request tenant when
one is set; embeddings carry the `model_version` that made them and are never compared across
versions (`re-enrolment required`, an infrastructure-class error, not a biometric NO_MATCH).

## 4. Data and storage

`face_embedding(id, company_id, employee_id, person_ref, sample_index, model_version, embedding_enc,
created_at)`, `UNIQUE(person_ref, sample_index)`, RLS `tenant_isolation` (ENABLE + FORCE).
`embedding_enc` is `PiiCryptoService` AES-256-GCM (random 96-bit nonce per value, 128-bit tag
verified on every decrypt) under the **environment-wide** data key (DEK) - *not* a per-tenant key.
Correction: an earlier revision of this document said "tenant data key"; the code has one ACTIVE
DEK per environment (`encryption_keys`, wrapped by AES-GCM under SHA-256(`PII_MASTER_KEY`), see
`core/crypto/master_key.py`, `keys.py`). Tenant separation is therefore (1) row-level security on
`face_embedding`, (2) the 1:1 design (a person id is read from the caller's own profile and its
company must equal the request tenant) and (3) the ciphertext binding below - not cryptographic
key separation.

Ciphertext binding: the AAD is `face_embedding:embedding_enc:<record id>` where the record id is
`uuid5(row id | company | employee | person_ref | sample_index | model_version)`
(`store._aad_record_id`). Re-pointing a stored template at another employee/person/tenant, swapping
two rows' ciphertext, or relabelling its model version makes GCM authentication fail; the store
raises, `verify` surfaces `FaceProviderError` (PROVIDER_ERROR) - never a match and never a silent
skip (integration test `test_tampered_ownership_columns_fail_closed_never_match`). Decryption
happens only in `DbEmbeddingStore.load` for a 1:1 comparison. No API schema, audit row
(`provider_response`), log line or metric carries an embedding or image. No FK from the profile to
embeddings, mirroring Face++ (the provider-side person exists before the profile row); orphans are
removed by the existing `face_external_deletion` outbox, which routes each row to the engine that
created it.

Key lifecycle (details and limits in the audit, section 11): rotation adds a new DEK version for
new writes and keeps old versions decryptable; **no re-encryption sweep exists for
`face_embedding`**; losing `PII_MASTER_KEY` or the `encryption_keys` rows makes every stored
embedding unrecoverable (employees must re-enroll).

Existing Face++ enrollments cannot be converted: the original images are not stored and the FaceSet
holds no extractable embeddings. Moving an employee is revoke -> (outbox deletes the FaceSet) -> new
enrollment window -> self-enrollment with the new engine.

## 5. Runtime behaviour

- Local inference only; the OS engine imports no HTTP client (a test makes `httpx` clients fatal).
- Inference runs in a worker thread (`asyncio.to_thread`) behind a bounded pool of
  `FACE_OS_MAX_CONCURRENCY` model instances. Admission is on the event loop: an
  `asyncio.Semaphore(max_concurrency)` plus a waiting room of 4 x `FACE_OS_MAX_CONCURRENCY`
  requests; beyond that, or after `FACE_OS_INFERENCE_TIMEOUT_SECONDS`, a request fails fast
  (`EmbeddingTimeoutError` -> PROVIDER_ERROR). Waiters therefore never occupy default-executor
  threads (shared with liveness inference). The slot is released on success, error and
  cancellation (unit-tested). One model set per **process**: each gunicorn worker loads its own.
- Images: JPEG/PNG only, header-checked 160..4096 px before decode, downscaled to a 1280 px long side for detection.
- Multiple faces: a second detection counts only if its shorter side >= `FACE_OS_MIN_FACE_PX` -> `MULTIPLE_FACES`.
- No face / face smaller than `FACE_OS_MIN_FACE_PX` -> `NO_FACE` (verify) or `FaceProviderNoFaceError` (enroll).
- Shutdown: `close_face_verification_providers` clears both engine caches (the OS engine holds no connections).

## 5a. Switching engines - what each party sees

A profile keeps the `provider` that created it. After a switch, ENROLLED / PENDING_APPROVAL
profiles of the other engine get `requires_reenrollment: true` in `GET /v1/attendance/face-profiles`
and `.../{employee_id}/enrollment` (additive, defaulted field; computed only there; no biometric
data). Punches by those employees return `FACE_NOT_ENROLLED` ("created with a different face
engine"). Approving a PENDING_APPROVAL profile of the other engine is not blocked - HR should use
the flag to revoke it instead.

## 6. Error semantics (unchanged API contract)

| Cause | Port result | Recorded decision | Counts toward lockout |
|---|---|---|---|
| similarity >= threshold | MATCHED | MATCHED | n/a |
| similarity < threshold | NO_MATCH | NO_MATCH | yes |
| no/small face | NO_FACE | NO_FACE | yes |
| several faces | MULTIPLE_FACES | AMBIGUOUS_FACE | yes |
| liveness reject | (liveness engine) | LIVENESS_* | yes |
| model missing/timeout, store error, no comparable reference | `FaceProviderError` | PROVIDER_ERROR | **no** |

## 7. Configuration

All new settings are `FACE_OS_*` (see `.env.example`): `ENABLED`, `MODEL_DIR`, `MATCH_THRESHOLD`
(0.2-0.95, default 0.45, **uncalibrated**), `ENROLLMENT_ANGLE_THRESHOLD` (default 0.363),
`DETECTOR_SCORE_THRESHOLD`, `MIN_FACE_PX`, `MAX_CONCURRENCY` (default 1), `INFERENCE_TIMEOUT_SECONDS`,
`MAX_SAMPLES_PER_PERSON`. No secrets are involved. Thresholds are cosine similarities - not
comparable with `FACE_MATCH_MIN_SIMILARITY`.

## 8. Model choice

See `docs/operations/OPEN_SOURCE_FACE_ATTENDANCE_SETUP.md` section 2. Recognition and detection are
replaceable independently of liveness; a new model means a new `MODEL_VERSION` in
`opensource_face/assets.py` and re-enrollment.

## 9. Known limits of this design

Passive single-frame liveness is not proof of physical presence; the OS engine adds no
anti-spoofing of its own. No image-quality scoring (blur, exposure, pose) beyond detector score and
face size. Thresholds are not calibrated. Embedding model provenance is an open legal gate. The
store opens its own short transactions (like the Face++ HTTP calls it replaces), so a profile row
and its embeddings do not commit atomically; the existing compensation and outbox cover the gap.
