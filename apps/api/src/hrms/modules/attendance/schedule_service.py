"""Weekly operational schedule (shift coverage) and shift-swap requests.

The schedule is derived entirely from stored data: published `ShiftRoster` rows, each shift's
published `ShiftVersion` timings and `shift.min_staff` target, and the employee's current
assignment (department / branch). Nothing is computed from constants.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError
from hrms.core.rbac.types import DataScope
from hrms.modules.attendance.models import ShiftRoster, ShiftSwapRequest
from hrms.modules.attendance.service import (
    _ensure_date_open,
    _ensure_employee_visible,
    _resolve_visible_employee_ids,
)
from hrms.modules.employee.models import Employee, EmployeeAssignment
from hrms.modules.organisation.models import Department, Shift, ShiftVersion

_LIVE_STATUSES = ("ACTIVE", "PROBATION", "ON_NOTICE")
_PEOPLE_PREVIEW = 4


class SchedulePerson(BaseModel):
    id: UUID
    name: str
    initials: str


class ScheduleCell(BaseModel):
    date: date
    count: int
    met: bool | None  # None when the shift has no target
    people: list[SchedulePerson]
    has_pending_swap: bool


class ScheduleShift(BaseModel):
    id: UUID
    name: str
    code: str | None
    start_time: time | None
    end_time: time | None
    is_night_shift: bool
    daily_hours: float
    weekly_hours: float
    min_staff: int | None
    peak_staff: int
    departments: list[str]
    days_below_target: int
    cells: list[ScheduleCell]


class ScheduleTotals(BaseModel):
    active_headcount: int
    rostered_staff: int
    coverage_pct: float | None
    shifts_with_target: int
    cells_below_target: int
    night_staff: int
    night_shift_count: int
    pending_swaps: int
    allocated_hours: float
    last_roster_update: datetime | None


class WeeklySchedule(BaseModel):
    week_start: date
    week_end: date
    days: list[date]
    shifts: list[ScheduleShift]
    totals: ScheduleTotals


class SwapParty(BaseModel):
    employee_id: UUID
    name: str
    code: str
    department: str | None
    shift_id: UUID
    shift_name: str
    shift_start: time | None
    shift_end: time | None


class SwapRequestRead(BaseModel):
    id: UUID
    reference: str
    swap_date: date
    status: str
    reason: str | None
    counterpart_consented: bool
    coverage_ok: bool
    requester: SwapParty
    counterpart: SwapParty
    created_at: datetime
    decided_at: datetime | None
    decision_note: str | None


class SwapRequestCreate(BaseModel):
    requester_employee_id: UUID
    counterpart_employee_id: UUID
    swap_date: date
    reason: str | None = None
    counterpart_consented: bool = False


class SwapDecision(BaseModel):
    note: str | None = None


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def _full_name(e: Employee) -> str:
    return e.display_name or " ".join(p for p in (e.first_name, e.last_name) if p)


def _duration_hours(start: time | None, end: time | None) -> float:
    if start is None or end is None:
        return 0.0
    s = start.hour * 60 + start.minute
    e = end.hour * 60 + end.minute
    if e <= s:
        e += 24 * 60
    return round((e - s) / 60, 2)


class RosterScheduleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService()

    # -- shift timings -------------------------------------------------------------------------

    async def _shift_timings(
        self, company_id: UUID, on: date
    ) -> dict[UUID, tuple[time | None, time | None]]:
        """Published version covering `on`, else the master row's own timings."""
        rows = (
            await self._session.execute(
                select(ShiftVersion.shift_id, ShiftVersion.start_time, ShiftVersion.end_time)
                .where(
                    ShiftVersion.company_id == company_id,
                    ShiftVersion.status == "PUBLISHED",
                    ShiftVersion.deleted_at.is_(None),
                    ShiftVersion.effective_from <= on,
                    (ShiftVersion.effective_to.is_(None)) | (ShiftVersion.effective_to >= on),
                )
                .order_by(ShiftVersion.effective_from)
            )
        ).all()
        return {r.shift_id: (r.start_time, r.end_time) for r in rows}

    # -- weekly schedule -----------------------------------------------------------------------

    async def weekly_schedule(
        self,
        company_id: UUID,
        *,
        week_start: date,
        branch_id: UUID | None,
        department_id: UUID | None,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> WeeklySchedule:
        days = [week_start + timedelta(days=i) for i in range(7)]
        week_end = days[-1]
        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )

        emp_stmt = (
            select(Employee, Department.name.label("dept"))
            .join(
                EmployeeAssignment,
                (EmployeeAssignment.employee_id == Employee.id)
                & (EmployeeAssignment.effective_to.is_(None))
                & (EmployeeAssignment.deleted_at.is_(None)),
            )
            .outerjoin(Department, Department.id == EmployeeAssignment.department_id)
            .where(Employee.company_id == company_id, Employee.status.in_(_LIVE_STATUSES))
        )
        if branch_id:
            emp_stmt = emp_stmt.where(EmployeeAssignment.branch_id == branch_id)
        if department_id:
            emp_stmt = emp_stmt.where(EmployeeAssignment.department_id == department_id)
        if visible is not None:
            emp_stmt = emp_stmt.where(Employee.id.in_(visible or {uuid4()}))
        emp_rows = (await self._session.execute(emp_stmt)).all()
        employees = {e.id: (e, dept) for e, dept in emp_rows}

        roster = (
            (
                await self._session.execute(
                    select(ShiftRoster).where(
                        ShiftRoster.company_id == company_id,
                        ShiftRoster.status == "PUBLISHED",
                        ShiftRoster.deleted_at.is_(None),
                        ShiftRoster.roster_date >= week_start,
                        ShiftRoster.roster_date <= week_end,
                        ShiftRoster.employee_id.in_(employees.keys() or {uuid4()}),
                    )
                )
            )
            .scalars()
            .all()
        )

        shifts = (
            (
                await self._session.execute(
                    select(Shift)
                    .where(
                        Shift.company_id == company_id,
                        Shift.deleted_at.is_(None),
                        Shift.is_active.is_(True),
                    )
                    .order_by(Shift.created_at)
                )
            )
            .scalars()
            .all()
        )
        timings = await self._shift_timings(company_id, week_start)

        pending = (
            (
                await self._session.execute(
                    select(ShiftSwapRequest).where(
                        ShiftSwapRequest.company_id == company_id,
                        ShiftSwapRequest.status == "PENDING",
                    )
                )
            )
            .scalars()
            .all()
        )
        swap_dates = {(s.swap_date, s.requester_shift_id) for s in pending} | {
            (s.swap_date, s.counterpart_shift_id) for s in pending
        }

        by_cell: dict[tuple[UUID, date], list[UUID]] = defaultdict(list)
        for r in roster:
            if r.shift_id and not r.is_week_off_override:
                by_cell[(r.shift_id, r.roster_date)].append(r.employee_id)

        out_shifts: list[ScheduleShift] = []
        below_total = 0
        met_cells = 0
        target_cells = 0
        targeted = 0
        night_people: set[UUID] = set()
        night_shifts = 0
        allocated = 0.0
        rostered: set[UUID] = set()

        for sh in shifts:
            start, end = timings.get(sh.id, (sh.start_time, sh.end_time))
            daily = _duration_hours(start, end)
            cells: list[ScheduleCell] = []
            dept_counts: dict[str, int] = defaultdict(int)
            peak = 0
            people_in_shift: set[UUID] = set()
            operating = 0
            below = 0
            for d in days:
                ids = by_cell.get((sh.id, d), [])
                people_in_shift.update(ids)
                peak = max(peak, len(ids))
                if ids:
                    operating += 1
                    allocated += daily * len(ids)
                met: bool | None = None
                if sh.min_staff:
                    if ids:
                        met = len(ids) >= sh.min_staff
                        target_cells += 1
                        if met:
                            met_cells += 1
                        else:
                            below += 1
                ordered = sorted(ids, key=lambda i: _full_name(employees[i][0]))
                cells.append(
                    ScheduleCell(
                        date=d,
                        count=len(ids),
                        met=met,
                        people=[
                            SchedulePerson(
                                id=i,
                                name=_full_name(employees[i][0]),
                                initials=_initials(_full_name(employees[i][0])),
                            )
                            for i in ordered[:_PEOPLE_PREVIEW]
                        ],
                        has_pending_swap=(d, sh.id) in swap_dates,
                    )
                )
            if not people_in_shift and sh.id not in timings:
                continue  # never published and nobody rostered: not part of the schedule
            for i in people_in_shift:
                dept_counts[employees[i][1] or "Unassigned"] += 1
            rostered.update(people_in_shift)
            if sh.min_staff:
                targeted += 1
            if sh.is_night_shift:
                night_people.update(people_in_shift)
                night_shifts += 1
            below_total += below
            out_shifts.append(
                ScheduleShift(
                    id=sh.id,
                    name=sh.name,
                    code=sh.code,
                    start_time=start,
                    end_time=end,
                    is_night_shift=sh.is_night_shift,
                    daily_hours=daily,
                    weekly_hours=round(daily * operating, 2),
                    min_staff=sh.min_staff,
                    peak_staff=peak,
                    departments=[
                        n for n, _ in sorted(dept_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                    ][:3],
                    days_below_target=below,
                    cells=cells,
                )
            )

        last_update = max((r.updated_at for r in roster), default=None)
        return WeeklySchedule(
            week_start=week_start,
            week_end=week_end,
            days=days,
            shifts=out_shifts,
            totals=ScheduleTotals(
                active_headcount=len(employees),
                rostered_staff=len(rostered),
                coverage_pct=round(100 * met_cells / target_cells, 1) if target_cells else None,
                shifts_with_target=targeted,
                cells_below_target=below_total,
                night_staff=len(night_people),
                night_shift_count=night_shifts,
                pending_swaps=len(pending),
                allocated_hours=round(allocated, 1),
                last_roster_update=last_update,
            ),
        )

    # -- swap requests -------------------------------------------------------------------------

    async def _party(
        self, company_id: UUID, employee_id: UUID, shift_id: UUID, on: date
    ) -> SwapParty:
        row = (
            await self._session.execute(
                select(Employee, Department.name)
                .outerjoin(
                    EmployeeAssignment,
                    (EmployeeAssignment.employee_id == Employee.id)
                    & (EmployeeAssignment.effective_to.is_(None))
                    & (EmployeeAssignment.deleted_at.is_(None)),
                )
                .outerjoin(Department, Department.id == EmployeeAssignment.department_id)
                .where(Employee.id == employee_id, Employee.company_id == company_id)
            )
        ).first()
        shift = (
            await self._session.execute(
                select(Shift).where(Shift.id == shift_id, Shift.company_id == company_id)
            )
        ).scalar_one()
        start, end = (await self._shift_timings(company_id, on)).get(
            shift_id, (shift.start_time, shift.end_time)
        )
        assert row is not None
        emp, dept = row
        return SwapParty(
            employee_id=employee_id,
            name=_full_name(emp),
            code=emp.employee_code,
            department=dept,
            shift_id=shift_id,
            shift_name=shift.name,
            shift_start=start,
            shift_end=end,
        )

    async def _coverage_ok(self, company_id: UUID, s: ShiftSwapRequest) -> bool:
        """Both shifts still meet their target on the date. A swap exchanges one person each way,
        so headcount per shift is unchanged: the check is that neither is already below target."""
        for shift_id in {s.requester_shift_id, s.counterpart_shift_id}:
            min_staff = (
                await self._session.execute(select(Shift.min_staff).where(Shift.id == shift_id))
            ).scalar_one()
            if not min_staff:
                continue
            count = (
                await self._session.execute(
                    select(func.count())
                    .select_from(ShiftRoster)
                    .where(
                        ShiftRoster.company_id == company_id,
                        ShiftRoster.shift_id == shift_id,
                        ShiftRoster.roster_date == s.swap_date,
                        ShiftRoster.status == "PUBLISHED",
                        ShiftRoster.deleted_at.is_(None),
                        ShiftRoster.is_week_off_override.is_(False),
                    )
                )
            ).scalar_one()
            if count < min_staff:
                return False
        return True

    async def _read(self, company_id: UUID, s: ShiftSwapRequest) -> SwapRequestRead:
        return SwapRequestRead(
            id=s.id,
            reference=s.reference,
            swap_date=s.swap_date,
            status=s.status,
            reason=s.reason,
            counterpart_consented=s.counterpart_consented,
            coverage_ok=await self._coverage_ok(company_id, s),
            requester=await self._party(
                company_id, s.requester_employee_id, s.requester_shift_id, s.swap_date
            ),
            counterpart=await self._party(
                company_id, s.counterpart_employee_id, s.counterpart_shift_id, s.swap_date
            ),
            created_at=s.created_at,
            decided_at=s.decided_at,
            decision_note=s.decision_note,
        )

    async def list_swaps(
        self,
        company_id: UUID,
        *,
        status: str | None,
        date_from: date | None,
        date_to: date | None,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> list[SwapRequestRead]:
        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        stmt = select(ShiftSwapRequest).where(ShiftSwapRequest.company_id == company_id)
        if status:
            stmt = stmt.where(ShiftSwapRequest.status == status)
        if date_from:
            stmt = stmt.where(ShiftSwapRequest.swap_date >= date_from)
        if date_to:
            stmt = stmt.where(ShiftSwapRequest.swap_date <= date_to)
        if visible is not None:
            stmt = stmt.where(
                ShiftSwapRequest.requester_employee_id.in_(visible or {uuid4()})
                | ShiftSwapRequest.counterpart_employee_id.in_(visible or {uuid4()})
            )
        rows = (
            (
                await self._session.execute(
                    stmt.order_by(ShiftSwapRequest.created_at.desc()).limit(100)
                )
            )
            .scalars()
            .all()
        )
        return [await self._read(company_id, r) for r in rows]

    async def _published(self, company_id: UUID, employee_id: UUID, on: date) -> ShiftRoster | None:
        return (
            await self._session.execute(
                select(ShiftRoster).where(
                    ShiftRoster.company_id == company_id,
                    ShiftRoster.employee_id == employee_id,
                    ShiftRoster.roster_date == on,
                    ShiftRoster.status == "PUBLISHED",
                    ShiftRoster.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def create_swap(
        self,
        company_id: UUID,
        body: SwapRequestCreate,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
    ) -> SwapRequestRead:
        if body.requester_employee_id == body.counterpart_employee_id:
            raise ValidationError("Choose two different employees to swap.")
        for emp_id in (body.requester_employee_id, body.counterpart_employee_id):
            await _ensure_employee_visible(
                self._session, company_id, emp_id, scope, caller_employee_id
            )
        a = await self._published(company_id, body.requester_employee_id, body.swap_date)
        b = await self._published(company_id, body.counterpart_employee_id, body.swap_date)
        if not (a and a.shift_id and not a.is_week_off_override) or not (
            b and b.shift_id and not b.is_week_off_override
        ):
            raise ValidationError("Both employees need a published shift on that date to swap.")
        if a.shift_id == b.shift_id:
            raise ValidationError("Both employees are already on the same shift that day.")
        count = (
            await self._session.execute(
                select(func.count())
                .select_from(ShiftSwapRequest)
                .where(ShiftSwapRequest.company_id == company_id)
            )
        ).scalar_one()
        swap = ShiftSwapRequest(
            id=uuid4(),
            company_id=company_id,
            reference=f"SW-{200 + count + 1}",
            swap_date=body.swap_date,
            requester_employee_id=body.requester_employee_id,
            counterpart_employee_id=body.counterpart_employee_id,
            requester_shift_id=a.shift_id,
            counterpart_shift_id=b.shift_id,
            reason=body.reason,
            status="PENDING",
            counterpart_consented=body.counterpart_consented,
        )
        self._session.add(swap)
        await self._session.flush()
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_SWAP_REQUESTED",
            entity_type="shift_swap_request",
            entity_id=swap.id,
            after={"reference": swap.reference, "swap_date": swap.swap_date.isoformat()},
        )
        return await self._read(company_id, swap)

    async def decide(
        self,
        company_id: UUID,
        swap_id: UUID,
        *,
        approve: bool,
        note: str | None,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        actor_user_id: UUID | None,
    ) -> SwapRequestRead:
        swap = (
            await self._session.execute(
                select(ShiftSwapRequest)
                .where(ShiftSwapRequest.id == swap_id, ShiftSwapRequest.company_id == company_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if swap is None:
            raise NotFoundError("Swap request not found.")
        for emp_id in (swap.requester_employee_id, swap.counterpart_employee_id):
            await _ensure_employee_visible(
                self._session, company_id, emp_id, scope, caller_employee_id
            )
        if swap.status != "PENDING":
            raise ConflictError("This swap request has already been decided.")

        now = datetime.now(UTC)
        if approve:
            await _ensure_date_open(self._session, company_id, swap.swap_date, employee_id=None)
            a = await self._published(company_id, swap.requester_employee_id, swap.swap_date)
            b = await self._published(company_id, swap.counterpart_employee_id, swap.swap_date)
            if (
                a is None
                or b is None
                or a.shift_id != swap.requester_shift_id
                or b.shift_id != swap.counterpart_shift_id
            ):
                raise ConflictError(
                    "The roster changed since this swap was requested. "
                    "Decline it and raise a new one."
                )
            a.shift_id, b.shift_id = swap.counterpart_shift_id, swap.requester_shift_id
            for r in (a, b):
                r.version += 1
                r.updated_at = now
                r.updated_by = actor_user_id
                r.reason = f"Shift swap {swap.reference}"
        swap.status = "APPROVED" if approve else "DECLINED"
        swap.decided_by = actor_user_id
        swap.decided_at = now
        swap.decision_note = note
        swap.updated_at = now
        await self._session.flush()
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_SWAP_APPROVED" if approve else "SHIFT_SWAP_DECLINED",
            entity_type="shift_swap_request",
            entity_id=swap.id,
            after={"reference": swap.reference, "status": swap.status},
        )
        return await self._read(company_id, swap)
