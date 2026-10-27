# Open-source face engine - staging checklist

Written for: the authorised operator who validates the engine on staging.

Date: 2026-10-25 (second pass). **No live staging check has been performed; every "staging" row is
NOT RUN until an authorised operator fills in a dated result.** "Local" rows were run on a developer
host / disposable resources and are carried in the audit (section 13). Do not enable the provider
before sections A-B are closed. Status: PASS / FAIL / BLOCKED / NOT RUN / INSUFFICIENT EVIDENCE.

Companion: `FACE_ATTENDANCE_STAGING_SECURITY_CHECKLIST.md` (all items apply unchanged to
challenges, liveness, approvals and rate limits), `OPEN_SOURCE_FACE_ATTENDANCE_SETUP.md`.

| # | Check | Where | Status | Evidence / owner |
|---|---|---|---|---|
| **A. Legal and privacy (blocking)** | | | | |
| A1 | Counsel decision on commercial use of YuNet weights (WIDER Face CC BY-NC-ND training data) | - | BLOCKED | counsel |
| A2 | Counsel decision on commercial use of SFace weights (undocumented research training data, no upstream licence) | - | BLOCKED | counsel |
| A3 | Licence texts + NOTICE present beside the models in the repo (done) and in the release image (not yet checked); legal review of wording | - | NOT RUN | legal/release owner |
| A4 | Biometric consent text covers local template storage, retention, withdrawal; DPIA done | - | NOT RUN | data-protection owner |
| A5 | Decision on demographic evaluation data (what is lawful to collect) | - | NOT RUN | counsel/HR |
| **B. Provisioning and image** | | | | |
| B1 | Pinned-checksum fetch reproduces from a clean copy | local | PASS | audit 13 |
| B2 | Default image carries no open-source assets, defaults disabled, non-root | local | PASS | audit 13 |
| B3 | `FACE_OS_ASSETS=true` image: assets present, hashes match, boots offline | local | PASS | audit 13 |
| B4 | Release image built by CI/release pipeline: record **tag and digest** here: `________` | staging | NOT RUN | release owner |
| B5 | Assets in the release image re-verified (`python -m ...opensource_face.assets`) in the running container | staging | NOT RUN | operator |
| B6 | Corrupt/missing asset: container refuses to boot as `opensource`; boots as `facepp`/`disabled` | staging | NOT RUN | operator (local equivalent PASS) |
| B7 | Model directory is writable by the runtime user in the current image (finding H-1); decide on read-only root/volume | staging | NOT RUN | platform owner |
| B8 | `alembic upgrade head` on the staging DB; `face_embedding` ENABLE+FORCE RLS, one policy; `hrms_app` sees only the current tenant | staging | NOT RUN | DBA (local PASS) |
| B9 | `PII_MASTER_KEY` set (not development), exactly one ACTIVE `encryption_keys` row, key + master secret backed up separately | staging | NOT RUN | security owner |
| **C. Function (consented pilot staff, real devices)** | | | | |
| C1 | Explicit env: `FACE_VERIFICATION_PROVIDER=opensource`, `FACE_OS_ENABLED=true`, nothing else implied | staging | NOT RUN | operator |
| C2 | Enroll 3-5 pilot staff on different phones; HR approval; punch IN/OUT | staging | NOT RUN | pilot lead |
| C3 | Wrong person rejected (`FACE_NOT_MATCHED`); two faces; no face; tiny face | staging | NOT RUN | pilot lead |
| C4 | Engine unavailable (staging replica): `FACE_PROVIDER_FAILED`, no punch, no lockout beyond `FACE_PUNCH_MAX_FAILED_ATTEMPTS` | staging | NOT RUN | operator (local PASS) |
| C5 | Face++-enrolled employee gets `FACE_NOT_ENROLLED`, `requires_reenrollment=true` visible to HR; nothing sent to either engine | staging | NOT RUN | operator (local PASS) |
| C6 | Revoke an OS-enrolled pilot: outbox DONE, `face_embedding` rows gone; second revoke queues nothing | staging | NOT RUN | operator (local PASS) |
| C7 | Challenge/frame replay rejected | staging | NOT RUN | pilot lead |
| **D. Security and privacy** | | | | |
| D1 | Grep API/worker logs, metrics and `provider_response` after C: no embedding values, image bytes, keys | staging | NOT RUN | security owner |
| D2 | DB backup -> restore on a scratch DB: embeddings decrypt only with the same `PII_MASTER_KEY`; documented key-loss outcome acknowledged | staging | NOT RUN | DBA |
| D3 | Key-rotation rehearsal: new writes use the new version, old rows still decrypt; accept that no re-encryption sweep exists | staging | NOT RUN | security owner |
| D4 | Per-IP flood limits and liveness-session limits exercised against this engine | staging | NOT RUN | operator |
| **E. Capacity and operations** | | | | |
| E1 | Concurrency/admission behaviour (bounded queue, release on error/cancel) | local | PASS | audit 13 |
| E2 | Load test on the **target CPU** with real photo sizes: p95 latency, RSS per worker at `FACE_OS_MAX_CONCURRENCY` 1 and 2, no event-loop stalls; set container memory limits | staging | NOT RUN | operator |
| E3 | Celery worker and Beat running (deletion/cleanup depend on them): `attendance.run_face_deletions` executes on schedule | staging | NOT RUN | operator |
| E4 | `/health/ready` OK with the engine selected; behaviour when models are missing = boot refusal (not a runtime readiness flap) | staging | NOT RUN | operator |
| E5 | Alerts: `hrms_dependency_errors_total{dependency="face_local_engine"}`, deletion backlog / `face_deletion_failed`; no biometric content in alert text | staging | NOT RUN | on-call owner |
| E6 | Rollback to Face++ and to `disabled` rehearsed (setup doc sections 5-6) | staging | NOT RUN | operator |
| E7 | Incident owner and escalation path named for biometric incidents | - | NOT RUN | engineering manager |
| **F. Evaluation (blocking for thresholds)** | | | | |
| F1 | Consented dataset prepared per evaluation doc section 4 | - | BLOCKED | data-protection owner |
| F2 | `evaluate_captures` verdict is not INSUFFICIENT EVIDENCE; thresholds chosen on a development split and confirmed on an independent one; liveness APCER/BPCER by attack type recorded | - | INSUFFICIENT EVIDENCE | evaluator |
