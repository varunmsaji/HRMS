# Error Handling, Exception Management & Developer Observability — Comprehensive Audit

| | |
|---|---|
| **Date** | 2026-11-25 |
| **Mode** | Read-only audit. No source, config, schema or dependency was changed; nothing staged or committed. |
| **Git state at start** | Branch `test`, HEAD `de201a9`, 43 uncommitted entries belonging to the user's in-progress attendance work (untouched). The only new files from this audit are the six documents in this folder (untracked). |
| **Prior work** | `docs/audits/LOGGING_ERROR_HANDLING_*` (2026-10-13) already fixed LOG-01…LOG-08. This audit builds on it and does not re-report what it closed. |

## 0. Headline

The backend error architecture is **already mostly what you asked for**: every unexpected exception becomes one generic envelope (`{"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred","request_id":…}}`), the full traceback goes to server logs only, and logs are redacted. Web and mobile both have global fallbacks that refuse to print the raw exception message.

What is **missing** is mostly the *developer* half:

1. **One confirmed leak** of raw exception text to users (bulk employee import row errors) — `EH-B-01`.
2. **Frontend and mobile errors never reach the developer.** Web logs to the console only outside production; mobile keeps 20 entries in memory that nothing reads. A crash on a user's device is invisible to you — `EH-W-02`, `EH-M-01`.
3. **No error tracking** (no grouping, frequency, "is it recurring", resolved state, alerting). Logs are files plus a platform-admin log viewer — `EH-X-01`.
4. The user-facing "reference ID" is the request UUID (36 chars), shown on some screens but not others — `EH-W-03`.

**No Critical or High findings.** Highest severity is Medium. Counts: Medium 6, Low 8, Info/positive 6.

## 1. Application inventory (Phase 0)

| Component | Reality in this repo |
|---|---|
| Backend API | FastAPI, `apps/api`, 299 Python files, structlog JSON logging |
| Web | Next.js app router, `apps/web`, 381 `catch`/`.catch` sites, 111 files use `describeApiError` |
| Mobile | Flutter + Dio + Riverpod, `apps/mobile`, 237 Dart files, ~283 `catch (` sites |
| Workers | **Celery** (not RQ) + Redis, 31 task declarations, Beat scheduler |
| Data | PostgreSQL (RLS), Redis, MinIO/S3 |
| Integrations | Email (SMTP/Hostinger), FCM push, Face providers (Azure / CompreFace / open-source), no payment gateway |
| **Not present** | Payment processing, resume/PDF parsing, AI/LLM calls. Brief items on those are marked N/A; the nearest analogues (face verification providers, payroll runs) are audited instead. |
| Observability | `core/observability/*`: JSON logs → stdout + rotating files (`app.log`, per-module, `errors.log`), Prometheus metrics (optional compose overlay, not default), platform-admin log viewer `/v1/platform/logs/*` (access itself logged) |
| Prior decisions | `docs/architecture/OBSERVABILITY_ARCHITECTURE.md` explicitly records Sentry/Datadog as "Not added — vendor, data-protection review of employee data leaving the VPS". Web `route-error.tsx` and mobile `app_diagnostics.dart` repeat "no third-party error service has been approved". |

## 2. How an unexpected error travels today (traced end to end)

```
route/service raises Exception
  → RequestContextMiddleware (outermost ASGI, core/observability/request_context.py)
      → log_unhandled_exception(): ONE ERROR record, traceback, request_id, route template,
        verified tenant/user ids, error_category, metrics counter
      → unhandled_error_response(): 500 envelope, generic text, request_id
      → sent through the same CORS + security-header middleware (browser can read it)
  (fallback: @app.exception_handler(Exception) in handlers.py for apps built without middleware)
Other paths:
  AppError        → app_error_handler (handlers.py:141): message is shown as-is; 5xx also logged (LOG-02)
  RequestValidationError → 422 with field details
  HTTPException   → 5xx text replaced with generic; only a plain-string detail on 4xx is shown
  DBAPIError      → timeout/deadlock/serialization → 503 "busy" + Retry-After; unique → 409;
                    bad-input (SQLSTATE 22) → 422; everything else → generic 500, traceback logged
  PoolTimeout     → 503
Web:  apiClient.rawRequest → ApiError(status, code, message, requestId)
      page-level catch → ErrorState / toast / inline field errors
      uncaught render error → app/app/error.tsx | app/error.tsx | global-error.tsx (never prints message)
Mobile: Dio → ApiError / NetworkError → StateMessage / SnackBar
      uncaught → FlutterError.onError / PlatformDispatcher.onError → local AppDiagnostics (20 entries)
```

