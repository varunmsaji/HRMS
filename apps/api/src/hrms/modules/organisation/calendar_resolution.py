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
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.repository import (
    CalendarExceptionRepository,
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


@dataclass(frozen=True, slots=True)
class HolidayData:
    date: date
    name: str
    holiday_type: str
    is_paid: bool = True


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
            found = next((h for h in calendar_holidays if h.date == target_date), None)
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


# ---------------------------------------------------------------------------
# Precedence resolution — reads the database, calls into `employee` locally.
# ---------------------------------------------------------------------------


class CalendarResolutionService:
    def __init__(self, session: "AsyncSession") -> None:
        self._session = session
        self._org_repo = OrganisationRepository()
        self._policy_assignment_repo = PolicyAssignmentRepository()
        self._work_calendar_repo = WorkCalendarRepository()
        self._holiday_repo = HolidayRepository()
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
            found = await self._policy_assignment_repo.find_effective(
                self._session,
                company_id=company_id,
                policy_kind=policy_kind,
                scope_type=scope_type,
                scope_id=scope_id,
                as_of=target_date,
                leave_type_id=leave_type_id,
            )
            if found is not None:
                return found, scope_type
        return None

    async def _load_ordered_holidays(
        self, company_id: UUID, work_calendar_id: UUID
    ) -> list[list[HolidayData]]:
        links = await self._work_calendar_repo.list_holiday_calendar_links(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        if not links:
            return []
        all_holidays = await self._holiday_repo.list_for_calendars(
            self._session,
            company_id=company_id,
            calendar_ids=[link.holiday_calendar_id for link in links],
        )
        by_calendar: dict[UUID, list[HolidayData]] = {
            link.holiday_calendar_id: [] for link in links
        }
        for holiday in all_holidays:
            by_calendar[holiday.calendar_id].append(
                HolidayData(
                    date=holiday.date,
                    name=holiday.name,
                    holiday_type=holiday.holiday_type,
                    is_paid=holiday.is_paid,
                )
            )
        return [by_calendar[link.holiday_calendar_id] for link in links]

    async def _load_weekly_off_rules(
        self, company_id: UUID, pattern_id: UUID | None
    ) -> list[WeeklyOffRuleData]:
        if pattern_id is None:
            return []
        rules = await self._weekly_off_repo.list_rules(
            self._session, company_id=company_id, pattern_id=pattern_id
        )
        return [
            WeeklyOffRuleData(
                weekday=rule.weekday,
                nth_in_month=rule.nth_in_month,
                cycle_start_date=rule.cycle_start_date,
                off_fraction=rule.off_fraction,
                week_parity=rule.week_parity,
            )
            for rule in rules
        ]

    async def _load_exception(
        self, company_id: UUID, work_calendar_id: UUID, target_date: date
    ) -> CalendarExceptionData | None:
        exceptions = await self._calendar_exception_repo.list_active_for_calendars(
            self._session, company_id=company_id, work_calendar_ids=[work_calendar_id]
        )
        match = next((e for e in exceptions if e.exception_date == target_date), None)
        if match is None:
            return None
        return CalendarExceptionData(exception_type=match.exception_type, name=match.name)

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
        effective_pattern_id = (
            weekly_off_pattern_id_override
            if _weekly_off_override_present
            else work_calendar.weekly_off_pattern_id
        )
        weekly_off_rules = await self._load_weekly_off_rules(company_id, effective_pattern_id)
        exception = await self._load_exception(company_id, work_calendar_id, target_date)

        return classify_work_calendar_date(
            target_date=target_date,
            ordered_holiday_lists=ordered_holiday_lists,
            weekly_off_rules=weekly_off_rules,
            restricted_holidays_are_off_by_default=work_calendar.restricted_holidays_are_off_by_default,
            exception=exception,
        )

    async def resolve_for_employee(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> CalendarResolutionRead:
        """architecture §10's contract: employee + date -> resolved calendar -> day type.
        Fails closed to `config_incomplete=True` (WD-21) rather than assuming `WORKING`."""
        calendar_result = await self.resolve_policy_assignment(
            company_id, "WORK_CALENDAR", employee_id=employee_id, target_date=target_date
        )
        if calendar_result is None:
            return CalendarResolutionRead(
                employee_id=employee_id, date=target_date, config_incomplete=True
            )
        assignment, resolved_scope = calendar_result

        work_calendar_row: WorkCalendar | None = await self._work_calendar_repo.get(
            self._session, company_id=company_id, work_calendar_id=assignment.policy_id
        )
        if work_calendar_row is None:
            # The assignment points at a WorkCalendar that no longer exists or was
            # deactivated after the assignment was made — fail closed (WD-21), never guess.
            return CalendarResolutionRead(
                employee_id=employee_id, date=target_date, config_incomplete=True
            )

        weekly_off_result = await self.resolve_policy_assignment(
            company_id, "WEEKLY_OFF", employee_id=employee_id, target_date=target_date
        )
        effective_weekly_off_pattern_id = work_calendar_row.weekly_off_pattern_id
        weekly_off_scope: str | None = None
        if weekly_off_result is not None:
            weekly_off_assignment, weekly_off_scope = weekly_off_result
            effective_weekly_off_pattern_id = weekly_off_assignment.policy_id

        day_type = await self.classify_date_for_work_calendar(
            company_id,
            work_calendar_row.id,
            target_date,
            weekly_off_pattern_id_override=effective_weekly_off_pattern_id,
            _weekly_off_override_present=True,
        )

        return CalendarResolutionRead(
            employee_id=employee_id,
            date=target_date,
            config_incomplete=False,
            work_calendar_id=work_calendar_row.id,
            work_calendar_name=work_calendar_row.name,
            resolved_scope_type=resolved_scope,
            weekly_off_pattern_id=effective_weekly_off_pattern_id,
            weekly_off_resolved_scope_type=weekly_off_scope,
            day_type=day_type,
        )
