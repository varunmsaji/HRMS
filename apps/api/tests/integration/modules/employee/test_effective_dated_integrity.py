"""Integrity of the four effective-dated employee histories — compensation, statutory, bank and
assignment — which payroll reads "as of" a date, so a gap, an overlap or two open rows is a wrong
paycheque.

One harness, four resources: contiguity after repeated revisions, as-of boundary reads, the
version-required / stale / backdated / same-day rules, and a concurrency race on the same
`If-Match` (exactly one writer may win; nobody may 500)."""

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from ...tenant_wipe import wipe_tenant
from .conftest import seeded_plan_catalogue  # noqa: F401
from .test_employee_assignment import (
    _create_branch,
    _create_department,
    _create_designation,
    _create_employee,
    _create_employment,
    _create_legal_entity,
    _register_tenant,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

JOIN = date(2027, 6, 1)


def _d(offset_days: int) -> str:
    return (JOIN + timedelta(days=offset_days)).isoformat()


async def _setup(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    employee = await _create_employee(client, headers)
    entity = await _create_legal_entity(client, headers)
    await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=entity["id"],
        joining_date=JOIN.isoformat(),
    )
    branch = await _create_branch(client, headers, entity["id"])
    dept = await _create_department(client, headers)
    desig = await _create_designation(client, headers)
    return {"employee_id": employee["id"], "refs": (branch["id"], dept["id"], desig["id"])}


def _resources(refs: tuple[str, str, str]) -> dict[str, Callable[[str, int], dict[str, Any]]]:
    branch, dept, desig = refs

    def comp(eff: str, n: int) -> dict[str, Any]:
        return {
            "effective_from": eff,
            "annual_ctc_minor": 10_00_000_00 + n * 1000,
            "currency": "INR",
            "revision_type": "ANNUAL",
            "revision_reason": f"rev {n}",
        }

    def stat(eff: str, n: int) -> dict[str, Any]:
        return {
            "effective_from": eff,
            "is_pf_applicable": True,
            "is_esi_applicable": False,
            "is_lwf_applicable": False,
            "tax_regime": "NEW",
            "revision_reason": f"rev {n}",
        }

    def bank(eff: str, n: int) -> dict[str, Any]:
        return {
            "effective_from": eff,
            "account_holder_name": f"Holder {n}",
            "bank_name": "HDFC",
            "ifsc": "HDFC0001234",
            "payment_mode": "BANK",
        }

    def assign(eff: str, n: int) -> dict[str, Any]:
        base: dict[str, Any] = {
            "effective_from": eff,
            "change_type": "INITIAL" if n == 0 else "TRANSFER",
            "work_location_type": "OFFICE" if n % 2 == 0 else "HYBRID",
        }
        if n == 0:
            base.update(branch_id=branch, department_id=dept, designation_id=desig)
        return base

    return {"compensation": comp, "statutory": stat, "bank": bank, "assignments": assign}


RESOURCES = ["compensation", "statutory", "bank", "assignments"]


async def _post(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    resource: str,
    body: dict[str, Any],
    if_match: str | None = None,
):
    h = dict(headers)
    if if_match is not None:
        h["If-Match"] = if_match
    return await client.post(f"/v1/employees/{employee_id}/{resource}", headers=h, json=body)


async def _history(client, headers, employee_id, resource) -> list[dict[str, Any]]:
    r = await client.get(f"/v1/employees/{employee_id}/{resource}", headers=headers)
    assert r.status_code == 200, r.text
    return list(r.json()["data"])


def _assert_contiguous(rows: list[dict[str, Any]]) -> None:
    rows = sorted(rows, key=lambda r: r["effective_from"])
    assert rows, "history empty"
    assert sum(1 for r in rows if r["effective_to"] is None) == 1, "exactly one open row"
    assert rows[-1]["effective_to"] is None
    for prev, nxt in zip(rows, rows[1:], strict=False):
        assert prev["effective_to"] is not None
        expected = date.fromisoformat(nxt["effective_from"]) - timedelta(days=1)
        assert prev["effective_to"] == expected.isoformat(), (prev, nxt)
        assert prev["effective_from"] <= prev["effective_to"]


@pytest.mark.parametrize("resource", RESOURCES)
async def test_history_stays_contiguous_and_as_of_reads_hit_the_right_row(
    client: AsyncClient, resource: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        eid = ctx["employee_id"]
        make = _resources(ctx["refs"])[resource]
        dates = [_d(0), _d(92), _d(200), _d(400)]

        version: str | None = None
        for n, eff in enumerate(dates):
            r = await _post(client, headers, eid, resource, make(eff, n), version)
            assert r.status_code == 201, (resource, n, r.text)
            # the new row's own version is what the next write must quote
            version = str(r.json()["data"]["version"])

        rows = await _history(client, headers, eid, resource)
        assert len(rows) == 4
        _assert_contiguous(rows)

        # as-of boundary reads: day before a revision → previous row; day of → new row
        ordered = sorted(rows, key=lambda r: r["effective_from"])
        for i in range(1, 4):
            boundary = date.fromisoformat(dates[i])
            for as_of, want in (
                (boundary - timedelta(days=1), ordered[i - 1]["id"]),
                (boundary, ordered[i]["id"]),
            ):
                r = await client.get(
                    f"/v1/employees/{eid}/{resource}",
                    headers=headers,
                    params={"as_of": as_of.isoformat()},
                )
                assert r.status_code == 200, r.text
                got = r.json()["data"]
                assert [x["id"] for x in got] == [want], (resource, as_of)
        # before the first row there is nothing
        r = await client.get(
            f"/v1/employees/{eid}/{resource}",
            headers=headers,
            params={"as_of": (JOIN - timedelta(days=1)).isoformat()},
        )
        assert r.json()["data"] == []
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize("resource", RESOURCES)
async def test_revision_rules_backdated_same_day_missing_and_stale_version(
    client: AsyncClient, resource: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        eid = ctx["employee_id"]
        make = _resources(ctx["refs"])[resource]
        first = await _post(client, headers, eid, resource, make(_d(10), 0))
        assert first.status_code == 201, first.text
        v1 = str(first.json()["data"]["version"])
        before = await _history(client, headers, eid, resource)

        async def attempt(eff: str, if_match: str | None):
            return await _post(client, headers, eid, resource, make(eff, 1), if_match)

        same_day = await attempt(_d(10), v1)
        backdated = await attempt(_d(5), v1)
        assert same_day.status_code in (409, 422), same_day.text
        assert backdated.status_code in (409, 422), backdated.text
        missing = await attempt(_d(50), None)
        assert missing.status_code in (409, 422, 428), missing.text
        stale = await attempt(_d(50), str(int(v1) + 7))
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] == "STALE_RESOURCE"
        junk = await attempt(_d(50), "abc")
        assert junk.status_code == 422 and junk.json()["error"]["code"] == "INVALID_IF_MATCH"

        # none of the refusals changed anything
        assert await _history(client, headers, eid, resource) == before

        ok = await attempt(_d(50), v1)
        assert ok.status_code == 201, ok.text
        _assert_contiguous(await _history(client, headers, eid, resource))
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize("resource", RESOURCES)
async def test_concurrent_revisions_with_the_same_version_have_exactly_one_winner(
    client: AsyncClient, resource: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        eid = ctx["employee_id"]
        make = _resources(ctx["refs"])[resource]
        first = await _post(client, headers, eid, resource, make(_d(0), 0))
        assert first.status_code == 201, first.text
        v1 = str(first.json()["data"]["version"])

        results = await asyncio.gather(
            *[_post(client, headers, eid, resource, make(_d(30 + i), i + 1), v1) for i in range(6)],
            return_exceptions=True,
        )
        escaped = [r for r in results if isinstance(r, BaseException)]
        assert not escaped, f"unhandled exception escaped the app: {escaped[:2]}"
        statuses = sorted(r.status_code for r in results)
        assert statuses.count(201) == 1, statuses
        assert all(s in (201, 409) for s in statuses), statuses
        rows = await _history(client, headers, eid, resource)
        assert len(rows) == 2
        _assert_contiguous(rows)
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize("resource", RESOURCES)
async def test_a_stale_if_match_is_a_409_even_when_the_date_is_also_invalid(
    client: AsyncClient, resource: str
) -> None:
    """Deterministic form of the race `test_concurrent_revisions_...` only hits by chance (it failed
    7 runs in 12 before the fix): a writer whose token was already superseded, and whose
    `effective_from` is also no longer later than the winner's, used to be told 422
    INVALID_EFFECTIVE_FROM - a complaint about a date it could not have known was wrong. The honest
    answer is 409 STALE_RESOURCE (reload and retry). No concurrency, no timing."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        eid = ctx["employee_id"]
        make = _resources(ctx["refs"])[resource]
        first = await _post(client, headers, eid, resource, make(_d(0), 0))
        v1 = str(first.json()["data"]["version"])

        winner = await _post(client, headers, eid, resource, make(_d(30), 1), v1)
        assert winner.status_code == 201, winner.text

        # Same consumed token, and a date that is NOT after the winner's row: both rules are
        # broken, and the stale token must be the one reported.
        loser = await _post(client, headers, eid, resource, make(_d(20), 2), v1)
        assert loser.status_code == 409, loser.text
        assert loser.json()["error"]["code"] == "STALE_RESOURCE"

        # A *current* token still gets the date rule: precedence changed, validation did not.
        current = str(winner.json()["data"]["version"])
        bad_date = await _post(client, headers, eid, resource, make(_d(20), 3), current)
        assert bad_date.status_code == 422, bad_date.text
        assert bad_date.json()["error"]["code"] == "INVALID_EFFECTIVE_FROM"

        assert len(await _history(client, headers, eid, resource)) == 2
        _assert_contiguous(await _history(client, headers, eid, resource))
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_compensation_and_statutory_need_a_covering_employment(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        eid = ctx["employee_id"]
        make = _resources(ctx["refs"])
        for resource in ("compensation", "statutory", "bank", "assignments"):
            r = await _post(client, headers, eid, resource, make[resource](_d(-1), 0))
            assert r.status_code in (409, 422), (resource, r.status_code, r.text)
            assert await _history(client, headers, eid, resource) == []
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize("resource", RESOURCES)
async def test_a_consumed_if_match_token_can_never_be_replayed_against_a_later_row(
    client: AsyncClient, resource: str
) -> None:
    """Regression (ABA): new rows used to restart at version 1, so the token a first revision had
    already consumed matched the next row too — a second user holding the old page silently
    stacked their change on top of the first user's. Deterministic, no concurrency needed."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        eid = ctx["employee_id"]
        make = _resources(ctx["refs"])[resource]
        first = await _post(client, headers, eid, resource, make(_d(0), 0))
        v1 = str(first.json()["data"]["version"])

        winner = await _post(client, headers, eid, resource, make(_d(30), 1), v1)
        assert winner.status_code == 201, winner.text

        replay = await _post(client, headers, eid, resource, make(_d(60), 2), v1)
        assert replay.status_code == 409, replay.text
        assert replay.json()["error"]["code"] == "STALE_RESOURCE"
        assert len(await _history(client, headers, eid, resource)) == 2

        # versions are strictly increasing along the chain
        rows = sorted(
            await _history(client, headers, eid, resource), key=lambda r: r["effective_from"]
        )
        assert rows[0]["version"] < rows[1]["version"]
        # quoting the *current* row's version works
        ok = await _post(client, headers, eid, resource, make(_d(60), 2), str(rows[1]["version"]))
        assert ok.status_code == 201, ok.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)
