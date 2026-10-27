"""Pure-query repository for the onboarding module — no business rules (Module Standard §2),
mirroring `employee/repository.py`'s own convention exactly."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.onboarding.models import (
    OnboardingCase,
    OnboardingDocument,
    OnboardingSectionReview,
    OnboardingToken,
)
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

    async def get_case_for_update(
        self, session: AsyncSession, *, company_id: UUID, case_id: UUID
    ) -> OnboardingCase | None:
        """`get_case` with a row lock (`SELECT ... FOR UPDATE`) held until the transaction ends.
        A concurrent transaction asking for the same row waits here, and when it is released it
        re-reads the row the winner committed (`populate_existing` refreshes any identity-map
        copy), so a state-machine check made after this call sees the real current status. This is
        what makes a one-shot transition such as activation single-winner across requests and
        across worker processes - the lock is in Postgres, not in Python (B12 / DEF-B11-02)."""
        stmt = (
            select(OnboardingCase)
            .where(
                OnboardingCase.id == case_id,
                OnboardingCase.company_id == company_id,
                OnboardingCase.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    def _list_conditions(self, *, company_id: UUID, status: str | None) -> list[Any]:
        """Shared WHERE predicates for `list_cases`/`count_cases` (FINDING-03) — kept identical
        between the two so pagination and the `total` it reports always agree."""
        conditions: list[Any] = [
            OnboardingCase.company_id == company_id,
            OnboardingCase.deleted_at.is_(None),
        ]
        if status is not None:
            conditions.append(OnboardingCase.status == status)
        return conditions

    async def list_cases(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[OnboardingCase]:
        """`limit=None` (the default) returns every case unpaginated — preserves the exact
        pre-FINDING-03 behavior for any non-HTTP caller. `GET /onboarding-cases` always passes an
        explicit `limit`/`offset`, applied at the SQL layer, never by slicing a fully-materialized
        Python list. `id` is a stable secondary key — `created_at` alone can tie for cases created
        in the same request burst (e.g. a bulk import), which would make page boundaries
        non-deterministic."""
        conditions = self._list_conditions(company_id=company_id, status=status)
        stmt = (
            select(OnboardingCase)
            .where(*conditions)
            .order_by(OnboardingCase.created_at.desc(), OnboardingCase.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list((await session.execute(stmt)).scalars().all())

    async def count_cases(
        self, session: AsyncSession, *, company_id: UUID, status: str | None = None
    ) -> int:
        """Same predicates as `list_cases`, no `ORDER BY`/`LIMIT` — the paired COUNT query for
        `GET /onboarding-cases`'s `pagination.total` (FINDING-03)."""
        conditions = self._list_conditions(company_id=company_id, status=status)
        stmt = select(func.count()).select_from(OnboardingCase).where(*conditions)
        return int((await session.execute(stmt)).scalar_one())

    async def get_active_case_by_email(
        self, session: AsyncSession, *, company_id: UUID, personal_email: str
    ) -> OnboardingCase | None:
        """The duplicate-prevention check (plan §13 Q5) — a case is "active" for this purpose if
        it is not yet in one of the terminal statuses.

        B12 (DEF-B11-03 / DEF-B11-05): the comparison is case-insensitive (`lower(personal_email)`),
        so rows stored before e-mails were normalised on write still match, and it returns the
        oldest match instead of requiring exactly one - a company that already holds duplicate
        rows must get a controlled "already exists" answer, not a `MultipleResultsFound` 500."""
        stmt = (
            select(OnboardingCase)
            .where(
                OnboardingCase.company_id == company_id,
                func.lower(OnboardingCase.personal_email) == personal_email.strip().lower(),
                OnboardingCase.deleted_at.is_(None),
                OnboardingCase.status.not_in(ONBOARDING_CASE_TERMINAL_STATUSES),
            )
            .order_by(OnboardingCase.created_at, OnboardingCase.id)
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()

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

    async def get_latest_for_case(
        self, session: AsyncSession, *, case_id: UUID
    ) -> OnboardingToken | None:
        """Admin-facing read (O6 detail view) — the most recently issued token row for a case,
        regardless of whether it's still live, so HR can see when the current/last link expires
        (or that it's already expired/revoked) without ever seeing the raw token itself, which
        this table never stores (module docstring)."""
        stmt = (
            select(OnboardingToken)
            .where(OnboardingToken.onboarding_case_id == case_id)
            .order_by(OnboardingToken.created_at.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


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


class OnboardingSectionReviewRepository:
    """No unique DB constraint on `(onboarding_case_id, section)` — `get_by_section`/`upsert`
    enforce "at most one row per section per case" at the application layer instead, mirroring
    `OnboardingCaseRepository.update_section`'s own "no DB constraint, service-enforced"
    convention for this module."""

    async def get_by_section(
        self, session: AsyncSession, *, company_id: UUID, case_id: UUID, section: str
    ) -> OnboardingSectionReview | None:
        stmt = select(OnboardingSectionReview).where(
            OnboardingSectionReview.company_id == company_id,
            OnboardingSectionReview.onboarding_case_id == case_id,
            OnboardingSectionReview.section == section,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_case(
        self, session: AsyncSession, *, company_id: UUID, case_id: UUID
    ) -> list[OnboardingSectionReview]:
        stmt = select(OnboardingSectionReview).where(
            OnboardingSectionReview.company_id == company_id,
            OnboardingSectionReview.onboarding_case_id == case_id,
        )
        return list((await session.execute(stmt)).scalars().all())

    async def upsert_review(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        case_id: UUID,
        section: str,
        status: str,
        rejection_reason: str | None,
        reviewed_by_user_id: UUID | None,
        now: datetime,
    ) -> OnboardingSectionReview:
        row = await self.get_by_section(
            session, company_id=company_id, case_id=case_id, section=section
        )
        if row is None:
            row = OnboardingSectionReview(
                id=uuid4(),
                company_id=company_id,
                onboarding_case_id=case_id,
                section=section,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        row.status = status
        row.rejection_reason = rejection_reason
        row.reviewed_by_user_id = reviewed_by_user_id
        row.reviewed_at = now
        row.updated_at = now
        await session.flush()
        return row

    async def reset_to_pending(
        self, session: AsyncSession, *, company_id: UUID, case_id: UUID, section: str, now: datetime
    ) -> None:
        """Called when the candidate edits a section HR had `REJECTED` (`OnboardingCaseService.
        update_section`) — clears the stale rejection reason and puts it back in HR's review
        queue. A no-op if the section has never been reviewed (`PENDING`) or is currently
        `VERIFIED` — `update_section` already rejects a write against a `VERIFIED` section before
        this could ever be called for one."""
        row = await self.get_by_section(
            session, company_id=company_id, case_id=case_id, section=section
        )
        if row is None or row.status != "REJECTED":
            return
        row.status = "PENDING"
        row.rejection_reason = None
        row.reviewed_by_user_id = None
        row.reviewed_at = None
        row.updated_at = now
        await session.flush()
