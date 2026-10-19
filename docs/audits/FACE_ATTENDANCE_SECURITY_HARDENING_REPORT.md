# Face Attendance — Security Hardening Report

**Part A** (§1–16) is the 2026-10-16 review, preserved as written except for inline
`[superseded → Part B …]` pointers where a finding has since been addressed. **Part B** (after §16)
is the 2026-10-17 integrity and biometric-data hardening pass. **Part E** (at the end) is the
2026-10-18 base-release critical-fix pass: it is the current statement of what is fixed, what was
verified and what is still open for a limited release.

Date: 2026-10-16 (Part A), 2026-10-17 (Part B). Companion: `docs/operations/FACE_ATTENDANCE_STAGING_SECURITY_CHECKLIST.md`.
Earlier work: `FACE_ATTENDANCE_LIVENESS_IMPLEMENTATION_REPORT.md`, `FACE_LIVENESS_DOCKER_PACKAGING_REPORT.md`.

Labels: **[V]** verified in this session (code read or command run), **[H]** historical claim from an
earlier report, not re-checked, **[R]** recommendation or assumption.

## 1. Executive summary and verdict

**Verdict: ready for controlled staging evaluation; not production-ready; not fraud-proof.**

The server-side trust boundary already enforced the important controls. This session found and fixed
**two concrete gaps** and added measurement tooling and documentation. It did **not** add active
liveness, device attestation or contextual risk scoring, because none could be implemented
soundly in this architecture (§7, §8). The anti-spoofing accuracy gate stays open: no real-device or
real-attack measurement exists.

Changes made:
1. **An employee can no longer approve or reject their own face enrolment** (a real
   separation-of-duties gap; §5).
2. **Every rejected face punch now emits a redacted `security.face_punch.rejected` log event**, so
   spoof, replay and challenge-abuse spikes can be alerted on, not only found in the database.
3. `scripts/liveness/evaluate_captures.py`: an aggregate-only APCER/BPCER harness for the staging gate.
4. Staging checklist (all rows `NOT RUN`/`BLOCKED`) and this report.

## 2. Initial state

Branch `main`, HEAD `d0c55f4ed3f87941cbefed57544313bf348d0ab9`. The tree already contained the
uncommitted liveness and Docker-packaging work (38 status entries at the start of this task); all of it
was preserved. Nothing was staged or committed. The model assets remain untracked **[V]**.

## 3. Existing controls verified [V — by reading `face_service.py`, `service.py`, `router.py`]

| Control | Where |
| --- | --- |
| Self-service punch time is the server clock; the client cannot supply an instant | `punch_self(... requested_punch_time=None)` |
| Employee id comes from the authenticated user, tenant from the token; target visibility re-checked | `record_punch_outcome` → `_ensure_employee_visible` |
| Punch refused after last working day / in a closed period | `_ensure_not_after_last_working_day`, `_ensure_punch_date_open` |
| Challenge: employee + tenant + direction bound, 120 s TTL, one ISSUED per employee (partial unique index), burned in its own committed transaction before any work | `issue_liveness_session`, `_consume_session` |
| Replay: identical frames within a request and across the employee's earlier sessions rejected | `punch_self`, `any_digest_seen` |
| Client liveness verdicts never read; model runs on **every** frame; all must be LIVE; engine error, timeout, disabled → no punch | `assess_liveness`, `liveness_rejection` |
| Identity matched only on the best frame **of the same request** | `punch_self` (`best_frame_index`) |
| Idempotency: advisory lock + unique index; same key other employee/direction → 409; rejected attempt leaves key reusable | `_replay_if_recorded`, `record_punch_outcome` |
| Attempt limiting (5 failed / 10 min) also gates challenge issuance; 20 challenges / window | `_enforce_attempt_limit`, `issue_liveness_session` |
| Enrollment: HR-opened one-time window, consent flag, liveness on the front capture, every angle must match the front, Face++ person deleted on any failure, review photo deleted at decision | `submit_self`, `_verify_and_add_angles`, `approve` |
| Fallback for outages/false rejects is **separate**: regularisation writes `source='REGULARIZATION'` punches, with self-approval blocked, never a fake `FACE` punch | `service.py`, `models.py` |
| Frame bytes never reach logs; error responses carry no scores | tests in `test_liveness.py`, `test_face_punch.py` |
| Model files verified by SHA-256 at load; API refuses to boot when enabled with bad assets | `liveness.py`, `app.py` (Docker phase) |

## 4. Threat model

Control / weakness / mitigation / residual risk. "Server" = enforced on the backend.

| Threat | Existing control | Weakness found | Mitigation | Residual |
| --- | --- | --- | --- | --- |
| Printed photo, photo on screen, video replay | MiniFASNet on all 3 frames, fail-closed | Accuracy unmeasured on our devices/attacks | Harness + staging rows A1–A6 | **Open**: high-quality screens, good prints, 3D masks may pass |
| Request replay / challenge reuse | Burned challenge, TTL, digest dedupe | Only byte-identical reuse is caught | None feasible without capture-time proof | Re-encoded replays rely on the model |
| Modified app / fabricated API calls | Server ignores client verdicts | Frames can come from anywhere | Model only | **Not mitigated** (no attestation, no active check) |
| Virtual camera / injected frames | — | Not detectable by protocol | Attestation (decision needed), staging T6 measures it | **Open** |
| Employee substitution (accomplice) | Identity matched via Face++ on a liveness-passed frame | Frames 2–3 are liveness-checked, not identity-checked **[superseded → Part B §B2: every frame is now identity-checked]** | [R] option: match all frames (extra Face++ cost per punch) | Low; needs a product/cost decision |
| Employee/tenant id substitution | Id from token, RLS, scope checks | None found | — | Low |
| Unauthorised or self-approved enrolment | HR window, HR approval | **Enrollee holding the manage permission could approve their own face** | **Fixed** (§5) | A single-admin tenant needs a second reviewer |
| Repeated / concurrent punches | Advisory lock, unique index, idempotency | None found | — | Low |
| Key reuse with different inputs | Employee + direction must match | Frames differ by design (retry carries new frames) | Documented | Low |
| Face++ timeout / ambiguous result | 502, no punch, key reusable | None found | — | Low |
| Model unavailable / corrupted | Checksum + fail closed + boot refusal | None found | — | Low |
| Network loss mid-punch | Mobile keeps the key on unknown outcomes; same key resolves via idempotency | None found | — | Low |
| Automated abuse | Per-employee limits | No per-IP / per-device limit; enrolment submissions unthrottled within the 48 h window **[enrolment part superseded → Part B §B3]** | [R] limit enrolment attempts (needs a counter column/table) | Medium for Face++ cost |
| Admin attendance changes | Regularisation with self-approval block, audit log | Not re-audited here | — | Not assessed |
| Biometric leakage | No frames in logs/DB; digests only | `face_verification_attempt.provider_response` stores Face++ search bodies (face tokens, request ids, confidences) **[superseded → Part B §B4]** | [R] store only the confidence and decision | Low-medium |
| Rejections invisible to monitoring | DB attempt rows only | **No operational log event for spoof/replay/challenge rejections** | **Fixed** (§5); monitor check added in Part B §B6 | Alert *delivery* still unverified |

## 5. Changes made

| File | Change and reason |
| --- | --- |
| `src/hrms/modules/attendance/exceptions.py` | New `FaceEnrollmentSelfApprovalNotAllowedError` (403 `FACE_ENROLLMENT_SELF_APPROVAL_NOT_ALLOWED`), same stance as WD-28: always blocked, no policy field |
| `src/hrms/modules/attendance/face_service.py` | `approve` and `reject` refuse when the caller's employee is the enrollee (checked after the visibility check, so scope/404 behaviour is unchanged). `_record_rejection` emits `security.face_punch.rejected` (level warning; fields: `reason` = fixed decision code, `company_id`, `employee_id`, `liveness_session_id`; no scores, frames or provider data) |
| `tests/integration/modules/attendance/test_face_enrollment.py` | New: a user with manage + punch permissions, linked to the enrollee, cannot approve or reject; the profile stays pending; another reviewer can approve |
| `tests/integration/modules/attendance/test_face_punch.py` | New: a spoof rejection emits exactly one redacted event with the right reason and no score |
| `scripts/liveness/evaluate_captures.py` (new) | Labelled-manifest evaluation: per category/device counts of LIVE/SPOOF/INCONCLUSIVE/error, APCER/BPCER, p50/p95 latency. Aggregate output only; does not choose thresholds |
| `tests/unit/modules/attendance/test_liveness.py` | New: the harness's APCER/BPCER definitions |
| two docs | This report and the staging checklist |

**Behaviour change to confirm:** a tenant whose only enrolment reviewer is also an enrollee now needs a
second reviewer. This is intentional.

No thresholds, identity similarity values, idempotency, replay or authorisation rules were weakened or changed.

## 6. Model and threshold evaluation

**Not measured.** Only the earlier 3 upstream samples exist **[H]**, which do not establish real-world
accuracy. A smoke run of the new harness on one synthetic noise image gave `INCONCLUSIVE` (NO_FACE),
confirming the harness runs, nothing more. Thresholds `0.90`/`0.50` are unchanged and remain
uncalibrated. Score semantics, class mapping, error handling (malformed output → error, never a
verdict) and frame binding were reviewed in `liveness.py` **[V]**. Inference time ≈ 6 ms/frame on the
dev CPU **[H]**; not re-measured on a production-like host. The evaluation protocol is the checklist
sections 1–2 with the harness.

## 7. Active challenge-response — not implemented (blocker)

A randomised head-turn or blink would only add security if the server could verify the *temporal
sequence* from a fresh capture. Blockers **[V — nothing in the repository provides these]**:
no server-side landmark/pose model; the pipeline takes 3 still frames 200 ms apart, not a video; a
prerecorded sequence containing the requested motion would pass. A client-side animation without
server verification would be exactly the superficial control to avoid. A real implementation needs a
server pose/landmark model (new dependency, calibration, accessibility review) and a decision. It would
also not stop a modified client. **Decision needed; not started.**

## 8. Device integrity, risk signals — not implemented

- **Play Integrity / App Attest:** needs a provider-console project, signing configuration and
  credentials, and a mobile dependency not evaluated here. Contract proposed **[R]**: the app requests a
  server-issued nonce (the liveness session id) and sends an attestation token with the punch; the
  server verifies it and records the verdict. Treated as a supporting signal only, since it does not prove
  the frame came from the camera. Blocked on credentials and a decision.
- **Geofence, registered device, impossible travel, anomaly scoring:** no existing product requirement
  or data model was found for them in this task; adding location tracking is a product/privacy
  decision. Not implemented. Review-queue-style alerting should come after the rejection event (§5) is
  wired to monitoring **[R]**.

## 9. Enrolment review (Phase 6)

Verified **[V]**: authenticated employee only for self-submission; HR permission to open/cancel/approve/
reject/revoke; window is one-time and tenant/employee-bound; both liveness and Face++ checks run on the
front capture; angles must match; failures delete the Face++ person and review photo; profile is only
`PENDING_APPROVAL` until approved, so no partially active identity; re-enrolment needs revoke (audited)
plus a new window, and cannot overwrite an enrolled profile (`FACE_PROFILE_ALREADY_ENROLLED`).
Gaps: self-approval (**fixed**); enrolment liveness is single-frame with no challenge (documented
mitigation: HR window and review); rejected enrolment liveness checks leave no attempt/audit record and
submissions are unthrottled (**not fixed** in Part A) **[superseded → Part B §B3: attempts are now limited and recorded]**;
the four extra angle photos match the front photo but are not liveness-checked **[superseded → Part B §B3: each angle is now liveness-checked]**.

