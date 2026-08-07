import os

import pytest
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


@pytest.fixture(autouse=True)
async def reset_db_engine() -> None:
    yield
    await dispose_engine()
    get_settings.cache_clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
