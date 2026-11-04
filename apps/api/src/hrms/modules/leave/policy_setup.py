"""Create a leave policy with its rules in one transaction, optionally publishing and assigning
it, so a failure at any step leaves nothing half-made. Reuses the same service methods as the
step-by-step routes, so the same validation and audit records apply."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.errors.base import ValidationError
from hrms.modules.leave.schemas import (
    LeavePolicyCreate,
    LeavePolicySetup,
    LeavePolicySetupRead,
    LeavePolicyVersionPublishRequest,
)
from hrms.modules.leave.service import LeavePolicyService


class LeavePolicySetupService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._leave = LeavePolicyService(session)

    async def setup(
        self,
        company_id: UUID,
        body: LeavePolicySetup,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LeavePolicySetupRead:
        if body.assign is not None and not body.publish:
            raise ValidationError(
                "A policy must be published to be assigned", code="POLICY_NOT_PUBLISHED"
            )
        audit = {"actor_user_id": actor_user_id, "ip_address": ip_address, "user_agent": user_agent}
        service = self._leave
        policy = await service.create_policy(
            company_id,
            LeavePolicyCreate(leave_type_id=body.leave_type_id, name=body.name),
            **audit,
        )
        version = await service.create_version(company_id, policy.id, body.rules, **audit)
        if body.publish:
            version = await service.publish_version(
                company_id,
                policy.id,
                version.id,
                LeavePolicyVersionPublishRequest(publish_reason=body.publish_reason),
                expected_version=version.version,
                **audit,
            )
        if body.assign is not None:
            assert version.effective_from is not None
            # Local import: `organisation` already reaches into `leave` the same way.
            from hrms.modules.organisation.policy_coverage import PolicyCoverageService
            from hrms.modules.organisation.schemas import (
                PolicyAssignmentBatch,
                PolicyAssignmentBatchChange,
            )

            await PolicyCoverageService(self._session).save_batch(
                company_id,
                PolicyAssignmentBatch(
                    scope_type=body.assign.scope_type,
                    scope_id=body.assign.scope_id,
                    effective_from=version.effective_from,
                    changes=[
                        PolicyAssignmentBatchChange(
                            policy_kind="LEAVE_POLICY",
                            policy_id=policy.id,
                            leave_type_id=body.leave_type_id,
                            expected_version=body.assign.expected_version,
                        )
                    ],
                ),
                **audit,
            )
        return LeavePolicySetupRead(policy=policy, version=version)
