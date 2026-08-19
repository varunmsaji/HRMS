"""Policy resolution (architecture §16, §19 step 7; WD-09) — "most specific applicable policy
wins" for Attendance/Overtime/Regularization policy kinds.

Deliberately thin: the actual 8-level precedence walk
(`EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY`) already
exists and is generic over `policy_kind` — `CalendarResolutionService.resolve_policy_assignment`
in `organisation/calendar_resolution.py`, built in W1 for `WORK_CALENDAR`/`WEEKLY_OFF` but never
restricted to those kinds in code (only the `policy_assignment.policy_kind` DB CHECK narrowed
what could be persisted — widened by this slice's migration). This module only adds the
version-lookup step once a matching `PolicyAssignment` row is found, and fails closed
(`config_incomplete=True`) exactly like `CalendarResolutionService.resolve_for_employee` does for
missing calendars (WD-21) — never guesses a default policy."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.attendance.models import (
    AttendancePolicy,
    AttendancePolicyVersion,
    OvertimePolicy,
    OvertimePolicyVersion,
    RegularizationPolicy,
    RegularizationPolicyVersion,
)
from hrms.modules.attendance.repository import (
    AttendancePolicyRepository,
    OvertimePolicyRepository,
    RegularizationPolicyRepository,
)
from hrms.modules.attendance.schemas import PolicyResolutionRead

_AnyPolicy = AttendancePolicy | OvertimePolicy | RegularizationPolicy
_AnyPolicyVersion = AttendancePolicyVersion | OvertimePolicyVersion | RegularizationPolicyVersion


class PolicyResolutionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._attendance_repo = AttendancePolicyRepository()
        self._overtime_repo = OvertimePolicyRepository()
        self._regularization_repo = RegularizationPolicyRepository()

    async def resolve(
        self, company_id: UUID, policy_kind: str, *, employee_id: UUID, target_date: date
    ) -> PolicyResolutionRead:
        # Local, function-scoped import — mirrors the established reverse-direction precedent
        # already used twice in this codebase (`calendar_resolution.py` importing
        # `employee.service.EmployeeAssignmentService`, `employee/service.py` importing
        # `organisation.service.OrganisationService`); the import-linter `layers` contract only
        # constrains `hrms.core`/`hrms.shared`, not sibling `hrms.modules` packages.
        from hrms.modules.organisation.calendar_resolution import CalendarResolutionService

        incomplete = PolicyResolutionRead(
            employee_id=employee_id,
            date=target_date,
            policy_kind=policy_kind,
            config_incomplete=True,
        )

        calendar_resolution = CalendarResolutionService(self._session)
        found = await calendar_resolution.resolve_policy_assignment(
            company_id, policy_kind, employee_id=employee_id, target_date=target_date
        )
        if found is None:
            return incomplete
        assignment, scope_type = found

        policy: _AnyPolicy | None
        version: _AnyPolicyVersion | None
        if policy_kind == "ATTENDANCE_POLICY":
            policy = await self._attendance_repo.get_policy(
                self._session, company_id=company_id, policy_id=assignment.policy_id
            )
            version = await self._attendance_repo.find_effective_as_of(
                self._session,
                company_id=company_id,
                policy_id=assignment.policy_id,
                as_of=target_date,
            )
        elif policy_kind == "OVERTIME_POLICY":
            policy = await self._overtime_repo.get_policy(
                self._session, company_id=company_id, policy_id=assignment.policy_id
            )
            version = await self._overtime_repo.find_effective_as_of(
                self._session,
                company_id=company_id,
                policy_id=assignment.policy_id,
                as_of=target_date,
            )
        elif policy_kind == "REGULARIZATION_POLICY":
            policy = await self._regularization_repo.get_policy(
                self._session, company_id=company_id, policy_id=assignment.policy_id
            )
            version = await self._regularization_repo.find_effective_as_of(
                self._session,
                company_id=company_id,
                policy_id=assignment.policy_id,
                as_of=target_date,
            )
        else:
            return incomplete

        if policy is None or version is None:
            return incomplete

        return PolicyResolutionRead(
            employee_id=employee_id,
            date=target_date,
            policy_kind=policy_kind,
            config_incomplete=False,
            resolved_policy_id=policy.id,
            resolved_policy_name=policy.name,
            resolved_policy_code=policy.code,
            resolved_version_id=version.id,
            resolved_through=scope_type,
        )
