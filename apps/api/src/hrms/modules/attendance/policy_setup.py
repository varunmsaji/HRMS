"""Create an attendance policy with its rules in one transaction, optionally publishing and
assigning it, so a failure at any step leaves nothing half-made. Reuses the same service methods
as the step-by-step routes, so the same validation and audit records apply."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.schemas import (
    AttendancePolicyCreate,
    AttendancePolicySetup,
    AttendancePolicySetupRead,
    AttendancePolicyVersionPublishRequest,
)
from hrms.modules.attendance.service import AttendanceService


class AttendancePolicySetupService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._attendance = AttendanceService(session)

    async def setup(
        self,
        company_id: UUID,
        body: AttendancePolicySetup,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePolicySetupRead:
        if body.assign is not None and not body.publish:
            raise ValidationError(
                "A policy must be published to be assigned", code="POLICY_NOT_PUBLISHED"
            )
        audit = {"actor_user_id": actor_user_id, "ip_address": ip_address, "user_agent": user_agent}
        policy = await self._attendance.create_attendance_policy(
            company_id, AttendancePolicyCreate(name=body.name), **audit
        )
        version = await self._attendance.create_attendance_policy_version(
            company_id, policy.id, body.rules, **audit
        )
        if body.publish:
            version = await self._attendance.publish_attendance_policy_version(
                company_id,
                policy.id,
                version.id,
                AttendancePolicyVersionPublishRequest(publish_reason=body.publish_reason),
                expected_version=version.version,
                **audit,
            )
        if body.assign is not None:
            # Local import: `organisation` already reaches into `attendance` the same way.
            from hrms.modules.organisation.policy_coverage import PolicyCoverageService
            from hrms.modules.organisation.schemas import (
                PolicyAssignmentBatch,
                PolicyAssignmentBatchChange,
            )

            assert version.effective_from is not None
            await PolicyCoverageService(self._session).save_batch(
                company_id,
                PolicyAssignmentBatch(
                    scope_type=body.assign.scope_type,
                    scope_id=body.assign.scope_id,
                    effective_from=version.effective_from,
                    changes=[
                        PolicyAssignmentBatchChange(
                            policy_kind="ATTENDANCE_POLICY",
                            policy_id=policy.id,
                            expected_version=body.assign.expected_version,
                        )
                    ],
                ),
                **audit,
            )
        return AttendancePolicySetupRead(policy=policy, version=version)


def get_attendance_policy_setup_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> AttendancePolicySetupService:
    return AttendancePolicySetupService(session)
