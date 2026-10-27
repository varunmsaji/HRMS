"""Open-source face engine through the real attendance stack: real app, Postgres (RLS), PII
encryption and outbox; only the neural network is replaced by a deterministic embedder (the real
model is exercised in tests/unit/modules/attendance/test_opensource_face.py). Proves the engine
obeys the same enrollment / challenge / lockout rules as Face++ and that the two never mix."""

import math
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from entrypoints.api import app
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import (
    FakeFaceProvider,
    FakeLivenessEngine,
    FakePhotoStorage,
    run_deletion_worker,
)
from tests.integration.modules.attendance.test_face_enrollment import (
    ANGLES,
    _employee,
    _sql,
    enroll_and_approve,
)
from tests.integration.modules.attendance.test_face_punch import (
    _attempts,
    _punch_count,
    face_punch,
)

from hrms.core.config.settings import get_settings
from hrms.modules.attendance.dependencies import get_face_provider
from hrms.modules.attendance.opensource_face.embedding_service import (
    EmbeddingOutcome,
    EmbeddingTimeoutError,
)
from hrms.modules.attendance.opensource_face.engine import OpenSourceFaceVerificationProvider
from hrms.modules.attendance.opensource_face.similarity import EMBEDDING_DIM, normalise
from hrms.modules.attendance.opensource_face.store import DbEmbeddingStore

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]


def _unit(axis: int, tilt: float = 0.0) -> tuple[float, ...]:
    v = [0.0] * EMBEDDING_DIM
    v[axis], v[axis + 1] = math.cos(tilt), math.sin(tilt)
    return normalise(v)


@dataclass
class DeterministicEmbedder:
    """Every image is "the same person" (axis 0, tilted a little per call) unless `identity` is
    switched, which models a different person. No network, no model."""

    model_version: str = "sface-2021dec"
    identity: int = 0
    #: Identities consumed one per call before falling back to `identity` (a "different person
    #: mid-enrollment" script).
    script: list[int] = field(default_factory=list)
    fail_with: Exception | None = None
    calls: int = 0
    _tilt: float = field(default=0.0)

    async def embed(self, image: bytes) -> EmbeddingOutcome:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        self._tilt += 0.03
        who = self.script.pop(0) if self.script else self.identity
        return EmbeddingOutcome("OK", _unit(who * 4, self._tilt))


@pytest.fixture
async def os_engine(
    fake_liveness_engine: FakeLivenessEngine, fake_photo_storage: FakePhotoStorage
) -> AsyncIterator[tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder]]:
    settings = get_settings().model_copy(
        update={"face_os_match_threshold": 0.45, "face_os_enrollment_angle_threshold": 0.363}
    )
    embedder = DeterministicEmbedder()
    provider = OpenSourceFaceVerificationProvider(
        settings,
        embedder=embedder,  # type: ignore[arg-type]
        store=DbEmbeddingStore(settings),
    )
    app.dependency_overrides[get_face_provider] = lambda: provider
    yield provider, embedder
    app.dependency_overrides.pop(get_face_provider, None)


async def _embedding_rows(company_id: UUID) -> list[Any]:
    return await _sql(
        company_id, "SELECT employee_id, model_version, embedding_enc FROM face_embedding"
    )


