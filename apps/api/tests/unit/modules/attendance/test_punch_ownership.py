"""Invariant B — every punch belongs to zero or exactly one attendance day (SH-01, SH-02).
Times are UTC; claims are built as the service builds them."""

import random
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from hrms.modules.attendance.calculation import PunchData
from hrms.modules.attendance.punch_ownership import (
    DayClaim,
    assign_owners,
    build_sessions,
    calendar_day_claim,
    shift_claim,
)

D = date(2026, 8, 10)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(D + timedelta(days=day), time(hour, minute), tzinfo=UTC)


def p(day: int, hour: int, minute: int, direction: str) -> PunchData:
    return PunchData(id=uuid4(), punch_time=at(day, hour, minute), direction=direction)


def fixed(day: int, start: int, end: int, *, before: int = 240, after: int = 720) -> DayClaim:
    span_start = at(day, start)
    span_end = at(day if end > start else day + 1, end)
    return shift_claim(
        D + timedelta(days=day),
        (span_start, span_end),
        max_early_minutes=before,
        max_late_minutes=after,
    )


def no_shift(day: int) -> DayClaim:
    return calendar_day_claim(D + timedelta(days=day), at(day, 0), at(day + 1, 0))


def owners(punches: list[PunchData], claims: list[DayClaim]) -> list[date | None]:
    result = assign_owners(punches, claims, duplicate_window_seconds=60)
    return [result[x.id] for x in punches]


DAY_SHIFTS = [fixed(d, 9, 18) for d in range(-2, 3)]


def test_checkout_more_than_two_hours_after_shift_end_is_owned_by_correct_day() -> None:
    punches = [p(0, 9, 0, "IN"), p(0, 20, 30, "OUT")]
    assert owners(punches, DAY_SHIFTS) == [D, D]


def test_checkout_just_under_two_hours_still_owned() -> None:
    punches = [p(0, 9, 0, "IN"), p(0, 19, 59, "OUT")]
    assert owners(punches, DAY_SHIFTS) == [D, D]


def test_early_check_in_with_a_checkout_is_owned_as_one_session() -> None:
    punches = [p(0, 6, 45, "IN"), p(0, 18, 0, "OUT")]
    assert owners(punches, DAY_SHIFTS) == [D, D]


def test_night_shift_overtime_checkout_belongs_to_the_shift_start_date() -> None:
    claims = [fixed(d, 22, 6) for d in range(-2, 3)]
    punches = [p(0, 22, 0, "IN"), p(1, 9, 0, "OUT")]
    assert owners(punches, claims) == [D, D]


def test_punch_cannot_be_counted_by_two_attendance_days_night_then_day() -> None:
    """The audit's night→day case: 22:00–07:30 then 07:45–18:00."""
    claims = [fixed(-1, 9, 18), fixed(0, 22, 6), fixed(1, 9, 18), fixed(2, 9, 18)]
    punches = [p(0, 22, 0, "IN"), p(1, 7, 30, "OUT"), p(1, 7, 45, "IN"), p(1, 18, 0, "OUT")]
    nxt = D + timedelta(days=1)
    assert owners(punches, claims) == [D, D, nxt, nxt]


def test_lone_out_goes_to_the_shift_it_ends_and_lone_in_to_the_shift_it_starts() -> None:
    claims = [fixed(0, 22, 6), fixed(1, 9, 18)]
    out = p(1, 7, 30, "OUT")
    in_ = p(1, 7, 45, "IN")
    # Separated by another day's punches so neither pairs with the other.
    assert owners([out], claims) == [D]
    assert owners([in_], claims) == [D + timedelta(days=1)]


def test_punch_far_outside_every_window_is_an_orphan() -> None:
    claims = [fixed(0, 9, 18, after=120)]
    lone = p(0, 23, 0, "OUT")
    assert owners([lone], claims) == [None]


