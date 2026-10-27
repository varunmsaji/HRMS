"""Workforce Calendar resolution engine (W1).

Implements two distinct, documented pieces of `docs/architecture/
WORKFORCE_ATTENDANCE_ARCHITECTURE.md`:

1. **Calendar-day classification** (§6.3, §7.3, §8.2) — `classify_work_calendar_date`, a pure
   function: given a WorkCalendar's already-loaded composition (ordered holiday lists,
   weekly-off rules, an optional exception for the date), what kind of day is this? Nothing
   here touches the database — it is deliberately kept side-effect-free for direct unit
   testing (see `tests/unit/modules/organisation/test_calendar_resolution.py`).

2. **Policy-assignment precedence resolution** (§15-16, WD-09) — `CalendarResolutionService`,
   which walks the 8-level scope chain (`EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT >
   BRANCH > LEGAL_ENTITY > COMPANY`) to find which `WorkCalendar`/`WeeklyOffPattern` applies to
   a given employee on a given date, then classifies that date. Fails closed (WD-21) — never
   invents a `WORKING` default when configuration is missing.

Kept as a separate module from `service.py` (already large) per the W1 implementation plan.
No attendance evaluation happens here — this only answers "what kind of day is this?", never
"was the employee present" (architecture §1, the Calendar/Shift/Attendance-Policy split).
"""

from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID

from hrms.core.errors.base import NotFoundError, ValidationError
from hrms.modules.organisation.calendar_overlay import CalendarOverlay, ProposedAssignment
from hrms.modules.organisation.repository import (
    CalendarExceptionRepository,
    HolidayCalendarRepository,
    HolidayRepository,
    OrganisationRepository,
    PolicyAssignmentRepository,
    WeeklyOffPatternRepository,
    WorkCalendarRepository,
)
from hrms.modules.organisation.schemas import CalendarResolutionRead, DayTypeRead

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from hrms.modules.organisation.models import PolicyAssignment, WorkCalendar

# WD-09 — most specific wins. Shift is "the shift resolved for that date, including roster"
# per §16; W1 has no roster yet, so this reads `EmployeeAssignment.shift_id` only.
_PRECEDENCE_SCOPES: tuple[str, ...] = (
    "EMPLOYEE",
    "SHIFT",
    "DESIGNATION",
    "GRADE",
    "DEPARTMENT",
    "BRANCH",
    "LEGAL_ENTITY",
    "COMPANY",
)


# ---------------------------------------------------------------------------
# Pure classification — no DB access.
# ---------------------------------------------------------------------------


_Date = date  # `HolidayData.date` shadows the name inside the class body


@dataclass(frozen=True, slots=True)
class HolidayData:
    date: date
    name: str
    holiday_type: str
    is_paid: bool = True
    # Identity of the stored row; lets a proposed-change overlay replace or remove it.
    holiday_id: UUID | None = None
    # Validity window of the holiday CALENDAR the row belongs to (Work Calendar phase 4, policy D).
    # Both ends inclusive; None = open-ended. Stamped by the loader for every row, including a
    # proposed one, so a holiday outside its calendar's window never reaches the classifier's match.
    calendar_valid_from: _Date | None = None
    calendar_valid_to: _Date | None = None

    def applies_on(self, target: _Date) -> bool:
        if self.calendar_valid_from is not None and target < self.calendar_valid_from:
            return False
        return self.calendar_valid_to is None or target <= self.calendar_valid_to


@dataclass(frozen=True, slots=True)
class WeeklyOffRuleData:
    # Weekday convention: Python's `date.weekday()` — Monday=0 .. Sunday=6 (not ISO's
    # Monday=1..Sunday=7, and not the product-facing MON/TUE/... strings used elsewhere in
    # this module for Company working-day config, which is a different concept entirely).
    weekday: int
    nth_in_month: int | None
    cycle_start_date: date | None
    off_fraction: Decimal
    week_parity: str | None


@dataclass(frozen=True, slots=True)
class CalendarExceptionData:
    exception_type: str
    name: str | None


def _nth_occurrence_in_month(target: date) -> int:
    return (target.day - 1) // 7 + 1


def _is_last_occurrence_in_month(target: date) -> bool:
    days_in_month = monthrange(target.year, target.month)[1]
    return target.day + 7 > days_in_month


