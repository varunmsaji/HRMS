"""Unit tests for organisation service Shift (identity) methods.

W2 trimmed `Shift` to identity-only (name/code/active) — the nine legacy schedule/
evaluation fields (start_time, end_time, breaks, grace, half-day/min-hours, night/cross-
midnight/OT flags) moved to `ShiftVersion` (see test_shift_version_service.py /
test_shift_version_validation.py). `create_shift` now also creates an initial empty DRAFT
`ShiftVersion` in the same transaction.
"""

from datetime import UTC, datetime, time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.exceptions import StaleResourceError
from hrms.modules.organisation.models import Shift, ShiftVersion
from hrms.modules.organisation.schemas import ShiftCreate, ShiftUpdate
from hrms.modules.organisation.service import OrganisationService


def _shift(**overrides: object) -> Shift:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "name": "General Shift",
        "code": "GEN",
        "start_time": time(0, 0),
        "end_time": time(0, 0),
        "break_minutes_paid": 0,
        "break_minutes_unpaid": 0,
        "grace_in_minutes": 0,
        "grace_out_minutes": 0,
        "half_day_threshold_hours": None,
        "min_hours_full_day": None,
        "is_night_shift": False,
        "is_cross_midnight": False,
        "is_ot_eligible": False,
        "is_active": True,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Shift(**defaults)  # type: ignore[arg-type]


