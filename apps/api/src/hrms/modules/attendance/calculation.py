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

#: PAY-008 — identifies the algorithm, unlike `AttendanceDay.calculation_version` (a per-row
#: recompute counter). Stored on every computed row (`attendance_day.engine_version`) and in its
#: `computation_snapshot`, so a payslip can name the rules its figures came from. Bump it
#: whenever a change alters any output for unchanged inputs. 1 = rows computed before this
#: constant existed (backfilled as NULL); 2 = payroll-readiness step 1 (PAY-002…PAY-012,
#: ATT-005, `docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decisions 1/4/5); 3 = break management
#: V1 (break events, automatic deduction, unresolved/excess breaks). Breaks with `mode=None`
#: (every break configured before V1) calculate exactly as under 2. 4 = flexible-shift lateness
#: runs from the end of the start window; on-duty clears an unpaid off day. 5 = half-day leave:
#: the worked half is judged on its own (`_half_day_leave_half`, `_apply_leave_overlay`).
ENGINE_VERSION = 5

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
    # Break management V1 — all defaulted so a break built the old way stays a legacy break.
    name: str = ""
    break_type: str = "OTHER"
    mode: str | None = (
        None  # None = legacy gap-matched | MANDATORY_PUNCH | AUTO_DEDUCT | OPTIONAL_PUNCH
    )
    scheduled_minutes: int | None = None
    crosses_midnight: bool = False
    excess_outcome: str | None = None  # RECORD_ONLY | EXCEPTION | REQUIRE_APPROVAL | DEDUCT
    auto_deduct_full: bool = False
    optional_recorded_deducts: bool = True
    optional_scheduled_fallback: bool = False
    is_enabled: bool = True
    sort_order: int = 0
    rule_source: str = "SHIFT"  # SHIFT | EMPLOYEE_OVERRIDE
    override_id: UUID | None = None
    allows_split: bool = False  # more than one punched instance of this break per day


@dataclass(frozen=True, slots=True)
class BreakEventData:
    """One row of `attendance_break_event`, as the pure engine sees it."""

    id: UUID
    event_type: str  # START | END
    event_time: datetime  # tz-aware, UTC
    break_name: str | None = None
    shift_break_id: UUID | None = None
    supersedes_event_id: UUID | None = None
    approved: bool = False


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
    # ATT-005 — the explicit night-shift flag `night_ot_mode=SHIFT_FLAG` reads (architecture
    # §9.5: "an explicit flag (night OT classification), not inferred solely from times").
    is_night_shift: bool = False
    duty_blocks: list[ShiftDutyBlockData] = field(default_factory=list)
    core_start: time | None = None
    core_end: time | None = None
    required_minutes: int | None = None  # FLEXIBLE
    # Break management V1 — which employee overrides shaped `breaks` (audit trail for the
    # calculation snapshot); empty when the shift's own breaks were used as configured.
    break_provenance: list[dict[str, str | None]] = field(default_factory=list)


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
    # PAY-012 — the calendar's `off_fraction` for a WEEKLY_OFF day (`0.50` = half-day weekly off,
    # e.g. alternate half Saturdays). Ignored unless `calendar_day_type == "WEEKLY_OFF"`.
    weekly_off_fraction: str = "1.00"
    # BUS-001 — the employment's pay basis (`MONTHLY` | `DAILY_WAGE`) and, for a day off because
    # of a holiday, that holiday's type and `is_paid` flag. Together they decide whether an off
    # day is paid (`_off_day_is_paid`).
    pay_basis: str = "MONTHLY"
    holiday_type: str | None = None
    holiday_is_paid: bool = True
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
    # Break management V1 — the day's break START/END events (including superseded ones; the
    # engine drops those itself) and whether the day can still receive punches. An open START
    # on a day that is still `day_open` and has no later OUT is an *active* break; on any other
    # day it is *unresolved* and needs review.
    break_events: list[BreakEventData] = field(default_factory=list)
    day_open: bool = False


@dataclass(frozen=True, slots=True)
class MatchedBreak:
    start: datetime | None
    end: datetime | None
    minutes: int
    is_paid: bool
    is_excess: bool
    shift_break_id: UUID | None
    # Break management V1 (defaults keep a legacy gap break constructible as before).
    kind: str = "PUNCHED_GAP"  # PUNCHED_GAP | EVENT | AUTO_DEDUCTED | UNRESOLVED
    name: str | None = None
    rule_source: str | None = None
    override_id: UUID | None = None
    scheduled_minutes: int | None = None
    excess_minutes: int = 0
    deducted_minutes: int = 0
    needs_review: bool = False
    is_approved: bool = False
    start_event_id: UUID | None = None
    end_event_id: UUID | None = None
    is_active: bool = False


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
    # Break management V1 — see `BreakTotals`; all derived, replaced on every recompute.
    actual_break_minutes: int = 0
    auto_deducted_break_minutes: int = 0
    unresolved_break_count: int = 0
    has_unresolved_break: bool = False
    has_active_break: bool = False
    has_excess_break_exception: bool = False
    gross_elapsed_minutes: int = 0
    # PAY-003 — the share of this day `_apply_leave_overlay` actually honoured as leave (0.00 when
    # no leave applied, or when `PRESENT_CANCEL_LEAVE_HINT` kept the punch-derived outcome). Lets
    # the period summary split a half-day-leave day into its leave and non-leave halves.
    leave_fraction: str = "0.00"
    # PAY-012 — the share of the day that is a paid weekly off on a half-day weekly-off date
    # (`0.50`); `0.00` otherwise, including full weekly offs (those are NOT_EXPECTED days).
    weekly_off_fraction: str = "0.00"
    # BUS-001 — the share of the day that is an unpaid off day (neither paid nor LOP): see
    # `_off_day_is_paid`. Every employed day satisfies `paid + lop + unpaid_off = 1.00`.
    unpaid_off_fraction: str = "0.00"


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
# Break management V1 — explicit break events, automatic deduction, unresolved / excess breaks
# ---------------------------------------------------------------------------
#
# Everything below is part of `evaluate_day`'s existing flow (called from
# `_evaluate_fixed_or_flex` / `_evaluate_split`); it is not a second engine. Rules:
#
# * A break whose `mode` is None is a *legacy* break: only punch gaps are matched against it
#   (`match_breaks`, unchanged). Breaks with a mode are resolved here and never matched to gaps.
# * Explicit START/END events are the only confirmation that a break was taken. A gap between
#   punches is never promoted to a MANDATORY/OPTIONAL break.
# * Every deduction is taken from *presence* (the credited IN→OUT intervals) and the deducted
#   intervals are unioned, so no minute of presence is deducted twice. A recorded event for a
#   rule replaces that rule's scheduled automatic deduction (1:05–2:00 recorded against a 1:00–
#   2:00 schedule deducts 55, not 55 + 60), and an event of one rule also keeps another rule's
#   automatic deduction off the minutes it covers.
# * An open START (no END) is *unresolved*: nothing after it is credited, the day cannot be
#   classified, and the break is never closed for the employee.

