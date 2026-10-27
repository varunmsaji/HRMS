"""Live half of the scope-enforcement guard (`tests/unit/core/test_scope_enforcement_guard.py`).

A route that ignores the data scope of its permission is only tolerated while NO shipped role holds
that permission below COMPANY. This registers a fresh tenant (which seeds the system roles exactly
as production does) and checks every exception against the real `role_permission` rows, and checks
that no scope-ignoring handler outside the exception list is gated by a sub-company grant.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register
from tests.unit.core import scope_guard as guard
from tests.unit.core.test_scope_enforcement_guard import _exceptions

from hrms.core.db.models.identity import Permission, Role, RolePermission
from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_KEEP_BELOW_COMPANY_OK = {"scope_irrelevant"}  # reviewed: returns no employee data / own record


async def test_no_shipped_role_holds_a_scope_ignoring_permission_below_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response, company_id, user_id = await _register(client)
    assert response.status_code == 201, response.text
    try:
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            rows = (
                await session.execute(
                    select(Role.code, Permission.code, RolePermission.data_scope)
                    .join(RolePermission, RolePermission.role_id == Role.id)
                    .join(Permission, Permission.id == RolePermission.permission_id)
                    .where(Role.company_id == company_id, Role.is_system.is_(True))
                )
            ).all()
        below = {(role, perm, scope) for role, perm, scope in rows if scope != "COMPANY"}
        below_perms = {perm for _role, perm, _scope in below}
        assert below_perms, "sanity: the shipped roles do hold some permissions below COMPANY"

        perms, handlers = _exceptions()
        offenders: list[str] = []
        for code, entry in perms.items():
            if code in below_perms:
                offenders.append(
                    f"permission exception {code} ({entry['kind']}) is held below COMPANY"
                )
        scanned = {h.key: h for h in guard.scan_repo()}
        for key, entry in handlers.items():
            if entry["kind"] in _KEEP_BELOW_COMPANY_OK:
                continue
            if entry["permission"] in below_perms:
                offenders.append(
                    f"handler exception {key} ({entry['kind']}): "
                    f"{entry['permission']} held below COMPANY"
                )
        for h in scanned.values():
            if not h.ignored:
                continue
            reviewed_irrelevant = key_kind(handlers, h.key) in _KEEP_BELOW_COMPANY_OK
            for perm in h.ignored:
                if perm in below_perms and not reviewed_irrelevant:
                    offenders.append(
                        f"{h.key} ignores the scope of {perm}, held below COMPANY by a shipped role"
                    )
        assert not offenders, "\n".join(sorted(set(offenders)))
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


def key_kind(handlers: dict[str, dict], key: str) -> str | None:
    return handlers[key]["kind"] if key in handlers else None
