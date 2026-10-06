"""FastAPI `Depends()` wiring for the attendance module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.core.storage import DocumentStorageService
from hrms.modules.attendance.face_service import (
    FaceEnrollmentService,
    FacePhotoStorage,
    FacePunchService,
)
from hrms.modules.attendance.face_verification import (
    FaceVerificationProvider,
    get_face_verification_provider,
)
from hrms.modules.attendance.service import (
    AttendanceDayService,
    AttendancePeriodService,
    AttendanceService,
    LeaveProjectionService,
    OvertimeRecordService,
    PunchService,
    RegularizationRequestService,
    ShiftRosterService,
)


def get_attendance_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> AttendanceService:
    return AttendanceService(session)


def get_punch_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> PunchService:
    return PunchService(session)


def get_attendance_day_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> AttendanceDayService:
    return AttendanceDayService(session)


def get_shift_roster_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> ShiftRosterService:
    return ShiftRosterService(session)


def get_regularization_request_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> RegularizationRequestService:
    return RegularizationRequestService(session)


def get_overtime_record_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> OvertimeRecordService:
    return OvertimeRecordService(session)


def get_attendance_period_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> AttendancePeriodService:
    return AttendancePeriodService(session)


def get_leave_projection_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> LeaveProjectionService:
    return LeaveProjectionService(session)


def get_face_provider() -> FaceVerificationProvider | None:
    return get_face_verification_provider(get_settings())


def get_face_photo_storage() -> FacePhotoStorage:
    return DocumentStorageService(get_settings())


def get_face_enrollment_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    provider: Annotated[FaceVerificationProvider | None, Depends(get_face_provider)],
    storage: Annotated[FacePhotoStorage, Depends(get_face_photo_storage)],
) -> FaceEnrollmentService:
    return FaceEnrollmentService(session, provider, get_settings(), storage)


def get_face_punch_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    provider: Annotated[FaceVerificationProvider | None, Depends(get_face_provider)],
) -> FacePunchService:
    return FacePunchService(session, provider, get_settings())
