from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import delete, select, text

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.face_verification import (
    PROVIDER_FACEPP,
    FaceMatchResult,
)
from hrms.modules.attendance.liveness import (
    FrameAssessment,
    InconclusiveReason,
    LivenessAssessment,
    aggregate,
    classify_frame,
    unscored_frame,
)
from hrms.modules.organisation.models import Plan, PlanFeature, Subscription
from hrms.seed.plan_catalogue import PLAN_CATALOGUE, seed_plan_catalogue

_REGISTRATION_RATE_LIMIT_KEY = "ratelimit:auth:127.0.0.1"


@pytest.fixture(autouse=True)
async def _reset_registration_rate_limit() -> None:
    """Every request through `ASGITransport` shares client host 127.0.0.1 — without this,
    registration tests across this module would exhaust the real 10/min bucket and start
    failing each other with 429s."""
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    await client.delete(_REGISTRATION_RATE_LIMIT_KEY)
    yield
    await client.delete(_REGISTRATION_RATE_LIMIT_KEY)
    await client.aclose()


@pytest.fixture
async def seeded_plan_catalogue() -> None:
    factory = get_session_factory()
    codes = [code for code, *_ in PLAN_CATALOGUE]
    async with factory() as session:
        await seed_plan_catalogue(session)
        await session.commit()
    yield
    async with factory() as session:
        plan_ids = select(Plan.id).where(Plan.code.in_(codes))
        await session.execute(delete(Subscription).where(Subscription.plan_id.in_(plan_ids)))
        await session.execute(delete(PlanFeature).where(PlanFeature.plan_id.in_(plan_ids)))
        await session.execute(delete(Plan).where(Plan.code.in_(codes)))
        await session.commit()


# --- Face attendance (fake provider + fake liveness engine; nothing here contacts Face++ or
# runs the real model — the real model is covered by tests/unit/.../test_liveness.py) ---

#: Fused class probabilities [spoof_a, real, spoof_b] — fed through the real `classify_frame`
#: and `aggregate`, so the decision rules under test are the production ones.
LIVE_PROBS = [0.02, 0.95, 0.03]
SPOOF_PROBS = [0.10, 0.07, 0.83]
UNSURE_PROBS = [0.30, 0.60, 0.10]


@dataclass
class FakeLivenessEngine:
    model_version: str = "fake-test-engine"
    #: Per-frame probabilities, cycled over the submitted frames.
    probs: list[list[float]] = field(default_factory=lambda: [LIVE_PROBS])
    #: When set, every frame is this unscored outcome instead (NO_FACE, MULTIPLE_FACES...).
    unscored: InconclusiveReason | None = None
    fail_with: Exception | None = None
    calls: list[list[bytes]] = field(default_factory=list)
    #: One entry consumed per `assess` call before falling back to `probs` / `unscored`; an entry
    #: is a list of per-frame probabilities, or a reason string for an unscored outcome. Lets a
    #: test fail exactly one enrollment angle (enrollment calls the engine once per image).
    per_call: list[list[list[float]] | InconclusiveReason] = field(default_factory=list)

    async def assess(self, frames: Sequence[bytes]) -> LivenessAssessment:
        self.calls.append(list(frames))
        if self.fail_with is not None:
            raise self.fail_with
        probs, unscored = self.probs, self.unscored
        if self.per_call:
            override = self.per_call.pop(0)
            if isinstance(override, str):
                unscored = override
            else:
                probs = override
        assessed: list[FrameAssessment] = []
        for i, _ in enumerate(frames):
            if unscored is not None:
                assessed.append(unscored_frame(unscored))
                continue
            assessed.append(
                classify_frame(probs[i % len(probs)], live_threshold=0.9, spoof_threshold=0.5)
            )
        return aggregate(assessed, model_version=self.model_version)


@pytest.fixture
async def fake_liveness_engine() -> AsyncIterator[FakeLivenessEngine]:
    from entrypoints.api import app

    from hrms.modules.attendance.dependencies import get_face_liveness_engine

    engine = FakeLivenessEngine()
    app.dependency_overrides[get_face_liveness_engine] = lambda: engine
    yield engine
    app.dependency_overrides.pop(get_face_liveness_engine, None)


