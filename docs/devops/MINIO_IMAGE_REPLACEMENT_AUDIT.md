# MinIO Container Image Replacement — Audit & Decision Gate

**Status:** AUDIT ONLY. No production, CI, Compose, or application files were changed while
producing this document. `docs/devops/MINIO_IMAGE_REPLACEMENT_AUDIT.md` is the only file this task
created.

**Date:** 2026-09-28

**Trigger:** Phase A CI verification (`docs/devops/PHASE_A_CI_IMPLEMENTATION.md` §17a) found that
`minio/minio:latest` — the image `docker-compose.yml` and `docker-compose.prod.yml` both still
reference — is no longer pullable, and its documented CI stop-gap (`bitnamilegacy/minio`) was
explicitly flagged as frozen and not evaluated for production use.

---

## 1. Executive Summary

**This is not a container-registry hiccup. MinIO Inc. has fully ended open-source development of
MinIO Server and MinIO Client.** Both `minio/minio` and `minio/mc` GitHub repositories are archived
(confirmed directly via the GitHub API: `archived: true`), MinIO's own binary distribution site
(`dl.min.io`) now returns `410 Gone` for every historical release with the message *"The open-source
MinIO Server, MinIO Client (mc) and MinIO KES projects are archived and no longer maintained. MinIO
does not provide product support, security updates, or security advisories for them"*, and both
container registries (Docker Hub, then quay.io) have had the images pulled entirely. MinIO's
commercial successor is **AIStor**, not a free/open continuation.

The good news, found during this audit: a real, actively-maintained, drop-in-compatible community
fork exists — **`pgsty/silo`** (formerly `pgsty/minio`, renamed in August 2026 for trademark
reasons), maintained by the team behind **Pigsty**, an established open-source PostgreSQL
distribution (5,699 GitHub stars, pushed commits the same day this audit was written). It ships
regular, CVE-referenced security releases (most recently 2026-09-16, with a security release history
running back to at least April 2026), is AGPL-3.0 (same license MinIO used), is multi-arch
(amd64/arm64), supports pinning by version tag or digest, and — verified directly in this audit, not
assumed — is a full drop-in replacement: same environment variables, same startup command, same `mc`
CLI binary name, and (critically) **the same on-disk data format**, confirmed by booting it directly
against a copy of this repository's real MinIO-written data with zero migration.

**Bottom line for the decision gate:** switching the container image (MinIO software → Silo, a
maintained fork of the identical codebase) is a low-risk, well-evidenced change. Switching to a
different S3-compatible server entirely (SeaweedFS, etc.) is a much bigger, data-migration-requiring
decision this audit does **not** recommend pursuing unless Silo itself becomes untrustworthy later.

---

## 2. Current State — Exactly What This Repository Uses Today

### Inventory (Part 1)

