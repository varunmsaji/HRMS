import pytest
import redis.asyncio as redis
from sqlalchemy import delete, select

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.models import Plan, PlanFeature
from hrms.seed.plan_catalogue import PLAN_CATALOGUE, seed_plan_catalogue

_REGISTRATION_RATE_LIMIT_KEY = "ratelimit:auth:127.0.0.1"


@pytest.fixture(autouse=True)
async def _reset_registration_rate_limit() -> None:
    """Every request through `ASGITransport` shares client host 127.0.0.1 — without this,
    registration tests across this module would exhaust the real 10/min bucket and start
    failing each other with 429s."""
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    await client.delete(_REGISTRATION_RATE_LIMIT_KEY)
    yield
    await client.delete(_REGISTRATION_RATE_LIMIT_KEY)
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
        await session.execute(
            delete(PlanFeature).where(
                PlanFeature.plan_id.in_(select(Plan.id).where(Plan.code.in_(codes)))
            )
        )
        await session.execute(delete(Plan).where(Plan.code.in_(codes)))
        await session.commit()