@dataclass
class FakeFaceProvider:
    provider_name: str = PROVIDER_FACEPP
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail_with: dict[str, Exception] = field(default_factory=dict)
    match: FaceMatchResult = field(
        default_factory=lambda: FaceMatchResult("MATCHED", Decimal("0.9700"), "req-fake-1")
    )

    #: Consumed one per `verify` call before falling back to `match` — lets a test fail one angle.
    verify_results: list[FaceMatchResult] = field(default_factory=list)

    def _call(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if name in self.fail_with:
            raise self.fail_with[name]

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str:
        self._call("enroll", label=label, content_type=content_type)
        return str(uuid4())

    async def add_reference_photo(self, *, person_id: str, image: bytes, content_type: str) -> None:
        self._call("add_reference_photo", person_id=person_id)

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        self._call("verify", person_id=person_id, image=image)
        return self.verify_results.pop(0) if self.verify_results else self.match

    async def delete_person(self, *, person_id: str) -> None:
        self._call("delete_person", person_id=person_id)


@pytest.fixture
async def fake_face_provider(
    fake_liveness_engine: FakeLivenessEngine,
) -> AsyncIterator[FakeFaceProvider]:
    """Also installs `fake_liveness_engine` (LIVE by default): face punching fails closed
    without a liveness engine."""
    from entrypoints.api import app

    from hrms.modules.attendance.dependencies import get_face_provider

    provider = FakeFaceProvider()
    app.dependency_overrides[get_face_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_face_provider, None)


@dataclass
class FakePhotoStorage:
    objects: dict[str, bytes] = field(default_factory=dict)
    fail_put: bool = False

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        if self.fail_put:
            raise RuntimeError("storage down")
        self.objects[key] = body

    async def get_object(self, *, key: str) -> bytes:
        return self.objects[key]

    async def delete_object(self, *, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
async def fake_photo_storage() -> AsyncIterator[FakePhotoStorage]:
    from entrypoints.api import app

    from hrms.modules.attendance.dependencies import get_face_photo_storage

    storage = FakePhotoStorage()
    app.dependency_overrides[get_face_photo_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_face_photo_storage, None)


async def run_deletion_worker(
    company_id: UUID,
    provider: Any,
    storage: Any,
    *,
    now: Any = None,
) -> Any:
    """One pass of the post-commit deletion worker (`attendance.run_face_deletions`) for one
    company, with the fake provider / storage injected."""
    from hrms.modules.attendance.face_deletion import process_company

    return await process_company(
        company_id, get_settings(), provider=provider, storage=storage, now=now
    )


@pytest.fixture
async def face_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    """A freshly registered company (admin headers, company id), torn down afterwards."""
    async for value in _face_tenant(client):
        yield value


@pytest.fixture
async def face_tenant_b(
    client: AsyncClient, seeded_plan_catalogue: None, face_tenant: tuple[dict[str, str], UUID]
) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    """A second, independent company alongside `face_tenant` (tenant-isolation tests)."""
    # `_cleanup_scoped_users` deletes every `scoped-%` user in the database, which would fail
    # (FK) while the primary tenant's scoped users still hold a `user_company` row; the primary
    # tenant's teardown runs afterwards and sweeps both tenants' scoped users.
    async for value in _face_tenant(client, sweep_scoped_users=False):
        yield value


async def _face_tenant(
    client: AsyncClient, *, sweep_scoped_users: bool = True
) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    from tests.integration.modules.attendance.test_attendance_day import (
        _cleanup_attendance_day,
        _register_tenant,
    )
    from tests.integration.modules.attendance.test_attendance_security import (
        _cleanup_scoped_users,
    )
    from tests.integration.modules.organisation.test_registration_flow import _cleanup

    headers, company_id, user_id = await _register_tenant(client)
    yield headers, company_id
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "face_verification_comparison",
            "face_shadow_enrollment",
            "face_embedding",
            "face_verification_attempt",
            "face_enrollment_attempt",
            "face_external_deletion",
            "face_liveness_session",
            "employee_face_profile",
            "face_enrollment_window",
            "company_face_policy",
            "notification",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    if sweep_scoped_users:
        await _cleanup_scoped_users()