async def test_enroll_and_punch_through_the_real_stack(
    client: AsyncClient,
    face_tenant: Tenant,
    os_engine: tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder],
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    me = await enroll_and_approve(client, admin, company_id, employee_id)

    (profile,) = await _sql(
        company_id, "SELECT provider, provider_person_id, status FROM employee_face_profile"
    )
    assert (
        profile[0] == "OPENSOURCE" and profile[1].startswith("osf1.") and profile[2] == "ENROLLED"
    )
    rows = await _embedding_rows(company_id)
    assert len(rows) == len(ANGLES)
    assert {str(r[0]) for r in rows} == {employee_id}
    for _, version, blob in rows:
        assert version == "sface-2021dec"
        assert blob.startswith("v1:") and "[" not in blob  # AES-GCM envelope, not JSON

    response = await face_punch(client, me)
    assert response.status_code == 201, response.text
    assert response.json()["data"]["punch"]["source"] == "FACE"
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "MATCHED"
    (provider,) = (
        r[0] for r in await _sql(company_id, "SELECT provider FROM face_verification_attempt")
    )
    assert provider == "OPENSOURCE"
    assert Decimal(str(attempt["similarity"])) >= Decimal("0.45")
    # Nothing biometric reached the audit evidence.
    assert "embedding" not in str(attempt["provider_response"]).lower()


async def test_other_person_is_rejected_without_a_punch(
    client: AsyncClient,
    face_tenant: Tenant,
    os_engine: tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder],
) -> None:
    admin, company_id = face_tenant
    _, embedder = os_engine
    employee_id = await _employee(client, admin)
    me = await enroll_and_approve(client, admin, company_id, employee_id)
    embedder.identity = 3  # a different face from here on

    response = await face_punch(client, me)

    assert response.status_code == 422 and response.json()["error"]["code"] == "FACE_NOT_MATCHED"
    (attempt,) = await _attempts(company_id)
    assert attempt["decision"] == "NO_MATCH" and attempt["punch_id"] is None
    assert await _punch_count(client, me) == 0


async def test_engine_outage_never_punches_and_never_locks_the_employee_out(
    client: AsyncClient,
    face_tenant: Tenant,
    os_engine: tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder],
) -> None:
    admin, company_id = face_tenant
    _, embedder = os_engine
    employee_id = await _employee(client, admin)
    me = await enroll_and_approve(client, admin, company_id, employee_id)
    embedder.fail_with = EmbeddingTimeoutError("busy")

    limit = get_settings().face_punch_max_failed_attempts
    for _ in range(limit + 1):
        response = await face_punch(client, me)
        assert response.status_code >= 500 or response.status_code == 502, response.text
        assert response.json()["error"]["code"] == "FACE_PROVIDER_FAILED"
    assert await _punch_count(client, me) == 0
    assert {a["decision"] for a in await _attempts(company_id)} == {"PROVIDER_ERROR"}

    embedder.fail_with = None  # engine recovers -> the employee is not locked out
    assert (await face_punch(client, me)).status_code == 201


async def test_profile_from_the_other_engine_is_not_usable(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    """A Face++ enrollment cannot be punched against the open-source engine (and vice versa):
    re-enrollment is required, nothing is sent to either engine, and there is no fallback."""
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    me = await enroll_and_approve(client, admin, company_id, employee_id)  # FACEPP profile

    settings = get_settings()
    embedder = DeterministicEmbedder()
    os_provider = OpenSourceFaceVerificationProvider(
        settings,
        embedder=embedder,
        store=DbEmbeddingStore(settings),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_face_provider] = lambda: os_provider
    fake_face_provider.calls.clear()
    response = await face_punch(client, me)
    assert response.status_code == 409 and response.json()["error"]["code"] == "FACE_NOT_ENROLLED"
    assert embedder.calls == [] or embedder.calls == 0
    assert fake_face_provider.calls == []
    assert await _punch_count(client, me) == 0

    # And the reverse direction: switch back to Face++ after an OPENSOURCE enrollment.
    await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)
    me2 = await enroll_and_approve(client, admin, company_id, employee_id)
    assert (await _sql(company_id, "SELECT provider FROM employee_face_profile"))[0][
        0
    ] == "OPENSOURCE"
    app.dependency_overrides[get_face_provider] = lambda: fake_face_provider
    fake_face_provider.calls.clear()
    response = await face_punch(client, me2)
    assert response.status_code == 409 and response.json()["error"]["code"] == "FACE_NOT_ENROLLED"
    assert fake_face_provider.calls == []


