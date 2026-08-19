"""Pure validator unit tests for the W2 Shift + Break System — no HTTP/DB round-trip.

Exercises `OrganisationService`'s private ShiftVersion validators directly: wrap-aware
interval overlap/containment math, break kind-field validation, duty-block publish-time
validation (count/sequence/overlap), the FIXED/FLEXIBLE/SPLIT type-combination guard, and
`is_cross_midnight` derivation. End-to-end HTTP flows (including breaks-outside-window and
insert-new/close-previous publish behavior) live in test_shift_version.py.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from hrms.core.errors.base import ValidationError
from hrms.modules.organisation.exceptions import (
    InvalidShiftBreakError,
    InvalidShiftBreakOverlapError,
    InvalidShiftVersionCoreHoursError,
    InvalidShiftVersionDutyBlockCountError,
    InvalidShiftVersionDutyBlockOverlapError,
    InvalidShiftVersionDutyBlockSequenceError,
    InvalidShiftVersionEffectiveFromError,
    InvalidShiftVersionFlexWindowError,
    InvalidShiftVersionTimeRangeError,
    InvalidShiftVersionTypeCombinationError,
)
from hrms.modules.organisation.schemas import ShiftBreakCreate, ShiftDutyBlockCreate
from hrms.modules.organisation.service import OrganisationService, _parse_time


@pytest.fixture
def service() -> OrganisationService:
    return OrganisationService(MagicMock())


def _duty_block(sequence: int, start: str, end: str) -> SimpleNamespace:
    return SimpleNamespace(
        sequence=sequence,
        start_time=_parse_time(start),
        end_time=_parse_time(end),
        crosses_midnight=end <= start,
    )


def _version(**overrides: object) -> SimpleNamespace:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "shift_type": "FIXED",
        "effective_from": None,
        "start_time": None,
        "end_time": None,
        "window_start": None,
        "window_end": None,
        "core_start": None,
        "core_end": None,
        "required_minutes": None,
        "created_at": now,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# --- interval math -----------------------------------------------------------------------


def test_interval_overlaps_simple_overlap(service: OrganisationService) -> None:
    assert service._interval_overlaps("09:00", "13:00", False, "12:00", "14:00", False) is True


def test_interval_overlaps_disjoint(service: OrganisationService) -> None:
    assert service._interval_overlaps("09:00", "13:00", False, "17:00", "21:00", False) is False


def test_interval_overlaps_wrap_aware(service: OrganisationService) -> None:
    # A 22:00-06:00 wrapping interval and a 05:00-07:00 interval overlap around 05:00-06:00.
    assert service._interval_overlaps("22:00", "06:00", True, "05:00", "07:00", False) is True


def test_interval_contains_simple(service: OrganisationService) -> None:
    assert service._interval_contains("09:00", "18:00", "13:00", "14:00") is True


def test_interval_contains_outside(service: OrganisationService) -> None:
    assert service._interval_contains("09:00", "18:00", "19:00", "19:30") is False


def test_interval_contains_wrap_aware_outer(service: OrganisationService) -> None:
    # 22:00-06:00 outer window contains a 23:00-23:30 break.
    assert service._interval_contains("22:00", "06:00", "23:00", "23:30") is True
    # ...but not a 12:00-12:30 break during the day.
    assert service._interval_contains("22:00", "06:00", "12:00", "12:30") is False


# --- is_cross_midnight derivation ---------------------------------------------------------


def test_derive_cross_midnight_fixed_same_day(service: OrganisationService) -> None:
    assert service._derive_cross_midnight("FIXED", "09:00", "18:00", None) is False


def test_derive_cross_midnight_fixed_wraps(service: OrganisationService) -> None:
    assert service._derive_cross_midnight("FIXED", "22:00", "06:00", None) is True


def test_derive_cross_midnight_flexible_always_false(service: OrganisationService) -> None:
    assert service._derive_cross_midnight("FLEXIBLE", "22:00", "06:00", None) is False


def test_derive_cross_midnight_split_from_blocks(service: OrganisationService) -> None:
    blocks = [
        ShiftDutyBlockCreate(sequence=1, start_time="09:00", end_time="13:00"),
        ShiftDutyBlockCreate(sequence=2, start_time="23:00", end_time="02:00"),
    ]
    assert service._derive_cross_midnight("SPLIT", None, None, blocks) is True


def test_derive_cross_midnight_none_type(service: OrganisationService) -> None:
    assert service._derive_cross_midnight(None, "09:00", "18:00", None) is False


# --- break validation ----------------------------------------------------------------------


def test_validate_breaks_fixed_window_missing_times_rejected(
    service: OrganisationService,
) -> None:
    with pytest.raises(InvalidShiftBreakError):
        service._validate_shift_breaks([ShiftBreakCreate(name="Lunch", break_kind="FIXED_WINDOW")])


def test_validate_breaks_flexible_missing_fields_rejected(service: OrganisationService) -> None:
    with pytest.raises(InvalidShiftBreakError):
        service._validate_shift_breaks(
            [ShiftBreakCreate(name="Flex", break_kind="FLEXIBLE_DURATION")]
        )


def test_validate_breaks_flexible_min_exceeds_max_rejected(
    service: OrganisationService,
) -> None:
    with pytest.raises(InvalidShiftBreakError):
        service._validate_shift_breaks(
            [
                ShiftBreakCreate(
                    name="Flex",
                    break_kind="FLEXIBLE_DURATION",
                    window_start="12:00",
                    window_end="15:00",
                    min_minutes=60,
                    max_minutes=30,
                )
            ]
        )


def test_validate_breaks_scheduled_outside_min_max_rejected(
    service: OrganisationService,
) -> None:
    with pytest.raises(InvalidShiftBreakError):
        service._validate_shift_breaks(
            [
                ShiftBreakCreate(
                    name="Flex",
                    break_kind="FLEXIBLE_DURATION",
                    window_start="12:00",
                    window_end="15:00",
                    min_minutes=15,
                    max_minutes=30,
                    scheduled_minutes=60,
                )
            ]
        )


def test_validate_breaks_fixed_window_overlap_rejected(service: OrganisationService) -> None:
    with pytest.raises(InvalidShiftBreakOverlapError):
        service._validate_shift_breaks(
            [
                ShiftBreakCreate(
                    name="Lunch", break_kind="FIXED_WINDOW", start_time="13:00", end_time="14:00"
                ),
                ShiftBreakCreate(
                    name="Tea", break_kind="FIXED_WINDOW", start_time="13:30", end_time="13:45"
                ),
            ]
        )


def test_validate_breaks_non_overlapping_accepted(service: OrganisationService) -> None:
    service._validate_shift_breaks(
        [
            ShiftBreakCreate(
                name="Lunch", break_kind="FIXED_WINDOW", start_time="13:00", end_time="14:00"
            ),
            ShiftBreakCreate(
                name="Tea", break_kind="FIXED_WINDOW", start_time="16:00", end_time="16:15"
            ),
        ]
    )


def test_validate_breaks_flexible_windows_may_overlap(service: OrganisationService) -> None:
    """FLEXIBLE_DURATION breaks describe a window the break *may* occur within, not a fixed
    occupied slot — they're excluded from the overlap check, per the W2 plan."""
    service._validate_shift_breaks(
        [
            ShiftBreakCreate(
                name="Break A",
                break_kind="FLEXIBLE_DURATION",
                window_start="10:00",
                window_end="14:00",
                min_minutes=15,
                max_minutes=30,
            ),
            ShiftBreakCreate(
                name="Break B",
                break_kind="FLEXIBLE_DURATION",
                window_start="12:00",
                window_end="16:00",
                min_minutes=15,
                max_minutes=30,
            ),
        ]
    )


