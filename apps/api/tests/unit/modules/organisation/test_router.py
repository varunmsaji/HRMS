import pytest


@pytest.mark.asyncio
async def test_organisation_router_mounted_returns_404_for_unknown_path(client) -> None:
    response = await client.get("/v1/organisation-does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_app_starts_with_existing_routes_still_reachable(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
