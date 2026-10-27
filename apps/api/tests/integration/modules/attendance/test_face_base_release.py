"""Base-release critical fixes for face attendance, end to end (real app, DB, RBAC, Redis;
fake provider / liveness engine / photo storage — nothing here reaches Face++):

* provider and liveness-engine errors never count towards the employee lockout;
* enrollment holds no transaction or row lock across provider calls, and is concurrency-safe
  through a committed reservation (lease);
* nothing external is deleted before the authorising transaction commits; deletions are queued,
  retried, idempotent and never touch a resource a live profile still uses;
* review-photo reads are audited;
* request-level flood limits;
* the ordinary punch endpoint is unchanged (face verification is optional in this release).
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import (
    FakeFaceProvider,
    FakeLivenessEngine,
    FakePhotoStorage,
    run_deletion_worker,
)
from tests.integration.modules.attendance.test_face_enrollment import (
    _employee,
    _open,
    _self_headers,
    _sql,
    _status,
    _submit,
    enroll_and_approve,
)
from tests.integration.modules.attendance.test_face_punch import (
    _attempts,
    _enrolled_self,
    face_punch,
)

from hrms.core.config.settings import get_settings
from hrms.modules.attendance.face_service import FaceEnrollmentService
from hrms.modules.attendance.face_verification import FaceMatchResult, FaceProviderError
from hrms.modules.attendance.liveness import LivenessTimeoutError

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]


@pytest.fixture(autouse=True)
def _photo_storage(fake_photo_storage: FakePhotoStorage) -> None:
    """Enrollment stores a review photo; keep it in memory for every test here."""


# --- B. provider / engine errors are not identity failures ------------------------------------


async def _decisions(company_id: UUID) -> list[str]:
    return [a["decision"] for a in await _attempts(company_id)]


async def test_repeated_provider_errors_never_lock_the_employee_out(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    me, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.fail_with["verify"] = FaceProviderError("down")

    for _ in range(8):  # well past the failed-attempt limit (5)
        response = await face_punch(client, me)
        assert response.status_code == 502, response.text
        assert response.json()["error"]["code"] == "FACE_PROVIDER_FAILED"
        assert "down" not in response.text  # nothing provider-side reaches the client

    # Persisted classification, not just the status code.
    assert await _decisions(company_id) == ["PROVIDER_ERROR"] * 8
    del fake_face_provider.fail_with["verify"]
    assert (await face_punch(client, me)).status_code == 201


async def test_repeated_liveness_engine_errors_never_lock_the_employee_out(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
) -> None:
    _, company_id = face_tenant
    me, _ = await _enrolled_self(client, face_tenant)
    fake_liveness_engine.fail_with = LivenessTimeoutError("slow")

    for _ in range(7):
        assert (await face_punch(client, me)).status_code == 503
    assert await _decisions(company_id) == ["LIVENESS_ERROR"] * 7

    fake_liveness_engine.fail_with = None
    assert (await face_punch(client, me)).status_code == 201


async def test_genuine_negative_matches_still_lock_out_and_infra_errors_do_not_add_to_it(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, company_id = face_tenant
    me, _ = await _enrolled_self(client, face_tenant)

    # Mixed: provider errors in between genuine NO_MATCHes. Only the five NO_MATCH count.
    fake_face_provider.fail_with["verify"] = FaceProviderError("down")
    for _ in range(3):
        assert (await face_punch(client, me)).status_code == 502
    del fake_face_provider.fail_with["verify"]
    fake_face_provider.match = FaceMatchResult("NO_MATCH", None)
    for _ in range(5):
        assert (await face_punch(client, me)).status_code == 422

    blocked = await face_punch(client, me)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "FACE_ATTEMPTS_EXCEEDED"
    assert await _decisions(company_id) == ["PROVIDER_ERROR"] * 3 + ["NO_MATCH"] * 5

    # Lockout expiry: once the genuine failures fall out of the window the employee can retry.
    await _sql(
        company_id,
        "UPDATE face_verification_attempt SET created_at = created_at - interval '11 minutes' "
        "WHERE company_id = :cid",
    )
    fake_face_provider.match = FaceMatchResult("MATCHED", Decimal("0.99"))
    assert (await face_punch(client, me)).status_code == 201


async def test_concurrent_attempts_during_an_outage_are_not_locked_out(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    from tests.integration.modules.attendance.test_face_punch import issue, submit

    _, company_id = face_tenant
    # One challenge per employee at a time, so concurrency is across employees of the tenant.
    people = [(await _enrolled_self(client, face_tenant))[0] for _ in range(4)]
    fake_face_provider.fail_with["verify"] = FaceProviderError("down")
    sessions = [await issue(client, headers) for headers in people]

    results = await asyncio.gather(
        *[submit(client, h, session_id=sid) for h, sid in zip(people, sessions, strict=True)]
    )

    assert [r.status_code for r in results] == [502] * 4
    assert await _decisions(company_id) == ["PROVIDER_ERROR"] * 4
    # ...and the same employees retry freely afterwards.
    del fake_face_provider.fail_with["verify"]
    assert [(await face_punch(client, h)).status_code for h in people] == [201] * 4


async def test_outage_retries_are_still_bounded_by_the_challenge_limit(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """Provider errors are not counted as failures, but every retry needs a new challenge and
    challenges per window are capped, so an outage cannot become an unbounded provider loop."""
    me, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.fail_with["verify"] = FaceProviderError("down")
    limit = get_settings().face_liveness_sessions_per_window

    statuses = [(await face_punch(client, me)).status_code for _ in range(limit + 2)]

    assert statuses[:limit] == [502] * limit
    assert statuses[limit:] == [429, 429]


# --- C. enrollment: no transaction or lock across provider calls ------------------------------


@dataclass
class ProbingProvider(FakeFaceProvider):
    """Fake provider whose every call (a) tries to take the window row lock `NOWAIT` from a
    different connection and (b) looks for sessions left `idle in transaction`, and which can be
    held at `enroll` until the test releases it."""

    company_id: UUID | None = None
    lock_free: list[bool] = field(default_factory=list)
    idle_in_tx: list[int] = field(default_factory=list)
    advisory_locks: list[int] = field(default_factory=list)
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    gate: asyncio.Event | None = None
    verify_delay: float = 0.0
    verify_gate: asyncio.Event | None = None
    verify_entered: asyncio.Event = field(default_factory=asyncio.Event)

    async def _probe(self) -> None:
        from hrms.core.db.session import get_session_factory, set_rls_company_id

        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(self.company_id))
            try:
                await session.execute(
                    text(
                        "SELECT 1 FROM face_enrollment_window "
                        "WHERE company_id = :c FOR UPDATE NOWAIT"
                    ),
                    {"c": str(self.company_id)},
                )
                self.lock_free.append(True)
            except Exception:  # noqa: BLE001 - lock_not_available
                self.lock_free.append(False)
            await session.rollback()
            idle = await session.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND state = 'idle in transaction' AND pid <> pg_backend_pid()"
                )
            )
            self.idle_in_tx.append(int(idle.scalar_one()))
            advisory = await session.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted")
            )
            self.advisory_locks.append(int(advisory.scalar_one()))

    async def enroll(self, *, label: str, image: bytes, content_type: str) -> str:
        await self._probe()
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        return await super().enroll(label=label, image=image, content_type=content_type)

    async def verify(self, *, person_id: str, image: bytes, content_type: str) -> FaceMatchResult:
        await self._probe()
        self.verify_entered.set()
        if self.verify_gate is not None:
            await self.verify_gate.wait()
        if self.verify_delay:
            await asyncio.sleep(self.verify_delay)
        return await super().verify(person_id=person_id, image=image, content_type=content_type)


@pytest.fixture
async def probing_provider(
    fake_liveness_engine: FakeLivenessEngine, face_tenant: Tenant
) -> AsyncIterator[ProbingProvider]:
    from entrypoints.api import app

    from hrms.modules.attendance.dependencies import get_face_provider

    provider = ProbingProvider(company_id=face_tenant[1])
    app.dependency_overrides[get_face_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_face_provider, None)


async def _enrolling(
    client: AsyncClient, face_tenant: Tenant
) -> tuple[dict[str, str], dict[str, str], str, UUID]:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    assert (await _open(client, admin, employee_id)).status_code == 201
    return admin, await _self_headers(company_id, employee_id), employee_id, company_id


async def test_no_row_lock_or_open_transaction_is_held_across_provider_calls(
    client: AsyncClient, face_tenant: Tenant, probing_provider: ProbingProvider
) -> None:
    _, me, _, _ = await _enrolling(client, face_tenant)

    response = await _submit(client, me)

    assert response.status_code == 201, response.text
    # enroll + 4 verify were probed: every time the window row was lockable by another
    # connection (no FOR UPDATE held), and no enrollment session sat idle in a transaction.
    assert len(probing_provider.lock_free) == 5
    assert all(probing_provider.lock_free)
    assert probing_provider.idle_in_tx == [0] * 5


async def test_a_punch_holds_no_connection_or_advisory_lock_across_provider_calls(
    client: AsyncClient,
    face_tenant: Tenant,
    probing_provider: ProbingProvider,
) -> None:
    me, _ = await _enrolled_self(client, face_tenant)
    probing_provider.lock_free.clear()
    probing_provider.idle_in_tx.clear()
    probing_provider.advisory_locks.clear()

    response = await face_punch(client, me, key="k" * 20)

    assert response.status_code == 201, response.text
    assert len(probing_provider.idle_in_tx) == 3  # one verify per frame
    assert probing_provider.idle_in_tx == [0, 0, 0]
    assert probing_provider.advisory_locks == [0, 0, 0]


async def test_duplicate_of_an_in_flight_punch_waits_and_gets_the_original_result(
    client: AsyncClient, face_tenant: Tenant, probing_provider: ProbingProvider
) -> None:
    from tests.integration.modules.attendance.test_face_punch import issue, submit

    me, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, me)
    verifies_before = probing_provider.names().count("verify")
    probing_provider.verify_entered.clear()
    probing_provider.verify_gate = asyncio.Event()
    key = "dup-key-" + "x" * 12

    original = asyncio.create_task(submit(client, me, session_id=session_id, key=key))
    await asyncio.wait_for(probing_provider.verify_entered.wait(), 5)
    duplicate = asyncio.create_task(submit(client, me, session_id=session_id, key=key))
    await asyncio.sleep(0.3)
    assert not duplicate.done()  # waiting for the original
    # ...and while it waits it holds no connection and no advisory lock. Probed from another
    # connection several times (the poll itself briefly opens short transactions, so "never
    # observed 0" is the failure signal: the old design held one continuously).
    probing_provider.idle_in_tx.clear()
    probing_provider.advisory_locks.clear()
    for _ in range(6):
        await probing_provider._probe()
        await asyncio.sleep(0.1)
    assert min(probing_provider.idle_in_tx) == 0
    assert min(probing_provider.advisory_locks) == 0
    assert not duplicate.done()
    probing_provider.verify_gate.set()
    first, second = await asyncio.gather(original, duplicate)

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["data"]["punch"]["id"] == second.json()["data"]["punch"]["id"]
    # The original's three frames only: the duplicate did no provider work of its own.
    assert probing_provider.names().count("verify") - verifies_before == 3


async def test_duplicate_of_a_rejected_in_flight_punch_does_not_wait_out_the_window(
    client: AsyncClient, face_tenant: Tenant, probing_provider: ProbingProvider
) -> None:
    from tests.integration.modules.attendance.test_face_punch import issue, submit

    me, _ = await _enrolled_self(client, face_tenant)
    session_id = await issue(client, me)
    probing_provider.match = FaceMatchResult("NO_MATCH", None)
    probing_provider.verify_entered.clear()
    probing_provider.verify_gate = asyncio.Event()
    key = "dup-key-" + "y" * 12

    original = asyncio.create_task(submit(client, me, session_id=session_id, key=key))
    await asyncio.wait_for(probing_provider.verify_entered.wait(), 5)
    duplicate = asyncio.create_task(submit(client, me, session_id=session_id, key=key))
    await asyncio.sleep(0.3)
    probing_provider.verify_gate.set()
    first = await original
    second = await asyncio.wait_for(duplicate, 10)  # not the multi-second wait window

    assert first.status_code == 422
    assert second.status_code == 409  # the challenge is spent, as for any duplicate of a failure


async def test_second_submission_during_provider_work_is_refused_and_only_one_enrolls(
    client: AsyncClient, face_tenant: Tenant, probing_provider: ProbingProvider
) -> None:
    admin, me, employee_id, company_id = await _enrolling(client, face_tenant)
    probing_provider.gate = asyncio.Event()

    first = asyncio.create_task(_submit(client, me))
    await asyncio.wait_for(probing_provider.entered.wait(), 5)
    second = await _submit(client, me)
    probing_provider.gate.set()
    first_response = await first

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "FACE_ENROLLMENT_IN_PROGRESS"
    assert first_response.status_code == 201, first_response.text
    assert probing_provider.names().count("enroll") == 1
    assert await _sql(company_id, "SELECT count(*) FROM employee_face_profile") == [(1,)]
    window = (
        await _sql(company_id, "SELECT status, submission_token FROM face_enrollment_window")
    )[0]
    assert tuple(window) == ("USED", None)


async def test_window_cancelled_during_provider_work_discards_the_provider_person(
    client: AsyncClient,
    face_tenant: Tenant,
    probing_provider: ProbingProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, me, employee_id, company_id = await _enrolling(client, face_tenant)
    probing_provider.gate = asyncio.Event()

    first = asyncio.create_task(_submit(client, me))
    await asyncio.wait_for(probing_provider.entered.wait(), 5)
    cancelled = await client.delete(
        f"/v1/attendance/face-profiles/{employee_id}/enrollment-window", headers=admin
    )
    probing_provider.gate.set()
    response = await first

    assert cancelled.status_code in (200, 204)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FACE_ENROLLMENT_NOT_OPEN"
    # Compensated: the FaceSet created meanwhile is deleted, the photo is gone, no profile.
    assert "delete_person" in probing_provider.names()
    assert fake_photo_storage.objects == {}
    assert await _sql(company_id, "SELECT count(*) FROM employee_face_profile") == [(0,)]


async def test_window_reopened_during_provider_work_does_not_let_the_old_submission_win(
    client: AsyncClient, face_tenant: Tenant, probing_provider: ProbingProvider
) -> None:
    admin, me, employee_id, company_id = await _enrolling(client, face_tenant)
    probing_provider.gate = asyncio.Event()

    first = asyncio.create_task(_submit(client, me))
    await asyncio.wait_for(probing_provider.entered.wait(), 5)
    assert (await _open(client, admin, employee_id)).status_code == 201  # supersedes the window
    probing_provider.gate.set()
    stale = await first

    assert stale.status_code == 409
    assert await _sql(company_id, "SELECT count(*) FROM employee_face_profile") == [(0,)]
    # The new window is intact and usable.
    probing_provider.gate = None
    assert (await _submit(client, me)).status_code == 201


async def test_provider_budget_exceeded_compensates_and_releases_the_reservation(
    client: AsyncClient,
    face_tenant: Tenant,
    probing_provider: ProbingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    monkeypatch.setattr(get_settings(), "face_enrollment_provider_budget_seconds", 0.3)
    probing_provider.verify_delay = 2.0

    slow = await _submit(client, me)

    assert slow.status_code == 502
    assert slow.json()["error"]["code"] == "FACE_PROVIDER_FAILED"
    assert "delete_person" in probing_provider.names()
    rows = await _sql(company_id, "SELECT decision FROM face_enrollment_attempt")
    assert [r[0] for r in rows] == ["PROVIDER_ERROR"]
    window = (
        await _sql(company_id, "SELECT status, submission_token FROM face_enrollment_window")
    )[0]
    assert tuple(window) == ("OPEN", None)  # not stuck: reservation released
    # Not counted against the employee: a retry with a healthy provider works.
    probing_provider.verify_delay = 0
    assert (await _submit(client, me)).status_code == 201


async def test_stale_reservation_from_a_crashed_worker_does_not_wedge_the_employee(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    await _sql(
        company_id,
        "UPDATE face_enrollment_window SET submission_token = gen_random_uuid(), "
        "submission_started_at = now() - interval '1 hour'",
    )

    assert (await _submit(client, me)).status_code == 201

    # ...whereas a fresh reservation does block.


async def test_fresh_reservation_blocks_a_second_submission(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    await _sql(
        company_id,
        "UPDATE face_enrollment_window SET submission_token = gen_random_uuid(), "
        "submission_started_at = now()",
    )

    blocked = await _submit(client, me)

    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "FACE_ENROLLMENT_IN_PROGRESS"
    assert fake_face_provider.calls == []


async def test_failed_finalize_compensates_then_retry_succeeds(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    original = FaceEnrollmentService._write_submission

    async def failing(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database went away")

    monkeypatch.setattr(FaceEnrollmentService, "_write_submission", failing)
    assert (await _submit(client, me)).status_code == 500
    monkeypatch.setattr(FaceEnrollmentService, "_write_submission", original)

    assert fake_face_provider.names().count("delete_person") == 1
    assert fake_photo_storage.objects == {}
    assert await _sql(company_id, "SELECT count(*) FROM employee_face_profile") == [(0,)]
    window = (
        await _sql(company_id, "SELECT status, submission_token FROM face_enrollment_window")
    )[0]
    assert tuple(window) == ("OPEN", None)

    assert (await _submit(client, me)).status_code == 201


async def test_compensation_that_cannot_reach_the_provider_is_queued_and_reconciled(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)

    async def failing(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database went away")

    monkeypatch.setattr(FaceEnrollmentService, "_write_submission", failing)
    fake_face_provider.fail_with["delete_person"] = FaceProviderError("down")
    assert (await _submit(client, me)).status_code == 500

    pending = await _sql(
        company_id, "SELECT kind, status FROM face_external_deletion ORDER BY kind"
    )
    assert [tuple(r) for r in pending] == [("PROVIDER_PERSON", "PENDING")]
    del fake_face_provider.fail_with["delete_person"]
    report = await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)
    assert (report.done, report.failed) == (1, 0)
    assert fake_face_provider.names().count("delete_person") == 2


async def test_crashed_enrollment_orphan_is_reaped_after_the_lease_but_a_live_one_is_not(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)
    (live_person,) = (
        await _sql(company_id, "SELECT provider_person_id FROM employee_face_profile")
    )[0]
    # A FaceSet some earlier process created and then died before recording any profile.
    orphan = f"orphan-{uuid4()}"
    await _sql(
        company_id,
        "INSERT INTO face_external_deletion (company_id, kind, provider, resource_ref, reason, "
        "next_attempt_at) VALUES (:cid, 'PROVIDER_PERSON', 'FACEPP', '" + orphan + "', "
        "'ENROLLMENT_COMPENSATION', now() + interval '4 minutes')",
    )

    # Before the lease has lapsed nothing is touched.
    early = await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)
    assert early.claimed <= 1  # only the approval's photo row
    assert "delete_person" not in fake_face_provider.names()

    later = await run_deletion_worker(
        company_id,
        fake_face_provider,
        fake_photo_storage,
        now=datetime.now(UTC) + timedelta(minutes=10),
    )

    deleted = [kw["person_id"] for name, kw in fake_face_provider.calls if name == "delete_person"]
    assert deleted == [orphan]  # the orphan only
    assert later.skipped_in_use == 1  # the enrolment's own guard row, whose person is in use
    assert live_person not in deleted


async def test_queued_deletion_never_deletes_a_resource_a_live_profile_uses(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)
    await _sql(company_id, "UPDATE face_external_deletion SET next_attempt_at = now()")

    report = await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)

    assert report.skipped_in_use >= 1
    assert "delete_person" not in fake_face_provider.names()
    # And if the profile is later revoked, the earlier SKIPPED row is re-armed, not swallowed.
    assert (
        await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)
    ).status_code == 200
    again = await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)
    assert again.done == 1
    assert fake_face_provider.names().count("delete_person") == 1


# --- D. nothing external before commit; races; duplicate workers ------------------------------


async def _pending_profile(
    client: AsyncClient, face_tenant: Tenant
) -> tuple[dict[str, str], str, UUID]:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    assert (await _open(client, admin, employee_id)).status_code == 201
    assert (await _submit(client, await _self_headers(company_id, employee_id))).status_code == 201
    return admin, employee_id, company_id


async def _outbox_count(company_id: UUID) -> int:
    return int((await _sql(company_id, "SELECT count(*) FROM face_external_deletion"))[0][0])


@pytest.mark.parametrize("action", ["approve", "reject", "revoke"])
async def test_a_failed_commit_leaves_local_state_and_external_resources_untouched(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    admin, employee_id, company_id = await _pending_profile(client, face_tenant)
    if action == "revoke":
        assert (
            await client.post(f"/v1/attendance/face-profiles/{employee_id}/approve", headers=admin)
        ).status_code == 200
        await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)
    calls_before = len(fake_face_provider.calls)
    photos_before = dict(fake_photo_storage.objects)
    status_before = (await _status(client, admin, employee_id))["profile"]["status"]
    outbox_before = await _outbox_count(company_id)

    async def failing(self: Any, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(FaceEnrollmentService, "_audit_profile", failing)
    if action == "revoke":
        failed = await client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin)
    else:
        failed = await client.post(
            f"/v1/attendance/face-profiles/{employee_id}/{action}", headers=admin, json={}
        )
    assert failed.status_code == 500
    monkeypatch.undo()

    # The transaction rolled back: same status, no new outbox rows, and nothing external touched.
    assert (await _status(client, admin, employee_id))["profile"]["status"] == status_before
    assert len(fake_face_provider.calls) == calls_before
    assert fake_photo_storage.objects == photos_before
    assert await _outbox_count(company_id) == outbox_before


async def test_concurrent_approve_and_reject_have_exactly_one_winner(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, employee_id, company_id = await _pending_profile(client, face_tenant)

    approve, reject = await asyncio.gather(
        client.post(f"/v1/attendance/face-profiles/{employee_id}/approve", headers=admin),
        client.post(f"/v1/attendance/face-profiles/{employee_id}/reject", headers=admin, json={}),
    )

    assert sorted([approve.status_code, reject.status_code]) == [200, 409]
    final = (await _status(client, admin, employee_id))["profile"]["status"]
    assert final == ("ENROLLED" if approve.status_code == 200 else "REJECTED")
    # Even long after the guard lease, the deletion worker honours the winner.
    await run_deletion_worker(
        company_id,
        fake_face_provider,
        fake_photo_storage,
        now=datetime.now(UTC) + timedelta(hours=1),
    )
    deleted_a_person = "delete_person" in fake_face_provider.names()
    assert deleted_a_person == (final == "REJECTED")
    assert fake_photo_storage.objects == {}


async def test_concurrent_revokes_queue_one_deletion(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, company_id = face_tenant
    employee_id = await _employee(client, admin)
    await enroll_and_approve(client, admin, company_id, employee_id)

    a, b = await asyncio.gather(
        client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin),
        client.delete(f"/v1/attendance/face-profiles/{employee_id}", headers=admin),
    )

    assert sorted([a.status_code, b.status_code]) == [200, 409]
    await run_deletion_worker(company_id, fake_face_provider, fake_photo_storage)
    assert fake_face_provider.names().count("delete_person") == 1


async def test_overlapping_workers_do_not_delete_twice(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, employee_id, company_id = await _pending_profile(client, face_tenant)
    assert (
        await client.post(
            f"/v1/attendance/face-profiles/{employee_id}/reject", headers=admin, json={}
        )
    ).status_code == 200

    reports = await asyncio.gather(
        *[run_deletion_worker(company_id, fake_face_provider, fake_photo_storage) for _ in range(4)]
    )

    assert sum(r.done for r in reports) == 2  # the FaceSet and the review photo, once each
    assert fake_face_provider.names().count("delete_person") == 1
    assert fake_photo_storage.objects == {}


async def test_disabled_provider_defers_person_deletions_instead_of_losing_them(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, employee_id, company_id = await _pending_profile(client, face_tenant)
    await client.post(f"/v1/attendance/face-profiles/{employee_id}/reject", headers=admin, json={})

    report = await run_deletion_worker(company_id, None, fake_photo_storage)

    assert (report.deferred, report.done) == (1, 1)  # person deferred, photo deleted
    row = (
        await _sql(
            company_id,
            "SELECT status, last_error_code FROM face_external_deletion "
            "WHERE kind = 'PROVIDER_PERSON'",
        )
    )[0]
    assert tuple(row) == ("PENDING", "PROVIDER_NOT_CONFIGURED")


# --- G. review photo access is audited --------------------------------------------------------


async def _photo_audit(company_id: UUID) -> list[dict[str, Any]]:
    rows = await _sql(
        company_id,
        "SELECT actor_user_id, entity_id, request_id, after_json::text AS after "
        "FROM audit_log WHERE company_id = :cid AND action = 'FACE_REVIEW_PHOTO_VIEWED'",
    )
    return [dict(r._mapping) for r in rows]


async def test_review_photo_read_is_audited_without_any_image_content(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import base64

    from tests.integration.modules.attendance.test_face_enrollment import IMAGES

    admin, employee_id, company_id = await _pending_profile(client, face_tenant)
    capsys.readouterr()

    response = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/review-photo", headers=admin
    )

    assert response.status_code == 200
    (row,) = await _photo_audit(company_id)
    profile_id = (await _sql(company_id, "SELECT id FROM employee_face_profile"))[0][0]
    assert row["entity_id"] == profile_id
    assert row["actor_user_id"] is not None
    assert row["request_id"]
    assert "outcome" in row["after"] and "SERVED" in row["after"]
    assert "front" not in row["after"] and "xff" not in row["after"].lower()
    # Nothing the request logged contains the image in any encoding.
    out = capsys.readouterr().out
    photo = IMAGES["front"]
    for needle in (photo.hex(), base64.b64encode(photo).decode(), repr(photo), "/9j/"):
        assert needle not in out
    # The only trace is the application's slim audit event: identifiers, no payload fields.
    (event,) = [line for line in out.splitlines() if "FACE_REVIEW_PHOTO_VIEWED" in line]
    assert '"event": "business.audit_recorded"' in event
    assert "review_photo_key" not in event and "face-review/" not in event


async def test_refused_or_failed_review_photo_reads_leave_no_access_record(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    admin, employee_id, company_id = await _pending_profile(client, face_tenant)
    me = await _self_headers(company_id, employee_id)

    # No manage permission (the employee themself): refused, nothing recorded.
    denied = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/review-photo", headers=me
    )
    assert denied.status_code == 403
    # Photo missing from storage: the read fails, so nothing was served and nothing is recorded.
    fake_photo_storage.objects.clear()
    missing = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/review-photo", headers=admin
    )
    assert missing.status_code == 500
    # After HR decides there is no photo any more.
    await client.post(f"/v1/attendance/face-profiles/{employee_id}/reject", headers=admin, json={})
    gone = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/review-photo", headers=admin
    )
    assert gone.status_code == 404

    assert await _photo_audit(company_id) == []


async def test_review_photo_of_another_tenants_employee_is_not_found_and_not_audited(
    client: AsyncClient,
    face_tenant: Tenant,
    face_tenant_b: Tenant,
    fake_face_provider: FakeFaceProvider,
) -> None:
    _, employee_id, company_a = await _pending_profile(client, face_tenant)
    admin_b, company_b = face_tenant_b

    response = await client.get(
        f"/v1/attendance/face-profiles/{employee_id}/review-photo", headers=admin_b
    )

    assert response.status_code == 404
    assert await _photo_audit(company_a) == []
    assert await _photo_audit(company_b) == []


# --- F. request-level flood limits ------------------------------------------------------------


@pytest.fixture
async def clean_face_buckets() -> AsyncIterator[None]:
    async def _clear() -> None:
        client = redis.from_url(get_settings().redis_url, decode_responses=True)
        async for key in client.scan_iter("ratelimit:face_*"):
            await client.delete(key)
        await client.aclose()

    await _clear()
    yield
    await _clear()


async def test_punch_endpoints_have_a_per_tenant_per_ip_flood_limit(
    client: AsyncClient,
    face_tenant: Tenant,
    face_tenant_b: Tenant,
    fake_face_provider: FakeFaceProvider,
    clean_face_buckets: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "face_punch_requests_per_minute_per_ip", 3)
    me, _ = await _enrolled_self(client, face_tenant)
    other, _ = await _enrolled_self(client, face_tenant_b)
    spoofed = {"X-Forwarded-For": "203.0.113.9"}

    codes = []
    for i in range(5):
        # A client-chosen X-Forwarded-For must not select a different bucket: the peer is not a
        # trusted proxy, so the header is ignored.
        headers = {**me, "X-Forwarded-For": f"203.0.113.{i}"} if i % 2 else {**me, **spoofed}
        response = await client.post(
            "/v1/attendance/face-punches/me/liveness-sessions",
            headers=headers,
            json={"direction": "IN"},
        )
        codes.append(response.status_code)

    assert codes == [201, 201, 201, 429, 429]
    # The limit is per tenant: another company on the same address is unaffected.
    assert (
        await client.post(
            "/v1/attendance/face-punches/me/liveness-sessions",
            headers=other,
            json={"direction": "IN"},
        )
    ).status_code == 201


async def test_enrollment_and_review_photo_have_flood_limits(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    clean_face_buckets: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "face_enrollment_requests_per_minute_per_ip", 2)
    monkeypatch.setattr(get_settings(), "face_review_photo_requests_per_minute_per_ip", 2)
    admin, me, employee_id, _ = await _enrolling(client, face_tenant)

    consent_missing = [(await _submit(client, me, consent="false")).status_code for _ in range(3)]
    photos = [
        (
            await client.get(
                f"/v1/attendance/face-profiles/{employee_id}/review-photo", headers=admin
            )
        ).status_code
        for _ in range(3)
    ]

    assert consent_missing == [422, 422, 429]
    assert photos == [404, 404, 429]


async def test_rate_limited_requests_do_no_provider_work(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    clean_face_buckets: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me, _ = await _enrolled_self(client, face_tenant)
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()
    monkeypatch.setattr(get_settings(), "face_punch_requests_per_minute_per_ip", 1)
    first = await face_punch(client, me)  # challenge consumes the single allowed request
    assert first.status_code == 201 or first.status_code == 429

    blocked = await face_punch(client, me)

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert fake_face_provider.calls == []


# --- H. attendance policy: face verification is MANDATORY once ENROLLED ------------------------


async def test_plain_punch_is_refused_for_a_face_enrolled_employee(
    client: AsyncClient, face_tenant: Tenant, fake_face_provider: FakeFaceProvider
) -> None:
    """An ENROLLED employee can only self-punch through `POST /attendance/face-punches/me`;
    `POST /attendance/punches/me` is a 403 for both directions and writes nothing."""
    me, _ = await _enrolled_self(client, face_tenant)

    for direction in ("IN", "OUT"):
        plain = await client.post(
            "/v1/attendance/punches/me", headers=me, json={"direction": direction}
        )
        assert plain.status_code == 403, plain.text
        assert plain.json()["error"]["code"] == "FACE_VERIFICATION_REQUIRED"
    face = await face_punch(client, me, "OUT")

    assert face.status_code == 201, face.text
    punches = (await client.get("/v1/attendance/punches", headers=me)).json()["data"]
    assert [p["source"] for p in punches] == ["FACE"]


# --- lifecycle: client disconnect, worker crash, stuck deletions, trusted proxy ----------------


async def test_client_disconnect_mid_enrollment_compensates_and_releases_the_reservation(
    client: AsyncClient,
    face_tenant: Tenant,
    probing_provider: ProbingProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    _, me, _, company_id = await _enrolling(client, face_tenant)
    probing_provider.verify_gate = asyncio.Event()

    task = asyncio.create_task(_submit(client, me))
    await asyncio.wait_for(probing_provider.verify_entered.wait(), 5)  # FaceSet exists by now
    task.cancel()  # the phone went away
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "delete_person" in probing_provider.names()  # the FaceSet was removed
    assert fake_photo_storage.objects == {}
    assert await _sql(company_id, "SELECT count(*) FROM employee_face_profile") == [(0,)]
    window = (
        await _sql(company_id, "SELECT status, submission_token FROM face_enrollment_window")
    )[0]
    assert tuple(window) == ("OPEN", None)  # released at once, not left to lapse
    probing_provider.verify_gate.set()
    assert (await _submit(client, me)).status_code == 201  # and the employee can simply retry


async def test_rows_claimed_by_a_crashed_worker_come_back_after_the_lease(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
) -> None:
    from hrms.core.db.session import session_scope
    from hrms.modules.attendance.repository import FaceExternalDeletionRepository

    admin, employee_id, company_id = await _pending_profile(client, face_tenant)
    await client.post(f"/v1/attendance/face-profiles/{employee_id}/reject", headers=admin, json={})
    now = datetime.now(UTC)

    # A worker claims the rows and dies before doing anything (the claim has committed).
    async with session_scope(company_id=str(company_id)) as session:
        claimed = await FaceExternalDeletionRepository().claim_due(
            session, company_id=company_id, now=now, limit=50, lease=timedelta(minutes=10)
        )
    assert len(claimed) == 2

    soon = await run_deletion_worker(
        company_id, fake_face_provider, fake_photo_storage, now=now + timedelta(minutes=1)
    )
    assert soon.claimed == 0  # still leased: nothing is deleted twice or in parallel
    later = await run_deletion_worker(
        company_id, fake_face_provider, fake_photo_storage, now=now + timedelta(minutes=11)
    )
    assert (later.claimed, later.done) == (2, 2)
    assert fake_face_provider.names().count("delete_person") == 1
    attempts = await _sql(company_id, "SELECT attempts FROM face_external_deletion ORDER BY kind")
    assert [r[0] for r in attempts] == [2, 2]


async def test_a_persistently_failing_deletion_escalates_to_an_error_log_and_report(
    client: AsyncClient,
    face_tenant: Tenant,
    fake_face_provider: FakeFaceProvider,
    fake_photo_storage: FakePhotoStorage,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, employee_id, company_id = await _pending_profile(client, face_tenant)
    await client.post(f"/v1/attendance/face-profiles/{employee_id}/reject", headers=admin, json={})
    fake_face_provider.fail_with["delete_person"] = FaceProviderError("down")
    threshold = get_settings().face_deletion_alert_after_attempts
    base = datetime.now(UTC)
    capsys.readouterr()

    reports = [
        await run_deletion_worker(
            company_id,
            fake_face_provider,
            fake_photo_storage,
            now=base + timedelta(hours=3 * (i + 1)),
        )
        for i in range(threshold)
    ]

    assert [r.persistently_failing for r in reports] == [0] * (threshold - 1) + [1]
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if '"event": "face_deletion_failed"' in line
    ]
    assert len(lines) == threshold
    assert all('"level": "warning"' in line for line in lines[:-1])
    assert '"level": "error"' in lines[-1]  # what the monitor's face_deletion_stuck matches
    assert "down" not in "".join(lines) and "FaceProviderError" in lines[-1]


async def test_face_flood_limit_keys_on_the_real_client_only_behind_a_trusted_proxy(
    clean_face_buckets: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    from hrms.core.config.settings import Settings
    from hrms.core.errors.handlers import register_exception_handlers
    from hrms.core.tenancy.context import TenantContext
    from hrms.core.tenancy.dependencies import get_tenant_context
    from hrms.modules.attendance.face_rate_limit import face_punch_rate_limit

    monkeypatch.setattr(get_settings(), "face_punch_requests_per_minute_per_ip", 1)
    tenant = TenantContext(company_id=uuid4(), user_id=uuid4())

    def build(settings: Settings) -> FastAPI:
        app = FastAPI()
        register_exception_handlers(app)
        app.dependency_overrides[get_tenant_context] = lambda: tenant
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=list(settings.trusted_proxy_hosts))

        @app.get("/probe")
        async def probe(_rl: None = Depends(face_punch_rate_limit)) -> dict[str, bool]:
            return {"ok": True}

        return app

    async def hit(app: FastAPI, peer: str, forwarded_for: str) -> int:
        transport = ASGITransport(app=app, client=(peer, 40000))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            return (await c.get("/probe", headers={"X-Forwarded-For": forwarded_for})).status_code

    # Trusted proxy: two real clients behind it are separate buckets; the same client repeats.
    trusted = build(Settings(environment="development", trusted_proxy_hosts=("10.0.0.5",)))
    assert await hit(trusted, "10.0.0.5", "198.51.100.1") == 200
    assert await hit(trusted, "10.0.0.5", "198.51.100.2") == 200
    assert await hit(trusted, "10.0.0.5", "198.51.100.1") == 429

    # Untrusted peer: the forged header is ignored, so changing it buys no fresh bucket.
    untrusted = build(Settings(environment="development", trusted_proxy_hosts=("10.0.0.5",)))
    assert await hit(untrusted, "10.0.0.77", "203.0.113.1") == 200
    assert await hit(untrusted, "10.0.0.77", "203.0.113.2") == 429
    assert await hit(untrusted, "10.0.0.77", "203.0.113.3") == 429
