# Production Hardening Consolidation Audit

**Type:** Read-only working-tree audit. No files were edited, staged, committed, reset, stashed, or reverted to produce this report. This document is the sole artifact created by this task.

**Date:** 2026-09-20
**Branch:** `main` @ `c3b8cec` (up to date with `origin/main`... actually `origin/main` is pinned at `713c539`; everything from `481641d` through `c3b8cec` — 10 commits — is local-only and unpushed)
**Scope:** everything currently uncommitted in the working tree, cross-referenced against `docs/audits/*.md` and live code.

---

## 1. Executive Summary

The working tree contains **eight distinct, mostly-real production-hardening workstreams**, all uncommitted, all mixed together across a small number of shared files. Verification (four parallel research passes, each reading the actual diffs/code/tests, plus direct inspection of ~30 files by the author of this report) found:

- **Upload Batches A, B, and C are genuinely complete** — real code, real tests, tests independently re-run and passing (with one caveat below). This matches what their own reports claim.
- **Pagination (API-01) is genuinely complete** for the 7 endpoints it targets (Tier 1). Independently re-run: 31/31 integration tests + 9/9 unit tests green. Tier 2 endpoints are deliberately left unpaginated behind a hardcoded safety-net `LIMIT`.
- **PII encryption (DATA-01) is real but partial.** The crypto primitives, the one live write path it targets (`employee_bank.account_number_enc` + `onboarding_case.bank_info`), and 94 tests are genuinely implemented and passing. But: no real KMS key has ever been provisioned in any environment (staging/production will refuse to boot by design until an operator does this), two compliance-sensitive remediation steps (historical audit-log redaction, onboarding post-activation cleanup) are explicitly *not* implemented pending sign-off that hasn't happened, and PAN/Aadhaar fields remain unencrypted (no write path exists for them — out of scope for this batch, not a bug). **DATA-01 is not closeable as a finding yet, and the plan document's own final checklist is 100% unchecked despite prose describing it as "COMPLETE."**
- **CORS (OPS-01), JWT secret hardening (SEC-01), credential rate limiting (SEC-02), and proxy-aware IP resolution (OPS-02)** all appear genuinely fixed per `PRODUCTION_HARDENING_BATCH_1_REPORT.md`, with a previously-reported full-suite result of 1303 passed / 1 known failure.
- **A single settings function (`Settings._guard_non_development_config`) interleaves four unrelated workstreams' boot-time validation in one contiguous function body** (SEC-01 + OPS-01 + Upload-Batch-A + DATA-01). This is the one place in the whole tree where a clean per-workstream commit split is *not* mechanically possible without manual rewriting.
- **Three files with no discernible relationship to any hardening workstream are sitting untracked at the repo root**: `mavericks-kit.zip` (3.8MB), `shirt.png`, `shorts.png` (~1.9MB each, both dated today). These must not be committed and should be confirmed with the user before any `git add`.
- 14 of the 22 originally-scoped P0/P1/P2 findings remain **OPEN** (untouched by this round of work) — see §7.
- The known pre-existing test failure (`test_registration_success_full_row_graph`, 3 missing RBAC permission codes) was independently reproduced in this session — confirmed real, confirmed unrelated to any of the above.

