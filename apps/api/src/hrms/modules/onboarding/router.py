"""HTTP routes for the onboarding module — thin layer only, per Module Standard §2.

O1: `POST /onboarding-cases`, `GET /onboarding-cases`, `GET /onboarding-cases/{id}`. O3 adds
`POST /onboarding-cases/{id}/send-invite`. O5 adds `GET .../documents` and
`POST .../documents/{id}/review` — the first real use of `ONBOARDING.REVIEW` (seeded/granted
since O1, unused until now). O6 adds `POST .../sections/{section}/review` and
`POST .../request-changes`, and `GET /onboarding-cases/{id}` now returns the richer
`OnboardingCaseDetailRead` (section data + review status) instead of the list-safe
`OnboardingCaseRead`. O7 adds `POST .../activate` — the first real use of
`ONBOARDING.ACTIVATE` (seeded/granted since O1, unused until now). No `DataScope` narrowing is
applied on any of these —
`require_permission`'s resolved scope is discarded, same posture as `EMPLOYEE.VIEW_STATUTORY`/
`.VIEW_COMPENSATION` (module docstring, `hrms.modules.employee.router`): no source document
proposes `SELF`/`REPORTEES`/`REPORTEE_TREE` visibility for onboarding cases, which have no
employee yet to scope against. Tenant isolation is still fully enforced via `company_id` +
Postgres RLS, same as every other route in this app."""

from collections.abc import Awaitable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.core.idempotency import (
    mark_replay,
    optional_idempotency_key,
    request_fingerprint_fields,
    run_idempotent,
)
from hrms.core.rbac.dependencies import require_permission
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.identity.schemas import build_meta
from hrms.modules.onboarding.dependencies import (
    get_onboarding_activation_service,
    get_onboarding_case_service,
    get_onboarding_document_service,
    get_onboarding_review_service,
    get_onboarding_token_service,
)
from hrms.modules.onboarding.permissions import (
    ONBOARDING_ACTIVATE,
    ONBOARDING_CREATE,
    ONBOARDING_REVIEW,
    ONBOARDING_VIEW,
)
from hrms.modules.onboarding.schemas import (
    OnboardingCaseCreate,
    OnboardingCaseDetailRead,
    OnboardingCaseRead,
    OnboardingDocumentRead,
    OnboardingDocumentReviewRequest,
    OnboardingDocumentWithUrlRead,
    OnboardingInviteRead,
    OnboardingSectionReviewRead,
    OnboardingSectionReviewRequest,
)
from hrms.modules.onboarding.service import (
    OnboardingActivationService,
    OnboardingCaseService,
    OnboardingDocumentService,
    OnboardingReviewService,
    OnboardingTokenService,
)
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    build_pagination_meta,
    pagination_params,
)

router = APIRouter(tags=["onboarding"])


