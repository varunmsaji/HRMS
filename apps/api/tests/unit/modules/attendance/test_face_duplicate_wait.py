"""A duplicate face punch waiting on the original must see its punch even when the original commits
between the duplicate's two reads. No DB/HTTP."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.modules.attendance import face_service
from hrms.modules.attendance.face_service import FacePunchService


async def test_original_committing_between_the_reads_still_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def fake_scope(company_id: str) -> AsyncIterator[MagicMock]:
        yield MagicMock()

    monkeypatch.setattr(face_service, "session_scope", fake_scope)
    monkeypatch.setattr(face_service, "_release_request_connection", AsyncMock())
    monkeypatch.setattr(face_service, "_resume_request_transaction", AsyncMock())

    # The original's attempt and punch commit together, right after this request's first read.
    committed = False

    async def read_attempt(*args: Any, **kwargs: Any) -> bool:
        nonlocal committed
        seen = committed
        committed = True
        return seen

    async def read_punch(*args: Any, **kwargs: Any) -> object | None:
        nonlocal committed
        seen = committed
        committed = True
        return object() if seen else None

    service = FacePunchService.__new__(FacePunchService)
    service._session = MagicMock()
    service._sessions = MagicMock(
        get_state=AsyncMock(return_value=("CONSUMED", "IN", datetime.now(UTC)))
    )
    service._attempts = MagicMock(exists_for_session=read_attempt)
    service._punches = MagicMock(get_by_idempotency_key=read_punch)
    service._in_flight_wait_seconds = lambda: 5.0  # type: ignore[method-assign]
    replayed = object()
    service._replay_if_recorded = AsyncMock(return_value=replayed)  # type: ignore[method-assign]

    result = await service._await_in_flight_duplicate(
        uuid4(), uuid4(), uuid4(), "face:key", direction="IN", ref="ref"
    )

    assert result is replayed
