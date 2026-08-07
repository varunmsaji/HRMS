import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session_factory
from hrms.seed.bootstrap import clear_b1_seed, seed_b1_foundation


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
