"""Read-only access to the local log files for the platform console.

Safety properties:

* the channel is chosen from a fixed allow-list (`ALL_CHANNELS`) and mapped to a file name by this
  module — no part of a request ever becomes a path;
* the lines were redacted before they were written (`redact_event`); nothing is added or unmasked
  here, and free-text search is a plain substring match on the stored line;
* every call is bounded: at most `MAX_FILES` files (live + rotated backups), `MAX_SCAN_BYTES`
  bytes read in total, and `MAX_LIMIT` entries returned;
* reading never takes the writers' locks and never modifies a file; a torn or unparsable line is
  skipped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hrms.core.observability.file_sink import ALL_CHANNELS

MAX_LIMIT = 200
MAX_FILES = 6
MAX_SCAN_BYTES = 64 * 1024 * 1024
LEVELS = ("debug", "info", "warning", "error", "critical")


@dataclass(frozen=True)
class LogFileInfo:
    channel: str
    size_bytes: int
    modified_at: datetime | None
    backups: int


@dataclass(frozen=True)
class LogQuery:
    channel: str
    levels: frozenset[str] | None = None
    text: str | None = None
    request_id: str | None = None
    event: str | None = None
    before: str | None = None  # ISO timestamp; only strictly older entries
    limit: int = 100


@dataclass(frozen=True)
class LogPage:
    entries: list[dict[str, Any]]
    next_before: str | None
    truncated: bool  # scan budget or file cap hit before the limit was reached


def _files_newest_first(directory: Path, channel: str) -> list[Path]:
    pattern = re.compile(rf"{re.escape(channel)}\.log\.(\d+)")
    numbered: list[tuple[int, Path]] = []
    for p in directory.iterdir():
        m = pattern.fullmatch(p.name)
        if m:
            numbered.append((int(m.group(1)), p))
    ordered = [directory / f"{channel}.log", *(p for _n, p in sorted(numbered))]
    return [p for p in ordered if p.is_file()][:MAX_FILES]


def list_log_files(directory: Path) -> list[LogFileInfo]:
    result: list[LogFileInfo] = []
    for channel in ALL_CHANNELS:
        files = _files_newest_first(directory, channel)
        if not files:
            result.append(LogFileInfo(channel, 0, None, 0))
            continue
        live = files[0] if files[0].name == f"{channel}.log" else None
        stat = live.stat() if live else None
        result.append(
            LogFileInfo(
                channel=channel,
                size_bytes=sum(p.stat().st_size for p in files),
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC) if stat else None,
                backups=len(files) - (1 if live else 0),
            )
        )
    return result


def read_entries(directory: Path, query: LogQuery) -> LogPage:
    if query.channel not in ALL_CHANNELS:
        raise ValueError("unknown channel")
    limit = max(1, min(query.limit, MAX_LIMIT))
    needle = query.text.lower() if query.text else None
    entries: list[dict[str, Any]] = []
    scanned = 0
    truncated = False

    for path in _files_newest_first(directory, query.channel):
        try:
            size = path.stat().st_size
            if scanned + size > MAX_SCAN_BYTES:
                truncated = True
                break
            scanned += size
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in reversed(lines):
            if needle and needle not in raw.lower():
                continue
            if query.request_id and query.request_id not in raw:
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            if query.levels and str(entry.get("level", "")).lower() not in query.levels:
                continue
            if query.event and query.event not in str(entry.get("event", "")):
                continue
            stamp = str(entry.get("timestamp", ""))
            if query.before and stamp >= query.before:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                return LogPage(entries, stamp or None, truncated)
    return LogPage(entries, None, truncated)
