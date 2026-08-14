"""Unit tests for organisation service Shift methods."""

from datetime import UTC, datetime, time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.exceptions import (
    InvalidShiftHoursRangeError,
    InvalidShiftTimeRangeError,
    StaleResourceError,
)
from hrms.modules.organisation.models import Shift
from hrms.modules.organisation.schemas import ShiftCreate, ShiftUpdate
from hrms.modules.organisation.service import OrganisationService


def _shift(**overrides: object) -> Shift:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "name": "General Shift",
        "code": "GEN",
        "start_time": time(9, 0),
        "end_time": time(18, 0),
        "break_minutes_paid": 0,
        "break_minutes_unpaid": 30,
        "grace_in_minutes": 10,
        "grace_out_minutes": 10,
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


@pytest.fixture
def service() -> OrganisationService:
    session = MagicMock()
    svc = OrganisationService(session)
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_create_shift_records_audit(service: OrganisationService) -> None:
    company_id = uuid4()
    shift = _shift(company_id=company_id)
    service._repo.insert_shift.return_value = shift

    result = await service.create_shift(
        company_id,
        ShiftCreate(name="General Shift", code="GEN", start_time="09:00", end_time="18:00"),
        actor_user_id=uuid4(),
    )

    assert result.name == "General Shift"
    assert result.start_time == "09:00"
    assert result.end_time == "18:00"
    assert result.is_active is True
    service._audit.record.assert_awaited_once()
    assert service._audit.record.call_args.kwargs["action"] == "SHIFT_CREATED"


@pytest.mark.asyncio
async def test_create_shift_end_before_start_rejected(service: OrganisationService) -> None:
    with pytest.raises(InvalidShiftTimeRangeError):
        await service.create_shift(
            uuid4(),
            ShiftCreate(name="Bad Shift", start_time="18:00", end_time="09:00"),
            actor_user_id=uuid4(),
        )
    service._repo.insert_shift.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_shift_end_before_start_allowed_when_cross_midnight(
    service: OrganisationService,
) -> None:
    company_id = uuid4()
    service._repo.insert_shift.return_value = _shift(
        company_id=company_id,
        start_time=time(22, 0),
        end_time=time(6, 0),
        is_cross_midnight=True,
    )

    result = await service.create_shift(
        company_id,
        ShiftCreate(
            name="Night Shift", start_time="22:00", end_time="06:00", is_cross_midnight=True
        ),
        actor_user_id=uuid4(),
    )

    assert result.start_time == "22:00"
    assert result.end_time == "06:00"


@pytest.mark.asyncio
async def test_create_shift_equal_start_end_accepted_when_cross_midnight(
    service: OrganisationService,
) -> None:
    """`end <= start` (including equal) is only rejected when `is_cross_midnight` is not set —
    per docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md §6.2, no document rejects an equal
    start/end combined with `is_cross_midnight=true`, so this audit does not invent one."""
    company_id = uuid4()
    service._repo.insert_shift.return_value = _shift(
        company_id=company_id,
        start_time=time(9, 0),
        end_time=time(9, 0),
        is_cross_midnight=True,
    )

    result = await service.create_shift(
        company_id,
        ShiftCreate(name="Full Day", start_time="09:00", end_time="09:00", is_cross_midnight=True),
        actor_user_id=uuid4(),
    )

    assert result.start_time == result.end_time == "09:00"


@pytest.mark.asyncio
async def test_create_shift_invalid_hours_range_rejected(service: OrganisationService) -> None:
    with pytest.raises(InvalidShiftHoursRangeError):
        await service.create_shift(
            uuid4(),
            ShiftCreate(
                name="Bad Hours",
                start_time="09:00",
                end_time="18:00",
                half_day_threshold_hours=8,
                min_hours_full_day=4,
            ),
            actor_user_id=uuid4(),
        )
    service._repo.insert_shift.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_shift_not_found(service: OrganisationService) -> None:
    service._repo.get_shift.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_shift(uuid4(), uuid4())


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
async def test_update_shift_invalid_time_range_rejected_against_existing_value(
    service: OrganisationService,
) -> None:
    """Patching only `end_time` below the *existing* `start_time` must still be rejected —
    the effective range is validated, not just the fields present in the patch."""
    shift = _shift(start_time=time(9, 0), end_time=time(18, 0), is_cross_midnight=False)
    service._repo.get_shift.return_value = shift

    with pytest.raises(InvalidShiftTimeRangeError):
        await service.update_shift(
            shift.company_id,
            shift.id,
            ShiftUpdate(end_time="08:00"),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_shift.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_shift_invalid_hours_range_rejected_against_existing_value(
    service: OrganisationService,
) -> None:
    shift = _shift(half_day_threshold_hours=None, min_hours_full_day=4)
    service._repo.get_shift.return_value = shift

    with pytest.raises(InvalidShiftHoursRangeError):
        await service.update_shift(
            shift.company_id,
            shift.id,
            ShiftUpdate(half_day_threshold_hours=8),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_shift.assert_not_awaited()


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
