# Open-source face attendance engine - setup and operation

Written for: the engineer/operator who provisions, selects and, if needed, rolls back the engine.

Date: 2026-10-25 (second pass). **The engine is disabled by default and is NOT approved for
production** (two model-licence questions and no accuracy evidence are open - audit sections 10-11).
Nothing here has been run on staging or production. Status words: PASS / FAIL / BLOCKED / NOT RUN /
INSUFFICIENT EVIDENCE as defined in the audit.

## 1. Requirements

- Python extra `liveness` (OpenCV `opencv-python-headless` 4.x; NumPy comes with it): `uv sync --extra liveness`. The Docker image already installs it.
- The liveness engine configured as for Face++ (`FACE_LIVENESS_ENGINE=minifasnet`, `FACE_LIVENESS_MODEL_DIR`): punching and self-enrollment need it for either recognition engine.
- PII encryption provisioned: `PII_MASTER_KEY` (outside development) and exactly one ACTIVE row in `encryption_keys`. Embeddings use that **environment-wide** key - there is no per-tenant key (section 6a).
- CPU only. Memory/latency: section 7.

## 2. Model choice and licensing (summary - evidence in the audit, section 10)

| Component | Code licence | Weight / training-data position | Status |
|---|---|---|---|
| YuNet `face_detection_yunet_2023mar.onnx` | MIT at the cited upstream commit (libfacedetection.train `a61a428`); the same repo now declares BSD-3-Clause | trained on WIDER Face, whose official page lists CC BY-NC-ND | **BLOCKED FOR COMMERCIAL PRODUCTION** pending counsel |
| SFace `face_recognition_sface_2021dec.onnx` | Apache-2.0 (OpenCV Zoo) | upstream repo has no licence; training data (CASIA-WebFace / VGGFace2 / MS-Celeb-1M per the paper) not stated for this file | **BLOCKED FOR COMMERCIAL PRODUCTION** pending counsel |
| MiniFASNet liveness (existing) | Apache-2.0 | unchanged from the earlier liveness release | out of scope here |
| InsightFace pretrained models | MIT code | non-commercial research only | rejected |

Do not replace a model without approval; if counsel refuses, see the audit's replacement section.

## 3. Provisioning the model files - reproducible, no downloads at runtime

Files are **not in git** (`models/face/opensource-v1/.gitignore`) and are **excluded from the Docker
build context** (`apps/api/.dockerignore`: `models/face/**/*.onnx`), so a developer's local copy can
never end up in an image.

```
cd apps/api
python scripts/face/fetch_opensource_assets.py models/face/opensource-v1     # fetch + verify
python -m hrms.modules.attendance.opensource_face.assets models/face/opensource-v1   # OK
```
Pinned SHA-256 (also in `opensource_face/assets.py`):
`face_detection_yunet_2023mar.onnx` = `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`;
`face_recognition_sface_2021dec.onnx` = `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`.
Sources are the OpenCV Zoo Git-LFS URLs listed in `assets.py` (a mutable `main` branch - the checksum,
not the URL, is the trust anchor; mirror the files into your own artifact store for release builds).
The fetch script discards any file whose digest differs; the service re-verifies before loading.

### What `--build-arg FACE_OS_ASSETS` controls (precisely)

| | `false` (default) | `true` |
|---|---|---|
| Model files in the image | none (verified in a real build: only the liveness `.onnx` files) | yes, fetched once **at build time**, checksum-verified; the build fails on any mismatch |
| Runtime activation | never | **never** - activation is only `FACE_VERIFICATION_PROVIDER=opensource` + `FACE_OS_ENABLED=true` + `FACE_OS_MODEL_DIR` at runtime |
| Network | none | build needs egress to `media.githubusercontent.com`; runtime needs none |

Because the argument changes only what is *inside* the image, one image with the assets can run as
Face++ or open-source depending purely on runtime env; conversely an image built without them
refuses to boot as `opensource` (clear error). The build trusts the network only to the extent of
the checksum; it does not verify a licence. Recommended distribution: keep the pinned-fetch process
for development; for release builds, copy the verified files into the organisation's private
artifact store and fetch from there (still checksum-pinned) - do not commit them to git.

## 4. Enabling (staging only, after the checklist)

```
FACE_VERIFICATION_PROVIDER=opensource
FACE_OS_ENABLED=true
FACE_OS_MODEL_DIR=/app/models/face/opensource-v1
FACE_LIVENESS_ENGINE=minifasnet
FACE_LIVENESS_MODEL_DIR=/app/models/liveness/minifasnet-v1
```
Run migration `20261022090000` first (normal release process only on shared databases). Default
remains `FACE_VERIFICATION_PROVIDER=disabled`; `facepp` still requires explicit selection and
credentials. Verified start-up behaviour (real lifespan, outbound network made fatal;
`tests/unit/modules/attendance/test_opensource_face_startup.py` and the same scenarios inside the
built image with `--network none`): disabled boots; Face++ boots without any open-source asset;
open-source with valid assets boots; open-source without `FACE_OS_ENABLED`, without a model dir,
with a missing/empty/nonexistent dir, with a tampered asset, with an out-of-range threshold, or
with an unknown provider name refuses to boot; Face++ selected with a tampered open-source dir
boots (the dir is never read).

## 5. Re-enrollment runbook (Face++ -> open-source, or back)

Never automatic. Nothing in the code revokes or re-enrolls anyone on a switch.

1. **Inventory and backup (read-only).** `GET /v1/attendance/face-profiles` as HR: count profiles by
   `provider` and `status`; `requires_reenrollment=true` lists who is blocked after a switch. Take a
   database backup (it holds profiles, attempts, the outbox and - for OPENSOURCE - the encrypted
   embeddings) and record `encryption_keys` + the secret custody for `PII_MASTER_KEY`.
