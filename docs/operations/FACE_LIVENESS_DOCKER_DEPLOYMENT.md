# Face liveness — Docker deployment

Scope: how the MiniFASNet liveness engine is packaged in the API image and how to build, inspect
and roll it out. Feature design and threat model: `docs/audits/FACE_ATTENDANCE_LIVENESS_IMPLEMENTATION_REPORT.md`.
Packaging evidence: `docs/audits/FACE_LIVENESS_DOCKER_PACKAGING_REPORT.md`.

> **Packaging is not validation.** A successful build proves the files are present and load. It says
> nothing about accuracy against real attacks. Production stays at `FACE_LIVENESS_ENGINE=disabled`
> until staging calibration (checklist B-21), legal sign-off and retention are done.

## Model distribution

**Decision: the assets are committed to the repository and copied into the image** (they are
5.4 MB in total).

- Licence: upstream Silent-Face-Anti-Spoofing is Apache-2.0 (`models/liveness/minifasnet-v1/LICENSE.upstream`),
  which permits redistribution with the licence text retained. The ONNX files are format conversions;
  a modification notice is in `models/liveness/minifasnet-v1/README.md`.
- Build-time download was rejected: the ONNX files are *derived* (converted with torch + onnx), so
  there is no upstream URL that serves them, and converting at image-build time would add torch to
  the build.
- **Open (not code):** upstream does not disclose its training data. Legal must accept that before
  production use. Until then the feature stays disabled.

| File | SHA-256 |
| --- | --- |
| `minifasnet_v2_scale2.7_80x80.onnx` | `079399882d651cb9126de6444ca0fabce952db7d5792823ef6c4ae004132534f` |
| `minifasnet_v1se_scale4.0_80x80.onnx` | `828e4476ac4561c9185c092d173105f30c51f814d93fd71a892c1b67b41e5dd9` |
| `retinaface_deploy.prototxt` | `9fe2f141b4baee039ed9442da2833e216af40a6ff3e639e7b39258812bcda808` |
| `retinaface_widerface.caffemodel` | `d08338a2c207df16a9c566f767fea67fb43ba6fff76ce11e938fe3fabefb9402` |

The source of truth is `_PINNED_SHA256` in `src/hrms/modules/attendance/liveness.py`. Provenance:
upstream commit `b6d5f04ad78778917853b25c778acef6d5626d15`, reproducible export via
`scripts/liveness/build_minifasnet_assets.py`. **Never edit a pinned hash to make a file pass** — a
different file is a new model version needing review.

## What the image contains

`apps/api/Dockerfile` (two stages: `builder` installs dependencies, `runtime` runs gunicorn as uid 1000 `hrms`):

- `uv sync --frozen --no-dev --extra liveness` — adds `opencv-python-headless` (+ numpy). No dev dependencies.
- `COPY models ./models`, then a **build gate**: `scripts/liveness/verify_assets.py` checks all four
  hashes and loads the models. A missing, altered or unloadable file fails `docker build`.
- The runtime stage copies `/app` from the builder, so the models are at
  `/app/models/liveness/minifasnet-v1` (owned by `hrms`, read by the runtime user).
- `.dockerignore` already excludes `.env`, `.env.*` and `tests/`; `models/` is not excluded.
- The extra and models ship in **every** image (api, worker, beat share it) but are inert unless enabled.
  Cost: roughly +230 MB uncompressed (OpenCV ≈ 160 MB, numpy ≈ 58 MB, models 6 MB).

## Configuration

| Variable | Disabled (default, safe) | Enabled (staging only, after approval) |
| --- | --- | --- |
| `FACE_LIVENESS_ENGINE` | `disabled` | `minifasnet` |
| `FACE_LIVENESS_MODEL_DIR` | unset | `/app/models/liveness/minifasnet-v1` |
| thresholds / frames / TTL | defaults | `FACE_LIVENESS_LIVE_THRESHOLD` etc. (uncalibrated defaults) |

Set through the existing env files (`apps/api/env/.env.<environment>`, git-ignored; template
`apps/api/.env.example`). `docker-compose.prod.yml` needed no change: the api service already reads
`env_file`. Do not put values in committed Compose files.

Behaviour:

- **Disabled:** the API boots normally, loads nothing. Face punching and self-enrollment return 503
  `FACE_LIVENESS_UNAVAILABLE`. There is no fallback to "face detected = live". Other punch types are unaffected.
- **Enabled, valid assets:** the API verifies and loads the models at startup.
- **Enabled, missing/tampered/unloadable assets or missing OpenCV:** the **API refuses to boot**
  (`LivenessUnavailableError` in the startup log) rather than serve 503s later. Enabled with an empty
  `FACE_LIVENESS_MODEL_DIR` is refused by settings validation. This only affects the API process.
- Runtime failures after boot (timeout, engine error) still return 503 and never record a punch.

## Build and inspect locally

Needs Docker and network access to the base image and PyPI; no credentials.

```bash
cd apps/api
docker build -t hrms-api:liveness-local .

# hashes, model load and (optionally) one inference, as the runtime user, with no network:
docker run --rm --network none hrms-api:liveness-local \
  python scripts/liveness/verify_assets.py models/liveness/minifasnet-v1

# inference on your own image (mount it; use an approved test image, never employee data):
docker run --rm --network none -v "$PWD/sample.jpg:/s.jpg:ro" hrms-api:liveness-local \
  python scripts/liveness/verify_assets.py models/liveness/minifasnet-v1 --infer /s.jpg
```

Expected: four `OK <hash>` lines, `OK engine loaded`, exit 0. Any `FAIL` line exits 1.

Failure checks (mount a modified copy of the directory at `/m:ro`): a deleted file prints
`FAIL MISSING <name>`, an appended byte prints `FAIL <hash>`; both exit 1.

## Database migration — NOT EXECUTED

`alembic/versions/20261015090000_face_liveness_session.py` adds `face_liveness_session` and the new
`face_verification_attempt` decisions. It has only been applied to the local Docker database in
earlier work. The environment owner must run it (the `migrate` service, `--profile tools`) **before**
the new API serves face punches. Rollback: `alembic downgrade 20261014091000` (attempt rows are kept, remapped).

## Rollout

1. Release the mobile app and the API together: old app builds send `photo` and get
   `FACE_LIVENESS_CHALLENGE_REQUIRED`.
2. Apply the migration. Deploy the image with liveness **disabled**; confirm startup and `/health/live`.
3. Staging only: enable the two variables, restart, run the B-21 evaluation (real devices, real
   attacks, consented participants), choose thresholds from data.
4. Production enablement is a separate decision after sign-off.

**Rollback:** set `FACE_LIVENESS_ENGINE=disabled` and restart the API. Face punching returns 503;
web/mobile/HR punches are unaffected. Reverting the image does not need the schema rolled back.

## Limits

Passive single-frame model; unvalidated on real attacks; cannot detect injected or virtual-camera
frames from a modified app; no device attestation; enrollment is not challenge-bound; model is
unmaintained upstream; retention for liveness/attempt rows is undefined. Details in the
implementation report §13–14.

> **Update 2026-10-17:** a second migration, `20261017090000_face_integrity_hardening`, must also be applied (enrollment attempt log,
> two new attempt decisions, **irreversible erasure of stored Face++ search bodies**; downgrade does not restore them). Backup first.
> Staging preflight, post-checks and rollback levels: `docs/operations/FACE_ATTENDANCE_STAGING_READINESS_PLAN.md` §B.
