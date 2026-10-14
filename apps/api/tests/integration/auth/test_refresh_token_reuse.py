"""TXN-01 (`docs/audits/LOGGING_ERROR_HANDLING_OBSERVABILITY_PLAN.md`) — refresh-token reuse
detection must revoke the token family *durably*. Before the fix the revocation was written and
then `InvalidTokenError` was raised, and `get_session` rolled the request transaction back,
silently undoing it: the newest token in a stolen family kept working.

Each request goes through the real app (`client` fixture), so the request-scoped session,
its commit/rollback, and the exception handlers are all the production ones."""

import asyncio
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from hrms.core.auth.tokens import hash_token
from hrms.core.db.models.identity import RefreshToken, Session
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import get_session_factory
from hrms.seed.constants import ADMIN_EMAIL, COMPANY_A_ID, DEMO_PASSWORD


async def _login(client: AsyncClient) -> tuple[str, str]:
    response = await client.post(
        "/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD, "company_id": str(COMPANY_A_ID)},
    )
    assert response.status_code == 200
    refresh = response.cookies.get("hrms_refresh")
    assert refresh
    return response.json()["data"]["access_token"], refresh


async def _refresh(client: AsyncClient, token: str):  # type: ignore[no-untyped-def]
    return await client.post("/v1/auth/token/refresh", json={"refresh_token": token})


async def _family_rows(token: str) -> tuple[list[RefreshToken], list[Session]]:
    async with get_session_factory()() as session:
        record = (
            await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
            )
        ).scalar_one()
        family = list(
            (
                await session.execute(
                    select(RefreshToken).where(
                        RefreshToken.token_family_id == record.token_family_id
                    )
                )
            ).scalars()
        )
        sessions = list(
            (
                await session.execute(
                    select(Session).where(Session.id.in_({r.session_id for r in family}))
                )
            ).scalars()
        )
        return family, sessions


async def test_reuse_revokes_family_and_session_durably(
    client: AsyncClient, seeded_db: None
) -> None:
    _, old = await _login(client)
    rotated = await _refresh(client, old)
    assert rotated.status_code == 200
    newest = rotated.cookies.get("hrms_refresh")
    newest_access = rotated.json()["data"]["access_token"]

    reuse = await _refresh(client, old)
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "INVALID_TOKEN"

    # Read back through a fresh connection: the revocation survived the failed request.
    family, sessions = await _family_rows(newest)
    assert len(family) == 2
    newest_row = next(r for r in family if r.token_hash == hash_token(newest))
    assert newest_row.revoked_at is not None
    assert newest_row.revoked_reason == "REUSE_DETECTED"
    assert all(s.revoked_at is not None for s in sessions)

    # Both the newest refresh token and an access token minted for that session are dead.
    assert (await _refresh(client, newest)).status_code == 401
    me = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {newest_access}"})
    assert me.status_code == 401


async def test_reuse_does_not_touch_an_unrelated_family(
    client: AsyncClient, seeded_db: None
) -> None:
    _, victim_old = await _login(client)
    _, other = await _login(client)  # a second, independent login = its own family

    assert (await _refresh(client, victim_old)).status_code == 200
    assert (await _refresh(client, victim_old)).status_code == 401  # reuse

    other_family, other_sessions = await _family_rows(other)
    assert all(r.revoked_at is None for r in other_family)
    assert all(s.revoked_at is None for s in other_sessions)
    assert (await _refresh(client, other)).status_code == 200


async def test_concurrent_refresh_of_one_token_has_a_single_winner(
    client: AsyncClient, seeded_db: None
) -> None:
    """Two requests presenting the same token at once: the conditional rotation lets exactly one
    rotate it. The loser is indistinguishable from a replay, so — by design, and documented in
    the remediation report as a known UX limitation for multi-tab clients — the family is then
    revoked and the winner's new token is dead too. What must never happen is two live
    descendants of one token."""
    _, token = await _login(client)

    first, second = await asyncio.gather(_refresh(client, token), _refresh(client, token))
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 401]

    winner = first if first.status_code == 200 else second
    winner_token = winner.json().get("data") and winner.cookies.get("hrms_refresh")
    assert winner_token
    family, _ = await _family_rows(winner_token)
    # one original + one descendant, never two descendants
    assert len(family) == 2
    assert all(r.revoked_at is not None for r in family)
    assert (await _refresh(client, winner_token)).status_code == 401


async def test_revocation_failure_is_a_server_error_not_a_revoked_401(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the family cannot be revoked, the caller must not be told "revoked" (401), and nothing
    may be half-written: the response is the generic 500 and the newest token is untouched."""
    _, old = await _login(client)
    rotated = await _refresh(client, old)
    newest = rotated.cookies.get("hrms_refresh")

    async def _fail(self: IdentityRepository, session: object, family_id: UUID, reason: str):  # type: ignore[no-untyped-def]
        raise OperationalError("UPDATE refresh_token ...", {}, Exception("connection lost"))

    monkeypatch.setattr(IdentityRepository, "revoke_refresh_family", _fail)
    reuse = await _refresh(client, old)
    assert reuse.status_code == 500
    assert reuse.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "connection lost" not in reuse.text

    monkeypatch.undo()
    family, _ = await _family_rows(newest)
    newest_row = next(r for r in family if r.token_hash == hash_token(newest))
    assert newest_row.revoked_at is None


async def test_conditional_rotation_is_single_winner_under_a_row_lock(
    client: AsyncClient, seeded_db: None
) -> None:
    """Deterministic version of the race above, at the repository layer: transaction A rotates
    the token and holds the row lock; transaction B's rotation blocks on it, and once A commits,
    B re-checks `revoked_at IS NULL` and reports that it did *not* rotate."""
    _, token = await _login(client)
    repo = IdentityRepository()
    factory = get_session_factory()
    async with factory() as probe:
        token_id = (
            await probe.execute(
                select(RefreshToken.id).where(RefreshToken.token_hash == hash_token(token))
            )
        ).scalar_one()

    async with factory() as a, factory() as b:
        assert await repo.rotate_refresh_token(a, token_id) is True
        b_attempt = asyncio.create_task(repo.rotate_refresh_token(b, token_id))
        await asyncio.sleep(0.3)
        assert not b_attempt.done()  # blocked on A's row lock
        await a.commit()
        assert await b_attempt is False
        await b.rollback()
