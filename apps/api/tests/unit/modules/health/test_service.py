import pytest

from hrms.modules.health.service import HealthService


@pytest.mark.asyncio
async def test_health_service_returns_status() -> None:
    service = HealthService()
    result = await service.check()
    assert result.status in ("ok", "degraded")
    assert result.database in ("ok", "error")
