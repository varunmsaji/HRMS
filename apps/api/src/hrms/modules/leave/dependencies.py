"""FastAPI `Depends()` wiring for the Leave module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.modules.leave.service import (
    LeaveApplicationService,
    LeaveCombinationRuleService,
    LeaveLedgerService,
    LeavePolicyService,
    LeaveTypeService,
    LeaveYearSettingService,
    StatutoryLeaveMinimumService,
)


def get_leave_type_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> LeaveTypeService:
    return LeaveTypeService(session)


def get_leave_combination_rule_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> LeaveCombinationRuleService:
    return LeaveCombinationRuleService(session)


def get_leave_policy_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> LeavePolicyService:
    return LeavePolicyService(session)


def get_leave_ledger_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> LeaveLedgerService:
    return LeaveLedgerService(session)


def get_leave_application_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> LeaveApplicationService:
    return LeaveApplicationService(session)


def get_leave_year_setting_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> LeaveYearSettingService:
    return LeaveYearSettingService(session)


def get_statutory_leave_minimum_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> StatutoryLeaveMinimumService:
    return StatutoryLeaveMinimumService(session)
