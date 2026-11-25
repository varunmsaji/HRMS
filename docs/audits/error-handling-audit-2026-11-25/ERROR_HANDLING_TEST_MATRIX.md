# Error Handling — Test & Verification Matrix

Date 2026-11-25. **Existing** = I found a test that covers it (not executed in this audit). **GAP** = no test found by search. "N/A" = capability does not exist in this product.

Evidence of existing tests: `apps/api/tests/integration/core/test_request_context_and_error_logging.py`, `test_db_failure_classification.py`, `test_http_access_event.py`, `test_token_path_redaction.py`, `tests/integration/test_route_robustness.py`; `apps/web/src/lib/api/client.test.ts`, `client-cross-tab.test.ts`, `errors.test.ts`, `components/common/route-error.test.tsx`; `apps/mobile/test/core/api_error_handling_test.dart`, `token_refresh_test.dart`, `punch_idempotency_test.dart`.

| # | Scenario | User should see | Developer should see | Log | Retry? | Data consistency | Leak check | Coverage |
|---|---|---|---|---|---|---|---|---|
| 1 | Unexpected backend exception | Generic message + `ERR-…` | traceback, route template, user/company, request id | 1 × ERROR `unhandled_exception` | Client may retry reads only | Request transaction rolled back by `get_session` | body contains no exception text | **Existing** (middleware tests); add explicit "secret string in exception not in body" |
| 2 | DB connection failure | Generic 500 (conn loss) | `sqlstate`, driver class, traceback | ERROR `db_error` | **No auto-retry** for writes (COMMIT may have landed) | Unknown commit outcome → idempotency keys | no SQL in body | **Existing** (classification tests) |
| 3 | DB transaction failure (deadlock/serialization/lock timeout) | "System busy, try again" 503 | category, WARNING | WARNING | Yes (`Retry-After: 2`) | Rolled back | none | **Existing** |
| 4 | Third-party API timeout (face provider/email/FCM) | Generic "temporarily unavailable" | `cause_type`, provider, outcome | WARNING `email.delivery.failed` / `app_error` | email outbox retry per class; face: user retries | no partial enrollment (cleanup `_discard`) | message fixed strings | Partial — **GAP**: face provider timeout → body test; `_discard` failure logged (EH-B-06) |
| 5 | Third-party returns error | same as 4 | provider status class | WARNING | by `retryable` flag | same | provider body never echoed | **GAP** (add test that provider error text is absent from response) |
| 6 | Redis unavailable | 503 `RATE_LIMITER_UNAVAILABLE` (fail closed), `Retry-After: 5` | ERROR/WARNING, counters | WARNING | Yes | none | none | Existing for limiter (SEC-11) — **GAP** for Celery publish failure message (import path covered by `ImportQueueUnavailableError`) |
| 7 | Background worker crashes | Job status "failed/processing" generic | `celery_task_failed` + Celery traceback, `task_id`, request id | ERROR | per task policy (EH-B-04) | `acks_late` only for Leave; others may be lost | no error text in job status | **GAP** (worker kill/restart test) |
| 8 | Job retry exhaustion | "Could not be processed" | `retries`, category; final failure | ERROR once | — | batch → FAILED | none | **GAP** for Leave exhaustion; Import: closed as FAILED (code present, test not located) |
| 9 | Frontend component crash | Generic page + reference, nav intact | client report with top frames (new) | `client_error` | "Try again" button | none (UI only) | message never rendered | `route-error.test.tsx` **Existing**; client report **GAP** |
| 10 | Unhandled promise rejection | Nothing visible or toast "Something went wrong" | client report | `client_error` | — | — | no message | **GAP** (no listener exists) |
| 11 | Mobile widget failure | Fixed "This part of the screen could not be displayed" | diagnostics entry → report | — | back/retry | — | no stack | **GAP** (release ErrorWidget has no test located) |
| 12 | Mobile API request failure | `StateMessage` w/ retry; reference for 5xx | request id in diagnostics | server log by id | reads only | idempotency keys on punches | no `e.toString()` | **Existing** (`api_error_handling_test`, `punch_idempotency_test`) |
| 13 | Network disconnection | "Could not reach the server / offline" | — (client only) | — | auto for reads on reconnect (UI choice) | writes: "may or may not have been saved" | — | Existing web (`client.test.ts`) & mobile |
| 14 | Auth token expiry | silent refresh; else sign-in screen | `security.refresh_token_*` events | INFO/WARN | single-flight refresh | replay detection revokes family | no token in logs | **Existing** (`client-cross-tab`, `token_refresh_test`, identity tests) |
| 15 | Invalid permissions | "You don't have permission" | 403 logged at access level | `http_request` w/ `error_code` | no | none | no role/internal names | Existing broadly; add one shared FE test of mapping |
| 16 | File upload failure (oversize, storage down) | specific size/type message; storage down → generic | storage error class | WARNING/ERROR | user re-upload | batch FAILED, no partial | no bucket/path | Existing (`test_employee_import_upload_bounds`) — **GAP** storage-down body test |
| 17 | "AI" failure → face verification/liveness failure | fixed "Face check took too long…" / "temporarily unavailable" | provider class, liveness category | WARNING | user retries | no punch recorded on failure (fails closed) | fixed strings | Existing in face tests; **GAP** for provider-error text absence |
| 18 | Payment failure | N/A | | | | | | N/A (no payments) |
| 19 | Attendance processing failure | no-impact to user; status "calculation pending" | task failure record | ERROR | per-day idempotent recompute | idempotent per day | none | **GAP** (task-level failure test) |
| 20 | Payroll processing failure | pay run shows issue codes/curated messages; unexpected → generic | traceback | ERROR | manual re-run | pay run state machine; transaction rollback | `BreakupError` text curated | **GAP** for unexpected-exception path in pay-run |

## Tests that prove raw technical errors cannot reach production users (new)

1. **Backend sentinel test:** for every route in the OpenAPI schema (dev mode) with a dependency override raising `Exception("SENTINEL-sql SELECT * FROM x")`, assert response body has no `SENTINEL`, no `Traceback`, no `SELECT`, status 500, envelope shape.
2. **All 5xx `AppError` subclasses:** construct with sentinel message → body must not contain it (after Phase 2).
3. **Data-as-error test:** import with injected `DBAPIError`; `/errors` text has no SQL (EH-B-01).
4. **Static check (CI):** no `AppError(...str(`/`f"{exc}"` in `modules/`; no `e.toString()` in `apps/mobile/lib` widgets; no `.message` of non-`ApiError` in web components.
5. **Web:** vitest — `describeApiError(new Error("SENTINEL"))`; Playwright with network stub returning 500 without body → "Something went wrong" + reference, no "status 500".
6. **Mobile:** widget test with a throwing child under release `ErrorWidget.builder`; unit test for `describeApiError` with arbitrary `Exception`.
7. **Redaction tests** for Aadhaar-12, bank account, `*_reason` fields (after EH-S-01/02).
8. **Log-presence tests:** each scenario above emits exactly one ERROR with the reference id.