| Location | Purpose | Runtime | Criticality |
|---|---|---|---|
| [`docker-compose.yml:46`](../../docker-compose.yml) | `minio` service — dev object storage server | dev | High — every onboarding-document/employee-import feature needs it locally |
| [`docker-compose.yml:71`](../../docker-compose.yml) | `minio-init` service — bucket bootstrap (`mc alias/mb/anonymous set`) | dev | High — API returns storage errors without the bucket |
| [`docker-compose.prod.yml:83`](../../docker-compose.prod.yml) | `minio` service — production object storage server | production | **Critical** — the only place uploaded employee documents physically live |
| [`docker-compose.prod.yml:100`](../../docker-compose.prod.yml) | `minio-init` service — production bucket bootstrap | production | Critical on first boot / fresh volume; a no-op afterward |
| [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) (lines 155–210, as of the Phase A fix) | Disposable MinIO + `mc` for integration tests | CI | Medium — already patched to `bitnamilegacy/*` as a temporary stop-gap; this audit's subject |
| [`apps/api/src/hrms/core/storage.py`](../../apps/api/src/hrms/core/storage.py) | `DocumentStorageService` — the only application code that talks to object storage | API (and any Celery task using it, e.g. employee-import) | Critical — all `put_object`/`get_object`/`delete_object`/`presigned_get_url` calls |
| `apps/api/src/hrms/core/config/settings.py` | `s3_endpoint_url`, `s3_public_endpoint_url`, `s3_bucket_documents`, `aws_access_key_id/secret_access_key`, `aws_region` | API config | High — `_guard_non_development_config` fails the app closed if any of these is unset outside dev |
| `apps/api/src/hrms/modules/health/service.py` | Readiness check — confirms S3 config is present, **no live round-trip** | API | Low coupling by design (documented in the code itself) |
| `tests/integration/core/test_storage.py`, `tests/integration/modules/employee_import/*`, `tests/integration/modules/onboarding/test_onboarding_documents*.py`, `test_onboarding_upload_bounds.py`, `test_onboarding_upload_rate_limit.py` | Real, unmocked S3-API integration tests (41 tests total, counted directly) | CI/local | High — this is the suite this audit re-ran against the candidate, see §5 |
| [`infra/backup/minio_backup.sh`](../../infra/backup/minio_backup.sh) | Nightly-intended backup via `docker compose run --rm minio-init` overridden to run `mc mirror` | operations | Critical for disaster recovery — **also depends on pulling the `minio-init` image**, i.e. the same broken `quay.io/minio/mc:latest` |
| [`infra/backup/minio_restore.sh`](../../infra/backup/minio_restore.sh) | Restore-verification via the same `minio-init` service override | operations | Critical — same dependency |
| `apps/api/env/.env.*.example`, `.env.prod.example` | Documented credential/endpoint shape for every environment | config templates | Reference only, no image dependency |

The application does not use `boto3`/`aiobotocore` directly anywhere else, and does not reference
`aws_s3`, `S3_BUCKET`, or any AWS SDK feature outside `hrms/core/storage.py` and its two direct
importers (`employee_import/service.py`, `onboarding/models.py`/`email_sender.py` reference
settings only, not the client). Confirmed by the repo-wide grep in Part 1's search terms — no other
storage client exists.

**A finding that broadens this audit's scope beyond the CI job:** `minio_backup.sh` and
`minio_restore.sh` do not run a standalone `mc` — they re-run the compose file's own `minio-init`
service definition with an overridden entrypoint (`docker compose run --rm ... minio-init -c "..."`).
That means **backup and restore both transitively depend on `quay.io/minio/mc:latest` being
pullable**, the exact image this audit already confirmed returns 401 anonymously. This was not
previously identified in `PHASE_A_CI_IMPLEMENTATION.md` (which only looked at the CI job) — see §8.

---

## 3. Application Storage Contract (Part 2)

Read directly from `hrms/core/storage.py` and its test suite — not inferred:

```text
STORAGE COMPATIBILITY CONTRACT

Required S3 API operations:
  - PutObject          (DocumentStorageService.put_object)
  - GetObject           (DocumentStorageService.get_object)
  - DeleteObject        (DocumentStorageService.delete_object)
  - HeadObject          (integration tests' existence checks only, not app code)
  - ListBuckets         (integration tests' readiness-wait helper only)
  - GeneratePresignedUrl for GetObject, SigV4          (DocumentStorageService.presigned_get_url)

NOT used anywhere in this codebase:
  - Multipart upload
  - Object versioning
  - Bucket lifecycle rules
  - Object-level ACLs beyond one bucket-wide policy
  - Range requests (partial GET)
  - Server-side encryption (SSE) — encryption at rest, if any, is MinIO/Silo's own volume-level
    concern, never requested via the S3 API by this app
  - Rich object metadata beyond Content-Type
  - MinIO-specific extensions (no `X-Minio-*` headers, no MinIO admin API, no MinIO SDK — only
    the vendor-neutral `boto3`/`aioboto3` S3 client)

Addressing / signing:
  - No explicit `addressing_style` override — relies on boto3/aioboto3's own default resolution
    against a custom `endpoint_url`.
  - Signature version pinned to `s3v4` in the test client; production `DocumentStorageService`
    relies on aioboto3's default (also SigV4 for a custom endpoint).

Bucket policy:
  - Exactly one operation used in practice: "deny anonymous access" (`mc anonymous set none`,
    applied once at bootstrap by `minio-init`). Verified in this audit: unauthenticated GET against
    a private-bucket object returns HTTP 403.

TLS:
  - Not terminated by MinIO/Silo itself in any environment. Dev talks to it in plaintext over the
    Docker network; production's `S3_PUBLIC_ENDPOINT_URL` is presigned against Nginx's
    HTTPS-terminated hostname, not the internal object-storage container directly.

Public access:
  - Prohibited by design (private bucket, confirmed enforced) — the only public-facing access path
    is a short-lived (default 300s) presigned URL, never a public bucket policy.

Object keys:
  - Applcation-generated, prefixed paths (e.g. `onboarding-documents/...`); no client-supplied
    filename is ever used as the key (confirmed by
    `test_object_key_ignores_the_client_supplied_filename`, which passed against the candidate —
    see §5).
```

