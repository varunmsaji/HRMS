"""Integration tests for the Onboarding module's O3 slice —
`POST /v1/onboarding-cases/{id}/send-invite`.

The dev/test environment has no AWS credentials configured, so `get_email_sender` always
resolves to `LoggingEmailSender` here (`hrms.modules.onboarding.email_sender`) — `email_sent` is
therefore always `True` in these tests (logging never raises), and no real network call is ever
made. This is the intended, documented behavior for every local dev environment today, not a
test-only stub.

Covers: first send transitions `DRAFT -> INVITED` and the returned `invite_url` is immediately
usable against the O2 public routes; resend revokes the previous token (old link 404s, new one
works); permission gating; rejection once the case is no longer invitable; and not-found for an
unknown case."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from .test_onboarding_case import (
    _case_payload,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
    _register_tenant,
    _teardown,
)

pytestmark = pytest.mark.asyncio


async def _create_case(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/onboarding-cases", headers=headers, json=_case_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def _token_from_invite_url(invite_url: str) -> str:
    return invite_url.rsplit("/", 1)[-1]


async def _force_status(*, case_id: UUID, status: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE onboarding_case SET status = :status WHERE id = :cid"),
            {"status": status, "cid": str(case_id)},
        )
        await session.commit()


async def _cleanup_tokens(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM onboarding_token WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _teardown_with_tokens(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_tokens(company_id=company_id)
    await _teardown(company_id=company_id, user_id=user_id)


async def test_send_invite_success_transitions_draft_to_invited(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        assert case["status"] == "DRAFT"

        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/send-invite", headers=headers
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["case"]["status"] == "INVITED"
        assert data["email_sent"] is True
        assert data["invite_url"].endswith(_token_from_invite_url(data["invite_url"]))

        token = _token_from_invite_url(data["invite_url"])
        public_response = await client.get(f"/v1/public/onboarding/{token}")
        assert public_response.status_code == 200
        assert public_response.json()["data"]["status"] == "IN_PROGRESS"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_resend_invite_revokes_previous_token(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)

        send_invite_url = f"/v1/onboarding-cases/{case['id']}/send-invite"
        first = await client.post(send_invite_url, headers=headers)
        second = await client.post(send_invite_url, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200

        old_token = _token_from_invite_url(first.json()["data"]["invite_url"])
        new_token = _token_from_invite_url(second.json()["data"]["invite_url"])
        assert old_token != new_token

        old_response = await client.get(f"/v1/public/onboarding/{old_token}")
        assert old_response.status_code == 404

        new_response = await client.get(f"/v1/public/onboarding/{new_token}")
        assert new_response.status_code == 200
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_send_invite_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[]
        )

        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/send-invite", headers=scoped_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_send_invite_rejected_once_case_is_not_invitable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        await _force_status(case_id=UUID(case["id"]), status="SUBMITTED")

        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/send-invite", headers=headers
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_CASE_NOT_INVITABLE"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_send_invite_unknown_case_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            f"/v1/onboarding-cases/{uuid4()}/send-invite", headers=headers
        )
        assert response.status_code == 404
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)
