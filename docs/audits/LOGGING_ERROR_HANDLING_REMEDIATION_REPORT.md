# Logging and Error Handling — Remediation Report

| | |
|---|---|
| **Date** | 2026-10-13 |
| **Source plan** | `docs/audits/LOGGING_ERROR_HANDLING_OBSERVABILITY_PLAN.md` |
| **Scope** | TXN-01, PRA-04, LOG-01, LOG-02, LOG-05, LOG-03, and the immediate log-redaction part of LOG-04. Nothing else. |
| **Baseline commit** | `a2047b303c8f35aa3b0d81f8589b27762aac4f07` on `main` (HEAD unchanged; nothing committed, pushed, merged or deployed) |
| **Verdict** | **COMPLETE** for the scoped findings, with two operational decisions open (§9). The wider observability programme is **not** complete (§9). |

---

## 1. Working-tree baseline and final state

**Initial:** 90 `git status` entries: 78 modified tracked files plus 12 untracked. All of them were user-owned in-progress work (employee documents, onboarding, organisation, web UI, env examples) plus the audit plan.

**Final:** 110 entries. A line-by-line diff of `git status --short` before and after shows **only additions** (20 entries, listed in §3). No pre-existing entry changed state.

Two files that already had user hunks were also edited by this work:
- `apps/api/src/hrms/app.py`: the user's employee-document `MaxUploadSizeMiddleware` block.
- `docs/deployment/PRODUCTION_DEPLOYMENT.md`: the user's `WEB_APP_BASE_URL` paragraph.

For both, every line the user had added was verified still present after editing (10/10 and 6/6), by script against a snapshot of the initial `git diff`. My edits touched separate regions.

No stash, reset, checkout, clean, commit or push was performed.

---

## 2. Findings: re-confirmation

All target files except `app.py` and `PRODUCTION_DEPLOYMENT.md` (user hunks unrelated to these findings) were byte-identical to HEAD. Every finding was re-traced before editing.

| Finding | Status before fix | How re-confirmed |
|---|---|---|
| TXN-01 refresh-token reuse revocation rolled back | **Confirmed** | `identity/service.py::refresh` wrote `revoke_refresh_family`, then raised; `get_session` rolled back. `test_refresh_token_rotation` asserted that the newest token still worked after reuse, and it passed. A second, unreported defect was also found: rotation was not atomic (two concurrent refreshes of one token could both succeed and fork the family). |
| PRA-04 import queue never consumed | **Confirmed, and reproduced on this machine** | (a) Code: `queue="reports_exports"`; compose worker has no `-Q`; no `task_queues`/`task_routes`. (b) **Local Redis db0 held 223 unconsumed `reports_exports` messages** left by earlier test runs. They were left untouched. (c) A real `celery worker` with the exact compose command, on an isolated Redis DB, left a freshly uploaded batch **PENDING** after 20 s with the message still queued. |
| LOG-01 unhandled 500 loses request id / CORS | **Confirmed** | Audit probe re-run unchanged: `request_id:"unknown"`, no `X-Request-Id`, no ACAO, no CSP. |
| LOG-02 handled 5xx not logged | **Confirmed** | Audit probe: generic `DBAPIError` 500 and 5xx `AppError` produced no log line. |
| LOG-05 unvalidated `X-Request-Id` | **Confirmed** | Audit run on the test DB: login with a 65-char id returned 422 `INVALID_VALUE`. Code unchanged. |
| LOG-03 worker/beat logging unconfigured | **Confirmed** | `configure_logging()` called only in `create_app()`. |
| LOG-04 tokens in URL paths reach logs | **Confirmed** | Nginx `$request_uri`, uvicorn access log, `unhandled_exception.http_path=request.url.path`. |

None were already fixed elsewhere, and none failed to reproduce.

---

## 3. Files changed

