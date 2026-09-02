"""Public, unauthenticated HTTP routes for the onboarding module — O2 (token-authenticated case
read + section write only; document upload is O5, submit/accept-policies land with the wizard
UI in O4).

No JWT, no `X-Company-Id` header, no `require_permission` — the single security boundary for
this entire router is `get_onboarding_case_from_token` (plan §5,
`hrms.modules.onboarding.dependencies`), which every route below takes as a required dependency.
No route accepts a `company_id` or `case_id` as a client-supplied parameter — both always come
from the resolved `OnboardingTokenContext`, never from the request."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from hrms.core.tenancy.context import current_request_id
from hrms.modules.identity.schemas import build_meta
from hrms.modules.onboarding.dependencies import (
    get_onboarding_case_from_token,
    get_onboarding_case_service,
)
from hrms.modules.onboarding.exceptions import InvalidOnboardingSectionError
from hrms.modules.onboarding.schemas import SECTION_SCHEMAS, PublicOnboardingCaseRead
from hrms.modules.onboarding.service import OnboardingCaseService, OnboardingTokenContext
from hrms.shared.pagination import DataEnvelope

router = APIRouter(prefix="/public/onboarding", tags=["onboarding-public"])


@router.get("/{token}", status_code=status.HTTP_200_OK)
async def get_public_onboarding_case(
    ctx: Annotated[OnboardingTokenContext, Depends(get_onboarding_case_from_token)],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
) -> DataEnvelope[PublicOnboardingCaseRead]:
    data = await service.get_public_case(ctx.company_id, ctx.case_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/{token}/sections/{section}", status_code=status.HTTP_200_OK)
async def update_onboarding_section(
    section: str,
    request: Request,
    ctx: Annotated[OnboardingTokenContext, Depends(get_onboarding_case_from_token)],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
) -> DataEnvelope[PublicOnboardingCaseRead]:
    section_schema = SECTION_SCHEMAS.get(section)
    if section_schema is None:
        raise InvalidOnboardingSectionError(section)

    raw_body = await request.json()
    if not isinstance(raw_body, dict):
        raise RequestValidationError(
            [{"loc": ("body",), "msg": "value is not a valid dict", "type": "type_error.dict"}]
        )
    try:
        validated = section_schema(**raw_body)
    except PydanticValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    data = await service.update_section(
        ctx.company_id, ctx.case_id, section, validated.model_dump(mode="json")
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
