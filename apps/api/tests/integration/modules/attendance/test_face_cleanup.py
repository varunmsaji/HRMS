"""Retention cleanup of face records (`attendance/face_cleanup.py`) against the real database and
row-level security. No retention period is defaulted in production; every period here is set
explicitly by the test."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import FakeFaceProvider, FakePhotoStorage
from tests.integration.modules.attendance.test_face_enrollment import _employee
from tests.integration.modules.attendance.test_face_punch import (
    _enrolled_self,
    _punch_count,
    face_punch,
)

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.face_cleanup import cleanup_company, retention_configured

pytestmark = pytest.mark.asyncio

Tenant = tuple[dict[str, str], UUID]
OLD = timedelta(days=400)
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _fakes(fake_photo_storage: FakePhotoStorage, fake_face_provider: FakeFaceProvider) -> None:
    """Employee/enrollment helpers need a configured (fake) provider and in-memory storage."""


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "face_liveness_session_retention_days": 90,
        "face_attempt_detail_retention_days": 180,
        "face_enrollment_attempt_retention_days": 90,
        "face_cleanup_dry_run": False,
    }
    return get_settings().model_copy(update={**base, **overrides})


async def _sql(company_id: UUID, query: str, **params: Any) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(text(query), {"cid": company_id, **params})
        rows = [dict(r._mapping) for r in result] if result.returns_rows else []
        await session.commit()
        return rows


async def _seed_session(
    company_id: UUID,
    employee_id: str,
    *,
    age: timedelta,
    status: str = "CONSUMED",
    expires_in: timedelta | None = None,
) -> UUID:
    session_id = uuid4()
    created = NOW - age
    expires = created + timedelta(seconds=120) if expires_in is None else NOW + expires_in
    await _sql(
        company_id,
        "INSERT INTO face_liveness_session (id, company_id, employee_id, direction, status, "
        "issued_at, expires_at, consumed_at, frame_digests, created_at, updated_at) VALUES "
        "(:id, :cid, :eid, 'IN', :status, :issued, :expires, :consumed, "
        "ARRAY['digest-marker-1','digest-marker-2'], :created, :created)",
        id=session_id,
        eid=UUID(employee_id),
        status=status,
        issued=created,
        expires=expires,
        consumed=created if status == "CONSUMED" else None,
        created=created,
    )
    return session_id


async def _seed_attempt(
    company_id: UUID, employee_id: str, *, age: timedelta, decision: str = "NO_MATCH"
) -> UUID:
    attempt_id = uuid4()
    await _sql(
        company_id,
        "INSERT INTO face_verification_attempt (id, company_id, employee_id, provider, "
        "provider_person_id, decision, similarity, liveness_score, provider_response, created_at) "
        "VALUES (:id, :cid, :eid, 'FACEPP', 'fs_person', :decision, 0.5, 0.9, "
        'CAST(\'{"identity":{"frames":[]}}\' AS jsonb), :created)',
        id=attempt_id,
        eid=UUID(employee_id),
        decision=decision,
        created=NOW - age,
    )
    return attempt_id


async def _seed_enrollment_attempt(company_id: UUID, employee_id: str, *, age: timedelta) -> UUID:
    attempt_id = uuid4()
    await _sql(
        company_id,
        "INSERT INTO face_enrollment_attempt (id, company_id, employee_id, "
        "enrollment_window_id, decision, angle, created_at) VALUES "
        "(:id, :cid, :eid, :wid, 'SPOOF_SUSPECTED', 'front', :created)",
        id=attempt_id,
        eid=UUID(employee_id),
        wid=uuid4(),
        created=NOW - age,
    )
    return attempt_id


async def _count(company_id: UUID, table: str) -> int:
    return int(
        (await _sql(company_id, f"SELECT count(*) AS n FROM {table} WHERE company_id = :cid"))[0][
            "n"
        ]
    )


async def test_nothing_is_configured_by_default() -> None:
    settings = get_settings()
    assert retention_configured(settings) is False
    assert settings.face_cleanup_dry_run is True
    assert settings.face_liveness_session_retention_days is None
    assert settings.face_attempt_detail_retention_days is None
    assert settings.face_enrollment_attempt_retention_days is None


async def test_unset_periods_delete_nothing_even_when_not_a_dry_run(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    employee = await _employee(client, admin)
    await _seed_session(company_id, employee, age=OLD)
    await _seed_attempt(company_id, employee, age=OLD)
    await _seed_enrollment_attempt(company_id, employee, age=OLD)
    unset = get_settings().model_copy(update={"face_cleanup_dry_run": False})

    report = await cleanup_company(company_id, unset, now=NOW)

    assert (report.liveness_sessions, report.attempt_details_erased) == (0, 0)
    assert report.enrollment_attempts == 0
    assert await _count(company_id, "face_liveness_session") == 1
    assert await _count(company_id, "face_enrollment_attempt") == 1
    assert (await _sql(company_id, "SELECT provider_response FROM face_verification_attempt"))[0][
        "provider_response"
    ] is not None


async def test_dry_run_reports_and_changes_nothing(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    employee = await _employee(client, admin)
    await _seed_session(company_id, employee, age=OLD)
    await _seed_attempt(company_id, employee, age=OLD)
    await _seed_enrollment_attempt(company_id, employee, age=OLD)

    report = await cleanup_company(company_id, _settings(face_cleanup_dry_run=True), now=NOW)

    assert report.dry_run is True
    assert (report.liveness_sessions, report.attempt_details_erased) == (1, 1)
    assert report.enrollment_attempts == 1
    assert await _count(company_id, "face_liveness_session") == 1
    assert await _count(company_id, "face_enrollment_attempt") == 1
    assert (await _sql(company_id, "SELECT provider_person_id FROM face_verification_attempt"))[0][
        "provider_person_id"
    ] == "fs_person"


async def test_apply_removes_only_expired_records_and_is_idempotent(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    employee = await _employee(client, admin)
    old_session = await _seed_session(company_id, employee, age=OLD)
    old_superseded = await _seed_session(company_id, employee, age=OLD, status="SUPERSEDED")
    recent_session = await _seed_session(company_id, employee, age=timedelta(days=1))
    # Old by creation date but still ISSUED and unexpired: an active challenge, never deleted.
    active = await _seed_session(
        company_id, employee, age=OLD, status="ISSUED", expires_in=timedelta(seconds=60)
    )
    old_attempt = await _seed_attempt(company_id, employee, age=OLD)
    recent_attempt = await _seed_attempt(company_id, employee, age=timedelta(days=1))
    await _seed_enrollment_attempt(company_id, employee, age=OLD)
    await _seed_enrollment_attempt(company_id, employee, age=timedelta(days=1))

    first = await cleanup_company(company_id, _settings(), now=NOW)
    second = await cleanup_company(company_id, _settings(), now=NOW)

    assert (first.liveness_sessions, first.attempt_details_erased) == (2, 1)
    assert first.enrollment_attempts == 1
    assert not first.truncated
    # Re-running finds nothing left to do.
    assert (second.liveness_sessions, second.attempt_details_erased) == (0, 0)
    assert second.enrollment_attempts == 0
    remaining = {r["id"] for r in await _sql(company_id, "SELECT id FROM face_liveness_session")}
    assert remaining == {recent_session, active}
    assert old_session not in remaining and old_superseded not in remaining
    assert await _count(company_id, "face_enrollment_attempt") == 1

    rows = {
        r["id"]: r
        for r in await _sql(
            company_id,
            "SELECT id, decision, similarity, liveness_score, provider_response, "
            "provider_person_id FROM face_verification_attempt",
        )
    }
    # The audit row survives with its outcome; only the free-form detail is erased.
    assert rows[old_attempt]["provider_response"] is None
    assert rows[old_attempt]["provider_person_id"] is None
    assert rows[old_attempt]["decision"] == "NO_MATCH"
    assert str(rows[old_attempt]["similarity"]) == "0.5000"
    assert rows[recent_attempt]["provider_response"] is not None
    assert rows[recent_attempt]["provider_person_id"] == "fs_person"


async def test_batches_are_bounded_and_a_later_run_continues(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    admin, company_id = face_tenant
    employee = await _employee(client, admin)
    for _ in range(7):
        await _seed_session(company_id, employee, age=OLD)
    bounded = _settings(face_cleanup_batch_size=2, face_cleanup_max_batches=2)

    first = await cleanup_company(company_id, bounded, now=NOW)
    assert (first.liveness_sessions, first.truncated) == (4, True)
    assert await _count(company_id, "face_liveness_session") == 3

    second = await cleanup_company(company_id, bounded, now=NOW)
    assert (second.liveness_sessions, second.truncated) == (3, False)
    assert await _count(company_id, "face_liveness_session") == 0


async def test_batch_bound_holds_when_table_statistics_say_the_table_is_empty(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    """Regression: with `WHERE id IN (SELECT ... LIMIT n FOR UPDATE SKIP LOCKED)` the planner could
    ignore the LIMIT when the statistics described an (almost) empty table - the normal state after
    a bulk delete - so one batch of 2 removed every eligible row. Pins the statistics to that state
    for every table the cleanup touches."""
    admin, company_id = face_tenant
    employee = await _employee(client, admin)
    for _ in range(7):
        await _seed_session(company_id, employee, age=OLD)
        await _seed_attempt(company_id, employee, age=OLD)
        await _seed_enrollment_attempt(company_id, employee, age=OLD)
    for table in ("face_liveness_session", "face_verification_attempt", "face_enrollment_attempt"):
        await _sql(
            company_id,
            f"UPDATE pg_class SET reltuples = 0, relpages = 1 WHERE relname = '{table}'",
        )
    bounded = _settings(face_cleanup_batch_size=2, face_cleanup_max_batches=2)

    first = await cleanup_company(company_id, bounded, now=NOW)

    assert (first.liveness_sessions, first.attempt_details_erased, first.enrollment_attempts) == (
        4,
        4,
        4,
    )
    assert first.truncated is True
    assert await _count(company_id, "face_liveness_session") == 3
    assert await _count(company_id, "face_enrollment_attempt") == 3


async def test_company_on_hold_is_untouched(client: AsyncClient, face_tenant: Tenant) -> None:
    admin, company_id = face_tenant
    employee = await _employee(client, admin)
    await _seed_session(company_id, employee, age=OLD)
    await _seed_attempt(company_id, employee, age=OLD)
    await _seed_enrollment_attempt(company_id, employee, age=OLD)
    held = _settings(face_cleanup_hold_company_ids=f" {uuid4()} , {company_id}")

    report = await cleanup_company(company_id, held, now=NOW)

    assert report.held is True
    assert (report.liveness_sessions, report.attempt_details_erased) == (0, 0)
    assert await _count(company_id, "face_liveness_session") == 1
    assert await _count(company_id, "face_enrollment_attempt") == 1
    assert (await _sql(company_id, "SELECT provider_person_id FROM face_verification_attempt"))[0][
        "provider_person_id"
    ] == "fs_person"


async def test_cleanup_is_scoped_to_one_tenant(
    client: AsyncClient, face_tenant: Tenant, face_tenant_b: Tenant
) -> None:
    admin_a, company_a = face_tenant
    admin_b, company_b = face_tenant_b
    employee_a = await _employee(client, admin_a)
    employee_b = await _employee(client, admin_b, "Zed")
    await _seed_session(company_a, employee_a, age=OLD)
    await _seed_session(company_b, employee_b, age=OLD)
    await _seed_enrollment_attempt(company_b, employee_b, age=OLD)

    await cleanup_company(company_a, _settings(), now=NOW)

    assert await _count(company_a, "face_liveness_session") == 0
    assert await _count(company_b, "face_liveness_session") == 1
    assert await _count(company_b, "face_enrollment_attempt") == 1


async def test_cleanup_never_removes_punches_and_an_idempotent_replay_still_works(
    client: AsyncClient, face_tenant: Tenant
) -> None:
    _, company_id = face_tenant
    headers, _ = await _enrolled_self(client, face_tenant)
    key = "retention-key-" + "x" * 8
    first = await face_punch(client, headers, "IN", key=key)
    assert first.status_code == 201, first.text
    punch_id = first.json()["data"]["punch"]["id"]
    await _sql(
        company_id,
        "UPDATE face_verification_attempt SET created_at = :old WHERE company_id = :cid",
        old=NOW - OLD,
    )
    punches_before = await _sql(company_id, "SELECT id FROM punch WHERE company_id = :cid")

    report = await cleanup_company(company_id, _settings(), now=NOW)

    assert report.attempt_details_erased >= 1
    assert await _sql(company_id, "SELECT id FROM punch WHERE company_id = :cid") == punches_before
    (attempt,) = await _sql(
        company_id,
        "SELECT decision, punch_id, similarity, liveness_score, provider_response "
        "FROM face_verification_attempt WHERE company_id = :cid AND decision = 'MATCHED'",
    )
    assert str(attempt["punch_id"]) == punch_id
    assert attempt["provider_response"] is None
    assert attempt["similarity"] is not None
    # Retrying the original request with the same key still returns the original punch.
    replay = await face_punch(client, headers, "IN", key=key)
    assert replay.status_code == 201, replay.text
    assert replay.json()["data"]["punch"]["id"] == punch_id
    assert await _punch_count(client, headers) == 1


async def test_report_and_logs_carry_counts_only(
    client: AsyncClient, face_tenant: Tenant, capsys: pytest.CaptureFixture[str]
) -> None:
    admin, company_id = face_tenant
    employee = await _employee(client, admin)
    await _seed_session(company_id, employee, age=OLD)
    capsys.readouterr()

    await cleanup_company(company_id, _settings(), now=NOW)

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if "face_cleanup_finished" in line
    ]
    assert len(events) == 1
    assert events[0]["liveness_sessions"] == 1
    assert events[0]["company_id"] == str(company_id)
    assert "digest-marker" not in json.dumps(events[0])  # frame digests never reach the log
