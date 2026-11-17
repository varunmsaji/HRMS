"""H-04 (owner decision): a rostered day off.

* Scope: a published roster row that is a week-off carries no shift, so its SHIFT scope for
  resolving policies and calendars is the employee's ASSIGNED shift (`scope_shift_id_for`). No
  assigned shift: no SHIFT scope, resolution falls through. A roster row that names a shift, and
  every other case,
  is unchanged; the work schedule of a rostered day off stays "no shift".
* Engine: a rostered day off with no punches is paid and NOT_EXPECTED even when no calendar or
  attendance policy resolves (missing configuration must not block the close for a day nobody
  worked). With punches it is real work and the configuration checks apply as always.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.unit.modules.attendance.test_attendance_rules_remediation import _day, _pay

from hrms.modules.attendance.work_schedule import scope_shift_id_for, shift_id_for

ASSIGNED = uuid4()
ROSTERED = uuid4()


def _roster(shift_id: object, *, week_off: bool) -> SimpleNamespace:
    return SimpleNamespace(shift_id=shift_id, is_week_off_override=week_off)


def _assignment(shift_id: object) -> SimpleNamespace:
    return SimpleNamespace(shift_id=shift_id)


# --- scope ---


def test_a_rostered_day_off_uses_the_assigned_shift_for_scope() -> None:
    assert scope_shift_id_for(_assignment(ASSIGNED), _roster(None, week_off=True)) == ASSIGNED


def test_with_no_assigned_shift_a_rostered_day_off_has_no_shift_scope() -> None:
    assert scope_shift_id_for(_assignment(None), _roster(None, week_off=True)) is None
    assert scope_shift_id_for(None, _roster(None, week_off=True)) is None


def test_a_roster_row_that_names_a_shift_is_unchanged() -> None:
    assert scope_shift_id_for(_assignment(ASSIGNED), _roster(ROSTERED, week_off=False)) == ROSTERED
    # even a week-off row that explicitly carries a shift keeps it
    assert scope_shift_id_for(_assignment(ASSIGNED), _roster(ROSTERED, week_off=True)) == ROSTERED


def test_a_shiftless_roster_row_that_is_not_a_day_off_is_unchanged() -> None:
    row = _roster(None, week_off=False)
    assert scope_shift_id_for(_assignment(ASSIGNED), row) is None
    assert shift_id_for(_assignment(ASSIGNED), row)[0] is None


def test_with_no_roster_row_the_assigned_shift_applies_as_before() -> None:
    assert scope_shift_id_for(_assignment(ASSIGNED), None) == ASSIGNED
    assert scope_shift_id_for(_assignment(None), None) is None
    assert scope_shift_id_for(None, None) is None


def test_the_work_schedule_resolution_is_not_changed_by_h04() -> None:
    """`shift_id_for` still says a rostered day off has no shift of its own."""
    assert shift_id_for(_assignment(ASSIGNED), _roster(None, week_off=True)) == (None, "ROSTER")


# --- engine: a day off with nothing to calculate needs no configuration ---


def test_a_rostered_day_off_with_no_punches_is_paid_even_with_no_policy_and_no_calendar() -> None:
    result = _day([], roster_week_off_override=True, policy=None, calendar_day_type=None)
    assert result.attendance_status == "NOT_EXPECTED"
    assert _pay(result) == ("1.00", "0.00")
    assert result.snapshot["terminal_reason"] == "roster_week_off_override"


@pytest.mark.parametrize("missing", ["policy", "calendar", "both"])
def test_each_missing_piece_of_configuration_is_tolerated_on_a_day_off(missing: str) -> None:
    overrides: dict[str, object] = {}
    if missing in ("policy", "both"):
        overrides["policy"] = None
    if missing in ("calendar", "both"):
        overrides["calendar_day_type"] = None
    result = _day([], roster_week_off_override=True, **overrides)
    assert result.attendance_status == "NOT_EXPECTED"
    assert _pay(result) == ("1.00", "0.00")


def test_work_on_a_rostered_day_off_still_needs_the_configuration() -> None:
    """Punches make it real work: missing configuration is still a CONFIG_ERROR, not bypassed."""
    no_policy = _day([(10, 0, "IN"), (14, 0, "OUT")], roster_week_off_override=True, policy=None)
    assert no_policy.attendance_status == "CONFIG_ERROR"
    no_calendar = _day(
        [(10, 0, "IN"), (14, 0, "OUT")], roster_week_off_override=True, calendar_day_type=None
    )
    assert no_calendar.attendance_status == "CONFIG_ERROR"


def test_a_working_day_with_missing_configuration_is_still_a_config_error() -> None:
    assert _day([], policy=None).attendance_status == "CONFIG_ERROR"
    assert _day([], calendar_day_type=None).attendance_status == "CONFIG_ERROR"


def test_work_on_a_rostered_day_off_with_full_configuration_is_unchanged() -> None:
    result = _day([(10, 0, "IN"), (14, 0, "OUT")], roster_week_off_override=True)
    assert result.attendance_status == "PRESENT"
    assert result.paid_day_fraction == "1.00"


def test_a_not_joined_employee_is_still_not_joined_on_a_rostered_day_off() -> None:
    result = _day([], roster_week_off_override=True, population_status="NOT_JOINED", policy=None)
    assert result.attendance_status == "NOT_JOINED"
