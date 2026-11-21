"""R-C01 — "why this result": a plain-language explanation of one stored attendance day.

`explain()` is a pure function. It reads the day the engine already decided (the stored row and its
`computation_snapshot`) and the policy version that governed it, and writes the reason in words.
It never recomputes a verdict: every threshold it quotes comes from the policy's own bands, and
every figure from the row. If the facts for a sentence are not on hand it says less, not something
invented. Clients render the result; they do not derive it.

Contract: `docs/audits/attendance-complete-audit-2026-11-19/ATTENDANCE_UI_UX_IMPROVEMENT_PLAN.md`
section 4. `action` (R-C02) is set only for an INCOMPLETE day: the deadline is the end of the open
attendance period (the cutoff the reminders name) and the consequence follows the policy's
`incomplete_at_lock_behaviour`, with the engine's own rule that a day with no punches at all
resolves as absent whatever the company chose (H-02). `overtime` (R-C03) comes from the day's
overtime record when one exists, else from the figures stored on the day.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from hrms.modules.attendance.calculation import day_has_no_punches


@dataclass(frozen=True)
class PolicyBand:
    """One worked-hours band of the policy version in force."""

    min_minutes: int
    max_minutes: int | None
    result_status: str


@dataclass(frozen=True)
class PolicyFacts:
    """The parts of the governing attendance policy version the explanation may quote."""

    name: str | None
    grace_in_minutes: int
    grace_out_minutes: int
    hour_bands: Sequence[PolicyBand]
    incomplete_at_lock_behaviour: str | None = None


class ExplanationVerdict(BaseModel):
    status: str
    label: str
    tone: str


class ExplanationFact(BaseModel):
    key: str
    label: str
    value: str


class ExplanationPay(BaseModel):
    paid: str | None
    unpaid: str | None
    leave: str | None
    label: str


class ExplanationOvertime(BaseModel):
    found_min: int
    approved_min: int
    pending_min: int
    class_label: str | None


class ExplanationAction(BaseModel):
    kind: str
    deadline: str | None
    consequence: str


@dataclass(frozen=True)
class OvertimeFacts:
    """The day's overtime record, when one exists."""

    minutes_detected: int
    minutes_approved: int
    status: str
    classification_code: str | None


class DayExplanation(BaseModel):
    verdict: ExplanationVerdict
    reason: str
    facts: list[ExplanationFact]
    rules_applied: list[str]
    pay: ExplanationPay
    overtime: ExplanationOvertime | None
    action: ExplanationAction | None = None
    provisional: bool


# -- formatting helpers ------------------------------------------------------------------------


def _duration(minutes: int) -> str:
    """`3 h 50 m`, `45 m`, `6 h`."""
    minutes = max(0, int(minutes))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} h {rest} m"
    if hours:
        return f"{hours} h"
    return f"{rest} m"


