"""SC-01 / SC-02 - shift names: trimmed at the API, unique among live shifts, race-proof.

Rule (owner decisions D-1, D-2): per company, compared as `lower(btrim(name))`, among shifts that
are not deleted. A deactivated shift keeps its name; only a deleted one releases it. Existing stored
values are never rewritten.

Concurrency tests run real parallel requests (separate sessions, separate connections) because the
defect was a check-then-insert race: both requests passed the check before either had committed.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.organisation.service import OrganisationService

from .test_registration_flow import _cleanup
from .test_shift import _cleanup_shifts, _create_shift, _register_tenant

INDEX = "shift_company_live_name_key"
BLANK_CHECK = "shift_live_name_not_blank_check"
ROUNDS = 8


async def _names(company_id: UUID) -> list[str]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT name FROM shift WHERE company_id = :c AND deleted_at IS NULL ORDER BY name"
            ),
            {"c": str(company_id)},
        )
        return [r[0] for r in rows]


async def _drafts(company_id: UUID) -> int:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text("SELECT count(*) FROM shift_version WHERE company_id = :c"), {"c": str(company_id)}
        )
        return int(row.scalar_one())


async def _raw_insert(company_id: UUID, name: str, *, deleted: bool = False) -> None:
    """Writes a shift straight to the table, as a writer that bypasses the service would."""
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "INSERT INTO shift (company_id, name, code, start_time, end_time, deleted_at) "
                "VALUES (:c, :n, :code, '09:00', '18:00', "
                "CASE WHEN :d THEN now() ELSE NULL END)"
            ),
            {"c": str(company_id), "n": name, "code": f"RAW-{uuid4().hex[:6]}", "d": deleted},
        )
        await session.commit()


def _setup_body(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "publish": False,
        "rules": {
            "shift_type": "FIXED",
            "effective_from": "2026-01-01",
            "start_time": "09:00",
            "end_time": "18:00",
        },
    }


# --- SC-02: the API trims and refuses blank names -------------------------------------------------


@pytest.mark.asyncio
async def test_create_stores_the_trimmed_name(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers, name="  Morning  ")
        assert shift["name"] == "Morning"
        assert await _names(company_id) == ["Morning"]
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", " ", "     ", "\t", "\n "])
async def test_create_refuses_a_blank_name(
    client: AsyncClient, seeded_plan_catalogue: None, blank: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post("/v1/shifts", headers=headers, json={"name": blank})
        assert response.status_code == 422, response.text
        assert await _names(company_id) == []
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_rename_trims_and_refuses_blank(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers, name="Day")
        blank = await client.patch(
            f"/v1/shifts/{shift['id']}",
            headers={**headers, "If-Match": str(shift["version"])},
            json={"name": "   "},
        )
        assert blank.status_code == 422, blank.text
        renamed = await client.patch(
            f"/v1/shifts/{shift['id']}",
            headers={**headers, "If-Match": str(shift["version"])},
            json={"name": "  Evening "},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["data"]["name"] == "Evening"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_setup_trims_and_refuses_blank(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        bad = await client.post("/v1/shifts/setup", headers=headers, json=_setup_body("   "))
        assert bad.status_code == 422, bad.text
        good = await client.post("/v1/shifts/setup", headers=headers, json=_setup_body("  Setup "))
        assert good.status_code == 201, good.text
        assert good.json()["data"]["shift"]["name"] == "Setup"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_break_names_are_trimmed_and_blank_refused(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        url = f"/v1/shifts/{shift['id']}/versions/{shift['draft_version_id']}"

        def body(name: str) -> dict[str, Any]:
            return {
                "breaks": [
                    {
                        "name": name,
                        "break_kind": "FIXED_WINDOW",
                        "start_time": "13:00",
                        "end_time": "14:00",
                    }
                ]
            }

        blank = await client.patch(url, headers={**headers, "If-Match": "1"}, json=body("  "))
        assert blank.status_code == 422, blank.text
        ok = await client.patch(url, headers={**headers, "If-Match": "1"}, json=body(" Lunch "))
        assert ok.status_code == 200, ok.text
        assert ok.json()["data"]["breaks"][0]["name"] == "Lunch"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- SC-01: uniqueness rules ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["morning", "MORNING", "  Morning ", "mOrNiNg\t"])
async def test_duplicate_names_are_refused_ignoring_case_and_spaces(
    client: AsyncClient, seeded_plan_catalogue: None, variant: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_shift(client, headers, name="Morning")
        dup = await client.post("/v1/shifts", headers=headers, json={"name": variant})
        assert dup.status_code == 409, dup.text
        assert dup.json()["error"]["code"] == "SHIFT_NAME_ALREADY_EXISTS"
        assert await _names(company_id) == ["Morning"]
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_the_same_name_in_two_companies_is_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await _create_shift(client, headers_a, name="Morning")
        await _create_shift(client, headers_b, name="Morning")
        assert await _names(company_a) == ["Morning"]
        assert await _names(company_b) == ["Morning"]
    finally:
        await _cleanup_shifts(company_id=company_a)
        await _cleanup_shifts(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_a_deactivated_shift_keeps_its_name(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """D-1."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers, name="Night")
        off = await client.delete(
            f"/v1/shifts/{shift['id']}", headers={**headers, "If-Match": str(shift["version"])}
        )
        assert off.status_code == 200, off.text
        assert off.json()["data"]["is_active"] is False
        again = await client.post("/v1/shifts", headers=headers, json={"name": "night"})
        assert again.status_code == 409, again.text
        assert again.json()["error"]["code"] == "SHIFT_NAME_ALREADY_EXISTS"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_a_deleted_shift_releases_its_name(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers, name="Old")
        off = await client.delete(
            f"/v1/shifts/{shift['id']}", headers={**headers, "If-Match": str(shift["version"])}
        )
        assert off.status_code == 200, off.text
        deleted = await client.post(
            f"/v1/shifts/{shift['id']}/delete",
            headers={**headers, "If-Match": str(off.json()["data"]["version"])},
            json={
                "confirm_name": "Old",
                "reason": "created by mistake, never used",
                "acknowledge_irreversible": True,
            },
        )
        assert deleted.status_code == 204, deleted.text
        reused = await client.post("/v1/shifts", headers=headers, json={"name": "Old"})
        assert reused.status_code == 201, reused.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_rename_to_an_existing_name_is_refused_but_to_its_own_is_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        a = await _create_shift(client, headers, name="Alpha")
        b = await _create_shift(client, headers, name="Beta")
        clash = await client.patch(
            f"/v1/shifts/{b['id']}",
            headers={**headers, "If-Match": str(b["version"])},
            json={"name": " ALPHA "},
        )
        assert clash.status_code == 409, clash.text
        recase = await client.patch(
            f"/v1/shifts/{a['id']}",
            headers={**headers, "If-Match": str(a["version"])},
            json={"name": "alpha"},
        )
        assert recase.status_code == 200, recase.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- SC-01: concurrency ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_creates_of_one_name_make_exactly_one_shift(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for round_no in range(ROUNDS):
            name = f"Race {round_no}"
            variants = [name, name.upper(), f"  {name}  ", name.lower()]
            results = await asyncio.gather(
                *(client.post("/v1/shifts", headers=headers, json={"name": v}) for v in variants)
            )
            codes = sorted(r.status_code for r in results)
            assert codes == [201, 409, 409, 409], [r.text for r in results]
            for r in results:
                if r.status_code == 409:
                    assert r.json()["error"]["code"] == "SHIFT_NAME_ALREADY_EXISTS"
        names = await _names(company_id)
        assert len(names) == ROUNDS and len({n.lower() for n in names}) == ROUNDS
        # Every shift has exactly its one draft: no half-made shift from a losing request.
        assert await _drafts(company_id) == ROUNDS
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_parallel_creates_of_different_names_all_succeed_with_distinct_codes(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The name lock must not turn into a global lock, and code assignment stays correct."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        results = await asyncio.gather(
            *(
                client.post("/v1/shifts", headers=headers, json={"name": f"Shift {i}"})
                for i in range(6)
            )
        )
        assert [r.status_code for r in results] == [201] * 6, [r.text for r in results]
        codes = [r.json()["data"]["code"] for r in results]
        assert len(set(codes)) == 6
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_parallel_setups_of_one_name_leave_no_orphan(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for round_no in range(ROUNDS):
            name = f"Setup race {round_no}"
            results = await asyncio.gather(
                *(
                    client.post("/v1/shifts/setup", headers=headers, json=_setup_body(v))
                    for v in (name, name.upper(), f" {name} ")
                )
            )
            assert sorted(r.status_code for r in results) == [201, 409, 409], [
                r.text for r in results
            ]
        assert len(await _names(company_id)) == ROUNDS
        assert await _drafts(company_id) == ROUNDS
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_parallel_renames_to_one_name_allow_exactly_one(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for round_no in range(ROUNDS):
            shifts = [
                await _create_shift(client, headers, name=f"R{round_no}-{i}") for i in range(3)
            ]
            target = f"Target {round_no}"
            results = await asyncio.gather(
                *(
                    client.patch(
                        f"/v1/shifts/{s['id']}",
                        headers={**headers, "If-Match": str(s["version"])},
                        json={"name": target},
                    )
                    for s in shifts
                )
            )
            assert sorted(r.status_code for r in results) == [200, 409, 409], [
                r.text for r in results
            ]
        lowered = [n.lower() for n in await _names(company_id)]
        assert len(lowered) == len(set(lowered))
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_a_create_racing_a_rename_cannot_both_win(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for round_no in range(ROUNDS):
            existing = await _create_shift(client, headers, name=f"Old {round_no}")
            target = f"Contested {round_no}"
            create, rename = await asyncio.gather(
                client.post("/v1/shifts", headers=headers, json={"name": target}),
                client.patch(
                    f"/v1/shifts/{existing['id']}",
                    headers={**headers, "If-Match": str(existing["version"])},
                    json={"name": target.upper()},
                ),
            )
            assert sorted([create.status_code, rename.status_code]) in ([200, 409], [201, 409])
        lowered = [n.lower() for n in await _names(company_id)]
        assert len(lowered) == len(set(lowered))
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- SC-01: the database backstop -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_database_refuses_a_duplicate_written_around_the_service(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_shift(client, headers, name="Morning")
        with pytest.raises(IntegrityError, match=INDEX):
            await _raw_insert(company_id, " MORNING ")
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_the_database_refuses_a_blank_live_name_but_allows_a_deleted_one(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for blank in ("", "   ", "\t "):
            with pytest.raises((IntegrityError, DBAPIError), match=BLANK_CHECK):
                await _raw_insert(company_id, blank)
        await _raw_insert(company_id, "   ", deleted=True)  # a deleted shift is history
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_a_duplicate_that_reaches_the_index_becomes_the_same_409(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates a writer that got past the name check (the check is disabled here): the unique
    index still refuses it and the service reports it exactly like the checked duplicate."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers, name="Morning")
        other = await _create_shift(client, headers, name="Other")

        async def _skip(self: Any, *args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr(OrganisationService, "_assert_shift_name_free", _skip)
        created = await client.post("/v1/shifts", headers=headers, json={"name": " morning "})
        assert created.status_code == 409, created.text
        assert created.json()["error"]["code"] == "SHIFT_NAME_ALREADY_EXISTS"
        renamed = await client.patch(
            f"/v1/shifts/{other['id']}",
            headers={**headers, "If-Match": str(other["version"])},
            json={"name": "MORNING"},
        )
        assert renamed.status_code == 409, renamed.text
        assert renamed.json()["error"]["code"] == "SHIFT_NAME_ALREADY_EXISTS"
        assert shift["name"] == "Morning"
        assert await _names(company_id) == ["Morning", "Other"]
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_existing_shifts_with_their_stored_names_are_unaffected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """D-2: nothing rewrites stored names. A shift stored with padding before SC-02 can still be
    read, renamed to something else, and compared by its trimmed form."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _raw_insert(company_id, "  Legacy  ")
        listed = await client.get("/v1/shifts", headers=headers)
        assert [s["name"] for s in listed.json()["data"]] == ["  Legacy  "]
        dup = await client.post("/v1/shifts", headers=headers, json={"name": "legacy"})
        assert dup.status_code == 409, dup.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
