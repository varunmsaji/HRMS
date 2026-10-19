# Face Liveness — Docker Packaging Report

Date: 2026-10-16. Scope: package the existing MiniFASNet liveness engine in the API image and verify
it locally. No feature rebuild, no accuracy work.

> **Status:** packaging verified locally. **Not production-ready.** Docker builds and passing tests
> say nothing about spoof resistance. Liveness remains disabled by default everywhere.

## 1. Initial Git state

Branch `main`, HEAD `d0c55f4ed3f87941cbefed57544313bf348d0ab9`. The tree already held the
uncommitted liveness work from the previous phase (24 modified, 11 untracked paths, including
`apps/api/models/`, `liveness.py`, the migration and the report). All of it was preserved; nothing
was staged, committed, stashed or reset. `git ls-files apps/api/models` is empty: the model files are
**untracked**, not ignored (no `.gitignore` rule matches them).

## 2. Files modified in this phase

| File | Why |
| --- | --- |
| `apps/api/Dockerfile` | `--extra liveness` on both `uv sync` steps; `COPY models`; build gate running `verify_assets.py` |
| `apps/api/scripts/liveness/verify_assets.py` (new) | Hash + load (+ optional inference) check, used by the build gate and for inspection |
| `apps/api/src/hrms/app.py` | Startup: when the engine is enabled, load and verify the models, else refuse to boot |
| `apps/api/tests/unit/modules/attendance/test_liveness.py` | +3 startup tests (disabled boots; enabled+missing refuses; enabled+valid boots) |
| `apps/api/.env.example` | Comment on the container path and boot behaviour; value stays `disabled` |
| `docs/operations/FACE_LIVENESS_DOCKER_DEPLOYMENT.md` (new), this report | Documentation |

No Compose file changed: `docker-compose.prod.yml` already supplies configuration through
`env_file: apps/api/env/.env.production` (git-ignored). `.dockerignore` already excludes `.env*` and
`tests/`, so no secrets enter the image.

## 3. Model distribution decision

**Option A: commit the assets and copy them into the image.**

- Evidence: `LICENSE.upstream` is Apache-2.0 (sha256 `daf94bf1…edee6fb`, matches `MANIFEST.json`), which
  permits redistribution with the licence kept; the assets README carries the modification notice.
- Option B (build-time download) is not possible for the ONNX files: they are our own conversion of
  upstream `.pth` checkpoints, and no URL serves them. Converting during the image build would need
  torch. Only the two detector files exist upstream, and splitting the sources was not worth it.
- Option C: no private artifact source exists in the repository.
- **Unresolved:** upstream's training data is undisclosed (legal question, unchanged). That is why
  the feature stays disabled.
- **Action needed from you:** the files are untracked. A CI/clean-checkout build fails at `COPY models`
  until they are committed (or a different distribution is chosen). I did not commit.

## 4. Docker and Compose changes

The image is two-stage: `builder` (uv, dependency install, build gate) and `runtime` (fresh
`python:3.12-slim`, copies `/app`, runs gunicorn as uid 1000 `hrms`). The extra, models and gate are in
the builder, and the models reach the runtime through the existing `COPY --from=builder`. No dev
dependencies were added (`pytest`, `ruff`, `mypy` absent from site-packages, checked in the image).
Disabled remains the default; the enabled setting is documented, not committed.

Startup behaviour added: enabled + invalid assets → API refuses to boot (explicit
`LivenessUnavailableError`). Disabled → unchanged. Request-time 503 `FACE_LIVENESS_UNAVAILABLE` is
unchanged and still covered by the integration tests.

## 5. Hash verification (inside the built image, as `hrms`, `--network none`)

| File | Result |
| --- | --- |
| `minifasnet_v2_scale2.7_80x80.onnx` | OK `07939988…32534f` |
| `minifasnet_v1se_scale4.0_80x80.onnx` | OK `828e4476…b41e5dd9` |
| `retinaface_deploy.prototxt` | OK `9fe2f141…d808` |
| `retinaface_widerface.caffemodel` | OK `d08338a2…b9402` |

All four match `_PINNED_SHA256`. The host copies hash identically.

## 6. Container build and inference results

