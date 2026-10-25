# Mobile integration guide (Android / iOS / Flutter)

Everything here conforms to the verified contract in [API_OVERVIEW.md](API_OVERVIEW.md) and [AUTHENTICATION.md](AUTHENTICATION.md). The repository already contains a **Flutter client (`apps/mobile`, Dio + cookie jar + `flutter_secure_storage`)** that implements most of this; Dart snippets below are taken from it, the Kotlin/Swift/TypeScript snippets are *illustrative implementations of the same contract* (not part of the repo and not compiled here).

## 1. Environments & configuration
| Item | Value |
|---|---|
| Local base URL | `http://localhost:8000` (simulators); Android emulator `http://10.0.2.2:8000`; physical device → your machine's LAN IP |
| Staging / production | **Not defined in this repository.** Obtain from the backend/DevOps team; the server has no environment endpoint. |
| Path prefix | `/v1` for everything except `/health*` |
| Config mechanism (Flutter) | `--dart-define=API_BASE_URL=https://…` (`String.fromEnvironment`, default `http://localhost:8000`) |
| Android | Cleartext HTTP is blocked on API 28+ by default; allow only for debug via a `network_security_config`, release must be HTTPS |
| iOS | App Transport Security blocks HTTP; add a debug-only exception for local testing |
| Verify connectivity | `GET {base}/health/ready` → `200 {"data":{"ready":true,"database":"ok","redis":"ok",…}}` (`503` when not ready) |
| Interactive docs | `/docs` only exists on a development server |

Recommended: three build flavors (`dev`, `staging`, `prod`) each fixing the base URL at build time; never let a release build accept an arbitrary URL.

## 2. HTTP client initialisation
Required behaviour: JSON in/out; `Authorization: Bearer`; a **persistent cookie store** for `hrms_refresh` (path `/v1/auth`); timeouts; `X-Request-Id`; a single-flight refresh on `401`.

### Dart (from `apps/mobile/lib/core/api/api_client.dart`)
```dart
const connectTimeout = Duration(seconds: 10);
const receiveTimeout = Duration(seconds: 30);
const sendTimeout    = Duration(seconds: 60);
const transferTimeout = Duration(seconds: 120);   // uploads / downloads

final dir = await getApplicationSupportDirectory();
final jar = PersistCookieJar(storage: FileStorage('${dir.path}/.cookies/'));
final dio = Dio(BaseOptions(baseUrl: '$apiBase/v1',
    connectTimeout: connectTimeout, receiveTimeout: receiveTimeout, sendTimeout: sendTimeout));
dio.interceptors.add(CookieManager(jar));
// per request:
headers['X-Request-Id'] = 'req_${DateTime.now().millisecondsSinceEpoch}_${Random().nextInt(1<<32).toRadixString(16)}';
headers['Authorization'] = 'Bearer ${session.accessToken}';
headers['X-Company-Id'] = session.companyId;      // optional; must equal the token's company
```
Note: the request-id pattern the server accepts is `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}` — `req_…` ids conform.

### Kotlin (OkHttp + Retrofit, illustrative)
```kotlin
val cookieJar = PersistentCookieJar(SetCookieCache(), SharedPrefsCookiePersistor(context)) // e.g. franmontiel/PersistentCookieJar
val client = OkHttpClient.Builder()
    .cookieJar(cookieJar)
    .connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).writeTimeout(60, TimeUnit.SECONDS)
    .addInterceptor { chain ->
        val b = chain.request().newBuilder().header("X-Request-Id", "req_${System.currentTimeMillis()}_${UUID.randomUUID().toString().take(8)}")
        tokenStore.accessToken?.let { b.header("Authorization", "Bearer $it") }
        chain.proceed(b.build())
    }
    .authenticator(RefreshAuthenticator(api, tokenStore))      // see §3: one in-flight refresh, one replay
    .build()
```

### Swift (URLSession, illustrative)
```swift
let cfg = URLSessionConfiguration.default
cfg.httpCookieStorage = HTTPCookieStorage.shared; cfg.httpCookieAcceptPolicy = .always   // persisted across launches by the system
cfg.timeoutIntervalForRequest = 30; cfg.timeoutIntervalForResource = 120
let session = URLSession(configuration: cfg)
func request(_ path: String, method: String = "GET", body: Data? = nil) -> URLRequest {
  var r = URLRequest(url: base.appendingPathComponent("v1").appendingPathComponent(path)); r.httpMethod = method
  r.setValue("req_\(UUID().uuidString.prefix(12))", forHTTPHeaderField: "X-Request-Id")
  if let t = tokenStore.accessToken { r.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
  if body != nil { r.setValue("application/json", forHTTPHeaderField: "Content-Type"); r.httpBody = body }
  return r }
```
Caveat: keep the refresh cookie out of iCloud/device backups and consider scoping a dedicated `HTTPCookieStorage` to the app; the cookie is the long-lived (30-day) credential.

