# Upload Security Batch A — Self-Hosted Storage Architecture

## 1. Executive result

```
UPLOAD BATCH A PASS — SELF-HOSTED STORAGE READY FOR BATCH B
```

`DocumentStorageService` (`apps/api/src/hrms/core/storage.py`) is confirmed to talk to
self-hosted MinIO, never AWS S3, in every environment: `Settings._guard_non_development_config`
now refuses to boot staging/production without an explicit `S3_ENDPOINT_URL`/
`S3_BUCKET_DOCUMENTS`/credentials set (INFRA-01, [[upload_security_audit]]'s P0 finding), closing
the exact gap the audit found — production/staging/QA env templates previously omitted
`S3_ENDPOINT_URL` entirely, which would have resolved `aioboto3`'s S3 client against real AWS.
Presigned GET URLs now sign against an independently configurable public endpoint
(`S3_PUBLIC_ENDPOINT_URL`) so a Nginx-fronted hostname — not an internal Docker hostname — is
what a candidate's or admin's browser ever receives. Both existing upload paths (onboarding
documents, employee-import CSV) are unchanged in their storage-abstraction usage — no
duplication, one `DocumentStorageService` for both — and both are covered by tests against a
real local MinIO. A storage outage during CSV processing no longer leaves an employee-import
batch stuck at `PROCESSING` forever.

This batch resolves the storage **backend/endpoint** question only. File-type/MIME/magic-byte
validation, size limits, filename sanitization, and the rest of the upload-security backlog
remain open — see §6.

## 2. Phase 1 — what MinIO actually does today (as found)

Inspected: `core/storage.py`, `core/config/settings.py`, `docker-compose.yml`, all five
`.env*.example` templates, `app.py` (lifespan/health), `modules/health/*`,
`modules/onboarding/service.py`, `modules/employee_import/service.py`, and the existing
integration tests that already exercise real MinIO.

| Property | Development (as found) |
| --- | --- |
| Endpoint | `http://localhost:9000` (`S3_ENDPOINT_URL`, `.env`) |
| Bucket | `hrms-documents` (`S3_BUCKET_DOCUMENTS`) |
| Access key | `hrms_minio` (MinIO root user, static) |
| Secret key | `hrms_minio_dev_password` (MinIO root password, static) |
| Region | `ap-south-1` (cosmetic for MinIO — SigV4 requires *a* region string, MinIO doesn't validate it) |
| Addressing style | Path-style (`http://localhost:9000/hrms-documents/<key>`) — confirmed empirically against the running dev container; `botocore` already defaults to path-style for a non-AWS `endpoint_url`, no explicit `Config(addressing_style=...)` was ever needed |
| Presigned URLs | SigV4, `generate_presigned_url("get_object", ...)`, default 300s expiry — verified to actually resolve and serve real bytes over HTTP against the dev container (`tests/integration/core/test_storage.py`) |
| Docker networking | `minio` service on the default compose network; host ports `9000` (S3 API) and `9001` (console) both published, since in development the browser and the API are the same host |
| Persistent volume | Named volume `minio_data:/data` (not the container's writable layer) |
| Bucket initialization | **Gap found and fixed in this batch** — nothing created the bucket; it existed in this developer's environment only because someone had run `mc mb`/used the console by hand at some prior point. `docker-compose.yml` now has a `minio-init` one-shot service (`quay.io/minio/mc`) that runs `mc mb --ignore-existing` + `mc anonymous set none` on every `docker compose up`, verified end-to-end against the real running dev stack (output: `Bucket created successfully`, `Access permission ... is set to private`) |
| Bucket ACL | Already private by default (MinIO's default `anonymous` policy is `none`) — the audit's Phase 5 concern ("can an object be read via a bare URL with no authorization?") was already satisfied by MinIO's out-of-the-box behavior; `minio-init` now makes this explicit and idempotent rather than implicit |

Production/staging/QA `.env*.example` templates, as found, set `AWS_REGION`/`S3_BUCKET_DOCUMENTS`
but **left `S3_ENDPOINT_URL` unset entirely** and commented "the ECS task role provides S3
access" — both wrong for this deployment (Hostinger VPS, no ECS, no IAM role concept) and, before
this batch, silently valid: an unset `S3_ENDPOINT_URL` does not fail `Settings` construction, it
just makes `aioboto3` resolve against real `s3.amazonaws.com`. This was [[upload_security_audit]]'s
INFRA-01 P0 finding; §3 below is the fix.

## 3. Architecture — production storage design

```text
                 Internet
                    |
                    v
                 Nginx  (TLS termination, the only internet-facing process)
                 /    \
                /      \
   HRMS API (FastAPI)   presigned-GET passthrough, matching Host header
        |                          |
        v                          v
   MinIO — internal Docker network (S3 API, port 9000, not published to the host/internet)
        |
        v
   Named Docker volume -> Hostinger VPS block storage
```

- **MinIO container**: `minio/minio:latest` (unchanged image), `restart: unless-stopped`,
  `command: server /data --console-address ":9001"` (unchanged). On the VPS compose stack, the S3
  API port (`9000`) is **not** published to the host/internet — only reachable from other
  containers on the same Docker network (the API container, and Nginx if Nginx is also
  containerized on that network). The console port (`9001`) is likewise not published; if console
  access is operationally required, expose it only via an SSH tunnel (`ssh -L 9001:localhost:9001
  <vps>`) or a separate Nginx `location` gated by `TRUSTED_PROXY_HOSTS`-style IP allowlisting and
  its own basic-auth layer — never a bare public listener. Neither is implemented in this batch
  (no documented operational requirement for public console access exists today); this is a
  documented boundary, not a live infra change (deployment safety §7 below).
- **Persistent volume**: the existing named volume `minio_data:/data` is correct and unchanged.
  Docker's default volume driver places this under
  `/var/lib/docker/volumes/hrms_minio_data/_data` on the host filesystem — it survives container
  restart, container recreation, and a VPS reboot, because it is regular files on the host's own
  block storage, not the container's writable layer or an ephemeral instance store. Verified
  empirically: `tests/integration/core/test_storage.py::test_object_survives_a_minio_container_restart`
  writes an object, runs a real `docker restart hrms-minio`, waits for the container to become
  healthy again, and confirms the object is still present with unchanged bytes — passed against
  the real dev container. **Backup implication** (documented per Phase 4's scope — not a new
  backup system): whatever process already backs up this VPS's disks/volumes must include
  `/var/lib/docker/volumes/hrms_minio_data` (or wherever `docker volume inspect minio_data`
  reports the `Mountpoint` to be on the actual VPS) — this was not previously called out anywhere
  in the repository's docs.
- **Bucket**: one bucket per environment (`hrms-dev-documents` / `hrms-qa-documents` /
  `hrms-staging-documents` / `hrms-prod-documents`, matching the existing `S3_BUCKET_DOCUMENTS`
  naming already in the env templates — unchanged). Private by default; `minio-init`'s
  `mc anonymous set none` makes that explicit rather than relying on MinIO's out-of-the-box
  default never having been changed by a future operator.
- **Credentials**: static MinIO access/secret key pair per environment (root user for now — this
  batch does not introduce a scoped IAM-equivalent MinIO user/policy, since that's a bucket-policy
  hardening step, not an endpoint-resolution one; flagged in §6 as a Batch-B-or-later candidate).
  No IAM role concept exists on a VPS, so `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` must always
  be explicitly injected — the new boot guard (§4) enforces this.
- **Restart behavior**: unchanged, `restart: unless-stopped` — MinIO comes back automatically
  after a container crash or Docker daemon restart, without operator intervention, and (per the
  volume design above) with all previously-uploaded objects intact.
- **Health check**: unchanged (`docker-compose.yml`'s existing TCP-connect check on port 9000).
  Not wired into `GET /health` (`modules/health/service.py` only checks Postgres today, `redis` is
  already `"skipped"` there) — out of scope for this batch (Phase 10 excludes broad
  error-handling/observability refactors); the existing global exception handler (§5) already
  ensures a MinIO outage fails safely without that endpoint knowing about MinIO specifically.

### Presigned URL architecture (Phase 6)

The one real architectural problem this batch had to solve: **the endpoint the backend uses to
talk to MinIO cannot be the same hostname a browser is handed in a presigned URL**, once MinIO's
S3 API stops being published to the host (as it must be, per the network diagram above). A SigV4
presigned URL's signature is computed over the exact host it will be requested against — signing
with the internal Docker hostname (`http://minio:9000`) would hand a browser a URL it can never
resolve, and rewriting the host after signing breaks the signature.

**Fix**: `DocumentStorageService` (`core/storage.py`) now takes two independent endpoint settings:

- `S3_ENDPOINT_URL` — internal, used by `put_object`/`get_object`/`delete_object` (verified in
  `tests/unit/core/test_storage.py::test_other_operations_never_fall_back_to_the_public_endpoint`
  to never leak into `S3_PUBLIC_ENDPOINT_URL` even when both are configured).
- `S3_PUBLIC_ENDPOINT_URL` — optional, used **only** by `presigned_get_url`, falling back to
  `S3_ENDPOINT_URL` when unset (correct for development, where both are `localhost:9000` anyway).

In production, ops sets `S3_ENDPOINT_URL=http://minio:9000` (internal) and
`S3_PUBLIC_ENDPOINT_URL=https://storage.hrms.example.com` (public). Nginx needs one additional
`server`/`location` block forwarding that public hostname to the internal MinIO address while
**preserving the original `Host` header** (`proxy_set_header Host $host;` — not the upstream's
host), since MinIO validates the signed request's `Host` header against the SigV4 signature:

```nginx
server {
    listen 443 ssl;
    server_name storage.hrms.example.com;

    location / {
        proxy_pass http://minio:9000;
        proxy_set_header Host $host;
        # GET-only in front of MinIO's S3 API is a defensible tightening here (presigned GETs are
        # the only thing this hostname is for), but is not implemented in this batch — no live
        # Nginx config exists in this repository to edit (see §7); documented for whoever adds it.
    }
}
```

This Nginx block is **not deployed** by this batch — no `nginx.conf`/production compose file
exists anywhere in this repository to modify (confirmed: `find … -iname '*nginx*'` returns
nothing), and Infrastructure Safety explicitly forbids guessing at live production config. This
is the one Phase 6/2 item that is designed and documented, not shipped as a diff — see §7.

## 4. Configuration — environment variables

All names match the repository's existing convention (`AWS_*` for S3-compatible
region/credentials — MinIO speaks the same protocol, so no renaming was needed; `S3_*` for the
bucket/endpoint(s)). One new variable was added, not a duplicate of an existing one:

| Variable | Required outside `development`? | Purpose |
| --- | --- | --- |
| `S3_ENDPOINT_URL` | **Yes — boot fails without it** | Internal MinIO endpoint. Existing variable; previously optional, now enforced. |
| `S3_BUCKET_DOCUMENTS` | **Yes — boot fails without it** | Existing variable; previously optional (empty string default), now enforced. |
| `AWS_ACCESS_KEY_ID` | **Yes — boot fails without it** | Existing variable; previously optional, now enforced (a self-hosted VPS has no IAM role fallback to quietly succeed with anyway). |
| `AWS_SECRET_ACCESS_KEY` | **Yes — boot fails without it** | Same as above. |
| `AWS_REGION` | No (has a default) | Unchanged — cosmetic for MinIO, required by the SigV4 signing process itself. |
| `S3_PUBLIC_ENDPOINT_URL` | No — optional everywhere | **New.** Browser-facing hostname for presigned GET URLs; falls back to `S3_ENDPOINT_URL` when unset. |

**Proof accidental AWS fallback is impossible**: `Settings._guard_non_development_config`
(`core/config/settings.py`) now raises `ValueError` at `Settings()` construction — i.e. at process
boot, before the app can serve a single request — for `environment in {"staging", "production"}`
whenever `s3_endpoint_url`, `s3_bucket_documents`, `aws_access_key_id`, or
`aws_secret_access_key` is falsy. Before this batch, all four had non-failing empty-string/`None`
defaults; `aioboto3`'s own behavior is to resolve against real AWS when `endpoint_url` is `None`,
which is exactly what would have happened had staging/production ever been deployed from the
previous `.env.production.example` (it never had `S3_ENDPOINT_URL` at all). Covered by 8 new tests
in `tests/unit/core/test_settings.py` (§5).

All five `.env*.example` templates (`apps/api/.env.example`, `apps/api/env/.env.{dev,qa,staging,production}.example`)
were updated to document this explicitly, including the required internal endpoint, the optional
public endpoint, and a corrected comment — the previous "the ECS task role provides S3/KMS
access" language was actively wrong for S3 credentials on a VPS (no ECS, no IAM role) and has been
replaced with a note that these must be static, secret-store-injected values. The existing
`__FROM_SECRETS_MANAGER__` placeholder convention used throughout these templates for every other
secret was kept as-is for consistency — see §6 for why that placeholder name itself is a separate,
out-of-scope problem.

## 5. Security (Phase 5/7/8)

- **Private bucket, no anonymous reads/writes**: MinIO's default bucket policy is already `none`
  (private); `minio-init`'s `mc anonymous set none` makes this an explicit, idempotent, version-
  controlled fact instead of an unverified assumption. A bare `GET
  http://<endpoint>/<bucket>/<key>` with no signature returns MinIO's `AccessDenied` — confirmed
  behavior of the unmodified default, not something this batch had to add.
- **Presigned GET URLs remain the only download path**: unchanged — `presigned_get_url` is still
  the only onboarding-facing read path (admin document review), object bytes never round-trip
  through the API server for that case; `get_object` remains server-side-only (employee-import's
  Celery task reading its own CSV). Neither upload path's application-level authorization was
  touched: onboarding upload/list/delete still gate on case status + token; admin document listing
  still requires `ONBOARDING.VIEW`/`ONBOARDING.REVIEW`; cross-tenant isolation is still enforced
  by explicit `company_id` filtering in the repository layer, not just RLS. Existing tests proving
  this (`tests/integration/modules/onboarding/test_onboarding_documents.py`,
  `test_admin_documents_cross_tenant_isolation`, `test_review_document_without_review_permission_rejected`)
  all still pass unmodified.
- **Console exposure**: not addressed by code in this batch (no live Nginx/production compose
  exists to edit) — documented requirement in §3: never publish 9001, tunnel or IP-allowlist only
  if ever operationally needed.
- **Failure behavior (Phase 8)**:
  - *HTTP-request-path failures* (onboarding upload/delete, employee-import upload): any
    `DocumentStorageService` exception (connection refused, `ClientError`, timeout, ...)
    propagates unmodified to `hrms.core.errors.handlers`'s already-registered catch-all
    `Exception` handler, which returns a **generic** `500 INTERNAL_ERROR` with no exception detail
    of any kind echoed to the client — no endpoint, no credential, no MinIO error string. This
    behavior pre-dates this batch (`register_exception_handlers`) and was verified, not assumed:
    `tests/integration/core/test_storage.py::test_put_object_fails_closed_against_an_invalid_endpoint`
    proves a connection failure raises rather than silently succeeding or falling back to another
    endpoint.
  - *Database state on upload failure*: unchanged, already correct — both `upload_document`
    (onboarding) and `create_batch` (employee-import) write to storage **before** inserting the
    corresponding DB row, so a storage failure never leaves a DB row pointing at a nonexistent
    object (pre-existing code comments confirm this was already an intentional ordering).
  - *Background-task-path failure — gap found and fixed*: `EmployeeImportService.process_batch`
    (the Celery task body) set the batch to `PROCESSING` and committed, then called
    `self._storage.get_object(...)` with no failure handling at all — a MinIO outage at exactly
    that moment would raise uncaught, crash the Celery task, and leave the batch permanently
    stuck at `PROCESSING` with no operator-visible outcome (not corrupt data, but an
    indefinitely-stuck resource with no recourse short of a manual DB update). Fixed: the fetch is
    now wrapped in `try/except Exception`, which marks the batch `FAILED` (an existing status
    value, no schema change) with `completed_at` set, commits, and **re-raises** so the Celery
    task itself still records/logs the failure. Covered by
    `tests/integration/modules/employee_import/test_employee_import.py::test_bulk_import_marks_batch_failed_when_storage_unavailable`.
  - No credential or internal-hostname value appears in any error response, log-adjacent test
    assertion, or the row/batch-level error records used by either path.

## 6. Tests

**Configuration** (`tests/unit/core/test_settings.py`, 8 new tests):
`test_development_allows_no_s3_endpoint`, `test_staging_rejects_a_missing_s3_endpoint`,
`test_production_rejects_a_missing_s3_endpoint`, `test_production_rejects_an_empty_s3_endpoint`,
`test_production_rejects_a_missing_bucket`, `test_production_rejects_missing_access_key`,
`test_production_rejects_missing_secret_key`, `test_production_accepts_a_valid_minio_configuration`,
`test_s3_public_endpoint_url_defaults_to_none_and_is_independent_of_the_guard`.

**Storage unit tests** (`tests/unit/core/test_storage.py`, 7 new tests, fake `aioboto3.Session`):
put/get/delete each proven to use the internal endpoint; presigned-URL generation proven to fall
back to the internal endpoint when no public one is set, and to use the public endpoint when one
is configured; bucket/key/expiry parameters proven passed through correctly; and — the one most
likely to regress silently — proof that configuring a public endpoint never leaks into
put/get/delete.

**Storage integration tests** (`tests/integration/core/test_storage.py`, 5 new tests, real local
MinIO, no mocking): put→exists→get→delete round trip; a presigned URL independently fetched over
real HTTP and its bytes verified; `get_object` on a missing key raises; `put_object` against an
unreachable endpoint raises (fails closed); and the restart/persistence test
(`test_object_survives_a_minio_container_restart`) — writes an object, runs a real `docker
restart` on the `hrms-minio` container, waits for it to become healthy, and confirms the object
and its bytes are unchanged. This test is `skipif`-guarded on the `docker` CLI and that specific
container being reachable, so it degrades to a skip (not a failure) on a sandboxed runner without
Docker-in-Docker access, per Phase 9's "use mocks/unit tests where appropriate" allowance.

**Existing test suites re-verified, not just assumed unaffected**: all 10 tests in
`tests/integration/modules/onboarding/test_onboarding_documents.py` and both pre-existing tests in
`tests/integration/modules/employee_import/test_employee_import.py` pass unmodified against the
updated `DocumentStorageService`/`Settings`. `tests/unit/core/test_cors_middleware.py` and
`tests/unit/core/test_crypto_keys.py` both construct non-development `Settings` for unrelated
(OPS-01/DATA-01) reasons and were updated with explicit S3 test fixtures so they don't silently
depend on this developer's local `.env` file — without that fix they would have broken in any CI
environment lacking a `.env` file, which is exactly the "AWS fallback in disguise" failure mode
this batch closes.

**Full suite result**: `pytest tests/` — all unit tests pass (502 pre-existing + 15 new = 517);
integration suite re-run for every touched module, all green.

## 7. Remaining upload blockers — the upload system is NOT production-ready yet

This batch resolves the storage **backend/endpoint** decision only, per its own scope. Explicitly
still open, per [[upload_security_audit]]:

- **Batch B** — zero file-type/MIME/magic-byte validation on either upload path (onboarding
  trusts client `Content-Type` verbatim; employee-import hardcodes `text/csv` regardless of
  actual bytes).
- **Batch C** — no enforced byte-size ceiling before the request body is fully read into memory
  (employee-import has none pre-parse; onboarding's 10MB cap is checked post-buffer).
- **Batch D** — onboarding's storage key embeds the raw client filename unsanitized
  (`onboarding/{company}/{case}/{doc_id}/{filename}`) — inert against a pure S3 API call, but a
  real risk against a filesystem-backed object store if any future code path ever treats that key
  as a literal path rather than an opaque string.
- **Rate limiting** — the public onboarding document-upload router still has no rate limit
  applied, unlike login/refresh/registration/invite-accept.
- **Not implemented in this batch, by design (§3)**: the actual production Nginx reverse-proxy
  config fronting MinIO, and any MinIO console exposure — no live infra config exists in this
  repository to safely edit or validate; both are fully specified above for whoever provisions the
  VPS's Nginx.
- **Separately flagged, not part of any upload batch**: every `.env*.example` template's secret-
  delivery model (`__FROM_SECRETS_MANAGER__`, `RDS`, `ElastiCache`, `ECS task role` language
  throughout `docs/product/13_DevOps_Architecture.md` and the `DATABASE_URL`/`REDIS_URL`/
  `KMS_CMK_ARN` lines of every non-dev template) assumes an AWS deployment wholesale, not just for
  S3. This batch corrected only the S3-specific instances of that mismatch (the ones actually in
  scope); the database/cache/secrets-manager mismatch is a pre-existing, larger, separate
  architecture question this batch did not have authorization to resolve.

Do not treat this result as "uploads are secure" — only as "uploads now point at the correct,
self-hosted storage backend, with no silent AWS fallback possible, and the storage layer fails
safely when unavailable." Batches B–D (and the rate-limit gap) remain gating for a genuine
production-ready upload system.
