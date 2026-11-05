"""Rules around policy assignments and workforce calendars that no other suite exercises:
references to missing / foreign-tenant policies, the effective-dated assignment chain (including
the replayed-`If-Match` regression), parallel writers, calendar deactivation while in use, and
holiday / work-calendar parent references."""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from ...tenant_wipe import wipe_tenant
from ..employee.test_employee_assignment import _register_tenant
from .conftest import seeded_plan_catalogue  # noqa: F401
from .test_workforce_calendar import (
    _create_holiday_calendar,
    _create_weekly_off_pattern,
    _create_work_calendar,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]


def _body(kind: str, policy_id: str, eff: str, **extra: Any) -> dict[str, Any]:
    return {
        "policy_kind": kind,
        "policy_id": policy_id,
        "scope_type": "COMPANY",
        "effective_from": eff,
        **extra,
    }


async def _assign(client, headers, body, if_match=None):
    h = dict(headers)
    if if_match is not None:
        h["If-Match"] = str(if_match)
    return await client.post("/v1/policy-assignments", headers=h, json=body)


async def _history(client, headers, kind) -> list[dict[str, Any]]:
    r = await client.get(
        "/v1/policy-assignments", headers=headers, params={"policy_kind": kind, "page_size": 100}
    )
    assert r.status_code == 200, r.text
    return list(r.json()["data"])


# ---------------------------------------------------------------- references


async def test_policy_assignment_reference_and_scope_validation(client: AsyncClient) -> None:
    ha, ca, ua = await _register_tenant(client)
    hb, cb, ub = await _register_tenant(client)
    try:
        mine = await _create_work_calendar(client, ha)
        foreign = await _create_work_calendar(client, hb)

        # unknown kind / scope type: schema-level 422
        for patch in ({"policy_kind": "NOPE"}, {"scope_type": "GALAXY"}):
            r = await _assign(
                client, ha, {**_body("WORK_CALENDAR", mine["id"], "2027-01-01"), **patch}
            )
            assert r.status_code == 422, (patch, r.text)

        # COMPANY scope must not carry a scope_id; any other scope requires one
        r = await _assign(
            client, ha, _body("WORK_CALENDAR", mine["id"], "2027-01-01", scope_id=str(uuid4()))
        )
        assert r.status_code == 422
        r = await _assign(
            client, ha, _body("WORK_CALENDAR", mine["id"], "2027-01-01", scope_type="BRANCH")
        )
        assert r.status_code == 422

        # missing and foreign-tenant policies are indistinguishable: INVALID_POLICY_REFERENCE
        for bad in (str(uuid4()), foreign["id"]):
            r = await _assign(client, ha, _body("WORK_CALENDAR", bad, "2027-01-01"))
            assert r.status_code == 422, r.text
            assert r.json()["error"]["code"] == "INVALID_POLICY_REFERENCE"
            r = await _assign(client, ha, _body("WEEKLY_OFF", bad, "2027-01-01"))
            assert r.status_code == 422
            assert r.json()["error"]["code"] == "INVALID_POLICY_REFERENCE"

        # a work-calendar id cannot be used as a WEEKLY_OFF policy (kinds don't cross)
        r = await _assign(client, ha, _body("WEEKLY_OFF", mine["id"], "2027-01-01"))
        assert r.status_code == 422

        # LEAVE_POLICY needs its leave_type_id; the other kinds must not carry one
        r = await _assign(client, ha, _body("LEAVE_POLICY", str(uuid4()), "2027-01-01"))
        assert r.status_code == 422

        assert await _history(client, ha, "WORK_CALENDAR") == []
    finally:
        await wipe_tenant(company_id=ca, user_id=ua)
        await wipe_tenant(company_id=cb, user_id=ub)


