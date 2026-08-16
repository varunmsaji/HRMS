"""FastAPI `Depends()` wiring for the employee module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.modules.employee.service import (
    EmployeeAssignmentService,
    EmployeeBankService,
    EmployeeCompensationService,
    EmployeeService,
    EmployeeStatutoryService,
    EmploymentService,
)


def get_employee_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmployeeService:
    return EmployeeService(session, get_settings())


def get_employment_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmploymentService:
    return EmploymentService(session, get_settings())


def get_employee_assignment_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmployeeAssignmentService:
    return EmployeeAssignmentService(session, get_settings())


def get_employee_compensation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmployeeCompensationService:
    return EmployeeCompensationService(session, get_settings())


def get_employee_statutory_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmployeeStatutoryService:
    return EmployeeStatutoryService(session, get_settings())


def get_employee_bank_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmployeeBankService:
    return EmployeeBankService(session, get_settings())
