"""Punch ownership with I/O (Invariant B): resolves each candidate day's claim from the shared work
schedule and that day's attendance policy, loads the punches, and applies `punch_ownership`.

The day being calculated is compared with its two neighbours on each side. Every day reachable
from a punch near D is in that set, so the owner a punch gets does not depend on which day is
asking: D's calculation and D+1's calculation reach the same answer for every punch they share.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.attendance import calculation as calc
from hrms.modules.attendance.models import PunchDismissal
from hrms.modules.attendance.punch_ownership import (
    DayClaim,
    assign_owners,
    calendar_day_claim,
    ownership_span,
    shift_claim,
)
from hrms.modules.attendance.repository import AttendancePolicyRepository, PunchRepository
from hrms.modules.attendance.resolution import PolicyResolutionService
from hrms.modules.attendance.work_schedule import WorkScheduleResolver

#: Neighbouring dates on each side whose claims are compared with the target date's.
NEIGHBOUR_DAYS = 2
#: Defaults when no attendance policy resolves for a date (the migration's column defaults).
DEFAULT_MAX_EARLY_PUNCH_MINUTES = 240
DEFAULT_MAX_LATE_PUNCH_MINUTES = 720
#: Folding window for exact resubmissions when building sessions. Fixed (not the per-day
#: policy value) so every day groups the same punches the same way.
OWNERSHIP_DUPLICATE_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class OwnedPunches:
    claim: DayClaim | None
    punches: list[calc.PunchData]
    #: Punches loaded for comparison that belong to no day (shown on the orphan report).
    orphan_ids: list[UUID]


@dataclass
class PunchOwnershipService:
    session: AsyncSession
    resolver: WorkScheduleResolver | None = None
    _claims: dict[tuple[UUID, UUID, date], DayClaim | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.resolver is None:
            self.resolver = WorkScheduleResolver(self.session)

    async def _punch_limits(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> tuple[int, int]:
        resolution = await PolicyResolutionService(self.session).resolve(
            company_id, "ATTENDANCE_POLICY", employee_id=employee_id, target_date=target_date
        )
        if (
            resolution.config_incomplete
            or resolution.resolved_policy_id is None
            or resolution.resolved_version_id is None
        ):
            return DEFAULT_MAX_EARLY_PUNCH_MINUTES, DEFAULT_MAX_LATE_PUNCH_MINUTES
        version = await AttendancePolicyRepository().get_version(
            self.session,
            company_id=company_id,
            policy_id=resolution.resolved_policy_id,
            version_id=resolution.resolved_version_id,
        )
        if version is None:
            return DEFAULT_MAX_EARLY_PUNCH_MINUTES, DEFAULT_MAX_LATE_PUNCH_MINUTES
        return version.max_early_punch_minutes, version.max_late_punch_minutes

    async def claim_for(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> DayClaim | None:
        """The date's claim, or None when the employee is not employed that day (such a day
        never owns a punch)."""
        key = (company_id, employee_id, target_date)
        if key in self._claims:
            return self._claims[key]
        from hrms.modules.employee.service import EmploymentService

        claim: DayClaim | None = None
        employment = await EmploymentService(self.session).get_employment_as_of(
            company_id, employee_id, target_date
        )
        if employment is not None:
            assert self.resolver is not None
            resolved = await self.resolver.resolve(company_id, employee_id, target_date)
            schedule = resolved.schedule
            span = ownership_span(schedule.shift_inputs, schedule.window)
            if span is not None:
                before, after = await self._punch_limits(company_id, employee_id, target_date)
                claim = shift_claim(
                    target_date, span, max_early_minutes=before, max_late_minutes=after
                )
            else:
                day_start, day_end = calc.calendar_day_window_utc(
                    attendance_date=target_date, tz_name=schedule.tz_name
                )
                claim = calendar_day_claim(target_date, day_start, day_end)
        self._claims[key] = claim
        return claim

    async def claims_around(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> list[DayClaim]:
        claims: list[DayClaim] = []
        for offset in range(-NEIGHBOUR_DAYS, NEIGHBOUR_DAYS + 1):
            claim = await self.claim_for(
                company_id, employee_id, target_date + timedelta(days=offset)
            )
            if claim is not None:
                claims.append(claim)
        return claims

    async def _load(
        self, company_id: UUID, employee_id: UUID, claims: list[DayClaim]
    ) -> list[calc.PunchData]:
        if not claims:
            return []
        start = min(c.window_start for c in claims)
        end = max(c.window_end for c in claims)
        rows = await PunchRepository().list_for_employee_window(
            self.session,
            company_id=company_id,
            employee_id=employee_id,
            window_start=start,
            window_end=end,
        )
        dismissed = await self._dismissed_ids(company_id, [r.id for r in rows])
        return [
            calc.PunchData(id=r.id, punch_time=r.punch_time, direction=r.direction)
            for r in rows
            if r.id not in dismissed
        ]

    async def _dismissed_ids(self, company_id: UUID, punch_ids: list[UUID]) -> set[UUID]:
        if not punch_ids:
            return set()
        stmt = select(PunchDismissal.punch_id).where(
            PunchDismissal.company_id == company_id, PunchDismissal.punch_id.in_(punch_ids)
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def owned_punches(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> OwnedPunches:
        claims = await self.claims_around(company_id, employee_id, target_date)
        own = next((c for c in claims if c.attendance_date == target_date), None)
        if own is None:
            return OwnedPunches(claim=None, punches=[], orphan_ids=[])
        punches = await self._load(company_id, employee_id, claims)
        owners = assign_owners(
            punches, claims, duplicate_window_seconds=OWNERSHIP_DUPLICATE_WINDOW_SECONDS
        )
        return OwnedPunches(
            claim=own,
            punches=[p for p in punches if owners.get(p.id) == target_date],
            orphan_ids=[p.id for p in punches if owners.get(p.id) is None],
        )

    async def owners_near(
        self, company_id: UUID, employee_id: UUID, local_date: date
    ) -> dict[UUID, date | None]:
        """Owners of every non-dismissed punch near `local_date`, for callers that start from a
        punch (immediate recalculation, the last-working-day check, the orphan report)."""
        claims = await self.claims_around(company_id, employee_id, local_date)
        punches = await self._load(company_id, employee_id, claims)
        return assign_owners(
            punches, claims, duplicate_window_seconds=OWNERSHIP_DUPLICATE_WINDOW_SECONDS
        )

    async def claimed_by(
        self,
        company_id: UUID,
        employee_id: UUID,
        instant: datetime,
        candidates: list[date],
        *,
        direction: str,
    ) -> date | None:
        """The first candidate date that could own a punch at `instant` — a check for a punch not
        yet written, so it is judged as a lone punch: inside the date's ownership window, and an
        IN no later than the shift's end, an OUT no earlier than its start."""
        for target in candidates:
            claim = await self.claim_for(company_id, employee_id, target)
            if claim is None or not (claim.window_start <= instant < claim.window_end):
                continue
            if claim.has_shift:
                assert claim.span_start is not None and claim.span_end is not None
                if direction == "IN" and instant > claim.span_end:
                    continue
                if direction == "OUT" and instant < claim.span_start:
                    continue
            return target
        return None
