"""FastAPI `Depends()` wiring for the Payroll module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.modules.payroll.service import (
    EmployeeSalaryService,
    SalaryComponentService,
    SalaryStructureService,
)


def get_salary_component_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SalaryComponentService:
    return SalaryComponentService(session)


def get_salary_structure_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SalaryStructureService:
    return SalaryStructureService(session)


def get_employee_salary_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmployeeSalaryService:
    return EmployeeSalaryService(session)