def _rule_matches(rule: WeeklyOffRuleData, target: date) -> bool:
    """A rule is self-describing — which fields are set determines how it's evaluated, so the
    same function handles `FIXED_WEEKDAYS`/`NTH_WEEKDAY`/`ALTERNATE`/`CUSTOM` rows uniformly
    (architecture §8.1: "CUSTOM = the same child table, any combination")."""
    if rule.weekday != target.weekday():
        return False
    if rule.nth_in_month is not None:
        if rule.nth_in_month == -1:
            return _is_last_occurrence_in_month(target)
        return _nth_occurrence_in_month(target) == rule.nth_in_month
    if rule.cycle_start_date is not None:
        weeks_since = (target - rule.cycle_start_date).days // 7
        parity = "EVEN" if weeks_since % 2 == 0 else "ODD"
        # No documented default for an ALTERNATE rule with no explicit `week_parity` — treat
        # the cycle-start week itself (weeks_since == 0, i.e. EVEN) as the "off" week, the
        # only reading consistent with "alternate Saturday starting from this date is off".
        wanted_parity = rule.week_parity or "EVEN"
        return parity == wanted_parity
    return True


def evaluate_weekly_off(target: date, rules: list[WeeklyOffRuleData]) -> tuple[bool, Decimal]:
    """Returns `(is_off, off_fraction)`. If more than one rule matches the same date
    (a configuration edge case, not a documented scenario), the most conservative — largest —
    fraction wins."""
    matched = [rule.off_fraction for rule in rules if _rule_matches(rule, target)]
    if not matched:
        return False, Decimal("0")
    return True, max(matched)


def weekly_off_fraction_of(day: "DayTypeRead") -> Decimal:
    """The OFF (non-working) share of a `WEEKLY_OFF` day: 1.00 = a full day off, 0.50 = half off
    and half working. This is the single interpretation of `WeeklyOffRule.off_fraction` /
    `DayTypeRead.weekly_off_fraction`: attendance (`weekly_off_fraction` on the day row, PAY-012)
    and leave (`working_fraction_of`) both derive from it. `None` on a WEEKLY_OFF day means a full
    day - e.g. a holiday on a half-day weekly off covers the working half too (WD-05)."""
    if day.weekly_off_fraction is None:
        return Decimal("1.00")
    return Decimal(day.weekly_off_fraction)


def working_fraction_of(day: "DayTypeRead") -> Decimal:
    """How much of the day an employee is expected to work, hence how much leave can consume:
    WORKING / SPECIAL_WORKING 1.00; WEEKLY_OFF `1 - off share` (0.50 on a half-day weekly off,
    0.00 on a full one); HOLIDAY / SHUTDOWN 0.00."""
    if day.day_type in ("WORKING", "SPECIAL_WORKING"):
        return Decimal("1.00")
    if day.day_type == "WEEKLY_OFF":
        return Decimal("1.00") - weekly_off_fraction_of(day)
    return Decimal("0.00")


