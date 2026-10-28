"""`POST /v1/onboarding-cases/{id}/cancel`: permission, state machine, link revocation, audit."""

from uuid import UUID

import pytest
from httpx import AsyncClient

from .test_invitation_compose import _counts, _no_dispatch, _outbox_for, _q, _send  # noqa: F401
from .test_onboarding_case import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
    _register_tenant,
)
from .test_onboarding_invite import (
    _create_case,
    _force_status,
    _teardown_with_tokens,
    _token_from_invite_url,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]


def _cancel_url(case_id: str) -> str:
    return f"/v1/onboarding-cases/{case_id}/cancel"


async def _status(client: AsyncClient, headers: dict[str, str], case_id: str) -> str:
    r = await client.get(f"/v1/onboarding-cases/{case_id}", headers=headers)
    return str(r.json()["data"]["status"])


async def test_cancel_draft_case_sets_status_audits_and_sends_nothing(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        r = await client.post(_cancel_url(case["id"]), headers=headers, json={"reason": " dup "})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "CANCELLED"
        assert await _status(client, headers, case["id"]) == "CANCELLED"
        audit = await _q(
            company_id,
            "SELECT before_json::text, after_json::text, actor_user_id FROM audit_log "
            "WHERE action='ONBOARDING_CASE_CANCELLED' AND entity_id=:k",
            k=case["id"],
        )
        assert len(audit) == 1
        assert "DRAFT" in audit[0][0] and "CANCELLED" in audit[0][1] and "dup" in audit[0][1]
        assert audit[0][2] == user_id
        assert await _counts(company_id, case["id"]) == {"outbox": 0, "message": 0, "token": 0}
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_cancel_without_body_works(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        assert (await client.post(_cancel_url(case["id"]), headers=headers)).status_code == 200
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_cancel_after_invite_revokes_the_live_link_and_queues_no_email(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        sent = (await _send(client, headers, case["id"])).json()["data"]
        token = _token_from_invite_url(sent["invite_url"])
        assert (await client.get(f"/v1/public/onboarding/{token}")).status_code == 200
        outbox_before = len(await _outbox_for(company_id))

        assert (await client.post(_cancel_url(case["id"]), headers=headers)).status_code == 200

        assert (await client.get(f"/v1/public/onboarding/{token}")).status_code == 404
        live = await _q(
            company_id,
            "SELECT count(*) FROM onboarding_token "
            "WHERE onboarding_case_id=:k AND revoked_at IS NULL",
            k=case["id"],
        )
        assert live[0][0] == 0
        assert len(await _outbox_for(company_id)) == outbox_before  # candidate not emailed
        # history is kept
        msgs = await client.get(f"/v1/onboarding-cases/{case['id']}/messages", headers=headers)
        assert len(msgs.json()["data"]) == 1
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_cancelled_case_cannot_be_invited_or_cancelled_again_and_frees_the_email(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        assert (await client.post(_cancel_url(case["id"]), headers=headers)).status_code == 200
        again = await client.post(_cancel_url(case["id"]), headers=headers)
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "ONBOARDING_CASE_NOT_CANCELLABLE"
        assert (await _send(client, headers, case["id"])).status_code == 409
        # the same address can be onboarded again
        fresh = await _create_case(client, headers, personal_email=case["personal_email"])
        assert fresh["id"] != case["id"] and fresh["status"] == "DRAFT"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    "status", ["IN_PROGRESS", "SUBMITTED", "UNDER_REVIEW", "VERIFIED", "CHANGES_REQUESTED"]
)
async def test_cancellable_in_every_open_status(client: AsyncClient, status: str) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        await _force_status(case_id=UUID(case["id"]), status=status)
        assert (await client.post(_cancel_url(case["id"]), headers=headers)).status_code == 200
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize("status", ["ACTIVATED", "EXPIRED"])
async def test_closed_or_activated_cases_cannot_be_cancelled(
    client: AsyncClient, status: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        await _force_status(case_id=UUID(case["id"]), status=status)
        r = await client.post(_cancel_url(case["id"]), headers=headers)
        assert r.status_code == 409
        assert await _status(client, headers, case["id"]) == status
        audit = await _q(
            company_id, "SELECT count(*) FROM audit_log WHERE action='ONBOARDING_CASE_CANCELLED'"
        )
        assert audit[0][0] == 0
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_cancel_requires_its_own_permission(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        for codes in (
            [],
            ["ONBOARDING.VIEW"],
            ["ONBOARDING.CREATE", "ONBOARDING.REVIEW", "ONBOARDING.ACTIVATE"],
        ):
            h, _ = await _create_permission_scoped_user(
                company_id=company_id, permission_codes=codes
            )
            assert (await client.post(_cancel_url(case["id"]), headers=h)).status_code == 403
        assert await _status(client, headers, case["id"]) == "DRAFT"
        ok, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["ONBOARDING.CANCEL"]
        )
        assert (await client.post(_cancel_url(case["id"]), headers=ok)).status_code == 200
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_other_tenant_cannot_cancel_and_bad_bodies_are_rejected(client: AsyncClient) -> None:
    ha, ca, ua = await _register_tenant(client)
    hb, cb, ub = await _register_tenant(client)
    try:
        case = await _create_case(client, ha)
        assert (await client.post(_cancel_url(case["id"]), headers=hb)).status_code == 404
        for bad in ({"reason": "x" * 501}, {"company_id": str(cb)}, {"status": "ACTIVATED"}):
            r = await client.post(_cancel_url(case["id"]), headers=ha, json=bad)
            assert r.status_code == 422, bad
        assert await _status(client, ha, case["id"]) == "DRAFT"
    finally:
        await _teardown_with_tokens(company_id=ca, user_id=ua)
        await _teardown_with_tokens(company_id=cb, user_id=ub)
