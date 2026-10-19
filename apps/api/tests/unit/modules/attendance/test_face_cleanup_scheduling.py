"""The scheduled entry point and CLI of face-record retention cleanup, without any database:
nothing is dispatched or deleted while no retention period is configured, and the CLI reports
rather than deletes unless `--apply` is passed."""

from typing import Any

import pytest

from hrms.core.celery_app import celery_app
from hrms.core.config.settings import Settings
from hrms.modules.attendance import face_cleanup, tasks


def _settings(**overrides: Any) -> Settings:
    return Settings(environment="development", **overrides)


def test_beat_schedule_contains_the_cleanup_task() -> None:
    entry = celery_app.conf.beat_schedule["attendance-run-face-cleanup"]
    assert entry["task"] == "attendance.run_face_cleanup"


def test_unset_retention_dispatches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatched: list[Any] = []
    monkeypatch.setattr("hrms.core.config.settings.get_settings", lambda: _settings())
    monkeypatch.setattr(tasks, "dispatch_per_company", lambda *a, **k: dispatched.append(a))

    assert tasks.run_face_cleanup() == 0
    assert dispatched == []


def test_configured_retention_fans_out_per_company(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_ids() -> list[str]:
        return ["c1", "c2"]

    monkeypatch.setattr(
        "hrms.core.config.settings.get_settings",
        lambda: _settings(face_attempt_detail_retention_days=30),
    )
    monkeypatch.setattr(face_cleanup, "_all_company_ids", fake_ids)
    monkeypatch.setattr(
        tasks,
        "dispatch_per_company",
        lambda task, ids, *a: seen.update(task=task.name, ids=list(ids)) or len(seen["ids"]),
    )

    assert tasks.run_face_cleanup() == 2
    assert seen["task"] == "attendance.cleanup_face_records_company"
    assert seen["ids"] == ["c1", "c2"]


async def test_cli_without_apply_is_a_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    modes: list[bool | None] = []

    async def fake_cleanup(
        company_id: Any, settings: Any, *, dry_run: bool | None = None, **_: Any
    ):
        modes.append(dry_run)
        return face_cleanup.CleanupReport(company_id=str(company_id), dry_run=bool(dry_run))

    async def no_dispose() -> None:
        return None

    monkeypatch.setattr(
        face_cleanup, "get_settings", lambda: _settings(face_liveness_session_retention_days=5)
    )
    monkeypatch.setattr(face_cleanup, "cleanup_company", fake_cleanup)
    monkeypatch.setattr(face_cleanup, "dispose_engine", no_dispose)
    company = __import__("uuid").uuid4()

    await face_cleanup._main(False, company)
    await face_cleanup._main(True, company)

    assert modes == [True, False]


async def test_cli_does_nothing_when_no_period_is_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(face_cleanup, "get_settings", lambda: _settings())

    assert await face_cleanup._main(True, None) == []
    assert "no retention period configured" in capsys.readouterr().out
