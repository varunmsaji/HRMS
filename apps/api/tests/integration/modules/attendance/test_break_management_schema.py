"""Stage 1 checkpoint — the break-management schema: append-only events, tenant isolation,
override uniqueness, and constraint vocabulary. Talks to the database directly."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_EVENT_SQL = text(
    """
    INSERT INTO attendance_break_event
      (id, company_id, employee_id, attendance_date, event_type, event_time, source,
       idempotency_key)
    VALUES (:id, :cid, :eid, :d, :t, :ts, :src, :key)
    """
)


async def _insert_event(
    session: Any,
    cid: UUID,
    eid: UUID,
    *,
    kind: str = "START",
    key: str | None = None,
    source: str = "MOBILE",
) -> UUID:
    event_id = uuid4()
    await session.execute(
        _EVENT_SQL,
        {
            "id": event_id,
            "cid": cid,
            "eid": eid,
            "d": date(2026, 8, 10),
            "t": kind,
            "ts": datetime(2026, 8, 10, 7, 30, tzinfo=UTC),
            "src": source,
            "key": key,
        },
    )
    return event_id


async def test_events_are_append_only_and_validated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _build_wired_employee(client, headers)
        eid = UUID(employee["employee"]["id"])
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            event_id = await _insert_event(session, company_id, eid, key="k-1")
            await session.commit()

        # UPDATE of what happened is refused by the trigger.
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            with pytest.raises((DBAPIError, IntegrityError)):
                await session.execute(
                    text("UPDATE attendance_break_event SET event_type='END' WHERE id=:i"),
                    {"i": event_id},
                )
            await session.rollback()

        # The same idempotency key cannot be written twice for a company.
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            with pytest.raises(IntegrityError):
                await _insert_event(session, company_id, eid, key="k-1")
            await session.rollback()

        # Source and event type vocabularies are enforced.
        for kwargs in ({"source": "DEVICE"}, {"kind": "PAUSE"}):
            async with factory() as session:
                await set_rls_company_id(session, str(company_id))
                with pytest.raises(IntegrityError):
                    await _insert_event(session, company_id, eid, **kwargs)
                await session.rollback()
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_events_are_tenant_isolated(
    client: AsyncClient, seeded_plan_catalogue: None, app_as_runtime_role: Any
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee = await _build_wired_employee(client, headers_a)
        eid = UUID(employee["employee"]["id"])
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_a))
            await _insert_event(session, company_a, eid)
            await session.commit()
        async with app_as_runtime_role():
            factory = get_session_factory()
            counts = []
            for company in (company_a, company_b):
                async with factory() as session:
                    await set_rls_company_id(session, str(company))
                    counts.append(
                        (
                            await session.execute(
                                text("SELECT count(*) FROM attendance_break_event")
                            )
                        ).scalar()
                    )
        assert counts == [1, 0]
    finally:
        await _cleanup_attendance_day(company_id=company_a)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


async def test_override_overlap_and_vocabulary(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _build_wired_employee(client, headers)
        eid = UUID(employee["employee"]["id"])
        factory = get_session_factory()
        sql = text(
            """
            INSERT INTO employee_break_override
              (id, company_id, employee_id, action, target_break_name, effective_from,
               effective_to, reason, revoked_at)
            VALUES (:id, :cid, :eid, :a, :n, :f, :t, 'why', :rev)
            """
        )

        async def insert(action: str, name: str | None, f: date, t: date | None, rev: Any = None):
            async with factory() as session:
                await set_rls_company_id(session, str(company_id))
                await session.execute(
                    sql,
                    {
                        "id": uuid4(),
                        "cid": company_id,
                        "eid": eid,
                        "a": action,
                        "n": name,
                        "f": f,
                        "t": t,
                        "rev": rev,
                    },
                )
                await session.commit()

        await insert("REPLACE", "Lunch", date(2026, 1, 1), date(2026, 3, 31))
        # Same break, overlapping dates: refused.
        with pytest.raises(IntegrityError):
            await insert("DISABLE", "lunch", date(2026, 3, 1), None)
        # Adjacent range, a different break, and a revoked row are all fine.
        await insert("DISABLE", "Lunch", date(2026, 4, 1), None)
        await insert("REPLACE", "Tea", date(2026, 1, 1), None)
        await insert("REPLACE", "Lunch", date(2026, 1, 1), None, rev=datetime.now(UTC))
        # REPLACE/DISABLE need a target; ADD does not; actions are a closed set.
        with pytest.raises(IntegrityError):
            await insert("REPLACE", None, date(2026, 1, 1), None)
        await insert("ADD", None, date(2026, 1, 1), None)
        with pytest.raises(IntegrityError):
            await insert("MOVE", "Lunch", date(2026, 1, 1), None)
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_new_columns_default_to_legacy_behaviour(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        cols = {
            (r[0], r[1]): (r[2], r[3])
            for r in (
                await session.execute(
                    text(
                        """
                        SELECT table_name, column_name, is_nullable, column_default
                        FROM information_schema.columns
                        WHERE table_name IN ('shift_break', 'attendance_day', 'attendance_break',
                                             'attendance_period_summary')
                        """
                    )
                )
            ).all()
        }
    assert cols[("shift_break", "mode")][0] == "YES"  # NULL = legacy break
    assert "OTHER" in cols[("shift_break", "break_type")][1]
    assert cols[("shift_break", "is_enabled")][1] == "true"
    assert cols[("attendance_day", "has_unresolved_break")][1] == "false"
    assert cols[("attendance_break", "kind")][1].startswith("'PUNCHED_GAP'")
    # frozen-before-V1 period summaries read NULL, not a fabricated zero
    assert cols[("attendance_period_summary", "unpaid_break_minutes_total")][0] == "YES"