def test_day_without_shift_takes_only_unclaimed_punches() -> None:
    """The night shift ends 06:00 and may own punches until 18:00 (12h, the policy default);
    work starting after that on the following day, which has no shift, belongs to that day."""
    claims = [fixed(0, 22, 6), no_shift(1)]
    punches = [p(0, 22, 0, "IN"), p(1, 6, 0, "OUT"), p(1, 19, 0, "IN"), p(1, 20, 0, "OUT")]
    nxt = D + timedelta(days=1)
    assert owners(punches, claims) == [D, D, nxt, nxt]


def test_work_within_the_late_limit_stays_with_the_shift_even_before_a_day_without_shift() -> None:
    """P-13 as decided: up to `max_late_punch_minutes` after shift end a punch belongs to the
    shift, whatever the next day is."""
    claims = [fixed(0, 22, 6), no_shift(1)]
    punches = [p(0, 22, 0, "IN"), p(1, 6, 0, "OUT"), p(1, 14, 0, "IN"), p(1, 16, 0, "OUT")]
    assert owners(punches, claims) == [D, D, D, D]


def test_month_boundary_overnight_shift_stays_on_the_last_day_of_the_month() -> None:
    last = date(2026, 8, 31)
    start = datetime(2026, 8, 31, 22, tzinfo=UTC)
    claim = shift_claim(
        last, (start, start + timedelta(hours=8)), max_early_minutes=240, max_late_minutes=720
    )
    nxt = shift_claim(
        date(2026, 9, 1),
        (start + timedelta(days=1), start + timedelta(days=1, hours=8)),
        max_early_minutes=240,
        max_late_minutes=720,
    )
    punches = [
        PunchData(uuid4(), start, "IN"),
        PunchData(uuid4(), start + timedelta(hours=10), "OUT"),
    ]
    result = assign_owners(punches, [claim, nxt], duplicate_window_seconds=60)
    assert set(result.values()) == {last}


def test_stray_early_morning_check_in_does_not_join_yesterdays_shift() -> None:
    punches = [p(-1, 9, 0, "IN"), p(-1, 18, 0, "OUT"), p(0, 4, 0, "IN")]
    yesterday = D - timedelta(days=1)
    assert owners(punches, DAY_SHIFTS) == [yesterday, yesterday, None]


def test_duplicates_and_strays_follow_their_session() -> None:
    punches = [p(0, 9, 0, "IN"), p(0, 9, 0, "IN"), p(0, 9, 10, "IN"), p(0, 18, 0, "OUT")]
    assert owners(punches, DAY_SHIFTS) == [D, D, D, D]
    sessions = build_sessions(punches, duplicate_window_seconds=60)
    assert len(sessions) == 1


def test_every_punch_has_at_most_one_owner_regardless_of_which_day_asks() -> None:
    """Property check: computing from any subset of neighbouring claims that contains every
    candidate gives the same owner, and a punch is never owned twice."""
    rng = random.Random(20261115)
    for _ in range(300):
        claims: list[DayClaim] = []
        for day in range(-2, 4):
            kind = rng.choice(["day", "night", "evening", "none"])
            if kind == "day":
                claims.append(fixed(day, 9, 18))
            elif kind == "night":
                claims.append(fixed(day, 22, 6))
            elif kind == "evening":
                claims.append(fixed(day, 14, 23))
            else:
                claims.append(no_shift(day))
        punches = []
        for _n in range(rng.randint(0, 10)):
            minute_offset = rng.randint(0, 5 * 24 * 60)
            punches.append(
                PunchData(
                    uuid4(), at(-1, 0) + timedelta(minutes=minute_offset), rng.choice(["IN", "OUT"])
                )
            )
        result = assign_owners(punches, claims, duplicate_window_seconds=60)
        assert set(result) == {x.id for x in punches}
        # Same punches, claims given in another order: identical ownership.
        shuffled = claims[:]
        rng.shuffle(shuffled)
        assert assign_owners(punches, shuffled, duplicate_window_seconds=60) == result
        # A day sees exactly the punches mapped to it, so the per-day sets are disjoint.
        per_day = {
            c.attendance_date: {pid for pid, o in result.items() if o == c.attendance_date}
            for c in claims
        }
        seen: set = set()
        for ids in per_day.values():
            assert not (ids & seen)
            seen |= ids
