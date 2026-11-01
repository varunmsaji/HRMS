"""Break events (break management V1): start / end / state / correction.

The backend is the only authority. The mobile and web clients render `BreakStateRead` and send
named intents; every rule below is re-checked here whatever the client believes:

* the employee has an effective shift, is checked in (last punch is IN) and has not checked out;
* no other break is active, the break exists in the employee's *resolved* configuration
  (shift defaults + employee overrides, by date), and its mode allows punching;
* the instant is the server clock — there is no client time on the self routes;
* the attendance date is not in a closed period;
* a repeated request with the same idempotency key replays instead of writing again.

Events are never edited. A correction writes a new event that supersedes the old one, so the
original punch, its source and its timestamp stay in the table forever.
"""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import AppError, PermissionDeniedError, ValidationError
from hrms.core.observability.logging import get_logger
from hrms.core.rbac.types import DataScope
from hrms.modules.attendance import calculation as calc
from hrms.modules.attendance.break_repository import (
    BreakEventRepository,
    EmployeeBreakOverrideRepository,
)
from hrms.modules.attendance.break_rules import BreakOverrideData, resolve_breaks
from hrms.modules.attendance.break_schemas import (
    ActiveBreakRead,
    BreakActionSelf,
    BreakDayRead,
    BreakEventRead,
    BreakResolveInput,
    BreakRuleRead,
    BreakStateRead,
    CompletedBreakRead,
    ResolvedBreakRulesRead,
    break_event_to_audit_dict,
    break_event_to_read,
)
from hrms.modules.attendance.models import AttendanceBreakEvent, EmployeeBreakOverride, Punch
from hrms.modules.attendance.repository import (
    AttendanceDayRepository,
    PunchRepository,
    ShiftRosterRepository,
)
from hrms.modules.attendance.service import (
    _ensure_date_open,
    _ensure_employee_visible,
    _resolve_shift_schedule,
    _resolve_visible_employee_ids,
    _ResolvedShiftSchedule,
)
from hrms.shared.timezone import resolve_zoneinfo

_logger = get_logger(__name__)

PUNCHABLE_MODES = ("MANDATORY_PUNCH", "OPTIONAL_PUNCH")


def utcnow() -> datetime:
    """The one clock break events and the active/unresolved decision read; tests replace it."""
    return datetime.now(UTC)


class BreakActionError(AppError):
    """A break action the server refuses. `code` says why, so clients can react without parsing
    the message (the mobile app maps `BREAK_ALREADY_ACTIVE` to "refresh state", for example)."""

    status_code = 409

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(
            message, code=code, details=[{"field": "break", "code": code, "message": message}]
        )
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Rule resolution shared with the calculation (`AttendanceDayService._build_calculation_input`)
# ---------------------------------------------------------------------------


def override_to_data(row: EmployeeBreakOverride) -> BreakOverrideData:
    return BreakOverrideData(
        id=row.id,
        action=row.action,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        target_break_name=row.target_break_name,
        shift_id=row.shift_id,
        revoked=row.revoked_at is not None,
        name=row.name,
        break_type=row.break_type,
        break_kind=row.break_kind,
        mode=row.mode,
        start_time=row.start_time,
        end_time=row.end_time,
        window_start=row.window_start,
        window_end=row.window_end,
        min_minutes=row.min_minutes,
        max_minutes=row.max_minutes,
        scheduled_minutes=row.scheduled_minutes,
        is_paid=row.is_paid,
        is_mandatory=row.is_mandatory,
        crosses_midnight=row.crosses_midnight,
        excess_outcome=row.excess_outcome,
        auto_deduct_full=row.auto_deduct_full,
        optional_recorded_deducts=row.optional_recorded_deducts,
        optional_scheduled_fallback=row.optional_scheduled_fallback,
        sort_order=row.sort_order,
    )


