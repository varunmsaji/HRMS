"""SC-03 / SC-04 - break validation that does not depend on a database.

SC-04 (owner decision D-6): the duration rules for a break hold for every break. Before, they were
skipped when `mode` was empty, which is every break while `shift_break_modes_enabled` is off.
No mode is enabled here and no mode gains behaviour; the AUTO_DEDUCT rule stays tied to its mode.

SC-03 (D-5): a flexible break's window must lie wholly inside the shift's window, as a fixed break's
already had to. SPLIT shifts are still skipped (D-7).
"""

from datetime import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hrms.modules.organisation.exceptions import InvalidShiftBreakError
from hrms.modules.organisation.schemas import ShiftBreakCreate
from hrms.modules.organisation.service import OrganisationService


@pytest.fixture
def service() -> OrganisationService:
    return OrganisationService(MagicMock())


def _flex(**kw: object) -> ShiftBreakCreate:
    base: dict[str, object] = {
        "name": "Lunch",
        "break_kind": "FLEXIBLE_DURATION",
        "window_start": "12:00",
        "window_end": "15:00",
        "min_minutes": 30,
        "max_minutes": 60,
    }
    base.update(kw)
    return ShiftBreakCreate(**base)  # type: ignore[arg-type]


def _fixed(**kw: object) -> ShiftBreakCreate:
    base: dict[str, object] = {
        "name": "Lunch",
        "break_kind": "FIXED_WINDOW",
        "start_time": "13:00",
        "end_time": "14:00",
    }
    base.update(kw)
    return ShiftBreakCreate(**base)  # type: ignore[arg-type]