@router.post("/onboarding-cases", status_code=status.HTTP_201_CREATED)
async def create_onboarding_case(
    body: OnboardingCaseCreate,
    request: Request,
    response: Response,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_CREATE))],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> DataEnvelope[OnboardingCaseRead]:
    """`Idempotency-Key` is optional (API audit H-4); see `create_employee`."""

    def execute() -> Awaitable[OnboardingCaseRead]:
        return service.create_case(
            tenant.company_id,
            body,
            actor_user_id=tenant.user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        )

    if idempotency_key is None:
        return DataEnvelope(
            data=await execute(), meta=build_meta(current_request_id() or "unknown")
        )
    result = await run_idempotent(
        session,
        company_id=tenant.company_id,
        operation="onboarding.case.create",
        key=idempotency_key,
        fingerprint_fields=request_fingerprint_fields(body, tenant.user_id),
        response_model=OnboardingCaseRead,
        status_code=status.HTTP_201_CREATED,
        execute=execute,
    )
    mark_replay(response, result.replayed, result.status_code)
    return DataEnvelope(data=result.data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/onboarding-cases", status_code=status.HTTP_200_OK)
async def list_onboarding_cases(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_VIEW))],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> ListEnvelope[OnboardingCaseRead]:
    data, total = await service.list_cases(tenant.company_id, status=status_filter, page=page)
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/onboarding-cases/{case_id}", status_code=status.HTTP_200_OK)
async def get_onboarding_case(
    case_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_VIEW))],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
) -> DataEnvelope[OnboardingCaseDetailRead]:
    data = await service.get_case_detail(tenant.company_id, case_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/onboarding-cases/{case_id}/send-invite", status_code=status.HTTP_200_OK)
async def send_onboarding_invite(
    case_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_CREATE))],
    service: Annotated[OnboardingTokenService, Depends(get_onboarding_token_service)],
) -> DataEnvelope[OnboardingInviteRead]:
    """(Re)issues the candidate's public link and emails it — gated by `ONBOARDING.CREATE`, the
    same code that gates starting the case in the first place (plan §7.1: sending the first
    invite is inherent to "starting" onboarding, not a separate review-adjacent action)."""
    data = await service.send_invite(
        tenant.company_id,
        case_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/onboarding-cases/{case_id}/documents", status_code=status.HTTP_200_OK)
async def list_onboarding_case_documents(
    case_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_VIEW))],
    service: Annotated[OnboardingDocumentService, Depends(get_onboarding_document_service)],
) -> ListEnvelope[OnboardingDocumentWithUrlRead]:
    data = await service.list_documents_with_urls(tenant.company_id, case_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/onboarding-cases/{case_id}/documents/{document_id}/review", status_code=status.HTTP_200_OK
)
async def review_onboarding_document(
    case_id: UUID,
    document_id: UUID,
    body: OnboardingDocumentReviewRequest,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_REVIEW))],
    service: Annotated[OnboardingDocumentService, Depends(get_onboarding_document_service)],
) -> DataEnvelope[OnboardingDocumentRead]:
    data = await service.review_document(
        tenant.company_id,
        case_id,
        document_id,
        status=body.status,
        rejection_reason=body.rejection_reason,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/onboarding-cases/{case_id}/sections/{section}/review", status_code=status.HTTP_200_OK
)
async def review_onboarding_section(
    case_id: UUID,
    section: str,
    body: OnboardingSectionReviewRequest,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_REVIEW))],
    service: Annotated[OnboardingReviewService, Depends(get_onboarding_review_service)],
) -> DataEnvelope[OnboardingSectionReviewRead]:
    """Records HR's verdict on one section — does not itself move the case to
    `CHANGES_REQUESTED`; that's a separate, explicit `request-changes` call once every section/
    document has been reviewed (plan §7.1)."""
    data = await service.review_section(
        tenant.company_id,
        case_id,
        section,
        status=body.status,
        rejection_reason=body.rejection_reason,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/onboarding-cases/{case_id}/request-changes", status_code=status.HTTP_200_OK)
async def request_onboarding_changes(
    case_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_REVIEW))],
    service: Annotated[OnboardingReviewService, Depends(get_onboarding_review_service)],
) -> DataEnvelope[OnboardingCaseRead]:
    data = await service.request_changes(
        tenant.company_id,
        case_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/onboarding-cases/{case_id}/activate", status_code=status.HTTP_200_OK)
async def activate_onboarding_case(
    case_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_ACTIVATE))],
    service: Annotated[OnboardingActivationService, Depends(get_onboarding_activation_service)],
) -> DataEnvelope[OnboardingCaseRead]:
    """The payoff of the whole module (plan §8.6) — creates the real Employee/Employment/
    Assignment(/Bank/Statutory) row graph from a `VERIFIED` case. Gated by its own
    `ONBOARDING.ACTIVATE` code, separate from `.REVIEW` — activation is irreversible, mirroring
    why `EMPLOYEE.TERMINATE` got its own code rather than folding into `.UPDATE`
    (permissions.py)."""
    data = await service.activate_case(
        tenant.company_id,
        case_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