async def apply_break_overrides(
    session: AsyncSession,
    *,
    company_id: UUID,
    employee_id: UUID,
    target_date: date,
    shift_id: UUID | None,
    schedule: _ResolvedShiftSchedule,
) -> _ResolvedShiftSchedule:
    """Layers the employee's in-force overrides over the shift version's breaks. Returns the
    schedule unchanged when the employee has none (the common case: one indexed query)."""
    if schedule.shift_inputs is None:
        return schedule
    rows = await EmployeeBreakOverrideRepository().list_in_force(
        session, company_id=company_id, employee_id=employee_id, target_date=target_date
    )
    if not rows:
        return schedule
    resolved = resolve_breaks(
        list(schedule.shift_inputs.breaks),
        [override_to_data(r) for r in rows],
        target_date=target_date,
        shift_id=shift_id,
    )
    return replace(
        schedule,
        shift_inputs=replace(
            schedule.shift_inputs,
            breaks=resolved.breaks,
            break_provenance=resolved.provenance,
        ),
    )


def to_event_data(rows: list[AttendanceBreakEvent]) -> list[calc.BreakEventData]:
    return [
        calc.BreakEventData(
            id=r.id,
            event_type=r.event_type,
            event_time=r.event_time,
            break_name=r.break_name,
            shift_break_id=r.shift_break_id,
            supersedes_event_id=r.supersedes_event_id,
            approved=r.approved_by_user_id is not None,
        )
        for r in rows
    ]


def _rule_read(
    rule: calc.ShiftBreakData, *, taken: bool, can_punch: bool, window: tuple[str, str] | None
) -> BreakRuleRead:
    return BreakRuleRead(
        name=rule.name,
        break_type=rule.break_type,
        mode=rule.mode,
        is_paid=rule.is_paid,
        is_mandatory=rule.is_mandatory,
        scheduled_start=window[0] if window else None,
        scheduled_end=window[1] if window else None,
        scheduled_minutes=rule.scheduled_minutes,
        min_minutes=rule.min_minutes,
        max_minutes=rule.max_minutes,
        rule_source=rule.rule_source,
        can_punch=can_punch,
        taken=taken,
    )


def _window_labels(rule: calc.ShiftBreakData) -> tuple[str, str] | None:
    start, end = (
        (rule.start_time, rule.end_time)
        if rule.break_kind == "FIXED_WINDOW"
        else (rule.window_start, rule.window_end)
    )
    if start is None or end is None:
        return None
    return start.strftime("%H:%M"), end.strftime("%H:%M")


# ---------------------------------------------------------------------------
# Day context
# ---------------------------------------------------------------------------


@dataclass
class _Day:
    attendance_date: date
    shift_id: UUID | None
    schedule: _ResolvedShiftSchedule
    punches: list[Punch]
    events: list[AttendanceBreakEvent]

    @property
    def rules(self) -> list[calc.ShiftBreakData]:
        shift = self.schedule.shift_inputs
        return [b for b in (shift.breaks if shift else []) if b.is_enabled]

    @property
    def last_punch(self) -> Punch | None:
        return self.punches[-1] if self.punches else None

    @property
    def checked_in(self) -> bool:
        return self.last_punch is not None and self.last_punch.direction == "IN"

    @property
    def checked_out(self) -> bool:
        return self.last_punch is not None and self.last_punch.direction == "OUT"

    def pairs(
        self,
    ) -> list[tuple[calc.BreakEventData, calc.BreakEventData | None]]:
        return calc.pair_break_events(calc.effective_break_events(to_event_data(self.events)))

    def active_start(self) -> calc.BreakEventData | None:
        for start, end in self.pairs():
            if end is None:
                return start
        return None


