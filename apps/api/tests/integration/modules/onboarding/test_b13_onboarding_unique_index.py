"""B13 Workstream B (application side) - the index behind `DUPLICATE_ACTIVE_ONBOARDING_CASE`.

Migration `20261027091000` (tested on scratch databases in `tests/integration/migrations`) creates
the partial unique index. These tests prove, on the migrated run database, that the application and
the index agree: the application answer stays the established 409; and even when the application's
own check and lock are bypassed, the index turns the would-be duplicate into the same 409 - with
nothing written (no row, no audit event, no e-mail).
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.b12_support import audit_count, scalar

from hrms.core.db.session import get_session_factory
from hrms.modules.onboarding import service as onboarding_service
from hrms.modules.onboarding.repository import OnboardingCaseRepository

from .test_onboarding_case import _case_payload, _register_tenant, _teardown

pytestmark = pytest.mark.asyncio


async def _create(client: AsyncClient, headers: dict[str, str], email: str):  # type: ignore[no-untyped-def]
    return await client.post(
        "/v1/onboarding-cases", headers=headers, json=_case_payload(personal_email=email)
    )


async def _live_cases(company_id, email: str) -> int:  # type: ignore[no-untyped-def]
    return int(
        await scalar(
            company_id,
            "SELECT count(*) FROM onboarding_case "
            "WHERE company_id=:cid AND lower(personal_email)=:e",
            e=email.lower(),
        )
    )


async def test_index_exists_and_matches_the_application_rule(seeded_plan_catalogue: None) -> None:
    async with get_session_factory()() as session:
        definition = (
            await session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname='onboarding_case_company_live_email_key'"
                )
            )
        ).scalar_one()
    assert "UNIQUE" in definition and "company_id" in definition
    assert "lower((personal_email)::text)" in definition
    for terminal in ("ACTIVATED", "EXPIRED", "CANCELLED"):
        assert terminal in definition  # same terminal set as ONBOARDING_CASE_TERMINAL_STATUSES


async def test_database_index_is_the_backstop_when_the_application_check_is_bypassed(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        email = f"backstop.{uuid4().hex[:8]}@personal.example"
        assert (await _create(client, headers, email)).status_code == 201
        before_audit = await audit_count(company_id, "ONBOARDING_CASE_CREATED")

        async def _no_lock(*_a: object, **_k: object) -> None:
            return None

        async def _blind(*_a: object, **_k: object) -> None:
            return None

        monkeypatch.setattr(onboarding_service, "lock_onboarding_case_email", _no_lock)
        monkeypatch.setattr(OnboardingCaseRepository, "get_active_case_by_email", _blind)
        for variant in (email, email.upper(), email.title()):
            r = await _create(client, headers, variant)
            assert r.status_code == 409, r.text
            assert r.json()["error"]["code"] == "DUPLICATE_ACTIVE_ONBOARDING_CASE"
        assert await _live_cases(company_id, email) == 1  # nothing was written
        assert await audit_count(company_id, "ONBOARDING_CASE_CREATED") == before_audit
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_history_and_other_tenants_do_not_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    other_headers, other_company, other_user = await _register_tenant(client)
    try:
        email = f"hist.{uuid4().hex[:8]}@personal.example"
        first = await _create(client, headers, email)
        assert first.status_code == 201
        assert (await _create(client, other_headers, email)).status_code == 201  # other tenant
        async with get_session_factory()() as session:
            await session.execute(
                text("UPDATE onboarding_case SET status='CANCELLED' WHERE id=:i"),
                {"i": first.json()["data"]["id"]},
            )
            await session.commit()
        assert (
            await _create(client, headers, email.upper())
        ).status_code == 201  # history frees it
        assert (await _create(client, headers, email)).status_code == 409  # and now it is taken
    finally:
        await _teardown(company_id=other_company, user_id=other_user)
        await _teardown(company_id=company_id, user_id=user_id)
