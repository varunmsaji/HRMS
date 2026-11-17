"""SC-03 / SC-04 - break validation through the API.

SC-04 (D-6): the duration rules for a break apply to every break. They used to run only for a break
with a `mode`, which no client can set while `shift_break_modes_enabled` is off, so they never ran.
SC-03 (D-5): a flexible break's window must lie wholly inside the shift's window.

The test environment turns `SHIFT_BREAK_MODES_ENABLED` on for the break-management suite; every
payload below leaves `mode` empty, which is the only thing a client can send in production.
"""

from datetime import time
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

from .test_registration_flow import _cleanup
from .test_shift import _cleanup_shifts, _create_shift, _register_tenant

FIXED_DAY = {
    "shift_type": "FIXED",
    "effective_from": "2026-01-01",
    "start_time": "09:00",
    "end_time": "18:00",
}


def _flex(name: str = "Lunch", **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "break_kind": "FLEXIBLE_DURATION",
        "window_start": "12:00",
        "window_end": "15:00",
        "min_minutes": 30,
        "max_minutes": 60,
    }
    body.update(kw)
    return body


def _fixed(name: str = "Tea", **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "break_kind": "FIXED_WINDOW",
        "start_time": "16:00",
        "end_time": "16:15",
    }
    body.update(kw)
    return body


async def _patch(
    client: AsyncClient, headers: dict[str, str], shift: dict[str, Any], body: dict[str, Any]
) -> Any:
    return await client.patch(
        f"/v1/shifts/{shift['id']}/versions/{shift['draft_version_id']}",
        headers={**headers, "If-Match": "1"},
        json=body,
    )


async def _publish(client: AsyncClient, headers: dict[str, str], shift: dict[str, Any]) -> Any:
    return await client.post(
        f"/v1/shifts/{shift['id']}/versions/{shift['draft_version_id']}/publish",
        headers={**headers, "If-Match": "2"},
        json={},
    )


