"""The one resolution of an employee's work schedule for a date (Invariant A,
`docs/audits/SHIFT_REMEDIATION_PLAN_2026-11-15.md` §3.1).

Precedence, the same for every caller: a PUBLISHED roster row for the date, else the shift on the
employee assignment covering the date, else no shift. A roster row whose `shift_id` is NULL (a
pure day off) means no shift; it never falls back to the assignment.

Day calculation, the self-service shift-window check, punch ownership, SHIFT-scoped policy and
calendar resolution, Leave's working shares and the employee/planner views all read the schedule
through this module, so no two of them can disagree about which shift applies.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.attendance import calculation as calc
from hrms.modules.attendance.schemas import _parse_time
from hrms.shared.timezone import TimezoneConfigurationError, resolve_zoneinfo

ScheduleSource = Literal["ROSTER", "ASSIGNMENT", "NONE"]


@dataclass(frozen=True)
class ResolvedShiftSchedule:
    shift_inputs: calc.ShiftInputs | None
    shift_version_id: UUID | None
    tz_name: str
    window: calc.ScheduleWindow


def zone_or_none(tz_name: str | None) -> ZoneInfo | None:
    """A stored timezone, or None when it is missing or no longer resolvable.

    `None` is not a guess at UTC: the shift-window check fails open when the date it would
    judge cannot be resolved (`TimezoneConfigurationError`), rather than refusing a punch
    against the wrong day or failing the request."""
    if not tz_name:
        return None
    try:
        return resolve_zoneinfo(tz_name)
    except TimezoneConfigurationError:
        return None


async def resolve_shift_schedule(
    organisation_service: Any,
    *,
    company_id: UUID,
    shift_id: UUID | None,
    target_date: date,
    branch_timezone: str | None,
    company_timezone: str,
) -> ResolvedShiftSchedule:
    """The shift version, timezone and schedule window of `shift_id` on one date. The single
    resolution both the calculation input and the self-service punch shift-window check use."""
    from hrms.modules.organisation.exceptions import ShiftVersionNotFoundForDateError

    shift_inputs: calc.ShiftInputs | None = None
    shift_version_timezone: str | None = None
    shift_version_id: UUID | None = None
    raw_start_time = raw_end_time = raw_window_start = raw_window_end = None
    if shift_id is not None:
        try:
            shift_version = await organisation_service.resolve_shift_version_as_of(
                company_id, shift_id, target_date
            )
        except ShiftVersionNotFoundForDateError:
            shift_version = None
        if shift_version is not None:
            shift_version_id = shift_version.id
            shift_version_timezone = shift_version.timezone
            raw_start_time = (
                _parse_time(shift_version.start_time) if shift_version.start_time else None
            )
            raw_end_time = _parse_time(shift_version.end_time) if shift_version.end_time else None
            raw_window_start = (
                _parse_time(shift_version.window_start) if shift_version.window_start else None
            )
            raw_window_end = (
                _parse_time(shift_version.window_end) if shift_version.window_end else None
            )
            shift_inputs = calc.ShiftInputs(
                shift_type=shift_version.shift_type,
                is_ot_eligible=shift_version.is_ot_eligible,
                operates_on_holiday=shift_version.operates_on_holiday,
                operates_on_weekly_off=shift_version.operates_on_weekly_off,
                is_cross_midnight=shift_version.is_cross_midnight,
                is_night_shift=shift_version.is_night_shift,
                breaks=[
                    calc.ShiftBreakData(
                        id=b.id,
                        break_kind=b.break_kind,
                        start_time=_parse_time(b.start_time) if b.start_time else None,
                        end_time=_parse_time(b.end_time) if b.end_time else None,
                        window_start=_parse_time(b.window_start) if b.window_start else None,
                        window_end=_parse_time(b.window_end) if b.window_end else None,
                        min_minutes=b.min_minutes,
                        max_minutes=b.max_minutes,
                        is_paid=b.is_paid,
                        is_mandatory=b.is_mandatory,
                        name=b.name,
                        break_type=b.break_type,
                        mode=b.mode,
                        scheduled_minutes=b.scheduled_minutes,
                        crosses_midnight=b.crosses_midnight,
                        excess_outcome=b.excess_outcome,
                        auto_deduct_full=b.auto_deduct_full,
                        optional_recorded_deducts=b.optional_recorded_deducts,
                        optional_scheduled_fallback=b.optional_scheduled_fallback,
                        is_enabled=b.is_enabled,
                        sort_order=b.sort_order,
                        allows_split=b.allows_split,
                    )
                    for b in shift_version.breaks
                ],
                duty_blocks=[
                    calc.ShiftDutyBlockData(
                        sequence=d.sequence,
                        start_time=_parse_time(d.start_time),
                        end_time=_parse_time(d.end_time),
                        crosses_midnight=d.crosses_midnight,
                    )
                    for d in shift_version.duty_blocks
                ],
                core_start=(
                    _parse_time(shift_version.core_start) if shift_version.core_start else None
                ),
                core_end=(_parse_time(shift_version.core_end) if shift_version.core_end else None),
                required_minutes=shift_version.required_minutes,
            )

    tz_name = calc.resolve_timezone(
        shift_version_timezone=shift_version_timezone,
        branch_timezone=branch_timezone,
        company_timezone=company_timezone,
    )

    window = calc.resolve_schedule_window(
        attendance_date=target_date,
        tz_name=tz_name,
        shift=shift_inputs,
        start_time=raw_start_time,
        end_time=raw_end_time,
        window_start=raw_window_start,
        window_end=raw_window_end,
    )
    return ResolvedShiftSchedule(
        shift_inputs=shift_inputs,
        shift_version_id=shift_version_id,
        tz_name=tz_name,
        window=window,
    )


@dataclass(frozen=True)
class ResolvedWorkSchedule:
    """Everything about one employee-date's schedule that downstream code may depend on."""

    employee_id: UUID
    target_date: date
    assignment: Any | None
    roster_entry: Any | None
    shift_id: UUID | None
    source: ScheduleSource
    company_timezone: str
    branch_timezone: str | None
    schedule: ResolvedShiftSchedule

    @property
    def roster_week_off_override(self) -> bool:
        return bool(self.roster_entry is not None and self.roster_entry.is_week_off_override)

    @property
    def roster_holiday_working_override(self) -> bool:
        return bool(self.roster_entry is not None and self.roster_entry.is_holiday_working_override)

    @property
    def version_missing(self) -> bool:
        """A shift is named for the date but has no published version covering it - a
        configuration gap, as opposed to an employee who simply has no shift."""
        return self.shift_id is not None and self.schedule.shift_inputs is None


