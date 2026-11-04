"""Create an attendance, overtime or regularization policy with its rules in one transaction,
optionally publishing and assigning it, so a failure at any step leaves nothing half-made. Reuses
the same service methods as the step-by-step routes, so the same validation and audit records
apply."""

from datetime import date
from typing import Annotated, Any
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
    OvertimePolicyCreate,
    OvertimePolicySetup,
    OvertimePolicySetupRead,
    OvertimePolicyVersionPublishRequest,
    PolicySetupAssign,
    RegularizationPolicyCreate,
    RegularizationPolicySetup,
    RegularizationPolicySetupRead,
    RegularizationPolicyVersionPublishRequest,
)
from hrms.modules.attendance.service import AttendanceService


class AttendancePolicySetupService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._attendance = AttendanceService(session)

    async def _assign(
        self,
        company_id: UUID,
        policy_kind: str,
        policy_id: UUID,
        effective_from: date,
        assign: PolicySetupAssign,
        audit: dict[str, Any],
    ) -> None:
        # Local import: `organisation` already reaches into `attendance` the same way.
        from hrms.modules.organisation.policy_coverage import PolicyCoverageService
        from hrms.modules.organisation.schemas import (
            PolicyAssignmentBatch,
            PolicyAssignmentBatchChange,
        )

        await PolicyCoverageService(self._session).save_batch(
            company_id,
            PolicyAssignmentBatch(
                scope_type=assign.scope_type,
                scope_id=assign.scope_id,
                effective_from=effective_from,
                changes=[
                    PolicyAssignmentBatchChange(
                        policy_kind=policy_kind,
                        policy_id=policy_id,
                        expected_version=assign.expected_version,
                    )
                ],
            ),
            **audit,
        )

    @staticmethod
    def _check(publish: bool, assign: PolicySetupAssign | None) -> None:
        if assign is not None and not publish:
            raise ValidationError(
                "A policy must be published to be assigned", code="POLICY_NOT_PUBLISHED"
            )

    async def setup(
        self,
        company_id: UUID,
        body: AttendancePolicySetup,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendancePolicySetupRead:
        self._check(body.publish, body.assign)
        audit: dict[str, Any] = {
            "actor_user_id": actor_user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }
        service = self._attendance
        policy = await service.create_attendance_policy(
            company_id, AttendancePolicyCreate(name=body.name), **audit
        )
        version = await service.create_attendance_policy_version(
            company_id, policy.id, body.rules, **audit
        )
        if body.publish:
            version = await service.publish_attendance_policy_version(
                company_id,
                policy.id,
                version.id,
                AttendancePolicyVersionPublishRequest(publish_reason=body.publish_reason),
                expected_version=version.version,
                **audit,
            )
        if body.assign is not None:
            assert version.effective_from is not None
            await self._assign(
                company_id,
                "ATTENDANCE_POLICY",
                policy.id,
                version.effective_from,
                body.assign,
                audit,
            )
        return AttendancePolicySetupRead(policy=policy, version=version)

    async def setup_overtime(
        self,
        company_id: UUID,
        body: OvertimePolicySetup,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OvertimePolicySetupRead:
        self._check(body.publish, body.assign)
        audit: dict[str, Any] = {
            "actor_user_id": actor_user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }
        service = self._attendance
        policy = await service.create_overtime_policy(
            company_id, OvertimePolicyCreate(name=body.name), **audit
        )
        version = await service.create_overtime_policy_version(
            company_id, policy.id, body.rules, **audit
        )
        if body.publish:
            version = await service.publish_overtime_policy_version(
                company_id,
                policy.id,
                version.id,
                OvertimePolicyVersionPublishRequest(publish_reason=body.publish_reason),
                expected_version=version.version,
                **audit,
            )
        if body.assign is not None:
            assert version.effective_from is not None
            await self._assign(
                company_id, "OVERTIME_POLICY", policy.id, version.effective_from, body.assign, audit
            )
        return OvertimePolicySetupRead(policy=policy, version=version)

    async def setup_regularization(
        self,
        company_id: UUID,
        body: RegularizationPolicySetup,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> RegularizationPolicySetupRead:
        self._check(body.publish, body.assign)
        audit: dict[str, Any] = {
            "actor_user_id": actor_user_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }
        service = self._attendance
        policy = await service.create_regularization_policy(
            company_id, RegularizationPolicyCreate(name=body.name), **audit
        )
        version = await service.create_regularization_policy_version(
            company_id, policy.id, body.rules, **audit
        )
        if body.publish:
            version = await service.publish_regularization_policy_version(
                company_id,
                policy.id,
                version.id,
                RegularizationPolicyVersionPublishRequest(publish_reason=body.publish_reason),
                expected_version=version.version,
                **audit,
            )
        if body.assign is not None:
            assert version.effective_from is not None
            await self._assign(
                company_id,
                "REGULARIZATION_POLICY",
                policy.id,
                version.effective_from,
                body.assign,
                audit,
            )
        return RegularizationPolicySetupRead(policy=policy, version=version)


def get_attendance_policy_setup_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> AttendancePolicySetupService:
    return AttendancePolicySetupService(session)