def classify_work_calendar_date(
    *,
    target_date: date,
    ordered_holiday_lists: list[list[HolidayData]],
    weekly_off_rules: list[WeeklyOffRuleData],
    restricted_holidays_are_off_by_default: bool,
    exception: CalendarExceptionData | None,
) -> DayTypeRead:
    """architecture §6.3 precedence: CalendarException always wins > composed holiday union
    (first-list-wins tie-break) > weekly-off pattern > WORKING."""
    is_off, off_fraction = evaluate_weekly_off(target_date, weekly_off_rules)

    if exception is not None:
        if exception.exception_type == "SHUTDOWN":
            return DayTypeRead(
                date=target_date,
                day_type="SHUTDOWN",
                holiday_name=exception.name,
                exception_type="SHUTDOWN",
            )
        if exception.exception_type == "SPECIAL_WORKING":
            return DayTypeRead(
                date=target_date,
                day_type="SPECIAL_WORKING",
                holiday_name=exception.name,
                exception_type="SPECIAL_WORKING",
            )
        if exception.exception_type == "SUBSTITUTE_HOLIDAY":
            return DayTypeRead(
                date=target_date,
                day_type="HOLIDAY",
                holiday_name=exception.name,
                exception_type="SUBSTITUTE_HOLIDAY",
                holiday_type="SUBSTITUTE",
                holiday_is_paid=True,
            )
        # CANCEL_HOLIDAY: remove any holiday match for this date only, then fall through to
        # the weekly-off/working check below (architecture §7.3).

    skip_holiday_lookup = exception is not None and exception.exception_type == "CANCEL_HOLIDAY"

    matched_holiday: HolidayData | None = None
    if not skip_holiday_lookup:
        for calendar_holidays in ordered_holiday_lists:
            found = next(
                (
                    h
                    for h in calendar_holidays
                    if h.date == target_date and h.applies_on(target_date)
                ),
                None,
            )
            if found is not None:
                matched_holiday = found
                break

    if matched_holiday is None:
        if is_off:
            return DayTypeRead(
                date=target_date, day_type="WEEKLY_OFF", weekly_off_fraction=off_fraction
            )
        return DayTypeRead(date=target_date, day_type="WORKING")

    if matched_holiday.holiday_type == "WORKING_HOLIDAY":
        return DayTypeRead(
            date=target_date,
            day_type="WORKING",
            holiday_name=matched_holiday.name,
            is_holiday_named=True,
        )

    is_soft = matched_holiday.holiday_type in ("OPTIONAL", "RESTRICTED")
    # PD-CAL-1 (open product decision, architecture §32) — restricted/optional holidays
    # default to "working until Leave applies" unless the WorkCalendar's
    # `restricted_holidays_are_off_by_default` flag says otherwise. This is the only
    # sanctioned per-company override; do not add a second knob for this.
    treat_as_hard_holiday = not is_soft or restricted_holidays_are_off_by_default

    optional_name = (
        matched_holiday.name
        if matched_holiday.holiday_type == "OPTIONAL" and not treat_as_hard_holiday
        else None
    )
    restricted_name = (
        matched_holiday.name
        if matched_holiday.holiday_type == "RESTRICTED" and not treat_as_hard_holiday
        else None
    )

    if treat_as_hard_holiday:
        if is_off:
            # WD-05 — holiday landing on weekly-off stays WEEKLY_OFF with a flag; no
            # auto-substitution (PD-CAL-2, open — default is "stay WO", substitution is an
            # explicit CalendarException pair). `weekly_off_fraction` is left unset (a full day
            # off): the holiday covers the working half of a half-day weekly off too.
            return DayTypeRead(
                date=target_date,
                day_type="WEEKLY_OFF",
                holiday_name=matched_holiday.name,
                holiday_on_weekly_off=True,
                holiday_type=matched_holiday.holiday_type,
                holiday_is_paid=matched_holiday.is_paid,
            )
        return DayTypeRead(
            date=target_date,
            day_type="HOLIDAY",
            holiday_name=matched_holiday.name,
            holiday_type=matched_holiday.holiday_type,
            holiday_is_paid=matched_holiday.is_paid,
        )

    if is_off:
        return DayTypeRead(
            date=target_date,
            day_type="WEEKLY_OFF",
            weekly_off_fraction=off_fraction,
            optional_holiday_name=optional_name,
            restricted_holiday_name=restricted_name,
        )
    return DayTypeRead(
        date=target_date,
        day_type="WORKING",
        optional_holiday_name=optional_name,
        restricted_holiday_name=restricted_name,
    )


# Upper bound for one range request (a six-week month grid plus slack). Keeps the pure loop and
# the response bounded; callers needing more issue several requests.
MAX_CALENDAR_RANGE_DAYS = 100


class CalendarRangeInvalidError(ValidationError):
    code = "CALENDAR_RANGE_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(
            message, details=[{"field": "to", "code": "CALENDAR_RANGE_INVALID", "message": message}]
        )


class HolidayIsWorkingConflictError(ValidationError):
    code = "HOLIDAY_IS_WORKING_CONFLICT"

    def __init__(self, holiday_type: str, is_working: bool) -> None:
        message = (
            "is_working must match the holiday type: it is true exactly for WORKING_HOLIDAY "
            f"(got holiday_type={holiday_type}, is_working={str(is_working).lower()})"
        )
        super().__init__(
            message,
            details=[
                {"field": "is_working", "code": "HOLIDAY_IS_WORKING_CONFLICT", "message": message}
            ],
        )


def reconcile_holiday_is_working(*, holiday_type: str, is_working: bool, explicit: bool) -> bool:
    """Policy C - `Holiday.is_working` is a stored mirror of `holiday_type == "WORKING_HOLIDAY"`
    (architecture: "true for WORKING_HOLIDAY"). Resolution reads the type, never the flag, so the
    two can never disagree about a day. A client that states the flag explicitly must state the
    value the type implies (otherwise 422); one that omits it gets the implied value."""
    expected = holiday_type == "WORKING_HOLIDAY"
    if explicit and is_working != expected:
        raise HolidayIsWorkingConflictError(holiday_type, is_working)
    return expected


