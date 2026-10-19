# Face Attendance — Liveness / Anti-Spoofing Implementation Report

Date: 2026-10-15. Scope: replace the placeholder face "liveness" with genuine presentation-attack
detection (PAD) that the server, not the phone, decides; no paid liveness API.

> **Status: locally implemented and tested; NOT production-ready.** Face punching with
> server-side liveness is ready for **controlled staging evaluation** only. Production stays off
> (`FACE_LIVENESS_ENGINE=disabled`, the default). The model has not been calibrated on real
> devices or real attacks. A green test suite here proves the plumbing and the decision rules,
> not the model's accuracy against attacks.

---

## 1. Executive summary

- The old `FaceppFaceVerificationProvider.check_liveness` answered `LIVE` for any image in which
  Face++ detected a face (FINDING-005 in `COMPLETE_CODEBASE_FORENSIC_REVIEW.md`). It is
  **removed**. Nothing in the active path treats face detection as liveness any more.
- **Selected model:** Silent-Face-Anti-Spoofing (Minivision, Apache-2.0). It fuses two
  MiniFASNet models with the upstream RetinaFace detector. The pretrained weights come from the
  original repository at a pinned commit and are checked by SHA-256. They are exported to ONNX
  reproducibly and run on **our own API server** with OpenCV DNN (no PyTorch at runtime).
- **Trust boundary:** the server decides. Each punch works like this:
  1. The server issues a short-lived, single-use **challenge** bound to the employee, the tenant
     and the punch direction.
  2. The app captures N frames (default 3) after the challenge is issued and uploads them with it.
  3. The server burns the challenge, rejects byte-identical replayed frames, and runs the model
     on **every** frame.
  4. Face++ then matches identity on the best frame — bytes that themselves passed liveness in
     the same request.
  5. Only then does the existing idempotent punch path write a `FACE` punch.
- The app never sends a liveness verdict, and the server ignores any it is sent (tested).
  On-device ML Kit is used only as a **capture-quality gate**: one face, close enough, facing the
  camera, eyes open.
- **Fails closed.** If the liveness engine is disabled, missing, fails its checksum, times out,
  or returns a malformed or ambiguous result, no punch is recorded. There is no fallback to the
  placeholder.
- **No recurring cost:** inference is local (≈ 7 ms per frame warm on the dev CPU, §12), and
  Face++ usage per punch was originally described here as one `detect` + one `search`. **That is no longer true** (superseded by the security-hardening report, Part B2): every submitted frame is now identity-checked, so a default 3-frame punch makes 3 `detect` + 3 `search` requests, and an enrollment about 18. Size quota and cost on that basis.
- **Tests:**
  - Backend unit: 1087 pass, including 42 new liveness tests, some of which load the real verified model.
  - Backend face integration: 122 pass, against the local Docker DB/Redis with mocked Face++ and
    a fake engine that runs the production decision rules.
  - Full backend suite: 2774 passed, 0 failed.
  - Flutter: 503 pass, 1 skipped.
- **Real-model evaluation so far:** only the 3 upstream sample images (2 spoof, 1 genuine), all
  classified correctly. This is a smoke check, **not** an accuracy claim (§13).

## 2. Starting branch and HEAD

- Branch `main`, HEAD `d0c55f4ed3f87941cbefed57544313bf348d0ab9`
  ("chore(ops): monitoring script, runbooks, audit reports, and mobile CI job").

## 3. Initial working-tree state

`git status --short` was empty: no staged, unstaged or untracked changes. No pre-existing user
changes needed preserving.

Local services seen: Docker `hrms-postgres` (localhost:5433, `hrms_dev`), `hrms-redis`
(localhost:6380) and `hrms-minio`. All integration tests and migrations in this work ran only
against these local containers.

## 4. Selected model and why

### Candidates evaluated

| Candidate | Real anti-spoof inference? | Weights & source | Licence | Runs where | Verdict |
| --- | --- | --- | --- | --- | --- |
| **Silent-Face-Anti-Spoofing / MiniFASNet** (minivision-ai) | Yes. A 3-class real/spoof classifier with an auxiliary Fourier-spectrum branch during training. Verified by running it: upstream sample spoofs → class 2, genuine → class 1 at 0.9936. | Pretrained `.pth` in the original GitHub repo (commit `b6d5f04`, 2020). Hashes pinned. | Apache-2.0 (repo licence covers code and weights; training data undisclosed, see §5) | Server CPU via OpenCV DNN (exported ONNX, ~1.7 MB each); also deployable on-device (upstream ships an Android APK demo) | **Selected.** Reproducible, small, permissive licence, server-runnable without torch. |
| DeepFace `anti_spoofing` | Yes, but it **is** MiniFASNet (wraps the same Minivision weights) | Weights downloaded at runtime from the DeepFace GitHub releases | MIT wrapper + Apache weights | Server (pulls TensorFlow/torch stack) | Rejected: same model with a much heavier dependency tree and a runtime download. |
| Community MiniFASNet retrains (e.g. CelebA-Spoof-trained ONNX repos) | Yes | Third-party GitHub repos | Repo code Apache/MIT, but **CelebA-Spoof is licensed for non-commercial research only** and restricts derived data | Server/device | Rejected: licence risk for a commercial HRMS; unvetted provenance. |
| pub.dev `passive_liveness` (0.1.x), `flutter_face_liveness`, `flutter_biometric_liveness` (1.0.x), `human_security` (0.2.x), `face_guard_liveness` (1.0.0), `trueface_liveness` | Mixed: some bundle a MiniFAS-style TFLite model, some are ML Kit challenge wrappers or texture heuristics, one has only a "bring your own model" slot, one auto-downloads models at runtime | Bundled or runtime-downloaded, provenance mostly undocumented | Varies; model licence usually unstated | Device only | Rejected: early versions, weak maintenance signals, unverifiable model provenance, and client-only (cannot be the authority, §6). |
| Face++ "FaceID" liveness | Yes (active, SDK-based) | Vendor | Paid, separate product | Vendor cloud + SDK | Out of scope: a paid liveness API is explicitly excluded. |
| Training a new model | — | — | — | — | Out of scope by instruction. |

