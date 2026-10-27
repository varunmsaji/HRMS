"""In-memory "proposed change" overlay for the calendar resolver (Work Calendar phase 3).

A change-impact preview must evaluate a configuration that is not saved. Rather than a second
rule engine or temporary rows, the one resolver (`CalendarResolutionService`) accepts an optional
`CalendarOverlay` that adjusts what it has just loaded from the database. With no overlay every
code path is byte-for-byte the previous behaviour.

The overlay mirrors what the resolver reads: holidays, links, weekly-off rules, calendar settings,
exceptions, assignments and (phase 4) holiday-calendar validity windows. It deliberately does not
model `is_active` flags on patterns, work calendars or holiday calendars, which the resolver does
not read; `Holiday.is_working` is a mirror of `holiday_type = WORKING_HOLIDAY` (phase 4, policy C)
and needs no separate modelling.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from hrms.modules.organisation.calendar_resolution import HolidayData, WeeklyOffRuleData


@dataclass(frozen=True, slots=True)
class ExceptionRow:
    """Duck-types the `CalendarException` columns the resolver reads."""

    id: UUID | None
    exception_date: date
    exception_type: str
    name: str | None


@dataclass(frozen=True, slots=True)
class ProposedAssignment:
    """A `PolicyAssignment` insert-new/close-previous at one (kind, scope)."""

    policy_kind: str
    policy_id: UUID
    scope_type: str
    scope_id: UUID | None
    effective_from: date
    effective_to: date | None


@dataclass
class CalendarOverlay:
    holidays_added: dict[UUID, list["HolidayData"]] = field(default_factory=dict)
    # holiday id -> replacement (None = removed / deactivated)
    holidays_changed: dict[UUID, "HolidayData | None"] = field(default_factory=dict)
    links: dict[UUID, list[UUID]] = field(default_factory=dict)
    rules: dict[UUID, list["WeeklyOffRuleData"]] = field(default_factory=dict)
    # work calendar id -> (weekly_off_pattern_id, restricted_holidays_are_off_by_default)
    calendar_settings: dict[UUID, tuple[UUID | None, bool]] = field(default_factory=dict)
    exceptions_added: dict[UUID, list[ExceptionRow]] = field(default_factory=dict)
    # exception id -> replacement (None = deactivated)
    exceptions_changed: dict[UUID, ExceptionRow | None] = field(default_factory=dict)
    assignment: ProposedAssignment | None = None
    # holiday calendar id -> proposed (valid_from, valid_to)
    validity: dict[UUID, tuple[date | None, date | None]] = field(default_factory=dict)

    # -- hooks called by the resolver -------------------------------------------------------

    def adjust_holidays(
        self, calendar_id: UUID, loaded: list["HolidayData"]
    ) -> list["HolidayData"]:
        out: list[HolidayData] = []
        for holiday in loaded:
            if holiday.holiday_id is not None and holiday.holiday_id in self.holidays_changed:
                replacement = self.holidays_changed[holiday.holiday_id]
                if replacement is not None:
                    out.append(replacement)
            else:
                out.append(holiday)
        out.extend(self.holidays_added.get(calendar_id, []))
        return out

    def adjust_validity(
        self, calendar_id: UUID, loaded: tuple[date | None, date | None]
    ) -> tuple[date | None, date | None]:
        return self.validity.get(calendar_id, loaded)

    def adjust_links(self, work_calendar_id: UUID, loaded: list[UUID]) -> list[UUID]:
        return self.links.get(work_calendar_id, loaded)

    def adjust_rules(
        self, pattern_id: UUID, loaded: list["WeeklyOffRuleData"]
    ) -> list["WeeklyOffRuleData"]:
        return self.rules.get(pattern_id, loaded)

    def adjust_settings(
        self, work_calendar_id: UUID, pattern_id: UUID | None, restricted_off: bool
    ) -> tuple[UUID | None, bool]:
        return self.calendar_settings.get(work_calendar_id, (pattern_id, restricted_off))

    def adjust_exceptions(self, work_calendar_id: UUID, loaded: list[Any]) -> list[Any]:
        out: list[Any] = []
        for row in loaded:
            if row.id in self.exceptions_changed:
                replacement = self.exceptions_changed[row.id]
                if replacement is not None:
                    out.append(replacement)
            else:
                out.append(row)
        out.extend(self.exceptions_added.get(work_calendar_id, []))
        return out

    def adjust_assignment(
        self,
        policy_kind: str,
        scope_type: str,
        scope_id: UUID | None,
        as_of: date,
        found: Any,
    ) -> tuple[bool, ProposedAssignment | None]:
        """Returns `(replaced, proposed)`. `replaced=False` -> keep `found` as loaded. Otherwise
        the effective row is `proposed` (or nothing when `proposed is None`)."""
        change = self.assignment
        if (
            change is None
            or change.policy_kind != policy_kind
            or change.scope_type != scope_type
            or change.scope_id != scope_id
            or as_of < change.effective_from
        ):
            return False, None
        if change.effective_to is None or as_of <= change.effective_to:
            return True, change
        return True, None  # the previous row is closed the day before, the new one has ended
