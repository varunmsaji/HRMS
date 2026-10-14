"""LOG-05 — a client-supplied `X-Request-Id` can no longer make an audited write fail.

Before the fix the header was copied verbatim into `audit_log.request_id` (`VARCHAR(64)`), so a
valid login sent with a 65-character request id failed with `422 INVALID_VALUE` (reproduced
against this same test database in the audit). Now an out-of-policy id is replaced by a fresh
UUID, and the id actually stored is the one returned to the client."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.seed.constants import ADMIN_EMAIL, COMPANY_A_ID, DEMO_PASSWORD


async def _login(client: AsyncClient, request_id: str):  # type: ignore[no-untyped-def]
    return await client.post(
        "/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD, "company_id": str(COMPANY_A_ID)},
        headers={"X-Request-Id": request_id},
    )


async def _audited_request_ids(request_id: str) -> list[str | None]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(COMPANY_A_ID))
        rows = await session.execute(
            select(AuditLog.request_id).where(
                AuditLog.company_id == COMPANY_A_ID,
                AuditLog.action == "LOGIN",
                AuditLog.request_id == request_id,
            )
        )
        return list(rows.scalars())


@pytest.mark.parametrize("bad", ["r" * 65, "x" * 3000, "has space"])
async def test_oversized_or_malformed_request_id_does_not_break_login(
    client: AsyncClient, seeded_db: None, bad: str
) -> None:
    response = await _login(client, bad)
    assert response.status_code == 200, response.text
    issued = response.headers["x-request-id"]
    assert issued != bad and UUID(issued)
    assert await _audited_request_ids(issued) == [issued]


async def test_request_id_at_the_64_character_bound_is_kept_and_audited(
    client: AsyncClient, seeded_db: None
) -> None:
    exact = "a" * 64
    response = await _login(client, exact)
    assert response.status_code == 200
    assert response.headers["x-request-id"] == exact
    assert await _audited_request_ids(exact) == [exact]
