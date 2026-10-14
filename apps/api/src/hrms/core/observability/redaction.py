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


class AccessLogPathRedactionFilter(logging.Filter):
    """Rewrites the path argument of uvicorn's access-log record — `(client_addr, method,
    full_path, http_version, status_code)` — before any handler (uvicorn's own, or gunicorn's
    when run under `UvicornWorker`) formats it. Never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact_path(args[2]), *args[3:])
        return True
