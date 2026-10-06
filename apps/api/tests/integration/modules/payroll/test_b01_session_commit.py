"""PAY-B01 — a mutation must not report success when its transaction cannot commit.

`get_session` commits after the endpoint returns. With the default dependency scope FastAPI runs
that teardown *after the response has been sent*, so a failing COMMIT happened too late to change
the status the client had already received. The dependency is now function-scoped
(`SessionDep`), so the commit runs before the response is built and a failure becomes a 500.

The transport has `raise_app_exceptions=False`, which is what a real server does: an exception
raised after the response started cannot change what the client saw.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from entrypoints.api import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def lenient_client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _legal_entity_names(company_id: UUID) -> list[str]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(text("SELECT name FROM legal_entity"))
        return [r[0] for r in rows]


async def test_commit_failure_is_reported_not_returned_as_success(
    client: AsyncClient,
    lenient_client: AsyncClient,
    seeded_plan_catalogue: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        real_commit = AsyncSession.commit
        armed = {"on": False, "calls": 0}

        async def failing_commit(self: AsyncSession) -> None:
            if armed["on"]:
                armed["calls"] += 1
                raise OperationalError("COMMIT", {}, Exception("simulated commit failure"))
            await real_commit(self)

        monkeypatch.setattr(AsyncSession, "commit", failing_commit)

        armed["on"] = True
        response = await lenient_client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Never Committed"}
        )
        armed["on"] = False

        assert armed["calls"] >= 1, "the request never reached a commit"
        assert response.status_code >= 500, (response.status_code, response.text)
        assert "Never Committed" not in await _legal_entity_names(company_id)

        # The failure leaves nothing behind and the same request works once commit works again.
        ok = await lenient_client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Committed"}
        )
        assert ok.status_code == 201, ok.text
        assert await _legal_entity_names(company_id) == ["Committed"]
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_read_only_request_commits_nothing_visible_and_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/legal-entities", headers=headers)
        assert response.status_code == 200, response.text
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_endpoint_error_still_rolls_back(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        bad: dict[str, Any] = {"name": ""}
        response = await client.post("/v1/legal-entities", headers=headers, json=bad)
        assert response.status_code in (400, 422), response.text
        assert await _legal_entity_names(company_id) == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
