"""Mirrors `tests/integration/modules/employee/conftest.py` — a small, independent conftest for
the onboarding module's own test directory rather than reaching into employee's/organisation's
(each module owns its own test fixtures, same boundary as the production code)."""

import pytest
import redis.asyncio as redis
from sqlalchemy import delete, select

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.models import Plan, PlanFeature, Subscription
from hrms.seed.plan_catalogue import PLAN_CATALOGUE, seed_plan_catalogue

_REGISTRATION_RATE_LIMIT_KEY = "ratelimit:auth:127.0.0.1"


@pytest.fixture(autouse=True)
async def _reset_registration_rate_limit() -> None:
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    await client.delete(_REGISTRATION_RATE_LIMIT_KEY)
    yield
    await client.delete(_REGISTRATION_RATE_LIMIT_KEY)
    await client.aclose()


@pytest.fixture(autouse=True)
async def _reset_onboarding_upload_rate_limit() -> None:
    """Batch C's `OnboardingUploadRateLimitMiddleware` (SEC-03) shares one Redis instance across
    the whole suite, and (like `_reset_registration_rate_limit` above) almost every test in this
    directory that uploads a document does so from the same `ASGITransport` client IP —
    `SCAN`-and-delete rather than a fixed key list because the token-keyed bucket's key changes
    (a SHA-256 hash) with every test's freshly issued onboarding token."""
    client = redis.from_url(get_settings().redis_url, decode_responses=True)

    async def _clear() -> None:
        async for key in client.scan_iter(match="ratelimit:onboarding_upload:*"):
            await client.delete(key)

    await _clear()
    yield
    await _clear()
    await client.aclose()


@pytest.fixture
async def seeded_plan_catalogue() -> None:
    factory = get_session_factory()
    codes = [code for code, *_ in PLAN_CATALOGUE]
    async with factory() as session:
        await seed_plan_catalogue(session)
        await session.commit()
    yield
    async with factory() as session:
        plan_ids = select(Plan.id).where(Plan.code.in_(codes))
        await session.execute(delete(Subscription).where(Subscription.plan_id.in_(plan_ids)))
        await session.execute(delete(PlanFeature).where(PlanFeature.plan_id.in_(plan_ids)))
        await session.execute(delete(Plan).where(Plan.code.in_(codes)))
        await session.commit()
