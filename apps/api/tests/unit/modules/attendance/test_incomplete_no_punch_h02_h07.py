"""H-02 and H-07 (owner decisions), engine and wording.

* `day_has_no_punches` tells a true no-show (no punch at all, not even a lone OUT) from a day with
  at least one punch; the period lock uses it so `TREAT_PRESENT` never pays a no-show.
* A half-day-leave day with no punch keeps its worked half PENDING (INCOMPLETE) until the lock
  instead of being lost at once; the leave half is settled on its own. A policy that sets
  `missing_punch_behaviour=ABSENT` still resolves it at once, and a half-weekly-off day fully
  covered by leave has nothing left to decide.
* The HR digest says how many days had no punches and that a day with a punch follows the policy.
"""

from datetime import UTC, datetime

import pytest
from tests.unit.modules.attendance.test_attendance_rules_remediation import _day, _leave
from tests.unit.modules.attendance.test_calculation import _policy

from hrms.modules.attendance.calculation import day_has_no_punches
from hrms.modules.attendance.email_templates import build_incomplete_days_hr_digest_email

IN_AT = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def _triple(result: object) -> tuple[str, str, str]:
    return (result.attendance_status, result.paid_day_fraction, result.lop_fraction)  # type: ignore[attr-defined]


# --- the no-punch test ---


def test_a_snapshot_with_no_punch_ids_is_a_no_show() -> None:
    assert day_has_no_punches({"inputs": {"punch_ids": []}}, None, None) is True


@pytest.mark.parametrize("ids", [["a"], ["a", "b"]])
def test_a_snapshot_with_any_punch_is_not_a_no_show(ids: list[str]) -> None:
    assert day_has_no_punches({"inputs": {"punch_ids": ids}}, None, None) is False


def test_a_lone_out_punch_is_still_a_punch() -> None:
    """No recorded first-in, but the day owns a punch: not a no-show."""
    assert day_has_no_punches({"inputs": {"punch_ids": ["only-out"]}}, None, None) is False


@pytest.mark.parametrize(
    ("snapshot", "first_in", "last_out", "expected"),
    [
        (
            None,
            None,
            None,
            True,
        ),  # a row that predates the snapshot: falls back to the recorded times
        ({}, None, None, True),
        ({}, IN_AT, None, False),
        ({"inputs": {}}, None, IN_AT, False),
        ({"inputs": {"punch_ids": None}}, IN_AT, None, False),
    ],
)
def test_rows_without_the_punch_list_fall_back_to_the_recorded_times(
    snapshot: dict | None, first_in: datetime | None, last_out: datetime | None, expected: bool
) -> None:
    assert day_has_no_punches(snapshot, first_in, last_out) is expected


# --- the engine: a no-show day and a half-day-leave day with no punch ---


def test_a_full_no_show_is_pending_until_the_lock() -> None:
    result = _day([])
    assert _triple(result) == ("INCOMPLETE", "0.00", "0.00")  # nothing decided yet


@pytest.mark.parametrize(
    ("paid_leave", "paid", "lop"),
    [(True, "0.50", "0.00"), (False, "0.00", "0.50")],
)
@pytest.mark.parametrize("half", ["FIRST", "SECOND"])
def test_half_day_leave_with_no_punch_keeps_the_worked_half_pending(
    half: str, paid_leave: bool, paid: str, lop: str
) -> None:
    result = _day([], leave_entries=_leave(half, paid=paid_leave))
    assert result.attendance_status == "INCOMPLETE"
    assert (result.paid_day_fraction, result.lop_fraction) == (paid, lop)  # only the leave half
    assert result.leave_fraction == "0.50"  # the leave debit is exactly the half


def test_a_half_day_leave_day_with_an_in_punch_is_pending_as_before() -> None:
    result = _day([(14, 0, "IN")], leave_entries=_leave("FIRST"))
    assert result.attendance_status == "INCOMPLETE"
    assert (result.paid_day_fraction, result.lop_fraction) == ("0.50", "0.00")


def test_a_policy_that_sets_missing_punch_to_absent_still_resolves_the_half_at_once() -> None:
    policy = _policy(grace_in_minutes=10, grace_out_minutes=10, missing_punch_behaviour="ABSENT")
    result = _day([], policy=policy, leave_entries=_leave("FIRST"))
    assert _triple(result) == ("LEAVE", "0.50", "0.50")


def test_a_worked_half_is_never_left_pending_when_it_is_worked() -> None:
    result = _day([(13, 30, "IN"), (18, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert _triple(result) == ("HALF_DAY", "1.00", "0.00")


# --- the HR digest says it ---


def _digest(no_punch: int) -> tuple[str, str, str]:
    return build_incomplete_days_hr_digest_email(
        period_label="Aug 2026",
        period_end=datetime(2026, 8, 31, tzinfo=UTC).date(),
        employee_count=4,
        incomplete_day_count=9,
        employees_without_email=0,
        period_url="https://example.test/period",
        no_punch_day_count=no_punch,
    )


def test_the_digest_states_the_no_punch_rule_and_that_an_in_only_day_follows_the_policy() -> None:
    _, html_body, text_body = _digest(3)
    assert "3 of them have no punches at all and will be counted as absent" in text_body
    assert "whatever the policy says" in text_body
    assert "only an IN punch" in text_body and "paid in full" in text_body
    assert "3 of them have no punches" in html_body


def test_the_digest_omits_the_no_punch_sentence_when_there_are_none() -> None:
    _, _, text_body = _digest(0)
    assert "no punches at all" not in text_body
    assert "only an IN punch" in text_body  # the policy explanation is always there
