# Error Handling — Target Architecture

Date 2026-11-25. Design only; nothing implemented. Principle: **extend what exists** (`AppError` + envelope + `request_id` + redacted structlog + platform log viewer). Do not introduce a second error system.

## 1. Error classes → behaviour

| Class | HTTP / signal | Backend today | User sees | Developer sees |
|---|---|---|---|---|
| Validation | 422 `REQUEST_VALIDATION_ERROR`/domain code + `details[field]` | ✔ exists | field-level messages | nothing logged (4xx) |
| Business rule | 4xx `AppError` with curated message | ✔ | the actual restriction | not logged unless 5xx |
| Authentication | 401 `UNAUTHORIZED`/`INVALID_TOKEN`; 423 locked | ✔ | "session expired / sign in" | security event |
| Authorization | 403 | ✔ | generic "no permission" | — |
| Not found / conflict | 404 / 409 | ✔ | clear message | — |
| Rate limit | 429 + `Retry-After` | ✔ | "try again in N s" | counter |
| Network (client) | status 0 `NETWORK_ERROR`/`OFFLINE`/`REQUEST_TIMEOUT` | ✔ web+mobile | connection message; writes: "may not have saved" | client report (new) |
| Unexpected exception | 500 `INTERNAL_ERROR` | ✔ | generic + reference | traceback, request id, route, user/company |
| Database failure | 503 `DATABASE_BUSY` (retryable) / 500 / 409 / 422 | ✔ | busy or generic | `sqlstate`, driver class, traceback |
| Third-party failure | 502/503 `AppError` w/ fixed message | ✔ | generic "service unavailable" | `cause_type`, WARNING |
| Background job failure | task status + `celery_task_failed` | ✔ logging; status messages fixed | "processing failed" (no detail) | task, task_id, retries, category |
| Critical system failure | 500/503 + metrics/alerts | partial | generic | alert (new, see §5) |

Rule: generic text applies only to the bottom five rows. Rows 1–7 keep their specific, useful wording.

## 2. Reference ID

Use the existing **`request_id`** as the single correlation key. Changes (small):
- For any 5xx the server sets `error.request_id` to a *server-generated* id (ignore the client-supplied value for the displayed reference only; the log still carries both).
- Define display form `ERR-` + first 8 hex chars of that id; clients show `ERR-1A2B3C4D`; support types it into the log viewer filter, which matches the prefix.
- Do not create a separate error table. One request ≈ one reference; a job failure uses `task_id` the same way.
- Envelope stays backward compatible (add optional `error.reference`; keep `request_id`). Illustrative:

```json
{"error":{"code":"INTERNAL_ERROR","message":"Something went wrong. Please try again later.",
          "request_id":"<uuid>","reference":"ERR-1A2B3C4D","details":[]}}
```

## 3. Backend

1. **Keep** `RequestContextMiddleware` as the outermost catcher and `register_exception_handlers`.
2. **Guard 5xx messages:** `AppError.public_message` class attribute; handler uses it for `status_code >= 500` (EH-B-02). Add a unit test enumerating all 5xx subclasses.
3. **Never persist raw exception text** in business data (EH-B-01). Add a tiny helper `safe_public_failure(exc) -> (code, message)` for "record failure as data" cases, used by import now and by future batch features.
4. **Celery task base class** (opt-in): transient-category autoretry with backoff for idempotent tasks (pattern from `leave/tasks.py`), explicit `no-retry` for non-idempotent; failure signal already logs. Add `dead-letter` visibility = existing `celery_task_failed` log + metric.
5. **No silent `pass`:** ruff rule `S110`/`BLE001` review; replace with `safe_log(warning)` (EH-B-06).
6. **Redaction tweaks** (EH-S-01/02): remove `_reason` from the safe list or content-scan it; add Aadhaar-12 and account-number patterns.

## 4. Developer observability

