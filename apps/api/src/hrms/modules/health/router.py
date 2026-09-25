from fastapi import APIRouter, Response, status

from hrms.modules.health.service import (
    HealthData,
    HealthService,
    ReadinessData,
    build_health_envelope,
    build_readiness_envelope,
)
from hrms.shared.pagination import DataEnvelope

router = APIRouter(tags=["health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> DataEnvelope[HealthData]:
    service = HealthService()
    data = await service.check()
    envelope = build_health_envelope(data)
    return envelope


@router.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness_check() -> dict[str, str]:
    """RELEASE_HARDENING_PHASE_3B §7 — liveness answers "is this process alive?" only: no
    database/Redis/storage check, so a dependency outage never causes an orchestrator to restart
    an otherwise-healthy process (a restart storm that would make the outage worse, not better).
    This is what `apps/api/Dockerfile`'s own `HEALTHCHECK` targets."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_check(response: Response) -> DataEnvelope[ReadinessData]:
    """Readiness answers "can this service actually serve production traffic?" — checks
    PostgreSQL, Redis, and required object-storage configuration (RELEASE_HARDENING_PHASE_3B §7).
    Returns HTTP 503 (not 200 with a "degraded" body) when not ready, since Nginx/an orchestrator
    typically gates routing on status code rather than parsing the response body. Never returns
    credentials, connection strings, or a stack trace — only ok/error per dependency."""
    service = HealthService()
    data = await service.check_ready()
    if not data.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return build_readiness_envelope(data)
