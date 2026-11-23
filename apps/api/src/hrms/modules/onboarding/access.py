"""Branch access for onboarding cases.

A caller limited to their assigned branches (an HR administrator / branch manager without
`COMPANY_ADMIN`) reaches only the cases whose branch is one of those branches and still live. A case
with no branch is hidden from them (decision D4): nothing says whose it is. Every other caller is
unaffected. An out-of-reach case answers the same 404 as a missing or other-company one."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from hrms.core.rbac.dependencies import require_permission
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.onboarding.dependencies import get_onboarding_case_service
from hrms.modules.onboarding.service import OnboardingCaseService


def case_access(permission: str) -> Callable[..., Awaitable[DataScope]]:
    """Replaces `require_permission(permission)` on a `/onboarding-cases/{case_id}...` route:
    checks the permission, then (for a branch-restricted caller only) that the case is in reach."""
    require = require_permission(permission)

    async def dependency(
        case_id: UUID,
        tenant: Annotated[TenantContext, Depends(get_tenant_context)],
        scope: Annotated[DataScope, Depends(require)],
        service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
    ) -> DataScope:
        await service.assert_case_in_scope(tenant.company_id, case_id, scope)
        return scope

    return dependency