async def test_scope_target_must_exist_in_this_company(client: AsyncClient) -> None:
    """A BRANCH/DEPARTMENT/LEGAL_ENTITY-scoped assignment aimed at an id that is not one of this
    company's records would silently never apply — a typo the admin never learns about."""
    ha, ca, ua = await _register_tenant(client)
    hb, cb, ub = await _register_tenant(client)
    try:
        cal = await _create_work_calendar(client, ha)
        other_dept = (
            await client.post("/v1/departments", headers=hb, json={"name": "Foreign Dept"})
        ).json()["data"]
        for scope_type, scope_id in (
            ("DEPARTMENT", str(uuid4())),
            ("DEPARTMENT", other_dept["id"]),
            ("BRANCH", str(uuid4())),
            ("LEGAL_ENTITY", str(uuid4())),
        ):
            r = await _assign(
                client,
                ha,
                _body(
                    "WORK_CALENDAR",
                    cal["id"],
                    "2027-01-01",
                    scope_type=scope_type,
                    scope_id=scope_id,
                ),
            )
            assert r.status_code == 422, (scope_type, r.status_code, r.text[:200])
        mine = (await client.post("/v1/departments", headers=ha, json={"name": "Mine"})).json()[
            "data"
        ]
        ok = await _assign(
            client,
            ha,
            _body(
                "WORK_CALENDAR",
                cal["id"],
                "2027-01-01",
                scope_type="DEPARTMENT",
                scope_id=mine["id"],
            ),
        )
        assert ok.status_code == 201, ok.text
    finally:
        await wipe_tenant(company_id=ca, user_id=ua)
        await wipe_tenant(company_id=cb, user_id=ub)


# ---------------------------------------------------------------- the effective-dated chain