2. **Approval and notice.** Written approval from the data-protection owner and HR; employee notice
   covering that the template is stored locally, how long, and how to withdraw; consent text
   updated before the first new enrollment (consent is re-recorded per enrollment).
3. **Pilot.** Choose a small consenting group (e.g. 3-5, mixed devices). Switch a **staging** deployment
   first; production only after the staging checklist.
4. **Revoke the old enrollment.** HR: `DELETE /v1/attendance/face-profiles/{employee_id}`. The
   profile becomes REVOKED immediately (punches by that employee stop using face; ordinary punching
   is unaffected) and a `face_external_deletion` row is queued. The worker (`attendance.run_face_deletions`,
   needs Celery worker + Beat) deletes the old engine's data - Face++ FaceSet or embeddings - using the
   engine named on the row. **Deletion is irreversible; a Face++ backup cannot restore a deleted
   FaceSet, and profiles cannot be converted between engines.** Revoking twice does not queue a
   second deletion.
5. **New enrollment.** HR opens a window (`POST .../enrollment-window`); the employee self-enrolls
   (consent, 5 captures, liveness on each); HR approves. Verify one punch.
6. **Failed or interrupted enrollment.** A rejected/aborted submission leaves no profile and no
   embeddings (compensated at once; tested); the window stays usable until it expires or is cancelled.
   If the process dies mid-enrollment, the crash-reaper queues the orphan after the lease
   (`FACE_ENROLLMENT_LEASE_SECONDS`).
7. **Audit verification.** Check `audit_log` for FACE_PROFILE_SUBMITTED/APPROVED/REVOKED per employee,
   `face_external_deletion` rows reach DONE (none stuck past `FACE_DELETION_ALERT_AFTER_ATTEMPTS`),
   and no `face_embedding` rows remain for revoked people.
8. **Rollback.** Set `FACE_VERIFICATION_PROVIDER=facepp` and restart; employees enrolled only with
   the open-source engine then show `requires_reenrollment` and must enroll again with Face++.
   Anything already deleted stays deleted. Switching alone deletes nothing.

## 6. Rollback and disablement

Disable: `FACE_VERIFICATION_PROVIDER=disabled` (face punching/enrollment fail closed; ordinary
punches unaffected; Face++ deletions stay deferred, open-source deletions still run because they
need no model). Migration `alembic downgrade -1` refuses while OPENSOURCE data exists.

### 6a. Encryption and key lifecycle (limits)

AES-256-GCM, random nonce per value, tag verified on read; one environment-wide DEK, wrapped under
SHA-256(`PII_MASTER_KEY`) in `encryption_keys`; ciphertext bound to the row **and its ownership
columns** (architecture doc section 4). Consequences operators must know:
- **Backups** contain only ciphertext + wrapped DEKs. Restoring the DB without the same
  `PII_MASTER_KEY` yields undecryptable templates -> everyone re-enrolls. Back the secret up separately.
- **Key loss** (secret or `encryption_keys` rows) is unrecoverable for embeddings; there is no escrow.
- **Rotation** (`provisioning.rotate_key`) affects new writes only; **no sweep re-encrypts existing
  `face_embedding` rows** and old DEK versions must be kept. Smallest remediation if needed: a
  re-encrypt job over `face_embedding` modelled on `pii_backfill` (decrypt with the binding, re-encrypt
  with the current DEK) - not built, not needed until a rotation is scheduled.
- **Development mode** uses a deterministic dev key; never run staging/production with `ENVIRONMENT=development`.
- The master secret is hashed once (no KDF stretching): it must be a high-entropy random value.

## 7. Capacity (measured on one dev host; not a guarantee)

Host: 24 logical cores, Python 3.12, OpenCV 4.14, one 512 px portrait, synthetic load only.
- Cold start in the final image (no network): import 0.56 s, model load 0.25 s, first embedding 50 ms.
- Warm embedding p50 17.5 ms (p95 18.1 ms), concurrency 1.
- Process RSS after warm-up and sustained load: **~203 MB at concurrency 1, ~323 MB at 2** (baseline
  Python+OpenCV import ~52 MB). Earlier "430 MB" came from a 40-task burst that queued decoded images;
  the admission gate now bounds that.
- Sustained throughput (in-flight capped at the waiting room): 51/s (conc 1), 77/s (conc 2) per
  process. Overload (200 simultaneous): 195/190 rejected in ~0.1 s as `EmbeddingTimeoutError`,
  memory flat.
- Topology arithmetic for the shipped defaults (2 gunicorn workers, `FACE_OS_MAX_CONCURRENCY=1`):
  2 model copies -> roughly **+0.3-0.4 GB RAM** for the engine on top of the API, plus the existing
  liveness model per worker. The Celery worker and Beat load **no** model (deletion needs none).
  `docker-compose.prod.yml` sets no memory limits - set them from a staging measurement.
- A face punch embeds each of 3 frames (verify) and an enrollment 5 captures; divide the rates above
  accordingly. Real 1280 px phone photos, the target VPS CPU, HTTP/TLS and database time are **not
  measured** - no employee-count capacity claim is made.

## 8. Test commands (results in the audit, section 13)

```
cd apps/api
.venv/bin/python -m pytest tests/unit -q
python run_full_tests.py --integration     # isolated hrms_test DB + Redis /1
# or, with that environment: pytest tests/integration/modules/attendance tests/security
.venv/bin/ruff check src tests scripts; .venv/bin/python -m mypy src/hrms
```

## 9. Remaining production gates

See the gate matrix in `docs/audits/OPEN_SOURCE_FACE_ATTENDANCE_AUDIT.md` (section 12) and
`OPEN_SOURCE_FACE_ATTENDANCE_STAGING_CHECKLIST.md`.
