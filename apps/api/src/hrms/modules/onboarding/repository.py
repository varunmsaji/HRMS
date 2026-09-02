"""Pure-query repository for the onboarding module — no business rules (Module Standard §2),
mirroring `employee/repository.py`'s own convention exactly."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.onboarding.models import OnboardingCase, OnboardingDocument, OnboardingToken
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

    async def update_section(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        case_id: UUID,
        column: str,
        value: dict[str, Any],
        now: datetime,
    ) -> OnboardingCase | None:
        """`column` is one of `ONBOARDING_SECTION_NAMES` — always caller-controlled from a fixed
        allowlist (`SECTION_SCHEMAS` keys), never client input, so building the `setattr` target
        dynamically here does not open a mass-assignment hole."""
        case = await self.get_case(session, company_id=company_id, case_id=case_id)
        if case is None:
            return None
        setattr(case, column, value)
        case.updated_at = now
        await session.flush()
        return case

    async def set_status(
        self, session: AsyncSession, *, case: OnboardingCase, status: str, now: datetime
    ) -> None:
        case.status = status
        case.updated_at = now
        await session.flush()


class OnboardingTokenRepository:
    """Deliberately **not** RLS-scoped by `company_id` in any query here — `onboarding_token`
    itself carries no RLS policy (module docstring, `models.OnboardingToken`), mirroring
    `refresh_token`'s own pre-tenant-context shape (`scripts/sql/001_init_schema.sql`): a public,
    unauthenticated caller has no company context yet, so the *only* thing that can look up a
    token is its hash, before any tenant scope exists to filter by."""

    async def insert_token(self, session: AsyncSession, *, data: dict[str, Any]) -> OnboardingToken:
        row = OnboardingToken(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_by_hash(
        self, session: AsyncSession, *, token_hash: str
    ) -> OnboardingToken | None:
        stmt = select(OnboardingToken).where(OnboardingToken.token_hash == token_hash)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def revoke_live_tokens_for_case(
        self, session: AsyncSession, *, case_id: UUID, now: datetime
    ) -> None:
        stmt = select(OnboardingToken).where(
            OnboardingToken.onboarding_case_id == case_id,
            OnboardingToken.revoked_at.is_(None),
        )
        live_tokens = (await session.execute(stmt)).scalars().all()
        for token in live_tokens:
            token.revoked_at = now
        if live_tokens:
            await session.flush()

    async def mark_used_first_at(
        self, session: AsyncSession, *, token: OnboardingToken, now: datetime
    ) -> None:
        if token.used_first_at is None:
            token.used_first_at = now
            await session.flush()


class OnboardingDocumentRepository:
    async def insert_document(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> OnboardingDocument:
        row = OnboardingDocument(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_document(
        self, session: AsyncSession, *, company_id: UUID, case_id: UUID, document_id: UUID
    ) -> OnboardingDocument | None:
        stmt = select(OnboardingDocument).where(
            OnboardingDocument.id == document_id,
            OnboardingDocument.onboarding_case_id == case_id,
            OnboardingDocument.company_id == company_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_documents(
        self, session: AsyncSession, *, company_id: UUID, case_id: UUID
    ) -> list[OnboardingDocument]:
        stmt = (
            select(OnboardingDocument)
            .where(
                OnboardingDocument.company_id == company_id,
                OnboardingDocument.onboarding_case_id == case_id,
            )
            .order_by(OnboardingDocument.uploaded_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def delete_document(self, session: AsyncSession, *, document: OnboardingDocument) -> None:
        await session.delete(document)
        await session.flush()

    async def update_review(
        self,
        session: AsyncSession,
        *,
        document: OnboardingDocument,
        status: str,
        rejection_reason: str | None,
        verified_by_user_id: UUID | None,
        now: datetime,
    ) -> OnboardingDocument:
        document.status = status
        document.rejection_reason = rejection_reason
        document.verified_by_user_id = verified_by_user_id
        document.verified_at = now
        document.updated_at = now
        await session.flush()
        return document
