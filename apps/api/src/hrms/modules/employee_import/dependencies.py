"""FastAPI `Depends()` wiring for the employee_import module's service."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.modules.employee_import.service import EmployeeImportService


def get_employee_import_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmployeeImportService:
    return EmployeeImportService(session, get_settings())
