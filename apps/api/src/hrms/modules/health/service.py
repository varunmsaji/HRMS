from typing import Literal

from pydantic import BaseModel

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_engine
from hrms.core.errors.handlers import server_meta
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.tenancy.context import current_request_id
from hrms.shared.pagination import DataEnvelope, ResponseMeta

#: RELEASE_HARDENING_PHASE_3B §7 — a hung/unreachable dependency must fail the readiness check
#: fast rather than block the probe indefinitely; neither asyncpg's `connect()` nor redis-py's
#: `ping()` applies a timeout by default.
_READINESS_TIMEOUT_SECONDS = 3.0

_logger = get_logger(__name__)


def _log_dependency_failure(dependency: str, exc: BaseException) -> None:
    """LOG-12 — a failing readiness probe used to return 503 with no server-side record of which
    dependency failed or why. One compact WARNING per failing probe (no traceback); the
    response body itself stays ok/error only."""
    safe_log(
        _logger.warning,
        "readiness_dependency_failed",
        dependency=dependency,
        **safe_error(exc),
    )


class HealthData(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    database: Literal["ok", "error"] = "ok"
    redis: Literal["ok", "error", "skipped"] = "skipped"


class ReadinessData(BaseModel):
    """Dependency-aware — distinct from `HealthData`/`/health` (unchanged, kept for backward
    compatibility with existing callers) and from liveness (`/health/live`, no dependency checks
    at all). Consumed by Nginx/an orchestrator to decide whether to route traffic here, not by
    Docker's own container `HEALTHCHECK` (that targets `/health/live` — see `apps/api/Dockerfile`
    — precisely so a dependency outage doesn't trigger container restart storms)."""

    ready: bool
    database: Literal["ok", "error"]
    redis: Literal["ok", "error"]
    storage_configured: bool


class HealthService:
    async def check(self) -> HealthData:
        db_status = await _check_database()
        overall: Literal["ok", "degraded"] = "ok" if db_status == "ok" else "degraded"
        return HealthData(status=overall, database=db_status, redis="skipped")

    async def check_ready(self) -> ReadinessData:
        database = await _check_database()
        redis_status = await _check_redis()
        storage_configured = _check_storage_configured()
        ready = database == "ok" and redis_status == "ok" and storage_configured
        return ReadinessData(
            ready=ready,
            database=database,
            redis=redis_status,
            storage_configured=storage_configured,
        )


async def _check_database() -> Literal["ok", "error"]:
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        engine = get_engine()
        async with asyncio.timeout(_READINESS_TIMEOUT_SECONDS):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except (SQLAlchemyError, TimeoutError, OSError) as exc:
        _log_dependency_failure("database", exc)
        return "error"
    else:
        return "ok"


async def _check_redis() -> Literal["ok", "error"]:
    import redis.asyncio as redis
    from redis.exceptions import RedisError

    settings = get_settings()
    client = redis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url,
        socket_timeout=_READINESS_TIMEOUT_SECONDS,
        socket_connect_timeout=_READINESS_TIMEOUT_SECONDS,
    )
    try:
        await client.ping()
    except (RedisError, OSError) as exc:
        _log_dependency_failure("redis", exc)
        return "error"
    else:
        return "ok"
    finally:
        await client.aclose()


def _check_storage_configured() -> bool:
    """No live MinIO round-trip here, deliberately — readiness only needs to prove the required
    *configuration* is present (`Settings._guard_non_development_config` already fails boot
    without it outside development), matching the brief's own "required storage configuration"
    scope rather than a full connectivity probe on every readiness poll."""
    settings = get_settings()
    if settings.is_development:
        return True
    return bool(
        settings.s3_endpoint_url and settings.s3_bucket_documents and settings.aws_access_key_id
    )


def build_health_envelope(data: HealthData) -> DataEnvelope[HealthData]:
    request_id = current_request_id() or "unknown"
    meta = ResponseMeta(request_id=request_id, server_time=server_meta()["server_time"])
    return DataEnvelope(data=data, meta=meta)


def build_readiness_envelope(data: ReadinessData) -> DataEnvelope[ReadinessData]:
    request_id = current_request_id() or "unknown"
    meta = ResponseMeta(request_id=request_id, server_time=server_meta()["server_time"])
    return DataEnvelope(data=data, meta=meta)
