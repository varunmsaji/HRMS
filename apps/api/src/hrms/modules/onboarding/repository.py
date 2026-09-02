"""Pure-query repository for the onboarding module — no business rules (Module Standard §2),
mirroring `employee/repository.py`'s own convention exactly."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.onboarding.models import OnboardingCase
from hrms.modules.onboarding.schemas import ONBOARDING_CASE_TERMINAL_STATUSES


class OnboardingCaseRepository:
    async def insert_case(self, session: AsyncSession, *, data: dict[str, Any]) -> OnboardingCase:
        row = OnboardingCase(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_case(
        self, session: AsyncSession, *, company_id: UUID, case_id: UUID
    ) -> OnboardingCase | None:
        stmt = select(OnboardingCase).where(
            OnboardingCase.id == case_id,
            OnboardingCase.company_id == company_id,
            OnboardingCase.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_cases(
        self, session: AsyncSession, *, company_id: UUID, status: str | None = None
    ) -> list[OnboardingCase]:
        conditions = [
            OnboardingCase.company_id == company_id,
            OnboardingCase.deleted_at.is_(None),
        ]
        if status is not None:
            conditions.append(OnboardingCase.status == status)
        stmt = select(OnboardingCase).where(*conditions).order_by(OnboardingCase.created_at.desc())
        return list((await session.execute(stmt)).scalars().all())

    async def get_active_case_by_email(
        self, session: AsyncSession, *, company_id: UUID, personal_email: str
    ) -> OnboardingCase | None:
        """The duplicate-prevention check (plan §13 Q5) — a case is "active" for this purpose if
        it is not yet in one of the terminal statuses."""
        stmt = select(OnboardingCase).where(
            OnboardingCase.company_id == company_id,
            OnboardingCase.personal_email == personal_email,
            OnboardingCase.deleted_at.is_(None),
            OnboardingCase.status.not_in(ONBOARDING_CASE_TERMINAL_STATUSES),
        )
        return (await session.execute(stmt)).scalar_one_or_none()
