import pytest
import redis.asyncio as redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.models import Plan, PlanFeature
from hrms.seed.bootstrap import clear_b1_seed, seed_b1_foundation
from hrms.seed.plan_catalogue import PLAN_CATALOGUE, seed_plan_catalogue

_REGISTRATION_RATE_LIMIT_KEY = "ratelimit:auth:127.0.0.1"


@pytest.fixture
async def seeded_db() -> None:
    factory = get_session_factory()
    async with factory() as session:
        await clear_b1_seed(session)
        await seed_b1_foundation(session)
        await session.commit()


@pytest.fixture
async def db_session(seeded_db: None) -> AsyncSession:
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _reset_registration_rate_limit() -> None:
    """Same convention as `tests/integration/modules/organisation/conftest.py` — every request
    through `ASGITransport` shares client host 127.0.0.1, so self-registration tests in this
    directory (`test_employee_jwt_linkage.py`) would otherwise exhaust the real 10/min bucket."""
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
