"""Server-side geofence enforcement for self-service punches, and its admin surface.

`GeofenceService.enforce` is the only place a punch location is judged. It resolves the policy and
the applicable workplaces from trusted server data (the authenticated employee's assignment,
administrator-created authorisations, the published policy version) and never reads a company,
employee, workplace or threshold from the client. See `geofence.py` for the decision rules and the
limits of what a device-reported position proves."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.db.session import session_scope
from hrms.core.errors.base import NotFoundError, ValidationError
from hrms.core.observability.security_events import security_event
from hrms.core.rbac.types import DataScope
from hrms.modules.attendance.exceptions import (
    GeofenceRejectedError,
    WorkplaceAuthorizationExistsError,
)
from hrms.modules.attendance.geofence import (
    GeofenceDecision,
    GeofencePolicy,
    ReportedLocation,
    Workplace,
    decide,
    round_coordinate,
)
from hrms.modules.attendance.geofence_repository import GeofenceRepository
from hrms.modules.attendance.geofence_schemas import GeofenceWorkplaceRead
from hrms.modules.attendance.models import EmployeeWorkplaceAuthorization, GeofenceAttempt
from hrms.modules.attendance.repository import AttendancePolicyRepository
from hrms.modules.attendance.resolution import PolicyResolutionService
from hrms.modules.attendance.schemas import GeofenceDecisionRead, PunchLocation

_DISABLED = GeofencePolicy(mode="DISABLED", max_accuracy_m=100, max_age_seconds=60)

#: Sources that are self-service punches and therefore geofenced. `ADMIN` (HR on behalf) and
#: `REGULARIZATION` are corrections by an authorised person and are never location-checked.
GEOFENCED_SOURCES = frozenset({"WEB", "FACE"})


class GeofenceEvaluation:
    """Result of `enforce`: the policy in force, the decision, and the workplace name (for the
    response only — never persisted as text)."""

    __slots__ = ("decision", "policy", "workplace_name")

    def __init__(
        self, policy: GeofencePolicy, decision: GeofenceDecision, workplace_name: str | None
    ) -> None:
        self.policy = policy
        self.decision = decision
        self.workplace_name = workplace_name

    @property
    def active(self) -> bool:
        return self.policy.mode != "DISABLED"

    def to_read(self) -> GeofenceDecisionRead | None:
        if not self.active:
            return None
        d = self.decision
        return GeofenceDecisionRead(
            mode=self.policy.mode,
            outcome=d.outcome,
            accepted=d.allowed,
            workplace_name=self.workplace_name,
            distance_m=d.distance_m,
            radius_m=d.radius_m,
            accuracy_m=d.accuracy_m,
        )


class GeofenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = GeofenceRepository()
        self._audit = AuditService()

    # -- trusted inputs ----------------------------------------------------------------------

    async def resolve_policy(
        self, company_id: UUID, employee_id: UUID, today: datetime
    ) -> GeofencePolicy:
        """The geofence settings of the employee's resolved attendance policy version. No policy
        (incomplete configuration) means DISABLED — punching behaves exactly as before. The
        lookup date is the UTC calendar date of the punch, the same documented approximation the
        rest of the punch path uses before shift resolution (WD-30)."""
        resolution = await PolicyResolutionService(self._session).resolve(
            company_id, "ATTENDANCE_POLICY", employee_id=employee_id, target_date=today.date()
        )
        if (
            resolution.config_incomplete
            or resolution.resolved_policy_id is None
            or resolution.resolved_version_id is None
        ):
            return _DISABLED
        version = await AttendancePolicyRepository().get_version(
            self._session,
            company_id=company_id,
            policy_id=resolution.resolved_policy_id,
            version_id=resolution.resolved_version_id,
        )
        if version is None:
            return _DISABLED
        return GeofencePolicy(
            mode=version.geofence_mode,
            max_accuracy_m=version.geofence_max_accuracy_m,
            max_age_seconds=version.geofence_max_age_seconds,
        )

    async def resolve_workplaces(
        self, company_id: UUID, employee_id: UUID, today: datetime
    ) -> list[Workplace]:
        """Active, same-company branches with a complete geofence that apply to this employee:
        the branch on their assignment plus administrator-granted extras. Never client-chosen."""
        from hrms.modules.employee.service import EmployeeAssignmentService
        from hrms.modules.organisation.models import Branch

        branch_ids: set[UUID] = set(
            await self._repo.authorized_branch_ids(
                self._session, company_id=company_id, employee_id=employee_id
            )
        )
        assignment = await EmployeeAssignmentService(self._session).get_assignment_as_of(
            company_id, employee_id, today.date()
        )
        if assignment is not None and assignment.branch_id is not None:
            branch_ids.add(assignment.branch_id)
        if not branch_ids:
            return []
        rows = (
            await self._session.execute(
                select(Branch).where(
                    Branch.company_id == company_id,
                    Branch.id.in_(branch_ids),
                    Branch.is_active.is_(True),
                    Branch.deleted_at.is_(None),
                    Branch.latitude.is_not(None),
                    Branch.longitude.is_not(None),
                    Branch.geofence_radius_m.is_not(None),
                )
            )
        ).scalars()
        workplaces: list[Workplace] = []
        for b in rows:
            # The query above already excludes rows with missing coordinates/radius; the checks
            # make that invariant explicit for the type checker and for any future query change.
            if b.latitude is None or b.longitude is None or b.geofence_radius_m is None:
                continue
            workplaces.append(
                Workplace(
                    branch_id=b.id,
                    name=b.name,
                    latitude=float(b.latitude),
                    longitude=float(b.longitude),
                    radius_m=float(b.geofence_radius_m),
                )
            )
        return workplaces

    # -- decision ----------------------------------------------------------------------------

    async def evaluate(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        location: PunchLocation | None,
        location_error: str | None,
        now: datetime | None = None,
    ) -> GeofenceEvaluation:
        now = now or datetime.now(UTC)
        policy = await self.resolve_policy(company_id, employee_id, now)
        if policy.mode == "DISABLED":
            return GeofenceEvaluation(
                policy,
                decide(policy=policy, location=None, client_error=None, workplaces=[], now=now),
                None,
            )
        workplaces = await self.resolve_workplaces(company_id, employee_id, now)
        reported = (
            ReportedLocation(
                latitude=location.latitude,
                longitude=location.longitude,
                accuracy_m=location.accuracy_m,
                captured_at=location.captured_at,
            )
            if location is not None
            else None
        )
        decision = decide(
            policy=policy,
            location=reported,
            client_error=location_error,
            workplaces=workplaces,
            now=now,
        )
        names = {w.branch_id: w.name for w in workplaces}
        name = names.get(decision.branch_id) if decision.branch_id is not None else None
        return GeofenceEvaluation(policy, decision, name)

    def _attempt_data(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        direction: str,
        source: str,
        evaluation: GeofenceEvaluation,
        location: PunchLocation | None,
        location_error: str | None,
        punch_id: UUID | None,
        now: datetime,
    ) -> dict[str, Any]:
        d = evaluation.decision
        return {
            "id": uuid4(),
            "company_id": company_id,
            "employee_id": employee_id,
            "punch_id": punch_id,
            "direction": direction,
            "source": source,
            "mode": evaluation.policy.mode,
            "outcome": d.outcome,
            "accepted": d.allowed,
            "branch_id": d.branch_id,
            "distance_m": d.distance_m,
            "radius_m": d.radius_m,
            "accuracy_m": d.accuracy_m,
            # Rounded to ~11 m; kept only so HR can review a dispute (see GeofenceAttempt).
            "latitude": round_coordinate(location.latitude) if location else None,
            "longitude": round_coordinate(location.longitude) if location else None,
            "captured_at": location.captured_at if location else None,
            "client_error": location_error,
            "created_at": now,
        }

    async def enforce(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        direction: str,
        source: str,
        location: PunchLocation | None,
        location_error: str | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> GeofenceEvaluation:
        """Judge the punch location. Returns the evaluation when the punch may proceed; raises
        `GeofenceRejectedError` otherwise, after recording the rejected attempt and an audit event
        in their own transaction (the request transaction rolls back with the error). A rejected
        attempt never creates a punch."""
        now = datetime.now(UTC)
        evaluation = await self.evaluate(
            company_id, employee_id, location=location, location_error=location_error, now=now
        )
        if evaluation.decision.allowed:
            return evaluation

        d = evaluation.decision
        attempt = self._attempt_data(
            company_id,
            employee_id,
            direction=direction,
            source=source,
            evaluation=evaluation,
            location=location,
            location_error=location_error,
            punch_id=None,
            now=now,
        )
        async with session_scope(company_id=str(company_id)) as audit_session:
            await self._repo.insert_attempt(audit_session, data=attempt)
            await self._audit.record(
                audit_session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="PUNCH_REJECTED_GEOFENCE",
                entity_type="employee",
                entity_id=employee_id,
                after={
                    "reason": d.outcome,
                    "direction": direction,
                    "source": source,
                    "distance_m": d.distance_m,
                    "radius_m": d.radius_m,
                    "accuracy_m": d.accuracy_m,
                    "attempt_id": str(attempt["id"]),
                },
                ip=ip_address,
                user_agent=user_agent,
            )
        security_event(
            "punch.rejected",
            level="warning",
            reason=d.outcome,
            company_id=str(company_id),
            employee_id=str(employee_id),
        )
        raise GeofenceRejectedError(
            d.outcome,
            distance_m=d.distance_m,
            radius_m=d.radius_m,
            accuracy_m=d.accuracy_m,
            workplace_name=evaluation.workplace_name,
        )

    async def record_accepted(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        direction: str,
        source: str,
        evaluation: GeofenceEvaluation,
        location: PunchLocation | None,
        location_error: str | None,
        punch_id: UUID,
    ) -> None:
        """Persist the evaluation next to the punch it allowed (same transaction). A no-op when
        the policy is DISABLED. Under OPTIONAL this also records non-INSIDE outcomes that did not
        block, so HR can see what REQUIRED would have done before turning it on."""
        if not evaluation.active:
            return
        await self._repo.insert_attempt(
            self._session,
            data=self._attempt_data(
                company_id,
                employee_id,
                direction=direction,
                source=source,
                evaluation=evaluation,
                location=location,
                location_error=location_error,
                punch_id=punch_id,
                now=datetime.now(UTC),
            ),
        )

    # -- admin: extra workplace authorisations ------------------------------------------------

    async def add_authorization(
        self,
        company_id: UUID,
        *,
        employee_id: UUID,
        branch_id: UUID,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeWorkplaceAuthorization:
        from hrms.modules.employee.models import Employee
        from hrms.modules.organisation.models import Branch

        employee = (
            await self._session.execute(
                select(Employee.id).where(
                    Employee.company_id == company_id, Employee.id == employee_id
                )
            )
        ).scalar_one_or_none()
        if employee is None:
            raise NotFoundError("Employee not found")
        branch = (
            await self._session.execute(
                select(Branch).where(
                    Branch.company_id == company_id,
                    Branch.id == branch_id,
                    Branch.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if branch is None:
            raise NotFoundError("Workplace not found")
        if (
            not branch.is_active
            or branch.latitude is None
            or branch.longitude is None
            or branch.geofence_radius_m is None
        ):
            raise ValidationError(
                "The workplace must be active and have coordinates and a radius configured"
            )
        try:
            async with self._session.begin_nested():
                row = await self._repo.insert_authorization(
                    self._session,
                    data={
                        "id": uuid4(),
                        "company_id": company_id,
                        "employee_id": employee_id,
                        "branch_id": branch_id,
                        "created_by_user_id": actor_user_id,
                    },
                )
        except IntegrityError as exc:
            raise WorkplaceAuthorizationExistsError() from exc
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="WORKPLACE_AUTHORIZATION_ADDED",
            entity_type="employee",
            entity_id=employee_id,
            after={"branch_id": str(branch_id), "authorization_id": str(row.id)},
            ip=ip_address,
            user_agent=user_agent,
        )
        return row

    async def remove_authorization(
        self,
        company_id: UUID,
        authorization_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        row = await self._repo.get_authorization(
            self._session, company_id=company_id, authorization_id=authorization_id
        )
        if row is None:
            raise NotFoundError("Authorization not found")
        await self._repo.delete_authorization(
            self._session, company_id=company_id, authorization_id=authorization_id
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="WORKPLACE_AUTHORIZATION_REMOVED",
            entity_type="employee",
            entity_id=row.employee_id,
            before={"branch_id": str(row.branch_id), "authorization_id": str(row.id)},
            ip=ip_address,
            user_agent=user_agent,
        )

    async def purge_expired_attempts(self, company_id: UUID, retention_days: int) -> int:
        """Delete attempt rows older than the retention window; returns the number removed."""
        if retention_days < 1:
            raise ValidationError("retention_days must be at least 1")
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        return await self._repo.purge_attempts_before(
            self._session, company_id=company_id, cutoff=cutoff
        )

    # -- admin: reads -----------------------------------------------------------------------

    async def list_workplaces(self, company_id: UUID) -> list[GeofenceWorkplaceRead]:
        from sqlalchemy import func

        from hrms.modules.employee.models import EmployeeAssignment
        from hrms.modules.organisation.models import Branch

        today = datetime.now(UTC).date()
        branches = (
            (
                await self._session.execute(
                    select(Branch)
                    .where(Branch.company_id == company_id, Branch.deleted_at.is_(None))
                    .order_by(Branch.name, Branch.id)
                )
            )
            .scalars()
            .all()
        )
        assigned: dict[UUID, int] = {
            branch_id: count
            for branch_id, count in (
                await self._session.execute(
                    select(EmployeeAssignment.branch_id, func.count())
                    .where(
                        EmployeeAssignment.company_id == company_id,
                        EmployeeAssignment.deleted_at.is_(None),
                        EmployeeAssignment.branch_id.is_not(None),
                        EmployeeAssignment.effective_from <= today,
                        (EmployeeAssignment.effective_to.is_(None))
                        | (EmployeeAssignment.effective_to >= today),
                    )
                    .group_by(EmployeeAssignment.branch_id)
                )
            ).all()
            if branch_id is not None
        }
        authorized = await self._repo.authorization_counts_by_branch(
            self._session, company_id=company_id
        )
        return [
            GeofenceWorkplaceRead(
                branch_id=b.id,
                name=b.name,
                code=b.code,
                is_active=b.is_active,
                latitude=float(b.latitude) if b.latitude is not None else None,
                longitude=float(b.longitude) if b.longitude is not None else None,
                radius_m=b.geofence_radius_m,
                configured=(
                    b.latitude is not None
                    and b.longitude is not None
                    and b.geofence_radius_m is not None
                ),
                assigned_employee_count=assigned.get(b.id, 0),
                authorized_employee_count=authorized.get(b.id, 0),
            )
            for b in branches
        ]

    async def list_authorizations(
        self,
        *,
        company_id: UUID,
        employee_id: UUID | None = None,
        branch_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[EmployeeWorkplaceAuthorization], int]:
        return await self._repo.list_authorizations(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            branch_id=branch_id,
            limit=limit,
            offset=offset,
        )

    async def list_attempts(
        self,
        *,
        company_id: UUID,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
        employee_id: UUID | None = None,
        accepted: bool | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GeofenceAttempt], int]:
        """Recorded attempts, restricted to the employees the caller's data scope can see (a
        grant narrower than COMPANY must not expose other people's location history)."""
        from hrms.modules.attendance.service import _resolve_visible_employee_ids

        visible = await _resolve_visible_employee_ids(
            self._session, company_id, scope, caller_employee_id
        )
        return await self._repo.list_attempts(
            self._session,
            company_id=company_id,
            visible_employee_ids=visible,
            employee_id=employee_id,
            accepted=accepted,
            outcome=outcome,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
