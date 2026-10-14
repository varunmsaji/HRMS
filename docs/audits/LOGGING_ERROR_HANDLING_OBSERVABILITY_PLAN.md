# Logging, Error Handling & Observability — Audit and Implementation Plan

| | |
|---|---|
| **Date** | 2026-10-13 |
| **Type** | Audit and plan only. No application code, tests, configuration, migrations, dependencies or deployment files were changed. |
| **Branch / HEAD** | `main` @ `a2047b303c8f35aa3b0d81f8589b27762aac4f07` ("test plan document added") |
| **Working tree** | Dirty before this audit: 89 entries. That is 78 modified tracked files (API employee/onboarding/organisation modules, `app.py`, `settings.py`, env examples, many web pages/components, `PRODUCTION_DEPLOYMENT.md`) and 11 untracked files: the employee-document migrations, `document_validation.py`, document tests, web document components, and 3 audit docs. Findings were made against the working tree as it stands, so the employee-documents code is uncommitted work in progress. |
| **Only artifact created** | This file. Scratch probe scripts lived in the session scratchpad, outside the repository. |

### How the evidence was gathered

- I read all of the code involved: the logging config, middleware, exception handlers, the DB session, Celery app and tasks, the health module, email senders, the face provider, storage, rate limiting, identity, Nginx, compose, the Dockerfile, CI, the web API client and the mobile API client.
- I ran two runtime probes in the scratchpad against the real `create_app()` middleware stack (`fastapi.testclient`, no DB writes). One raised an unhandled exception, a `DBAPIError` and a 5xx `AppError`. The other sent an oversized `X-Request-Id`.
- I sent one login against the **local test database** (`localhost:5433`, the suite's own seed user), with a short and a 65-char `X-Request-Id`.
- I ran 4 existing test files / 9 tests: `test_unhandled_exception_logging.py`, `test_celery_task_failure_logging.py`, `test_db_error_handler.py` and `test_auth_security.py::test_refresh_token_rotation`. All 9 passed.
- I imported the worker entrypoint to see whether structlog is configured in the worker.
- No emails were sent and no production systems were touched.

Locked versions (`apps/api/uv.lock`): fastapi 0.141.1, starlette 1.3.1, uvicorn 0.52.1, gunicorn 26.0.0, structlog 26.1.0, celery 5.6.3, kombu 5.6.2, redis-py 6.4.0, sqlalchemy 2.0.51, httpx 0.28.1, aioboto3 15.5.0, aiosmtplib 5.1.3. Web: next ^16.3.8, react ^18.3.1. Mobile: dio ^5.7.0, flutter_secure_storage ^9.2.2. **There is no Sentry, OpenTelemetry or Prometheus dependency anywhere.**

---

## A. Executive Summary

### Current maturity: **Level 1.5 of 4. Server-side logging exists but is fragmented. There are no metrics, no tracing and no alerting.**

Earlier audits drove real progress, and it holds up in this review:

- The catch-all 500 handler now logs with a traceback (FINDING-01).
- Celery has a global `task_failure` backstop.
- Leave tasks have bounded retries, `acks_late` and time limits.
- Liveness and readiness are separate endpoints.
- Docker logs are size-bounded.
- Nginx writes JSON access logs.
- Email and face-provider transports log failures without leaking secrets.
- The business audit log already stores `request_id`.

Request-scoped DB sessions use `Depends(get_session, scope="function")`, so commits happen **before** the response is sent. A commit failure therefore surfaces as an error and never as a false 200.

### Major strengths
1. **The error envelope is consistent.** Every handled error uses one `{error:{code,message,details,request_id}}` envelope (`core/errors/envelope.py`) with 262 stable codes. No stack trace or SQL reaches the client. I verified this by probe.
2. **Business audit trail is separate from operational logs.** It has redaction (`core/audit/redact.py`) and `request_id` on every row.
3. **Lock and statement timeouts are classified.** `core/db/timeouts.py::is_wait_timeout` maps them to `503 DATABASE_BUSY` + `Retry-After`.
4. **Fan-out tasks isolate failures per company and per employee**, with structured warning events.
5. **Provider error text is deliberately kept out of logs and responses** (email senders, Face++).

### Critical gaps (confirmed)
| # | Gap | Severity |
|---|---|---|
| LOG-01 | Unhandled exceptions lose correlation in the real middleware stack. The request ID is `"unknown"` in the log and in the response body, there is no `X-Request-Id` header, and there are **no CORS headers**, so the web app shows "Could not reach the server" instead of the error. *Verified by probe.* The existing test does not catch this because it skips the middleware. | **P1** |
| LOG-02 | Handled 5xx responses leave **no server log at all**. This covers generic DB errors (connection loss, pool exhaustion, unmapped integrity errors), `DATABASE_BUSY`, `RATE_LIMITER_UNAVAILABLE` (a Redis outage = total login outage with zero log lines) and crypto `DECRYPTION_FAILED`/`UNKNOWN_KEY_VERSION`. *Verified by probe.* | **P1** |
| TXN-01 | Refresh-token **reuse detection is rolled back**. The family revocation is written, then `InvalidTokenError` is raised, then `get_session` rolls the transaction back. The existing test asserts that the newest token **still works after reuse was detected**, and it passes. | **P1** (security) |
| PRA-04 (carried forward) | `employee_import.process_batch` is routed to `reports_exports`, but the production worker only consumes `default`. Imports sit at PENDING forever with no alert. This was already recorded and is still open. | **P1** |
| LOG-03 | Worker and Beat never call `configure_logging()`. Their logs are not JSON, the level filter is not applied, and `celery_task_failed` has no traceback. This contradicts `PRODUCTION_DEPLOYMENT.md` §15. *Verified.* | P2 |
| LOG-04 | Bearer tokens (onboarding and account-invite) sit in URL paths. They are written to the Nginx `$request_uri`, the gunicorn/uvicorn access log and the unhandled-exception `http_path`. | P2 |
| LOG-05 | `X-Request-Id` is accepted from clients with no validation. A 65-char value makes **any audited request fail with 422**, because `audit_log.request_id` is `VARCHAR(64)`. *Verified on the test DB:* login returned 200 with an 11-char ID and 422 `INVALID_VALUE` with a 65-char one. | P2 |
| OPS-A | No metrics, no alerting and no error tracking. Docker `HEALTHCHECK` status is not acted on by Compose, and nothing watches Beat. | P2 |

### Production-readiness implications
- Today, if an unexpected 500 happens in production, support gets a user report saying the server could not be reached. The matching log line says `request_id: "unknown"`. Many DB-originated 500s and every 503 leave no log line at all.
- Correlating a user complaint with the backend requires guessing from timestamps in the Nginx access log.
- **LOG-01, LOG-02, TXN-01 and PRA-04 are production blockers.** They are all small, localized fixes. The rest is staged hardening.

---

## B. Current-State Inventory

| Area | Existing Implementation | Evidence | Gap | Status |
|---|---|---|---|---|
| Logging library | structlog 26.1, JSON renderer, ISO timestamp, `format_exc_info`, `merge_contextvars` | `core/observability/logging.py:9-27` | Stdlib loggers (uvicorn, gunicorn, celery, sqlalchemy, httpx, botocore) are not routed through structlog, so output formats are mixed. No `service`/`environment` fields. | Partial |
| Logging config: API | `configure_logging()` called in `create_app()` | `app.py:50` | — | Implemented |
| Logging config: worker/beat | **None.** structlog is not configured, so it uses the dev console renderer. | `entrypoints/worker.py`, `core/celery_app.py`; probe: `structlog.is_configured() == False` | No JSON, no level filter | **Absent** |
| Contextvar binding | `merge_contextvars` is configured, but `bind_contextvars` is never called | `grep bind_contextvars` → 0 hits | request_id/company/user never appear in ordinary log events | **Absent** (configured but unused) |
| Request ID | `TenancyMiddleware` reads `X-Request-Id` or generates uuid4, stores it in a ContextVar, echoes it in the response header, and copies it into the error envelope and audit rows | `core/tenancy/middleware.py:18-34`, `core/audit/service.py:36` | No validation or length bound. Lost on unhandled exceptions (LOG-01). | Partial |
| Middleware order (outer→inner) | ServerErrorMiddleware → ProxyHeaders → SecurityHeaders → Tenancy → OnboardingUploadRateLimit → 5× MaxUploadSize → CORS → ExceptionMiddleware → router | `app.py:70-155` | CORS and Tenancy sit **inside** ServerErrorMiddleware, so a 500 from the catch-all loses both | Implemented, with a consequence |
| Global exception handlers | `AppError`, `RequestValidationError`, `DBAPIError`, `StarletteHTTPException`, `Exception` | `core/errors/handlers.py:60-150` | Only `Exception` logs. `AppError` 5xx and `DBAPIError` 500/503 are silent (LOG-02). | Partial |
| HTTP access log | gunicorn `--access-logfile -` with the deprecated `uvicorn.workers.UvicornWorker` (plaintext uvicorn format, full path + query) | `apps/api/Dockerfile` CMD; `uvicorn/workers.py:18,41` | No request_id, no duration, raw path (tokens), not JSON | Partial |
| Edge access log | Nginx `json_combined` with `request_time` and `upstream_response_time` | `infra/nginx/nginx.conf` | Logs `$request_uri` (tokens and presigned signatures). No request ID generated or forwarded. | Partial |
| DB error handling | Wait-timeout → 503, SQLSTATE 22 → 422, else 500 | `handlers.py:96-116`, `core/db/timeouts.py` | No log on 500/503. Engine has no `hide_parameters`, so `str(DBAPIError)` contains bound parameters. | Partial |
| Transactions | `get_session`/`session_scope` commit or roll back. All 53 uses are `scope="function"`, so the commit happens before the response. | `core/db/session.py:52-83` | "Write then raise" patterns are silently discarded (TXN-01). Login knows this and commits first (`identity/service.py:71-74`). | Implemented (with a defect) |
| Celery failure logging | `task_failure` signal → `celery_task_failed`. Leave `_LeaveTask.on_failure`. | `core/celery_app.py:89-109`, `leave/tasks.py:33-47` | No traceback in the structured event. Retries not logged. Partial-failure tasks report success. | Partial |
| Celery reliability | Leave: `acks_late`, `reject_on_worker_lost`, bounded autoretry, soft/hard time limits | `leave/tasks.py:54-67` | Attendance/employee/import tasks have none of this. Import queue is not consumed (PRA-04). | Partial |
| Beat observability | Single instance; healthcheck disabled | `docker-compose.prod.yml:195-220` | No heartbeat, so a missed schedule is invisible | **Absent** |
| Health | `/health/live` (no deps), `/health/ready` (DB, Redis, storage config; 3 s timeouts; 503 when not ready), legacy `/health` | `modules/health/router.py`, `service.py` | Readiness failures are not logged. Storage check is config-only. Nothing polls `/ready`. | Implemented |
| Container health | API `HEALTHCHECK` → `/health/live`; worker → `celery inspect ping` | `Dockerfile`, compose | Plain Compose does **not** restart an "unhealthy" container. Nothing alerts on it. | Partial |
| Email | Sender classes log transport failures with `error_type`/`status_code` only. Callers swallow the exception. | `onboarding/email_sender.py:80-195` | No outbox, no retry, not queued. `to=` email address is logged. `email_sent` is recorded in audit for only 2 of 7 call sites. | Partial |
| External: Face++ | httpx timeout from settings; failure logged with operation/status; credentials not logged | `attendance/face_verification.py:110-150` | Orphan-cleanup failure logs no identifiers (LOG-09) | Implemented |
| External: object storage | aioboto3, new client per call | `core/storage.py` | No botocore `Config` (default 60 s connect/read and legacy retries can exceed gunicorn's 60 s timeout). Upload/delete ordering can orphan objects or rows. | Partial |
| Rate limiting | Redis INCR; fails closed with 503 | `shared/rate_limit.py:74-140` | 429 and 503 are not logged. No `Retry-After` on 429. | Partial |
| Security events | Audit rows for LOGIN/TOKEN_REFRESH/LOGOUT; failed-login counter and lockout | `identity/service.py` | No log or audit for failed login, lockout, reuse detection or rate-limit trips | **Absent** |
| Frontend API client | Per-request `X-Request-Id`, typed `ApiError` with `requestId` from envelope, `NetworkError`, single-flight refresh | `apps/web/src/lib/api/client.ts`, `errors.ts` | Request ID never shown to users. Unhandled 500 → `NetworkError` (LOG-01). | Partial |
| Frontend error boundaries | **None.** No `error.tsx`, no `global-error.tsx`, no `ErrorBoundary`. | `find src -name error.tsx` → 0 | A render error blanks the whole app | **Absent** |
| Frontend telemetry | None; no `console.*` in non-test code | grep | Acceptable for now (privacy) | Absent (by choice) |
| Mobile global handlers | **None.** No `FlutterError.onError`, `PlatformDispatcher.onError`, `runZonedGuarded` or `ErrorWidget.builder`. | `apps/mobile/lib/main.dart` | Uncaught async errors are invisible. Release builds show a grey box. | **Absent** |
| Mobile API client | Mirrors web; `X-Request-Id`; secure-storage tokens; refresh single-flight | `lib/core/api/api_client.dart` | **No dio timeouts** (infinite). Request ID never shown. Face punch has no idempotency key. | Partial |
| Metrics / tracing / alerting | None | grep of deps and config | — | **Absent** |
| Log retention | Docker json-file 10 MB × 5 per container; backups keep 14 days with a file log | compose `x-logging`; `infra/backup/*.sh` | No central store. No alert on backup failure. Retention is set by size, not by policy. | Partial |
| CI | Ruff (incl. `BLE`, `TRY`), mypy strict, import-linter, gitleaks, pip-audit, npm audit, unit/integration/security tests, web build | `.github/workflows/ci.yml` | No mobile job. No test proves request-ID propagation through the real stack. | Partial |
| Tests | Unhandled-exception logging, celery failure logging, DB error handler, wait-timeout handler, health router, audit redaction, security headers, CORS | `tests/unit/core/*`, `tests/security/*` | **No test references `X-Request-Id`.** Logging tests use bare apps, not `create_app()`. | Partial |

---

## C. Architecture Assessment

### C.1 HTTP request: current behavior (observed)

```
Client ──X-Request-Id?──▶ Nginx (JSON access log: $request_uri, no request id)
  ▶ gunicorn/uvicorn (plaintext access log: raw path+query, client = nginx IP)
    ▶ ServerErrorMiddleware [catch-all Exception handler lives HERE: outermost]
      ▶ ProxyHeaders ▶ SecurityHeaders ▶ Tenancy(set request_id ContextVar; finally: clear)
        ▶ RateLimit ▶ MaxUpload×5 ▶ CORS ▶ ExceptionMiddleware[AppError/DBAPIError/HTTP/Validation]
          ▶ route ▶ deps(get_session scope=function) ▶ service ▶ DB / storage / provider
```

| Outcome | Server log | Response request_id | `X-Request-Id` header | CORS headers |
|---|---|---|---|---|
| 2xx/4xx | none (except provider-level events) | n/a / correct | ✅ | ✅ |
| `AppError` 5xx (`RATE_LIMITER_UNAVAILABLE`, `ENCRYPTION_UNAVAILABLE`, `DECRYPTION_FAILED`, `FACE_PROVIDER_FAILED`…) | **none** (face provider logs at source) | ✅ | ✅ | ✅ |
| `DBAPIError` → 500 / 503 | **none** | ✅ | ✅ | ✅ |
| Any other exception → 500 | `unhandled_exception` + traceback, **`request_id:"unknown"`**, plus a duplicate plaintext "Exception in ASGI application" from uvicorn | **`"unknown"`** | **missing** | **missing** (browser sees a network error) |

Root cause of the last row: the catch-all handler runs in `ServerErrorMiddleware`, which is outside `TenancyMiddleware`. By the time it runs, `TenancyMiddleware`'s `finally: clear_context()` (`middleware.py:31`) has already reset the ContextVar. CORS and SecurityHeaders are also inner layers, so their headers are never applied to that response.

### C.2 Recommended request flow

```
Nginx: generate $request_id when none was sent; forward X-Request-Id; log request_id + route-safe URI
  ▶ RequestContextMiddleware (pure ASGI, OUTERMOST app middleware, wraps everything incl. the 500 path):
       validate/replace X-Request-Id → bind_contextvars(request_id, method)
       time the request; on completion emit ONE `http_request` event
         {request_id, method, route_template, status_code, duration_ms, company_id?, user_id?}
       on an exception escaping the stack: log `unhandled_exception` ONCE (traceback), build the
       envelope itself with the real request_id, and add X-Request-Id + CORS-allowed-origin headers
  ▶ ProxyHeaders ▶ SecurityHeaders ▶ (Tenancy reduced to tenant resolution) ▶ … ▶ handlers
       AppError: 4xx → no ERROR log (the access event carries code); 5xx → `app_error` at ERROR
       DBAPIError: every 500/503 → `db_error` with sqlstate/class, no parameters
  ▶ get_tenant_context: after membership is verified, bind_contextvars(company_id, user_id)
  ▶ service ▶ outbound calls (httpx/aioboto3/SMTP) tag events with request_id from the context
  ▶ Celery .delay(): pass request_id in headers → worker task_prerun binds it (task_id + request_id)
```

Design rules:
- One access event per request and one error event per failure. Never log the same exception at several layers.
- Use the route template (`request.scope["route"].path`, for example `/v1/public/onboarding/{token}/documents`), never the raw path.
- Replace the default uvicorn access log with the structured `http_request` event, or drop its query string and path parameters.

### C.3 Celery flow (recommended)
`worker_process_init`/`setup_logging` signal → `configure_logging(service="worker")`, which applies one JSON configuration to structlog and the stdlib root logger (Celery's own loggers included).
- `task_prerun` → bind `task_id`, `task_name`, `request_id` (from headers, if dispatched by a request), `company_id` (first argument by convention).
- `task_retry` → `celery_task_retry` at WARNING.
- `task_failure` → `celery_task_failed` at ERROR with `exc_info`.
- `task_postrun` → `celery_task_finished` with `duration_ms` and state.
- Fan-out tasks that complete with per-item failures emit `*_incomplete` (this already exists) and also return a structured result that the metrics counter can pick up.

### C.4 Frontend flow
1. `apiClient` already sets `X-Request-Id`.
2. Keep the **client-sent** ID on `ApiError` (`clientRequestId`) and use it when the body carries none (5xx without envelope, 502 from Nginx, network error).
3. Route-level `error.tsx` and root `global-error.tsx` render a fallback that shows "Reference: <request id>" with a copy button.
4. No third-party telemetry for now (see §I).

### C.5 Mobile flow
1. `runZonedGuarded` + `FlutterError.onError` + `PlatformDispatcher.instance.onError` route to a local, bounded, redacted ring buffer (no tokens, no images, no payloads).
2. Set dio `connectTimeout`/`receiveTimeout`/`sendTimeout`, with longer send for uploads.
3. Show "Reference: <request id>" on error snackbars and dialogs.
4. Face punch sends an idempotency key that is reused on retry.
5. Crash-reporting service: evaluate later (§I).

---

## D. Findings Register

Severity: P0 = data loss/security breach in progress; P1 = production blocker; P2 = must fix before scale/pilot sign-off; P3 = improvement; INFO = observation. Only findings with direct evidence are rated P1.

### LOG-01: Unhandled exceptions lose request correlation, CORS and security headers
- **Severity / Confidence:** P1 / HIGH (runtime-verified)
- **Module:** core/errors, core/tenancy
- **Where:** `core/tenancy/middleware.py::TenancyMiddleware.dispatch` (lines 28-33: `finally: clear_context()`, then `response.headers["X-Request-Id"]` is only reached on success); `core/errors/handlers.py::unhandled_exception_handler`; `app.py:70-153` (middleware order).
- **Evidence:** A probe with `create_app()`, sending `GET /__probe/boom` with `X-Request-Id: client-supplied-1` and `Origin: http://localhost:3000`, produced:
  - Log: `"request_id": "unknown"` with an ExceptionGroup traceback.
  - Response: 500, body `request_id: "unknown"`, no `x-request-id` header, no `access-control-allow-origin`, no CSP.
  - The same probe against a `DBAPIError` route returned all three.
- **Why tests miss it:** `tests/unit/core/test_unhandled_exception_logging.py` builds a bare `FastAPI()` with no middleware and sets the request ID inside the route.
- **Failure scenario:** An HR user hits a bug. The browser blocks the CORS-less 500, so `fetch` throws and the web client shows "Could not reach the server" (`client.ts:106`). Support has no request ID. The server log line says `"unknown"`.
- **Impact:** The primary diagnostic path for unexpected crashes cannot be correlated. Users are told the wrong thing (network issue instead of server error).
- **Remediation:**
  1. Move request-ID handling into a pure-ASGI middleware added **last** (outermost of the app's own middleware). Do not clear the context until after the response is sent.
  2. Have that middleware catch exceptions and build the 500 envelope itself, with `X-Request-Id`, the security headers, and the CORS headers for an allowed origin (reuse `settings.effective_cors_origins`).
  3. Alternatively, keep Starlette's catch-all but read the request ID from `request.state`/`scope` (set by the middleware) instead of a ContextVar that has been cleared, and add CORS headers explicitly.
  4. Suppress uvicorn's duplicate "Exception in ASGI application" traceback, or accept it knowingly.
- **Test needed:** Integration test on `create_app()` with an injected failing route, sending `X-Request-Id` and `Origin`. Assert the log `request_id`, envelope `request_id` and response header all equal the sent ID; assert `Access-Control-Allow-Origin` is present; assert exactly one ERROR event.

### LOG-02: Handled 5xx responses leave no server-side trace
- **Severity / Confidence:** P1 / HIGH (runtime-verified)
- **Module:** core/errors
- **Where:** `core/errors/handlers.py::db_error_handler` (lines 96-116: the `DATABASE_BUSY` 503 branch and the final `INTERNAL_ERROR` 500 have no log call) and `::app_error_handler` (lines 63-74: never logs, whatever the `status_code`).
- **Evidence:** In the probe, an `OperationalError` route returned 500 and an `AppError("upstream failed")` returned 500, and neither produced any log output. 5xx `AppError`s in the codebase:
  - `RateLimiterUnavailableError` 503 (`shared/rate_limit.py:45`)
  - `EncryptionUnavailable`/`DecryptionUnavailable`/`NoActiveEncryptionKey` 503
  - `DecryptionFailed`/`MalformedCiphertext`/`UnknownKeyVersion` 500 (`core/crypto/errors.py`)
  - `FaceVerificationUnavailableError` 503
  - `FaceProviderFailedError` 502 (logged at the provider, `face_verification.py:127`)
- **Failure scenario:**
  - Redis goes down: every `/auth/login`, `/auth/token/refresh` and password-reset request returns 503, and the API logs nothing.
  - A Postgres failover or pool exhaustion: 500s with no line.
  - A PII decryption failure (key mismatch, a data-integrity event): 500 with no line.
- **Impact:** Outages and data-integrity events can only be diagnosed from Nginx status codes.
- **Remediation:**
  - In `app_error_handler`, log at ERROR when `status_code >= 500`, with `error_code`, `exception_type` and `exc_info` of the `__cause__` (safe: the traceback is server-side only).
  - In `db_error_handler`, log `db_error` (500 at ERROR, 503 at WARNING) with `sqlstate`, the driver exception class and the route template. **Never `str(exc)`**: see LOG-08.
  - Keep 4xx `AppError`s off ERROR. Their code goes on the access event.
- **Test needed:** For each of `AppError(status 503)`, a generic `DBAPIError`, and a wait-timeout `DBAPIError`: assert exactly one event at the right level containing `error_code`/`sqlstate` and the correct `request_id`, and that the bound parameter value does **not** appear in it.

### TXN-01: Refresh-token reuse detection is rolled back
- **Severity / Confidence:** P1 / HIGH (verified by the existing passing test)
- **Module:** identity
- **Where:** `modules/identity/service.py::IdentityService.refresh` (lines ~129-143), `core/db/repositories/identity.py::revoke_refresh_family` (143-164), `core/db/session.py::get_session` (`except Exception: rollback`).
- **Evidence:** `revoke_refresh_family` executes the UPDATEs, then `raise InvalidTokenError`, then the request transaction is rolled back. `tests/integration/auth/test_auth_security.py::test_refresh_token_rotation` (lines 106-122) asserts that after the reuse returns 401, `second = refresh(new_refresh)` returns **200**. It passes (run 2026-10-13). By contrast, `login()` explicitly commits before raising, with a comment explaining exactly this rollback hazard (`identity/service.py:71-74`).
- **Failure scenario:** An attacker steals a refresh token, and the legitimate user (or the attacker) rotates it. Presenting the old token triggers "reuse detected". The family is meant to be revoked, but the revocation is discarded, so whoever holds the newest token keeps a valid session.
- **Impact:** The token-theft containment control does not work. There is also no log or audit event for reuse, so the incident is invisible.
- **Remediation:**
  1. Commit the revocation before raising (same pattern as `login`), or do the revocation in a separate `session_scope()`.
  2. Emit a `security.refresh_token_reuse_detected` WARNING event (user_id, family_id, never the token) and an audit row.
  3. Fix the test: assert that the newest token is **rejected** after reuse.
  4. Sweep for other "write then raise" sites (Phase 1 task).
- **Test needed:** Rotate, replay the old token (401), then the new token is also 401. Assert DB rows have `revoked_reason='REUSE_DETECTED'` and that one security event was emitted.

### PRA-04 (carried forward, still open): import batches never processed
- **Severity / Confidence:** P1 / HIGH
- **Where:** `modules/employee_import/tasks.py:32` (`queue="reports_exports"`); `docker-compose.prod.yml:170` worker command has no `-Q`; no `task_queues`/`task_routes` in `core/celery_app.py`.
- **Evidence:** Already recorded in `PRODUCTION_READINESS_AUDIT_PRE_PAYROLL.md:355,802`, and the code is unchanged.
- **Observability angle:** There is no queue-depth or stuck-batch signal, so this fails silently. Remediation is as already written (`-Q default,reports_exports`), plus the queue-depth and oldest-PENDING-batch alert in §J.

### LOG-03: Worker and Beat logging is never configured
- **Severity / Confidence:** P2 / HIGH (verified)
- **Where:** `configure_logging()` is called only from `app.py:50`. `entrypoints/worker.py`/`beat.py` and `core/celery_app.py` never call it.
- **Evidence:** Importing `entrypoints.worker` gives `structlog.is_configured() == False`, and `celery_task_failed` renders as `2026-10-13 20:28:30 [error ] celery_task_failed exception_message=boom …` (console format, not JSON). `PRODUCTION_DEPLOYMENT.md` §15 claims "API/worker/beat emit structured JSON".
- **Impact:**
  - Worker events cannot be parsed by the same pipeline.
  - `LOG_LEVEL` is ignored, so debug events are emitted.
  - The `celery_task_failed` and `leave_task_failed` events carry no traceback. Only Celery's own plaintext "Task … raised unexpected" line has it.
- **Remediation:**
  - Add `configure_logging()` to a `celery.signals.setup_logging` handler (this also stops Celery hijacking the root logger) and route stdlib logging through `structlog.stdlib.ProcessorFormatter` so Celery, kombu and httpx lines become JSON too.
  - Add `exc_info=exception` to the failure events.
  - Correct the deployment doc.
- **Test needed:** Subprocess test: import the worker entrypoint, emit an event, assert one JSON line containing `service:"worker"` and, for failures, `exception` with a traceback.

### LOG-04: Bearer tokens in URL paths are written to three logs
- **Severity / Confidence:** P2 / HIGH
- **Where:**
  - `modules/onboarding/public_router.py:44-121` (`/v1/public/onboarding/{token}/…`) and `modules/account_invite/public_router.py:30,39` (`/{token}`, `/{token}/accept`).
  - Web routes `/reset-password/{token}` and `/verify-email/{token}` (`identity/service.py:335,412`).
  - Logged by Nginx `log_format json_combined` → `$request_uri` (`infra/nginx/nginx.conf`), the uvicorn access logger via gunicorn `--access-logfile -` (`Dockerfile` CMD; uvicorn logs the path with query string), and `unhandled_exception.http_path=request.url.path` (`handlers.py:144`).
- **Failure scenario:** Anyone who can read `docker logs`, or a future log shipper, can replay an onboarding token. That gives access to a candidate's personal, statutory and bank sections while the token is valid. An invite token lets them accept an account invite.
- **Impact:** Credential exposure in logs. **This becomes P1 the moment logs are shipped off-host.**
- **Remediation:**
  - API: log `route_template` only. Replace or disable the uvicorn access log (structured `http_request` event).
  - Nginx: log `$uri` with the token segment masked via a `map` (e.g. `^/v1/public/(onboarding|account-invites)/[^/]+` → `…/{token}`), and drop `$args` for the storage vhost.
  - Long term (product decision): move tokens to a header or POST body. **Not** recommended now because of the client compatibility impact.
- **Test needed:** Request a public onboarding route with a sentinel token through `create_app()`. Assert the sentinel is absent from every captured log line. Add an Nginx config test (`nginx -t` plus a fixture request in a disposable container) asserting the masked URI.

### LOG-05: Client-supplied `X-Request-Id` is unvalidated, and >64 chars breaks audited requests
- **Severity / Confidence:** P2 / HIGH (verified on the test DB)
- **Where:** `core/tenancy/middleware.py:18` (`request.headers.get("X-Request-Id") or uuid4`); `core/audit/models.py:28` (`String(64)`); migration `20260803200000_b1_auth_audit.py:39`.
- **Evidence:** `POST /v1/auth/login` with seed credentials returned 200 with an 11-char ID and **422 `INVALID_VALUE`** with a 65-char ID. A 3000-char ID was echoed verbatim in the response header (probe).
- **Failure scenario:** Any client, proxy or tracing library that sends an ID longer than 64 chars makes every audited mutation (login, refresh, HR writes) fail. An attacker can also choose arbitrary request IDs to collide with or confuse audit and log correlation. Newlines cannot get through, because the HTTP layer rejects them and the JSON renderer escapes.
- **Remediation:**
  - Accept the client value only if it matches `^[A-Za-z0-9._:-]{8,64}$`. Otherwise generate a new UUID.
  - When a valid client ID is replaced or kept, log the original as `client_request_id` (truncated and sanitised) for traceability.
  - Nginx should set `X-Request-Id $request_id` when the header is absent, so edge and API logs share an ID.
- **Test needed:** Parametrised: absent → UUID generated; valid → propagated to header, envelope, log and audit row; 65 chars, empty, or containing spaces/control characters → replaced; login with an over-long ID → 200.

### LOG-06: Email delivery failures are swallowed at 5 call sites with no outcome record
- **Severity / Confidence:** P2 / HIGH
- **Where:**
  - `identity/service.py:343` (password reset) and `:420` (verification): `except Exception: pass`.
  - `onboarding/service.py:1089` (changes requested), `:1495` (activated) and `:1513` (account-invite auto-issue, which swallows *any* exception, not only email).
  - `account_invite/service.py:196` and `onboarding/service.py:759` record `email_sent` in audit (good).
- **Evidence:** The sender classes do log transport failures (`email_sender.py:97,143,188`), but:
  - (a) exceptions outside the transport, such as template building, misconfiguration or a non-`SMTPException` `OSError`, are swallowed with no log;
  - (b) `onboarding.py:1513` can hide a real bug in `issue_for_employee` (for example a DB error);
  - (c) every event name is prefixed `onboarding_email_*` even for password reset and verification, which misleads alert rules.
- **Failure scenario:** The account-invite auto-issue fails after activation because of a bug. The employee never gets login access, and there is no log line.
- **Remediation:**
  - Replace `pass` with a WARNING `email_delivery_failed`/`account_invite_auto_issue_failed` event carrying `exc_info`, `email_kind`, `entity_id` and request_id (no address).
  - Rename the sender events to `email_send_failed` with a `provider` field.
  - Phase 2: move to a DB outbox with retries (§F Phase 2).
- **Test needed:** A fake sender raising `RuntimeError` makes the request still succeed, exactly one WARNING event is emitted with `email_kind`, and the address does not appear in it.

### LOG-07: Rate-limit trips and security events are not logged
- **Severity / Confidence:** P2 / HIGH
- **Where:**
  - `shared/rate_limit.py:74-140` (429 and 503 raised with no log); the onboarding upload middleware returns 429/503 directly (same file, ~lines 60-95).
  - `identity/service.py:62-75` (failed login and lockout not logged or audited); `refresh` (reuse not logged).
- **Impact:** Credential stuffing, lockout storms and token theft are invisible except through the DB counters.
- **Remediation:**
  - Emit a `security.*` event family at WARNING: `login_failed` (hash of the email, IP, reason category), `account_locked`, `rate_limited` (bucket, IP), `refresh_token_reuse_detected`.
  - Never log passwords or tokens. These events must not be sampled.
  - Add `Retry-After` to 429.
- **Test needed:** Six bad logins produce five `login_failed` events and one `account_locked`, and none contains the plaintext password or email.

### LOG-08: Exception text and SQLAlchemy parameters can carry PII into logs
- **Severity / Confidence:** P2 / MEDIUM. The mechanism is certain; the actual PII exposure depends on which statement fails.
- **Where:**
  - `core/db/session.py:23` (`create_async_engine` without `hide_parameters=True`).
  - `str(exc)` is logged at `attendance/tasks.py:110` (`[:600]`), `leave/service.py:1631,1802` (`[:300]`), `leave/tasks.py:46,83`, `handlers.py:148` (`exception_message=str(exc)`), and `celery_app.py:108`.
- **Evidence:** SQLAlchemy's `DBAPIError.__str__` appends `[SQL: …] [parameters: …]` unless the engine has `hide_parameters=True`. FastAPI's `ResponseValidationError` string includes the offending `input` values. The `format_exc_info` traceback repeats the message.
- **Failure scenario:** An integrity error during leave accrual logs employee identifiers, names or encrypted blobs.
- **Remediation:**
  - Set `hide_parameters=True` outside development.
  - Introduce `safe_error(exc)` → `{exception_type, sqlstate?, error_code?}` and use it instead of `str(exc)` in all structured fields. Keep `exc_info` for the traceback only.
  - Add a redaction processor as a last line of defence (§H).
- **Test needed:** Force an IntegrityError carrying a sentinel value through a task and through a request. Assert the sentinel is absent from logs.

### LOG-09: Biometric and document orphans are logged without identifiers, or not logged
- **Severity / Confidence:** P2 / HIGH
- **Where:**
  - `attendance/face_service.py:485` (`face_enrollment_orphaned_provider_person`: provider name only, no `person_id`/company/employee) and `:493` (`face_review_photo_delete_failed`: no key).
  - `employee/service.py:3492` (`put_object` before `insert_document`; no cleanup if the insert, audit or commit fails) and `:3578` (`delete_object` before the row delete; if the commit fails, the row points at a deleted object). This is uncommitted work-tree code.
- **Impact:** Orphaned face photos, provider persons and employee documents cannot be found for deletion. That is a privacy and retention problem: biometric data that should be deleted cannot be located.
- **Remediation:**
  - Log the opaque identifiers needed for reconciliation (`company_id`, `employee_id`, object key, provider `person_id`), which are not PII by themselves.
  - Mirror face_service's compensating cleanup in the document upload path.
  - For delete, either delete the row first and remove the object after commit (an orphan object is preferable to a dangling row), or mark the row `DELETING` and use a sweeper.
  - Add a periodic reconciliation job (Phase 2).
- **Test needed:** Make `insert_document` raise after `put_object`. Assert `delete_object` was called with the key, or that an `orphaned_object` event carries the key.

### LOG-10: Celery tasks other than Leave lack bounded runtime, ack policy and retry observability
- **Severity / Confidence:** P2 / HIGH
- **Where:** `attendance/tasks.py:152-300`, `employee/tasks.py:37-47` and `employee_import/tasks.py:32` use bare decorators: no `time_limit`, default early ack, no retry. Fan-outs `run_termination_access_sweep`/`run_daily_calculation` call `.delay()` with no per-company try/except, unlike `leave/tasks.py::_dispatch`.
- **Failure scenarios:**
  - A hung `calculate_company`, for example a DB wait outside `bounded_waits`, occupies one of the two worker slots indefinitely.
  - A broker hiccup mid-fan-out silently skips the remaining companies' termination-access sweep. This is a security-relevant control: terminated employees keep access.
  - With early ack, a worker crash loses the task.
- **Remediation:**
  - Apply the Leave option set (soft/hard limits, `acks_late`, `reject_on_worker_lost`) to every idempotent task.
  - Use `_dispatch`-style isolation for all fan-outs.
  - Add `task_retry` and `task_postrun` signal logging.
  - Set the global `worker_prefetch_multiplier=1` for long tasks.
- **Test needed:** Eager-mode test where `.delay()` raises for company 2 of 3, so companies 1 and 3 are still dispatched and one WARNING is emitted. Settings test asserting every registered task has a `time_limit`.

### LOG-11: Partial-failure tasks report success, and the outcome is only a WARNING
- **Severity / Confidence:** P2 / MEDIUM
- **Where:** `attendance/tasks.py:142-149` (`attendance_scheduled_calculate_incomplete`), `leave/service.py:1634-1640` (`leave_accrual_incomplete`) and the year-end equivalent. The task returns normally, so `task_failure` never fires.
- **Impact:** Payroll inputs (attendance days, leave balances) can be silently incomplete. The only evidence is one WARNING line in a 50 MB rotating Docker log.
- **Remediation:** Treat `*_incomplete` as an alertable signal (§J). Persist a per-run summary row (company, task, counts, finished_at) so Payroll period-close can check that the last run was complete. That is a business control, not just logging.
- **Test needed:** Inject a failure for one employee. Assert the run summary records `failed=1` and the event is at the agreed level.

### LOG-12: Health signals are not acted on or alerted
- **Severity / Confidence:** P2 / HIGH
- **Where:**
  - `Dockerfile` `HEALTHCHECK`; `docker-compose.prod.yml` worker healthcheck (184-190); beat `healthcheck: disable` (212-213).
  - Nginx `location = /health/ready` is only proxied and does not gate routing (Nginx OSS has no active health checks).
  - `health/service.py::check_ready` does not log which dependency failed.
- **Evidence:** Docker Compose (non-Swarm) does not restart containers marked `unhealthy`. `restart: unless-stopped` only reacts to process exit.
- **Impact:** A wedged worker (alive but not consuming), a stopped Beat, or an API that keeps failing readiness all go unnoticed.
- **Remediation:**
  - An external uptime monitor polls `/health/ready` (and `/health/live`).
  - Add a Beat heartbeat task (e.g. `health.beat_heartbeat` every 5 min writing a Redis key with a TTL) and expose its age through readiness or a separate `/health/jobs` (authenticated or internal).
  - Log `readiness_failed` with the dependency name and exception type.
  - Optionally run `autoheal` or a cron `docker ps --filter health=unhealthy` script.
- **Test needed:** Readiness with Redis down returns 503 and exactly one WARNING naming `redis`. Heartbeat: an age above threshold reports not-OK.

### LOG-13: Web app has no error boundaries and never shows the request ID
- **Severity / Confidence:** P2 / HIGH
- **Where:** `apps/web/src/app` has no `error.tsx`/`global-error.tsx` and there are no `ErrorBoundary` components. `ApiError.requestId` is never rendered (grep: only `client.ts`/`errors.ts`).
- **Impact:** Any render-time exception blanks the screen with the Next.js default. Users cannot give support a reference.
- **Remediation:**
  - Add `app/global-error.tsx` and `app/app/error.tsx` with retry plus "Reference: <id>".
  - Add a `clientRequestId` fallback in `rawRequest`.
  - Show the reference in toast/banner helpers for status ≥ 500 and status 0.
- **Test needed:** Vitest: a component that throws renders the fallback. A 500 without JSON body produces an `ApiError` carrying the client-sent ID.

### LOG-14: Some web screens turn load failures into empty data
- **Severity / Confidence:** P3 / HIGH
- **Where:** `app/app/departments/page.tsx:59` (`employeeData = []`), `app/app/attendance/[id]/page.tsx:75` (`setLeaveProjections([])`), `components/employee/employee-overview.tsx:70` (`manager = null`).
- **Impact:** The UI shows "0 employees" or "no projections" when the request actually failed.
- **Remediation:** Render an explicit "couldn't load" state with retry.
- **Test:** Mock a failure and assert the error text, not an empty list.

### LOG-15: Mobile has no global error capture and no network timeouts
- **Severity / Confidence:** P2 / HIGH
- **Where:** `apps/mobile/lib/main.dart` (no handlers); `lib/core/api/api_client.dart:59` (`BaseOptions(baseUrl:)` only, so dio waits indefinitely); several screens use `catch (_) {}` (`policy_resolution_screen.dart:54`, `rosters_screen.dart:83`, `policy_assignments_screen.dart:51,91`). No mobile job in CI.
- **Failure scenario:** On a weak network a face punch spins forever. The employee kills the app and punches again (no idempotency key on `/attendance/face-punches/me`, `attendance_repository.dart:328`), which can create a duplicate punch. Whether the server deduplicates within a window is **unverified** (§M).
- **Remediation:**
  - Timeouts: connect 10 s, receive 30 s, send 60 s for multipart uploads.
  - Global handlers with a local redacted ring buffer and a "copy diagnostics" action.
  - Show the reference on errors.
  - Idempotency key on face punch, reused on retry (needs API support).
  - Add `flutter analyze && flutter test` to CI.
- **Test needed:** A dio mock with delay greater than the timeout gives `NetworkError` with a timeout subtype. Widget test: an error snackbar contains the reference.

### LOG-16: Storage client has no explicit timeouts or retries
- **Severity / Confidence:** P3 / MEDIUM
- **Where:** `core/storage.py::_client_kwargs` (no `botocore.config.Config`).
- **Impact:** Botocore defaults (60 s connect, 60 s read, legacy retries) can exceed gunicorn `--timeout 60`. The worker is killed with "WORKER TIMEOUT" and there is no application log.
- **Remediation:** `Config(connect_timeout=5, read_timeout=30, retries={"mode":"standard","max_attempts":3})`, plus a `storage_operation_failed` event classifying the error by type.
- **Test:** A stubbed slow endpoint raises a classified error within the timeout.

### LOG-17: Inbound and outbound access-log quality
- **Severity / Confidence:** P3 / HIGH
- **Where:**
  - `uvicorn.workers` is deprecated (warning at `uvicorn/workers.py:18`).
  - The uvicorn access log records the Nginx container IP (uvicorn's own `forwarded_allow_ips` defaults to 127.0.0.1), with no duration and no request ID.
  - In the worker, Celery's root logger at `--loglevel=info` will emit httpx `HTTP Request: POST https://api.mail.hostinger.com/api/v1/mailboxes/<id>/send` lines.
  - Nginx logs presigned URLs, with `X-Amz-Signature`, for the storage vhost.
- **Remediation:**
  - Switch to the `uvicorn-worker` package or `uvicorn --workers`.
  - Replace the access log with the structured `http_request` event.
  - Set `httpx`/`httpcore` loggers to WARNING.
  - Drop query strings for the storage vhost.
- **Test:** Covered by LOG-04's sentinel test, extended to `X-Amz-Signature`.

### INFO-01: Things that work and should be preserved
- `get_session(scope="function")` means commits happen before the response.
- `is_wait_timeout` → 503 + `Retry-After`.
- Provider error text is never logged (`EmailDeliveryError`, `FaceProviderError`).
- Leave task option set.
- Liveness and readiness split.
- Docker log size caps.
- Audit `request_id`.
- `LoggingEmailSender` is blocked outside development by settings guards. That matters, because it logs `text_body` containing reset and invite links.

---

## E. Proposed Standards

### E.1 Log format
One JSON object per line on stdout, for every process (api, worker, beat, ingestion). Stdlib loggers go through `structlog.stdlib.ProcessorFormatter` so third-party lines are JSON too. Processors, in order:

`merge_contextvars → add_log_level → add_logger_name → TimeStamper(iso, utc) → static {service, environment, version} → redact_processor → format_exc_info → JSONRenderer`

### E.2 Fields
| Field | When | Notes |
|---|---|---|
| `timestamp`, `level`, `event`, `logger`, `service`, `environment`, `version` | always | `event` is a stable snake_case name; it is the contract, not the message wording |
| `request_id` | request-scoped and request-dispatched tasks | validated (LOG-05) |
| `method`, `route_template`, `status_code`, `duration_ms` | `http_request` | never the raw path |
| `company_id`, `user_id` | after `get_tenant_context` verification | opaque UUIDs; **not** metric labels |
| `error_code`, `exception_type`, `sqlstate` | errors | never `str(exc)` for DB/validation errors |
| `exception` (traceback) | unexpected errors only | via `exc_info` |
| `task_id`, `task_name`, `retries`, `duration_ms` | Celery | |
| `provider`, `operation`, `status_code` | outbound calls | no URLs with secrets |

### E.3 Exception classification
| Class | Examples | Log level | Traceback | Response |
|---|---|---|---|---|
| Expected business rule | `AppError` 4xx (409 STALE_RESOURCE, 422, 404, 403) | none (code on access event) | no | as today |
| Client input | `RequestValidationError`, SQLSTATE 22 | none (INFO on access event) | no | 422 |
| Security-relevant client error | 401 invalid token/creds, 429, reuse, lockout | WARNING `security.*` | no | as today |
| Transient dependency | wait timeout, Redis down, provider timeout, storage timeout | WARNING (ERROR if sustained, via alerting) | no | 503/502/504 + `Retry-After` |
| Unexpected | everything else, 5xx `AppError`, unmapped `DBAPIError` | ERROR | yes | 500 envelope |
| Integrity | decryption failure, unknown key version, partial payroll/attendance run | ERROR + dedicated event | yes | 500 |

### E.4 Error response contract
Keep the existing envelope unchanged, because the web and mobile clients and the tests depend on it:

`{"error":{"code","message","details":[{field,code,message,context}],"request_id","documentation_url"}}`

Additions, all backward-compatible:
- `X-Request-Id` on **every** response, including the catch-all 500.
- `Retry-After` on 429 and 503.
- Do not change existing status codes. `423 ACCOUNT_LOCKED`/`LOCKED` and `422` for domain validation are established contracts.
- `HTTP_ERROR` (Starlette 404/405) stays.

### E.5 Correlation propagation
| Hop | How the ID travels |
|---|---|
| Client → Nginx | Client sends `X-Request-Id`; Nginx sets it from `$request_id` if absent. |
| Nginx → API | Header is forwarded and validated (LOG-05). |
| API internal | ContextVar via `bind_contextvars`. |
| API → Celery | `apply_async(headers={"request_id": …})`; `task_prerun` binds it. |
| API → audit | Already done. |
| API → outbound | Optional `X-Request-Id` on httpx calls to providers that echo it (not required). |
| Back to client | Response header plus envelope. Clients show it as "Reference". |

### E.6 Log levels
| Level | Use |
|---|---|
| DEBUG | Development only. |
| INFO | Lifecycle events: `http_request`, task finished, scheduled run summaries, startup and config summary (no secrets). |
| WARNING | Degraded but handled: per-item failures, retries, transient dependency errors, security events. |
| ERROR | Unexpected failures, 5xx, integrity events, task final failure. |
| CRITICAL | Boot refused (bad config, no active key). |

### E.7 Retention approach
See §I/§J. Operational logs: short (days to weeks), bounded by size. Security events: longer, in a separate stream once centralised. Business audit: the DB `audit_log`, governed separately and never replaced by logs.

### E.8 Monitoring standards
Metrics labels must be low-cardinality: `route_template`, `method`, `status_class`, `task_name`, `queue`, `provider`, `error_code`. Never use `user_id`, `company_id`, `employee_id` or `request_id` as labels.

---

## F. Phased Implementation Roadmap

### Phase 0: Baseline and urgent gaps (production blockers)
- **Objective:** Every 5xx is logged once with the correct request ID. The client always gets the request ID and a readable error. Reuse detection works. Imports run.
- **Findings:** LOG-01, LOG-02, TXN-01, PRA-04, LOG-05 (cheap, and it blocks audited requests).
- **Files expected to change:**
  - `core/tenancy/middleware.py` (or a new `core/observability/request_context.py`), `app.py` (middleware order), `core/errors/handlers.py`, `core/observability/logging.py`
  - `modules/identity/service.py` (+ test fix in `tests/integration/auth/test_auth_security.py`)
  - `docker-compose.prod.yml` (worker `-Q`) or `core/celery_app.py` (`task_routes`)
  - `infra/nginx/conf.d/hrms.conf.template` (`proxy_set_header X-Request-Id`)
- **Dependencies:** none.
- **Tasks:**
  1. Pure-ASGI request-context middleware (outermost): validate or generate the ID, `bind_contextvars`, set `scope["state"]["request_id"]`, always add `X-Request-Id`, clear the context only after the response completes.
  2. Catch-all 500: read the request ID from scope state; add CORS headers for allowed origins and the security headers; one log event.
  3. Log 5xx in `app_error_handler`/`db_error_handler` with safe fields.
  4. Commit the family revocation before raising; add a `security.refresh_token_reuse_detected` event; invert the test assertion.
  5. Consume `reports_exports`.
  6. `hide_parameters=True` outside development (one line; prevents LOG-02's new logs from leaking).
- **Tests:** see §K items T1–T8.
- **Acceptance:** The LOG-01 probe scenario returns the sent request ID in log, body and header with ACAO present. Generic DB 500/503 and 5xx `AppError` each produce exactly one event. Replaying a refresh token revokes the newest token. An import batch completes in a compose smoke test.
- **Deployment:** API + worker restart; Nginx reload. No migration.
- **Rollback:** Revert the commit; no data shape change. TXN-01 rollback re-opens the security gap, so do not roll it back alone.
- **Risks:**
  - Middleware reordering can affect CORS preflight and rate-limit IP resolution. Keep ProxyHeaders ahead of anything reading the client IP, and run the existing `test_cors_middleware.py`/`test_proxy_headers.py`/security suites.
  - Users with stolen-then-rotated sessions will be logged out (intended).
- **Effort:** Small–Medium.

### Phase 1: Backend consistency
- **Objective:** One structured logging contract across API and worker; safe error text; integrity-preserving transactions.
- **Findings:** LOG-03, LOG-04, LOG-06, LOG-07, LOG-08, LOG-09, LOG-16, LOG-17.
- **Files expected to change:**
  - `core/observability/logging.py` (shared config, ProcessorFormatter, redaction processor, `safe_error`), `core/celery_app.py` (`setup_logging` signal)
  - `core/errors/handlers.py`, `shared/rate_limit.py`, `modules/identity/service.py`, `onboarding/service.py`, `account_invite/service.py`, `onboarding/email_sender.py` (event names)
  - `attendance/face_service.py`, `employee/service.py` (document ordering), `core/storage.py` (botocore Config), `core/db/session.py`
  - `attendance/tasks.py`, `leave/*`, `Dockerfile` (worker class / access log)
  - `infra/nginx/nginx.conf` (masked URI, request_id field)
- **Dependencies:** Phase 0 (context binding).
- **Tasks:**
  1. Shared `configure_logging(service=…)` for all processes.
  2. `http_request` access event with `route_template` and `duration_ms`; disable the uvicorn access log.
  3. Redaction processor (§H) plus `safe_error`.
  4. `security.*` events.
  5. Replace `except Exception: pass` with logged warnings.
  6. Orphan-safe document upload and delete.
  7. Storage timeouts.
  8. Sweep for "write then raise" (grep for repository writes followed by `raise` inside one request transaction).
- **Tests:** T9–T16.
- **Acceptance:** No test-fixture sentinel secret or PII appears in any captured log across the suite. Every process emits JSON. No `except …: pass` without a log in `src/` (enforced by a ruff rule or a small CI grep).
- **Deployment:** Log format changes. Anyone grepping current plaintext lines must update their queries; announce it in the runbook.
- **Rollback:** Code revert. Logging-only changes are low risk. Document-ordering changes need their own tests.
- **Risks:** Over-redaction removing useful IDs. Keep UUIDs and redact only by key name and pattern.
- **Effort:** Medium.

### Phase 2: Background jobs and email
- **Objective:** Make task health, retries, scheduling and email delivery observable and recoverable.
- **Findings:** LOG-10, LOG-11, LOG-12 (Beat part), LOG-06 (delivery durability), PRA-04 follow-up.
- **Files expected to change:**
  - `core/celery_app.py` (signals, global defaults, heartbeat task); `attendance/tasks.py`, `employee/tasks.py`, `employee_import/tasks.py`
  - New `email_outbox` table + migration + `notifications` sending task (**decision required**, §O); a job-run summary table (**decision required**)
  - `modules/health/*`
- **Tasks:**
  1. Apply the Leave option set to all idempotent tasks; isolated fan-out dispatch.
  2. `task_retry`/`task_postrun` events with duration.
  3. Beat heartbeat.
  4. Job-run summary rows for attendance, accrual and year-end.
  5. Outbox: render → insert row in the business transaction → worker sends with bounded retries → status `SENT`/`FAILED_PERMANENT`. Deduplicate by `(kind, entity_id, version)`.
  6. Stuck-import detection: batches in PENDING/PROCESSING for more than N minutes are reported.
- **Tests:** T17–T22.
- **Acceptance:** Every task has a time limit. A killed worker redelivers idempotent tasks. Heartbeat age is visible. An email provider outage results in queued then sent mail, not lost mail.
- **Deployment:** Migration for the outbox and run-summary tables. Deploy the worker before relying on the outbox.
- **Rollback:** Feature flag on outbox use (callers fall back to direct send).
- **Risks:** Duplicate sends on retry. The outbox row is the dedup key, and providers are not idempotent, so accept at-least-once and record it.
- **Effort:** Large.

### Phase 3: Frontend and mobile
- **Objective:** Readable, correlated errors on every client surface without sending sensitive telemetry.
- **Findings:** LOG-13, LOG-14, LOG-15.
- **Files expected to change:**
  - Web: `src/app/global-error.tsx`, `src/app/app/error.tsx`, `src/lib/api/client.ts`, `errors.ts`, the toast helper, the 3 pages in LOG-14
  - Mobile: `lib/main.dart`, `lib/core/api/api_client.dart`, `api_error.dart`, snackbar helpers, `attendance_repository.dart` (idempotency key, which needs API support first)
  - `.github/workflows/ci.yml` (mobile job)
- **Tasks:**
  1. Error boundaries.
  2. Client request-ID fallback and "Reference" display.
  3. Explicit failed states.
  4. Dio timeouts.
  5. Flutter global handlers writing to a bounded local buffer.
  6. Face-punch idempotency (API + mobile).
  7. Mobile CI.
- **Tests:** T23–T27.
- **Acceptance:** Every error toast or dialog for status ≥ 500 or status 0 shows a reference. No screen renders empty data on a failed fetch.
- **Deployment:** Web redeploy; mobile release (store review lead time).
- **Rollback:** Standard.
- **Risks:** None material. Crash-reporting vendor deferred to §I.
- **Effort:** Medium.

### Phase 4: Operations
- **Objective:** Someone is notified when production is unhealthy.
- **Findings:** LOG-12, OPS-A, plus backup alerting.
- **Files expected to change:** `docker-compose.prod.yml` (optional monitoring services), `infra/` (alert scripts or config), `docs/deployment/PRODUCTION_DEPLOYMENT.md`, a new runbook. Optional `/metrics` endpoint (`prometheus-client`, **decision required**).
- **Tasks (minimal tier, §I):**
  1. External uptime check on `/health/ready` and the web root.
  2. Cron host script for disk %, memory, `docker ps` unhealthy, backup-log `FAILED`, Beat heartbeat age, Redis queue length, sending to email/Telegram/Slack webhook.
  3. Log-based alerts using a lightweight shipper (§I intermediate) **or** cron + `docker logs --since` + `jq` counts for `level=error`.
  4. Retention policy document.
- **Acceptance:** Each §J alert has been fired once in staging by fault injection, and its notification was received.
- **Effort:** Medium.

### Phase 5: Regression and production validation
- **Objective:** Prove it works and keep it working.
- **Tasks:**
  1. The full §K suite in CI.
  2. Fault injection in staging (stop Redis, stop the worker, block SMTP egress, fill a test volume, kill Postgres for 30 s).
  3. Deployment smoke script (health/ready, a forced 404 carries the request ID, an import batch completes).
  4. Runbook: "user reports error with Reference X → `docker compose logs api | jq 'select(.request_id=="X")'`".
  5. Final audit against §N.
- **Effort:** Medium.

---

## G. Error Code Catalogue

**Existing codes to preserve. They are API contracts used by the web and mobile clients and the tests.**

| Code | Status | Origin |
|---|---|---|
| `INTERNAL_ERROR` | 500 | `AppError` default, DB fallback, catch-all |
| `REQUEST_VALIDATION_ERROR` | 422 | FastAPI validation |
| `VALIDATION_ERROR` | 422 | domain validation |
| `INVALID_VALUE` | 422 | DB SQLSTATE 22 |
| `DATABASE_BUSY` | 503 + Retry-After | lock/statement timeout |
| `HTTP_ERROR` | 404/405… | Starlette |
| `NOT_FOUND` | 404 | |
| `CONFLICT` | 409 | |
| `STALE_RESOURCE` | 409 (detail code) | If-Match concurrency; web `getStaleResourceCurrent` depends on it |
| `PERMISSION_DENIED` | 403 | |
| `LOCKED`, `ACCOUNT_LOCKED` | 423 | |
| `UNAUTHORIZED`, `INVALID_CREDENTIALS`, `INVALID_TOKEN` | 401 | client refresh logic keys on 401 |
| `EMAIL_NOT_VERIFIED` | 403 | |
| `RATE_LIMITED` | 429 | |
| `RATE_LIMITER_UNAVAILABLE` | 503 | |
| `PAYLOAD_TOO_LARGE` | 413 | upload middleware |
| `IDEMPOTENCY_KEY_REQUIRED` / `_INVALID` / `_CONFLICT`, `DUPLICATE_PUNCH_IDEMPOTENCY_KEY` | 4xx | idempotency |
| `ENCRYPTION_UNAVAILABLE`, `DECRYPTION_UNAVAILABLE`, `NO_ACTIVE_ENCRYPTION_KEY` | 503 | crypto |
| `DECRYPTION_FAILED`, `MALFORMED_CIPHERTEXT`, `UNKNOWN_KEY_VERSION` | 500 | crypto (integrity: alert) |
| `FACE_VERIFICATION_UNAVAILABLE` / `FACE_PROVIDER_FAILED` | 503 / 502 | face |
| `MASTER_DATA_HAS_ACTIVE_EMPLOYEES`, `INACTIVE_*`, `COMPENSATION_CURRENCY_MISMATCH` | 409/422 | web `describeLifecycleError` depends on these |

There are 262 distinct `code = "…"` declarations in `src/`. Ten names are declared in more than one module with the same meaning (e.g. `NOT_FOUND`, `STALE_RESOURCE`, `INVALID_BRANCH`). That is acceptable.

**Conventions for new codes:**
- `UPPER_SNAKE`, domain-prefixed when module-specific (`PAYROLL_…`, `LEAVE_…`).
- Never reuse a code for a different meaning, and never rename one (add a new one and deprecate the old).
- `message` is safe, user-facing English. It must never contain exception text, SQL, provider text, file paths or IDs that were not supplied by the caller.
- Internal diagnosis goes in logs (`exception_type`, `sqlstate`, traceback), never in `details`.
- `details[].context` may carry structured, non-sensitive hints (counts, current resource for `STALE_RESOURCE`).
- Proposed new codes:
  - `UPSTREAM_TIMEOUT` (504) for provider/storage timeouts.
  - `STORAGE_UNAVAILABLE` (503) for object-storage failures. Today these are generic 500s.

---

## H. Redaction and Privacy Policy

### Must never be logged (anywhere, any level, any environment except the dev-only `LoggingEmailSender`)
- Passwords, password hashes, new-password fields.
- Access and refresh tokens; the `Authorization` header; the `Cookie`/`Set-Cookie` headers (`hrms_refresh`).
- Password-reset, email-verification, onboarding and account-invite tokens, **including URLs containing them**.
- Idempotency keys (low risk, but they are bearer-like for replay detection, so log a hash if needed).
- API keys and secrets: Face++ `api_key`/`api_secret`, Mailtrap/Hostinger tokens, SMTP password, S3 secret, JWT secrets, `pii_master_key`.
- Presigned URLs (`X-Amz-Signature`, `X-Amz-Credential`).
- Face images, face templates or embeddings, liveness payloads. Uploaded document contents.
- Aadhaar, PAN, bank account and IFSC numbers (plaintext or ciphertext), salary/CTC figures, payslip lines, tax computations.
- Raw request or response bodies, multipart parts.
- SQL bound parameters (`hide_parameters=True`); `ResponseValidationError` inputs.

### Minimise (log only when needed, in this form)
| Data | Allowed form |
|---|---|
| Email address | Not logged. Use `user_id` or a salted hash for security events. Applies to the current `to=` in `email_sender.py` and `reminders.py:232`. |
| IP address | Security events and Nginx only; same retention as security logs. |
| User agent | Nginx only. |
| Names, phone, DOB, address | Never. |
| `company_id`, `user_id`, `employee_id`, object keys, provider person IDs | Allowed (opaque identifiers needed for reconciliation). |
| Exception messages | Only for exception types known to be safe. Otherwise `exception_type` plus traceback in `exception`. |

### Enforcement
1. A structlog processor redacts by key name (`password|token|secret|authorization|cookie|api_key|signature|aadhaar|pan|account_number|ifsc|photo|image`) and by value pattern (JWT `eyJ…`, `X-Amz-Signature=`, 12-digit Aadhaar, PAN regex). Replace with `[REDACTED]`.
2. Log `route_template`, never raw paths.
3. A CI test runs a representative request set with sentinel secrets and asserts absence.
4. The same rules apply to frontend and mobile diagnostics. No tokens, payloads or employee data go to the console or local buffers.

### Log types
| Type | Content | Store |
|---|---|---|
| Operational | `http_request`, task events, errors | stdout → Docker → (later) aggregator; short retention |
| Security | `security.*` events | same stream now, filterable by prefix; longer retention once centralised |
| Business audit | who changed what | Postgres `audit_log`, immutable and redacted. **Not** replaced by logs. |

---

## I. Observability Cost and Tooling

| Tier | Components | Cost | Setup | Maintenance | Privacy / residency | Fit for the Hostinger VPS |
|---|---|---|---|---|---|---|
| **Minimal (recommended first)** | JSON stdout + Docker json-file (exists) · external uptime monitor (UptimeRobot/Better Stack free tier, or self-hosted Uptime Kuma container) on `/health/ready` · host cron script (disk, memory, unhealthy containers, backup FAILED, Beat heartbeat, Redis `LLEN default`/`reports_exports`, error-count from `docker logs --since 5m \| jq`) sending to an email/chat webhook | ~0 | 1–2 days | Low | Logs stay on the VPS. Only health status leaves. | ✅ |
| **Intermediate** | + Grafana Loki + Promtail/Alloy (or Vector) on the same VPS, ~0.5–1 GB RAM · `prometheus-client` `/metrics` (internal network only) + Prometheus + Grafana · Alertmanager | VPS resources only | 3–5 days | Medium (upgrades, disk for TSDB/Loki) | Self-hosted; data stays in region | ✅ if the VPS has ≥ 4 GB RAM headroom; verify |
| **Advanced** | + OpenTelemetry tracing (Tempo/Jaeger) · Sentry (self-hosted is heavy, about 8 GB+ RAM; SaaS sends stack traces and context to a third party) · mobile crash reporting (Firebase Crashlytics/Sentry) | SaaS $ or significant RAM | 1–2 weeks | High | SaaS needs a DPA, data-residency review, and scrubbing (§H) **before** enabling. Crashlytics = Google. | Defer until traffic/team size justifies it |

**Recommendation:**
- **Do Minimal in Phase 4.** Re-evaluate Intermediate after the payroll pilot, and only if incident volume or debugging time justifies it.
- Do not add Sentry or Crashlytics until the privacy review in §O decision D3 is done.
- OpenTelemetry tracing is not justified for a single-VPS modular monolith. The request ID plus Celery header propagation gives the same correlation for much less effort.

---

## J. Monitoring and Alert Matrix

These thresholds are **starting points**. Calibrate each against two to four weeks of observed baseline in staging and pilot. Notification targets are placeholders until §O decision D1 is made.

| Signal | Trigger (starting point) | Severity | Notification Target | First Response |
|---|---|---|---|---|
| API readiness | `/health/ready` non-200 for 3 consecutive 1-min checks | Critical | On-call (chat + email) | Read `readiness_failed` event → check `docker compose ps`, Postgres/Redis containers |
| API liveness / container unhealthy | `docker ps --filter health=unhealthy` non-empty for 5 min | Critical | On-call | `docker compose logs --tail=200 <svc>`, restart service, capture logs first |
| HTTP 5xx rate | Nginx `status>=500` above max(5/5 min, 2% of requests) | High | On-call | Group by `route_template`/`error_code` in API logs; correlate by request_id |
| Unhandled exceptions | Any `unhandled_exception` or `level=error` in API logs, 5-min window, excluding known noise | High (first occurrence) | Dev channel | Find the traceback by request_id; open an issue |
| DB connectivity | `db_error` with connection SQLSTATE class 08 ≥ 3 in 5 min, or readiness `database:error` | Critical | On-call | Check Postgres container, disk, `max_connections` |
| DB contention | `DATABASE_BUSY` responses > baseline × 3 for 15 min | Medium | Dev channel | Check long transactions (`pg_stat_activity`), running sweeps |
| Auth infrastructure | `RATE_LIMITER_UNAVAILABLE` ≥ 1 | Critical (login is down) | On-call | Redis container health and memory |
| Credential attack | `security.login_failed` > 50 / 10 min from one IP, or `account_locked` > 10 / hour | Medium | Security owner | Review IPs; consider an Nginx deny |
| Refresh reuse | `security.refresh_token_reuse_detected` ≥ 1 | Medium | Security owner | Contact the affected user; review sessions |
| Integrity | `DECRYPTION_FAILED` / `UNKNOWN_KEY_VERSION` / `MALFORMED_CIPHERTEXT` ≥ 1 | Critical | On-call + security owner | Stop key rotation; check the `encryption_keys` table |
| Worker unavailable | `celery inspect ping` fails 3× or the worker container is unhealthy | Critical | On-call | Restart the worker; check broker |
| Beat missed | Heartbeat key age > 15 min | High | On-call | Restart Beat; check for a double instance |
| Queue backlog | `LLEN default` > 100 for 15 min, or any `reports_exports` message older than 10 min | High | Dev channel | Check worker concurrency, stuck tasks |
| Stuck import | Batch PENDING/PROCESSING > 30 min | Medium | Dev channel | Inspect batch, worker logs by task_id |
| Task failures | `celery_task_failed` ≥ 3 for the same task in 1 hour, or any failure of `employee.*`/`attendance.run_daily_calculation` | High | Dev channel | Traceback by task_id; re-run idempotent task |
| Partial runs | Any `*_incomplete` event (attendance, accrual, year-end) | High before payroll cut-off, else Medium | Payroll/HR ops + dev | Re-run for the company; fix failing employees before period close |
| Email failures | `email_send_failed` ≥ 5 in 15 min, or outbox `FAILED_PERMANENT` ≥ 1 | High | Dev channel | Check provider status and credentials; resend from outbox |
| Object storage | `storage_operation_failed` ≥ 3 in 5 min | High | On-call | MinIO container and disk |
| Payroll finalization | Any 5xx on payroll finalize/approve routes | Critical | On-call + payroll owner | Do not retry blindly; verify pay-run state by its ID |
| Backup | `backup.log` lacks a `SUCCESS` line in the last 26 h, or contains `FAILED` | High | Ops owner | Run the script manually; check disk |
| Disk | Root or Docker volume > 80% (warn), > 90% (critical) | High/Critical | On-call | `docker system df`, prune images, check backups |
| Memory | Host available < 10% for 10 min, or OOM-kill in `dmesg` | High | On-call | Identify the container; adjust concurrency/limits |
| TLS | Certificate expiry < 14 days | Medium | Ops owner | Check certbot container logs |

---

## K. Test Plan

### Existing coverage (verified)
| Test | Proves | Limitation |
|---|---|---|
| `tests/unit/core/test_unhandled_exception_logging.py` | catch-all logs with traceback; client gets a clean 500 | bare app, so it misses LOG-01 |
| `tests/unit/core/test_celery_task_failure_logging.py` | `task_failure` emits an event | uses `capture_logs`; does not prove the JSON format or traceback |
| `tests/unit/core/test_db_error_handler.py`, `test_db_wait_timeout_handler.py`, `tests/integration/test_db_wait_timeouts.py` | status mapping | no logging assertions |
| `tests/unit/modules/health/test_router.py` | live/ready status codes | — |
| `tests/unit/core/test_audit_redact.py` | audit masking | logs not covered |
| `tests/security/test_security_headers.py`, `tests/unit/core/test_cors_middleware.py`, `test_proxy_headers.py` | headers on normal responses | not on the catch-all 500 |
| `tests/integration/auth/test_auth_security.py::test_refresh_token_rotation` | rotation | **asserts the defective behavior (TXN-01)** |
| `apps/web/src/lib/api/client.test.ts` | API client mapping | no request-ID fallback |
| `apps/mobile/test/*` (27 files) | screens and parsing | not run in CI; no timeout or error-handler tests |

There is no test that references `X-Request-Id`. No test asserts that secrets are absent from logs.

### Proposed tests (each states its invariant)
Assertions use structured fields (`event`, `level`, `request_id`), not message wording. Capture through `capfd` with JSON parsing, the established pattern in this repo, because structlog's `cache_logger_on_first_use` defeats `capture_logs()`. Alternatively, add a test-only `configure_logging(cache=False)`.

| ID | Test | Invariant |
|---|---|---|
| T1 | Request ID absent → generated UUID appears in header, envelope, log and audit row | every request is correlatable |
| T2 | Valid client ID propagates end to end through `create_app()` | client and server correlation |
| T3 | Invalid or over-long ID is replaced; login with a 65-char ID → 200 | client input cannot break audited writes (LOG-05) |
| T4 | Injected unhandled error via `create_app()` → one ERROR event with traceback; body/header request_id equal; ACAO present; no traceback in body | LOG-01 |
| T5 | 5xx `AppError`, generic `DBAPIError`, wait-timeout → exactly one event at the right level; sentinel bind parameter absent | LOG-02, LOG-08 |
| T6 | 4xx `AppError` → no ERROR-level event | expected errors are not crashes |
| T7 | Refresh reuse → newest token rejected; rows revoked; security event emitted | TXN-01 |
| T8 | Every registered task's queue is consumed by the production worker command (parse compose or assert `task_routes` ⊆ consumed queues) | PRA-04 |
| T9 | Worker process emits JSON with `service=worker`; failure event has a traceback | LOG-03 |
| T10 | Sentinel onboarding token and `X-Amz-Signature` absent from all log lines for a public request | LOG-04 |
| T11 | Redaction processor masks keys and patterns (unit, table-driven) | §H |
| T12 | Sender raising `RuntimeError` → request succeeds, one WARNING, no email address in it | LOG-06 |
| T13 | 6 bad logins → `login_failed`×5 + `account_locked`, no password or email | LOG-07 |
| T14 | `insert_document` failure after `put_object` → object deleted or orphan event with key | LOG-09 |
| T15 | Storage stub slower than the timeout → classified error before gunicorn timeout | LOG-16 |
| T16 | Logging failure (a processor raises) does not fail a punch or leave write. Wrap the sink so logging errors are swallowed and counted. | logging cannot corrupt business ops |
| T17 | All tasks declare `time_limit`; idempotent tasks `acks_late` | LOG-10 |
| T18 | Fan-out with one `.delay()` failure dispatches the rest | LOG-10 |
| T19 | Partial attendance or accrual run writes a summary with `failed>0` | LOG-11 |
| T20 | Beat heartbeat stale → reported not-OK | LOG-12 |
| T21 | Readiness with Redis down → 503 and one `readiness_failed{dependency:redis}` | LOG-12 |
| T22 | Outbox: provider down → row retried with bounded attempts → `FAILED_PERMANENT`; no duplicate on success | Phase 2 |
| T23 | Web: throwing component renders the `error.tsx` fallback with reference | LOG-13 |
| T24 | Web: 500 without JSON body → `ApiError.requestId` equals the sent ID | LOG-13 |
| T25 | Web: failed employee fetch on departments shows an error state, not 0 | LOG-14 |
| T26 | Mobile: dio timeout → `NetworkError`; snackbar shows reference | LOG-15 |
| T27 | Mobile: `FlutterError.onError` captures to buffer without token or image bytes | LOG-15 |
| T28 | Retry policy bounded: autoretry stops at `max_retries`, then failure event | Phase 2 |
| T29 | Log rotation: compose `x-logging` present on every service (static config test) | §I |

### Commands (once implementation is approved)
```bash
cd apps/api && uv run ruff check . && uv run mypy src/hrms && uv run lint-imports
cd apps/api && uv run pytest tests/unit -q
cd apps/api && uv run pytest tests/integration tests/security -q
cd apps/api && uv run pytest -q -k "request_id or logging or redact or readiness or task_failure or reuse"
cd apps/web && npx tsc --noEmit && npx vitest run
cd apps/mobile && flutter analyze && flutter test
docker compose -f docker-compose.prod.yml config --quiet
```
Integration tests need the local Postgres (5433), Redis (6380) and MinIO, as in CI.

---

## L. Implementation Order

**Mandatory production blockers. Do these first, in this order:**
1. **TXN-01** (security control is broken; smallest diff).
2. **LOG-01 + LOG-05** together (one middleware rewrite).
3. **LOG-02** + `hide_parameters` (depends on 2 for the request ID).
4. **PRA-04** (one-line compose change and a test).

**Required before pilot / payroll go-live:**

5. LOG-03 (worker JSON).
6. LOG-04 (tokens in logs).
7. LOG-07 (security events).
8. LOG-06 (email swallow).
9. LOG-12 + Phase 4 minimal alerting: uptime, disk, backup, Beat heartbeat, queue depth, `*_incomplete`.
10. LOG-11 (partial-run visibility before payroll period close).
11. LOG-10 (task limits and fan-out isolation).
12. LOG-13 / LOG-15 (client error boundaries, timeouts, reference display).

**Recommended improvements:** LOG-08 full redaction processor, LOG-09, LOG-14, LOG-16, LOG-17, email outbox, mobile CI, face-punch idempotency.

**Optional tooling:** Loki/Grafana, Prometheus `/metrics`, Sentry/Crashlytics (after the privacy review), OpenTelemetry (not recommended at current scale).

---

## M. Unverified Items

| Item | Why unverified | How to verify |
|---|---|---|
| Exact gunicorn and uvicorn output for the duplicate "Exception in ASGI application" in production | Did not run gunicorn | Staging: trigger a 500 and read `docker logs api` |
| Whether Nginx's `/var/log/nginx/access.log` → stdout symlink still applies with the custom `nginx.conf` | Image detail | `docker compose exec nginx ls -l /var/log/nginx` |
| Server-side duplicate-punch protection for face punches retried after a client timeout | Not traced in full | Read `PunchService` dedup and run a double-submit integration test |
| Storage failure behavior under a real MinIO outage (error type and latency) | No fault injection | Staging: stop MinIO during upload and download |
| Real email provider rejection codes and latency | Must not send real email | Provider sandbox / Mailtrap test inbox |
| VPS memory and disk headroom for the Intermediate tier | No host access | `free -m`, `df -h`, `docker stats` on the VPS |
| Baseline traffic, 5xx rate and queue depth for alert thresholds | No production data | Two to four weeks of Minimal-tier data |
| Celery Redis `visibility_timeout` vs the longest `acks_late` task (1800 s < default 3600 s; looks fine) | Config default reasoning only | Confirm in staging with a long task and a worker kill |
| Mobile release-build behavior of uncaught errors on Android and iOS | Needs devices | Device test after Phase 3 |
| Other "write then raise" sites besides TXN-01 | Pattern sweep not exhaustive | Phase 1 task 8 |
| Behavior of the uncommitted employee-documents code once committed | Work in progress | Re-check LOG-09 after it lands |

---

## N. Acceptance Criteria

Implementation is complete when every item below has been demonstrated, with test or log evidence attached to the completion report:

1. **Correlation.** Every API response carries a valid `X-Request-Id`, including catch-all 500s, 413s and 429s. The same ID appears in the envelope, every log event for that request, audit rows, and Celery events for tasks dispatched by it (T1–T4).
2. **No silent 5xx.** Every 5xx response produces exactly one ERROR or WARNING event with `error_code`/`exception_type` (T4, T5).
3. **No leaks.** No password, token, signed URL, bind parameter, email address or document/biometric content appears in any log line in the sentinel test suite (T10, T11, T12, T13). No client response contains a traceback, SQL or provider text.
4. **Security controls work and are visible.** Refresh-token reuse revokes the family, and reuse, lockout and rate-limit trips emit `security.*` events (T7, T13).
5. **One format.** API, worker and Beat emit JSON with `service` and `environment` (T9).
6. **Background jobs.** Every task has a time limit. Every declared queue is consumed. Partial runs are recorded and alertable. Beat liveness is observable (T8, T17–T21).
7. **Clients.** Web and mobile show a reference ID on unexpected or network errors. Web has route and global error boundaries. Mobile has timeouts and global handlers (T23–T27).
8. **Operations.** Each Critical/High alert in §J has been triggered once in staging and its notification received. Disk, backup and certificate checks are scheduled. The runbook explains how to look up a request ID.
9. **Regression.** Full API, web and mobile suites are green in CI, and the mobile job has been added.
10. **Docs.** `PRODUCTION_DEPLOYMENT.md` §15/§16 match reality. The retention policy is written and approved.

---

## O. Final Verdict

### **PLAN COMPLETE — READY FOR IMPLEMENTATION** (Phases 0–1). Phases 2–4 have open decisions.

Phase 0 and Phase 1 have no unresolved decisions and can start as soon as they are authorized. These decisions are needed before the later phases and do not block Phase 0:

| ID | Decision | Blocks |
|---|---|---|
| D1 | Alert destination and on-call owner (email / Telegram / Slack; who responds out of hours) | Phase 4 |
| D2 | Log retention periods for operational and security logs, given applicable Indian data-protection obligations (DPDP Act 2023) and client contracts. **Legal/compliance input needed. This plan does not invent one.** | Phase 4 |
| D3 | Whether any third-party error or crash service (Sentry SaaS, Crashlytics) is acceptable, including the DPA and data-residency review | Phase 3/4 optional tier |
| D4 | Email outbox (durable, retried) vs. keeping best-effort direct send | Phase 2 |
| D5 | Whether a job-run summary is a hard precondition for payroll period close | Phase 2 (LOG-11) |
| D6 | Long-term: move public tokens out of URL paths (client-compatibility change) | Optional, after LOG-04 masking |

*End of plan. No implementation has been started.*