| Check | Result |
| --- | --- |
| `docker build -t hrms-api:liveness-local apps/api` | success |
| Models present at `/app/models/liveness/minifasnet-v1`, readable by uid 1000 | yes (6 MB; files `rw-rw-r-- hrms`) |
| Engine imports and loads in the container | yes (`engine loaded`) |
| Inference with a synthetic noise image | ran, decision `INCONCLUSIVE/NO_FACE`, 26 ms, no punch-capable result |
| Missing asset (runtime, mounted copy) | `FAIL MISSING retinaface_widerface.caffemodel`, exit 1 |
| Altered asset (runtime) | `FAIL <hash>`, `failed verification`, exit 1 |
| Altered asset (**build**) | `docker build` failed at the gate, exit 1, no image produced |
| API boot: enabled + missing assets | traceback `LivenessUnavailableError`, exit 1 |
| API boot: enabled + valid assets | boots |
| API boot: disabled | boots |
| Full container, default CMD, dev env, isolated | gunicorn starts; the Dockerfile HEALTHCHECK's `/health/live` probe returned 200 |
| Image size | 724 MB; added content ≈ OpenCV 162 MB + numpy 58 MB + models 6 MB. The older local `latest` tag (392 MB, 3 weeks old) was not a like-for-like baseline, so the exact delta was not measured |

**Not demonstrated:** inference on a real face. No face image is in the repository and none was
downloaded; the real-face upstream samples were checked in the previous phase (spoof/spoof/genuine
classified as expected) but not re-run in the container. The container runs the identical Python code
and verified weights, but this is a gap in the evidence, not a claim.

All containers ran with `--network none` or no shared services: no database, Redis, MinIO, Face++ or
email. No Compose stack was started.

## 7. Tests actually run

| Command (from `apps/api`) | Result / exit |
| --- | --- |
| `pytest tests/unit/modules/attendance/test_liveness.py` | 45 passed, exit 0 |
| `pytest tests/unit` | 1090 passed, exit 0 |
| `pytest` on `test_face_punch.py`, `test_face_liveness_session.py`, `test_face_punch_idempotency.py`, `test_face_enrollment.py` (local Docker DB/Redis, fakes) | 80 passed, exit 0 |
| `pytest tests` (full, local Docker DB/Redis) | **2777 passed**, 4 warnings, 12 min 17 s, exit 0 |
| `ruff format --check .` | 583 files already formatted, exit 0 |
| `ruff check .` | exit 1: 4 errors, all E501 in the two older migrations `20261007090000` and `20261008090000` (pre-existing, untouched); 0 in changed files |
| `mypy` | no issues, 195 files |
| `lint-imports` (`PYTHONPATH=src`) | 1 kept, 0 broken |

The face API, idempotency and liveness-session suites pass unchanged, so API contracts and
attendance decisions are unaffected. Flutter was not touched this phase and was not re-run.

## 8. Not run, and why

- **Alembic migration:** not run (instructed). It was applied to the local Docker database in the
  previous phase only.
- **Compose stack / worker / beat:** not started, to avoid shared infrastructure and Redis consumption.
- **Real-face inference, calibration, real-device tests:** out of scope for this phase.
- **Flutter tests:** unchanged code.

## 9. Remaining blockers

1. **Commit decision for the model files** (untracked; a clean build fails until tracked or sourced otherwise).
2. **Legal:** undisclosed training data of the upstream weights; retention for liveness sessions and
   attempt rows is unset and no purge job exists.
3. **Accuracy:** no real-device, real-attack calibration (B-21); thresholds are uncalibrated.
4. **Security limits:** passive single-frame model; injected/virtual-camera input is not detected; no
   device attestation; enrollment is not challenge-bound.
5. **Operations:** the migration must be applied by the environment owner before the API serves face
   punches; app and API must ship together; the image is ~230 MB larger for every service.
6. **Behaviour note to confirm:** with the engine enabled and bad assets, the whole API process now
   fails to boot (by design, matching the existing boot guards), not just face punching.

## 10. Confirmation

No commit, push, merge, rebase, reset, stash, clean, tag or deployment was made. No service was
restarted and no remote command was run. No migration was run in this phase. No production or shared
database, broker, object store, Face++ or email provider was touched. Production configuration was not
changed and liveness was not enabled anywhere. Temporary test images (`hrms-api:liveness-local`)
remain in the local Docker daemon; the tamper-test image was never created. Temporary files used
for the missing/altered-asset checks lived only in the session scratchpad.
