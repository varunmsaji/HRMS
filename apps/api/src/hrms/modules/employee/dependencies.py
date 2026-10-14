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
    EmployeeDependentService,
    EmployeeDocumentService,
    EmployeeEducationService,
    EmployeeExperienceService,
    EmployeeService,
    EmployeeStatutoryService,
    EmploymentService,
)


def get_employee_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeService:
    return EmployeeService(session, get_settings())


def get_employment_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmploymentService:
    return EmploymentService(session, get_settings())


def get_employee_assignment_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeAssignmentService:
    return EmployeeAssignmentService(session, get_settings())


def get_employee_compensation_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeCompensationService:
    return EmployeeCompensationService(session, get_settings())


def get_employee_statutory_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeStatutoryService:
    return EmployeeStatutoryService(session, get_settings())


def get_employee_bank_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeBankService:
    return EmployeeBankService(session, get_settings())


def get_employee_experience_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeExperienceService:
    return EmployeeExperienceService(session, get_settings())


def get_employee_education_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeEducationService:
    return EmployeeEducationService(session, get_settings())


def get_employee_dependent_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeDependentService:
    return EmployeeDependentService(session, get_settings())


def get_employee_document_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeDocumentService:
    return EmployeeDocumentService(session, get_settings())
