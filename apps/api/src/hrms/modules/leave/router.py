"""HTTP routes for the Leave module — thin layer only, per Module Standard §2.

L1: leave types + leave policy identity/version CRUD. All L1 routes are COMPANY-scoped and gated
by `LEAVE.TYPE_MANAGE`/`LEAVE.POLICY_MANAGE` — config screens, no self-service, mirroring
Attendance's own `.POLICY_MANAGE` posture (architecture §23.2: "Employee self-service never
manages policies").

L2: the leave ledger. `POST /leave-ledger/adjustments` is COMPANY-scoped HR admin
(`LEAVE.BALANCE_ADJUST`, no per-employee visibility narrowing — mirrors `.POLICY_MANAGE`).
`GET /leave-ledger`/`GET /leave-balances` are visibility-narrowed reads: `LEAVE.BALANCE_VIEW`
("own") unioned with `LEAVE.BALANCE_VIEW_ALL` ("within scope") into one combined `DataScope`,
mirroring `cancel_regularization_request`'s exact two-resolve_data_scope-calls-unioned shape
(attendance/router.py) — the only existing precedent in this codebase for a route effectively
accepting either of two permission grants."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.session import get_session
from hrms.core.errors.base import PermissionDeniedError, ValidationError
from hrms.core.idempotency import (
    mark_replay,
    request_fingerprint_fields,
    require_idempotency_key,
    run_idempotent,
)
from hrms.core.rbac.dependencies import get_rbac_service, require_permission
from hrms.core.rbac.service import RbacService
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.identity.schemas import build_meta
from hrms.modules.leave.dependencies import (
    get_leave_application_service,
    get_leave_combination_rule_service,
    get_leave_ledger_service,
    get_leave_policy_service,
    get_leave_type_service,
    get_leave_year_setting_service,
    get_statutory_leave_minimum_service,
)
from hrms.modules.leave.permissions import (
    LEAVE_APPLICATION_APPROVE,
    LEAVE_APPLICATION_CANCEL_APPROVED,
    LEAVE_APPLICATION_REASSIGN,
    LEAVE_APPLICATION_SUBMIT,
    LEAVE_APPLICATION_SUBMIT_ON_BEHALF,
    LEAVE_BALANCE_ADJUST,
    LEAVE_BALANCE_VIEW,
    LEAVE_BALANCE_VIEW_ALL,
    LEAVE_COMBINATION_RULE_MANAGE,
    LEAVE_POLICY_MANAGE,
    LEAVE_STATUTORY_MINIMUM_MANAGE,
    LEAVE_TYPE_MANAGE,
    LEAVE_YEAR_SETTING_MANAGE,
)
from hrms.modules.leave.schemas import (
    LeaveApplicationCancelInput,
    LeaveApplicationCreate,
    LeaveApplicationRead,
    LeaveApplicationReassignInput,
    LeaveApplicationReviewInput,
    LeaveBalanceRead,
    LeaveCombinationRuleCreate,
    LeaveCombinationRuleRead,
    LeaveLedgerAdjustmentCreate,
    LeaveLedgerEncashmentCreate,
    LeaveLedgerEntryRead,
    LeavePolicyCreate,
    LeavePolicyRead,
    LeavePolicyUpdate,
    LeavePolicyVersionCreate,
    LeavePolicyVersionPublishRequest,
    LeavePolicyVersionRead,
    LeavePolicyVersionUpdate,
    LeaveTypeCreate,
    LeaveTypeRead,
    LeaveTypeUpdate,
    LeaveYearSettingRead,
    LeaveYearSettingUpsert,
    StatutoryLeaveMinimumCreate,
    StatutoryLeaveMinimumRead,
)
from hrms.modules.leave.service import (
    LeaveApplicationService,
    LeaveCombinationRuleService,
    LeaveLedgerService,
    LeavePolicyService,
    LeaveTypeService,
    LeaveYearSettingService,
    StatutoryLeaveMinimumService,
)
from hrms.shared.if_match import parse_if_match
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    build_pagination_meta,
    pagination_params,
)

router = APIRouter(tags=["leave"])


# ---------------------------------------------------------------------------
# Leave Types
# ---------------------------------------------------------------------------


@router.get("/leave-types", status_code=status.HTTP_200_OK)
async def list_leave_types(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[LeaveTypeService, Depends(get_leave_type_service)],
) -> ListEnvelope[LeaveTypeRead]:
    """LM-05 / decision 12 - the apply workflow needs the company's leave types, so a submitter
    reads the *active* ones without holding `LEAVE.TYPE_MANAGE` (which also grants writes).
    A type manager still sees every type, inactive included."""
    codes = await rbac.get_permission_codes(user.user_id, user.company_id)
    can_manage = LEAVE_TYPE_MANAGE in codes
    if not can_manage and not (
        {LEAVE_APPLICATION_SUBMIT, LEAVE_APPLICATION_SUBMIT_ON_BEHALF} & codes
    ):
        raise PermissionDeniedError(
            f"Permission {LEAVE_TYPE_MANAGE} is required", code="PERMISSION_DENIED"
        )
    data = await service.list(tenant.company_id)
    if not can_manage:
        data = [leave_type for leave_type in data if leave_type.is_active]
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-types", status_code=status.HTTP_201_CREATED)
async def create_leave_type(
    body: LeaveTypeCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_TYPE_MANAGE))],
    service: Annotated[LeaveTypeService, Depends(get_leave_type_service)],
) -> DataEnvelope[LeaveTypeRead]:
    data = await service.create(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-types/{leave_type_id}", status_code=status.HTTP_200_OK)
async def get_leave_type(
    leave_type_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_TYPE_MANAGE))],
    service: Annotated[LeaveTypeService, Depends(get_leave_type_service)],
) -> DataEnvelope[LeaveTypeRead]:
    data = await service.get(tenant.company_id, leave_type_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/leave-types/{leave_type_id}", status_code=status.HTTP_200_OK)
async def update_leave_type(
    leave_type_id: UUID,
    body: LeaveTypeUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_TYPE_MANAGE))],
    service: Annotated[LeaveTypeService, Depends(get_leave_type_service)],
) -> DataEnvelope[LeaveTypeRead]:
    data = await service.update(
        tenant.company_id,
        leave_type_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Leave Policies
# ---------------------------------------------------------------------------


@router.get("/leave-policies", status_code=status.HTTP_200_OK)
async def list_leave_policies(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> ListEnvelope[LeavePolicyRead]:
    data = await service.list_policies(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-policies", status_code=status.HTTP_201_CREATED)
async def create_leave_policy(
    body: LeavePolicyCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyRead]:
    data = await service.create_policy(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def get_leave_policy(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyRead]:
    data = await service.get_policy(tenant.company_id, policy_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/leave-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def update_leave_policy(
    policy_id: UUID,
    body: LeavePolicyUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyRead]:
    data = await service.update_policy(
        tenant.company_id,
        policy_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-policies/{policy_id}/versions", status_code=status.HTTP_200_OK)
async def list_leave_policy_versions(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> ListEnvelope[LeavePolicyVersionRead]:
    data = await service.list_versions(tenant.company_id, policy_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-policies/{policy_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_leave_policy_version(
    policy_id: UUID,
    body: LeavePolicyVersionCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.create_version(
        tenant.company_id,
        policy_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-policies/{policy_id}/versions/resolve", status_code=status.HTTP_200_OK)
async def resolve_leave_policy_version(
    policy_id: UUID,
    as_of: Annotated[date, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    """Registered ahead of `{version_id}` — a literal path segment must be matched before the
    parameterized route (mirrors `/attendance-policies/{id}/versions/resolve`)."""
    data = await service.resolve_version_as_of(tenant.company_id, policy_id, as_of)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def get_leave_policy_version(
    policy_id: UUID,
    version_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.get_version(tenant.company_id, policy_id, version_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/leave-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def update_leave_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: LeavePolicyVersionUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.update_version(
        tenant.company_id,
        policy_id,
        version_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/leave-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def discard_leave_policy_version(
    policy_id: UUID,
    version_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.discard_version(
        tenant.company_id,
        policy_id,
        version_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/leave-policies/{policy_id}/versions/{version_id}/publish",
    status_code=status.HTTP_200_OK,
)
async def publish_leave_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: LeavePolicyVersionPublishRequest,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.publish_version(
        tenant.company_id,
        policy_id,
        version_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Leave Year Setting — client spec §10 (LD-20), singleton per company
# ---------------------------------------------------------------------------


@router.get("/leave-year-setting", status_code=status.HTTP_200_OK)
async def get_leave_year_setting(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_YEAR_SETTING_MANAGE))],
    service: Annotated[LeaveYearSettingService, Depends(get_leave_year_setting_service)],
) -> DataEnvelope[LeaveYearSettingRead]:
    data = await service.get_effective(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.put("/leave-year-setting", status_code=status.HTTP_200_OK)
async def upsert_leave_year_setting(
    body: LeaveYearSettingUpsert,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_YEAR_SETTING_MANAGE))],
    service: Annotated[LeaveYearSettingService, Depends(get_leave_year_setting_service)],
) -> DataEnvelope[LeaveYearSettingRead]:
    """A singleton resource — `PUT` creates or replaces it, no `If-Match` required (low-
    contention, HR-only company-wide config; a genuine concurrent-write race raises
    `STALE_RESOURCE` regardless, LeaveYearSettingService.upsert)."""
    data = await service.upsert(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Leave Combination Rules — client spec §7 (LD-16)
# ---------------------------------------------------------------------------


@router.get("/leave-combination-rules", status_code=status.HTTP_200_OK)
async def list_leave_combination_rules(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_COMBINATION_RULE_MANAGE))],
    service: Annotated[LeaveCombinationRuleService, Depends(get_leave_combination_rule_service)],
) -> ListEnvelope[LeaveCombinationRuleRead]:
    data = await service.list(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-combination-rules", status_code=status.HTTP_201_CREATED)
async def create_leave_combination_rule(
    body: LeaveCombinationRuleCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_COMBINATION_RULE_MANAGE))],
    service: Annotated[LeaveCombinationRuleService, Depends(get_leave_combination_rule_service)],
) -> DataEnvelope[LeaveCombinationRuleRead]:
    data = await service.create(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/leave-combination-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_leave_combination_rule(
    rule_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_COMBINATION_RULE_MANAGE))],
    service: Annotated[LeaveCombinationRuleService, Depends(get_leave_combination_rule_service)],
) -> None:
    await service.delete(
        tenant.company_id,
        rule_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


# ---------------------------------------------------------------------------
# Leave Ledger — L2
# ---------------------------------------------------------------------------


async def _combined_balance_scope(user: AuthenticatedUser, rbac: RbacService) -> DataScope:
    """Unions `LEAVE.BALANCE_VIEW` ("own") with `LEAVE.BALANCE_VIEW_ALL` ("within scope") into
    one `DataScope` — mirrors `cancel_regularization_request`'s exact shape
    (attendance/router.py), the only existing precedent for a route accepting either of two
    permission grants rather than a single static `require_permission` code."""
    self_scope = await rbac.resolve_data_scope(user.user_id, user.company_id, LEAVE_BALANCE_VIEW)
    all_scope = await rbac.resolve_data_scope(user.user_id, user.company_id, LEAVE_BALANCE_VIEW_ALL)
    combined = DataScope(levels=self_scope.levels | all_scope.levels)
    if not combined.levels:
        raise PermissionDeniedError(
            f"Permission {LEAVE_BALANCE_VIEW} is required", code="PERMISSION_DENIED"
        )
    return combined


@router.post("/leave-ledger/adjustments", status_code=status.HTTP_201_CREATED)
async def create_leave_ledger_adjustment(
    body: LeaveLedgerAdjustmentCreate,
    request: Request,
    response: Response,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(LEAVE_BALANCE_ADJUST))],
    service: Annotated[LeaveLedgerService, Depends(get_leave_ledger_service)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> DataEnvelope[LeaveLedgerEntryRead]:
    """Requires an `Idempotency-Key` (LM-03): a retry with the same key and body replays the
    original entry instead of writing a second one."""
    # DEF-B10-01 - scope check before the idempotency wrapper: a denied request (first attempt
    # or replay) stores nothing and mutates nothing.
    await service.ensure_can_adjust_balance(
        tenant.company_id, body.employee_id, scope=scope, caller_employee_id=user.employee_id
    )
    result = await run_idempotent(
        session,
        company_id=tenant.company_id,
        operation="leave.ledger.adjustment",
        key=idempotency_key,
        fingerprint_fields=request_fingerprint_fields(body, tenant.user_id),
        response_model=LeaveLedgerEntryRead,
        status_code=status.HTTP_201_CREATED,
        execute=lambda: service.create_adjustment(
            tenant.company_id,
            body.employee_id,
            body,
            scope=scope,
            caller_employee_id=user.employee_id,
            actor_user_id=tenant.user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        ),
    )
    mark_replay(response, result.replayed, result.status_code)
    return DataEnvelope(data=result.data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-ledger/encashments", status_code=status.HTTP_201_CREATED)
async def create_leave_ledger_encashment(
    body: LeaveLedgerEncashmentCreate,
    request: Request,
    response: Response,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(LEAVE_BALANCE_ADJUST))],
    service: Annotated[LeaveLedgerService, Depends(get_leave_ledger_service)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> DataEnvelope[LeaveLedgerEntryRead]:
    """Client spec §12 (LD-19) — same `LEAVE.BALANCE_ADJUST` HR-admin gate as
    `create_leave_ledger_adjustment` above, but validated against the applicable policy's
    encashment config rather than writing unconditionally. Requires an `Idempotency-Key`
    (LM-03), so a retried request never encashes twice."""
    # DEF-B10-01 - scope check before the idempotency wrapper: a denied request (first attempt
    # or replay) stores nothing and mutates nothing.
    await service.ensure_can_adjust_balance(
        tenant.company_id, body.employee_id, scope=scope, caller_employee_id=user.employee_id
    )
    result = await run_idempotent(
        session,
        company_id=tenant.company_id,
        operation="leave.ledger.encashment",
        key=idempotency_key,
        fingerprint_fields=request_fingerprint_fields(body, tenant.user_id),
        response_model=LeaveLedgerEntryRead,
        status_code=status.HTTP_201_CREATED,
        execute=lambda: service.create_encashment(
            tenant.company_id,
            body.employee_id,
            body,
            scope=scope,
            caller_employee_id=user.employee_id,
            actor_user_id=tenant.user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        ),
    )
    mark_replay(response, result.replayed, result.status_code)
    return DataEnvelope(data=result.data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-ledger", status_code=status.HTTP_200_OK)
async def list_leave_ledger_entries(
    employee_id: Annotated[UUID, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[LeaveLedgerService, Depends(get_leave_ledger_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
    leave_type_id: Annotated[UUID | None, Query()] = None,
) -> ListEnvelope[LeaveLedgerEntryRead]:
    scope = await _combined_balance_scope(user, rbac)
    data, total = await service.list_entries(
        tenant.company_id,
        employee_id,
        leave_type_id=leave_type_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/leave-balances", status_code=status.HTTP_200_OK)
async def get_leave_balances(
    employee_id: Annotated[UUID, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[LeaveLedgerService, Depends(get_leave_ledger_service)],
) -> ListEnvelope[LeaveBalanceRead]:
    scope = await _combined_balance_scope(user, rbac)
    data = await service.get_balances(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Leave Applications — L4. Submit/approve/reject/cancel mirror
# `attendance/router.py`'s regularization-request routes exactly (LD-05); reads reuse the same
# combined `LEAVE.BALANCE_VIEW`/`_VIEW_ALL` scope as the ledger/balance routes above (LD-08: no
# dedicated view code — reads reuse a `.VIEW`-style code).
# ---------------------------------------------------------------------------


@router.post("/leave-applications", status_code=status.HTTP_201_CREATED)
async def create_leave_application(
    body: LeaveApplicationCreate,
    request: Request,
    response: Response,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[LeaveApplicationService, Depends(get_leave_application_service)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> DataEnvelope[LeaveApplicationRead]:
    """Requires an `Idempotency-Key` (LM-03). Self-submit (`LEAVE.APPLICATION_SUBMIT`, SELF) when
    `employee_id` is omitted or matches the caller's own; on-behalf
    (`LEAVE.APPLICATION_SUBMIT_ON_BEHALF`, COMPANY) when it names someone else — mirrors
    `create_regularization_request`'s exact shape, since the gating permission here also depends
    on the request body."""
    target_employee_id = body.employee_id or user.employee_id
    if target_employee_id is None:
        raise ValidationError("employee_id is required — the caller has no linked employee record")

    on_behalf = body.employee_id is not None and body.employee_id != user.employee_id
    required_permission = (
        LEAVE_APPLICATION_SUBMIT_ON_BEHALF if on_behalf else LEAVE_APPLICATION_SUBMIT
    )
    scope = await rbac.resolve_data_scope(user.user_id, user.company_id, required_permission)
    if not scope.levels:
        raise PermissionDeniedError(
            f"Permission {required_permission} is required", code="PERMISSION_DENIED"
        )

    result = await run_idempotent(
        session,
        company_id=tenant.company_id,
        operation="leave.application.submit",
        key=idempotency_key,
        fingerprint_fields=request_fingerprint_fields(
            body, tenant.user_id, target_employee_id=str(target_employee_id)
        ),
        response_model=LeaveApplicationRead,
        status_code=status.HTTP_201_CREATED,
        execute=lambda: service.submit(
            tenant.company_id,
            target_employee_id,
            body,
            scope=scope,
            caller_employee_id=user.employee_id,
            on_behalf=on_behalf,
            actor_user_id=tenant.user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        ),
    )
    mark_replay(response, result.replayed, result.status_code)
    return DataEnvelope(data=result.data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-applications", status_code=status.HTTP_200_OK)
async def list_leave_applications(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[LeaveApplicationService, Depends(get_leave_application_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    application_status: Annotated[str | None, Query()] = None,
) -> ListEnvelope[LeaveApplicationRead]:
    scope = await _combined_balance_scope(user, rbac)
    data, total = await service.list_applications(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=application_status,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/leave-applications/{application_id}", status_code=status.HTTP_200_OK)
async def get_leave_application(
    application_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[LeaveApplicationService, Depends(get_leave_application_service)],
) -> DataEnvelope[LeaveApplicationRead]:
    scope = await _combined_balance_scope(user, rbac)
    data = await service.get_application(
        tenant.company_id, application_id, scope=scope, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-applications/{application_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_leave_application(
    application_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[LeaveApplicationService, Depends(get_leave_application_service)],
    body: LeaveApplicationCancelInput | None = None,
) -> DataEnvelope[LeaveApplicationRead]:
    """Who may cancel is decided in the service (decision 10): the submitter or the employee
    while `SUBMITTED`; the employee before an approved leave starts; after that only a
    company-scoped `LEAVE.APPLICATION_CANCEL_APPROVED` holder, with a reason. This route accepts
    either submission permission or that HR permission — mirrors
    `cancel_regularization_request`'s combined-scope shape."""
    self_scope = await rbac.resolve_data_scope(
        user.user_id, user.company_id, LEAVE_APPLICATION_SUBMIT
    )
    on_behalf_scope = await rbac.resolve_data_scope(
        user.user_id, user.company_id, LEAVE_APPLICATION_SUBMIT_ON_BEHALF
    )
    cancel_approved_scope = await rbac.resolve_data_scope(
        user.user_id, user.company_id, LEAVE_APPLICATION_CANCEL_APPROVED
    )
    combined_scope = DataScope(
        levels=self_scope.levels | on_behalf_scope.levels | cancel_approved_scope.levels
    )
    if not combined_scope.levels:
        raise PermissionDeniedError(
            f"Permission {LEAVE_APPLICATION_SUBMIT} is required", code="PERMISSION_DENIED"
        )

    data = await service.cancel(
        tenant.company_id,
        application_id,
        scope=combined_scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        expected_version=parse_if_match(if_match),
        reason=body.reason if body else None,
        can_cancel_approved=DataScopeLevel.COMPANY in cancel_approved_scope.levels,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-applications/{application_id}/approve", status_code=status.HTTP_200_OK)
async def approve_leave_application(
    application_id: UUID,
    body: LeaveApplicationReviewInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(LEAVE_APPLICATION_APPROVE))],
    service: Annotated[LeaveApplicationService, Depends(get_leave_application_service)],
) -> DataEnvelope[LeaveApplicationRead]:
    """`MANAGER` stage requires the caller to *be* the snapshotted
    `resolved_approver_manager_id`; `HR` stage requires a COMPANY-scoped grant — both checked in
    the service (`LeaveApplicationService._get_reviewable`), not here, since the correct check
    depends on the application's current stage."""
    data = await service.approve(
        tenant.company_id,
        application_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        expected_version=parse_if_match(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-applications/{application_id}/reject", status_code=status.HTTP_200_OK)
async def reject_leave_application(
    application_id: UUID,
    body: LeaveApplicationReviewInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(LEAVE_APPLICATION_APPROVE))],
    service: Annotated[LeaveApplicationService, Depends(get_leave_application_service)],
) -> DataEnvelope[LeaveApplicationRead]:
    data = await service.reject(
        tenant.company_id,
        application_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        expected_version=parse_if_match(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/leave-applications/{application_id}/reassign-approver", status_code=status.HTTP_200_OK
)
async def reassign_leave_application_approver(
    application_id: UUID,
    body: LeaveApplicationReassignInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    scope: Annotated[DataScope, Depends(require_permission(LEAVE_APPLICATION_REASSIGN))],
    service: Annotated[LeaveApplicationService, Depends(get_leave_application_service)],
) -> DataEnvelope[LeaveApplicationRead]:
    """Decision 13 - HR reassigns a stuck MANAGER/HOD stage to another eligible approver. The
    service enforces the company-wide scope, the stuck-approver and new-approver eligibility
    rules, the mandatory reason and the `If-Match` version."""
    data = await service.reassign_approver(
        tenant.company_id,
        application_id,
        body,
        scope=scope,
        actor_user_id=tenant.user_id,
        expected_version=parse_if_match(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Statutory Leave Minimum — client spec §16 (LD-22), legal compliance floor
# ---------------------------------------------------------------------------


@router.get("/statutory-leave-minimums", status_code=status.HTTP_200_OK)
async def list_statutory_leave_minimums(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_STATUTORY_MINIMUM_MANAGE))],
    service: Annotated[StatutoryLeaveMinimumService, Depends(get_statutory_leave_minimum_service)],
) -> ListEnvelope[StatutoryLeaveMinimumRead]:
    data = await service.list(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/statutory-leave-minimums", status_code=status.HTTP_201_CREATED)
async def create_statutory_leave_minimum(
    body: StatutoryLeaveMinimumCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_STATUTORY_MINIMUM_MANAGE))],
    service: Annotated[StatutoryLeaveMinimumService, Depends(get_statutory_leave_minimum_service)],
) -> DataEnvelope[StatutoryLeaveMinimumRead]:
    data = await service.create(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/statutory-leave-minimums/{minimum_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_statutory_leave_minimum(
    minimum_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_STATUTORY_MINIMUM_MANAGE))],
    service: Annotated[StatutoryLeaveMinimumService, Depends(get_statutory_leave_minimum_service)],
) -> None:
    await service.delete(
        tenant.company_id,
        minimum_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
