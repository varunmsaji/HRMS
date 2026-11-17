"""H-05 (owner decision): plain grace credit applies only to a miss WITHIN the grace.

At each shift boundary the missed minutes are measured on their own. A miss of at most the grace
credits its whole duration to the hour-band lookup (exactly the grace qualifies); a miss beyond the
grace credits nothing at that boundary, except where a late/early MARK judges it (D-01b reading 1:
the grace portion of a qualifying mark is credited together with the beyond-grace mark credit). The
rule is global, applies to start and end independently, and moves only the hour-band lookup - never
worked, overtime, late or early-departure minutes.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.unit.modules.attendance.test_attendance_rules_remediation import _day, _pay

from hrms.modules.attendance import calculation as c

NET = 480


def credit(
    late: int,
    early: int,
    *,
    grace_in: int = 10,
    grace_out: int = 10,
    in_judged: bool = False,
    out_judged: bool = False,
    tz: object = UTC,
) -> c.BandCredit:
    start = datetime(2026, 11, 2, 9, 0, tzinfo=tz)  # type: ignore[arg-type]
    end = start + timedelta(hours=8)
    return c.grace_band_credit_detail(
        first_in=start + timedelta(minutes=late),
        last_out=end - timedelta(minutes=early),
        start_anchor=start,
        end_anchor=end,
        grace_in_minutes=grace_in,
        grace_out_minutes=grace_out,
        worked_minutes=NET - late - early,
        net_scheduled_minutes=NET,
        late_judged=in_judged,
        early_judged=out_judged,
    )


# --- the approved examples ---


@pytest.mark.parametrize(
    ("grace", "missed", "credited"),
    [
        (10, 10, 10),  # exactly the grace qualifies
        (10, 11, 0),  # one minute beyond: nothing at that boundary
        (30, 30, 30),
        (30, 31, 0),
        (0, 0, 0),
        (0, 1, 0),  # a grace of zero credits nothing
        (10, 3, 3),  # the whole missed duration, not the grace
        (10, 0, 0),
    ],
)
@pytest.mark.parametrize("boundary", ["start", "end"])
def test_a_boundary_is_credited_only_when_the_miss_is_within_the_grace(
    grace: int, missed: int, credited: int, boundary: str
) -> None:
    late, early = (missed, 0) if boundary == "start" else (0, missed)
    d = credit(late, early, grace_in=grace, grace_out=grace)
    assert d.plain_grace_in + d.plain_grace_out == credited
    assert d.band_minutes == (NET - missed) + credited


def test_each_boundary_is_judged_independently() -> None:
    """One boundary within the grace, the other beyond it: only the qualifying one is credited."""
    both_within = credit(10, 10)
    assert (both_within.plain_grace_in, both_within.plain_grace_out) == (10, 10)
    start_beyond = credit(11, 10)
    assert (start_beyond.plain_grace_in, start_beyond.plain_grace_out) == (0, 10)
    end_beyond = credit(10, 11)
    assert (end_beyond.plain_grace_in, end_beyond.plain_grace_out) == (10, 0)
    both_beyond = credit(11, 11)
    assert (both_beyond.plain_grace_in, both_beyond.plain_grace_out) == (0, 0)


def test_unequal_graces_are_each_applied_to_their_own_boundary() -> None:
    d = credit(30, 12, grace_in=30, grace_out=10)  # start exactly at its grace, end beyond its own
    assert (d.plain_grace_in, d.plain_grace_out) == (30, 0)


def test_a_mark_that_judges_a_miss_keeps_its_grace_portion() -> None:
    """D-01b reading 1: beyond the grace but judged by a mark band, the grace portion is credited
    with the beyond-grace mark credit (the standalone H-05 zero applies to unjudged misses)."""
    judged = credit(25, 0, in_judged=True)
    assert judged.plain_grace_in == 10 and judged.beyond_grace_credit == 15
    unjudged = credit(25, 0, in_judged=False)
    assert unjudged.plain_grace_in == 0 and unjudged.beyond_grace_credit == 0


# --- hour-band boundaries through the engine ---
# 09:00-18:00 with an unpaid 13:00-14:00 lunch (net 480), grace 10/10, bands ABSENT < 240,
# HALF_DAY 240-479, PRESENT >= 480, no late/early mark bands.


@pytest.mark.parametrize(
    ("out_hour", "out_minute", "worked", "status"),
    [
        (12, 59, 229, "ABSENT"),  # 229 + 10 (start within grace) = 239
        (13, 0, 230, "HALF_DAY"),  # 230 + 10 = 240: the half-day threshold, exactly
        (13, 1, 230, "HALF_DAY"),  # 13:00-14:00 is the unpaid lunch: no more worked time
    ],
)
def test_the_half_day_boundary_with_the_start_within_the_grace(
    out_hour: int, out_minute: int, worked: int, status: str
) -> None:
    """Arrives at 09:10 (exactly the grace) and leaves early beyond the grace: only the start earns
    credit. Before H-05 the early leaving also earned the full grace (the boundary was 220)."""
    result = _day([(9, 10, "IN"), (out_hour, out_minute, "OUT")])
    assert result.worked_minutes == worked
    assert result.attendance_status == status


def test_the_full_day_threshold_needs_the_credit_of_a_boundary_within_its_grace() -> None:
    within = _day([(9, 10, "IN"), (18, 0, "OUT")])  # 470 worked + 10
    assert within.attendance_status == "PRESENT"
    beyond = _day([(9, 11, "IN"), (18, 0, "OUT")])  # 469 worked, 11 missed: no credit
    assert beyond.attendance_status == "HALF_DAY"
    both = _day([(9, 10, "IN"), (17, 50, "OUT")])  # 460 worked + 10 + 10
    assert both.attendance_status == "PRESENT"
    end_beyond = _day([(9, 10, "IN"), (17, 49, "OUT")])  # 459 worked + 10 only
    assert end_beyond.attendance_status == "HALF_DAY"


def test_a_longer_shift_without_mark_bands_loses_the_grace_it_no_longer_earns() -> None:
    """The case R9 found: a 9-hour-net shift against an 8-hour full-day band. Arriving 70 minutes
    late (10 beyond the grace) was PRESENT only because 10 minutes of grace were credited."""
    nine_hours = {"scheduled_end": datetime(2026, 8, 10, 19, 0, tzinfo=UTC)}
    within = _day([(9, 10, "IN"), (19, 0, "OUT")], **nine_hours)  # 530 net of lunch
    assert within.attendance_status == "PRESENT"
    beyond = _day([(10, 10, "IN"), (19, 0, "OUT")], **nine_hours)  # 70 late; 470 worked
    assert beyond.worked_minutes == 470
    assert beyond.attendance_status == "HALF_DAY"
    assert _pay(beyond) == ("0.50", "0.50")


# --- nothing but the hour-band lookup moves ---


@pytest.mark.parametrize("late", [0, 5, 10, 11, 40, 75])
def test_worked_late_early_and_overtime_minutes_are_never_changed_by_the_grace_credit(
    late: int,
) -> None:
    punches = [(9, 0, "IN"), (18, 0, "OUT")]
    shifted = (
        [(9, late, "IN"), (18, 0, "OUT")] if late < 60 else [(10, late - 60, "IN"), (18, 0, "OUT")]
    )
    result = _day(shifted)
    plain = _day(punches)
    assert plain.late_minutes == 0
    assert result.late_minutes == max(late - 10, 0)  # raw late minus the grace, as before
    assert result.early_departure_minutes == 0
    assert result.worked_minutes == 480 - late


def test_overtime_is_the_same_whether_or_not_the_start_earned_grace_credit() -> None:
    """Same worked time, one day with the start inside the grace (credit 10), one just beyond it
    (credit 0): the detected overtime must be identical - the credit never feeds overtime."""
    within = _day([(9, 10, "IN"), (19, 0, "OUT")])  # 09:10 is exactly the grace
    beyond = _day([(9, 11, "IN"), (19, 1, "OUT")])  # one minute beyond the grace
    assert within.worked_minutes == beyond.worked_minutes == 530
    assert within.ot_minutes_detected == beyond.ot_minutes_detected > 0


# --- grace values 0 / 10 / 30 across the scenario grid ---


@pytest.mark.parametrize("grace", [0, 10, 30])
def test_at_every_grace_the_credit_is_the_miss_up_to_the_grace_and_zero_after(grace: int) -> None:
    for missed in range(0, 70):
        d = credit(missed, 0, grace_in=grace, grace_out=grace)
        expected = missed if missed <= grace else 0
        assert d.plain_grace_in == expected, (grace, missed)


# --- timezone regression: the rule is arithmetic on instants, so the zone must not matter ---


@pytest.mark.parametrize("zone", ["UTC", "Asia/Kolkata", "America/New_York"])
def test_the_rule_is_the_same_in_every_timezone(zone: str) -> None:
    tz = ZoneInfo(zone)
    for late, expected_in in [(10, 10), (11, 0)]:
        d = credit(late, 0, tz=tz)
        assert d.plain_grace_in == expected_in, (zone, late)
    # a New York day on which the clocks go back (2026-11-01): the instants, not the wall clock
    start = datetime(2026, 11, 1, 0, 30, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
    d = c.grace_band_credit_detail(
        first_in=start + timedelta(minutes=10),
        last_out=start + timedelta(hours=8),
        start_anchor=start,
        end_anchor=start + timedelta(hours=8),
        grace_in_minutes=10,
        grace_out_minutes=10,
        worked_minutes=470,
        net_scheduled_minutes=NET,
    )
    assert d.plain_grace_in == 10