async def test_policy_assignment_chain_rules(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        c1 = await _create_work_calendar(client, headers, name="One")
        c2 = await _create_work_calendar(client, headers, name="Two")
        c3 = await _create_work_calendar(client, headers, name="Three")

        first = await _assign(client, headers, _body("WORK_CALENDAR", c1["id"], "2027-01-01"))
        assert first.status_code == 201, first.text
        v1 = first.json()["data"]["version"]

        # same day / earlier than the open row, no token, stale token, junk token
        assert (
            await _assign(client, headers, _body("WORK_CALENDAR", c2["id"], "2027-01-01"), v1)
        ).status_code == 422
        assert (
            await _assign(client, headers, _body("WORK_CALENDAR", c2["id"], "2026-12-01"), v1)
        ).status_code == 422
        missing = await _assign(client, headers, _body("WORK_CALENDAR", c2["id"], "2027-03-01"))
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "POLICY_ASSIGNMENT_VERSION_REQUIRED"
        stale = await _assign(
            client, headers, _body("WORK_CALENDAR", c2["id"], "2027-03-01"), v1 + 9
        )
        assert stale.status_code == 409
        junk = await _assign(client, headers, _body("WORK_CALENDAR", c2["id"], "2027-03-01"), "abc")
        assert junk.status_code == 422 and junk.json()["error"]["code"] == "INVALID_IF_MATCH"
        assert len(await _history(client, headers, "WORK_CALENDAR")) == 1

        second = await _assign(client, headers, _body("WORK_CALENDAR", c2["id"], "2027-03-01"), v1)
        assert second.status_code == 201, second.text

        # the token the first revision consumed must not work against the new open row (ABA)
        replay = await _assign(client, headers, _body("WORK_CALENDAR", c3["id"], "2027-06-01"), v1)
        assert replay.status_code == 409, replay.text
        assert replay.json()["error"]["code"] == "STALE_RESOURCE"

        rows = sorted(
            await _history(client, headers, "WORK_CALENDAR"), key=lambda r: r["effective_from"]
        )
        assert [r["effective_to"] for r in rows] == ["2027-02-28", None]
        assert rows[0]["version"] < rows[1]["version"]
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_stale_assignment_is_reported_as_stale_whatever_its_date(client: AsyncClient) -> None:
    """Someone assigned a later date first. The stale caller must hear that it is stale, not that
    its date is invalid against a row it has never seen."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        base = await _create_work_calendar(client, headers, name="Base")
        first = await _assign(client, headers, _body("WORK_CALENDAR", base["id"], "2027-01-01"))
        version = first.json()["data"]["version"]
        late = await _create_work_calendar(client, headers, name="Late")
        early = await _create_work_calendar(client, headers, name="Early")

        winner = await _assign(
            client, headers, _body("WORK_CALENDAR", late["id"], "2027-06-01"), version
        )
        assert winner.status_code == 201, winner.text
        loser = await _assign(
            client, headers, _body("WORK_CALENDAR", early["id"], "2027-02-01"), version
        )
        assert loser.status_code == 409, loser.text
        assert loser.json()["error"]["code"] == "STALE_RESOURCE"

        # With the current version the same date really is invalid.
        fresh = await _assign(
            client,
            headers,
            _body("WORK_CALENDAR", early["id"], "2027-02-01"),
            winner.json()["data"]["version"],
        )
        assert fresh.status_code == 422, fresh.text
        assert fresh.json()["error"]["code"] == "INVALID_EFFECTIVE_FROM"
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_parallel_policy_assignments_have_a_single_winner(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        base = await _create_work_calendar(client, headers, name="Base")
        first = await _assign(client, headers, _body("WORK_CALENDAR", base["id"], "2027-01-01"))
        v1 = first.json()["data"]["version"]
        cals = [await _create_work_calendar(client, headers, name=f"C{i}") for i in range(5)]
        results = await asyncio.gather(
            *[
                _assign(client, headers, _body("WORK_CALENDAR", c["id"], f"2027-0{2 + i}-01"), v1)
                for i, c in enumerate(cals)
            ],
            return_exceptions=True,
        )
        escaped = [r for r in results if isinstance(r, BaseException)]
        assert not escaped, f"unhandled exception escaped the app: {escaped[:2]}"
        statuses = sorted(r.status_code for r in results)
        assert statuses.count(201) == 1 and set(statuses) <= {201, 409}, statuses
        rows = await _history(client, headers, "WORK_CALENDAR")
        assert len(rows) == 2 and sum(1 for r in rows if r["effective_to"] is None) == 1
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------- calendars


async def test_work_calendar_cannot_be_deactivated_while_assigned(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        cal = await _create_work_calendar(client, headers)
        a = await _assign(client, headers, _body("WORK_CALENDAR", cal["id"], "2027-01-01"))
        assert a.status_code == 201
        d = await client.delete(
            f"/v1/work-calendars/{cal['id']}",
            headers={**headers, "If-Match": str(cal["version"])},
        )
        assert d.status_code == 409, d.text
        assert d.json()["error"]["code"] == "WORK_CALENDAR_HAS_ACTIVE_ASSIGNMENTS"

        other = await _create_work_calendar(client, headers, name="Other")
        free = await client.delete(
            f"/v1/work-calendars/{other['id']}",
            headers={**headers, "If-Match": str(other["version"])},
        )
        assert free.status_code == 200, free.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_calendar_parents_must_exist_in_this_company(client: AsyncClient) -> None:
    ha, ca, ua = await _register_tenant(client)
    hb, cb, ub = await _register_tenant(client)
    try:
        foreign_hc = await _create_holiday_calendar(client, hb)
        foreign_wc = await _create_work_calendar(client, hb)
        foreign_pattern = await _create_weekly_off_pattern(client, hb)

        # holiday into a missing / foreign holiday calendar
        for cal_id in (str(uuid4()), foreign_hc["id"]):
            r = await client.post(
                f"/v1/holiday-calendars/{cal_id}/holidays",
                headers=ha,
                json={"date": "2027-01-26", "name": "Republic Day"},
            )
            assert r.status_code in (404, 422), r.text
            if r.status_code == 422:
                assert r.json()["error"]["code"] == "INVALID_HOLIDAY_CALENDAR"

        # calendar exception into a missing / foreign work calendar
        for cal_id in (str(uuid4()), foreign_wc["id"]):
            r = await client.post(
                f"/v1/work-calendars/{cal_id}/exceptions",
                headers=ha,
                json={"date": "2027-01-27", "exception_type": "WORKING"},
            )
            assert r.status_code in (404, 422), r.text

        # a work calendar may not be composed from foreign holiday calendars / patterns
        r = await client.post(
            "/v1/work-calendars",
            headers=ha,
            json={"name": "Composed", "holiday_calendar_ids": [foreign_hc["id"]]},
        )
        assert r.status_code in (404, 422), r.text
        r = await client.post(
            "/v1/work-calendars",
            headers=ha,
            json={"name": "Composed2", "weekly_off_pattern_id": foreign_pattern["id"]},
        )
        assert r.status_code in (404, 422), r.text
        r = await client.get("/v1/work-calendars", headers=ha)
        assert [w["name"] for w in r.json()["data"]] == []
    finally:
        await wipe_tenant(company_id=ca, user_id=ua)
        await wipe_tenant(company_id=cb, user_id=ub)
