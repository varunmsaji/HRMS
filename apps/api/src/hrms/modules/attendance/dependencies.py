"""FastAPI `Depends()` wiring for the attendance module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.modules.attendance.service import (
    AttendanceDayService,
    AttendanceService,
    PunchService,
    RegularizationRequestService,
    ShiftRosterService,
)


def get_attendance_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttendanceService:
    return AttendanceService(session)


def get_punch_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PunchService:
    return PunchService(session)


def get_attendance_day_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttendanceDayService:
    return AttendanceDayService(session)


def get_shift_roster_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ShiftRosterService:
    return ShiftRosterService(session)


def get_regularization_request_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RegularizationRequestService:
    return RegularizationRequestService(session)
