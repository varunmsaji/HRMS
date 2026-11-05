"""Create a shift with its schedule in one transaction, publishing it unless asked not to, so a
failure at any step leaves no half-made shift behind. Reuses the step-by-step service methods,
so the same validation and audit records apply."""

from typing import Any
from uuid import UUID

from hrms.modules.organisation.schemas import (
    ShiftCreate,
    ShiftSetup,
    ShiftSetupRead,
    ShiftVersionPublishRequest,
    ShiftVersionUpdate,
)
from hrms.modules.organisation.service import OrganisationService


async def setup_shift(
    service: OrganisationService,
    company_id: UUID,
    body: ShiftSetup,
    *,
    actor_user_id: UUID | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ShiftSetupRead:
    audit: dict[str, Any] = {
        "actor_user_id": actor_user_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
    }
    shift = await service.create_shift(company_id, ShiftCreate(name=body.name), **audit)
    # `create_shift` opens an empty draft; fill it rather than creating a second one.
    assert shift.draft_version_id is not None
    version = await service.update_shift_version(
        company_id,
        shift.id,
        shift.draft_version_id,
        ShiftVersionUpdate(**body.rules.model_dump(exclude_unset=True)),
        expected_version=1,
        **audit,
    )
    if body.publish:
        version = await service.publish_shift_version(
            company_id,
            shift.id,
            version.id,
            ShiftVersionPublishRequest(publish_reason=body.publish_reason),
            expected_version=version.version,
            **audit,
        )
    return ShiftSetupRead(shift=await service.get_shift(company_id, shift.id), version=version)