async def test_revocation_deletes_embeddings_through_the_outbox(
    client: AsyncClient,
    face_tenant: Tenant,
    os_engine: tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder],
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)
    assert len(await _embedding_rows(company_id)) == len(ANGLES)

    assert (
        await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)
    ).status_code == 200
    # Revocation alone does not delete: the outbox does, after the commit.
    assert len(await _embedding_rows(company_id)) == len(ANGLES)
    (row,) = await _sql(
        company_id,
        "SELECT provider, status FROM face_external_deletion WHERE kind = 'PROVIDER_PERSON'",
    )
    assert row[0] == "OPENSOURCE"

    # No provider injected: the worker picks the engine named on the outbox row.
    report = await run_deletion_worker(company_id, None, fake_photo_storage)
    assert report.done >= 1 and report.failed == 0
    assert await _embedding_rows(company_id) == []


async def test_embeddings_are_tenant_scoped_at_the_database(
    client: AsyncClient,
    face_tenant: Tenant,
    face_tenant_b: Tenant,
    os_engine: tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder],
) -> None:
    admin, company_id = face_tenant
    _, other_company = face_tenant_b
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)
    (person_id,) = (
        r[0] for r in await _sql(company_id, "SELECT provider_person_id FROM employee_face_profile")
    )
    # The provider refuses another tenant's person id while that tenant's request is active.
    from hrms.core.tenancy.context import TenantContext, clear_tenant, set_tenant
    from hrms.modules.attendance.face_verification import FaceProviderError

    provider, _ = os_engine
    set_tenant(TenantContext(company_id=other_company))
    try:
        with pytest.raises(FaceProviderError):
            await provider.verify(person_id=person_id, image=b"x", content_type="image/jpeg")
    finally:
        clear_tenant()

    # Row-level security itself, under the NON-bypass runtime role (the suite's own role owns
    # the tables and bypasses RLS, so only an `hrms_app` connection proves the policy).
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    url = make_url(get_settings().database_url).set(
        drivername="postgresql+asyncpg", username="hrms_app", password="hrms_app_dev_password"
    )
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            counts = {}
            for label, tenant in (("owner", company_id), ("other", other_company)):
                await conn.execute(
                    text("SELECT set_config('app.company_id', :c, false)"), {"c": str(tenant)}
                )
                counts[label] = (
                    await conn.execute(text("SELECT count(*) FROM face_embedding"))
                ).scalar_one()
            await conn.execute(
                text("SELECT set_config('app.company_id', :c, false)"), {"c": str(other_company)}
            )
            cross = (
                await conn.execute(
                    text("SELECT count(*) FROM face_embedding WHERE company_id = :c"),
                    {"c": str(company_id)},
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert counts == {"owner": len(ANGLES), "other": 0} and cross == 0


async def test_tampered_ownership_columns_fail_closed_never_match(
    client: AsyncClient,
    face_tenant: Tenant,
    os_engine: tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder],
) -> None:
    """Re-pointing a stored template at another employee (owner-role UPDATE) or swapping two
    rows' ciphertext must make verification an error, not a match and not a silent pass."""
    from hrms.modules.attendance.face_verification import FaceProviderError

    admin, company_id = face_tenant
    provider, _ = os_engine
    employee_id = await _employee(client, admin)
    other_employee = await _employee(client, admin, "Ravi")
    await enroll_and_approve(client, admin, company_id, employee_id)
    (person_id,) = (
        r[0] for r in await _sql(company_id, "SELECT provider_person_id FROM employee_face_profile")
    )
    from hrms.core.tenancy.context import TenantContext, clear_tenant, set_tenant

    async def verify() -> None:
        set_tenant(TenantContext(company_id=company_id))
        try:
            await provider.verify(person_id=person_id, image=b"x", content_type="image/jpeg")
        finally:
            clear_tenant()

    await verify()  # intact rows verify fine
    await _sql(company_id, f"UPDATE face_embedding SET employee_id = '{other_employee}'")
    with pytest.raises(FaceProviderError):
        await verify()
    await _sql(company_id, f"UPDATE face_embedding SET employee_id = '{employee_id}'")
    await verify()  # restoring the true owner restores decryptability
    await _sql(
        company_id,
        "UPDATE face_embedding a SET embedding_enc = b.embedding_enc FROM face_embedding b "
        "WHERE a.sample_index = 0 AND b.sample_index = 1",
    )
    with pytest.raises(FaceProviderError):
        await verify()


async def test_requires_reenrollment_flag_follows_the_selected_engine(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)  # FACEPP profile

    def flag(body: dict[str, Any]) -> bool:
        return bool(body["profile"]["requires_reenrollment"])

    response = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/enrollment", headers=admin
    )
    assert response.status_code == 200 and flag(response.json()["data"]) is False

    settings = get_settings()
    os_provider = OpenSourceFaceVerificationProvider(
        settings,
        embedder=DeterministicEmbedder(),
        store=DbEmbeddingStore(settings),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_face_provider] = lambda: os_provider
    response = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/enrollment", headers=admin
    )
    assert flag(response.json()["data"]) is True
    listed = await client.get("/v1/attendance/face-profiles", headers=admin)
    assert listed.status_code == 200
    items = listed.json()["data"]
    assert [i["requires_reenrollment"] for i in items] == [True]
    # No biometric handle is ever part of the response.
    assert "provider_person_id" not in str(listed.json()) and "embedding" not in str(listed.json())


