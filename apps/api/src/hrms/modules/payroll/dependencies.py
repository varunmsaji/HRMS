"""FastAPI `Depends()` wiring for the Payroll module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.modules.payroll.service import (
    EmployeeSalaryService,
    PayAdjustmentService,
    PayrollSettingService,
    PayRunService,
    PayslipService,
    SalaryComponentService,
    SalaryStructureService,
    StatutoryRateService,
)


def get_salary_component_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> SalaryComponentService:
    return SalaryComponentService(session)


def get_salary_structure_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> SalaryStructureService:
    return SalaryStructureService(session)


def get_employee_salary_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeSalaryService:
    return EmployeeSalaryService(session)


def get_payroll_setting_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> PayrollSettingService:
    return PayrollSettingService(session)


def get_pay_run_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> PayRunService:
    return PayRunService(session)


def get_statutory_rate_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> StatutoryRateService:
    return StatutoryRateService(session)


def get_payslip_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> PayslipService:
    return PayslipService(session)


def get_pay_adjustment_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> PayAdjustmentService:
    return PayAdjustmentService(session)
