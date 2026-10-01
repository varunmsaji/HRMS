from collections.abc import AsyncIterator
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
    LivenessResult,
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


# --- Face attendance (fake provider; nothing here contacts Face++) ---


@dataclass
class FakeFaceProvider:
    provider_name: str = PROVIDER_FACEPP
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail_with: dict[str, Exception] = field(default_factory=dict)
    liveness: LivenessResult = field(
        default_factory=lambda: LivenessResult("LIVE", Decimal("0.9500"), {"result": "real"})
    )
    match: FaceMatchResult = field(
        default_factory=lambda: FaceMatchResult(
            "MATCHED", Decimal("0.9700"), {"message": "verified"}
        )
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
        self._call("verify", person_id=person_id)
        return self.verify_results.pop(0) if self.verify_results else self.match

    async def check_liveness(self, *, image: bytes, content_type: str) -> LivenessResult:
        self._call("check_liveness")
        return self.liveness

    async def delete_person(self, *, person_id: str) -> None:
        self._call("delete_person", person_id=person_id)


@pytest.fixture
async def fake_face_provider() -> AsyncIterator[FakeFaceProvider]:
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


@pytest.fixture
async def face_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    """A freshly registered company (admin headers, company id), torn down afterwards."""
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
            "face_verification_attempt",
            "employee_face_profile",
            "face_enrollment_window",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    await _cleanup_scoped_users()