def validate_calendar_range(start: date, end: date) -> None:
    if end < start:
        raise CalendarRangeInvalidError("'to' must not be before 'from'")
    if (end - start).days + 1 > MAX_CALENDAR_RANGE_DAYS:
        raise CalendarRangeInvalidError(
            f"The requested range may not exceed {MAX_CALENDAR_RANGE_DAYS} days"
        )


def classify_date_range(
    *,
    start: date,
    end: date,
    ordered_holiday_lists: list[list[HolidayData]],
    weekly_off_rules: list[WeeklyOffRuleData],
    restricted_holidays_are_off_by_default: bool,
    exception_by_date: dict[date, CalendarExceptionData],
) -> list[DayTypeRead]:
    """Pure: applies `classify_work_calendar_date` to each date of an inclusive range. Takes an
    in-memory composition, so it also evaluates a proposed (unsaved) configuration."""
    return [
        classify_work_calendar_date(
            target_date=start + timedelta(days=offset),
            ordered_holiday_lists=ordered_holiday_lists,
            weekly_off_rules=weekly_off_rules,
            restricted_holidays_are_off_by_default=restricted_holidays_are_off_by_default,
            exception=exception_by_date.get(start + timedelta(days=offset)),
        )
        for offset in range((end - start).days + 1)
    ]


# ---------------------------------------------------------------------------
# Precedence resolution — reads the database, calls into `employee` locally.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalendarChoice:
    work_calendar: "WorkCalendar"
    resolved_scope: str
    weekly_off_pattern_id: UUID | None
    weekly_off_scope: str | None


