"""What applies at a scope, and where it comes from, plus saving several changes at once.

`coverage` backs the assignment screen: for one scope it lists each policy kind (each leave type
for leave), the open assignment set at that scope, and what actually applies on a date after
walking to wider scopes. For an employee the walk is the exact WD-09 chain. Other scopes use the
containment that is known (department -> branch -> legal entity -> company); grades, designations
and shifts only have the company above them, because they do not sit inside one another.

`save_batch` applies changes for the versioned kinds in one transaction. Calendar kinds are refused
because they change day classification and go through the impact preview one at a time."""

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.core.errors.base import AppError, ValidationError
from hrms.modules.organisation.calendar_resolution import CalendarResolutionService
from hrms.modules.organisation.repository import (
    OrganisationRepository,
    PolicyAssignmentRepository,
    WeeklyOffPatternRepository,
    WorkCalendarRepository,
)
from hrms.modules.organisation.schemas import (
    PolicyAssignmentBatch,
    PolicyAssignmentCreate,
    PolicyAssignmentRead,
    PolicyCoverageApplied,
    PolicyCoverageOwn,
    PolicyCoverageRead,
    PolicyCoverageRow,
)
from hrms.modules.organisation.service import OrganisationService

CALENDAR_KINDS = ("WORK_CALENDAR", "WEEKLY_OFF")
ATTENDANCE_KINDS = ("ATTENDANCE_POLICY", "OVERTIME_POLICY", "REGULARIZATION_POLICY")
LEAVE_KIND = "LEAVE_POLICY"

_Scope = tuple[str, UUID | None]


