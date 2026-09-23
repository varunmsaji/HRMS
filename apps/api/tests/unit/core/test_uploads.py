"""Unit tests for SEC-03's bounded-upload primitives (`hrms.core.uploads`,
docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md) — `MaxUploadSizeMiddleware` exercised directly
against a minimal Starlette app (no FastAPI/route/DB dependencies needed, since the behavior
under test is purely at the ASGI layer), `read_upload_bounded` exercised against a stub
`UploadFile`-shaped object. The full stack (real onboarding/employee-import endpoints, real
multipart bodies) is covered by the integration boundary tests in
`tests/integration/modules/onboarding/test_onboarding_upload_bounds.py`."""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from hrms.core.uploads import MaxUploadSizeMiddleware, read_upload_bounded

pytestmark = pytest.mark.asyncio


async def _echo(request: Any) -> JSONResponse:
    body = await request.body()
    return JSONResponse({"received": len(body)})


def _build_app(*, max_bytes: int, path_prefixes: tuple[str, ...] = ("/upload",)) -> Starlette:
    app = Starlette(
        routes=[
            Route("/upload", _echo, methods=["POST"]),
            Route("/other", _echo, methods=["POST"]),
        ]
    )
    app.add_middleware(MaxUploadSizeMiddleware, max_bytes=max_bytes, path_prefixes=path_prefixes)
    return app


class TestMaxUploadSizeMiddleware:
    async def test_below_maximum_is_accepted(self) -> None:
        app = _build_app(max_bytes=100)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/upload", content=b"x" * 50)
        assert response.status_code == 200
        assert response.json()["received"] == 50

    async def test_exactly_maximum_is_accepted(self) -> None:
        app = _build_app(max_bytes=100)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/upload", content=b"x" * 100)
        assert response.status_code == 200
        assert response.json()["received"] == 100

    async def test_one_byte_above_maximum_is_rejected(self) -> None:
        app = _build_app(max_bytes=100)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/upload", content=b"x" * 101)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    async def test_very_large_declared_content_length_is_rejected_without_crash(self) -> None:
        app = _build_app(max_bytes=100)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/upload", content=b"x" * (10 * 1024 * 1024))
        assert response.status_code == 413

    async def test_path_outside_prefixes_is_not_bounded(self) -> None:
        app = _build_app(max_bytes=10, path_prefixes=("/upload",))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/other", content=b"x" * 1000)
        assert response.status_code == 200
        assert response.json()["received"] == 1000

    async def test_missing_content_length_is_still_enforced_by_the_streaming_cap(self) -> None:
        # httpx sends a concrete Content-Length for `content=bytes`; to exercise the "trust
        # nothing but the actual bytes received" path we drive python-multipart-free streaming
        # explicitly, since bytes over the wire (not the declared header) is what the running
        # total is computed from regardless of whether a header was present.
        app = _build_app(max_bytes=10)

        async def _body_stream():
            for _ in range(5):
                yield b"123456"  # 5 * 6 = 30 bytes total, over the 10 byte cap

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/upload", content=_body_stream())
        assert response.status_code == 413


class _StubUploadFile:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class TestReadUploadBounded:
    async def test_reads_full_content_below_cap(self) -> None:
        result = await read_upload_bounded(_StubUploadFile(b"hello world"), max_bytes=1000)
        assert result == b"hello world"

    async def test_stops_accumulating_once_over_cap_bounded_overshoot(self) -> None:
        data = b"x" * 10_000
        result = await read_upload_bounded(_StubUploadFile(data), max_bytes=100, chunk_size=64)
        # Never reads the whole 10,000 bytes — stops within one chunk of the cap.
        assert len(result) <= 100 + 64

    async def test_exact_boundary_is_not_truncated(self) -> None:
        data = b"y" * 256
        result = await read_upload_bounded(_StubUploadFile(data), max_bytes=256, chunk_size=64)
        assert result == data
