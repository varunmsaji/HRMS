"""B12 regression - DEF-B11-03 (concurrent duplicate cases + later 500s) and DEF-B11-05
(case-sensitive duplicate detection) for `POST /v1/onboarding-cases`.

Rule: one ACTIVE (non-terminal) case per company per candidate e-mail, compared on the normalised
address (stripped, lower-cased - the rule invites and user accounts already use). Enforced under
concurrency by a transaction-scoped advisory lock around check-and-insert, so the loser gets the
established 409 `DUPLICATE_ACTIVE_ONBOARDING_CASE`, never a 500 and never a second row. Only
onboarding-case e-mails are normalised; no wider identity rule changes.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

from ...b12_support import audit_count, fingerprint, live_email_index_absent, scalar
from .test_onboarding_case import _case_payload, _register_tenant, _teardown

pytestmark = pytest.mark.asyncio


def _create(client: AsyncClient, headers: dict[str, str], email: str):  # type: ignore[no-untyped-def]
    return client.post(
        "/v1/onboarding-cases", headers=headers, json=_case_payload(personal_email=email)
    )


async def _cases(company_id: UUID, email: str | None = None) -> list[tuple[str, str]]:
    sql = "SELECT personal_email, status FROM onboarding_case WHERE company_id=:cid"
    params: dict[str, Any] = {}
    if email:
        sql += " AND lower(personal_email)=:e"
        params["e"] = email.lower()
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(text(sql), {"cid": str(company_id), **params})
        return [(r[0], r[1]) for r in rows]


async def test_exact_and_case_variant_duplicates_are_refused_without_effect(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        tag = uuid4().hex[:8]
        first = await _create(client, headers, f"Asha.{tag}@Personal.Example")
        assert first.status_code == 201, first.text
        # stored normalised
        assert first.json()["data"]["personal_email"] == f"asha.{tag}@personal.example"

        before = await fingerprint(company_id)
        for variant in (
            f"asha.{tag}@personal.example",  # exact (normalised)
            f"ASHA.{tag}@PERSONAL.EXAMPLE",  # case variant
            f"Asha.{tag}@personal.example",
        ):
            r = await _create(client, headers, variant)
            assert r.status_code == 409, (variant, r.text)
            assert r.json()["error"]["code"] == "DUPLICATE_ACTIVE_ONBOARDING_CASE"
        assert len(await _cases(company_id)) == 1
        assert await fingerprint(company_id) == before  # no row, no audit event

        # unrelated address is unaffected; so is the same address in another tenant
        other = await _create(client, headers, f"someone-else-{tag}@personal.example")
        assert other.status_code == 201
        h2, c2, u2 = await _register_tenant(client)
        try:
            ok = await _create(client, h2, f"asha.{tag}@personal.example")
            assert ok.status_code == 201, ok.text
        finally:
            await _teardown(company_id=c2, user_id=u2)
        assert await audit_count(company_id, "ONBOARDING_CASE_CREATED") == 2
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_def_b11_03_concurrent_creates_for_one_email_make_exactly_one_case(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        tag = uuid4().hex[:8]
        spellings = [f"Race.{tag}@Personal.Example", f"race.{tag}@personal.example"] * 4
        results = await asyncio.gather(*[_create(client, headers, e) for e in spellings])
        codes = sorted(r.status_code for r in results)
        assert codes == [201] + [409] * 7, [(r.status_code, r.text[:100]) for r in results]
        assert not any(r.status_code >= 500 for r in results)
        assert len(await _cases(company_id, f"race.{tag}@personal.example")) == 1
        assert await audit_count(company_id, "ONBOARDING_CASE_CREATED") == 1

        # the old failure mode: every later create for that e-mail answered 500 - now a clean 409
        later = await _create(client, headers, f"RACE.{tag}@personal.example")
        assert later.status_code == 409
        assert later.json()["error"]["code"] == "DUPLICATE_ACTIVE_ONBOARDING_CASE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_concurrent_creates_for_different_emails_all_succeed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        emails = [f"cand{i}-{uuid4().hex[:6]}@personal.example" for i in range(6)]
        results = await asyncio.gather(*[_create(client, headers, e) for e in emails])
        assert [r.status_code for r in results] == [201] * 6
        assert len(await _cases(company_id)) == 6
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_legacy_duplicate_rows_with_mixed_case_give_409_not_500_and_retry_is_stable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Synthetic pre-fix data: two active rows for one address in different cases (what the
    concurrent-create defect left behind). The old `scalar_one_or_none()` raised
    `MultipleResultsFound` -> 500 for every create. Now: 409, and a retry gives the same answer."""
    # B13: migration 20261027091000 makes such rows impossible, so this runs as on a database that
    # has not got the index yet (the situation the legacy-tolerant lookup exists for).
    async with live_email_index_absent():
        await _legacy_duplicates_body(client)


async def _legacy_duplicates_body(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        tag = uuid4().hex[:8]
        first = await _create(client, headers, f"legacy.{tag}@personal.example")
        second = await _create(client, headers, f"other.{tag}@personal.example")
        third = await _create(client, headers, f"solo.{tag}@personal.example")
        assert first.status_code == second.status_code == third.status_code == 201
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            # `second` becomes an exact duplicate of `first` (what the concurrent-create defect
            # left behind); `third` becomes a mixed-case row (written before normalisation).
            for case, address in (
                (second, f"legacy.{tag}@personal.example"),
                (third, f"SOLO.{tag}@Personal.Example"),
            ):
                await session.execute(
                    text("UPDATE onboarding_case SET personal_email=:e WHERE id=:i"),
                    {"e": address, "i": case.json()["data"]["id"]},
                )
            await session.commit()
        before = len(await _cases(company_id))
        for attempt in range(2):  # a retry gets the same controlled answer
            for address in (f"Legacy.{tag}@personal.example", f"solo.{tag}@personal.example"):
                r = await _create(client, headers, address)
                assert r.status_code == 409, (attempt, address, r.text)  # old: 500 / 201
                assert r.json()["error"]["code"] == "DUPLICATE_ACTIVE_ONBOARDING_CASE"
        assert len(await _cases(company_id)) == before  # nothing added
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_retry_after_the_blocking_case_is_terminal_is_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        tag = uuid4().hex[:8]
        email = f"retry.{tag}@personal.example"
        first = await _create(client, headers, email)
        assert first.status_code == 201
        assert (await _create(client, headers, email.upper())).status_code == 409
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("UPDATE onboarding_case SET status='CANCELLED' WHERE id=:i"),
                {"i": first.json()["data"]["id"]},
            )
            await session.commit()
        again = await _create(client, headers, email.upper())
        assert again.status_code == 201, again.text
        assert (
            await scalar(
                company_id,
                "SELECT count(*) FROM onboarding_case "
                "WHERE company_id=:cid AND status<>'CANCELLED'",
            )
            == 1
        )
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