### Answers to the §4 evaluation questions (selected model)

1. **Real anti-spoofing inference?** Yes: a learned real-vs-spoof classifier, not face detection.
2. **Trustworthy weights?** From the original authors' repository at a pinned commit. Each file's
   SHA-256 is pinned in the build script and again for the derived ONNX assets in the API.
3. **Commercial use?** The repository licence is Apache-2.0, which permits commercial use. The
   training-data caveat is in §5.
4. **Android/iOS?** Not needed for the authoritative path: the model runs on the server.
   Upstream reports 19–25 ms on mid-range Android SoCs, so on-device inference is feasible later
   as a UX pre-check.
5. **Flutter compatibility?** Unaffected. No new Flutter dependency; the existing `camera` and
   `google_mlkit_face_detection` packages are reused.
6. **Known limitations?** Upstream says robustness depends on camera model and scene, that it
   expects camera-captured frames with head rotation under 30°, and that its open-source model is
   the lighter one (it publishes 97.8% TPR at FPR 1e-5 for the open APK model on its own data, not
   an independent benchmark). Not robust by design to 3D masks, high-quality replays on large
   high-DPI screens, or injected camera streams (§13).
7. **Active, temporal or single-frame?** Passive, single-frame. This implementation applies it to
   every one of N frames and requires all to be LIVE. That is **not** active liveness and is not
   described as such.
8. **Server feasibility?** Yes. Two models of ~0.08 GFLOPs plus a small detector take ≈ 7 ms per
   frame on the dev CPU with 2 OpenCV threads, and resident memory grows by tens of MB (§12).
9. **Packaged and tested without a paid API?** Yes. One optional dependency
   (`opencv-python-headless`, Apache-2.0) plus 5.4 MB of verified assets.

## 5. Licence, source and provenance findings

- Upstream repository: <https://github.com/minivision-ai/Silent-Face-Anti-Spoofing>, commit
  `b6d5f04ad78778917853b25c778acef6d5626d15` (last commit 2020-08-05; the project is **not
  actively maintained**, so we pin it and own the conversion).
- Licence: Apache License 2.0 (`LICENSE` sha256 `daf94bf1dc9cc5700fe5af2c7c0cbd1836e70d509ed78fd0bebef7432edee6fb`), copied as
  `models/liveness/minifasnet-v1/LICENSE.upstream` along with an attribution notice in the
  assets README.
- Upstream file hashes (verified on download and against a clone):

  | Upstream file | SHA-256 |
  | --- | --- |
  | `resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth` | `a5eb02e1843f19b5386b953cc4c9f011c3f985d0ee2bb9819eea9a142099bec0` |
  | `resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth` | `84ee1d37d96894d5e82de5a57df044ef80a58be2b218b5ed7cdfd875ec2f5990` |
  | `resources/detection_model/deploy.prototxt` | `9fe2f141b4baee039ed9442da2833e216af40a6ff3e639e7b39258812bcda808` |
  | `resources/detection_model/Widerface-RetinaFace.caffemodel` | `d08338a2c207df16a9c566f767fea67fb43ba6fff76ce11e938fe3fabefb9402` |
  | `src/model_lib/MiniFASNet.py` (architecture, reviewed: plain PyTorch layers) | `e498c4ec5e1ddfaba62b941a126c19d65aa564999f3309661fe43ee8bf38acd7` |

- Deployed asset hashes (pinned in `liveness.py`, `_PINNED_SHA256`):

  | Asset | SHA-256 |
  | --- | --- |
  | `minifasnet_v2_scale2.7_80x80.onnx` | `079399882d651cb9126de6444ca0fabce952db7d5792823ef6c4ae004132534f` |
  | `minifasnet_v1se_scale4.0_80x80.onnx` | `828e4476ac4561c9185c092d173105f30c51f814d93fd71a892c1b67b41e5dd9` |
  | `retinaface_deploy.prototxt` | `9fe2f141b4baee039ed9442da2833e216af40a6ff3e639e7b39258812bcda808` (byte-identical to upstream) |
  | `retinaface_widerface.caffemodel` | `d08338a2c207df16a9c566f767fea67fb43ba6fff76ce11e938fe3fabefb9402` (byte-identical to upstream) |

