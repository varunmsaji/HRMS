"""Shift-window rule for self-service punches — pure, no I/O (the service resolves the shifts).

Only one thing is ever refused: a punch-IN earlier than `early_in_allowance_minutes` before the
shift starts. Late punches, punch-OUTs and punches after the shift ended are recorded as they
always were (the calculation engine marks lateness; a punch after shift end + grace-out is only
reported here as `AFTER_SHIFT` so the caller can log it).

A punch just after midnight can belong to the previous date's overnight shift, so the caller
passes both that shift and the one for the punch's own local date; the punch is accepted when
either allows it.

Weekly offs and holidays are not an input. An authorized rostered shift, a holiday-working
roster, or an assigned shift that operates on an off day does not bypass this window: the
resolved shift (the same one calculation uses) still defines the earliest punch-in. A non-working
day does not, by itself, let an employee punch earlier than that. Whether self-service punches
should be refused entirely on a day the employee is not expected to work is a separate product
decision and is intentionally not decided here — punches remain facts for the engine.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

ShiftWindowOutcome = Literal["NO_SHIFT", "ALLOWED", "AFTER_SHIFT", "TOO_EARLY"]


@dataclass(frozen=True)
class ShiftSpan:
    """One resolved shift as UTC instants (`calculation.resolve_schedule_window`)."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class ShiftWindowDecision:
    outcome: ShiftWindowOutcome
    #: The shift of the punch's own local date; None only for `NO_SHIFT`.
    shift: ShiftSpan | None = None
    #: `shift.start` minus the allowance; None when the policy sets no early limit.
    earliest_punch_in: datetime | None = None


def evaluate_shift_window(
    *,
    direction: str,
    punch_time: datetime,
    current: ShiftSpan | None,
    previous: ShiftSpan | None,
    early_in_allowance_minutes: int | None,
    grace_out_minutes: int,
) -> ShiftWindowDecision:
    """`current` is the shift resolved for the punch's local date, `previous` the one for the day
    before. No `current` shift means nothing to compare with: the punch goes through and the
    policy's `missing_shift_behaviour` stays a calculation matter, exactly as before."""
    if current is None:
        return ShiftWindowDecision("NO_SHIFT")
    grace_out = timedelta(minutes=grace_out_minutes)
    earliest = (
        current.start - timedelta(minutes=early_in_allowance_minutes)
        if early_in_allowance_minutes is not None
        else None
    )
    # An overnight shift that started yesterday and is still running (or within its grace-out).
    in_previous = (
        previous is not None
        and previous.start - timedelta(minutes=early_in_allowance_minutes or 0) <= punch_time
        and punch_time <= previous.end + grace_out
    )
    if direction == "IN" and earliest is not None and punch_time < earliest and not in_previous:
        return ShiftWindowDecision("TOO_EARLY", current, earliest)
    if punch_time > current.end + grace_out and not in_previous:
        return ShiftWindowDecision("AFTER_SHIFT", current, earliest)
    return ShiftWindowDecision("ALLOWED", current, earliest)


def combine_shift_window_decisions(
    decisions: list[ShiftWindowDecision],
) -> ShiftWindowDecision:
    """Fold candidate dates into one decision.

    Branch-local and shift-local calendar dates can differ across midnight. The punch is refused
    only when every candidate is `TOO_EARLY`. An allowed punch, a punch after shift end, or a
    date with no shift wins, so an ambiguous date fails open instead of refusing a punch that
    one of the resolutions would record. When every candidate is `TOO_EARLY`, the first decision
    (the branch-local date) is the one shown to the employee.
    """
    if not decisions:
        return ShiftWindowDecision("NO_SHIFT")
    if all(item.outcome == "TOO_EARLY" for item in decisions):
        return decisions[0]
    for outcome in ("ALLOWED", "AFTER_SHIFT", "NO_SHIFT"):
        for item in decisions:
            if item.outcome == outcome:
                return item
    return decisions[0]
