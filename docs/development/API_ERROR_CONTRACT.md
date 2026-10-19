# API error contract

Authoritative description of how the HRMS API reports failures. Implementation:
`apps/api/src/hrms/core/errors/` (`base.py`, `auth.py`, `envelope.py`, `handlers.py`),
`core/observability/request_context.py`, `core/uploads.py`, `shared/rate_limit.py`.
Tests: `tests/unit/core/test_error_contract.py`, `test_db_error_handler.py`, `test_cors_middleware.py`,
`tests/integration/core/`.

The project already had an envelope (Document 09 §1.3). It was kept rather than replaced with
RFC 9457 Problem Details, because the Next.js and Flutter clients parse it today
(`apps/web/src/lib/api/errors.ts`, `apps/mobile/lib/core/api/api_error.dart`).

## Envelope

Every non-2xx response from the application — domain errors, validation, framework errors, upload
limits, rate limits, unhandled exceptions — has this body:

```json
{
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      { "field": "body.email", "code": "value_error", "message": "value is not a valid email address" }
    ],
    "request_id": "0b3f6c1e-…"
  }
}
```

| Field | Meaning |
| --- | --- |
| `code` | Stable, machine-readable, `UPPER_SNAKE_CASE`. Clients branch on this, never on `message`. |
| `message` | User-safe English text. May change; never contains SQL, paths, tokens, provider bodies, personal or biometric data. |
| `details[]` | Field-level (`field`, `code`, `message`, optional `context`). Always present, possibly empty. `field` is dotted (`body.name`) for schema validation and the bare name for service-raised errors; clients match on the last segment. |
| `request_id` | The same value as the `X-Request-Id` response header and every server log line for the request. Quote it to support. |

`X-Request-Id`: a caller-supplied value is used only if it matches `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`;
otherwise a UUID is generated (the request is never rejected for a bad id). It is echoed on every
response, including 4xx/5xx produced by middleware. CORS and security headers are present on error
responses too.

## Status codes and codes

| Status | When | Typical `code` |
| --- | --- | --- |
| 400 | Malformed request that is not schema validation | `BAD_REQUEST` |
| 401 | Missing/invalid/expired credentials, revoked session. Carries `WWW-Authenticate: Bearer` | `UNAUTHORIZED`, `INVALID_TOKEN`, `INVALID_CREDENTIALS` |
| 403 | Authenticated but not allowed (permission, data scope, unverified email) | `PERMISSION_DENIED`, `FORBIDDEN`, `EMAIL_NOT_VERIFIED` |
| 404 | Unknown route, or resource absent / not visible to the caller's tenant | `NOT_FOUND`, module `*_NOT_FOUND` |
| 405 | Wrong method. Carries `Allow` | `METHOD_NOT_ALLOWED` |
| 409 | State conflict, duplicate, stale `If-Match` version | `CONFLICT`, `DUPLICATE_RESOURCE`, `STALE_RESOURCE`, module codes |
| 413 | Upload/body over the limit | `PAYLOAD_TOO_LARGE` |
| 422 | Schema validation or business input rule failed; value not storable | `REQUEST_VALIDATION_ERROR`, `VALIDATION_ERROR`, `INVALID_VALUE`, module codes |
| 423 | Account locked | `ACCOUNT_LOCKED`, `LOCKED` |
| 429 | Rate limit. Carries `Retry-After` (seconds) | `RATE_LIMITED`, `FACE_ATTEMPTS_EXCEEDED` |
| 500 | Unexpected failure; generic text, traceback only in server logs | `INTERNAL_ERROR` |
| 502/504 | Upstream provider failure/timeout | module codes |
| 503 | Dependency unavailable or busy; **retry is safe** (`Retry-After` set) | `DATABASE_BUSY`, `RATE_LIMITER_UNAVAILABLE`, `IMPORT_QUEUE_UNAVAILABLE`, `ATTENDANCE_QUEUE_UNAVAILABLE` |

Framework-raised `HTTPException`s map to a code by status (`404 → NOT_FOUND`, `405 →
METHOD_NOT_ALLOWED`, …; unlisted statuses → `CLIENT_ERROR`/`SERVER_ERROR`). Their `detail` is shown
only if it is a plain string; for 5xx it is never forwarded.

Validation messages are the validator's own text (the Pydantic `Value error, ` prefix is removed).
Submitted values are never echoed.

Successful creates return `201`; deliberate empty successes `204`. A failed operation never returns 2xx.

## Retryability and idempotency

- **Safe to retry automatically (reads, or when the server says nothing was done):** `429` after
  `Retry-After`; `503` (`DATABASE_BUSY`, `*_QUEUE_UNAVAILABLE`, `RATE_LIMITER_UNAVAILABLE`) — the
  transaction was rolled back or never started.
- **Not retryable blindly:** a plain `500`, and a client-side timeout/no response on a write. A lost
  database connection is deliberately a `500`, not a `503`: the COMMIT may have landed. Clients
  (`timeoutError`, `NetworkError.timeout`) tell the user the outcome is unknown and do not resubmit.
- Punches, leave applications, imports, etc. accept an idempotency key where documented; a replay
  returns the original result rather than a second record.
- A `202`/queued response means *accepted for processing*, not completed. If the broker is
  unreachable the API answers `503` and records nothing as queued.

## Database errors

`DBAPIError`s that reach the global handler are translated, with details kept in server logs only:
lock/statement timeout, deadlock, serialization failure, pool exhaustion → `503 DATABASE_BUSY`;
unique violation (a race no service converted) → `409 DUPLICATE_RESOURCE`; value not storable
(SQLSTATE class 22) → `422 INVALID_VALUE`; anything else → `500 INTERNAL_ERROR`. Services should still
catch the `IntegrityError`s they anticipate and raise a specific domain code.

## Client expectations

1. Parse `error.code`, `error.message`, `error.details[]`, `error.request_id`; fall back to the
   `X-Request-Id` header and the HTTP status if the body is not an envelope (proxy-generated 502/504).
2. Show `details[].message` next to the matching field; show `message` otherwise.
3. Show the `request_id` as a support reference for network failures and `5xx` only.
4. Treat `401` as "re-authenticate" (one refresh attempt), `403` as "not allowed", `409` as
   "reload and retry", `422` as "fix input", `429`/`503` as "wait `Retry-After`, then retry reads".

## Verified status

Verified by automated tests: the envelope on `HTTPException`, 404/405, 401 `WWW-Authenticate`,
429/503 `Retry-After`, validation shape, DB-error mapping, queue-outage 503, 413, request-id handling,
CORS/security headers on 500. Not verified endpoint-by-endpoint: each module's domain codes (they
follow the `AppError` pattern but were not individually re-audited).