## 10. Tests and checks actually run

All against the local Docker Postgres/Redis (the previously used local containers) with mocked Face++,
mocked photo storage and a fake liveness engine; no real Face++ call, email or remote service.

| Check | Result |
| --- | --- |
| `pytest tests/integration/modules/attendance/test_face_enrollment.py` | 20 passed |
| `pytest tests/integration/modules/attendance/test_face_punch.py` | 24 passed |
| `pytest tests/unit/modules/attendance/test_liveness.py` | 46 passed |
| **Full backend `pytest tests`** | **2780 passed**, 4 warnings, 12 min 32 s, exit 0 |
| `ruff format --check .` | 584 files already formatted |
| `ruff check .` | 4 errors, all E501 in older migrations `20261007090000` and `20261008090000` (pre-existing, untouched); 0 in changed files |
| `mypy` | no issues, 195 source files |
| `lint-imports` (from `apps/api`, `PYTHONPATH=src`) | 1 kept, 0 broken |
| `flutter analyze` | no issues |
| Flutter face tests (`face_punch_card`, `face_liveness_capture`, `punch_idempotency`, `face_punch_result`) | all passed |

The Flutter full suite was not re-run; the mobile code was not changed in this session. The mobile
capture, retry-key and duplicate-tap behaviour was **not re-audited** beyond running those tests; it
is covered by the earlier work **[H]**.

Mocked tests prove contracts, ordering and fail-closed behaviour. They do not prove spoof resistance.

## 11. Database and migration

`20261015090000_face_liveness_session` was **not** run in this session. Nothing in this session
changes the schema. Staging application status is unknown **[R: confirm with the environment owner]**.

## 12. Privacy, retention, provenance

- Stored: SHA-256 frame digests, per-frame scores and decisions, Face++ search response bodies
  (opaque tokens, confidences), review photo until HR decides, Face++ holds enrolled face data. No
  frames, videos or embeddings in our DB or logs **[V by code and tests]**.
- **Retention is undefined and no purge job exists** for `face_liveness_session` or
  `face_verification_attempt` **[plumbing added in Part B §B5; the period is still undecided]**. Recommendation for approval, not implemented: set a retention period
  (HR/legal), then add a scheduled purge with an audit counter. I did not invent a period.
- Model: Apache-2.0 upstream, hashes pinned and verified **[V]**; training-data provenance
  undisclosed, so legal sign-off remains a production gate.

## 13. Unresolved risks and production blockers

1. No real-device/real-attack accuracy data; thresholds uncalibrated (checklist sections 1–2).
2. Modified clients and virtual cameras are not detected (no attestation, no verified active challenge).
3. Legal acceptance of the model's undisclosed training data; retention and purge undefined.
4. Model assets untracked in git; a clean CI build fails at `COPY models` until resolved.
5. ~~Enrolment submissions unthrottled; enrolment rejections not recorded; angle photos not liveness-checked.~~ **Addressed in Part B §B3.**
6. Alert delivery for the new event, and for failure spikes and dropped logs, is **not verified**. **Still open; a monitor check now exists (Part B §B6).**
7. ~~Face++ search bodies stored in attempt rows.~~ **Addressed in Part B §B4.**
8. Migration status in staging unknown; app and API must ship together.

## 14. Staging scenario status

All scenarios in the checklist are `NOT RUN` or `BLOCKED`. None is marked `PASS`.

## 15. Recommended next steps

1. Commit decision for the model assets; apply the migration in staging.
2. Run the staging checklist with consented participants and the harness; set thresholds from data.
3. Decide on device attestation and on an active challenge (each needs credentials or a server model).
4. Define retention, then implement the purge. *(Purge implemented but disabled; retention undecided — Part B §B5.)*
5. ~~Add an enrolment attempt limit and record enrolment rejections.~~ *(Done — Part B §B3.)*
6. Wire `security.face_punch.rejected` to an alert and test delivery. *(Monitor check added; delivery destination still not configured — Part B §B6.)*

## 16. Confirmation

No commit, push, merge, rebase, stash, reset, clean, tag or deployment was made. No service was
restarted and no remote command was run. No migration was run. No production or shared database,
Redis, object store, Face++ endpoint or email provider was used. Production face liveness was not
enabled. All pre-existing working-tree changes, including untracked files, were preserved.

---

# Part B — Integrity and biometric-data hardening (2026-10-17)

Status labels: **[T]** implemented and tested (automated, mocked provider/engine); **[I]** implemented, not fully tested;
**[N]** not implemented; **[M]** needs real-device or real-attack measurement; **[A]** needs business/privacy/legal approval;
**[S]** needs staging infrastructure or external-provider setup.

## B0. Verdict

Still **not production-ready and not fraud-proof.** Six outstanding risks were addressed in code; the
measurement, approval and alert-delivery gates in Part A are unchanged and open. Nothing here was run against
real Face++, real devices, a shared database or production.

## B1. Baseline (before changes)

Working tree: the 38-entry uncommitted liveness/hardening state plus Part A docs, all preserved. Baseline
focused run: 148 passed (enrollment, punch, idempotency, liveness-session, Face++ adapter, liveness unit).

Findings from tracing the code **[V]**:
- Punch: `punch_self` ran liveness on all frames but called `provider.verify` once, on the best frame.
- Face++ design: one FaceSet **per employee**; `verify(person_id=faceset_token, …)` searches only that
  employee's FaceSet (`face_verification.py`). So a per-frame check against the *expected* identity is directly
  supported by the existing contract; no provider field was invented.
- The adapter took `faces[0]` when `detect` returned several faces (ambiguity silently resolved).
- Enrollment: the window stays OPEN after a failed submission → unlimited tries for 48 h; nothing recorded.
- Raw Face++ search bodies were stored under `provider_response.verify`. Only consumers: tests, and a staging
  checklist reference to `provider_response.liveness` (kept). No application code read the stored body.
- `security.face_punch.rejected` was only a log line; the repo's established alert path is
  `infra/monitoring/hrms_monitor.sh` → `HRMS_ALERT_COMMAND`, which had no face check; **no alert destination is configured**.
- No retention or cleanup existed for any face table.

## B2. Identity verified on every punch frame **[T]**

