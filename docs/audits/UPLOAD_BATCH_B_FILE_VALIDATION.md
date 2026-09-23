# Upload Security Batch B — File Validation & Upload Hardening

## 1. Objective

Close two production-audit findings against the two real upload paths this application has
([[upload_security_audit]]), without redoing or regressing Batch A
(docs/audits/UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md — self-hosted MinIO, private bucket, dual
internal/public endpoints, boot-time AWS-fallback guard) and without touching anything outside
upload safety (PAN/Aadhaar/bank encryption, pagination, login rate limiting, JWT secrets, CORS,
proxy handling, email verification, password reset, RBAC, attendance/timezone, leave, payroll,
Nginx production config):

- **SEC-03** — the public onboarding document-upload endpoint buffered the entire request body
  into memory (`body = await file.read()`) before any size check ran, and the endpoint is
  reachable without authentication.
- **SEC-04** — uploaded content type was trusted verbatim from the client, replayed on download,
  the object key embedded the raw client filename, and presigned downloads carried no
  `Content-Disposition` override, so an uploaded HTML/SVG file could in principle render in a
  browser instead of downloading.

## 2. Production Audit Findings Addressed

| Task label | Prior audit label(s) | Description |
| --- | --- | --- |
| SEC-03 | SEC-006 (`PAYROLL_BLOCKER_REGISTER.md`), FIND-02/03 ([[upload_security_audit]]), "Batch C" (`UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md` §7) | Unbounded buffering before size check |
| SEC-04 | SEC-005 (`PAYROLL_BLOCKER_REGISTER.md`), FIND-01/FIND-04 ([[upload_security_audit]]), "Batch B"/"Batch D" (`UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md` §7) | No MIME/magic-byte validation, unsanitized filename in the object key, no forced download disposition |

The task brief's own SEC-03/SEC-04 numbering is a new, independent scheme from this repository's
existing `SEC-0NN` audit labels — both are cross-referenced above to avoid confusion with the
already-closed SEC-01/SEC-02 (`PRODUCTION_HARDENING_BATCH_1_REPORT.md`).

## 3. Files Changed

**New:**
- `apps/api/src/hrms/core/uploads.py` — `MaxUploadSizeMiddleware` (ASGI-level early/streaming
  size guard) and `read_upload_bounded` (chunked `UploadFile` read).
- `apps/api/src/hrms/modules/onboarding/document_validation.py` — magic-byte sniffing
  (`sniff_document_content_type`), filename sanitization (`sanitize_display_filename`), safe
  object-key construction (`safe_document_object_key`), forced-download header
  (`content_disposition_attachment`).

