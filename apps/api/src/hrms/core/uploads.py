"""Bounded-upload primitives for untrusted file uploads (SEC-03,
docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md).

`MaxUploadSizeMiddleware` is the real enforcement point: FastAPI's own dependency-injection
machinery (`UploadFile`/`File()`/`Form()` route parameters) calls `await request.form()` to fully
parse and spool the incoming multipart body *before* any `Depends()` or the endpoint function
itself ever runs (`fastapi.dependencies.utils.solve_dependencies` extracts the body up front) —
so a `Content-Length` check or a bounded `file.read()` written inside the route handler can only
react *after* the body has already been received in full. This middleware instead wraps the raw
ASGI `receive` channel, upstream of multipart parsing, so an oversized request is rejected while
it is still arriving.

`read_upload_bounded` is the secondary, defense-in-depth layer used inside the route/service
code itself (replacing the flagged `body = await file.read()` pattern) — it ensures the
application never materializes more than `max_bytes` (plus one chunk) of a file into a single
`bytes` object, regardless of what already made it past the middleware."""

import json

from fastapi import UploadFile
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hrms.core.errors.envelope import ErrorBody, ErrorEnvelope
from hrms.core.tenancy.context import current_request_id


class _UploadTooLargeError(Exception):
    """Internal signal only — raised inside `_bounded_receive` (called deep inside Starlette's
    multipart parser, several async frames below this middleware) and caught in `__call__`
    itself, right where `send` is still in scope. Deliberately not `PayloadTooLargeError`/
    `AppError`: Starlette's `ExceptionMiddleware` (which dispatches to `@app.exception_handler`-
    registered handlers) sits *inside* every user-added middleware
    (`Starlette.build_middleware_stack`: `ServerErrorMiddleware -> user middleware ->
    ExceptionMiddleware -> router`), so an exception raised by a middleware itself — as opposed to
    by a route handler — would never reach it; it would fall through to `ServerErrorMiddleware`'s
    generic 500 instead. Building the 413 response directly here is what actually produces a
    controlled 4xx rather than a crash."""


class MaxUploadSizeMiddleware:
    """Rejects requests to `path_prefixes` whose body exceeds `max_bytes`.

    Two checks, because neither alone is trustworthy (plan requirement — do not rely solely on
    `Content-Length`):
    - an early `Content-Length` check, when the header is present and honest, rejects before a
      single byte of the body is read;
    - a running total over the actual bytes received from `receive()` enforces the same cap when
      `Content-Length` is absent, wrong, or the transfer is chunked — this is the one that
      actually bounds memory/disk usage during multipart parsing itself."""

    def __init__(self, app: ASGIApp, *, max_bytes: int, path_prefixes: tuple[str, ...]) -> None:
        self._app = app
        self._max_bytes = max_bytes
        self._path_prefixes = path_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not any(
            scope["path"].startswith(prefix) for prefix in self._path_prefixes
        ):
            await self._app(scope, receive, send)
            return

        declared_length = Headers(scope=scope).get("content-length")
        if declared_length is not None:
            try:
                declared_bytes = int(declared_length)
            except ValueError:
                declared_bytes = None
            if declared_bytes is not None and declared_bytes > self._max_bytes:
                await self._send_413(send)
                return

        received = 0

        async def _bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    raise _UploadTooLargeError()
            return message

        try:
            await self._app(scope, _bounded_receive, send)
        except _UploadTooLargeError:
            await self._send_413(send)

    async def _send_413(self, send: Send) -> None:
        envelope = ErrorEnvelope(
            error=ErrorBody(
                code="PAYLOAD_TOO_LARGE",
                message=f"Request body exceeds the {self._max_bytes} byte upload limit",
                details=[],
                request_id=current_request_id() or "unknown",
            )
        )
        body = json.dumps(envelope.model_dump(mode="json")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})


async def read_upload_bounded(
    file: UploadFile, *, max_bytes: int, chunk_size: int = 1024 * 1024
) -> bytes:
    """Reads a FastAPI `UploadFile` in bounded chunks instead of one unbounded `await
    file.read()`. Does not itself raise on overflow — it stops accumulating once the running
    total exceeds `max_bytes` and returns what it has (bounded to `max_bytes + chunk_size`),
    leaving the existing per-upload business-rule size check (e.g.
    `OnboardingDocumentTooLargeError`) to produce its own specific error from the resulting
    length, unchanged."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            break
    return b"".join(chunks)
