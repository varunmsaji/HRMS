import pytest
from sqlalchemy import delete, func, select

from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.models import Plan, PlanFeature
from hrms.seed.plan_catalogue import PLAN_CATALOGUE, seed_plan_catalogue


@pytest.fixture
async def clean_plan_catalogue() -> None:
    factory = get_session_factory()
    codes = [code for code, *_ in PLAN_CATALOGUE]
    async with factory() as session:
        await session.execute(
            delete(PlanFeature).where(
                PlanFeature.plan_id.in_(select(Plan.id).where(Plan.code.in_(codes)))
            )
        )
        await session.execute(delete(Plan).where(Plan.code.in_(codes)))
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


@pytest.mark.asyncio
async def test_seed_plan_catalogue_is_idempotent(clean_plan_catalogue: None) -> None:
    factory = get_session_factory()
    codes = [code for code, *_ in PLAN_CATALOGUE]

    async with factory() as session:
        await seed_plan_catalogue(session)
        await session.commit()

    async with factory() as session:
        await seed_plan_catalogue(session)
        await session.commit()

    async with factory() as session:
        plan_count = (
            await session.execute(
                select(func.count()).select_from(Plan).where(Plan.code.in_(codes))
            )
        ).scalar_one()
        assert plan_count == len(PLAN_CATALOGUE)

        feature_count = (
            await session.execute(
                select(func.count())
                .select_from(PlanFeature)
                .where(PlanFeature.plan_id.in_(select(Plan.id).where(Plan.code.in_(codes))))
            )
        ).scalar_one()
        assert feature_count == len(PLAN_CATALOGUE)
