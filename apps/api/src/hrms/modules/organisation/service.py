"""Business logic for the organisation module — the public interface for other modules."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.auth.passwords import hash_password, is_password_strong_enough
from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.locks import lock_calendar_policy_dependencies
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError
from hrms.core.rbac.types import DataScopeLevel
from hrms.modules.employee.permissions import (
    EMPLOYEE_PERMISSIONS,
    EMPLOYEE_VIEW_ALL,
    EMPLOYEE_VIEW_BANKING,
    EMPLOYEE_VIEW_COMPENSATION,
    EMPLOYEE_VIEW_DOCUMENTS,
    EMPLOYEE_VIEW_EXPERIENCE,
    EMPLOYEE_VIEW_NOMINEE,
    EMPLOYEE_VIEW_SENSITIVE,
    EMPLOYEE_VIEW_STATUTORY,
)
from hrms.modules.employee.repository import EmployeeRepository
from hrms.modules.identity.permissions import (
    EMPLOYEE_VIEW,
    SETTINGS_ROLE_MANAGE,
    SETTINGS_USER_MANAGE,
)
from hrms.modules.identity.schemas import CompanySummary, TokenResponseData
from hrms.modules.identity.service import IdentityService
from hrms.modules.organisation.calendar_resolution import (
    CalendarResolutionService,
    reconcile_holiday_is_working,
)
from hrms.modules.organisation.exceptions import (
    BranchDeactivationBlockedError,
    BranchHasWorkplaceAuthorizationsError,
    CalendarExceptionDateConflictError,
    CompanyLimitReachedError,
    CompanyWriteBlockedError,
    CurrencyLockedError,
    DepartmentCycleDetectedError,
    DepartmentMaxDepthExceededError,
    GradeCodeAlreadyExistsError,
    HolidayCalendarCodeAlreadyExistsError,
    HolidayDateAlreadyExistsError,
    InvalidBranchError,
    InvalidCtcRangeError,
    InvalidDepartmentError,
    InvalidDepartmentHeadError,
    InvalidGradeError,
    InvalidHolidayCalendarError,
    InvalidLegalEntityError,
    InvalidParentDepartmentError,
    InvalidPolicyReferenceError,
    InvalidPolicyScopeError,
    InvalidShiftBreakError,
    InvalidShiftBreakOverlapError,
    InvalidShiftVersionCoreHoursError,
    InvalidShiftVersionDutyBlockCountError,
    InvalidShiftVersionDutyBlockOverlapError,
    InvalidShiftVersionDutyBlockSequenceError,
    InvalidShiftVersionEffectiveFromError,
    InvalidShiftVersionFlexWindowError,
    InvalidShiftVersionTimeRangeError,
    InvalidShiftVersionTypeCombinationError,
    InvalidWorkCalendarError,
    InvalidWorkingDaysError,
    LegalEntityDeactivationBlockedError,
    MasterDataInUseError,
    PolicyAssignmentNotEndableError,
    PolicyAssignmentOverlapError,
    PolicyAssignmentVersionRequiredError,
    PolicyKindNotSupportedError,
    PolicyNotPublishedError,
    ShiftDeleteConfirmationMismatchError,
    ShiftDeletionBlockedError,
    ShiftVersionDraftAlreadyExistsError,
    ShiftVersionNotDraftError,
    ShiftVersionNotFoundForDateError,
    ShiftVersionOverlapError,
    ShiftVersionPreviousVersionRequiredError,
    StaleResourceError,
    TimezoneChangeBlockedError,
    WeeklyOffPatternDeactivationBlockedError,
    WeeklyOffRuleInvalidError,
    WorkCalendarCompositionInvalidError,
    WorkCalendarDeactivationBlockedError,
)
from hrms.modules.organisation.models import (
    Branch,
    Department,
    Designation,
    Grade,
    HolidayCalendar,
    WeeklyOffPattern,
    WorkCalendar,
)
from hrms.modules.organisation.permissions import (
    DASHBOARD_COMPANY_VIEW,
    ORG_BRANCH_MANAGE,
    ORG_CALENDAR_MANAGE,
    ORG_COMPANY_MANAGE,
    ORG_DEPARTMENT_MANAGE,
    ORG_DESIGNATION_MANAGE,
    ORG_GRADE_MANAGE,
    ORG_HOLIDAY_MANAGE,
    ORG_LEGAL_ENTITY_MANAGE,
    ORG_SHIFT_MANAGE,
)
from hrms.modules.organisation.repository import (
    CalendarExceptionRepository,
    HolidayCalendarRepository,
    HolidayRepository,
    OrganisationRepository,
    PolicyAssignmentRepository,
    ShiftVersionRepository,
    WeeklyOffPatternRepository,
    WorkCalendarRepository,
)
from hrms.modules.organisation.schemas import (
    BranchCreate,
    BranchRead,
    BranchUpdate,
    CalendarExceptionCreate,
    CalendarExceptionRead,
    CalendarExceptionUpdate,
    CalendarResolutionRead,
    CompanyDashboardSummary,
    CompanyProfileRead,
    CompanyProfileUpdate,
    CompanyRegistrationRequest,
    CompanySetupProgressSummary,
    DashboardSetupProgress,
    DashboardSubscription,
    DayTypeRead,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    DesignationCreate,
    DesignationRead,
    DesignationUpdate,
    FeatureFlagView,
    GradeCreate,
    GradeRead,
    GradeUpdate,
    HolidayCalendarCreate,
    HolidayCalendarRead,
    HolidayCalendarUpdate,
    HolidayCreate,
    HolidayRead,
    HolidayUpdate,
    LegalEntityCreate,
    LegalEntityRead,
    LegalEntityUpdate,
    PlanSummary,
    PolicyAssignmentCreate,
    PolicyAssignmentEnd,
    PolicyAssignmentRead,
    SetupStepDefinition,
    SetupStepSummary,
    ShiftBreakCreate,
    ShiftCreate,
    ShiftDeleteRequest,
    ShiftDeletionBlocker,
    ShiftDeletionCheck,
    ShiftDutyBlockCreate,
    ShiftRead,
    ShiftUpdate,
    ShiftVersionCreate,
    ShiftVersionPublishRequest,
    ShiftVersionRead,
    ShiftVersionUpdate,
    SubscriptionSummary,
    WeeklyOffPatternCreate,
    WeeklyOffPatternRead,
    WeeklyOffPatternUpdate,
    WeeklyOffRuleInput,
    WorkCalendarCreate,
    WorkCalendarRead,
    WorkCalendarUpdate,
    branch_to_audit_dict,
    branch_to_read,
    build_branch_update_values,
    build_calendar_exception_update_values,
    build_department_update_values,
    build_designation_update_values,
    build_grade_update_values,
    build_holiday_calendar_update_values,
    build_holiday_update_values,
    build_legal_entity_update_values,
    build_shift_update_values,
    build_shift_version_update_values,
    build_update_values,
    build_weekly_off_pattern_update_values,
    build_work_calendar_update_values,
    calendar_exception_to_audit_dict,
    calendar_exception_to_read,
    company_to_profile_read,
    count_working_days,
    department_to_audit_dict,
    department_to_read,
    designation_to_audit_dict,
    designation_to_read,
    grade_to_audit_dict,
    grade_to_read,
    holiday_calendar_to_audit_dict,
    holiday_calendar_to_read,
    holiday_to_audit_dict,
    holiday_to_read,
    legal_entity_to_audit_dict,
    legal_entity_to_read,
    policy_assignment_to_audit_dict,
    policy_assignment_to_read,
    profile_to_audit_dict,
    setup_progress_to_summary,
    shift_to_audit_dict,
    shift_to_read,
    shift_version_to_audit_dict,
    shift_version_to_read,
    weekly_off_pattern_to_audit_dict,
    weekly_off_pattern_to_read,
    work_calendar_to_audit_dict,
    work_calendar_to_read,
)
from hrms.seed.plan_catalogue import SEAT_LIMIT_FEATURE_CODE
from hrms.shared.business_time import business_today
from hrms.shared.pagination import PageParams
from hrms.shared.timezone import validate_iana_timezone

# No explicit trial length is defined anywhere in the frozen Company docs — 14 days is an
# assumed, easily-changed default (common SaaS convention), not a sourced product decision.
TRIAL_PERIOD_DAYS = 14

# No `Plan.is_default` flag exists (frozen schema, C-05). "FREE" is treated as the default
# trial plan because it is the only catalogue entry whose own description says "for
# evaluating the platform" (`hrms/seed/plan_catalogue.py`) — the closest match to "trial."
DEFAULT_TRIAL_PLAN_CODE = "FREE"

COMPANY_ADMIN_ROLE_CODE = "COMPANY_ADMIN"
# `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision H — the three default roles the
# SELF/REPORTEES/REPORTEE_TREE data-scope model (`docs/modules/employee/
# 25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md`) needs a second holder to ever apply to.
# Seeded here (role rows only) so a future account-provisioning flow
# (`docs/modules/employee/41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md`) has a role
# to assign; none of these roles are assigned to the registering admin, who keeps COMPANY_ADMIN.
HR_ADMIN_ROLE_CODE = "HR_ADMIN"
REPORTING_MANAGER_ROLE_CODE = "REPORTING_MANAGER"
# `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md`'s 2026-09-23/24 Addendum — a manager whose
# scope is their own branch (`DataScopeLevel.BRANCH`, resolved from the holder's own current
# `EmployeeAssignment.branch_id`), for tenants that manage each branch as its own unit rather
# than through the reporting hierarchy `REPORTING_MANAGER` already covers. Also granted
# `EMPLOYEE.VIEW_ALL` (gates `GET /v1/employees`, the list endpoint `/app/employees` calls —
# distinct from `EMPLOYEE.VIEW`, which only gates the single-record `GET /v1/employees/{id}`) and
# `ATTENDANCE.VIEW` at `BRANCH` scope: both permissions' read paths resolve scope generically
# through `EmployeeService.resolve_visible_employee_ids` (same seam `EMPLOYEE.VIEW` uses), so
# `BRANCH` works there with no service-layer change. Deliberately NOT granted
# `ATTENDANCE.REGULARIZATION_APPROVE`/`ATTENDANCE.OVERTIME_APPROVE`/`LEAVE.APPLICATION_APPROVE`:
# those services' `_get_reviewable()` gates the MANAGER stage on an exact
# `resolved_approver_manager_id`/`resolved_department_head_id` identity match and the HR stage on
# `DataScopeLevel.COMPANY` specifically — neither branch treats `BRANCH` as satisfying anything,
# so granting those codes at `BRANCH` scope today would be a silent no-op (the permission would
# exist but every approve/reject call would still raise an approver-mismatch error). Revisit if a
# future change teaches those three `_get_reviewable()` methods a `BRANCH` branch.
BRANCH_MANAGER_ROLE_CODE = "BRANCH_MANAGER"
EMPLOYEE_ROLE_CODE = "EMPLOYEE"

# FR-ORG-005 — department hierarchy is capped at 5 levels (root = depth 1).
DEPARTMENT_MAX_DEPTH = 5

# Extensibility point (05_Backend_Architecture.md §3.1): Company owns this registry and the
# aggregation loop in `get_setup_progress`, never the predicate logic for a sibling step once
# one exists — e.g. a future `SetupStepDefinition(code="BRANCHES", ..., check=lambda repo,
# session, cid: repo.branch_count(session, company_id=cid) > 0)` would live in a Branch-owned
# repository method, appended here without touching the aggregation loop below.
SETUP_STEPS: list[SetupStepDefinition] = [
    SetupStepDefinition(
        code="COMPANY_PROFILE",
        label="Company Profile",
        check=lambda repo, session, company_id: repo.company_profile_is_complete(
            session, company_id=company_id
        ),
    ),
]


class OrganisationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = OrganisationRepository()
        self._identity_repo = IdentityRepository()
        self._identity = IdentityService(session, self._settings)
        self._audit = AuditService()
        self._holiday_calendar_repo = HolidayCalendarRepository()
        self._holiday_repo = HolidayRepository()
        self._weekly_off_repo = WeeklyOffPatternRepository()
        self._work_calendar_repo = WorkCalendarRepository()
        self._calendar_exception_repo = CalendarExceptionRepository()
        self._policy_assignment_repo = PolicyAssignmentRepository()
        self._shift_version_repo = ShiftVersionRepository()
        self._calendar_resolution = CalendarResolutionService(session)
        self._employee_repo = EmployeeRepository()

    async def register_company(
        self,
        body: CompanyRegistrationRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponseData:
        if not is_password_strong_enough(body.admin_password):
            raise ValidationError(
                "Password does not meet minimum strength requirements",
                details=[
                    {
                        "field": "admin_password",
                        "code": "WEAK_PASSWORD",
                        "message": "Password must be at least 8 characters and include "
                        "both a letter and a digit",
                    }
                ],
            )

        admin_email = body.admin_email.lower()
        existing_user = await self._identity_repo.get_user_by_email(self._session, admin_email)
        if existing_user is not None:
            raise ConflictError("An account with this email already exists")

        now = datetime.now(UTC)
        user_id = uuid4()
        company_id = uuid4()

        # Set the RLS tenant variable for this new company before touching any RLS-bearing
        # table (`company_setup_progress`, `subscription`, `audit_log`) — there is no
        # pre-existing tenant context for a public registration request.
        await set_rls_company_id(self._session, str(company_id))

        try:
            await self._repo.insert_user(
                self._session,
                user_id=user_id,
                email=admin_email,
                password_hash=hash_password(body.admin_password),
                first_name=body.admin_first_name,
                last_name=body.admin_last_name,
                now=now,
            )
        except IntegrityError as exc:
            # The pre-check above is racy by construction — `user.email` carries a real DB
            # unique index (`user_email_key`, scripts/sql/001_init_schema.sql) that is the
            # actual backstop for two concurrent registrations with the same email.
            raise ConflictError("An account with this email already exists") from exc

        # Platform console: with approval required the company starts `PENDING_APPROVAL` with no
        # trial clock; the clock starts when a platform admin approves it.
        needs_approval = self._settings.company_approval_required
        trial_ends_at = None if needs_approval else now + timedelta(days=TRIAL_PERIOD_DAYS)
        company = await self._repo.insert_company(
            self._session,
            data={
                "id": company_id,
                "name": body.name,
                "industry_code": body.industry_code,
                "country_code": body.country_code,
                "currency": body.currency,
                "timezone": body.timezone,
                "fy_start_month": body.fy_start_month,
                "company_size": body.company_size,
                "status": "PENDING_APPROVAL" if needs_approval else "TRIAL",
                "trial_ends_at": trial_ends_at,
                "created_by": user_id,
                "updated_by": user_id,
                "created_at": now,
                "updated_at": now,
            },
        )

        user_company = await self._repo.insert_user_company(
            self._session,
            user_id=user_id,
            company_id=company_id,
            is_primary=True,
            now=now,
        )

        org_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_COMPANY_MANAGE,
            domain="ORG",
            description="Manage company settings",
        )
        dashboard_view_perm = await self._repo.get_or_create_permission(
            self._session,
            code=DASHBOARD_COMPANY_VIEW,
            domain="DASHBOARD",
            description="View company dashboard",
        )
        legal_entity_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_LEGAL_ENTITY_MANAGE,
            domain="ORG",
            description="Manage legal entities",
        )
        branch_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_BRANCH_MANAGE,
            domain="ORG",
            description="Manage branches",
        )
        department_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_DEPARTMENT_MANAGE,
            domain="ORG",
            description="Manage departments",
        )
        designation_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_DESIGNATION_MANAGE,
            domain="ORG",
            description="Manage designations",
        )
        grade_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_GRADE_MANAGE,
            domain="ORG",
            description="Manage grades",
        )
        shift_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_SHIFT_MANAGE,
            domain="ORG",
            description="Manage shifts",
        )
        employee_view_perm = await self._repo.get_or_create_permission(
            self._session,
            code=EMPLOYEE_VIEW,
            domain="EMPLOYEE",
            description="View employees within scope",
        )
        # `EMPLOYEE_PERMISSIONS` (employee/permissions.py) — granted here, not just seeded,
        # because this is the live registration path every real company goes through
        # (`seed/bootstrap.py` only seeds two fixed demo companies). Without this, a newly
        # registered company's own admin would have zero EMPLOYEE.* access, matching the same
        # pattern every organisation-module permission already follows in this method.
        employee_permission_rows = [
            await self._repo.get_or_create_permission(
                self._session, code=code, domain=domain, description=description
            )
            for code, domain, description in EMPLOYEE_PERMISSIONS
        ]
        employee_permission_by_code = {perm.code: perm for perm in employee_permission_rows}
        # Workforce Calendar (W1) — `ORG.CALENDAR.MANAGE` / `ORG.HOLIDAY.MANAGE`
        # (architecture §23.2, WD-19). Granted here via the same list-comprehension idiom as
        # `EMPLOYEE_PERMISSIONS` immediately above, rather than the older one-call-per-code
        # style used for the pre-existing ORG codes — this is the live registration path every
        # real company goes through; the demo seed (`seed/bootstrap.py::seed_b1_foundation`)
        # picks these up automatically via `ORGANISATION_PERMISSIONS`.
        calendar_permission_rows = [
            await self._repo.get_or_create_permission(
                self._session, code=code, domain=domain, description=description
            )
            for code, domain, description in (
                (
                    ORG_CALENDAR_MANAGE,
                    "ORG",
                    "Manage workforce calendars, weekly-off patterns, and calendar assignments",
                ),
                (ORG_HOLIDAY_MANAGE, "ORG", "Manage holiday calendars and holidays"),
            )
        ]
        # W3 — `ATTENDANCE.POLICY_MANAGE` (architecture §23.2, WD-19). Same live-registration-path
        # rationale as `calendar_permission_rows` above; a local import avoids a module-top-level
        # organisation -> attendance dependency (mirrors `_validate_policy_reference`).
        from hrms.modules.attendance.permissions import (
            ATTENDANCE_OVERTIME_APPROVE,
            ATTENDANCE_PERMISSIONS,
            ATTENDANCE_PUNCH,
            ATTENDANCE_REGULARIZATION_APPROVE,
            ATTENDANCE_REGULARIZATION_REQUEST,
            ATTENDANCE_VIEW,
            ATTENDANCE_VIEW_ALL,
        )

        attendance_permission_rows = [
            await self._repo.get_or_create_permission(
                self._session, code=code, domain=domain, description=description
            )
            for code, domain, description in ATTENDANCE_PERMISSIONS
        ]
        attendance_permission_by_code = {perm.code: perm for perm in attendance_permission_rows}

        # L1 — `LEAVE.*` (LEAVE_DECISION_LOG.md LD-08). Same live-registration-path rationale as
        # `attendance_permission_rows` immediately above.
        from hrms.modules.leave.permissions import (
            LEAVE_APPLICATION_APPROVE,
            LEAVE_APPLICATION_CANCEL_APPROVED,
            LEAVE_APPLICATION_REASSIGN,
            LEAVE_APPLICATION_SUBMIT,
            LEAVE_APPLICATION_SUBMIT_ON_BEHALF,
            LEAVE_BALANCE_ADJUST,
            LEAVE_BALANCE_VIEW,
            LEAVE_BALANCE_VIEW_ALL,
            LEAVE_PERMISSIONS,
        )

        leave_permission_rows = [
            await self._repo.get_or_create_permission(
                self._session, code=code, domain=domain, description=description
            )
            for code, domain, description in LEAVE_PERMISSIONS
        ]
        leave_permission_by_code = {perm.code: perm for perm in leave_permission_rows}

        # Onboarding O1 — `ONBOARDING.*` (docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md
        # §7.1/§11). Same live-registration-path rationale as `leave_permission_rows` above.
        from hrms.modules.onboarding.permissions import ONBOARDING_PERMISSIONS

        onboarding_permission_rows = [
            await self._repo.get_or_create_permission(
                self._session, code=code, domain=domain, description=description
            )
            for code, domain, description in ONBOARDING_PERMISSIONS
        ]

        # Payroll Phase 5.1 — `PAYROLL.*` (docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md).
        # Same live-registration-path rationale as `onboarding_permission_rows` above.
        from hrms.modules.payroll.permissions import (
            PAYROLL_HR_ADMIN_PERMISSIONS,
            PAYROLL_PAYSLIP_VIEW_OWN,
            PAYROLL_PERMISSIONS,
        )

        payroll_permission_rows = [
            await self._repo.get_or_create_permission(
                self._session, code=code, domain=domain, description=description
            )
            for code, domain, description in PAYROLL_PERMISSIONS
        ]

        role = await self._repo.insert_role(
            self._session,
            company_id=company_id,
            code=COMPANY_ADMIN_ROLE_CODE,
            name="Company Administrator",
            is_system=True,
            now=now,
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=org_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=dashboard_view_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=legal_entity_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=branch_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=department_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=designation_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=grade_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=shift_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=employee_view_perm.id
        )
        for perm in employee_permission_rows:
            await self._repo.insert_role_permission(
                self._session, role_id=role.id, permission_id=perm.id
            )
        for perm in calendar_permission_rows:
            await self._repo.insert_role_permission(
                self._session, role_id=role.id, permission_id=perm.id
            )
        for perm in attendance_permission_rows:
            await self._repo.insert_role_permission(
                self._session, role_id=role.id, permission_id=perm.id
            )
        for perm in leave_permission_rows:
            await self._repo.insert_role_permission(
                self._session, role_id=role.id, permission_id=perm.id
            )
        for perm in onboarding_permission_rows:
            await self._repo.insert_role_permission(
                self._session, role_id=role.id, permission_id=perm.id
            )
        for perm in payroll_permission_rows:
            await self._repo.insert_role_permission(
                self._session, role_id=role.id, permission_id=perm.id
            )
        await self._repo.insert_user_role(
            self._session, user_company_id=user_company.id, role_id=role.id
        )

        # `SETTINGS.USER.MANAGE`/`SETTINGS.ROLE.MANAGE` were previously never granted to
        # `COMPANY_ADMIN` at all — dead permission codes with no holder, per `docs/modules/
        # employee/41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` Decision P5. Granting
        # them here is what will let a future role-assignment endpoint be callable by the one role
        # that exists today.
        settings_user_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=SETTINGS_USER_MANAGE,
            domain="SETTINGS",
            description="Manage users",
        )
        settings_role_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=SETTINGS_ROLE_MANAGE,
            domain="SETTINGS",
            description="Manage roles",
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=settings_user_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=settings_role_manage_perm.id
        )

        # Default roles beyond `COMPANY_ADMIN` — `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md`
        # Decision H. Role rows only; none is assigned to the registering admin. They exist so a
        # future invite/role-assignment flow (doc 41) has something to assign. Grants below reuse
        # the `Permission` rows already fetched above rather than re-querying.
        hr_admin_role = await self._repo.insert_role(
            self._session,
            company_id=company_id,
            code=HR_ADMIN_ROLE_CODE,
            name="HR Administrator",
            is_system=True,
            now=now,
        )
        await self._repo.insert_role_permission(
            self._session, role_id=hr_admin_role.id, permission_id=employee_view_perm.id
        )
        for perm in employee_permission_rows:
            await self._repo.insert_role_permission(
                self._session, role_id=hr_admin_role.id, permission_id=perm.id
            )
        # HR-stage approval on all three request types (attendance/service.py's
        # `_get_reviewable`/`leave/service.py`'s equivalent) checks only `DataScopeLevel.COMPANY`
        # on the matching `.APPROVE` code — no identity match, unlike the MANAGER/HOD stages
        # below. Before this grant, the only role holding these codes at all was `COMPANY_ADMIN`,
        # which typically has no `Employee` record (a registering admin never entered into the
        # roster is the expected, documented case) and so fails the *other* two stages' identity
        # check outright — meaning an HR-stage request was the only one approvable by anyone,
        # and only by whoever happened to hold `COMPANY_ADMIN`. `HR_ADMIN` is the role this
        # product's own default-role catalogue (Decision H) already designates for "runs HR
        # operations" — granting it here at `COMPANY` scope is what actually lets that persona do
        # the job the role's name implies.
        # Decision 10 — HR cancels approved leave after it has started (employees only before).
        # Payroll 5.1/5.2 — HR sets up salaries and prepares pay runs; approving a run
        # (`PAYROLL.RUN_APPROVE`) stays with COMPANY_ADMIN (D9).
        for perm in (
            attendance_permission_by_code[ATTENDANCE_REGULARIZATION_APPROVE],
            attendance_permission_by_code[ATTENDANCE_OVERTIME_APPROVE],
            # HR_ADMIN policy - company-wide attendance READ for HR/payroll work (the period
            # summary and day/punch reads). Read only: policies, shifts, rosters and period
            # lock/unlock stay with COMPANY_ADMIN.
            attendance_permission_by_code[ATTENDANCE_VIEW],
            attendance_permission_by_code[ATTENDANCE_VIEW_ALL],
            leave_permission_by_code[LEAVE_APPLICATION_APPROVE],
            leave_permission_by_code[LEAVE_APPLICATION_CANCEL_APPROVED],
            # Decision 12 - normal company-level Leave administration: see every application and
            # balance, correct or encash a balance, act for an employee, and unstick an approval
            # (decision 13). Leave-type and policy management stay with COMPANY_ADMIN.
            leave_permission_by_code[LEAVE_BALANCE_VIEW_ALL],
            leave_permission_by_code[LEAVE_BALANCE_ADJUST],
            leave_permission_by_code[LEAVE_APPLICATION_SUBMIT_ON_BEHALF],
            leave_permission_by_code[LEAVE_APPLICATION_REASSIGN],
            *(p for p in payroll_permission_rows if p.code in PAYROLL_HR_ADMIN_PERMISSIONS),
            # HR_ADMIN policy - HR runs onboarding end to end (create, review, activate, cancel).
            *onboarding_permission_rows,
            # Work calendar: HR_ADMIN and COMPANY_ADMIN both manage calendars, weekly offs,
            # exceptions, assignments and holiday calendars (approved decision B).
            *calendar_permission_rows,
        ):
            await self._repo.insert_role_permission(
                self._session,
                role_id=hr_admin_role.id,
                permission_id=perm.id,
                data_scope=DataScopeLevel.COMPANY,
            )

        reporting_manager_role = await self._repo.insert_role(
            self._session,
            company_id=company_id,
            code=REPORTING_MANAGER_ROLE_CODE,
            name="Reporting Manager",
            is_system=True,
            now=now,
        )
        await self._repo.insert_role_permission(
            self._session,
            role_id=reporting_manager_role.id,
            permission_id=employee_view_perm.id,
            data_scope=DataScopeLevel.REPORTEE_TREE,
        )
        # MANAGER/HOD-stage approval checks the caller's `employee_id` against the request's
        # snapshotted `resolved_approver_manager_id`/`resolved_department_head_id` — an exact
        # identity match, not this scope value. What the scope value *does* gate is whether the
        # caller holds the `.APPROVE` code at all (the router's `require_permission` check, a
        # defence-in-depth layer before the identity check ever runs) and, separately, list/filter
        # endpoints that reuse `resolve_visible_employee_ids`. `REPORTEE_TREE` is used here purely
        # for consistency with this role's own `EMPLOYEE.VIEW` grant above — the identity check
        # doesn't consult it. Before this grant, `REPORTING_MANAGER` held none of these three
        # codes, so even the literal manager named on a request could never pass the router gate
        # to reach the identity check at all — a direct manager could not approve their own
        # report's regularization/overtime/leave request, full stop.
        for perm in (
            attendance_permission_by_code[ATTENDANCE_REGULARIZATION_APPROVE],
            attendance_permission_by_code[ATTENDANCE_OVERTIME_APPROVE],
            leave_permission_by_code[LEAVE_APPLICATION_APPROVE],
            # Decision 12 - a manager sees their reportees' leave applications and balances.
            leave_permission_by_code[LEAVE_BALANCE_VIEW_ALL],
        ):
            await self._repo.insert_role_permission(
                self._session,
                role_id=reporting_manager_role.id,
                permission_id=perm.id,
                data_scope=DataScopeLevel.REPORTEE_TREE,
            )

        branch_manager_role = await self._repo.insert_role(
            self._session,
            company_id=company_id,
            code=BRANCH_MANAGER_ROLE_CODE,
            name="Branch Manager",
            is_system=True,
            now=now,
        )
        await self._repo.insert_role_permission(
            self._session,
            role_id=branch_manager_role.id,
            permission_id=employee_view_perm.id,
            data_scope=DataScopeLevel.BRANCH,
        )
        # `GET /v1/employees` (the list endpoint `/app/employees` calls) gates on
        # `EMPLOYEE.VIEW_ALL`, not `EMPLOYEE.VIEW` (`employee/router.py:list_employees` vs.
        # `get_employee`) — without this, a branch manager could fetch a colleague's record by ID
        # but never see their own branch's roster. Both still resolve the same generic
        # `resolve_visible_employee_ids` seam, so `BRANCH` scope filters this list identically to
        # the single-record read.
        await self._repo.insert_role_permission(
            self._session,
            role_id=branch_manager_role.id,
            permission_id=employee_permission_by_code[EMPLOYEE_VIEW_ALL].id,
            data_scope=DataScopeLevel.BRANCH,
        )
        await self._repo.insert_role_permission(
            self._session,
            role_id=branch_manager_role.id,
            permission_id=attendance_permission_by_code[ATTENDANCE_VIEW].id,
            data_scope=DataScopeLevel.BRANCH,
        )
        # Same three approve grants as `REPORTING_MANAGER`, same caveat: the MANAGER/HOD-stage
        # identity check is against `reporting_manager_id`/department-head, a field this role's
        # `BRANCH` scope has no relationship to (branch assignment and reporting line are
        # independent). This grant alone does not make branch-scoped approval work — it only
        # takes effect for a branch manager who is *also* literally set as `reporting_manager_id`
        # for the colleagues they're approving for (a reasonable, common real-world shape: the
        # branch manager doubles as the reporting manager for everyone at that branch), the exact
        # same mechanism `REPORTING_MANAGER` uses. Granted anyway, at `BRANCH` scope for
        # consistency with this role's other grants, so that shape works out of the box the moment
        # it's true, rather than requiring a second role assignment.
        for perm in (
            attendance_permission_by_code[ATTENDANCE_REGULARIZATION_APPROVE],
            attendance_permission_by_code[ATTENDANCE_OVERTIME_APPROVE],
            leave_permission_by_code[LEAVE_APPLICATION_APPROVE],
            leave_permission_by_code[LEAVE_BALANCE_VIEW_ALL],
        ):
            await self._repo.insert_role_permission(
                self._session,
                role_id=branch_manager_role.id,
                permission_id=perm.id,
                data_scope=DataScopeLevel.BRANCH,
            )

        employee_role = await self._repo.insert_role(
            self._session,
            company_id=company_id,
            code=EMPLOYEE_ROLE_CODE,
            name="Employee",
            is_system=True,
            now=now,
        )
        await self._repo.insert_role_permission(
            self._session,
            role_id=employee_role.id,
            permission_id=employee_view_perm.id,
            data_scope=DataScopeLevel.SELF,
        )
        for code in (
            EMPLOYEE_VIEW_COMPENSATION,
            EMPLOYEE_VIEW_STATUTORY,
            EMPLOYEE_VIEW_BANKING,
            EMPLOYEE_VIEW_SENSITIVE,
            EMPLOYEE_VIEW_EXPERIENCE,
            EMPLOYEE_VIEW_NOMINEE,
            EMPLOYEE_VIEW_DOCUMENTS,
        ):
            await self._repo.insert_role_permission(
                self._session,
                role_id=employee_role.id,
                permission_id=employee_permission_by_code[code].id,
                data_scope=DataScopeLevel.SELF,
            )
        # Decision 12 - an employee submits their own leave and sees their own balances and
        # history (cancel/withdraw rides on the submit grant). Nothing administrative.
        for leave_code in (LEAVE_APPLICATION_SUBMIT, LEAVE_BALANCE_VIEW):
            await self._repo.insert_role_permission(
                self._session,
                role_id=employee_role.id,
                permission_id=leave_permission_by_code[leave_code].id,
                data_scope=DataScopeLevel.SELF,
            )
        # API audit C-1 — every employee records and reviews their own attendance. All three codes
        # are SELF-scoped: `/attendance/punches/me`, the face-punch routes and self-submitted
        # regularizations never take a target employee, and reads are narrowed to the caller's own
        # record by `resolve_visible_employee_ids`. Deliberately NOT granted: `PUNCH_ON_BEHALF`,
        # `VIEW_ALL`, `REGULARIZATION_REQUEST_ON_BEHALF` or any approve/manage code. Existing
        # tenants are backfilled by migration 20261020090000.
        for attendance_code in (
            ATTENDANCE_PUNCH,
            ATTENDANCE_VIEW,
            ATTENDANCE_REGULARIZATION_REQUEST,
        ):
            await self._repo.insert_role_permission(
                self._session,
                role_id=employee_role.id,
                permission_id=attendance_permission_by_code[attendance_code].id,
                data_scope=DataScopeLevel.SELF,
            )
        # Payroll 5.4 — every employee reads their own finalised payslips.
        for perm in payroll_permission_rows:
            if perm.code == PAYROLL_PAYSLIP_VIEW_OWN:
                await self._repo.insert_role_permission(
                    self._session,
                    role_id=employee_role.id,
                    permission_id=perm.id,
                    data_scope=DataScopeLevel.SELF,
                )

        await self._repo.insert_setup_progress(self._session, company_id=company_id, now=now)

        plan = await self._repo.get_plan_by_code(self._session, code=DEFAULT_TRIAL_PLAN_CODE)
        if plan is not None:
            await self._repo.insert_subscription(
                self._session,
                company_id=company_id,
                plan_id=plan.id,
                status="TRIALING",
                trial_ends_at=trial_ends_at,
                now=now,
            )

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=user_id,
            action="COMPANY_REGISTERED",
            entity_type="company",
            entity_id=company_id,
            ip=ip_address,
            user_agent=user_agent,
        )

        tokens = await self._identity.issue_tokens_for(
            user_id=user_id,
            company_id=company_id,
            companies=[CompanySummary(id=company_id, name=company.name, is_primary=True)],
            ip_address=ip_address,
            user_agent=user_agent,
            audit_action="COMPANY_REGISTERED",
        )
        # SEC-09 (RELEASE_HARDENING_PHASE_3A) — the registrant's session above is unaffected by
        # this (registration itself doesn't change); a *subsequent* login is blocked until this
        # link is used (`IdentityService.login`). Issued after the session so a delivery failure
        # (best-effort — see the method's own docstring) never turns a successful registration
        # into an error response.
        await self._identity.send_verification_email(
            user_id=user_id, email=admin_email, first_name=body.admin_first_name
        )
        return tokens

    async def get_company_profile(self, company_id: UUID) -> CompanyProfileRead:
        company = await self._repo.get_company(self._session, company_id=company_id)
        if company is None:
            raise NotFoundError("Resource not found")
        return company_to_profile_read(company)

    async def update_company_profile(
        self,
        company_id: UUID,
        patch: CompanyProfileUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CompanyProfileRead:
        company = await self._repo.get_company(self._session, company_id=company_id)
        if company is None:
            raise NotFoundError("Resource not found")

        if company.status == "SUSPENDED":
            raise CompanyWriteBlockedError()

        before_profile = company_to_profile_read(company)
        before_json = profile_to_audit_dict(before_profile)

        if patch.currency is not None and patch.currency != company.currency:
            if company.status != "TRIAL":
                raise CurrencyLockedError()

        if patch.timezone is not None and patch.timezone != company.timezone:
            await self._assert_timezone_change_allowed(company_id, employee_ids=None)

        if count_working_days(company, patch) < 1:
            raise InvalidWorkingDaysError()

        values = build_update_values(company, patch)
        if not values:
            return before_profile

        now = datetime.now(UTC)
        updated = await self._repo.update_company(
            self._session,
            company_id=company_id,
            values=values,
            expected_version=expected_version,
            updated_by=actor_user_id,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_company(self._session, company_id=company_id)
            if current is None:
                raise NotFoundError("Resource not found")
            current_profile = company_to_profile_read(current)
            raise StaleResourceError(
                "The company profile has been modified by another request",
                current=profile_to_audit_dict(current_profile),
            )

        after_profile = company_to_profile_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="UPDATED",
            entity_type="company",
            entity_id=company_id,
            before=before_json,
            after=profile_to_audit_dict(after_profile),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_profile

    async def _assert_timezone_change_allowed(
        self, company_id: UUID, *, employee_ids: list[UUID] | None
    ) -> None:
        """`TZ-01`/`DEC-TZ-04` (SELECTED, execution gate §12) — was a documented no-op hook
        (Domain Model §5.5) until this phase; now `async` because it needs an existence query
        against computed attendance (`ED-11`), which the previous synchronous stub could not
        perform.

        `employee_ids=None` — a company-scope change (`update_company_profile`): blocked if any
        attendance exists anywhere in the company. `employee_ids=[...]` — a branch-scope change
        (`update_branch`): the caller has already walked `EmployeeAssignment` history for every
        employee ever assigned to that branch (`ED-12`, not just the current roster — an employee
        who has since transferred away still has historical days computed in the old zone).

        Local, function-scoped import — mirrors the established reverse-direction precedent
        (`policy_exists`, above, and `employee/service.py` importing `organisation.service`
        locally): `attendance` already imports `organisation` at module scope for shift/branch/
        company resolution, so a module-level import in the other direction would be circular."""
        from hrms.modules.attendance.service import AttendanceService

        attendance_service = AttendanceService(self._session)
        blocked = await attendance_service.has_computed_attendance_blocking_timezone_change(
            company_id, employee_ids=employee_ids
        )
        if blocked:
            raise TimezoneChangeBlockedError()

    async def get_setup_progress(self, company_id: UUID) -> CompanySetupProgressSummary:
        progress = await self._repo.get_setup_progress(self._session, company_id=company_id)
        if progress is None:
            # This resource always exists once a company does (created at registration,
            # see 04_API_Design.md §5) — reaching here would indicate a data-integrity bug,
            # not a normal client error, mirroring get_company_profile's own NotFoundError use.
            raise NotFoundError("Resource not found")
        # Captured before `update_setup_progress` runs below: that bulk UPDATE
        # auto-synchronizes the session's identity map, mutating this same
        # already-loaded `progress` instance in place — reading `.status` off it
        # afterwards would silently observe the *new* value, not the prior one.
        previous_status = progress.status
        previous_completed_at = progress.completed_at

        completed_codes = [
            step.code
            for step in SETUP_STEPS
            if await step.check(self._repo, self._session, company_id)
        ]
        all_complete = len(completed_codes) == len(SETUP_STEPS)
        status = "COMPLETE" if all_complete else "IN_PROGRESS"
        # current_step is a UX hint only, never gates access (Domain Model §2.2) — derived
        # here as the first incomplete step, since no wizard-navigation endpoint exists to
        # set it explicitly in V1.
        current_step = next(
            (step.code for step in SETUP_STEPS if step.code not in completed_codes), None
        )

        now = datetime.now(UTC)
        completed_at = now if all_complete else None
        if all_complete and previous_status == "COMPLETE":
            completed_at = previous_completed_at

        updated = await self._repo.update_setup_progress(
            self._session,
            company_id=company_id,
            steps_completed=completed_codes,
            current_step=current_step,
            status=status,
            completed_at=completed_at,
            now=now,
        )

        if all_complete and previous_status != "COMPLETE":
            await self._repo.mark_company_onboarded(
                self._session, company_id=company_id, onboarded_at=now
            )

        steps = [
            SetupStepSummary(
                code=step.code, label=step.label, is_complete=step.code in completed_codes
            )
            for step in SETUP_STEPS
        ]
        return setup_progress_to_summary(updated, steps)

    async def get_subscription_summary(self, company_id: UUID) -> SubscriptionSummary:
        """Resolve live plan + effective feature flags (04_API_Design.md §6).

        Feature resolution (Domain Model §5.10):
        - Plan features seed the effective set with ``source=PLAN``.
        - ``overrides_plan=true`` company flags win even when the plan lacks the feature
          (``source=COMPANY_OVERRIDE``).
        - ``overrides_plan=false`` company flags may only toggle features already on the
          plan; orphans are ignored on read (write-time rejection is out of scope until a
          feature-flag write API exists).
        """
        subscription = await self._repo.get_active_subscription(
            self._session, company_id=company_id
        )
        if subscription is None:
            raise NotFoundError("Resource not found")

        plan = await self._repo.get_plan(self._session, plan_id=subscription.plan_id)
        if plan is None:
            raise NotFoundError("Resource not found")

        plan_features = await self._repo.get_plan_features(self._session, plan_id=plan.id)
        company_flags = await self._repo.get_company_feature_flags(
            self._session, company_id=company_id
        )

        features_by_code: dict[str, FeatureFlagView] = {}
        plan_seat_limit: int | None = None

        for feature in plan_features:
            features_by_code[feature.feature_code] = FeatureFlagView(
                code=feature.feature_code,
                is_enabled=feature.is_enabled,
                source="PLAN",
                limit_value=feature.limit_value,
            )
            if feature.feature_code == SEAT_LIMIT_FEATURE_CODE:
                plan_seat_limit = feature.limit_value

        for flag in company_flags:
            if flag.overrides_plan:
                existing = features_by_code.get(flag.feature_code)
                features_by_code[flag.feature_code] = FeatureFlagView(
                    code=flag.feature_code,
                    is_enabled=flag.is_enabled,
                    source="COMPANY_OVERRIDE",
                    limit_value=existing.limit_value if existing is not None else None,
                )
            elif flag.feature_code in features_by_code:
                existing = features_by_code[flag.feature_code]
                features_by_code[flag.feature_code] = FeatureFlagView(
                    code=flag.feature_code,
                    is_enabled=flag.is_enabled,
                    source="PLAN",
                    limit_value=existing.limit_value,
                )

        seat_limit = (
            subscription.seat_limit_override
            if subscription.seat_limit_override is not None
            else plan_seat_limit
        )

        return SubscriptionSummary(
            plan=PlanSummary(code=plan.code, name=plan.name),
            status=subscription.status,
            current_period_start=_format_optional_timestamp(subscription.current_period_start),
            current_period_end=_format_optional_timestamp(subscription.current_period_end),
            trial_ends_at=_format_optional_timestamp(subscription.trial_ends_at),
            seat_limit=seat_limit,
            features=sorted(features_by_code.values(), key=lambda item: item.code),
        )

    async def get_dashboard_summary(self, company_id: UUID) -> CompanyDashboardSummary:
        """Company Admin dashboard aggregation (04_API_Design.md §7)."""
        setup = await self.get_setup_progress(company_id)
        steps_completed = sum(1 for step in setup.steps if step.is_complete)

        subscription_block: DashboardSubscription | None = None
        try:
            subscription = await self.get_subscription_summary(company_id)
            subscription_block = DashboardSubscription(
                plan_code=subscription.plan.code,
                status=subscription.status,
                trial_ends_at=subscription.trial_ends_at,
            )
        except NotFoundError:
            subscription_block = None

        branches = await self._repo.list_branches(self._session, company_id=company_id)
        departments = await self._repo.list_departments(self._session, company_id=company_id)
        employee_count = await self._employee_repo.count_employees(
            self._session, company_id=company_id
        )

        return CompanyDashboardSummary(
            setup_progress=DashboardSetupProgress(
                status=setup.status,
                steps_completed=steps_completed,
                steps_total=len(setup.steps),
            ),
            subscription=subscription_block,
            branch_count=len(branches),
            department_count=len(departments),
            employee_count=employee_count,
        )

    async def create_legal_entity(
        self,
        company_id: UUID,
        body: LegalEntityCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LegalEntityRead:
        limit = self._settings.max_legal_entities_per_company
        if (
            limit > 0
            and await self._repo.count_legal_entities(self._session, company_id=company_id) >= limit
        ):
            raise CompanyLimitReachedError(limit=limit)

        now = datetime.now(UTC)
        entity_id = uuid4()
        entity = await self._repo.insert_legal_entity(
            self._session,
            data={
                "id": entity_id,
                "company_id": company_id,
                "name": body.name,
                "registered_address": body.registered_address,
                "pan": body.pan,
                "tan": body.tan,
                "cin": body.cin,
                "gstin": body.gstin,
                "pf_code": body.pf_code,
                "esi_code": body.esi_code,
                "lwf_reg": body.lwf_reg,
                "signatory_name": body.signatory_name,
                "signatory_designation": body.signatory_designation,
                "signature_image_url": body.signature_image_url,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = legal_entity_to_read(entity)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEGAL_ENTITY_CREATED",
            entity_type="legal_entity",
            entity_id=entity_id,
            after=legal_entity_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_legal_entities(self, company_id: UUID) -> list[LegalEntityRead]:
        entities = await self._repo.list_legal_entities(self._session, company_id=company_id)
        return [legal_entity_to_read(entity) for entity in entities]

    async def get_legal_entity(self, company_id: UUID, entity_id: UUID) -> LegalEntityRead:
        entity = await self._repo.get_legal_entity(
            self._session, company_id=company_id, entity_id=entity_id
        )
        if entity is None:
            raise NotFoundError("Resource not found")
        return legal_entity_to_read(entity)

    async def update_legal_entity(
        self,
        company_id: UUID,
        entity_id: UUID,
        patch: LegalEntityUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LegalEntityRead:
        entity = await self._repo.get_legal_entity(
            self._session, company_id=company_id, entity_id=entity_id
        )
        if entity is None:
            raise NotFoundError("Resource not found")

        before_read = legal_entity_to_read(entity)
        # Captured before `update_legal_entity` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `entity` instance in place (same gotcha documented on `update_setup_progress`
        # above) — reading `.is_active` off it afterwards would silently observe the *new*
        # value, not the prior one.
        was_active_before = entity.is_active

        deactivating = patch.is_active is False and was_active_before is True
        if deactivating:
            active_branches = await self._repo.count_active_branches_for_legal_entity(
                self._session, entity_id=entity_id
            )
            if active_branches > 0:
                raise LegalEntityDeactivationBlockedError(active_branch_count=active_branches)

        values = build_legal_entity_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_legal_entity(
            self._session,
            company_id=company_id,
            entity_id=entity_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_legal_entity(
                self._session, company_id=company_id, entity_id=entity_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = legal_entity_to_read(current)
            raise StaleResourceError(
                "This legal entity has been modified by another request",
                current=legal_entity_to_audit_dict(current_read),
            )

        after_read = legal_entity_to_read(updated)
        action = (
            "LEGAL_ENTITY_DEACTIVATED"
            if deactivating
            else "LEGAL_ENTITY_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "LEGAL_ENTITY_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="legal_entity",
            entity_id=entity_id,
            before=legal_entity_to_audit_dict(before_read),
            after=legal_entity_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_legal_entity(
        self,
        company_id: UUID,
        entity_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LegalEntityRead:
        """Semantic wrapper around `update_legal_entity` for `DELETE /legal-entities/{id}` —
        never a hard delete (FR-ORG-014); flips `is_active` to False via the same
        business-rule path (blocked-branch check, audit, optimistic concurrency)."""
        return await self.update_legal_entity(
            company_id,
            entity_id,
            LegalEntityUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _assert_legal_entity_ownership(self, company_id: UUID, legal_entity_id: UUID) -> None:
        """A Branch may only reference a Legal Entity that exists and belongs to the same
        tenant — the FK constraint alone would surface an opaque `IntegrityError`/500 for
        a bad id, and would not catch a cross-tenant reference at all (RLS would just make
        the FK lookup fail the same way as a nonexistent id, which is the desired 422)."""
        entity = await self._repo.get_legal_entity(
            self._session, company_id=company_id, entity_id=legal_entity_id
        )
        if entity is None:
            raise InvalidLegalEntityError()

    async def create_branch(
        self,
        company_id: UUID,
        body: BranchCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BranchRead:
        await self._assert_legal_entity_ownership(company_id, body.legal_entity_id)

        now = datetime.now(UTC)
        branch_id = uuid4()
        branch = await self._repo.insert_branch(
            self._session,
            data={
                "id": branch_id,
                "company_id": company_id,
                "legal_entity_id": body.legal_entity_id,
                "name": body.name,
                "code": await self._repo.next_auto_code(
                    self._session, model=Branch, company_id=company_id, prefix="BR"
                ),
                "address_line1": body.address_line1,
                "address_line2": body.address_line2,
                "city": body.city,
                "state_code": body.state_code,
                "pincode": body.pincode,
                "timezone": body.timezone,
                "latitude": body.latitude,
                "longitude": body.longitude,
                "geofence_radius_m": body.geofence_radius_m,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = branch_to_read(branch)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="BRANCH_CREATED",
            entity_type="branch",
            entity_id=branch_id,
            after=branch_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_branches(self, company_id: UUID) -> list[BranchRead]:
        branches = await self._repo.list_branches(self._session, company_id=company_id)
        return [branch_to_read(branch) for branch in branches]

    async def get_branch(self, company_id: UUID, branch_id: UUID) -> BranchRead:
        branch = await self._repo.get_branch(
            self._session, company_id=company_id, branch_id=branch_id
        )
        if branch is None:
            raise NotFoundError("Resource not found")
        return branch_to_read(branch)

    async def _assert_master_not_in_use(
        self, company_id: UUID, *, kind: str, column: str, master_id: UUID
    ) -> None:
        """Decision 2 — refuse to deactivate a department/designation/grade/shift that active
        employees still depend on. `employee.service` is the only surface consulted, via the same
        lazy import the branch timezone guard uses."""
        from hrms.modules.employee.service import EmployeeAssignmentService

        company = await self._repo.get_company(self._session, company_id=company_id)
        as_of = business_today(company.timezone) if company is not None else date.today()
        count = await EmployeeAssignmentService(self._session).count_active_employees_for_master(
            company_id, column=column, master_id=master_id, as_of=as_of
        )
        if count > 0:
            raise MasterDataInUseError(kind=kind, active_employee_count=count)

    async def _assert_no_workplace_authorizations(self, company_id: UUID, branch_id: UUID) -> None:
        """Attendance geofencing: employees authorised to punch at this branch (beyond their own
        assignment) would be left with no approved workplace if it were deactivated. Lazy import,
        same cross-module-seam convention as `_assert_master_not_in_use`."""
        from hrms.modules.attendance.geofence_repository import GeofenceRepository

        counts = await GeofenceRepository().authorization_counts_by_branch(
            self._session, company_id=company_id
        )
        if counts.get(branch_id, 0) > 0:
            raise BranchHasWorkplaceAuthorizationsError(authorization_count=counts[branch_id])

    async def update_branch(
        self,
        company_id: UUID,
        branch_id: UUID,
        patch: BranchUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BranchRead:
        branch = await self._repo.get_branch(
            self._session, company_id=company_id, branch_id=branch_id
        )
        if branch is None:
            raise NotFoundError("Resource not found")

        if patch.legal_entity_id is not None:
            await self._assert_legal_entity_ownership(company_id, patch.legal_entity_id)

        if patch.timezone is not None and patch.timezone != branch.timezone:
            # `TZ-01`/`DEC-TZ-04` (SELECTED, execution gate §12) — `update_branch` had NO guard
            # at all before this phase (confirmed: only `update_company_profile` had a call site,
            # and that call site was itself a no-op). `ED-12`: scope is every employee ever
            # assigned to this branch, not the current roster.
            from hrms.modules.employee.service import EmployeeAssignmentService

            branch_employee_ids = await EmployeeAssignmentService(
                self._session
            ).list_distinct_employee_ids_for_branch(company_id, branch_id)
            await self._assert_timezone_change_allowed(company_id, employee_ids=branch_employee_ids)

        before_read = branch_to_read(branch)
        # Captured before `update_branch` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `branch` instance in place (same gotcha documented on `update_legal_entity`) —
        # reading `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = branch.is_active

        deactivating = patch.is_active is False and was_active_before is True
        if deactivating:
            active_departments = await self._repo.count_active_departments_for_branch(
                self._session, branch_id=branch_id
            )
            if active_departments > 0:
                raise BranchDeactivationBlockedError(active_department_count=active_departments)
            # The Employee half of FR-ORG-014: active employees still placed here block it too.
            await self._assert_master_not_in_use(
                company_id, kind="branch", column="branch_id", master_id=branch_id
            )
            await self._assert_no_workplace_authorizations(company_id, branch_id)

        values = build_branch_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_branch(
            self._session,
            company_id=company_id,
            branch_id=branch_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_branch(
                self._session, company_id=company_id, branch_id=branch_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = branch_to_read(current)
            raise StaleResourceError(
                "This branch has been modified by another request",
                current=branch_to_audit_dict(current_read),
            )

        after_read = branch_to_read(updated)
        action = (
            "BRANCH_DEACTIVATED"
            if deactivating
            else "BRANCH_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "BRANCH_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="branch",
            entity_id=branch_id,
            before=branch_to_audit_dict(before_read),
            after=branch_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_branch(
        self,
        company_id: UUID,
        branch_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BranchRead:
        """Semantic wrapper around `update_branch` for `DELETE /branches/{id}` — never a
        hard delete (FR-ORG-014); flips `is_active` to False via the same business-rule
        path (blocked-department check, audit, optimistic concurrency)."""
        return await self.update_branch(
            company_id,
            branch_id,
            BranchUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _assert_branch_ownership(self, company_id: UUID, branch_id: UUID) -> None:
        """A Department's `branch_id`, when provided, must belong to the same tenant —
        mirrors `_assert_legal_entity_ownership` for Branch's own `legal_entity_id`."""
        branch = await self._repo.get_branch(
            self._session, company_id=company_id, branch_id=branch_id
        )
        if branch is None:
            raise InvalidBranchError()

    async def _assert_department_head_reference(
        self, company_id: UUID, head_employee_id: UUID
    ) -> None:
        """A Department's `head_employee_id`, when provided, must reference an existing,
        same-tenant employee — repo-level existence check, same shape as Employee's own
        `_assert_manager_reference` (cheaper than the full `EmployeeService`, no data-scope
        resolution needed for a plain existence check). `head_employee_id` has carried a real
        DB-level FK to `employee.id` since migration 20260813140000 — this is the first slice
        to validate it at the application layer too (LD-23)."""
        from hrms.modules.employee.repository import EmployeeRepository

        employee = await EmployeeRepository().get_employee(
            self._session, company_id=company_id, employee_id=head_employee_id
        )
        if employee is None:
            raise InvalidDepartmentHeadError()

    async def _validate_department_parent(
        self, company_id: UUID, own_id: UUID | None, parent_id: UUID
    ) -> None:
        """FR-ORG-005 — hierarchy must reject cycles and cap depth at
        `DEPARTMENT_MAX_DEPTH`. `own_id` is `None` on create (a brand-new department can
        never already be its own ancestor)."""
        if own_id is not None and parent_id == own_id:
            raise DepartmentCycleDetectedError()

        parent = await self._repo.get_department(
            self._session, company_id=company_id, department_id=parent_id
        )
        if parent is None:
            raise InvalidParentDepartmentError()

        ancestor_chain = await self._repo.get_department_ancestor_chain(
            self._session, company_id=company_id, start_id=parent_id
        )
        if own_id is not None and own_id in ancestor_chain:
            raise DepartmentCycleDetectedError()
        if len(ancestor_chain) >= DEPARTMENT_MAX_DEPTH:
            raise DepartmentMaxDepthExceededError()

    async def create_department(
        self,
        company_id: UUID,
        body: DepartmentCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DepartmentRead:
        if body.branch_id is not None:
            await self._assert_branch_ownership(company_id, body.branch_id)
        if body.parent_id is not None:
            await self._validate_department_parent(company_id, None, body.parent_id)
        if body.head_employee_id is not None:
            await self._assert_department_head_reference(company_id, body.head_employee_id)

        now = datetime.now(UTC)
        department_id = uuid4()
        department = await self._repo.insert_department(
            self._session,
            data={
                "id": department_id,
                "company_id": company_id,
                "branch_id": body.branch_id,
                "parent_id": body.parent_id,
                "name": body.name,
                "code": await self._repo.next_auto_code(
                    self._session, model=Department, company_id=company_id, prefix="DEPT"
                ),
                "head_employee_id": body.head_employee_id,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = department_to_read(department)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="DEPARTMENT_CREATED",
            entity_type="department",
            entity_id=department_id,
            after=department_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_departments(self, company_id: UUID) -> list[DepartmentRead]:
        departments = await self._repo.list_departments(self._session, company_id=company_id)
        return [department_to_read(department) for department in departments]

    async def get_department(self, company_id: UUID, department_id: UUID) -> DepartmentRead:
        department = await self._repo.get_department(
            self._session, company_id=company_id, department_id=department_id
        )
        if department is None:
            raise NotFoundError("Resource not found")
        return department_to_read(department)

    async def update_department(
        self,
        company_id: UUID,
        department_id: UUID,
        patch: DepartmentUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DepartmentRead:
        department = await self._repo.get_department(
            self._session, company_id=company_id, department_id=department_id
        )
        if department is None:
            raise NotFoundError("Resource not found")

        if patch.branch_id is not None:
            await self._assert_branch_ownership(company_id, patch.branch_id)
        if patch.parent_id is not None:
            await self._validate_department_parent(company_id, department_id, patch.parent_id)
        if patch.head_employee_id is not None:
            await self._assert_department_head_reference(company_id, patch.head_employee_id)

        before_read = department_to_read(department)
        # Captured before `update_department` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `department` instance in place (same gotcha documented on `update_branch`) —
        # reading `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = department.is_active

        # No documented dependency-blocking rule applies to Department deactivation this
        # slice (FR-ORG-014's only named blocker — active employees — can't be checked
        # since Employee doesn't exist; no doc names sub-departments/Designations as
        # blockers either, unlike Branch's own explicit "blocked by active department"
        # gloss). See docs/modules/department/00_DEPARTMENT_AUDIT.md §5.3/§8.1.
        deactivating = patch.is_active is False and was_active_before is True
        if deactivating:
            await self._assert_master_not_in_use(
                company_id, kind="department", column="department_id", master_id=department_id
            )

        values = build_department_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_department(
            self._session,
            company_id=company_id,
            department_id=department_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_department(
                self._session, company_id=company_id, department_id=department_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = department_to_read(current)
            raise StaleResourceError(
                "This department has been modified by another request",
                current=department_to_audit_dict(current_read),
            )

        after_read = department_to_read(updated)
        action = (
            "DEPARTMENT_DEACTIVATED"
            if deactivating
            else "DEPARTMENT_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "DEPARTMENT_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="department",
            entity_id=department_id,
            before=department_to_audit_dict(before_read),
            after=department_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_department(
        self,
        company_id: UUID,
        department_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DepartmentRead:
        """Semantic wrapper around `update_department` for `DELETE /departments/{id}` —
        never a hard delete (FR-ORG-014); flips `is_active` to False via the same
        business-rule path (audit, optimistic concurrency)."""
        return await self.update_department(
            company_id,
            department_id,
            DepartmentUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _assert_department_ownership(self, company_id: UUID, department_id: UUID) -> None:
        """A Designation's `department_id`, when provided, must belong to the same tenant —
        mirrors `_assert_branch_ownership` for Designation's own `department_id`."""
        department = await self._repo.get_department(
            self._session, company_id=company_id, department_id=department_id
        )
        if department is None:
            raise InvalidDepartmentError()

    async def _assert_grade_ownership(self, company_id: UUID, grade_id: UUID) -> None:
        """A Designation's `grade_id`, when provided, must belong to the same tenant —
        mirrors `_assert_department_ownership` for Designation's own `department_id`. See
        docs/modules/grade/00_GRADE_AUDIT.md §3/§6.7."""
        grade = await self._repo.get_grade(self._session, company_id=company_id, grade_id=grade_id)
        if grade is None:
            raise InvalidGradeError()

    async def create_designation(
        self,
        company_id: UUID,
        body: DesignationCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DesignationRead:
        if body.department_id is not None:
            await self._assert_department_ownership(company_id, body.department_id)
        if body.grade_id is not None:
            await self._assert_grade_ownership(company_id, body.grade_id)

        now = datetime.now(UTC)
        designation_id = uuid4()
        designation = await self._repo.insert_designation(
            self._session,
            data={
                "id": designation_id,
                "company_id": company_id,
                "department_id": body.department_id,
                "grade_id": body.grade_id,
                "title": body.title,
                "code": await self._repo.next_auto_code(
                    self._session, model=Designation, company_id=company_id, prefix="DSG"
                ),
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = designation_to_read(designation)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="DESIGNATION_CREATED",
            entity_type="designation",
            entity_id=designation_id,
            after=designation_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_designations(self, company_id: UUID) -> list[DesignationRead]:
        designations = await self._repo.list_designations(self._session, company_id=company_id)
        return [designation_to_read(designation) for designation in designations]

    async def get_designation(self, company_id: UUID, designation_id: UUID) -> DesignationRead:
        designation = await self._repo.get_designation(
            self._session, company_id=company_id, designation_id=designation_id
        )
        if designation is None:
            raise NotFoundError("Resource not found")
        return designation_to_read(designation)

    async def update_designation(
        self,
        company_id: UUID,
        designation_id: UUID,
        patch: DesignationUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DesignationRead:
        designation = await self._repo.get_designation(
            self._session, company_id=company_id, designation_id=designation_id
        )
        if designation is None:
            raise NotFoundError("Resource not found")

        if patch.department_id is not None:
            await self._assert_department_ownership(company_id, patch.department_id)
        if patch.grade_id is not None:
            await self._assert_grade_ownership(company_id, patch.grade_id)

        before_read = designation_to_read(designation)
        # Captured before `update_designation` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `designation` instance in place (same gotcha documented on `update_department`) —
        # reading `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = designation.is_active

        # No documented dependency-blocking rule applies to Designation deactivation this
        # slice (FR-ORG-014's only named blocker — active employees — can't be checked
        # since Employee doesn't exist; the only other named blocker, a
        # `next_designation_id` career-path reference, is not implementable this slice
        # since `next_designation_id` itself has no UI control — see
        # docs/modules/designation/00_DESIGNATION_AUDIT.md §5.3/§5.4).
        deactivating = patch.is_active is False and was_active_before is True
        if deactivating:
            await self._assert_master_not_in_use(
                company_id, kind="designation", column="designation_id", master_id=designation_id
            )

        values = build_designation_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_designation(
            self._session,
            company_id=company_id,
            designation_id=designation_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_designation(
                self._session, company_id=company_id, designation_id=designation_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = designation_to_read(current)
            raise StaleResourceError(
                "This designation has been modified by another request",
                current=designation_to_audit_dict(current_read),
            )

        after_read = designation_to_read(updated)
        action = (
            "DESIGNATION_DEACTIVATED"
            if deactivating
            else "DESIGNATION_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "DESIGNATION_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="designation",
            entity_id=designation_id,
            before=designation_to_audit_dict(before_read),
            after=designation_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_designation(
        self,
        company_id: UUID,
        designation_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DesignationRead:
        """Semantic wrapper around `update_designation` for `DELETE /designations/{id}` —
        never a hard delete (FR-ORG-014); flips `is_active` to False via the same
        business-rule path (audit, optimistic concurrency)."""
        return await self.update_designation(
            company_id,
            designation_id,
            DesignationUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    def _validate_ctc_range(self, min_ctc: int | None, max_ctc: int | None) -> None:
        """Sprint 3 Task 3.3.1's own documented rule: `min_ctc <= max_ctc` when both are
        present (docs/modules/grade/00_GRADE_AUDIT.md §6.4)."""
        if min_ctc is not None and max_ctc is not None and min_ctc > max_ctc:
            raise InvalidCtcRangeError()

    async def create_grade(
        self,
        company_id: UUID,
        body: GradeCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> GradeRead:
        self._validate_ctc_range(body.min_ctc, body.max_ctc)

        now = datetime.now(UTC)
        grade_id = uuid4()
        try:
            grade = await self._repo.insert_grade(
                self._session,
                data={
                    "id": grade_id,
                    "company_id": company_id,
                    "code": await self._repo.next_auto_code(
                        self._session, model=Grade, company_id=company_id, prefix="GR"
                    ),
                    "name": body.name,
                    "level": body.level,
                    "min_ctc": body.min_ctc,
                    "max_ctc": body.max_ctc,
                    "notice_period_days": body.notice_period_days,
                    "probation_days": body.probation_days,
                    "approval_limit": body.approval_limit,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            # `grade_company_id_code_key UNIQUE (company_id, code)` predates this slice
            # (scripts/sql/001_init_schema.sql) — the real backstop for a race between two
            # concurrent creates with the same code, same pattern as `register_company`'s
            # duplicate-email handling.
            raise GradeCodeAlreadyExistsError() from exc

        read = grade_to_read(grade)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="GRADE_CREATED",
            entity_type="grade",
            entity_id=grade_id,
            after=grade_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_grades(self, company_id: UUID) -> list[GradeRead]:
        grades = await self._repo.list_grades(self._session, company_id=company_id)
        return [grade_to_read(grade) for grade in grades]

    async def get_grade(self, company_id: UUID, grade_id: UUID) -> GradeRead:
        grade = await self._repo.get_grade(self._session, company_id=company_id, grade_id=grade_id)
        if grade is None:
            raise NotFoundError("Resource not found")
        return grade_to_read(grade)

    async def update_grade(
        self,
        company_id: UUID,
        grade_id: UUID,
        patch: GradeUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> GradeRead:
        grade = await self._repo.get_grade(self._session, company_id=company_id, grade_id=grade_id)
        if grade is None:
            raise NotFoundError("Resource not found")

        effective_min = patch.min_ctc if "min_ctc" in patch.model_fields_set else grade.min_ctc
        effective_max = patch.max_ctc if "max_ctc" in patch.model_fields_set else grade.max_ctc
        self._validate_ctc_range(effective_min, effective_max)

        before_read = grade_to_read(grade)
        # Captured before `update_grade` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `grade` instance in place (same gotcha documented on `update_designation`) —
        # reading `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = grade.is_active

        # No documented dependency-blocking rule applies to Grade deactivation this slice
        # (FR-ORG-014's only named blocker — active employees — can't be checked since
        # Employee doesn't exist; no document names an active Designation referencing a
        # Grade as a blocker either — see docs/modules/grade/00_GRADE_AUDIT.md §6.3).
        deactivating = patch.is_active is False and was_active_before is True
        if deactivating:
            await self._assert_master_not_in_use(
                company_id, kind="grade", column="grade_id", master_id=grade_id
            )

        values = build_grade_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        try:
            updated = await self._repo.update_grade(
                self._session,
                company_id=company_id,
                grade_id=grade_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
        except IntegrityError as exc:
            raise GradeCodeAlreadyExistsError() from exc
        if updated is None:
            current = await self._repo.get_grade(
                self._session, company_id=company_id, grade_id=grade_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = grade_to_read(current)
            raise StaleResourceError(
                "This grade has been modified by another request",
                current=grade_to_audit_dict(current_read),
            )

        after_read = grade_to_read(updated)
        action = (
            "GRADE_DEACTIVATED"
            if deactivating
            else "GRADE_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "GRADE_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="grade",
            entity_id=grade_id,
            before=grade_to_audit_dict(before_read),
            after=grade_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_grade(
        self,
        company_id: UUID,
        grade_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> GradeRead:
        """Semantic wrapper around `update_grade` for `DELETE /grades/{id}` — never a hard
        delete (FR-ORG-014); flips `is_active` to False via the same business-rule path
        (audit, optimistic concurrency)."""
        return await self.update_grade(
            company_id,
            grade_id,
            GradeUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def create_shift(
        self,
        company_id: UUID,
        body: ShiftCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftRead:
        """W2 — `Shift` is identity-only now (name/code/active); the nine legacy schedule/
        evaluation columns are frozen-zero placeholders for new rows (never read again by W2+
        code — see `ShiftRead`'s field docstrings). A new shift is meaningless without a
        schedule, so an initial empty DRAFT `ShiftVersion` is created in the same transaction
        rather than requiring a mandatory second round-trip. The `code` is always auto-assigned
        (`SHF-001`, `SHF-002`, …); the client never supplies one."""
        now = datetime.now(UTC)
        shift_id = uuid4()
        code = await self._repo.next_auto_shift_code(self._session, company_id=company_id)
        shift = await self._repo.insert_shift(
            self._session,
            data={
                "id": shift_id,
                "company_id": company_id,
                "name": body.name,
                "code": code,
                "start_time": time(0, 0),
                "end_time": time(0, 0),
                "break_minutes_paid": 0,
                "break_minutes_unpaid": 0,
                "grace_in_minutes": 0,
                "grace_out_minutes": 0,
                "half_day_threshold_hours": None,
                "min_hours_full_day": None,
                "is_night_shift": False,
                "is_cross_midnight": False,
                "is_ot_eligible": False,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        draft = await self._shift_version_repo.insert(
            self._session,
            data=self._empty_draft_shift_version_data(
                company_id=company_id, shift_id=shift_id, now=now
            ),
        )
        read = shift_to_read(shift, draft_version_id=draft.id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_CREATED",
            entity_type="shift",
            entity_id=shift_id,
            after=shift_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        draft_read = shift_version_to_read(draft, [], [])
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_VERSION_CREATED",
            entity_type="shift_version",
            entity_id=draft.id,
            after=shift_version_to_audit_dict(draft_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    def _empty_draft_shift_version_data(
        self, *, company_id: UUID, shift_id: UUID, now: datetime
    ) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "company_id": company_id,
            "shift_id": shift_id,
            "status": "DRAFT",
            "version": 1,
            "effective_from": None,
            "effective_to": None,
            "shift_type": None,
            "timezone": None,
            "start_time": None,
            "end_time": None,
            "window_start": None,
            "window_end": None,
            "core_start": None,
            "core_end": None,
            "required_minutes": None,
            "scheduled_minutes": None,
            "min_scheduled_minutes": None,
            "max_scheduled_minutes": None,
            "is_night_shift": False,
            "is_cross_midnight": False,
            "is_ot_eligible": False,
            "operates_on_holiday": False,
            "operates_on_weekly_off": False,
            "weekly_off_pattern_id": None,
            "publish_reason": None,
            "published_at": None,
            "published_by": None,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }

    async def list_shifts(self, company_id: UUID) -> list[ShiftRead]:
        shifts = await self._repo.list_shifts(self._session, company_id=company_id)
        versions = await self._shift_version_repo.list_open_and_draft_for_shifts(
            self._session, company_id=company_id, shift_ids=[shift.id for shift in shifts]
        )
        current_by_shift: dict[UUID, UUID] = {}
        draft_by_shift: dict[UUID, UUID] = {}
        for version in versions:
            if version.status == "PUBLISHED":
                current_by_shift[version.shift_id] = version.id
            else:
                draft_by_shift[version.shift_id] = version.id
        return [
            shift_to_read(
                shift,
                current_version_id=current_by_shift.get(shift.id),
                draft_version_id=draft_by_shift.get(shift.id),
            )
            for shift in shifts
        ]

    async def get_shift(self, company_id: UUID, shift_id: UUID) -> ShiftRead:
        shift = await self._repo.get_shift(self._session, company_id=company_id, shift_id=shift_id)
        if shift is None:
            raise NotFoundError("Resource not found")
        current = await self._shift_version_repo.get_current_published(
            self._session, company_id=company_id, shift_id=shift_id
        )
        draft = await self._shift_version_repo.get_open_draft(
            self._session, company_id=company_id, shift_id=shift_id
        )
        return shift_to_read(
            shift,
            current_version_id=current.id if current is not None else None,
            draft_version_id=draft.id if draft is not None else None,
        )

    async def update_shift(
        self,
        company_id: UUID,
        shift_id: UUID,
        patch: ShiftUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftRead:
        shift = await self._repo.get_shift(self._session, company_id=company_id, shift_id=shift_id)
        if shift is None:
            raise NotFoundError("Resource not found")

        before_read = shift_to_read(shift)
        # Captured before `update_shift` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `shift` instance in place (same gotcha documented on `update_grade`) — reading
        # `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = shift.is_active

        # No documented dependency-blocking rule applies to Shift deactivation this slice
        # (FR-ORG-014's only named blocker — active employees — can't be checked since
        # Employee doesn't exist; see docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md §6.4).
        deactivating = patch.is_active is False and was_active_before is True
        if deactivating:
            await self._assert_master_not_in_use(
                company_id, kind="shift", column="shift_id", master_id=shift_id
            )

        values = build_shift_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_shift(
            self._session,
            company_id=company_id,
            shift_id=shift_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_shift(
                self._session, company_id=company_id, shift_id=shift_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = shift_to_read(current)
            raise StaleResourceError(
                "This shift has been modified by another request",
                current=shift_to_audit_dict(current_read),
            )

        after_read = shift_to_read(updated)
        action = (
            "SHIFT_DEACTIVATED"
            if deactivating
            else "SHIFT_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "SHIFT_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="shift",
            entity_id=shift_id,
            before=shift_to_audit_dict(before_read),
            after=shift_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_shift(
        self,
        company_id: UUID,
        shift_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftRead:
        """Semantic wrapper around `update_shift` for `DELETE /shifts/{id}` — never a hard
        delete (FR-ORG-014); flips `is_active` to False via the same business-rule path
        (audit, optimistic concurrency)."""
        return await self.update_shift(
            company_id,
            shift_id,
            ShiftUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _shift_deletion_check(self, company_id: UUID, shift: Any) -> ShiftDeletionCheck:
        refs = await self._repo.count_shift_references(
            self._session, company_id=company_id, shift_id=shift.id
        )
        blockers: list[ShiftDeletionBlocker] = []

        def block(code: str, message: str, count: int) -> None:
            blockers.append(ShiftDeletionBlocker(code=code, message=message, count=count))

        if shift.is_active:
            block(
                "SHIFT_STILL_ACTIVE",
                "the shift is still active; deactivate it first",
                1,
            )
        if refs["active_employees"]:
            block(
                "SHIFT_HAS_ACTIVE_EMPLOYEES",
                f"{refs['active_employees']} active employee(s) are currently assigned to it",
                refs["active_employees"],
            )
        past_only = refs["assignment_rows"]
        if past_only:
            block(
                "SHIFT_HAS_ASSIGNMENT_HISTORY",
                f"{past_only} employee assignment record(s), current or historical, use it",
                past_only,
            )
        if refs["roster_rows"]:
            block(
                "SHIFT_HAS_ROSTER_ENTRIES",
                f"{refs['roster_rows']} roster entr(ies) use it",
                refs["roster_rows"],
            )
        if refs["attendance_days"]:
            block(
                "SHIFT_HAS_ATTENDANCE_RECORDS",
                f"{refs['attendance_days']} attendance day record(s) were calculated against it",
                refs["attendance_days"],
            )
        if refs["regularization_requests"]:
            block(
                "SHIFT_HAS_REGULARIZATION_REQUESTS",
                f"{refs['regularization_requests']} attendance regularisation request(s) "
                "reference it",
                refs["regularization_requests"],
            )
        return ShiftDeletionCheck(
            can_delete=not blockers,
            blockers=blockers,
            published_version_count=refs["published_versions"],
            draft_version_count=refs["draft_versions"],
        )

    async def get_shift_deletion_check(
        self, company_id: UUID, shift_id: UUID
    ) -> ShiftDeletionCheck:
        shift = await self._repo.get_shift(self._session, company_id=company_id, shift_id=shift_id)
        if shift is None:
            raise NotFoundError("Resource not found")
        return await self._shift_deletion_check(company_id, shift)

    async def delete_shift(
        self,
        company_id: UUID,
        shift_id: UUID,
        body: ShiftDeleteRequest,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Guarded removal of a shift that has never been used. A soft delete (`deleted_at`) —
        FR-ORG-014 forbids hard deletes — so the row, its versions and the full audit trail
        stay recoverable by an operator.

        Safeguards, in order: the row is locked `FOR UPDATE`; the optimistic-concurrency token
        must match; the deactivate-first rule and every reference check are re-run *inside* the
        locked transaction (not trusted from the earlier preview); the typed name must match
        exactly; a written reason is recorded in the audit log together with a full snapshot."""
        shift = await self._repo.lock_shift(self._session, company_id=company_id, shift_id=shift_id)
        if shift is None:
            raise NotFoundError("Resource not found")
        if shift.version != expected_version:
            raise StaleResourceError(
                "This shift has been modified by another request",
                current=shift_to_audit_dict(shift_to_read(shift)),
            )

        check = await self._shift_deletion_check(company_id, shift)
        if not check.can_delete:
            raise ShiftDeletionBlockedError(blockers=[b.model_dump() for b in check.blockers])
        if body.confirm_name != shift.name:
            raise ShiftDeleteConfirmationMismatchError()

        snapshot = shift_to_audit_dict(shift_to_read(shift))
        snapshot["published_version_count"] = check.published_version_count
        snapshot["draft_version_count"] = check.draft_version_count
        now = datetime.now(UTC)
        updated = await self._repo.update_shift(
            self._session,
            company_id=company_id,
            shift_id=shift_id,
            values={"deleted_at": now, "is_active": False},
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            raise NotFoundError("Resource not found")
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_DELETED",
            entity_type="shift",
            entity_id=shift_id,
            before=snapshot,
            after={"deleted_at": now.isoformat(), "reason": body.reason},
            ip=ip_address,
            user_agent=user_agent,
        )

    # -----------------------------------------------------------------
    # Shift + Break System (W2) — ShiftVersion, ShiftBreak, ShiftDutyBlock.
    # docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §9-§10.
    # -----------------------------------------------------------------

    @staticmethod
    def _time_to_minutes(value: str) -> int:
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)

    def _interval_overlaps(
        self,
        a_start: str,
        a_end: str,
        a_wraps: bool,
        b_start: str,
        b_end: str,
        b_wraps: bool,
    ) -> bool:
        """Wrap-aware half-open interval overlap on a 24h clock. A midnight-crossing interval
        is represented as two segments: [start, 1440) and [0, end)."""

        def segments(start: str, end: str, wraps: bool) -> list[tuple[int, int]]:
            s, e = self._time_to_minutes(start), self._time_to_minutes(end)
            return [(s, 1440), (0, e)] if wraps else [(s, e)]

        for a_s, a_e in segments(a_start, a_end, a_wraps):
            for b_s, b_e in segments(b_start, b_end, b_wraps):
                if a_s < b_e and b_s < a_e:
                    return True
        return False

    def _interval_contains(
        self, outer_start: str, outer_end: str, inner_start: str, inner_end: str
    ) -> bool:
        """Wrap-aware containment, via a projection onto a 1440-minute clock with
        `outer_start` as the origin — handles midnight-crossing outer/inner intervals
        uniformly without needing explicit wrap flags."""
        base = self._time_to_minutes(outer_start)
        outer_duration = (self._time_to_minutes(outer_end) - base) % 1440 or 1440
        inner_start_offset = (self._time_to_minutes(inner_start) - base) % 1440
        inner_duration = (
            self._time_to_minutes(inner_end) - self._time_to_minutes(inner_start)
        ) % 1440 or 1440
        return inner_start_offset + inner_duration <= outer_duration

    def _derive_cross_midnight(
        self,
        shift_type: str | None,
        start_time: str | None,
        end_time: str | None,
        duty_blocks: list[ShiftDutyBlockCreate] | None,
    ) -> bool:
        """`is_cross_midnight` is always server-derived (architecture §9.5: "must be
        consistent with start/end (already validated)"), never client-settable. FLEXIBLE is
        forced non-cross-midnight — a known limitation, since the architecture doesn't specify
        the flex+cross-midnight interaction."""
        if shift_type == "FIXED":
            if start_time is None or end_time is None or start_time == end_time:
                return False
            return end_time < start_time
        if shift_type == "SPLIT":
            if not duty_blocks:
                return False
            return any(block.end_time <= block.start_time for block in duty_blocks)
        return False

    def _validate_shift_breaks(self, breaks: list[ShiftBreakCreate]) -> None:
        fixed_windows: list[tuple[int, str, str]] = []
        seen_names: set[str] = set()
        for index, brk in enumerate(breaks):
            # Break management V1: a break is addressed by name (employee overrides, break
            # events), so names must be unique within a version.
            key = brk.name.strip().lower()
            if key in seen_names:
                raise InvalidShiftBreakError(
                    "break names must be unique within a shift", index=index
                )
            seen_names.add(key)
            self._validate_break_durations(brk, index)
            if brk.break_kind == "FIXED_WINDOW":
                if brk.start_time is None or brk.end_time is None:
                    raise InvalidShiftBreakError(
                        "start_time and end_time are required for a FIXED_WINDOW break",
                        index=index,
                    )
                if brk.start_time == brk.end_time:
                    raise InvalidShiftBreakError(
                        "start_time and end_time must differ for a FIXED_WINDOW break",
                        index=index,
                    )
                fixed_windows.append((index, brk.start_time, brk.end_time))
            else:
                if (
                    brk.window_start is None
                    or brk.window_end is None
                    or brk.min_minutes is None
                    or brk.max_minutes is None
                ):
                    raise InvalidShiftBreakError(
                        "window_start, window_end, min_minutes and max_minutes are required "
                        "for a FLEXIBLE_DURATION break",
                        index=index,
                    )
                if brk.window_end <= brk.window_start:
                    raise InvalidShiftBreakError(
                        "window_end must be after window_start for a FLEXIBLE_DURATION break",
                        index=index,
                    )
                if brk.min_minutes > brk.max_minutes:
                    raise InvalidShiftBreakError(
                        "min_minutes must not exceed max_minutes", index=index
                    )
                if brk.scheduled_minutes is not None and not (
                    brk.min_minutes <= brk.scheduled_minutes <= brk.max_minutes
                ):
                    raise InvalidShiftBreakError(
                        "scheduled_minutes must fall between min_minutes and max_minutes",
                        index=index,
                    )

        for i in range(len(fixed_windows)):
            for j in range(i + 1, len(fixed_windows)):
                idx_a, start_a, end_a = fixed_windows[i]
                idx_b, start_b, end_b = fixed_windows[j]
                wraps_a = end_a < start_a
                wraps_b = end_b < start_b
                if self._interval_overlaps(start_a, end_a, wraps_a, start_b, end_b, wraps_b):
                    raise InvalidShiftBreakOverlapError(index=idx_b)

    @staticmethod
    def _validate_break_durations(brk: ShiftBreakCreate, index: int) -> None:
        """Duration rules shared by every break kind (V1). `mode=None` legacy breaks keep the
        pre-V1 rules only, so existing payloads still validate."""
        if brk.mode is None:
            return
        if brk.max_minutes is not None and brk.max_minutes < 1:
            raise InvalidShiftBreakError("max_minutes must be at least 1", index=index)
        if (
            brk.min_minutes is not None
            and brk.max_minutes is not None
            and brk.min_minutes > brk.max_minutes
        ):
            raise InvalidShiftBreakError("min_minutes must not exceed max_minutes", index=index)
        if (
            brk.scheduled_minutes is not None
            and brk.max_minutes is not None
            and brk.scheduled_minutes > brk.max_minutes
        ):
            raise InvalidShiftBreakError(
                "scheduled_minutes must not exceed max_minutes", index=index
            )
        if (
            brk.scheduled_minutes is not None
            and brk.min_minutes is not None
            and brk.scheduled_minutes < brk.min_minutes
        ):
            raise InvalidShiftBreakError(
                "scheduled_minutes must not be below min_minutes", index=index
            )
        if brk.mode == "AUTO_DEDUCT":
            if brk.break_kind == "FLEXIBLE_DURATION" and not brk.scheduled_minutes:
                raise InvalidShiftBreakError(
                    "scheduled_minutes is required for an AUTO_DEDUCT FLEXIBLE_DURATION break",
                    index=index,
                )
            if brk.break_kind == "FIXED_WINDOW" and brk.scheduled_minutes:
                # A deduction longer than its own window can never be taken from presence.
                start, end = brk.start_time, brk.end_time
                if start and end:
                    span = _clock_minutes(end) - _clock_minutes(start)
                    span = span + 1440 if span <= 0 else span
                    if brk.scheduled_minutes > span:
                        raise InvalidShiftBreakError(
                            "scheduled_minutes must not exceed the break window", index=index
                        )

    def _build_break_rows(
        self, *, company_id: UUID, shift_version_id: UUID, breaks: list[ShiftBreakCreate]
    ) -> list[dict[str, Any]]:
        self._validate_shift_breaks(breaks)
        rows = []
        for brk in breaks:
            crosses_midnight = (
                brk.break_kind == "FIXED_WINDOW"
                and brk.start_time is not None
                and brk.end_time is not None
                and brk.end_time < brk.start_time
            )
            rows.append(
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "shift_version_id": shift_version_id,
                    "name": brk.name,
                    "break_kind": brk.break_kind,
                    "start_time": _parse_time(brk.start_time) if brk.start_time else None,
                    "end_time": _parse_time(brk.end_time) if brk.end_time else None,
                    "window_start": _parse_time(brk.window_start) if brk.window_start else None,
                    "window_end": _parse_time(brk.window_end) if brk.window_end else None,
                    "min_minutes": brk.min_minutes,
                    "max_minutes": brk.max_minutes,
                    "scheduled_minutes": brk.scheduled_minutes,
                    "is_paid": brk.is_paid,
                    "is_mandatory": brk.is_mandatory,
                    "allows_split": brk.allows_split,
                    "crosses_midnight": crosses_midnight,
                    "sort_order": brk.sort_order,
                    "mode": brk.mode,
                    "break_type": brk.break_type,
                    "is_enabled": brk.is_enabled,
                    "excess_outcome": brk.excess_outcome,
                    "auto_deduct_full": brk.auto_deduct_full,
                    "optional_recorded_deducts": brk.optional_recorded_deducts,
                    "optional_scheduled_fallback": brk.optional_scheduled_fallback,
                }
            )
        return rows

    def _build_duty_block_rows(
        self, *, company_id: UUID, shift_version_id: UUID, blocks: list[ShiftDutyBlockCreate]
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": uuid4(),
                "company_id": company_id,
                "shift_version_id": shift_version_id,
                "sequence": block.sequence,
                "start_time": _parse_time(block.start_time),
                "end_time": _parse_time(block.end_time),
                "crosses_midnight": block.end_time <= block.start_time,
            }
            for block in blocks
        ]

    def _validate_duty_blocks_for_publish(self, blocks: list[Any]) -> None:
        """SPLIT shift type only — count/sequence/overlap can't be DB CHECKs (they count/
        compare across child rows), so they're enforced here at publish time only (a draft may
        be incomplete mid-edit)."""
        if len(blocks) < 2:
            raise InvalidShiftVersionDutyBlockCountError()
        ordered = sorted(blocks, key=lambda b: b.sequence)
        if [b.sequence for b in ordered] != list(range(1, len(ordered) + 1)):
            raise InvalidShiftVersionDutyBlockSequenceError()
        for block in ordered:
            start, end = _format_time(block.start_time), _format_time(block.end_time)
            if start == end:
                raise ValidationError(
                    "Each duty block's start_time and end_time must differ",
                    code="INVALID_SHIFT_VERSION_DUTY_BLOCK_TIME_RANGE",
                    details=[
                        {
                            "field": f"duty_blocks.{block.sequence}",
                            "code": "INVALID_SHIFT_VERSION_DUTY_BLOCK_TIME_RANGE",
                            "message": "start_time and end_time must differ",
                        }
                    ],
                )
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                a, b = ordered[i], ordered[j]
                a_start, a_end = _format_time(a.start_time), _format_time(a.end_time)
                b_start, b_end = _format_time(b.start_time), _format_time(b.end_time)
                assert a_start and a_end and b_start and b_end
                if self._interval_overlaps(
                    a_start, a_end, a.crosses_midnight, b_start, b_end, b.crosses_midnight
                ):
                    raise InvalidShiftVersionDutyBlockOverlapError(index=b.sequence)

    def _validate_breaks_boundaries_for_publish(
        self,
        *,
        shift_type: str,
        start_time: str | None,
        end_time: str | None,
        window_start: str | None,
        window_end: str | None,
        breaks: list[Any],
    ) -> None:
        """FIXED/FLEXIBLE only — containment of `FIXED_WINDOW` breaks inside the shift's
        overall span. SPLIT is skipped: `ShiftBreak` has no `duty_block_id` (known
        limitation — the architecture's own field list omits this link), so
        containment-within-duty-block can't be validated."""
        if shift_type == "SPLIT":
            return
        bound_start, bound_end = (
            (start_time, end_time) if shift_type == "FIXED" else (window_start, window_end)
        )
        if bound_start is None or bound_end is None:
            return
        for brk in breaks:
            if brk.break_kind != "FIXED_WINDOW":
                continue
            b_start, b_end = _format_time(brk.start_time), _format_time(brk.end_time)
            if b_start is None or b_end is None:
                continue
            if not self._interval_contains(bound_start, bound_end, b_start, b_end):
                raise InvalidShiftBreakError("break falls outside the shift's scheduled window")

    def _validate_shift_version_type_fields(self, shift_type: str, version: Any) -> None:
        """A friendly service-layer surface for what would otherwise be an opaque DB CHECK
        violation — rejects fields that only make sense for a *different* `shift_type` being
        populated (e.g. `window_start` on a FIXED version)."""
        fixed_fields = {"start_time": version.start_time, "end_time": version.end_time}
        flex_fields = {
            "window_start": version.window_start,
            "window_end": version.window_end,
            "core_start": version.core_start,
            "core_end": version.core_end,
            "required_minutes": version.required_minutes,
        }
        if shift_type == "FIXED":
            offending = flex_fields
        elif shift_type == "FLEXIBLE":
            offending = fixed_fields
        else:
            offending = {**fixed_fields, **flex_fields}
        for name, value in offending.items():
            if value is not None:
                raise InvalidShiftVersionTypeCombinationError(
                    f"{name} must not be set for a {shift_type} shift"
                )

    def _validate_and_derive_for_publish(
        self, version: Any, breaks: list[Any], duty_blocks: list[Any]
    ) -> bool:
        """Runs the full type-specific publish-time validation (plan §4) and returns the
        authoritative `is_cross_midnight` to store. `shift_type`/`effective_from` presence is
        also required by the DB CHECK `shift_version_published_required_check` — checked here
        first for a friendlier 422 instead of an opaque CHECK-violation error."""
        if version.shift_type is None:
            raise ValidationError(
                "shift_type is required to publish a shift version",
                code="SHIFT_VERSION_TYPE_REQUIRED",
                details=[
                    {
                        "field": "shift_type",
                        "code": "SHIFT_VERSION_TYPE_REQUIRED",
                        "message": "shift_type is required to publish a shift version",
                    }
                ],
            )
        if version.effective_from is None:
            raise InvalidShiftVersionEffectiveFromError(
                "effective_from is required to publish a shift version"
            )
        # `NEW-01` publish-time re-check (execution gate §4.3, defence in depth). The `Create`/
        # `Update` schema validators now reject an invalid timezone at every write, so the only
        # way an invalid value reaches this point is a row written before that validator existed,
        # whose `timezone` field a later PATCH never happened to touch (every `Update` field is
        # optional and only-if-set). Re-validating here, once, at the one gate every version must
        # pass before it can affect real attendance, closes that window without needing a
        # one-off data migration to sweep legacy rows first.
        if version.timezone is not None:
            try:
                validate_iana_timezone(version.timezone)
            except ValueError as exc:
                raise ValidationError(
                    str(exc),
                    code="INVALID_SHIFT_VERSION_TIMEZONE",
                    details=[
                        {
                            "field": "timezone",
                            "code": "INVALID_SHIFT_VERSION_TIMEZONE",
                            "message": str(exc),
                        }
                    ],
                ) from exc
        self._validate_shift_version_type_fields(version.shift_type, version)

        start_time = _format_time(version.start_time)
        end_time = _format_time(version.end_time)
        window_start = _format_time(version.window_start)
        window_end = _format_time(version.window_end)
        core_start = _format_time(version.core_start)
        core_end = _format_time(version.core_end)

        is_cross_midnight = False
        if version.shift_type == "FIXED":
            if start_time is None or end_time is None:
                raise InvalidShiftVersionTimeRangeError(
                    "start_time and end_time are required for a FIXED shift"
                )
            if start_time == end_time:
                raise InvalidShiftVersionTimeRangeError()
            is_cross_midnight = end_time < start_time
        elif version.shift_type == "FLEXIBLE":
            if window_start is None or window_end is None or version.required_minutes is None:
                raise InvalidShiftVersionFlexWindowError()
            if window_end <= window_start:
                raise InvalidShiftVersionFlexWindowError()
            if (core_start is None) != (core_end is None):
                raise InvalidShiftVersionCoreHoursError(
                    "core_start and core_end must be given together"
                )
            # `window_start`-`window_end` is the *start-time* flexibility range (architecture
            # §9.4's own example: "07:00-10:00 start"), not the whole working span — core
            # hours are a separate, independently-positioned block and are not required to
            # nest inside it. Only a sane (non-empty) core range is enforced.
            if core_start is not None and core_end is not None and core_end <= core_start:
                raise InvalidShiftVersionCoreHoursError("core_end must be after core_start")
            is_cross_midnight = False
        elif version.shift_type == "SPLIT":
            self._validate_duty_blocks_for_publish(duty_blocks)
            is_cross_midnight = any(block.crosses_midnight for block in duty_blocks)

        self._validate_breaks_boundaries_for_publish(
            shift_type=version.shift_type,
            start_time=start_time,
            end_time=end_time,
            window_start=window_start,
            window_end=window_end,
            breaks=breaks,
        )
        return is_cross_midnight

    async def _validate_weekly_off_pattern_reference(
        self, company_id: UUID, weekly_off_pattern_id: UUID
    ) -> None:
        pattern = await self._weekly_off_repo.get(
            self._session, company_id=company_id, pattern_id=weekly_off_pattern_id
        )
        if pattern is None:
            raise ValidationError(
                "weekly_off_pattern_id does not reference a valid weekly-off pattern",
                code="INVALID_WEEKLY_OFF_PATTERN_REFERENCE",
                details=[
                    {
                        "field": "weekly_off_pattern_id",
                        "code": "INVALID_WEEKLY_OFF_PATTERN_REFERENCE",
                        "message": (
                            "weekly_off_pattern_id does not reference a valid weekly-off pattern"
                        ),
                    }
                ],
            )

    async def create_shift_version(
        self,
        company_id: UUID,
        shift_id: UUID,
        body: ShiftVersionCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftVersionRead:
        shift = await self._repo.get_shift(self._session, company_id=company_id, shift_id=shift_id)
        if shift is None:
            raise NotFoundError("Resource not found")
        existing_draft = await self._shift_version_repo.get_open_draft(
            self._session, company_id=company_id, shift_id=shift_id
        )
        if existing_draft is not None:
            raise ShiftVersionDraftAlreadyExistsError()
        if body.weekly_off_pattern_id is not None:
            await self._validate_weekly_off_pattern_reference(
                company_id, body.weekly_off_pattern_id
            )

        now = datetime.now(UTC)
        version_id = uuid4()
        is_cross_midnight = self._derive_cross_midnight(
            body.shift_type, body.start_time, body.end_time, body.duty_blocks
        )
        row = await self._shift_version_repo.insert(
            self._session,
            data={
                "id": version_id,
                "company_id": company_id,
                "shift_id": shift_id,
                "status": "DRAFT",
                "version": 1,
                "effective_from": body.effective_from,
                "effective_to": None,
                "shift_type": body.shift_type,
                "timezone": body.timezone,
                "start_time": _parse_time(body.start_time) if body.start_time else None,
                "end_time": _parse_time(body.end_time) if body.end_time else None,
                "window_start": _parse_time(body.window_start) if body.window_start else None,
                "window_end": _parse_time(body.window_end) if body.window_end else None,
                "core_start": _parse_time(body.core_start) if body.core_start else None,
                "core_end": _parse_time(body.core_end) if body.core_end else None,
                "required_minutes": body.required_minutes,
                "scheduled_minutes": body.scheduled_minutes,
                "min_scheduled_minutes": body.min_scheduled_minutes,
                "max_scheduled_minutes": body.max_scheduled_minutes,
                "is_night_shift": body.is_night_shift,
                "is_cross_midnight": is_cross_midnight,
                "is_ot_eligible": body.is_ot_eligible,
                "operates_on_holiday": body.operates_on_holiday,
                "operates_on_weekly_off": body.operates_on_weekly_off,
                "weekly_off_pattern_id": body.weekly_off_pattern_id,
                "publish_reason": None,
                "published_at": None,
                "published_by": None,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            },
        )
        breaks: list[Any] = []
        duty_blocks: list[Any] = []
        if body.breaks:
            try:
                breaks = await self._shift_version_repo.replace_breaks(
                    self._session,
                    company_id=company_id,
                    shift_version_id=version_id,
                    rows=self._build_break_rows(
                        company_id=company_id, shift_version_id=version_id, breaks=body.breaks
                    ),
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise InvalidShiftBreakError("breaks could not be saved") from exc
        if body.duty_blocks:
            try:
                duty_blocks = await self._shift_version_repo.replace_duty_blocks(
                    self._session,
                    company_id=company_id,
                    shift_version_id=version_id,
                    rows=self._build_duty_block_rows(
                        company_id=company_id, shift_version_id=version_id, blocks=body.duty_blocks
                    ),
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise InvalidShiftVersionDutyBlockSequenceError(
                    "duty_blocks sequence values must be unique"
                ) from exc

        read = shift_version_to_read(row, breaks, duty_blocks)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_VERSION_CREATED",
            entity_type="shift_version",
            entity_id=version_id,
            after=shift_version_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_shift_versions(
        self, company_id: UUID, shift_id: UUID, *, page: PageParams
    ) -> tuple[list[ShiftVersionRead], int]:
        shift = await self._repo.get_shift(self._session, company_id=company_id, shift_id=shift_id)
        if shift is None:
            raise NotFoundError("Resource not found")
        versions = await self._shift_version_repo.list_versions(
            self._session,
            company_id=company_id,
            shift_id=shift_id,
            limit=page.limit,
            offset=page.offset,
        )
        total = await self._shift_version_repo.count_versions(
            self._session, company_id=company_id, shift_id=shift_id
        )
        # Breaks/duty-blocks are fetched only for *this page's* version IDs — pagination narrows
        # the parent query first, and the already-batched child fetch below (no N+1 here to
        # begin with) composes correctly on top of it (API-01 §6).
        version_ids = [v.id for v in versions]
        all_breaks = await self._shift_version_repo.list_breaks_for_versions(
            self._session, company_id=company_id, version_ids=version_ids
        )
        all_duty_blocks = await self._shift_version_repo.list_duty_blocks_for_versions(
            self._session, company_id=company_id, version_ids=version_ids
        )
        breaks_by_version: dict[UUID, list[Any]] = {vid: [] for vid in version_ids}
        for b in all_breaks:
            breaks_by_version[b.shift_version_id].append(b)
        blocks_by_version: dict[UUID, list[Any]] = {vid: [] for vid in version_ids}
        for d in all_duty_blocks:
            blocks_by_version[d.shift_version_id].append(d)
        reads = [
            shift_version_to_read(v, breaks_by_version[v.id], blocks_by_version[v.id])
            for v in versions
        ]
        return reads, total

    async def get_shift_version(
        self, company_id: UUID, shift_id: UUID, version_id: UUID
    ) -> ShiftVersionRead:
        version = await self._shift_version_repo.get(
            self._session, company_id=company_id, shift_id=shift_id, version_id=version_id
        )
        if version is None:
            raise NotFoundError("Resource not found")
        breaks = await self._shift_version_repo.list_breaks(
            self._session, company_id=company_id, shift_version_id=version_id
        )
        duty_blocks = await self._shift_version_repo.list_duty_blocks(
            self._session, company_id=company_id, shift_version_id=version_id
        )
        return shift_version_to_read(version, breaks, duty_blocks)

    async def update_shift_version(
        self,
        company_id: UUID,
        shift_id: UUID,
        version_id: UUID,
        patch: ShiftVersionUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftVersionRead:
        version = await self._shift_version_repo.get(
            self._session, company_id=company_id, shift_id=shift_id, version_id=version_id
        )
        if version is None:
            raise NotFoundError("Resource not found")
        if version.status != "DRAFT":
            raise ShiftVersionNotDraftError()

        current_breaks = await self._shift_version_repo.list_breaks(
            self._session, company_id=company_id, shift_version_id=version_id
        )
        current_duty_blocks = await self._shift_version_repo.list_duty_blocks(
            self._session, company_id=company_id, shift_version_id=version_id
        )
        before_read = shift_version_to_read(version, current_breaks, current_duty_blocks)

        if (
            "weekly_off_pattern_id" in patch.model_fields_set
            and patch.weekly_off_pattern_id is not None
        ):
            await self._validate_weekly_off_pattern_reference(
                company_id, patch.weekly_off_pattern_id
            )

        values = build_shift_version_update_values(patch)
        _time_fields = (
            "start_time",
            "end_time",
            "window_start",
            "window_end",
            "core_start",
            "core_end",
        )
        for field in _time_fields:
            if field in values:
                raw = getattr(patch, field)
                values[field] = _parse_time(raw) if raw else None

        # Opportunistic recompute — only for the simple, unambiguous FIXED case where both
        # times are given in this same PATCH; SPLIT is only finalized at publish time (it
        # depends on duty blocks, which have no independent lifecycle validation until then).
        if (
            "shift_type" in patch.model_fields_set
            or "start_time" in patch.model_fields_set
            or "end_time" in patch.model_fields_set
        ):
            effective_type = (
                patch.shift_type if "shift_type" in patch.model_fields_set else version.shift_type
            )
            effective_start = (
                patch.start_time
                if "start_time" in patch.model_fields_set
                else _format_time(version.start_time)
            )
            effective_end = (
                patch.end_time
                if "end_time" in patch.model_fields_set
                else _format_time(version.end_time)
            )
            if effective_type == "FIXED" and effective_start and effective_end:
                values["is_cross_midnight"] = self._derive_cross_midnight(
                    "FIXED", effective_start, effective_end, None
                )
            elif effective_type == "FLEXIBLE":
                values["is_cross_midnight"] = False

        now = datetime.now(UTC)
        updated = version
        if values:
            result = await self._shift_version_repo.update(
                self._session,
                company_id=company_id,
                shift_id=shift_id,
                version_id=version_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
            if result is None:
                latest = await self._shift_version_repo.get(
                    self._session, company_id=company_id, shift_id=shift_id, version_id=version_id
                )
                if latest is None:
                    raise NotFoundError("Resource not found")
                latest_breaks = await self._shift_version_repo.list_breaks(
                    self._session, company_id=company_id, shift_version_id=version_id
                )
                latest_blocks = await self._shift_version_repo.list_duty_blocks(
                    self._session, company_id=company_id, shift_version_id=version_id
                )
                raise StaleResourceError(
                    "This shift version has been modified by another request",
                    current=shift_version_to_audit_dict(
                        shift_version_to_read(latest, latest_breaks, latest_blocks)
                    ),
                )
            updated = result

        breaks = current_breaks
        if patch.breaks is not None:
            try:
                breaks = await self._shift_version_repo.replace_breaks(
                    self._session,
                    company_id=company_id,
                    shift_version_id=version_id,
                    rows=self._build_break_rows(
                        company_id=company_id, shift_version_id=version_id, breaks=patch.breaks
                    ),
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise InvalidShiftBreakError("breaks could not be saved") from exc

        duty_blocks = current_duty_blocks
        if patch.duty_blocks is not None:
            try:
                duty_blocks = await self._shift_version_repo.replace_duty_blocks(
                    self._session,
                    company_id=company_id,
                    shift_version_id=version_id,
                    rows=self._build_duty_block_rows(
                        company_id=company_id,
                        shift_version_id=version_id,
                        blocks=patch.duty_blocks,
                    ),
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise InvalidShiftVersionDutyBlockSequenceError(
                    "duty_blocks sequence values must be unique"
                ) from exc

        after_read = shift_version_to_read(updated, breaks, duty_blocks)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_VERSION_UPDATED",
            entity_type="shift_version",
            entity_id=version_id,
            before=shift_version_to_audit_dict(before_read),
            after=shift_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def discard_shift_version(
        self,
        company_id: UUID,
        shift_id: UUID,
        version_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftVersionRead:
        version = await self._shift_version_repo.get(
            self._session, company_id=company_id, shift_id=shift_id, version_id=version_id
        )
        if version is None:
            raise NotFoundError("Resource not found")
        if version.status != "DRAFT":
            raise ShiftVersionNotDraftError()

        breaks = await self._shift_version_repo.list_breaks(
            self._session, company_id=company_id, shift_version_id=version_id
        )
        duty_blocks = await self._shift_version_repo.list_duty_blocks(
            self._session, company_id=company_id, shift_version_id=version_id
        )
        before_read = shift_version_to_read(version, breaks, duty_blocks)

        now = datetime.now(UTC)
        result = await self._shift_version_repo.discard(
            self._session,
            company_id=company_id,
            shift_id=shift_id,
            version_id=version_id,
            expected_version=expected_version,
            now=now,
        )
        if result is None:
            latest = await self._shift_version_repo.get(
                self._session, company_id=company_id, shift_id=shift_id, version_id=version_id
            )
            if latest is None:
                raise NotFoundError("Resource not found")
            latest_breaks = await self._shift_version_repo.list_breaks(
                self._session, company_id=company_id, shift_version_id=version_id
            )
            latest_blocks = await self._shift_version_repo.list_duty_blocks(
                self._session, company_id=company_id, shift_version_id=version_id
            )
            raise StaleResourceError(
                "This shift version has been modified by another request",
                current=shift_version_to_audit_dict(
                    shift_version_to_read(latest, latest_breaks, latest_blocks)
                ),
            )

        after_read = shift_version_to_read(result, breaks, duty_blocks)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_VERSION_DISCARDED",
            entity_type="shift_version",
            entity_id=version_id,
            before=shift_version_to_audit_dict(before_read),
            after=shift_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def publish_shift_version(
        self,
        company_id: UUID,
        shift_id: UUID,
        version_id: UUID,
        body: ShiftVersionPublishRequest,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ShiftVersionRead:
        """Insert-new/close-previous — mirrors `create_policy_assignment`, just with two
        concurrency tokens instead of one since two different rows are mutated: `expected_version`
        (If-Match) is the draft's own token, `body.expected_previous_version` is the currently
        open PUBLISHED version's token, required only when one exists."""
        draft = await self._shift_version_repo.get(
            self._session, company_id=company_id, shift_id=shift_id, version_id=version_id
        )
        if draft is None:
            raise NotFoundError("Resource not found")
        if draft.status != "DRAFT":
            raise ShiftVersionNotDraftError()

        breaks = await self._shift_version_repo.list_breaks(
            self._session, company_id=company_id, shift_version_id=version_id
        )
        duty_blocks = await self._shift_version_repo.list_duty_blocks(
            self._session, company_id=company_id, shift_version_id=version_id
        )
        before_read = shift_version_to_read(draft, breaks, duty_blocks)

        is_cross_midnight = self._validate_and_derive_for_publish(draft, breaks, duty_blocks)

        # `SR-11` (execution gate §12.4) — a backdated publish whose `effective_from` falls
        # inside an already-`CLOSED` period must be refused, the same way punch ingestion and
        # roster writes already are. Narrow, deliberately: only this one publish path, not every
        # backdated policy version (recorded as debt elsewhere, §12.4).
        # enforced above, inside _validate_and_derive_for_publish:
        assert draft.effective_from is not None
        from hrms.modules.attendance.service import AttendanceService

        await AttendanceService(self._session).assert_date_open(company_id, draft.effective_from)

        current = await self._shift_version_repo.get_current_published(
            self._session, company_id=company_id, shift_id=shift_id
        )
        now = datetime.now(UTC)
        if current is not None:
            assert draft.effective_from is not None
            assert current.effective_from is not None
            if draft.effective_from <= current.effective_from:
                raise InvalidShiftVersionEffectiveFromError()
            if body.expected_previous_version is None:
                raise ShiftVersionPreviousVersionRequiredError()
            closed = await self._shift_version_repo.close(
                self._session,
                company_id=company_id,
                version_id=current.id,
                effective_to=draft.effective_from - timedelta(days=1),
                expected_version=body.expected_previous_version,
                now=now,
            )
            if closed is None:
                latest_current = await self._shift_version_repo.get(
                    self._session, company_id=company_id, shift_id=shift_id, version_id=current.id
                )
                if latest_current is None:
                    raise NotFoundError("Resource not found")
                latest_current_breaks = await self._shift_version_repo.list_breaks(
                    self._session, company_id=company_id, shift_version_id=current.id
                )
                latest_current_blocks = await self._shift_version_repo.list_duty_blocks(
                    self._session, company_id=company_id, shift_version_id=current.id
                )
                raise StaleResourceError(
                    "The currently published shift version has been modified by another request",
                    current=shift_version_to_audit_dict(
                        shift_version_to_read(
                            latest_current, latest_current_breaks, latest_current_blocks
                        )
                    ),
                )

        try:
            updated = await self._shift_version_repo.update(
                self._session,
                company_id=company_id,
                shift_id=shift_id,
                version_id=version_id,
                values={
                    "status": "PUBLISHED",
                    "is_cross_midnight": is_cross_midnight,
                    "publish_reason": body.publish_reason,
                    "published_at": now,
                    "published_by": actor_user_id,
                },
                expected_version=expected_version,
                now=now,
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise ShiftVersionOverlapError() from exc

        if updated is None:
            latest = await self._shift_version_repo.get(
                self._session, company_id=company_id, shift_id=shift_id, version_id=version_id
            )
            if latest is None:
                raise NotFoundError("Resource not found")
            latest_breaks = await self._shift_version_repo.list_breaks(
                self._session, company_id=company_id, shift_version_id=version_id
            )
            latest_blocks = await self._shift_version_repo.list_duty_blocks(
                self._session, company_id=company_id, shift_version_id=version_id
            )
            raise StaleResourceError(
                "This shift version has been modified by another request",
                current=shift_version_to_audit_dict(
                    shift_version_to_read(latest, latest_breaks, latest_blocks)
                ),
            )

        after_read = shift_version_to_read(updated, breaks, duty_blocks)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="SHIFT_VERSION_PUBLISHED",
            entity_type="shift_version",
            entity_id=version_id,
            before=shift_version_to_audit_dict(before_read),
            after=shift_version_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def resolve_shift_version_as_of(
        self, company_id: UUID, shift_id: UUID, as_of: date
    ) -> ShiftVersionRead:
        shift = await self._repo.get_shift(self._session, company_id=company_id, shift_id=shift_id)
        if shift is None:
            raise NotFoundError("Resource not found")
        version = await self._shift_version_repo.find_effective_as_of(
            self._session, company_id=company_id, shift_id=shift_id, as_of=as_of
        )
        if version is None:
            raise ShiftVersionNotFoundForDateError()
        breaks = await self._shift_version_repo.list_breaks(
            self._session, company_id=company_id, shift_version_id=version.id
        )
        duty_blocks = await self._shift_version_repo.list_duty_blocks(
            self._session, company_id=company_id, shift_version_id=version.id
        )
        return shift_version_to_read(version, breaks, duty_blocks)

    # -----------------------------------------------------------------
    # Workforce Calendar (W1) — HolidayCalendar
    # -----------------------------------------------------------------

    async def create_holiday_calendar(
        self,
        company_id: UUID,
        body: HolidayCalendarCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> HolidayCalendarRead:
        now = datetime.now(UTC)
        calendar_id = uuid4()
        try:
            row = await self._holiday_calendar_repo.insert(
                self._session,
                data={
                    "id": calendar_id,
                    "company_id": company_id,
                    "name": body.name,
                    "code": await self._repo.next_auto_code(
                        self._session, model=HolidayCalendar, company_id=company_id, prefix="HC"
                    ),
                    "kind": body.kind,
                    "state_code": body.state_code,
                    "valid_from": body.valid_from,
                    "valid_to": body.valid_to,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise HolidayCalendarCodeAlreadyExistsError() from exc
        read = holiday_calendar_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="HOLIDAY_CALENDAR_CREATED",
            entity_type="holiday_calendar",
            entity_id=calendar_id,
            after=holiday_calendar_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_holiday_calendars(self, company_id: UUID) -> list[HolidayCalendarRead]:
        rows = await self._holiday_calendar_repo.list_calendars(
            self._session, company_id=company_id
        )
        return [holiday_calendar_to_read(row) for row in rows]

    async def get_holiday_calendar(
        self, company_id: UUID, calendar_id: UUID
    ) -> HolidayCalendarRead:
        row = await self._holiday_calendar_repo.get(
            self._session, company_id=company_id, calendar_id=calendar_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return holiday_calendar_to_read(row)

    async def update_holiday_calendar(
        self,
        company_id: UUID,
        calendar_id: UUID,
        patch: HolidayCalendarUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> HolidayCalendarRead:
        row = await self._holiday_calendar_repo.get(
            self._session, company_id=company_id, calendar_id=calendar_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        before_read = holiday_calendar_to_read(row)
        was_active_before = row.is_active

        values = build_holiday_calendar_update_values(patch)
        if not values:
            return before_read
        merged_from = values["valid_from"] if "valid_from" in values else row.valid_from
        merged_to = values["valid_to"] if "valid_to" in values else row.valid_to
        if merged_from is not None and merged_to is not None and merged_from > merged_to:
            raise ValidationError(
                "valid_from must not be after valid_to",
                details=[
                    {
                        "field": "valid_from",
                        "code": "HOLIDAY_CALENDAR_VALIDITY_INVALID",
                        "message": "valid_from must not be after valid_to",
                    }
                ],
            )

        now = datetime.now(UTC)
        try:
            updated = await self._holiday_calendar_repo.update(
                self._session,
                company_id=company_id,
                calendar_id=calendar_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise HolidayCalendarCodeAlreadyExistsError() from exc
        if updated is None:
            current = await self._holiday_calendar_repo.get(
                self._session, company_id=company_id, calendar_id=calendar_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            raise StaleResourceError(
                "This holiday calendar has been modified by another request",
                current=holiday_calendar_to_audit_dict(holiday_calendar_to_read(current)),
            )

        after_read = holiday_calendar_to_read(updated)
        action = (
            "HOLIDAY_CALENDAR_DEACTIVATED"
            if patch.is_active is False and was_active_before is True
            else "HOLIDAY_CALENDAR_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "HOLIDAY_CALENDAR_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="holiday_calendar",
            entity_id=calendar_id,
            before=holiday_calendar_to_audit_dict(before_read),
            after=holiday_calendar_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_holiday_calendar(
        self,
        company_id: UUID,
        calendar_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> HolidayCalendarRead:
        return await self.update_holiday_calendar(
            company_id,
            calendar_id,
            HolidayCalendarUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # -----------------------------------------------------------------
    # Workforce Calendar (W1) — Holiday
    # -----------------------------------------------------------------

    async def create_holiday(
        self,
        company_id: UUID,
        calendar_id: UUID,
        body: HolidayCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> HolidayRead:
        calendar = await self._holiday_calendar_repo.get(
            self._session, company_id=company_id, calendar_id=calendar_id
        )
        if calendar is None:
            raise InvalidHolidayCalendarError()

        now = datetime.now(UTC)
        holiday_id = uuid4()
        try:
            row = await self._holiday_repo.insert(
                self._session,
                data={
                    "id": holiday_id,
                    "company_id": company_id,
                    "calendar_id": calendar_id,
                    "date": body.date,
                    "name": body.name,
                    "is_optional": body.holiday_type == "OPTIONAL",
                    "holiday_type": body.holiday_type,
                    "is_paid": body.is_paid,
                    "is_working": reconcile_holiday_is_working(
                        holiday_type=body.holiday_type,
                        is_working=body.is_working,
                        explicit="is_working" in body.model_fields_set,
                    ),
                    "region_note": body.region_note,
                    "replaced_holiday_id": body.replaced_holiday_id,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise HolidayDateAlreadyExistsError() from exc
        read = holiday_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="HOLIDAY_CREATED",
            entity_type="holiday",
            entity_id=holiday_id,
            after=holiday_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_holidays(
        self, company_id: UUID, calendar_id: UUID, *, year: int | None = None, page: PageParams
    ) -> tuple[list[HolidayRead], int]:
        rows = await self._holiday_repo.list_holidays(
            self._session,
            company_id=company_id,
            calendar_id=calendar_id,
            year=year,
            limit=page.limit,
            offset=page.offset,
        )
        total = await self._holiday_repo.count_holidays(
            self._session, company_id=company_id, calendar_id=calendar_id, year=year
        )
        return [holiday_to_read(row) for row in rows], total

    async def get_holiday(self, company_id: UUID, holiday_id: UUID) -> HolidayRead:
        row = await self._holiday_repo.get(
            self._session, company_id=company_id, holiday_id=holiday_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return holiday_to_read(row)

    async def update_holiday(
        self,
        company_id: UUID,
        holiday_id: UUID,
        patch: HolidayUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> HolidayRead:
        row = await self._holiday_repo.get(
            self._session, company_id=company_id, holiday_id=holiday_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        before_read = holiday_to_read(row)
        was_active_before = row.is_active

        values = build_holiday_update_values(patch)
        if not values:
            return before_read
        if "is_working" in values or "holiday_type" in values:
            # Policy C: the flag mirrors the type. A legacy row that already disagrees is left
            # alone unless this edit touches the type or the flag.
            values["is_working"] = reconcile_holiday_is_working(
                holiday_type=values.get("holiday_type") or row.holiday_type,
                is_working=values.get("is_working", row.is_working),
                explicit="is_working" in values,
            )

        now = datetime.now(UTC)
        updated = await self._holiday_repo.update(
            self._session,
            company_id=company_id,
            holiday_id=holiday_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._holiday_repo.get(
                self._session, company_id=company_id, holiday_id=holiday_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            raise StaleResourceError(
                "This holiday has been modified by another request",
                current=holiday_to_audit_dict(holiday_to_read(current)),
            )

        after_read = holiday_to_read(updated)
        action = (
            "HOLIDAY_DEACTIVATED"
            if patch.is_active is False and was_active_before is True
            else "HOLIDAY_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "HOLIDAY_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="holiday",
            entity_id=holiday_id,
            before=holiday_to_audit_dict(before_read),
            after=holiday_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    # -----------------------------------------------------------------
    # Workforce Calendar (W1) — WeeklyOffPattern
    # -----------------------------------------------------------------

    def _validate_weekly_off_rules(
        self, pattern_kind: str, rules: list[WeeklyOffRuleInput]
    ) -> None:
        """architecture §8.1 — the rule shape must match the declared `pattern_kind`. `CUSTOM`
        accepts any combination (that is the point of `CUSTOM`)."""
        if pattern_kind == "CUSTOM":
            return
        for rule in rules:
            if pattern_kind == "NTH_WEEKDAY" and rule.nth_in_month is None:
                raise WeeklyOffRuleInvalidError(
                    "nth_in_month is required for every rule when pattern_kind is NTH_WEEKDAY"
                )
            if pattern_kind == "ALTERNATE" and rule.cycle_start_date is None:
                raise WeeklyOffRuleInvalidError(
                    "cycle_start_date is required for every rule when pattern_kind is ALTERNATE"
                )
            if pattern_kind == "FIXED_WEEKDAYS" and (
                rule.nth_in_month is not None or rule.cycle_start_date is not None
            ):
                raise WeeklyOffRuleInvalidError(
                    "nth_in_month/cycle_start_date must be omitted when "
                    "pattern_kind is FIXED_WEEKDAYS"
                )

    async def create_weekly_off_pattern(
        self,
        company_id: UUID,
        body: WeeklyOffPatternCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WeeklyOffPatternRead:
        self._validate_weekly_off_rules(body.pattern_kind, body.rules)

        now = datetime.now(UTC)
        pattern_id = uuid4()
        row = await self._weekly_off_repo.insert(
            self._session,
            data={
                "id": pattern_id,
                "company_id": company_id,
                "name": body.name,
                "code": await self._repo.next_auto_code(
                    self._session, model=WeeklyOffPattern, company_id=company_id, prefix="WOP"
                ),
                "pattern_kind": body.pattern_kind,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        rules = await self._weekly_off_repo.replace_rules(
            self._session,
            company_id=company_id,
            pattern_id=pattern_id,
            rows=[
                {
                    "id": uuid4(),
                    "company_id": company_id,
                    "pattern_id": pattern_id,
                    "weekday": rule.weekday,
                    "nth_in_month": rule.nth_in_month,
                    "cycle_start_date": rule.cycle_start_date,
                    "off_fraction": rule.off_fraction,
                    "week_parity": rule.week_parity,
                }
                for rule in body.rules
            ],
        )
        read = weekly_off_pattern_to_read(row, rules)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="WEEKLY_OFF_PATTERN_CREATED",
            entity_type="weekly_off_pattern",
            entity_id=pattern_id,
            after=weekly_off_pattern_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_weekly_off_patterns(self, company_id: UUID) -> list[WeeklyOffPatternRead]:
        rows = await self._weekly_off_repo.list_patterns(self._session, company_id=company_id)
        all_rules = await self._weekly_off_repo.list_rules_for_patterns(
            self._session, company_id=company_id, pattern_ids=[row.id for row in rows]
        )
        rules_by_pattern: dict[UUID, list[Any]] = {row.id: [] for row in rows}
        for rule in all_rules:
            rules_by_pattern[rule.pattern_id].append(rule)
        return [weekly_off_pattern_to_read(row, rules_by_pattern[row.id]) for row in rows]

    async def get_weekly_off_pattern(
        self, company_id: UUID, pattern_id: UUID
    ) -> WeeklyOffPatternRead:
        row = await self._weekly_off_repo.get(
            self._session, company_id=company_id, pattern_id=pattern_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        rules = await self._weekly_off_repo.list_rules(
            self._session, company_id=company_id, pattern_id=pattern_id
        )
        return weekly_off_pattern_to_read(row, rules)

    async def update_weekly_off_pattern(
        self,
        company_id: UUID,
        pattern_id: UUID,
        patch: WeeklyOffPatternUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WeeklyOffPatternRead:
        row = await self._weekly_off_repo.get(
            self._session, company_id=company_id, pattern_id=pattern_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        if patch.is_active is False and row.is_active:
            await lock_calendar_policy_dependencies(self._session, company_id)
            await self._ensure_weekly_off_pattern_unassigned(company_id, pattern_id)
        current_rules = await self._weekly_off_repo.list_rules(
            self._session, company_id=company_id, pattern_id=pattern_id
        )
        before_read = weekly_off_pattern_to_read(row, current_rules)
        was_active_before = row.is_active

        effective_kind = patch.pattern_kind if patch.pattern_kind is not None else row.pattern_kind
        if patch.rules is not None:
            self._validate_weekly_off_rules(effective_kind, patch.rules)

        values = build_weekly_off_pattern_update_values(patch)
        now = datetime.now(UTC)
        updated = row
        if values:
            result = await self._weekly_off_repo.update(
                self._session,
                company_id=company_id,
                pattern_id=pattern_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
            if result is None:
                current = await self._weekly_off_repo.get(
                    self._session, company_id=company_id, pattern_id=pattern_id
                )
                if current is None:
                    raise NotFoundError("Resource not found")
                current_rules_for_error = await self._weekly_off_repo.list_rules(
                    self._session, company_id=company_id, pattern_id=pattern_id
                )
                raise StaleResourceError(
                    "This weekly-off pattern has been modified by another request",
                    current=weekly_off_pattern_to_audit_dict(
                        weekly_off_pattern_to_read(current, current_rules_for_error)
                    ),
                )
            updated = result

        rules = current_rules
        if patch.rules is not None:
            rules = await self._weekly_off_repo.replace_rules(
                self._session,
                company_id=company_id,
                pattern_id=pattern_id,
                rows=[
                    {
                        "id": uuid4(),
                        "company_id": company_id,
                        "pattern_id": pattern_id,
                        "weekday": rule.weekday,
                        "nth_in_month": rule.nth_in_month,
                        "cycle_start_date": rule.cycle_start_date,
                        "off_fraction": rule.off_fraction,
                        "week_parity": rule.week_parity,
                    }
                    for rule in patch.rules
                ],
            )

        after_read = weekly_off_pattern_to_read(updated, rules)
        action = (
            "WEEKLY_OFF_PATTERN_DEACTIVATED"
            if patch.is_active is False and was_active_before is True
            else "WEEKLY_OFF_PATTERN_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "WEEKLY_OFF_PATTERN_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="weekly_off_pattern",
            entity_id=pattern_id,
            before=weekly_off_pattern_to_audit_dict(before_read),
            after=weekly_off_pattern_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_weekly_off_pattern(
        self,
        company_id: UUID,
        pattern_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WeeklyOffPatternRead:
        return await self.update_weekly_off_pattern(
            company_id,
            pattern_id,
            WeeklyOffPatternUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # -----------------------------------------------------------------
    # Workforce Calendar (W1) — WorkCalendar
    # -----------------------------------------------------------------

    async def _validate_work_calendar_composition(
        self, company_id: UUID, weekly_off_pattern_id: UUID | None, holiday_calendar_ids: list[UUID]
    ) -> None:
        if weekly_off_pattern_id is not None:
            pattern = await self._weekly_off_repo.get(
                self._session, company_id=company_id, pattern_id=weekly_off_pattern_id
            )
            if pattern is None:
                raise WorkCalendarCompositionInvalidError(
                    "weekly_off_pattern_id does not reference a valid weekly-off pattern"
                )
        for calendar_id in holiday_calendar_ids:
            calendar = await self._holiday_calendar_repo.get(
                self._session, company_id=company_id, calendar_id=calendar_id
            )
            if calendar is None:
                raise WorkCalendarCompositionInvalidError(
                    f"holiday_calendar_ids contains an invalid calendar id: {calendar_id}"
                )

    async def create_work_calendar(
        self,
        company_id: UUID,
        body: WorkCalendarCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WorkCalendarRead:
        await self._validate_work_calendar_composition(
            company_id, body.weekly_off_pattern_id, body.holiday_calendar_ids
        )

        now = datetime.now(UTC)
        work_calendar_id = uuid4()
        try:
            row = await self._work_calendar_repo.insert(
                self._session,
                data={
                    "id": work_calendar_id,
                    "company_id": company_id,
                    "name": body.name,
                    "code": await self._repo.next_auto_code(
                        self._session, model=WorkCalendar, company_id=company_id, prefix="WC"
                    ),
                    "description": body.description,
                    "weekly_off_pattern_id": body.weekly_off_pattern_id,
                    "restricted_holidays_are_off_by_default": (
                        body.restricted_holidays_are_off_by_default
                    ),
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise WorkCalendarCompositionInvalidError(
                "A work calendar with this code already exists"
            ) from exc
        await self._work_calendar_repo.replace_holiday_calendar_links(
            self._session,
            company_id=company_id,
            work_calendar_id=work_calendar_id,
            holiday_calendar_ids=body.holiday_calendar_ids,
            now=now,
        )
        read = work_calendar_to_read(row, body.holiday_calendar_ids)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="WORK_CALENDAR_CREATED",
            entity_type="work_calendar",
            entity_id=work_calendar_id,
            after=work_calendar_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def _work_calendar_holiday_ids(
        self, company_id: UUID, work_calendar_id: UUID
    ) -> list[UUID]:
        links = await self._work_calendar_repo.list_holiday_calendar_links(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        return [link.holiday_calendar_id for link in links]

    async def list_work_calendars(self, company_id: UUID) -> list[WorkCalendarRead]:
        rows = await self._work_calendar_repo.list_work_calendars(
            self._session, company_id=company_id
        )
        return [
            work_calendar_to_read(row, await self._work_calendar_holiday_ids(company_id, row.id))
            for row in rows
        ]

    async def get_work_calendar(self, company_id: UUID, work_calendar_id: UUID) -> WorkCalendarRead:
        row = await self._work_calendar_repo.get(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return work_calendar_to_read(
            row, await self._work_calendar_holiday_ids(company_id, work_calendar_id)
        )

    async def update_work_calendar(
        self,
        company_id: UUID,
        work_calendar_id: UUID,
        patch: WorkCalendarUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WorkCalendarRead:
        row = await self._work_calendar_repo.get(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        if patch.is_active is False and row.is_active:
            # Policy F: serialised against a concurrent assignment, then checked.
            await lock_calendar_policy_dependencies(self._session, company_id)
            await self._ensure_work_calendar_unassigned(company_id, work_calendar_id)
        elif patch.weekly_off_pattern_id is not None:
            await lock_calendar_policy_dependencies(self._session, company_id)
        current_holiday_ids = await self._work_calendar_holiday_ids(company_id, work_calendar_id)
        before_read = work_calendar_to_read(row, current_holiday_ids)
        was_active_before = row.is_active

        effective_pattern_id = (
            patch.weekly_off_pattern_id
            if "weekly_off_pattern_id" in patch.model_fields_set
            else row.weekly_off_pattern_id
        )
        effective_holiday_ids = (
            patch.holiday_calendar_ids
            if patch.holiday_calendar_ids is not None
            else current_holiday_ids
        )
        await self._validate_work_calendar_composition(
            company_id, effective_pattern_id, effective_holiday_ids
        )

        values = build_work_calendar_update_values(patch)
        now = datetime.now(UTC)
        updated = row
        if values:
            try:
                result = await self._work_calendar_repo.update(
                    self._session,
                    company_id=company_id,
                    work_calendar_id=work_calendar_id,
                    values=values,
                    expected_version=expected_version,
                    now=now,
                )
            except IntegrityError as exc:
                await self._session.rollback()
                raise WorkCalendarCompositionInvalidError(
                    "A work calendar with this code already exists"
                ) from exc
            if result is None:
                current = await self._work_calendar_repo.get(
                    self._session, company_id=company_id, work_calendar_id=work_calendar_id
                )
                if current is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This work calendar has been modified by another request",
                    current=work_calendar_to_audit_dict(
                        work_calendar_to_read(
                            current,
                            await self._work_calendar_holiday_ids(company_id, work_calendar_id),
                        )
                    ),
                )
            updated = result

        holiday_ids = current_holiday_ids
        if patch.holiday_calendar_ids is not None:
            await self._work_calendar_repo.replace_holiday_calendar_links(
                self._session,
                company_id=company_id,
                work_calendar_id=work_calendar_id,
                holiday_calendar_ids=patch.holiday_calendar_ids,
                now=now,
            )
            holiday_ids = patch.holiday_calendar_ids

        after_read = work_calendar_to_read(updated, holiday_ids)
        action = (
            "WORK_CALENDAR_DEACTIVATED"
            if patch.is_active is False and was_active_before is True
            else "WORK_CALENDAR_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "WORK_CALENDAR_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="work_calendar",
            entity_id=work_calendar_id,
            before=work_calendar_to_audit_dict(before_read),
            after=work_calendar_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def _calendar_dependents(
        self, company_id: UUID, policy_kind: str, policy_id: UUID
    ) -> tuple[int, list[dict[str, str | None]]]:
        company = await self._repo.get_company(self._session, company_id=company_id)
        as_of = business_today(company.timezone) if company is not None else date.today()
        total, rows = await self._policy_assignment_repo.list_dependents(
            self._session,
            company_id=company_id,
            policy_kind=policy_kind,
            policy_id=policy_id,
            as_of=as_of,
        )
        return total, [
            {
                "scope_type": r.scope_type,
                "scope_id": str(r.scope_id) if r.scope_id else None,
                "effective_from": r.effective_from.isoformat(),
                "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            }
            for r in rows
        ]

    async def _ensure_work_calendar_unassigned(self, company_id: UUID, calendar_id: UUID) -> None:
        total, items = await self._calendar_dependents(company_id, "WORK_CALENDAR", calendar_id)
        if total:
            raise WorkCalendarDeactivationBlockedError(
                active_assignment_count=total, dependents=items
            )

    async def _ensure_weekly_off_pattern_unassigned(
        self, company_id: UUID, pattern_id: UUID
    ) -> None:
        total, items = await self._calendar_dependents(company_id, "WEEKLY_OFF", pattern_id)
        defaults = await self._work_calendar_repo.count_active_with_default_pattern(
            self._session, company_id=company_id, pattern_id=pattern_id
        )
        if total or defaults:
            raise WeeklyOffPatternDeactivationBlockedError(
                active_assignment_count=total, dependents=items, default_for_calendars=defaults
            )

    async def deactivate_work_calendar(
        self,
        company_id: UUID,
        work_calendar_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> WorkCalendarRead:
        """Architecture §4.2: "Blocked if referenced by an open assignment". The check itself lives
        in `update_work_calendar` so the `PATCH is_active=false` route cannot bypass it."""
        return await self.update_work_calendar(
            company_id,
            work_calendar_id,
            WorkCalendarUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def get_work_calendar_day_type(
        self, company_id: UUID, work_calendar_id: UUID, target_date: date
    ) -> DayTypeRead:
        return await self._calendar_resolution.classify_date_for_work_calendar(
            company_id, work_calendar_id, target_date
        )

    # -----------------------------------------------------------------
    # Workforce Calendar (W1) — CalendarException
    # -----------------------------------------------------------------

    async def create_calendar_exception(
        self,
        company_id: UUID,
        work_calendar_id: UUID,
        body: CalendarExceptionCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CalendarExceptionRead:
        calendar = await self._work_calendar_repo.get(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        if calendar is None:
            raise InvalidWorkCalendarError()

        now = datetime.now(UTC)
        exception_id = uuid4()
        try:
            row = await self._calendar_exception_repo.insert(
                self._session,
                data={
                    "id": exception_id,
                    "company_id": company_id,
                    "work_calendar_id": work_calendar_id,
                    "exception_date": body.exception_date,
                    "exception_type": body.exception_type,
                    "name": body.name,
                    "reason": body.reason,
                    "is_paid": body.is_paid,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise CalendarExceptionDateConflictError() from exc
        read = calendar_exception_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="CALENDAR_EXCEPTION_CREATED",
            entity_type="calendar_exception",
            entity_id=exception_id,
            after=calendar_exception_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_calendar_exceptions(
        self, company_id: UUID, work_calendar_id: UUID, *, page: PageParams
    ) -> tuple[list[CalendarExceptionRead], int]:
        rows = await self._calendar_exception_repo.list_exceptions(
            self._session,
            company_id=company_id,
            work_calendar_id=work_calendar_id,
            limit=page.limit,
            offset=page.offset,
        )
        total = await self._calendar_exception_repo.count_exceptions(
            self._session, company_id=company_id, work_calendar_id=work_calendar_id
        )
        return [calendar_exception_to_read(row) for row in rows], total

    async def update_calendar_exception(
        self,
        company_id: UUID,
        exception_id: UUID,
        patch: CalendarExceptionUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CalendarExceptionRead:
        row = await self._calendar_exception_repo.get(
            self._session, company_id=company_id, exception_id=exception_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        before_read = calendar_exception_to_read(row)
        was_active_before = row.is_active

        values = build_calendar_exception_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._calendar_exception_repo.update(
            self._session,
            company_id=company_id,
            exception_id=exception_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._calendar_exception_repo.get(
                self._session, company_id=company_id, exception_id=exception_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            raise StaleResourceError(
                "This calendar exception has been modified by another request",
                current=calendar_exception_to_audit_dict(calendar_exception_to_read(current)),
            )

        after_read = calendar_exception_to_read(updated)
        action = (
            "CALENDAR_EXCEPTION_DEACTIVATED"
            if patch.is_active is False and was_active_before is True
            else "CALENDAR_EXCEPTION_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "CALENDAR_EXCEPTION_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="calendar_exception",
            entity_id=exception_id,
            before=calendar_exception_to_audit_dict(before_read),
            after=calendar_exception_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    # -----------------------------------------------------------------
    # Workforce Calendar (W1) + W3 — PolicyAssignment (WD-09 precedence machinery, widened by
    # W3's migration to also carry ATTENDANCE_POLICY/OVERTIME_POLICY/REGULARIZATION_POLICY —
    # see WD-24 in the decision log)
    # -----------------------------------------------------------------

    async def _validate_policy_reference(
        self,
        company_id: UUID,
        policy_kind: str,
        policy_id: UUID,
        leave_type_id: UUID | None = None,
    ) -> None:
        found: Any
        # Work calendars and weekly-off patterns have no versions, so nothing to publish.
        is_published = True
        if policy_kind == "WORK_CALENDAR":
            found = await self._work_calendar_repo.get(
                self._session, company_id=company_id, work_calendar_id=policy_id
            )
        elif policy_kind == "WEEKLY_OFF":
            found = await self._weekly_off_repo.get(
                self._session, company_id=company_id, pattern_id=policy_id
            )
        elif policy_kind in ("ATTENDANCE_POLICY", "OVERTIME_POLICY", "REGULARIZATION_POLICY"):
            # Local, function-scoped import — mirrors the established reverse-direction
            # precedent (`employee/service.py` imports `organisation.service.OrganisationService`
            # locally; `calendar_resolution.py` imports `employee.service` locally). W3's
            # AttendancePolicy/OvertimePolicy/RegularizationPolicy identities live in the
            # `attendance` module (DEC-023), not `organisation` — this is the one place
            # `organisation` needs to know they exist, to validate a polymorphic `policy_id`
            # the same way it already does for its own WORK_CALENDAR/WEEKLY_OFF kinds.
            from hrms.modules.attendance.service import AttendanceService

            attendance = AttendanceService(self._session)
            found = await attendance.find_policy(company_id, policy_kind, policy_id)
            is_published = found is not None and await attendance.policy_is_published(
                company_id, policy_kind, policy_id
            )
        elif policy_kind == "LEAVE_POLICY":
            # Same local-import rationale as the ATTENDANCE_POLICY/OVERTIME_POLICY/
            # REGULARIZATION_POLICY branch above — LeavePolicy's identity lives in the `leave`
            # module (LEAVE_DECISION_LOG.md LD-04), not `organisation`. LD-11: also checks the
            # referenced policy's own `leave_type_id` matches the assignment's — a request can't
            # name a Casual Leave policy but tag the assignment as Earned Leave.
            from hrms.modules.leave.service import LeavePolicyService

            leave_policies = LeavePolicyService(self._session)
            try:
                policy = await leave_policies.get_policy(company_id, policy_id)
                found = policy if policy.leave_type_id == leave_type_id else None
                is_published = found is not None and await leave_policies.policy_is_published(
                    company_id, policy_id
                )
            except NotFoundError:
                found = None
        else:
            raise PolicyKindNotSupportedError(policy_kind)
        if found is None or getattr(found, "is_active", True) is False:
            raise InvalidPolicyReferenceError()
        if not is_published:
            raise PolicyNotPublishedError()

    async def _validate_policy_scope(
        self, company_id: UUID, scope_type: str, scope_id: UUID | None
    ) -> None:
        if scope_type == "COMPANY" or scope_id is None:
            return
        try:
            if scope_type == "LEGAL_ENTITY":
                await self.get_legal_entity(company_id, scope_id)
            elif scope_type == "BRANCH":
                await self.get_branch(company_id, scope_id)
            elif scope_type == "DEPARTMENT":
                await self.get_department(company_id, scope_id)
            elif scope_type == "GRADE":
                await self.get_grade(company_id, scope_id)
            elif scope_type == "DESIGNATION":
                await self.get_designation(company_id, scope_id)
            elif scope_type == "SHIFT":
                await self.get_shift(company_id, scope_id)
            elif scope_type == "EMPLOYEE":
                # Same local-import precedent as `_validate_policy_reference` above.
                from hrms.modules.employee.repository import EmployeeRepository

                employee = await EmployeeRepository().get_employee(
                    self._session, company_id=company_id, employee_id=scope_id
                )
                if employee is None:
                    raise InvalidPolicyScopeError()
        except NotFoundError as exc:
            raise InvalidPolicyScopeError() from exc

    async def create_policy_assignment(
        self,
        company_id: UUID,
        body: PolicyAssignmentCreate,
        *,
        expected_version: int | None = None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PolicyAssignmentRead:
        """Insert-new/close-previous — mirrors `EmployeeAssignmentService.create_assignment`
        (see architecture doc §15.1: "no overlap at same scope... close the old assignment and
        insert a new one"), keyed on `(policy_kind, scope_type, scope_id)` instead of
        `employee_id` — plus `leave_type_id` (LD-11) when `policy_kind` is `LEAVE_POLICY`."""
        if body.policy_kind in ("WORK_CALENDAR", "WEEKLY_OFF"):
            # Policy F: serialised against deactivation; an inactive calendar/pattern is not
            # assignable, so the dependency cannot be created after the deactivation either.
            await lock_calendar_policy_dependencies(self._session, company_id)
        await self._validate_policy_reference(
            company_id, body.policy_kind, body.policy_id, body.leave_type_id
        )
        await self._validate_policy_scope(company_id, body.scope_type, body.scope_id)

        current = await self._policy_assignment_repo.get_current(
            self._session,
            company_id=company_id,
            policy_kind=body.policy_kind,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            leave_type_id=body.leave_type_id,
        )
        now = datetime.now(UTC)
        before_read: PolicyAssignmentRead | None = None
        if current is not None:
            if body.effective_from <= current.effective_from:
                raise ValidationError(
                    "effective_from must be after the current assignment's effective_from",
                    code="INVALID_EFFECTIVE_FROM",
                )
            if expected_version is None:
                raise PolicyAssignmentVersionRequiredError()
            before_read = policy_assignment_to_read(current)
            closed = await self._policy_assignment_repo.close(
                self._session,
                company_id=company_id,
                assignment_id=current.id,
                effective_to=body.effective_from - timedelta(days=1),
                expected_version=expected_version,
                now=now,
            )
            if closed is None:
                latest = await self._policy_assignment_repo.get(
                    self._session, company_id=company_id, assignment_id=current.id
                )
                if latest is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This assignment has been modified by another request",
                    current=policy_assignment_to_audit_dict(policy_assignment_to_read(latest)),
                )

        assignment_id = uuid4()
        try:
            row = await self._policy_assignment_repo.insert(
                self._session,
                data={
                    "id": assignment_id,
                    "company_id": company_id,
                    "policy_kind": body.policy_kind,
                    "policy_id": body.policy_id,
                    "leave_type_id": body.leave_type_id,
                    "scope_type": body.scope_type,
                    "scope_id": body.scope_id,
                    "effective_from": body.effective_from,
                    "effective_to": body.effective_to,
                    "priority": body.priority,
                    "reason": body.reason,
                    "is_active": True,
                    # Continues the chain's version counter (the closed row was bumped to
                    # `expected_version + 1`) instead of restarting at 1 — otherwise a stale
                    # `If-Match` that an earlier revision already consumed would match this row.
                    "version": 1 if current is None else (expected_version or 0) + 2,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            await self._session.rollback()
            raise PolicyAssignmentOverlapError() from exc

        read = policy_assignment_to_read(row)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="POLICY_ASSIGNMENT_CHANGED",
            entity_type="policy_assignment",
            entity_id=assignment_id,
            before=policy_assignment_to_audit_dict(before_read)
            if before_read is not None
            else None,
            after=policy_assignment_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def get_policy_assignment(
        self, company_id: UUID, assignment_id: UUID
    ) -> PolicyAssignmentRead:
        row = await self._policy_assignment_repo.get(
            self._session, company_id=company_id, assignment_id=assignment_id
        )
        if row is None:
            raise NotFoundError("Resource not found")
        return policy_assignment_to_read(row)

    async def end_policy_assignment(
        self,
        company_id: UUID,
        assignment_id: UUID,
        body: PolicyAssignmentEnd,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> PolicyAssignmentRead:
        """Closes an open assignment without a replacement, so its scope falls back to the next
        wider assignment from the following day. Company-level assignments are the safety net and
        calendar kinds change day classification (which needs the impact preview), so neither can
        be ended here."""
        current = await self._policy_assignment_repo.get(
            self._session, company_id=company_id, assignment_id=assignment_id
        )
        if current is None:
            raise NotFoundError("Resource not found")
        if current.effective_to is not None:
            raise PolicyAssignmentNotEndableError("This assignment has already ended")
        if current.scope_type == "COMPANY":
            raise PolicyAssignmentNotEndableError(
                "A company-wide assignment can only be replaced, so nobody is left without a policy"
            )
        if current.policy_kind in ("WORK_CALENDAR", "WEEKLY_OFF"):
            raise PolicyAssignmentNotEndableError(
                "Work calendar and weekly-off assignments can only be replaced"
            )
        if body.effective_to < current.effective_from:
            raise ValidationError(
                "The end date cannot be before the assignment's effective date",
                code="INVALID_EFFECTIVE_TO",
            )
        # Any closed period after the end date would have its rules changed retroactively.
        from hrms.modules.attendance.exceptions import AttendancePeriodClosedError
        from hrms.modules.attendance.repository import AttendancePeriodRepository

        if await AttendancePeriodRepository().list_closed_overlapping(
            self._session,
            company_id=company_id,
            date_from=body.effective_to + timedelta(days=1),
            date_to=date.max,
        ):
            raise AttendancePeriodClosedError()

        before_read = policy_assignment_to_read(current)
        closed = await self._policy_assignment_repo.close(
            self._session,
            company_id=company_id,
            assignment_id=assignment_id,
            effective_to=body.effective_to,
            expected_version=expected_version,
            now=datetime.now(UTC),
        )
        if closed is None:
            raise StaleResourceError(
                "This assignment has been modified by another request",
                current=policy_assignment_to_audit_dict(before_read),
            )
        read = policy_assignment_to_read(closed)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="POLICY_ASSIGNMENT_CHANGED",
            entity_type="policy_assignment",
            entity_id=assignment_id,
            before=policy_assignment_to_audit_dict(before_read),
            after=policy_assignment_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_policy_assignments(
        self,
        company_id: UUID,
        *,
        policy_kind: str | None = None,
        scope_type: str | None = None,
        scope_id: UUID | None = None,
        leave_type_id: UUID | None = None,
        current_only: bool = False,
        page: PageParams,
    ) -> tuple[list[PolicyAssignmentRead], int]:
        rows = await self._policy_assignment_repo.list_assignments(
            self._session,
            company_id=company_id,
            policy_kind=policy_kind,
            scope_type=scope_type,
            scope_id=scope_id,
            leave_type_id=leave_type_id,
            current_only=current_only,
            limit=page.limit,
            offset=page.offset,
        )
        total = await self._policy_assignment_repo.count_assignments(
            self._session,
            company_id=company_id,
            policy_kind=policy_kind,
            scope_type=scope_type,
            scope_id=scope_id,
            leave_type_id=leave_type_id,
            current_only=current_only,
        )
        return [policy_assignment_to_read(row) for row in rows], total

    async def resolve_calendar_for_employee(
        self, company_id: UUID, employee_id: UUID, target_date: date
    ) -> CalendarResolutionRead:
        return await self._calendar_resolution.resolve_for_employee(
            company_id, employee_id, target_date
        )


def _format_optional_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    iso = value.isoformat()
    return iso.replace("+00:00", "Z")


def _format_time(value: time | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M")


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _clock_minutes(value: str) -> int:
    parsed = _parse_time(value)
    return parsed.hour * 60 + parsed.minute