Decision needed (see Execution Gate): three options, in recommended order.

| Option | What | Pros | Cons |
|---|---|---|---|
| **A (recommended first)** — client error beacon into the existing logs | `POST /v1/client-errors` (authenticated or pre-auth with tight limits), body: `source` (web/mobile), `kind` (render/unhandled/network), `message_class`, `stack_top_frames`, `route`, `app_version`, `request_id` of last failed call; server **redacts with the same `redact_event`**, rate-limits per IP/user, logs `client_error` event (ERROR) with user/company from the token. Show in the existing platform log viewer. | No new vendor, no data leaves VPS (consistent with the recorded decision), reuses redaction & retention, 1–2 days of work | No grouping/alerting; you search logs |
| **B** — self-hosted GlitchTip (Sentry-compatible, open source, runs in Docker beside the app) | SDKs for Next.js, Flutter, FastAPI, Celery; grouping, counts, first/last seen, resolve state, alerts; `before_send` scrubbing | Answers "recurring? how many users? resolved?" | New service to run/patch (Postgres + Redis + worker, ~1 GB RAM), needs scrubbing review, still needs a decision memo |
| **C** — hosted Sentry | same | least ops | employee data leaves VPS; conflicts with the recorded "not added" decision; needs data-protection sign-off |

Recommendation: ship **A** now; revisit **B** once you want grouping/alerting. Keep the beacon payload schema stable so a later swap to GlitchTip is mechanical.

Developer workflow with A: user quotes `ERR-1A2B3C4D` → platform log viewer / `grep` by prefix → one `unhandled_exception` (backend) or `client_error` (device) record with traceback/frames, route, user_id, company_id, trace_id, Celery `task_id` if any.

Add a **default-on** alert for `hrms_errors_total{type="http_unhandled"}` rate (the Prometheus overlay exists but is not started by default — start it or alert from `hrms_monitor.sh`).

## 5. Web

- `ApiErrorState` (single component): chooses message/title/reference/retry from `ApiError` category (validation → inline; 403 → access restricted; 0 → connection; ≥500 → generic + `ERR-…`). Replace ~50 direct `error.message` call sites (EH-W-03).
- `describeApiError`: non-`ApiError` → generic fixed string (EH-W-01).
- Global reporter in root layout: `window.addEventListener('error'|'unhandledrejection')` + `RouteError` effect → `reportClientError()` (Option A). Strip message content to class name + top frames; never include props/state/form values.
- Add a reusable `<SectionBoundary>` class component for heavy widgets (charts, calendar) so one widget failing doesn't replace the page.
- Fallback wording: replace `Request failed with status N` with "Something went wrong. Please try again." (EH-W-04).
- Keep: timeouts, offline handling, 401 single-flight refresh, `global-error.tsx`.

## 6. Mobile

- Persist `AppDiagnostics` ring buffer (small file) and flush to `/v1/client-errors` when online; sampling + cap (e.g. 20 per day). Include app version/build, OS, route name.
- Use `describeApiError` everywhere (add lint/grep test against `e.message` in widgets), same reference format.
- Replace the 40 `catch (_) {}` with `AppDiagnostics.recordHandled(source, error)` (no UI).
- Keep release `ErrorWidget.builder` generic; add a "Copy diagnostics" row under Profile/Help using the existing `summary()` (EH-M-01).
- Wrap the `FlutterError.onError` release path so the error is still reported (currently only `kDebugMode` presents it).

## 7. Shared vs separate

| Shared (one definition) | Per-platform |
|---|---|
| Envelope + `reference` field, error-code catalogue, display strings table (single JSON/Markdown spec), client-error payload schema | React `ApiErrorState`, boundaries, listeners; Flutter `StateMessage` mapping, diagnostics persistence; Celery base task |

## 8. Out of scope here

Payments, AI, resume parsing do not exist in this product; the architecture leaves a slot (third-party failure row) if they are added.