class PolicyCoverageService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._org = OrganisationService(session)
        self._org_repo = OrganisationRepository()
        self._assignments = PolicyAssignmentRepository()

    async def _chain(
        self, company_id: UUID, scope_type: str, scope_id: UUID | None, as_of: date
    ) -> list[_Scope]:
        """The scope itself followed by the wider scopes it falls back to, narrowest first."""
        company: _Scope = ("COMPANY", None)
        if scope_type == "COMPANY":
            return [company]
        assert scope_id is not None
        if scope_type == "EMPLOYEE":
            return await CalendarResolutionService(self._session)._scope_candidates(
                company_id, scope_id, as_of
            )
        chain: list[_Scope] = [(scope_type, scope_id)]
        branch_id: UUID | None = None
        if scope_type == "DEPARTMENT":
            department = await self._org.get_department(company_id, scope_id)
            branch_id = department.branch_id
            if branch_id is not None:
                chain.append(("BRANCH", branch_id))
        elif scope_type == "BRANCH":
            branch_id = scope_id
        if branch_id is not None:
            branch = await self._org_repo.get_branch(
                self._session, company_id=company_id, branch_id=branch_id
            )
            if branch is not None:
                chain.append(("LEGAL_ENTITY", branch.legal_entity_id))
        chain.append(company)
        return chain

    async def _policy_names(self, company_id: UUID, kinds: list[str]) -> dict[UUID, str]:
        from hrms.modules.attendance.service import AttendanceService
        from hrms.modules.leave.service import LeavePolicyService

        attendance = AttendanceService(self._session)
        rows: list[Any] = []
        if "WORK_CALENDAR" in kinds:
            rows += await WorkCalendarRepository().list_work_calendars(
                self._session, company_id=company_id
            )
        if "WEEKLY_OFF" in kinds:
            rows += await WeeklyOffPatternRepository().list_patterns(
                self._session, company_id=company_id
            )
        if "ATTENDANCE_POLICY" in kinds:
            rows += await attendance.list_attendance_policies(company_id)
        if "OVERTIME_POLICY" in kinds:
            rows += await attendance.list_overtime_policies(company_id)
        if "REGULARIZATION_POLICY" in kinds:
            rows += await attendance.list_regularization_policies(company_id)
        if LEAVE_KIND in kinds:
            rows += await LeavePolicyService(self._session).list_policies(company_id)
        return {row.id: row.name for row in rows}

    async def _scope_name(self, company_id: UUID, scope_type: str, scope_id: UUID) -> str | None:
        load = {
            "LEGAL_ENTITY": self._org.get_legal_entity,
            "BRANCH": self._org.get_branch,
            "DEPARTMENT": self._org.get_department,
            "GRADE": self._org.get_grade,
            "DESIGNATION": self._org.get_designation,
            "SHIFT": self._org.get_shift,
        }.get(scope_type)
        if load is None:
            return None
        row = await load(company_id, scope_id)
        return getattr(row, "name", None) or getattr(row, "title", None)

    async def _has_rules_on(
        self, company_id: UUID, policy_kind: str, policy_id: UUID, as_of: date
    ) -> bool:
        """Calendars have no versions; the rest need a published version effective on `as_of`."""
        if policy_kind in CALENDAR_KINDS:
            return True
        if policy_kind == LEAVE_KIND:
            from hrms.modules.leave.service import LeavePolicyService

            return await LeavePolicyService(self._session).policy_has_version_as_of(
                company_id, policy_id, as_of
            )
        from hrms.modules.attendance.service import AttendanceService

        return await AttendanceService(self._session).policy_has_version_as_of(
            company_id, policy_kind, policy_id, as_of
        )

    async def coverage(
        self,
        company_id: UUID,
        *,
        scope_type: str,
        scope_id: UUID | None,
        as_of: date,
        kinds: list[str],
    ) -> PolicyCoverageRead:
        if (scope_type == "COMPANY") != (scope_id is None):
            raise ValidationError("scope_id is required unless scope_type is COMPANY")
        await self._org._validate_policy_scope(company_id, scope_type, scope_id)

        chain = await self._chain(company_id, scope_type, scope_id, as_of)
        effective = await self._assignments.list_effective_at_scopes(
            self._session, company_id=company_id, scopes=chain, as_of=as_of
        )
        by_slot = {(r.policy_kind, r.leave_type_id, r.scope_type, r.scope_id): r for r in effective}
        open_rows = await self._assignments.list_assignments(
            self._session,
            company_id=company_id,
            scope_type=scope_type,
            scope_id=scope_id,
            current_only=True,
        )
        own_by_slot = {(r.policy_kind, r.leave_type_id): r for r in open_rows}
        names = await self._policy_names(company_id, kinds)

        slots: list[tuple[str, UUID | None, str | None]] = [
            (kind, None, None) for kind in kinds if kind != LEAVE_KIND
        ]
        if LEAVE_KIND in kinds:
            from hrms.modules.leave.repository import LeaveTypeRepository

            for leave_type in await LeaveTypeRepository().list(
                self._session, company_id=company_id
            ):
                if leave_type.is_active or (LEAVE_KIND, leave_type.id) in own_by_slot:
                    slots.append((LEAVE_KIND, leave_type.id, leave_type.name))

        scope_names: dict[_Scope, str | None] = {}
        rows: list[PolicyCoverageRow] = []
        for kind, leave_type_id, leave_type_name in slots:
            own = own_by_slot.get((kind, leave_type_id))
            applied: PolicyCoverageApplied | None = None
            for level_type, level_id in chain:
                found = by_slot.get((kind, leave_type_id, level_type, level_id))
                if found is None:
                    continue
                if level_id is not None and (level_type, level_id) not in scope_names:
                    scope_names[(level_type, level_id)] = await self._scope_name(
                        company_id, level_type, level_id
                    )
                applied = PolicyCoverageApplied(
                    policy_id=found.policy_id,
                    policy_name=names.get(found.policy_id),
                    scope_type=level_type,
                    scope_id=level_id,
                    scope_name=scope_names.get((level_type, level_id)),
                    effective_from=found.effective_from,
                    effective_to=found.effective_to,
                    has_rules=await self._has_rules_on(company_id, kind, found.policy_id, as_of),
                )
                break
            rows.append(
                PolicyCoverageRow(
                    policy_kind=kind,
                    leave_type_id=leave_type_id,
                    leave_type_name=leave_type_name,
                    own=PolicyCoverageOwn(
                        assignment_id=own.id,
                        policy_id=own.policy_id,
                        policy_name=names.get(own.policy_id),
                        effective_from=own.effective_from,
                        version=own.version,
                    )
                    if own is not None
                    else None,
                    applied=applied,
                )
            )
        return PolicyCoverageRead(scope_type=scope_type, scope_id=scope_id, as_of=as_of, rows=rows)

    async def save_batch(
        self,
        company_id: UUID,
        body: PolicyAssignmentBatch,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> list[PolicyAssignmentRead]:
        """All or nothing: any failure raises, and the request's transaction rolls back. The
        failing row is named in the error details so the screen can point at it."""
        if any(change.policy_kind in CALENDAR_KINDS for change in body.changes):
            raise ValidationError(
                "Work calendar and weekly-off changes go through the impact preview",
                code="POLICY_BATCH_KIND_NOT_ALLOWED",
            )
        # A new assignment takes over from its effective date, so no closed period may follow it.
        from hrms.modules.attendance.exceptions import AttendancePeriodClosedError
        from hrms.modules.attendance.repository import AttendancePeriodRepository

        if await AttendancePeriodRepository().list_closed_overlapping(
            self._session,
            company_id=company_id,
            date_from=body.effective_from,
            date_to=date.max,
        ):
            raise AttendancePeriodClosedError()

        created: list[PolicyAssignmentRead] = []
        for change in body.changes:
            try:
                created.append(
                    await self._org.create_policy_assignment(
                        company_id,
                        PolicyAssignmentCreate(
                            policy_kind=change.policy_kind,
                            policy_id=change.policy_id,
                            leave_type_id=change.leave_type_id,
                            scope_type=body.scope_type,
                            scope_id=body.scope_id,
                            effective_from=body.effective_from,
                            reason=body.reason,
                        ),
                        expected_version=change.expected_version,
                        actor_user_id=actor_user_id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                )
            except AppError as exc:
                exc.details = [
                    {
                        "field": "changes",
                        "code": exc.code,
                        "message": exc.message,
                        "context": {
                            "policy_kind": change.policy_kind,
                            "leave_type_id": str(change.leave_type_id)
                            if change.leave_type_id
                            else None,
                        },
                    }
                ]
                raise
        return created


def get_policy_coverage_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> PolicyCoverageService:
    return PolicyCoverageService(session)
