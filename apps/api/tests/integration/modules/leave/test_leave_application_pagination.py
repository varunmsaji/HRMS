"""Integration tests for `GET /v1/leave-applications` pagination + the N+1 fix (API-01 §5).

Reuses `test_leave_application.py`'s exact fixture helpers (employee/employment/calendar/policy
setup, `_submit`) — this is the same submission flow, just listing many applications instead of
one.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _give_balance,
    _register_tenant,
    _setup_calendar,
    _setup_leave_policy,
    _submit,
    _teardown,
)

from hrms.core.db.session import get_engine, get_session_factory
from hrms.modules.organisation.models import Subscription

pytestmark = pytest.mark.asyncio


class QueryCounter:
    """Counts SQL statements issued through the shared engine for the duration of a `with`
    block — used to prove the N+1 fix stays a fixed number of queries per page, not one that
    scales with how many applications are on that page (API-01 §5/§11)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sync_engine = engine.sync_engine
        self.count = 0

    def _on_execute(self, *_args: Any, **_kwargs: Any) -> None:
        self.count += 1

    def __enter__(self) -> "QueryCounter":
        self.count = 0
        event.listen(self._sync_engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *_exc: Any) -> None:
        event.remove(self._sync_engine, "before_cursor_execute", self._on_execute)


async def _raise_seat_limit(*, company_id: UUID, limit: int = 500) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Subscription)
            .where(Subscription.company_id == company_id)
            .values(seat_limit_override=limit)
        )
        await session.commit()


async def _setup_shared(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    legal_entity = await _create_legal_entity(client, headers)
    leave_type = await _create_leave_type(client, headers)
    await _setup_calendar(client, headers)
    policy = await _setup_leave_policy(client, headers, leave_type_id=leave_type["id"])
    return {"legal_entity": legal_entity, "leave_type": leave_type, "policy": policy}


async def _submit_one(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    shared: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    """One employee, one employment, one opening balance, one submitted application — a
    self-contained row for pagination purposes. Every employee uses the same
    `start_date`/`end_date`; the "no overlapping application" rule is scoped per-employee, so
    distinct employees on the same date don't collide."""
    employee = await _create_employee(client, headers, first_name=f"Applicant{index:03d}")
    await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=shared["legal_entity"]["id"],
    )
    await _give_balance(
        client,
        headers,
        employee_id=employee["id"],
        leave_type_id=shared["leave_type"]["id"],
        amount="20.00",
    )
    response = await _submit(
        client,
        headers,
        employee_id=employee["id"],
        leave_type_id=shared["leave_type"]["id"],
        start_date="2026-09-08",
        end_date="2026-09-08",
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def test_default_page_and_filters_preserved(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _raise_seat_limit(company_id=company_id)
        shared = await _setup_shared(client, headers)
        applications = [
            await _submit_one(client, headers, shared=shared, index=i) for i in range(27)
        ]

        response = await client.get("/v1/leave-applications", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 25
        assert body["pagination"]["page"] == 1
        assert body["pagination"]["per_page"] == 25
        assert body["pagination"]["total"] == 27
        assert body["pagination"]["total_pages"] == 2

        # `employee_id` filter still narrows correctly under pagination.
        single = await client.get(
            "/v1/leave-applications",
            headers=headers,
            params={"employee_id": applications[0]["employee_id"]},
        )
        assert single.status_code == 200
        single_body = single.json()
        assert single_body["pagination"]["total"] == 1
        assert single_body["data"][0]["id"] == applications[0]["id"]
    finally:
        await _teardown(company_id=company_id)


async def test_page_two_and_boundary(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _raise_seat_limit(company_id=company_id)
        shared = await _setup_shared(client, headers)
        created = [await _submit_one(client, headers, shared=shared, index=i) for i in range(7)]
        created_ids = {a["id"] for a in created}

        seen_ids: set[str] = set()
        page = 1
        while True:
            response = await client.get(
                "/v1/leave-applications", headers=headers, params={"page": page, "per_page": 3}
            )
            assert response.status_code == 200
            body = response.json()
            if not body["data"]:
                break
            seen_ids.update(row["id"] for row in body["data"])
            if page >= body["pagination"]["total_pages"]:
                break
            page += 1
        assert seen_ids == created_ids

        beyond = await client.get("/v1/leave-applications", headers=headers, params={"page": 99})
        assert beyond.json()["data"] == []
        assert beyond.json()["pagination"]["total"] == 7
    finally:
        await _teardown(company_id=company_id)


@pytest.mark.parametrize("query", ["page=0", "per_page=0", "per_page=101"])
async def test_invalid_pagination_params_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, query: str
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/leave-applications?{query}", headers=headers)
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id)


async def test_day_and_action_data_correct_under_pagination(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression: each returned application's `days`/`actions` must still be its own — batch
    loading (API-01 §5) must not cross-associate one application's child rows with another's."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _raise_seat_limit(company_id=company_id)
        shared = await _setup_shared(client, headers)
        created = [await _submit_one(client, headers, shared=shared, index=i) for i in range(5)]

        response = await client.get(
            "/v1/leave-applications", headers=headers, params={"per_page": 5}
        )
        assert response.status_code == 200
        by_id = {row["id"]: row for row in response.json()["data"]}
        assert set(by_id) == {a["id"] for a in created}

        for original in created:
            row = by_id[original["id"]]
            assert row["employee_id"] == original["employee_id"]
            # Every submitted application here is a single day off, auto-approved (default
            # chain) — one day row, at least a SUBMITTED action.
            assert len(row["days"]) == 1
            assert row["days"][0]["calendar_date"] == "2026-09-08"
            assert any(a["action"] == "SUBMITTED" for a in row["actions"])
    finally:
        await _teardown(company_id=company_id)


async def test_n_plus_one_removed_query_count_bounded(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The core API-01 §5 regression proof: listing a page with many applications must not
    issue more SQL statements than listing a page with few — day/action loading is 2 bounded
    batch queries per *page*, not 2 queries per *row* (the pre-fix N+1 pattern)."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _raise_seat_limit(company_id=company_id)
        shared = await _setup_shared(client, headers)
        for i in range(12):
            await _submit_one(client, headers, shared=shared, index=i)

        engine = get_engine()

        with QueryCounter(engine) as small_page:
            small = await client.get(
                "/v1/leave-applications", headers=headers, params={"per_page": 3}
            )
        assert small.status_code == 200
        assert len(small.json()["data"]) == 3

        with QueryCounter(engine) as large_page:
            large = await client.get(
                "/v1/leave-applications", headers=headers, params={"per_page": 12}
            )
        assert large.status_code == 200
        assert len(large.json()["data"]) == 12

        # Same request shape, 4x the rows on the page — if days/actions were still loaded
        # per-row (the pre-fix N+1 pattern), `large_page.count` would scale with row count
        # instead of staying flat.
        assert large_page.count == small_page.count
    finally:
        await _teardown(company_id=company_id)
