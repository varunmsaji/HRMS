"""Punch ownership (Invariant B, SH-01/SH-02) — which attendance day a punch belongs to. Pure, no
I/O; `ownership_service.py` resolves the claims and loads the punches.

Before engine 13 each day loaded every punch within two hours of its shift. A checkout more than
two hours after shift end was read by no day at all, and neighbouring days' windows overlapped,
so one punch could be counted on two days. Here every punch has exactly one owner, or none.

**Claims.** Each candidate day claims a *span* (the work it expects) and a *window* around it:

* shift day: span = scheduled work; window = span widened by the day's attendance policy
  `max_early_punch_minutes` before and `max_late_punch_minutes` after;
* day without a shift: span = none; window = the local calendar day. Such a day only takes
  what no shift day claims.

**Sessions.** Punches are put in order, duplicates and strays are folded into the punch they
repeat (the same rules the engine applies), and the rest are paired IN→OUT. A pair, or a lone
punch, is a *session*, and a session is never split between days.

**Assignment.** A session goes to a shift day whose window it overlaps (a lone IN only to a
shift that has not yet ended, a lone OUT only to one that has started). With several, the one
whose span it overlaps most wins; with no overlap, the nearest (a lone IN is measured to span
starts, a lone OUT to span ends); ties go to the earlier date. Failing that, a day without a
shift whose calendar day the session starts in takes it. Otherwise the punches are orphans.

The result for a punch depends only on the punches and the claims, never on which day is being
calculated, so two days can never both own it.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from hrms.modules.attendance.calculation import (
    STRAY_PUNCH_WINDOW_MINUTES,
    PunchData,
    ScheduleWindow,
    ShiftInputs,
    punches_in_order,
)


@dataclass(frozen=True, slots=True)
class DayClaim:
    attendance_date: date
    #: Expected work. None for a day without a shift.
    span_start: datetime | None
    span_end: datetime | None
    #: Half-open `[window_start, window_end)`.
    window_start: datetime
    window_end: datetime

    @property
    def has_shift(self) -> bool:
        return self.span_start is not None and self.span_end is not None


def ownership_span(
    shift: ShiftInputs | None, window: ScheduleWindow
) -> tuple[datetime, datetime] | None:
    """The work a shift day expects. FIXED and SPLIT: the scheduled span. FLEXIBLE: from the
    start of the start window to its end plus the required minutes (the latest legitimate end)."""
    if shift is None or window.scheduled_start is None or window.scheduled_end is None:
        return None
    if shift.shift_type == "FLEXIBLE":
        required = timedelta(minutes=shift.required_minutes or 0)
        return window.scheduled_start, window.scheduled_end + required
    return window.scheduled_start, window.scheduled_end


def shift_claim(
    attendance_date: date,
    span: tuple[datetime, datetime],
    *,
    max_early_minutes: int,
    max_late_minutes: int,
) -> DayClaim:
    start, end = span
    return DayClaim(
        attendance_date=attendance_date,
        span_start=start,
        span_end=end,
        window_start=start - timedelta(minutes=max_early_minutes),
        # +1 minute keeps a punch at exactly `end + max_late` inside the half-open window.
        window_end=end + timedelta(minutes=max_late_minutes, seconds=60),
    )


def calendar_day_claim(attendance_date: date, day_start: datetime, day_end: datetime) -> DayClaim:
    return DayClaim(
        attendance_date=attendance_date,
        span_start=None,
        span_end=None,
        window_start=day_start,
        window_end=day_end,
    )


@dataclass(frozen=True, slots=True)
class Session:
    start: datetime
    end: datetime
    #: Every raw punch in the session, including folded duplicates and strays.
    punch_ids: tuple[UUID, ...]
    #: For a lone punch, its direction; None for a pair.
    lone_direction: str | None
    #: For a pair, the raw punches standing for its IN and for its OUT (so the pair can be split
    #: again, see `split_pair`). Empty for a lone punch.
    in_ids: tuple[UUID, ...] = ()
    out_ids: tuple[UUID, ...] = ()


def build_sessions(punches: list[PunchData], *, duplicate_window_seconds: int) -> list[Session]:
    """Mirrors `collapse_duplicate_punches` then `drop_stray_punches` then `pair_punches`, but
    keeps track of which raw punches each kept punch stands for."""
    kept: list[PunchData] = []
    members: dict[UUID, list[UUID]] = {}
    for punch in punches_in_order(punches):
        prev = kept[-1] if kept else None
        if (
            prev is not None
            and punch.direction == prev.direction
            and (punch.punch_time - prev.punch_time).total_seconds() <= duplicate_window_seconds
        ):
            members[prev.id].append(punch.id)
            continue
        kept.append(punch)
        members[punch.id] = [punch.id]

    folded: list[PunchData] = []
    for punch in kept:
        prev = folded[-1] if folded else None
        if (
            prev is None
            or punch.direction != prev.direction
            or punch.punch_time - prev.punch_time > timedelta(minutes=STRAY_PUNCH_WINDOW_MINUTES)
        ):
            folded.append(punch)
        elif punch.direction == "IN":
            members[prev.id].extend(members.pop(punch.id))
        else:
            members[punch.id] = members.pop(prev.id) + members[punch.id]
            folded[-1] = punch

    sessions: list[Session] = []
    pending: PunchData | None = None
    for punch in folded:
        if punch.direction == "IN":
            if pending is not None:
                sessions.append(_lone(pending, members))
            pending = punch
        elif pending is not None:
            sessions.append(
                Session(
                    start=pending.punch_time,
                    end=punch.punch_time,
                    punch_ids=tuple(members[pending.id] + members[punch.id]),
                    lone_direction=None,
                    in_ids=tuple(members[pending.id]),
                    out_ids=tuple(members[punch.id]),
                )
            )
            pending = None
        else:
            sessions.append(_lone(punch, members))
    if pending is not None:
        sessions.append(_lone(pending, members))
    return sessions


def _lone(punch: PunchData, members: dict[UUID, list[UUID]]) -> Session:
    return Session(
        start=punch.punch_time,
        end=punch.punch_time,
        punch_ids=tuple(members[punch.id]),
        lone_direction=punch.direction,
    )


def _overlap_seconds(session: Session, claim: DayClaim) -> float:
    assert claim.span_start is not None and claim.span_end is not None
    return max(
        0.0,
        (min(session.end, claim.span_end) - max(session.start, claim.span_start)).total_seconds(),
    )


def _distance_seconds(session: Session, claim: DayClaim) -> float:
    assert claim.span_start is not None and claim.span_end is not None
    if session.lone_direction == "IN":
        return abs((session.start - claim.span_start).total_seconds())
    if session.lone_direction == "OUT":
        return abs((session.end - claim.span_end).total_seconds())
    if session.end <= claim.span_start:
        return (claim.span_start - session.end).total_seconds()
    return max(0.0, (session.start - claim.span_end).total_seconds())


def _in_window(session: Session, claim: DayClaim) -> bool:
    return session.start < claim.window_end and session.end >= claim.window_start


def _can_claim(session: Session, claim: DayClaim) -> bool:
    """A lone IN cannot start work for a shift that has already ended, and a lone OUT cannot
    end work for a shift that has not started: a stray 04:00 check-in is not part of
    yesterday's 09:00-18:00 shift, even though it falls inside yesterday's late limit."""
    if not _in_window(session, claim):
        return False
    assert claim.span_start is not None and claim.span_end is not None
    if session.lone_direction == "IN":
        return session.start <= claim.span_end
    if session.lone_direction == "OUT":
        return session.end >= claim.span_start
    return True


def owner_of(session: Session, claims: list[DayClaim]) -> date | None:
    shift_claims = [c for c in claims if c.has_shift and _can_claim(session, c)]
    if shift_claims:
        overlapping = [c for c in shift_claims if _overlap_seconds(session, c) > 0]
        if overlapping:
            best = max(
                overlapping,
                key=lambda c: (_overlap_seconds(session, c), -c.attendance_date.toordinal()),
            )
        else:
            best = min(
                shift_claims,
                key=lambda c: (_distance_seconds(session, c), c.attendance_date.toordinal()),
            )
        return best.attendance_date
    for claim in claims:
        if not claim.has_shift and claim.window_start <= session.start < claim.window_end:
            return claim.attendance_date
    return None


def split_pair(session: Session) -> tuple[Session, Session]:
    """N-03 - an IN-OUT pair taken apart into a lone IN and a lone OUT."""
    assert session.lone_direction is None
    return (
        Session(session.start, session.start, session.in_ids, "IN"),
        Session(session.end, session.end, session.out_ids, "OUT"),
    )


def _outruns_owner(session: Session, owner: date | None, claims: list[DayClaim]) -> bool:
    """N-03 - a pair whose OUT lies at or beyond the end of its owning shift day's window.
    Only a shift day's window is a statement about how long its work can last; a day without
    a shift has no schedule to outrun."""
    if owner is None or session.lone_direction is not None:
        return False
    claim = next((c for c in claims if c.attendance_date == owner), None)
    return claim is not None and claim.has_shift and session.end >= claim.window_end


def assign_owners(
    punches: list[PunchData], claims: list[DayClaim], *, duplicate_window_seconds: int
) -> dict[UUID, date | None]:
    """`{punch_id: owning date, or None for an orphan}` for every punch given.

    N-03: a pair is never one work session longer than its day's window. A forgotten OUT followed
    by a next-morning OUT used to pair into a single 24-hour session owned by the first day, with
    about 15 hours of overtime. Such a pair is split into its IN and its OUT, which are then
    owned separately as lone punches: the IN stays with the day it started (INCOMPLETE, no
    checkout), the OUT goes to the day that can take it, or is an orphan. Neither day is paid
    work nobody can vouch for; both need a regularization."""
    owners: dict[UUID, date | None] = {}
    for session in build_sessions(punches, duplicate_window_seconds=duplicate_window_seconds):
        owner = owner_of(session, claims)
        if _outruns_owner(session, owner, claims):
            for part in split_pair(session):
                part_owner = owner_of(part, claims)
                for punch_id in part.punch_ids:
                    owners[punch_id] = part_owner
            continue
        for punch_id in session.punch_ids:
            owners[punch_id] = owner
    return owners