**Bottom line for this task:** the working tree is coherent and mostly trustworthy, but it is **not one unit of work** — it needs to be split into at minimum 7 commits, one of which (`settings.py`'s guard function) requires hand-editing to separate cleanly. See §13 for the recommended sequence.

---

## 2. Current Git State

```
Branch:            main
HEAD:              c3b8cec fix(rbac): grant approval authority to HR_ADMIN, REPORTING_MANAGER, and BRANCH_MANAGER
origin/main:        713c539 feat(onboarding): implement O7 — activation into real Employee records
Local-only commits: 10 (481641d..c3b8cec — employee_import, comp-off, employee confirmation,
                     attendance/timezone, RBAC/account-invites, all already merged to local main
                     and NOT part of this audit's scope; they predate the working-tree changes below)
Staged changes:     none (git diff --cached is empty)
Unstaged modified:  36 files (apps/api) + 27 files (apps/web) + docker-compose.yml = 64 files
Untracked:          ~45 paths (new source files, new test files, new docs, and 3 unrelated files)
Deleted:            none
```

Full `git diff --stat`: 66 tracked files changed, 2497 insertions(+), 354 deletions(-).

---

## 3. Committed Baseline

Everything at and before `c3b8cec` is **out of scope** for this audit — it's already landed on local `main` (RBAC/BRANCH_MANAGER work, account invites, attendance/timezone remediation, employee confirmation workflow, comp-off, CSV import). Per user memory, this baseline is understood and stable. This audit concerns only what sits on top of it, uncommitted.

Note: local `main` is 10 commits ahead of `origin/main`. That gap is pre-existing and not something this task should touch (no push was requested, none performed).

---

## 4. Uncommitted Work Inventory

Eight workstreams, all uncommitted, identified by content (not by trusting filenames or doc claims):

| Code | Workstream | Backing doc(s) | Verified status |
|---|---|---|---|
| A | Upload Batch A — storage architecture (MinIO/S3 endpoint split, boot guard) | `UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md` | **COMPLETE** |
| B | Upload Batch B — file validation (magic-byte sniff, size middleware, safe keys) | `UPLOAD_BATCH_B_FILE_VALIDATION.md` | **COMPLETE** |
| C | Upload Batch C — onboarding-upload rate limiting | `UPLOAD_BATCH_C_RATE_LIMITING.md` | **COMPLETE** |
| D | PII encryption (DATA-01) | `DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` + 2 more | **PARTIAL** — see §1, §11 |
| E | Pagination (API-01) | `API_01_PAGINATION_IMPLEMENTATION_REPORT.md` | **COMPLETE** (Tier 1 scope) |
| F | CORS (OPS-01) | `PRODUCTION_HARDENING_BATCH_1_REPORT.md` | **COMPLETE** per report; spot-checked, consistent |
| G | Proxy-aware rate limiting / IP resolution (OPS-02) | `PRODUCTION_HARDENING_BATCH_1_REPORT.md` | **COMPLETE** per report; spot-checked, consistent |
| H | Credential rate limiting (SEC-02) | `PRODUCTION_HARDENING_BATCH_1_REPORT.md` | **COMPLETE** per report; spot-checked, consistent |
| K | Other production hardening (JWT secret enforcement, SEC-01) | `PRODUCTION_HARDENING_BATCH_1_REPORT.md` | **COMPLETE** per report; spot-checked, consistent |
| L | Unrelated | — | 3 files, flagged, not to be committed |

F, G, H, K were verified primarily via the report + the cross-file diff agent's line-by-line read of `app.py`/`settings.py`/`rate_limit.py`/`identity/router.py` (§6) rather than an independent test re-run in this session — their own report states a full-suite result of **1303 passed, 1 failed (pre-existing, unrelated)**, consistent with everything else found.

---

## 5. Workstream Classification — Full File Table

Legend: A=Batch A, B=Batch B, C=Batch C, D=PII encryption, E=Pagination, F=CORS, G=Proxy RL, H=Credential RL, I=RBAC (already committed, N/A here), J=Attendance/TZ (already committed, N/A here), K=Other hardening, L=Unrelated, M=Unknown.

### Backend — core/shared (multi-workstream files)

| File | Classification | Why | Related finding | Safe to commit independently? |
|---|---|---|---|---|
| `apps/api/src/hrms/app.py` | F+G+D+B+C | 5 block-separable additions: CORS origin swap, lifespan KMS-key-count guard, 2× `MaxUploadSizeMiddleware` registration, `OnboardingUploadRateLimitMiddleware` registration, `ProxyHeadersMiddleware` registration | OPS-01, OPS-02, DATA-01, SEC-03/Batch B, Batch C | **Partially** — hunks are physically separable, but middleware *registration order* is load-bearing: Batch C's rate limiter must land after (outermost of) OPS-02's `ProxyHeadersMiddleware` or it keys on the proxy's IP instead of the real client IP. Commit OPS-02 before/with Batch C. |
| `apps/api/src/hrms/core/config/settings.py` | K+F+G+A+D | New fields cleanly attributable per-workstream (`cors_allowed_origins`→F, `trusted_proxy_hosts`→G, `s3_public_endpoint_url`→A, `kms_cmk_arn`/`dev_encryption_key`/`encryption_dek_cache_ttl_seconds`→D), **but** `_guard_non_development_config` is one function with sequential K+F+A+D checks in one body, and `_parse_comma_separated` serves both F and G fields | SEC-01, OPS-01, OPS-02, Upload Batch A, DATA-01 | **NO, not cleanly** — this is the one file in the tree that needs manual hand-splitting (not a mechanical `git add -p`) to separate into per-workstream commits. See §6. |
| `apps/api/src/hrms/core/storage.py` | A+B | `_client_kwargs(endpoint_url=...)` (A) and `presigned_get_url`'s new `response_content_disposition` param (B) are interleaved in the same method body | Upload Batch A, SEC-04/Batch B | **Mostly** — needs a manual split of one hunk (`presigned_get_url`), everything else in the file is Batch A only |
| `apps/api/src/hrms/shared/rate_limit.py` | H+C | Three genuinely independent implementations appended back-to-back: pre-existing `rate_limit()`, new `rate_limit_by_ip_and_email()` (H), new `OnboardingUploadRateLimitMiddleware` class (C) — no shared state or code path | SEC-02, Batch C | **YES** — cleanly, by function/class boundary |
| `apps/api/.env.example`, `apps/api/env/.env.{dev,production,qa,staging}.example` (5 files) | F+G+A+D+K | Repeated pattern per file: `ENVIRONMENT=` comment (K), `CORS_ALLOWED_ORIGINS` block (F), `TRUSTED_PROXY_HOSTS` block (G), MinIO/S3/AWS creds block (A), `KMS_CMK_ARN`/`DEV_ENCRYPTION_KEY`/`ENCRYPTION_DEK_CACHE_TTL_SECONDS` block (D) | all five | **YES with manual hunk-splitting** — config blocks are adjacent but not code-interleaved; `git add -p` with `s` (split) needed since diff hunks group adjacent unrelated blocks |
| `docker-compose.yml` | A | Single addition: `minio-init` service (bucket creation/lockdown) | Upload Batch A | **YES**, trivially its own commit |

### Backend — module files (single-workstream, per direct+agent verification)

| File | Classification | Why | Safe independently? |
|---|---|---|---|
| `apps/api/src/hrms/modules/identity/router.py` | H | `rate_limit_by_ip_and_email` wired onto `login()`/`refresh_token()` only | YES |
| `apps/api/tests/conftest.py` | H | Autouse fixture resetting `ratelimit:login:*`/`ratelimit:token_refresh:*` buckets between tests | YES |
| `apps/api/tests/integration/auth/test_credential_rate_limit.py` (new) | H | Dedicated SEC-02 test file | YES |
| `apps/api/tests/unit/shared/test_rate_limit_dual_bucket.py` (new) | H | Unit tests for the dual IP+email bucket | YES |
| `apps/api/tests/unit/core/test_cors_middleware.py` (new) | F | Dedicated OPS-01 test file | YES |
| `apps/api/tests/unit/core/test_proxy_headers.py` (new) | G | Dedicated OPS-02 test file | YES |
| `apps/api/tests/integration/test_proxy_aware_rate_limiting.py` (new) | G | Integration coverage for proxy-aware IP resolution feeding rate limits | YES |
| `apps/api/tests/unit/core/test_settings.py` (new, 286 lines) | K+F+G+A+D (bundled) | Covers the shared `_guard_non_development_config`/`_parse_comma_separated` validators for all four workstreams in one file — mirrors the settings.py interleaving | Splittable by test function, not by file |
| `apps/api/src/hrms/core/uploads.py` (new) | B | `MaxUploadSizeMiddleware` + `read_upload_bounded` | YES |
| `apps/api/src/hrms/modules/onboarding/document_validation.py` (new) | B | Magic-byte sniffing, filename sanitizer, safe object-key builder | YES |
| `apps/api/tests/unit/core/test_uploads.py` (new) | B | | YES |
| `apps/api/tests/unit/modules/onboarding/test_document_validation.py` (new) | B | | YES |
| `apps/api/tests/integration/modules/onboarding/test_onboarding_upload_bounds.py` (new) | B | | YES |
| `apps/api/tests/integration/modules/employee_import/test_employee_import_upload_bounds.py` (new) | B | | YES |
| `apps/api/src/hrms/modules/onboarding/exceptions.py` | B | New `UnsupportedDocumentContentError` etc. | YES |
| `apps/api/src/hrms/modules/onboarding/public_router.py` | B | Bounded-read wiring only (Batch C touches nothing here — no route-level dependency, confirmed by agent) | YES |
| `apps/api/src/hrms/modules/employee_import/{exceptions,router,schemas}.py` | B | Upload validation/size wiring for CSV import | YES |
| `apps/api/src/hrms/modules/employee_import/service.py` | A+B | Storage-outage → FAILED handling (A, "Phase 8") + pre-parse size check (B) | Mostly — two distinct additions, not interleaved in the same lines per direct read |
| `apps/api/tests/integration/modules/employee_import/test_employee_import.py` | A | New `test_bulk_import_marks_batch_failed_when_storage_unavailable`, explicitly labeled "Upload Security Batch A, Phase 8" in its own docstring | YES |
| `apps/api/tests/unit/core/test_storage.py`, `apps/api/tests/integration/core/test_storage.py` (new) | A | | YES |
| `apps/api/tests/integration/modules/onboarding/test_onboarding_documents.py` | B | SEC-04 content-sniffing assertions added to existing doc-upload tests | YES |
| `apps/api/tests/integration/modules/onboarding/conftest.py` | C | Autouse fixture resetting `ratelimit:onboarding_upload:*` buckets | YES |
| `apps/api/tests/integration/modules/onboarding/test_onboarding_upload_rate_limit.py`, `apps/api/tests/unit/shared/test_onboarding_upload_rate_limit_middleware.py` (new) | C | | YES |
| `apps/api/src/hrms/core/crypto/*.py` (10 files, new) | D | Full envelope-encryption implementation — real AES-256-GCM, AAD, key registry, KMS client, DEK cache, provisioning, backfill | YES (this is the clean core of DATA-01) |
| `apps/api/src/hrms/core/audit/redact.py` (new) | D | `mask_sensitive()` for audit-log PII masking | YES |
| `apps/api/alembic/versions/20260927090000_encryption_key_registry.py` (new) | D | Creates *only* `encryption_keys` table + partial unique index; touches no PII columns | YES — single head, no conflict (§9) |
| `apps/api/src/hrms/modules/employee/{models,service,schemas,repository}.py` | D (models/service/schemas) + E (repository) | `models.py`/`service.py`/`schemas.py`: PII encrypt/decrypt wiring, `bank_to_read`'s new required `decrypted_account_number` kwarg, audit redaction. `repository.py`: pagination `.limit/.offset` on `list_employees` | Split by file: `repository.py` is E-only and independent; the other three are D and move together |
| `apps/api/src/hrms/modules/employee/router.py` | E | Pagination query-param plumbing | YES |
| `apps/api/tests/integration/modules/employee/test_employee_banking.py`, `apps/api/tests/unit/modules/employee/test_employee_bank_service.py` | D | New encryption-at-rest + audit-redaction proof tests | YES |
| `apps/api/tests/integration/modules/employee/test_employee_pagination.py` (new) | E | | YES |
| `apps/api/src/hrms/modules/onboarding/{models,schemas,service}.py` | D (bank_info encrypt/decrypt, activation re-encrypt handoff) + B (service.py also has document-sniffing/safe-key calls) | `service.py` specifically mixes D and B; `models.py`/`schemas.py` are D-only | `service.py` needs care; `models.py`/`schemas.py` independent |
| `apps/api/tests/integration/modules/onboarding/test_onboarding_activation.py` | D | Bank decrypt-then-re-encrypt handoff test | YES |
| `apps/api/tests/integration/test_pii_encryption_backfill.py`, `apps/api/tests/unit/core/test_{crypto_field,crypto_keys,pii_crypto_service,audit_redact}.py` (new) | D | | YES |
| `apps/api/src/hrms/modules/leave/{repository,router,service}.py`, `apps/api/src/hrms/modules/organisation/{repository,router,service}.py`, `apps/api/src/hrms/shared/pagination.py` | E | SQL-level `.limit/.offset` + `PageParams`/`build_pagination_meta` across leave-applications, leave-ledger, shift-versions, holiday-calendar, workforce-calendar-exception, policy-assignment lists; Tier 2 endpoints deliberately left on a hardcoded `TIER2_SAFETY_LIMIT` | YES, all E-only |
| `apps/api/tests/integration/modules/{leave,organisation}/test_*_pagination.py`, `apps/api/tests/unit/shared/test_pagination.py` (new) | E | | YES |

### Frontend (`apps/web`)

All 27 modified/new `apps/web` files (list: `attendance/page.{tsx,test.tsx}`, `departments/page.tsx`, `departments/[id]/page.{tsx,test.tsx}`, `employees/page.tsx`, `holiday-calendars/[id]/page.tsx`, `leave-applications/page.tsx`, `leave-balances/page.tsx`, `overtime/page.{tsx,test.tsx}`, `policy-assignments/page.tsx`, `policy-resolution/page.tsx`, `regularizations/page.{tsx,test.tsx}`, `rosters/page.tsx`, `rosters/calendar/page.tsx`, `shifts/[id]/page.{tsx,test.tsx}`, `work-calendars/[id]/page.tsx`, `punch-entry-dialog.tsx`, `assignment-panel.tsx`, `leave-application-dialog.tsx`, `regularization-request-dialog.tsx`, `roster-entry-dialog.tsx`, `lib/api/client.ts`, `lib/api/types.ts`, `components/common/pagination-controls.tsx` (new)) are classified **E — Pagination**, confirmed by direct diff read (not just agent report): they either (a) switch a reference-data `/employees` dropdown fetch from `.get()` to `.getList({per_page:100})` because the endpoint now returns an envelope, or (b) wire a real paginated table to the new `<PaginationControls>` component and `page`/`pagination` state (`employees`, `leave-applications`, `leave-balances`, `policy-assignments`, `shifts/[id]` — the last has genuine, non-trivial logic pinning the draft/current-published sections to page 1 regardless of which history page is being browsed). **All safe to commit as one frontend-pagination commit; no interleaving with any other workstream found.**

### Documentation / untracked docs

| Path | Classification | Why | Safe to commit independently? |
|---|---|---|---|
| `docs/audits/UPLOAD_BATCH_{A,B,C}_*.md`, `API_01_PAGINATION_IMPLEMENTATION_REPORT.md`, `DATA_01_PII_*.md` (3 files), `PRODUCTION_HARDENING_BATCH_1_REPORT.md`, `PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.{md,html}` | K (documentation, one per workstream) | These are the audit trail this report is built from | YES, each pairs with its own code commit |
| `docs/business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md`, `ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md` | J (already-committed baseline) | Documentation for the attendance/timezone remediation that landed at `34ccd45` but whose docs were never committed alongside it | YES, but out of scope for *this* hardening round — belongs with the J commit that already happened |
| `docs/modules/employee/41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` | I (already-committed baseline) | Full plan doc for the RBAC/account-provisioning work committed at `2c1d885`/`8114b4e`/`c3b8cec`; per user memory this is the canonical plan doc for the still-open "no add-user/invite flow" gap | YES, out of scope for this round |
| `docs/business-rules/policies/*` (17 files) | **L — Unrelated to this hardening round** | Pre-existing Attendance/Leave policy business-rules documentation (matches user memory's "Policy baseline doc" reference). Not touched by, or related to, any of the 8 hardening workstreams above. | Legitimate prior work, but not part of *this* consolidation — needs its own separate decision, not bundled into a hardening commit |

### Unrelated / suspicious (do not commit)

| Path | Classification | Why | Recommendation |
|---|---|---|---|
| `mavericks-kit.zip` (3.8MB, root) | **L** | No reference anywhere in code, tests, or docs; not an HRMS artifact; zip contents unknown | **Do not commit.** Confirm with user whether this is intentional local clutter before any broad `git add`. |
| `shirt.png` (1.9MB, root) | **L** | Same — no code/doc reference, dated today | **Do not commit.** Confirm with user. |
| `shorts.png` (1.9MB, root) | **L** | Same | **Do not commit.** Confirm with user. |

None of these three appear in `.gitignore` (there is no root `.gitignore` matching `*.zip`/`*.png`), so a careless `git add -A` would pick them up. **This is the single biggest "must not commit" risk in the current tree** — flagging explicitly per §16.

---

## 6. Cross-File Overlap (detail)

This section expands §5's overlap notes with the exact interleaving evidence.

### `apps/api/src/hrms/core/config/settings.py` — genuine interleaving, cannot be mechanically split

`Settings._guard_non_development_config` is **one function** whose body runs, in sequence: (1) JWT secret strength checks [K/SEC-01], (2) `cors_allowed_origins` non-empty check [F/OPS-01], (3) S3/MinIO config completeness check [A/Upload-Batch-A], (4) `kms_cmk_arn` presence check [D/DATA-01]. There is no clean hunk boundary between these — they are sequential `if ...: raise ValueError(...)` blocks inside the same function, added (it appears) across four different work sessions to the same growing function.

`_parse_comma_separated` is a second, smaller shared function: it's the field-validator both `cors_allowed_origins` [F] and `trusted_proxy_hosts` [G] use.

**Conclusion: this file cannot be split via `git add -p` alone.** To commit F, G, A, D, K as separate changes, someone must manually rewrite `_guard_non_development_config` into either (a) one commit per check with the function edited incrementally, or (b) accept that this one file's commit is a single "settings hardening" commit that bundles all four, landing wherever the *last* of {F, G, A, D, K} lands in the sequence. Given the interleaving, **recommendation: this file moves as one commit, paired with whichever of the five workstreams is committed last** (see §13).

### `apps/api/src/hrms/core/storage.py` — one interleaved hunk

`presigned_get_url`'s signature and body changed once, in one hunk, for two reasons simultaneously: switching to `s3_public_endpoint_url` (Batch A) and adding `response_content_disposition` (Batch B/SEC-04). Every other change in the file is Batch-A-only. **Recommendation: since Batch A and Batch B are both being committed in this round anyway (§13), this doesn't block anything — just don't try to land Batch A without Batch B's half of this one hunk, or `presigned_get_url` won't compile/type-check.**

### `apps/api/src/hrms/app.py` — functional (not textual) dependency

Hunks are cleanly separable by block, but **middleware registration order matters at runtime**: `OnboardingUploadRateLimitMiddleware` (Batch C) reads `scope["client"]` to key its IP bucket, which is only the *real* client IP once `ProxyHeadersMiddleware` (OPS-02, registered last = outermost, per Starlette's reverse-add-order stacking) has already run for that request. **Recommendation: commit OPS-02 no later than the same commit as Batch C**, even though the text diffs could technically be split further.

### `apps/api/src/hrms/shared/rate_limit.py` — no real overlap

Verified directly: this file holds **three independent implementations** (pre-existing generic `rate_limit()`, new `rate_limit_by_ip_and_email()` for SEC-02, new `OnboardingUploadRateLimitMiddleware` class for Batch C) with no shared code path, no shared Redis key namespace, and — notably — **two separate, non-unified Redis-failure policies**: Batch C's middleware fails closed (503) on `RedisError`; SEC-02's `rate_limit_by_ip_and_email` and every other consumer of the generic `rate_limit()` dependency (login, refresh, registration, forgot-password, reset-password, invite-accept) still has no failure policy at all and will 500 on a Redis outage. **This is exactly finding SEC-11, confirmed still open except for this one narrow exception** (§7).

### `apps/api/tests/unit/core/test_settings.py` — mirrors the settings.py interleaving

286 lines covering all four workstreams' validators in one file, by construction (it's testing the one interleaved function above). Splittable by test function if `settings.py` itself is ever split; not worth doing unless that split happens.

---

## 7. Production Finding Status

Status current as of the most-recently-dated doc for each ID (numbering per `PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md`, which superseded the Sep-10 `SEC-0XX`/`OPS-0XX` scheme — **the two schemes use the same ID shapes for different findings**, e.g. old `SEC-001`=CORS became new `OPS-01`; see caveat at the end of this section).

| Finding | Current status | Evidence | Remaining action |
|---|---|---|---|
| OPS-01 CORS | **FIXED** (uncommitted) | `cors_allowed_origins` setting, boot fails on empty list outside dev, `app.py` origin swap, `test_cors_middleware.py` | Commit |
| SEC-01 JWT secrets | **FIXED** (uncommitted) | `_guard_non_development_config` rejects missing/default/low-entropy secrets outside dev; 18 tests | Commit |
| SEC-02 login/refresh throttling | **FIXED** (uncommitted) | `rate_limit_by_ip_and_email`, dual IP+email bucket on `/auth/login`, separate bucket on `/auth/token/refresh` | Commit. Note: a **separate, pre-existing** account-lockout persistence bug was discovered during this work (rollback discards `failed_login_count`) — flagged as a new follow-up item, not fixed here |
| DATA-01 PII encryption | **PARTIAL — not closeable** | Real crypto infra + bank-field write path + 94 passing tests; but no KMS key provisioned anywhere, audit-log historical remediation and onboarding-cleanup unimplemented, PAN/Aadhaar unencrypted (no write path), plan's own checklist 100% unchecked | Needs: (1) KMS CMK provisioning per environment, (2) product/compliance sign-off on the two deferred remediation items, (3) explicit scope decision on PAN/Aadhaar before this can be marked closed |
| API-01 pagination | **FIXED (Tier 1 scope)** (uncommitted) | 7 endpoints SQL-paginated, `ListEnvelope`/`PaginationMeta`, frontend wired, 40/40 new tests + re-run 31/31 integration + 9/9 unit green | Commit. Tier 2/3 endpoints intentionally left on a safety-net `LIMIT`, not a gap |
| SEC-03 upload size/rate limit | **FIXED** (uncommitted, Batch B+C combined) | ASGI `MaxUploadSizeMiddleware` + bounded read (B) + dual IP/token rate limit, fail-closed 503 (C) | Commit both |
| SEC-04 upload validation | **FIXED** (uncommitted, Batch B) | Magic-byte sniffing, filename sanitization, safe object keys, forced `Content-Disposition: attachment` | Commit. No AV/malware scanning — explicitly out of scope, not claimed as done |
| SEC-05 security headers | **OPEN** | Not touched by any batch (confirmed in `PRODUCTION_HARDENING_BATCH_1_REPORT.md`'s own scope-compliance list) | Not started |
| SEC-06 refresh cookie | **OPEN** | Refresh tokens still in `localStorage`, no CSP | Not started |
| SEC-07 password reset sessions | **OPEN** | Password reset doesn't revoke existing sessions/refresh families | Not started |
| SEC-08 invite authentication | **OPEN** | Invite acceptance for an existing-account email still issues a session without a password check | Not started |
| OPS-02 proxy handling | **FIXED** (uncommitted) | `ProxyHeadersMiddleware` wired as outermost middleware, `trusted_proxy_hosts` setting, reused (not re-implemented) by Batch C | Commit |
| SEC-09 email verification | **OPEN** | Registration still creates unverified tenants | Not started |
| DEP-01 JWT dependency | **OPEN** | Still on unmaintained `python-jose` (CVE-2024-33663/33664); no CI dependency scanning | Not started |
| SEC-11 Redis failure policy | **PARTIAL, mostly OPEN** | Only Batch C's new onboarding-upload limiter fails closed; the pre-existing generic `rate_limit()`/`rate_limit_by_ip_and_email()` (used by login/refresh/registration/forgot-password/reset-password/invite-accept) still has no failure policy and 500s on Redis outage | Global policy still needs design + implementation |
| OBS-01 error tracking | **OPEN** | No Sentry/error tracking; exceptions still swallowed in places | Not started |
| OBS-02 request logging | **OPEN** | No request access log/metrics/tracing despite `structlog` being configured | Not started |
| OPS-03 readiness | **OPEN** | No liveness/readiness split; Redis reported "skipped" in health check | Not started |
| OPS-04 API container | **OPEN** | Runs as root, no `HEALTHCHECK`, single-process uvicorn | Not started |
| OPS-05 web container/build | **OPEN** | No web container/build pipeline; CI never runs `next build` | Not started |
| QA-01 frontend lint | **OPEN** | No ESLint config; CI substitutes `tsc --noEmit` only | Not started |
| SEC-10 password/MFA | **OPEN** | Weak password policy (8 chars), no MFA, no breach-list/history/rotation | Not started |
| AUD-01 audit coverage | **OPEN** | Zero audit records for `employee_import`, none for credential changes | Not started |

**Findings not in the requested 22-ID list but surfaced during this audit** (flagging per the research agent's own caveat, for the user's awareness — not acted on):
- **OPS-06** — `/docs`, `/redoc`, `/openapi.json` served unconditionally in every environment (P2, `PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17.md` §5, confirmed untouched by this round).
- **TEN-002** — test-suite DB role scoping; appears to have silently improved between the Sep-10 and Sep-17 audits without a dedicated finding ID change; worth a decision on whether it needs its own tracked ID.
- Old-scheme **SEC-007** (`company` table has `FORCE` RLS but no `ENABLE`/policy) — still open, not renumbered into the current OPS/SEC-0X scheme; may already be folded into DATA-01/database findings territory or may need its own ID.

**Numbering caveat:** the Sep-10 docs (`SECURITY_READINESS_AUDIT.md`, `TECHNICAL_DEBT_REGISTER.md`) use `SEC-001`…`SEC-011`/`OPS-001`…`OPS-006`; the Sep-17 doc independently reassigned `SEC-01`…`SEC-11`/`OPS-01`…`OPS-06` to **different, non-corresponding findings**. All statuses above use the Sep-17 scheme, which is what every Sep-20 batch report cites.

---

## 8. Test Baselines

Verified against the literal text of each dated report (not the task brief's paraphrased figures, which don't appear verbatim in any doc found):

| Milestone | Doc | Documented result |
|---|---|---|
| After Hardening Batch 1 (CORS/JWT/SEC-02/OPS-02) | `PRODUCTION_HARDENING_BATCH_1_REPORT.md`, 13:46 | Targeted: 50 passed. Full backend suite: **1303 passed, 1 failed** (pre-existing, unrelated) |
| After DATA-01 (PII encryption) | `DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md`, 16:22 | No full-suite figure stated in the plan doc; targeted DATA-01 tests (94: crypto/keys/service/redact/backfill/banking/activation) independently re-run in this session, all pass |
| After API-01 (pagination) | `API_01_PAGINATION_IMPLEMENTATION_REPORT.md`, 18:48 | Targeted: 40/40 passed. Full backend: **1402 passed, 1 failed / 1403**. Full frontend `vitest`: **364 passed, 4 failed / 368** (pre-existing, unrelated) |
| After Upload Batch A | `UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md`, 19:39 | Unit tests only stated: **502 pre-existing + 15 new = 517**, all pass. No full-suite figure given in this doc. |
| After Upload Batch B | `UPLOAD_BATCH_B_FILE_VALIDATION.md`, 20:21 | **1 failed, 1473 passed** |
| After Upload Batch C | `UPLOAD_BATCH_C_RATE_LIMITING.md`, 20:54 | **1 failed, 1489 passed** (= Batch B's 1473 + 16 new: 8 unit + 8 integration) — matches the task brief's reported final number exactly |

The task brief's stated interim figures ("1425/1424 before Batch B", "1473/1472 after Batch B") do not appear verbatim in any doc read for this audit — they may be a paraphrase or a number from a run not captured in these reports. The **numbers that are directly documented** are the ones in the table above; the final Batch C figure (1489 passed / 1 failed) matches exactly.

**The one known failure — `test_registration_success_full_row_graph`** — was independently reproduced in this session (by the upload-verification agent, running it directly) and is caused by 3 missing RBAC permission codes; every doc from Sep 15 onward reports the identical single failure. **Confirmed: still exactly this one test, still unrelated to any of the 8 workstreams above. No new regressions were found anywhere in this audit.**

---

## 8a. Workstream Implementation-Consistency Matrix

Requested separately from the finding-status table above: for each workstream, whether code, tests, integration coverage, migration, config, and docs each exist. `N/A` means the workstream genuinely doesn't need that category (e.g. no schema change needed); `NO` means it's missing and that's a real gap, not just an absence.

| Workstream | Code | Tests | Integration | Migration | Config | Docs |
|---|---|---|---|---|---|---|
| A — Upload Batch A | YES | YES | YES (real MinIO container) | N/A | YES (`S3_ENDPOINT_URL`/`S3_PUBLIC_ENDPOINT_URL`/AWS creds, docker-compose) | YES |
| B — Upload Batch B | YES | YES | YES | N/A | N/A (allowlist is inline constants, not a setting — see §11) | YES |
| C — Upload Batch C | YES | YES | YES | N/A | N/A (30/min IP, 10/min token limits are hardcoded call-site args, not settings fields — see §11) | YES |
| D — PII encryption | YES (partial — bank field only) | YES | YES (real Postgres) | YES (key-registry table only) | YES (`KMS_CMK_ARN`, `DEV_ENCRYPTION_KEY`, `ENCRYPTION_DEK_CACHE_TTL_SECONDS`) | YES (3 docs) — but see §10/§11, code+docs disagree on completion state |
| E — Pagination | YES | YES | YES (re-run 31/31 + 9/9) | N/A | N/A (no new settings needed) | YES |
| F — CORS (OPS-01) | YES | YES (`test_cors_middleware.py`) | Not independently re-run this session; part of the reported 1303-passed full-suite result | N/A | YES (`CORS_ALLOWED_ORIGINS`) | YES (bundled in `PRODUCTION_HARDENING_BATCH_1_REPORT.md`, no dedicated doc) |
| G — Proxy-aware RL (OPS-02) | YES | YES (`test_proxy_headers.py`, `test_proxy_aware_rate_limiting.py`) | YES (dedicated integration file exists) | N/A | YES (`TRUSTED_PROXY_HOSTS`) | YES (bundled, no dedicated doc) |
| H — Credential RL (SEC-02) | YES | YES (`test_credential_rate_limit.py`, `test_rate_limit_dual_bucket.py`) | YES | N/A | N/A (`limit=10` is a hardcoded call-site arg, not a setting) | YES (bundled, no dedicated doc) |
| K — JWT secrets (SEC-01) | YES | YES (part of `test_settings.py`, 18 tests) | N/A (boot-time validator, unit-testable by construction) | N/A | N/A (validates the pre-existing `jwt_access_secret`/`jwt_refresh_secret` fields, adds no new setting) | YES (bundled, no dedicated doc) |

Two things this matrix surfaces that the narrative sections don't emphasize as sharply: (1) **F, G, H, K have no dedicated audit doc of their own** — they're all covered by one shared `PRODUCTION_HARDENING_BATCH_1_REPORT.md`, unlike A/B/C/D/E which each got a dedicated report; (2) **B, C, H, K deliberately expose no settings field for their policy-relevant numbers** (MIME allowlist, rate-limit thresholds, secret-strength minimums) — reasonable for a first pass, but it means changing any of those values later requires a code change, not a config change, which is worth a product decision in its own right, separate from the approvals already flagged in §11.

---

## 9. Migration State

```
alembic heads:   20260927090000 (single head — no branching, no conflicts)
alembic history: linear, most recent entry:
  20260926090000 -> 20260927090000 (head), "DATA-01 — the encryption-key registry...
  creates the (empty) table only; initial key provisioning is an operational step
  run by the implementer against each real environment's own KMS CMK, not something
  a migration can safely do."
alembic current: COULD NOT BE VERIFIED in this sandbox — apps/api/.venv's shebang
  points at a stale absolute path (/media/varun/varun6/... vs the repo's actual
  /media/varun/varun8/... mount), and the fallback system Python (conda, 3.9) is
  below this project's pyproject.toml floor (requires-python = ">=3.12"), so
  `Settings`' `str | None` syntax fails to import. This is a local environment
  issue, not a repository defect — `alembic heads`/`alembic history` (which don't
  need to import Settings or hit a live DB) both ran cleanly and are trustworthy.
```

**Conclusion:** no conflicting heads, no uncommitted schema drift detected beyond the one new (untracked) migration, which correctly creates only the key-registry table and touches no PII columns — consistent with the DATA-01 plan's stated Option A design (encrypt at the application layer, not via a schema/column-type change). **This migration is safe to commit alongside the rest of workstream D.**

---

## 10. Incomplete Work

| Item | Classification | Detail |
|---|---|---|
| DATA-01 KMS provisioning | **STUB** (by design, documented) | `provisioning.py`'s `provision_initial_key()` exists and is tested against a fake KMS (`_FakeKms`), but has never been run against real AWS KMS in any environment. Staging/production will refuse to boot until this happens — that's the intended fail-closed behavior, not a bug. |
| DATA-01 §8 historical audit-log remediation | **DOCUMENTATION ONLY** | Strategy is fully written in the plan doc; no remediation script exists in the repo. Explicitly gated on product/compliance sign-off that hasn't happened. |
| DATA-01 §9.1 onboarding post-activation cleanup | **STUB / not implemented** | No clearing/pop logic in `onboarding/service.py`. The retention alternative (§9.2) is what actually runs today by default — meaning `onboarding_case.bank_info` and `employee_bank` both permanently retain encrypted copies of the same account number. |
| DATA-01 PAN/Aadhaar encryption | **NOT STARTED** | `employee.pan_number_enc`/`.aadhaar_number_enc` columns are unchanged `String` types with no service-layer write path — explicitly out of scope for this batch per the plan, not an oversight, but also means DATA-01 is far from fully closed as a finding. |
| DATA-01 implementation checklist | **DOCUMENTATION INCONSISTENCY** | The plan doc's final checklist (its own lines ~1360–1396) is 100% unchecked (`[ ]` on every item) despite surrounding prose describing the batch as "COMPLETE — READY FOR REVIEW." The code substantiates most of the prose's claims, but the checklist itself was never updated — worth fixing in the doc regardless of what code lands. |
| Upload Batch A integration container-restart test | **COMPLETE but conditionally skipped** | `skipif`-guarded on Docker-in-Docker access; degrades to skip, not failure, on a sandboxed runner — by design, not a gap. |
| Tier 2/3 pagination (branches/departments/designations/shifts list) | **COMPLETE as scoped** | Deliberately left on a hardcoded `TIER2_SAFETY_LIMIT` rather than true pagination — a documented scope decision, not an incomplete implementation of API-01's actual Tier-1 target list. |
| Employee-directory dropdowns (manager/department-head pickers) | **KNOWN LIMITATION, documented in-code** | Every reference-data `/employees` dropdown now requests `per_page: 100` and will silently truncate for any company with >100 employees. Comments in the code itself flag this as known and accepted, not hidden. |

Everything else reviewed (crypto core, storage, upload validation, rate limiting, pagination plumbing, RBAC/attendance baseline) is **COMPLETE**: code + tests + (where applicable) migration + config all present and consistent.

---

## 11. Policy Decisions Awaiting Approval

Per the task's explicit callouts:

- **30/min IP rate limit, 10/min onboarding-token rate limit (Upload Batch C)** — hardcoded call-site arguments (`ip_limit=30, token_limit=10, window_seconds=60` in `app.py`) with no settings-field override and no evidence in any doc of product/security sign-off on these specific numbers. **WAITING FOR POLICY APPROVAL.**
- **MIME allowlist (PDF/JPEG/PNG only, Upload Batch B)** — a product/security policy choice (what document types onboarding accepts), not something this audit can independently validate as "right." **WAITING FOR POLICY APPROVAL.**
- **PII encryption scope and remediation plan (DATA-01)** — the plan doc itself states its two deferred items (§8 historical audit-log remediation, §9.1 onboarding cleanup) are gated on sign-off that has not happened. The PAN/Aadhaar out-of-scope decision also reads as one that should be confirmed with the business, not just the implementer. **WAITING FOR POLICY APPROVAL** on all three sub-decisions.
- **Pagination `per_page` ceiling (100) and Tier 2/3 scope decision (API-01)** — framed in the report as an implementer scoping choice; reasonable, but nothing in the docs indicates product sign-off on "employee dropdowns silently truncate above 100" as an acceptable production behavior. **Recommend confirming, not blocking** — lower risk than the other three.

---

## 12. Cross-Workstream Risks

- **Rate limiting**: Batch C and SEC-02 share a file (`rate_limit.py`) but not code — confirmed independent, confirmed Batch C can commit without SEC-02 or vice versa. However Batch C has a **functional runtime dependency on OPS-02** (middleware ordering) that isn't visible in the diff alone — see §6. SEC-11 (global Redis failure policy) remains open except for Batch C's own narrow, self-contained exception — this creates a slightly inconsistent failure posture across the app (some rate limiters fail closed, most still fail open/500) that's worth flagging to the team even though it isn't a regression.
- **CORS**: touches `app.py` and `settings.py` only; no overlap with deployment configuration beyond the new `.env*.example` blocks, which are themselves shared with 4 other workstreams (§6).
- **PII encryption**: touches `employee/service.py`, `employee/schemas.py` (audit redaction), and `onboarding/service.py` (bank_info + activation handoff) — confirmed **not** touching search, exports, admin views, or payroll (payroll doesn't exist yet per prior audits). The one real cross-module touch is onboarding→employee at activation (decrypt candidate-submitted bank info, re-encrypt into the new `employee_bank` row under a fresh AAD) — verified correct by a dedicated test.
- **Pagination**: touches employee, leave (applications + ledger), and organisation (shift versions, holiday calendars, workforce-calendar exceptions, policy assignments) APIs, plus their frontend consumers. No overlap found with attendance, payroll, or PII-encryption code paths.

---

## 13. Recommended Commit Boundaries

Based on actual overlap (§6), not an assumed ideal structure:

```
Commit 1 — Upload Batch A (storage architecture)
Files: core/storage.py (endpoint-selection half only — see note),
       docker-compose.yml, env example files (S3/MinIO block only),
       tests/unit/core/test_storage.py, tests/integration/core/test_storage.py,
       employee_import/service.py (storage-outage half), test_employee_import.py (new test)
Purpose: split MinIO/S3 endpoint config from JWT/CORS/DATA-01 settings work
Dependencies: none
Tests: 517 unit (502 pre-existing + 15 new), all green
Rollback impact: low — additive config + a fallback in an already-isolated method
Note: core/storage.py's presigned_get_url hunk must land together with Batch B's
      half of the same hunk (see Commit 2) or the file won't be internally consistent.

Commit 2 — Upload Batch B (file validation)
Files: core/uploads.py, modules/onboarding/document_validation.py,
       modules/onboarding/{exceptions,public_router,service}.py (validation half),
       modules/employee_import/{exceptions,router,schemas,service}.py (size-check half),
       core/storage.py (response_content_disposition half),
       app.py (MaxUploadSizeMiddleware registrations only),
       all Batch B test files
Purpose: magic-byte sniffing, size limits, safe filenames/keys
Dependencies: Commit 1 (shares core/storage.py and onboarding/service.py)
Tests: 34 unit + 15 integration, all green
Rollback impact: low-medium — changes accepted-content behavior for real uploads

Commit 3 — Upload Batch C (onboarding upload rate limiting)
Files: shared/rate_limit.py (OnboardingUploadRateLimitMiddleware class only),
       app.py (middleware registration), onboarding/conftest.py, Batch C test files
Purpose: dual IP/token rate limit on the public document-upload route
Dependencies: MUST land no earlier than OPS-02 (Commit 5) — see §6 ordering note
Tests: 16 new (8 unit + 8 integration), all green; full suite at this point: 1489/1 known failure
Rollback impact: low — additive middleware, fails closed (503) on Redis outage

Commit 4 — CORS + JWT secret enforcement (OPS-01 + SEC-01)
Files: app.py (CORS origin swap only), settings.py (JWT+CORS portions —
       requires manual splitting of _guard_non_development_config, see §6),
       env example files (ENVIRONMENT + CORS_ALLOWED_ORIGINS blocks),
       test_cors_middleware.py, relevant slice of test_settings.py
Purpose: close OPS-01 and SEC-01
Dependencies: settings.py hand-split required (§6) — cannot be purely mechanical
Tests: covered within the 1303-passed full-suite result already reported
Rollback impact: HIGH if done carelessly — a bad CORS/JWT-secret guard can prevent
       the API from booting in staging/production; test the guard's failure paths
       before merging

Commit 5 — Proxy handling + credential rate limiting (OPS-02 + SEC-02)
Files: app.py (ProxyHeadersMiddleware registration), settings.py
       (trusted_proxy_hosts portion), identity/router.py, shared/rate_limit.py
       (rate_limit_by_ip_and_email + _extract_login_identity only), tests/conftest.py,
       test_proxy_headers.py, test_proxy_aware_rate_limiting.py,
       test_credential_rate_limit.py, test_rate_limit_dual_bucket.py
Purpose: close OPS-02 and SEC-02 together — OPS-02 must land in or before this
       commit for Batch C (Commit 3) to be correct at runtime
Dependencies: none upstream; Commit 3 depends on this
Tests: within the 1303-passed full-suite result
Rollback impact: medium — affects every authenticated and public request's IP
       resolution; verify against the real reverse-proxy topology before deploying

Commit 6 — PII encryption (DATA-01)
Files: core/crypto/* (all 10 files), core/audit/redact.py,
       alembic/versions/20260927090000_encryption_key_registry.py,
       modules/employee/{models,service,schemas}.py (NOT repository.py — that's E),
       modules/onboarding/{models,schemas}.py + service.py's D-half,
       settings.py (kms_cmk_arn/dev_encryption_key/encryption_dek_cache_ttl_seconds
       portion), env example files (KMS_CMK_ARN/DEV_ENCRYPTION_KEY blocks),
       all DATA-01 test files
Purpose: land the tested crypto core and its one live write path
Dependencies: settings.py hand-split (§6)
Tests: 94 tests, all green in this session
Rollback impact: HIGH — this is a data-format change (ciphertext at rest) for a
       live table. Do NOT deploy to any environment without KMS CMK provisioning
       done first (§10, §11) — the boot guard will refuse to start without it, which
       is correct, but plan the provisioning step as its own pre-deploy action item,
       not as part of "merge this commit."
       DO NOT mark DATA-01 as closed in any tracker after this commit — see §7, §11.

Commit 7 — Pagination (API-01)
Files: shared/pagination.py, modules/employee/repository.py, modules/leave/*,
       modules/organisation/*, all 27 apps/web files, all pagination test files
Purpose: close API-01 for its Tier 1 scope
Dependencies: none (fully independent of Commits 1-6)
Tests: 40 new + full re-run 31/31 integration + 9/9 unit green
Rollback impact: low — additive query params with backward-compatible defaults
       (page=1, per_page unset → server default), frontend gracefully handles
       pagination:null

Explicitly excluded from all commits above:
  - mavericks-kit.zip, shirt.png, shorts.png (§5, §16 — confirm with user first)
  - docs/business-rules/policies/* (§5 — unrelated prior work, separate decision)
  - docs/business-rules/attendance/*, docs/modules/employee/41_*.md (§5 — belongs
    with already-committed J/I work, not this round)
```

Commits 1→2→3 and 4/5→3 are the only hard orderings found; 6 and 7 are independent of everything else and of each other.

---

## 14. Changes That Must Not Be Committed Yet

- **`mavericks-kit.zip`, `shirt.png`, `shorts.png`** — no relationship to any workstream found; confirm with the user before touching. Highest-priority item in this whole report because a routine `git add -A` would silently include them.
- **DATA-01 as a "closed" finding** — the code and tests are real, but per §7/§10/§11 this cannot be marked CLOSED: no KMS key provisioned anywhere, two remediation steps explicitly awaiting sign-off, PAN/Aadhaar out of scope, and the plan doc's own checklist is unchecked. Committing the code is reasonable (see Commit 6 above); declaring the finding resolved is not.
- **SEC-11 (Redis failure policy)** — do not report this as fixed. Only one narrow, new code path (Batch C's upload limiter) fails closed; the much larger surface (login, refresh, registration, password flows, invite-accept) is unchanged and still fails open/500 on a Redis outage.
- **Upload Batch C's rate-limit values (30/min IP, 10/10min token) and Batch B's MIME allowlist** — awaiting policy approval per §11; land the code, but don't treat the specific numbers as final/unchangeable without a sign-off record.
- **`docs/business-rules/policies/*` and the two already-committed-baseline doc directories** — legitimate work, but bundling them into a "production hardening" commit would misrepresent what that commit is. Handle as a separate, explicit decision with the user.

---

## 15. Recommended Next Implementation Step

Not a new feature — a process step: **get `settings.py`'s `_guard_non_development_config` and `_parse_comma_separated` manually split** (§6) before attempting Commits 4/5/6, since those are the only places in the tree where a mechanical `git add -p` commit split will fail. Everything else in §13 is ready to commit in the stated order today. Separately, resolve the environment issue noted in §9 (`apps/api/.venv`'s stale shebang path) before anyone tries to run `alembic current`/apply migrations locally — it currently fails outright.

---

## 16. Final Status

```
PRODUCTION HARDENING CONSOLIDATION

Working tree understood:
YES

Upload A:
PASS

Upload B:
PASS

Upload C:
PASS

P0 status:
OPS-01 CORS — fixed, uncommitted
SEC-01 JWT secrets — fixed, uncommitted
SEC-02 login/refresh throttling — fixed, uncommitted (one new unrelated follow-up
  found: pre-existing account-lockout persistence bug, not fixed, not blocking)
DATA-01 PII encryption — partial, not closeable (no KMS provisioned, 2 remediation
  items pending sign-off, PAN/Aadhaar out of scope)
API-01 pagination — fixed for Tier 1 scope, uncommitted

P1 status:
SEC-03 upload size/rate limit — fixed (Batch B + C), uncommitted
SEC-04 upload validation — fixed (Batch B), uncommitted
OPS-02 proxy handling — fixed, uncommitted
SEC-05, SEC-06, SEC-07, SEC-08, SEC-09, DEP-01 — all still OPEN, untouched

P2 status:
SEC-11 Redis failure policy — partial (one narrow exception), mostly OPEN
OBS-01, OBS-02, OPS-03, OPS-04, OPS-05, QA-01, SEC-10, AUD-01 — all still OPEN,
  untouched. Also newly surfaced: OPS-06 (unconditional API docs exposure, P2,
  untouched) — not in the original 22-ID list.

Known pre-existing test failures:
test_registration_success_full_row_graph (3 missing RBAC permission codes) —
  confirmed present, confirmed unrelated, reproduced independently in this session

New regressions:
none found

Policy approvals required:
Upload Batch C rate-limit thresholds (30/min IP, 10/min token) — WAITING FOR
  POLICY APPROVAL
Upload Batch B MIME allowlist (PDF/JPEG/PNG) — WAITING FOR POLICY APPROVAL
DATA-01 historical audit-log remediation (plan §8) — WAITING FOR POLICY APPROVAL
DATA-01 onboarding post-activation cleanup vs. retention (plan §9) — WAITING FOR
  POLICY APPROVAL
DATA-01 PAN/Aadhaar encryption scope decision — WAITING FOR POLICY APPROVAL
API-01 100-item dropdown truncation / Tier 2-3 scope — recommend confirming,
  lower risk

Recommended next implementation:
Manually split settings.py's _guard_non_development_config and
_parse_comma_separated (§6, §15) before attempting the CORS/JWT (Commit 4),
proxy/credential-rate-limit (Commit 5), or PII-encryption (Commit 6) commits —
this is the one file in the tree that resists a mechanical split.

Recommended commit sequence:
1. Upload Batch A → 2. Upload Batch B → 3. Upload Batch C (after/with 5) →
4. CORS + JWT secrets → 5. Proxy handling + credential rate limiting →
6. PII encryption → 7. Pagination
(3 must not precede 5's OPS-02 half at runtime; 6 and 7 are otherwise independent
of everything else)

Production readiness:
NOT READY FOR PRODUCTION
```
