"""Stage 1 (production-readiness programme): user management and invite acceptance under `hrms_app`.

`test_user_access_control.py::test_cross_tenant_isolation_for_user_management` runs as the schema
owner, which bypasses RLS. This repeats the cross-tenant scenario with the API running as the
restricted runtime role, including the real invite -> accept flow used to create the second user.
Only API calls run as `hrms_app`; registration, assertions and teardown use the admin role."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from .uac_helpers import onboard, register_tenant, teardown

pytestmark = pytest.mark.asyncio


async def test_cross_tenant_user_management_under_runtime_role(
    client: AsyncClient, seeded_plan_catalogue: None, app_as_runtime_role: object
) -> None:
    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        async with app_as_runtime_role():  # type: ignore[operator]
            b_member = await onboard(client, b, "HR_ADMIN")
            b_employee = await client.post(
                "/v1/employees",
                headers=b.headers,
                json={"first_name": "Bee", "personal_email": f"bee-{uuid4().hex[:8]}@example.com"},
            )
            assert b_employee.status_code == 201, b_employee.text

            listing = await client.get("/v1/users", headers=a.headers)
            assert listing.status_code == 200, listing.text
            ids = {row["user_id"] for row in listing.json()["data"]}
            assert str(b_member.user_id) not in ids
            assert str(b.admin_user_id) not in ids

            assign = await client.patch(
                f"/v1/users/{b_member.user_id}/roles",
                headers=a.headers,
                json={"role_codes": ["EMPLOYEE"]},
            )
            assert assign.status_code == 404, assign.text

            invite = await client.post(
                f"/v1/employees/{b_employee.json()['data']['id']}/invite", headers=a.headers
            )
            assert invite.status_code == 404, invite.text

            pivot = await client.get(
                "/v1/users",
                headers={
                    "Authorization": a.headers["Authorization"],
                    "X-Company-Id": str(b.company_id),
                },
            )
            assert pivot.status_code == 404, pivot.text

            replay = await client.get(
                "/v1/users",
                headers={
                    "Authorization": b_member.headers["Authorization"],
                    "X-Company-Id": str(a.company_id),
                },
            )
            assert replay.status_code == 404, replay.text

            still = await client.get("/v1/users", headers=b.headers)
            roles = {r["user_id"]: r["role_codes"] for r in still.json()["data"]}
            assert roles[str(b_member.user_id)] == ["HR_ADMIN"]
    finally:
        await teardown(a)
        await teardown(b)