class BreakEventService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._events = BreakEventRepository()
        self._overrides = EmployeeBreakOverrideRepository()
        self._punches = PunchRepository()
        self._rosters = ShiftRosterRepository()
        self._days = AttendanceDayRepository()
        self._audit = AuditService()

    # --- context -----------------------------------------------------------------------------

    async def _schedule_for(
        self, company_id: UUID, employee_id: UUID, target_date: date, company_tz: str
    ) -> tuple[_ResolvedShiftSchedule, UUID | None]:
        from hrms.modules.employee.service import EmployeeAssignmentService
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session)
        assignment = await EmployeeAssignmentService(self._session).get_assignment_as_of(
            company_id, employee_id, target_date
        )
        branch_tz: str | None = None
        if assignment is not None and assignment.branch_id is not None:
            branch_tz = (await organisation.get_branch(company_id, assignment.branch_id)).timezone
        roster = await self._rosters.get_published_for_date(
            self._session, company_id=company_id, employee_id=employee_id, roster_date=target_date
        )
        shift_id = (
            roster.shift_id if roster is not None else (assignment.shift_id if assignment else None)
        )
        schedule = await _resolve_shift_schedule(
            organisation,
            company_id=company_id,
            shift_id=shift_id,
            target_date=target_date,
            branch_timezone=branch_tz,
            company_timezone=company_tz,
        )
        schedule = await apply_break_overrides(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            target_date=target_date,
            shift_id=shift_id,
            schedule=schedule,
        )
        return schedule, shift_id

    async def _load_day(self, company_id: UUID, employee_id: UUID, at: datetime) -> _Day:
        """The attendance day `at` belongs to. Both the local date and the day before are tried,
        so 00:30 on a night shift that started yesterday resolves to yesterday's day, and the
        date is derived from the shift window — never from the device."""
        from hrms.modules.organisation.service import OrganisationService

        company = await OrganisationService(self._session).get_company_profile(company_id)
        local_date = at.astimezone(resolve_zoneinfo(company.timezone)).date()
        first: tuple[date, _ResolvedShiftSchedule, UUID | None] | None = None
        for target in (local_date, local_date - timedelta(days=1)):
            schedule, shift_id = await self._schedule_for(
                company_id, employee_id, target, company.timezone
            )
            if first is None:
                first = (target, schedule, shift_id)
            window = schedule.window
            if schedule.shift_inputs is None or not (window.load_start <= at <= window.load_end):
                continue
            return await self._day(company_id, employee_id, target, schedule, shift_id, at)
        assert first is not None
        return await self._day(company_id, employee_id, first[0], first[1], first[2], at)

    async def _day(
        self,
        company_id: UUID,
        employee_id: UUID,
        target: date,
        schedule: _ResolvedShiftSchedule,
        shift_id: UUID | None,
        at: datetime,
    ) -> _Day:
        window = schedule.window
        punches = await self._punches.list_for_employee_window(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            window_start=window.load_start,
            window_end=max(window.load_end, at) + timedelta(seconds=1),
        )
        events = await self._events.list_for_date(
            self._session, company_id=company_id, employee_id=employee_id, attendance_date=target
        )
        return _Day(
            attendance_date=target,
            shift_id=shift_id,
            schedule=schedule,
            punches=[p for p in punches if p.punch_time <= at],
            events=events,
        )

    # --- state -------------------------------------------------------------------------------

    def _state(self, day: _Day, at: datetime) -> BreakStateRead:
        rules = day.rules
        active = day.active_start()
        completed: list[CompletedBreakRead] = []
        taken_names: set[str] = set()
        for start, end in day.pairs():
            name = (start.break_name or "").lower()
            taken_names.add(name)
            if end is not None:
                completed.append(
                    CompletedBreakRead(
                        break_name=start.break_name,
                        started_at=start.event_time.isoformat().replace("+00:00", "Z"),
                        ended_at=end.event_time.isoformat().replace("+00:00", "Z"),
                        minutes=max(
                            0, int((end.event_time - start.event_time).total_seconds() // 60)
                        ),
                        is_approved=end.approved,
                    )
                )
        in_shift = day.schedule.shift_inputs is not None
        can_work = in_shift and day.checked_in
        rule_reads: list[BreakRuleRead] = []
        any_available = False
        for rule in rules:
            taken = rule.name.lower() in taken_names and not self._allows_split(rule)
            punchable = rule.mode in PUNCHABLE_MODES
            rule_reads.append(
                _rule_read(rule, taken=taken, can_punch=punchable, window=_window_labels(rule))
            )
            if punchable and not taken:
                any_available = True
        modes = {r.mode for r in rules if r.mode in PUNCHABLE_MODES}
        punching = "MANDATORY" if "MANDATORY_PUNCH" in modes else "OPTIONAL" if modes else "NONE"
        active_read: ActiveBreakRead | None = None
        if active is not None:
            active_rule = self._rule_by_name(rules, active.break_name)
            active_read = ActiveBreakRead(
                event_id=active.id,
                break_name=active.break_name,
                break_type=active_rule.break_type if active_rule else None,
                is_paid=active_rule.is_paid if active_rule else None,
                started_at=active.event_time.isoformat().replace("+00:00", "Z"),
                max_minutes=active_rule.max_minutes if active_rule else None,
            )
        return BreakStateRead(
            attendance_date=day.attendance_date,
            shift_name_known=in_shift,
            checked_in=day.checked_in,
            checked_out=day.checked_out,
            can_start=can_work and active is None and any_available,
            can_end=active is not None and day.checked_in,
            punching=punching,  # type: ignore[arg-type]
            active_break=active_read,
            rules=rule_reads,
            completed=completed,
            server_time=at.isoformat().replace("+00:00", "Z"),
        )

    @staticmethod
    def _allows_split(rule: calc.ShiftBreakData) -> bool:
        return rule.allows_split

    @staticmethod
    def _rule_by_name(
        rules: list[calc.ShiftBreakData], name: str | None
    ) -> calc.ShiftBreakData | None:
        wanted = (name or "").strip().lower()
        for rule in rules:
            if rule.name.strip().lower() == wanted:
                return rule
        return None

    async def get_state(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> BreakStateRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        at = utcnow()
        return self._state(await self._load_day(company_id, employee_id, at), at)

    # --- start / end -------------------------------------------------------------------------

    async def _lock(self, employee_id: UUID, attendance_date: date) -> None:
        """Serialises start/end for one employee-day so two concurrent requests cannot both pass
        the "no active break" check."""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"break:{employee_id}:{attendance_date}"},
        )

    async def _replay(
        self,
        company_id: UUID,
        employee_id: UUID,
        event_type: str,
        idempotency_key: str | None,
        break_name: str | None,
    ) -> AttendanceBreakEvent | None:
        if not idempotency_key:
            return None
        existing = await self._events.get_by_idempotency_key(
            self._session, company_id=company_id, idempotency_key=idempotency_key
        )
        if existing is None:
            return None
        if (
            existing.employee_id != employee_id
            or existing.event_type != event_type
            or (
                break_name
                and existing.break_name
                and existing.break_name.lower() != break_name.lower()
            )
        ):
            raise BreakActionError(
                "BREAK_IDEMPOTENCY_KEY_REUSED",
                "This idempotency_key was already used for a different break action",
            )
        return existing

    async def start_break(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: BreakActionSelf,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BreakStateRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        at = utcnow()
        if await self._replay(
            company_id, employee_id, "START", body.idempotency_key, body.break_name
        ):
            return self._state(await self._load_day(company_id, employee_id, at), at)

        day = await self._load_day(company_id, employee_id, at)
        await self._lock(employee_id, day.attendance_date)
        # Re-read under the lock: a concurrent request may have just written an event.
        day.events = await self._events.list_for_date(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=day.attendance_date,
        )
        if await self._replay(
            company_id, employee_id, "START", body.idempotency_key, body.break_name
        ):
            return self._state(day, at)

        if day.schedule.shift_inputs is None:
            raise BreakActionError(
                "BREAK_NO_ACTIVE_SHIFT", "You have no active shift today.", status_code=422
            )
        if day.last_punch is None:
            raise BreakActionError("BREAK_NOT_CHECKED_IN", "Check in before starting a break.")
        if day.checked_out:
            raise BreakActionError(
                "BREAK_ALREADY_CHECKED_OUT", "You have checked out; a break cannot be started."
            )
        if day.active_start() is not None:
            raise BreakActionError(
                "BREAK_ALREADY_ACTIVE", "A break is already in progress. End it first."
            )
        assert day.last_punch is not None
        if at <= day.last_punch.punch_time:
            raise BreakActionError("BREAK_BEFORE_CHECK_IN", "A break cannot start before check-in.")

        rule = self._pick_rule(day, body.break_name)
        await _ensure_date_open(
            self._session, company_id, day.attendance_date, employee_id=employee_id
        )
        event = await self._write_event(
            company_id,
            employee_id,
            day,
            event_type="START",
            event_time=at,
            rule=rule,
            source=body.client,
            idempotency_key=body.idempotency_key,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        day.events.append(event)
        await self._recalculate(company_id, employee_id, day.attendance_date, actor_user_id)
        return self._state(day, at)

    def _pick_rule(self, day: _Day, break_name: str | None) -> calc.ShiftBreakData:
        taken = {(s.break_name or "").lower() for s, _e in day.pairs()}
        punchable = [r for r in day.rules if r.mode in PUNCHABLE_MODES]
        if break_name is None:
            open_rules = [
                r for r in punchable if r.name.lower() not in taken or self._allows_split(r)
            ]
            if len(open_rules) != 1:
                raise BreakActionError(
                    "BREAK_NAME_REQUIRED",
                    "Choose which break to start.",
                    status_code=422,
                )
            return open_rules[0]
        rule = self._rule_by_name(day.rules, break_name)
        if rule is None:
            raise BreakActionError(
                "BREAK_NOT_CONFIGURED",
                "That break is not part of your shift.",
                status_code=422,
            )
        if rule.mode not in PUNCHABLE_MODES:
            raise BreakActionError(
                "BREAK_PUNCHING_NOT_ALLOWED",
                "This break is deducted automatically and is not punched.",
                status_code=422,
            )
        if rule.name.lower() in taken and not self._allows_split(rule):
            raise BreakActionError(
                "BREAK_ALREADY_TAKEN", "You have already taken this break today."
            )
        return rule

    async def end_break(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: BreakActionSelf,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BreakStateRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        at = utcnow()
        if await self._replay(
            company_id, employee_id, "END", body.idempotency_key, body.break_name
        ):
            return self._state(await self._load_day(company_id, employee_id, at), at)

        day = await self._load_day(company_id, employee_id, at)
        await self._lock(employee_id, day.attendance_date)
        day.events = await self._events.list_for_date(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=day.attendance_date,
        )
        if await self._replay(
            company_id, employee_id, "END", body.idempotency_key, body.break_name
        ):
            return self._state(day, at)

        active = day.active_start()
        if active is None:
            raise BreakActionError("BREAK_NOT_ACTIVE", "There is no break in progress to end.")
        if day.checked_out:
            raise BreakActionError(
                "BREAK_ENDED_AFTER_CHECKOUT",
                "You have already checked out. Ask HR to correct this break.",
            )
        if (
            body.break_name
            and active.break_name
            and body.break_name.lower() != active.break_name.lower()
        ):
            raise BreakActionError(
                "BREAK_NAME_MISMATCH", f"The active break is '{active.break_name}'."
            )
        if at <= active.event_time:
            raise BreakActionError("BREAK_END_BEFORE_START", "A break cannot end before it starts.")
        await _ensure_date_open(
            self._session, company_id, day.attendance_date, employee_id=employee_id
        )
        rule = self._rule_by_name(day.rules, active.break_name)
        event = await self._write_event(
            company_id,
            employee_id,
            day,
            event_type="END",
            event_time=at,
            rule=rule,
            break_name=active.break_name,
            source=body.client,
            idempotency_key=body.idempotency_key,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        day.events.append(event)
        await self._recalculate(company_id, employee_id, day.attendance_date, actor_user_id)
        return self._state(day, at)

    async def _write_event(
        self,
        company_id: UUID,
        employee_id: UUID,
        day: _Day,
        *,
        event_type: str,
        event_time: datetime,
        rule: calc.ShiftBreakData | None,
        source: str,
        actor_user_id: UUID | None,
        idempotency_key: str | None = None,
        break_name: str | None = None,
        approved_by: UUID | None = None,
        supersedes: UUID | None = None,
        regularization_request_id: UUID | None = None,
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AttendanceBreakEvent:
        existing_day = await self._days.get_by_employee_date(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=day.attendance_date,
        )
        data: dict[str, Any] = {
            "id": uuid4(),
            "company_id": company_id,
            "employee_id": employee_id,
            "attendance_date": day.attendance_date,
            "attendance_day_id": existing_day.id if existing_day else None,
            "shift_break_id": rule.id if rule is not None and rule.rule_source == "SHIFT" else None,
            "break_name": break_name or (rule.name if rule is not None else None),
            "event_type": event_type,
            "event_time": event_time,
            "source": source,
            "idempotency_key": idempotency_key,
            "recorded_by_user_id": actor_user_id,
            "approved_by_user_id": approved_by,
            "supersedes_event_id": supersedes,
            "regularization_request_id": regularization_request_id,
            "reason": reason,
            "meta": {
                "ip": ip_address,
                "user_agent": user_agent,
                "shift_version_id": str(day.schedule.shift_version_id)
                if day.schedule.shift_version_id
                else None,
                "rule_source": rule.rule_source if rule is not None else None,
                "override_id": str(rule.override_id)
                if rule is not None and rule.override_id
                else None,
            },
        }
        try:
            async with self._session.begin_nested():
                row = await self._events.insert(self._session, data=data)
        except IntegrityError as exc:
            if idempotency_key:
                winner = await self._events.get_by_idempotency_key(
                    self._session, company_id=company_id, idempotency_key=idempotency_key
                )
                if winner is not None and winner.employee_id == employee_id:
                    return winner
            raise BreakActionError(
                "BREAK_EVENT_CONFLICT", "The break could not be recorded; refresh and retry."
            ) from exc
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="BREAK_STARTED" if event_type == "START" else "BREAK_ENDED",
            entity_type="attendance_break_event",
            entity_id=row.id,
            after=break_event_to_audit_dict(break_event_to_read(row)),
            ip=ip_address,
            user_agent=user_agent,
        )
        return row

    async def _recalculate(
        self, company_id: UUID, employee_id: UUID, attendance_date: date, actor_user_id: UUID | None
    ) -> None:
        """Best-effort, like the punch hook: the event is the fact, the day row a derivation.
        A failure is logged and the scheduled sweep recomputes the day."""
        from hrms.modules.attendance.service import AttendanceDayService

        try:
            async with self._session.begin_nested():
                await AttendanceDayService(self._session).calculate(
                    company_id, employee_id, attendance_date, actor_user_id=actor_user_id
                )
        except Exception:  # noqa: BLE001 - see docstring
            _logger.warning(
                "break_immediate_calculate_failed",
                company_id=str(company_id),
                employee_id=str(employee_id),
                attendance_date=attendance_date.isoformat(),
            )

    # --- review / correction -----------------------------------------------------------------

    async def list_events(
        self,
        company_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None,
        date_from: date,
        date_to: date,
    ) -> list[BreakEventRead]:
        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        if employee_id is not None:
            if visible is not None and employee_id not in visible:
                from hrms.core.errors.base import NotFoundError

                raise NotFoundError("Resource not found")
            visible = frozenset({employee_id})
        rows = await self._events.list_in_range(
            self._session,
            company_id=company_id,
            employee_ids=visible,
            date_from=date_from,
            date_to=date_to,
        )
        return [break_event_to_read(r) for r in rows]

    async def resolved_rules(
        self,
        company_id: UUID,
        employee_id: UUID,
        target_date: date,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> ResolvedBreakRulesRead:
        """The configuration the engine will use — shift defaults with overrides applied and
        every rule labelled by origin (the "inherited vs overridden" view)."""
        from hrms.modules.organisation.service import OrganisationService

        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        company = await OrganisationService(self._session).get_company_profile(company_id)
        schedule, shift_id = await self._schedule_for(
            company_id, employee_id, target_date, company.timezone
        )
        shift = schedule.shift_inputs
        rules = [b for b in (shift.breaks if shift else []) if b.is_enabled]
        return ResolvedBreakRulesRead(
            employee_id=employee_id,
            date=target_date,
            shift_id=shift_id,
            shift_version_id=schedule.shift_version_id,
            rules=[
                _rule_read(
                    r, taken=False, can_punch=r.mode in PUNCHABLE_MODES, window=_window_labels(r)
                )
                for r in rules
            ],
            overrides_applied=list(shift.break_provenance) if shift else [],
        )

    async def resolve_break(
        self,
        company_id: UUID,
        body: BreakResolveInput,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
        regularization_request_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BreakDayRead:
        """HR / authorised-manager resolution of an unresolved or disputed break.

        Writes a new END event (source ADMIN, `approved_by` = the actor) — for an unresolved
        break it completes the pair; for a closed one it supersedes the old END. The employee's
        own request is never allowed to resolve itself."""
        start = await self._events.get(
            self._session, company_id=company_id, event_id=body.start_event_id
        )
        if start is None or start.event_type != "START":
            from hrms.core.errors.base import NotFoundError

            raise NotFoundError("Resource not found")
        await _ensure_employee_visible(
            self._session, company_id, start.employee_id, scope, caller_employee_id
        )
        if caller_employee_id is not None and caller_employee_id == start.employee_id:
            raise PermissionDeniedError("You cannot resolve your own break")
        return await self._apply_correction(
            company_id,
            start=start,
            corrected_end=body.corrected_end,
            approved_minutes=body.approved_minutes,
            reason=body.reason,
            actor_user_id=actor_user_id,
            regularization_request_id=regularization_request_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _apply_correction(
        self,
        company_id: UUID,
        *,
        start: AttendanceBreakEvent,
        corrected_end: datetime | None,
        approved_minutes: int | None,
        reason: str,
        actor_user_id: UUID | None,
        regularization_request_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> BreakDayRead:
        if await self._events.has_superseding_event(
            self._session, company_id=company_id, event_id=start.id
        ):
            raise BreakActionError(
                "BREAK_START_SUPERSEDED", "This break start has itself been corrected."
            )
        end_time = (
            corrected_end
            if corrected_end is not None
            else start.event_time + timedelta(minutes=approved_minutes or 0)
        )
        end_time = end_time.astimezone(UTC)
        now = utcnow()
        if end_time <= start.event_time:
            raise ValidationError("The break must end after it starts")
        if end_time > now:
            raise ValidationError("The break end cannot be in the future")
        await self._lock(start.employee_id, start.attendance_date)
        await _ensure_date_open(
            self._session, company_id, start.attendance_date, employee_id=start.employee_id
        )
        events = await self._events.list_for_date(
            self._session,
            company_id=company_id,
            employee_id=start.employee_id,
            attendance_date=start.attendance_date,
        )
        pair = next(
            (
                (s, e)
                for s, e in calc.pair_break_events(
                    calc.effective_break_events(to_event_data(events))
                )
                if s.id == start.id
            ),
            None,
        )
        if pair is None:
            raise BreakActionError(
                "BREAK_NOT_RESOLVABLE", "That break start is no longer in effect."
            )
        _start_data, current_end = pair
        later_start = min(
            (
                e.event_time
                for e in events
                if e.event_type == "START" and e.event_time > start.event_time
            ),
            default=None,
        )
        if later_start is not None and end_time > later_start:
            raise ValidationError("The break cannot end after the next break starts")

        day = _Day(
            attendance_date=start.attendance_date,
            shift_id=None,
            schedule=_ResolvedShiftSchedule(
                shift_inputs=None,
                shift_version_id=None,
                tz_name="UTC",
                window=calc.ScheduleWindow(None, None, end_time, end_time),
            ),
            punches=[],
            events=events,
        )
        row = await self._write_event(
            company_id,
            start.employee_id,
            day,
            event_type="END",
            event_time=end_time,
            rule=None,
            break_name=start.break_name,
            source="ADMIN",
            actor_user_id=actor_user_id,
            approved_by=actor_user_id,
            supersedes=current_end.id if current_end is not None else None,
            regularization_request_id=regularization_request_id,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="BREAK_CORRECTED",
            entity_type="attendance_break_event",
            entity_id=row.id,
            before={
                "start_event_id": str(start.id),
                "end_event_id": str(current_end.id) if current_end else None,
            },
            after=break_event_to_audit_dict(break_event_to_read(row)),
            ip=ip_address,
            user_agent=user_agent,
        )
        await self._recalculate(company_id, start.employee_id, start.attendance_date, actor_user_id)
        events.append(row)
        return BreakDayRead(
            employee_id=start.employee_id,
            attendance_date=start.attendance_date,
            events=[break_event_to_read(e) for e in events],
        )

    async def day_events(
        self,
        company_id: UUID,
        employee_id: UUID,
        attendance_date: date,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> BreakDayRead:
        await _ensure_employee_visible(
            self._session, company_id, employee_id, scope, caller_employee_id
        )
        rows = await self._events.list_for_date(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            attendance_date=attendance_date,
        )
        return BreakDayRead(
            employee_id=employee_id,
            attendance_date=attendance_date,
            events=[break_event_to_read(e) for e in rows],
        )