`FacePunchService.punch_self`: after all frames pass liveness, **every** frame is verified against the employee's
own FaceSet (`profile.provider_person_id`, from the token's employee, never a tenant-wide search). The
best-liveness frame goes first; checking stops at the first failure.
- Any frame NO_FACE → `NO_FACE`; several faces → `AMBIGUOUS_FACE` (422 `FACE_MULTIPLE_FACES`);
  not matching → `NO_MATCH` (first frame) or `IDENTITY_INCONSISTENT` (an earlier frame matched, a later one did not);
  provider error → `PROVIDER_ERROR` (502); unknown verdict, `MATCHED` without a similarity, or `MATCHED` below
  `face_match_min_similarity` → rejection. Fail closed throughout; an explicit post-loop invariant requires one
  MATCHED verdict per frame.
- Reported similarity = the **weakest** frame.
- Adapter: several faces in a frame is ambiguity (no search is made); every `results` entry must be well formed
  (one bad entry = provider error); best confidence decides.
- Unchanged: tenant/employee binding, challenge burn-before-work, expiry, direction binding, replay digests,
  advisory-lock idempotency, attempt limits, server clock. No attendance row is written on any failure; the
  challenge stays burned; the idempotency key stays reusable.
- **Cost/latency [M][S]:** a punch now makes 3 detect + 3 search calls (6 requests) instead of 2. Latency and Face++
  quota/QPS (Face++ may return `CONCURRENCY_LIMIT_EXCEEDED`) are unmeasured. Calls are sequential on purpose.
- **Limit:** per-frame identity proves each frame shows the employee; it does not prove the frames came from a live
  camera (virtual camera / injected real frames remain **[N]**, Part A §8, checklist T6).
- **Real-provider behaviour [S]:** treating `detect` returning >1 face as ambiguity is our policy; how often Face++
  reports background faces on genuine captures is unmeasured (checklist G10).

## B3. Enrollment abuse protection **[T]**

- Table `face_enrollment_attempt` (migration `20261017090000`): decision, angle, window id, employee, requester, time.
  No image, score or provider data. Decisions: `SPOOF_SUSPECTED`, `LIVENESS_INCONCLUSIVE`, `NO_FACE`, `MULTIPLE_FACES`,
  `ANGLE_MISMATCH`, `INVALID_IMAGE`, `LIVENESS_ERROR`, `PROVIDER_ERROR`. Written in its own committed transaction.
- Limit `FACE_ENROLLMENT_MAX_FAILED_ATTEMPTS` (default 5) **per HR-opened window** (tenant + employee + window;
  the requester is always the authenticated employee). Reopening the window is an HR action and resets the count.
  `PROVIDER_ERROR` and `LIVENESS_ERROR` are recorded but not counted, so an outage never locks anyone out.
- Concurrency: submissions already lock the window row `FOR UPDATE`, so concurrent submissions queue and each sees the
  previous one's committed rejection. Test: 9 concurrent failing submissions → exactly 5×422 and 4×429, 5 rows.
- DoS: only the authenticated employee's own session adds to their count; a refused request does no engine/provider
  work and writes nothing; no unauthenticated path was added. Cheap validation errors (bad image type, no consent)
  are not counted.
- Error code (new, stable): **429 `FACE_ENROLLMENT_ATTEMPTS_EXCEEDED`** — "Too many unsuccessful face enrollment
  attempts. Ask HR to open a new enrollment window." No reason, score or provider detail.
- Event `security.face_enrollment.rejected` (fixed `reason`, `angle`, ids). Volume bounded by the limit.
- Reviewer separation and the self-approval ban are untouched (re-tested).
- **Angle liveness [T for the contract, M for accuracy]:** the existing engine takes a single frame, so each of the
  five captures now gets its own server-side liveness call before anything is sent to Face++. A spoofed *turned* photo
  is rejected with the angle recorded (tests for left/right/up/down). The model has not been measured on turned/tilted
  heads; false rejects there would burn the 5 attempts (checklist G9). No client-side check is used.
- Angle photos with several faces count as `ANGLE_MISMATCH`.

## B4. Biometric data minimisation **[T]**

- `FaceMatchResult` is now `(decision, similarity, provider_request_id)`; the raw body never leaves the adapter.
  `provider_request_id` is Face++'s correlation id, kept only if it matches `^[A-Za-z0-9._:-]{1,64}$`.
- `face_verification_attempt.provider_response` (column name kept, so rollback needs no rename) now holds
  `{"liveness": {...}, "identity": {"primary_frame": n, "frames": [{index, decision, similarity, request_id}]}}`.
  No face tokens, rectangles, landmarks, thresholds, image ids or FaceSet tokens. Tests assert the exact key sets and
  absence of `face_token`/`face_rectangle`/`landmark`/`faceset`/`embedding`.
- Provider error logging: only the leading `UPPER_SNAKE` code of `error_message` is logged (`error_code`);
  echoed tokens/keys are dropped; unrecognisable text → `UNKNOWN`. Tests cover key, secret, faceset and face token.
- `provider_person_id` on attempts is still written (needed while a row is live); erased by retention (B5).
- **Migration** `20261017090000` also rewrites existing rows: `provider_response.verify` → `identity.{legacy_redacted,
  request_id}` (verified on a scratch table). **Irreversible**: the downgrade restores schema only.
- Not changed: Face++ itself holds the enrolled faces (FaceSets) — that is the matching data, not application storage.

## B5. Retention and cleanup — plumbing **[T]**, periods **[A]**

| Record | Holds | Why kept | Cleanup action | Period |
| --- | --- | --- | --- | --- |
| `face_liveness_session` | challenge state, SHA-256 frame digests | single-use + cross-session replay detection | delete when older than the period; never an unexpired ISSUED one | **undecided [A]**; must cover the replay horizon the business wants |
| `face_verification_attempt` | outcome, similarity, liveness score, punch link, per-frame detail | attendance-dispute evidence, rate limiting | **keep row**; erase only `provider_response` and `provider_person_id` after the period; never delete | **undecided [A]** |
| `face_enrollment_attempt` | rejected-submission decision/angle | abuse review, limit counting | delete after the period | **undecided [A]** |
| punches, attendance days, regularisations, face profiles, audit log | — | — | **never touched** | — |

No period is defaulted (`FACE_LIVENESS_SESSION_RETENTION_DAYS`, `FACE_ATTEMPT_DETAIL_RETENTION_DAYS`,
`FACE_ENROLLMENT_ATTEMPT_RETENTION_DAYS` unset ⇒ nothing happens). Even when set, the scheduled run reports only until
`FACE_CLEANUP_DRY_RUN=false`. Implementation: `modules/attendance/face_cleanup.py`; Beat `attendance.run_face_cleanup`
daily 03:15 (a no-op while unconfigured) fans out per company; manual: `python -m hrms.modules.attendance.face_cleanup`
(report) / `--apply` / `--company-id`. Bounded batches (`FACE_CLEANUP_BATCH_SIZE`, `FACE_CLEANUP_MAX_BATCHES`),
`FOR UPDATE SKIP LOCKED`, per-company RLS scope, eligible-only statements ⇒ idempotent and safe to retry or overlap.
Legal/operational hold: `FACE_CLEANUP_HOLD_COMPANY_IDS` (whole company only; a per-employee hold needs a data model — **[N]**).
Monitoring: `face_cleanup_finished` log (counts, `truncated`), failures surface as `task_failures`.
Tests (9) cover defaults, unset periods, dry run, apply + idempotency, active challenge kept, batch bounds, hold,
tenant isolation, punches untouched and idempotent replay after a scrub.
Deletion vs disputes: because the attempt row and its scores are kept, a dispute after the detail period can still see
the decision and scores but not per-frame detail — the approver should confirm that is enough.

## B6. Rejection monitoring **[I]**

Trace: `_record_rejection` → DB attempt row + `security_event("face_punch.rejected")` → API JSON stdout → docker logs →
`infra/monitoring/hrms_monitor.sh` (cron, stateless) → `HRMS_ALERT_COMMAND`. New checks: `face_rejections`
(>10 punch/enrollment rejections per 5 min, medium) and `face_spoof_signals` (>3 with reason `SPOOF_SUSPECTED`,
`CAPTURE_REPLAYED`, `IDENTITY_INCONSISTENT`, `AMBIGUOUS_FACE`, `MULTIPLE_FACES`, high); thresholds provisional and
overridable (`HRMS_MAX_FACE_REJECTIONS`, `HRMS_MAX_FACE_SPOOF_SIGNALS`); runbook added. Tested against the fake-docker
harness (incl. "8 ordinary rejections do not alert"). **Alert delivery is NOT verified and no destination is
configured in the repository** — that needs a real `HRMS_ALERT_COMMAND` (**[S]**, checklist L3/L3a).
Log injection/volume: `reason` is checked against a fixed vocabulary (else `UNKNOWN`), all other fields are UUIDs or
fixed strings, output is structured JSON; emissions sit behind the 5-failures/10-min punch limit and the 5-per-window
enrollment limit.

## B7. Open items found, not changed

- **Termination does not remove face data**: nothing in the employee module revokes `employee_face_profile` or deletes
  the Face++ FaceSet when someone leaves (grep-verified). A product/privacy decision plus a change in another module. **[A]**
- Per-employee legal hold; device attestation; verified active challenge; injected-frame detection (Part A §7–8). **[N]**
- Alert destination/ownership. **[S]**
- Enrollment liveness is still single-frame without a challenge (HR window + review remain the compensating controls).

## B8. Migration `20261017090000_face_integrity_hardening`

Creates `face_enrollment_attempt` (RLS, `tenant_isolation`); adds age indexes on `face_liveness_session` and
`face_verification_attempt`; extends the attempt `decision` check with `AMBIGUOUS_FACE`, `IDENTITY_INCONSISTENT`;
scrubs stored Face++ bodies (irreversible). Compatibility: API and migration must ship together (the new code writes the
new decisions). Rollback: `alembic downgrade 20261015090000` — drops the table, maps the two new decisions to `NO_MATCH`;
erased bodies are not restored. Applied **only** to a throwaway clone (`hrms_face_hardening_test`, cloned from the local dev DB);
upgrade → downgrade → upgrade round trip run there. Not applied to `hrms_dev` or anything shared.

## B9. Changed files

New: `alembic/versions/20261017090000_face_integrity_hardening.py`, `modules/attendance/face_cleanup.py`,
`tests/integration/modules/attendance/test_face_integrity_hardening.py`, `…/test_face_cleanup.py`.
Modified (this pass): `face_service.py`, `face_verification.py`, `models.py`, `repository.py`, `exceptions.py`, `tasks.py`,
`core/celery_app.py` (one Beat entry), `core/config/settings.py`, `.env.example`, tests `conftest.py`, `test_face_enrollment.py`,
`test_face_punch.py`, `test_face_punch_idempotency.py`, `test_face_liveness_session.py`, `test_face_verification.py`,
`tests/unit/ops/test_host_monitor.py`, `infra/monitoring/hrms_monitor.sh`, `docs/operations/ALERTS_AND_RUNBOOKS.md`,
this report and the staging checklist. No mobile code changed (the client shows server messages and maps no codes).

## B10. Commands run and results (all against local docker Postgres clone / Redis, mocked Face++ and liveness, logging email, Celery broker DB 15)

| Check | Result |
| --- | --- |
| Baseline focused face suite | 148 passed |
| Full backend `pytest tests` (`DATABASE_URL`=clone) | **2840 passed**, 4 warnings, 12 min 21 s, exit 0 |
| After the final similarity-floor edit: `pytest -k "face or liveness or monitor"` over attendance integration+unit and ops | 248 passed (the full suite predates this one edit and its added test case) |
| `ruff format --check .` | 588 files already formatted |
| `ruff check .` | 4 errors, all the **pre-existing** E501 in migrations `20261007090000`, `20261008090000`; 0 new |
| `mypy` | no issues, 196 source files |
| `lint-imports` | 1 kept, 0 broken |
| Flutter `face_punch_card`, `face_liveness_capture`, `punch_idempotency` | 30 passed (full Flutter suite not run; no mobile change) |

## B11. Incident during verification (disclosed)

My first test run used the default `DATABASE_URL` (local `hrms_dev`) **before** the new table existed, so the updated
fixture teardown failed mid-way and ~83 test tenants (companies with `@acme.example` admins, 78 `scoped-*` users, created
2026-10-17 11:22–11:23 UTC) were left in `hrms_dev`. Automated cleanup of `hrms_dev` was blocked by the harness's
permission check, so **it has not been cleaned**; it needs the owner's decision (script: the scratchpad
`cleanup_my_run.py`, which reuses the suite's teardown helpers). The same leftovers in my own clone were removed.
No migration was run on `hrms_dev`; its schema is unchanged.

## B12. Residual risks (ranking by importance)

1. No real-device/real-attack data; thresholds uncalibrated; turned-angle enrollment liveness unmeasured. **[M]**
2. Injected/virtual-camera frames and modified clients undetected. **[N]**
3. Alert delivery unverified; no destination. **[S]**
4. Retention periods undecided; face data survives employee termination. **[A]**
5. 3× Face++ cost/latency per punch unmeasured; possible false `AMBIGUOUS_FACE` from background faces. **[M][S]**
6. Model training-data provenance and untracked model assets (Part A §13.3–4).

## B13. Confirmation

No commit, push, merge, stash, reset, clean, deploy or service restart. No production or shared database used; the only
schema change was to a clone I created. No real Face++ call, email or external API. Pre-existing working-tree changes preserved.

---

# Part C — Final engineering verification and staging gate (2026-10-17)

Scope: verification only, no redesign. Labels as in Part B ([T] tested, [I] implemented not fully tested, [N] not implemented,
[M] needs real-device/attack measurement, [A] needs approval, [S] needs staging/provider setup).

## C0. Status

**Engineering verification: complete and passing for everything that can be verified locally with mocks.**
**Staging gate: NOT passed** — every checklist scenario is still `NOT RUN`/`BLOCKED`. Not production-ready, not fraud-proof.

## C1. Isolation used (verified before running, not assumed)

| Resource | Value |
| --- | --- |
| Test database | `hrms_final_verify2` — newly created, local docker Postgres (`hrms-postgres`, port 5433); provisioned like CI: `001_extensions.sql`, `002_app_role.sh`, then `alembic upgrade head` (head `20261017090000`) |
| App Redis | `redis://localhost:6380/14` (empty beforehand); **DB0 never used** |
| Celery broker/backend | `redis://localhost:6380/15` (the suite's forced test DB) |
| Email / Face++ / liveness | `logging` / `disabled` + mocks / fakes — printed from the resolved settings before the run |
| `hrms_dev` | read-only inspection only (server-enforced `default_transaction_read_only=on`; a probe `CREATE TABLE` was refused) |

## C2. Final regression results

| Check | Command (abbrev.) | Result |
| --- | --- | --- |
| **Full backend suite, after the similarity-floor edit** | `DATABASE_URL=…/hrms_final_verify2 REDIS_URL=…/14 HRMS_TEST_CELERY_DB=15 pytest tests -q` | **2852 passed**, 4 warnings, 12 min 23 s, **exit 0** |
| Earlier attempt, same code, **mis-provisioned** DB `hrms_final_verify` (created without the CI init scripts, so no `hrms_app` grants) | same | 7 failed / 2840 passed — all `permission denied for table pay_run / pay_run_employee / pay_adjustment / leave…` for the `hrms_app` runtime-role tests (6 payroll `test_b05_db_immutability`, 1 leave `test_leave_hardening`). **Cause: my provisioning, not the code** — proven by the identical tests passing on a correctly provisioned DB. Log kept as `final_suite_run1_unprovisioned.log` in the session scratchpad |
| Similarity-floor change | `face_service.py` (re-check `similarity >= face_match_min_similarity` per frame) covered by the `MATCHED 0.5000` case in `test_face_integrity_hardening.py` | passes inside the full run |
| New this pass: cleanup scheduling/CLI | `tests/unit/modules/attendance/test_face_cleanup_scheduling.py` | 5 passed |
| `ruff format --check .` | | 589 files already formatted, exit 0 |
| `ruff check .` | | 4 errors, all **pre-existing** E501 in `20261007090000` (×2) and `20261008090000` (×2); **0 new** |
| `mypy` | | no issues, 196 source files |
| `lint-imports` | | 1 kept, 0 broken |
| Flutter face tests (`face_punch_card`, `face_liveness_capture`, `punch_idempotency`, `face_punch_result`, `face_pose_tracker`) | `flutter test …` | 39 passed |
| `flutter analyze` | | No issues found |

Not run: the full Flutter suite (no mobile change in this work).

## C3. Migration `20261017090000` — validation on disposable DBs only

Fresh-from-empty chain to head (`hrms_final_verify`, `hrms_final_verify2`): applies cleanly. Round trip on `hrms_final_migtest` with seeded rows:

| Step | Observed |
| --- | --- |
| Upgrade with legacy rows (one with a raw body containing a face token) | 0.37 s; token occurrences 1 → **0**; all 4 rows kept; legacy rows now `identity:{legacy_redacted:true, request_id}`; rows without `verify` untouched; `NULL` stays `NULL` |
| Schema | table + RLS (enabled **and** forced) + `tenant_isolation` policy; 5 expected indexes; new decisions accepted; bogus decision / angle rejected by CHECKs |
| Downgrade (with new-decision rows and an enrollment attempt present) | version back to `20261015090000`; `face_enrollment_attempt` **dropped (its rows are destroyed)**; `IDENTITY_INCONSISTENT`/`AMBIGUOUS_FACE` rows **mapped to `NO_MATCH`** (information lost); the age indexes removed; new decisions rejected again. **The erased Face++ bodies are not restored** — rows keep `legacy_redacted:true`, so the data does not falsely claim to be the original |
| Re-upgrade, then a second `upgrade head` | succeeds; second is a no-op |

Locking/compat review: runs in one transaction. Non-concurrent `CREATE INDEX` on two existing tables (SHARE lock, blocks writes while building) and the `DROP/ADD CONSTRAINT` check rewrite (scans and locks the table) are cheap on today's small tables; on a large table schedule it in a quiet window. Older application code against the new schema is fine (new table and decisions unused); **new code against the old schema fails**, so migrate before deploying.

**Recovery strategy.** Treat the migration as forward-only in practice. To back out the feature: `FACE_LIVENESS_ENGINE=disabled` (face punches 503, other punch types unaffected), leave the schema in place. Only if a schema downgrade is unavoidable: first export `face_enrollment_attempt` and the `IDENTITY_INCONSISTENT`/`AMBIGUOUS_FACE` attempt rows, and accept that erased bodies cannot be recovered (take a database backup *before* upgrading anywhere that matters; that is the only way to get them back).

## C4. `hrms_dev` cleanup investigation — **DRY RUN / NOT EXECUTED**

Read-only queries only. Target verified first: container `hrms-postgres`, database `hrms_dev`, `default_transaction_read_only=on`.
No row was inserted, updated or deleted; `cleanup_my_run.py` was not run against it.

| Finding | Value |
| --- | --- |
| Schema state | head `20261015090000`; `face_enrollment_attempt` does not exist → **migration was never applied to `hrms_dev`** |
| Candidate window | `company.created_at` in 2026-10-17 11:22:00–11:24:00 UTC |
| Candidate companies | **83** (12 in minute 11:22, 71 in 11:23), all status TRIAL, **all** named `Acme <10 hex>` |
| Candidate users | **161** = 83 admins `priya-<10 hex>@acme.example` (one per company) + 78 `scoped-*@example.com` |
| Audit actions on candidates | only `COMPANY_REGISTERED`, `EMPLOYEE_CREATED`, `FACE_ENROLLMENT_OPENED`, `FACE_ENROLLMENT_CANCELLED`; span 11:22:54–11:23:29 UTC |
| Activity after the run | none (latest session 11:23:29.97) |
| Referential closure | no candidate user belongs to any non-candidate company; 0 rows outside the candidate companies reference a candidate user (`user_company`, `session`, `refresh_token`, `audit_log`, `face_enrollment_window`) |
| Candidate rows by table | audit_log 325 (of 784), company_setup_progress 83 (of 90), employee 81 (81), face_enrollment_window 77 (77), number_series 80 (80), refresh_token 83 (of 91), role 493 (of 530), session 161 (of 169), user_company 161 (of 171); plus `company` 83, `user` 161, `email_verification_token` 83 (via user) |
| Confidence | High but not proof: nothing records a test-run id. Attribution rests on the exact pattern, a 35-second window, closed references and no later activity |
| **Ambiguity / manual review** | (1) the owner must confirm no human registered `@acme.example` accounts in that window; (2) **7 older `Acme …` companies + 7 admins from 2026-10-16 14:38 UTC** are the same kind of test leftover from earlier runs but **outside this scope** — separate decision; (3) `Demo Company A/B` are seed data, never candidates; (4) the suite's own `_cleanup_scoped_users` deletes *every* `scoped-%` user globally — never use it as the criterion |
| **Proposed exact scope (not executed)** | delete by **explicit ID lists**, not patterns: the 83 company ids and 161 user ids exported (read-only) to the session scratchpad (`hrms_dev_candidate_company_ids.txt`, `…_user_ids.txt`), dependents first (face tables, attendance/employee tables, `audit_log`, `session`, `refresh_token`, `email_verification_token`, `user_company`, `role`/`role_permission`, setup/feature/subscription rows), then `user`, then `company`, inside one transaction with expected counts asserted (83/161) and a rollback on any mismatch, after a database backup, and only after the owner authorises it |

## C5. Retention and monitoring safety — verified

| Property | Evidence |
| --- | --- |
| No period invented | defaults `None` for all three; `test_nothing_is_configured_by_default`; settings unit test |
| Nothing deleted while unset | `test_unset_periods_delete_nothing_even_when_not_a_dry_run`; Beat task returns 0 and dispatches nothing (`test_unset_retention_dispatches_nothing`); CLI prints "no retention period configured" |
| Dry run is the default | `face_cleanup_dry_run=True` default; scheduled run follows it; CLI needs explicit `--apply` (`test_cli_without_apply_is_a_dry_run`) |
| Bounded, retry-safe | `test_batches_are_bounded_and_a_later_run_continues`; `test_apply_removes_only_expired_records_and_is_idempotent` |
| Company hold | `test_company_on_hold_is_untouched` |
| Attendance data protected | `test_cleanup_never_removes_punches_and_an_idempotent_replay_still_works`: punches intact, MATCHED attempt row kept (only detail NULLed), replay by key still returns the original punch |
| Monitor checks | `test_host_monitor.py` 39 passed incl. `face_rejections` (punch and enrollment events) and `face_spoof_signals` (SPOOF_SUSPECTED, IDENTITY_INCONSISTENT) and a no-alert case for 8 ordinary rejections |
| **Alert destination** | **still unconfigured**: `HRMS_ALERT_COMMAND` appears nowhere in the repository's configuration (only in the script's own docs). Delivery is unverified. Nothing was configured |

## C6. Remaining blockers and required approvals

1. Staging run of the whole checklist with consented participants and devices **[M][S]** (none executed).
2. Real Face++ behaviour: multi-face handling, 6 requests/punch quota and latency **[S][M]**.
3. Alert destination, owner, and an end-to-end delivery test **[S]**.
4. Retention periods, legal-hold process, dispute-evidence sufficiency **[A]**.
5. Face data on employee termination (no automatic revoke) **[A]**, a change in another module.
6. Owner decision on the `hrms_dev` leftovers (83 + 7) **[A]**.
7. Device attestation, verified active challenge, injected-frame detection **[N]**.
8. Model training-data provenance sign-off; model assets still untracked in git.

## C7. Files changed in this verification pass

Added: `tests/unit/modules/attendance/test_face_cleanup_scheduling.py`. Reports updated: this file and
`docs/operations/FACE_ATTENDANCE_STAGING_SECURITY_CHECKLIST.md`. No source changed in this pass.
Created (local, disposable, untouched by anything shared): databases `hrms_final_verify`, `hrms_final_verify2`,
`hrms_final_migtest`, and (earlier) `hrms_face_hardening_test`. They hold only test data and may be dropped by the owner.

## C8. Confirmation

No rows were deleted or updated in `hrms_dev`; no migration was run against `hrms_dev`, any shared or production database;
the cleanup script was not run against `hrms_dev`; nothing was committed, pushed, merged, deployed or restarted; no real
Face++ call or email; Redis DB0 untouched.

---

# Part D — Staging readiness preparation (2026-10-17)

Scope: preparation only. No application behaviour was changed. Companion documents:
`docs/operations/FACE_ATTENDANCE_STAGING_READINESS_PLAN.md` (plan, protocol, worksheets) and the staging checklist, sections 9–18.

## D0. Verdict

**Staging execution: `BLOCKED`.** The repository defines no staging environment (no staging compose project, no env template, no hosts or credentials),
there is no Face++ test account on record and no alert destination. The plan, protocol, evaluation tooling, approval worksheets and a
71-row register are prepared. Of the 71 new register rows, **61 are `BLOCKED` and 10 are `NOT RUN`; none is `PASS` or `FAIL`.**
This is not production readiness and not a claim of fraud-proof behaviour; the passive three-frame approach cannot detect injected or virtual-camera frames.

## D1. What this pass produced

| Output | Content |
| --- | --- |
| Handover matrix | plan §A — verified locally / reported / needs staging / needs devices / needs approval |
| Staging deployment plan | plan §B — secret inventory, model checksums, backup/restore, migration preflight and post-check SQL (tested read-only on a disposable DB), queue isolation, health, rollback levels, the irreversible-erasure statement |
| Evaluation protocol | plan §C — consent and data handling, calibration/holdout discipline, scenario matrix, metric definitions with numerators/denominators/exclusions/independence, target worksheet (no targets adopted), limitations |
| Evaluation tooling | `apps/api/scripts/liveness/summarise_trials.py` + 16 unit tests: outcome-log summariser (no biometric data), enforces disjoint participants across splits, refuses holdout reporting without a frozen-config declaration, never merges splits |
| Alerting readiness | plan §D — what the monitor checks, frequency, output, consumer (none), investigation workflow, requirements to make alerting operational |
| Approval worksheet | plan §E — 13 decisions, each with decision-maker and evidence needed |
| `hrms_dev` decision record | plan §F — six-step process and blank sign-off table; deletion **not** performed |
| Checklist | sections 9–18: ENV, MB, RD, CH, LQ, AL, LC, PV, SP, FS with owner, prerequisites, procedure, expected, actual, evidence, sign-off, status |

## D2. Observations from inspecting the repository (new evidence this pass)

1. **The monitor is not scheduled anywhere.** `hrms_monitor.sh` runs only if an operator installs the cron entry; its default compose project is `hrms-prod`, so a staging run
   must set `HRMS_COMPOSE_PROJECT`/`HRMS_COMPOSE_CMD`. Alerting is therefore not operational in any environment.
2. **Provider errors count toward the punch attempt limit.** `FaceAttemptRepository.count_failed_since` counts every non-`MATCHED` attempt, including `PROVIDER_ERROR` and
   `LIVENESS_ERROR`. During a Face++ outage employees can reach `FACE_ATTEMPTS_EXCEEDED` (5 per 10 minutes) through no fault of their own. Enrollment deliberately does not
   count them. This is pre-existing behaviour, not changed here; it is recorded as checklist row LQ-4 and needs a PRD decision (count them, or not).
3. **A database restore resurrects data that cleanup or revocation removed**, and may reference Face++ FaceSets that no longer exist. A post-restore reconciliation step does not exist (LC-6, plan E10).
4. **No staging environment template exists** (`apps/api/env/` holds only a README); the face variables are in no template.
5. **Model assets are untracked** (`git ls-files apps/api/models` = 0). The Docker doc says they are committed; a clean-checkout build fails at `COPY models`. Pre-existing and already listed; now a row (ENV-3).
6. `FACE_LIVENESS_DOCKER_DEPLOYMENT.md` and `STAGING_VALIDATION_CHECKLIST.md` B-21 mention only migration `20261015090000`; pointer notes were added so the second migration is not missed.
7. A single-admin tenant cannot approve its own enrollment (by design) — every tenant using face attendance needs a second reviewer (SP-5).
8. A defect in my own new tooling was found and fixed by its tests: enrollment rates counted participants whose only submissions were excluded errors in the denominator. Fixed before use.

No resolved engineering issue was reopened; items 1–3 and 7 are operational/decision items, not code regressions.

## D3. Checks actually executed this pass, and results

| Check | Result |
| --- | --- |
| Resolve `Settings` defaults (retention, dry-run, limits, thresholds, engine/provider) | all as documented: retention `None` ×3, `face_cleanup_dry_run=True`, hold list empty, limits 5/5, engine and provider `disabled` |
| `pytest tests/integration/modules/attendance/test_face_cleanup.py tests/integration/modules/attendance/test_face_integrity_hardening.py` against disposable DB `hrms_final_verify2` (Redis DB14, Celery DB15, logging email, mocked Face++/liveness) | **36 passed** |
| `pytest tests/unit/modules/attendance/test_evaluation_summary.py tests/unit/modules/attendance/test_face_cleanup_scheduling.py tests/unit/ops/test_host_monitor.py` | **60 passed** (16 + 5 + 39) |
| Migration preflight/post-check SQL (plan §B5), run inside a read-only session against `hrms_final_verify2` | all queries run; outputs `20261017090000`, `t / t / tenant_isolation / t`, `0`, `t` (a malformed draft of POST-4 was corrected and re-run) |
| `ruff format --check .` | 591 files already formatted |
| `ruff check .` | 4 errors, all the pre-existing E501 in `20261007090000` (×2) and `20261008090000` (×2); 0 new |
| `mypy` (project) and `mypy scripts/liveness/summarise_trials.py` | no issues |
| Read-only verification that `/health/live`, `/health/ready` exist, the four model hashes match the code and the deployment doc, exit codes of the monitor, the error codes listed in SP-6 | confirmed by reading source |

**Not re-run (reported baseline only):** full backend suite (2,852), Flutter face tests (39), `flutter analyze`, import-linter, migration upgrade/downgrade/re-upgrade round trip.
No application code changed in this pass, so no reason to repeat them.

## D4. Required decisions and owners (detail: plan §E, §C7, §F)

| Decision | Owner |
| --- | --- |
| Retention periods (sessions, attempt detail, enrollment attempts); legal-hold process | DPO, HR, LEGAL |
| Termination clean-up policy (HRMS + Face++) and whether to build it | HR, DPO (then API for the employee-module change) |
| Consent/notice wording; evaluation-data handling; privacy impact assessment if required | LEGAL, DPO, HR |
| Model training-data/licence acceptance; Face++ terms and region | LEGAL, SEC, DPO |
| APCER/BPCER, latency, cost and lock-out targets (pre-registered before data collection) | SEC, PRD, HR |
| Accept/mitigate injected-frame risk; device attestation; active challenge | SEC, PRD |
| Alert destination, recipients, escalation path | SEC, STG |
| Whether provider outages should count toward the punch attempt limit | PRD, SEC |
| Commit the model assets so images can be built from a clean tree | STG, SEC |
| Staging environment, Face++ test account, device matrix, evidence store | STG, SEC, QA |
| `hrms_dev` leftover cleanup (six-step process) | database owner |

## D5. Files changed in this pass

Added: `docs/operations/FACE_ATTENDANCE_STAGING_READINESS_PLAN.md`, `apps/api/scripts/liveness/summarise_trials.py`,
`apps/api/tests/unit/modules/attendance/test_evaluation_summary.py`. Appended: this report (Part D), the staging checklist (sections 9–18),
`docs/operations/FACE_LIVENESS_DOCKER_DEPLOYMENT.md` and `docs/operations/STAGING_VALIDATION_CHECKLIST.md` (one pointer note each).
No application source, migration, configuration or infrastructure script changed.

## D6. Actions not performed

No deployment; no migration against any shared, production or `hrms_dev` database; no row deleted or updated in `hrms_dev` and no cleanup script run;
no database dropped; no real Face++ call; no email or alert sent; no external service or credential created; Redis DB0 untouched; no commit, push, merge or service restart.
No staging result, device result, alert delivery, model accuracy or sign-off has been recorded, because none exists.

---

# Part E — Base-release critical fixes and deployment readiness (2026-10-18)

Labels as in Part B: **[T]** implemented and tested (automated; fake Face++/engine/storage), **[I]** implemented, not fully
tested, **[N]** not implemented, **[M]** needs real-device/real-attack measurement, **[A]** needs a business/privacy/legal
decision, **[S]** needs staging infrastructure or the real provider. **[V]** = verified in this pass by reading code or running a
command. Companion: `docs/operations/FACE_ATTENDANCE_BASE_RELEASE_RUNBOOK.md` (procedure) and the checklist's section 19.

## E0. Verdict — three separate questions

| Question | Answer |
| --- | --- |
| **Code verification** (do the fixes work, locally, against fakes?) | **Yes.** The critical software defects below are fixed and covered by automated tests; results in E6. |
| **Staging readiness** | **Not yet established.** Nothing was run against real Face++, real devices, a staging environment, a load test or alert delivery. Section 19 of the checklist is the work list; every row is `NOT RUN`. The change set is *ready to be put on staging*. |
| **Production approval** | **Not granted and not claimable.** Open: real-device/attack calibration, vendor limits, retention/exit-deletion/consent/cross-border decisions, alert delivery, load capacity (E8). |

**Release mode: A — face verification is optional** (E4). It is supplementary evidence. It is **not** an anti-buddy-punching
control and must not be described as one. Mandatory face attendance (mode B) is **not implemented** (a product decision).

## E1. Reported findings, independently traced

Every finding was checked against the current code before any change. "Confirmed" means the behaviour described was present.

| # | Reported finding | Verified evidence [V] | Severity | Result |
| --- | --- | --- | --- | --- |
| 1 | Lockout counts provider/liveness errors | `FaceAttemptRepository.count_failed_since` counted every `decision != 'MATCHED'`; `PROVIDER_ERROR` and `LIVENESS_ERROR` rows are written on every provider/engine failure; 5 in 10 minutes ⇒ `FACE_ATTEMPTS_EXCEEDED`, and app retries extended it. (Enrollment already exempted them; punching did not.) | High (availability) | **Confirmed — fixed [T]** |
| 2 | Enrollment holds DB locks across ~18 provider calls | `submit_self` took `FOR UPDATE` on the window and profile and kept the request transaction open through liveness and every Face++ call (≈18 sequential requests, 15 s timeout each). **Also found:** the request session was `idle in transaction` on a pooled connection for the whole conversation (it is opened by `get_tenant_context`), and the **punch** path held that connection plus the idempotency-key advisory lock across up to 6 provider calls. | High (availability) | **Confirmed — fixed [T]** (enrollment *and* punch) |
| 3 | New HTTP client per provider call | `_request` built `httpx.AsyncClient` in an `async with` per call (new TLS handshake each). | Medium | **Confirmed — fixed [T]** |
| 4 | Several provider requests per workflow; limits unconfirmed | Confirmed: punch = one detect + one search **per frame** (default 3 ⇒ 6); enrollment ≈ 2 + 8 + 8 = 18. (The older liveness report still said "one detect + one search per punch"; corrected.) Vendor QPS / concurrency / FaceSet quotas are unknown. | Medium / blocker for sizing | **Confirmed — bounded client-side [T]; vendor limits [S][A] open** |
| 5 | External deletion before DB commit | `approve` deleted the review photo after `flush`, before the request transaction committed; `reject`/`revoke` called `provider.delete_person` before changing local state, inside the transaction. A failed commit could leave a valid local profile pointing at a deleted FaceSet / photo. | High (integrity) | **Confirmed — fixed [T]** (outbox) |
| 6 | Review-photo access not audited | `get_review_photo` wrote no audit record. | Medium | **Confirmed — fixed [T]** |
| 7 | Rate limiting employee-scoped only | The face endpoints had no request-level limit; the existing `rate_limit` helpers were used on auth routes only. | Medium | **Confirmed — flood ceilings added [T]** (not an identity control) |
| 8 | Ordinary punch available without face | `POST /attendance/punches/me` is independent of face status and no company-level face policy exists in the data model. | Policy | **Confirmed — documented, not changed** (mode A) |
| 9 | Thresholds uncalibrated | `FACE_LIVENESS_*` and `FACE_MATCH_*` are engineering defaults; no real-device/attack data. | High (security claim) | **Open [M][S]** — out of scope |
| 10 | Retention / exit deletion / consent version / cross-border | No retention period set (cleanup is dry-run, off by default); no employee-exit hook; only `consent_recorded_at` stored; provider is `api-us.faceplusplus.com`. | Compliance | **Open [A]** — decisions, not code |
| 11 | `20261017090000` irreversibly redacts bodies | Read the migration: the `UPDATE … SET provider_response = (provider_response - 'verify') || …` discards the bodies; the downgrade restores schema only. | Operational | **Confirmed — documented (runbook §4)** |
| 12 | Real Face++, devices, attacks, load, alert delivery unverified | True: nothing was run against any real external system. | — | **Open [S][M]** |

## E2. What changed

### E2.1 Provider/engine errors no longer lock employees out [T]
`INFRASTRUCTURE_FAILURE_DECISIONS = (PROVIDER_ERROR, LIVENESS_ERROR)` is excluded from `count_failed_since`
(`repository.py`). They remain stored (audit, alerting, monitor). Timeouts, network errors, non-JSON/malformed bodies and
unrecognised Face++ replies already map to `FaceProviderError` ⇒ `PROVIDER_ERROR`; engine timeouts/unavailability ⇒
`LIVENESS_ERROR`. Every other non-`MATCHED` decision (NO_MATCH, NO_FACE, SPOOF_SUSPECTED, LIVENESS_INCONCLUSIVE,
CHALLENGE_REJECTED, CAPTURE_REPLAYED, AMBIGUOUS_FACE, IDENTITY_INCONSISTENT, NOT_ENROLLED) still counts. Outage retries stay
bounded because each retry needs a fresh challenge and challenges are capped per window (`FACE_LIVENESS_SESSIONS_PER_WINDOW`,
default 20) — tested. The client message never contains provider text.

### E2.2 No database lock or connection across provider calls [T]
*Enrollment* is three phases (`face_service.py`): **reserve** (short transaction: `FOR UPDATE` on window + profile, all
checks incl. the attempt limit, commit a lease `submission_token`/`submission_started_at` on the window) → **work** (liveness on
five captures, ~18 provider calls under one wall-clock budget, `asyncio.timeout`, no transaction) → **finalize** (short
transaction: re-lock the window, prove status `OPEN`, token still ours, not expired, profile still not ENROLLED/PENDING; then
write the profile, mark the window `USED`, audit). The lease replaces the lock's protection: a second submission during the
first gets `409 FACE_ENROLLMENT_IN_PROGRESS`; an HR cancel/reopen makes finalize fail with `FACE_ENROLLMENT_NOT_OPEN` and the
just-created FaceSet and photo are discarded; a crashed worker's lease lapses after `FACE_ENROLLMENT_LEASE_SECONDS` (240,
validated to exceed the 120 s budget); the budget being exceeded is a `PROVIDER_ERROR` (not counted against the employee); a
client disconnect (cancellation) compensates under `asyncio.shield`; the attempt limit still cannot be overshot because
reservations are exclusive. Compensation deletes directly and, if that fails, queues the deletion (E2.3). A *guard* outbox row is
queued the moment a FaceSet exists, due only after the lease lapses, so a process that dies mid-enrollment cannot orphan it.
*Punch*: the request transaction (and with it the idempotency-key advisory lock) is ended before liveness/provider work; the
punch is written in a fresh transaction that re-takes the key lock and re-checks for a replay (the unique index remains the
backstop). **Regression caught by the existing suite and fixed:** releasing the key lock early let a same-key, same-challenge
duplicate (a double-tap or an app retry while the original is still at the provider) through to a "challenge already used" 409, where
before it queued on the lock and received the original punch. Duplicates now recognise the in-flight original (challenge `CONSUMED`
moments ago), release their own connection, and poll with short transactions until the original has produced the punch (they return
it) or has recorded a rejection / the wait window (≈ liveness timeout + 2 × frames × provider timeout + 5 s = 105 s by default) ends
(they fall through to the normal path, as a duplicate of a failed request always did). A duplicate does no provider work of its own
(tested). Tests probe, from another connection and during every provider call, that the window row is lockable `NOWAIT`, that no
session is `idle in transaction` and that no advisory lock is held.
Migration `20261018090000` adds the two window columns. Schema change: reversible.