def shift_id_for(
    assignment: Any | None, roster_entry: Any | None
) -> tuple[UUID | None, ScheduleSource]:
    """The precedence rule itself, as a pure function."""
    if roster_entry is not None:
        return roster_entry.shift_id, "ROSTER"
    if assignment is not None and assignment.shift_id is not None:
        return assignment.shift_id, "ASSIGNMENT"
    return None, "NONE"


async def resolved_shift_id(
    session: AsyncSession, company_id: UUID, employee_id: UUID, target_date: date
) -> UUID | None:
    """Only the shift id - for callers (policy and calendar scope) that need nothing else."""
    from hrms.modules.attendance.repository import ShiftRosterRepository
    from hrms.modules.employee.service import EmployeeAssignmentService

    assignment = await EmployeeAssignmentService(session).get_assignment_as_of(
        company_id, employee_id, target_date
    )
    roster_entry = await ShiftRosterRepository().get_published_for_date(
        session, company_id=company_id, employee_id=employee_id, roster_date=target_date
    )
    return shift_id_for(assignment, roster_entry)[0]


@dataclass
class WorkScheduleResolver:
    """Resolves `ResolvedWorkSchedule`s, memoising within one unit of work (a request or one
    calculation), so resolving the neighbouring days for punch ownership stays cheap."""

    session: AsyncSession
    _company_tz: dict[UUID, str] = field(default_factory=dict)
    _branch_tz: dict[tuple[UUID, UUID], str | None] = field(default_factory=dict)
    _memo: dict[tuple[UUID, UUID, date], ResolvedWorkSchedule] = field(default_factory=dict)

    async def company_timezone(self, company_id: UUID) -> str:
        if company_id not in self._company_tz:
            from hrms.modules.organisation.service import OrganisationService

            company = await OrganisationService(self.session).get_company_profile(company_id)
            self._company_tz[company_id] = company.timezone
        return self._company_tz[company_id]

    async def _branch_timezone(self, company_id: UUID, branch_id: UUID | None) -> str | None:
        if branch_id is None:
            return None
        key = (company_id, branch_id)
        if key not in self._branch_tz:
            from hrms.modules.organisation.service import OrganisationService

            branch = await OrganisationService(self.session).get_branch(company_id, branch_id)
            self._branch_tz[key] = branch.timezone
        return self._branch_tz[key]

    async def resolve(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> ResolvedWorkSchedule:
        key = (company_id, employee_id, target_date)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        from hrms.modules.attendance.repository import ShiftRosterRepository
        from hrms.modules.employee.service import EmployeeAssignmentService
        from hrms.modules.organisation.service import OrganisationService

        assignment = await EmployeeAssignmentService(self.session).get_assignment_as_of(
            company_id, employee_id, target_date
        )
        roster_entry = await ShiftRosterRepository().get_published_for_date(
            self.session, company_id=company_id, employee_id=employee_id, roster_date=target_date
        )
        shift_id, source = shift_id_for(assignment, roster_entry)
        company_tz = await self.company_timezone(company_id)
        branch_tz = await self._branch_timezone(
            company_id, assignment.branch_id if assignment is not None else None
        )
        schedule = await resolve_shift_schedule(
            OrganisationService(self.session),
            company_id=company_id,
            shift_id=shift_id,
            target_date=target_date,
            branch_timezone=branch_tz,
            company_timezone=company_tz,
        )
        resolved = ResolvedWorkSchedule(
            employee_id=employee_id,
            target_date=target_date,
            assignment=assignment,
            roster_entry=roster_entry,
            shift_id=shift_id,
            source=source,
            company_timezone=company_tz,
            branch_timezone=branch_tz,
            schedule=schedule,
        )
        self._memo[key] = resolved
        return resolved