### TypeScript (React Native / web, illustrative)
```ts
export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const res = await fetch(`${BASE}/v1${path}`, { ...init, credentials: 'include',   // sends hrms_refresh to /v1/auth/* only
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': `req_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
               ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } });
  if (res.status === 401 && retry && !path.startsWith('/auth/')) { if (await refreshOnce()) return api<T>(path, init, false); }
  return parse<T>(res);
}
```
(React Native's `fetch` cookie persistence is platform-dependent; prefer a native cookie jar or `@react-native-cookies/cookies`.)

## 3. Authentication lifecycle (single-flight refresh)
```dart
Completer<bool>? _refreshInFlight;
Future<bool> refreshOnce() { if (_refreshInFlight != null) return _refreshInFlight!.future;
  _refreshInFlight = Completer<bool>(); _refresh().then((ok) { _refreshInFlight!.complete(ok); _refreshInFlight = null; });
  return _refreshInFlight!.future; }
```
* Trigger on `401` for **non-auth** endpoints only; replay the original request **once**; if the refresh fails (`401`), clear the session and route to sign-in. Do not auto-retry after a refresh *timeout* (the rotation may have happened — see [AUTHENTICATION.md §4.2](AUTHENTICATION.md)).
* Proactive refresh is optional: `expires_in_minutes` is relative to the response time; compute `expiresAt = now + minutes` (the Flutter `StoredSession` does) and refresh ~1 min before.
* After login/refresh call `GET /auth/me` and cache `permissions`, `employee_id`, `company_timezone`, `company_status` (the latter drives the read-only banner).

## 4. Serialization rules
| Wire | Client type | Rule |
|---|---|---|
| `*_id`, uuid strings | `UUID`/`String` | Opaque. |
| Instants (`created_at`, `punch_time`) | `Instant`/`DateTime` UTC | ISO-8601 with `Z` and up to 6 fractional digits (`2026-10-24T13:17:22.407820Z`). Accept both with/without fraction. |
| Dates (`attendance_date`, `start_date`) | `LocalDate` | `YYYY-MM-DD`, **no timezone**; they belong to the company/shift timezone. Never convert through the phone's zone. |
| Time of day | `LocalTime` | `HH:MM` |
| Decimals (`"1.50"` leave days, balances, similarity) | `BigDecimal`/`Decimal`/`Decimal` | Strings; never `double`. |
| Money `*_minor` | `Long` | Integer paise; format with the currency (`INR`). |
| `version` | `Int` | Echo into `If-Match`. |
| Nullable keys | | Read models always include the key; treat `null` ≠ absent only for requests. |
| Sending datetimes | | ISO-8601 **with offset** (`2026-10-24T09:05:00+05:30` or `…Z`); naive values are rejected on the two client-time endpoints (on-behalf punch, regularization). |
| Unknown enum values | | Tolerate (server vocabularies are plain strings and may grow). |

**Timezone assumption**: the business day is the company's (`company_timezone`, currently only `Asia/Kolkata`). When asking "today's punches" compute the date in `company_timezone`, not the device's, or omit date parameters where the API allows (`POST /attendance/days/calculate`).

## 5. Lists: pagination, search, sorting, infinite scroll
```dart
// works for both paginated and unpaginated collections
final env = await api.getList('/employees', query: PageQuery(page: p, perPage: 25));
final hasMore = env.pagination != null && env.pagination!.page < env.pagination!.totalPages;
```
* Standard lists paginate at 25/100; the attendance, roster, regularization, overtime, period, projection, face-profile and payroll-run collections are now **bounded** (`per_page` 1-500, default 500, `pagination` always present). Loop `page = 1…` until `page >= total_pages` exactly like the Flutter helpers do (`per_page: 100`). Small master-data lists remain unpaginated (`pagination == null`). Still send a bounded `date_from`/`date_to` for attendance lists. See [API_OVERVIEW §4.4](API_OVERVIEW.md).
* No sort or search parameters exist; sort client-side (stable keys: `punch_time`, `attendance_date`, `submitted_at`). A page boundary can shift if rows are inserted — de-duplicate by `id` when appending.
* `per_page > 100` or `page < 1` → `422` (not clamped).

## 6. Typed error / envelope models
### Kotlin
```kotlin
@Serializable data class ErrorDetail(val field: String? = null, val code: String, val message: String, val context: JsonObject? = null)
@Serializable data class ErrorBody(val code: String, val message: String, val details: List<ErrorDetail> = emptyList(),
                                   @SerialName("request_id") val requestId: String, @SerialName("documentation_url") val documentationUrl: String? = null)
