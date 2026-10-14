"""Celery tasks owned by employee_import.

Same sync-wrapper-over-async pattern as `leave/tasks.py::accrue_company` — the only prior Celery
task in this codebase, itself Beat-triggered only. This is the first task invoked synchronously
from a router (`service.py::EmployeeImportService.create_batch` calls `.delay(...)` right after
committing the batch row). Queue is `reports_exports`, per
`docs/product/11_Background_Job_Architecture.md` §1, which already names "bulk imports" as
belonging there.

No automatic Celery retry (`max_retries=0`, the decorator default): this pipeline is
create-only, so a blind retry after a partial failure risks duplicate employees for rows that
already succeeded. A stuck/failed batch is inspected via `GET /employee-imports/{id}/errors` and
the remaining rows re-submitted as a fresh, smaller import.
"""

import asyncio
from uuid import UUID

from hrms.core.celery_app import celery_app
from hrms.core.db.session import session_scope


async def _process_batch_async(
    company_id: UUID, batch_id: UUID, actor_user_id: UUID | None
) -> None:
    from hrms.modules.employee_import.service import EmployeeImportService

    async with session_scope(company_id=str(company_id)) as session:
        await EmployeeImportService(session).process_batch(company_id, batch_id, actor_user_id)


#: Hard limit only, deliberately no soft limit: a soft limit would raise mid-batch and leave a
#: partly imported batch in a state the import semantics do not define. The hard limit only frees
#: a worker slot from a genuinely hung run (the batch then stays PROCESSING, which the
#: stuck-import check in the runbook detects) — before this, a hang held the slot forever.
@celery_app.task(name="employee_import.process_batch", queue="reports_exports", time_limit=3600)  # type: ignore[untyped-decorator]
def process_batch(company_id: str, batch_id: str, actor_user_id: str | None) -> None:
    resolved_actor_id = UUID(actor_user_id) if actor_user_id is not None else None
    asyncio.run(_process_batch_async(UUID(company_id), UUID(batch_id), resolved_actor_id))