async def _save_and_publish(
    client: AsyncClient,
    headers: dict[str, str],
    schedule: dict[str, Any],
    breaks: list[dict[str, Any]],
) -> tuple[dict[str, Any], Any]:
    shift = await _create_shift(client, headers, name=f"S{len(breaks)}{id(breaks)}")
    saved = await _patch(client, headers, shift, {**schedule, "breaks": breaks})
    assert saved.status_code == 200, saved.text
    return shift, await _publish(client, headers, shift)


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# --- SC-04 ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "brk",
    [
        _flex(min_minutes=0, max_minutes=0),
        _flex(scheduled_minutes=61),
        _flex(scheduled_minutes=10),
        _fixed(max_minutes=0),
        _fixed(min_minutes=50, max_minutes=20),
        _fixed(max_minutes=10, scheduled_minutes=15),
        _fixed(min_minutes=10, scheduled_minutes=5),
        _fixed(scheduled_minutes=16),
    ],
    ids=[
        "flex-max-zero",
        "flex-scheduled-over-max",
        "flex-scheduled-under-min",
        "fixed-max-zero",
        "fixed-min-over-max",
        "fixed-scheduled-over-max",
        "fixed-scheduled-under-min",
        "fixed-scheduled-over-window",
    ],
)
async def test_incoherent_break_durations_are_refused_at_save(
    client: AsyncClient, seeded_plan_catalogue: None, brk: dict[str, Any]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await _patch(client, headers, shift, {"breaks": [brk]})
        assert response.status_code == 422, response.text
        assert _code(response) == "INVALID_SHIFT_BREAK"
        assert response.json()["error"]["details"][0]["field"] == "breaks.0"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_coherent_break_durations_are_saved_and_published(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift, published = await _save_and_publish(
            client,
            headers,
            FIXED_DAY,
            [
                _flex(scheduled_minutes=45),
                _fixed(min_minutes=5, max_minutes=15, scheduled_minutes=15),
            ],
        )
        assert published.status_code == 200, published.text
        names = [b["name"] for b in published.json()["data"]["breaks"]]
        assert names == ["Lunch", "Tea"]
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_a_break_mode_is_still_not_accepted_when_the_feature_is_off(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing in SC-04 turns break modes on."""
    from hrms.core.config.settings import get_settings

    monkeypatch.setenv("SHIFT_BREAK_MODES_ENABLED", "false")
    get_settings.cache_clear()
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await _patch(
            client, headers, shift, {"breaks": [_flex(mode="AUTO_DEDUCT", scheduled_minutes=30)]}
        )
        assert response.status_code == 422, response.text
        assert "Break modes are not available yet" in response.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        get_settings.cache_clear()


# --- SC-03 ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("window", "status"),
    [
        (("12:00", "15:00"), 200),
        (("09:00", "18:00"), 200),
        (("19:00", "20:00"), 422),
        (("07:00", "08:00"), 422),
        (("08:00", "10:00"), 422),
        (("17:00", "19:00"), 422),
    ],
    ids=["inside", "equal-to-shift", "after", "before", "starts-early", "ends-late"],
)
async def test_flexible_window_must_be_inside_a_fixed_shift(
    client: AsyncClient, seeded_plan_catalogue: None, window: tuple[str, str], status: int
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        _, published = await _save_and_publish(
            client,
            headers,
            FIXED_DAY,
            [_flex(window_start=window[0], window_end=window[1], min_minutes=15, max_minutes=45)],
        )
        assert published.status_code == status, published.text
        if status == 422:
            assert _code(published) == "INVALID_SHIFT_BREAK"
            assert "outside the shift" in published.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("window", "status"),
    [(("23:00", "23:59"), 200), (("01:00", "03:00"), 200), (("12:00", "14:00"), 422)],
    ids=["before-midnight", "after-midnight", "daytime-gap"],
)
async def test_overnight_fixed_shift_windows(
    client: AsyncClient, seeded_plan_catalogue: None, window: tuple[str, str], status: int
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        _, published = await _save_and_publish(
            client,
            headers,
            {**FIXED_DAY, "start_time": "22:00", "end_time": "06:00"},
            [_flex(window_start=window[0], window_end=window[1], min_minutes=15, max_minutes=45)],
        )
        assert published.status_code == status, published.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("window", "status"),
    [(("12:00", "14:00"), 200), (("20:00", "21:00"), 422)],
    ids=["inside-working-span", "past-latest-end"],
)
async def test_flexible_window_in_a_flexible_shift(
    client: AsyncClient, seeded_plan_catalogue: None, window: tuple[str, str], status: int
) -> None:
    """Bound is the start window's opening to its close plus `required_minutes` (SH-11)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        _, published = await _save_and_publish(
            client,
            headers,
            {
                "shift_type": "FLEXIBLE",
                "effective_from": "2026-01-01",
                "window_start": "07:00",
                "window_end": "11:00",
                "required_minutes": 480,
            },
            [_flex(window_start=window[0], window_end=window[1], min_minutes=15, max_minutes=45)],
        )
        assert published.status_code == status, published.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_split_shifts_are_not_checked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """D-7: SPLIT break-to-block relationships are deferred, so nothing new applies to them."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        _, published = await _save_and_publish(
            client,
            headers,
            {
                "shift_type": "SPLIT",
                "effective_from": "2026-01-01",
                "duty_blocks": [
                    {"sequence": 1, "start_time": "08:00", "end_time": "12:00"},
                    {"sequence": 2, "start_time": "16:00", "end_time": "20:00"},
                ],
            },
            [_flex(window_start="13:00", window_end="15:00", min_minutes=15, max_minutes=45)],
        )
        assert published.status_code == 200, published.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_a_draft_may_hold_an_outside_window_until_it_is_published(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Containment depends on the shift's times, which a draft may not have yet, so it is a
    publish-time check exactly as it is for a fixed break."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        saved = await _patch(
            client, headers, shift, {"breaks": [_flex(window_start="22:00", window_end="23:00")]}
        )
        assert saved.status_code == 200, saved.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- Existing data and neighbouring rules ---------------------------------------------------------


async def _force_break_window(company_id: UUID, version_id: str, start: str, end: str) -> None:
    """Rewrites a stored break as pre-SC-03 data could have been (outside the shift)."""
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "UPDATE shift_break SET window_start = :s, window_end = :e "
                "WHERE shift_version_id = :v AND break_kind = 'FLEXIBLE_DURATION'"
            ),
            {"s": time.fromisoformat(start), "e": time.fromisoformat(end), "v": version_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_a_published_version_with_an_outside_break_is_left_alone(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Published versions are history and are never re-validated: reading, resolving and
    publishing the next version all still work, and the stored break is unchanged."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift, published = await _save_and_publish(client, headers, FIXED_DAY, [_flex(), _fixed()])
        assert published.status_code == 200, published.text
        v1 = published.json()["data"]
        await _force_break_window(company_id, v1["id"], "20:00", "22:00")

        resolved = await client.get(
            f"/v1/shifts/{shift['id']}/versions/resolve",
            headers=headers,
            params={"as_of": "2026-06-01"},
        )
        assert resolved.status_code == 200, resolved.text
        flexible = next(b for b in resolved.json()["data"]["breaks"] if b["name"] == "Lunch")
        assert (flexible["window_start"], flexible["window_end"]) == ("20:00", "22:00")

        draft = await client.post(
            f"/v1/shifts/{shift['id']}/versions",
            headers=headers,
            json={**FIXED_DAY, "effective_from": "2026-07-01", "breaks": [_fixed("Tea 2")]},
        )
        assert draft.status_code == 201, draft.text
        v2 = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft.json()['data']['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={"expected_previous_version": v1["version"]},
        )
        assert v2.status_code == 200, v2.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_saving_other_fields_does_not_revalidate_stored_breaks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Only a request that sends `breaks` re-checks them, as before SC-04."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        saved = await _patch(client, headers, shift, {"breaks": [_flex()]})
        assert saved.status_code == 200, saved.text
        await _force_break_window(company_id, shift["draft_version_id"], "20:00", "22:00")
        other = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{shift['draft_version_id']}",
            headers={**headers, "If-Match": str(saved.json()["data"]["version"])},
            json=FIXED_DAY,
        )
        assert other.status_code == 200, other.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_fixed_break_checks_are_unchanged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        _, outside = await _save_and_publish(
            client, headers, FIXED_DAY, [_fixed(start_time="19:00", end_time="19:30")]
        )
        assert outside.status_code == 422 and _code(outside) == "INVALID_SHIFT_BREAK"
        _, overlap_saved = await _save_and_publish(
            client, headers, FIXED_DAY, [_fixed("A", start_time="12:00", end_time="13:00")]
        )
        assert overlap_saved.status_code == 200
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_setup_in_one_request_applies_the_same_rules(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`POST /shifts/setup` reuses the step methods, so a bad break leaves no shift behind."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        bad = await client.post(
            "/v1/shifts/setup",
            headers=headers,
            json={
                "name": "Via setup",
                "rules": {**FIXED_DAY, "breaks": [_flex(window_start="19:00", window_end="20:00")]},
            },
        )
        assert bad.status_code == 422, bad.text
        listed = await client.get("/v1/shifts", headers=headers)
        assert listed.json()["data"] == []
        good = await client.post(
            "/v1/shifts/setup",
            headers=headers,
            json={"name": "Via setup", "rules": {**FIXED_DAY, "breaks": [_flex()]}},
        )
        assert good.status_code == 201, good.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
