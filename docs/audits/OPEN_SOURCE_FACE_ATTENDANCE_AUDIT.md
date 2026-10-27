# Open-source face attendance engine - baseline audit

Written for: engineers and the release owner deciding whether and how a second face engine may
coexist with Face++.

Date: 2026-10-25 (first pass: sections 1-9; **second pass - final readiness: sections 10-14**). Evidence is from reading the repository at the working-tree state of that day
(uncommitted work preserved) and from the tests named below. Statuses: VERIFIED, PARTIAL, MISSING,
NOT TESTED, BLOCKED.

## 1. How the current engine is selected

`Settings.face_verification_provider: Literal["disabled", "facepp"]` (default `disabled`,
`core/config/settings.py`). `attendance/face_verification.py::get_face_verification_provider`
returns one process-wide `FaceppFaceVerificationProvider` or `None`; `attendance/dependencies.py`
injects it into `FaceEnrollmentService` / `FacePunchService`. There is no fallback logic anywhere:
`None` makes enrollment and punching fail closed. **VERIFIED** (existing tests + new factory test).

## 2. Coupling of recognition and liveness - none

Liveness is `attendance/liveness.py` (MiniFASNet over OpenCV DNN, local, checksum-pinned,
`LivenessEngine` protocol, own settings `face_liveness_*`). Its module docstring records that it
*replaced* Face++-based liveness. Both services take `provider` and `liveness` as independent
constructor arguments and require both. So liveness is already a shared, provider-independent
component and was reused unchanged. **VERIFIED.**

## 3. The seam that already existed

`FaceVerificationProvider` (Protocol): `enroll`, `add_reference_photo`, `verify`, `delete_person`,
`aclose`, `provider_name`. Results are `FaceMatchResult(decision, similarity, provider_request_id)`
with decisions `MATCHED | NO_MATCH | NO_FACE | MULTIPLE_FACES`; unusable enrollment photos raise
`FaceProviderNoFaceError` / `FaceProviderMultipleFacesError`; infrastructure problems raise
`FaceProviderError`. The attendance services never import anything Face++-specific except these
port types, so no new abstraction was introduced: the open-source engine is a second
implementation of this port.

## 4. Shared data model

| Table | Provider-neutral? | Notes |
|---|---|---|
| `employee_face_profile` | yes (`provider`, `provider_person_id` opaque) | `provider` CHECK allowed only `LUXAND`,`FACEPP` -> widened (migration `20261022090000`) |
| `face_verification_attempt` | yes | same CHECK widened; `provider_response` is JSONB evidence (liveness + identity scores only) |
| `face_external_deletion` | yes (`provider` nullable, `resource_ref` opaque) | outbox drives post-commit deletion |
| `face_enrollment_window`, `face_liveness_session`, `face_enrollment_attempt` | yes | engine-agnostic |
| embeddings | **did not exist** | new table `face_embedding` |

## 5. Provider-specific operations that cannot be reused

FaceSet creation/lookup/deletion, `face_token` handling, the 0..100 `confidence` scale, the
request-id correlation and the pooled `httpx` client are Face++ only and stay in
`FaceppFaceVerificationProvider`. Embedding extraction, cosine matching and embedding storage are
new and live in `attendance/opensource_face/`.

## 6. Existing protections (all inherited unchanged by the new engine)

Single-use, expiring liveness challenges with frame-digest replay detection; per-employee failed-
attempt limit that excludes infrastructure failures (`INFRASTRUCTURE_FAILURE_DECISIONS`); idempotency
keys and the in-flight duplicate wait; per-IP flood limits; HR approval of self-enrollment; revocation
and the deletion outbox; retention cleanup; audit events; RLS on every face table. **VERIFIED**
by the existing 400+ attendance/security integration tests, re-run (section 9).

## 7. Findings that required changes

