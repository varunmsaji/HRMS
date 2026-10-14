"""LOG-01 / LOG-05 — request correlation that survives every failure path
(`docs/audits/LOGGING_ERROR_HANDLING_OBSERVABILITY_PLAN.md` §D).

`RequestContextMiddleware` is the outermost middleware `create_app` adds (pure ASGI, so it runs in
the same task as everything inside it). It:

1. Resolves the request id: the client's `X-Request-Id` only if it matches `REQUEST_ID_PATTERN`
   (bounded to 64 characters — `audit_log.request_id` is `VARCHAR(64)` — and a header-, log- and
   URL-safe alphabet), otherwise a fresh UUID. A bad client value is replaced, never rejected,
   so it can no longer make an audited write fail.
2. Publishes it to `current_request_id()` and structlog's context, so every log event emitted
   while serving the request carries it.
3. Adds `X-Request-Id` to every response, whichever layer produced it.
4. Catches any exception that escapes the whole stack (route, dependency, or another
   middleware). Before this existed, such an exception reached Starlette's
   `ServerErrorMiddleware`, which sits *outside* every user middleware: by then `TenancyMiddleware`
   had already cleared the request id (logged and returned as `"unknown"`), and the 500 skipped
   CORS and the security headers, so browsers reported a network failure instead of the error.
   Now the exception is logged exactly once, with its traceback, and the standard 500 envelope is
   sent through the *same* CORS and security-header middleware classes the app uses, configured
   identically. It is not re-raised, so uvicorn does not print a second traceback.
5. Restores the previous context only after the response is complete.
"""

import re
import uuid
from collections.abc import Mapping
from typing import Any

import structlog
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hrms.core.errors.handlers import log_unhandled_exception, unhandled_error_response
from hrms.core.security_headers import SecurityHeadersMiddleware
from hrms.core.tenancy.context import (
    reset_request_context,
    snapshot_request_context,
)
from hrms.core.tenancy.context import (
    set_request_id as _set_request_id_var,
)

#: 1-64 characters, starting alphanumeric, then alphanumerics and `.` `_` `:` `-`. Covers UUIDs
#: (web client), `req_<millis>_<hex>` (mobile client) and common tracing formats, while excluding
#: whitespace, control characters, quotes, `/`, and anything non-ASCII.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
REQUEST_ID_HEADER = "x-request-id"


def resolve_request_id(raw: str | None) -> str:
    if raw is not None and REQUEST_ID_PATTERN.fullmatch(raw):
        return raw
    return str(uuid.uuid4())


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key == name:
            # Starlette decodes header values as latin-1; anything outside the pattern's ASCII
            # alphabet then simply fails validation.
            return str(value.decode("latin-1"))
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, cors_options: Mapping[str, Any]) -> None:
        self.app = app
        self._cors_options = dict(cors_options)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(_header(scope, b"x-request-id"))
        snapshot = snapshot_request_context()
        _set_request_id_var(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        log_tokens = structlog.contextvars.bind_contextvars(request_id=request_id)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            # Logged before the context is restored, so request id / verified tenant are present.
            log_unhandled_exception(scope, exc, response_started=response_started)
            if response_started:
                # Too late for a clean envelope; let the server close the connection.
                raise
            await self._send_error(scope, receive, send_with_request_id)
        finally:
            structlog.contextvars.reset_contextvars(**log_tokens)
            reset_request_context(snapshot)

    async def _send_error(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = unhandled_error_response()
        app: ASGIApp = CORSMiddleware(response, **self._cors_options)
        app = SecurityHeadersMiddleware(app)
        await app(scope, receive, send)