@Serializable data class ErrorEnvelope(val error: ErrorBody)
@Serializable data class ResponseMeta(@SerialName("request_id") val requestId: String, @SerialName("server_time") val serverTime: String? = null)
@Serializable data class PaginationMeta(val page: Int, @SerialName("per_page") val perPage: Int, val total: Int,
                                        @SerialName("total_pages") val totalPages: Int, @SerialName("next_cursor") val nextCursor: String? = null)
@Serializable data class Data<T>(val data: T, val meta: ResponseMeta)
@Serializable data class Page<T>(val data: List<T>, val pagination: PaginationMeta? = null, val meta: ResponseMeta)
```
### Swift
```swift
struct ErrorDetail: Codable { let field: String?; let code: String; let message: String; let context: [String: JSONValue]? }
struct ErrorBody: Codable { let code, message: String; let details: [ErrorDetail]; let requestId: String; let documentationUrl: String? }
struct ErrorEnvelope: Codable { let error: ErrorBody }
struct PaginationMeta: Codable { let page, perPage, total, totalPages: Int; let nextCursor: String? }
// decoder.keyDecodingStrategy = .convertFromSnakeCase; decoder.dateDecodingStrategy = custom ISO8601 (with & without fractional seconds)
```
### Domain example (`/auth/me`)
```kotlin
@Serializable data class UserProfile(val id: String, val email: String? = null, @SerialName("company_id") val companyId: String,
  @SerialName("employee_id") val employeeId: String? = null, val permissions: List<String>,
  @SerialName("company_timezone") val companyTimezone: String, @SerialName("company_status") val companyStatus: String = "ACTIVE")