| ID | Finding | Status | Resolution |
|---|---|---|---|
| FE-01 | `FacePunchService.punch_self` never compared `profile.provider` with the active provider; with two engines a Face++ FaceSet token would be handed to the other engine (or the reverse). | **was MISSING** | Guard added: mismatch -> `FACE_NOT_ENROLLED` (409), recorded as `NOT_ENROLLED`, nothing sent to either engine. Integration test `test_profile_from_the_other_engine_is_not_usable`. |
| FE-02 | The match floor was `face_match_min_similarity` (0.90, Face++ 0..1 confidence) at two places in `face_service.py`; reusing it would make a cosine score of 0.6 fail or force a wrong scale. | was MISSING | Service reads optional `provider.match_threshold` / `provider.angle_threshold`, falling back to the settings as before (Face++ behaviour byte-identical). |
| FE-03 | Deletion worker only built a Face++ client, and only when Face++ was the *selected* provider. After a switch, the other engine's data would be stranded or (worse) its ids passed to the wrong engine. | was MISSING | Worker picks the engine named on each outbox row (`provider_for_stored_name`). Face++ rows stay deferred while face attendance is disabled (previous behaviour; a regression in this very change was caught by `test_disabled_provider_defers_person_deletions_instead_of_losing_them` and fixed). |
| FE-04 | Startup validation only for Face++ credentials / liveness assets. | PARTIAL | `face_os_*` settings validated; selecting `opensource` needs `face_os_enabled=true` and a model dir; `app.py` lifespan loads and checksums the models at boot. |
| FE-05 | No place to store embeddings. | MISSING | `face_embedding` (encrypted, RLS) - architecture doc section 4. |

## 8. Things deliberately not changed

Face++ adapter code, its settings and defaults, API routes and schemas, error codes, attendance
rules, the liveness engine, enrollment/approval/revocation flows, idempotency and challenge logic.
The default provider remains `disabled`; the new engine cannot be enabled by the provider switch
alone.

## 9. Baseline test evidence (before/after)

- Unit: 1303 passed (`.venv/bin/python -m pytest tests/unit`). With the optional `liveness` extra
  (OpenCV) installed, the two `test_liveness.py` boot tests that fail without it pass.
- Integration, isolated disposable DB (`hrms_test`, created and dropped by this work; Redis /1):
  `tests/integration/modules/attendance` + `tests/security` -> 402 passed, 1 failed on the first run
  (FE-03 regression above); after the fix the same folders re-run end to end -> **403 passed**
  (including the 6 new engine tests and an `hrms_app` runtime-role RLS check on `face_embedding`).
- Migration `20261022090000` upgrade -> downgrade -> upgrade -> downgrade -> upgrade on the disposable
  DB: clean. The downgrade refuses to run while OPENSOURCE data exists.
- ruff, ruff format, mypy (only the pre-existing `seed/bootstrap.py:135` error remains) and
  import-linter (contract kept) are clean for the changed code.
- Not run: Docker image build, a real browser/mobile capture, staging, any load test beyond the
  single-process measurements in the evaluation document.


---

# Second pass - final readiness verification (2026-10-25)

Status words: **PASS** directly verified with recorded evidence; **FAIL** reproducible defect;
**BLOCKED** needs approval/data/access/legal decision; **NOT RUN** not performed; **INSUFFICIENT
EVIDENCE** ran, but cannot support the conclusion. Source inspection alone is never PASS for a
runtime property.

## 10. Model licence and commercial-use review

Sources read on 2026-10-25 (re-check before relying on them; licences and README text change).

| Item | Verified facts | Source |
|---|---|---|
| OpenCV Zoo repo | Licensed Apache-2.0; its README says "Please refer to licenses of different models". The Zoo's per-model LICENSE files are what apply to each file. | `opencv/opencv_zoo` `README.md` (License section), `LICENSE` |
| **YuNet** `face_detection_yunet_2023mar.onnx` (SHA-256 `8f2383e4...`, 232,589 B) | Zoo per-model LICENSE: **MIT**, (c) 2020 Shiqi Yu. Zoo README: model source is `ShiqiYu/libfacedetection.train` commit `a61a428929148171b488f024b5d6774f93cdbc13`, `onnx/yunet.onnx`; added to the Zoo 2023-06-06. At that commit the training repo's LICENSE is **MIT** (copyright Max deGroot/Ellis Brown 2017, Zisian Wong/Shifeng Zhang 2019, Shiqi Yu 2020) while its README badge says "BSD"; today GitHub reports the repo as **BSD-3-Clause**. The inference library `ShiqiYu/libfacedetection` has a custom BSD-style licence (GitHub: NOASSERTION). | `opencv_zoo/models/face_detection_yunet/{LICENSE,README.md}`; `libfacedetection.train` LICENSE @a61a428 and GitHub licence API |
| YuNet training data | README: trained on **WIDER Face**. The official WIDER FACE page lists its licence as **CC BY-NC-ND**. | `libfacedetection.train` README; `shuoyang1213.me/WIDERFACE/` |
| **SFace** `face_recognition_sface_2021dec.onnx` (SHA-256 `0ba9fbfa...`, 38,696,353 B) | Zoo per-model LICENSE: **Apache-2.0**. Zoo README: "MobileFaceNet instances trained on the SFace loss function", converted from `zhongyy/SFace` by a third party. The upstream code repository `zhongyy/SFace` has **no licence file** (GitHub licence: null). The paper reports training on CASIA-WebFace, VGGFace2 and MS-Celeb-1M; **which dataset produced this published file is not stated** by the Zoo. | `opencv_zoo/models/face_recognition_sface/{LICENSE,README.md}`; GitHub API `repos/zhongyy/SFace`; its README |
| Loader/wrapper | OpenCV (`opencv-python-headless`) is Apache-2.0 (code only). It says nothing about the weights it loads. Our own loader code is the repository's. | - |
| MiniFASNet (liveness, pre-existing) | Apache-2.0 upstream (see its `LICENSE.upstream` / README in the repo). Not re-reviewed in this pass. | `models/liveness/minifasnet-v1/` |
| InsightFace pretrained models (considered, rejected) | Code MIT; pretrained models "for non-commercial research purposes only"; commercial licensing by contacting the vendor. | `deepinsight/insightface` README, `python-package/README.md` |

