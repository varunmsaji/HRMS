"""Platform console: read-only view of the application log files (`/v1/platform/logs/*`).

Authenticated with a platform-admin token like every other platform route. Entries are returned
exactly as stored (already redacted at write time). Opening the viewer is itself logged as a
`security.platform.logs_viewed` event so access to logs is traceable."""

from datetime import datetime
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from hrms.core.config.settings import get_settings
from hrms.core.errors.base import AppError
from hrms.core.observability.file_sink import ALL_CHANNELS
from hrms.core.observability.log_reader import (
    LEVELS,
    LogQuery,
    list_log_files,
    read_entries,
)
from hrms.core.observability.logging import resolve_log_dir
from hrms.core.observability.security_events import security_event
from hrms.core.tenancy.context import current_request_id
from hrms.modules.identity.schemas import build_meta
from hrms.modules.platform.security import PlatformPrincipal, get_current_platform_admin
from hrms.shared.pagination import DataEnvelope

router = APIRouter(prefix="/platform/logs", tags=["platform"])
Principal = Annotated[PlatformPrincipal, Depends(get_current_platform_admin)]


class LogFileOut(BaseModel):
    channel: str
    size_bytes: int
    modified_at: datetime | None
    backups: int


class LogFilesOut(BaseModel):
    enabled: bool
    files: list[LogFileOut]


class LogEntriesOut(BaseModel):
    channel: str
    entries: list[dict[str, Any]]
    next_before: str | None
    truncated: bool


class InvalidLogQueryError(AppError):
    code = "VALIDATION_FAILED"
    status_code = 422


def _meta() -> object:
    return build_meta(current_request_id() or "unknown")


@router.get("/files")
async def log_files(_p: Principal) -> DataEnvelope[LogFilesOut]:
    settings = get_settings()
    directory = resolve_log_dir(settings.log_dir)
    files = await anyio.to_thread.run_sync(list_log_files, directory) if directory.is_dir() else []
    data = LogFilesOut(
        enabled=settings.log_to_files,
        files=[LogFileOut(**f.__dict__) for f in files],
    )
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.get("/entries")
async def log_entries(
    principal: Principal,
    channel: Annotated[str, Query(max_length=32)] = "errors",
    level: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    request_id: Annotated[str | None, Query(max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")] = None,
    event: Annotated[str | None, Query(max_length=100)] = None,
    before: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> DataEnvelope[LogEntriesOut]:
    if channel not in ALL_CHANNELS:
        raise InvalidLogQueryError("Unknown log file")
    levels = frozenset(v.lower() for v in level) if level else None
    if levels and not levels <= set(LEVELS):
        raise InvalidLogQueryError("Unknown level")
    directory = resolve_log_dir(get_settings().log_dir)
    query = LogQuery(
        channel=channel,
        levels=levels,
        text=q,
        request_id=request_id,
        event=event,
        before=before,
        limit=limit,
    )
    page = await anyio.to_thread.run_sync(read_entries, directory, query)
    security_event(
        "platform.logs_viewed",
        platform_admin=principal.username,
        channel=channel,
        filtered=bool(q or request_id or event or levels),
    )
    data = LogEntriesOut(
        channel=channel,
        entries=page.entries,
        next_before=page.next_before,
        truncated=page.truncated,
    )
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]