```

## 7. File upload
* Use `multipart/form-data`. Face endpoints: `frames` repeated field (`frames_required` entries from the session), `direction` and `liveness_session_id` text fields; enrollment: file fields `front,left,right,up,down` + `consent_confirmed=true`. Documents: `document_type` + `file`.
* Types are decided by **magic bytes** (PDF/JPEG/PNG for documents; JPEG/PNG for faces). A wrong `Content-Type` or extension does not matter; a wrong *content* → `422`.
* Compress before upload to stay under limits (face frame ≤ **1 MiB**, enrollment image ≤ **5 MiB**, document ≤ **10 MiB**) — the request cap is slightly above the sum; oversize → `413 PAYLOAD_TOO_LARGE` immediately, even before parsing.
* A `FormData` can be sent once — rebuild it for any retry (the Flutter client takes a builder for this reason).
* Use the longer transfer timeouts (120 s); uploads are not resumable and have no progress API.
* Dart sketch: `FormData.fromMap({'direction':'IN','liveness_session_id':sid,'frames':[MultipartFile.fromBytes(b0, filename:'f0.jpg', contentType: MediaType('image','jpeg')), …]})`.

## 8. Downloads, images, documents
* CSV (`bank-advice`, import template): request as bytes; filename is in `Content-Disposition`. The Flutter `download()` does exactly this.
* `review-photo`: raw image bytes, `Cache-Control: no-store, private` — do not cache to disk.
* **There are no file/image URLs in any response** (employee `photo_url` is a free-text field owned by clients; documents have no download route). No URL lifetime or CDN behaviour exists to handle.

## 9. Timeouts, retries, backoff
| Case | Policy |
|---|---|
| Connect timeout | 10 s; nothing reached the server → safe to retry any call |
| Read/send timeout on GET | retry with exponential backoff + jitter (e.g. 0.5 s, 1 s, 2 s; max 3) |
| Read/send timeout on a write | **outcome unknown** — do not blind-retry. If the call has `Idempotency-Key`/`idempotency_key`, retry with the **same** key; otherwise reconcile by reading (e.g. list leave applications) |
| `503 DATABASE_BUSY` / `RATE_LIMITER_UNAVAILABLE` | honour `Retry-After`, backoff, ≤3 tries |
| `429` | wait `Retry-After`; surface to the user for login |
| `5xx` without envelope (proxy) | treat as `SERVICE_UNAVAILABLE`, backoff |
The Flutter client intentionally never retries automatically on timeout (LOG-15) and distinguishes `connectionTimeout` (nothing sent) from send/receive timeouts.

## 10. Duplicate-submission prevention
| Action | Mechanism |
|---|---|
| Leave application, ledger adjustment/encashment, payroll adjustment | **Required** `Idempotency-Key` header: generate one UUID per user intent, persist it with the pending action, reuse on retry, discard on success/definitive failure. Replays return the stored response + `Idempotent-Replayed: true`. |
| Manual punch | Body `idempotency_key` (≤100) — generate per tap; the server also accepts duplicates (see [API_WORKFLOWS §4](API_WORKFLOWS.md)), so disable the button while in flight. |
| Face punch | Form `idempotency_key` (16–64); retries need a **fresh** liveness session + capture but the same key. |
| Versioned edits | `If-Match` makes a second identical submit fail with `409 STALE_RESOURCE`. |
| Create employee, create onboarding case | **Optional** `Idempotency-Key` (H-4 remediation): send one UUID per user intent; a retry replays the first result (`Idempotent-Replayed: true`), concurrent duplicates create one row. |
| Approve/reject/cancel, publish, pay-run transitions, regularization/leave state changes | Protected by state-machine checks (a repeat is a `409`), not by keys - safe to retry, but treat a `409 …INVALID_TRANSITION` after a timeout as "probably already applied" and re-read. |
The idempotency fingerprint covers the body *and the acting user*; the same key from another user is a different request.

## 11. Offline behaviour & caching
* The API sends **no cache headers** (no `ETag`/`Last-Modified`/`Cache-Control` on JSON) and does not support conditional requests; caching is entirely client policy. Suggested: cache `/auth/me`, leave types, company profile with short TTL and refresh on app foreground; never cache `review-photo`.
* **Attendance is online-only by design** (`DEC-TZ-01`: the server clock is authoritative). `POST /attendance/punches/me` has no time field and stamps *receipt time*, so a queued offline punch would be recorded at replay. Disable punching when offline; a missed punch goes through `POST /regularizations`. The secure design that would be required for offline capture, and the open decisions, are in [OFFLINE_ATTENDANCE_DESIGN.md](OFFLINE_ATTENDANCE_DESIGN.md).
* Queue writes only if they carry an idempotency key; drop silently-stale ones on `409 STALE_RESOURCE`.
* Reads are tenant-scoped by token — clear all caches on sign-out or company change.

## 12. UI states ↔ API behaviour
| State | Source |
|---|---|
| Loading | request in flight (respect 30 s read timeout) |
| Empty | `data: []` — **also what an out-of-scope or unconfigured query returns** (200 with empty list), so show a neutral empty state, not an error |
| Read-only company | `company_status` ∈ {`PENDING_APPROVAL`,`SUSPENDED`} or `403 COMPANY_*` on a write |
| Not permitted | `permissions[]` lacks the code → hide; `403 PERMISSION_DENIED` → refresh `/auth/me` |
| Misconfigured company | e.g. attendance day `attendance_status = CONFIG_ERROR`, `422 …_NOT_RESOLVED` leave/calendar errors → message "your company has not finished setup" |
| Feature off | `503 FACE_VERIFICATION_UNAVAILABLE`/`FACE_LIVENESS_UNAVAILABLE` → hide face punching |
| Stale edit | `409 STALE_RESOURCE` → merge dialog with `details[0].context.current` |
| Rate limited / locked | `429` + `Retry-After`; `423 ACCOUNT_LOCKED` (15 min) |

## 13. Secure storage & logging
* Access token → Keychain/Keystore; refresh cookie → app-private cookie store (excluded from backup); never in `SharedPreferences`/`UserDefaults`/logs/analytics.
* Log: method, path template (not query values containing employee ids if your policy forbids), status, `X-Request-Id`, `error.code`, latency. Never log `Authorization`, `Cookie`/`Set-Cookie`, request bodies of `/auth/*`, `/public/*/accept`, `/companies/register`, uploads (face frames are biometric data), or response bodies of `/employees/*` (PII: bank, statutory ids) and payslips.
* Biometric data: face frames go only to the two face endpoints over TLS; do not persist them; the server also keeps only the HR review photo until a decision.
* Show `request_id` in a "copy support code" action on fatal errors.

## 14. Testing the integration
* Import [postman/hrms-api.postman_collection.json](postman/hrms-api.postman_collection.json) + [hrms-local.postman_environment.json](postman/hrms-local.postman_environment.json); run **Identity → POST /auth/login** first (its test script stores `access_token`/`company_id`); enable Postman's cookie jar so the refresh cookie is kept. Request bodies are schema-derived placeholders (**not executed**) — replace ids/values.
* Reproduce the recorded flows in [examples/](examples/) with `docs/api/tools/record_examples.py` against a throwaway server.
* Flutter: `apps/mobile/test/` has contract-fixture tests (`test/fixtures/contract`), a fake API client (`test/support`), and a `test/live/live_contract_test.dart` for live checks; the backend's own auth tests pass against `hrms_test` (see the audit for run details).
* Create test users via the invite flow; remember the default `EMPLOYEE` role lacks `ATTENDANCE.*` ([audit C-1](API_CONTRACT_AUDIT.md)) so seed that permission in test environments (the recorded flow did it with SQL on the test DB).
