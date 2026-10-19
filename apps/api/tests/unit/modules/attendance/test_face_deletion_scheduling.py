"""Scheduling of the external-deletion worker. Unlike retention cleanup it has no off switch:
it only acts on rows the application itself queued after a committed approve / reject / revoke."""

from typing import Any

import pytest

from hrms.core.celery_app import celery_app
from hrms.modules.attendance import face_cleanup, tasks
from hrms.modules.attendance.face_deletion import _backoff


def test_beat_schedule_runs_the_worker_every_few_minutes() -> None:
    entry = celery_app.conf.beat_schedule["attendance-run-face-deletions"]
    assert entry["task"] == "attendance.run_face_deletions"
    assert entry["schedule"]._orig_minute == "*/2"


def test_fan_out_dispatches_one_task_per_company(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_ids() -> list[str]:
        return ["c1", "c2", "c3"]

    monkeypatch.setattr(face_cleanup, "_all_company_ids", fake_ids)
    monkeypatch.setattr(
        tasks,
        "dispatch_per_company",
        lambda task, ids, *a: seen.update(task=task.name, ids=list(ids)) or len(seen["ids"]),
    )

    assert tasks.run_face_deletions() == 3
    assert seen == {
        "task": "attendance.process_face_deletions_company",
        "ids": ["c1", "c2", "c3"],
    }


def test_backoff_grows_and_is_capped() -> None:
    minutes = [_backoff(n).total_seconds() / 60 for n in (0, 1, 2, 3, 5, 6, 10, 50)]
    assert minutes == [2, 2, 4, 8, 32, 60, 60, 60]
