"""Celery tasks owned by the Leave module — L3's monthly accrual (LEAVE_DECISION_LOG.md LD-06).

Two-tier fan-out, per `docs/architecture/04_Background_Job_Architecture.md` §3's "`company_id`
first argument on every task, no ambient request context" convention: `run_monthly_accrual`
(Beat-scheduled, no args) enumerates active companies and dispatches one `accrue_company` task
per company, so one tenant's failure/retry never blocks another's. Tasks are sync (Celery's
default), each bridging into this codebase's async session/service layer via `asyncio.run` —
there is no prior async-task precedent here to mirror; `health.ping` takes no arguments and opens
no DB session.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from hrms.core.celery_app import celery_app
from hrms.core.db.models.identity import Company
from hrms.core.db.session import session_scope


async def _list_active_company_ids() -> list[UUID]:
    async with session_scope() as session:
        stmt = select(Company.id).where(Company.status.in_(("TRIAL", "ACTIVE")))
        return list((await session.execute(stmt)).scalars().all())


async def _accrue_company_async(company_id: UUID) -> int:
    from hrms.modules.leave.service import LeaveAccrualService

    async with session_scope(company_id=str(company_id)) as session:
        return await LeaveAccrualService(session).run_for_company(
            company_id, as_of=datetime.now(UTC).date()
        )


@celery_app.task(name="leave.accrue_company")  # type: ignore[untyped-decorator]
def accrue_company(company_id: str) -> int:
    return asyncio.run(_accrue_company_async(UUID(company_id)))


@celery_app.task(name="leave.run_monthly_accrual")  # type: ignore[untyped-decorator]
def run_monthly_accrual() -> int:
    """Beat-scheduled entrypoint (monthly cron, `celery_app.py`'s `beat_schedule`). Fans out one
    `accrue_company` task per active company rather than accruing inline — keeps each tenant's
    run independently retryable."""
    company_ids = asyncio.run(_list_active_company_ids())
    for company_id in company_ids:
        accrue_company.delay(str(company_id))
    return len(company_ids)