def _draft_version(**overrides: object) -> ShiftVersion:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "shift_id": uuid4(),
        "status": "DRAFT",
        "version": 1,
        "effective_from": None,
        "effective_to": None,
        "shift_type": None,
        "timezone": None,
        "start_time": None,
        "end_time": None,
        "window_start": None,
        "window_end": None,
        "core_start": None,
        "core_end": None,
        "required_minutes": None,
        "scheduled_minutes": None,
        "min_scheduled_minutes": None,
        "max_scheduled_minutes": None,
        "is_night_shift": False,
        "is_cross_midnight": False,
        "is_ot_eligible": False,
        "operates_on_holiday": False,
        "operates_on_weekly_off": False,
        "weekly_off_pattern_id": None,
        "publish_reason": None,
        "published_at": None,
        "published_by": None,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    defaults.update(overrides)
    return ShiftVersion(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> OrganisationService:
    session = MagicMock()
    svc = OrganisationService(session)
    svc._repo = AsyncMock()
    svc._shift_version_repo = AsyncMock()
    svc._audit = AsyncMock()
    svc._assert_master_not_in_use = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_create_shift_records_audit_and_creates_initial_draft(
    service: OrganisationService,
) -> None:
    company_id = uuid4()
    shift = _shift(company_id=company_id)
    service._repo.insert_shift.return_value = shift
    service._shift_version_repo.insert.return_value = _draft_version(
        company_id=company_id, shift_id=shift.id
    )

    result = await service.create_shift(
        company_id,
        ShiftCreate(name="General Shift"),
        actor_user_id=uuid4(),
    )

    assert result.name == "General Shift"
    assert result.code == "GEN"
    assert result.is_active is True
    assert result.draft_version_id is not None
    service._shift_version_repo.insert.assert_awaited_once()
    shift_insert_data = service._repo.insert_shift.call_args.kwargs["data"]
    version_insert_data = service._shift_version_repo.insert.call_args.kwargs["data"]
    assert version_insert_data["status"] == "DRAFT"
    # Both inserts happen in the same `create_shift` call, keyed on the same freshly
    # generated shift id — not the mocked return value's own (unrelated) id.
    assert version_insert_data["shift_id"] == shift_insert_data["id"]
    # Two audit events: the shift identity itself, and the auto-created draft version.
    assert service._audit.record.await_count == 2
    actions = [call.kwargs["action"] for call in service._audit.record.await_args_list]
    assert actions == ["SHIFT_CREATED", "SHIFT_VERSION_CREATED"]


@pytest.mark.asyncio
async def test_create_shift_rejects_legacy_schedule_fields(
    service: OrganisationService,
) -> None:
    """`extra="forbid"` on `ShiftCreate` — the nine legacy schedule/evaluation fields are no
    longer accepted, not just ignored."""
    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError, not our AppError
        ShiftCreate(name="Bad Shift", start_time="09:00", end_time="18:00")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_get_shift_not_found(service: OrganisationService) -> None:
    service._repo.get_shift.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_shift(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_get_shift_includes_current_and_draft_version_ids(
    service: OrganisationService,
) -> None:
    shift = _shift()
    service._repo.get_shift.return_value = shift
    current = _draft_version(shift_id=shift.id, status="PUBLISHED")
    draft = _draft_version(shift_id=shift.id, status="DRAFT")
    service._shift_version_repo.get_current_published.return_value = current
    service._shift_version_repo.get_open_draft.return_value = draft

    result = await service.get_shift(shift.company_id, shift.id)

    assert result.current_version_id == current.id
    assert result.draft_version_id == draft.id


@pytest.mark.asyncio
async def test_update_shift_not_found(service: OrganisationService) -> None:
    service._repo.get_shift.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_shift(
            uuid4(),
            uuid4(),
            ShiftUpdate(name="New Name"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_deactivate_shift_not_blocked_by_anything(service: OrganisationService) -> None:
    """No documented dependency-blocking rule applies to Shift deactivation this slice —
    see docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md §6.4."""
    shift = _shift(is_active=True)
    service._repo.get_shift.return_value = shift
    service._repo.update_shift.return_value = _shift(
        id=shift.id, company_id=shift.company_id, is_active=False, version=2
    )

    result = await service.update_shift(
        shift.company_id,
        shift.id,
        ShiftUpdate(is_active=False),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is False
    assert service._audit.record.call_args.kwargs["action"] == "SHIFT_DEACTIVATED"


@pytest.mark.asyncio
async def test_reactivate_shift_records_distinct_audit_action(
    service: OrganisationService,
) -> None:
    shift = _shift(is_active=False)
    service._repo.get_shift.return_value = shift
    service._repo.update_shift.return_value = _shift(
        id=shift.id, company_id=shift.company_id, is_active=True, version=2
    )

    result = await service.update_shift(
        shift.company_id,
        shift.id,
        ShiftUpdate(is_active=True),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is True
    assert service._audit.record.call_args.kwargs["action"] == "SHIFT_REACTIVATED"


@pytest.mark.asyncio
async def test_update_shift_stale_version_conflict(service: OrganisationService) -> None:
    shift = _shift()
    service._repo.get_shift.return_value = shift
    service._repo.update_shift.return_value = None

    with pytest.raises(StaleResourceError):
        await service.update_shift(
            shift.company_id,
            shift.id,
            ShiftUpdate(name="Renamed"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_shift_noop_when_patch_empty(service: OrganisationService) -> None:
    shift = _shift()
    service._repo.get_shift.return_value = shift

    result = await service.update_shift(
        shift.company_id,
        shift.id,
        ShiftUpdate(),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.name == shift.name
    service._repo.update_shift.assert_not_awaited()
    service._audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_shift_is_semantic_wrapper_around_update_shift(
    service: OrganisationService,
) -> None:
    shift = _shift(is_active=True)
    service._repo.get_shift.return_value = shift
    service._repo.update_shift.return_value = _shift(
        id=shift.id, company_id=shift.company_id, is_active=False, version=2
    )

    result = await service.deactivate_shift(
        shift.company_id,
        shift.id,
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is False
    assert service._audit.record.call_args.kwargs["action"] == "SHIFT_DEACTIVATED"


class _FakeShift:
    def __init__(self, *, is_active: bool) -> None:
        self.id = uuid4()
        self.is_active = is_active


class _FakeRepo:
    def __init__(self, refs: dict[str, int]) -> None:
        self._refs = refs
        self._session = None

    async def count_shift_references(self, session, *, company_id, shift_id):  # type: ignore[no-untyped-def]
        return self._refs


_NO_REFS = {
    "assignment_rows": 0,
    "active_employees": 0,
    "roster_rows": 0,
    "attendance_days": 0,
    "regularization_requests": 0,
    "published_versions": 1,
    "draft_versions": 0,
}


async def _deletion_check(refs: dict[str, int], *, is_active: bool):  # type: ignore[no-untyped-def]
    service = OrganisationService.__new__(OrganisationService)
    service._repo = _FakeRepo(refs)  # type: ignore[attr-defined]
    service._session = None  # type: ignore[attr-defined]
    return await service._shift_deletion_check(uuid4(), _FakeShift(is_active=is_active))  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_deletion_check_allows_an_inactive_never_used_shift() -> None:
    check = await _deletion_check(_NO_REFS, is_active=False)
    assert check.can_delete is True
    assert check.blockers == []
    assert check.published_version_count == 1


@pytest.mark.asyncio
async def test_deletion_check_reports_every_blocker_at_once() -> None:
    refs = {
        **_NO_REFS,
        "assignment_rows": 4,
        "active_employees": 2,
        "roster_rows": 3,
        "attendance_days": 10,
        "regularization_requests": 1,
    }
    check = await _deletion_check(refs, is_active=True)
    assert check.can_delete is False
    assert {b.code for b in check.blockers} == {
        "SHIFT_STILL_ACTIVE",
        "SHIFT_HAS_ACTIVE_EMPLOYEES",
        "SHIFT_HAS_ASSIGNMENT_HISTORY",
        "SHIFT_HAS_ROSTER_ENTRIES",
        "SHIFT_HAS_ATTENDANCE_RECORDS",
        "SHIFT_HAS_REGULARIZATION_REQUESTS",
    }