class CalendarResolutionService:
    def __init__(
        self,
        session: "AsyncSession",
        *,
        overlay: CalendarOverlay | None = None,
        memo: dict[object, object] | None = None,
    ) -> None:
        """`overlay` evaluates a proposed, unsaved change (change-impact preview). `memo`, when
        given, caches identical assignment lookups across many resolutions of one request."""
        self._session = session
        self._overlay = overlay
        self._memo = memo
        self._org_repo = OrganisationRepository()
        self._policy_assignment_repo = PolicyAssignmentRepository()
        self._work_calendar_repo = WorkCalendarRepository()
        self._holiday_repo = HolidayRepository()
        self._holiday_calendar_repo = HolidayCalendarRepository()
        self._weekly_off_repo = WeeklyOffPatternRepository()
        self._calendar_exception_repo = CalendarExceptionRepository()

    async def _scope_candidates(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> list[tuple[str, UUID | None]]:
        """Local, function-scoped import — mirrors the existing reverse-direction precedent
        (`employee/service.py` imports `organisation.service.OrganisationService` locally
        inside each method, never at module top-level); the import-linter `layers` contract
        allows sibling `hrms.modules` imports, this only follows the established style."""
        from hrms.modules.employee.service import EmployeeAssignmentService

        assignment_service = EmployeeAssignmentService(self._session)
        assignment = await assignment_service.get_assignment_as_of(
            company_id, employee_id, target_date
        )

        candidates: list[tuple[str, UUID | None]] = [("EMPLOYEE", employee_id)]
        if assignment is None:
            candidates.append(("COMPANY", None))
            return candidates

        if assignment.shift_id is not None:
            candidates.append(("SHIFT", assignment.shift_id))
        if assignment.designation_id is not None:
            candidates.append(("DESIGNATION", assignment.designation_id))
        if assignment.grade_id is not None:
            candidates.append(("GRADE", assignment.grade_id))
        if assignment.department_id is not None:
            candidates.append(("DEPARTMENT", assignment.department_id))
        if assignment.branch_id is not None:
            candidates.append(("BRANCH", assignment.branch_id))
            branch = await self._org_repo.get_branch(
                self._session, company_id=company_id, branch_id=assignment.branch_id
            )
            if branch is not None:
                candidates.append(("LEGAL_ENTITY", branch.legal_entity_id))
        candidates.append(("COMPANY", None))
        return candidates

    async def resolve_policy_assignment(
        self,
        company_id: UUID,
        policy_kind: str,
        *,
        employee_id: UUID,
        target_date: date,
        leave_type_id: UUID | None = None,
    ) -> tuple["PolicyAssignment", str] | None:
        """WD-09's 8-level precedence walk. Returns `(assignment, matched_scope_type)` or
        `None` — fail-closed, never guesses a default (WD-21). `leave_type_id` (LD-11) is passed
        through for `policy_kind="LEAVE_POLICY"`, where a scope can have multiple simultaneously
        active assignments, one per leave type."""
        for scope_type, scope_id in await self._scope_candidates(
            company_id, employee_id, target_date
        ):
            memo_key = (
                "assignment",
                company_id,
                policy_kind,
                scope_type,
                scope_id,
                target_date,
                leave_type_id,
            )
            if self._memo is not None and memo_key in self._memo:
                found = cast("PolicyAssignment | None", self._memo[memo_key])
            else:
                found = await self._policy_assignment_repo.find_effective(
                    self._session,
                    company_id=company_id,
                    policy_kind=policy_kind,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    as_of=target_date,
                    leave_type_id=leave_type_id,
                )
                if self._memo is not None:
                    self._memo[memo_key] = found
            if self._overlay is not None:
                replaced, proposed = self._overlay.adjust_assignment(
                    policy_kind, scope_type, scope_id, target_date, found
                )
                if replaced:
                    found = self._proposed_row(company_id, proposed)
            if found is not None:
                return found, scope_type
        return None

    @staticmethod
    def _proposed_row(
        company_id: UUID, proposed: ProposedAssignment | None
    ) -> "PolicyAssignment | None":
        if proposed is None:
            return None
        from hrms.modules.organisation.models import PolicyAssignment

        # Transient, never added to a session: carries only what the resolver reads.
        return PolicyAssignment(
            company_id=company_id,
            policy_kind=proposed.policy_kind,
            policy_id=proposed.policy_id,
            scope_type=proposed.scope_type,
            scope_id=proposed.scope_id,
            effective_from=proposed.effective_from,
            effective_to=proposed.effective_to,
        )

    async def _load_ordered_holidays(
        self, company_id: UUID, work_calendar_id: UUID
    ) -> list[list[HolidayData]]:
        links = await self._work_calendar_repo.list_holiday_calendar_links(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        calendar_ids = [link.holiday_calendar_id for link in links]
        if self._overlay is not None:
            calendar_ids = self._overlay.adjust_links(work_calendar_id, calendar_ids)
        return await self.load_ordered_holidays_for_calendars(company_id, calendar_ids)

    async def load_ordered_holidays_for_calendars(
        self, company_id: UUID, holiday_calendar_ids: list[UUID]
    ) -> list[list[HolidayData]]:
        """Read-only. One query for all calendars; result order follows `holiday_calendar_ids`
        (first list wins a display-name tie). Also used to evaluate a *proposed* composition
        that has not been saved."""
        if not holiday_calendar_ids:
            return []
        all_holidays = await self._holiday_repo.list_for_calendars(
            self._session,
            company_id=company_id,
            calendar_ids=holiday_calendar_ids,
        )
        by_calendar: dict[UUID, list[HolidayData]] = {cid: [] for cid in holiday_calendar_ids}
        windows = await self._holiday_calendar_windows(company_id, holiday_calendar_ids)
        for holiday in all_holidays:
            by_calendar[holiday.calendar_id].append(
                HolidayData(
                    date=holiday.date,
                    name=holiday.name,
                    holiday_type=holiday.holiday_type,
                    is_paid=holiday.is_paid,
                    holiday_id=holiday.id,
                )
            )
        lists = (
            [self._overlay.adjust_holidays(cid, by_calendar[cid]) for cid in holiday_calendar_ids]
            if self._overlay is not None
            else [by_calendar[cid] for cid in holiday_calendar_ids]
        )
        # Policy D: stamp each calendar's validity window on every row, proposed rows included.
        return [
            [
                replace(h, calendar_valid_from=windows[cid][0], calendar_valid_to=windows[cid][1])
                for h in rows
            ]
            for cid, rows in zip(holiday_calendar_ids, lists, strict=True)
        ]

    async def _holiday_calendar_windows(
        self, company_id: UUID, holiday_calendar_ids: list[UUID]
    ) -> dict[UUID, tuple[date | None, date | None]]:
        """(valid_from, valid_to) per holiday calendar - one query, plus the overlay's proposed
        validity change. A calendar that cannot be read gets an open window (it has no holidays
        either, so nothing is resolved from it)."""
        rows = await self._holiday_calendar_repo.list_by_ids(
            self._session, company_id=company_id, calendar_ids=holiday_calendar_ids
        )
        windows: dict[UUID, tuple[date | None, date | None]] = {
            cid: (None, None) for cid in holiday_calendar_ids
        }
        for row in rows:
            windows[row.id] = (row.valid_from, row.valid_to)
        if self._overlay is not None:
            for cid in holiday_calendar_ids:
                windows[cid] = self._overlay.adjust_validity(cid, windows[cid])
        return windows

    async def _load_weekly_off_rules(
        self, company_id: UUID, pattern_id: UUID | None
    ) -> list[WeeklyOffRuleData]:
        if pattern_id is None:
            return []
        rules = await self._weekly_off_repo.list_rules(
            self._session, company_id=company_id, pattern_id=pattern_id
        )
        loaded = [
            WeeklyOffRuleData(
                weekday=rule.weekday,
                nth_in_month=rule.nth_in_month,
                cycle_start_date=rule.cycle_start_date,
                off_fraction=rule.off_fraction,
                week_parity=rule.week_parity,
            )
            for rule in rules
        ]
        if self._overlay is not None:
            return self._overlay.adjust_rules(pattern_id, loaded)
        return loaded

    async def _load_exception(
        self, company_id: UUID, work_calendar_id: UUID, target_date: date
    ) -> CalendarExceptionData | None:
        exceptions = await self._calendar_exception_repo.list_active_for_calendars(
            self._session, company_id=company_id, work_calendar_ids=[work_calendar_id]
        )
        if self._overlay is not None:
            exceptions = self._overlay.adjust_exceptions(work_calendar_id, exceptions)
        match = next((e for e in exceptions if e.exception_date == target_date), None)
        if match is None:
            return None
        return CalendarExceptionData(exception_type=match.exception_type, name=match.name)

    def _calendar_settings(self, work_calendar: "WorkCalendar") -> tuple[UUID | None, bool]:
        pattern_id = work_calendar.weekly_off_pattern_id
        restricted_off = work_calendar.restricted_holidays_are_off_by_default
        if self._overlay is not None:
            return self._overlay.adjust_settings(work_calendar.id, pattern_id, restricted_off)
        return pattern_id, restricted_off

    async def classify_date_for_work_calendar(
        self,
        company_id: UUID,
        work_calendar_id: UUID,
        target_date: date,
        *,
        weekly_off_pattern_id_override: UUID | None = None,
        _weekly_off_override_present: bool = False,
    ) -> DayTypeRead:
        """Calendar-level classification — powers `/work-calendars/{id}/day-type` directly,
        and is reused by `resolve_for_employee` with an explicit weekly-off pattern override
        when a `WEEKLY_OFF`-kind `PolicyAssignment` outranks the calendar's own default."""
        work_calendar = await self._work_calendar_repo.get(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        if work_calendar is None:
            raise NotFoundError("Resource not found")

        ordered_holiday_lists = await self._load_ordered_holidays(company_id, work_calendar_id)
        calendar_pattern_id, restricted_off = self._calendar_settings(work_calendar)
        effective_pattern_id = (
            weekly_off_pattern_id_override if _weekly_off_override_present else calendar_pattern_id
        )
        weekly_off_rules = await self._load_weekly_off_rules(company_id, effective_pattern_id)
        exception = await self._load_exception(company_id, work_calendar_id, target_date)

        return classify_work_calendar_date(
            target_date=target_date,
            ordered_holiday_lists=ordered_holiday_lists,
            weekly_off_rules=weekly_off_rules,
            restricted_holidays_are_off_by_default=restricted_off,
            exception=exception,
        )

    async def classify_range_for_work_calendar(
        self,
        company_id: UUID,
        work_calendar_id: UUID,
        start: date,
        end: date,
        *,
        weekly_off_pattern_id_override: UUID | None = None,
        _weekly_off_override_present: bool = False,
    ) -> list[DayTypeRead]:
        """Calendar-level classification of every date in `[start, end]` with a constant number
        of queries (holiday links, holidays, weekly-off rules, exceptions), independent of the
        range length. Same classifier as the single-date path - no second rule engine. Uses the
        calendar's own weekly-off pattern unless the caller passes the resolved employee-level
        `WEEKLY_OFF` pattern (`_weekly_off_override_present=True`, same convention as
        `classify_date_for_work_calendar`)."""
        validate_calendar_range(start, end)
        work_calendar = await self._work_calendar_repo.get(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        if work_calendar is None:
            raise NotFoundError("Resource not found")
        ordered_holiday_lists = await self._load_ordered_holidays(company_id, work_calendar_id)
        calendar_pattern_id, restricted_off = self._calendar_settings(work_calendar)
        effective_pattern_id = (
            weekly_off_pattern_id_override if _weekly_off_override_present else calendar_pattern_id
        )
        weekly_off_rules = await self._load_weekly_off_rules(company_id, effective_pattern_id)
        exceptions = await self._calendar_exception_repo.list_active_for_calendars(
            self._session, company_id=company_id, work_calendar_ids=[work_calendar_id]
        )
        if self._overlay is not None:
            exceptions = self._overlay.adjust_exceptions(work_calendar_id, exceptions)
        exception_by_date: dict[date, CalendarExceptionData] = {}
        for row in exceptions:
            exception_by_date.setdefault(
                row.exception_date,
                CalendarExceptionData(exception_type=row.exception_type, name=row.name),
            )
        return classify_date_range(
            start=start,
            end=end,
            ordered_holiday_lists=ordered_holiday_lists,
            weekly_off_rules=weekly_off_rules,
            restricted_holidays_are_off_by_default=restricted_off,
            exception_by_date=exception_by_date,
        )

    async def resolve_calendar_choice(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> "CalendarChoice | None":
        """Which work calendar and weekly-off pattern apply to the employee on a date, without
        classifying the date. `None` = fail closed (WD-21). Shared by `resolve_for_employee` and
        range callers that classify many dates against one resolved pair."""
        calendar_result = await self.resolve_policy_assignment(
            company_id, "WORK_CALENDAR", employee_id=employee_id, target_date=target_date
        )
        if calendar_result is None:
            return None
        assignment, resolved_scope = calendar_result

        memo_key = ("work_calendar", company_id, assignment.policy_id)
        if self._memo is not None and memo_key in self._memo:
            work_calendar_row = cast("WorkCalendar | None", self._memo[memo_key])
        else:
            work_calendar_row = await self._work_calendar_repo.get(
                self._session, company_id=company_id, work_calendar_id=assignment.policy_id
            )
            if self._memo is not None:
                self._memo[memo_key] = work_calendar_row
        if work_calendar_row is None:
            # The assignment points at a WorkCalendar that no longer exists or was
            # deactivated after the assignment was made - fail closed (WD-21), never guess.
            return None

        weekly_off_result = await self.resolve_policy_assignment(
            company_id, "WEEKLY_OFF", employee_id=employee_id, target_date=target_date
        )
        effective_weekly_off_pattern_id = self._calendar_settings(work_calendar_row)[0]
        weekly_off_scope: str | None = None
        if weekly_off_result is not None:
            weekly_off_assignment, weekly_off_scope = weekly_off_result
            effective_weekly_off_pattern_id = weekly_off_assignment.policy_id
        return CalendarChoice(
            work_calendar=work_calendar_row,
            resolved_scope=resolved_scope,
            weekly_off_pattern_id=effective_weekly_off_pattern_id,
            weekly_off_scope=weekly_off_scope,
        )

    async def resolve_for_employee(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> CalendarResolutionRead:
        """architecture section 10's contract: employee + date -> resolved calendar -> day type.
        Fails closed to `config_incomplete=True` (WD-21) rather than assuming `WORKING`."""
        choice = await self.resolve_calendar_choice(company_id, employee_id, target_date)
        if choice is None:
            return CalendarResolutionRead(
                employee_id=employee_id, date=target_date, config_incomplete=True
            )
        day_type = await self.classify_date_for_work_calendar(
            company_id,
            choice.work_calendar.id,
            target_date,
            weekly_off_pattern_id_override=choice.weekly_off_pattern_id,
            _weekly_off_override_present=True,
        )
        return CalendarResolutionRead(
            employee_id=employee_id,
            date=target_date,
            config_incomplete=False,
            work_calendar_id=choice.work_calendar.id,
            work_calendar_name=choice.work_calendar.name,
            resolved_scope_type=choice.resolved_scope,
            weekly_off_pattern_id=choice.weekly_off_pattern_id,
            weekly_off_resolved_scope_type=choice.weekly_off_scope,
            day_type=day_type,
        )