- Conversion: `scripts/liveness/build_minifasnet_assets.py`, run with torch 2.5.1+cpu, onnx
  1.17.0, Python 3.12 in a throwaway scratch venv (not an application dependency). Checkpoints
  are loaded with `torch.load(..., weights_only=True)`, so no pickle code runs. ONNX opset 13
  with a fixed 1×3×80×80 input. Parity was checked on random inputs and on the upstream samples
  across PyTorch, onnxruntime and OpenCV DNN (max logit difference < 1e-4; identical
  probabilities to 4 dp). **The export is byte-reproducible**: two independent builds, one from
  the download and one from a clone, produced identical hashes.
- **Open legal question (needs a decision, not code):** the upstream README does not disclose the
  training data. Apache-2.0 covers the published code and weights, but the terms of whatever
  data trained them are unknown. Before production use, legal should confirm they are content
  with that (or ask Minivision). The community retrains on CelebA-Spoof were rejected precisely
  because that dataset is non-commercial.
- Dependency added: `opencv-python-headless` 4.14.0.94 (Apache-2.0, OpenCV team, released
  2026-07-28) under a new **optional** extra `liveness`. It pulls numpy, which is locked at 2.5.2
  (BSD-3, released 2026-08-09). The lock was deliberately moved off numpy 2.5.4 because that
  release was only 5 days old. Nothing else in `uv.lock` changed.

## 6. Architecture and trust-boundary decisions

```
Phone (untrusted)                        API server (decides)                       Face++
─────────────────                        ────────────────────                       ──────
tap "Face punch in"
  POST …/face-punches/me/liveness-sessions {direction}
                                         authn + ATTENDANCE.PUNCH + linked employee
                                         attempt limit, issuance limit, ENROLLED?
                                         supersede old ISSUED; insert ISSUED (TTL 120 s)
  ◄── {session_id, expires_at, frames_required=3}
camera + ML Kit quality gate (not liveness)
take 3 photos, delete temp files
  POST …/face-punches/me  multipart: direction, liveness_session_id, idempotency_key, frames×3
                                         size/count/format checks, distinct frames
                                         idempotency replay? → original result (advisory lock)
                                         attempt limit
                                         BURN session (own committed txn): exists for THIS
                                           employee+tenant? ISSUED? unexpired? same direction?
                                         frame SHA-256 seen in an earlier session? → replay
                                         profile ENROLLED?
                                         MiniFASNet on EVERY frame (thread, timeout, lock)
                                           all LIVE? else SPOOF/INCONCLUSIVE/ERROR → reject
                                         best live frame ───────────────────────────► detect+search
                                                                           ◄──────── confidence
                                         MATCHED ≥ 0.90? → punch (existing idempotent path)
                                           + MATCHED attempt row, same transaction
  ◄── 201 {punch, similarity, liveness_score}
```

**What the server can verify:**

- The caller is authenticated, holds `ATTENDANCE.PUNCH`, and is linked to an employee.
- The challenge was issued by this server to this employee in this tenant, for this direction.
- The challenge is unexpired and has never been presented before, enforced by an atomic burn
  committed in its own transaction.
- No frame is byte-identical to a frame from an earlier challenge of this employee, or to
  another frame in the same request.
- Every frame passes our own model.
- The identity frame is one of those frames.
- Identity matches the enrolled Face++ FaceSet at the existing threshold.
- The punch is written exactly once per idempotency key.

**What it cannot verify (documented limits, no cryptographic claim):**

- That the frames came from the phone's physical camera, or when they were captured. A
  modified app or a virtual camera can submit any images within the 120 s window.
- That a pre-recorded or re-encoded (not byte-identical) capture is fresh. Digest replay
  protection only catches exact reuse.
- That the app is genuine. There is no device attestation (Play Integrity / App Attest) in this
  phase.

Because of these limits, the model is the barrier for a modified client. The challenge reduces
replay and pre-staging but does not prove capture freshness.

**Not done, deliberately:**

- On-device MiniFASNet. A client score cannot be trusted and would add a TFLite runtime and
  model to the app. ML Kit is used only to gate capture quality, and its output is never sent.
- An active challenge (head turn, blink) verified server-side. We have no server-side
  pose/landmark model, and Face++ head-pose attributes would add extra calls and cost per punch.

**Enrollment:** the straight-on enrollment capture must also pass the server model before
anything is sent to Face++. Enrollment has no challenge session. It remains protected by the
HR-opened one-time window and HR's manual review of the photo.

## 7. Files changed and why

**Backend — new**
- `src/hrms/modules/attendance/liveness.py` — `LivenessEngine` protocol and the
  `MiniFasNetLivenessEngine` (OpenCV DNN). It contains:
  - checksum-pinned loading;
  - preprocessing faithful to upstream;
  - score interpretation;
  - per-frame and aggregate decisions;
  - header-based dimension checks (decompression-bomb guard);
  - a thread lock plus a deadline, and a timeout;
  - typed errors and a per-configuration engine cache.
- `alembic/versions/20261015090000_face_liveness_session.py`:
  - adds the `face_liveness_session` table (RLS forced, one-ISSUED-per-employee partial unique
    index, GIN index on `frame_digests`);
  - adds `face_verification_attempt.liveness_session_id`;
  - widens the attempt decision check;
  - downgrade keeps audit rows by remapping the new decisions to `LIVENESS_FAILED`.
