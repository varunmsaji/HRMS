import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] in ("ok", "degraded")
    assert "meta" in body
    assert body["meta"]["request_id"]