I confirmed these are actually wired (not just defined): `create_app()` registers `RequestContextMiddleware` last (outermost) and calls `register_exception_handlers(app)`; web boundaries are Next.js convention files so are invoked by the framework; mobile handlers are installed in `main()` before `runApp`.

## 3. Findings

Severity scale: Critical = remote exploitation or mass exposure; High = sensitive data or secrets reach end users; Medium = technical detail reaches users, or a significant blind spot; Low = hygiene/fragility; Info = positive or note.
"Confirmed" = I read the code path. "Potential" = depends on conditions I could not fully trace.

### Backend

#### EH-B-01 — Bulk import stores raw `str(exc)` and returns it to the user — **Medium, Confirmed**
- **File / function:** `apps/api/src/hrms/modules/employee_import/service.py` → `_record_row_error`, lines 565–596 (`message = str(exc)` at 584); caller catch-all at 409–411.
- **Current behaviour:** Each CSV row runs inside `except Exception`. `PydanticValidationError` and `AppError` are translated safely. Any *other* exception (a `DBAPIError`, `KeyError`, `TypeError`, a storage error mid-row) is stored verbatim as `error_message` in `employee_import_row_errors`, and returned by `GET /v1/employee-imports/{id}/errors` (`schemas.py:154,186`).
- **Problem:** For a `DBAPIError`, `str(exc)` includes the SQL statement text (table and column names; bound values are hidden by `hide_parameters=True`), the driver error and constraint names. This bypasses the generic-envelope guarantee because it is returned as *data* in a 200 response, not as an error. It is also *persisted*, so it is retrievable later and never goes through the log redaction processor.
- **Risk:** Schema disclosure to any authenticated user who can run imports (HR admin). Needs an authenticated user and a row that triggers a non-domain exception, so exploitability is low; impact is exactly the class you asked to eliminate.
- **Recommendation:** In the final `else` branch of `_record_row_error`, store a fixed message ("This row could not be imported. Reference: <request_id/short id>"), code `IMPORT_ROW_FAILED`, and log the exception once via `safe_log(..., exc_info=exc)` with `batch_id`, `row_number`. Keep the `AppError` and Pydantic branches (their text is curated). Backfill is not required unless existing rows contain such text — query `error_code='IMPORT_ROW_FAILED'` first.
- **Dependencies:** none. **Verification:** unit test injecting a `DBAPIError` and a `KeyError` into the row loop and asserting the stored text contains neither SQL nor exception text; an API test on `/errors`.

#### EH-B-02 — `AppError` messages are trusted with no guard — **Low (potential)**
- **File:** `core/errors/handlers.py` `app_error_handler` (line 141); `core/errors/base.py` `AppError`.
- **Current behaviour:** `exc.message` is returned unchanged for every status, including 5xx. I reviewed every 5xx `AppError` class (`core/crypto/errors.py`, `attendance/exceptions.py`, `employee_import/exceptions.py`, `shared/rate_limit.py`): all use fixed, safe text today.
- **Problem:** Nothing enforces it. A future developer writing `raise SomeError(str(exc))` on a 5xx class would leak with no test failing. Already-present risky pattern sites, all currently safe: `face_comparison_admin.py:193,201` (`f"…rejected the photo: {exc}"`; safe only because every `FaceProviderError` is a fixed string in the three providers), `face_service.py:223` (`LivenessImageError` fixed strings), payroll `service.py:673,954,1169,1325,1470,1546,1605,3774` (`BreakupError(ValueError)` curated text; the exception type at 3774 was not traced), `organisation/service.py:3001,3007`.
- **Recommendation:** In `app_error_handler`, when `status_code >= 500`, ignore the instance message and use a class-level `public_message` (default generic). Add a lint/test that greps for `AppError subclass(...str(` / `f"{exc}"` patterns.
- **Verification:** parametrised test over all `AppError` subclasses with `status_code>=500`: raise with a secret-looking message and assert it is absent from the body.