- `models/liveness/minifasnet-v1/` — the 4 verified assets, `MANIFEST.json`, `LICENSE.upstream`
  and a provenance `README.md`.
- `scripts/liveness/build_minifasnet_assets.py` — reproducible, hash-verified download and
  conversion.
- `tests/unit/modules/attendance/test_liveness.py` — 42 tests, including the real model.
- `tests/integration/modules/attendance/test_face_liveness_session.py` — 19 challenge tests (23 parametrised cases).

**Backend — modified**
- `face_verification.py` — removed `check_liveness`, `LivenessResult` and `LivenessDecision`;
  the docstring now says Face++ does identity only.
- `face_service.py`:
  - enrollment calls the engine;
  - `FacePunchService` gains `issue_liveness_session`, a new `punch_self` pipeline and
    `_consume_session`;
  - new helpers `assess_liveness` / `liveness_rejection`;
  - `sniff_face_image` gains a per-call byte cap;
  - attempts record `liveness_session_id`.
- `router.py` — new `POST /attendance/face-punches/me/liveness-sessions`. The punch route now
  takes `frames[]` and `liveness_session_id` (`photo` is no longer read) and caps the frame count
  before reading anything.
- `dependencies.py` — `get_face_liveness_engine`, injected into both face services.
- `models.py`, `repository.py`, `schemas.py`, `exceptions.py` — session ORM model and
  repository, request/response schemas and limits, and the new stable error codes (§8).
- `core/config/settings.py` — `FACE_LIVENESS_*` settings and boot guards (model dir required
  when enabled; live + spoof thresholds must exceed 1).
- `app.py` — face-punch upload ceiling expressed as frames × per-frame cap + 1 MB (6 MB, the
  same value as before).
- `pyproject.toml`, `uv.lock` — optional `liveness` extra.
- `.env.example` — documented, disabled settings.
- Tests:
  - `conftest.py` — `FakeLivenessEngine` using the production `classify_frame`/`aggregate`; the
    fake provider records the verified image.
  - `test_face_punch.py`, `test_face_punch_idempotency.py`, `test_face_enrollment.py` — moved to
    the challenge + frames flow, with new liveness cases.
  - `test_face_verification.py` — placeholder tests replaced by "adapter has no
    `check_liveness`".

**Mobile — new**
- `domain/face_liveness_capture.dart` — the quality gate (explicitly not liveness), challenge
  expiry check and capture outcome types.
- `presentation/face_liveness_capture_screen.dart` — guided capture of N frames for one
  challenge. It handles permission denial, a missing camera or unsupported device, app
  backgrounding, challenge expiry and cancel, and uses a live-region hint.
- `presentation/camera_input_image.dart` — the camera → ML Kit conversion, extracted from the
  enrollment screen and shared, plus `readAndDeleteCapture` (reads a photo, then deletes the
  camera temp file).
- `test/face_liveness_capture_test.dart`.

**Mobile — modified**
- `data/attendance_repository.dart` — `FaceLivenessSession`, `startFaceLivenessSession`, the new
  `facePunchMe` (session + frames + required key) and `facePunchOutcomeUnknown`.
- `presentation/face_punch_card.dart` — challenge → capture → verify state machine. It allows
  one attempt at a time, keeps the key across unknown outcomes (including proxy 502/503/504
  without the API envelope — previously only status 0), offers no override, and clears frames
  after each attempt. `image_picker` is no longer used here.
- `presentation/face_enrollment_screen.dart` — uses the shared conversion helper and deletes each
  capture's temp file after reading it.
- `test/face_punch_card_test.dart`, `test/core/punch_idempotency_test.dart`.

**Docs**
- This report.
- `docs/operations/STAGING_VALIDATION_CHECKLIST.md` — new B-21 calibration gate; B-20 now names
  the new migration.

## 8. Backend and Flutter implementation details

### API contract

`POST /v1/attendance/face-punches/me/liveness-sessions` — JSON `{"direction": "IN"|"OUT"}` →
`201 {"data": {"session_id", "direction", "expires_at", "frames_required"}}`.

`POST /v1/attendance/face-punches/me` — multipart:
- `direction`;
- `liveness_session_id`;
- `frames` × `frames_required` (JPEG/PNG, ≤ 1 MB each, 240–4096 px per side);
- optional `idempotency_key`.

Any other field (for example `is_live`, `liveness_score`) is ignored. Success is
`201 {"data": {"punch", "similarity", "liveness_score"}}`. `liveness_score` is the weakest
frame's P(real), with 4 decimals both fresh and on replay.

