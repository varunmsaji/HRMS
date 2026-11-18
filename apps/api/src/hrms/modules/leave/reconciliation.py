"""AC-03 / owner decision P-E (16 Nov 2026) - approved leave follows the calendar it sits on.

A leave application's day breakdown (which dates consume leave, and how much) is decided when it
is submitted. A holiday, weekly-off pattern, work-calendar, shift or roster change made afterwards
does not rewrite it, so an approved application can:

* **over-charge**: a holiday added inside the leave - the day still debits the balance;
* **under-charge**: a holiday removed inside the leave - the day is now a working day that has no
  leave day behind it, so attendance sees an unexplained absence and loses a day's pay.

`find_discrepancies` is read-only: it re-derives each approved application's breakdown from the
current authoritative calendar and schedule (the same `_compute_day_breakdown` submit used) and
compares it with what is stored. Period close uses it to refuse to lock disagreeing inputs.

`reconcile` repairs what it finds, as decided in P-E:

* over-charge -> the day's projection is cancelled, the day row removed, and the debit refunded
  by a **new** `ADJUSTMENT` ledger entry referencing the application (never an edit);
* under-charge -> the balance is debited by a **new** `APPLICATION` entry and the day is added and
  projected, when the balance (plus the policy's negative floor, where the leave type allows a
  negative balance) covers it. Otherwise a `leave_balance_shortfall` exception is opened for HR.
  The day is **not** turned into loss of pay, and attendance period close stays blocked.

Controls. The original application, its approval and every earlier ledger entry are untouched; the
application keeps its date range. Each change is one application action, one audit row and one
notification to the employee and HR. Idempotent by state: once reconciled, a date no longer
differs, so a repeated run finds nothing and writes nothing. Dates inside a closed attendance
period (and so any finalized payroll) are never changed - they are counted as `protected` and stay
reported. Projection sync / cancel recalculates the affected attendance days. No payroll figure is
computed here.

Cross-application sandwich bridge days (R-02) are stored as sandwich days the application's own
range does not explain; they are left alone rather than treated as over-charges.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.locks import lock_attendance_period_close, lock_employee_leave_dates
from hrms.core.observability.logging import get_logger, safe_error
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.leave.exceptions import (
    LeaveApplicationCalendarNotResolvedError,
    LeaveApplicationDateRangeInvalidError,
    LeaveReconciliationPreviewStaleError,
)
from hrms.modules.leave.models import (
    LeaveApplication,
    LeaveApplicationDay,
    LeaveBalanceShortfall,
)

_logger = get_logger(__name__)

OVER_CHARGED = "OVER_CHARGED"
UNDER_CHARGED = "UNDER_CHARGED"
_ZERO = Decimal("0.00")
#: "No end": a calendar-wide change (a pattern or work-calendar edit) reaches future leave too.
FAR_FUTURE = date(9999, 12, 31)


def _full_scope() -> DataScope:
    return DataScope(levels=frozenset({DataScopeLevel.COMPANY}))


@dataclass(frozen=True, slots=True)
class LeaveCalendarDiscrepancy:
    employee_id: UUID
    application_id: UUID
    calendar_date: date
    kind: str  # OVER_CHARGED | UNDER_CHARGED
    stored_fraction: Decimal
    expected_fraction: Decimal
    reason: str
    #: the stored day was approved as loss of pay: releasing it refunds nothing (OVER_CHARGED only)
    is_lop: bool = False

    def describe(self) -> str:
        return (
            f"{self.employee_id}:{self.application_id}:{self.calendar_date.isoformat()}:"
            f"{self.kind}(charged {self.stored_fraction}, "
            f"calendar expects {self.expected_fraction})"
        )


@dataclass(slots=True)
class ReconciliationResult:
    applications_changed: int = 0
    refunded_days: Decimal = _ZERO
    debited_days: Decimal = _ZERO
    days_released: int = 0
    days_added: int = 0
    shortfalls_opened: int = 0
    shortfalls_resolved: int = 0
    #: differences on dates inside a closed attendance period: reported, never changed
    protected: list[LeaveCalendarDiscrepancy] = field(default_factory=list)


#: Outcomes a preview line can have. Only PROTECTED lines are never written.
OUTCOME_REFUND = "REFUND"  # over-charge: days returned to the balance by a new ADJUSTMENT entry
OUTCOME_RELEASE_ONLY = "RELEASE_ONLY"  # over-charge, nothing to refund (LOP day / no balance)
OUTCOME_DEBIT = "DEBIT"  # under-charge: debited by a new APPLICATION entry
OUTCOME_ADD_ONLY = "ADD_ONLY"  # under-charge on a leave type with no balance: day added only
OUTCOME_SHORTFALL = "SHORTFALL"  # under-charge the balance cannot cover: exception, never LOP
OUTCOME_PROTECTED = "PROTECTED"  # inside a closed attendance period: reported, never changed


@dataclass(frozen=True, slots=True)
class ReconciliationPreviewItem:
    employee_id: UUID
    application_id: UUID
    leave_type_id: UUID
    calendar_date: date
    kind: str
    stored_fraction: Decimal
    expected_fraction: Decimal
    outcome: str
    #: signed days on the balance: + refund, - debit, 0 when the balance is not touched
    balance_effect: Decimal
    reason: str

    def fingerprint(self) -> str:
        return (
            f"{self.application_id}|{self.calendar_date.isoformat()}|{self.kind}|"
            f"{self.stored_fraction}|{self.expected_fraction}|{self.outcome}|{self.balance_effect}"
        )


@dataclass(slots=True)
class ReconciliationPreview:
    items: list[ReconciliationPreviewItem] = field(default_factory=list)

    @property
    def actionable(self) -> list[ReconciliationPreviewItem]:
        return [i for i in self.items if i.outcome != OUTCOME_PROTECTED]

    @property
    def digest(self) -> str:
        """Identifies the exact set of changes previewed. `apply` refuses to run if the state it
        finds under its locks no longer produces the same digest."""
        lines = sorted(i.fingerprint() for i in self.items)
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()

    def total(self, outcome: str) -> Decimal:
        return sum((abs(i.balance_effect) for i in self.items if i.outcome == outcome), _ZERO)


@dataclass(slots=True)
class ReconciliationRun:
    run_id: UUID
    preview: ReconciliationPreview
    result: ReconciliationResult
    #: nothing needed changing (already reconciled, or everything is protected)
    noop: bool


class LeaveCalendarReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        from hrms.modules.leave.service import LeaveApplicationService

        self._session = session
        self._leave = LeaveApplicationService(session)

    # -- detection (read-only) -------------------------------------------------------------

    async def _approved_applications(
        self,
        company_id: UUID,
        date_from: date,
        date_to: date,
        employee_ids: frozenset[UUID] | None,
        *,
        refresh: bool = False,
    ) -> list[LeaveApplication]:
        stmt = select(LeaveApplication).where(
            LeaveApplication.company_id == company_id,
            LeaveApplication.status == "APPROVED",
            LeaveApplication.start_date <= date_to,
            LeaveApplication.end_date >= date_from,
        )
        if employee_ids is not None:
            if not employee_ids:
                return []
            stmt = stmt.where(LeaveApplication.employee_id.in_(employee_ids))
        stmt = stmt.order_by(
            LeaveApplication.employee_id, LeaveApplication.start_date, LeaveApplication.id
        )
        if refresh:
            stmt = stmt.execution_options(populate_existing=True)
        return list((await self._session.execute(stmt)).scalars().all())

    async def _application_discrepancies(
        self, company_id: UUID, application: LeaveApplication
    ) -> tuple[list[LeaveCalendarDiscrepancy], dict[date, dict[str, Any]]]:
        """This application's differences, and the breakdown the calendar expects today."""
        leave = self._leave
        stored = await leave._day_repo.list_for_application(
            self._session, company_id=company_id, leave_application_id=application.id
        )
        # R-1: an application whose every day was released has no day rows, but it is still an
        # approved leave and is rebuilt like any other - the half lives on the application. Rows
        # written before `half_day` existed fall back to the single stored day's half.
        version = await leave._policy_repo.get_version_by_id(
            self._session, company_id=company_id, version_id=application.leave_policy_version_id
        )
        half_day = application.half_day
        if half_day is None and len(stored) == 1 and application.start_date == application.end_date:
            half_day = stored[0].half
        body = SimpleNamespace(
            start_date=application.start_date, end_date=application.end_date, half_day=half_day
        )
        try:
            expected_rows = await leave._compute_day_breakdown(
                company_id,
                application.employee_id,
                body,  # type: ignore[arg-type]
                bool(version.sandwich_rule_enabled) if version is not None else False,
            )
        except LeaveApplicationDateRangeInvalidError:
            expected_rows = []  # every date is now off: nothing should be charged
        except LeaveApplicationCalendarNotResolvedError:
            return [], {}  # a calendar that does not resolve is its own blocker, not a drift
        expected = {r["date"]: r for r in expected_rows}
        stored_by_date = {d.calendar_date: d for d in stored}

        found: list[LeaveCalendarDiscrepancy] = []
        for day, row in stored_by_date.items():
            want = Decimal(expected[day]["fraction"]) if day in expected else _ZERO
            if row.is_sandwich_generated and day not in expected:
                continue  # a cross-application bridge day: not explained by this range alone
            if row.fraction > want:
                found.append(
                    LeaveCalendarDiscrepancy(
                        application.employee_id,
                        application.id,
                        day,
                        OVER_CHARGED,
                        Decimal(row.fraction),
                        want,
                        "the calendar or schedule no longer makes this a leave-consuming day",
                        bool(row.is_lop),
                    )
                )
        for day, entry in expected.items():
            existing_day = stored_by_date.get(day)
            have = Decimal(existing_day.fraction) if existing_day else _ZERO
            want = Decimal(entry["fraction"])
            if have < want:
                found.append(
                    LeaveCalendarDiscrepancy(
                        application.employee_id,
                        application.id,
                        day,
                        UNDER_CHARGED,
                        have,
                        want,
                        "the calendar or schedule now makes this a leave-consuming day "
                        "that the approved leave does not cover",
                    )
                )
        found.sort(key=lambda d: d.calendar_date)
        return found, expected

    async def find_discrepancies(
        self,
        company_id: UUID,
        *,
        date_from: date,
        date_to: date,
        employee_ids: frozenset[UUID] | None = None,
    ) -> list[LeaveCalendarDiscrepancy]:
        """Approved applications overlapping `[date_from, date_to]` whose stored days disagree
        with the breakdown the current calendar and schedule would give today. Only dates inside
        the window are reported. Writes nothing."""
        found: list[LeaveCalendarDiscrepancy] = []
        for application in await self._approved_applications(
            company_id, date_from, date_to, employee_ids
        ):
            mine, _ = await self._application_discrepancies(company_id, application)
            found.extend(d for d in mine if date_from <= d.calendar_date <= date_to)
        return found

    async def list_open_shortfalls(
        self, company_id: UUID, *, date_from: date, date_to: date
    ) -> list[LeaveBalanceShortfall]:
        stmt = (
            select(LeaveBalanceShortfall)
            .where(
                LeaveBalanceShortfall.company_id == company_id,
                LeaveBalanceShortfall.status == "OPEN",
                LeaveBalanceShortfall.calendar_date >= date_from,
                LeaveBalanceShortfall.calendar_date <= date_to,
            )
            .order_by(LeaveBalanceShortfall.calendar_date, LeaveBalanceShortfall.employee_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # -- reconciliation (writes) -----------------------------------------------------------

    async def _lock(self, company_id: UUID, applications: list[LeaveApplication]) -> None:
        """Locks first, in one order for every path: each employee's leave-dates lock (ascending
        id), then the shared side of the attendance period-close lock - the order approval and
        cancellation use, so a finalisation cannot freeze days this run is about to change.
        Advisory transaction locks are re-entrant, so taking them again is harmless."""
        for employee_id in sorted({a.employee_id for a in applications}, key=str):
            await lock_employee_leave_dates(self._session, company_id, employee_id)
        if applications:
            await lock_attendance_period_close(self._session, company_id, exclusive=False)

    async def reconcile(
        self,
        company_id: UUID,
        *,
        date_from: date,
        date_to: date,
        employee_ids: frozenset[UUID] | None = None,
        actor_user_id: UUID | None = None,
        note: str | None = None,
    ) -> ReconciliationResult:
        """Repairs every difference in the window (see the module docstring). Runs in the caller's
        transaction. Safe to repeat: a second run over the same state changes nothing. `note` is
        the HR reason of a manual run, appended to each application's timeline entry."""
        result = ReconciliationResult()
        applications = await self._approved_applications(
            company_id, date_from, date_to, employee_ids
        )
        await self._lock(company_id, applications)
        for application_id in [a.id for a in applications]:
            await self._reconcile_application(
                company_id, application_id, date_from, date_to, actor_user_id, result, note
            )
        await self._close_obsolete_shortfalls(company_id, date_from, date_to, employee_ids, result)
        return result

    async def _reconcile_application(
        self,
        company_id: UUID,
        application_id: UUID,
        date_from: date,
        date_to: date,
        actor_user_id: UUID | None,
        result: ReconciliationResult,
        note: str | None = None,
    ) -> None:
        from hrms.modules.attendance.service import AttendanceService

        leave = self._leave
        application = await leave._repo.get(
            self._session, company_id=company_id, application_id=application_id
        )
        if application is None:
            return
        # Re-read under the locks: the list above was read before they were held.
        await self._session.refresh(application)
        if application.status != "APPROVED":
            return
        found, expected = await self._application_discrepancies(company_id, application)
        found = [d for d in found if date_from <= d.calendar_date <= date_to]
        if not found:
            return
        leave_type = await leave._type_repo.get(
            self._session, company_id=company_id, leave_type_id=application.leave_type_id
        )
        requires_balance = bool(leave_type is not None and leave_type.requires_balance)
        attendance = AttendanceService(self._session)

        refunded = debited = _ZERO
        released: list[date] = []
        added: list[date] = []
        shortfalls: list[tuple[date, Decimal, Decimal]] = []
        for item in found:
            day = item.calendar_date
            if (
                await attendance.closed_period_overlapping(
                    company_id, application.employee_id, day, day
                )
                is not None
            ):
                result.protected.append(item)
                continue
            if item.kind == OVER_CHARGED:
                refunded += await self._release_day(
                    company_id, application, item, requires_balance, actor_user_id
                )
                released.append(day)
                continue
            need = item.expected_fraction - item.stored_fraction
            short_balance = await self._charge_day(
                company_id, application, item, expected[day], requires_balance, actor_user_id
            )
            if short_balance is None:
                added.append(day)
                if requires_balance:
                    debited += need
            else:
                shortfalls.append((day, need, short_balance))

        if released or added:
            await self._record_change(
                company_id, application, released, added, refunded, debited, actor_user_id, note
            )
            result.applications_changed += 1
            result.refunded_days += refunded
            result.debited_days += debited
            result.days_released += len(released)
            result.days_added += len(added)
        for day, required, available in shortfalls:
            if await self._open_shortfall(
                company_id, application, day, required, available, actor_user_id
            ):
                result.shortfalls_opened += 1
        for day in added:
            if await self._resolve_shortfall(company_id, application.id, day, "DEBITED"):
                result.shortfalls_resolved += 1

    async def _cancel_projection(
        self, company_id: UUID, projection_id: UUID | None, actor_user_id: UUID | None
    ) -> None:
        from hrms.modules.attendance.schemas import LeaveProjectionCancelInput
        from hrms.modules.attendance.service import LeaveProjectionService

        if projection_id is None:
            return
        service = LeaveProjectionService(self._session)
        projection = await service.get_projection(
            company_id, projection_id, scope=_full_scope(), caller_employee_id=None
        )
        await service.cancel(
            company_id,
            projection_id,
            LeaveProjectionCancelInput(reason="Leave reconciled after a calendar change"),
            expected_version=projection.version,
            scope=_full_scope(),
            caller_employee_id=None,
            actor_user_id=actor_user_id,
            ip_address=None,
            user_agent=None,
        )

    async def _project_day(
        self,
        company_id: UUID,
        application: LeaveApplication,
        day_id: UUID,
        day: date,
        actor_user_id: UUID | None,
    ) -> None:
        from hrms.modules.attendance.schemas import LeaveProjectionSync
        from hrms.modules.attendance.service import LeaveProjectionService

        synced = await LeaveProjectionService(self._session).sync(
            company_id,
            LeaveProjectionSync(
                employee_id=application.employee_id,
                attendance_date=day,
                leave_application_id=application.id,
            ),
            scope=_full_scope(),
            caller_employee_id=None,
            actor_user_id=actor_user_id,
            ip_address=None,
            user_agent=None,
        )
        await self._leave._day_repo.set_projection_id(
            self._session,
            company_id=company_id,
            day_id=day_id,
            leave_day_projection_id=synced.id,
            now=datetime.now(UTC),
        )

    async def _set_day_fraction(self, row: LeaveApplicationDay, fraction: Decimal) -> None:
        """Through the ORM object, so the totals read afterwards see the new fraction."""
        row.fraction = fraction
        row.leave_day_projection_id = None
        await self._session.flush()

    async def _release_day(
        self,
        company_id: UUID,
        application: LeaveApplication,
        item: LeaveCalendarDiscrepancy,
        requires_balance: bool,
        actor_user_id: UUID | None,
    ) -> Decimal:
        """Over-charge: the date consumes less leave than was charged (usually none). Returns the
        days refunded."""
        leave = self._leave
        row = await leave._day_repo.get_for_date(
            self._session,
            company_id=company_id,
            leave_application_id=application.id,
            calendar_date=item.calendar_date,
        )
        if row is None:
            return _ZERO
        was_lop = bool(row.is_lop)
        await self._cancel_projection(company_id, row.leave_day_projection_id, actor_user_id)
        if item.expected_fraction == _ZERO:
            await leave._day_repo.delete_days(
                self._session, company_id=company_id, day_ids=[row.id]
            )
        else:
            await self._set_day_fraction(row, item.expected_fraction)
            await self._project_day(
                company_id, application, row.id, item.calendar_date, actor_user_id
            )

        if was_lop or not requires_balance:
            return _ZERO  # the day never debited the balance, so there is nothing to refund
        ledger = leave._ledger_repo
        debited = -await ledger.sum_for_reference(
            self._session,
            company_id=company_id,
            employee_id=application.employee_id,
            entry_type="APPLICATION",
            reference_id=application.id,
        )
        already = await ledger.sum_refunds_for_reference(
            self._session,
            company_id=company_id,
            employee_id=application.employee_id,
            reference_id=application.id,
        )
        refund = min(item.stored_fraction - item.expected_fraction, max(debited - already, _ZERO))
        if refund <= _ZERO:
            return _ZERO
        today = await leave._business_today(company_id)
        await ledger.insert(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "employee_id": application.employee_id,
                "leave_type_id": application.leave_type_id,
                "entry_type": "ADJUSTMENT",
                "amount": refund,
                "effective_date": today,
                "reference_id": application.id,
                "reason": (
                    f"Calendar change: {item.calendar_date} is no longer a leave day for the "
                    f"leave of {application.start_date} to {application.end_date}; "
                    f"{refund} day(s) refunded"
                ),
                "created_by_user_id": actor_user_id,
            },
        )
        await leave._apply_closed_year_rule(
            company_id, application, refund, today=today, actor_user_id=actor_user_id
        )
        return refund

    async def _charge_day(
        self,
        company_id: UUID,
        application: LeaveApplication,
        item: LeaveCalendarDiscrepancy,
        expected_row: dict[str, Any],
        requires_balance: bool,
        actor_user_id: UUID | None,
    ) -> Decimal | None:
        """Under-charge: the date now consumes leave the application has not been charged for.
        Returns `None` when the day was debited and added, or the current balance when it could
        not be covered (a shortfall: nothing is written for the day)."""
        from hrms.modules.leave.service import _negative_floor

        leave = self._leave
        need = item.expected_fraction - item.stored_fraction
        if requires_balance:
            ledger = leave._ledger_repo
            await ledger.lock_balance(
                self._session,
                company_id=company_id,
                employee_id=application.employee_id,
                leave_type_id=application.leave_type_id,
            )
            balance = await ledger.get_balance(
                self._session,
                company_id=company_id,
                employee_id=application.employee_id,
                leave_type_id=application.leave_type_id,
            )
            version = await leave._policy_repo.get_version_by_id(
                self._session,
                company_id=company_id,
                version_id=application.leave_policy_version_id,
            )
            # A negative balance only where the leave policy explicitly allows one (P-E).
            if need > balance + _negative_floor(version):
                return Decimal(balance)
            await ledger.insert(
                self._session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": application.employee_id,
                    "leave_type_id": application.leave_type_id,
                    "entry_type": "APPLICATION",
                    "amount": -need,
                    "effective_date": await leave._business_today(company_id),
                    "reference_id": application.id,
                    "reason": (
                        f"Calendar change: {item.calendar_date} is now a leave day for the "
                        f"leave of {application.start_date} to {application.end_date}; "
                        f"{need} day(s) debited"
                    ),
                    "created_by_user_id": actor_user_id,
                },
            )

        existing = await leave._day_repo.get_for_date(
            self._session,
            company_id=company_id,
            leave_application_id=application.id,
            calendar_date=item.calendar_date,
        )
        if existing is None:
            day_id = uuid4()
            await leave._day_repo.insert_many(
                self._session,
                rows=[
                    {
                        "id": day_id,
                        "company_id": company_id,
                        "leave_application_id": application.id,
                        "calendar_date": item.calendar_date,
                        "fraction": item.expected_fraction,
                        "half": expected_row["half"],
                        "is_sandwich_generated": expected_row["is_sandwich_generated"],
                    }
                ],
            )
        else:
            day_id = existing.id
            await self._cancel_projection(
                company_id, existing.leave_day_projection_id, actor_user_id
            )
            await self._set_day_fraction(existing, item.expected_fraction)
        await self._project_day(company_id, application, day_id, item.calendar_date, actor_user_id)
        return None

    async def _recipients(self, company_id: UUID, employee_id: UUID) -> list[UUID | None]:
        """The employee, and HR (company-wide leave approvers)."""
        from hrms.modules.leave.permissions import LEAVE_APPLICATION_APPROVE
        from hrms.modules.notification.producer import (
            employee_user_id,
            permission_holder_user_ids,
        )

        return [
            await employee_user_id(self._session, company_id, employee_id),
            *await permission_holder_user_ids(self._session, company_id, LEAVE_APPLICATION_APPROVE),
        ]

    async def _record_change(
        self,
        company_id: UUID,
        application: LeaveApplication,
        released: list[date],
        added: list[date],
        refunded: Decimal,
        debited: Decimal,
        actor_user_id: UUID | None,
        note: str | None = None,
    ) -> None:
        """Totals, timeline, audit and notifications for one application's reconciliation. The
        application keeps its status, its approval and its original date range."""
        from hrms.modules.notification.approvals import fmt_date
        from hrms.modules.notification.producer import notify
        from hrms.modules.notification.types import LEAVE_BALANCE_RECONCILED

        leave = self._leave
        before = {"total_days": str(application.total_days), "lop_days": str(application.lop_days)}
        start_date, end_date = application.start_date, application.end_date
        employee_id = application.employee_id
        days = await leave._day_repo.list_for_application(
            self._session, company_id=company_id, leave_application_id=application.id
        )
        total = sum((d.fraction for d in days), _ZERO)
        lop = sum((d.fraction for d in days if d.is_lop), _ZERO)
        await leave._repo.shrink_after_release(  # totals only: the date range is kept
            self._session,
            company_id=company_id,
            application_id=application.id,
            start_date=start_date,
            end_date=end_date,
            total_days=total,
            lop_days=lop,
            now=datetime.now(UTC),
        )
        parts: list[str] = []
        if released:
            parts.append(
                f"{', '.join(fmt_date(d) for d in released)} no longer a leave day"
                f" ({refunded} day(s) refunded)"
            )
        if added:
            parts.append(
                f"{', '.join(fmt_date(d) for d in added)} now a leave day"
                f" ({debited} day(s) debited)"
            )
        comment = "Calendar change: " + "; ".join(parts)
        if note:
            comment += f" (HR reconciliation: {note})"
        await leave._record_action(
            company_id=company_id,
            leave_application_id=application.id,
            action="CALENDAR_RECONCILED",
            actor_user_id=actor_user_id,
            actor_employee_id=None,
            stage=None,
            comment=comment,
        )
        await leave._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_APPLICATION_CALENDAR_RECONCILED",
            entity_type="leave_application",
            entity_id=application.id,
            before=before,
            after={
                "total_days": str(total),
                "lop_days": str(lop),
                "released_dates": [d.isoformat() for d in released],
                "added_dates": [d.isoformat() for d in added],
                "refunded_days": str(refunded),
                "debited_days": str(debited),
            },
        )
        await notify(
            self._session,
            company_id=company_id,
            recipients=await self._recipients(company_id, employee_id),
            type=LEAVE_BALANCE_RECONCILED,
            title="Leave balance adjusted after a calendar change",
            body=comment,
            # One notification per actual change: state-based idempotency means a repeated run
            # never reaches this point, so the key only has to be unique per change.
            dedupe_key=f"leave-reconciled:{application.id}:{uuid4()}",
            entity_type="leave_application",
            entity_id=application.id,
            action_url="/app/leave-applications",
        )

    # -- HR-initiated reconciliation (R-3): preview, then apply what was previewed ---------

    async def preview(
        self,
        company_id: UUID,
        *,
        date_from: date,
        date_to: date,
        employee_ids: frozenset[UUID] | None = None,
    ) -> ReconciliationPreview:
        """What `reconcile` would do over this window, line by line, with the balance effect of
        each. Writes nothing. The balance forecast follows the order `reconcile` works in, so it
        matches the run unless the state changes in between - which `apply_reviewed` detects."""
        applications = await self._approved_applications(
            company_id, date_from, date_to, employee_ids
        )
        return await self._build_preview(company_id, applications, date_from, date_to)

    async def _build_preview(
        self,
        company_id: UUID,
        applications: list[LeaveApplication],
        date_from: date,
        date_to: date,
    ) -> ReconciliationPreview:
        from hrms.modules.attendance.service import AttendanceService
        from hrms.modules.leave.service import _negative_floor

        leave = self._leave
        attendance = AttendanceService(self._session)
        preview = ReconciliationPreview()
        balances: dict[tuple[UUID, UUID], Decimal] = {}
        for application in applications:
            found, _ = await self._application_discrepancies(company_id, application)
            found = [d for d in found if date_from <= d.calendar_date <= date_to]
            if not found:
                continue
            leave_type = await leave._type_repo.get(
                self._session, company_id=company_id, leave_type_id=application.leave_type_id
            )
            requires_balance = bool(leave_type is not None and leave_type.requires_balance)
            version = await leave._policy_repo.get_version_by_id(
                self._session,
                company_id=company_id,
                version_id=application.leave_policy_version_id,
            )
            floor = _negative_floor(version)
            key = (application.employee_id, application.leave_type_id)
            refundable = _ZERO
            if requires_balance:
                if key not in balances:
                    balances[key] = Decimal(
                        await leave._ledger_repo.get_balance(
                            self._session,
                            company_id=company_id,
                            employee_id=application.employee_id,
                            leave_type_id=application.leave_type_id,
                        )
                    )
                debited = -await leave._ledger_repo.sum_for_reference(
                    self._session,
                    company_id=company_id,
                    employee_id=application.employee_id,
                    entry_type="APPLICATION",
                    reference_id=application.id,
                )
                already = await leave._ledger_repo.sum_refunds_for_reference(
                    self._session,
                    company_id=company_id,
                    employee_id=application.employee_id,
                    reference_id=application.id,
                )
                refundable = max(debited - already, _ZERO)
            for item in found:
                outcome, effect = OUTCOME_PROTECTED, _ZERO
                protected = (
                    await attendance.closed_period_overlapping(
                        company_id, application.employee_id, item.calendar_date, item.calendar_date
                    )
                    is not None
                )
                if protected:
                    pass
                elif item.kind == OVER_CHARGED:
                    refund = _ZERO
                    if requires_balance and not item.is_lop:
                        refund = min(item.stored_fraction - item.expected_fraction, refundable)
                    if refund > _ZERO:
                        refundable -= refund
                        balances[key] += refund
                        outcome, effect = OUTCOME_REFUND, refund
                    else:
                        outcome = OUTCOME_RELEASE_ONLY
                else:
                    need = item.expected_fraction - item.stored_fraction
                    if not requires_balance:
                        outcome = OUTCOME_ADD_ONLY
                    elif need <= balances[key] + floor:
                        balances[key] -= need
                        outcome, effect = OUTCOME_DEBIT, -need
                    else:
                        outcome = OUTCOME_SHORTFALL
                preview.items.append(
                    ReconciliationPreviewItem(
                        employee_id=application.employee_id,
                        application_id=application.id,
                        leave_type_id=application.leave_type_id,
                        calendar_date=item.calendar_date,
                        kind=item.kind,
                        stored_fraction=item.stored_fraction,
                        expected_fraction=item.expected_fraction,
                        outcome=outcome,
                        balance_effect=effect,
                        reason=item.reason,
                    )
                )
        return preview

    async def apply_reviewed(
        self,
        company_id: UUID,
        *,
        date_from: date,
        date_to: date,
        employee_ids: frozenset[UUID] | None,
        preview_digest: str,
        reason: str,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ReconciliationRun:
        """Applies exactly what a reviewer previewed. Takes the locks first, re-derives the
        preview from the state it finds under them, and refuses (409) if that no longer matches
        `preview_digest` - nothing is written then. When there is nothing left to do (a repeat of
        a run that already worked, or only closed-period dates remain) it changes nothing and
        reports `noop` whatever the digest. Everything runs in the caller's transaction: any
        failure rolls the whole run back, balance, days, projections and audit alike."""
        applications = await self._approved_applications(
            company_id, date_from, date_to, employee_ids
        )
        await self._lock(company_id, applications)
        # Re-read under the locks, overwriting anything loaded before them.
        applications = await self._approved_applications(
            company_id, date_from, date_to, employee_ids, refresh=True
        )
        preview = await self._build_preview(company_id, applications, date_from, date_to)
        run_id = uuid4()
        if preview.actionable and preview.digest != preview_digest:
            raise LeaveReconciliationPreviewStaleError()
        result = ReconciliationResult()
        noop = not preview.actionable
        if not noop:
            result = await self.reconcile(
                company_id,
                date_from=date_from,
                date_to=date_to,
                employee_ids=employee_ids,
                actor_user_id=actor_user_id,
                note=reason,
            )
        else:
            result.protected = []
        await self._leave._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_CALENDAR_RECONCILIATION_RUN",
            entity_type="leave_reconciliation",
            entity_id=run_id,
            after={
                "reason": reason,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "employee_ids": sorted(str(e) for e in employee_ids) if employee_ids else None,
                "preview_digest": preview_digest,
                "noop": noop,
                "applications_changed": result.applications_changed,
                "refunded_days": str(result.refunded_days),
                "debited_days": str(result.debited_days),
                "days_released": result.days_released,
                "days_added": result.days_added,
                "shortfalls_opened": result.shortfalls_opened,
                "protected": sum(1 for i in preview.items if i.outcome == OUTCOME_PROTECTED),
            },
            ip=ip_address,
            user_agent=user_agent,
        )
        return ReconciliationRun(run_id=run_id, preview=preview, result=result, noop=noop)

    # -- shortfall exceptions --------------------------------------------------------------

    async def _get_shortfall(
        self, company_id: UUID, application_id: UUID, day: date
    ) -> LeaveBalanceShortfall | None:
        stmt = select(LeaveBalanceShortfall).where(
            LeaveBalanceShortfall.company_id == company_id,
            LeaveBalanceShortfall.leave_application_id == application_id,
            LeaveBalanceShortfall.calendar_date == day,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _open_shortfall(
        self,
        company_id: UUID,
        application: LeaveApplication,
        day: date,
        required: Decimal,
        available: Decimal,
        actor_user_id: UUID | None,
    ) -> bool:
        """Opens (or reopens) the exception for this application-date. Returns False when it was
        already open - then only its figures are refreshed, with no new timeline entry or
        notification, so a repeated run stays quiet."""
        from hrms.modules.notification.approvals import fmt_date
        from hrms.modules.notification.producer import notify
        from hrms.modules.notification.types import LEAVE_BALANCE_SHORTFALL

        now = datetime.now(UTC)
        row = await self._get_shortfall(company_id, application.id, day)
        if row is not None and row.status == "OPEN":
            row.required_fraction = required
            row.available_balance = available
            await self._session.flush()
            return False
        if row is None:
            row = LeaveBalanceShortfall(
                id=uuid4(),
                company_id=company_id,
                employee_id=application.employee_id,
                leave_application_id=application.id,
                leave_type_id=application.leave_type_id,
                calendar_date=day,
                required_fraction=required,
                available_balance=available,
                status="OPEN",
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.status = "OPEN"
            row.resolution = None
            row.resolved_at = None
            row.required_fraction = required
            row.available_balance = available
        await self._session.flush()
        shortfall_id = row.id

        comment = (
            f"Calendar change: {fmt_date(day)} is now a leave day, but the balance "
            f"({available}) does not cover {required} day(s). Not debited and not converted to "
            "loss of pay; HR must resolve it before the attendance period can be finalized."
        )
        leave = self._leave
        await leave._record_action(
            company_id=company_id,
            leave_application_id=application.id,
            action="BALANCE_SHORTFALL",
            actor_user_id=actor_user_id,
            actor_employee_id=None,
            stage=None,
            comment=comment,
        )
        await leave._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEAVE_BALANCE_SHORTFALL_OPENED",
            entity_type="leave_application",
            entity_id=application.id,
            after={
                "calendar_date": day.isoformat(),
                "required_fraction": str(required),
                "available_balance": str(available),
            },
        )
        await notify(
            self._session,
            company_id=company_id,
            recipients=await self._recipients(company_id, application.employee_id),
            type=LEAVE_BALANCE_SHORTFALL,
            title="Leave balance shortfall after a calendar change",
            body=comment,
            dedupe_key=f"leave-shortfall:{shortfall_id}:{uuid4()}",
            entity_type="leave_application",
            entity_id=application.id,
            action_url="/app/leave-applications",
        )
        return True

    async def _resolve_shortfall(
        self, company_id: UUID, application_id: UUID, day: date, resolution: str
    ) -> bool:
        row = await self._get_shortfall(company_id, application_id, day)
        if row is None or row.status != "OPEN":
            return False
        row.status = "RESOLVED"
        row.resolution = resolution
        row.resolved_at = datetime.now(UTC)
        await self._session.flush()
        await self._leave._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=None,
            action="LEAVE_BALANCE_SHORTFALL_RESOLVED",
            entity_type="leave_application",
            entity_id=application_id,
            after={"calendar_date": day.isoformat(), "resolution": resolution},
        )
        return True

    async def _close_obsolete_shortfalls(
        self,
        company_id: UUID,
        date_from: date,
        date_to: date,
        employee_ids: frozenset[UUID] | None,
        result: ReconciliationResult,
    ) -> None:
        """An open exception whose date is no longer under-charged - the calendar change was
        undone, or the leave was cancelled or rejected - has nothing left to resolve."""
        for row in await self.list_open_shortfalls(
            company_id, date_from=date_from, date_to=date_to
        ):
            if employee_ids is not None and row.employee_id not in employee_ids:
                continue
            application_id, day = row.leave_application_id, row.calendar_date
            application = await self._leave._repo.get(
                self._session, company_id=company_id, application_id=application_id
            )
            still_short = False
            if application is not None and application.status == "APPROVED":
                found, _ = await self._application_discrepancies(company_id, application)
                still_short = any(d.kind == UNDER_CHARGED and d.calendar_date == day for d in found)
            if not still_short and await self._resolve_shortfall(
                company_id, application_id, day, "NO_LONGER_REQUIRED"
            ):
                result.shortfalls_resolved += 1


async def reconcile_after_calendar_change(
    session: AsyncSession,
    *,
    company_id: UUID,
    dates: list[tuple[date, date]] | None,
    actor_user_id: UUID | None,
) -> None:
    """Called from every *dated* calendar mutation (holiday, calendar exception), in its
    transaction (P-E: automatic). Dates in closed periods are protected inside `reconcile`.

    Runs in a SAVEPOINT and never fails the calendar change itself: if reconciliation cannot
    complete, nothing of it is written, the failure is logged, and the difference stays visible
    to - and blocks - attendance period close (`LEAVE_CALENDAR_MISMATCH`)."""
    ranges = dates if dates is not None else [(date(1900, 1, 1), FAR_FUTURE)]
    try:
        async with session.begin_nested():
            service = LeaveCalendarReconciliationService(session)
            for date_from, date_to in ranges:
                await service.reconcile(
                    company_id, date_from=date_from, date_to=date_to, actor_user_id=actor_user_id
                )
    except Exception as exc:  # noqa: BLE001 - the calendar change must stand; close still blocks
        _logger.warning(
            "leave_calendar_reconciliation_failed",
            company_id=str(company_id),
            error=safe_error(exc),
        )
