"""Platform console log viewer: platform-admin only, allow-listed channels, bounded, filterable."""

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from hrms.core.config.settings import get_settings

P = "/v1/platform/logs"


def _line(ts: str, level: str, event: str, **extra: Any) -> str:
    return json.dumps({"timestamp": ts, "level": level, "event": event, **extra})


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "errors.log").write_text(
        "\n".join(
            [
                _line("2026-10-20T10:00:00Z", "error", "old_failure", request_id="r-old"),
                "{not json",
                _line(
                    "2026-10-20T10:05:00Z",
                    "error",
                    "unhandled_exception",
                    request_id="r-1",
                    exception="Traceback ... ValueError",
                ),
            ]
        )
        + "\n"
    )
    (tmp_path / "errors.log.1").write_text(
        _line("2026-10-19T10:00:00Z", "error", "rotated_failure") + "\n"
    )
    (tmp_path / "app.log").write_text(_line("2026-10-20T10:06:00Z", "info", "http_request") + "\n")
    (tmp_path / "secret.txt").write_text("must never be readable")
    return tmp_path


async def test_requires_platform_admin(
    client: AsyncClient, make_tenant: Any, log_dir: Path
) -> None:
    assert (await client.get(f"{P}/files")).status_code == 401
    tenant = await make_tenant()
    assert (await client.get(f"{P}/entries", headers=tenant.headers)).status_code in (401, 403)


async def test_lists_files_and_reads_newest_first_including_rotated(
    client: AsyncClient, platform_admin: Any, log_dir: Path
) -> None:
    files = (await client.get(f"{P}/files", headers=platform_admin.headers)).json()["data"]
    by_channel = {f["channel"]: f for f in files["files"]}
    assert by_channel["errors"]["backups"] == 1 and by_channel["errors"]["size_bytes"] > 0
    assert by_channel["leave"]["size_bytes"] == 0

    r = await client.get(f"{P}/entries?channel=errors", headers=platform_admin.headers)
    data = r.json()["data"]
    assert [e["event"] for e in data["entries"]] == [
        "unhandled_exception",
        "old_failure",
        "rotated_failure",
    ]
    assert data["entries"][0]["exception"].startswith("Traceback")  # full detail, unmodified


async def test_filters_and_pagination(
    client: AsyncClient, platform_admin: Any, log_dir: Path
) -> None:
    h = platform_admin.headers
    r = await client.get(f"{P}/entries?channel=errors&request_id=r-old", headers=h)
    assert [e["event"] for e in r.json()["data"]["entries"]] == ["old_failure"]
    r = await client.get(f"{P}/entries?channel=errors&q=ROTATED", headers=h)
    assert [e["event"] for e in r.json()["data"]["entries"]] == ["rotated_failure"]
    r = await client.get(f"{P}/entries?channel=errors&limit=1", headers=h)
    page = r.json()["data"]
    assert len(page["entries"]) == 1 and page["next_before"]
    r = await client.get(f"{P}/entries?channel=errors&before={page['next_before']}", headers=h)
    assert [e["event"] for e in r.json()["data"]["entries"]] == ["old_failure", "rotated_failure"]
    r = await client.get(f"{P}/entries?channel=app&level=info", headers=h)
    assert [e["event"] for e in r.json()["data"]["entries"]] == ["http_request"]


@pytest.mark.parametrize("channel", ["../etc/passwd", "secret", "errors.log", "ERRORS", ""])
async def test_channel_is_allow_listed(
    client: AsyncClient, platform_admin: Any, log_dir: Path, channel: str
) -> None:
    r = await client.get(
        f"{P}/entries", params={"channel": channel}, headers=platform_admin.headers
    )
    assert r.status_code == 422
    assert "must never be readable" not in r.text


async def test_bad_level_rejected(client: AsyncClient, platform_admin: Any, log_dir: Path) -> None:
    r = await client.get(f"{P}/entries?level=loud", headers=platform_admin.headers)
    assert r.status_code == 422