**Modified:**
- `apps/api/src/hrms/app.py` — wires `MaxUploadSizeMiddleware` for the two upload paths.
- `apps/api/src/hrms/core/storage.py` — `presigned_get_url` gains an optional
  `response_content_disposition` parameter (S3's `ResponseContentDisposition` override).
- `apps/api/src/hrms/modules/onboarding/service.py` — `upload_document` sniffs/validates content,
  sanitizes the display filename, builds a safe object key; `list_documents_with_urls` forces
  attachment disposition on every presigned URL.
- `apps/api/src/hrms/modules/onboarding/public_router.py` — bounded read instead of
  `await file.read()`.
- `apps/api/src/hrms/modules/onboarding/exceptions.py` — new `UnsupportedDocumentContentError`.
- `apps/api/src/hrms/modules/employee_import/service.py` — file-size check before parsing; fixed,
  non-client-derived object-key filename component.
- `apps/api/src/hrms/modules/employee_import/router.py` — bounded read instead of
  `await file.read()`.
- `apps/api/src/hrms/modules/employee_import/exceptions.py` — new `ImportFileTooLargeError`.
- `apps/api/src/hrms/modules/employee_import/schemas.py` — new `MAX_IMPORT_FILE_SIZE_BYTES`.

**Tests (new):**
- `apps/api/tests/unit/core/test_uploads.py`
- `apps/api/tests/unit/modules/onboarding/test_document_validation.py`
- `apps/api/tests/integration/modules/onboarding/test_onboarding_upload_bounds.py`
- `apps/api/tests/integration/modules/employee_import/test_employee_import_upload_bounds.py`

**Tests (modified — existing fixtures used fake, non-magic-byte-matching bytes for "success"
cases, which the new SEC-04 validation now correctly rejects; updated to real minimal
signatures, not weakened):**
- `apps/api/tests/integration/modules/onboarding/test_onboarding_documents.py`

## 4. Upload Paths Reviewed

| Upload path | Auth | File type | Size enforcement (before) | Size enforcement (after) | Storage | Download path |
| --- | --- | --- | --- | --- | --- | --- |
| `POST /public/onboarding/{token}/documents` | Token-gated, unauthenticated | PAN/Aadhaar/photo/certificate images or PDFs | `await file.read()` then a 10MB post-buffer check | ASGI middleware (12MB ceiling) + bounded chunked read + unchanged 10MB business check | `DocumentStorageService.put_object`, safe generated key | Admin-only presigned GET, now forced `attachment` |
| `POST /employee-imports` | JWT + `EMPLOYEE.BULK_IMPORT` permission | Employee CSV | `await file.read()`, no size check pre-parse (only a 1000-row cap post-parse) | ASGI middleware (6MB ceiling) + bounded chunked read + new 5MB business check | `DocumentStorageService.put_object`, fixed `import.csv` key | Server-side only (`get_object`, Celery task) — never a presigned URL, never rendered to a browser |

No third upload path exists — confirmed by re-grepping the whole `apps/api/src` tree for
`UploadFile`/`File(`/`await .*\.read\(\)` outside these two routers, matching
[[upload_security_audit]]'s original inventory.

## 5. Size Enforcement

Two independent layers, because FastAPI's own dependency-injection machinery calls `await
request.form()` — fully parsing and spooling the multipart body — *before* any `Depends()` or the
endpoint function itself runs. A `Content-Length` check or bounded read written inside the route
handler therefore cannot prevent the framework from already having received the full body; only
an ASGI-level guard, positioned ahead of routing, can.

1. **`MaxUploadSizeMiddleware`** (`hrms/core/uploads.py`, wired in `app.py`, scoped by path
   prefix — not a general request-body limiter): checks `Content-Length` early when present and
   honest; independently tracks the actual bytes read from the ASGI `receive()` channel and
   aborts as soon as the running total exceeds the ceiling, regardless of what `Content-Length`
   claimed (covers missing/wrong/absent headers and chunked transfer). On overflow it constructs
   and sends a `413 PAYLOAD_TOO_LARGE` response directly at the ASGI layer — Starlette's
   `ExceptionMiddleware` (which dispatches `@app.exception_handler`-registered handlers) sits
   *inside* all user-added middleware, so an exception raised by a middleware itself would
   otherwise fall through to `ServerErrorMiddleware`'s generic, unstructured 500. This was caught
   by the unit tests in `test_uploads.py` before it ever reached an integration test.
2. **`read_upload_bounded`** (same module, used in both routers in place of the flagged
   `await file.read()`): reads the already-admitted `UploadFile` in 1MB chunks, stopping once the
   running total exceeds the caller's cap. Does not itself raise — it hands back a
   bounded-length result and lets the existing, specific business-rule error
   (`OnboardingDocumentTooLargeError` / new `ImportFileTooLargeError`) fire exactly as before from
   the resulting length. Defense-in-depth: bounds the application's own in-memory `bytes` object
   even if a request already passed layer 1's more generous ceiling.

Ceilings (`app.py`): each is the corresponding per-file business limit plus headroom for
multipart overhead (boundary markers, part headers, the `document_type` field sharing the
request) — `ONBOARDING_DOCUMENT_MAX_SIZE_BYTES + 2MB` (12MB) for onboarding,
`MAX_IMPORT_FILE_SIZE_BYTES + 1MB` (6MB) for employee-import. The exact per-file number is still
enforced by the unchanged/new business-rule checks, not the middleware.

`MAX_IMPORT_FILE_SIZE_BYTES = 5 * 1024 * 1024` is this task's own engineering decision — no
source document named a byte ceiling for the import CSV (only the existing 1000-row cap, itself
enforced *after* parsing), so it was sized the same way `ONBOARDING_DOCUMENT_MAX_SIZE_BYTES`
(10MB) already was: generous for the documented 50–5,000 row target range while still bounding
worst-case memory/storage use ahead of the row-count check.

## 6. MIME Validation

No source document (plan, schema, or product spec) names an allowed file-type list for onboarding
documents. This is this task's own engineering decision, flagged as an open ambiguity rather than
a silent product call: **PDF, JPEG, PNG** — the minimal set covering a phone-camera ID-document
photo or a scanned/exported certificate, matching what the web wizard's tests and the existing
test fixtures already assumed. Widening this list (HEIC, WebP, TIFF, ...) is a product decision,
not an engineering one, and is called out in §15.

The client's `UploadFile.content_type` header is never trusted or persisted. Every accepted
upload's `content_type` — in the API response, the stored object's S3 `ContentType`, and the
object key's extension — comes from `sniff_document_content_type(data)` instead, which classifies
purely from the file's own magic bytes. A caller claiming one type for bytes that sniff to a
*different supported* type is silently normalized to the real type (documented design choice —
bytes are authoritative, the claimed header is not); a caller whose bytes don't match any
supported signature is rejected outright regardless of what was claimed
(`UnsupportedDocumentContentError`, 422).

Employee-import's CSV upload already hardcoded `content_type="text/csv"` server-side before this
batch — the client's header was already ignored, so no change was needed there for the
MIME-trust half of SEC-04. See §15 for why magic-byte sniffing itself doesn't extend to CSV.

## 7. Magic-Byte Validation

`sniff_document_content_type` (`hrms/modules/onboarding/document_validation.py`) checks the
file's own byte prefix against three signatures:

| Format | Signature | Content-Type |
| --- | --- | --- |
| PDF | `%PDF-` | `application/pdf` |
| JPEG | `FF D8 FF` | `image/jpeg` |
| PNG | `89 50 4E 47 0D 0A 1A 0A` | `image/png` |

No content-sniffing/`libmagic` dependency was added — a manual prefix check is sufficient for a
closed, three-format allowlist and avoids a new native-library dependency for this batch. Not
implemented (and not claimed): deep/structural validation (e.g. parsing the PDF object tree,
decoding the JPEG), so a file that has a correct magic-byte prefix but is otherwise malformed or
carries embedded malicious content past the header is not caught by this batch — see §15.

## 8. Filename/Object-Key Safety

`sanitize_display_filename` and `safe_document_object_key` split the client-supplied filename
into two independent uses that never share a code path:

- **Object key (storage-path authority)** — never derived from the client filename at all.
  `safe_document_object_key` returns
  `onboarding/{company_id}/{case_id}/{document_id}/document{extension}`, where `extension` comes
  from the verified sniffed type, not the client's claimed filename. `employee-import`'s key is
  the fixed literal `employee-imports/{company_id}/{batch_id}/import.csv` (the format is always
  CSV, so no extension-selection logic was needed there). Neither key can ever contain a path
  separator, `..`, or any other client-controlled byte — `company_id`/`case_id`/`document_id`/
  `batch_id` are server-generated UUIDs, and every remaining path segment is a fixed literal.
- **Display filename (metadata only)** — `sanitize_display_filename` strips any directory
  component, drops non-printable characters (including the CR/LF that would otherwise allow
  response-header injection into a later `Content-Disposition`), replaces anything outside a
  small safe-ASCII allowlist (letters, digits, `._ -`) with `_`, and falls back to a fixed name if
  nothing safe survives. Stored as `original_filename` and reused (unchanged, no further
  transformation needed) as the `Content-Disposition` filename on download — see §9.

Employee-import's `original_filename` is **not** run through this sanitizer — it's returned only
as a plain JSON field to the React admin UI (auto-escaped, no stored-XSS surface) and is never
used in an HTTP header (employee-import has no presigned-download path at all, §4), so the
header-injection/path-authority risk this sanitizer exists for doesn't apply there. Its only
real risk — the object key — is already closed by the fixed `import.csv` literal.

## 9. Download Security

`DocumentStorageService.presigned_get_url` (`hrms/core/storage.py`) gained an optional
`response_content_disposition` parameter, mapped to S3's standard `ResponseContentDisposition`
query-string override on the signed `GetObject` request. `OnboardingDocumentService.
list_documents_with_urls` now passes `content_disposition_attachment(document.original_filename)`
on every presigned URL it issues, forcing
`Content-Disposition: attachment; filename="<sanitized-name>"` on the response itself —
independent of whatever `ContentType`/`Content-Disposition` was set (or not set) on the stored
object at upload time. Verified against real MinIO
(`test_admin_list_documents_has_download_url`): the presigned URL's query string carries
`response-content-disposition`, and an actual HTTP `GET` against that URL returns the header and
forces a download rather than in-browser rendering.

Employee-import never issues a presigned URL (§4) — `get_object` is server-side only, read by the
Celery import task, never handed to a browser — so this finding doesn't apply to that path; no
change was made there.

**Known gap, not closed by this batch:** onboarding documents uploaded *before* this batch has
their pre-existing, unsanitized `original_filename` in the database — no backfill/migration was
run (out of scope: this repository has no production data yet, per the broader pre-payroll gating
docs, and a backfill is a data-migration decision, not an upload-hardening one). Any such
pre-existing row would still get `Content-Disposition: attachment`, which is the actual
XSS-prevention mechanism — the sanitizer is defense-in-depth against header injection, not the
primary control.

## 10. Authorization Preservation

No RBAC, tenant-scoping, or permission-check code was touched. Verified, not assumed —
`test_admin_documents_cross_tenant_isolation` and `test_review_document_without_review_permission_
rejected` (both pre-existing, `test_onboarding_documents.py`) pass unmodified in behavior (only
their upload fixtures changed from fake to magic-byte-valid bytes, per §3); tenant/permission
enforcement itself was not touched by any edit in this batch.

## 11. Storage Failure Handling

Batch A's storage-failure behavior (`DocumentStorageService` exceptions propagate to the
catch-all `500` handler; `EmployeeImportService.process_batch` marks a batch `FAILED` rather than
leaving it stuck at `PROCESSING` on a MinIO outage) was not touched. The relevant Batch A test
(`test_bulk_import_marks_batch_failed_when_storage_unavailable`) passes unmodified.

This batch's own size/content checks all run **before** any storage write
(`put_object`) — an oversized or invalid-content upload never reaches MinIO at all, so there is no
new partial-object/cleanup scenario introduced by this batch: rejection happens purely in-request,
before the existing "storage write, then DB insert" ordering (Batch A, unchanged) ever begins.

## 12. Tests

34 new unit tests (`test_uploads.py`, `test_document_validation.py`) covering the full SEC-03 size
matrix (below/exactly/one-byte-above the cap, missing/wrong/very-large declared `Content-Length`,
streaming without a trustworthy header) and the full SEC-04 MIME/magic-byte and filename matrix
(correct signature per format, HTML/JS/random-binary/empty/truncated/polyglot rejection, path
traversal in both slash conventions, control characters, unicode, absurd length, SQL/script-tag
injection attempts).

15 new integration tests against the real onboarding and employee-import endpoints
(`test_onboarding_upload_bounds.py`, `test_employee_import_upload_bounds.py`) proving the same
behavior end-to-end through the actual ASGI middleware stack, FastAPI DI, and
`DocumentStorageService` — including the three-way size boundary (accepted / over business limit
under the ASGI ceiling / over the ASGI ceiling itself, each producing the *specific* expected
error) and a real presigned-URL fetch verifying the `Content-Disposition` header and byte-for-byte
content match.

10 existing onboarding-document integration tests updated (not weakened) to use real magic-byte
fixtures instead of arbitrary fake bytes, since the new SEC-04 validation correctly rejects what
those fixtures previously contained.

## 13. Real MinIO Verification

All new/updated integration tests run against the real local MinIO container (`docker-compose.yml`
`minio` service), no mocking of `DocumentStorageService` — consistent with Batch A's own testing
posture. Specifically verified against real MinIO: successful upload of each supported format,
MIME/magic-byte rejection, size rejection at both layers, the safe object key actually present at
its expected path (`_s3_object_exists` via `boto3.head_object`) and the unsafe raw-filename path
*not* present, a real presigned-URL `GET` returning the forced `Content-Disposition` header and
correct bytes. Batch A's own restart/persistence test was not touched and was re-run as part of
the full suite (§14) — no regression.

## 14. Regression Results

```
apps/api $ .venv/bin/python -m pytest -q
1 failed, 1473 passed in 278.42s (0:04:38)
```

The one failure, `tests/integration/modules/organisation/test_registration_flow.py::
test_registration_success_full_row_graph`, asserts the exact seeded default-permission set for a
newly registered company and finds three extra permissions present (`SETTINGS.ROLE.MANAGE`,
`SETTINGS.USER.MANAGE`, `EMPLOYEE.INVITE`) beyond what the test currently expects. This is an
RBAC/default-role-seeding drift — the same category as the Batch A baseline's documented
"1 pre-existing unrelated RBAC failure" — not an upload-path test, not touched by any file in §3,
and not affected by anything this batch changed (no RBAC/permission/role code was modified).
**Classification: PRE-EXISTING, not a Batch B regression** (task scope rule §21/§16: this batch
does not modify RBAC).

`ruff check` and `mypy` were run against every file touched by this batch (§3) — both clean,
zero errors. (Pre-existing, unrelated `E501` line-length violations exist in three
`alembic/versions/*.py` migration files and were left untouched, per scope discipline — not part
of this batch's changes.)

Batch A's own tests (`tests/unit/core/test_storage.py`, `tests/integration/core/test_storage.py`,
`tests/integration/modules/onboarding/test_onboarding_documents.py`'s pre-existing cases,
`tests/integration/modules/employee_import/test_employee_import.py`) all pass — re-verified, not
assumed, individually before the full-suite run (§13).

## 15. Known Remaining Findings

Explicitly **not** closed by this batch:

- **No malware/AV scanning** — magic-byte validation proves a file's *header* matches a supported
  format; it does not scan for embedded exploits, macros, or malformed-but-signature-valid
  content. Flagged as out of scope from the very first audit ([[upload_security_audit]]) and
  reiterated here per the task brief's own instruction not to claim scanning that doesn't exist.
- **No structural/deep file validation** — a byte sequence that starts with a valid PDF/JPEG/PNG
  signature but is otherwise corrupt or malformed past the header is accepted; only the prefix is
  checked (§7).
- **No rate limiting on the public onboarding upload endpoint** — explicitly out of scope for this
  batch per the task brief (§16 of the brief); still open from [[upload_security_audit]]'s
  FIND-05, and from the original audit's own Batch-E-equivalent backlog item. A future batch
  should add the same `shared/rate_limit.py` primitive already used for login/refresh/
  registration/invite-accept.
- **No scoped (non-root) MinIO credentials** — unchanged from Batch A §6, still a static
  root-user key pair per environment.
- **No backfill of pre-existing document filenames** — §9's known gap; the primary XSS control
  (forced `Content-Disposition: attachment`) applies uniformly regardless, but the display
  filename itself is unsanitized for any document row inserted before this batch.
- **No CSV structural/content validation beyond the existing shape check** — `employee_import`'s
  `_parse_and_validate_shape` (`csv.DictReader` over `.decode("utf-8-sig")`) can raise an
  unhandled `UnicodeDecodeError` (→ generic `500`) for a non-UTF-8 binary file uploaded with a
  `.csv` extension. Pre-existing, not introduced by this batch, and not named by SEC-03/SEC-04 —
  flagged here rather than silently fixed, per the task's scope-discipline instruction not to
  mechanically "fix" unrelated failures. Worth a dedicated small follow-up (catch
  `UnicodeDecodeError` and translate it into the existing `ImportHeaderInvalidError`-style 422),
  but out of scope for this batch.
- **The MIME allowlist itself (PDF/JPEG/PNG) is an engineering decision, not a product one** — see
  §6; widening it is a product call for a future batch, not a bug in this one.

## 16. Final Status

```
Batch A:  PASS (unchanged, re-verified)
Batch B:  PASS

Overall upload security:  NOT READY FOR PRODUCTION

  - SEC-03 and SEC-04 are closed for both real upload paths.
  - Batches C/D-equivalent items from Batch A's own §7 backlog (rate limiting on the public
    onboarding endpoint; scoped, non-root MinIO credentials) remain open, as do the malware-
    scanning and pre-existing-row-filename-backfill gaps named in §15 above.
  - This batch does not claim, and this report does not assert, that the upload system —
    or the platform — is production-ready as a whole.
```