| Outcome | HTTP | `error.code` | Punch? | Attempt row |
| --- | --- | --- | --- | --- |
| Success | 201 | — | yes | `MATCHED` (+ session id, per-frame scores) |
| Idempotent retry (same key, any new challenge) | 201 | — (original result) | no new one | none |
| Suspected spoof (any frame) | 422 | `FACE_SPOOF_SUSPECTED` | no | `SPOOF_SUSPECTED` |
| Inconclusive (low confidence / face too small) | 422 | `FACE_LIVENESS_INCONCLUSIVE` | no | `LIVENESS_INCONCLUSIVE` |
| Multiple faces | 422 | `FACE_MULTIPLE_FACES` | no | `LIVENESS_INCONCLUSIVE` |
| No face (model or Face++) | 422 | `FACE_NOT_DETECTED` | no | `NO_FACE` |
| Face mismatch | 422 | `FACE_NOT_MATCHED` | no | `NO_MATCH` |
| Missing challenge / outdated app (`photo`) | 422 | `FACE_LIVENESS_CHALLENGE_REQUIRED` | no | none |
| Unknown / other employee's / other tenant's / superseded / wrong-direction challenge | 422 | `FACE_LIVENESS_CHALLENGE_INVALID` | no | `CHALLENGE_REJECTED` |
| Expired challenge | 409 | `FACE_LIVENESS_CHALLENGE_EXPIRED` | no | `CHALLENGE_REJECTED` |
| Reused challenge | 409 | `FACE_LIVENESS_CHALLENGE_USED` | no | `CHALLENGE_REJECTED` |
| Replayed / duplicate frames | 422 | `FACE_CAPTURE_REPLAYED` | no | `CAPTURE_REPLAYED` (cross-session) |
| Invalid capture (count, size, format, dimensions, undecodable) | 422 | `FACE_IMAGE_INVALID` (`field: frames`) | no | `LIVENESS_INCONCLUSIVE` if found by the model |
| Liveness engine timeout | 503 | `FACE_LIVENESS_TIMEOUT` | no | `LIVENESS_ERROR` |
| Model disabled / missing / failed checksum | 503 | `FACE_LIVENESS_UNAVAILABLE` | no | `LIVENESS_ERROR` (if reached) |
| Face++ timeout / error | 502 | `FACE_PROVIDER_FAILED` | no | `PROVIDER_ERROR` |
| Face provider disabled | 503 | `FACE_VERIFICATION_UNAVAILABLE` | no | none |
| Not enrolled | 409 | `FACE_NOT_ENROLLED` | no | `NOT_ENROLLED` (if after challenge) |
| Unauthorised (no permission) | 403 | `PERMISSION_DENIED` | no | none |
| Too many failures / challenges | 429 | `FACE_ATTEMPTS_EXCEEDED` | no | — |
| Same key, other direction / employee | 409 | `DUPLICATE_PUNCH_IDEMPOTENCY_KEY` | no | none |

Error responses never carry model scores or provider bodies. Scores stay in the server-side
attempt row.

### Decision rules

Per frame, the two models' softmax outputs are averaged into fused probabilities. Then:

- `live` = P(class 1);
- `spoof` = P(class 0) + P(class 2);
- `live ≥ 0.90` → **LIVE**;
- else `spoof ≥ 0.50` → **SPOOF_SUSPECTED**;
- else → **INCONCLUSIVE** (`LOW_CONFIDENCE`).

