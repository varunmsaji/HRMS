"""Attendance calculation engine (W4 — docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md
§19, WD-10/WD-11).

Split the same way `organisation/calendar_resolution.py` is split: everything in this module is
a pure, side-effect-free function or dataclass — no DB access, directly unit-testable. The
DB-touching orchestration (loading punches/policies/shift, writing `AttendanceDay`) lives in
`attendance/service.py`, which calls `evaluate_day` once every input has been resolved and
converts the result into ORM rows.

Implements architecture §19.1 steps 3, 8-18 as small, separately callable stages (steps 1-2,
4-7 — employment gate, assignment, shift/calendar/policy resolution — happen in
`service.py` by calling the existing `employee.service`/`organisation.calendar_resolution`/
`attendance.resolution` seams; nothing here re-implements them, per the plan's reuse mandate).

Known, documented simplifications (not silent gaps):

- SPLIT shifts: each `ShiftDutyBlock` is checked for at least one punch pair overlapping it;
  a block with none is "missed" and `split_shift_missed_block_behaviour` applies. Partial
  overlap within a block is not further sub-analysed (e.g. a block worked for only half its
  span is treated as satisfied, not partially credited) — the architecture does not specify a
  finer contract, and the task brief's own instruction is to build mechanisms the policy
  configures, not invent new undocumented granularity.
- `AttendancePolicyVersion` (W3) has no "auto-deduct a scheduled break with no punched gap"
  field (architecture §10.2 names `DEDUCT_SCHEDULED` as a *behaviour*, but W3 never added the
  corresponding column). Adding one would be an out-of-scope schema change to a table W3 owns.
  W4 therefore only deducts unpaid minutes for *detected* gaps (matched against `ShiftBreak`
  windows); a mandatory break with zero punched gap is not silently deducted — documented as a
  known limitation, not invented behaviour.
- (W7, WD-29 decision 3) `OvertimePolicyInputs.remaining_weekly_minutes`/
  `remaining_monthly_minutes` make a day's detected OT depend on sibling-day state computed by
  `service.py` immediately before calling `evaluate_day`. This means `evaluate_day` is **not**
  strictly idempotent across that one dimension: recomputing the same day with unchanged punches
  can still produce a different `ot_minutes_detected` if a sibling day's `overtime_record` state
  changed in between. Accepted and documented, not silently discovered — see WD-29.
- (W9) Half-day leave's "computed only on the working half" (§19.4) is implemented as a flat
  0.50 contribution from whatever the punch-derived outcome already produced, not a minute-by-
  minute re-evaluation restricted to one half of the shift — the same block-level-not-finer-
  grained simplification `_evaluate_split` already applies to SPLIT shift duty blocks. See
  `_apply_leave_overlay` and decision log WD-31.
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from hrms.shared.timezone import TimezoneConfigurationError, resolve_zoneinfo

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PunchData:
    id: UUID
    punch_time: datetime  # tz-aware, UTC
    direction: str  # IN | OUT


@dataclass(frozen=True, slots=True)
class ShiftBreakData:
    id: UUID
    break_kind: str  # FIXED_WINDOW | FLEXIBLE_DURATION
    start_time: time | None
    end_time: time | None
    window_start: time | None
    window_end: time | None
    min_minutes: int | None
    max_minutes: int | None
    is_paid: bool
    is_mandatory: bool


@dataclass(frozen=True, slots=True)
class ShiftDutyBlockData:
    sequence: int
    start_time: time
    end_time: time
    crosses_midnight: bool


@dataclass(frozen=True, slots=True)
class BandData:
    min_minutes: int
    max_minutes: int | None
    classification: str  # result_status / classification, both use this field name here


@dataclass(frozen=True, slots=True)
class OvertimeRateRowData:
    day_class: str
    classification_code: str


@dataclass(frozen=True, slots=True)
class PolicyInputs:
    """The subset of `AttendancePolicyVersion` fields the engine reads (W3 model, unchanged)."""

    grace_in_minutes: int
    grace_out_minutes: int
    punch_rounding: str
    rounding_minutes: int | None
    missing_punch_behaviour: str
    missing_shift_behaviour: str
    half_day_split: str
    half_day_boundary_minutes: int | None
    multi_punch_mode: str
    duplicate_punch_window_seconds: int
    core_hours_breach_behaviour: str
    early_out_uses_core_end: bool
    split_shift_missed_block_behaviour: str
    excess_break_behaviour: str
    incomplete_at_lock_behaviour: str
    work_on_leave_behaviour: str
    # WD-32 — cumulative-day counters and early-departure/on-duty enforcement. `None` count
    # means "no cumulative rule configured" (matches `daily_cap_minutes`'s own None-means-
    # uncapped convention elsewhere in this module).
    lates_to_half_day_count: int | None = None
    excess_break_days_to_half_day_count: int | None = None
    early_departure_requires_approval: bool = False
    on_duty_requires_punch: bool = False


@dataclass(frozen=True, slots=True)
class OvertimePolicyInputs:
    """The subset of `OvertimePolicyVersion` fields the engine reads (W3 model, unchanged)."""

    eligibility: str  # SHIFT_FLAG | ALWAYS | NEVER | GRADE_VIA_ASSIGNMENT
    min_ot_minutes: int
    rounding_minutes: int | None
    rounding_mode: str
    requires_post_approval: bool
    daily_cap_minutes: int | None
    comp_off_instead_of_pay: bool
    night_ot_mode: str  # SHIFT_FLAG | WINDOW | BOTH
    night_window_start: time | None
    night_window_end: time | None
    rate_rows: list[OvertimeRateRowData] = field(default_factory=list)
    # W7 (WD-29 decision 3) — sibling-day cumulative budget remaining for this employee's ISO
    # week / calendar month, computed by `service.py` (DB access) before calling this pure
    # engine. `None` means uncapped, matching `daily_cap_minutes`'s own convention.
    remaining_weekly_minutes: int | None = None
    remaining_monthly_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class ShiftInputs:
    shift_type: str | None  # None => no shift resolved
    is_ot_eligible: bool
    operates_on_holiday: bool
    operates_on_weekly_off: bool
    is_cross_midnight: bool
    breaks: list[ShiftBreakData] = field(default_factory=list)
    duty_blocks: list[ShiftDutyBlockData] = field(default_factory=list)
    core_start: time | None = None
    core_end: time | None = None
    required_minutes: int | None = None  # FLEXIBLE


@dataclass(frozen=True, slots=True)
class LeaveOverlayEntry:
    """One active (`APPROVED`, not `CANCELLED`) `LeaveDayProjection` row for this employee-date
    (W9 — architecture §21). `fraction` is Decimal-as-str (`"0.50"`/`"1.00"`), matching
    `AttendanceCalculationResult.paid_day_fraction`'s own convention. `half` is carried through
    for snapshot/provenance only — the overlay's own arithmetic (`_apply_leave_overlay`) only
    ever needs the fraction and `is_paid`."""

    fraction: str
    is_paid: bool
    half: str | None = None


@dataclass(frozen=True, slots=True)
class AttendanceCalculationInput:
    employee_id: UUID
    attendance_date: date
    timezone: str
    population_status: str  # ACTIVE | NOT_JOINED | EXITED
    calendar_day_type: str | None  # None => CONFIG_ERROR (no calendar resolved)
    holiday_name: str | None
    holiday_on_weekly_off: bool
    shift: ShiftInputs | None
    scheduled_start: datetime | None  # UTC, None if no fixed/flex window resolvable
    scheduled_end: datetime | None
    policy: PolicyInputs | None  # None => CONFIG_ERROR (no attendance policy resolved)
    hour_bands: list[BandData] = field(default_factory=list)
    late_bands: list[BandData] = field(default_factory=list)
    early_bands: list[BandData] = field(default_factory=list)
    ot_policy: OvertimePolicyInputs | None = None
    punches: list[PunchData] = field(default_factory=list)
    # W5 (architecture §9.7, WD-27) — set from a PUBLISHED `ShiftRoster` row for this
    # employee-date, if one exists. Roster overrides only change expectation-of-presence in
    # `evaluate_day`; they never touch `calendar_day_type` (WD-04/WD-07).
    roster_week_off_override: bool = False
    roster_holiday_working_override: bool = False
    # W9 (architecture §21) — active approved leave projections for this employee-date, resolved
    # by `service.py` from `LeaveDayProjection` before calling this pure engine, mirroring how
    # the roster overrides above are resolved. Empty list => overlay is a no-op.
    leave_entries: list[LeaveOverlayEntry] = field(default_factory=list)
    # WD-32 decision 2/3 — count of *prior* qualifying days (late-beyond-grace / excess-break)
    # for this employee within the policy's trailing counting window, excluding this date itself
    # (mirrors `OvertimePolicyInputs.remaining_weekly_minutes`'s "sibling-day sum computed by
    # service.py, combined with this day's own fresh computation inside the pure engine" shape,
    # WD-29 decision 3). Resolved by `service.py`; 0 when no cumulative rule is configured or
    # this is the first qualifying day in the window.
    prior_late_days_in_window: int = 0
    prior_excess_break_days_in_window: int = 0
    # WD-32 decision 5 — whether an `APPROVED` `EARLY_DEPARTURE_APPROVAL` regularization request
    # covers this date, resolved by `service.py`. Only consulted when
    # `PolicyInputs.early_departure_requires_approval` is True.
    early_departure_pre_approved: bool = False
    # WD-32 decision 6 — whether an `APPROVED` `ON_DUTY` regularization request covers this date,
    # resolved by `service.py`. Mirrors `leave_entries`: an empty/False value makes the overlay a
    # complete no-op.
    on_duty_approved: bool = False


@dataclass(frozen=True, slots=True)
class MatchedBreak:
    start: datetime
    end: datetime
    minutes: int
    is_paid: bool
    is_excess: bool
    shift_break_id: UUID | None


@dataclass(frozen=True, slots=True)
class PairingResult:
    pairs: list[tuple[PunchData, PunchData]]
    orphans: list[PunchData]


@dataclass(frozen=True, slots=True)
class AttendanceCalculationResult:
    attendance_status: str
    calendar_day_type: str | None
    holiday_name: str | None
    holiday_on_weekly_off: bool
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    scheduled_minutes: int | None
    actual_first_in: datetime | None
    actual_last_out: datetime | None
    worked_minutes: int
    unpaid_break_minutes: int
    paid_break_minutes: int
    excess_break_minutes: int
    breaks: list[MatchedBreak]
    late_minutes: int
    early_departure_minutes: int
    late_classification: str | None
    early_departure_classification: str | None
    missing_punch: bool
    auto_closed: bool
    is_late: bool
    is_early_out: bool
    is_overtime: bool
    worked_on_holiday: bool
    worked_on_weekly_off: bool
    paid_day_fraction: str  # Decimal-as-str, service layer converts
    lop_fraction: str
    ot_minutes_detected: int
    ot_minutes_approved: int
    ot_pending: bool
    ot_classification: str | None
    comp_off_minutes_earned: int
    # W7 — the day_class (NORMAL|WEEKLY_OFF|HOLIDAY|NIGHT) `ot_classification` was resolved
    # against, surfaced separately since `detect_overtime` only returns the policy-configured
    # `classification_code`, not the day_class it matched (WD-29).
    ot_day_class: str | None
    snapshot: dict[str, Any]
    # W9 — set only when an approved leave projection covers this day, punches exist despite it,
    # and policy `work_on_leave_behaviour=PRESENT_CANCEL_LEAVE_HINT`: the punch-derived outcome
    # is kept as-is and this flag tells Leave the application may need cancelling (§19.3).
    # Attendance never writes the leave ledger itself.
    work_on_leave_flagged: bool = False
    # WD-32 decision 1 — set whenever a FLEX shift's core hours are breached and
    # `core_hours_breach_behaviour != IGNORE` (independent of whether the breach also forced a
    # HALF_DAY/ABSENT status override).
    is_core_hours_breach: bool = False
    # WD-32 decision 6 — set only under `on_duty_requires_punch=True` ("keep punch status +
    # flag" mode, mirroring `work_on_leave_flagged`'s own shape); the `on_duty_requires_punch
    # =False` short-circuit path sets `attendance_status="ON_DUTY"` directly instead.
    is_on_duty_flagged: bool = False


# ---------------------------------------------------------------------------
# Timezone (WD-06)
# ---------------------------------------------------------------------------


def resolve_timezone(
    *, shift_version_timezone: str | None, branch_timezone: str | None, company_timezone: str
) -> str:
    """WD-06: `ShiftVersion.timezone` > `Branch.timezone` > `Company.timezone`."""
    return shift_version_timezone or branch_timezone or company_timezone


# ---------------------------------------------------------------------------
# Schedule window (§9.5 cross-midnight, §11.8 flexible)
# ---------------------------------------------------------------------------


def _local_to_utc(local_date: date, local_time: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(local_date, local_time, tzinfo=tz).astimezone(UTC)


def punch_window_utc(
    *,
    attendance_date: date,
    tz_name: str,
    start_time: time,
    end_time: time,
    is_cross_midnight: bool,
    lookback_hours: int = 2,
    lookahead_hours: int = 2,
) -> tuple[datetime, datetime]:
    """The UTC window punches are loaded from for a FIXED/FLEXIBLE shift on `attendance_date` —
    the scheduled span padded by `lookback_hours`/`lookahead_hours` so an early-arriving or
    auto-closed-late punch is still attributed to this date, not silently dropped. SPLIT shifts
    use `duty_block_window_utc` instead (multiple spans, not one)."""
    tz = ZoneInfo(tz_name)
    start = _local_to_utc(attendance_date, start_time, tz)
    end_date = attendance_date + timedelta(days=1) if is_cross_midnight else attendance_date
    end = _local_to_utc(end_date, end_time, tz)
    if end <= start:
        end = end + timedelta(days=1)
    return start - timedelta(hours=lookback_hours), end + timedelta(hours=lookahead_hours)


def scheduled_span_utc(
    *,
    attendance_date: date,
    tz_name: str,
    start_time: time,
    end_time: time,
    is_cross_midnight: bool,
) -> tuple[datetime, datetime]:
    """The exact scheduled span (no padding) — what gets stored as
    `AttendanceDay.scheduled_start`/`scheduled_end`."""
    tz = ZoneInfo(tz_name)
    start = _local_to_utc(attendance_date, start_time, tz)
    end_date = attendance_date + timedelta(days=1) if is_cross_midnight else attendance_date
    end = _local_to_utc(end_date, end_time, tz)
    if end <= start:
        end = end + timedelta(days=1)
    return start, end


def calendar_day_window_utc(*, attendance_date: date, tz_name: str) -> tuple[datetime, datetime]:
    """Plain 00:00-24:00 local window — used only when no shift resolves (NULL shift, DEC-018)
    so punches can still be loaded and evaluated without a scheduled span to anchor lateness."""
    tz = ZoneInfo(tz_name)
    start = _local_to_utc(attendance_date, time(0, 0), tz)
    end = _local_to_utc(attendance_date + timedelta(days=1), time(0, 0), tz)
    return start, end


def local_time_to_utc(attendance_date: date, local_time: time, tz_name: str) -> datetime:
    """Public wrapper around the module's local-time conversion — used by `service.py` for
    FLEXIBLE/SPLIT window math that doesn't fit `scheduled_span_utc`'s FIXED-only shape."""
    return _local_to_utc(attendance_date, local_time, ZoneInfo(tz_name))


@dataclass(frozen=True, slots=True)
class ScheduleWindow:
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    load_start: datetime
    load_end: datetime


def resolve_schedule_window(
    *,
    attendance_date: date,
    tz_name: str,
    shift: ShiftInputs | None,
    start_time: time | None,
    end_time: time | None,
    window_start: time | None,
    window_end: time | None,
) -> ScheduleWindow:
    """The one place that turns a resolved shift's raw local times into the UTC spans the rest
    of the pipeline needs: `scheduled_start`/`scheduled_end` (stored on `AttendanceDay`) and
    `load_start`/`load_end` (the padded window punches are loaded from, §19.1 step 9).

    - No shift: plain local calendar day, no scheduled span (missing-shift policy handles the
      status; punches are still loaded so an unscheduled presence isn't silently dropped).
    - FIXED: `scheduled_span_utc`/`punch_window_utc` (existing, cross-midnight-aware).
    - FLEXIBLE: the start *window* (`window_start`-`window_end`) doubles as the scheduled span
      for late/early comparison and as the punch-load window — architecture §11.8 defines
      lateness relative to `window_end`, not a single scheduled instant.
    - SPLIT: span from the first duty block's start to the last duty block's end; each block's
      own overlap is checked separately in `calculation.evaluate_day` (`_evaluate_split`).
    """
    tz = ZoneInfo(tz_name)
    if shift is None:
        start, end = calendar_day_window_utc(attendance_date=attendance_date, tz_name=tz_name)
        return ScheduleWindow(
            scheduled_start=None, scheduled_end=None, load_start=start, load_end=end
        )

    if shift.shift_type == "SPLIT" and shift.duty_blocks:
        first_block = min(shift.duty_blocks, key=lambda b: b.sequence)
        last_block = max(shift.duty_blocks, key=lambda b: b.sequence)
        sched_start = _local_to_utc(attendance_date, first_block.start_time, tz)
        end_date = (
            attendance_date + timedelta(days=1) if last_block.crosses_midnight else attendance_date
        )
        sched_end = _local_to_utc(end_date, last_block.end_time, tz)
        if sched_end <= sched_start:
            sched_end += timedelta(days=1)
        return ScheduleWindow(
            scheduled_start=sched_start,
            scheduled_end=sched_end,
            load_start=sched_start - timedelta(hours=2),
            load_end=sched_end + timedelta(hours=2),
        )

    if shift.shift_type == "FLEXIBLE" and window_start is not None and window_end is not None:
        sched_start = _local_to_utc(attendance_date, window_start, tz)
        sched_end = _local_to_utc(attendance_date, window_end, tz)
        if sched_end <= sched_start:
            sched_end += timedelta(days=1)
        return ScheduleWindow(
            scheduled_start=sched_start,
            scheduled_end=sched_end,
            load_start=sched_start - timedelta(hours=2),
            load_end=sched_end + timedelta(hours=12),
        )

    if start_time is not None and end_time is not None:
        sched_start, sched_end = scheduled_span_utc(
            attendance_date=attendance_date,
            tz_name=tz_name,
            start_time=start_time,
            end_time=end_time,
            is_cross_midnight=shift.is_cross_midnight,
        )
        load_start, load_end = punch_window_utc(
            attendance_date=attendance_date,
            tz_name=tz_name,
            start_time=start_time,
            end_time=end_time,
            is_cross_midnight=shift.is_cross_midnight,
        )
        return ScheduleWindow(
            scheduled_start=sched_start,
            scheduled_end=sched_end,
            load_start=load_start,
            load_end=load_end,
        )

    # Shift resolved but no usable timing (shouldn't happen for a published version, but fail
    # safe rather than raise — the missing-shift-style INCOMPLETE path handles a schedule-less
    # day gracefully).
    start, end = calendar_day_window_utc(attendance_date=attendance_date, tz_name=tz_name)
    return ScheduleWindow(scheduled_start=None, scheduled_end=None, load_start=start, load_end=end)


# ---------------------------------------------------------------------------
# Duplicate collapsing (§19.1 step 9, FR-ATT-017)
# ---------------------------------------------------------------------------


def collapse_duplicate_punches(punches: list[PunchData], *, window_seconds: int) -> list[PunchData]:
    """Consecutive punches of the **same direction** within `window_seconds` of the prior kept
    punch collapse to the first one (device/client resubmission, not a real second event).
    Punches must already be sorted by `punch_time`."""
    if not punches:
        return []
    kept = [punches[0]]
    for punch in punches[1:]:
        prev = kept[-1]
        if (
            punch.direction == prev.direction
            and (punch.punch_time - prev.punch_time).total_seconds() <= window_seconds
        ):
            continue
        kept.append(punch)
    return kept


# ---------------------------------------------------------------------------
# Punch pairing (§19.1 step 10, decision 7 of the plan — explicit `direction`)
# ---------------------------------------------------------------------------


def pair_punches(punches: list[PunchData]) -> PairingResult:
    """Deterministic IN/OUT pairing. Punches must already be sorted by `punch_time`.

    Consecutive `IN`s: the earlier one is an orphan (no matching `OUT` arrived before the next
    `IN`); the later one becomes the open `IN`. An `OUT` with no open `IN` is itself an orphan.
    A trailing open `IN` with no closing `OUT` is an orphan (missing-punch territory, resolved
    by `missing_punch_behaviour` upstream, not here)."""
    pairs: list[tuple[PunchData, PunchData]] = []
    orphans: list[PunchData] = []
    pending_in: PunchData | None = None

    for punch in punches:
        if punch.direction == "IN":
            if pending_in is not None:
                orphans.append(pending_in)
            pending_in = punch
        else:  # OUT
            if pending_in is not None:
                pairs.append((pending_in, punch))
                pending_in = None
            else:
                orphans.append(punch)

    if pending_in is not None:
        orphans.append(pending_in)

    return PairingResult(pairs=pairs, orphans=orphans)


def presence_span(
    pairs: list[tuple[PunchData, PunchData]], *, mode: str
) -> tuple[datetime | None, datetime | None, int, list[tuple[datetime, datetime]]]:
    """Returns `(first_in, last_out, gross_minutes, gap_intervals)`.

    `PAIR_ALL` sums every paired interval independently — gaps between pairs are excluded from
    `gross_minutes` up front (they are candidate breaks, matched separately).
    `FIRST_IN_LAST_OUT` treats the whole span from the first `IN` to the last `OUT` as gross
    presence; gaps are still returned so they can be matched/deducted as breaks the same way."""
    if not pairs:
        return None, None, 0, []

    first_in = pairs[0][0].punch_time
    last_out = pairs[-1][1].punch_time
    gaps = [
        (pairs[i][1].punch_time, pairs[i + 1][0].punch_time)
        for i in range(len(pairs) - 1)
        if pairs[i + 1][0].punch_time > pairs[i][1].punch_time
    ]

    if mode == "FIRST_IN_LAST_OUT":
        gross_minutes = int((last_out - first_in).total_seconds() // 60)
    else:  # PAIR_ALL
        gross_minutes = sum(
            int((out_p.punch_time - in_p.punch_time).total_seconds() // 60) for in_p, out_p in pairs
        )

    return first_in, last_out, gross_minutes, gaps


def worked_minutes_from_gross(
    gross_minutes: int, *, mode: str, paid_break_minutes: int, unpaid_break_minutes: int
) -> int:
    """§10.2: "unpaid break minutes are excluded from worked minutes... paid break minutes are
    included." The correct arithmetic depends on what `gross_minutes` already contains:

    - `PAIR_ALL`'s `gross_minutes` is the sum of clocked-in intervals only — every gap between
      pairs (paid or unpaid) is *already excluded* by construction (`presence_span`). Unpaid
      gaps therefore need no further subtraction here — subtracting them again would double
      -count the deduction. Paid gaps must be added *back*, since a paid break still counts
      toward worked time despite the employee having punched out.
    - `FIRST_IN_LAST_OUT`'s `gross_minutes` spans first-`IN` to last-`OUT` and so *includes*
      every intermediate gap. Unpaid gaps must be subtracted; paid gaps need no adjustment
      since they're already counted."""
    if mode == "FIRST_IN_LAST_OUT":
        return max(0, gross_minutes - unpaid_break_minutes)
    return gross_minutes + paid_break_minutes  # PAIR_ALL


# ---------------------------------------------------------------------------
# Breaks (§10.2)
# ---------------------------------------------------------------------------


def _break_window_contains(start: time, end: time | None, point: time) -> bool:
    """`SR-01` (execution gate §1.4) — Approach A, wrap-aware time-of-day containment, applied
    identically to `FIXED_WINDOW` (`start_time`/`end_time`) and `FLEXIBLE_DURATION`
    (`window_start`/`window_end`):

        end is None or end == start  ->  match only when point == start
                                          (a point-in-time break, never a 24-hour "always
                                          matches" window — this is the guard case 6 in the
                                          gate's scenario table depends on)
        start < end                  ->  match when start <= point <= end
                                          (ordinary same-day window, BYTE-IDENTICAL to the
                                          previous implementation — cases 1 and 4 in the gate's
                                          table are the regression guards this preserves)
        start > end                  ->  the window wraps past midnight;
                                          match when point >= start OR point <= end

    This is the ONLY change `SR-01` makes: `match_breaks` below still computes `gap_start_local`
    exactly as before (line untouched, `PC-15`), and neither its signature nor either call site
    changes. Approach B (rejected, §1.2) would have rebuilt UTC spans from the attendance date
    instead — CODE-PROVEN to regress case 4 (an after-midnight break on a night shift, already
    correct today) while fixing the same three cases this function fixes."""
    if end is None or end == start:
        return point == start
    if start < end:
        return start <= point <= end
    return point >= start or point <= end


def match_breaks(
    gaps: list[tuple[datetime, datetime]], shift_breaks: list[ShiftBreakData], *, tz_name: str
) -> list[MatchedBreak]:
    """Matches each detected punch gap against the configured `ShiftBreak`s by time overlap
    (local time-of-day comparison for `FIXED_WINDOW`/`FLEXIBLE_DURATION` window bounds). An
    unmatched gap defaults unpaid (conservative — architecture §10.2's default is that unpaid
    break minutes are excluded from worked minutes unless configured otherwise). A matched gap
    exceeding the break's `max_minutes` is flagged `is_excess`."""
    tz = ZoneInfo(tz_name)
    matched: list[MatchedBreak] = []
    for gap_start, gap_end in gaps:
        minutes = max(0, int((gap_end - gap_start).total_seconds() // 60))
        gap_start_local = gap_start.astimezone(tz).time()
        best: ShiftBreakData | None = None
        for shift_break in shift_breaks:
            if shift_break.break_kind == "FIXED_WINDOW" and shift_break.start_time is not None:
                if _break_window_contains(
                    shift_break.start_time, shift_break.end_time, gap_start_local
                ):
                    best = shift_break
                    break
            elif (
                shift_break.break_kind == "FLEXIBLE_DURATION"
                and shift_break.window_start is not None
            ):
                if _break_window_contains(
                    shift_break.window_start, shift_break.window_end, gap_start_local
                ):
                    best = shift_break
                    break
        is_paid = best.is_paid if best is not None else False
        is_excess = best is not None and best.max_minutes is not None and minutes > best.max_minutes
        matched.append(
            MatchedBreak(
                start=gap_start,
                end=gap_end,
                minutes=minutes,
                is_paid=is_paid,
                is_excess=is_excess,
                shift_break_id=best.id if best is not None else None,
            )
        )
    return matched


# ---------------------------------------------------------------------------
# Rounding (§11.6)
# ---------------------------------------------------------------------------


def round_minutes(value: int, *, mode: str, minutes: int | None) -> int:
    """Rounds a minute count to the nearest/up/down multiple of `minutes`. Shared by
    `apply_rounding` (punch instants) and `detect_overtime` (OT duration)."""
    if mode == "NONE" or not minutes:
        return value
    if mode == "UP":
        return -(-value // minutes) * minutes
    if mode == "DOWN":
        return (value // minutes) * minutes
    return round(value / minutes) * minutes  # NEAREST


def apply_rounding(instant: datetime, *, mode: str, minutes: int | None) -> datetime:
    """Evaluation-only rounding — the raw punch timestamp is never mutated (WD-11); this
    produces a *copy* used for late/early/worked-minutes math."""
    if mode == "NONE" or not minutes:
        return instant
    epoch_minutes = int(instant.timestamp() // 60)
    rounded = round_minutes(epoch_minutes, mode=mode, minutes=minutes)
    return datetime.fromtimestamp(rounded * 60, tz=UTC)


# ---------------------------------------------------------------------------
# Bands (§11.1)
# ---------------------------------------------------------------------------


def lookup_band(value: int, bands: list[BandData]) -> str | None:
    """First ordered band whose `[min_minutes, max_minutes]` (inclusive, `max_minutes=None`
    meaning open-ended) contains `value`. Bands are assumed pre-validated non-overlapping
    (W3 `InvalidPolicyBandError` at publish time) — the first match is *the* match."""
    for band in bands:
        if band.min_minutes <= value and (band.max_minutes is None or value <= band.max_minutes):
            return band.classification
    return None


_EARLY_BAND_SEVERITY = {"NONE": 0, "EARLY_DEPARTURE": 1, "HALF_DAY": 2, "ABSENT": 3}


def _harshest_band_classification(bands: list[BandData]) -> str | None:
    """WD-32 decision 5 — the most severe classification among a policy's *configured*
    early-departure bands, used to force an unapproved-but-required early departure to the worst
    outcome the policy actually set up — never invents a severity the policy didn't configure."""
    if not bands:
        return None
    return max((b.classification for b in bands), key=lambda c: _EARLY_BAND_SEVERITY.get(c, 0))


# ---------------------------------------------------------------------------
# Overtime (§12)
# ---------------------------------------------------------------------------


def classify_ot_day(
    *, is_holiday: bool, is_weekly_off: bool, is_night: bool, night_ot_mode: str
) -> str:
    """The day_class (NORMAL|WEEKLY_OFF|HOLIDAY|NIGHT) OT is classified against for rate-row
    lookup — extracted so `service.py` can recover it for `OvertimeRecord.day_class` (W7) without
    `detect_overtime` needing to change its tested return shape."""
    return (
        "HOLIDAY"
        if is_holiday
        else "WEEKLY_OFF"
        if is_weekly_off
        else "NIGHT"
        if (is_night and night_ot_mode in ("WINDOW", "BOTH"))
        else "NORMAL"
    )


def detect_overtime(
    *,
    worked_minutes: int,
    scheduled_minutes: int | None,
    is_shift_ot_eligible: bool,
    is_holiday: bool,
    is_weekly_off: bool,
    is_night: bool,
    policy: OvertimePolicyInputs | None,
) -> tuple[int, str | None, bool]:
    """Returns `(ot_minutes_detected, ot_classification, eligible)`. Detection only — no
    approval, no money (§12.2/ADR-0006). `eligible=False` short-circuits to
    `(0, None, False)` so the caller never has to re-check eligibility separately."""
    if policy is None:
        return 0, None, False
    if policy.eligibility == "NEVER":
        return 0, None, False
    if policy.eligibility == "SHIFT_FLAG" and not is_shift_ot_eligible:
        return 0, None, False

    excess = max(0, worked_minutes - (scheduled_minutes or worked_minutes))
    if excess < policy.min_ot_minutes:
        return 0, None, False

    if policy.rounding_minutes:
        excess = round_minutes(excess, mode=policy.rounding_mode, minutes=policy.rounding_minutes)

    if policy.daily_cap_minutes is not None:
        excess = min(excess, policy.daily_cap_minutes)
    if policy.remaining_weekly_minutes is not None:
        excess = min(excess, policy.remaining_weekly_minutes)
    if policy.remaining_monthly_minutes is not None:
        excess = min(excess, policy.remaining_monthly_minutes)

    day_class = classify_ot_day(
        is_holiday=is_holiday,
        is_weekly_off=is_weekly_off,
        is_night=is_night,
        night_ot_mode=policy.night_ot_mode,
    )
    classification = next(
        (row.classification_code for row in policy.rate_rows if row.day_class == day_class), None
    )
    return excess, classification, True


# ---------------------------------------------------------------------------
# Day evaluation (§19.1 steps 11-19, §19.4 overlay precedence)
# ---------------------------------------------------------------------------


def evaluate_day(inputs: AttendanceCalculationInput) -> AttendanceCalculationResult:
    """The full §19.1 pipeline (steps 3, 8-19) for a single employee-date, entirely in memory —
    every DB read has already happened in `service.py`. The regularization overlay (§19.1 step
    15) remains a no-op seam here — regularization is applied upstream as synthetic punches
    (WD-28 decision 1), never as a status branch inside this engine. The leave overlay (§19.1
    step 14/16, §19.4) is real as of W9: `_apply_leave_overlay` is applied once the punch-derived
    outcome is known, for every path except the population gate (NOT_JOINED/EXITED, which ranks
    above LEAVE in §19.4's precedence) and CONFIG_ERROR (nothing well-defined to overlay onto)."""
    snapshot: dict[str, Any] = {
        "inputs": {
            "employee_id": str(inputs.employee_id),
            "attendance_date": inputs.attendance_date.isoformat(),
            "timezone": inputs.timezone,
            "population_status": inputs.population_status,
            "calendar_day_type": inputs.calendar_day_type,
            "punch_ids": [str(p.id) for p in inputs.punches],
        }
    }

    # §19.1 step 1 — employment gate
    if inputs.population_status != "ACTIVE":
        status = "NOT_JOINED" if inputs.population_status == "NOT_JOINED" else "EXITED"
        return _terminal_result(status, inputs, snapshot)

    # `ED-10` (execution gate §4.3) — an unresolvable timezone must degrade this one
    # employee-date to CONFIG_ERROR, never raise past this function as an unhandled
    # `ZoneInfoNotFoundError` -> 500. Checked once, here, before any of the internal
    # `ZoneInfo(inputs.timezone)` constructions later in this module run, so none of them need
    # their own try/except — Phase 2's schema validators make this unreachable for any row
    # written after they shipped; this is the fail-safe for a row written before they existed.
    try:
        resolve_zoneinfo(inputs.timezone)
    except TimezoneConfigurationError:
        return _terminal_result("CONFIG_ERROR", inputs, snapshot, reason="unresolvable_timezone")

    # §19.1 step 6 — calendar resolution failure (WD-21 fail closed)
    if inputs.calendar_day_type is None:
        return _terminal_result("CONFIG_ERROR", inputs, snapshot, reason="no_calendar_resolved")

    # §19.1 step 7 — policy resolution failure (WD-21 fail closed)
    if inputs.policy is None:
        return _terminal_result("CONFIG_ERROR", inputs, snapshot, reason="no_policy_resolved")

    # W5 (architecture §9.7) — a roster week-off override is a schedule fact, independent of
    # whether a shift resolved: "you're off this day" needs no shift to be meaningful, and must
    # win even when the calendar itself says WORKING (a rotating-crew Wednesday-off case, not
    # representable by the calendar/weekly-off pattern alone). Checked ahead of the "missing
    # shift" branch below so a pure roster week-off row (shift_id NULL) doesn't fall through to
    # `missing_shift_behaviour` and get misread as an unresolved-shift config problem.
    if inputs.roster_week_off_override and not inputs.punches:
        return _apply_leave_overlay(
            _apply_on_duty_overlay(
                _terminal_result(
                    "NOT_EXPECTED", inputs, snapshot, reason="roster_week_off_override"
                ),
                inputs,
            ),
            inputs,
        )

    # §19.1 step 4 — missing shift
    if inputs.shift is None:
        behaviour = "INCOMPLETE"  # missing_shift_behaviour default; real value read from policy
        if inputs.policy is not None:
            behaviour = inputs.policy.missing_shift_behaviour
        if not inputs.punches:
            status = "ABSENT" if behaviour == "ABSENT" else "INCOMPLETE"
            return _apply_leave_overlay(
                _apply_on_duty_overlay(
                    _terminal_result(status, inputs, snapshot, reason="missing_shift"), inputs
                ),
                inputs,
            )
        # Punches exist despite no shift — evaluate presence with no schedule to compare against.
        return _apply_leave_overlay(
            _apply_on_duty_overlay(_evaluate_no_schedule(inputs, snapshot), inputs), inputs
        )

    day_type = inputs.calendar_day_type
    # W5: roster overrides extend §19.1 step 8 without ever touching `calendar_day_type`
    # (WD-04/WD-07 — calendar type is Calendar's concern; roster only changes whether presence
    # is *expected*). `roster_holiday_working_override` mirrors what a per-shift
    # `operates_on_holiday`/`operates_on_weekly_off` flag already does, just scoped to one
    # employee-date instead of the whole shift.
    not_expected = (
        day_type in ("HOLIDAY", "WEEKLY_OFF", "SHUTDOWN") or inputs.roster_week_off_override
    )
    shift_operates = (
        (day_type == "HOLIDAY" and inputs.shift.operates_on_holiday)
        or (day_type == "WEEKLY_OFF" and inputs.shift.operates_on_weekly_off)
        or inputs.roster_holiday_working_override
    )

    collapsed = collapse_duplicate_punches(
        sorted(inputs.punches, key=lambda p: p.punch_time),
        window_seconds=inputs.policy.duplicate_punch_window_seconds,
    )
    snapshot["collapsed_punch_ids"] = [str(p.id) for p in collapsed]

    # §19.1 step 8 — not expected + shift does not operate + no punches => NOT_EXPECTED
    if not_expected and not shift_operates and not collapsed:
        return _apply_leave_overlay(
            _apply_on_duty_overlay(
                _terminal_result(
                    "NOT_EXPECTED", inputs, snapshot, worked_on=day_type if not_expected else None
                ),
                inputs,
            ),
            inputs,
        )

    pairing = pair_punches(collapsed)
    snapshot["pairing"] = {
        "pairs": [(str(a.id), str(b.id)) for a, b in pairing.pairs],
        "orphans": [str(p.id) for p in pairing.orphans],
    }

    if inputs.shift.shift_type == "SPLIT" and inputs.shift.duty_blocks:
        result = _evaluate_split(inputs, pairing, snapshot, day_type, not_expected)
    else:
        result = _evaluate_fixed_or_flex(inputs, pairing, snapshot, day_type, not_expected)

    return _apply_leave_overlay(_apply_on_duty_overlay(result, inputs), inputs)


def _apply_leave_overlay(
    result: AttendanceCalculationResult, inputs: AttendanceCalculationInput
) -> AttendanceCalculationResult:
    """§19.3/§19.4 (W9) — approved leave overlay, applied once the punch-derived outcome is
    known. Never touches `calendar_day_type` (Calendar's own concern, WD-04/WD-07) — only
    `attendance_status`/`paid_day_fraction`/`lop_fraction`/late-early fields, mirroring exactly
    what the W5 roster overrides already do to expectation-of-presence.

    Full-day leave (active fractions summing to >= 1.00) wins outright per §19.4's precedence —
    it ranks above calendar `NOT_EXPECTED`, so it can apply even on a holiday/weekly-off date
    that Leave has (redundantly) projected as covered; `calendar_day_type` itself still reports
    HOLIDAY/WEEKLY_OFF unchanged, matching the architecture's contract-table note that Attendance
    "will still classify the calendar type as HOLIDAY/WO" regardless. `NOT_JOINED`/`EXITED`
    (population gate) and `CONFIG_ERROR` (nothing well-defined to overlay onto — fail closed) are
    never touched; the caller skips this function entirely for the population-gate case, and it
    short-circuits below for the other two.

    Punches despite full-day leave: `work_on_leave_behaviour=KEEP_LEAVE` (default) keeps
    `attendance_status=LEAVE` and zeroes late/early (§19.3 — "full-day leave: late/early not
    computed"); `PRESENT_CANCEL_LEAVE_HINT` keeps the punch-derived outcome untouched and only
    raises `work_on_leave_flagged` for Leave to see (Attendance never cancels the leave itself).

    Half-day leave (0 < fraction < 1.00): the remaining half of the day is whatever the
    punch-derived outcome already computed, contributed as a flat 0.50 (documented
    simplification, module docstring) — `status="HALF_DAY"` if punches produced any worked
    minutes, else `"LEAVE"` (mirrors "if they do not punch, LEAVE not ABSENT", scaled to a half
    day)."""
    if not inputs.leave_entries:
        return result
    if result.attendance_status in ("NOT_JOINED", "EXITED", "CONFIG_ERROR"):
        return result

    total_fraction = sum(
        (Decimal(entry.fraction) for entry in inputs.leave_entries), Decimal("0.00")
    )
    paid_from_leave = sum(
        (Decimal(entry.fraction) for entry in inputs.leave_entries if entry.is_paid),
        Decimal("0.00"),
    )
    lop_from_leave = total_fraction - paid_from_leave
    has_work = result.worked_minutes > 0
    behaviour = inputs.policy.work_on_leave_behaviour if inputs.policy else "KEEP_LEAVE"
    hint = has_work and behaviour == "PRESENT_CANCEL_LEAVE_HINT"

    if total_fraction >= Decimal("1.00"):
        if hint:
            return replace(result, work_on_leave_flagged=True)
        return replace(
            result,
            attendance_status="LEAVE",
            late_minutes=0,
            late_classification=None,
            early_departure_minutes=0,
            early_departure_classification=None,
            is_late=False,
            is_early_out=False,
            paid_day_fraction=str(paid_from_leave.quantize(Decimal("0.01"))),
            lop_fraction=str(lop_from_leave.quantize(Decimal("0.01"))),
            work_on_leave_flagged=False,
        )

    # Half-day leave (0 < total_fraction < 1.00).
    if hint:
        return replace(result, work_on_leave_flagged=True)
    remaining = Decimal("1.00") - total_fraction
    work_paid = remaining if has_work else Decimal("0.00")
    work_lop = Decimal("0.00") if has_work else remaining
    status = "HALF_DAY" if has_work else "LEAVE"
    return replace(
        result,
        attendance_status=status,
        paid_day_fraction=str((paid_from_leave + work_paid).quantize(Decimal("0.01"))),
        lop_fraction=str((lop_from_leave + work_lop).quantize(Decimal("0.01"))),
        work_on_leave_flagged=False,
    )


def _apply_on_duty_overlay(
    result: AttendanceCalculationResult, inputs: AttendanceCalculationInput
) -> AttendanceCalculationResult:
    """WD-32 decision 6 — real `ON_DUTY` status, applied once the punch-derived outcome is known,
    in the exact same precedence slot `_apply_leave_overlay` occupies (`evaluate_day` calls this
    first, then wraps the result in `_apply_leave_overlay` — an active leave entry still wins
    outright per §19.4 if both somehow cover the same date, mirroring how leave already outranks
    every other overlay).

    `on_duty_requires_punch=False` (the default) short-circuits straight to `ON_DUTY`, full paid
    day, no punch evaluation needed — the exact shape of the full-day-leave short-circuit in
    `_apply_leave_overlay`. `on_duty_requires_punch=True` keeps the punch-derived status and only
    raises `is_on_duty_flagged` for reporting — the exact shape of `work_on_leave_flagged`'s
    "keep punch status + flag" mode."""
    if not inputs.on_duty_approved:
        return result
    if result.attendance_status in ("NOT_JOINED", "EXITED", "CONFIG_ERROR"):
        return result
    requires_punch = inputs.policy.on_duty_requires_punch if inputs.policy else False
    if requires_punch:
        return replace(result, is_on_duty_flagged=True)
    return replace(
        result,
        attendance_status="ON_DUTY",
        late_minutes=0,
        late_classification=None,
        early_departure_minutes=0,
        early_departure_classification=None,
        is_late=False,
        is_early_out=False,
        paid_day_fraction="1.00",
        lop_fraction="0.00",
        is_on_duty_flagged=False,
    )


def _terminal_result(
    status: str,
    inputs: AttendanceCalculationInput,
    snapshot: dict[str, Any],
    *,
    reason: str | None = None,
    worked_on: str | None = None,
) -> AttendanceCalculationResult:
    if reason:
        snapshot["terminal_reason"] = reason
    paid_fraction = "1.00" if status in ("NOT_JOINED", "NOT_EXPECTED") else "0.00"
    lop_fraction = (
        "0.00"
        if status in ("NOT_JOINED", "NOT_EXPECTED")
        else ("1.00" if status in ("ABSENT", "EXITED") else "0.00")
    )
    return AttendanceCalculationResult(
        attendance_status=status,
        calendar_day_type=inputs.calendar_day_type,
        holiday_name=inputs.holiday_name,
        holiday_on_weekly_off=inputs.holiday_on_weekly_off,
        scheduled_start=inputs.scheduled_start,
        scheduled_end=inputs.scheduled_end,
        scheduled_minutes=None,
        actual_first_in=None,
        actual_last_out=None,
        worked_minutes=0,
        unpaid_break_minutes=0,
        paid_break_minutes=0,
        excess_break_minutes=0,
        breaks=[],
        late_minutes=0,
        early_departure_minutes=0,
        late_classification=None,
        early_departure_classification=None,
        missing_punch=status == "INCOMPLETE",
        auto_closed=False,
        is_late=False,
        is_early_out=False,
        is_overtime=False,
        worked_on_holiday=False,
        worked_on_weekly_off=False,
        paid_day_fraction=paid_fraction,
        lop_fraction=lop_fraction,
        ot_minutes_detected=0,
        ot_minutes_approved=0,
        ot_pending=False,
        ot_classification=None,
        comp_off_minutes_earned=0,
        ot_day_class=None,
        snapshot=snapshot,
    )


def _evaluate_no_schedule(
    inputs: AttendanceCalculationInput, snapshot: dict[str, Any]
) -> AttendanceCalculationResult:
    collapsed = collapse_duplicate_punches(
        sorted(inputs.punches, key=lambda p: p.punch_time),
        window_seconds=(inputs.policy.duplicate_punch_window_seconds if inputs.policy else 60),
    )
    pairing = pair_punches(collapsed)
    first_in, last_out, gross_minutes, _gaps = presence_span(
        pairing.pairs, mode=inputs.policy.multi_punch_mode if inputs.policy else "PAIR_ALL"
    )
    snapshot["no_schedule"] = True
    status = "PRESENT" if gross_minutes > 0 else "INCOMPLETE"
    return AttendanceCalculationResult(
        attendance_status=status,
        calendar_day_type=inputs.calendar_day_type,
        holiday_name=inputs.holiday_name,
        holiday_on_weekly_off=inputs.holiday_on_weekly_off,
        scheduled_start=None,
        scheduled_end=None,
        scheduled_minutes=None,
        actual_first_in=first_in,
        actual_last_out=last_out,
        worked_minutes=gross_minutes,
        unpaid_break_minutes=0,
        paid_break_minutes=0,
        excess_break_minutes=0,
        breaks=[],
        late_minutes=0,
        early_departure_minutes=0,
        late_classification=None,
        early_departure_classification=None,
        missing_punch=bool(pairing.orphans),
        auto_closed=False,
        is_late=False,
        is_early_out=False,
        is_overtime=False,
        worked_on_holiday=False,
        worked_on_weekly_off=False,
        paid_day_fraction="1.00" if status == "PRESENT" else "0.00",
        lop_fraction="0.00" if status == "PRESENT" else "0.00",
        ot_minutes_detected=0,
        ot_minutes_approved=0,
        ot_pending=False,
        ot_classification=None,
        comp_off_minutes_earned=0,
        ot_day_class=None,
        snapshot=snapshot,
    )


def _core_hours_breached(
    *,
    first_in: datetime | None,
    last_out: datetime | None,
    gaps: list[tuple[datetime, datetime]],
    core_start: time,
    core_end: time,
    attendance_date: date,
    tz_name: str,
) -> bool:
    """WD-32 decision 1 — block-level check (the same "not further sub-analysed" precedent this
    module's docstring already sets for SPLIT duty blocks, applied here to core hours): breached
    if presence doesn't fully span `[core_start, core_end]`, or a punch gap falls inside it. Not
    minute-by-minute beyond that."""
    if first_in is None or last_out is None:
        return True
    tz = ZoneInfo(tz_name)
    core_start_utc = _local_to_utc(attendance_date, core_start, tz)
    core_end_utc = _local_to_utc(attendance_date, core_end, tz)
    if core_end_utc <= core_start_utc:
        core_end_utc = core_end_utc + timedelta(days=1)
    if first_in > core_start_utc or last_out < core_end_utc:
        return True
    return any(gap_start < core_end_utc and gap_end > core_start_utc for gap_start, gap_end in gaps)


def _evaluate_fixed_or_flex(
    inputs: AttendanceCalculationInput,
    pairing: PairingResult,
    snapshot: dict[str, Any],
    day_type: str,
    not_expected: bool,
) -> AttendanceCalculationResult:
    assert inputs.policy is not None and inputs.shift is not None
    policy = inputs.policy
    shift = inputs.shift

    first_in, last_out, gross_minutes, gaps = presence_span(
        pairing.pairs, mode=policy.multi_punch_mode
    )
    matched_breaks = match_breaks(gaps, shift.breaks, tz_name=inputs.timezone)
    unpaid_minutes = sum(b.minutes for b in matched_breaks if not b.is_paid)
    paid_minutes = sum(b.minutes for b in matched_breaks if b.is_paid)
    excess_minutes = sum(b.minutes for b in matched_breaks if b.is_excess)
    worked_minutes = worked_minutes_from_gross(
        gross_minutes,
        mode=policy.multi_punch_mode,
        paid_break_minutes=paid_minutes,
        unpaid_break_minutes=unpaid_minutes,
    )

    snapshot["presence"] = {
        "first_in": first_in.isoformat() if first_in else None,
        "last_out": last_out.isoformat() if last_out else None,
        "gross_minutes": gross_minutes,
        "unpaid_break_minutes": unpaid_minutes,
        "worked_minutes": worked_minutes,
    }

    missing_punch = bool(pairing.orphans) or first_in is None
    auto_closed = False

    late_minutes = 0
    late_classification = None
    early_minutes = 0
    early_classification = None

    if first_in is not None and inputs.scheduled_start is not None:
        late_raw = int((first_in - inputs.scheduled_start).total_seconds() // 60)
        late_minutes = max(0, late_raw - policy.grace_in_minutes)
        if late_minutes > 0:
            late_classification = lookup_band(late_minutes, inputs.late_bands)

    if last_out is not None and inputs.scheduled_end is not None:
        early_raw = int((inputs.scheduled_end - last_out).total_seconds() // 60)
        early_minutes = max(0, early_raw - policy.grace_out_minutes)
        if early_minutes > 0:
            early_classification = lookup_band(early_minutes, inputs.early_bands)
            # WD-32 decision 5 — an early departure beyond grace with no matching APPROVED
            # `EARLY_DEPARTURE_APPROVAL` request on file is forced to the harshest *configured*
            # band (mirrors decisions 1/3's "force the worse status" override shape) rather than
            # the graduated bands the raw minutes would otherwise select — the policy has
            # declared unapproved early exits unacceptable, not merely worth flagging.
            if policy.early_departure_requires_approval and not inputs.early_departure_pre_approved:
                harshest = _harshest_band_classification(inputs.early_bands)
                if harshest is not None:
                    early_classification = harshest

    # WD-32 decision 1 — FLEX-only core-hours breach (§11.8: core hours is a flexible-shift
    # concept; FIXED shifts have no window to breach). `IGNORE` computes nothing extra, matching
    # its name; `FLAG`/`HALF_DAY`/`ABSENT` all set `is_core_hours_breach` for reporting, and only
    # the latter two also override the resolved status (same override shape late/early already
    # use).
    is_core_hours_breach = False
    core_hours_status_override: str | None = None
    if (
        shift.shift_type == "FLEXIBLE"
        and shift.core_start is not None
        and shift.core_end is not None
        and policy.core_hours_breach_behaviour != "IGNORE"
    ):
        is_core_hours_breach = _core_hours_breached(
            first_in=first_in,
            last_out=last_out,
            gaps=gaps,
            core_start=shift.core_start,
            core_end=shift.core_end,
            attendance_date=inputs.attendance_date,
            tz_name=inputs.timezone,
        )
        if is_core_hours_breach and policy.core_hours_breach_behaviour in ("HALF_DAY", "ABSENT"):
            core_hours_status_override = policy.core_hours_breach_behaviour

    # WD-32 decisions 2/3/4 — cumulative-day counters. Each counts this day (if it itself
    # qualifies) plus `service.py`'s pre-computed sibling-day sum for the trailing window; once
    # the HR-set threshold is met or crossed, the day is forced to HALF_DAY — same override shape
    # as the late/early bands, just a second, independent trigger into the same override point
    # (WD-29 decision 3's sibling-day-dependency trade-off applies here identically: a day's
    # status can depend on sibling days' state, accepted and documented, not a silent gap).
    cumulative_status_override: str | None = None
    if (
        policy.lates_to_half_day_count is not None
        and late_minutes > 0
        and (inputs.prior_late_days_in_window + 1) >= policy.lates_to_half_day_count
    ):
        cumulative_status_override = "HALF_DAY"
    if (
        policy.excess_break_days_to_half_day_count is not None
        and excess_minutes > 0
        and (inputs.prior_excess_break_days_in_window + 1)
        >= policy.excess_break_days_to_half_day_count
    ):
        cumulative_status_override = "HALF_DAY"

    hour_band_status = lookup_band(worked_minutes, inputs.hour_bands) if worked_minutes else None

    status = _resolve_primary_status(
        day_type=day_type,
        not_expected=not_expected,
        worked_minutes=worked_minutes,
        missing_punch=missing_punch,
        missing_punch_behaviour=policy.missing_punch_behaviour,
        hour_band_status=hour_band_status,
        late_classification=late_classification,
        early_classification=early_classification,
        core_hours_status_override=core_hours_status_override,
        cumulative_status_override=cumulative_status_override,
    )

    worked_on_holiday = day_type == "HOLIDAY" and worked_minutes > 0
    worked_on_weekly_off = day_type == "WEEKLY_OFF" and worked_minutes > 0

    scheduled_minutes = (
        int((inputs.scheduled_end - inputs.scheduled_start).total_seconds() // 60)
        if inputs.scheduled_start and inputs.scheduled_end
        else shift.required_minutes
    )

    is_night = shift.is_cross_midnight
    ot_minutes, ot_classification, ot_eligible = detect_overtime(
        worked_minutes=worked_minutes,
        scheduled_minutes=scheduled_minutes,
        is_shift_ot_eligible=shift.is_ot_eligible,
        is_holiday=worked_on_holiday,
        is_weekly_off=worked_on_weekly_off,
        is_night=is_night,
        policy=inputs.ot_policy,
    )
    ot_approved = 0
    ot_pending = False
    comp_off_minutes = 0
    ot_day_class: str | None = None
    if ot_eligible and ot_minutes > 0:
        if inputs.ot_policy is not None and not inputs.ot_policy.requires_post_approval:
            ot_approved = ot_minutes
        else:
            ot_pending = True
        if inputs.ot_policy is not None and inputs.ot_policy.comp_off_instead_of_pay:
            comp_off_minutes = ot_minutes
        ot_day_class = classify_ot_day(
            is_holiday=worked_on_holiday,
            is_weekly_off=worked_on_weekly_off,
            is_night=is_night,
            night_ot_mode=inputs.ot_policy.night_ot_mode if inputs.ot_policy else "SHIFT_FLAG",
        )

    paid_fraction, lop_fraction = _paid_lop_fraction(status, hour_band_status)

    return AttendanceCalculationResult(
        attendance_status=status,
        calendar_day_type=day_type,
        holiday_name=inputs.holiday_name,
        holiday_on_weekly_off=inputs.holiday_on_weekly_off,
        scheduled_start=inputs.scheduled_start,
        scheduled_end=inputs.scheduled_end,
        scheduled_minutes=scheduled_minutes,
        actual_first_in=first_in,
        actual_last_out=last_out,
        worked_minutes=worked_minutes,
        unpaid_break_minutes=unpaid_minutes,
        paid_break_minutes=paid_minutes,
        excess_break_minutes=excess_minutes,
        breaks=matched_breaks,
        late_minutes=late_minutes,
        early_departure_minutes=early_minutes,
        late_classification=late_classification,
        early_departure_classification=early_classification,
        missing_punch=missing_punch,
        auto_closed=auto_closed,
        is_late=late_minutes > 0,
        is_early_out=early_minutes > 0,
        is_overtime=ot_minutes > 0,
        worked_on_holiday=worked_on_holiday,
        worked_on_weekly_off=worked_on_weekly_off,
        paid_day_fraction=paid_fraction,
        lop_fraction=lop_fraction,
        ot_minutes_detected=ot_minutes,
        ot_minutes_approved=ot_approved,
        ot_pending=ot_pending,
        ot_classification=ot_classification,
        comp_off_minutes_earned=comp_off_minutes,
        ot_day_class=ot_day_class,
        snapshot=snapshot,
        is_core_hours_breach=is_core_hours_breach,
    )


def _evaluate_split(
    inputs: AttendanceCalculationInput,
    pairing: PairingResult,
    snapshot: dict[str, Any],
    day_type: str,
    not_expected: bool,
) -> AttendanceCalculationResult:
    """SPLIT shift — each duty block is checked for at least one overlapping pair (documented
    simplification, module docstring)."""
    assert inputs.policy is not None and inputs.shift is not None
    policy = inputs.policy
    shift = inputs.shift

    first_in, last_out, gross_minutes, gaps = presence_span(
        pairing.pairs, mode=policy.multi_punch_mode
    )
    matched_breaks = match_breaks(gaps, shift.breaks, tz_name=inputs.timezone)
    unpaid_minutes = sum(b.minutes for b in matched_breaks if not b.is_paid)
    paid_minutes = sum(b.minutes for b in matched_breaks if b.is_paid)
    worked_minutes = worked_minutes_from_gross(
        gross_minutes,
        mode=policy.multi_punch_mode,
        paid_break_minutes=paid_minutes,
        unpaid_break_minutes=unpaid_minutes,
    )

    tz = ZoneInfo(inputs.timezone)
    missed_blocks = 0
    for block in shift.duty_blocks:
        block_start = _local_to_utc(inputs.attendance_date, block.start_time, tz)
        block_end_date = (
            inputs.attendance_date + timedelta(days=1)
            if block.crosses_midnight
            else inputs.attendance_date
        )
        block_end = _local_to_utc(block_end_date, block.end_time, tz)
        overlapped = any(
            in_p.punch_time < block_end and out_p.punch_time > block_start
            for in_p, out_p in pairing.pairs
        )
        if not overlapped:
            missed_blocks += 1
    snapshot["split_missed_blocks"] = missed_blocks

    missing_punch = bool(pairing.orphans) or first_in is None
    hour_band_status = lookup_band(worked_minutes, inputs.hour_bands) if worked_minutes else None

    # `split_shift_missed_block_behaviour` (W3) is one of IGNORE/HALF_DAY/ABSENT/
    # REQUIRE_REGULARIZATION. IGNORE falls through to the ordinary status resolution below (the
    # missed block carries no special weight); the other three map directly.
    behaviour = policy.split_shift_missed_block_behaviour
    if missed_blocks > 0 and behaviour in ("HALF_DAY", "ABSENT"):
        status = behaviour
    elif missed_blocks > 0 and behaviour == "REQUIRE_REGULARIZATION":
        status = "INCOMPLETE"
    else:
        status = _resolve_primary_status(
            day_type=day_type,
            not_expected=not_expected,
            worked_minutes=worked_minutes,
            missing_punch=missing_punch,
            missing_punch_behaviour=policy.missing_punch_behaviour,
            hour_band_status=hour_band_status,
            late_classification=None,
            early_classification=None,
        )

    paid_fraction, lop_fraction = _paid_lop_fraction(status, hour_band_status)

    worked_on_holiday = day_type == "HOLIDAY" and worked_minutes > 0
    worked_on_weekly_off = day_type == "WEEKLY_OFF" and worked_minutes > 0

    # W7 (WD-29 decision 5) — SPLIT shifts previously never detected overtime at all. No input
    # is actually missing here: `scheduled_minutes=shift.required_minutes` is the same fallback
    # `_evaluate_fixed_or_flex` uses whenever no `scheduled_start`/`scheduled_end` is set, so the
    # detection call is wired in identically to that path.
    ot_minutes, ot_classification, ot_eligible = detect_overtime(
        worked_minutes=worked_minutes,
        scheduled_minutes=shift.required_minutes,
        is_shift_ot_eligible=shift.is_ot_eligible,
        is_holiday=worked_on_holiday,
        is_weekly_off=worked_on_weekly_off,
        is_night=shift.is_cross_midnight,
        policy=inputs.ot_policy,
    )
    ot_approved = 0
    ot_pending = False
    comp_off_minutes = 0
    ot_day_class: str | None = None
    if ot_eligible and ot_minutes > 0:
        if inputs.ot_policy is not None and not inputs.ot_policy.requires_post_approval:
            ot_approved = ot_minutes
        else:
            ot_pending = True
        if inputs.ot_policy is not None and inputs.ot_policy.comp_off_instead_of_pay:
            comp_off_minutes = ot_minutes
        ot_day_class = classify_ot_day(
            is_holiday=worked_on_holiday,
            is_weekly_off=worked_on_weekly_off,
            is_night=shift.is_cross_midnight,
            night_ot_mode=inputs.ot_policy.night_ot_mode if inputs.ot_policy else "SHIFT_FLAG",
        )

    return AttendanceCalculationResult(
        attendance_status=status,
        calendar_day_type=day_type,
        holiday_name=inputs.holiday_name,
        holiday_on_weekly_off=inputs.holiday_on_weekly_off,
        scheduled_start=inputs.scheduled_start,
        scheduled_end=inputs.scheduled_end,
        scheduled_minutes=shift.required_minutes,
        actual_first_in=first_in,
        actual_last_out=last_out,
        worked_minutes=worked_minutes,
        unpaid_break_minutes=unpaid_minutes,
        paid_break_minutes=paid_minutes,
        excess_break_minutes=sum(b.minutes for b in matched_breaks if b.is_excess),
        breaks=matched_breaks,
        late_minutes=0,
        early_departure_minutes=0,
        late_classification=None,
        early_departure_classification=None,
        missing_punch=missing_punch,
        auto_closed=False,
        is_late=False,
        is_early_out=False,
        is_overtime=ot_minutes > 0,
        worked_on_holiday=worked_on_holiday,
        worked_on_weekly_off=worked_on_weekly_off,
        paid_day_fraction=paid_fraction,
        lop_fraction=lop_fraction,
        ot_minutes_detected=ot_minutes,
        ot_minutes_approved=ot_approved,
        ot_pending=ot_pending,
        ot_classification=ot_classification,
        comp_off_minutes_earned=comp_off_minutes,
        ot_day_class=ot_day_class,
        snapshot=snapshot,
    )


def _resolve_primary_status(
    *,
    day_type: str,
    not_expected: bool,
    worked_minutes: int,
    missing_punch: bool,
    missing_punch_behaviour: str,
    hour_band_status: str | None,
    late_classification: str | None,
    early_classification: str | None,
    core_hours_status_override: str | None = None,
    cumulative_status_override: str | None = None,
) -> str:
    """§19.4 overlay precedence, collapsed to the punch-derived tier (NOT_JOINED/EXITED/
    NOT_EXPECTED already ruled out by the caller; Leave and ON_DUTY are separate overlays applied
    by the caller after this function returns — WFH remains a no-op, WD-32 scoped `ON_DUTY` only).

    `core_hours_status_override`/`cumulative_status_override` (WD-32 decisions 1/2/3) are two more
    independent triggers into the exact same override point late/early classifications already
    use below — any one of the four can force HALF_DAY (or, for core-hours, ABSENT); none of them
    interact with or suppress each other.

    §11.5: "ABSENT is harsh and must be an explicit policy choice" — a zero-punch expected
    working day therefore defaults to `INCOMPLETE` (the documented default for
    `missing_punch_behaviour`), never silently `ABSENT`, unless the policy explicitly sets
    `missing_punch_behaviour=ABSENT`."""
    if worked_minutes == 0:
        if not_expected:
            return "NOT_EXPECTED"
        if missing_punch:
            return "ABSENT" if missing_punch_behaviour == "ABSENT" else "INCOMPLETE"
        return "ABSENT"

    if missing_punch:
        if missing_punch_behaviour == "ABSENT":
            return "ABSENT"
        if missing_punch_behaviour == "AUTO_CLOSE":
            pass  # falls through to band-based status below (auto_closed flag set by caller)
        else:
            return "INCOMPLETE"

    if hour_band_status in ("ABSENT", "HALF_DAY", "PRESENT"):
        status = hour_band_status
    else:
        status = "PRESENT"

    if (
        late_classification == "ABSENT"
        or early_classification == "ABSENT"
        or core_hours_status_override == "ABSENT"
    ):
        return "ABSENT"
    if (
        late_classification == "HALF_DAY"
        or early_classification == "HALF_DAY"
        or core_hours_status_override == "HALF_DAY"
        or cumulative_status_override == "HALF_DAY"
    ):
        return "HALF_DAY"

    return status


def _paid_lop_fraction(status: str, hour_band_status: str | None) -> tuple[str, str]:
    if status == "PRESENT":
        return "1.00", "0.00"
    if status == "HALF_DAY":
        return "0.50", "0.50"
    if status == "ABSENT":
        return "0.00", "1.00"
    if status == "NOT_EXPECTED":
        return "1.00", "0.00"
    return "0.00", "0.00"  # INCOMPLETE / CONFIG_ERROR — not sent to payroll (§11.4)
