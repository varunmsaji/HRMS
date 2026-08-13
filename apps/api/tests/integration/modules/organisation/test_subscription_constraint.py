from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from hrms.core.db.models.identity import Company
from hrms.core.db.session import get_session_factory, session_scope
from hrms.modules.organisation.models import Plan, Subscription


@pytest.fixture
async def company_and_plan() -> AsyncGenerator[tuple[Company, Plan], None]:
    now = datetime.now(UTC)
    company = Company(id=uuid4(), name="Subscription Test Co", created_at=now, updated_at=now)
    plan = Plan(
        id=uuid4(),
        code=f"TEST_{uuid4().hex[:8].upper()}",
        name="Test Plan",
        created_at=now,
        updated_at=now,
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add_all([company, plan])
        await session.commit()

    yield company, plan

    async with factory() as session:
        await session.execute(delete(Subscription).where(Subscription.company_id == company.id))
        await session.execute(delete(Plan).where(Plan.id == plan.id))
        await session.execute(delete(Company).where(Company.id == company.id))
        await session.commit()


@pytest.mark.asyncio
async def test_subscription_partial_unique_constraint(
    company_and_plan: tuple[Company, Plan],
) -> None:
    company, plan = company_and_plan
    now = datetime.now(UTC)

    async with session_scope(company_id=str(company.id)) as session:
        session.add(
            Subscription(
                id=uuid4(),
                company_id=company.id,
                plan_id=plan.id,
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )

    with pytest.raises(IntegrityError):
        async with session_scope(company_id=str(company.id)) as session:
            session.add(
                Subscription(
                    id=uuid4(),
                    company_id=company.id,
                    plan_id=plan.id,
                    status="TRIALING",
                    created_at=now,
                    updated_at=now,
                )
            )


@pytest.mark.asyncio
async def test_subscription_allows_new_row_after_prior_is_terminal(
    company_and_plan: tuple[Company, Plan],
) -> None:
    company, plan = company_and_plan
    now = datetime.now(UTC)

    async with session_scope(company_id=str(company.id)) as session:
        session.add(
            Subscription(
                id=uuid4(),
                company_id=company.id,
                plan_id=plan.id,
                status="CANCELED",
                created_at=now,
                updated_at=now,
            )
        )

    async with session_scope(company_id=str(company.id)) as session:
        session.add(
            Subscription(
                id=uuid4(),
                company_id=company.id,
                plan_id=plan.id,
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
