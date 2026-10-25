# Error handling & recovery

Source of truth: `apps/api/src/hrms/core/errors/{base,handlers,envelope,auth,company}.py`, `shared/rate_limit.py`, `core/uploads.py`, `core/idempotency.py`; recorded behaviour in [examples/conventions-and-errors.md](examples/conventions-and-errors.md). The exhaustive generated list of all **315 error classes / 291 distinct codes** is [ERROR_CODES.md](ERROR_CODES.md); per-module vocabularies are at the top of each [modules/*.md](modules/).

## 1. The envelope
Every error the application itself produces has this shape (`ErrorEnvelope`):
```json
{ "error": {
    "code": "STALE_RESOURCE",             // stable, upper-snake; branch on this, never on message
    "message": "The company profile has been modified by another request",   // English, human-readable, safe to show
    "details": [ { "field": "version", "code": "STALE_RESOURCE", "message": "…", "context": { "current": { …resource… } } } ],
    "request_id": "47218734-c428-4a96-8e6b-d61b5a3709ee",   // = X-Request-Id response header; quote to support
    "documentation_url": null } }          // field exists; the server never sets it
```
* `details` is always an array (possibly empty). `details[].field` is `null`/empty for non-field errors.
* `message` is not localised and may change; `code` is the contract.
* 5xx messages are generic by design (`"An unexpected error occurred"`); internals never leak.

## 2. Not every failure uses the application envelope
The client must also survive these (all observed in code):

| Source | Looks like | When |
|---|---|---|
| Reverse proxy / load balancer | `502/503/504` with **HTML or empty body** | Upstream down or restarting. The Flutter client maps this to `SERVICE_UNAVAILABLE` when there is no `error` object. |
| Connection failure/timeout | no HTTP response | Offline, DNS, TLS, read timeout (outcome of a write is unknown). |
| `204 No Content` | empty body | logout, several DELETEs. |
| `GET /health/live` | `{"status":"ok"}` (no envelope) | health only. |
| CSV/binary responses | `text/csv`, image bytes | downloads; their errors, however, use the envelope with `Content-Type: application/json`. |
| Pre-parse upload rejection | envelope, but built by middleware (`code=PAYLOAD_TOO_LARGE`, 413, `details: []`) | body larger than the endpoint cap. |

Within the envelope there are **three different "validation" shapes** — branch on `code`:

| `code` | HTTP | Produced by | `details[].field` format |
|---|---|---|---|
| `REQUEST_VALIDATION_ERROR` | 422 | FastAPI/Pydantic schema validation (types, required, ranges, `pattern`, enum validators, `If-Match` missing) | dotted location **with prefix**: `body.admin_email`, `query.per_page`, `header.If-Match`, `body.items.0.name` |
| `VALIDATION_ERROR` | 422 | Domain rule raised by a service (e.g. "caller has no linked employee record", weak password, cross-field rules) | the model's own field name, e.g. `password`, `version`, or empty |
| module-specific 422 codes (e.g. `PUNCH_TIME_IN_FUTURE`, `FACE_NOT_MATCHED`, `INVALID_IF_MATCH`, `IDEMPOTENCY_KEY_REQUIRED`) | 422 | Domain rules with their own code | usually a named field or the header name |
| `INVALID_VALUE` | 422 | A value passed schema validation but could not be stored (DB range/format error: e.g. an integer beyond int64, NUL byte) | none |

## 3. HTTP status → meaning → client policy
| HTTP | Typical `code` values | Meaning | Policy |
|---|---|---|---|
| 400 | `BAD_REQUEST`, `CLIENT_ERROR` (framework) | Rare; malformed request line/body from the framework | Treat as a client bug; show generic error. |
| 401 | `UNAUTHORIZED`, `INVALID_TOKEN`, `INVALID_CREDENTIALS` (all with `WWW-Authenticate: Bearer`) | See [AUTHENTICATION.md §5](AUTHENTICATION.md) | Refresh once and replay; on failure sign out. `INVALID_CREDENTIALS` is a login failure, **never** trigger refresh for it. |
| 403 | `PERMISSION_DENIED`, `COMPANY_*`, `EMAIL_NOT_VERIFIED`, domain 403s (e.g. `FACE_ENROLLMENT_SELF_APPROVAL_NOT_ALLOWED`) | Authenticated but not allowed | Do not retry. `PERMISSION_DENIED.message` names the missing code (`Permission X is required`) — useful for logs, not for users. |
| 404 | `NOT_FOUND`, module `*_NOT_FOUND` | Resource missing **or hidden** (tenant mismatch, out-of-scope id on some routes, invalid/expired/used invite token — deliberately identical) | Do not retry. Don't infer existence. |
| 405 | `METHOD_NOT_ALLOWED` | Wrong verb | Client bug. |
| 409 | `STALE_RESOURCE`, `DUPLICATE_RESOURCE`, `IDEMPOTENCY_KEY_CONFLICT`, ~110 module state/conflict codes | State conflict. For `STALE_RESOURCE`, `details[0].context.current` holds the up-to-date resource | Re-read (or use `context.current`), re-apply the user's edit, resubmit with the new `version`. Others: show message; don't blindly retry. |
| 413 | `PAYLOAD_TOO_LARGE` | Upload over cap | Downscale/compress; never retry unchanged. |
| 422 | see §2 | Validation / business-rule rejection | Map `details[]` to fields; fix and resubmit. |
| 423 | `ACCOUNT_LOCKED`, `LOCKED` | Locked account/resource | Wait (login lock = 15 min). |
| 429 | `RATE_LIMITED`, `FACE_ATTEMPTS_EXCEEDED`, `FACE_ENROLLMENT_ATTEMPTS_EXCEEDED` | Throttled | Honour `Retry-After` (seconds) for `RATE_LIMITED`; the face codes carry no header — wait out the 10-minute window / ask HR to reopen enrollment. |
| 500 | `INTERNAL_ERROR`, `DECRYPTION_FAILED`, `MALFORMED_CIPHERTEXT`, `UNKNOWN_KEY_VERSION` | Server fault | Show `request_id`. Reads: retry with backoff. **Writes: outcome unknown → re-read before retrying unless the call is idempotent.** |
| 502 | `FACE_PROVIDER_FAILED`, `BAD_GATEWAY` | Upstream face provider/gateway failure | Retry later; for a punch use the same `idempotency_key`. |
| 503 | `DATABASE_BUSY` (`Retry-After: 2`), `RATE_LIMITER_UNAVAILABLE` (`Retry-After: 5`), `FACE_*_UNAVAILABLE`, `FACE_LIVENESS_TIMEOUT`, `IMPORT_QUEUE_UNAVAILABLE`, `ENCRYPTION_UNAVAILABLE` | Transient or feature switched off | `DATABASE_BUSY`: the transaction was **rolled back**, safe to retry. `FACE_VERIFICATION_UNAVAILABLE`/`FACE_LIVENESS_UNAVAILABLE`: feature disabled on this deployment → hide face UI / fall back to manual punch; do not loop. |

`DATABASE_BUSY` is only returned for lock/statement timeouts, deadlock victims and serialization failures — cases where the database rolled back. A *lost connection* deliberately surfaces as `500`, because the commit may have landed (`core/errors/handlers.py:db_error_handler`).

## 4. Domain error vocabulary (what to expect per module)
| Module | # codes | Highlights (see the module doc for the full list) |
|---|---|---|
| core / shared | 26 (24 + 2) | `UNAUTHORIZED`, `INVALID_TOKEN`, `INVALID_CREDENTIALS`, `PERMISSION_DENIED`, `COMPANY_*`, `EMAIL_NOT_VERIFIED`, `ACCOUNT_LOCKED`, `IDEMPOTENCY_KEY_*`, `RATE_LIMITED`, `RATE_LIMITER_UNAVAILABLE` |
| attendance (largest, 88) | see [modules/attendance.md](modules/attendance.md#domain-error-codes-raised-by-this-module-88) | punch (`PUNCH_TIME_IN_FUTURE`, `PUNCH_TIME_BEFORE_EMPLOYMENT`, `DUPLICATE_PUNCH_IDEMPOTENCY_KEY`), face (`FACE_NOT_ENROLLED`, `FACE_NOT_MATCHED`, `FACE_SPOOF_SUSPECTED`, `FACE_LIVENESS_*`, `FACE_CAPTURE_REPLAYED`, `FACE_PROFILE_PENDING_APPROVAL`), periods (`ATTENDANCE_PERIOD_CLOSED`, `ATTENDANCE_FINALIZATION_BLOCKED`, `ATTENDANCE_DAY_LOCKED`), regularization/overtime stage errors |
| leave (47) | [modules/leave.md](modules/leave.md) | policy/balance/overlap/approval-stage errors |
| payroll (28) | [modules/payroll.md](modules/payroll.md) | pay-run state-machine errors |
| employee, organisation, onboarding, account_invite, employee_import, platform | in the respective module doc | |

## 5. Which endpoint raises which domain code?
**Not mapped.** The domain codes are defined per module but raised from service code with branching logic; this documentation does not attempt a per-endpoint static trace and does not claim one. What *is* guaranteed per endpoint (auth, permission, validation, `If-Match`, idempotency, rate limit) is derived from the dependency graph and shown in each endpoint's "Error responses" table. For the auth endpoints the domain errors were read from `identity/service.py` and listed explicitly. **Open item:** a per-endpoint error matrix needs either service-level tracing or contract tests ([audit M-6](API_CONTRACT_AUDIT.md)).

## 6. Recommended mobile strategy (respects the behaviour above)
```
response = send(request)
if no HTTP response:                  → NetworkError(timeout?)  # writes: unknown outcome
elif status in 200..299:              → parse envelope (or empty for 204)
else:
    err = body.error if present else synthesize(status)       # proxy 502/503/504 have no envelope
    switch err.code:
        INVALID_TOKEN, UNAUTHORIZED (and not a /auth/login|refresh call):
            refreshOnce() then replay once; else sign out
        COMPANY_PENDING_APPROVAL, COMPANY_SUSPENDED:  switch UI to read-only; disable write actions
        COMPANY_REJECTED, COMPANY_TERMINATED:         sign out → company-state screen
        STALE_RESOURCE:                               merge using details[0].context.current, resubmit with new version
        RATE_LIMITED:                                 wait Retry-After (default 60 s), then manual retry
        DATABASE_BUSY, RATE_LIMITER_UNAVAILABLE:      auto-retry with jittered backoff, ≤3 attempts
        REQUEST_VALIDATION_ERROR, VALIDATION_ERROR, *422*:   show per-field errors from details[]
        PERMISSION_DENIED:                            hide the control; refresh /auth/me permissions
        FACE_*:                                       see API_WORKFLOWS.md §Face punch
        default 5xx:                                  generic message + request_id
```
Rules of thumb
* **Retry safe**: any `GET`; `POST /auth/login` (rate-limited, not side-effecting beyond lockout counters); writes carrying an `Idempotency-Key`/`idempotency_key` replayed with the **same** key; `503 DATABASE_BUSY`.
* **Retry unsafe**: refresh-token call after an unknown outcome; any write without an idempotency mechanism after a timeout/`500`/dropped connection (reconcile by reading first). Most business writes (create employee, approve, publish version, pay-run transitions) have **no** idempotency protection ([audit H-4](API_CONTRACT_AUDIT.md)); they are protected only by `If-Match`/state checks, which makes a blind retry typically fail with `409` rather than double-apply — but that is state-machine behaviour per route, not a guarantee.
* Always capture `error.request_id` (or the `X-Request-Id` response header, or your own sent id when there is no body) into your crash/diagnostic log.

### Reference parsing code
Dart (this is what `apps/mobile/lib/core/api/api_client.dart` does):
```dart
final err = payload is Map ? payload['error'] as Map<String, dynamic>? : null;
throw ApiError(
  status: res.statusCode ?? 0,
  code: err?['code'] ?? (const {502,503,504}.contains(res.statusCode) ? 'SERVICE_UNAVAILABLE' : 'UNKNOWN_ERROR'),
  message: err?['message'] ?? 'Request failed with status ${res.statusCode}',
  details: (err?['details'] as List? ?? []).map((d) => ErrorDetail.fromJson(d)).toList(),
  requestId: err?['request_id'] ?? res.headers.value('x-request-id'));
```
TypeScript:
```ts
type ErrorEnvelope = { error: { code: string; message: string; request_id: string;
  details: { field?: string | null; code: string; message: string; context?: Record<string, unknown> | null }[];
  documentation_url?: string | null } };
async function parse(res: Response) {
  if (res.status === 204) return null;
  const body = await res.json().catch(() => null);
  if (res.ok) return body;
  const e = (body as ErrorEnvelope | null)?.error;
  throw new ApiError(res.status, e?.code ?? ([502,503,504].includes(res.status) ? 'SERVICE_UNAVAILABLE' : 'UNKNOWN_ERROR'),
                     e?.message ?? res.statusText, e?.details ?? [], e?.request_id ?? res.headers.get('x-request-id'));
}
```
Kotlin (kotlinx.serialization) / Swift (Codable) models are in [MOBILE_INTEGRATION_GUIDE.md](MOBILE_INTEGRATION_GUIDE.md#6-typed-error--envelope-models).

## 7. Recommended improvements (separate from observed behaviour)
See [API_CONTRACT_AUDIT.md](API_CONTRACT_AUDIT.md) §Recommendations: one validation code, a `details[].field` convention, populating `documentation_url`, a machine-readable `retryable` flag, `Retry-After` on face 429s, and a per-endpoint error matrix generated from tests.
