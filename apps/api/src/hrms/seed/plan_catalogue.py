"""Seed the platform plan catalogue (global reference data, not tenant-scoped)."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.organisation.models import Plan, PlanFeature

SEAT_LIMIT_FEATURE_CODE = "EMPLOYEE_SEATS"

# (code, name, description, employee_seat_limit) — None means unlimited.
PLAN_CATALOGUE: tuple[tuple[str, str, str, int | None], ...] = (
    ("FREE", "Free", "Entry-level plan for evaluating the platform.", 5),
    ("STARTER", "Starter", "For small teams getting started with HR operations.", 25),
    ("PROFESSIONAL", "Professional", "For growing companies needing full HR coverage.", 100),
    ("ENTERPRISE", "Enterprise", "For large organisations with custom requirements.", None),
)


async def seed_plan_catalogue(session: AsyncSession) -> None:
    """Insert/update the platform plan catalogue (idempotent — upsert by `code`)."""
    now = datetime.now(UTC)

    for code, name, description, seat_limit in PLAN_CATALOGUE:
        plan = (await session.execute(select(Plan).where(Plan.code == code))).scalar_one_or_none()
        if plan is None:
            plan = Plan(
                id=uuid4(),
                code=code,
                name=name,
                description=description,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(plan)
            await session.flush()
        else:
            plan.name = name
            plan.description = description
            plan.is_active = True
            plan.updated_at = now

        feature = (
            await session.execute(
                select(PlanFeature).where(
                    PlanFeature.plan_id == plan.id,
                    PlanFeature.feature_code == SEAT_LIMIT_FEATURE_CODE,
                )
            )
        ).scalar_one_or_none()
        if feature is None:
            session.add(
                PlanFeature(
                    id=uuid4(),
                    plan_id=plan.id,
                    feature_code=SEAT_LIMIT_FEATURE_CODE,
                    is_enabled=True,
                    limit_value=seat_limit,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            feature.is_enabled = True
            feature.limit_value = seat_limit
            feature.updated_at = now

    await session.flush()
