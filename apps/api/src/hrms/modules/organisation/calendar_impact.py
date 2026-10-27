"""Work-calendar change-impact preview and safe confirmation (Work Calendar phase 3).

`preview` answers "what would this change do?" without writing anything: the proposed change is
applied to the one resolver as an in-memory `CalendarOverlay` (see `calendar_overlay`), and every
affected employee's dates are classified twice - current rules vs proposed rules - with the same
`classify_work_calendar_date`. No temporary records are created.

`confirm` is never authorised by a preview. It takes the change again plus the `impact_digest` the
administrator saw, takes a per-company advisory lock, recomputes the impact against the database
as it is *now*, and refuses (409 `CALENDAR_PREVIEW_STALE`) if the digest differs. Only then does
it call the existing `OrganisationService` method for the change, in the request's transaction,
and records one extra audit event. Calendar changes never rewrite leave days, attendance or
payroll; they are reported, and protected periods require an explicit acknowledgement.

Population handling: employees are grouped by identical placement history (branch, department,
designation, grade, shift over time) so the resolver runs once per group, not once per employee.
Employees with their own EMPLOYEE-scope assignment are resolved individually. The population and
group counts are capped; when a cap is hit the result says so instead of pretending to be exact.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.core.db.timeouts import bounded_lock_wait
from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError
from hrms.modules.organisation.calendar_overlay import (
    CalendarOverlay,
    ExceptionRow,
    ProposedAssignment,
)
from hrms.modules.organisation.calendar_resolution import (
    MAX_CALENDAR_RANGE_DAYS,
    CalendarResolutionService,
    HolidayData,
    WeeklyOffRuleData,
    reconcile_holiday_is_working,
)
from hrms.modules.organisation.exceptions import StaleResourceError
from hrms.modules.organisation.models import PolicyAssignment
from hrms.modules.organisation.repository import (
    CalendarExceptionRepository,
    HolidayCalendarRepository,
    HolidayRepository,
    PolicyAssignmentRepository,
    WeeklyOffPatternRepository,
    WorkCalendarRepository,
)
from hrms.modules.organisation.schemas import (
    CalendarExceptionCreate,
    CalendarExceptionUpdate,
    DayTypeRead,
    HolidayCalendarUpdate,
    HolidayCreate,
    HolidayUpdate,
    PolicyAssignmentCreate,
    WeeklyOffPatternUpdate,
    WorkCalendarUpdate,
)
from hrms.modules.organisation.service import OrganisationService

MAX_PREVIEW_WINDOW_DAYS = 366
MAX_PREVIEW_EMPLOYEES = 5000
MAX_PREVIEW_GROUPS = 300
MAX_ROWS_RETURNED = 500
MAX_LEAVE_ITEMS = 100
MAX_EMPLOYEE_SAMPLES = 25
_LEAVE_FETCH_LIMIT = 20000
_PROTECTED_PAY_RUN_STATUSES = ("INPUTS_LOCKED", "COMPUTED", "APPROVED", "FINALISED", "PAID")


class CalendarPreviewInvalidError(ValidationError):
    code = "CALENDAR_PREVIEW_INVALID"

    def __init__(self, message: str, field_name: str = "change") -> None:
        super().__init__(
            message, details=[{"field": field_name, "code": self.code, "message": message}]
        )


class CalendarPreviewStaleError(ConflictError):
    code = "CALENDAR_PREVIEW_STALE"

    def __init__(self) -> None:
        message = (
            "The calendar configuration or its impact changed since this preview. "
            "Run a new preview and review it before confirming."
        )
        super().__init__(
            message, details=[{"field": "impact_digest", "code": self.code, "message": message}]
        )


class CalendarAcknowledgementRequiredError(ValidationError):
    code = "CALENDAR_IMPACT_ACKNOWLEDGEMENT_REQUIRED"

    def __init__(self) -> None:
        message = (
            "This change affects leave or protected attendance/payroll periods. "
            "Acknowledge the impact to confirm."
        )
        super().__init__(
            message,
            details=[
                {"field": "acknowledge_protected_impact", "code": self.code, "message": message}
            ],
        )


# ---------------------------------------------------------------------------
# Proposed changes: typed wrappers around the existing create/update models (no new policy
# schema). Each carries the optimistic-lock version the administrator edited from.
# ---------------------------------------------------------------------------


class _Change(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HolidayCreateChange(_Change):
    change_type: Literal["HOLIDAY_CREATE"]
    holiday_calendar_id: UUID
    body: HolidayCreate


class HolidayUpdateChange(_Change):
    change_type: Literal["HOLIDAY_UPDATE"]
    holiday_id: UUID
    expected_version: int
    patch: HolidayUpdate


class HolidayCalendarUpdateChange(_Change):
    """Only `valid_from` / `valid_to` change day classification (policy D); a rename or code edit
    previews as "no effect" but travels the same confirmed path."""

    change_type: Literal["HOLIDAY_CALENDAR_UPDATE"]
    holiday_calendar_id: UUID
    expected_version: int
    patch: HolidayCalendarUpdate


class ExceptionCreateChange(_Change):
    change_type: Literal["EXCEPTION_CREATE"]
    work_calendar_id: UUID
    body: CalendarExceptionCreate


class ExceptionUpdateChange(_Change):
    change_type: Literal["EXCEPTION_UPDATE"]
    exception_id: UUID
    expected_version: int
    patch: CalendarExceptionUpdate


class WeeklyOffPatternUpdateChange(_Change):
    change_type: Literal["WEEKLY_OFF_PATTERN_UPDATE"]
    pattern_id: UUID
    expected_version: int
    patch: WeeklyOffPatternUpdate


class WorkCalendarUpdateChange(_Change):
    change_type: Literal["WORK_CALENDAR_UPDATE"]
    work_calendar_id: UUID
    expected_version: int
    patch: WorkCalendarUpdate


class AssignmentCreateChange(_Change):
    change_type: Literal["ASSIGNMENT_CREATE"]
    body: PolicyAssignmentCreate
    # Version of the currently open assignment at the same scope, when there is one.
    expected_version: int | None = None


ProposedChange = Annotated[
    HolidayCreateChange
    | HolidayUpdateChange
    | HolidayCalendarUpdateChange
    | ExceptionCreateChange
    | ExceptionUpdateChange
    | WeeklyOffPatternUpdateChange
    | WorkCalendarUpdateChange
    | AssignmentCreateChange,
    Field(discriminator="change_type"),
]

HOLIDAY_CHANGE_TYPES = frozenset({"HOLIDAY_CREATE", "HOLIDAY_UPDATE", "HOLIDAY_CALENDAR_UPDATE"})


class ImpactPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change: ProposedChange
    window_from: date
    window_to: date


class ImpactConfirmRequest(ImpactPreviewRequest):
    # `impact_digest` from the preview the administrator reviewed.
    impact_digest: str = Field(min_length=64, max_length=64)
    acknowledge_protected_impact: bool = False


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DaySnapshot(BaseModel):
    configured: bool
    day_type: str | None = None
    label: str | None = None
    weekly_off_fraction: str | None = None


class ImpactRow(BaseModel):
    date: date
    previous: DaySnapshot
    proposed: DaySnapshot
    affected_employee_count: int


class ImpactWarning(BaseModel):
    code: str
    message: str


class EmployeeSample(BaseModel):
    employee_id: UUID
    employee_code: str
    name: str
    changed_date_count: int


class PopulationInfo(BaseModel):
    employees_in_scope: int
    employees_analysed: int
    groups_analysed: int
    # False when a cap was hit: counts are then a lower bound, not the full population.
    complete: bool


class LeaveImpactItem(BaseModel):
    application_id: UUID
    employee_id: UUID
    employee_code: str
    date: date
    status: Literal["APPROVED", "PENDING"]
    previous_day_type: str | None
    proposed_day_type: str | None


class LeaveImpact(BaseModel):
    approved_day_records: int
    pending_day_records: int
    applications: int
    employees: int
    items: list[LeaveImpactItem]
    items_truncated: bool
    # Leave day records are never rewritten by a calendar change.
    records_modified: Literal[0] = 0


class ProtectedPeriod(BaseModel):
    id: UUID
    kind: Literal["ATTENDANCE_PERIOD", "PAY_RUN"]
    legal_entity_id: UUID
    period_start: date
    period_end: date
    status: str
    changed_dates_in_period: int


class IncompleteConfiguration(BaseModel):
    employees: int
    dates: int


class ImpactPreview(BaseModel):
    change_type: str
    window_from: date
    window_to: date
    population: PopulationInfo
    changed_date_count: int
    affected_employee_count: int
    rows: list[ImpactRow]
    rows_truncated: bool
    employee_samples: list[EmployeeSample]
    excluded_not_employed_employee_dates: int
    incomplete_configuration: IncompleteConfiguration
    leave_impact: LeaveImpact
    protected_periods: list[ProtectedPeriod]
    warnings: list[ImpactWarning]
    requires_acknowledgement: bool
    impact_digest: str


class ImpactConfirmed(BaseModel):
    change_type: str
    entity_id: UUID | None
    impact_digest: str
    affected_employee_count: int
    changed_date_count: int
    confirmed_by: UUID | None
    confirmed_at: str


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_Sig = tuple[bool, str | None, str | None, str | None, str | None, str | None, bool, str | None]


def _signature(day: DayTypeRead | None) -> _Sig:
    """Everything that distinguishes two classifications for display and policy purposes."""
    if day is None:
        return (False, None, None, None, None, None, False, None)
    fraction = None if day.weekly_off_fraction is None else f"{day.weekly_off_fraction:.2f}"
    return (
        True,
        day.day_type,
        day.holiday_name,
        day.optional_holiday_name,
        day.restricted_holiday_name,
        fraction,
        day.holiday_on_weekly_off,
        day.exception_type,
    )


def _snapshot(sig: _Sig) -> DaySnapshot:
    configured, day_type, holiday, optional, restricted, fraction, _, _ = sig
    label = holiday or optional or restricted
    if optional:
        label = f"Optional: {optional}"
    elif restricted:
        label = f"Restricted: {restricted}"
    return DaySnapshot(
        configured=configured, day_type=day_type, label=label, weekly_off_fraction=fraction
    )


@dataclass
class _Span:
    start: date
    end: date | None
    legal_entity_id: UUID

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass
class _Member:
    employee_id: UUID
    employee_code: str
    spans: list[_Span]

    def employed_on(self, day: date) -> _Span | None:
        return next((s for s in self.spans if s.covers(day)), None)


@dataclass
class _Group:
    members: list[_Member] = field(default_factory=list)
    changes: dict[date, tuple[_Sig, _Sig]] = field(default_factory=dict)
    unresolved_dates: set[date] = field(default_factory=set)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class CalendarImpactService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._org = OrganisationService(session, get_settings())
        self._audit = AuditService()
        self._holiday_calendars = HolidayCalendarRepository()
        self._holidays = HolidayRepository()
        self._patterns = WeeklyOffPatternRepository()
        self._work_calendars = WorkCalendarRepository()
        self._exceptions = CalendarExceptionRepository()
        self._assignments = PolicyAssignmentRepository()

    # -- validation and overlay construction -------------------------------------------------

    @staticmethod
    def _validate_window(start: date, end: date) -> None:
        if end < start:
            raise CalendarPreviewInvalidError(
                "'window_to' must not be before 'window_from'", "window_to"
            )
        if (end - start).days + 1 > MAX_PREVIEW_WINDOW_DAYS:
            raise CalendarPreviewInvalidError(
                f"The preview window may not exceed {MAX_PREVIEW_WINDOW_DAYS} days", "window_to"
            )

    @staticmethod
    def _stale(entity: str, current_version: int, expected: int) -> None:
        if current_version != expected:
            raise StaleResourceError(
                f"This {entity} has been modified since it was loaded",
                current={"version": current_version},
            )

    async def _build_overlay(
        self, company_id: UUID, change: Any, warnings: list[ImpactWarning]
    ) -> tuple[CalendarOverlay, set[UUID]]:
        """Returns the overlay and the employees that must be resolved individually."""
        overlay = CalendarOverlay()
        individuals: set[UUID] = set()
        kind = change.change_type

        if kind == "HOLIDAY_CREATE":
            calendar = await self._holiday_calendars.get(
                self._session, company_id=company_id, calendar_id=change.holiday_calendar_id
            )
            if calendar is None:
                raise NotFoundError("Resource not found")
            existing = await self._holidays.list_for_calendars(
                self._session, company_id=company_id, calendar_ids=[calendar.id]
            )
            if any(h.date == change.body.date for h in existing):
                raise CalendarPreviewInvalidError(
                    "An active holiday already exists on this date in the calendar"
                )
            body = change.body
            # Same rule the confirmed path applies (policy C), so preview cannot accept what
            # confirmation would refuse.
            reconcile_holiday_is_working(
                holiday_type=body.holiday_type,
                is_working=body.is_working,
                explicit="is_working" in body.model_fields_set,
            )
            overlay.holidays_added[calendar.id] = [
                HolidayData(
                    date=body.date,
                    name=body.name,
                    holiday_type=body.holiday_type,
                    is_paid=body.is_paid,
                )
            ]
            self._holiday_warnings(calendar, body.date, warnings)

        elif kind == "HOLIDAY_UPDATE":
            row = await self._holidays.get(
                self._session, company_id=company_id, holiday_id=change.holiday_id
            )
            if row is None:
                raise NotFoundError("Resource not found")
            self._stale("holiday", row.version, change.expected_version)
            patch = change.patch
            new_name: str = patch.name if patch.name else row.name
            new_type: str = patch.holiday_type or row.holiday_type
            new_paid: bool = row.is_paid if patch.is_paid is None else patch.is_paid
            new_active: bool = row.is_active if patch.is_active is None else patch.is_active
            if "is_working" in patch.model_fields_set or "holiday_type" in patch.model_fields_set:
                reconcile_holiday_is_working(
                    holiday_type=new_type,
                    is_working=row.is_working if patch.is_working is None else patch.is_working,
                    explicit=patch.is_working is not None,
                )
            calendar = await self._holiday_calendars.get(
                self._session, company_id=company_id, calendar_id=row.calendar_id
            )
            replacement = HolidayData(
                date=row.date,
                name=new_name,
                holiday_type=new_type,
                is_paid=new_paid,
                holiday_id=row.id,
            )
            if row.is_active and new_active:
                overlay.holidays_changed[row.id] = replacement
            elif row.is_active:
                overlay.holidays_changed[row.id] = None
            elif new_active:
                existing = await self._holidays.list_for_calendars(
                    self._session, company_id=company_id, calendar_ids=[row.calendar_id]
                )
                if any(h.date == row.date for h in existing):
                    raise CalendarPreviewInvalidError(
                        "Another active holiday already exists on this date in the calendar"
                    )
                overlay.holidays_added[row.calendar_id] = [replacement]
            if calendar is not None:
                self._holiday_warnings(calendar, row.date, warnings)

        elif kind == "HOLIDAY_CALENDAR_UPDATE":
            hcal = await self._holiday_calendars.get(
                self._session, company_id=company_id, calendar_id=change.holiday_calendar_id
            )
            if hcal is None:
                raise NotFoundError("Resource not found")
            self._stale("holiday calendar", hcal.version, change.expected_version)
            patch = change.patch
            new_from = (
                patch.valid_from if "valid_from" in patch.model_fields_set else hcal.valid_from
            )
            new_to = patch.valid_to if "valid_to" in patch.model_fields_set else hcal.valid_to
            if new_from is not None and new_to is not None and new_from > new_to:
                raise CalendarPreviewInvalidError(
                    "valid_from must not be after valid_to", "valid_from"
                )
            overlay.validity[hcal.id] = (new_from, new_to)
            if (new_from, new_to) == (hcal.valid_from, hcal.valid_to):
                warnings.append(
                    ImpactWarning(
                        code="NO_RESOLUTION_EFFECT",
                        message="Only the calendar's validity dates affect day classification; "
                        "this edit changes none.",
                    )
                )

        elif kind == "EXCEPTION_CREATE":
            calendar_row = await self._work_calendars.get(
                self._session, company_id=company_id, work_calendar_id=change.work_calendar_id
            )
            if calendar_row is None:
                raise NotFoundError("Resource not found")
            existing_exc = await self._exceptions.list_active_for_calendars(
                self._session, company_id=company_id, work_calendar_ids=[calendar_row.id]
            )
            body = change.body
            if any(e.exception_date == body.exception_date for e in existing_exc):
                raise CalendarPreviewInvalidError(
                    "An active exception already exists on this date for the work calendar"
                )
            overlay.exceptions_added[calendar_row.id] = [
                ExceptionRow(None, body.exception_date, body.exception_type, body.name)
            ]

        elif kind == "EXCEPTION_UPDATE":
            exc = await self._exceptions.get(
                self._session, company_id=company_id, exception_id=change.exception_id
            )
            if exc is None:
                raise NotFoundError("Resource not found")
            self._stale("exception", exc.version, change.expected_version)
            patch = change.patch
            exc_active = exc.is_active if patch.is_active is None else patch.is_active
            exc_name = patch.name if "name" in patch.model_fields_set else exc.name
            replacement_row = ExceptionRow(exc.id, exc.exception_date, exc.exception_type, exc_name)
            if exc.is_active and exc_active:
                overlay.exceptions_changed[exc.id] = replacement_row
            elif exc.is_active:
                overlay.exceptions_changed[exc.id] = None
            elif exc_active:
                active = await self._exceptions.list_active_for_calendars(
                    self._session, company_id=company_id, work_calendar_ids=[exc.work_calendar_id]
                )
                if any(e.exception_date == exc.exception_date for e in active):
                    raise CalendarPreviewInvalidError(
                        "Another active exception already exists on this date"
                    )
                overlay.exceptions_added[exc.work_calendar_id] = [replacement_row]

        elif kind == "WEEKLY_OFF_PATTERN_UPDATE":
            pattern = await self._patterns.get(
                self._session, company_id=company_id, pattern_id=change.pattern_id
            )
            if pattern is None:
                raise NotFoundError("Resource not found")
            self._stale("weekly-off pattern", pattern.version, change.expected_version)
            patch = change.patch
            if patch.rules is not None:
                effective_kind = patch.pattern_kind or pattern.pattern_kind
                self._org._validate_weekly_off_rules(effective_kind, patch.rules)
                overlay.rules[pattern.id] = [
                    WeeklyOffRuleData(
                        weekday=r.weekday,
                        nth_in_month=r.nth_in_month,
                        cycle_start_date=r.cycle_start_date,
                        off_fraction=r.off_fraction,
                        week_parity=r.week_parity,
                    )
                    for r in patch.rules
                ]
            else:
                warnings.append(
                    ImpactWarning(
                        code="NO_RESOLUTION_EFFECT",
                        message="Only the pattern's rules affect day classification; this edit "
                        "changes none.",
                    )
                )

        elif kind == "WORK_CALENDAR_UPDATE":
            wc = await self._work_calendars.get(
                self._session, company_id=company_id, work_calendar_id=change.work_calendar_id
            )
            if wc is None:
                raise NotFoundError("Resource not found")
            self._stale("work calendar", wc.version, change.expected_version)
            patch = change.patch
            pattern_id = (
                patch.weekly_off_pattern_id
                if "weekly_off_pattern_id" in patch.model_fields_set
                else wc.weekly_off_pattern_id
            )
            if pattern_id is not None:
                if (
                    await self._patterns.get(
                        self._session, company_id=company_id, pattern_id=pattern_id
                    )
                    is None
                ):
                    raise CalendarPreviewInvalidError(
                        "The weekly-off pattern does not exist", "weekly_off_pattern_id"
                    )
            restricted = (
                wc.restricted_holidays_are_off_by_default
                if patch.restricted_holidays_are_off_by_default is None
                else patch.restricted_holidays_are_off_by_default
            )
            overlay.calendar_settings[wc.id] = (pattern_id, restricted)
            if patch.holiday_calendar_ids is not None:
                for calendar_id in patch.holiday_calendar_ids:
                    cal = await self._holiday_calendars.get(
                        self._session, company_id=company_id, calendar_id=calendar_id
                    )
                    if cal is None:
                        raise CalendarPreviewInvalidError(
                            "A linked holiday calendar does not exist", "holiday_calendar_ids"
                        )
                overlay.links[wc.id] = list(patch.holiday_calendar_ids)

        elif kind == "ASSIGNMENT_CREATE":
            body = change.body
            if body.policy_kind not in ("WORK_CALENDAR", "WEEKLY_OFF"):
                raise CalendarPreviewInvalidError(
                    "Only WORK_CALENDAR and WEEKLY_OFF assignments change day classification",
                    "policy_kind",
                )
            await self._org._validate_policy_reference(
                company_id, body.policy_kind, body.policy_id, body.leave_type_id
            )
            await self._org._validate_policy_scope(company_id, body.scope_type, body.scope_id)
            current = await self._assignments.get_current(
                self._session,
                company_id=company_id,
                policy_kind=body.policy_kind,
                scope_type=body.scope_type,
                scope_id=body.scope_id,
                leave_type_id=body.leave_type_id,
            )
            if current is not None:
                if body.effective_from <= current.effective_from:
                    raise CalendarPreviewInvalidError(
                        "effective_from must be after the current assignment's effective_from",
                        "effective_from",
                    )
                if change.expected_version is None:
                    raise CalendarPreviewInvalidError(
                        "expected_version of the current assignment is required", "expected_version"
                    )
                self._stale("assignment", current.version, change.expected_version)
            overlay.assignment = ProposedAssignment(
                policy_kind=body.policy_kind,
                policy_id=body.policy_id,
                scope_type=body.scope_type,
                scope_id=body.scope_id,
                effective_from=body.effective_from,
                effective_to=body.effective_to,
            )
            if body.scope_type == "EMPLOYEE" and body.scope_id is not None:
                individuals.add(body.scope_id)
        return overlay, individuals

    @staticmethod
    def _holiday_warnings(calendar: Any, holiday_date: date, warnings: list[ImpactWarning]) -> None:
        """Policy D: a holiday dated outside its calendar's validity window is stored but never
        applies, so the preview reports no change for it - say why."""
        outside = (calendar.valid_from is not None and holiday_date < calendar.valid_from) or (
            calendar.valid_to is not None and holiday_date > calendar.valid_to
        )
        if outside and not any(w.code == "HOLIDAY_OUTSIDE_CALENDAR_VALIDITY" for w in warnings):
            warnings.append(
                ImpactWarning(
                    code="HOLIDAY_OUTSIDE_CALENDAR_VALIDITY",
                    message="This holiday is dated outside its holiday calendar's valid-from/"
                    "valid-to window, so it does not apply to any employee until the window is "
                    "changed.",
                )
            )

    # -- population --------------------------------------------------------------------------

    async def _load_population(
        self, company_id: UUID, start: date, end: date
    ) -> tuple[dict[UUID, _Member], bool]:
        from hrms.modules.employee.models import Employee, Employment

        stmt = (
            select(
                Employment.employee_id,
                Employment.joining_date,
                Employment.last_working_day,
                Employment.legal_entity_id,
                Employee.employee_code,
            )
            .join(
                Employee,
                (Employee.id == Employment.employee_id) & (Employee.company_id == company_id),
            )
            .where(
                Employment.company_id == company_id,
                Employment.deleted_at.is_(None),
                Employment.joining_date <= end,
                (Employment.last_working_day.is_(None)) | (Employment.last_working_day >= start),
            )
            .order_by(Employment.employee_id, Employment.joining_date)
            .limit(MAX_PREVIEW_EMPLOYEES * 3)
        )
        rows = (await self._session.execute(stmt)).all()
        members: dict[UUID, _Member] = {}
        truncated = len(rows) >= MAX_PREVIEW_EMPLOYEES * 3
        for employee_id, joining, last_day, legal_entity_id, code in rows:
            if employee_id not in members:
                if len(members) >= MAX_PREVIEW_EMPLOYEES:
                    truncated = True
                    break
                members[employee_id] = _Member(employee_id, code, [])
            members[employee_id].spans.append(_Span(joining, last_day, legal_entity_id))
        return members, truncated

    async def _load_placements(
        self, company_id: UUID, employee_ids: list[UUID], start: date, end: date
    ) -> dict[UUID, list[Any]]:
        from hrms.modules.employee.models import EmployeeAssignment

        out: dict[UUID, list[Any]] = defaultdict(list)
        for i in range(0, len(employee_ids), 1000):
            chunk = employee_ids[i : i + 1000]
            stmt = (
                select(EmployeeAssignment)
                .where(
                    EmployeeAssignment.company_id == company_id,
                    EmployeeAssignment.employee_id.in_(chunk),
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.effective_from <= end,
                    (EmployeeAssignment.effective_to.is_(None))
                    | (EmployeeAssignment.effective_to >= start),
                )
                .order_by(EmployeeAssignment.employee_id, EmployeeAssignment.effective_from)
            )
            for row in (await self._session.execute(stmt)).scalars():
                out[row.employee_id].append(row)
        return out

    async def _employee_scope_assignments(
        self, company_id: UUID, start: date, end: date
    ) -> list[PolicyAssignment]:
        stmt = select(PolicyAssignment).where(
            PolicyAssignment.company_id == company_id,
            PolicyAssignment.policy_kind.in_(("WORK_CALENDAR", "WEEKLY_OFF")),
            PolicyAssignment.scope_type == "EMPLOYEE",
            PolicyAssignment.deleted_at.is_(None),
            PolicyAssignment.is_active.is_(True),
            PolicyAssignment.effective_from <= end,
            (PolicyAssignment.effective_to.is_(None)) | (PolicyAssignment.effective_to >= start),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # -- the computation ---------------------------------------------------------------------

    async def _compute(
        self, company_id: UUID, request: ImpactPreviewRequest
    ) -> tuple[ImpactPreview, dict[str, Any]]:
        start, end = request.window_from, request.window_to
        self._validate_window(start, end)
        warnings: list[ImpactWarning] = []
        change = request.change
        overlay, forced_individuals = await self._build_overlay(company_id, change, warnings)

        members, population_truncated = await self._load_population(company_id, start, end)
        employee_ids = list(members)
        placements = await self._load_placements(company_id, employee_ids, start, end)
        employee_scope = await self._employee_scope_assignments(company_id, start, end)
        individuals = set(forced_individuals) | {
            a.scope_id for a in employee_scope if a.scope_id is not None
        }

        # Dates on which an assignment (any scope) can change what applies.
        global_points: set[date] = set()

        def add_point(target: set[date], day: date | None) -> None:
            if day is not None and start < day <= end:
                target.add(day)

        for assignment in await self._assignments.list_overlapping(
            self._session,
            company_id=company_id,
            policy_kinds=["WORK_CALENDAR", "WEEKLY_OFF"],
            employee_id=UUID(int=0),
            range_start=start,
            range_end=end,
        ):
            add_point(global_points, assignment.effective_from)
            if assignment.effective_to is not None:
                add_point(global_points, assignment.effective_to + timedelta(days=1))
        if overlay.assignment is not None:
            add_point(global_points, overlay.assignment.effective_from)
            if overlay.assignment.effective_to is not None:
                add_point(global_points, overlay.assignment.effective_to + timedelta(days=1))
        employee_points: dict[UUID, set[date]] = defaultdict(set)
        for assignment in employee_scope:
            if assignment.scope_id is None:
                continue
            add_point(employee_points[assignment.scope_id], assignment.effective_from)
            if assignment.effective_to is not None:
                add_point(
                    employee_points[assignment.scope_id],
                    assignment.effective_to + timedelta(days=1),
                )

        # Group employees with an identical placement history.
        groups: dict[object, _Group] = {}
        group_points: dict[object, set[date]] = {}
        for employee_id, member in members.items():
            rows = placements.get(employee_id, [])
            key: object
            if employee_id in individuals:
                key = ("individual", employee_id)
            else:
                key = tuple(
                    (
                        max(r.effective_from, start),
                        min(r.effective_to or end, end),
                        r.shift_id,
                        r.designation_id,
                        r.grade_id,
                        r.department_id,
                        r.branch_id,
                    )
                    for r in rows
                )
            group = groups.setdefault(key, _Group())
            group.members.append(member)
            if key not in group_points:
                points: set[date] = set(employee_points.get(employee_id, ()))
                for r in rows:
                    add_point(points, r.effective_from)
                    if r.effective_to is not None:
                        add_point(points, r.effective_to + timedelta(days=1))
                group_points[key] = points

        ordered_keys = list(groups)
        groups_skipped = max(0, len(ordered_keys) - MAX_PREVIEW_GROUPS)
        analysed_keys = ordered_keys[:MAX_PREVIEW_GROUPS]

        memo: dict[object, object] = {}
        current_resolver = CalendarResolutionService(self._session, memo=memo)
        proposed_resolver = CalendarResolutionService(self._session, overlay=overlay, memo={})
        range_cache: dict[tuple[str, UUID, UUID | None, date, date], list[DayTypeRead]] = {}

        async def classify(
            tag: str,
            resolver: CalendarResolutionService,
            representative: UUID,
            seg_start: date,
            seg_end: date,
        ) -> list[_Sig]:
            choice = await resolver.resolve_calendar_choice(company_id, representative, seg_start)
            length = (seg_end - seg_start).days + 1
            if choice is None:
                return [_signature(None)] * length
            sigs: list[_Sig] = []
            chunk_start = seg_start
            while chunk_start <= seg_end:
                # The shared range classifier is bounded (100 days); long windows are chunked.
                chunk_end = min(seg_end, chunk_start + timedelta(days=MAX_CALENDAR_RANGE_DAYS - 1))
                cache_key = (
                    tag,
                    choice.work_calendar.id,
                    choice.weekly_off_pattern_id,
                    chunk_start,
                    chunk_end,
                )
                if cache_key not in range_cache:
                    range_cache[cache_key] = await resolver.classify_range_for_work_calendar(
                        company_id,
                        choice.work_calendar.id,
                        chunk_start,
                        chunk_end,
                        weekly_off_pattern_id_override=choice.weekly_off_pattern_id,
                        _weekly_off_override_present=True,
                    )
                sigs.extend(_signature(d) for d in range_cache[cache_key])
                chunk_start = chunk_end + timedelta(days=1)
            return sigs

        for key in analysed_keys:
            group = groups[key]
            representative = group.members[0].employee_id
            starts = sorted({start} | global_points | group_points[key])
            for index, seg_start in enumerate(starts):
                seg_end = starts[index + 1] - timedelta(days=1) if index + 1 < len(starts) else end
                before = await classify("cur", current_resolver, representative, seg_start, seg_end)
                after = await classify("new", proposed_resolver, representative, seg_start, seg_end)
                for offset, (b, a) in enumerate(zip(before, after, strict=True)):
                    day = seg_start + timedelta(days=offset)
                    if not b[0] or not a[0]:
                        group.unresolved_dates.add(day)
                    if b != a:
                        group.changes[day] = (b, a)

        # Aggregate over the employment-eligible (employee, date) pairs.
        row_counts: dict[tuple[date, _Sig, _Sig], int] = defaultdict(int)
        per_employee: dict[UUID, int] = defaultdict(int)
        excluded = 0
        incomplete_employees: set[UUID] = set()
        incomplete_dates: set[date] = set()
        changed_dates: set[date] = set()
        dates_by_entity: dict[UUID, set[date]] = defaultdict(set)
        group_of: dict[UUID, _Group] = {}
        for key in analysed_keys:
            group = groups[key]
            for member in group.members:
                group_of[member.employee_id] = group
                for day, (b, a) in group.changes.items():
                    span = member.employed_on(day)
                    if span is None:
                        excluded += 1
                        continue
                    row_counts[(day, b, a)] += 1
                    per_employee[member.employee_id] += 1
                    changed_dates.add(day)
                    dates_by_entity[span.legal_entity_id].add(day)
                for day in group.unresolved_dates:
                    if member.employed_on(day) is not None:
                        incomplete_employees.add(member.employee_id)
                        incomplete_dates.add(day)

        all_rows = sorted(
            row_counts.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), str(kv[0][2]))
        )
        rows = [
            ImpactRow(
                date=day,
                previous=_snapshot(b),
                proposed=_snapshot(a),
                affected_employee_count=count,
            )
            for (day, b, a), count in all_rows
        ]

        samples = await self._samples(company_id, per_employee, members)
        leave = await self._leave_impact(company_id, per_employee, group_of, members, start, end)
        protected = await self._protected(company_id, dates_by_entity)

        self._policy_warnings(
            warnings,
            all_rows,
            population_truncated,
            groups_skipped,
            len(incomplete_employees),
            leave,
            protected,
            has_overlay_effect=bool(rows),
        )

        requires_ack = (
            leave.approved_day_records + leave.pending_day_records > 0 or len(protected) > 0
        )
        analysed_members = sum(len(groups[k].members) for k in analysed_keys)
        digest_source = {
            "change": change.model_dump(mode="json"),
            "window": [start.isoformat(), end.isoformat()],
            "rows": [
                [
                    r.date.isoformat(),
                    r.previous.model_dump(),
                    r.proposed.model_dump(),
                    r.affected_employee_count,
                ]
                for r in rows
            ],
            "affected": len(per_employee),
            "leave": [leave.approved_day_records, leave.pending_day_records, leave.applications],
            "protected": sorted(
                [str(p.id), p.status, p.changed_dates_in_period] for p in protected
            ),
            "population": [len(members), analysed_members, population_truncated, groups_skipped],
        }
        digest = hashlib.sha256(_canonical(digest_source).encode()).hexdigest()

        preview = ImpactPreview(
            change_type=change.change_type,
            window_from=start,
            window_to=end,
            population=PopulationInfo(
                employees_in_scope=len(members),
                employees_analysed=analysed_members,
                groups_analysed=len(analysed_keys),
                complete=not population_truncated and groups_skipped == 0,
            ),
            changed_date_count=len(changed_dates),
            affected_employee_count=len(per_employee),
            rows=rows[:MAX_ROWS_RETURNED],
            rows_truncated=len(rows) > MAX_ROWS_RETURNED,
            employee_samples=samples,
            excluded_not_employed_employee_dates=excluded,
            incomplete_configuration=IncompleteConfiguration(
                employees=len(incomplete_employees), dates=len(incomplete_dates)
            ),
            leave_impact=leave,
            protected_periods=protected,
            warnings=warnings,
            requires_acknowledgement=requires_ack,
            impact_digest=digest,
        )
        return preview, {"per_employee": per_employee}

    async def _samples(
        self, company_id: UUID, per_employee: dict[UUID, int], members: dict[UUID, _Member]
    ) -> list[EmployeeSample]:
        from hrms.modules.employee.models import Employee

        top = sorted(per_employee.items(), key=lambda kv: (-kv[1], str(kv[0])))[
            :MAX_EMPLOYEE_SAMPLES
        ]
        if not top:
            return []
        rows = (
            await self._session.execute(
                select(
                    Employee.id, Employee.display_name, Employee.first_name, Employee.last_name
                ).where(Employee.company_id == company_id, Employee.id.in_([e for e, _ in top]))
            )
        ).all()
        names = {r[0]: (r[1] or " ".join(p for p in (r[2], r[3]) if p)).strip() for r in rows}
        return [
            EmployeeSample(
                employee_id=e,
                employee_code=members[e].employee_code,
                name=names.get(e, ""),
                changed_date_count=n,
            )
            for e, n in top
        ]

    async def _leave_impact(
        self,
        company_id: UUID,
        per_employee: dict[UUID, int],
        group_of: dict[UUID, _Group],
        members: dict[UUID, _Member],
        start: date,
        end: date,
    ) -> LeaveImpact:
        from hrms.modules.leave.models import LeaveApplication, LeaveApplicationDay

        empty = LeaveImpact(
            approved_day_records=0,
            pending_day_records=0,
            applications=0,
            employees=0,
            items=[],
            items_truncated=False,
        )
        if not per_employee:
            return empty
        approved = pending = 0
        applications: set[UUID] = set()
        leave_employees: set[UUID] = set()
        items: list[LeaveImpactItem] = []
        ids = list(per_employee)
        for i in range(0, len(ids), 1000):
            chunk = ids[i : i + 1000]
            stmt = (
                select(
                    LeaveApplication.id,
                    LeaveApplication.employee_id,
                    LeaveApplication.status,
                    LeaveApplicationDay.calendar_date,
                )
                .join(
                    LeaveApplicationDay,
                    (LeaveApplicationDay.leave_application_id == LeaveApplication.id)
                    & (LeaveApplicationDay.company_id == LeaveApplication.company_id),
                )
                .where(
                    LeaveApplication.company_id == company_id,
                    LeaveApplication.employee_id.in_(chunk),
                    LeaveApplication.status.in_(("SUBMITTED", "APPROVED")),
                    LeaveApplicationDay.calendar_date >= start,
                    LeaveApplicationDay.calendar_date <= end,
                )
                .limit(_LEAVE_FETCH_LIMIT)
            )
            for app_id, employee_id, status, day in (await self._session.execute(stmt)).all():
                group = group_of.get(employee_id)
                if group is None or day not in group.changes:
                    continue
                if members[employee_id].employed_on(day) is None:
                    continue
                previous, proposed = group.changes[day]
                if status == "APPROVED":
                    approved += 1
                else:
                    pending += 1
                applications.add(app_id)
                leave_employees.add(employee_id)
                if len(items) < MAX_LEAVE_ITEMS:
                    items.append(
                        LeaveImpactItem(
                            application_id=app_id,
                            employee_id=employee_id,
                            employee_code=members[employee_id].employee_code,
                            date=day,
                            status="APPROVED" if status == "APPROVED" else "PENDING",
                            previous_day_type=previous[1],
                            proposed_day_type=proposed[1],
                        )
                    )
        items.sort(key=lambda item: (item.date, str(item.application_id)))
        return LeaveImpact(
            approved_day_records=approved,
            pending_day_records=pending,
            applications=len(applications),
            employees=len(leave_employees),
            items=items,
            items_truncated=(approved + pending) > len(items),
        )

    async def _protected(
        self, company_id: UUID, dates_by_entity: dict[UUID, set[date]]
    ) -> list[ProtectedPeriod]:
        from hrms.modules.attendance.models import AttendancePeriod
        from hrms.modules.payroll.models import PayRun

        if not dates_by_entity:
            return []
        entities = list(dates_by_entity)
        lo = min(min(d) for d in dates_by_entity.values())
        hi = max(max(d) for d in dates_by_entity.values())
        out: list[ProtectedPeriod] = []

        def count(entity: UUID, p_start: date, p_end: date) -> int:
            return sum(1 for d in dates_by_entity[entity] if p_start <= d <= p_end)

        periods = await self._session.execute(
            select(AttendancePeriod).where(
                AttendancePeriod.company_id == company_id,
                AttendancePeriod.legal_entity_id.in_(entities),
                AttendancePeriod.status != "OPEN",
                AttendancePeriod.period_start <= hi,
                AttendancePeriod.period_end >= lo,
            )
        )
        for period in periods.scalars():
            n = count(period.legal_entity_id, period.period_start, period.period_end)
            if n:
                out.append(
                    ProtectedPeriod(
                        id=period.id,
                        kind="ATTENDANCE_PERIOD",
                        legal_entity_id=period.legal_entity_id,
                        period_start=period.period_start,
                        period_end=period.period_end,
                        status=period.status,
                        changed_dates_in_period=n,
                    )
                )
        runs = await self._session.execute(
            select(PayRun).where(
                PayRun.company_id == company_id,
                PayRun.legal_entity_id.in_(entities),
                PayRun.status.in_(_PROTECTED_PAY_RUN_STATUSES),
                PayRun.period_start <= hi,
                PayRun.period_end >= lo,
            )
        )
        for run in runs.scalars():
            n = count(run.legal_entity_id, run.period_start, run.period_end)
            if n:
                out.append(
                    ProtectedPeriod(
                        id=run.id,
                        kind="PAY_RUN",
                        legal_entity_id=run.legal_entity_id,
                        period_start=run.period_start,
                        period_end=run.period_end,
                        status=run.status,
                        changed_dates_in_period=n,
                    )
                )
        out.sort(key=lambda p: (p.period_start, p.kind, str(p.id)))
        return out

    @staticmethod
    def _policy_warnings(
        warnings: list[ImpactWarning],
        all_rows: list[tuple[tuple[date, _Sig, _Sig], int]],
        population_truncated: bool,
        groups_skipped: int,
        incomplete_employees: int,
        leave: LeaveImpact,
        protected: list[ProtectedPeriod],
        *,
        has_overlay_effect: bool,
    ) -> None:
        if not has_overlay_effect and not any(w.code == "NO_RESOLUTION_EFFECT" for w in warnings):
            warnings.append(
                ImpactWarning(
                    code="NO_EFFECTIVE_CHANGE",
                    message="No employee's day classification changes in this window.",
                )
            )
        if population_truncated or groups_skipped:
            warnings.append(
                ImpactWarning(
                    code="POPULATION_INCOMPLETE",
                    message="The employee population exceeded the preview limit. Counts are a "
                    "lower bound, not the full population.",
                )
            )
        if incomplete_employees:
            warnings.append(
                ImpactWarning(
                    code="INCOMPLETE_CONFIGURATION",
                    message=f"{incomplete_employees} employee(s) have dates with no resolvable "
                    "work calendar, so their impact cannot be fully calculated.",
                )
            )
        sigs = [s for (_, b, a), _ in all_rows for s in (b, a)]
        if any(s[5] is not None and s[5] != "1.00" for s in sigs):
            warnings.append(
                ImpactWarning(
                    code="HALF_DAY_WEEKLY_OFF",
                    message="A half-day weekly off is involved: half of the day is a paid day off "
                    "and half is a working day. Leave can consume only the working half, and "
                    "attendance expects the working half to be worked or covered.",
                )
            )
        if any(s[6] for s in sigs):
            warnings.append(
                ImpactWarning(
                    code="HOLIDAY_ON_WEEKLY_OFF",
                    message="A holiday falls on a weekly off. It stays a weekly off and no "
                    "substitute holiday is created (PD-CAL-2).",
                )
            )
        if any(s[3] or s[4] for s in sigs):
            warnings.append(
                ImpactWarning(
                    code="OPTIONAL_RESTRICTED_WORKING",
                    message="An optional or restricted holiday remains a working day unless the "
                    "work calendar treats restricted holidays as off (PD-CAL-1).",
                )
            )
        if leave.approved_day_records or leave.pending_day_records:
            warnings.append(
                ImpactWarning(
                    code="LEAVE_NOT_RECALCULATED",
                    message="Existing leave day records are not changed. Review the listed "
                    "leave; any adjustment is a separate leave action.",
                )
            )
        if protected:
            warnings.append(
                ImpactWarning(
                    code="PROTECTED_PERIODS",
                    message="Locked attendance periods and payroll runs are listed. They are not "
                    "recalculated; only future calculations use the new configuration.",
                )
            )

    # -- public API --------------------------------------------------------------------------

    async def preview(self, company_id: UUID, request: ImpactPreviewRequest) -> ImpactPreview:
        preview, _ = await self._compute(company_id, request)
        return preview

    async def _lock(self, company_id: UUID) -> None:
        key = f"work-calendar-change:{company_id}"
        async with bounded_lock_wait(
            self._session, lock_timeout_ms=get_settings().attendance_lock_timeout_ms
        ):
            await self._session.execute(
                select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
            )

    async def confirm(
        self,
        company_id: UUID,
        request: ImpactConfirmRequest,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ImpactConfirmed:
        # Same lock the guided setup uses for its own writes would be wrong to share (different
        # operation); this one serialises calendar-change confirmations per company.
        await self._lock(company_id)
        preview, _ = await self._compute(company_id, request)
        if preview.impact_digest != request.impact_digest:
            raise CalendarPreviewStaleError()
        if preview.requires_acknowledgement and not request.acknowledge_protected_impact:
            raise CalendarAcknowledgementRequiredError()

        entity_id = await self._apply(
            company_id, request.change, actor_user_id, ip_address, user_agent
        )
        confirmed_at = datetime.now(UTC)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="WORK_CALENDAR_CHANGE_CONFIRMED",
            entity_type="work_calendar_change",
            entity_id=entity_id,
            after={
                "change": request.change.model_dump(mode="json"),
                "window": [request.window_from.isoformat(), request.window_to.isoformat()],
                "impact_digest": preview.impact_digest,
                "affected_employee_count": preview.affected_employee_count,
                "changed_date_count": preview.changed_date_count,
                "leave_day_records_affected": preview.leave_impact.approved_day_records
                + preview.leave_impact.pending_day_records,
                "protected_periods": len(preview.protected_periods),
                "acknowledged_protected_impact": request.acknowledge_protected_impact,
                "population_complete": preview.population.complete,
            },
            ip=ip_address,
            user_agent=user_agent,
        )
        return ImpactConfirmed(
            change_type=request.change.change_type,
            entity_id=entity_id,
            impact_digest=preview.impact_digest,
            affected_employee_count=preview.affected_employee_count,
            changed_date_count=preview.changed_date_count,
            confirmed_by=actor_user_id,
            confirmed_at=confirmed_at.isoformat().replace("+00:00", "Z"),
        )

    async def _apply(
        self,
        company_id: UUID,
        change: Any,
        actor_user_id: UUID | None,
        ip: str | None,
        user_agent: str | None,
    ) -> UUID | None:
        """Calls the existing service method for the change, unchanged - validation, optimistic
        locking and per-entity audit stay exactly as the ordinary admin flows."""
        kind = change.change_type
        if kind == "HOLIDAY_CREATE":
            created = await self._org.create_holiday(
                company_id,
                change.holiday_calendar_id,
                change.body,
                actor_user_id=actor_user_id,
                ip_address=ip,
                user_agent=user_agent,
            )
            return created.id
        if kind == "HOLIDAY_UPDATE":
            updated = await self._org.update_holiday(
                company_id,
                change.holiday_id,
                change.patch,
                expected_version=change.expected_version,
                actor_user_id=actor_user_id,
                ip_address=ip,
                user_agent=user_agent,
            )
            return updated.id
        if kind == "HOLIDAY_CALENDAR_UPDATE":
            hcal_updated = await self._org.update_holiday_calendar(
                company_id,
                change.holiday_calendar_id,
                change.patch,
                expected_version=change.expected_version,
                actor_user_id=actor_user_id,
                ip_address=ip,
                user_agent=user_agent,
            )
            return hcal_updated.id
        if kind == "EXCEPTION_CREATE":
            exc = await self._org.create_calendar_exception(
                company_id,
                change.work_calendar_id,
                change.body,
                actor_user_id=actor_user_id,
                ip_address=ip,
                user_agent=user_agent,
            )
            return exc.id
        if kind == "EXCEPTION_UPDATE":
            exc_updated = await self._org.update_calendar_exception(
                company_id,
                change.exception_id,
                change.patch,
                expected_version=change.expected_version,
                actor_user_id=actor_user_id,
                ip_address=ip,
                user_agent=user_agent,
            )
            return exc_updated.id
        if kind == "WEEKLY_OFF_PATTERN_UPDATE":
            pattern = await self._org.update_weekly_off_pattern(
                company_id,
                change.pattern_id,
                change.patch,
                expected_version=change.expected_version,
                actor_user_id=actor_user_id,
                ip_address=ip,
                user_agent=user_agent,
            )
            return pattern.id
        if kind == "WORK_CALENDAR_UPDATE":
            calendar = await self._org.update_work_calendar(
                company_id,
                change.work_calendar_id,
                change.patch,
                expected_version=change.expected_version,
                actor_user_id=actor_user_id,
                ip_address=ip,
                user_agent=user_agent,
            )
            return calendar.id
        assignment = await self._org.create_policy_assignment(
            company_id,
            change.body,
            expected_version=change.expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip,
            user_agent=user_agent,
        )
        return assignment.id


def get_calendar_impact_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> CalendarImpactService:
    return CalendarImpactService(session)
