"""Self-service punch gap and in/out order: no two punches closer than the minimum gap, and no
repeat of the latest punch's direction. HR on-behalf corrections are exempt."""

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_face_mandatory_punch import PLAIN
from tests.integration.modules.attendance.test_face_punch import _enrolled_self

from hrms.core.config.settings import get_settings

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _rules_on(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setenv("ATTENDANCE_PUNCH_MIN_GAP_SECONDS", "120")
    monkeypatch.setenv("ATTENDANCE_PUNCH_ORDER_CHECK_ENABLED", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


async def _punch(client: AsyncClient, headers: dict[str, str], direction: str):  # type: ignore[no-untyped-def]
    return await client.post(PLAIN, headers=headers, json={"direction": direction})


async def test_second_punch_inside_the_gap_is_refused_with_details(
    client: AsyncClient,
    face_tenant,
    fake_face_provider,  # type: ignore[no-untyped-def]
) -> None:
    me, _ = await _enrolled_self(client, face_tenant)

    assert (await _punch(client, me, "OUT")).status_code == 201
    response = await _punch(client, me, "OUT")

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "PUNCH_TOO_SOON"
    context = error["details"][0]["context"]
    assert context["last_direction"] == "OUT"
    assert context["min_gap_seconds"] == 120
    assert 0 < context["retry_after_seconds"] <= 120


async def test_repeating_the_same_direction_is_refused_once_the_gap_is_off(
    client: AsyncClient,
    face_tenant,
    fake_face_provider,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("ATTENDANCE_PUNCH_MIN_GAP_SECONDS", "0")
    get_settings.cache_clear()
    me, _ = await _enrolled_self(client, face_tenant)

    assert (await _punch(client, me, "OUT")).status_code == 201
    response = await _punch(client, me, "OUT")

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "PUNCH_ALREADY_RECORDED"
    assert error["details"][0]["context"]["last_direction"] == "OUT"
