"""`hrms.ops.import_backlog` — pure parsing/classification/reconciliation, and the proof that it
only ever issues read-only Redis commands. No database or broker needed."""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from hrms.ops import import_backlog as ib

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
STALE = timedelta(hours=24)


def _message(
    company_id: str, batch_id: str, *, task: str = ib.TASK_NAME, task_id: str = "t1"
) -> bytes:
    body = [[company_id, batch_id, None], {}, {"callbacks": None}]
    return json.dumps({
        "body": base64.b64encode(json.dumps(body).encode()).decode(),
        "headers": {"task": task, "id": task_id, "retries": 0, "hrms_enqueued_at": 1_700_000_000.0},
    }).encode()  # fmt: skip


def _ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


def _batch(status: str, *, age_hours: float = 1, **over: Any) -> dict[str, Any]:
    base = {
        "id": uuid4(), "company_id": uuid4(), "status": status, "original_filename": "emp.csv",
        "total_rows": 0, "processed_rows": 0, "success_count": 0, "error_count": 0,
        "created_at": NOW - timedelta(hours=age_hours), "started_at": None, "completed_at": None,
        "version": 1,
    }  # fmt: skip
    base.update(over)
    return base


def _classify(
    batch: dict[str, Any] | None, messages: int = 1, later: list[str] | None = None
) -> tuple[str, str]:
    state, rec, _ = ib.classify(
        batch=batch,
        message_count=messages,
        later_same_file=later or [],
        now=NOW,
        stale_pending=STALE,
    )
    return state, rec


def test_parse_extracts_ids_without_consuming_anything() -> None:
    c, b = str(uuid4()), str(uuid4())
    msg, other = ib.parse_message(3, _message(c, b))
    assert other is None and msg is not None
    assert (msg.company_id, msg.batch_id, msg.position, msg.task_id) == (c, b, 3, "t1")


def test_other_tasks_and_garbage_are_counted_not_guessed() -> None:
    assert ib.parse_message(0, _message("x", "y", task="reports.export")) == (
        None,
        "reports.export",
    )
    assert ib.parse_message(0, b"not json") == (None, "unparseable")
    msg, _ = ib.parse_message(
        0, json.dumps({"body": "!!", "headers": {"task": ib.TASK_NAME}}).encode()
    )
    assert msg is not None and msg.batch_id is None  # unreadable args -> no invented IDs


@pytest.mark.parametrize(
    ("batch", "messages", "later", "expected"),
    [
        (_batch("PENDING", age_hours=1), 1, [], ("PENDING", "ELIGIBLE_TO_RUN")),
        (_batch("PENDING", age_hours=48), 1, [], ("STALE_PENDING", "MANUAL_REVIEW")),
        (_batch("PENDING", age_hours=1), 2, [], ("PENDING", "MANUAL_REVIEW")),  # duplicates
        (_batch("PENDING", age_hours=1), 1, ["later"], ("PENDING", "MANUAL_REVIEW")),  # resubmitted
        (_batch("PENDING", age_hours=1), 0, [], ("PENDING_NO_MESSAGE", "MANUAL_REVIEW")),
        (_batch("PENDING", processed_rows=3), 1, [], ("AMBIGUOUS", "MANUAL_REVIEW")),
        (_batch("COMPLETED"), 1, [], ("TERMINAL", "SAFE_TO_DRAIN")),
        (_batch("COMPLETED_WITH_ERRORS"), 1, [], ("TERMINAL", "SAFE_TO_DRAIN")),
        (_batch("FAILED"), 1, [], ("TERMINAL", "SAFE_TO_DRAIN")),
        (_batch("PROCESSING", started_at=_ago(minutes=5)), 1, [], ("IN_PROGRESS", "SAFE_TO_DRAIN")),
        (_batch("PROCESSING", started_at=_ago(hours=5)), 1, [],
         ("STALE_PROCESSING", "MANUAL_REVIEW")),
        (_batch("WEIRD"), 1, [], ("AMBIGUOUS", "MANUAL_REVIEW")),
        (None, 1, [], ("NOT_VISIBLE", "MANUAL_REVIEW")),
    ],
)  # fmt: skip
def test_classification_matrix(
    batch: dict[str, Any] | None, messages: int, later: list[str], expected: tuple[str, str]
) -> None:
    assert _classify(batch, messages, later) == expected


def test_a_queued_message_never_implies_success() -> None:
    """A message for a batch that is still PENDING is never reported as done/safe-because-sent."""
    _, rec = _classify(_batch("PENDING", age_hours=100), messages=5)
    assert rec == "MANUAL_REVIEW"


def test_reconcile_detects_resubmission_and_finds_open_batches_without_messages() -> None:
    company = str(uuid4())
    original = _batch("PENDING", age_hours=30, company_id=company)
    resubmitted = _batch("COMPLETED", age_hours=2, company_id=company)  # same filename, later
    orphan_open = _batch("PENDING", age_hours=3, original_filename="other.csv", company_id=company)
    batches = {company: {str(b["id"]): b for b in (original, resubmitted, orphan_open)}}
    messages = [ib.parse_message(0, _message(company, str(original["id"])))[0]]
    assert messages[0] is not None

    report = ib.reconcile(
        [m for m in messages if m],
        batches,
        now=NOW,
        stale_pending=STALE,
        scanned_companies={company},
    )

    by_id = {r["batch_id"]: r for r in report}
    assert by_id[str(original["id"])]["recommendation"] == "MANUAL_REVIEW"
    assert by_id[str(original["id"])]["later_batches_same_filename"] == [str(resubmitted["id"])]
    # open, no message: surfaced because the company was scanned; the finished batch is not listed
    assert by_id[str(orphan_open["id"])]["state"] == "PENDING_NO_MESSAGE"
    assert str(resubmitted["id"]) not in by_id


def test_reconcile_reports_unidentified_messages() -> None:
    msg, _ = ib.parse_message(
        0, json.dumps({"body": "!!", "headers": {"task": ib.TASK_NAME}}).encode()
    )
    assert msg is not None
    (item,) = ib.reconcile([msg], {}, now=NOW, stale_pending=STALE, scanned_companies=set())
    assert item["state"] == "UNIDENTIFIED_MESSAGE" and item["recommendation"] == "MANUAL_REVIEW"


class _RecordingRedis:
    """Records every command; any command that is not LLEN/LRANGE would be a bug."""

    def __init__(self, messages: list[bytes]) -> None:
        self.messages = messages
        self.commands: list[str] = []

    def llen(self, name: str) -> int:
        self.commands.append("LLEN")
        return len(self.messages)

    def lrange(self, name: str, start: int, end: int) -> list[bytes]:
        self.commands.append("LRANGE")
        return self.messages[start : end + 1]


def test_read_queue_pages_through_everything_with_read_only_commands() -> None:
    raws = [_message(str(uuid4()), str(uuid4()), task_id=f"t{i}") for i in range(1203)]
    raws.append(_message("x", "y", task="reports.export"))
    client = _RecordingRedis(raws)

    messages, other = ib.read_queue(client)

    assert len(messages) == 1203 and other == {"reports.export": 1}
    assert [m.position for m in messages][:3] == [0, 1, 2]
    assert set(client.commands) <= {"LLEN", "LRANGE"}
    assert len(client.messages) == 1204  # nothing removed