#### EH-B-03 — No explicit, short, user-quotable error reference — **Medium (UX/operational)**
- **Current:** The envelope carries `request_id` (UUID or a client-supplied id matching `REQUEST_ID_PATTERN`) and every response has `X-Request-Id`. Logs are keyed by it. This already achieves correlation.
- **Problem:** A 36-char UUID is hard to read out over the phone; a *client-supplied* id means the "reference" is not guaranteed unique/trustworthy; and there is no separate identifier per *error* (one request can in principle log several).
- **Recommendation:** Do **not** add a second ID system. Keep `request_id` as the single correlation key and add a derived display form (`ERR-` + first 8 hex of the server-generated id), always server-generated for 5xx. See Target Architecture §2.
- **Dependencies:** web + mobile display helper.

#### EH-B-04 — Failed background jobs: retry policy exists for one task family only — **Medium, Confirmed**
- **Evidence:** 31 Celery task declarations; `autoretry_for`/`retry_backoff`/`acks_late`/`max_retries` appear only in `modules/leave/tasks.py:55–61`; `self.retry(` appears nowhere. `employee_import/tasks.py` documents "no retry" deliberately (create-only pipeline) — that one is correct.
- **Good:** global `task_failure`, `task_retry`, `task_unknown`, `task_rejected` signal handlers log structured records with `task`, `task_id`, `retries`, `error_category` (no `str(exc)`); request id and trace id propagate from the API into tasks; fan-out publish failures are isolated per company.
- **Problem:** Attendance, digest, notification and reminder tasks have no explicit transient-vs-permanent classification; a transient DB blip fails the run until the next Beat tick. I did not read each of the 31 tasks to prove the consequence for each, so this is a *systemic gap*, not a per-task bug list.
- **Recommendation:** Task base class applying the Leave policy to transient exception categories already defined in `observability/classification.py` (`RETRYABLE_DB_CATEGORIES`) while excluding non-idempotent tasks (opt-in per task).

#### EH-B-05 — Job failure status visible to users — **Low, Confirmed (acceptable)**
- Import batches become `FAILED` with no message (`service.py:343–350, 185–200`) and the client receives `IMPORT_QUEUE_UNAVAILABLE` with fixed text. Good. Only the row-level leak (EH-B-01) violates the rule.

#### EH-B-06 — Silent swallow in face enrollment cleanup — **Low, Confirmed**
- **File:** `attendance/face_comparison_admin.py:269–273` `_discard` → `except Exception: pass`. A failed provider cleanup leaves an orphan provider-side person with zero log trace.
- **Recommendation:** `safe_log(warning, "face_shadow_discard_failed", **safe_error(exc))`.

#### EH-B-07 — `str(exc)` in an internal asset error — **Low (potential, untraced)**
- `attendance/opensource_face/embedding_service.py:133` `EmbeddingUnavailableError(str(exc))` wraps an `AssetError` that may name a model file path. I did not trace it to a response; `engine.py:135,149` re-wraps to a fixed `FaceProviderError("Face engine … failed.")`, so it is likely log-only. Needs a one-line check before closing.

#### EH-B-08 — Database failure semantics — **Info (positive)**
- Lock/statement timeout, deadlock, serialization → 503 + `Retry-After`; connection loss deliberately stays 500 because the COMMIT may have landed (prevents duplicate mutation); unique violation → 409; SQLSTATE 22 → 422. Tests: `tests/integration/core/test_db_failure_classification.py`, `test_request_context_and_error_logging.py`, `test_route_robustness.py` (hostile bodies/query/path ids never 500).

### Web

