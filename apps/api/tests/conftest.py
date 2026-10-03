import os

import pytest
import redis.asyncio as redis
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("JWT_ACCESS_SECRET", "test-access-secret-min-16-chars")
os.environ.setdefault("JWT_REFRESH_SECRET", "test-refresh-secret-min-16-chars")

from entrypoints.api import app

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine
from hrms.shared.rate_limit import close_rate_limiter


@pytest.fixture(autouse=True)
async def reset_db_engine() -> None:
    yield
    await dispose_engine()
    await close_rate_limiter()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _reset_credential_rate_limits() -> None:
    """`/auth/login` and `/auth/token/refresh` (SEC-02) are now rate-limited, and — unlike the
    directory-scoped registration bucket reset in `tests/integration/auth/conftest.py` — both
    endpoints are exercised from almost every integration test in the suite (most via an
    `admin_tokens`/`viewer_tokens`-style login fixture), all through the same ASGITransport
    client IP and a small set of reused seed emails. Without a reset between every test, those
    shared "login"/"token_refresh" buckets would trip well before any single test intends to
    exercise the limit itself. `SCAN`-and-delete (rather than a fixed key list) so this stays
    correct regardless of which email or IP a given test happens to use."""
    client = redis.from_url(get_settings().redis_url, decode_responses=True)

    async def _clear() -> None:
        for pattern in (
            "ratelimit:login:*",
            "ratelimit:token_refresh:*",
            # Same reasoning: these buckets (10/min per IP) outlive a pytest run, so a rerun
            # within a minute of the previous one 429s on its very first request.
            "ratelimit:email_verification:*",
            "ratelimit:auth:*",
        ):
            async for key in client.scan_iter(match=pattern):
                await client.delete(key)

    await _clear()
    yield
    await _clear()
    await client.aclose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
