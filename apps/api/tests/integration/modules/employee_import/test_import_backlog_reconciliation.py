"""`python -m hrms.ops.import_backlog` against a real database and real Celery-published messages.

Messages go to a throw-away queue name on the isolated test broker (Redis DB 15), never to
`reports_exports` in DB 0. Proves: the report matches the batch rows, nothing is written or
consumed, the database refuses writes from the tool's session, and the worker-side claim skips
exactly the batches the report calls SAFE_TO_DRAIN."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import redis
from httpx import AsyncClient
from pytest import CaptureFixture
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory, session_scope, set_rls_company_id
from hrms.modules.employee_import.tasks import process_batch
from hrms.ops import import_backlog as ib

from ..organisation.test_registration_flow import _cleanup
from .test_employee_import import _cleanup_import_tables, _register_tenant
from .test_import_idempotency import _events, _process

pytestmark = pytest.mark.asyncio

TEST_QUEUE = "hrms_test_import_backlog"


@pytest.fixture
def broker() -> Any:
    client = redis.Redis.from_url(get_settings().celery_broker)
    assert client.connection_pool.connection_kwargs["db"] != 0, "tests must not use the real db0"
    client.delete(TEST_QUEUE)
    yield client
    client.delete(TEST_QUEUE)
    client.close()


async def _insert_batch(
    company_id: UUID, *, status: str, age_hours: float, filename: str = "emp.csv", **cols: Any
) -> UUID:
    batch_id = uuid4()
    created = datetime.now(UTC) - timedelta(hours=age_hours)
    values = {
        "id": batch_id, "cid": company_id, "status": status, "fn": filename, "created": created,
        "started": cols.get("started_at"), "processed": cols.get("processed_rows", 0),
    }  # fmt: skip
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "INSERT INTO employee_import_batch (id, company_id, status, original_filename, "
                "s3_key, total_rows, processed_rows, success_count, error_count, version, "
                "started_at, created_at, updated_at) VALUES (:id, :cid, :status, :fn, 'k', 0, "
                ":processed, 0, 0, 1, :started, :created, :created)"
            ),
            values,
        )
        await session.commit()
    return batch_id


def _enqueue(company_id: UUID, batch_id: UUID) -> None:
    process_batch.apply_async(args=[str(company_id), str(batch_id), None], queue=TEST_QUEUE)


async def _snapshot(company_id: UUID) -> list[tuple[Any, ...]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text("SELECT * FROM employee_import_batch WHERE company_id = :c ORDER BY id"),
            {"c": str(company_id)},
        )
        return [tuple(r) for r in rows]


async def test_report_matches_database_and_changes_nothing(
    client: AsyncClient, seeded_plan_catalogue: None, broker: Any
) -> None:
    _, company_id, user_id = await _register_tenant(client)
    try:
        fresh = await _insert_batch(company_id, status="PENDING", age_hours=1, filename="a.csv")
        stale = await _insert_batch(company_id, status="PENDING", age_hours=72, filename="b.csv")
        done = await _insert_batch(company_id, status="COMPLETED", age_hours=5, filename="c.csv")
        failed = await _insert_batch(company_id, status="FAILED", age_hours=5, filename="d.csv")
        dup = await _insert_batch(company_id, status="PENDING", age_hours=1, filename="e.csv")
        resub_old = await _insert_batch(company_id, status="PENDING", age_hours=6, filename="f.csv")
        await _insert_batch(company_id, status="COMPLETED", age_hours=2, filename="f.csv")
        stuck = await _insert_batch(
            company_id, status="PROCESSING", age_hours=30,
            filename="g.csv", started_at=datetime.now(UTC) - timedelta(hours=10),
        )  # fmt: skip
        no_msg = await _insert_batch(company_id, status="PENDING", age_hours=2, filename="h.csv")
        missing = uuid4()
        for b in (fresh, stale, done, failed, dup, dup, resub_old, stuck, missing):
            _enqueue(company_id, b)
        depth_before = broker.llen(TEST_QUEUE)
        before = await _snapshot(company_id)

        report = await ib.collect(
            broker, company_ids=[str(company_id)], all_companies=False,
            stale_pending=timedelta(hours=24), queue=TEST_QUEUE,
        )  # fmt: skip

        by_id = {i["batch_id"]: i for i in report["items"]}
        rec = {k: by_id[str(v)]["recommendation"] for k, v in {
            "fresh": fresh, "stale": stale, "done": done, "failed": failed, "dup": dup,
            "resub_old": resub_old, "stuck": stuck, "no_msg": no_msg, "missing": missing,
        }.items()}  # fmt: skip
        assert rec == {
            "fresh": "ELIGIBLE_TO_RUN", "stale": "MANUAL_REVIEW", "done": "SAFE_TO_DRAIN",
            "failed": "SAFE_TO_DRAIN", "dup": "MANUAL_REVIEW", "resub_old": "MANUAL_REVIEW",
            "stuck": "MANUAL_REVIEW", "no_msg": "MANUAL_REVIEW", "missing": "MANUAL_REVIEW",
        }  # fmt: skip
        assert by_id[str(missing)]["state"] == "NOT_VISIBLE"
        assert by_id[str(no_msg)]["state"] == "PENDING_NO_MESSAGE"
        assert len(by_id[str(dup)]["queued_messages"]) == 2
        assert by_id[str(resub_old)]["later_batches_same_filename"]
        assert report["read_only"] is True
        assert report["queue"]["import_messages"] == depth_before == 9

        # Read-only: queue and rows are exactly as they were.
        assert broker.llen(TEST_QUEUE) == depth_before
        assert await _snapshot(company_id) == before
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_tool_session_is_read_only_at_the_database(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    _, company_id, user_id = await _register_tenant(client)
    try:
        batch_id = await _insert_batch(company_id, status="PENDING", age_hours=1)
        with pytest.raises(DBAPIError, match="read-only transaction"):
            async with session_scope(company_id=str(company_id)) as session:
                await ib._read_only(session)
                await session.execute(
                    text("UPDATE employee_import_batch SET status = 'FAILED' WHERE id = :i"),
                    {"i": str(batch_id)},
                )
        assert [r[2] for r in await _snapshot(company_id)] == ["PENDING"]
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_worker_skips_exactly_what_the_report_calls_safe_to_drain(
    client: AsyncClient, seeded_plan_catalogue: None, capfd: CaptureFixture[str]
) -> None:
    """The documented operator step: mark an unwanted PENDING batch FAILED *before* the worker
    starts; its queued message is then skipped and never touches the batch."""
    _, company_id, user_id = await _register_tenant(client)
    try:
        unwanted = await _insert_batch(company_id, status="PENDING", age_hours=100)
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("UPDATE employee_import_batch SET status='FAILED' WHERE id = :i"),
                {"i": str(unwanted)},
            )
            await session.commit()
        before = await _snapshot(company_id)
        capfd.readouterr()

        await _process(company_id, unwanted, user_id)

        (skipped,) = _events(capfd.readouterr().out, "employee_import.batch.skipped")
        assert skipped["reason"] == "not_pending" and skipped["status"] == "FAILED"
        assert await _snapshot(company_id) == before  # untouched, incl. version and timestamps
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