### Production code
| File | Change and reason |
|---|---|
| `apps/api/src/hrms/core/db/repositories/identity.py` | **TXN-01.** New `rotate_refresh_token()`: a conditional `UPDATE … WHERE id=:id AND revoked_at IS NULL RETURNING id` that reports whether *this* call rotated the token. |
| `apps/api/src/hrms/modules/identity/service.py` | **TXN-01.** Reuse and lost-race paths call the new `_revoke_family_on_reuse()`. It revokes the family and its session(s), **commits**, emits `security.refresh_token_reuse_detected` (user_id and family_id only, never the token), then the caller raises `InvalidTokenError`. Rotation uses the conditional update; losing the race is treated as reuse. |
| `apps/api/src/hrms/core/celery_app.py` | **PRA-04:** `task_queues = (default, reports_exports)`. **LOG-03:** `setup_logging` handler (JSON for worker and Beat, including Celery's stdlib records); `before_task_publish` copies the API request id into a namespaced `hrms_request_id` header; `task_prerun`/`task_postrun` bind and restore `task_id`, `task_name` and `request_id` via contextvar tokens. Also added `# type: ignore[untyped-decorator]` to the **pre-existing** `@task_failure.connect`, which already failed `mypy` at HEAD (verified by type-checking `git show HEAD:` of the file). |
| `apps/api/src/hrms/core/observability/request_context.py` (new) | **LOG-01/LOG-05.** Outermost pure-ASGI `RequestContextMiddleware`: validates or generates the id, publishes it to the ContextVar and structlog, adds `X-Request-Id` to every response, catches any exception escaping the stack (logs once, sends the 500 envelope through the same `CORSMiddleware`/`SecurityHeadersMiddleware` classes and config), and restores context afterwards. |
| `apps/api/src/hrms/core/observability/redaction.py` (new) | **LOG-04.** `TOKEN_PATH_PREFIXES`, `redact_path()`, and `AccessLogPathRedactionFilter` for uvicorn's access logger. |
| `apps/api/src/hrms/core/observability/logging.py` | Shared `configure_logging(service, configure_stdlib=False)`: adds `service`/`environment` fields, installs the access-log filter idempotently, and optionally routes stdlib logging through one JSON root handler (worker/Beat). New `safe_log()` so a broken log sink can never change a response. |
| `apps/api/src/hrms/core/errors/handlers.py` | **LOG-02.** 5xx `AppError` → `app_error` (500 at ERROR with traceback; 502/503/504 at WARNING with `cause_type`, no traceback). `DBAPIError` → `db_wait_timeout` (WARNING) or `db_error` (ERROR with traceback, `sqlstate`, driver class). 4xx and SQLSTATE-22 cases stay silent. Unhandled-exception logging and response moved into shared `log_unhandled_exception()`/`unhandled_error_response()`; the `Exception` handler remains only as a fallback for apps built without the middleware. `route_for_logging()` logs the full route template (FastAPI 0.141 nests routers, so the include prefix is rebuilt from the raw path) or the redacted path. |
| `apps/api/src/hrms/core/tenancy/context.py` | Per-request holder so the outermost catcher can see the **membership-verified** tenant set in a child task (`BaseHTTPMiddleware` runs downstream in a task with a copied context). Unverified `X-Company-Id` values are never logged. Added `clear_tenant`, `snapshot_request_context`/`reset_request_context` and `verified_tenant_for_logging`. Existing functions unchanged. |
| `apps/api/src/hrms/core/tenancy/middleware.py` | No longer resolves or clears the request id (the root cause of LOG-01); clears only the tenant it set. |
| `apps/api/src/hrms/core/db/session.py` | `hide_parameters=True` on the engine, so bound values never enter `DBAPIError` text and therefore the tracebacks LOG-02 now records. |
| `apps/api/src/hrms/app.py` | CORS options defined once and shared with `RequestContextMiddleware`. Added `expose_headers=["X-Request-Id"]`. `RequestContextMiddleware` added last (outermost). |
| `infra/nginx/nginx.conf` | **LOG-04:** `map $uri $hrms_log_uri` masks the token segment for the same six prefixes and logs no query string, which also removes presigned-URL signatures. **LOG-01:** `map $http_x_request_id $hrms_request_id` uses the client id or Nginx's `$request_id`; `request_id` added to the JSON log line. |
| `infra/nginx/conf.d/hrms.conf.template` | API vhost forwards `X-Request-Id $hrms_request_id`. |
| `docs/deployment/PRODUCTION_DEPLOYMENT.md` §15 | Rewritten to match verified behaviour: JSON per service, which lines remain plain text, request-id lookup, token masking. |

### Tests
| File | Purpose |
|---|---|
| `tests/integration/auth/test_auth_security.py` (modified) | `test_refresh_token_rotation` no longer asserts the defective behaviour. New `test_refresh_token_reuse_revokes_the_newest_token`. |
| `tests/integration/auth/test_refresh_token_reuse.py` (new) | Durable family and session revocation (read back on a fresh connection), access token dead after reuse, unrelated family unaffected, concurrent refresh has a single winner, a deterministic row-lock race at the repository layer, and a revocation DB failure giving 500 with nothing revoked. |
| `tests/integration/auth/test_request_id_audit.py` (new) | Login with 65-char, 3000-char and whitespace ids returns 200, and the audit row stores the issued UUID. A 64-char id is kept end to end. |
| `tests/integration/core/test_request_context_and_error_logging.py` (new) | Real `create_app()`: unhandled errors from a route, a dependency and **another middleware**; verified tenant logged; unverified header not logged; logging failure does not change responses; 5xx `AppError` for Redis, encryption-unavailable, decryption-failed and unknown-key; 4xx silent; DB timeout; a real failing query through the real engine with a sentinel bound parameter; the request-id policy table (bounds, control characters, Unicode, oversize). |
| `tests/integration/core/test_token_path_redaction.py` (new) | `redact_path` table, uvicorn record filter, idempotent install, and a crash on `/v1/public/account-invites/{token}` that logs the template with the token absent from stdout and stderr. |
| `tests/unit/test_celery_queue_routing.py` (new) | Every registered task routes to a declared queue; the import task routes to `reports_exports` and all others to `default`; the compose worker command consumes every declared queue. |
| `tests/unit/core/test_worker_logging.py` (new) | Subprocess: worker entrypoint plus Celery's real logging bootstrap run twice. All output is JSON, `service=worker`, no duplicates, `LOG_LEVEL` honoured, and Celery's failure record carries the traceback. |
| `tests/integration/modules/attendance/test_face_enrollment.py` (modified) | `test_storage_failure_cleans_up_provider_person` expected the exception to escape to the test transport. It now asserts the rendered 500 envelope. Its actual invariant (provider person cleaned up) is unchanged and still asserted. |

---

## 4. Implementation decisions

### 4.1 TXN-01 transaction boundaries
- **Why commit before raising, and why it is safe.** The request transaction (`get_session`, `scope="function"`) rolls back on any exception. Both call sites of `_revoke_family_on_reuse` are reached **before the request has written anything else**: only SELECTs, plus in the race path an UPDATE that matched zero rows. So the commit persists exactly the revocation. This is the same pattern `login()` already uses for its failed-attempt counter.
- **Considered and rejected: a separate transaction.** A separate `session_scope()` would hold a second pooled connection while the first is open, for no added safety.
- **Atomic rotation.** The `revoked_at IS NULL` predicate makes rotation single-winner. Under READ COMMITTED, a concurrent rotation blocks on the row lock and then re-evaluates the predicate. The repository test proves this deterministically: B is still blocked 300 ms after A's update and returns `False` after A commits.
- **Race with a late descendant.** The family UPDATE could in theory miss a descendant committed after the revocation statement starts. That descendant still belongs to the same session, which is revoked, so both its refresh and its access tokens fail (`get_current_user` and `refresh` both check the session).
- **Failure semantics.** If revocation or its commit fails, the DB error propagates as a logged 500. The client is **not** told "revoked", and nothing is persisted (test asserts the newest token row is untouched).

### 4.2 Middleware ordering (outer → inner)
`ServerErrorMiddleware` → **`RequestContextMiddleware`** → ProxyHeaders → SecurityHeaders → Tenancy → OnboardingUploadRateLimit → MaxUploadSize×5 → CORS → ExceptionMiddleware → routes.

- Starlette always places `ServerErrorMiddleware` outside every user middleware, so the only way to log with context **and** shape the 500 is to catch in the outermost user middleware.
- The 500 is replayed through real `CORSMiddleware` and `SecurityHeadersMiddleware` instances built from the same `cors_options`, rather than re-implementing CORS.
- `RequestContextMiddleware` does not read the client IP, so sitting outside ProxyHeaders is safe. ProxyHeaders mutates `scope` in place, so the security-header HSTS check on a replayed 500 still sees the resolved scheme.
- Exceptions are not re-raised (unless the response had already started), so uvicorn no longer prints a second "Exception in ASGI application" traceback.

### 4.3 Request-id policy
- Accepted pattern: `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`, i.e. 1–64 characters. Anything else is replaced with `uuid4()` and never rejected.
- This fits `audit_log.request_id VARCHAR(64)`, cannot carry whitespace, control characters, quotes, `/` or non-ASCII, and accepts both clients' current formats (web UUID, mobile `req_<ms>_<hex>`) and Nginx's 32-hex `$request_id`.

### 4.4 5xx logging levels
- 500 `AppError` and generic DB errors are unexpected or integrity events, logged at ERROR with traceback.
- 502/503/504 `AppError` and DB wait timeouts are a dependency being unavailable, logged at WARNING with exception and cause type only. An outage then yields one compact line per request, not a traceback per request.
- No path logs the same traceback twice. Tests assert exactly one event and exactly one traceback-bearing event per failure.

### 4.5 Worker logging
- Celery's own `celery.app.trace` "Task … raised unexpected" record, now rendered as JSON, is the **single** traceback for a failed task. `celery_task_failed` stays a compact summary.
- Level comes from `LOG_LEVEL` (same source as the API), not the CLI `--loglevel`.
- The API process does **not** route stdlib logging through the JSON root handler, because under gunicorn that would duplicate uvicorn/gunicorn lines.

### 4.6 PRA-04 fix choice
Declaring `task_queues` is one change in one place. It makes **every** worker started without `-Q` consume both queues: production compose, `apps/api/README.md` dev instructions, and any other invocation. No second worker was added, and no task routing changed. Queue names, exchange and routing key match what Celery auto-created before.

---

## 5. Tests executed and results

All runs used the local test environment (Postgres `localhost:5433`, Redis `localhost:6380`, local MinIO), **with `EMAIL_PROVIDER=logging` forced** (see §6). Every run that could enqueue Celery work pointed the broker at **Redis DB 9**, which was verified empty before use and flushed after, so the user's db0 backlog was never touched. The db0 `reports_exports` length was checked after each run: 223, then 224 (the extra message came from one early run before isolation was applied; see §6).

| Run | Command (from `apps/api`) | Result |
|---|---|---|
| TXN-01 targeted | `pytest tests/integration/auth/test_refresh_token_reuse.py tests/integration/auth/test_auth_security.py tests/integration/auth/test_credential_rate_limit.py` | **22 passed**, later 5/5 for the new file including the row-lock test |
| Refresh-related suites | `pytest tests/integration/auth tests/integration/modules/account_invite/test_session_lifecycle.py tests/security/test_rls_runtime_role.py tests/integration/modules/employee/test_employee_lifecycle_and_concurrency.py tests/integration/modules/employee/test_master_data_compensation_termination.py tests/unit/shared/test_rate_limit_dual_bucket.py` | **104 passed** (logging email provider) |
| Celery routing / registration | `pytest tests/unit/test_celery_queue_routing.py tests/unit/test_termination_task_registration.py tests/unit/modules/leave/test_leave_task_hardening.py tests/unit/core/test_celery_task_failure_logging.py` | **18 passed** |
| Employee import | `pytest tests/integration/modules/employee_import` (broker → DB 9) | **7 passed**; its messages landed in DB 9 `reports_exports` |
| Request context / 5xx / redaction | `pytest tests/integration/core/test_request_context_and_error_logging.py tests/integration/core/test_token_path_redaction.py` | **48 passed** |
| Core unit + audit request id | `pytest tests/integration/auth/test_request_id_audit.py tests/unit/core` | **151 passed** |
| **Full backend suite** | `pytest tests` (logging email, broker → DB 9) | **2481 passed, 2 failed** (both analysed below) |
| Post-fix re-run of every changed or related file | `pytest` on the 13 files/dirs listed in §3 + `tests/integration/test_proxy_aware_rate_limiting.py tests/security tests/integration/modules/employee_import` | **141 passed** |
| Ruff | `ruff check` + `ruff format --check` on all 19 changed/new Python files | **All checks passed**, 19 files formatted |
| mypy (strict) | `python -m mypy src/hrms` | **Success: no issues found in 180 source files** |
| import-linter | `lint-imports` | **1 kept, 0 broken** |

The two failures in the full suite:
1. `test_face_enrollment.py::test_storage_failure_cleans_up_provider_person`. **Caused by this change, and expected.** It relied on the old re-raise to the transport. Updated as described in §3, and it now passes.
2. `test_account_invite.py::test_invite_employee_accept_and_login_success`. **Not related to this work.** It fails on `Extra items in the left set: 'EMPLOYEE.VIEW_DOCUMENTS'`, a permission introduced by the user's uncommitted employee-documents work (untracked `…_employee_view_documents_backfill.py` migration). No permission, RBAC or seed code was touched here. It was not independently re-run at the baseline commit, so "pre-existing" is an attribution from the diff content, not a measured fact.

### Runtime probes (scratchpad scripts, not part of the repo)

**PRA-04, real worker.** `python -m celery -A entrypoints.worker worker --loglevel=info` (the compose command, no `-Q`) on broker DB 9, driving a real CSV upload through the real app:
- Before the fix: `FINAL batch status: PENDING`, `reports_exports: 1` still queued.
- After the fix: `FINAL batch status: COMPLETED_WITH_ERRORS 2 3`, which is the fixture's designed 2 valid / 3 invalid rows. Queue drained.

All rows the probe created were removed with the integration suite's own cleanup helpers, and the plan catalogue was restored to its prior state.

**PRA-04, legacy-message compatibility.** A message enqueued with the **pre-fix** configuration (no `task_queues`) into `reports_exports`, and a `default`-queue message under the new configuration, were both consumed by a new-configuration worker: `legacy result: pong`, `default result: pong`, both lists drained to 0.

**LOG-03, real worker and Beat processes.**
- Worker: a real registered task (`employee.enforce_terminations_company`) was sent an invalid argument (fails on UUID parsing, no side effects) under request id `probe-req-1`. Every log record was JSON with `service:"worker"`. The failing task produced `celery_task_failed` (no traceback) plus Celery's failure record (with traceback), both carrying `task_id`, `task_name` and `request_id:"probe-req-1"`. **Exactly one traceback.** Zero duplicate lines.
- Beat: JSON with `service:"beat"`.
- The only non-JSON lines were Celery's `print()`-based startup banners and the "Warm shutdown" notice.

**LOG-01, real gunicorn.** `gunicorn … -k uvicorn.workers.UvicornWorker --access-logfile - --error-logfile -` with a crashing route returned HTTP 500 with `x-request-id: crash-probe-1`, `access-control-allow-origin`, `access-control-expose-headers: X-Request-Id`, and envelope `request_id:"crash-probe-1"`. The output had **0** "Exception in ASGI application" lines and **1** `unhandled_exception` event. That event holds all traceback text; there are three "Traceback" headers because Starlette's `BaseHTTPMiddleware` wraps the error in an exception group.

**LOG-04, real gunicorn access log.** Requests to `/v1/public/account-invites/tok_GUNICORN_SENTINEL_1?q=TOKQ` and `/v1/public/onboarding/tok_GUNICORN_SENTINEL_2/documents` were logged as `"GET /v1/public/account-invites/[REDACTED] HTTP/1.1" 404` and `…/onboarding/[REDACTED]/documents…`. **0 occurrences** of either sentinel in the output.

**LOG-04 and LOG-01, real Nginx.** The production `nginx:1.27-alpine` image (already cached locally, not pulled) ran the **real** `infra/nginx/nginx.conf` in a disposable container on 127.0.0.1:
- `nginx -t` passed.
- All six token prefixes were logged as `[REDACTED]`.
- `/doc.pdf?X-Amz-Signature=…` was logged as `/doc.pdf`.
- 0 secrets in output.
- A missing client id produced a 32-hex id; `X-Request-Id: client-rid-9` was kept; `proxy_set_header X-Request-Id $hrms_request_id` delivered the same id upstream.

The container and its scratch config were removed afterwards.

---

## 6. Failed, skipped or unrun tests, and environment notes

- **Real email provider in the local `.env` (environmental, disclosed).** `apps/api/.env` sets `EMAIL_PROVIDER=hostinger`, and the test suite does not override it. The **first** run of the refresh-related suites in this session (before this was noticed) made real Hostinger Mail API calls for password-reset, verification and invite emails. Every recipient in those tests is on a reserved, undeliverable domain (`example.com`, `acme.example`; checked by grepping the test sources), and the provider answered **422** (it rejected them). That run's 12 failures were caused by this, not by code. Every later run forced `EMAIL_PROVIDER=logging` through the environment. **`.env` was not modified.** Recommendation: make the test `conftest.py` force `EMAIL_PROVIDER=logging`. This is out of scope here.
- **Local test suite enqueues into the developer's Redis db0.** Integration tests that call `POST /v1/employee-imports` push real Celery messages into `redis://localhost:6380/0`. That is how 223 messages had accumulated. One early run in this session, before isolation was applied, added one more (224). All later runs used DB 9. **The db0 backlog was not consumed or deleted.** Because of the PRA-04 fix, a local worker started against db0 will now process those 224 stale messages. They reference test batches that the suite has already deleted, so `process_batch` returns early ("batch is None"), but a developer should know before starting a worker. Clearing them is the user's call.
- **Venv shebangs.** Console scripts in `apps/api/.venv/bin` point at `/media/varun/varun9/...` (the venv was copied), so `.venv/bin/mypy` and `.venv/bin/celery` do not run. Every tool was invoked as `python -m …`. This is pre-existing and environmental.
- **Not run:**
  - Web (`tsc`, `vitest`, `next build`) and mobile (`flutter test`): no web or mobile files were changed.
  - The full rendered `hrms.conf.template` under `nginx -t`: it needs real certificates. Only the one-line `proxy_set_header` addition was validated, in an equivalent test server block.
  - No production, staging or shared-environment checks of any kind.

---

## 7. Security, compatibility, deployment and migration implications

- **Users will be logged out after reuse detection, as intended.** Replaying an old refresh token now ends the whole session server-side, which was the original design.
- **Known UX limitation (decision D-A, §9).** Two browser tabs refreshing the same cookie at the same moment are indistinguishable from a replay, so the losing tab's request revokes the session for both. The web client already single-flights refresh within a tab, but not across tabs. Before this fix the same race returned 401 to the losing tab and the web client cleared the shared session anyway, so the visible effect is similar, but now it is server-side. A short reuse grace window is the usual mitigation and is a product/security decision.
- **Error contract unchanged.** Envelope shape, codes and status codes are unchanged; existing clients are unaffected.
  - Newly added to responses: `X-Request-Id` on the catch-all 500 (and readable cross-origin via `Access-Control-Expose-Headers`), and CORS/security headers on that 500.
  - The app no longer re-raises unhandled exceptions to the ASGI server. Anything that relied on the server's own traceback should use the `unhandled_exception` event instead.
- **Log-shape changes.**
  - All structlog events gain `service` and `environment`.
  - `http_path` in error events is now the route template (or redacted path), not the raw path.
  - Worker and Beat output switches from plaintext to JSON.
  - Nginx `request_uri` is now the masked path **without query string**, and a `request_id` field was added.
  - Anyone grepping the old plaintext worker lines needs to update their queries.
- **`hide_parameters=True` in every environment.** Developers lose bound values in DB error messages and in `DEBUG` SQL echo. This is deliberate: the redaction test runs in development, so gating it on environment would have let tests pass while dev logs leaked.
- **Deployment.**
  - Rebuild and redeploy the image for `api`, `worker` and `beat`, and reload `nginx`. No migration, no new dependency (`kombu` is already a Celery dependency), no env-var change.
  - **Do the §8 inventory before deploying the worker.**
  - Nothing was deployed or restarted by this work.
- **Rollback.**
  - Reverting the code is safe: no schema or data-shape change.
  - Reverting TXN-01 alone re-opens the session-theft gap, so don't.
  - Reverting PRA-04 strands newly enqueued imports again.

---

## 8. Operational recovery: imports already stuck in PENDING (production)

**Not executed anywhere.** For the operator, before deploying the fixed worker. Once the fix is deployed, the worker immediately processes **every** message already waiting in `reports_exports`. `EmployeeImportService.process_batch` has **no "still PENDING?" guard**, so an old batch will be processed however stale it is, including one HR may since have re-uploaded by hand. That can create duplicate employees for rows that don't collide on `employee_code`.

1. **Inventory (read-only).**
   - `docker compose -f docker-compose.prod.yml exec redis redis-cli LLEN reports_exports`
   - In Postgres as an admin role: `SELECT company_id, id, status, total_rows, created_at FROM employee_import_batch WHERE status = 'PENDING' ORDER BY created_at;`
   - Expect the two counts to roughly match.
2. **Decide per batch, with the tenant's HR owner.** Was it re-submitted manually since? Is it still wanted?
3. **Batches that must NOT run:** mark them terminal **before** deploying, for example `UPDATE employee_import_batch SET status='FAILED', completed_at=now() WHERE id IN (...) AND status='PENDING';`.
   - This needs the RLS company GUC set per company, or an RLS-exempt maintenance role.
   - The queued message will still be consumed, and `process_batch` will then flip the row back to PROCESSING and run it. This is the missing guard.
   - So for batches that must not run, **also** delete the batch row (its message then hits "batch is None" and is a no-op).
   - Alternatively, add a `status == 'PENDING'` guard to `process_batch` first. That is a small code change and **not made here** (decision D-B, §9).
4. **Batches that should run:** leave them PENDING. Deploy, then confirm with `LLEN reports_exports` → 0 and the batch statuses moving to `COMPLETED`/`COMPLETED_WITH_ERRORS`/`FAILED`.
5. **Never** `FLUSHDB`/`DEL` the Redis keys. Other queues and rate-limit state share the instance.

---

## 9. Remaining findings, risks and decisions required

**Decisions required:**
- **D-A (product/security):** keep strict reuse detection, or add a few-second grace window for concurrent refreshes (multi-tab)? Strict is what is implemented and tested.
- **D-B (engineering, before the production deploy):** add a `status == 'PENDING'` guard to `EmployeeImportService.process_batch` so stale or cancelled batches cannot run when the queue starts draining. It is not added here because it changes import semantics beyond the queue mismatch. §8 is written to work without it.

**Remaining risks and limitations of this change:**
- The API's own access line (gunicorn/uvicorn) is still plain text, now redacted. It has no request id or duration; Nginx carries both.
- If an exception occurs **after** a response has started streaming, it is logged without traceback and re-raised, so the server prints the traceback once. No route streams today.
- The refresh-token reuse event goes to logs only, not to the immutable `audit_log`. Auditing it needs the RLS company context and was left out of scope.
- `exception_message` in `unhandled_exception` is still `str(exc)`, kept for contract compatibility with the existing test. `hide_parameters` removes SQL bound values, but other exception types could carry user input. This is LOG-08 in the plan.

**Still open from the plan (deliberately not implemented; out of scope):**
- LOG-06 (email swallow sites), LOG-07 (security events for failed login, lockout and rate-limit trips), LOG-08 (full redaction processor and `safe_error`), LOG-09 to LOG-17.
- Metrics, alerting, retention policy, uptime and Beat-heartbeat monitoring, error boundaries and timeouts on web and mobile.
- **The observability programme as a whole is not complete.**

**Environment follow-ups (not code in scope):**
- Test `conftest.py` should force `EMAIL_PROVIDER=logging` and an isolated Celery broker.
- The local db0 backlog of 224 stale messages.
- The broken venv shebangs.

---

## 10. Verdict

**COMPLETE** for TXN-01, PRA-04, LOG-01, LOG-02, LOG-05, LOG-03 and the immediate redaction part of LOG-04. Each one has a regression test that passes and, where the defect lived at runtime, a real-process probe:

- real worker for PRA-04;
- real worker and Beat for LOG-03;
- real gunicorn for LOG-01 and LOG-04;
- real Nginx for LOG-04 and edge request-id.

Two decisions (D-A, D-B) and the §8 inventory must happen before the production deploy. Nothing has been committed or deployed; this is stopped for review.