async def test_failed_open_source_enrollment_leaves_no_profile_and_no_embeddings(
    client: AsyncClient,
    face_tenant: Tenant,
    os_engine: tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder],
) -> None:
    from tests.integration.modules.attendance.test_face_enrollment import (
        _open,
        _self_headers,
        _submit,
    )

    admin, company_id = face_tenant
    _, embedder = os_engine
    employee_id = await _employee(client, admin)
    assert (await _open(client, admin, employee_id)).status_code == 201
    me = await _self_headers(company_id, employee_id)
    embedder.script = [0, 5]  # front is person 0, the first turned capture is someone else

    response = await _submit(client, me)

    assert response.status_code >= 400, response.text
    assert await _sql(company_id, "SELECT 1 FROM employee_face_profile") == []
    assert await _embedding_rows(company_id) == []  # compensated immediately, nothing orphaned
    # The window is not consumed by the failure: the employee can try again.
    embedder.script = []
    assert (await _submit(client, me)).status_code == 201


async def test_revoke_is_idempotent_and_deletion_retries_after_a_store_failure(
    client: AsyncClient,
    face_tenant: Tenant,
    os_engine: tuple[OpenSourceFaceVerificationProvider, DeterministicEmbedder],
    fake_photo_storage: FakePhotoStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)

    assert (
        await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)
    ).status_code == 200
    again = await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)
    assert again.status_code in (200, 409), again.text
    (queued,) = await _sql(
        company_id,
        "SELECT count(*) FROM face_external_deletion "
        "WHERE kind = 'PROVIDER_PERSON' AND status <> 'DONE'",
    )
    assert queued[0] == 1  # one deletion queued for the one profile, however often revoked

    real = DbEmbeddingStore.delete_person
    calls = {"n": 0}

    async def flaky(self: DbEmbeddingStore, **kw: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database hiccup")
        await real(self, **kw)

    monkeypatch.setattr(DbEmbeddingStore, "delete_person", flaky)
    first = await run_deletion_worker(company_id, None, fake_photo_storage)
    assert first.failed >= 1 and len(await _embedding_rows(company_id)) == len(ANGLES)
    later = datetime.now(UTC) + timedelta(hours=2)
    second = await run_deletion_worker(company_id, None, fake_photo_storage, now=later)
    assert second.done >= 1 and await _embedding_rows(company_id) == []