def _t(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _row(kind: str, a: str, b: str) -> SimpleNamespace:
    """A stored break as the publish check sees it."""
    if kind == "FIXED_WINDOW":
        return SimpleNamespace(
            name="B", break_kind=kind, start_time=_t(a), end_time=_t(b),
            window_start=None, window_end=None,
        )  # fmt: skip
    return SimpleNamespace(
        name="B", break_kind=kind, start_time=None, end_time=None,
        window_start=_t(a), window_end=_t(b),
    )  # fmt: skip


class TestBreakDurationsApplyToEveryBreak:
    """SC-04. Every case below has `mode=None`, the only value possible today."""

    def test_the_mode_really_is_empty_in_these_cases(self) -> None:
        assert _flex().mode is None
        assert _fixed().mode is None

    def test_a_valid_flexible_break_passes(self, service: OrganisationService) -> None:
        service._validate_shift_breaks([_flex(scheduled_minutes=45)])

    def test_a_valid_fixed_break_with_a_length_passes(self, service: OrganisationService) -> None:
        service._validate_shift_breaks([_fixed(scheduled_minutes=60)])

    def test_flexible_max_of_zero_is_refused(self, service: OrganisationService) -> None:
        with pytest.raises(InvalidShiftBreakError, match="max_minutes must be at least 1"):
            service._validate_shift_breaks([_flex(min_minutes=0, max_minutes=0)])

    def test_fixed_max_of_zero_is_refused(self, service: OrganisationService) -> None:
        with pytest.raises(InvalidShiftBreakError, match="max_minutes must be at least 1"):
            service._validate_shift_breaks([_fixed(max_minutes=0)])

    def test_fixed_min_above_max_is_refused(self, service: OrganisationService) -> None:
        with pytest.raises(InvalidShiftBreakError, match="min_minutes must not exceed"):
            service._validate_shift_breaks([_fixed(min_minutes=50, max_minutes=20)])

    def test_scheduled_above_max_is_refused_for_a_flexible_break(
        self, service: OrganisationService
    ) -> None:
        with pytest.raises(InvalidShiftBreakError, match="scheduled_minutes must not exceed max"):
            service._validate_shift_breaks([_flex(scheduled_minutes=61)])

    def test_scheduled_below_min_is_refused_for_a_flexible_break(
        self, service: OrganisationService
    ) -> None:
        with pytest.raises(InvalidShiftBreakError, match="scheduled_minutes must not be below"):
            service._validate_shift_breaks([_flex(scheduled_minutes=10)])

    def test_scheduled_above_max_is_refused_for_a_fixed_break(
        self, service: OrganisationService
    ) -> None:
        with pytest.raises(InvalidShiftBreakError, match="scheduled_minutes must not exceed max"):
            service._validate_shift_breaks([_fixed(max_minutes=30, scheduled_minutes=45)])

    def test_scheduled_below_min_is_refused_for_a_fixed_break(
        self, service: OrganisationService
    ) -> None:
        with pytest.raises(InvalidShiftBreakError, match="scheduled_minutes must not be below"):
            service._validate_shift_breaks([_fixed(min_minutes=30, scheduled_minutes=10)])

    def test_scheduled_longer_than_a_fixed_window_is_refused(
        self, service: OrganisationService
    ) -> None:
        with pytest.raises(InvalidShiftBreakError, match="must not exceed the break window"):
            service._validate_shift_breaks([_fixed(scheduled_minutes=61)])

    def test_scheduled_equal_to_the_fixed_window_is_allowed(
        self, service: OrganisationService
    ) -> None:
        service._validate_shift_breaks([_fixed(scheduled_minutes=60)])

    def test_scheduled_inside_an_overnight_fixed_window_uses_the_wrapped_span(
        self, service: OrganisationService
    ) -> None:
        brk = _fixed(start_time="23:30", end_time="00:30", scheduled_minutes=60)
        service._validate_shift_breaks([brk])
        with pytest.raises(InvalidShiftBreakError, match="must not exceed the break window"):
            service._validate_shift_breaks(
                [_fixed(start_time="23:30", end_time="00:30", scheduled_minutes=61)]
            )

    def test_an_unset_scheduled_length_is_never_compared(
        self, service: OrganisationService
    ) -> None:
        service._validate_shift_breaks([_fixed(min_minutes=10, max_minutes=20)])

    def test_the_error_names_the_break_by_index(self, service: OrganisationService) -> None:
        with pytest.raises(InvalidShiftBreakError) as caught:
            service._validate_shift_breaks(
                [
                    _fixed(name="Tea", start_time="10:00", end_time="10:15"),
                    _flex(max_minutes=0, min_minutes=0),
                ]
            )
        assert caught.value.details[0]["field"] == "breaks.1"

    def test_an_existing_rule_keeps_its_wording(self, service: OrganisationService) -> None:
        with pytest.raises(InvalidShiftBreakError, match="min_minutes must not exceed max_minutes"):
            service._validate_shift_breaks([_flex(min_minutes=60, max_minutes=30)])


class TestAutoDeductStaysTiedToItsMode:
    """The one mode-dependent rule is untouched, and a mode is still just data."""

    def test_flexible_without_a_length_is_fine_when_no_mode_is_set(
        self, service: OrganisationService
    ) -> None:
        service._validate_shift_breaks([_flex()])

    def test_auto_deduct_flexible_still_needs_a_length(self, service: OrganisationService) -> None:
        brk = ShiftBreakCreate.model_construct(**{**_flex().model_dump(), "mode": "AUTO_DEDUCT"})
        with pytest.raises(InvalidShiftBreakError, match="AUTO_DEDUCT"):
            service._validate_shift_breaks([brk])

    def test_a_mode_is_still_refused_while_the_feature_is_off(self) -> None:
        """Nothing here enables break modes: the schema refuses one unless the setting is on."""
        from unittest.mock import patch

        from hrms.core.config.settings import Settings

        off = Settings.model_construct(shift_break_modes_enabled=False)
        with patch("hrms.modules.organisation.schemas.get_settings", return_value=off):
            with pytest.raises(ValueError, match="Break modes are not available yet"):
                _flex(mode="AUTO_DEDUCT", scheduled_minutes=30)


class TestFlexibleWindowsAreContainedInTheShift:
    """SC-03. `_validate_breaks_boundaries_for_publish` is the publish-time check."""

    def _check(
        self,
        service: OrganisationService,
        brk: SimpleNamespace,
        *,
        shift_type: str = "FIXED",
        start: str | None = "09:00",
        end: str | None = "18:00",
        window_start: str | None = None,
        window_end: str | None = None,
        required: int | None = None,
    ) -> None:
        service._validate_breaks_boundaries_for_publish(
            shift_type=shift_type,
            start_time=start,
            end_time=end,
            window_start=window_start,
            window_end=window_end,
            breaks=[brk],
            required_minutes=required,
        )

    def test_a_window_inside_a_fixed_shift_passes(self, service: OrganisationService) -> None:
        self._check(service, _row("FLEXIBLE_DURATION", "12:00", "15:00"))

    def test_a_window_equal_to_the_shift_passes(self, service: OrganisationService) -> None:
        self._check(service, _row("FLEXIBLE_DURATION", "09:00", "18:00"))

    @pytest.mark.parametrize(
        ("a", "b"),
        [("19:00", "20:00"), ("06:00", "08:00"), ("08:00", "10:00"), ("17:00", "19:00")],
        ids=["after", "before", "starts-early", "ends-late"],
    )
    def test_a_window_not_wholly_inside_is_refused(
        self, service: OrganisationService, a: str, b: str
    ) -> None:
        with pytest.raises(InvalidShiftBreakError, match="outside the shift"):
            self._check(service, _row("FLEXIBLE_DURATION", a, b))

    def test_overnight_shift_window_before_midnight_passes(
        self, service: OrganisationService
    ) -> None:
        self._check(
            service, _row("FLEXIBLE_DURATION", "23:00", "23:59"), start="22:00", end="06:00"
        )

    def test_overnight_shift_window_after_midnight_passes(
        self, service: OrganisationService
    ) -> None:
        self._check(
            service, _row("FLEXIBLE_DURATION", "01:00", "03:00"), start="22:00", end="06:00"
        )

    def test_overnight_shift_window_in_the_daytime_gap_is_refused(
        self, service: OrganisationService
    ) -> None:
        with pytest.raises(InvalidShiftBreakError, match="outside the shift"):
            self._check(
                service, _row("FLEXIBLE_DURATION", "12:00", "14:00"), start="22:00", end="06:00"
            )

    def test_flexible_shift_bound_is_window_start_to_window_end_plus_required_minutes(
        self, service: OrganisationService
    ) -> None:
        kw = {
            "shift_type": "FLEXIBLE", "start": None, "end": None,
            "window_start": "07:00", "window_end": "11:00", "required": 480,
        }  # fmt: skip
        self._check(service, _row("FLEXIBLE_DURATION", "12:00", "14:00"), **kw)  # type: ignore[arg-type]
        with pytest.raises(InvalidShiftBreakError, match="outside the shift"):
            self._check(service, _row("FLEXIBLE_DURATION", "20:00", "21:00"), **kw)  # type: ignore[arg-type]

    def test_split_shifts_are_still_skipped(self, service: OrganisationService) -> None:
        self._check(
            service,
            _row("FLEXIBLE_DURATION", "03:00", "04:00"),
            shift_type="SPLIT",
            start=None,
            end=None,
        )

    def test_fixed_breaks_keep_their_existing_behaviour(self, service: OrganisationService) -> None:
        self._check(service, _row("FIXED_WINDOW", "13:00", "14:00"))
        with pytest.raises(InvalidShiftBreakError, match="outside the shift"):
            self._check(service, _row("FIXED_WINDOW", "19:00", "19:30"))

    def test_a_break_without_times_is_left_to_the_other_checks(
        self, service: OrganisationService
    ) -> None:
        bare = SimpleNamespace(
            name="B", break_kind="FLEXIBLE_DURATION", start_time=None, end_time=None,
            window_start=None, window_end=None,
        )  # fmt: skip
        self._check(service, bare)
