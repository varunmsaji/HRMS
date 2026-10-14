"""Mission Phase 5 — `emit_after_commit`: a business event is written only if the transaction
that produced it commits, never for a rolled-back transaction or SAVEPOINT, and it keeps the log
context (request id) it was raised under. `AuditService.record` uses it for one slim operational
line per audited transition, carrying identifiers and the state change only."""

import json

import pytest
import structlog
from pytest import CaptureFixture
from sqlalchemy import text
from structlog.testing import capture_logs

from hrms.core.audit.service import _status_of
from hrms.core.db.session import dispose_engine, get_session_factory
from hrms.core.observability.business_events import emit_after_commit
from hrms.core.observability.logging import configure_logging


@pytest.fixture(autouse=True)
async def _fresh_engine() -> None:
    yield
    await dispose_engine()


async def test_only_committed_work_is_logged() -> None:
    factory = get_session_factory()
    with capture_logs() as logs:
        async with factory() as session:
            emit_after_commit(session, "t.queued_before_autobegin")
            await session.execute(text("SELECT 1"))
            emit_after_commit(session, "t.outer")
            with pytest.raises(Exception, match="nope_business_events"):
                async with session.begin_nested():
                    emit_after_commit(session, "t.savepoint_rolled_back")
                    await session.execute(text("SELECT * FROM nope_business_events"))
            async with session.begin_nested():
                emit_after_commit(session, "t.savepoint_released")
            await session.commit()

        async with factory() as session:
            emit_after_commit(session, "t.rolled_back_pre_autobegin")
            await session.execute(text("SELECT 1"))
            emit_after_commit(session, "t.rolled_back")
            await session.rollback()
            # A new transaction on the same session must not resurrect them.
            await session.execute(text("SELECT 1"))
            await session.commit()

    assert [e["event"] for e in logs] == [
        "t.queued_before_autobegin",
        "t.outer",
        "t.savepoint_released",
    ]


async def test_event_keeps_the_context_it_was_raised_under(capfd: CaptureFixture[str]) -> None:
    # Through the real JSON pipeline: `capture_logs()` would bypass `merge_contextvars`.
    configure_logging("api")
    factory = get_session_factory()
    capfd.readouterr()
    async with factory() as session:
        with structlog.contextvars.bound_contextvars(request_id="biz-req-1"):
            emit_after_commit(session, "t.with_context", entity_id="e-1")
        await session.commit()  # the context is already unbound here
    lines = [json.loads(line) for line in capfd.readouterr().out.splitlines() if line.strip()]
    (entry,) = [e for e in lines if e.get("event") == "t.with_context"]
    assert entry["request_id"] == "biz-req-1"
    assert entry["entity_id"] == "e-1"


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        ({"status": "APPROVED"}, "APPROVED"),
        ({"status": "INPUTS_LOCKED"}, "INPUTS_LOCKED"),
        ({"status": "x" * 41}, None),
        ({"status": "Ravi Kumar <ravi@example.com>"}, None),
        ({"status": 3}, None),
        ({"name": "no status"}, None),
        (None, None),
    ],
)
def test_only_a_state_code_is_copied_from_the_audit_snapshot(
    snapshot: dict[str, object] | None, expected: str | None
) -> None:
    assert _status_of(snapshot) == expected
