"""Per-status onboarding case counts (`GET /v1/onboarding-cases/status-counts`) for the tab strip
on the onboarding list. Read-only; a status with no cases is simply absent."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class OnboardingStatusCounts(BaseModel):
    total: int
    by_status: dict[str, int]


async def onboarding_status_counts(
    session: AsyncSession, company_id: UUID, *, branch_ids: frozenset[UUID] | None = None
) -> OnboardingStatusCounts:
    """`branch_ids=None` counts every case; a set counts only cases in those branches (an empty
    set counts nothing, and a case with no branch is never counted)."""
    where = "company_id = :cid"
    params: dict[str, object] = {"cid": company_id}
    if branch_ids is not None:
        where += " AND branch_id = ANY(:bids)"
        params["bids"] = list(branch_ids)
    rows = (
        await session.execute(
            text(
                f"SELECT status, count(*) AS n FROM onboarding_case WHERE {where} GROUP BY status"
            ),  # noqa: S608
            params,
        )
    ).all()
    by_status = {r.status: int(r.n) for r in rows}
    return OnboardingStatusCounts(total=sum(by_status.values()), by_status=by_status)
