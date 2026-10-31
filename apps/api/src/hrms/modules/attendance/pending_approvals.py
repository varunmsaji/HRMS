"""Cross-module seam: attendance requests waiting on an employee's reporting manager.

The employment module warns before a reporting-manager change that the employee's pending
requests will stay with their original approver. Regularization requests and overtime records
live here, so this module answers "which are waiting on a manager's decision?" as plain ids -
the caller never sees request data or touches this module's models.

Only the `MANAGER` stage counts. A request waiting on `HR` is not tied to the reporting manager,
and one already decided is not pending.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.attendance.models import AttendanceRegularizationRequest, OvertimeRecord


async def list_pending_manager_stage_ids(
    session: AsyncSession,
    company_id: UUID,
    employee_id: UUID,
    *,
    excluding_manager_id: UUID | None,
) -> dict[str, list[UUID]]:
    """`{"regularization": [...], "overtime": [...]}` - requests waiting on a manager whose
    snapshotted approver is anyone other than `excluding_manager_id` (`None`: the manager is
    being removed, so every such request counts)."""
    regularizations = (
        (
            await session.execute(
                select(AttendanceRegularizationRequest.id)
                .where(
                    AttendanceRegularizationRequest.company_id == company_id,
                    AttendanceRegularizationRequest.employee_id == employee_id,
                    AttendanceRegularizationRequest.status == "SUBMITTED",
                    AttendanceRegularizationRequest.approval_stage == "MANAGER",
                    AttendanceRegularizationRequest.resolved_approver_manager_id.is_distinct_from(
                        excluding_manager_id
                    ),
                )
                .order_by(AttendanceRegularizationRequest.id)
            )
        )
        .scalars()
        .all()
    )
    overtime = (
        (
            await session.execute(
                select(OvertimeRecord.id)
                .where(
                    OvertimeRecord.company_id == company_id,
                    OvertimeRecord.employee_id == employee_id,
                    OvertimeRecord.status == "PENDING",
                    OvertimeRecord.approval_stage == "MANAGER",
                    OvertimeRecord.resolved_approver_manager_id.is_distinct_from(
                        excluding_manager_id
                    ),
                )
                .order_by(OvertimeRecord.id)
            )
        )
        .scalars()
        .all()
    )
    return {"regularization": list(regularizations), "overtime": list(overtime)}
