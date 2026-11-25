# Error Handling — Security & Data Exposure Report

Date 2026-11-25. Read-only audit; companion to `ERROR_HANDLING_COMPREHENSIVE_AUDIT.md` (finding IDs match).

## 1. Can technical detail reach an end user? (Phase 4 checklist)

| Exposure | Verdict | Evidence |
|---|---|---|
| Python stack traces | **No** | `unhandled_error_response()` returns fixed text; traceback only in logs (`handlers.py:326`, `request_context.py`) |
| Dart stack traces | **No** | release `ErrorWidget.builder` fixed text; `AppDiagnostics` stores code locations only and is never rendered |
| Database table names / SQL | **One path: yes** | `EH-B-01` import row errors persist `str(DBAPIError)` (contains SQL text, table/column names; bound values hidden). Everywhere else DB errors → generic 500/503/409/422 |
| DB connection info | No | engine hides parameters (`core/db/session.py`); health/ready returns ok/error per dependency only |
| Internal file paths | Not found on any response path | `EH-B-07` (asset path in a wrapped message) is log-only as far as traced |
| Env vars / API keys / tokens | No | none echoed; OpenAPI/Swagger disabled outside development (`app.py`, OPS-06) |
| Auth headers / session info | No | `WWW-Authenticate: Bearer` only; `HTTPException` headers filtered to an allow-list (`_PASSTHROUGH_HTTP_HEADERS`) |
| Third-party responses | No | face providers raise fixed-string `FaceProviderError`; email failures classified (`EmailDeliveryError` fixed message); push result enum |
| Payment provider details | N/A | no payment integration exists |
| Internal service names | No | |
| Debug metadata | No | no debug flag in settings; production and development use the same handlers |
| Framework 5xx text | No | `_http_exception_message` replaces any ≥500 `HTTPException.detail` |
| Unknown-route/validation noise | Low | 422 returns Pydantic `loc`/`msg` (field names, not values); acceptable and intentional |

Different behaviour dev vs prod: only `/docs`, `/redoc`, `/v1/openapi.json` (enabled in development only). Error bodies are identical — good: it means tests exercise production behaviour.

## 2. Findings by severity and exploitability

| ID | Severity | Exploitability | Summary |
|---|---|---|---|
| EH-B-01 | **Medium** | Authenticated HR/admin with import permission; needs a CSV row that triggers a non-domain exception | Raw exception text (SQL for DB errors) stored and returned by `GET /v1/employee-imports/{id}/errors` |
| EH-B-02 | Low | Requires a future code change | 5xx `AppError.message` is trusted; no guard (all current classes safe) |
| EH-W-01 | Medium (UX/info) | Local to the user's own session | Non-API `Error.message` can render in toasts via `describeApiError` |
| EH-S-01 | Low | Needs a code path that logs a free-text `*_reason` | `_reason` suffix bypasses key-based redaction |
| EH-S-02 | Low | Needs an exception/field containing Aadhaar/bank digits or a name in free text | value patterns omit 12-digit Aadhaar, account numbers, names |
| EH-S-03 | Low | Operational | log retention default `0`, semantics unverified; logs contain tracebacks |
| EH-B-07 | Low | Untraced | asset path inside `EmbeddingUnavailableError` text |
| EH-W-04 / EH-M-03 | Low | — | `Request failed with status N` fallback string |

No Critical or High findings. I did not find any path that returns passwords, tokens, keys, salary data or other employees' personal data in an error response.

## 3. Does logging itself create risk?

**Strong controls present** (`core/observability/redaction.py`, `logging.py`):
- Every sink passes through `redact_event` *after* traceback rendering, so tracebacks are masked.
- Key-name masking: password, token, authorization, cookie, api_key, otp, signature, aadhaar, pan, account_number, ifsc, salary, ctc, phone, dob, passport, uan, payroll amounts, image/photo/biometric/base64, body/text_body.
- Value masking: JWT, Bearer/Basic, presigned signatures, `scheme://user:pass@`, Postgres `Key (…)=(…)`, e-mail, Indian mobile, PAN, token-bearing URL path segments (LOG-04). Query strings dropped.
- Bytes → `[BYTES n]`; length caps (2k field, 16k traceback); redaction failure degrades to structural fields only (fail closed).
- Policy: never `str(exc)` as a log field (`safe_error()`); route *templates* logged, never raw paths; only the membership-verified tenant is logged.
- DB engine `hide_parameters=True` keeps bound values out of SQL in tracebacks.
- Log viewer is platform-admin-only and its use emits `security.platform.logs_viewed`.

**Gaps:**
1. `_SAFE_KEY_SUFFIXES` includes `_reason`; the name-based mask is skipped for any field ending `_reason` (`redaction.py:58`). Free-text reasons (leave, regularization, rejection) can contain medical or personal detail.
2. Value patterns do not recognise 12-digit Aadhaar, bank account digits, or person names/addresses. Key-name masking covers the *named* fields; the same data inside a traceback's exception text is only partly covered.
3. `raw_row` (employee import CSV row, stored in the DB per row error) is a PII container (names, phones, CTC). It is in the database, not logs; confirm that nothing logs `raw_row` (not found in my sweep, but not proven exhaustively).
4. Retention: `log_retention_days=0` (`settings.py:113`) — verify in `file_sink.py` what 0 does; define a retention for `errors.log` (tracebacks).
5. Access: only platform admins can read logs through the app; host-level access to the log directory/Docker logs is an infrastructure matter I did not audit.

## 4. Recommended order for security items

1. EH-B-01 (stop persisting raw exception text).
2. EH-B-02 (5xx `public_message` guard + test) — makes the guarantee structural.
3. EH-W-01 (`describeApiError` generic fallback).
4. EH-S-01/02 redaction tweaks (drop `_reason` from the safe list or add content patterns; add Aadhaar-12 and bank-account patterns) with tests.
5. EH-S-03 retention decision.