#### EH-W-01 — `describeApiError` returns `error.message` of any `Error` — **Medium, Confirmed**
- **File:** `apps/web/src/lib/api/errors.ts:116` (`if (error instanceof Error) return error.message;`). Used by 111 files for toasts and `ErrorState`.
- **Problem:** The route boundary (`route-error.tsx`) correctly refuses non-API messages, but this helper does not. A `TypeError: Cannot read properties of undefined (reading 'x')`, a `DOMException`, or a library message thrown inside a `try` would be shown in a toast. Today most callers pass `ApiError`, so frequency is unknown, but nothing prevents it.
- **Recommendation:** return the generic string for non-`ApiError`; log the original (see EH-W-02).
- **Verification:** extend `lib/api/errors.test.ts` with `describeApiError(new TypeError("secret"))` must not contain "secret".

#### EH-W-02 — Browser errors never reach the developer — **Medium, Confirmed**
- **Evidence:** `components/common/route-error.tsx:35` logs `console.error` only when `NODE_ENV !== "production"`; no `window.onerror` / `unhandledrejection` listener anywhere in `src/`; no component-level boundary (only Next route boundaries `app/error.tsx`, `app/app/error.tsx`, `global-error.tsx`; `/platform/**` falls back to `app/error.tsx`).
- **Problem:** A user hitting a render crash sees the nicely generic page with a digest/reference — but the *client-side* exception message and stack exist only in their browser. An unhandled promise rejection (very common in async handlers) produces no UI and no record at all. You cannot know it happened.
- **Recommendation:** Small client reporter + a rate-limited ingestion endpoint feeding the existing structured log pipeline (Target Architecture §4). No third-party vendor required.

#### EH-W-03 — Inconsistent support reference on page-level errors — **Low–Medium, Confirmed**
- ~50 pages render `error.message` directly into `ErrorState` (e.g. `app/app/overtime/page.tsx:192`, `me/page.tsx:131`, `users/page.tsx:216`, `departments/page.tsx:178`, `employees/page.tsx:416`, …) while `describeApiError`/`RouteError` append "Reference: <id>". For a 5xx the user sees "An unexpected error occurred" with **no** reference they could quote.
- **Recommendation:** one `<ApiErrorState error={…}>` that picks title/message/reference/retry by category; replace the 50 call sites mechanically.

#### EH-W-04 — Technical fallback strings — **Low, Confirmed**
- `lib/api/client.ts:184` `Request failed with status ${status}` and `:84` `Authentication required` appear when the body has no envelope (non-502/503/504, e.g. a proxy 500/413/429 page). Exposes a status code only; low risk but off-brand and inconsistent with the generic wording.

#### EH-W-05 — Silent catches — **Low, Confirmed**
- `.catch(() => {})` at `app/app/onboarding/page.tsx:125`, `employees/page.tsx:150`, `components/employee/employee-side-cards.tsx:48,61,65`, `attendance/[id]/page.tsx:124–156`, `notifications/use-open-notification.ts:28`, `layout/employee-top-bar.tsx:37`. Mostly secondary lookups where degrading silently is right for the *user*, but there is no record for the *developer*.

#### EH-W-06 — Client-side positives — **Info**
- Timeouts (30s/120s), offline vs timeout vs unreachable distinguished, "write may or may not have been saved" wording, single-flight cross-tab refresh with replay-safe handling, 401 → clear session + notify, `isRetryableError` only for reads. `global-error.tsx` shows no message. Tests: `lib/api/client*.test.ts`, `errors.test.ts`, `route-error.test.tsx`.

### Mobile

#### EH-M-01 — Diagnostics are local-only and unreachable — **Medium, Confirmed**
- **Files:** `apps/mobile/lib/core/diagnostics/app_diagnostics.dart`, `main.dart:58–90`.
- `AppDiagnostics` holds 20 entries in memory; `summary()` (line 96) **has no caller anywhere in `lib/`** — there is no "copy diagnostics" screen — so the data is neither shown to the user nor sent anywhere, and is lost on restart. Net effect: mobile crashes are unobservable. (The code comment says the intent was a user-copyable block; the UI half was never built.)
- **Recommendation:** same reporter as web (Target Architecture §4) + a persisted ring buffer; optionally add a Settings → "Copy diagnostics" row.

