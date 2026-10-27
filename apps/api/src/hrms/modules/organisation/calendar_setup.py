"""Work-calendar guided setup: suggested defaults, read-only preview, explicit confirmation.

Product rules (approved decisions A and B):

* The suggested working week is *only a suggestion*. Nothing here reads
  `company.working_days_pattern`, and nothing is written until an administrator calls `confirm`.
* Before confirmation the company has no company-level `WORK_CALENDAR` assignment, so
  `CalendarResolutionService` keeps failing closed (`config_incomplete`). That behaviour is
  deliberately untouched.
* No public holidays are created. The administrator links holiday calendars they own.
* `preview` performs reads only and evaluates the proposed composition in memory with the same
  `classify_work_calendar_date` classifier.
* `confirm` builds a new weekly-off pattern, a new work calendar and one effective-dated
  `WORK_CALENDAR` assignment through the existing `OrganisationService` methods, inside the
  request's single transaction, behind a per-company advisory lock, and records one extra audit
  event naming the administrator who confirmed.

New rows are always created (never silently shared with another work calendar) so that a later
edit to one calendar cannot change another's meaning. A repeated confirm is rejected because an
open assignment already exists at the scope.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.core.db.timeouts import bounded_lock_wait
from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError
from hrms.modules.organisation.calendar_resolution import (
    CalendarResolutionService,
    WeeklyOffRuleData,
    classify_date_range,
    validate_calendar_range,
)
from hrms.modules.organisation.models import PolicyAssignment
from hrms.modules.organisation.repository import (
    HolidayCalendarRepository,
    PolicyAssignmentRepository,
)
from hrms.modules.organisation.schemas import (
    DayTypeRead,
    PolicyAssignmentCreate,
    WeeklyOffPatternCreate,
    WeeklyOffRuleInput,
    WorkCalendarCreate,
)
from hrms.modules.organisation.service import OrganisationService

# Monday=0 .. Sunday=6 - the resolver's convention (`date.weekday()`).
_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SUGGESTED_WEEKLY_OFF_WEEKDAYS = (5, 6)
_PREVIEW_DEFAULT_DAYS = 42


class WorkCalendarAlreadyConfiguredError(ConflictError):
    code = "WORK_CALENDAR_ALREADY_CONFIGURED"

    def __init__(self, message: str = "A work calendar is already active at this scope") -> None:
        super().__init__(
            message,
            details=[{"field": "scope", "code": self.code, "message": message}],
        )


class WorkCalendarSetupInvalidError(ValidationError):
    code = "WORK_CALENDAR_SETUP_INVALID"

    def __init__(self, message: str, field: str = "configuration") -> None:
        super().__init__(message, details=[{"field": field, "code": self.code, "message": message}])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class WorkCalendarSetupConfig(BaseModel):
    """A proposed configuration. `weekly_off_weekdays` use Monday=0 .. Sunday=6; every other
    weekday is a working day. Half-day weekly offs are intentionally not offered here - leave and
    attendance interpret them differently today (a separate policy decision)."""

    model_config = ConfigDict(extra="forbid")

    weekly_off_weekdays: list[int] = Field(default_factory=list, max_length=6)
    holiday_calendar_ids: list[UUID] = Field(default_factory=list, max_length=20)
    # None = company-wide default; otherwise the setup applies to that branch only.
    branch_id: UUID | None = None
    effective_from: date

    @field_validator("weekly_off_weekdays")
    @classmethod
    def _validate_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekly_off_weekdays must be between 0 (Monday) and 6 (Sunday)")
        if len(set(value)) != len(value):
            raise ValueError("weekly_off_weekdays must not repeat a weekday")
        return sorted(value)

    @field_validator("holiday_calendar_ids")
    @classmethod
    def _validate_calendars(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("holiday_calendar_ids must not repeat a calendar")
        return value


class WorkCalendarSetupPreviewRequest(WorkCalendarSetupConfig):
    preview_from: date | None = None
    preview_to: date | None = None


class WorkCalendarSetupConfirmRequest(WorkCalendarSetupConfig):
    name: str = Field(min_length=1, max_length=150)
    # The administrator must explicitly acknowledge activation; a bare config cannot confirm.
    confirm: Literal[True]


class SetupSuggestion(BaseModel):
    confirmed: Literal[False] = False
    working_weekdays: list[int]
    weekly_off_weekdays: list[int]
    weekday_labels: list[str]
    holidays_included: Literal[False] = False
    notice: str


class SetupAssignmentSummary(BaseModel):
    assignment_id: UUID
    work_calendar_id: UUID
    scope_type: str
    scope_id: UUID | None
    effective_from: date
    effective_to: date | None


class WorkCalendarSetupStatus(BaseModel):
    state: Literal["SETUP_REQUIRED", "CONFIGURED"]
    message: str
    company_assignment: SetupAssignmentSummary | None = None
    holiday_calendar_count: int
    suggestion: SetupSuggestion | None = None


class WorkCalendarSetupPreview(BaseModel):
    preview_only: Literal[True] = True
    notice: str
    effective_from: date
    range_from: date
    range_to: date
    working_day_count: int
    non_working_day_count: int
    holiday_calendar_count: int
    warnings: list[str]
    days: list[DayTypeRead]


class WorkCalendarSetupConfirmed(BaseModel):
    work_calendar_id: UUID
    weekly_off_pattern_id: UUID | None
    assignment_id: UUID
    scope_type: str
    scope_id: UUID | None
    effective_from: date
    confirmed_at: str
    confirmed_by: UUID | None


class WorkCalendarDaysRead(BaseModel):
    """One work calendar classified over a bounded range. `days` carries the resolver's own
    `DayTypeRead`: `holiday_name` / `holiday_type` for hard holidays, `optional_holiday_name` /
    `restricted_holiday_name` / `is_holiday_named` for named holidays that are still working days,
    `weekly_off_fraction` for weekly offs, `exception_type` for exceptions."""

    work_calendar_id: UUID
    work_calendar_name: str
    is_active: bool
    range_from: date
    range_to: date
    weekly_off_pattern_id: UUID | None
    holiday_calendar_ids: list[UUID]
    restricted_holidays_are_off_by_default: bool
    days: list[DayTypeRead]


def _label_weekdays(weekdays: list[int]) -> list[str]:
    return [_WEEKDAY_LABELS[d] for d in weekdays]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WorkCalendarSetupService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._org = OrganisationService(session, get_settings())
        self._resolution = CalendarResolutionService(session)
        self._holiday_calendar_repo = HolidayCalendarRepository()
        self._assignment_repo = PolicyAssignmentRepository()
        self._audit = AuditService()

    @staticmethod
    def _scope(config: WorkCalendarSetupConfig) -> tuple[str, UUID | None]:
        return ("BRANCH", config.branch_id) if config.branch_id else ("COMPANY", None)

    async def _current_assignment(
        self, company_id: UUID, scope_type: str, scope_id: UUID | None
    ) -> PolicyAssignment | None:
        return await self._assignment_repo.get_current(
            self._session,
            company_id=company_id,
            policy_kind="WORK_CALENDAR",
            scope_type=scope_type,
            scope_id=scope_id,
            leave_type_id=None,
        )

    async def get_status(self, company_id: UUID) -> WorkCalendarSetupStatus:
        calendars = await self._holiday_calendar_repo.list_calendars(
            self._session, company_id=company_id
        )
        current = await self._current_assignment(company_id, "COMPANY", None)
        if current is not None:
            return WorkCalendarSetupStatus(
                state="CONFIGURED",
                message="A company-wide work calendar is configured.",
                company_assignment=SetupAssignmentSummary(
                    assignment_id=current.id,
                    work_calendar_id=current.policy_id,
                    scope_type=current.scope_type,
                    scope_id=current.scope_id,
                    effective_from=current.effective_from,
                    effective_to=current.effective_to,
                ),
                holiday_calendar_count=len(calendars),
            )
        suggested_off = list(SUGGESTED_WEEKLY_OFF_WEEKDAYS)
        suggested_working = [d for d in range(7) if d not in suggested_off]
        return WorkCalendarSetupStatus(
            state="SETUP_REQUIRED",
            message="Work calendar setup required",
            holiday_calendar_count=len(calendars),
            suggestion=SetupSuggestion(
                working_weekdays=suggested_working,
                weekly_off_weekdays=suggested_off,
                weekday_labels=list(_WEEKDAY_LABELS),
                notice=(
                    "This working week is a suggestion and has not been activated. Leave and "
                    "attendance will not use it until an administrator confirms a calendar. "
                    "Public holidays are not added automatically."
                ),
            ),
        )

    async def _validate_references(self, company_id: UUID, config: WorkCalendarSetupConfig) -> None:
        for calendar_id in config.holiday_calendar_ids:
            row = await self._holiday_calendar_repo.get(
                self._session, company_id=company_id, calendar_id=calendar_id
            )
            if row is None or not row.is_active:
                raise WorkCalendarSetupInvalidError(
                    "holiday_calendar_ids contains a calendar that does not exist or is inactive",
                    field="holiday_calendar_ids",
                )
        if config.branch_id is not None:
            try:
                await self._org.get_branch(company_id, config.branch_id)
            except NotFoundError as exc:
                raise WorkCalendarSetupInvalidError(
                    "branch_id does not reference a branch of this company", field="branch_id"
                ) from exc

    async def preview(
        self, company_id: UUID, request: WorkCalendarSetupPreviewRequest
    ) -> WorkCalendarSetupPreview:
        """Reads only. Evaluates the proposed week and the chosen holiday calendars in memory."""
        await self._validate_references(company_id, request)
        range_from = request.preview_from or request.effective_from
        range_to = request.preview_to or (range_from + timedelta(days=_PREVIEW_DEFAULT_DAYS - 1))
        validate_calendar_range(range_from, range_to)

        holiday_lists = await self._resolution.load_ordered_holidays_for_calendars(
            company_id, request.holiday_calendar_ids
        )
        rules = [
            WeeklyOffRuleData(
                weekday=weekday,
                nth_in_month=None,
                cycle_start_date=None,
                off_fraction=Decimal("1.00"),
                week_parity=None,
            )
            for weekday in request.weekly_off_weekdays
        ]
        days = classify_date_range(
            start=range_from,
            end=range_to,
            ordered_holiday_lists=holiday_lists,
            weekly_off_rules=rules,
            restricted_holidays_are_off_by_default=False,
            exception_by_date={},
        )
        working = sum(1 for d in days if d.day_type in ("WORKING", "SPECIAL_WORKING"))

        warnings: list[str] = []
        if not request.holiday_calendar_ids:
            warnings.append(
                "No holiday calendar is linked. Public holidays have not been added "
                "automatically; add and link a holiday calendar if you observe holidays."
            )
        if not request.weekly_off_weekdays:
            warnings.append("No weekly off is selected: every weekday will be a working day.")
        if len(request.weekly_off_weekdays) >= 7:
            warnings.append("Every weekday is a weekly off: no working days remain.")
        if request.effective_from < datetime.now(UTC).date():
            warnings.append(
                "The effective date is in the past. Locked attendance periods and closed "
                "payroll are not recalculated; unlocked attendance follows the existing "
                "recalculation rules."
            )
        scope_type, scope_id = self._scope(request)
        if await self._current_assignment(company_id, scope_type, scope_id) is not None:
            warnings.append(
                "A work calendar is already active at this scope; confirming will be refused."
            )

        return WorkCalendarSetupPreview(
            notice="Preview only. Nothing has been saved or activated.",
            effective_from=request.effective_from,
            range_from=range_from,
            range_to=range_to,
            working_day_count=working,
            non_working_day_count=len(days) - working,
            holiday_calendar_count=len(request.holiday_calendar_ids),
            warnings=warnings,
            days=days,
        )

    async def get_calendar_days(
        self, company_id: UUID, work_calendar_id: UUID, range_from: date, range_to: date
    ) -> WorkCalendarDaysRead:
        """Read-only month/range view of one work calendar. `company_id` is the authenticated
        tenant; a calendar of another company is indistinguishable from a missing one (404)."""
        validate_calendar_range(range_from, range_to)
        calendar = await self._org.get_work_calendar(company_id, work_calendar_id)
        days = await self._resolution.classify_range_for_work_calendar(
            company_id, work_calendar_id, range_from, range_to
        )
        return WorkCalendarDaysRead(
            work_calendar_id=calendar.id,
            work_calendar_name=calendar.name,
            is_active=calendar.is_active,
            range_from=range_from,
            range_to=range_to,
            weekly_off_pattern_id=calendar.weekly_off_pattern_id,
            holiday_calendar_ids=calendar.holiday_calendar_ids,
            restricted_holidays_are_off_by_default=calendar.restricted_holidays_are_off_by_default,
            days=days,
        )

    async def _lock(self, company_id: UUID) -> None:
        """Transaction-scoped leaf lock: concurrent confirms for one company queue here, so the
        second sees the first's assignment and is refused instead of racing it."""
        key = f"work-calendar-setup:{company_id}"
        async with bounded_lock_wait(
            self._session, lock_timeout_ms=get_settings().attendance_lock_timeout_ms
        ):
            await self._session.execute(
                select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0)))
            )

    async def confirm(
        self,
        company_id: UUID,
        request: WorkCalendarSetupConfirmRequest,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WorkCalendarSetupConfirmed:
        await self._validate_references(company_id, request)
        if len(request.weekly_off_weekdays) >= 7:
            raise WorkCalendarSetupInvalidError(
                "At least one weekday must be a working day", field="weekly_off_weekdays"
            )
        scope_type, scope_id = self._scope(request)

        await self._lock(company_id)
        if await self._current_assignment(company_id, scope_type, scope_id) is not None:
            raise WorkCalendarAlreadyConfiguredError()

        pattern_id: UUID | None = None
        if request.weekly_off_weekdays:
            pattern = await self._org.create_weekly_off_pattern(
                company_id,
                WeeklyOffPatternCreate(
                    name=f"Weekly off: {', '.join(_label_weekdays(request.weekly_off_weekdays))}",
                    pattern_kind="FIXED_WEEKDAYS",
                    rules=[WeeklyOffRuleInput(weekday=d) for d in request.weekly_off_weekdays],
                ),
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            pattern_id = pattern.id

        calendar = await self._org.create_work_calendar(
            company_id,
            WorkCalendarCreate(
                name=request.name,
                description="Created through guided work calendar setup",
                weekly_off_pattern_id=pattern_id,
                holiday_calendar_ids=request.holiday_calendar_ids,
            ),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        assignment = await self._org.create_policy_assignment(
            company_id,
            PolicyAssignmentCreate(
                policy_kind="WORK_CALENDAR",
                policy_id=calendar.id,
                scope_type=scope_type,
                scope_id=scope_id,
                effective_from=request.effective_from,
                reason="Initial work calendar confirmed by administrator",
            ),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        confirmed_at = datetime.now(UTC)
        result = WorkCalendarSetupConfirmed(
            work_calendar_id=calendar.id,
            weekly_off_pattern_id=pattern_id,
            assignment_id=assignment.id,
            scope_type=scope_type,
            scope_id=scope_id,
            effective_from=request.effective_from,
            confirmed_at=confirmed_at.isoformat().replace("+00:00", "Z"),
            confirmed_by=actor_user_id,
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="WORK_CALENDAR_SETUP_CONFIRMED",
            entity_type="work_calendar",
            entity_id=calendar.id,
            after={
                **result.model_dump(mode="json"),
                "weekly_off_weekdays": request.weekly_off_weekdays,
                "holiday_calendar_ids": [str(i) for i in request.holiday_calendar_ids],
            },
            ip=ip_address,
            user_agent=user_agent,
        )
        return result


def get_work_calendar_setup_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> WorkCalendarSetupService:
    return WorkCalendarSetupService(session)