### E2.3 External deletion only after commit, with retry and reconciliation [T]
Transactional outbox `face_external_deletion` (RLS enabled and forced). `approve` queues the review photo; `reject` the FaceSet and
photo; `revoke` the FaceSet — in the **same transaction** as the status change. `attendance.run_face_deletions` (Beat, every 2
min) fans out per company; `face_deletion.process_company` claims due rows (`FOR UPDATE SKIP LOCKED` + lease), deletes outside any
transaction, and marks `DONE`; failures store a short error code and back off 2→60 min; rows with attempts ≥
`FACE_DELETION_ALERT_AFTER_ATTEMPTS` log at ERROR (monitor `face_deletion_stuck`). Idempotent; overlapping workers cannot share
a row. Safety: IDs/keys are unique and never reused, and the worker re-checks that no `PENDING_APPROVAL`/`ENROLLED` profile uses
the resource (⇒ `SKIPPED`); a later genuine reject/revoke re-arms a `SKIPPED`/`DONE` row. A rejected/revoked profile stops being
usable at commit; the provider-side delete lags by minutes. **No claim of PostgreSQL↔Face++ atomicity is made.** Behaviour change:
`reject`/`revoke` no longer fail with 502 when Face++ is down — they succeed locally and the deletion retries. Recovery:
runbook §5.

