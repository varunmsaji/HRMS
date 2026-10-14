"""LOG-04 — URL paths that carry a bearer token in a path segment must never reach a log line
with the token intact (`docs/audits/LOGGING_ERROR_HANDLING_OBSERVABILITY_PLAN.md` §D LOG-04).

The public onboarding and account-invite APIs, and the web pages the emails link to, put the
raw token in the path. Changing those URLs would break links already sitting in inboxes, so the
paths stay as they are and every log sink masks the segment instead: the uvicorn access logger
(filter below, installed by `configure_logging`), the API's own error events (which log the route
template, falling back to `redact_path`), and Nginx (`infra/nginx/nginx.conf` mirrors these
prefixes in its own `map`; keep the two lists in sync).
"""

import logging
import re
from collections.abc import MutableMapping
from typing import Any

REDACTED = "[REDACTED]"

#: A path prefix whose *next* segment is a secret token. API routes first, then the web pages
#: the verification / reset / invite / onboarding emails link to.
TOKEN_PATH_PREFIXES: tuple[str, ...] = (
    "/v1/public/onboarding/",
    "/v1/public/account-invites/",
    "/onboarding/",
    "/verify-email/",
    "/reset-password/",
    "/accept-invite/",
)

_TOKEN_SEGMENT = re.compile(
    "(" + "|".join(re.escape(prefix) for prefix in TOKEN_PATH_PREFIXES) + ")[^/?#]+"
)


def redact_path(path: str) -> str:
    """Masks the token segment of a known token-bearing path and drops any query string (query
    parameters are never needed to diagnose a request and may carry signatures or tokens)."""
    path = path.split("?", 1)[0]
    return _TOKEN_SEGMENT.sub(rf"\1{REDACTED}", path)


#: Field names whose value is a secret or sensitive personal data regardless of content
#: (LOG-08, plan §H). Matched as a whole `_`-separated word, so `password`, `new_password`,
#: `refresh_token`, `api_key` and `Authorization` are masked while identifiers *about* such
#: things (`family_id`, `token_kind`, `key_version`) are not — see `_SAFE_KEY_SUFFIXES`.
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:password|passwd|secret|token|authorization|cookie|set_cookie|api_?key|otp|"
    r"signature|credentials?|private_key|aadhaar|pan|pan_number|account_number|ifsc|salary|"
    r"ctc|text_body|html_body|body|face_template|embedding)(?:_|$)",
    re.IGNORECASE,
)
_SAFE_KEY_SUFFIXES = ("_id", "_ids", "_type", "_kind", "_count", "_version", "_status", "_reason")
#: Structural fields every event carries; never redacted by name or pattern. `event` is not one
#: of them: for stdlib records (Celery, kombu, httpx) it is the free-text message, so it goes
#: through the value patterns like any other string (our own event names are unaffected).
_STRUCTURAL_KEYS = frozenset(
    {"level", "timestamp", "logger", "service", "environment", "request_id"}
)

#: Value patterns masked inside any string field, including rendered tracebacks. Each replaces
#: only the secret part so the surrounding text stays diagnosable.
_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # JWTs (access/refresh tokens) wherever they appear.
    (re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*"), REDACTED),
    # `Authorization: Bearer …` / `Basic …`.
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {REDACTED}"),
    # Presigned-URL signatures and credentials (S3 v4 and v2).
    (
        re.compile(r"(?i)\b(X-Amz-(?:Signature|Credential|Security-Token)|Signature)=[^&\s\"']+"),
        rf"\1={REDACTED}",
    ),
    # A password embedded in a connection URL: `scheme://user:password@host`.
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://[^:/@\s]*:)[^@\s/]+@"), rf"\1{REDACTED}@"),
    # Postgres constraint-violation DETAIL echoes the offending values: `Key (email)=(a@b.c)`.
    (re.compile(r"(Key \([^)]*\)=\()[^)]*(\))"), rf"\1{REDACTED}\2"),
    # Email addresses — never needed to diagnose a failure; `user_id` identifies the account.
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), "[EMAIL]"),
    # Indian PAN (`ABCDE1234F`).
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), REDACTED),
    # Token-bearing URL path segments (same prefixes as `redact_path`), but not a route
    # template's `{token}` placeholder, which is exactly what the logs should show.
    (
        re.compile(
            "("
            + "|".join(re.escape(prefix) for prefix in TOKEN_PATH_PREFIXES)
            + r")(?!\{)[^/?#\s\"']+"
        ),
        rf"\1{REDACTED}",
    ),
)

#: Upper bound on any one string field. A traceback gets more room than an ordinary value; both
#: bounds stop an attacker-controlled or runaway value from flooding the bounded Docker log.
MAX_FIELD_CHARS = 2_000
MAX_EXCEPTION_CHARS = 16_000
_MAX_DEPTH = 4


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _STRUCTURAL_KEYS or lowered.endswith(_SAFE_KEY_SUFFIXES):
        return False
    return bool(_SENSITIVE_KEY.search(lowered))


def redact_text(text: str, *, limit: int = MAX_FIELD_CHARS) -> str:
    for pattern, replacement in _VALUE_PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > limit:
        text = f"{text[:limit]}…[truncated {len(text) - limit} chars]"
    return text


def _redact_value(value: object, depth: int, limit: int) -> object:
    if isinstance(value, str):
        return redact_text(value, limit=limit)
    if isinstance(value, (bytes, bytearray, memoryview)):
        # Raw bytes in a log field are never diagnosable and may be an image or a document.
        return f"[BYTES {len(value)}]"
    if depth >= _MAX_DEPTH:
        return value if isinstance(value, (int, float, bool)) or value is None else "[DEPTH]"
    if isinstance(value, dict):
        return {
            k: REDACTED
            if isinstance(k, str) and _is_sensitive_key(k)
            else _redact_value(v, depth + 1, MAX_FIELD_CHARS)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_value(v, depth + 1, MAX_FIELD_CHARS) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    # Anything else (UUID, date, Decimal, an ORM object passed by mistake) is rendered by
    # JSONRenderer via `str()`; redact that rendering so no object leaks unmasked.
    return redact_text(str(value), limit=limit)


def redact_event(
    _logger: object, _method: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """structlog processor — the shared last line of defence for every API, worker and Beat log
    line (plan §H). Runs after `format_exc_info`, so the rendered traceback is masked too.
    Masks by field name and by value pattern, and bounds string length. Never raises: if
    redaction itself fails, the event is reduced to its structural fields rather than being
    emitted unredacted."""
    try:
        out: dict[str, Any] = {}
        for key, value in event_dict.items():
            if key in _STRUCTURAL_KEYS:
                out[key] = value
            elif _is_sensitive_key(key):
                out[key] = REDACTED
            else:
                limit = MAX_EXCEPTION_CHARS if key == "exception" else MAX_FIELD_CHARS
                out[key] = _redact_value(value, 0, limit)
    except Exception:  # noqa: BLE001 — must never break or bypass logging
        safe = {k: event_dict[k] for k in _STRUCTURAL_KEYS if k in event_dict}
        safe["event"] = "log_redaction_failed"
        safe["redaction_failed"] = True
        return safe
    return out


class AccessLogPathRedactionFilter(logging.Filter):
    """Rewrites the path argument of uvicorn's access-log record — `(client_addr, method,
    full_path, http_version, status_code)` — before any handler (uvicorn's own, or gunicorn's
    when run under `UvicornWorker`) formats it. Never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact_path(args[2]), *args[3:])
        return True