Interval = tuple[datetime, datetime]

#: `excess_break_behaviour` (policy) → the per-break outcome vocabulary.
_POLICY_EXCESS_TO_OUTCOME = {
    "IGNORE": "RECORD_ONLY",
    "FLAG": "EXCEPTION",
    "REQUIRE_APPROVAL": "REQUIRE_APPROVAL",
    "DEDUCT": "DEDUCT",
}


def _merge_intervals(intervals: list[Interval]) -> list[Interval]:
    ordered = sorted((s, e) for s, e in intervals if e > s)
    merged: list[Interval] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _intersect_intervals(a: list[Interval], b: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for a_start, a_end in a:
        for b_start, b_end in b:
            start, end = max(a_start, b_start), min(a_end, b_end)
            if end > start:
                out.append((start, end))
    return _merge_intervals(out)


def _subtract_intervals(a: list[Interval], b: list[Interval]) -> list[Interval]:
    remaining = _merge_intervals(a)
    for b_start, b_end in _merge_intervals(b):
        next_remaining: list[Interval] = []
        for start, end in remaining:
            if b_end <= start or b_start >= end:
                next_remaining.append((start, end))
                continue
            if start < b_start:
                next_remaining.append((start, b_start))
            if b_end < end:
                next_remaining.append((b_end, end))
        remaining = next_remaining
    return remaining


def _intervals_minutes(intervals: list[Interval]) -> int:
    return int(sum((e - s).total_seconds() for s, e in intervals) // 60)


def _take_minutes(intervals: list[Interval], minutes: int) -> list[Interval]:
    """The first `minutes` minutes of `intervals` (already ordered/merged)."""
    out: list[Interval] = []
    left = timedelta(minutes=minutes)
    for start, end in intervals:
        if left <= timedelta(0):
            break
        take = min(end - start, left)
        out.append((start, start + take))
        left -= take
    return out


def effective_break_events(events: list[BreakEventData]) -> list[BreakEventData]:
    """The events that count: every event not superseded by a correction, in time order. The
    superseded originals stay in storage (and in the snapshot) but never feed a calculation."""
    superseded = {e.supersedes_event_id for e in events if e.supersedes_event_id is not None}
    live = [e for e in events if e.id not in superseded]
    return sorted(live, key=lambda e: (e.event_time, 0 if e.event_type == "START" else 1))


def pair_break_events(
    events: list[BreakEventData],
) -> list[tuple[BreakEventData, BreakEventData | None]]:
    """Pairs START with the next END. A START met while another is still open leaves the earlier
    one open (unresolved); an END with no open START is dropped (the service never writes one)."""
    pairs: list[tuple[BreakEventData, BreakEventData | None]] = []
    open_start: BreakEventData | None = None
    for event in events:
        if event.event_type == "START":
            if open_start is not None:
                pairs.append((open_start, None))
            open_start = event
        elif open_start is not None:
            pairs.append((open_start, event))
            open_start = None
    if open_start is not None:
        pairs.append((open_start, None))
    return pairs


def _rule_for_event(event: BreakEventData, rules: list[ShiftBreakData]) -> ShiftBreakData | None:
    if event.break_name:
        wanted = event.break_name.strip().lower()
        for rule in rules:
            if rule.name.strip().lower() == wanted:
                return rule
    if event.shift_break_id is not None:
        for rule in rules:
            if rule.id == event.shift_break_id:
                return rule
    return None


def _rule_window(
    rule: ShiftBreakData,
    *,
    attendance_date: date,
    tz: ZoneInfo,
    scheduled_start: datetime | None,
) -> Interval | None:
    """The rule's scheduled interval in UTC. A clock time earlier than the shift's own start
    belongs to the next calendar day (a night shift's 01:00 break), and an end at or before the
    start crosses midnight — dates are derived, never assumed to be the attendance date."""
    if rule.break_kind == "FIXED_WINDOW":
        start_t, end_t = rule.start_time, rule.end_time
    else:
        start_t, end_t = rule.window_start, rule.window_end
    if start_t is None:
        return None
    day = attendance_date
    start = _local_to_utc(day, start_t, tz)
    if scheduled_start is not None and start < scheduled_start:
        day = attendance_date + timedelta(days=1)
        start = _local_to_utc(day, start_t, tz)
    if end_t is None or end_t == start_t:
        duration = rule.scheduled_minutes or 0
        return (start, start + timedelta(minutes=duration)) if duration > 0 else None
    end_day = day + timedelta(days=1) if (end_t < start_t or rule.crosses_midnight) else day
    end = _local_to_utc(end_day, end_t, tz)
    if end <= start:
        end = _local_to_utc(end_day + timedelta(days=1), end_t, tz)
    return (start, end)


def _rule_duration(rule: ShiftBreakData, window: Interval | None) -> int:
    if rule.scheduled_minutes:
        return rule.scheduled_minutes
    if rule.break_kind == "FIXED_WINDOW" and window is not None:
        return int((window[1] - window[0]).total_seconds() // 60)
    return rule.max_minutes or rule.min_minutes or 0


def scheduled_unpaid_break_minutes(
    shift: ShiftInputs | None,
    *,
    attendance_date: date,
    tz_name: str,
    scheduled_start: datetime | None,
) -> int:
    """Unpaid minutes the shift's V1 breaks take out of its scheduled span, so overtime compares
    net worked time against the *net* schedule (9:00–18:00 less an unpaid hour is 480, not 540).
    Legacy (mode-less) breaks are excluded: they never reduced the scheduled side."""
    if shift is None:
        return 0
    tz = ZoneInfo(tz_name)
    total = 0
    for rule in shift.breaks:
        if rule.mode is None or not rule.is_enabled or rule.is_paid:
            continue
        window = _rule_window(
            rule, attendance_date=attendance_date, tz=tz, scheduled_start=scheduled_start
        )
        total += _rule_duration(rule, window)
    return total


@dataclass(frozen=True, slots=True)
class BreakComputation:
    breaks: list[MatchedBreak]
    #: the earliest unresolved break start; presence from here on is not credited
    credit_cutoff: datetime | None
    #: minutes removed from worked time by V1 breaks (recorded + automatic + paid-excess)
    v1_deducted_minutes: int
    snapshot: dict[str, Any]


def credit_cutoff_for(
    inputs: AttendanceCalculationInput, pairs: list[tuple[PunchData, PunchData]]
) -> datetime | None:
    """The earliest START that is still open on a day that can no longer produce its END
    (the employee punched out after it, or the day is closed) — `None` when every break is
    closed or merely active."""
    cutoff: datetime | None = None
    for start, end in pair_break_events(effective_break_events(inputs.break_events)):
        if end is not None:
            continue
        if _is_active_break(start, pairs, day_open=inputs.day_open):
            continue
        if cutoff is None or start.event_time < cutoff:
            cutoff = start.event_time
    return cutoff


def _is_active_break(
    start: BreakEventData, pairs: list[tuple[PunchData, PunchData]], *, day_open: bool
) -> bool:
    punched_out_after = any(out_p.punch_time > start.event_time for _in, out_p in pairs)
    return day_open and not punched_out_after


def clip_pairs_at(
    pairs: list[tuple[PunchData, PunchData]], cutoff: datetime | None
) -> list[tuple[PunchData, PunchData]]:
    """Presence credited up to `cutoff`: pairs after it are dropped and the pair spanning it is
    ended there. The original punches are untouched — only this evaluation copy is clipped."""
    if cutoff is None:
        return pairs
    clipped: list[tuple[PunchData, PunchData]] = []
    for in_p, out_p in pairs:
        if in_p.punch_time >= cutoff:
            continue
        if out_p.punch_time > cutoff:
            out_p = replace(out_p, punch_time=cutoff)
        clipped.append((in_p, out_p))
    return clipped


def clamp_pairs_to_start(
    pairs: list[tuple[PunchData, PunchData]], start: datetime | None
) -> list[tuple[PunchData, PunchData]]:
    """Credited presence never begins before the scheduled shift start. Time between an allowed
    early punch-in and the shift start is recorded attendance (the punch and `actual_first_in`
    keep the real instant) but is neither credited as normal work nor counted as overtime.
    A pair that ends at or before `start` earns no credit. Only this evaluation copy changes."""
    if start is None:
        return pairs
    clamped: list[tuple[PunchData, PunchData]] = []
    for in_p, out_p in pairs:
        if out_p.punch_time <= start:
            continue
        if in_p.punch_time < start:
            in_p = replace(in_p, punch_time=start)
        clamped.append((in_p, out_p))
    return clamped


def compute_breaks(
    inputs: AttendanceCalculationInput,
    *,
    pairs: list[tuple[PunchData, PunchData]],
    credit_pairs: list[tuple[PunchData, PunchData]],
    gaps: list[tuple[datetime, datetime]],
) -> BreakComputation:
    """Resolves the day's breaks: legacy gap matching, explicit events, automatic deduction."""
    assert inputs.shift is not None and inputs.policy is not None
    shift, policy = inputs.shift, inputs.policy
    tz = ZoneInfo(inputs.timezone)
    rules = [b for b in shift.breaks if b.is_enabled]
    legacy_rules = [b for b in rules if b.mode is None]
    v1_rules = sorted((b for b in rules if b.mode is not None), key=lambda b: b.sort_order)

    out: list[MatchedBreak] = []
    notes: dict[str, Any] = {}

    # --- legacy: punch gaps matched against mode-less breaks only (behaviour unchanged) -------
    for gap_break in match_breaks(gaps, legacy_rules, tz_name=inputs.timezone):
        out.append(gap_break)

    presence = _merge_intervals([(i.punch_time, o.punch_time) for i, o in credit_pairs])
    all_events = inputs.break_events
    live = effective_break_events(all_events)
    live_ids = {e.id for e in live}
    notes["superseded_event_ids"] = [str(e.id) for e in all_events if e.id not in live_ids]

    # --- explicit events -----------------------------------------------------------------------
    explicit_union: list[Interval] = []
    recorded_rules: set[UUID] = set()
    deducted_total = 0
    unclosed = pair_break_events(live)
    for start_ev, end_ev in unclosed:
        rule = _rule_for_event(start_ev, rules)
        is_paid = rule.is_paid if rule is not None else False
        base: dict[str, Any] = {
            "name": rule.name if rule is not None else start_ev.break_name,
            "rule_source": rule.rule_source if rule is not None else None,
            "override_id": rule.override_id if rule is not None else None,
            "shift_break_id": rule.id if rule is not None and rule.rule_source == "SHIFT" else None,
            "scheduled_minutes": rule.scheduled_minutes if rule is not None else None,
            "is_paid": is_paid,
            "start_event_id": start_ev.id,
        }
        if rule is not None:
            recorded_rules.add(rule.id)
        if end_ev is None:
            active = _is_active_break(start_ev, pairs, day_open=inputs.day_open)
            out.append(
                MatchedBreak(
                    start=start_ev.event_time,
                    end=None,
                    minutes=0,
                    is_excess=False,
                    kind="EVENT" if active else "UNRESOLVED",
                    needs_review=not active,
                    is_active=active,
                    **base,
                )
            )
            continue

        actual = max(0, int((end_ev.event_time - start_ev.event_time).total_seconds() // 60))
        window = [(start_ev.event_time, end_ev.event_time)]
        explicit_union = _merge_intervals(explicit_union + window)
        in_presence = _intersect_intervals(window, presence)
        clipped = _intervals_minutes(in_presence)
        approved = end_ev.approved or start_ev.approved
        max_minutes = rule.max_minutes if rule is not None else None
        excess = max(0, actual - max_minutes) if max_minutes is not None else 0
        outcome = (
            rule.excess_outcome if rule is not None else None
        ) or _POLICY_EXCESS_TO_OUTCOME.get(policy.excess_break_behaviour, "EXCEPTION")
        if (
            rule is not None
            and rule.mode == "OPTIONAL_PUNCH"
            and not rule.optional_recorded_deducts
        ):
            deducted = 0
        else:
            deducted = 0 if is_paid else clipped
        # A paid break that ran over its allowance: the excess is not paid time (DEDUCT only,
        # never when HR has approved the actual duration).
        if excess and is_paid and outcome == "DEDUCT" and not approved:
            deducted += min(excess, clipped)
        needs_review = (
            bool(excess) and outcome in ("EXCEPTION", "REQUIRE_APPROVAL") and not approved
        )
        if rule is not None and rule.min_minutes and actual < rule.min_minutes:
            notes.setdefault("below_minimum", []).append(str(start_ev.id))
        deducted_total += deducted
        out.append(
            MatchedBreak(
                start=start_ev.event_time,
                end=end_ev.event_time,
                minutes=actual,
                is_excess=bool(excess),
                excess_minutes=excess,
                deducted_minutes=deducted,
                kind="EVENT",
                needs_review=needs_review,
                is_approved=approved,
                end_event_id=end_ev.id,
                **base,
            )
        )

    # --- automatic deduction (and optional-mode fallback) ---------------------------------------
    claimed: list[Interval] = []
    for rule in v1_rules:
        automatic = rule.mode == "AUTO_DEDUCT" or (
            rule.mode == "OPTIONAL_PUNCH" and rule.optional_scheduled_fallback
        )
        if not automatic:
            if rule.mode == "MANDATORY_PUNCH" and rule.id not in recorded_rules:
                notes.setdefault("mandatory_not_recorded", []).append(rule.name)
            continue
        if rule.id in recorded_rules:
            continue  # the recorded interval replaces the scheduled deduction
        rule_window = _rule_window(
            rule,
            attendance_date=inputs.attendance_date,
            tz=tz,
            scheduled_start=inputs.scheduled_start,
        )
        duration = _rule_duration(rule, rule_window)
        if rule_window is None or duration <= 0:
            continue
        eligible = _subtract_intervals(
            _intersect_intervals(presence, [rule_window]), explicit_union + claimed
        )
        overlap = _intervals_minutes(eligible)
        if overlap <= 0:
            notes.setdefault("auto_not_eligible", []).append(rule.name)
            continue
        amount = duration if rule.auto_deduct_full else min(duration, overlap)
        taken = _take_minutes(eligible, amount)
        claimed = _merge_intervals(claimed + taken)
        start = taken[0][0]
        deducted = 0 if rule.is_paid else amount
        deducted_total += deducted
        out.append(
            MatchedBreak(
                start=start,
                end=start + timedelta(minutes=amount),
                minutes=amount,
                is_paid=rule.is_paid,
                is_excess=False,
                shift_break_id=rule.id if rule.rule_source == "SHIFT" else None,
                kind="AUTO_DEDUCTED",
                name=rule.name,
                rule_source=rule.rule_source,
                override_id=rule.override_id,
                scheduled_minutes=duration,
                deducted_minutes=deducted,
            )
        )

    notes["provenance"] = list(shift.break_provenance)
    notes["rules"] = [
        {
            "name": r.name,
            "mode": r.mode,
            "source": r.rule_source,
            "override_id": str(r.override_id) if r.override_id else None,
            "paid": r.is_paid,
        }
        for r in rules
    ]
    return BreakComputation(
        breaks=out,
        credit_cutoff=credit_cutoff_for(inputs, pairs),
        v1_deducted_minutes=deducted_total,
        snapshot=notes,
    )


@dataclass(frozen=True, slots=True)
class BreakTotals:
    unpaid_minutes: int
    paid_minutes: int
    excess_minutes: int
    auto_deducted_minutes: int
    actual_minutes: int
    unresolved_count: int
    has_active: bool
    has_excess_exception: bool


def summarize_breaks(breaks: list[MatchedBreak], *, legacy_excess_flagged: bool) -> BreakTotals:
    """Day-level break figures. Legacy gap breaks keep their old meaning (`minutes` is both the
    gap and the deduction); V1 breaks report `deducted_minutes` as the unpaid deduction."""
    unpaid = paid = excess = auto = actual = unresolved = 0
    active = exception = False
    for b in breaks:
        if b.kind == "PUNCHED_GAP":
            actual += b.minutes
            if b.is_paid:
                paid += b.minutes
            else:
                unpaid += b.minutes
            if b.is_excess:
                excess += b.minutes
                exception = exception or legacy_excess_flagged
            continue
        if b.kind == "UNRESOLVED":
            unresolved += 1
            continue
        if b.is_active:
            active = True
            continue
        if b.kind == "AUTO_DEDUCTED":
            if b.is_paid:
                paid += b.minutes
            else:
                unpaid += b.deducted_minutes
                auto += b.deducted_minutes
            continue
        actual += b.minutes
        excess += b.excess_minutes
        if b.is_paid:
            paid += b.minutes
        unpaid += b.deducted_minutes
        exception = exception or (b.is_excess and b.needs_review)
    return BreakTotals(unpaid, paid, excess, auto, actual, unresolved, active, exception)


@dataclass(frozen=True, slots=True)
class DayPresence:
    """Presence and break figures for one day — the shared first half of both the FIXED/FLEX and
    SPLIT evaluators."""

    first_in: datetime | None
    last_out: datetime | None
    gaps: list[tuple[datetime, datetime]]
    breaks: list[MatchedBreak]
    totals: BreakTotals
    gross_minutes: int
    worked_minutes: int
    gross_elapsed_minutes: int
    counter_excess_minutes: int


def evaluate_presence_and_breaks(
    inputs: AttendanceCalculationInput, pairing: PairingResult, snapshot: dict[str, Any]
) -> DayPresence:
    assert inputs.policy is not None and inputs.shift is not None
    policy = inputs.policy
    first_in, last_out, _gross_all, _gaps_all = presence_span(
        pairing.pairs, mode=policy.multi_punch_mode
    )
    cutoff = credit_cutoff_for(inputs, pairing.pairs)
    credit_pairs = clip_pairs_at(pairing.pairs, cutoff)
    if inputs.shift.shift_type == "FIXED":
        # Early punch-in allowance is a punch permission, not credited work (see
        # `clamp_pairs_to_start`). FLEXIBLE/SPLIT shifts have no single start to clamp to.
        credit_pairs = clamp_pairs_to_start(credit_pairs, inputs.scheduled_start)
    _fi, _lo, gross_minutes, gaps = presence_span(credit_pairs, mode=policy.multi_punch_mode)

    computation = compute_breaks(inputs, pairs=pairing.pairs, credit_pairs=credit_pairs, gaps=gaps)
    legacy = [b for b in computation.breaks if b.kind == "PUNCHED_GAP"]
    worked_minutes = max(
        0,
        worked_minutes_from_gross(
            gross_minutes,
            mode=policy.multi_punch_mode,
            paid_break_minutes=sum(b.minutes for b in legacy if b.is_paid),
            unpaid_break_minutes=sum(b.minutes for b in legacy if not b.is_paid),
        )
        - computation.v1_deducted_minutes,
    )
    totals = summarize_breaks(
        computation.breaks, legacy_excess_flagged=policy.excess_break_behaviour != "IGNORE"
    )
    counter_excess = sum(
        b.minutes if b.kind == "PUNCHED_GAP" else b.excess_minutes
        for b in computation.breaks
        if b.is_excess and (b.kind == "PUNCHED_GAP" or b.needs_review)
    )
    gross_elapsed = (
        int((last_out - first_in).total_seconds() // 60)
        if first_in is not None and last_out is not None
        else 0
    )
    snapshot["presence"] = {
        "first_in": first_in.isoformat() if first_in else None,
        "last_out": last_out.isoformat() if last_out else None,
        "gross_minutes": gross_minutes,
        "unpaid_break_minutes": totals.unpaid_minutes,
        "worked_minutes": worked_minutes,
    }
    snapshot["breaks"] = {
        **computation.snapshot,
        "credit_cutoff": cutoff.isoformat() if cutoff else None,
        "v1_deducted_minutes": computation.v1_deducted_minutes,
        "gross_elapsed_minutes": gross_elapsed,
    }
    return DayPresence(
        first_in=first_in,
        last_out=last_out,
        gaps=gaps,
        breaks=computation.breaks,
        totals=totals,
        gross_minutes=gross_minutes,
        worked_minutes=worked_minutes,
        gross_elapsed_minutes=gross_elapsed,
        counter_excess_minutes=counter_excess,
    )


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


def classify_ot_day(*, is_holiday: bool, is_weekly_off: bool, is_night: bool) -> str:
    """The day_class (NORMAL|WEEKLY_OFF|HOLIDAY|NIGHT) OT is classified against for rate-row
    lookup — extracted so `service.py` can recover it for `OvertimeRecord.day_class` (W7) without
    `detect_overtime` needing to change its tested return shape. `is_night` is already resolved
    against the policy's `night_ot_mode` (`resolve_is_night_ot`)."""
    return (
        "HOLIDAY"
        if is_holiday
        else "WEEKLY_OFF"
        if is_weekly_off
        else "NIGHT"
        if is_night
        else "NORMAL"
    )


def _span_overlaps_daily_window(
    span_start: datetime, span_end: datetime, window_start: time, window_end: time, tz: ZoneInfo
) -> bool:
    """True if `[span_start, span_end)` overlaps the local-time daily window on any local date
    the span touches. A window with `end <= start` (e.g. 22:00-06:00) runs into the next day."""
    if span_end <= span_start:
        return False
    local_start = span_start.astimezone(tz).date()
    local_end = span_end.astimezone(tz).date()
    day = local_start - timedelta(days=1)  # a window opened the previous evening
    while day <= local_end:
        win_start = datetime.combine(day, window_start, tzinfo=tz)
        win_end_day = day if window_end > window_start else day + timedelta(days=1)
        win_end = datetime.combine(win_end_day, window_end, tzinfo=tz)
        if span_start < win_end and win_start < span_end:
            return True
        day += timedelta(days=1)
    return False


def resolve_is_night_ot(
    *,
    shift: ShiftInputs,
    policy: OvertimePolicyInputs | None,
    timezone: str,
    scheduled_end: datetime | None,
    last_out: datetime | None,
    worked_minutes: int,
    scheduled_minutes: int | None,
) -> bool:
    """ATT-005 / architecture §12.1 — honours `night_ot_mode`:

    - `SHIFT_FLAG`: the shift's explicit `is_night_shift` flag.
    - `WINDOW`: the overtime span overlaps the policy's `night_window_start`-`night_window_end`
      (company-local time of the day's timezone). A window left unset never matches.
    - `BOTH`: either.

    The overtime span is the work after the scheduled end — `[scheduled_end, last_out)` — or,
    with no scheduled end (FLEX/SPLIT), the trailing excess `[last_out - excess, last_out)`.
    One classification per day (rate-row lookup is per day), so any overlap classifies the
    day's OT as NIGHT."""
    mode = policy.night_ot_mode if policy is not None else "SHIFT_FLAG"
    by_flag = shift.is_night_shift
    if mode == "SHIFT_FLAG":
        return by_flag

    by_window = False
    if (
        policy is not None
        and policy.night_window_start is not None
        and policy.night_window_end is not None
        and last_out is not None
    ):
        if scheduled_end is not None:
            span_start = scheduled_end
        else:
            excess = max(0, worked_minutes - (scheduled_minutes or worked_minutes))
            span_start = last_out - timedelta(minutes=excess)
        by_window = _span_overlaps_daily_window(
            span_start,
            last_out,
            policy.night_window_start,
            policy.night_window_end,
            resolve_zoneinfo(timezone),
        )
    if mode == "WINDOW":
        return by_window
    return by_flag or by_window  # BOTH


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
        is_holiday=is_holiday, is_weekly_off=is_weekly_off, is_night=is_night
    )
    classification = next(
        (row.classification_code for row in policy.rate_rows if row.day_class == day_class), None
    )
    if classification is None and day_class == "NIGHT":
        # ATT-005 — a policy with no NIGHT rate row pays night OT at its NORMAL rate rather than
        # leaving the minutes with no classification code at all.
        classification = next(
            (row.classification_code for row in policy.rate_rows if row.day_class == "NORMAL"),
            None,
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
        },
        "engine_version": ENGINE_VERSION,
        # PAY-008 — everything `service.py` derived from sibling days or other modules before
        # calling this engine. Recorded so a recompute that differs can be explained: the punch
        # ids and policy version ids pin the rest of the inputs, these would otherwise be lost.
        "derived_inputs": {
            "prior_late_days_in_window": inputs.prior_late_days_in_window,
            "prior_excess_break_days_in_window": inputs.prior_excess_break_days_in_window,
            "remaining_weekly_ot_minutes": (
                inputs.ot_policy.remaining_weekly_minutes if inputs.ot_policy else None
            ),
            "remaining_monthly_ot_minutes": (
                inputs.ot_policy.remaining_monthly_minutes if inputs.ot_policy else None
            ),
            "leave_entries": [
                {"fraction": e.fraction, "is_paid": e.is_paid, "half": e.half}
                for e in inputs.leave_entries
            ],
            "roster_week_off_override": inputs.roster_week_off_override,
            "roster_holiday_working_override": inputs.roster_holiday_working_override,
            "early_departure_pre_approved": inputs.early_departure_pre_approved,
            "on_duty_approved": inputs.on_duty_approved,
            "weekly_off_fraction": inputs.weekly_off_fraction,
            "pay_basis": inputs.pay_basis,
            "holiday_type": inputs.holiday_type,
            "holiday_is_paid": inputs.holiday_is_paid,
        },
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
        return _apply_overlays(
            _terminal_result("NOT_EXPECTED", inputs, snapshot, reason="roster_week_off_override"),
            inputs,
        )

    # §19.1 step 4 — missing shift
    if inputs.shift is None:
        behaviour = "INCOMPLETE"  # missing_shift_behaviour default; real value read from policy
        if inputs.policy is not None:
            behaviour = inputs.policy.missing_shift_behaviour
        if not inputs.punches:
            status = "ABSENT" if behaviour == "ABSENT" else "INCOMPLETE"
            return _apply_overlays(
                _terminal_result(status, inputs, snapshot, reason="missing_shift"), inputs
            )
        # Punches exist despite no shift — evaluate presence with no schedule to compare against.
        return _apply_overlays(_evaluate_no_schedule(inputs, snapshot), inputs)

    # PAY-012 — a half-day weekly off is evaluated as a working day (the employee is expected to
    # work the other half); `_apply_half_weekly_off` then credits the off half as paid.
    day_type = "WORKING" if _is_half_weekly_off(inputs) else inputs.calendar_day_type
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
        return _apply_overlays(
            _terminal_result(
                "NOT_EXPECTED", inputs, snapshot, worked_on=day_type if not_expected else None
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

    return _apply_overlays(result, inputs)


#: BUS-001 — holiday types a daily-wage employee is paid for (national/festival holidays are
#: entered as `PUBLIC`; a `SUBSTITUTE` holiday stands in for one).
_DAILY_WAGE_PAID_HOLIDAY_TYPES = ("PUBLIC", "SUBSTITUTE")


def _off_day_is_paid(inputs: AttendanceCalculationInput) -> bool:
    """BUS-001 (`PAYROLL_BUSINESS_DECISIONS.md` #1) — whether a day off is paid.

    - A holiday marked `is_paid = false` is unpaid for everyone.
    - `MONTHLY`: every other day off (holiday, weekly off, shutdown) is paid.
    - `DAILY_WAGE`: only `PUBLIC`/`SUBSTITUTE` holidays are paid; weekly offs, company
      holidays and shutdowns are not.

    A holiday landing on a weekly off follows the holiday rule."""
    if inputs.holiday_type is not None and not inputs.holiday_is_paid:
        return False
    if inputs.pay_basis != "DAILY_WAGE":
        return True
    return inputs.holiday_type in _DAILY_WAGE_PAID_HOLIDAY_TYPES


def _apply_off_day_pay(
    result: AttendanceCalculationResult, inputs: AttendanceCalculationInput
) -> AttendanceCalculationResult:
    """An unworked full day off (`NOT_EXPECTED`) that `_off_day_is_paid` says is unpaid carries
    0.00 paid / 0.00 LOP / 1.00 unpaid-off instead of the default 1.00 paid."""
    if result.attendance_status != "NOT_EXPECTED" or _off_day_is_paid(inputs):
        return result
    return replace(
        result, paid_day_fraction="0.00", lop_fraction="0.00", unpaid_off_fraction="1.00"
    )


def _is_half_weekly_off(inputs: AttendanceCalculationInput) -> bool:
    return inputs.calendar_day_type == "WEEKLY_OFF" and Decimal(
        inputs.weekly_off_fraction
    ) < Decimal("1.00")


def _apply_overlays(
    result: AttendanceCalculationResult, inputs: AttendanceCalculationInput
) -> AttendanceCalculationResult:
    """Overlay order: off-day pay (BUS-001) → half-day weekly off (PAY-012) → ON_DUTY → leave
    (§19.4, leave wins)."""
    with_off_pay = _apply_half_weekly_off(_apply_off_day_pay(result, inputs), inputs)
    return _apply_leave_overlay(_apply_on_duty_overlay(with_off_pay, inputs), inputs)


def _apply_half_weekly_off(
    result: AttendanceCalculationResult, inputs: AttendanceCalculationInput
) -> AttendanceCalculationResult:
    """PAY-012 / BUS-003 (`PAYROLL_BUSINESS_DECISIONS.md` #3) — half off, half working: the off
    half is always paid; the working half is paid only if worked, else it is loss of pay.

    The punch-derived outcome was computed as for a normal working day. Its paid share is
    topped up by the off share (capped at 1.00): PRESENT stays 1.00; a band HALF_DAY (worked
    half the shift) becomes a full paid day and therefore PRESENT; ABSENT becomes 0.50 paid /
    0.50 LOP. INCOMPLETE keeps 0.00/0.00 — lock-time resolution reads `weekly_off_fraction`.
    NOT_EXPECTED (a roster week-off override) is already a full paid off day."""
    if not _is_half_weekly_off(inputs):
        return result
    if result.attendance_status in ("NOT_JOINED", "EXITED", "CONFIG_ERROR", "NOT_EXPECTED"):
        return result
    off = Decimal(inputs.weekly_off_fraction)
    # BUS-001 — for a daily-wage employee the off half is unpaid rather than paid.
    unpaid_off = Decimal("0.00") if _off_day_is_paid(inputs) else off
    adjusted = replace(
        result,
        calendar_day_type=inputs.calendar_day_type,
        weekly_off_fraction=str(off.quantize(Decimal("0.01"))),
        unpaid_off_fraction=str(unpaid_off.quantize(Decimal("0.01"))),
    )
    if result.attendance_status == "INCOMPLETE":
        return adjusted
    # The worked outcome covers the working half first; the off half never adds LOP.
    covered = min(Decimal("1.00"), Decimal(result.paid_day_fraction) + off)
    paid = covered - unpaid_off
    status = result.attendance_status
    if status == "HALF_DAY" and covered == Decimal("1.00"):
        status = "PRESENT"
    return replace(
        adjusted,
        attendance_status=status,
        paid_day_fraction=str(paid.quantize(Decimal("0.01"))),
        lop_fraction=str((Decimal("1.00") - covered).quantize(Decimal("0.01"))),
    )


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

    Punches despite full-day leave: `attendance_status=LEAVE`, late/early and overtime zeroed
    (§19.3 — "full-day leave: late/early not computed"; BUS-011 — no OT on a leave day), and
    `work_on_leave_flagged` raised for HR to resolve before period close (BUS-012). Since
    BUS-012 the policy's `work_on_leave_behaviour` no longer changes the outcome: the former
    `PRESENT_CANCEL_LEAVE_HINT` mode paid the day as present while the leave stayed debited.
    Attendance never cancels the leave itself.

    Half-day leave (0 < fraction < 1.00): the remaining half follows the punch-derived outcome,
    which judged only the worked half (`_half_day_leave_half`). PRESENT is paid as `HALF_DAY`; a
    HALF_DAY or ABSENT outcome loses that half to LOP (`LEAVE`, as if unworked); ON_DUTY keeps it
    paid; a missing punch stays `INCOMPLETE` so period close resolves that half. SPLIT shifts and
    days without a schedule have no such judgement, so any worked minutes pay the half. With no
    punches at all the half is LOP (`LEAVE`, "if they do not punch, LEAVE not ABSENT")."""
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

    if total_fraction >= Decimal("1.00"):
        # BUS-011/BUS-012 (`PAYROLL_BUSINESS_DECISIONS.md` #4/#5) — an approved full-day leave
        # always wins: the day is paid once, as leave, whatever `work_on_leave_behaviour` says,
        # and overtime on it is never payable. Punches on it raise `work_on_leave_flagged`,
        # which blocks period close until HR either cancels the leave (the day then recomputes
        # from its punches) or confirms the leave stands (`work_on_leave_resolution`).
        return replace(
            result,
            attendance_status="LEAVE",
            is_overtime=False,
            ot_minutes_detected=0,
            ot_minutes_approved=0,
            ot_pending=False,
            ot_classification=None,
            ot_day_class=None,
            comp_off_minutes_earned=0,
            late_minutes=0,
            late_classification=None,
            early_departure_minutes=0,
            early_departure_classification=None,
            is_late=False,
            is_early_out=False,
            paid_day_fraction=str(paid_from_leave.quantize(Decimal("0.01"))),
            lop_fraction=str(lop_from_leave.quantize(Decimal("0.01"))),
            work_on_leave_flagged=has_work,
            leave_fraction="1.00",
            weekly_off_fraction="0.00",
            unpaid_off_fraction="0.00",
        )

    # Half-day leave (0 < total_fraction < 1.00) — working the other half is the expected case,
    # not a conflict; the leave half is paid as leave and only the remainder from punches.
    # PAY-012 — on a half-day weekly off the off half is already paid; leave covers (part of) the
    # working half, so only what is left of the day after both can be worked or lost.
    weekly_off = Decimal(result.weekly_off_fraction)
    paid_off = weekly_off - Decimal(result.unpaid_off_fraction)  # BUS-001
    remaining = max(Decimal("0.00"), Decimal("1.00") - total_fraction - weekly_off)
    leave_fraction = str(total_fraction.quantize(Decimal("0.01")))
    if result.attendance_status == "INCOMPLETE" and inputs.punches:
        # Not paid and not LOP yet: `_apply_incomplete_lock_resolution` decides the worked half.
        return replace(
            result,
            paid_day_fraction=str((paid_from_leave + paid_off).quantize(Decimal("0.01"))),
            lop_fraction=str(lop_from_leave.quantize(Decimal("0.01"))),
            work_on_leave_flagged=False,
            leave_fraction=leave_fraction,
        )
    worked_half_judged = inputs.shift is not None and inputs.shift.shift_type in (
        "FIXED",
        "FLEXIBLE",
    )
    worked_half_lost = worked_half_judged and result.attendance_status in ("HALF_DAY", "ABSENT")
    on_duty = result.attendance_status == "ON_DUTY"
    work_counts = on_duty or (has_work and not worked_half_lost)
    work_paid = remaining if work_counts else Decimal("0.00")
    work_lop = Decimal("0.00") if work_counts else remaining
    status = "ON_DUTY" if on_duty else "HALF_DAY" if work_counts else "LEAVE"
    return replace(
        result,
        attendance_status=status,
        paid_day_fraction=str((paid_from_leave + paid_off + work_paid).quantize(Decimal("0.01"))),
        lop_fraction=str((lop_from_leave + work_lop).quantize(Decimal("0.01"))),
        work_on_leave_flagged=False,
        leave_fraction=leave_fraction,
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
        # The whole day is now paid, so an unpaid off day (BUS-001) has nothing left unpaid.
        unpaid_off_fraction="0.00",
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
    # PAY-004/PAY-005 (BUS-002, PAYROLL_BUSINESS_DECISIONS.md #2): a day outside every employment
    # spell is neither paid nor loss-of-pay — Payroll prorates on employed days instead.
    paid_fraction = "1.00" if status == "NOT_EXPECTED" else "0.00"
    lop_fraction = "1.00" if status == "ABSENT" else "0.00"
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


def _half_day_leave_half(inputs: AttendanceCalculationInput) -> str | None:
    """`FIRST`/`SECOND` when one half of a working day is on leave and the other is expected to be
    worked, else `None`. A half-day weekly off leaves no half to work."""
    if len(inputs.leave_entries) != 1 or _is_half_weekly_off(inputs):
        return None
    entry = inputs.leave_entries[0]
    if Decimal(entry.fraction) >= Decimal("1.00"):
        return None
    return entry.half


def _shift_midpoint(inputs: AttendanceCalculationInput) -> datetime | None:
    if inputs.scheduled_start is None or inputs.scheduled_end is None:
        return None
    return inputs.scheduled_start + (inputs.scheduled_end - inputs.scheduled_start) / 2


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

    presence = evaluate_presence_and_breaks(inputs, pairing, snapshot)
    first_in, last_out, gaps = presence.first_in, presence.last_out, presence.gaps
    matched_breaks = presence.breaks
    totals = presence.totals
    unpaid_minutes = totals.unpaid_minutes
    paid_minutes = totals.paid_minutes
    excess_minutes = totals.excess_minutes
    worked_minutes = presence.worked_minutes

    missing_punch = bool(pairing.orphans) or first_in is None
    auto_closed = False

    late_minutes = 0
    late_classification = None
    early_minutes = 0
    early_classification = None

    # FLEXIBLE: `scheduled_start`/`scheduled_end` are the allowed start window, and any arrival
    # inside it is on time, so lateness runs from the end of the window (§11.8).
    late_from = inputs.scheduled_end if shift.shift_type == "FLEXIBLE" else inputs.scheduled_start
    early_until = inputs.scheduled_end
    # Half-day leave covers one half, so only the worked half can be late or left early. The shift
    # midpoint divides the two; a flexible shift has no midpoint, so nothing is measured.
    leave_half = _half_day_leave_half(inputs)
    if leave_half is not None:
        midpoint = _shift_midpoint(inputs) if shift.shift_type == "FIXED" else None
        if leave_half == "FIRST":
            late_from = midpoint
        else:
            early_until = midpoint
    if first_in is not None and late_from is not None:
        late_raw = int((first_in - late_from).total_seconds() // 60)
        late_minutes = max(0, late_raw - policy.grace_in_minutes)
        if late_minutes > 0:
            late_classification = lookup_band(late_minutes, inputs.late_bands)

    if last_out is not None and early_until is not None:
        early_raw = int((early_until - last_out).total_seconds() // 60)
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
        # Core hours span the working day, so half-day leave would always breach them.
        and leave_half is None
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
        and presence.counter_excess_minutes > 0
        and (inputs.prior_excess_break_days_in_window + 1)
        >= policy.excess_break_days_to_half_day_count
    ):
        cumulative_status_override = "HALF_DAY"

    # Hour bands describe a full day, so the worked half is judged in proportion: 4.5 hours worked
    # around a half-day leave counts as a full 9-hour day would.
    band_minutes = worked_minutes * 2 if leave_half is not None else worked_minutes
    hour_band_status = lookup_band(band_minutes, inputs.hour_bands) if worked_minutes else None

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
    if totals.unresolved_count and not not_expected:
        # An unresolved break is never silently turned into half-day/absent: the day waits for
        # an authorised correction. INCOMPLETE is the existing "needs review" status — not paid,
        # not LOP, and handled at period close by `incomplete_at_lock_behaviour`.
        status = "INCOMPLETE"

    worked_on_holiday = day_type == "HOLIDAY" and worked_minutes > 0
    worked_on_weekly_off = day_type == "WEEKLY_OFF" and worked_minutes > 0

    # FLEXIBLE: `scheduled_start`/`scheduled_end` are the *start-time window* (e.g. 09:00-10:00),
    # not the working span, so the amount of work expected is `required_minutes` (net of unpaid
    # breaks, like `worked_minutes`). Measuring against the window length made a normal 8-hour
    # day look like 7 hours of overtime.
    flexible_required = shift.required_minutes if shift.shift_type == "FLEXIBLE" else None
    scheduled_minutes = (
        flexible_required
        if flexible_required is not None
        else int((inputs.scheduled_end - inputs.scheduled_start).total_seconds() // 60)
        if inputs.scheduled_start and inputs.scheduled_end
        else shift.required_minutes
    )
    # Overtime compares net worked time against the net schedule (the shift less its V1 unpaid
    # breaks), so a deducted lunch does not hide the first hour of overtime. A flexible shift's
    # required minutes are already net of breaks, so nothing is subtracted from them.
    ot_scheduled_minutes = (
        flexible_required
        if flexible_required is not None
        else max(
            0,
            scheduled_minutes
            - scheduled_unpaid_break_minutes(
                shift,
                attendance_date=inputs.attendance_date,
                tz_name=inputs.timezone,
                scheduled_start=inputs.scheduled_start,
            ),
        )
        if scheduled_minutes is not None
        else None
    )

    is_night = resolve_is_night_ot(
        shift=shift,
        policy=inputs.ot_policy,
        timezone=inputs.timezone,
        # The window end is not the end of a flexible working day; the trailing excess is.
        scheduled_end=None if flexible_required is not None else inputs.scheduled_end,
        last_out=last_out,
        worked_minutes=worked_minutes,
        scheduled_minutes=ot_scheduled_minutes,
    )
    ot_minutes, ot_classification, ot_eligible = detect_overtime(
        worked_minutes=worked_minutes,
        scheduled_minutes=ot_scheduled_minutes,
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
            is_holiday=worked_on_holiday, is_weekly_off=worked_on_weekly_off, is_night=is_night
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
        actual_break_minutes=totals.actual_minutes,
        auto_deducted_break_minutes=totals.auto_deducted_minutes,
        unresolved_break_count=totals.unresolved_count,
        has_unresolved_break=totals.unresolved_count > 0,
        has_active_break=totals.has_active,
        has_excess_break_exception=totals.has_excess_exception,
        gross_elapsed_minutes=presence.gross_elapsed_minutes,
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

    presence = evaluate_presence_and_breaks(inputs, pairing, snapshot)
    first_in, last_out = presence.first_in, presence.last_out
    matched_breaks = presence.breaks
    totals = presence.totals
    unpaid_minutes = totals.unpaid_minutes
    paid_minutes = totals.paid_minutes
    worked_minutes = presence.worked_minutes

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
    if totals.unresolved_count and not not_expected:
        status = "INCOMPLETE"

    paid_fraction, lop_fraction = _paid_lop_fraction(status, hour_band_status)

    worked_on_holiday = day_type == "HOLIDAY" and worked_minutes > 0
    worked_on_weekly_off = day_type == "WEEKLY_OFF" and worked_minutes > 0

    # W7 (WD-29 decision 5) — SPLIT shifts previously never detected overtime at all. No input
    # is actually missing here: `scheduled_minutes=shift.required_minutes` is the same fallback
    # `_evaluate_fixed_or_flex` uses whenever no `scheduled_start`/`scheduled_end` is set, so the
    # detection call is wired in identically to that path.
    ot_scheduled_minutes = (
        max(
            0,
            shift.required_minutes
            - scheduled_unpaid_break_minutes(
                shift,
                attendance_date=inputs.attendance_date,
                tz_name=inputs.timezone,
                scheduled_start=inputs.scheduled_start,
            ),
        )
        if shift.required_minutes is not None
        else None
    )
    is_night = resolve_is_night_ot(
        shift=shift,
        policy=inputs.ot_policy,
        timezone=inputs.timezone,
        scheduled_end=inputs.scheduled_end,
        last_out=last_out,
        worked_minutes=worked_minutes,
        scheduled_minutes=ot_scheduled_minutes,
    )
    ot_minutes, ot_classification, ot_eligible = detect_overtime(
        worked_minutes=worked_minutes,
        scheduled_minutes=ot_scheduled_minutes,
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
            is_holiday=worked_on_holiday, is_weekly_off=worked_on_weekly_off, is_night=is_night
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
        excess_break_minutes=totals.excess_minutes,
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
        actual_break_minutes=totals.actual_minutes,
        auto_deducted_break_minutes=totals.auto_deducted_minutes,
        unresolved_break_count=totals.unresolved_count,
        has_unresolved_break=totals.unresolved_count > 0,
        has_active_break=totals.has_active,
        has_excess_break_exception=totals.has_excess_exception,
        gross_elapsed_minutes=presence.gross_elapsed_minutes,
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
