"""Unit tests for the attendance module's pure publish-time validators — no DB/HTTP."""

import pytest

from hrms.modules.attendance.exceptions import (
    InvalidPolicyBandError,
    InvalidPolicyRateRowError,
    InvalidRegularizationAllowedTypeError,
)
from hrms.modules.attendance.schemas import (
    AttendancePolicyHourBandInput,
    OvertimePolicyRateRowInput,
    RegularizationPolicyAllowedTypeInput,
)
from hrms.modules.attendance.service import (
    _validate_allowed_types,
    _validate_bands,
    _validate_rate_rows,
)


def _band(
    min_minutes: int, max_minutes: int | None, status: str = "PRESENT"
) -> AttendancePolicyHourBandInput:
    return AttendancePolicyHourBandInput(
        min_minutes=min_minutes, max_minutes=max_minutes, result_status=status
    )


def test_validate_bands_requires_at_least_one_when_required() -> None:
    with pytest.raises(InvalidPolicyBandError):
        _validate_bands([], required=True, field="hour_bands")


def test_validate_bands_allows_empty_when_not_required() -> None:
    _validate_bands([], required=False, field="late_bands")


def test_validate_bands_accepts_ordered_non_overlapping() -> None:
    bands = [
        _band(0, 239, "ABSENT"),
        _band(240, 479, "HALF_DAY"),
        _band(480, None, "PRESENT"),
    ]
    _validate_bands(bands, required=True, field="hour_bands")


def test_validate_bands_rejects_overlap() -> None:
    bands = [_band(0, 300, "ABSENT"), _band(200, 480, "HALF_DAY")]
    with pytest.raises(InvalidPolicyBandError):
        _validate_bands(bands, required=True, field="hour_bands")


def test_validate_bands_rejects_open_ended_band_not_last() -> None:
    bands = [_band(0, None, "PRESENT"), _band(500, 600, "HALF_DAY")]
    with pytest.raises(InvalidPolicyBandError):
        _validate_bands(bands, required=True, field="hour_bands")


def test_validate_bands_accepts_out_of_order_input() -> None:
    """Bands need not be submitted pre-sorted — the validator sorts by `min_minutes` first."""
    bands = [_band(480, None, "PRESENT"), _band(0, 239, "ABSENT"), _band(240, 479, "HALF_DAY")]
    _validate_bands(bands, required=True, field="hour_bands")


def test_validate_rate_rows_rejects_duplicate_day_class() -> None:
    rows = [
        OvertimePolicyRateRowInput(day_class="NORMAL", classification_code="A"),
        OvertimePolicyRateRowInput(day_class="NORMAL", classification_code="B"),
    ]
    with pytest.raises(InvalidPolicyRateRowError):
        _validate_rate_rows(rows)


def test_validate_rate_rows_accepts_distinct_day_classes() -> None:
    rows = [
        OvertimePolicyRateRowInput(day_class="NORMAL", classification_code="A"),
        OvertimePolicyRateRowInput(day_class="HOLIDAY", classification_code="B"),
    ]
    _validate_rate_rows(rows)


def test_validate_allowed_types_rejects_duplicates() -> None:
    rows = [
        RegularizationPolicyAllowedTypeInput(regularization_type="MISSING_PUNCH"),
        RegularizationPolicyAllowedTypeInput(regularization_type="MISSING_PUNCH"),
    ]
    with pytest.raises(InvalidRegularizationAllowedTypeError):
        _validate_allowed_types(rows)


def test_validate_allowed_types_accepts_distinct_types() -> None:
    rows = [
        RegularizationPolicyAllowedTypeInput(regularization_type="MISSING_PUNCH"),
        RegularizationPolicyAllowedTypeInput(regularization_type="EXCESS_BREAK"),
    ]
    _validate_allowed_types(rows)
