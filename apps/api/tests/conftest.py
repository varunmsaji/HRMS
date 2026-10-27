import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest
import redis.asyncio as redis
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("MAX_LEGAL_ENTITIES_PER_COMPANY", "0")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("JWT_ACCESS_SECRET", "test-access-secret-min-16-chars")
os.environ.setdefault("JWT_REFRESH_SECRET", "test-refresh-secret-min-16-chars")

# External-side-effect isolation. These are FORCED (not `setdefault`): a developer's
# `apps/api/.env` may select a real email provider, real Face++ credentials, or a broker DB
# holding a real backlog, and process env always wins over the dotenv file. Tests that need a
# specific provider construct `Settings(...)` explicitly or override the FastAPI dependency.
#
# The Celery broker/result backend go to a dedicated Redis DB (15 by default) so integration
# tests that enqueue work (employee imports) can never add to — or be mistaken for — the
# backlog in DB 0. `HRMS_TEST_CELERY_DB` lets a developer pick a different isolated DB.
# Platform console: production default is "new companies wait for approval". The rest of the suite
# registers companies and immediately writes to them, so it runs with approval off; the platform
# suite (tests/integration/modules/platform) switches it on explicitly.
os.environ["COMPANY_APPROVAL_REQUIRED"] = "false"
os.environ["EMAIL_PROVIDER"] = "logging"
# B13: the e-mail outbox delivers in the committing process right after commit under test, so the
# suites keep observing `email_log` without a Celery worker. The outbox tests choose their own mode.
os.environ["EMAIL_OUTBOX_DISPATCH"] = "inline"
# Local log files: the suite must never write into (or rotate) a developer's real `logs/`
# directory. File logging is off by default under test; the file-logging tests turn it on against
# a temporary directory they own (tests/unit/core/test_file_logging.py). To watch real module
# traffic land in the files, opt in explicitly with a throwaway directory:
#   HRMS_TEST_LOG_TO_FILES=true LOG_DIR=/tmp/hrms-test-logs pytest tests/integration/...
os.environ["LOG_TO_FILES"] = os.environ.get("HRMS_TEST_LOG_TO_FILES", "false")
os.environ["FACE_VERIFICATION_PROVIDER"] = "disabled"
os.environ["CELERY_BROKER_URL"] = urlunsplit(
    urlsplit(os.environ["REDIS_URL"])._replace(
        path="/" + os.environ.get("HRMS_TEST_CELERY_DB", "15")
    )
)
os.environ["CELERY_RESULT_BACKEND"] = os.environ["CELERY_BROKER_URL"]

# QA Phase 3: refuse to run against the shared dev stack unless explicitly acknowledged (or in
# CI). Evaluated after the defaults above so an unset DATABASE_URL (-> hrms_dev) is caught too.
from tests import isolation_guard

try:
    isolation_guard.check(os.environ)
except RuntimeError as _isolation_error:  # pragma: no cover - exercised by the unit test
    raise pytest.UsageError(str(_isolation_error)) from None

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


#: Endpoints that require an `Idempotency-Key` (LM-03). The shared `client` supplies a fresh key per
#: call when a test did not pass one, so the many tests that just *use* these endpoints stay about
#: their own subject. Tests of the idempotency contract itself pass explicit keys, or use a plain
#: `httpx.AsyncClient` to exercise the missing-header path.
_IDEMPOTENT_PATHS = (
    "/v1/leave-ledger/adjustments",
    "/v1/leave-ledger/encashments",
    "/v1/leave-applications",
    "/v1/payroll/adjustments",
)


class _AutoIdempotencyClient(AsyncClient):
    async def request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        if method.upper() == "POST" and str(url).split("?")[0] in _IDEMPOTENT_PATHS:
            headers = dict(kwargs.get("headers") or {})
            if not any(name.lower() == "idempotency-key" for name in headers):
                headers["Idempotency-Key"] = f"auto-{uuid.uuid4()}"
            kwargs["headers"] = headers
        return await super().request(method, url, **kwargs)


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with _AutoIdempotencyClient(transport=transport, base_url="http://test") as ac:
        yield ac