# --- duty block publish-time validation -----------------------------------------------------


def test_duty_blocks_count_below_two_rejected(service: OrganisationService) -> None:
    with pytest.raises(InvalidShiftVersionDutyBlockCountError):
        service._validate_duty_blocks_for_publish([_duty_block(1, "09:00", "13:00")])


def test_duty_blocks_non_contiguous_sequence_rejected(service: OrganisationService) -> None:
    with pytest.raises(InvalidShiftVersionDutyBlockSequenceError):
        service._validate_duty_blocks_for_publish(
            [_duty_block(1, "09:00", "13:00"), _duty_block(3, "17:00", "21:00")]
        )


def test_duty_blocks_overlap_rejected(service: OrganisationService) -> None:
    with pytest.raises(InvalidShiftVersionDutyBlockOverlapError):
        service._validate_duty_blocks_for_publish(
            [_duty_block(1, "09:00", "14:00"), _duty_block(2, "13:00", "18:00")]
        )


def test_duty_blocks_valid_split_accepted(service: OrganisationService) -> None:
    service._validate_duty_blocks_for_publish(
        [_duty_block(1, "09:00", "13:00"), _duty_block(2, "17:00", "21:00")]
    )


# --- shift_type <-> field combination guard -------------------------------------------------


def test_type_fields_fixed_rejects_flex_fields(service: OrganisationService) -> None:
    version = _version(shift_type="FIXED", window_start=_parse_time("07:00"))
    with pytest.raises(InvalidShiftVersionTypeCombinationError):
        service._validate_shift_version_type_fields("FIXED", version)


