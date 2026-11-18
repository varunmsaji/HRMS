"""Invariant A — the precedence rule every consumer of a date's shift goes through
(`attendance/work_schedule.py`, SHIFT_REMEDIATION_PLAN §3.1)."""

from types import SimpleNamespace
from uuid import uuid4

from hrms.modules.attendance.work_schedule import shift_id_for

ASSIGNED = uuid4()
ROSTERED = uuid4()


def test_published_roster_shift_wins_over_the_assignment() -> None:
    assignment = SimpleNamespace(shift_id=ASSIGNED)
    roster = SimpleNamespace(shift_id=ROSTERED)
    assert shift_id_for(assignment, roster) == (ROSTERED, "ROSTER")


def test_roster_row_without_a_shift_does_not_fall_back_to_the_assignment() -> None:
    assignment = SimpleNamespace(shift_id=ASSIGNED)
    roster = SimpleNamespace(shift_id=None)
    assert shift_id_for(assignment, roster) == (None, "ROSTER")


def test_assignment_shift_applies_without_a_roster_row() -> None:
    assert shift_id_for(SimpleNamespace(shift_id=ASSIGNED), None) == (ASSIGNED, "ASSIGNMENT")


def test_no_assignment_and_no_roster_means_no_shift() -> None:
    assert shift_id_for(None, None) == (None, "NONE")
    assert shift_id_for(SimpleNamespace(shift_id=None), None) == (None, "NONE")
