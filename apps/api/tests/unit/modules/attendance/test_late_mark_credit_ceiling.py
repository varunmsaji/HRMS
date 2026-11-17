"""R-2 (owner decision D-01b): the combined, per-policy-version mark-credit ceiling.

D-01 lets a late or early *mark* (a band classified `NONE` / `LATE` / `EARLY_DEPARTURE`) stand as
the whole verdict on the minutes beyond the grace, so a day a few minutes short of the full-day
hours band is not also a half day. Engine 16 as first written credited every minute a mark band
covered (a `LATE` 31-240 band turned a four-hour day into a full paid day), and the first fix
bounded it at 59 minutes *per end* with the grace folded in. The approved rule is:

    plain_grace  = min(raw_in, grace_in) + min(raw_out, grace_out)       # separate, additional
    qualifying_x = max(raw_x - grace_x, 0) if end x is judged by a mark band, else 0
    beyond       = min(qualifying_in + qualifying_out, ceiling)          # ONE ceiling per day
    credit       = plain_grace + beyond

`ceiling` is `PolicyInputs.mark_credit_ceiling_minutes` (default 59, stored per policy version,
0-120; 0 means no beyond-grace mark credit). The beyond-grace credit is allocated to the late end
first, then the early end - for the snapshot only; the hour-band lookup sees only the sum.

Part 1 tests `grace_band_credit_detail` directly on an 8-hour shift (net 480): the cases A-H of the
decision brief and the boundaries. Part 2 runs whole days through the engine: 09:00-18:00 UTC with
an unpaid 13:00-14:00 lunch (net 480), grace 10/10, ABSENT < 240, HALF_DAY 240-479, PRESENT >= 480.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.unit.modules.attendance.test_attendance_rules_remediation import (
    _LATE_BANDS,
    _day,
    _pay,
)
from tests.unit.modules.attendance.test_calculation import _policy

from hrms.modules.attendance import calculation as c
from hrms.modules.attendance.calculation import BandData
from hrms.modules.attendance.schemas import (
    MARK_CREDIT_CEILING_DEFAULT,
    MARK_CREDIT_CEILING_MAX,
    MARK_CREDIT_CEILING_MIN,
)

START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
END = START + timedelta(hours=8)
NET = 480


def credit(
    late: int,
    early: int,
    *,
    grace_in: int = 10,
    grace_out: int = 10,
    ceiling: int = 59,
    in_judged: bool = True,
    out_judged: bool = True,
) -> c.BandCredit:
    """One 8-hour day on which `late` minutes were missed at the start and `early` at the end."""
    return c.grace_band_credit_detail(
        first_in=START + timedelta(minutes=late),
        last_out=END - timedelta(minutes=early),
        start_anchor=START,
        end_anchor=END,
        grace_in_minutes=grace_in,
        grace_out_minutes=grace_out,
        worked_minutes=NET - late - early,
        net_scheduled_minutes=NET,
        late_judged=in_judged,
        early_judged=out_judged,
        ceiling_minutes=ceiling,
    )


def total_credit(d: c.BandCredit) -> int:
    return d.credit_in + d.credit_out


# --- Part 1a: the decision brief's cases A-H ---


@pytest.mark.parametrize(
    ("case", "args", "credit_minutes", "band", "qualifying", "beyond"),
    [
        ("A late 40, grace 10", dict(late=40, early=0), 40, 480, 30, 30),
        ("B late 75, beyond the ceiling", dict(late=75, early=0), 69, 474, 65, 59),
        ("C both ends qualify (40 + 40)", dict(late=40, early=40), 79, 479, 60, 59),
        ("D combined exceeds the ceiling (70 + 70)", dict(late=70, early=70), 79, 419, 120, 59),
        (
            "E grace 80 is greater than the ceiling 59",
            dict(late=90, early=0, grace_in=80, grace_out=80),
            90,
            480,
            10,
            10,
        ),
        ("F ceiling zero, late 40", dict(late=40, early=0, ceiling=0), 10, 450, 30, 0),
        ("G ceiling zero, late 5 (inside grace)", dict(late=5, early=0, ceiling=0), 5, 480, 0, 0),
        (
            "H ceiling 120, late 100 + early 100",
            dict(late=100, early=100, ceiling=120),
            140,
            420,
            180,
            120,
        ),
    ],
)
def test_the_decision_brief_cases(
    case: str,
    args: dict[str, int],
    credit_minutes: int,
    band: int,
    qualifying: int,
    beyond: int,
) -> None:
    d = credit(**args)
    assert total_credit(d) == credit_minutes, case
    assert d.band_minutes == band, case
    assert d.qualifying_in + d.qualifying_out == qualifying, case
    assert d.beyond_grace_credit == beyond, case


def test_both_ends_qualifying_is_one_ceiling_not_two() -> None:
    """The per-end rule gave 59 at each end (118); the approved rule gives 59 for the day."""
    d = credit(late=70, early=70)
    assert d.qualifying_in == 60 and d.qualifying_out == 60
    assert d.beyond_grace_credit == 59  # not 118
    assert d.capped is True


def test_grace_greater_than_the_ceiling_never_raises_the_ceiling() -> None:
    """`max(ceiling, grace)` is gone: a large grace is forgiven as plain grace, and the ceiling
    still bounds only the minutes beyond it."""
    d = credit(late=200, early=0, grace_in=80, grace_out=80, ceiling=59)
    assert d.plain_grace_in == 80
    assert d.qualifying_in == 120
    assert d.beyond_grace_credit == 59
    assert total_credit(d) == 139  # 80 + 59, not 80 and not 120


def test_plain_grace_is_independent_of_the_ceiling() -> None:
    for ceiling in (0, 30, 59, 120):
        d = credit(late=8, early=6, ceiling=ceiling)
        assert (d.plain_grace_in, d.plain_grace_out) == (8, 6)
        assert d.beyond_grace_credit == 0  # nothing beyond the grace
        assert total_credit(d) == 14


# --- Part 1b: boundaries of the ceiling ---


@pytest.mark.parametrize("ceiling", [0, 1, 58, 59, 60, 119, 120])
def test_the_beyond_grace_credit_is_min_of_qualifying_and_ceiling(ceiling: int) -> None:
    for late, early in [(10 + 5, 0), (10 + 59, 0), (10 + 60, 0), (10 + 200, 0), (10 + 70, 10 + 70)]:
        d = credit(late, early, ceiling=ceiling)
        qualifying = max(late - 10, 0) + max(early - 10, 0)
        assert d.beyond_grace_credit == min(qualifying, ceiling), (late, early, ceiling)
        assert d.capped is (qualifying > ceiling)


def test_zero_ceiling_means_no_beyond_grace_credit_at_all() -> None:
    d = credit(late=100, early=100, ceiling=0)
    assert d.beyond_grace_credit == 0
    assert total_credit(d) == 20  # plain grace only
    assert d.band_minutes == (NET - 200) + 20


def test_a_negative_ceiling_is_treated_as_zero() -> None:
    """The API and the database refuse it; the engine never runs on a negative credit."""
    assert credit(late=40, early=0, ceiling=-5).beyond_grace_credit == 0


@pytest.mark.parametrize(
    ("in_judged", "out_judged", "expected_qualifying", "grace_in", "grace_out"),
    [
        (True, True, 60, 10, 10),
        (True, False, 30, 10, 0),  # H-05: the unjudged end missed beyond its grace earns nothing
        (False, True, 30, 0, 10),
        (False, False, 0, 0, 0),
    ],
)
def test_only_the_ends_a_mark_band_judges_qualify(
    in_judged: bool,
    out_judged: bool,
    expected_qualifying: int,
    grace_in: int,
    grace_out: int,
) -> None:
    """A miss beyond the grace earns plain grace credit only where a mark judges it (H-05 +
    D-01b reading 1: the grace portion of a qualifying mark is credited with the mark)."""
    d = credit(late=40, early=40, in_judged=in_judged, out_judged=out_judged)
    assert d.qualifying_in + d.qualifying_out == expected_qualifying
    assert (d.plain_grace_in, d.plain_grace_out) == (grace_in, grace_out)


def test_the_credit_never_lifts_the_day_above_its_schedule_or_below_its_work() -> None:
    d = credit(late=40, early=0, ceiling=120)
    assert d.band_minutes <= NET
    d = credit(late=0, early=0)
    assert d.band_minutes == NET


# --- Part 1c: allocation is late end first, and reporting only ---


@pytest.mark.parametrize(
    ("late", "early", "ceiling", "alloc_in", "alloc_out"),
    [
        (40, 50, 59, 30, 29),  # 30 + 40 qualify, ceiling 59: late takes 30, early the rest
        (40, 50, 20, 20, 0),  # the ceiling is spent on the late end first
        (40, 50, 30, 30, 0),
        (40, 50, 31, 30, 1),
        (10, 60, 59, 0, 50),  # nothing qualifies late: all goes to the early end
        (40, 50, 120, 30, 40),  # ceiling above both: each end is credited what qualified
    ],
)
def test_the_beyond_grace_credit_is_allocated_late_first_then_early(
    late: int, early: int, ceiling: int, alloc_in: int, alloc_out: int
) -> None:
    d = credit(late, early, ceiling=ceiling)
    assert d.credit_in - d.plain_grace_in == alloc_in
    assert d.credit_out - d.plain_grace_out == alloc_out
    assert alloc_in + alloc_out == d.beyond_grace_credit
    assert alloc_in <= d.qualifying_in and alloc_out <= d.qualifying_out


@pytest.mark.parametrize("split", [(60, 0), (0, 60), (30, 30), (10, 50), (45, 15)])
def test_how_the_credit_is_allocated_cannot_change_the_band_minutes(split: tuple[int, int]) -> None:
    """The same total beyond-grace minutes missed, split differently between the two ends, give
    the same hour-band minutes: only the sum of the credit reaches the lookup."""
    q_in, q_out = split
    d = credit(late=10 + q_in, early=10 + q_out)
    baseline = credit(late=10 + 30, early=10 + 30)
    assert d.beyond_grace_credit == baseline.beyond_grace_credit == 59
    assert d.band_minutes == baseline.band_minutes == 479


# --- Part 2: whole days through the engine ---

_BROAD_LATE = [BandData(min_minutes=1, max_minutes=240, classification="LATE")]
_BROAD_EARLY = [BandData(min_minutes=1, max_minutes=240, classification="EARLY_DEPARTURE")]


def _policy_with(ceiling: int | None = None, **overrides: object) -> c.PolicyInputs:
    base = _policy(grace_in_minutes=10, grace_out_minutes=10, **overrides)
    return base if ceiling is None else replace(base, mark_credit_ceiling_minutes=ceiling)


def test_the_review_reproduction_a_four_hour_day_is_a_half_day_not_a_full_day() -> None:
    """Arrive 13:00, leave 18:00: 240 minutes worked, 230 late beyond grace. A `LATE` 31-240 band
    once paid this as PRESENT; the ceiling keeps it a half day."""
    punches = [(13, 0, "IN"), (18, 0, "OUT")]
    broad = [BandData(min_minutes=31, max_minutes=240, classification="LATE")]
    with_band = _day(punches, late_bands=broad)
    without_band = _day(punches)
    assert without_band.attendance_status == with_band.attendance_status == "HALF_DAY"
    assert _pay(with_band) == _pay(without_band) == ("0.50", "0.50")


def test_the_mark_itself_is_still_recorded_when_the_hours_decide() -> None:
    result = _day([(13, 0, "IN"), (18, 0, "OUT")], late_bands=_BROAD_LATE)
    assert result.worked_minutes == 240
    assert result.late_minutes == 230
    assert result.is_late is True
    assert result.late_classification == "LATE"


def test_a_mark_inside_the_ceiling_still_spares_the_day_as_d01_intended() -> None:
    """09:11 on an exactly-480 shift is a late mark, not a half day (the shipped 1-59 template)."""
    result = _day([(9, 11, "IN"), (18, 0, "OUT")], late_bands=_LATE_BANDS)
    assert result.attendance_status == "PRESENT"
    credit_ = result.snapshot["grace_band_credit"]
    assert credit_["in"] == 11  # 10 plain grace + 1 beyond grace
    assert credit_["capped"] is False


def test_an_open_ended_none_band_cannot_buy_a_full_day() -> None:
    open_ended = [BandData(min_minutes=1, max_minutes=None, classification="NONE")]
    result = _day([(11, 0, "IN"), (18, 0, "OUT")], late_bands=open_ended)
    assert result.worked_minutes == 360
    assert result.attendance_status == "HALF_DAY"
    assert _pay(result) == ("0.50", "0.50")


def test_both_ends_marked_share_one_ceiling_and_cost_half_a_day() -> None:
    """Case C through the engine. 09:40 in and 17:20 out: 40 minutes lost at each end, both
    marked, 400 worked. Credit = 10 + 10 plain + min(30 + 30, 59) = 79 -> 479, one minute short
    of a full day. (The per-end rule credited 59 at each end and paid this in full.)"""
    result = _day(
        [(9, 40, "IN"), (17, 20, "OUT")],
        late_bands=_BROAD_LATE,
        early_bands=_BROAD_EARLY,
    )
    snap = result.snapshot["grace_band_credit"]
    assert result.worked_minutes == 400
    assert snap["plain_grace"] == {"in": 10, "out": 10}
    assert snap["qualifying_beyond_grace"] == {"in": 30, "out": 30, "total": 60}
    assert snap["beyond_grace_credit"] == {"total": 59, "allocated_in": 30, "allocated_out": 29}
    assert snap["band_minutes"] == 479
    assert snap["capped"] is True
    assert result.attendance_status == "HALF_DAY"
    assert _pay(result) == ("0.50", "0.50")


@pytest.mark.parametrize(
    ("ceiling", "status", "pay"),
    [
        (0, "HALF_DAY", ("0.50", "0.50")),
        (59, "HALF_DAY", ("0.50", "0.50")),  # 479
        (60, "PRESENT", ("1.00", "0.00")),  # 480: the per-policy ceiling is what changes it
        (120, "PRESENT", ("1.00", "0.00")),
    ],
)
def test_the_policy_versions_ceiling_decides_the_borderline_day(
    ceiling: int, status: str, pay: tuple[str, str]
) -> None:
    result = _day(
        [(9, 40, "IN"), (17, 20, "OUT")],
        policy=_policy_with(ceiling),
        late_bands=_BROAD_LATE,
        early_bands=_BROAD_EARLY,
    )
    assert result.attendance_status == status
    assert _pay(result) == pay
    assert result.snapshot["grace_band_credit"]["ceiling"] == ceiling


def test_a_zero_ceiling_gives_no_mark_credit_but_keeps_grace() -> None:
    """09:40 in, 18:00 out, `LATE` band: 440 worked. Ceiling 59 -> 10 + 30 credit -> 480 PRESENT.
    Ceiling 0 -> only the 10 minutes of grace -> 450, a half day. Inside grace is unaffected."""
    punches = [(9, 40, "IN"), (18, 0, "OUT")]
    assert _day(punches, policy=_policy_with(59), late_bands=_BROAD_LATE).attendance_status == (
        "PRESENT"
    )
    none = _day(punches, policy=_policy_with(0), late_bands=_BROAD_LATE)
    assert none.attendance_status == "HALF_DAY"
    assert none.snapshot["grace_band_credit"]["band_minutes"] == 450
    inside_grace = _day([(9, 10, "IN"), (18, 0, "OUT")], policy=_policy_with(0), late_bands=[])
    assert inside_grace.attendance_status == "PRESENT"  # 470 worked + 10 plain grace


def test_a_grace_larger_than_the_ceiling_is_still_fully_forgiven() -> None:
    """Grace 80 > ceiling 59 (case E): arrive 10:30, `LATE` band after the grace, leave 18:00.
    390 worked + 80 plain grace + 10 beyond = 480. Under `max(ceiling, grace)` this was 470."""
    result = _day(
        [(10, 30, "IN"), (18, 0, "OUT")],
        policy=_policy(grace_in_minutes=80, grace_out_minutes=10),
        late_bands=_BROAD_LATE,
    )
    snap = result.snapshot["grace_band_credit"]
    assert snap["plain_grace"]["in"] == 80
    assert snap["qualifying_beyond_grace"]["in"] == 10
    assert snap["band_minutes"] == 480
    assert result.attendance_status == "PRESENT"


def test_the_snapshot_keeps_the_complete_credit_calculation() -> None:
    result = _day([(13, 0, "IN"), (18, 0, "OUT")], late_bands=_BROAD_LATE)
    snap = result.snapshot["grace_band_credit"]
    assert snap["ceiling"] == c.DEFAULT_MARK_CREDIT_CEILING_MINUTES == 59
    assert snap["capped"] is True
    assert snap["plain_grace"] == {"in": 10, "out": 0}
    assert snap["qualifying_beyond_grace"] == {"in": 230, "out": 0, "total": 230}
    assert snap["beyond_grace_credit"] == {"total": 59, "allocated_in": 59, "allocated_out": 0}
    assert (snap["in"], snap["out"]) == (69, 0)
    assert snap["worked_minutes"] == 240
    assert snap["net_scheduled_minutes"] == 480
    assert snap["band_minutes"] == 309


def test_a_missing_punch_day_records_no_credit() -> None:
    result = _day([(9, 5, "IN")])
    snap = result.snapshot["grace_band_credit"]
    assert result.attendance_status == "INCOMPLETE"
    assert (snap["in"], snap["out"], snap["band_minutes"]) == (0, 0, 0)
    assert snap["beyond_grace_credit"]["total"] == 0


@pytest.mark.parametrize("arrive_hour", range(9, 16))
@pytest.mark.parametrize("arrive_minute", [0, 15, 45])
@pytest.mark.parametrize("leave_hour", [14, 16, 17, 18])
@pytest.mark.parametrize("ceiling", [0, 59, 120])
def test_no_full_day_is_paid_for_more_than_grace_plus_the_ceiling_of_unworked_time(
    arrive_hour: int, arrive_minute: int, leave_hour: int, ceiling: int
) -> None:
    """Invariant over a grid of arrivals, departures and ceilings: a day paid in full was either
    worked in full, or short only by the plain grace (10 + 10) plus the day's ONE ceiling."""
    if (arrive_hour, arrive_minute) >= (leave_hour, 0):
        pytest.skip("arrives after leaving")
    result = _day(
        [(arrive_hour, arrive_minute, "IN"), (leave_hour, 0, "OUT")],
        policy=_policy_with(ceiling),
        late_bands=_BROAD_LATE,
        early_bands=_BROAD_EARLY,
    )
    if result.paid_day_fraction == "1.00" and result.attendance_status == "PRESENT":
        assert result.worked_minutes + 10 + 10 + ceiling >= 480, (
            f"paid a full day for {result.worked_minutes} worked minutes at ceiling {ceiling}"
        )
    snap = result.snapshot["grace_band_credit"]
    assert snap["beyond_grace_credit"]["total"] <= ceiling
    assert snap["in"] + snap["out"] == (
        snap["plain_grace"]["in"]
        + snap["plain_grace"]["out"]
        + snap["beyond_grace_credit"]["total"]
    )


# --- the stored default, bounds and the engine default stay one number ---


def test_the_schema_bounds_and_the_engine_default_agree() -> None:
    assert MARK_CREDIT_CEILING_DEFAULT == c.DEFAULT_MARK_CREDIT_CEILING_MINUTES == 59
    assert (MARK_CREDIT_CEILING_MIN, MARK_CREDIT_CEILING_MAX) == (0, 120)
    assert _policy().mark_credit_ceiling_minutes == 59