Quality outcomes are INCONCLUSIVE with a reason:
- no confident detection (detector confidence ≥ 0.6, upstream's value) → `NO_FACE`;
- more than one confident detection → `MULTIPLE_FACES`;
- face shorter than 80 px → `FACE_TOO_SMALL`.

Across frames, any SPOOF wins, otherwise any non-LIVE frame makes the capture INCONCLUSIVE,
and only all-LIVE passes. Malformed model output (wrong length, NaN, probabilities not summing
to 1) is an **error**, never a verdict.

### Resource bounds

- Each frame is ≤ 1 MB, and the route rejects more than 5 frames before reading them.
- The middleware caps the request at 6 MB.
- JPEG/PNG dimensions are read from the header **before** decoding and must be 240–4096 px per
  side. OpenCV's `OPENCV_IO_MAX_IMAGE_PIXELS` is also capped.
- Inference runs off the event loop (`asyncio.to_thread`) under `asyncio.wait_for` with a 10 s
  default. A per-engine lock serialises access to the non-thread-safe `cv2.dnn.Net`, and a
  waiter gives up at its deadline instead of queueing. OpenCV uses 2 threads.

### Rate and abuse limits

All limits follow existing conventions (DB-backed, per employee):
- The existing failed-attempt limit (5 in 10 min) also gates challenge issuance. Challenge,
  replay and liveness failures count towards it.
- At most 20 challenges per employee per 10-minute window.
- At most one ISSUED challenge per employee.

### Idempotency

The existing `face:<key>` namespace, transaction advisory lock and unique index are unchanged.
The replay check runs **before** the challenge is burned, so a retry with the same key returns
the original punch even though it carries a new challenge. Concurrent submissions of one
challenge (with or without a key) yield exactly one punch (tested). A rejected or failed attempt
still leaves its key reusable.

### Flutter flow

1. **Challenge:** the card requests a challenge. Errors such as not-enrolled or unavailable are
   shown, and the camera is never opened.
2. **Capture:** a full-screen capture screen opens the front camera at `medium` (480p) and runs
   ML Kit with classification. It waits for 3 consecutive good readings, then takes 3 photos
   200 ms apart. Each temp file is deleted immediately after it is read.
3. **Submit:** the frames and the challenge are uploaded with the idempotency key.

Behaviour around the flow:
- **Retry key:** reused only after an unknown outcome — no response, or a proxy 502/503/504 or
  500 without the API envelope. Every attempt uses a new challenge.
- **Concurrency:** only one attempt runs at a time; both buttons are disabled and taps are
  ignored.
- **Failed checks:** there is no "punch anyway" or override.
- **Frames:** the list is cleared in `finally`.
- **Expiry:** a timer abandons capture if the challenge would expire within 15 s, and frames
  are not sent if fewer than 5 s remain after capture.
- **App backgrounded:** only `paused` with the camera running counts, because the iOS
  permission prompt also makes the app `inactive`.
- **Logging:** nothing is logged on the device.

## 9. Face++ integration details

- Unchanged: the client, credentials (server-only), `face_match_min_similarity` = 0.90,
  `face_enrollment_angle_min_similarity` = 0.80, the timeout and the per-employee FaceSet.
- **Which image is matched:** `frames[assessment.best_frame_index()]`, the highest-P(real) frame
  from the same request, which itself passed liveness. A separately supplied image is never
  matched.
- Face++ is not called at all when the challenge, replay check or liveness check fails, so
  spoof attempts cost nothing.
- The only liveness-related Face++ code was the placeholder, now removed. No Face++ liveness or
  FaceID endpoint is used.
- Timeouts and errors keep the existing mapping: 502 `FACE_PROVIDER_FAILED`, a `PROVIDER_ERROR`
  attempt, and no punch.
- **Data sent to Face++:** one frame per punch (plus, at enrollment, the five captures, as
  before). Everything else stays on our server.

## 10. Security and privacy considerations

- **Biometric data minimisation:**
  - frames are processed in memory and are never written to object storage, logs or the
    database;
  - only SHA-256 digests (not images or templates) and decision metadata (per-frame scores,
    reason, engine version, identity frame index) are stored;
  - on the phone, frames exist in memory only, and camera temp files are deleted as soon as they
    are read. This was also added to the enrollment capture, which previously left temp files.
- **Logging:** `face_liveness_assessed` logs only the decision, reason, frame count and duration;
  `face_liveness_unavailable` logs only the error type. A test proves frame bytes never reach
  stdout, stderr or logging.
- **Purpose:** unchanged (attendance identity), with no new consent text. The existing consent
  and HR approval gates are preserved.
- **Tenant isolation:** the session table has forced RLS. Look-ups are scoped to company **and**
  employee, so another employee's or tenant's challenge reads as not existing and is not burned
  (tested).
- **Retention — business/legal decision needed:**
  - `face_liveness_session` rows (digests) and `face_verification_attempt` rows (now with
    per-frame scores) grow without a purge job;
  - a retention period (for example 90 days for sessions, aligned with the attempt-log policy)
    should be set by HR/legal and implemented as a purge task.
- **Credentials:** the local `apps/api/.env` contains Face++ credentials and sets
  `FACE_VERIFICATION_PROVIDER=facepp`. It was not modified.
  - **Consequence:** with the code in this change, local face punching on that `.env` answers
    503 `FACE_LIVENESS_UNAVAILABLE` until `FACE_LIVENESS_ENGINE=minifasnet` and
    `FACE_LIVENESS_MODEL_DIR` are added. That is the intended fail-closed behaviour.
  - **Hygiene:** consider rotating those keys if that file has ever been shared.

## 11. Tests executed and exact results

> Distinguish: **mocked** tests (fake engine, fake Face++) prove contracts, ordering, binding,
> idempotency and failure handling. **Real-model** tests prove that the verified model loads, runs
> and fails closed. **Neither** proves anti-spoofing accuracy on real attacks.

| Suite | Command (from `apps/api` or `apps/mobile`) | Result |
| --- | --- | --- |
| Liveness unit (real model + rules) | `.venv/bin/python -m pytest tests/unit/modules/attendance/test_liveness.py` | 42 passed (real-model tests ran; none skipped) |
| Face++ adapter unit | `… tests/unit/modules/attendance/test_face_verification.py` | 20 passed |
| All backend unit | `.venv/bin/python -m pytest tests/unit` | **1087 passed** |
| Face integration (local DB/Redis, fakes) | `… tests/integration/modules/attendance/test_face_punch.py test_face_liveness_session.py test_face_punch_idempotency.py test_face_enrollment.py` | **122 passed** (concurrency tests repeated 5×, stable) |
| Full backend suite | `.venv/bin/python -m pytest tests` | **2774 passed, 0 failed** (12 min 35 s). Ran before one last cosmetic change (enrollment error `field`); afterwards all attendance unit + face integration tests were re-run: 282 passed |
| Migration up/down/up (local Docker DB only) | `.venv/bin/python -m alembic upgrade head && … downgrade -1 && … upgrade head` | OK; RLS enabled+forced; `hrms_app` has privileges |
| Ruff lint | `.venv/bin/python -m ruff check .` | 4 errors, all **pre-existing** E501 in `20261007090000_…` and `20261008090000_…` (untouched); 0 in changed files |
| Ruff format | `.venv/bin/python -m ruff format --check .` | 581 files formatted |
| mypy (strict) | `.venv/bin/python -m mypy` | no issues, 195 files |
| Import contracts | `import-linter` | 1 kept, 0 broken |
| Flutter analyze | `~/flutter/bin/flutter analyze` | No issues |
| Flutter face tests | `~/flutter/bin/flutter test test/face_punch_card_test.dart test/face_liveness_capture_test.dart test/face_punch_result_test.dart test/core/punch_idempotency_test.dart` | 32 passed |
| Flutter full | `~/flutter/bin/flutter test` | **503 passed, 1 skipped** (skip pre-existing) |

### Defects found and fixed during this work

1. **Inconsistent `liveness_score` representation.** A fresh response returned `0.95`, while an
   idempotent replay (read back from `NUMERIC(5,4)`) returned `0.9500`. Scores are now
   quantised to 4 decimals at the source.
2. **The mobile retry key was dropped on proxy 502/503/504 without the API envelope.** The
   server may have committed in that case, so a retry with a fresh key could double-punch. Such
   outcomes are now treated as unknown.
3. **Capture would abort on the iOS camera-permission prompt.** The prompt makes the app
   `inactive`, which the capture screen treated as an interruption. Only `paused` with a running
   camera now counts.

### Real-model observations (not an evaluation)

The upstream repository's three sample images (not committed; used only in the scratch
directory) gave:

