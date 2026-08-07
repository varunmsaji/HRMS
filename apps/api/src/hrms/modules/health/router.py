from fastapi import APIRouter, status

from hrms.modules.health.service import HealthData, HealthService, build_health_envelope
from hrms.shared.pagination import DataEnvelope

router = APIRouter(tags=["health"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> DataEnvelope[HealthData]:
    service = HealthService()
    data = await service.check()
    envelope = build_health_envelope(data)
    return envelope
