"""FastAPI `Depends()` wiring for the Leave module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.modules.leave.service import (
    LeaveApplicationService,
    LeaveLedgerService,
    LeavePolicyService,
    LeaveTypeService,
)


def get_leave_type_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeaveTypeService:
    return LeaveTypeService(session)


def get_leave_policy_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeavePolicyService:
    return LeavePolicyService(session)


def get_leave_ledger_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeaveLedgerService:
    return LeaveLedgerService(session)


def get_leave_application_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeaveApplicationService:
    return LeaveApplicationService(session)