### E2.4 Pooled provider client [T]
One `httpx.AsyncClient` per provider instance per event loop (lazily created, rebuilt on a different loop), `httpx.Limits`
bounded by `FACE_PROVIDER_MAX_CONCURRENCY` (4), an `asyncio.Semaphore` of the same size, explicit connect (5 s) and total (15 s)
timeouts, `aclose()`; the API keeps one shared instance per configuration and closes it in the lifespan shutdown; Celery tasks
build and close their own. Error handling, log redaction and "unknown ⇒ error" are unchanged. These bounds are ours — they are not
Face++ limits.

### E2.5 Request-level flood limits [T]
`face_rate_limit.py`: per (tenant, client IP) per minute — punch/challenge 600, enrollment 60, review photo 120 (all settings).
Redis, fails closed (503) like the other limiters; the 429 is `RATE_LIMITED` before any liveness/provider work. Client IP is
`request.client.host`, replaced from `X-Forwarded-For` only for peers in `TRUSTED_PROXY_HOSTS` (verified in `app.py`); a forged header
from an untrusted peer does not change the bucket (tested). Counts requests regardless of outcome, so a provider outage neither
raises nor lowers it. Deliberately generous — a shared office NAT must not be locked out; the limits are flood ceilings, not
identity controls. No device fingerprinting was added.

