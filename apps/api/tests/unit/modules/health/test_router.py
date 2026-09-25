import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] in ("ok", "degraded")
    assert "meta" in body
    assert body["meta"]["request_id"]


@pytest.mark.asyncio
async def test_liveness_returns_ok_with_no_dependency_check(client) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_returns_200_when_dependencies_are_up(client) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["ready"] is True
    assert body["data"]["database"] == "ok"
    assert body["data"]["redis"] == "ok"
    assert body["data"]["storage_configured"] is True


@pytest.mark.asyncio
async def test_readiness_returns_503_when_redis_is_down(client, monkeypatch) -> None:
    from hrms.modules.health import service as health_service

    async def _redis_down() -> str:
        return "error"

    monkeypatch.setattr(health_service, "_check_redis", _redis_down)

    response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["data"]["ready"] is False
    assert body["data"]["redis"] == "error"


@pytest.mark.asyncio
async def test_readiness_response_never_leaks_connection_details(client) -> None:
    response = await client.get("/health/ready")
    body_text = response.text
    from hrms.core.config.settings import get_settings

    settings = get_settings()
    assert settings.database_url not in body_text
    assert settings.redis_url not in body_text
    assert settings.jwt_access_secret not in body_text
    assert settings.pii_master_key not in body_text