| Image | Expected | Fused P(class 0, real, class 2) | Decision |
| --- | --- | --- | --- |
| `image_F1.jpg` | spoof | 0.196, 0.0723, 0.7316 | SPOOF_SUSPECTED |
| `image_F2.jpg` | spoof | 0.0016, 0.1813, 0.8172 | SPOOF_SUSPECTED |
| `image_T1.jpg` | genuine | 0.0001, 0.9936, 0.0064 | LIVE |

These outputs match upstream's reference implementation exactly (PyTorch, onnxruntime and
OpenCV DNN agree).

### Spoofing evaluation plan (to run on staging; not yet run)

This is the gate for enabling production. It is recorded as B-21 in the staging checklist.

- **Participants and data:**
  - consented participants only, plus test employees;
  - captures are not retained beyond the evaluation, and only per-attempt scores are exported.
- **Devices:** at least 2 Android (low and mid tier) and 1 iOS, with front cameras of differing
  quality.
- **Genuine conditions:**
  - bright indoor, dim indoor, backlit window, outdoor daylight;
  - glasses / no glasses, cap or hijab, beard change;
  - 10 attempts each per participant per device.
- **Attacks (same matrix):**
  - printed photo (matte, glossy, A4 and wallet size, curved and cut-out);
  - photo on another phone and on a laptop or monitor;
  - pre-recorded video on a phone and a monitor;
  - a request-level replay with a fresh challenge;
  - a reused or expired challenge;
  - a network drop mid-upload.
- **Metrics:**
  - APCER per attack type (attacks accepted ÷ attacks);
  - BPCER (genuine rejected ÷ genuine);
  - per-frame score distributions per device.
- **Choosing thresholds:**
  - `FACE_LIVENESS_LIVE_THRESHOLD` is set from the genuine score distribution at the accepted
    BPCER, and must keep APCER at the agreed target (for example ≤ 1–5% per attack type,
    product decision);
  - if no threshold meets both, do not enable — escalate (§14).
- **Acceptance:** sign-off by product, security and HR on the measured numbers, not on this
  report.

## 12. Performance measurements

Measured locally on the developer workstation (13th Gen Intel i7-13700F, 24 logical CPUs; OpenCV
limited to 2 threads). These are indicative numbers, not a measurement of the production host.
The test inputs were the upstream 480×640 samples.

| Measure | Result |
| --- | --- |
| First use: SHA-256 verification of 5.4 MB assets + model load | 193 ms (once per process) |
| Liveness, 1 frame (detector + 2 classifiers) | median 6.0 ms, p95 10.9 ms, max 27.4 ms (30 runs) |
| Liveness, 3 frames (one punch) | median 15.9 ms, p95 17.9 ms, max 19.0 ms (30 runs) |
| Resident memory added by OpenCV + models | ≈ 60 MB per API worker process (peak RSS 50 → 110 MB) |
| Frame payload (480×640 JPEG) | 65–86 KB each → ≈ 0.25 MB per punch upload (cap: 1 MB/frame, 6 MB/request) |
| Docker image impact if the extra is installed | opencv-python-headless + numpy wheels (tens of MB); not measured because the image was not built |
| Recurring cost | none (Face++ calls per punch unchanged: 1 detect + 1 search) |

**Not measured:**
- server CPU on the real production host;
- behaviour under concurrent punch bursts (one engine per worker serialises inference, so
  expect roughly 16 ms of queueing per concurrent punch per worker);
- on-device capture time on real phones;
- end-to-end latency including Face++.

These belong to staging (B-21).

## 13. Known model limitations and unverified attack scenarios

**Unverified** (no real-device or real-attack data yet): every attack class listed in §11.
Nothing in this report shows the system resists printed photos, screen replays or video replays
in our conditions.

**Known or likely weaknesses:**

- **Passive single-frame model, applied per frame.** It looks for texture, moiré and
  reflection cues. High-resolution screens, good prints in good light, or 3D masks may pass.
  Silicone masks and 3D heads were not in scope.
- **Domain shift.** Upstream says its accuracy depends on camera model and scene. Its published
  numbers come from its own data and the private high-precision model differs from the open one.