### E2.6 Review-photo access audit [T]
`FACE_REVIEW_PHOTO_VIEWED` audit row on every served read: actor, profile id, employee id, request id, ip, user-agent, outcome
`SERVED` — no bytes, no key. Written in the request transaction before the image is returned, so a failed audit write means the image
is not served (the application's normal audit policy). Refused reads (403 permission, 404 other tenant / no photo) and storage
failures serve nothing and leave no access row; "not found" emits a `security.face_review_photo.not_found` event. This is the only
route that returns a stored biometric image (checked by grep).

### E2.7 Monitoring
`infra/monitoring/hrms_monitor.sh`: new `face_deletion_stuck` check (ERROR-level `face_deletion_failed`); its unit test added.

## E3. Exact files changed

Many files below already carried uncommitted changes from Parts A–D, so a diff against `HEAD` mixes both; the list is what *this
pass* edited or created.

New: `apps/api/alembic/versions/20261018090000_face_base_release_hardening.py`,
`apps/api/src/hrms/modules/attendance/face_deletion.py`, `…/face_rate_limit.py`,
`apps/api/tests/integration/modules/attendance/test_face_base_release.py`,
`apps/api/tests/unit/modules/attendance/test_face_provider_client.py`, `…/test_face_deletion_scheduling.py`,
`docs/operations/FACE_ATTENDANCE_BASE_RELEASE_RUNBOOK.md`.
Modified: `apps/api/src/hrms/modules/attendance/{face_service,face_verification,repository,models,exceptions,router,tasks}.py`,
`apps/api/src/hrms/{app.py,core/celery_app.py,core/config/settings.py,shared/rate_limit.py}`, `apps/api/.env.example`,
`infra/monitoring/hrms_monitor.sh`,
tests: `apps/api/tests/integration/modules/attendance/{conftest,test_face_enrollment,test_face_integrity_hardening}.py`,
`apps/api/tests/unit/ops/test_host_monitor.py`;
docs: this report, `docs/operations/FACE_ATTENDANCE_STAGING_SECURITY_CHECKLIST.md`, one correction in
`docs/audits/FACE_ATTENDANCE_LIVENESS_IMPLEMENTATION_REPORT.md`.
Not touched: mobile and web apps, existing migrations, Dockerfile, model assets.

## E4. Attendance policy for this release (finding 8)

Inspected `POST /attendance/punches/me`: it is a plain self-punch, independent of face status. There is no face field in
`attendance_policy` or any company setting, and no mobile/web string claims face verification prevents proxy punching (grep).
Therefore the base release is **mode A (optional)**; no company's behaviour was changed. Face punches carry `source = FACE`, so
reports can separate them (tested: an enrolled employee's two punches show two distinct sources). **Mode B was not implemented and
is not claimed.** If it is wanted it needs a per-company setting enforced server-side on every punch path plus a documented
recovery procedure — a product decision (E8).

## E5. Migration and configuration prerequisites

- Revisions in order: `20261015090000`, `20261017090000` (**irreversible data redaction**), `20261018090000` (reversible).
  Backup first; staging first; forward-only recovery for `…017`. Details and the downgrade caveat: runbook §4. [V]
  `20261018090000` was upgraded, downgraded and re-upgraded on a disposable DB; RLS on `face_external_deletion` was exercised as the
  `hrms_app` role (no tenant ⇒ 0 rows; own tenant only; cross-tenant insert refused).
- New settings (all defaulted, in `.env.example`): `FACE_PROVIDER_CONNECT_TIMEOUT_SECONDS`, `FACE_PROVIDER_MAX_CONCURRENCY`,
  `FACE_ENROLLMENT_PROVIDER_BUDGET_SECONDS`, `FACE_ENROLLMENT_LEASE_SECONDS`, `FACE_PUNCH/ENROLLMENT/REVIEW_PHOTO_REQUESTS_PER_MINUTE_PER_IP`,
  `FACE_DELETION_BATCH_SIZE`, `FACE_DELETION_ALERT_AFTER_ATTEMPTS`. `TRUSTED_PROXY_HOSTS` must be set correctly for the per-IP limit to mean
  anything. Celery Beat must run.
- API/mobile: request contracts unchanged. New outcomes the app has not been specifically tuned for: `409 FACE_ENROLLMENT_IN_PROGRESS`,
  `429 RATE_LIMITED` on face routes, and `reject`/`revoke` no longer returning 502. The mobile app shows the server message; the Flutter
  suite was **not** run in this pass. Model assets/checksums/boot validation are unchanged and still enforced.

## E6. Tests and commands actually executed

Isolation [V]: disposable PostgreSQL databases created inside the existing `hrms-postgres` container (`hrms_basefix_*`, never `hrms_dev`;
`hrms_dev` was only used as the connection database to issue `CREATE DATABASE` and to read `alembic_version`); `REDIS_URL` → Redis DB 14,
Celery broker/result → DB 15 (forced by `tests/conftest.py`), DB 0 not used; `FACE_VERIFICATION_PROVIDER=disabled` and logging email
forced by the test harness, fake provider/engine/storage injected — no Face++ call, no email, no alert. The disposable databases were
**not** dropped (this pass was told not to delete test databases): `hrms_basefix_20261018`, `hrms_basefix_b`, `hrms_basefix_mig`,
`hrms_basefix_full` remain for the owner to remove. `cleanup_my_run.py` was not run. Disclosure from the review step *before* this task's
safety rules were issued: the face integration tests were run once with the default `REDIS_URL` (DB 0; only rate-limiter keys of the test
harness are written there) and one scratch database of mine (`hrms_review_scratch`, created as a `TEMPLATE hrms_dev` copy) was dropped; no `hrms_dev` data was changed.

### Commands run and exact outcomes [V]

All from `apps/api` with `.venv/bin/python -m …`, against a disposable database migrated to head (`20261018090000`), Redis DB 14/15, fakes injected.

| # | Command | Outcome |
| --- | --- | --- |
| 1 | Baseline before any change: `pytest tests/unit/modules/attendance` and `pytest tests/integration/modules/attendance -k face` (clean migrated DB) | 252 passed; 118 passed. (Against the existing dev-style DB the face integration tests fail wholesale — migration `20261017090000` was never applied there and stale `scoped-*` users exist; an environment issue, not code.) |
| 2 | **Full backend suite:** `pytest tests -v` (2,921 collected), started before the idempotency fix below | **2,913 passed, 8 failed**, 814.75 s |
| 2a | …failure 1 of 8: `test_face_punch_idempotency.py::test_concurrent_same_key_creates_exactly_one_punch` | **A real regression from this pass** (key lock released early ⇒ duplicate got 409). Fixed (E2.2). Passes now. |
| 2b | …failures 2–8 of 8: `payroll/test_b05_db_immutability.py` ×6, `leave/test_leave_hardening.py::test_runtime_role_cannot_rewrite_or_erase_leave_history` | **Not caused by this change** (confirmed in Part F: with CI's database initialisation they pass). They exercise the `hrms_app` runtime role; my `CREATE DATABASE` copies lack the table grants that `infra/docker/postgres/init/002_app_role.sh` gives the real database (`permission denied for table pay_run`). After applying those grants in the disposable DB (and re-applying the migration's `REVOKE`s my blanket `GRANT` had undone) both files pass: 24 tests, 0 failures. |
| 3 | **Final-code regression:** `pytest tests/unit tests/integration/core tests/integration/modules/attendance -v` | **1,602 passed, 0 failed**, 243 s |
| 4 | New tests: `test_face_base_release.py` (33, integration), `test_face_provider_client.py` (18, unit), `test_face_deletion_scheduling.py` (3, unit); modified: `test_face_enrollment.py` (4 tests re-written for the new contract: deletion is post-commit; revoke survives a provider outage), `test_face_integrity_hardening.py` (concurrent-limit test re-written for reservations), `test_host_monitor.py` (+1 signal) | included in rows 2–3 |
| 5 | Mutation check: disable the lockout exemption (`INFRASTRUCTURE_FAILURE_DECISIONS = ("NEVER",)`), run the lockout tests | 3 of 4 selected tests fail as they must (the 4th, the 4-employee concurrency test, makes <5 attempts each and is not discriminating by design); restored and re-verified |
| 6 | `ruff check src tests alembic/versions/20261018090000_…`; `ruff format --check` (84 files); `mypy src/hrms/modules/attendance src/hrms/shared/rate_limit.py src/hrms/core/config/settings.py src/hrms/app.py`; import-linter; `bash -n infra/monitoring/hrms_monitor.sh`; `alembic heads` | all clean (mypy: 23 files, no issues; import-linter: 1 contract kept, 0 broken; single head `20261018090000`) |
| 7 | Migration: `alembic upgrade head`, `downgrade -1`, `upgrade head` on a disposable DB; RLS probe as role `hrms_app` in a rolled-back transaction | repeatable; no tenant ⇒ 0 rows, own tenant only, cross-tenant insert refused (`new row violates row-level security policy`) |

Scope of the regression evidence: the modules outside attendance (employee, leave, payroll, onboarding, …) were exercised by row 2 on the
code as it was before the idempotency fix; the only later source edits were in `face_service.py` and `repository.py` (face-specific
additions), and the attendance + core + unit suites were re-run on the final code (row 3). Failures seen elsewhere in row 2 are the
environmental ones in 2b, not pre-existing failures of the repository and not new ones.

**Not run (in Part E; Flutter and Docker were run in Part F):** the Flutter test suite; any real Face++ call; any real device or presentation attack; any load/latency/quota test; alert
delivery; any staging or production environment; the Docker image build.


## E7. Known limitations carried into the release

- Passive single-frame liveness; thresholds uncalibrated; no device attestation, no virtual-camera/injected-frame detection; a
  re-encoded old frame defeats the byte-digest replay check. A genuine digital photo of a colleague uploaded by a script with that
  colleague's credentials is not a "photo of a screen" and may pass. [M]
- Mode A: ordinary punching bypasses face verification.
- Provider-side deletion after reject/revoke/approve is eventually consistent (minutes). Outbox rows are not purged by this change (they
  hold only opaque ids/keys); a retention period for them is part of decision E8-4.
- The per-IP ceilings are generous flood limits and default to values chosen without traffic data. [S]
- `FACE_PROVIDER_MAX_CONCURRENCY=4` is an uncalibrated client-side bound: with a slow provider, requests queue on it (no DB connection is
  held while they wait, E2.2). Whether 4 is right depends on the vendor's limits and the shift-start load. [S]
- Face++ enrollment budget (120 s) vs real latency is unmeasured. [S]

## E8. Pending decisions and staging-only checks

Product/legal/privacy (not decided here): (1) optional vs mandatory per company, and the camera-failure fallback; (2) retention periods for
liveness sessions, attempt details, enrollment attempts and outbox rows; (3) deletion of an employee's FaceSet/profile on exit; (4) consent
wording and notice versioning; (5) cross-border processing and a DPA with the vendor; (6) APCER/BPCER targets; (7) acceptance of the liveness
model's training-data provenance.
Staging-only (checklist section 19 + Parts C/D rows): real Face++ behaviour and quotas, outage drill, deletion drain and stuck-alert delivery,
real-device and real-attack testing and threshold calibration, shift-start load/DB-pool behaviour, proxy handling through the real reverse
proxy, migration on a copy of production data, mobile build compatibility.

## E9. Confirmation

No commit, push, merge, rebase, stash, reset, clean, tag or deployment was made. No service was restarted. No migration was run against
production, a shared database or `hrms_dev`. No row in `hrms_dev` was read for content, changed or deleted. No real Face++ API was called, no
email or alert sent, no paid cost incurred. All existing modified and untracked files were preserved. Nothing here is marked `PASS` for real
Face++, real-device, real-attack, load, alert-delivery or legal-review scenarios, because none was run.

---

# Part F — Final pre-staging release gate (2026-10-18)

Writer's note: this part supersedes the *evidence* of Part E (Part E's design and findings stand). Labels as before: **[V]** verified in this run
with the exit status shown.

## F0. Verdicts

| Question | Verdict |
| --- | --- |
| **Local engineering verification** | **PASSED for the final working tree.** Backend unit 1,165 passed (exit 0); integration + security 1,759 passed (exit 0) under CI-equivalent initialisation; the RLS runtime-role suite 4 passed (exit 0, via a URL-substituted copy, see F2); Flutter analyze exit 0 / 503 tests passed (exit 0); Docker image built and checked; mypy, ruff format, import-linter clean. One genuine defect was found by this gate and fixed (F3). Known remaining items: F8. |
| **Staging readiness** | **READY TO BE PLACED ON STAGING for evaluation — not evaluated.** Every staging gate (F9) is `NOT RUN` or `BLOCKED`. Nothing was run against real Face++, real devices, a staging environment, a load test or alert delivery. |
| **Production approval** | **NOT GRANTED.** Passing local fakes is not evidence of anti-spoofing accuracy, vendor capacity, legal basis or operational readiness. Release mode stays **A (optional face verification)**; it does **not** prevent buddy-punching, and no wording may say it does. |

## F1. Baseline [V]

- Branch `main`, HEAD `d0c55f4`; 83 modified/untracked files at the start of the final run (all pre-existing work preserved; nothing reverted or
  cleaned; no commit/stash/reset). Migration chain head `20261018090000` (…`20261015090000` → `20261017090000` → `20261018090000`; single head).
- **Environment (new, disposable, CI-equivalent — nothing shared used in this gate):** containers `prefinal-pg` (`postgres:16-alpine`, port 15433),
  `prefinal-redis` (`redis:7-alpine`, 16380), `prefinal-minio` (`pgsty/silo`, 19000, bucket `hrms-documents`). CI's procedure was followed exactly:
  `infra/docker/postgres/init/*.sql` and `*.sh` applied **before** `alembic upgrade head`, so `hrms_app` exists, is `NOSUPERUSER NOBYPASSRLS`, and
  receives its DML grants through default privileges (verified: `hrms_app` can write `face_external_deletion` and `pay_run`, and cannot `UPDATE`
  `leave_ledger`). Env as in CI: `ENVIRONMENT=development`, `TZ=UTC`, `REDIS_URL=…:16380/0` (my own Redis; the shared Redis DB 0 was not touched),
  Celery broker/result DB 15 (forced by `tests/conftest.py`), `FACE_VERIFICATION_PROVIDER=disabled` and logging email forced by `tests/conftest.py`,
  fake Face++/liveness/photo-storage injected by fixtures. The shared `hrms-postgres` (5433), `hrms-redis` (6380) and `hrms-minio` (9000) were not
  used.
- Integration-test formatting: `ruff format --check .` reports all 597 files formatted (exit 0).

## F2. Test runs and exit codes [V]

| # | Command (from `apps/api`, CI env) | Exit | Result |
| --- | --- | --- | --- |
| 1 | `pytest tests/unit -q` | 0 | **1,165 passed** (43 s) |
| 2 | `pytest tests/integration tests/security --ignore=tests/security/test_rls_runtime_role.py -v` | 0 | **1,759 passed** (757 s) — all attendance/face/outbox/cleanup/migration-related tests included |
| 3 | `pytest` on a copy of `tests/security/test_rls_runtime_role.py` with `localhost:5433` → `localhost:15433` | 0 | **4 passed.** The original hard-codes the *shared* dev database (`localhost:5433/hrms_dev`) as both role URLs, and this gate may not write to `hrms_dev`, so the file was run through a temporary substituted copy (created and removed by me; the original is unmodified). Recommend parameterising those URLs (not changed here). |
| 4 | `ruff check .` | 1 | **4 errors, all E501 in two committed, untouched migrations** (`20261007090000_face_attendance_facepp_provider.py`, `20261008090000_compensation_ctc_positive.py`); identical at `HEAD` (checked with `git show HEAD:… | ruff --stdin-filename`). Pre-existing; not modified, per the rule against editing unrelated migrations to silence lint. Everything this work touched is lint-clean. |
| 5 | `ruff format --check .` | 0 | 597 files already formatted |
| 6 | `mypy src/hrms` | 0 | no issues in 190 source files |
| 7 | import-linter | 0 | 1 contract kept, 0 broken |
| 8 | CI's earlier backend-gate (previous runs on the intermediate tree, for the record) | — | 2,913 / 8 failed in Part E; the 7 non-face failures were setup artefacts (missing `hrms_app` grants) and **pass under CI initialisation**; the 8th was a real regression fixed in Part E. |

No code or test file changed after the final run began (checked by file modification times); the run is therefore evidence for the exact final tree
(final changes: F3 and the test additions below).

## F3. Defect found by this gate and fixed — retention cleanup batches were not bounded

**Symptom:** `test_face_cleanup.py::test_batches_are_bounded_and_a_later_run_continues` failed once in a 687-test attendance run and had passed in
the earlier full run (`assert (7, False) == (4, True)`: a batch of 2 deleted 7 rows).
**Reproduced, not dismissed:** 26 failures in 40 consecutive runs; deterministic once the planner statistics were pinned
(`UPDATE pg_class SET reltuples = 0` ⇒ fails, `52`/`1000`/`100000` ⇒ passes). Cause: `DELETE … WHERE id IN (SELECT … LIMIT n FOR UPDATE SKIP
LOCKED)` — when statistics describe a (nearly) empty table, which is the normal state of a cleanup target after a bulk delete and vacuum, the
planner re-evaluates the subquery per row and `LIMIT n` no longer bounds the statement. Only eligible rows were ever removed (the subquery is the
eligibility test), so no wrong data was deleted; but the documented "bounded batches / short locks" property did not hold, and the same shape was
used by the other two cleanup statements.
**Fix (`face_cleanup.py`):** the batch is selected in a `WITH batch AS MATERIALIZED (… FOR UPDATE SKIP LOCKED)` CTE for all three statements, so it is
evaluated once. **Tests:** new `test_batch_bound_holds_when_table_statistics_say_the_table_is_empty` pins the bad statistics for all three tables and
requires 4/4/4 rows; with the old statement shape restored (mutation) it fails (`(7, 7, 7) == (4, 4, 4)`), with the fix it passes at
`reltuples` 0, 52 and 100000. The outbox claim (`claim_due`) is unaffected: it selects ORM rows `FOR UPDATE SKIP LOCKED` and updates them in
Python. Cleanup remains report-only/off by default, so no deployment has been exposed to this.

## F4. Critical behaviour — where each is proven [V]

| Required behaviour | Evidence (tests in `tests/integration/modules/attendance/test_face_base_release.py` unless noted) |
| --- | --- |
| Provider/engine outages recorded, not counted toward lockout; genuine negatives still lock | `test_repeated_provider_errors_…`, `test_repeated_liveness_engine_errors_…`, `test_genuine_negative_matches_still_lock_out_…`, `test_concurrent_attempts_during_an_outage_…`, `test_outage_retries_are_still_bounded_…`; decisions asserted from the DB; mutation check (Part E) |
| Idempotent same-key concurrency returns the original result and holds no connection/advisory lock across slow calls | `test_a_punch_holds_no_connection_or_advisory_lock_across_provider_calls`; `test_duplicate_of_an_in_flight_punch_waits_and_gets_the_original_result` (now also probes that the waiting duplicate holds no connection/lock); `test_duplicate_of_a_rejected_in_flight_punch_…`; `test_face_punch_idempotency.py::test_concurrent_same_key_creates_exactly_one_punch` and the other idempotency tests |
| Enrollment reservations expire/abandon safely; competing submissions; cancelled/reopened windows cannot finalize | `test_stale_reservation_from_a_crashed_worker_…`, `test_fresh_reservation_blocks_…`, `test_second_submission_during_provider_work_…`, `test_window_cancelled_during_…`, `test_window_reopened_during_…`, `test_provider_budget_exceeded_…`, **new** `test_client_disconnect_mid_enrollment_compensates_and_releases_the_reservation` (task cancellation: FaceSet deleted, reservation released at once, employee can retry) |
| Face++ outside long transactions/row locks | `test_no_row_lock_or_open_transaction_is_held_across_provider_calls` (NOWAIT lock probe + `idle in transaction` probe on every call) |
| Approve/reject/revoke enqueue transactionally; worker cannot delete an in-use FaceSet/photo | `test_a_failed_commit_leaves_local_state_…[approve/reject/revoke]`, `test_queued_deletion_never_deletes_a_resource_a_live_profile_uses`, `test_concurrent_approve_and_reject_…`, `test_concurrent_revokes_…` |
| Retries, backoff, duplicate tasks, restarts, stuck jobs, orphans | `test_revoke_survives_a_provider_outage_…` (test_face_enrollment.py), `test_overlapping_workers_do_not_delete_twice`, **new** `test_rows_claimed_by_a_crashed_worker_come_back_after_the_lease`, **new** `test_a_persistently_failing_deletion_escalates_to_an_error_log_and_report`, `test_crashed_enrollment_orphan_is_reaped_…`, `test_compensation_that_cannot_reach_the_provider_is_queued_…`, `test_disabled_provider_defers_…`; unit `test_face_deletion_scheduling.py` |
| Review-photo audit holds only the required metadata; no image content stored/logged | `test_review_photo_read_is_audited_without_any_image_content` (now also scans everything logged for the image as hex/base64/repr/JPEG-base64 and checks the only trace is the slim `business.audit_recorded` event), `test_refused_or_failed_review_photo_reads_leave_no_access_record`, `test_review_photo_of_another_tenants_employee_…` |
| Rate limits use the real client address only behind a trusted proxy; forged headers ignored | `test_punch_endpoints_have_a_per_tenant_per_ip_flood_limit` (forged header from an untrusted peer), **new** `test_face_flood_limit_keys_on_the_real_client_only_behind_a_trusted_proxy` (the real face limiter behind `ProxyHeadersMiddleware`: trusted peer ⇒ per-real-client buckets; untrusted peer ⇒ forged header buys nothing), existing `tests/integration/test_proxy_aware_rate_limiting.py` |
| HTTP pooling, concurrency bound, timeouts, shutdown | `tests/unit/modules/attendance/test_face_provider_client.py` (18) |
| Release mode A unchanged | `test_ordinary_punch_remains_available_to_a_face_enrolled_employee` |

## F5. Flutter [V]

`flutter analyze` — exit 0, "No issues found". `flutter test` (Flutter 3.29.2, as in CI) — exit 0, **503 passed, 1 skipped**. Neither modified the
working tree (`pubspec.lock` unchanged). `dart format` was **not** applied to directories (repo convention); checked on the four new face files
individually: not format-clean — consistent with the repository baseline (CI runs analyze and test only), so not rewritten.

## F6. Docker image [V]

Built from the final tree with the repository `apps/api/Dockerfile`: `DOCKER_BUILDKIT=0 docker build -t hrms-api:prefinal-gate apps/api` — exit 0,
image `sha256:73ca5a17…` (180 MB). (This host has no `buildx`; the legacy builder is the supported fallback here. CI/staging should use its normal
pipeline.) The build step itself runs `verify_assets.py` and fails on any mismatch. Checks run against the built image:

| Check | Result |
| --- | --- |
| `verify_assets.py models/liveness/minifasnet-v1` | 4 × `OK` with the pinned SHA-256 values + "engine loaded" |
| Engine disabled (default) | `get_liveness_engine` returns `None` |
| Engine enabled without `FACE_LIVENESS_MODEL_DIR` | settings refuse to load |
| Engine enabled, real assets | `warm_up()` loads `minifasnet-v1` |
| One byte altered / one asset deleted (copied dir) | `LivenessUnavailableError: … failed verification` / `… asset missing` (API would refuse to boot) |
| `.env` / secrets | no `.env*` file anywhere in the image filesystem; `.dockerignore` excludes `.env`, `.env.*`, tests; the image runs as uid 1000 (`hrms`) |
| Worker and Beat code | `import entrypoints.worker` succeeds; registered face tasks: `attendance.cleanup_face_records_company`, `attendance.process_face_deletions_company`, `attendance.run_face_cleanup`, `attendance.run_face_deletions`; Beat entries `attendance-run-face-deletions` and `attendance-run-face-cleanup` present |
| Migration from the image | `alembic upgrade → head`, then down/up on a fresh DB, using the image's own `alembic` against `prefinal-pg` (F7) |

**Not exercised:** starting `gunicorn` (the API process) inside the image and a live Celery worker/Beat process — the API refuses to boot without exactly
one ACTIVE `encryption_keys` row (DATA-01 provisioning), which needs a provisioned database. Safe command for the authorised staging operator:
`docker run --rm --env-file <staging.env> <image> sh -c "python -c 'from hrms.app import create_app; create_app()'"` for an import check, then the
normal staging compose with `command:` overrides for `worker`/`beat` (see `docker-compose.prod.yml`). The production Compose stack was not started.

## F7. Migrations [V]

Fresh disposable database, CI init scripts applied, migrations run by the **built image**:
`…→ 20261014091000 → 20261015090000`; a row carrying a raw Face++ search body was seeded (`verify.results[].face_token`, `request_id`, thresholds);
`upgrade head` (⇒ `20261017090000`, `20261018090000`); `downgrade 20261014091000`; `upgrade head`; `alembic current` = `heads` = `20261018090000`.
- **Irreversible redaction demonstrated, not only stated:** after `20261017090000` the row's `provider_response` was
  `{"identity": {"legacy_redacted": true, "request_id": "req-abc"}, "liveness": …}` — the face token, results and thresholds were gone — and after the
  downgrade through it the redacted JSON was **unchanged**: the bodies do not come back. Schema (tables, constraints) is restored, data is not.
  The report (Part B, E5) and runbook §4 state this accurately: take a verified backup before applying, treat `…017` as forward-only.
- `20261018090000`: up/down/up repeatable; RLS enabled and forced; verified as `hrms_app` in Part E.
- Nothing was run against `hrms_dev`, the shared cluster or any staging/production database.

## F8. Remaining confirmed items (none blocks local verification; each is recorded, not hidden)

1. Four E501 lint errors in two committed migrations (pre-existing, untouched) — `ruff check .` exits 1 until fixed upstream.
2. `tests/security/test_rls_runtime_role.py` hard-codes the shared dev database URL; run via a substituted copy here. Parameterise via environment.
3. The four new Flutter face files are not `dart format`-clean (repo baseline).
4. Docker: no `buildx` on this host; legacy builder used.
5. Process-level API/worker/Beat boot of the image not run (F6).
6. Everything in Parts C–E "Known limitations" still applies (passive liveness, uncalibrated thresholds, optional mode, eventual-consistency of provider-side
   deletion, undecided retention/exit/consent/cross-border items).

## F9. Staging / production gates — all `NOT RUN` or `BLOCKED`

Checklist sections 0–19 (including new rows BR-15…BR-18). Nothing was executed. In particular: real Face++ behaviour and account quotas/concurrency
(`BLOCKED`: vendor information needed); real-device genuine-user (BPCER) and controlled-spoof (APCER) evaluation and threshold calibration
(`NOT RUN`/`BLOCKED`); shift-start load and DB-pool behaviour (`BLOCKED`); alert delivery for `face_deletion_stuck` and the face rejection signals
(`NOT RUN`); `TRUSTED_PROXY_HOSTS` through the real proxy (`NOT RUN`); Celery worker/Beat on staging (`NOT RUN`); migration on staging with a verified
backup/restore (`NOT RUN` — mandatory gate); mobile build ↔ API compatibility on devices (`NOT RUN`); biometric notice/consent, vendor DPA and
cross-border processing, retention periods, employee-exit deletion (`BLOCKED`: decisions by privacy/legal/HR/product).

## F10. Files changed in this gate

`apps/api/src/hrms/modules/attendance/face_cleanup.py` (F3 fix), `apps/api/tests/integration/modules/attendance/test_face_cleanup.py` (regression test),
`apps/api/tests/integration/modules/attendance/test_face_base_release.py` (five new tests, two strengthened), this report (Part F, cross-references),
`docs/operations/FACE_ATTENDANCE_BASE_RELEASE_RUNBOOK.md` (evidence and operator commands), `docs/operations/FACE_ATTENDANCE_STAGING_SECURITY_CHECKLIST.md`
(BR-15…BR-18). Formatting-only effects of `ruff format` on already-modified test files were checked: `ruff format --check .` is clean repo-wide.

## F11. Confirmation and resources left behind

No commit, push, merge, stash, reset, clean or deployment. No shared service restarted; the shared Postgres/Redis/MinIO were not used in this gate;
`hrms_dev` untouched. No real Face++ call, email or alert. The four disposable databases from Part E (`hrms_basefix_20261018`, `hrms_basefix_b`,
`hrms_basefix_mig`, `hrms_basefix_full`) were **not** deleted. New disposable resources created by this gate, left in place for the owner to remove
when finished: containers `prefinal-pg`, `prefinal-redis`, `prefinal-minio` (database `gate_img_mig` is inside `prefinal-pg`), image
`hrms-api:prefinal-gate`; `docker rm -f prefinal-pg prefinal-redis prefinal-minio` and `docker rmi hrms-api:prefinal-gate` remove them.