This is a deliberately small, vendor-neutral contract — the application was already written
defensively against MinIO lock-in (comment in `storage.py`: *"self-hosted MinIO... not AWS S3"*,
using only the generic S3 API). That is precisely why a compatible replacement is realistic here.

---

## 4. Operational Requirements (Part 3)

**Storage**
- Bucket: `hrms-documents` (fixed name, `MINIO_BUCKET_DOCUMENTS`/`S3_BUCKET_DOCUMENTS` in compose/app config respectively)
- Volume: named Docker volume `minio_data` (dev: `hrms_minio_data`), mounted at `/data`
- Ports: `9000` (S3 API, + presigned/public traffic proxied through it), `9001` (console, dev only — not exposed in prod's `edge`/`data` network split)
- Credentials: `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` (compose-level secrets, `${VAR:?required}` fail-closed in prod, fixed dev-only value in dev)
- Health endpoint: `/minio/health/live` (liveness only, matching the app's own `/health/live` vs `/health/ready` split)
- Initialization: `minio-init`, a one-shot dependent service (`depends_on: minio: condition: service_healthy`), idempotent (`--ignore-existing`)

**Security**
- Auth: root user/password only (no IAM/STS/OIDC in use)
- TLS: not MinIO's job in this architecture (see §3)
- Bucket: private by default + explicitly locked via `mc anonymous set none`
- Network: prod's `minio` service sits on both `data` and `edge` networks (needs `edge` so Nginx can proxy presigned-URL traffic); no host port published in prod at all — only reachable through Nginx or other containers on the same Docker networks

**Reliability**
- Persistence: named volume, `restart: unless-stopped`
- Backup: `infra/backup/minio_backup.sh`, intended nightly (not yet actually scheduled per `docs/devops/CI_CD_DEVOPS_IMPLEMENTATION_PLAN.md` G3) — `mc mirror` to a local dated archive
- Restore: `infra/backup/minio_restore.sh`, always into a new, non-live bucket — never overwrites `hrms-documents` directly

**CI**
- Startup + health-check + bucket-creation must complete before any storage-dependent test runs
- Already hardened (Phase A) against transient startup races with a short retry loop

---

## 5. Candidate Investigation (Part 4) — Evidence, Not Assumption

Five candidates were actually investigated; three were pull-tested live against this machine's
Docker daemon (not just researched), and the strongest candidate was tested against real
application code and real pre-existing data.

| # | Candidate | Pullable now? | Maintained? | Verdict |
|---|---|---|---|---|
| 1 | `minio/minio` (Docker Hub, official) | **No** — repo deleted, Hub API returns 404 | N/A — project archived | Dead end |
| 2 | `quay.io/minio/minio` / `quay.io/minio/mc` (official, alternate registry) | **No** — 401 "Requires authentication" on every tag, confirmed not a general quay.io outage (`quay.io/prometheus/prometheus` pulls fine from the same daemon) | N/A — project archived | Dead end |
| 3 | `bitnamilegacy/minio` / `bitnamilegacy/minio-client` (current CI stop-gap) | Yes, today | **No** — see §8, dedicated analysis | CI-only, not production |
| 4 | Self-built image from official MinIO source/binary | Partially possible (source still on the archived, read-only GitHub repo) but **no official binaries or checksums exist anymore** — `dl.min.io` returns 410 Gone for every release, including hotfixes; GitHub releases never attached binary assets. Would mean this team becomes the sole maintainer of a fork MinIO Inc. has explicitly disclaimed ("does not accept or process vulnerability reports") | Only as maintained as we choose to make it — real ongoing burden | Technically possible, not recommended (see §6.2) |
| 5 | **`pgsty/silo`** (community fork, Docker Hub `pgsty/silo` + `pgsty/mc`) | **Yes**, verified by direct `docker pull`, today | **Yes** — not archived, pushed the same day this audit ran; regular named security releases referencing real CVEs (e.g. `CVE-2026-42600`) from April 2026 through September 2026; maintained by Pigsty (5,699-star, actively-pushed PostgreSQL distribution project) | **Strongest candidate — see full evidence below** |
| 6 | A different S3-compatible server (SeaweedFS, etc.) | Yes (SeaweedFS: not archived, 35,028 stars, pushed today) | Yes, very actively | Viable *in the abstract*, but a different on-disk format and admin model — real data migration, not a drop-in swap. Not recommended unless Silo's fork later proves untrustworthy (see §10) |

### 5.1 Evidence for the recommended candidate (`pgsty/silo`)

All of the following were run directly in this session, against this repository's actual code —
not inferred from documentation:

1. **Pull test:** `docker pull docker.io/pgsty/silo:latest` and `docker.io/pgsty/mc:latest` — both succeed anonymously, no auth needed.
2. **Drop-in startup:** same `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` env vars, same `server /data --console-address ":9001"` command as `docker-compose.yml`'s current `minio` service — no changes needed to the compose service definition beyond the `image:` line.
3. **Drop-in bucket bootstrap:** the exact `mc alias set` / `mc mb --ignore-existing` / `mc anonymous set none` commands `minio-init` already runs, executed unmodified against `pgsty/mc` — succeeded, and the client binary is literally named `mc` (not just `mcli`), so **`minio_backup.sh`/`minio_restore.sh`/`minio-init`'s existing shell commands need zero changes**, only the `image:` reference.
4. **Application-level compatibility:** ran this repository's real `DocumentStorageService` code path directly (`put_object`, `head_object`, `get_object`, `generate_presigned_url`, `delete_object`) against a live `pgsty/silo` container — every operation succeeded, byte-for-byte round-trip confirmed, and an unauthenticated GET against the private bucket correctly returned `403`.
5. **Real integration test suite, actually executed (Part 6's explicit ask):** ran all 41 storage-dependent tests from `tests/integration/core/test_storage.py`, `tests/integration/modules/onboarding/{test_onboarding_documents,test_onboarding_upload_bounds,test_onboarding_upload_rate_limit}.py`, and `tests/integration/modules/employee_import/{test_employee_import,test_employee_import_upload_bounds}.py` against a real Postgres test database and a real `pgsty/silo` container — **41 passed, 0 failed.**
   - Caveat found and corrected during this run: `test_object_survives_a_minio_container_restart` matches its target container by the hardcoded name `hrms-minio`, so it silently restarted the *real dev* MinIO container instead of the candidate under test (it "passed" for the wrong reason). Verified separately and explicitly: wrote an object directly to the `pgsty/silo` test container, `docker restart`ed *that* container, confirmed the object was still readable afterward. Genuine restart-persistence: confirmed.
6. **On-disk data-format compatibility (the single most important question for production risk) — tested directly, not assumed:** copied this repository's actual `hrms_minio_data` Docker volume (written entirely by the real `minio/minio` image) into a separate scratch volume, booted `pgsty/silo` against the copy, and successfully read back an object that had been written by the original MinIO image before the copy was made. Then wrote a new object via Silo and read it back too. **No format conversion, no re-initialization, no data loss.** The live `hrms_minio_data` volume itself was never touched — the source volume was mounted read-only, and this test container was removed afterward.
7. **Versioning/pinning:** confirmed via the Docker Hub API that `pgsty/silo` publishes immutable per-release tags (e.g. `RELEASE.2026-09-16T00-00-00Z`), architecture-specific tags (`-amd64`, `-arm64`), a smaller `-distroless` variant, and that every tag resolves to a stable digest — full support for pinning by version or by digest, not just `latest`.
8. **License:** AGPL-3.0, unchanged from upstream MinIO — no new licensing obligation introduced.

None of this is "it works, ship it" — see §6 for the multi-dimensional tradeoff table Part 7 asked for.

---

## 6. Compatibility, Security, and Operational Findings

### 6.1 Tradeoff matrix (Part 7)

| Dimension | `bitnamilegacy/minio` (current CI stop-gap) | `pgsty/silo` (recommended) | Self-built from source |
|---|---|---|---|
| Availability | Pullable today | Pullable today | Source available; no official binaries |
| Maintenance | **None** — Bitnami's "legacy" tier is explicitly frozen (Broadcom's 2025 policy change); last tag update 2025-08-19, packaging MinIO `2025.7.23`, itself already older than MinIO's own last security release (2025-10-15) | Active — releases through 2026-09-16, CVE-referenced | Whatever this team commits to doing forever |
| Security | No future patches, ever, by design | Regular security releases, real CVE fixes | Depends entirely on us finding and backporting CVEs ourselves |
| Reproducibility | Frozen tag; fine for that reason, ironically | Pinnable by version or digest | Fully reproducible if we build it, but we own that pipeline |
| S3 compatibility | Full (it's MinIO, just old) | Full — verified directly, §5 | Full (same original source) |
| Application compatibility | Not tested in this audit (no reason to — not a production candidate) | **Verified: 41/41 real integration tests pass** | Same code, so equivalent to upstream MinIO by construction |
| Backup compatibility | N/A | **Verified: same `mc` binary name, same commands, zero script changes needed** | Same, if we build an equivalent `mc`-compatible client (Silo already gives us this for free) |
| CI compatibility | Already working (current state) | Would work identically — same env vars, same commands | Would require us to build/publish images ourselves in CI too |
| Production suitability | **Not recommended — see §8** | Recommended, pending human decision | Not recommended — see §6.2 |
| Upgrade path | None (frozen) | Pull a newer release tag | We'd have to build every future release ourselves |
| Rollback path | N/A (never update it) | Re-pin to the previous digest/tag | Re-deploy our own previous build |
| Operational complexity | Lowest today, but a dead end | Low — same operational model as MinIO already in place | Highest — new build/scan/publish pipeline to own |
| Cost | $0 | $0 | $0 in licensing, but real engineering time |
| Vendor/project dependency | Depends on Broadcom continuing to host even the frozen tag | Depends on Pigsty continuing to maintain the fork (mitigated: AGPL-3.0 source, so a re-fork is always possible if they stop) | Depends entirely on this team |

### 6.2 Why "build our own image" is not the recommendation

Part 5 explicitly asked to separate "MinIO the software" from "a specific container image." That
distinction was investigated directly: the *software* itself, as a self-built binary, is not
categorically impossible — the source is still readable on the archived GitHub repo. But building
and maintaining that ourselves means:

- No official checksums or signatures to verify against (dl.min.io's 410 response is explicit that
  this applies to *all* historical releases, not just future ones).
- We would become the sole party responsible for finding, understanding, and backporting any future
  MinIO/S3-protocol security issue — a burden a small team is unlikely to want, and one that
  `pgsty/silo` already does, publicly, with a visible release history.
- It duplicates work a maintained fork is already doing well, for no compatibility gain — Silo is
  built from the *same original source*, so a self-built image would not be any more "authentic" or
  compatible than Silo already is.

This audit finds no reason to recommend it over adopting the existing fork.

### 6.3 Security review (Part 12)

For the recommended candidate (`pgsty/silo`):

- **Provenance:** publicly buildable from source on GitHub (`pgsty/silo`, AGPL-3.0); Docker Hub
  images traceable to tagged releases with commit SHAs in each release's notes.
- **Signing:** not verified in this audit — worth checking (cosign/sigstore or similar) before final
  adoption; not a blocker, since MinIO itself never signed images either.
- **Digest pinning:** confirmed supported (§5.7).
- **Vulnerability scanning:** not run in this audit (explicitly out of scope — "only assess it");
  recommend a Trivy/Grype scan as part of Phase B's Docker CI work, once adopted.
- **Non-root execution:** not independently re-verified here; MinIO upstream historically ran as a
  configurable non-root user, and nothing observed in this audit's testing suggested a regression.
- **No embedded credentials:** confirmed — same `MINIO_ROOT_USER`/`PASSWORD` env-var model as before, nothing hardcoded in the image.
- **No public bucket / no public admin interface:** unchanged from current architecture (§4); this
  audit did not change any bucket policy or network exposure.
- **TLS / secret management / network isolation:** all unchanged from the current architecture — an
  image swap does not touch any of these.

### 6.4 Documented false claim worth flagging

The current CI workflow comment (`.github/workflows/ci.yml`, written during the Phase A fix, before
this audit existed) states `bitnamilegacy/minio` "is a stop-gap for this disposable, ephemeral
CI-only container" — that framing is confirmed **correct** by this audit, not overstated. It does
**not** claim Bitnami legacy is production-suitable anywhere, so no correction is needed there. This
audit's job is simply to now give the human the production-side answer that comment deferred.

---

## 7. Production Data Risk (Part 9)

**Risk of changing only the container image (MinIO → Silo): LOW.**

Evidence, not assertion:
- Directly booted `pgsty/silo` against a byte-for-byte copy of this repository's real
  `minio/minio`-written volume data. It started cleanly, listed the existing bucket, and correctly
  read back a pre-existing object with no conversion step, no re-initialization prompt, and no
  error. This is the strongest possible evidence short of doing it against the actual production
  volume.
- The credential model (`MINIO_ROOT_USER`/`PASSWORD`), bucket name, and API surface are all
  unchanged — nothing about how the application authenticates or addresses objects changes.
- The change is confined to one line per compose file (`image:`), with no code, migration, or
  schema change anywhere.

**Risk of changing to a non-MinIO-derived server (SeaweedFS, etc.): HIGH**, not evaluated as a live
option in this audit beyond the tradeoff table — different on-disk format means a real data
migration (export every object, stand up the new server, re-import, verify counts, cut over), which
is an entirely different, much larger, separately-scoped effort. Not recommended unless the Silo
fork itself later proves unmaintained.

**A risk this audit surfaces that is independent of which image is chosen:** because the production
VPS is not directly accessible from this session, whether production is *currently* exposed to this
problem is unverified. If the VPS's local Docker image cache still holds `minio/minio:latest` and
`quay.io/minio/mc:latest` from before they disappeared (this development machine's cache does — both
images are present locally, last pulled 2025-09-07), production is unaffected **until** something
forces a fresh pull: a `docker system prune`, a new/replacement VPS, or — critically — the **next
backup or restore run**, since `minio_backup.sh`/`minio_restore.sh` invoke `docker compose run`
against the `minio-init` service definition, which will attempt to pull `quay.io/minio/mc:latest`
if it is not already cached on that host. **Recommend the human check `docker images | grep minio`
on the production VPS as a first, immediate action independent of everything else in this
document** — this is a factual check, not an infrastructure change, and tells us whether backups are
silently already broken.

---

## 8. Bitnami Legacy — Dedicated Findings (Part 8)

Investigated directly, not assumed:

- **Why "legacy":** Broadcom's 2025 restructuring of Bitnami moved all free-tier images to a
  `bitnamilegacy` Docker Hub namespace and stopped updating them; ongoing maintenance now requires a
  paid "Bitnami Secure Images"/Tanzu subscription (the running container's own startup banner says
  this outright: *"there are enterprise versions of the Bitnami catalog... for enhanced secure
  software supply chain features... see Bitnami Premium"*).
- **Security updates:** none, by design, going forward.
- **MinIO version currency:** the frozen tag packages MinIO `2025.7.23` — older than MinIO's own
  final security release (`RELEASE.2025-10-15T17-29-55Z`, which fixed a real privilege-escalation
  CVE). The stop-gap is not just "won't get future patches," it is already missing one that existed
  before MinIO itself went fully dark.
- **`latest` mutability:** `bitnamilegacy/minio:latest` is a floating tag; Docker Hub also lists
  fully pinned digest and version tags (`2025.7.23-debian-12-rN`) for anyone who wants to freeze it
  further, but nothing changes the fact that the *content* behind any of those tags will never be
  patched.
- **Verdict:** appropriate only as a temporary, ephemeral CI convenience (which is exactly and only
  how it is currently used and commented in `ci.yml`) — **explicitly not appropriate for
  production**, on security-currency grounds alone, independent of any other factor.

---

## 9. Temporary vs. Durable (Part 11)

**Temporary (already in place, no action needed):** CI's `bitnamilegacy/minio` /
`bitnamilegacy/minio-client` stop-gap from the Phase A fix. Acceptable to leave as-is short-term
because CI containers are disposable, hold no real data, and are torn down every run — but see §11
for why minimizing environment drift is still worth doing soon.

**Durable (recommended, pending human approval — not implemented in this audit):** adopt
`pgsty/silo` (server) and `pgsty/mc` (client) everywhere — dev, CI, and production — replacing both
`minio/minio:latest` and `quay.io/minio/mc:latest` in `docker-compose.yml`,
`docker-compose.prod.yml`, and (once durable) `.github/workflows/ci.yml` too.

**Why the same image everywhere, once durable:** this repository's own stated convention (see
`ci.yml`'s existing comments) is "no CI-only path" — every service CI stands up already deliberately
mirrors what `docker-compose.yml` runs, specifically so a test passing in CI means something about
the real stack. Leaving CI on a different, frozen image than production indefinitely would quietly
break that invariant and reintroduce exactly the kind of environment-specific surprise Phase A's own
MinIO investigation was triggered by in the first place.

---

## 10. Proposed Durable Architecture (Part 10)

*(Recommendation only — none of this is implemented by this audit.)*

**Development (`docker-compose.yml`):** `pgsty/silo` for the `minio` service, `pgsty/mc` for
`minio-init`'s image — same env vars, same commands, only the `image:` lines change.

**CI (`.github/workflows/ci.yml`):** once the durable choice is approved, replace the
`bitnamilegacy/*` stop-gap with the same `pgsty/silo` / `pgsty/mc` images used everywhere else, to
restore full dev/CI/prod parity.

**Production (`docker-compose.prod.yml`):** `pgsty/silo` for `minio`, `pgsty/mc` for `minio-init`.

**Versioning:** pin to an explicit release tag (e.g. `RELEASE.2026-09-16T00-00-00Z`), not `latest`,
in production and CI — `latest` in a fork whose maintainers we don't control is exactly the kind of
silent-drift risk this whole audit exists because of. Dev can reasonably stay on `latest` for
convenience, consistent with how this repo already treats `postgres:16-alpine`/`redis:7-alpine` (dev
convenience, pinned major version, not pinned patch).

**Image integrity:** pin by version tag for readability in diffs/PRs, and record the corresponding
digest in the same commit/PR description for verification — both, not one or the other.

**Supply chain:** add a Trivy (or equivalent) scan of the pinned Silo image as part of Phase B's
Docker CI work (already planned in `CI_CD_DEVOPS_IMPLEMENTATION_PLAN.md` §8), report-only initially,
same policy this repo already applies to its other dependency scans.

**Update process:** a human reviews Silo's release notes periodically (its releases are explicit
about security content, as shown in §5.1/§8) and bumps the pinned tag deliberately — not automated,
consistent with how this repo already treats every other pinned base image.

**Rollback:** re-pin to the previous known-good tag/digest; because on-disk format compatibility is
confirmed (§7), this is a same-day, no-data-migration operation in either direction.

**Backup:** no change to the backup *strategy* — `minio_backup.sh`/`minio_restore.sh` need zero
script changes (§5.1.3), only benefit from `minio-init`'s image becoming pullable again.

---

## 11. Required Changes (Part 13) — If the Durable Recommendation Is Approved

Exact files that would eventually need editing (none edited by this audit):

- `docker-compose.yml` — 2 lines (`minio`, `minio-init` image references)
- `docker-compose.prod.yml` — 2 lines (same two services)
- `.github/workflows/ci.yml` — 2 lines (replace the `bitnamilegacy/*` stop-gap once the durable image is approved, to restore dev/CI/prod parity per §9)
- `docs/devops/CI.md` — update the MinIO section's image references and rationale
- `docs/devops/PHASE_A_CI_IMPLEMENTATION.md` — note that the CI stop-gap was superseded by the durable choice
- `docs/deployment/PRODUCTION_DEPLOYMENT.md` and `docs/deployment/DISASTER_RECOVERY.md` — anywhere either references `minio/minio` or `mc` by registry/image name (not yet greped in detail in this audit — flagged as a follow-up read before implementation, not before this decision)
- No change needed to `infra/backup/minio_backup.sh`, `infra/backup/minio_restore.sh`, or any application code — confirmed in §5.1

## 12. Migration Plan (Part 11 of the brief) — Description Only, Not Executed

1. Get explicit human approval on the durable image choice (this document's purpose).
2. Update `docker-compose.yml`'s `minio`/`minio-init` image references; `docker compose up -d minio minio-init` locally; confirm existing dev data (bucket, objects) is still reachable — expected to be a non-event given §7's evidence.
3. Update `.github/workflows/ci.yml` to match, removing the `bitnamilegacy/*` stop-gap; open a PR, confirm CI green.
4. Update `docker-compose.prod.yml`'s image references in a reviewed PR; do **not** apply to the live VPS yet.
5. On the VPS: check current image cache status first (§7's flagged action item), take a MinIO backup with whatever image is currently cached/working, `docker compose pull minio minio-init` with the new image references, `docker compose up -d minio minio-init` (data volume untouched), verify `/minio/health/live` and a real document round-trip (e.g. re-run the app's own upload flow once), then verify the *next* scheduled backup succeeds.
6. Update the documentation files listed in §11.

## 13. Rollback Plan — Description Only, Not Executed

Re-point the `image:` line(s) back to the previous value and `docker compose up -d minio minio-init`
again. Because §7 confirmed the on-disk format is unchanged, this is symmetric — rolling back is as
low-risk as rolling forward, in either direction, with no data conversion in either case.

---

## 14. Open Decisions Requiring Human Approval

1. **Approve (or reject) `pgsty/silo`/`pgsty/mc` as the durable replacement** for `minio/minio` and
   `quay.io/minio/mc` across dev, CI, and production. This is the central decision this audit exists
   to support.
2. **Immediate, zero-risk action independent of decision 1:** check the production VPS's Docker
   image cache for `minio/minio:latest` and `quay.io/minio/mc:latest` now, to learn whether backups
   are already silently failing there. This is a read-only check, not an infrastructure change, and
   this audit recommends doing it regardless of how decision 1 resolves.
3. **Pinning policy:** confirm version-tag + recorded digest (recommended, §10) vs. `latest`
   everywhere vs. digest-only.
4. **Timing:** whether to update CI's stop-gap and the dev/prod compose files together in one PR
   (minimizes drift fastest) or CI first, prod later (more cautious, more drift in the interim) —
   this audit recommends together, per §9, but leaves the final call to the human.
5. **Image signing/vulnerability scanning:** whether to add this as a Phase B Docker CI gate before
   or after adopting Silo in production (this audit recommends after adoption, report-only first,
   consistent with this repo's existing dependency-scan policy).
6. **Whether to re-evaluate a non-MinIO-derived server (SeaweedFS, etc.) at all**, given this audit's
   finding that it would require an actual data migration — this audit recommends not pursuing that
   path now, but the decision is the human's.
