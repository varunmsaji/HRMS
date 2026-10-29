"""Geofencing on the face-punch endpoint: the same server-side rules, enforced before the
one-time liveness challenge or any face work is spent."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import (
    FakeFaceProvider,
    FakeLivenessEngine,
    FakePhotoStorage,
)
from tests.integration.modules.attendance.test_face_enrollment import enroll_and_approve
from tests.integration.modules.attendance.test_face_punch import (
    challenge,
    face_punch,
    submit,
)
from tests.integration.modules.attendance.test_geofence import KOCHI, _wire, north

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]


@pytest.fixture(autouse=True)
def _face_fakes(
    fake_photo_storage: FakePhotoStorage,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    """In-memory photo storage, face provider and liveness engine for every test here (nothing
    contacts Face++ or runs the real model)."""


def form_fix(
    at: tuple[float, float] = KOCHI, *, accuracy: float = 10, age: float = 3
) -> dict[str, str]:
    captured = datetime.now(UTC) - timedelta(seconds=age)
    return {
        "location_latitude": str(at[0]),
        "location_longitude": str(at[1]),
        "location_accuracy_m": str(accuracy),
        "location_captured_at": captured.isoformat(),
    }


async def _enrolled_wired(
    client: AsyncClient, face_tenant: Tenant, *, mode: str | None
) -> tuple[dict[str, str], str, UUID]:
    admin, company_id = face_tenant
    wired = await _wire(client, admin, mode=mode)
    me = await enroll_and_approve(client, admin, company_id, wired["employee_id"])
    return me, wired["employee_id"], company_id


async def _rows(company_id: UUID, query: str) -> list[tuple]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        return [tuple(r) for r in await session.execute(text(query), {"cid": str(company_id)})]


async def test_required_inside_face_punch_is_recorded_with_the_geofence_decision(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    me, employee_id, company_id = await _enrolled_wired(client, face_tenant, mode="REQUIRED")
    response = await face_punch(client, me, extra=form_fix(north(40)))
    assert response.status_code == 201, response.text
    punch = response.json()["data"]["punch"]
    assert punch["source"] == "FACE"
    assert punch["geofence"]["outcome"] == "INSIDE" and punch["geofence"]["accepted"] is True
    attempts = await _rows(
        company_id,
        "SELECT outcome, accepted, punch_id FROM geofence_attempt WHERE company_id = :cid",
    )
    assert [(a[0], a[1], str(a[2])) for a in attempts] == [("INSIDE", True, punch["id"])]


async def test_outside_is_refused_before_face_work_and_keeps_the_challenge_usable(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    me, employee_id, company_id = await _enrolled_wired(client, face_tenant, mode="REQUIRED")
    issued = await challenge(client, me)
    assert issued.status_code == 201
    session_id = issued.json()["data"]["session_id"]
    provider_calls = len(fake_face_provider.calls)
    liveness_calls = len(fake_liveness_engine.calls)

    refused = await submit(client, me, session_id=session_id, extra=form_fix(north(2000)))
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "PUNCH_OUTSIDE_GEOFENCE"
    # No frame was assessed and the face provider was never contacted for the refused attempt.
    assert len(fake_liveness_engine.calls) == liveness_calls
    assert len(fake_face_provider.calls) == provider_calls
    assert await _rows(company_id, "SELECT 1 FROM punch WHERE company_id = :cid") == []

    # The one-time challenge was not spent: the same session now works from inside the fence.
    ok = await submit(client, me, session_id=session_id, extra=form_fix(north(10)))
    assert ok.status_code == 201, ok.text


async def test_required_face_punch_without_location_is_refused(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    me, _, company_id = await _enrolled_wired(client, face_tenant, mode="REQUIRED")
    response = await face_punch(client, me)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PUNCH_LOCATION_REQUIRED"
    assert await _rows(company_id, "SELECT 1 FROM punch WHERE company_id = :cid") == []

    denied = await face_punch(client, me, extra={"location_error": "PERMISSION_DENIED"})
    assert denied.status_code == 422
    assert denied.json()["error"]["code"] == "PUNCH_LOCATION_UNAVAILABLE_CLIENT"


@pytest.mark.parametrize(
    "extra",
    [
        {"location_latitude": "9.9"},  # partial
        {**form_fix(), "location_error": "TIMEOUT"},  # both
        {"location_error": "NOPE"},
        {**form_fix(), "location_latitude": "123"},  # out of range
        {**form_fix(), "location_captured_at": "2026-10-28T09:00:00"},  # naive timestamp
    ],
)
async def test_malformed_form_locations_are_validation_errors(
    client: AsyncClient, face_tenant: Tenant, extra: dict[str, str]
) -> None:
    me, _, company_id = await _enrolled_wired(client, face_tenant, mode="REQUIRED")
    response = await face_punch(client, me, extra=extra)
    assert response.status_code == 422, response.text
    assert await _rows(company_id, "SELECT 1 FROM punch WHERE company_id = :cid") == []


async def test_disabled_policy_ignores_the_form_location(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    me, _, company_id = await _enrolled_wired(client, face_tenant, mode=None)
    response = await face_punch(client, me, extra=form_fix(north(50_000)))
    assert response.status_code == 201, response.text
    assert response.json()["data"]["punch"]["geofence"] is None
    assert await _rows(company_id, "SELECT 1 FROM geofence_attempt WHERE company_id = :cid") == []