Obligations if the files are shipped (Apache-2.0 s.4: include licence copy and notices, state
changes; MIT/BSD: keep copyright + licence text): the repository now carries both licence texts and a
NOTICE beside the model directory (`apps/api/models/face/opensource-v1/{LICENSES/,NOTICE.md}`,
not git-ignored, not excluded from the build context, so `COPY models` ships them; **shipping in a
built image was not re-verified after adding them** - the images above predate the files). No modification of the weights is
made; they are used unmodified, so there is no "state changes" duty beyond the above.

**Unresolved legal interpretation (not decided here):** whether a permissive licence on a model file
is sufficient when the model was trained on data distributed for non-commercial / research use
(WIDER Face for YuNet; unspecified research datasets for SFace). Absence of a licence on the SFace
upstream repository is not permission. Evidence is **insufficient for a legal conclusion** on either.

**Status: YuNet - BLOCKED FOR COMMERCIAL PRODUCTION. SFace - BLOCKED FOR COMMERCIAL PRODUCTION.**
Use for development, evaluation and (with counsel's agreement) internal non-commercial pilots only.

**Recommendation requiring counsel's approval:** (a) obtain a written position on both models; or
(b) if refused, select a replacement. Candidates, honestly graded: *InsightFace* models - rights
holder offers commercial licences by contact (verified in its README), terms unknown; *keep Face++*
as the commercial engine (already integrated; vendor terms separate); other open face-recognition
weights - **not assessed in this session**, and most public ones were trained on research-only
datasets, so each needs its own review. No replacement was downloaded or integrated. Migration
impact of any replacement: new `MODEL_VERSION` and pinned digests in `assets.py`; a different
embedding size would need `EMBEDDING_DIM` (and tests) changed (the column is free-form encrypted
text, so no schema change); thresholds and the evaluation must be redone; **every enrolled employee
re-enrolls** (embeddings of different versions are never compared - tested); old rows are removed by
revocation/outbox.

## 11. Encryption, tenant isolation and key lifecycle

| Check | Result | Evidence |
|---|---|---|
| Encrypted before persistence, decrypted only for 1:1 comparison | PASS | stored value is a `v1:` envelope (integration test); `DbEmbeddingStore.load` is the only decrypt site (grep) |
| Algorithm/mode | PASS (design) | AES-256-GCM via `cryptography`; format `core/crypto/field.py` |
| Nonce per value | PASS | `os.urandom(12)` per encryption; unit test shows two encryptions of the same value differ |
| Integrity tag verified; tamper fails closed | PASS | `InvalidTag` -> `DecryptionFailedError`; flipping owner/person/sample/model/column/row fails (unit test, 6 variants); DB-level tamper and ciphertext swap -> `FaceProviderError`, never a match (integration test) |
| Keys not stored with data | PASS (design) | DEK is wrapped in `encryption_keys` under SHA-256(`PII_MASTER_KEY`) (env secret); embeddings table holds only ciphertext. Note the wrapped DEK is in the same database as the ciphertext; only the master secret is outside it |
| Key material in logs/metrics/responses | PASS (limited) | no key/embedding in the engine's log fields or the profile schema (tests assert absence in the profile responses and attempt evidence); a full log grep on staging is NOT RUN (checklist D1) |
| **Tenant-specific key** | **FAIL vs. earlier documentation** | one environment-wide DEK, not per tenant. The first-pass architecture/setup text said "tenant data key" - **wrong, corrected**. Separation is RLS + 1:1 flow + binding, not cryptographic. |
| Ownership columns authenticated | **was FAIL, fixed** | AAD bound only `table:column:row id`; an UPDATE of `employee_id`/`person_ref` would silently re-assign a template. AAD record id is now `uuid5(row, company, employee, person_ref, sample_index, model_version)`. No migration or data change needed (no rows exist in any real environment; the engine was never enabled). |
| Tenant identity derived server-side | PASS | engine takes the company from the profile row / request tenant context (set from the verified membership), never a caller-supplied id; mismatching person-id company -> error (unit + integration tests) |
| RLS under the real runtime role | PASS | `hrms_app` connection: owner sees 5 rows, other tenant 0, cross-tenant filter 0 (integration test); policy ENABLE+FORCE |
| Migrations/tests do not over-grant | PASS (inspection + run) | migration only creates the table + policy (grants follow existing default privileges); full suite incl. `tests/security` 407 passed |
| Wrong tenant / invalid ciphertext / decrypt errors fail closed | PASS | as above |
| Backup/restore, key loss | DOCUMENTED, NOT RUN | setup doc 6a; staging checklist D2 |
| Key rotation | **PARTIAL / limitation** | `rotate_key` adds a DEK version for new writes; old versions remain decryptable; **no re-encryption sweep exists for `face_embedding`**; remediation (modelled on `pii_backfill`) documented, not built - needed only when a rotation is scheduled |
| Weak points noted | - | master secret is hashed once with SHA-256 (no KDF) - fine for a random 32-byte secret, not for a passphrase; `ENVIRONMENT=development` uses a deterministic dev key |

## 12. Gate matrix

| Gate | Status | Evidence | Owner / approval | Next action |
|---|---|---|---|---|
| Default stays `disabled`; Face++ needs explicit selection + credentials | PASS | start-up tests + in-image boot | - | - |
| Open-source needs `FACE_OS_ENABLED` + model dir; never auto-enabled | PASS | tests; in-image boot | - | - |
| Clean-copy asset provisioning with pinned hashes | PASS | section 14 | - | mirror files to a private store for releases |
| Default image excludes assets (even if present locally) | PASS (was FAIL, fixed) | section 14 | - | - |
| Image with assets: files, hashes, non-root, boots/embeds offline | PASS | section 14 | - | rebuild in release pipeline; record digest (B4) |
| Tampered/missing/invalid assets and config refuse to boot | PASS | tests + in-image | - | - |
| No fallback between engines | PASS | tests: outage -> `FACE_PROVIDER_FAILED`; mismatch -> `FACE_NOT_ENROLLED`, neither engine called | - | - |
| Models never downloaded at startup/request | PASS | start-up tests with sockets/urlopen fatal; in-image `--network none` | - | - |
| Model dir read-only at runtime | FAIL (hardening H-1) | runtime user can write `/app/models/...` (whole `/app` is chowned) | platform owner | make models root-owned/read-only in the image or mount `:ro` (also covers liveness assets) |
| Encrypted storage, tamper-proof ownership, RLS | PASS | section 11 | - | - |
| Per-tenant keys | FAIL (as documented) / design decision | environment-wide DEK | security owner | accept + document, or request per-tenant DEKs (broad redesign - not done) |
| Key rotation of embeddings | INSUFFICIENT EVIDENCE | limitation documented | security owner | build re-encrypt job when rotating |
| Re-enrollment visibility | PASS (was FAIL, fixed) | `requires_reenrollment` flag, tests | - | UI to show it (mobile/web not changed) |
| Revoke/deletion routing, retry, idempotency (OPENSOURCE) | PASS | integration tests | - | staging smoke (C6) |
| Provider outage not counted as identity failure | PASS | integration test (6 outage punches, then success) | - | - |
| Concurrency bounded; no executor starvation; slot release | PASS (was FAIL, fixed) | unit tests + benchmark | - | target-CPU load test (E2) |
| Capacity for a stated employee count | INSUFFICIENT EVIDENCE | one host, synthetic input | operator | staging load test |
| Evaluation tool reproducible + aggregate-only | PASS (improved) | tests | - | - |
| Recognition accuracy / threshold | INSUFFICIENT EVIDENCE | no dataset | evaluator + data owner | evaluation doc section 4 |
| Liveness attack resistance (print/replay/video) | INSUFFICIENT EVIDENCE | no attack data | evaluator | same |
| Demographic performance | INSUFFICIENT EVIDENCE | no lawful data | counsel + evaluator | same |
| Model licences (YuNet, SFace) | BLOCKED | section 10 | counsel | written decision or replacement |
| Licence texts/NOTICE beside the models | PASS (repo) / NOT RUN (image) | files added; images predate them | release owner | confirm in the release image; legal review of attribution wording |
| Live staging checks | NOT RUN | checklist | operator | checklist B4-E7 |
| Consent/DPIA for local template storage | NOT RUN | - | data-protection owner | before pilot |

## 13. Commands run and results

New in this pass unless marked "carried". Host: Linux 6.8, Python 3.12.12, OpenCV 4.14.0, NumPy 2.5, Docker 29.1.3,
Postgres 16 (dev container, disposable `hrms_test` created and dropped), Redis /1.

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests/unit -q` | exit 0, **1315 passed** |
| `python run_full_tests.py`-style isolated DB: `pytest tests/integration/modules/attendance tests/security` | exit 0, **407 passed** (204 s) |
| `pytest .../test_face_opensource_engine.py` | 10 passed (6 from the first pass + 4 new: ownership tamper, re-enrollment flag, failed enrollment leaves nothing, revoke idempotency + deletion retry) |
| `pytest tests/unit/modules/attendance/test_opensource_face_startup.py` | 6 passed (real lifespan, sockets fatal) |
| `ruff check src tests scripts` ; `ruff format --check` | clean (5 pre-existing E501 in old unmodified migrations remain under `ruff check .`) |
| `mypy src/hrms` | 1 error, pre-existing `seed/bootstrap.py:135` |
| import-linter | 1 contract kept, 0 broken |
| Migration `20261022090000` upgrade/downgrade x2 | carried forward from the first pass (migration file unchanged except a docstring word) |
| Real Face++ calls / real employees / real biometrics | none |

## 14. Docker and clean-checkout asset verification

- **Method.** Because the repository has uncommitted/untracked work, a "clean checkout" cannot come from git; an isolated copy of `apps/api` (no `.venv`, no `.env`, no logs) was used. First copy excluded local `.onnx` files; second copy deliberately **included** the developer's local face `.onnx` files to test the build context rule.
- **Defect found and fixed (FAIL -> PASS).** `COPY models ./models` ran in every build and nothing excluded the git-ignored face weights, so a local copy would have been baked into the *default* image. `apps/api/.dockerignore` now excludes `models/face/**/*.onnx`/`*.part`. Proven with a throwaway context (face `.onnx` dropped, committed liveness `.onnx` kept) and in the second real build (default image contains only the liveness `.onnx`).
- **Provisioning.** `scripts/face/fetch_opensource_assets.py` fetched both files in the build; SHA-256 equal to the pins (`8f2383e4...`, `0ba9fbfa...`).
- **Images.** default `hrms-api-facecheck:default2` id `sha256:79cd5788b83d...`; assets `hrms-api-facecheck:os2` id `sha256:1ef1309cef99...` (both local, disposable, built from the working tree on this date; ~36 MB larger with assets). Build exit 0 for both.
- **Final-image runtime checks** (container, `--network none`, user uid 1000 `hrms`): files present and owned by `hrms`, hashes match; defaults `disabled` / `FACE_OS_ENABLED=false` / liveness `disabled`; boot OK with default env; boot OK with `opensource`+valid assets; tampered copy -> `EmbeddingUnavailableError ... failed verification`; missing flag / wrong dir refuse to boot; `embed()` returns `OK`. Cold start import 0.56 s, model load 0.25 s, first embedding 50 ms, warm p50 17.5 ms.
- **What the build arg controls**: model *inclusion* only, never runtime activation (setup doc 3).
- **Not verified**: a build in the project's CI/release pipeline, image digest from a registry, behaviour under the production compose file, Nginx/TLS path.
- Built images and test DB were created by this task and are removed after the run.
