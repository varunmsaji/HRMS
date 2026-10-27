"""Celery tasks owned by the employee module.

`employee.run_termination_access_sweep` is the Beat-scheduled safety net for future-dated
terminations: HR records a last working day ahead of time, the employee keeps access through
that day, and this sweep ends their login once the day has passed in the company's own timezone.
An immediate termination revokes access in the request itself and never waits for this task.

Same two-tier fan-out as the leave and attendance jobs: a no-arg entrypoint enumerates active
companies and dispatches one per-company task, so one tenant's failure never blocks another's.
Idempotent — an account already revoked is not selected again, so a repeated or overlapping run
changes nothing and writes no second audit event.
"""

from uuid import UUID

from sqlalchemy import select

from hrms.core.celery_app import (
    COMPANY_TASK_LIMITS,
    FANOUT_TASK_LIMITS,
    celery_app,
    dispatch_per_company,
)
from hrms.core.db.models.identity import Company
from hrms.core.db.session import run_task, session_scope


async def _list_active_company_ids() -> list[UUID]:
    async with session_scope() as session:
        stmt = select(Company.id).where(Company.status.in_(("TRIAL", "ACTIVE")))
        return list((await session.execute(stmt)).scalars().all())


async def _enforce_company_async(company_id: UUID) -> int:
    from hrms.modules.employee.service import EmploymentService

    async with session_scope(company_id=str(company_id)) as session:
        return await EmploymentService(session).enforce_elapsed_terminations(company_id)


@celery_app.task(name="employee.enforce_terminations_company", **COMPANY_TASK_LIMITS)  # type: ignore[untyped-decorator]
def enforce_terminations_company(company_id: str) -> int:
    return run_task(_enforce_company_async(UUID(company_id)))


@celery_app.task(name="employee.run_termination_access_sweep", **FANOUT_TASK_LIMITS)  # type: ignore[untyped-decorator]
def run_termination_access_sweep() -> int:
    company_ids = run_task(_list_active_company_ids())
    return dispatch_per_company(enforce_terminations_company, company_ids)
