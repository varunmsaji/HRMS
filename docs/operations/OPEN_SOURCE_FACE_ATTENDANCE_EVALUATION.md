# Open-source face engine - evaluation

Written for: the authorised evaluator and the reviewer who must decide whether accuracy is proven.

Date: 2026-10-25 (second pass).

## 1. Verdict

**Recognition accuracy: UNVERIFIED. Liveness attack resistance: UNVERIFIED. Demographic performance:
UNVERIFIED.** Status: INSUFFICIENT EVIDENCE (no consented, labelled capture set exists in this
environment and none was fabricated or borrowed from employees). The shipped thresholds
(`FACE_OS_MATCH_THRESHOLD=0.45`, `FACE_OS_ENROLLMENT_ANGLE_THRESHOLD=0.363`) are engineering
placeholders. 0.363 is the default in the OpenCV Zoo `sface.py` wrapper; neither value is a measured
operating point for this product and **neither may be promoted to production by copying it**.

## 2. What has been measured (plumbing and performance only - not accuracy)

- Real YuNet+SFace on one public sample portrait (transient, not stored): 128-d output, deterministic (self-cosine 1.0).
- Noise image -> `NO_FACE`; malformed / truncated / unsupported / out-of-range input -> `EmbeddingImageError` (unit tests, real models); corrupted or missing asset -> refused.
- Performance numbers: `OPEN_SOURCE_FACE_ATTENDANCE_SETUP.md` section 7 (one host, one image, synthetic load).
- Metric arithmetic and report hygiene are unit-tested with hand-built scores and a stub embedder. Those tests prove the tool computes correctly; **they say nothing about face-recognition quality.**

## 3. The tool

```
cd apps/api
.venv/bin/python -m hrms.modules.attendance.opensource_face.evaluation.evaluate_captures \
   --captures /secure/consented/captures --model-dir models/face/opensource-v1 \
   --liveness-dir models/liveness/minifasnet-v1 --thresholds 0.30,0.363,0.45,0.55
```
Run it on a machine approved for the data; stdout is JSON containing **aggregates only** (checked by
test: no identity names, paths, images or vectors). Redirect it to a file with the dataset's own
record id; do not paste data into tickets.

### Dataset format

```
<captures>/<identity>/<condition>/<image>.jpg      genuine captures
<captures>/_attacks/<attack_type>/<image>.jpg      presentation attacks (print, replay, video_frame, ...)
<captures>/_meta/groups.json                       OPTIONAL {"identity": "group label"} - only where lawful + consented
```
`<identity>` is a pseudonymous code (never a name or employee id). `<condition>` is a free label
(lighting, pose, camera, quality, occlusion ...). Per identity the first `--enroll-samples` images
(by file name) enrol; the rest are genuine probes; impostor trials are every other identity's probes
against that enrolment. Identity matching and liveness are evaluated **separately** (`--liveness-dir`
adds the liveness section; matching never uses liveness scores).

### What the report contains

`tool` version; `settings` (detector score, min face size, enrol samples, thresholds, similarity and
preprocessing description); `provenance` (model version, SHA-256 of the exact model files, OpenCV
version); counts (identities, genuine / impostor trials, excluded images by reason); `score_distributions`
(mean, percentiles, 20-bin histogram for genuine and impostor); `operating_points` (FAR, FRR at each
requested threshold); `equal_error_rate`; `tar_at_far` (1e-2, 1e-3); `far_zero_event_upper_bound_95`;
`frr_by_condition_at_threshold`; `latency_ms` p50/p95/p99 and `peak_rss_mb`; `liveness` (BPCER on
genuine images and APCER per attack type at the production thresholds, plus the count of unscorable
images); `demographic_breakdown`; `evidence_gaps` and `verdict`.

`verdict` is one of **INSUFFICIENT EVIDENCE** (any gap) or "MINIMUM EVIDENCE MET (not a production
approval ...)". Gaps are raised for: fewer than 30 identities; fewer than 300 genuine trials; too few
impostor trials to resolve FAR 1e-3 (10,000); some identity with no probes or a >5x spread of probes
per identity (unbalanced); no attack samples, or <100 per attack type. Sub-groups with <20 identities
are suppressed ("INSUFFICIENT EVIDENCE"), which also prevents small cohorts being singled out.
Synthetic or stub inputs cannot be detected by the tool - the evaluator attests the dataset.

### Interpreting results

- **FAR** = share of impostor trials scoring >= threshold; **FRR** = share of genuine trials < threshold. They trade off; the operating point is a business/security decision (cost of a proxy punch vs. an employee rejected), made from the distributions, not from a single number.
- With zero observed false accepts the true FAR is only bounded (rule of three: ~3/n at 95%); the report prints that bound.
- Read the genuine and impostor histograms: overlapping tails mean no threshold is clean; check per-condition FRR for low light / pose / camera / occlusion where rejections concentrate.
- **Liveness**: APCER (attacks accepted as LIVE) per attack type and BPCER (genuine rejected). Passive single-frame liveness is not proof of presence; replay and prerecorded-video results must be reported separately from print.
- **Demographic differences**: only from `_meta/groups.json` and only where collection is lawful, consented and each group meets the minimum; report differences in FRR/FAR with sample sizes, never a single "fairness score".
- **Latency / memory**: reported for the machine that ran it; repeat on the target CPU.
- Choose the threshold on a **development split**, confirm on an **independent validation split** (different people, devices, days); re-run after any model, preprocessing, camera-pipeline or OpenCV change.

## 4. Dataset requirements (future)

- **Consent**: written, specific to evaluation (separate from attendance consent), withdrawable, naming purpose, storage place, retention and who can access; minors excluded; no use of production enrolment images.
- **Access control**: named evaluators only, least privilege, access logged; evaluation machine disk-encrypted; no copies to laptops, chat or tickets; never inside the git repository, CI artifacts or Docker images.
- **Storage**: encrypted at rest, pseudonymous identity codes, the key to real identities held separately by the data-protection owner.
- **Retention and deletion**: fixed end date (propose project end + short validation window), certified secure deletion of images and any derived embeddings, and honouring withdrawal (remove the person's folder and re-run); record deletion in the evaluation log.
- **Attack data**: attacks are produced by volunteers' own consented captures (print, screen replay, recorded video) - not by impersonating real third parties.
- **Legal**: biometric-data law of each jurisdiction served (e.g. DPDP, GDPR Art. 9, BIPA-style statutes) reviewed by counsel before collection.

## 5. Results

| Date | Data set (size, conditions) | Split | Threshold | FAR | FRR | APCER (print/replay/video) | BPCER | Verdict |
|---|---|---|---|---|---|---|---|---|
| - | none available | - | - | - | - | - | - | INSUFFICIENT EVIDENCE |
