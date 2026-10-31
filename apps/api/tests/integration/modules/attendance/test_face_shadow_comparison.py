"""Shadow face-provider comparison through the real app, DB and RBAC. The primary and the shadow
are in-memory fakes. The point of this file is the safety rule: the shadow provider is only ever
observed - whatever it says, does or fails to do, the punch, the attempt log and the failed-attempt
count are exactly what the primary alone produces."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from entrypoints.api import app
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import FakeFaceProvider
from tests.integration.modules.attendance.test_attendance_security import (
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_face_punch import (
    _attempts,
    _enrolled_self,
    _punch_count,
    face_punch,
)

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.dependencies import get_shadow_face_provider
from hrms.modules.attendance.face_verification import FaceMatchResult, FaceProviderError
from hrms.modules.attendance.permissions import ATTENDANCE_PUNCH

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]


@dataclass
class SlowFake(FakeFaceProvider):
    delay: float = 0.0

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        await asyncio.sleep(self.delay)
        return await super().verify(person_id=person_id, image=image, content_type=content_type)


def _comparison_env(monkeypatch: pytest.MonkeyPatch, *, timeout: str = "2") -> None:
    for key, value in {
        "FACE_VERIFICATION_PROVIDER": "facepp",
        "FACEPP_API_KEY": "k",
        "FACEPP_API_SECRET": "s",
        "FACE_VERIFICATION_SHADOW_PROVIDER": "opensource",
        "FACE_PROVIDER_COMPARISON_ENABLED": "true",
        "FACE_OS_ENABLED": "true",
        "FACE_OS_MODEL_DIR": "/not-used",
        "FACE_PROVIDER_SHADOW_TIMEOUT_SECONDS": timeout,
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture
def shadow(monkeypatch: pytest.MonkeyPatch) -> SlowFake:
    _comparison_env(monkeypatch)
    fake = SlowFake(provider_name="OPENSOURCE")
    fake.match_threshold = Decimal("0.45")  # type: ignore[attr-defined]  # the engine's own floor
    app.dependency_overrides[get_shadow_face_provider] = lambda: fake
    yield fake  # type: ignore[misc]
    app.dependency_overrides.pop(get_shadow_face_provider, None)
    monkeypatch.undo()
    get_settings.cache_clear()


async def _enrol_shadow(company_id: UUID, employee_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "INSERT INTO face_shadow_enrollment (id, company_id, employee_id, provider, "
                "provider_person_id, consent_recorded_at) "
                "VALUES (:id, :c, :e, 'OPENSOURCE', 'shadow-person', now())"
            ),
            {"id": str(uuid4()), "c": str(company_id), "e": employee_id},
        )
        await session.commit()


async def _comparisons(company_id: UUID) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text("SELECT * FROM face_verification_comparison ORDER BY created_at")
        )
        return [dict(r._mapping) for r in rows]


async def _setup(
    client: AsyncClient, face_tenant: Tenant, *, shadow_enrolled: bool = True
) -> tuple[dict[str, str], UUID, str]:
    _, company_id = face_tenant
    headers, employee_id = await _enrolled_self(client, face_tenant)
    if shadow_enrolled:
        await _enrol_shadow(company_id, employee_id)
    return headers, company_id, employee_id


async def test_primary_match_shadow_match(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    headers, company_id, _ = await _setup(client, face_tenant)
    shadow.match = FaceMatchResult("MATCHED", Decimal("0.6100"))

    response = await face_punch(client, headers)

    assert response.status_code == 201, response.text
    (row,) = await _comparisons(company_id)
    assert (row["primary_result"], row["shadow_result"]) == ("MATCHED", "MATCHED")
    assert row["results_agree"] is True
    assert row["primary_provider"] == "FACEPP" and row["shadow_provider"] == "OPENSOURCE"
    assert row["primary_score"] == Decimal("0.9700") and row["shadow_score"] == Decimal("0.6100")
    assert row["frames_compared"] == 3
    assert row["primary_latency_ms"] is not None and row["shadow_latency_ms"] is not None
    assert row["liveness_session_id"] is not None
    assert shadow.names() == ["verify"] * 3


async def test_shadow_reject_cannot_change_primary_match(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    headers, company_id, _ = await _setup(client, face_tenant)
    shadow.match = FaceMatchResult("NO_MATCH", Decimal("0.1000"))

    response = await face_punch(client, headers)

    assert response.status_code == 201, response.text
    assert await _punch_count(client, headers) == 1
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "MATCHED" and attempt["punch_id"] is not None
    (row,) = await _comparisons(company_id)
    assert (row["primary_matched"], row["shadow_matched"], row["results_agree"]) == (
        True,
        False,
        False,
    )


async def test_shadow_match_cannot_change_primary_reject(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    headers, company_id, _ = await _setup(client, face_tenant)
    fake_face_provider.match = FaceMatchResult("NO_MATCH", Decimal("0.85"))
    shadow.match = FaceMatchResult("MATCHED", Decimal("0.9900"))

    response = await face_punch(client, headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACE_NOT_MATCHED"
    assert await _punch_count(client, headers) == 0
    # Exactly the one rejected attempt the primary alone produces (it counts toward the lockout).
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "NO_MATCH" and attempt["punch_id"] is None
    (row,) = await _comparisons(company_id)
    assert (row["primary_result"], row["shadow_result"]) == ("NO_MATCH", "MATCHED")
    assert row["results_agree"] is False


async def test_shadow_error_cannot_fail_a_successful_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    headers, company_id, _ = await _setup(client, face_tenant)
    shadow.fail_with["verify"] = FaceProviderError("shadow exploded")

    response = await face_punch(client, headers)

    assert response.status_code == 201, response.text
    assert await _punch_count(client, headers) == 1
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "MATCHED"
    (row,) = await _comparisons(company_id)
    assert (row["shadow_result"], row["shadow_error"], row["results_agree"]) == (
        "ERROR",
        "PROVIDER_ERROR",
        None,
    )
    assert "shadow exploded" not in str(row)


async def test_shadow_unexpected_exception_cannot_fail_a_punch(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    headers, company_id, _ = await _setup(client, face_tenant)
    shadow.fail_with["verify"] = RuntimeError("bug in adapter")

    response = await face_punch(client, headers)

    assert response.status_code == 201, response.text
    (row,) = await _comparisons(company_id)
    assert row["shadow_error"] == "UNEXPECTED"


async def test_shadow_timeout_cannot_alter_attendance_and_is_bounded(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    shadow: SlowFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _comparison_env(monkeypatch, timeout="0.3")
    headers, company_id, _ = await _setup(client, face_tenant)
    shadow.delay = 30

    started = asyncio.get_running_loop().time()
    response = await face_punch(client, headers)
    elapsed = asyncio.get_running_loop().time() - started

    assert response.status_code == 201, response.text
    assert elapsed < 10  # the 30s shadow did not hold the punch
    assert await _punch_count(client, headers) == 1
    (row,) = await _comparisons(company_id)
    assert (row["shadow_result"], row["shadow_timed_out"]) == ("TIMEOUT", True)


async def test_primary_provider_failure_keeps_existing_behaviour(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    headers, company_id, _ = await _setup(client, face_tenant)
    fake_face_provider.fail_with["verify"] = FaceProviderError("primary down")

    response = await face_punch(client, headers)

    assert response.status_code == 502
    assert await _punch_count(client, headers) == 0
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "PROVIDER_ERROR"
    (row,) = await _comparisons(company_id)
    assert row["primary_error"] == "PROVIDER_ERROR" and row["results_agree"] is None


async def test_shadow_not_enrolled_is_recorded_and_harmless(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    headers, company_id, _ = await _setup(client, face_tenant, shadow_enrolled=False)

    response = await face_punch(client, headers)

    assert response.status_code == 201, response.text
    (row,) = await _comparisons(company_id)
    assert row["shadow_result"] == "NOT_ENROLLED" and row["results_agree"] is None
    assert shadow.calls == []


async def test_comparison_disabled_never_touches_the_shadow(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """Default config (comparison off): the shadow provider is not even constructed."""
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    get_settings.cache_clear()
    assert get_shadow_face_provider() is None

    response = await face_punch(client, headers)

    assert response.status_code == 201, response.text
    assert await _comparisons(company_id) == []


# -- admin surface ---------------------------------------------------------------------------


async def test_report_filters_and_ground_truth_metrics(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    admin_headers, company_id = face_tenant
    headers, _, _ = await _setup(client, face_tenant)
    assert (await face_punch(client, headers, "IN")).status_code == 201
    shadow.match = FaceMatchResult("NO_MATCH", Decimal("0.2000"))
    assert (await face_punch(client, headers, "OUT")).status_code == 201

    base = "/v1/attendance/face-verification-comparisons"
    listed = await client.get(base, headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["pagination"]["total"] == 2
    assert "provider_person_id" not in listed.text
    disagree = await client.get(base, headers=admin_headers, params={"agreement": "disagree"})
    assert disagree.json()["pagination"]["total"] == 1

    rows = listed.json()["data"]
    for row, truth in zip(rows, ("GENUINE", "GENUINE"), strict=True):
        labelled = await client.patch(
            f"{base}/{row['id']}/ground-truth", headers=admin_headers, json={"ground_truth": truth}
        )
        assert labelled.status_code == 200, labelled.text

    summary = (await client.get(f"{base}/summary", headers=admin_headers)).json()["data"]
    assert summary["total"] == 2 and summary["comparable"] == 2
    assert summary["both_matched"] == 1 and summary["primary_only_matched"] == 1
    assert summary["agreement_pct"] == 50.0
    assert summary["primary"]["latency"]["samples"] == 2
    assert summary["shadow"]["latency"]["p95_ms"] is not None
    # Genuine attempts: the primary accepted both, the shadow wrongly rejected one.
    assert summary["primary"]["labelled"]["frr"] == 0.0
    assert summary["shadow"]["labelled"]["frr"] == 0.5
    assert summary["shadow"]["labelled"]["far"] is None  # no impostor trials yet


async def test_employees_cannot_read_comparisons(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    headers, _, _ = await _setup(client, face_tenant)
    base = "/v1/attendance/face-verification-comparisons"
    assert (await client.get(base, headers=headers)).status_code == 403
    assert (await client.get(f"{base}/summary", headers=headers)).status_code == 403
    assert (
        await client.get("/v1/attendance/face-shadow-enrollments", headers=headers)
    ).status_code == 403


async def test_shadow_enrollment_lifecycle_leaves_production_profile_alone(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider, shadow: SlowFake
) -> None:
    admin_headers, company_id = face_tenant
    headers, employee_id = await _enrolled_self(client, face_tenant)
    url = f"/v1/attendance/face-shadow-enrollments/{employee_id}"
    photo = ("photos", ("p.jpg", b"\xff\xd8\xff\xe0" + b"x" * 64, "image/jpeg"))

    refused = await client.post(
        url, headers=admin_headers, files=[photo], data={"consent_confirmed": "false"}
    )
    assert refused.status_code == 422
    assert shadow.calls == []

    created = await client.post(
        url, headers=admin_headers, files=[photo, photo], data={"consent_confirmed": "true"}
    )
    assert created.status_code == 201, created.text
    assert "provider_person_id" not in created.text
    assert shadow.names() == ["enroll", "add_reference_photo"]
    again = await client.post(
        url, headers=admin_headers, files=[photo], data={"consent_confirmed": "true"}
    )
    assert again.status_code == 409

    # The production profile and its punch ability are untouched.
    assert (await face_punch(client, headers)).status_code == 201

    deleted = await client.delete(url, headers=admin_headers)
    assert deleted.status_code == 204
    assert shadow.names()[-1] == "delete_person"
    assert (await client.delete(url, headers=admin_headers)).status_code == 404
    listed = await client.get("/v1/attendance/face-shadow-enrollments", headers=admin_headers)
    assert listed.json()["data"] == []


async def test_non_manager_with_punch_permission_only(
    client: AsyncClient, face_tenant: Tenant, shadow: SlowFake
) -> None:
    _, company_id = face_tenant
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH],
        data_scope="SELF",
        caller_employee_id=None,
    )
    response = await client.get("/v1/attendance/face-verification-comparisons", headers=headers)
    assert response.status_code == 403
