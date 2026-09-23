"""Public, unauthenticated HTTP routes for the onboarding module — O2 (token-authenticated case
read + section write), O4's own `submit` (the wizard's completion step), and O5 (document
upload/list/delete — review is admin-only, `hrms.modules.onboarding.router`). `accept-policies`
is not built — no wizard step consumes it yet.

No JWT, no `X-Company-Id` header, no `require_permission` — the single security boundary for
this entire router is `get_onboarding_case_from_token` (plan §5,
`hrms.modules.onboarding.dependencies`), which every route below takes as a required dependency.
No route accepts a `company_id` or `case_id` as a client-supplied parameter — both always come
from the resolved `OnboardingTokenContext`, never from the request."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

from hrms.core.tenancy.context import current_request_id
from hrms.core.uploads import read_upload_bounded
from hrms.modules.identity.schemas import build_meta
from hrms.modules.onboarding.dependencies import (
    get_onboarding_case_from_token,
    get_onboarding_case_service,
    get_onboarding_document_service,
)
from hrms.modules.onboarding.exceptions import InvalidOnboardingSectionError
from hrms.modules.onboarding.schemas import (
    ONBOARDING_DOCUMENT_MAX_SIZE_BYTES,
    SECTION_SCHEMAS,
    OnboardingDocumentRead,
    PublicOnboardingCaseRead,
)
from hrms.modules.onboarding.service import (
    OnboardingCaseService,
    OnboardingDocumentService,
    OnboardingTokenContext,
)
from hrms.shared.pagination import DataEnvelope, ListEnvelope

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


@router.post("/{token}/submit", status_code=status.HTTP_200_OK)
async def submit_onboarding_case(
    ctx: Annotated[OnboardingTokenContext, Depends(get_onboarding_case_from_token)],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
) -> DataEnvelope[PublicOnboardingCaseRead]:
    data = await service.submit_case(ctx.company_id, ctx.case_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/{token}/documents", status_code=status.HTTP_201_CREATED)
async def upload_onboarding_document(
    ctx: Annotated[OnboardingTokenContext, Depends(get_onboarding_case_from_token)],
    service: Annotated[OnboardingDocumentService, Depends(get_onboarding_document_service)],
    document_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> DataEnvelope[OnboardingDocumentRead]:
    # SEC-03 — bounded read, not one unbounded `await file.read()`; `MaxUploadSizeMiddleware`
    # (hrms.core.uploads, wired in app.py) is the primary defense stopping an oversized body
    # during transport, this is the defense-in-depth layer that also stops the handler itself
    # from ever materializing more than the size cap into one `bytes` object.
    body = await read_upload_bounded(file, max_bytes=ONBOARDING_DOCUMENT_MAX_SIZE_BYTES)
    data = await service.upload_document(
        ctx.company_id,
        ctx.case_id,
        document_type=document_type,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        data=body,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/{token}/documents", status_code=status.HTTP_200_OK)
async def list_onboarding_documents(
    ctx: Annotated[OnboardingTokenContext, Depends(get_onboarding_case_from_token)],
    service: Annotated[OnboardingDocumentService, Depends(get_onboarding_document_service)],
) -> ListEnvelope[OnboardingDocumentRead]:
    data = await service.list_documents(ctx.company_id, ctx.case_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/{token}/documents/{document_id}", status_code=status.HTTP_200_OK)
async def delete_onboarding_document(
    document_id: UUID,
    ctx: Annotated[OnboardingTokenContext, Depends(get_onboarding_case_from_token)],
    service: Annotated[OnboardingDocumentService, Depends(get_onboarding_document_service)],
) -> DataEnvelope[dict[str, bool]]:
    await service.delete_document(ctx.company_id, ctx.case_id, document_id)
    return DataEnvelope(data={"deleted": True}, meta=build_meta(current_request_id() or "unknown"))