def _clock(value: str | None, timezone: str) -> str | None:
    """`10:05` in the day's own timezone, from the ISO timestamp the day read carries."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is not None:
            moment = moment.astimezone(ZoneInfo(timezone))
    except (ValueError, KeyError):
        return None
    return moment.strftime("%H:%M")


def _days(fraction: str | None) -> str | None:
    """`1 day`, `0.5 day`, or None when nothing."""
    try:
        value = Decimal(str(fraction))
    except (ArithmeticError, ValueError):
        return None
    if value <= 0:
        return None
    text = f"{value.normalize():f}"
    return f"{text} {'day' if value <= 1 else 'days'}"


def _band_text(band: PolicyBand) -> str:
    low = _duration(band.min_minutes)
    if band.max_minutes is None:
        return f"{low} or more"
    return f"{low} to {_duration(band.max_minutes)}"


def _status_band(policy: PolicyFacts | None, status: str) -> PolicyBand | None:
    if policy is None:
        return None
    return next((b for b in policy.hour_bands if b.result_status == status), None)


def _band_for(policy: PolicyFacts | None, minutes: int) -> PolicyBand | None:
    if policy is None:
        return None
    for band in policy.hour_bands:
        if minutes >= band.min_minutes and (band.max_minutes is None or minutes < band.max_minutes):
            return band
    return None


def _policy_phrase(policy: PolicyFacts | None) -> str:
    return f" under the {policy.name} policy" if policy and policy.name else ""


# -- the explanation ---------------------------------------------------------------------------


def explain(
    day: Any,
    policy: PolicyFacts | None,
    *,
    shift_name: str | None = None,
    correction_deadline: date | None = None,
    overtime_record: OvertimeFacts | None = None,
) -> DayExplanation:
    """Explain one stored day. `day` is an `AttendanceDayRead` (read by attribute, so a test may
    pass any object with the same fields); `policy` is the version that governed the day, or None
    when it could not be loaded, in which case no threshold is quoted."""
    status: str = day.attendance_status
    snapshot: dict[str, Any] = day.computation_snapshot or {}
    display = day.display
    tz = day.timezone
    worked = int(day.worked_minutes or 0)
    first_in = _clock(day.actual_first_in, tz)
    last_out = _clock(day.actual_last_out, tz)
    provisional = bool(display.provisional) if display is not None else False
    rules: list[str] = []

    facts: list[ExplanationFact] = []
    start = _clock(day.scheduled_start, tz)
    end = _clock(day.scheduled_end, tz)
    if start and end:
        shift_text = f"{start} – {end}"
        if day.scheduled_minutes:
            shift_text += f" ({_duration(day.scheduled_minutes)} to work)"
        facts.append(ExplanationFact(key="scheduled", label="Shift", value=shift_text))
    if first_in:
        facts.append(ExplanationFact(key="first_in", label="First in", value=first_in))
    if last_out:
        facts.append(ExplanationFact(key="last_out", label="Last out", value=last_out))
    if policy and (policy.grace_in_minutes or policy.grace_out_minutes):
        facts.append(
            ExplanationFact(
                key="grace",
                label="Grace",
                value=f"{policy.grace_in_minutes} min in, {policy.grace_out_minutes} min out",
            )
        )
    if day.late_minutes:
        facts.append(
            ExplanationFact(key="late", label="Late by", value=_duration(day.late_minutes))
        )
    if day.early_departure_minutes:
        facts.append(
            ExplanationFact(
                key="early_out",
                label="Left early by",
                value=_duration(day.early_departure_minutes),
            )
        )
    full_band = _status_band(policy, "PRESENT")
    if full_band is not None and full_band.min_minutes:
        facts.append(
            ExplanationFact(
                key="required", label="Full day needs", value=_duration(full_band.min_minutes)
            )
        )
    if worked or first_in:
        facts.append(ExplanationFact(key="worked", label="Worked", value=_duration(worked)))
    if day.actual_break_minutes:
        text = _duration(day.actual_break_minutes)
        if day.unpaid_break_minutes:
            text += f" ({_duration(day.unpaid_break_minutes)} unpaid)"
        facts.append(ExplanationFact(key="breaks", label="Breaks", value=text))

    reason = _reason(day, status, policy, snapshot, worked, first_in, provisional, rules)
    action = _action(day, policy, correction_deadline) if not provisional else None
    if action is not None:
        by = f" Fix it by {correction_deadline:%d %b}." if correction_deadline else ""
        reason = f"{reason}{by} {action.consequence}."
    if day.late_classification and day.late_classification != "NONE":
        rules.append(f"late_band:{day.late_classification}")
    if day.early_departure_classification and day.early_departure_classification != "NONE":
        rules.append(f"early_band:{day.early_departure_classification}")
    if "grace_band_credit" in snapshot:
        rules.append("grace_credit")
    if day.is_regularized:
        rules.append("regularized")

    paid = _days(day.paid_day_fraction)
    unpaid = _days(day.lop_fraction)
    leave = _days(day.leave_fraction)
    return DayExplanation(
        verdict=ExplanationVerdict(
            status=display.code if display is not None else status,
            label=display.label if display is not None else status.replace("_", " ").title(),
            tone=display.tone if display is not None else "neutral",
        ),
        reason=reason,
        facts=facts,
        rules_applied=rules,
        pay=ExplanationPay(
            paid=paid, unpaid=unpaid, leave=leave, label=_pay_label(paid, unpaid, leave)
        ),
        overtime=_overtime(day, overtime_record),
        action=action,
        provisional=provisional,
    )


def _pay_label(paid: str | None, unpaid: str | None, leave: str | None) -> str:
    parts = []
    if paid:
        parts.append(f"{paid} paid")
    if leave:
        parts.append(f"{leave} leave")
    if unpaid:
        parts.append(f"{unpaid} unpaid")
    return ", ".join(parts) if parts else "No pay effect"


def _overtime(day: Any, record: OvertimeFacts | None) -> ExplanationOvertime | None:
    """Found / approved / pending. A record is the authority (payroll pays `minutes_approved`);
    without one, the figures stored on the day."""
    if record is not None:
        found = int(record.minutes_detected or 0)
        approved = int(record.minutes_approved or 0)
        pending = max(0, found - approved) if record.status == "PENDING" else 0
        label = record.classification_code
    else:
        found = int(day.ot_minutes_detected or 0)
        approved = int(day.ot_minutes_approved or 0)
        pending = max(0, found - approved) if day.ot_pending else 0
        label = day.ot_classification
    if found <= 0:
        return None
    return ExplanationOvertime(
        found_min=found, approved_min=approved, pending_min=pending, class_label=label
    )


#: What happens to an INCOMPLETE day that is still unfixed when the period closes.
_LOCK_CONSEQUENCE = {
    "TREAT_ABSENT": "Counts as absent (unpaid) if not fixed",
    "TREAT_PRESENT": "Counts as present if not fixed",
    "KEEP_INCOMPLETE": "Stays incomplete and HR cannot close the period until it is settled",
}


def _action(
    day: Any, policy: PolicyFacts | None, deadline: date | None
) -> ExplanationAction | None:
    """R-C02 — what to do about an INCOMPLETE day, by when, and what happens if nothing is done."""
    if day.attendance_status != "INCOMPLETE" or day.is_locked:
        return None
    behaviour = (policy.incomplete_at_lock_behaviour if policy else None) or "TREAT_ABSENT"
    no_punches = day_has_no_punches(
        day.computation_snapshot, day.actual_first_in, day.actual_last_out
    )
    if no_punches and behaviour == "TREAT_PRESENT":
        behaviour = "TREAT_ABSENT"  # H-02: a day with no punches at all is absent at close
    consequence = _LOCK_CONSEQUENCE.get(behaviour, _LOCK_CONSEQUENCE["TREAT_ABSENT"])
    return ExplanationAction(
        kind="REQUEST_CORRECTION",
        deadline=deadline.isoformat() if deadline else None,
        consequence=consequence,
    )


def _reason(
    day: Any,
    status: str,
    policy: PolicyFacts | None,
    snapshot: dict[str, Any],
    worked: int,
    first_in: str | None,
    provisional: bool,
    rules: list[str],
) -> str:
    if provisional:
        since = f" since {first_in}" if first_in else ""
        return f"Working{since}. The result is final after the shift ends."

    holiday = day.holiday_name
    if status == "NOT_JOINED":
        return "Not employed yet on this date. No attendance expected."
    if status == "EXITED":
        return "No longer employed on this date. No attendance expected."
    if status == "NOT_EXPECTED":
        if day.calendar_day_type == "HOLIDAY":
            return (
                f"{holiday} (holiday). No work expected."
                if holiday
                else "Holiday. No work expected."
            )
        if day.calendar_day_type == "WEEKLY_OFF":
            return "Weekly off. No work expected."
        return "Not a working day for this employee. No work expected."
    if status == "CONFIG_ERROR":
        rules.append(f"config:{snapshot.get('terminal_reason') or 'unknown'}")
        return "We couldn't calculate this day. HR has been told."
    if status == "LEAVE":
        return _leave_reason(day, snapshot)
    if status == "ON_DUTY":
        return "On duty away from the office. Counted as a full paid day."
    if status == "INCOMPLETE":
        rules.append("missing_punch")
        if first_in:
            return (
                f"Punched in at {first_in} with no punch out. Send a correction request to fix it."
            )
        return "No punches on a working day. Send a correction request if you worked."
    if status == "HALF_DAY":
        return _half_day_reason(day, policy, snapshot, worked, rules)
    if status == "ABSENT":
        if not first_in and worked == 0:
            return "No punches on a working day."
        band = _status_band(policy, "ABSENT")
        if band is not None and band.max_minutes is not None:
            rules.append("hour_band:ABSENT")
            return (
                f"Worked {_duration(worked)}. Under {_duration(band.max_minutes)} counts as absent"
                f"{_policy_phrase(policy)}."
            )
        return f"Worked {_duration(worked)}, which counts as absent."
    if status == "PRESENT":
        target = f" of {_duration(day.scheduled_minutes)}" if day.scheduled_minutes else ""
        timing = "On time." if not day.late_minutes else f"Late by {_duration(day.late_minutes)}."
        if day.late_classification in (None, "NONE") or not day.late_minutes:
            return f"Worked {_duration(worked)}{target}. {timing}"
        return f"Worked {_duration(worked)}{target}. {timing} Still counted as a full day."
    return f"Marked {status.replace('_', ' ').lower()}."


def _half_day_reason(
    day: Any, policy: PolicyFacts | None, snapshot: dict[str, Any], worked: int, rules: list[str]
) -> str:
    if "half_day_leave" in snapshot:
        rules.append("half_day_leave")
        half = snapshot["half_day_leave"].get("leave_half")
        which = f" ({str(half).lower()})" if half else ""
        return f"Half day of leave{which}; the other half was worked."
    if day.late_classification == "HALF_DAY":
        rules.append("late_band:HALF_DAY")
        return (
            f"Arrived {_clock(day.actual_first_in, day.timezone) or 'late'}, "
            f"{_duration(day.late_minutes)} late. Arriving this late counts as a half day"
            f"{_policy_phrase(policy)}."
        )
    if day.early_departure_classification == "HALF_DAY":
        rules.append("early_band:HALF_DAY")
        return (
            f"Left {_duration(day.early_departure_minutes)} early. Leaving this early counts as a "
            f"half day{_policy_phrase(policy)}."
        )
    band = _band_for(policy, worked)
    if band is not None and band.result_status == "HALF_DAY":
        rules.append("hour_band:HALF_DAY")
        full = _status_band(policy, "PRESENT")
        needs = (
            f" A full day needs {_duration(full.min_minutes)};" if full and full.min_minutes else ""
        )
        verdict = f"{_band_text(band)} is a half day{_policy_phrase(policy)}."
        return f"Worked {_duration(worked)}.{needs} {verdict}"
    return f"Worked {_duration(worked)}, which counts as a half day."


def _leave_reason(day: Any, snapshot: dict[str, Any]) -> str:
    fraction = _days(day.leave_fraction)
    if "half_day_leave" in snapshot or (fraction and fraction.startswith("0.5")):
        return "Half day of leave; the other half was worked or is unpaid."
    return "On leave for the full day (paid)." if fraction else "On leave."
