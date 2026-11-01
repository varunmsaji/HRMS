"""Company face-enrollment policy and the single derived enrollment state.

The policy (`company_face_policy`) only says whether enrollment is a required onboarding step. It
is not enrollment data: an employee's enrollment stays in `employee_face_profile` and
`face_enrollment_window`, and `derive_enrollment_state` is the one place those two are turned into
the state the web, mobile and onboarding screens show. Nothing here marks anyone enrolled.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.modules.attendance.models import (
    CompanyFacePolicy,
    EmployeeFaceProfile,
    FaceEnrollmentWindow,
)
from hrms.modules.attendance.repository import FaceEnrollmentWindowRepository, FaceProfileRepository

EnrollmentState = Literal[
    "NOT_ENROLLED",  # no profile, no window
    "ENROLLMENT_AVAILABLE",  # a window is open: the employee may capture now
    "PENDING_APPROVAL",  # captured, waiting for HR
    "ENROLLED",  # approved: usable for face attendance
    "REJECTED",  # HR rejected the capture
    "REVOKED",  # enrollment withdrawn
]


def derive_enrollment_state(
    profile: EmployeeFaceProfile | None, window: FaceEnrollmentWindow | None
) -> EnrollmentState:
    """`window` is the OPEN row for the employee, if any; an expired one does not count."""
    if profile is not None:
        if profile.status == "ENROLLED":
            return "ENROLLED"
        if profile.status == "PENDING_APPROVAL":
            return "PENDING_APPROVAL"
    usable = window is not None and window.expires_at > datetime.now(UTC)
    if usable:
        return "ENROLLMENT_AVAILABLE"
    if profile is not None and profile.status == "REJECTED":
        return "REJECTED"
    if profile is not None and profile.status == "REVOKED":
        return "REVOKED"
    return "NOT_ENROLLED"


class FaceEnrollmentPolicyRead(BaseModel):
    require_enrollment_on_onboarding: bool


class FaceEnrollmentPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    require_enrollment_on_onboarding: bool


class EmployeeFaceOnboardingRead(BaseModel):
    """What onboarding shows for one employee. `requirement_met` is true when the company does
    not require enrollment, or the employee's profile is ENROLLED (HR-approved)."""

    required: bool
    state: EnrollmentState
    requirement_met: bool


class FacePolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._profiles = FaceProfileRepository()
        self._windows = FaceEnrollmentWindowRepository()
        self._audit = AuditService()

    async def is_required(self, company_id: UUID) -> bool:
        row = (
            await self._session.execute(
                select(CompanyFacePolicy.require_enrollment_on_onboarding).where(
                    CompanyFacePolicy.company_id == company_id
                )
            )
        ).scalar_one_or_none()
        return bool(row)

    async def get_policy(self, company_id: UUID) -> FaceEnrollmentPolicyRead:
        return FaceEnrollmentPolicyRead(
            require_enrollment_on_onboarding=await self.is_required(company_id)
        )

    async def set_policy(
        self,
        company_id: UUID,
        body: FaceEnrollmentPolicyUpdate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> FaceEnrollmentPolicyRead:
        row = (
            await self._session.execute(
                select(CompanyFacePolicy)
                .where(CompanyFacePolicy.company_id == company_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        before = (
            None
            if row is None
            else {"require_enrollment_on_onboarding": row.require_enrollment_on_onboarding}
        )
        if row is None:
            row = CompanyFacePolicy(
                id=uuid4(),
                company_id=company_id,
                require_enrollment_on_onboarding=body.require_enrollment_on_onboarding,
                updated_by_user_id=actor_user_id,
            )
            self._session.add(row)
        else:
            row.require_enrollment_on_onboarding = body.require_enrollment_on_onboarding
            row.updated_by_user_id = actor_user_id
        await self._session.flush()
        after = {"require_enrollment_on_onboarding": row.require_enrollment_on_onboarding}
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="FACE_ENROLLMENT_POLICY_UPDATED",
            entity_type="company_face_policy",
            entity_id=row.id,
            before=before,
            after=after,
            ip=ip_address,
            user_agent=user_agent,
        )
        return FaceEnrollmentPolicyRead(**after)

    async def onboarding_status(
        self, company_id: UUID, employee_id: UUID
    ) -> EmployeeFaceOnboardingRead:
        profile = await self._profiles.get_for_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        window = await self._windows.get_open(
            self._session, company_id=company_id, employee_id=employee_id
        )
        state = derive_enrollment_state(profile, window)
        required = await self.is_required(company_id)
        return EmployeeFaceOnboardingRead(
            required=required, state=state, requirement_met=(not required) or state == "ENROLLED"
        )