def test_type_fields_flexible_rejects_fixed_fields(service: OrganisationService) -> None:
    version = _version(shift_type="FLEXIBLE", start_time=_parse_time("09:00"))
    with pytest.raises(InvalidShiftVersionTypeCombinationError):
        service._validate_shift_version_type_fields("FLEXIBLE", version)


def test_type_fields_clean_fixed_accepted(service: OrganisationService) -> None:
    version = _version(shift_type="FIXED", start_time=_parse_time("09:00"))
    service._validate_shift_version_type_fields("FIXED", version)


# --- full publish validation ------------------------------------------------------------------


def test_publish_validation_requires_shift_type(service: OrganisationService) -> None:
    version = _version(shift_type=None)
    with pytest.raises(ValidationError):
        service._validate_and_derive_for_publish(version, [], [])


def test_publish_validation_requires_effective_from(service: OrganisationService) -> None:
    version = _version(shift_type="FIXED", effective_from=None)
    with pytest.raises(InvalidShiftVersionEffectiveFromError):
        service._validate_and_derive_for_publish(version, [], [])


def test_publish_validation_fixed_missing_times_rejected(service: OrganisationService) -> None:
    from datetime import date

    version = _version(shift_type="FIXED", effective_from=date(2026, 1, 1))
    with pytest.raises(InvalidShiftVersionTimeRangeError):
        service._validate_and_derive_for_publish(version, [], [])


def test_publish_validation_flexible_missing_window_rejected(
    service: OrganisationService,
) -> None:
    from datetime import date

    version = _version(shift_type="FLEXIBLE", effective_from=date(2026, 1, 1))
    with pytest.raises(InvalidShiftVersionFlexWindowError):
        service._validate_and_derive_for_publish(version, [], [])


def test_publish_validation_flexible_partial_core_hours_rejected(
    service: OrganisationService,
) -> None:
    from datetime import date

    version = _version(
        shift_type="FLEXIBLE",
        effective_from=date(2026, 1, 1),
        window_start=_parse_time("07:00"),
        window_end=_parse_time("11:00"),
        required_minutes=480,
        core_start=_parse_time("10:00"),
        core_end=None,
    )
    with pytest.raises(InvalidShiftVersionCoreHoursError):
        service._validate_and_derive_for_publish(version, [], [])


def test_publish_validation_fixed_valid_returns_cross_midnight(
    service: OrganisationService,
) -> None:
    from datetime import date

    version = _version(
        shift_type="FIXED",
        effective_from=date(2026, 1, 1),
        start_time=_parse_time("22:00"),
        end_time=_parse_time("06:00"),
    )
    assert service._validate_and_derive_for_publish(version, [], []) is True