#### EH-M-02 — Empty `catch (_) {}` blocks — **Low–Medium, Confirmed**
- 40 occurrences in `lib/` (e.g. `core/resource/resource_screens.dart:231,238`, `core/requests/request_screens.dart:83,168`, `features/attendance/presentation/rosters_screen.dart:86`, `geofences_screen.dart:87`, `face_liveness_capture_screen.dart:140`). No log, no diagnostics entry.

#### EH-M-03 — Mixed use of `e.message` vs `describeApiError` — **Low, Confirmed**
- Most screens display `ApiError.message` (curated server text) and fall back to the fixed "Something went wrong." for non-API errors — good (no `e.toString()` reaches UI; I found none). But many (`request_screens.dart:374,394`, `rosters_screen.dart:132`, `async_list_screen.dart:91`, `shift_board_screen.dart:56`, …) omit the support reference that `describeApiError` adds, mirroring EH-W-03.
- `api_client.dart:183` has the same `Request failed with status` fallback as web.

#### EH-M-04 — Mobile positives — **Info**
- `FlutterError.onError` and `PlatformDispatcher.onError` both installed; release `ErrorWidget.builder` shows fixed text (no grey box/stack); timeout/network distinguished with the same wording as web; camera/liveness failures map to fixed strings (`face_liveness_capture_screen.dart`). `test/core/api_error_handling_test.dart` covers timeouts, proxy 502, request-id precedence and diagnostics bounds.

### Security / logging (details in the Security report)

- **EH-S-01 (Low, potential)** — redaction key allow-list `_SAFE_KEY_SUFFIXES` includes `_reason`; a free-text `leave_reason`/`rejection_reason` containing health information would be logged unredacted. (`redaction.py:58`)
- **EH-S-02 (Low, confirmed)** — value patterns cover email, 10-digit Indian mobile, PAN, JWT, bearer, URLs; **not** 12-digit Aadhaar, bank account numbers or person names appearing inside free text/tracebacks (`redaction.py:68–118`). Mitigated by key-name masking and by the policy of never logging `str(exc)`.
- **EH-S-03 (Low, confirmed)** — `log_retention_days` defaults to `0` (`settings.py:113`); I did not verify in `file_sink.py` whether 0 means "keep forever". Decide and document the retention for logs that contain tracebacks.

### Cross-cutting

#### EH-X-01 — No error tracking layer — **Medium, Confirmed**
Question-by-question against your list: *which error / where / which endpoint / module / frontend-vs-backend* — **answerable** from `errors.log` and the log viewer for the backend only. *Recurring, how often, how many users affected, resolved?* — **not answerable**: no grouping/fingerprinting, no counters per error signature in the UI, no status. Prometheus has `hrms_errors_total` style counters but the monitoring compose overlay is **optional and not started by default**. Frontend/mobile: not answerable at all (EH-W-02, EH-M-01).

## 4. What I did not inspect (no claim of complete coverage)

- I pattern-swept all of `apps/api/src`, `apps/web/src` and `apps/mobile/lib` for `str(e)/repr/traceback/except Exception/pass`, `.message`, `catch (_)`, `$e`, `toString()`, but **did not read every module's service flow line by line** (299 + 381 + 237 files). Modules read in depth: error handlers, middleware, logging/redaction, Celery wiring, employee import, face provider wrapping, health, platform log router, web API client and boundaries, mobile API client and diagnostics.
- The 31 Celery tasks were counted and retry config searched, not each read individually.
- `infra/monitoring/hrms_monitor.sh` and nginx error pages: existence confirmed, content not audited (no `error_page`/`proxy_intercept_errors` matches in `infra/nginx`, so nginx's own default HTML error pages would show for gateway failures that bypass the API — the clients handle 502/503/504 bodies gracefully, but this is unverified in a browser).
- Web `try/catch` sites (381) were sampled by pattern, not individually read.
- No runtime tests were executed (read-only audit; no server started).