- **Injected or virtual-camera input from a modified client is not detected by the protocol.**
  The challenge and digest checks only stop exact replays and stale challenges. A
  re-encoded or newly rendered spoof must be caught by the model itself.
- **The detector is upstream RetinaFace at a 192-pixel-area input.** Very small or far faces are
  rejected as `FACE_TOO_SMALL` or `NO_FACE`. Strong side light may increase INCONCLUSIVE rates,
  and therefore BPCER.
- **Enrollment liveness is single-frame with no challenge.** It is mitigated by the HR-opened
  window and HR review of the photo.
- **The upstream project is unmaintained since 2020.** We own the pinned copy and conversion.

**Possible future hardening** (each needs its own decision):

- device attestation (Play Integrity / App Attest);
- an active, server-verified challenge (random head turn checked with a landmark/pose model on
  the server);
- multiple models or ensembles calibrated on our own consented data.

## 14. Remaining staging and production blockers

1. **Calibration (B-21).** Real-device, real-attack evaluation with consented participants, and
   thresholds chosen from data. **Blocks production.**
2. **Legal.** Confirm acceptance of the upstream model given its undisclosed training data (§5).
   Set retention periods for liveness sessions and attempt scores (§10).
3. **Deployment packaging.** The default Dockerfile neither installs the `liveness` extra nor
   copies `models/`. A staging image needs `uv sync --frozen --no-dev --extra liveness` and
   `COPY models ./models` (or a mounted, read-only volume), plus the two env vars. Whether to
   commit the 5.4 MB of binary assets to git or fetch them at build time with the build script
   is a repository-policy decision; the files are currently **untracked** in the working tree.
4. **Migration.** `20261015090000_face_liveness_session` must be applied by the staging owner.
   It was applied only to the local Docker DB here.
5. **App rollout ordering.**
   - Older app builds send `photo` and will receive `FACE_LIVENESS_CHALLENGE_REQUIRED` ("update
     the app") once the API ships.
   - Face punching is unusable on any server where the liveness engine is disabled.
   - Release the app and server together, and enable per environment.
6. **Cleanup decision.** `image_picker` is no longer used by the app and can be removed from
   `pubspec.yaml` in a follow-up (left in place to keep this change scoped).

**Rollback / failure behaviour:**

- Set `FACE_LIVENESS_ENGINE=disabled` (or remove the model directory) and face punching returns
  503 `FACE_LIVENESS_UNAVAILABLE`. Web, mobile and HR punches are unaffected, and no punches are
  lost.
- A corrupted or tampered model file behaves the same way, because of the checksum check.
- Schema rollback: `alembic downgrade 20261014091000` (attempt rows are kept and remapped).

## 15. Commands to reproduce

```bash
# Backend (from apps/api; local Docker Postgres :5433 / Redis :6380 only)
uv sync --extra liveness --extra dev
.venv/bin/python -m alembic upgrade head          # local DB only
.venv/bin/python -m pytest tests/unit/modules/attendance/test_liveness.py tests/unit/modules/attendance/test_face_verification.py
.venv/bin/python -m pytest tests/integration/modules/attendance/test_face_punch.py tests/integration/modules/attendance/test_face_liveness_session.py tests/integration/modules/attendance/test_face_punch_idempotency.py tests/integration/modules/attendance/test_face_enrollment.py
.venv/bin/python -m pytest tests
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check . && .venv/bin/python -m mypy

# Rebuild + verify model assets (throwaway venv with torch==2.5.1 (CPU), onnx==1.17.0, opencv-python-headless, numpy)
python -I scripts/liveness/build_minifasnet_assets.py --out /tmp/minifasnet-check
diff <(cd models/liveness/minifasnet-v1 && sha256sum *.onnx *.prototxt *.caffemodel) <(cd /tmp/minifasnet-check && sha256sum *.onnx *.prototxt *.caffemodel)

# Mobile (from apps/mobile)
~/flutter/bin/flutter analyze
~/flutter/bin/flutter test
```

Local enablement for manual testing (never production): add the following to a **local** `.env`:

```
FACE_LIVENESS_ENGINE=minifasnet
FACE_LIVENESS_MODEL_DIR=models/liveness/minifasnet-v1
```

## 16. Explicit confirmation

- Nothing was committed, pushed, merged, rebased, tagged or deployed. All changes are in the
  working tree of `main` (§7). New files are untracked.
- No service was restarted.
- No production or shared infrastructure, database, Redis queue or employee record was accessed.
- The migration ran only against the local Docker Postgres at `localhost:5433` (`hrms_dev`).
- No email, SMS or notification was sent; the test suite uses the logging email provider.
- No Face++ request was made: tests force `FACE_VERIFICATION_PROVIDER=disabled` and use fakes.
- No paid API or service was introduced or purchased.
- External network access was limited to:
  - downloading the pinned upstream Silent-Face repository from GitHub;
  - PyPI / PyTorch's official index for the scratch conversion venv and the locked
    `opencv-python-headless` / `numpy`;
  - read-only web searches for the candidate evaluation.
- No model or test image of a real employee was used. The only face images processed were the
  upstream repository's own samples, and they were not added to this repository.
