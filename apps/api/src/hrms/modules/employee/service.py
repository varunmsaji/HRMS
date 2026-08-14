"""Business logic for the employee module — E-01 (identity foundation), E-03 (employment
lifecycle), and E-04 (employee assignment)."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings, get_settings
from hrms.core.errors.base import NotFoundError
from hrms.modules.employee.exceptions import (
    AssignmentDatesOverlapError,
    AssignmentFieldsRequiredError,
    AssignmentVersionRequiredError,
    EmployeeSeatLimitExceededError,
    EmploymentDatesOverlapError,
    EmploymentNotActiveError,
    InvalidBranchReferenceError,
    InvalidDepartmentReferenceError,
    InvalidDesignationReferenceError,
    InvalidEffectiveFromError,
    InvalidGradeReferenceError,
    InvalidLastWorkingDayError,
    InvalidLegalEntityReferenceError,
    InvalidReportingManagerError,
    InvalidShiftReferenceError,
    NoActiveEmploymentError,
    ShiftIdRequiredError,
    StaleResourceError,
)
from hrms.modules.employee.repository import (
    EmployeeAssignmentRepository,
    EmployeeRepository,
    EmploymentRepository,
)
from hrms.modules.employee.schemas import (
    AssignmentCreate,
    AssignmentRead,
    EmployeeCreate,
    EmployeeRead,
    EmployeeUpdate,
    EmploymentCreate,
    EmploymentRead,
    EmploymentTerminate,
    EmploymentUpdate,
    assignment_to_audit_dict,
    assignment_to_read,
    build_employee_update_values,
    build_employment_update_values,
    employee_to_audit_dict,
    employee_to_read,
    employment_to_audit_dict,
    employment_to_read,
)


class EmployeeService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeRepository()
        self._audit = AuditService()

    async def _check_seat_limit(self, company_id: UUID) -> None:
        """`EMPLOYEE_SEATS` enforcement (`docs/modules/employee/
        05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A6) — reads the plan's resolved seat limit
        via `OrganisationService`'s public surface (never `organisation.repository`/`.models`
        directly, mirroring how `OrganisationService` itself composes `IdentityService`).
        Imported lazily to avoid a module-level cross-import at collection time for a call that
        only fires on the create path."""
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            summary = await organisation.get_subscription_summary(company_id)
        except NotFoundError:
            # No subscription resolvable for this company — a data-integrity anomaly unrelated
            # to seat counting. Fail open on *unresolvable* data rather than blocking all
            # employee creation; an *actually resolved* limit is still enforced below
            # (01_EMPLOYEE_FOUNDATION_AUDIT.md §2.4).
            return

        if summary.seat_limit is None:
            return

        active_count = await self._repo.count_active_employees(self._session, company_id=company_id)
        if active_count >= summary.seat_limit:
            raise EmployeeSeatLimitExceededError(limit=summary.seat_limit)

    async def create_employee(
        self,
        company_id: UUID,
        body: EmployeeCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeRead:
        await self._check_seat_limit(company_id)

        employee_code = await self._repo.allocate_employee_code(
            self._session, company_id=company_id
        )

        now = datetime.now(UTC)
        employee_id = uuid4()
        employee = await self._repo.insert_employee(
            self._session,
            data={
                "id": employee_id,
                "company_id": company_id,
                "employee_code": employee_code,
                "first_name": body.first_name,
                "middle_name": body.middle_name,
                "last_name": body.last_name,
                "date_of_birth": body.date_of_birth,
                "gender": body.gender,
                "blood_group": body.blood_group,
                "marital_status": body.marital_status,
                "nationality": body.nationality,
                "personal_email": body.personal_email,
                "personal_mobile": body.personal_mobile,
                "photo_url": body.photo_url,
                "custom_fields": body.custom_fields,
                "status": "PRE_JOINING",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )

        read = employee_to_read(employee)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_CREATED",
            entity_type="employee",
            entity_id=employee_id,
            after=employee_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_employees(self, company_id: UUID) -> list[EmployeeRead]:
        employees = await self._repo.list_employees(self._session, company_id=company_id)
        return [employee_to_read(employee) for employee in employees]

    async def get_employee(self, company_id: UUID, employee_id: UUID) -> EmployeeRead:
        employee = await self._repo.get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if employee is None:
            raise NotFoundError("Resource not found")
        return employee_to_read(employee)

    async def update_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        patch: EmployeeUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeRead:
        employee = await self._repo.get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if employee is None:
            raise NotFoundError("Resource not found")

        before_read = employee_to_read(employee)
        # Captured before `update_employee` runs below: the `UPDATE ... RETURNING` synchronizes
        # the session's identity map, mutating this same already-loaded `employee` instance in
        # place (same gotcha documented on `OrganisationService.update_grade`) — reading
        # `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = employee.is_active

        values = build_employee_update_values(patch)
        if not values:
            return before_read

        deactivating = patch.is_active is False and was_active_before is True

        now = datetime.now(UTC)
        updated = await self._repo.update_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_employee(
                self._session, company_id=company_id, employee_id=employee_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = employee_to_read(current)
            raise StaleResourceError(
                "This employee has been modified by another request",
                current=employee_to_audit_dict(current_read),
            )

        after_read = employee_to_read(updated)
        action = (
            "EMPLOYEE_DEACTIVATED"
            if deactivating
            else "EMPLOYEE_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "EMPLOYEE_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="employee",
            entity_id=employee_id,
            before=employee_to_audit_dict(before_read),
            after=employee_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeRead:
        """Semantic wrapper around `update_employee` for `DELETE /employees/{id}` — never a
        hard delete. This is an account-level lock (e.g. suspected fraud, immediate access
        cutoff), deliberately distinct from `status → EXITED` (the FR-EMP-014 lifecycle
        transition the Exit module will drive) — `03_EMPLOYEE_API_PLAN.md` §2.1 flags this
        distinction as unconfirmed by product; this slice only implements the soft-deactivate
        CRUD parity every other organisation-module entity has, not the exit lifecycle."""
        return await self.update_employee(
            company_id,
            employee_id,
            EmployeeUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )


class EmploymentService:
    """E-03 — employment lifecycle. Create (first hire or rehire), read/list (incl. as-of-date),
    update (the one correctable field, `legal_entity_id`), and terminate (one-way `ACTIVE` →
    `TERMINATED`)."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmploymentRepository()
        self._employee_repo = EmployeeRepository()
        self._audit = AuditService()

    async def _assert_employee_exists(self, company_id: UUID, employee_id: UUID) -> None:
        employee = await self._employee_repo.get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if employee is None:
            raise NotFoundError("Resource not found")

    async def _assert_legal_entity_ownership(self, company_id: UUID, legal_entity_id: UUID) -> None:
        """An `Employment` may only reference a Legal Entity that exists and belongs to the
        same tenant — mirrors `OrganisationService._assert_legal_entity_ownership` exactly
        (same rationale: the FK constraint alone would surface an opaque 500, not the
        documented 422 envelope). Imported lazily, same cross-module-import convention as
        `EmployeeService._check_seat_limit` — `organisation.service` is the only surface this
        module may import from (Module Standard §2), never `.repository`/`.models`."""
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_legal_entity(company_id, legal_entity_id)
        except NotFoundError as exc:
            raise InvalidLegalEntityReferenceError() from exc

    async def create_employment(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmploymentCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmploymentRead:
        await self._assert_employee_exists(company_id, employee_id)
        await self._assert_legal_entity_ownership(company_id, body.legal_entity_id)

        previous = await self._repo.get_latest_employment(
            self._session, company_id=company_id, employee_id=employee_id
        )
        previous_employment_id = previous.id if previous is not None else None

        now = datetime.now(UTC)
        employment_id = uuid4()
        try:
            employment = await self._repo.insert_employment(
                self._session,
                data={
                    "id": employment_id,
                    "company_id": company_id,
                    "employee_id": employee_id,
                    "legal_entity_id": body.legal_entity_id,
                    "joining_date": body.joining_date,
                    "status": "ACTIVE",
                    "previous_employment_id": previous_employment_id,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            # `employment_no_overlap` GiST exclusion constraint — the race-condition backstop
            # for "employee already has an active employment" / a genuine date overlap with a
            # historical spell (`InvalidLastWorkingDayError`'s pre-check below covers the
            # common non-race case; this covers concurrent creates).
            raise EmploymentDatesOverlapError() from exc

        read = employment_to_read(employment)
        action = (
            "EMPLOYMENT_REHIRED" if previous_employment_id is not None else "EMPLOYMENT_STARTED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="employment",
            entity_id=employment_id,
            after=employment_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_employments(
        self, company_id: UUID, employee_id: UUID, *, as_of: date | None = None
    ) -> list[EmploymentRead]:
        await self._assert_employee_exists(company_id, employee_id)
        if as_of is not None:
            employment = await self._repo.get_employment_as_of(
                self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
            )
            return [employment_to_read(employment)] if employment is not None else []
        employments = await self._repo.list_employments(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [employment_to_read(employment) for employment in employments]

    async def get_employment(
        self, company_id: UUID, employee_id: UUID, employment_id: UUID
    ) -> EmploymentRead:
        await self._assert_employee_exists(company_id, employee_id)
        employment = await self._repo.get_employment(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            employment_id=employment_id,
        )
        if employment is None:
            raise NotFoundError("Resource not found")
        return employment_to_read(employment)

    async def update_employment(
        self,
        company_id: UUID,
        employee_id: UUID,
        employment_id: UUID,
        patch: EmploymentUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmploymentRead:
        await self._assert_employee_exists(company_id, employee_id)
        employment = await self._repo.get_employment(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            employment_id=employment_id,
        )
        if employment is None:
            raise NotFoundError("Resource not found")
        if employment.status != "ACTIVE":
            raise EmploymentNotActiveError(
                "This employment has been terminated and can no longer be modified"
            )

        before_read = employment_to_read(employment)
        values = build_employment_update_values(patch)
        if not values:
            return before_read

        if "legal_entity_id" in values:
            await self._assert_legal_entity_ownership(company_id, values["legal_entity_id"])

        now = datetime.now(UTC)
        updated = await self._repo.update_employment(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            employment_id=employment_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_employment(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                employment_id=employment_id,
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = employment_to_read(current)
            raise StaleResourceError(
                "This employment has been modified by another request",
                current=employment_to_audit_dict(current_read),
            )

        after_read = employment_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYMENT_UPDATED",
            entity_type="employment",
            entity_id=employment_id,
            before=employment_to_audit_dict(before_read),
            after=employment_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def terminate_employment(
        self,
        company_id: UUID,
        employee_id: UUID,
        employment_id: UUID,
        body: EmploymentTerminate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmploymentRead:
        """Transitions the current episode `ACTIVE` → `TERMINATED`, one-way — there is no
        action anywhere in this module that reopens a terminated employment. A later rejoin is
        always a new `create_employment` call, never a reversal of this one
        (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B2)."""
        await self._assert_employee_exists(company_id, employee_id)
        employment = await self._repo.get_employment(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            employment_id=employment_id,
        )
        if employment is None:
            raise NotFoundError("Resource not found")
        if employment.status != "ACTIVE":
            raise EmploymentNotActiveError("This employment is already terminated")
        if body.last_working_day < employment.joining_date:
            raise InvalidLastWorkingDayError()

        before_read = employment_to_read(employment)
        now = datetime.now(UTC)
        updated = await self._repo.update_employment(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            employment_id=employment_id,
            values={"status": "TERMINATED", "last_working_day": body.last_working_day},
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_employment(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                employment_id=employment_id,
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = employment_to_read(current)
            raise StaleResourceError(
                "This employment has been modified by another request",
                current=employment_to_audit_dict(current_read),
            )

        after_read = employment_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYMENT_TERMINATED",
            entity_type="employment",
            entity_id=employment_id,
            before=employment_to_audit_dict(before_read),
            after=employment_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read


class EmployeeAssignmentService:
    """E-04 — employee assignment (org placement + reporting line). One write operation,
    `create_assignment`, covering initial placement/transfer/promotion/manager-change alike
    (`docs/modules/employee/09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §9) — each is an
    insert of a new effective-dated row, never a column update (ADR-0003). No
    `update_assignment`/`delete_assignment` exists; there is no other mutation path."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeAssignmentRepository()
        self._employee_repo = EmployeeRepository()
        self._employment_repo = EmploymentRepository()
        self._audit = AuditService()

    async def _assert_employee_exists(self, company_id: UUID, employee_id: UUID) -> None:
        employee = await self._employee_repo.get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if employee is None:
            raise NotFoundError("Resource not found")

    async def _assert_branch_ownership(self, company_id: UUID, branch_id: UUID) -> None:
        """Cross-module reference check, mirroring
        `EmploymentService._assert_legal_entity_ownership` exactly — imported lazily,
        `organisation.service` is the only surface this module may import from (Module
        Standard §2), never `.repository`/`.models`."""
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_branch(company_id, branch_id)
        except NotFoundError as exc:
            raise InvalidBranchReferenceError() from exc

    async def _assert_department_ownership(self, company_id: UUID, department_id: UUID) -> None:
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_department(company_id, department_id)
        except NotFoundError as exc:
            raise InvalidDepartmentReferenceError() from exc

    async def _assert_designation_ownership(self, company_id: UUID, designation_id: UUID) -> None:
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_designation(company_id, designation_id)
        except NotFoundError as exc:
            raise InvalidDesignationReferenceError() from exc

    async def _assert_grade_ownership(self, company_id: UUID, grade_id: UUID) -> None:
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_grade(company_id, grade_id)
        except NotFoundError as exc:
            raise InvalidGradeReferenceError() from exc

    async def _assert_shift_ownership(self, company_id: UUID, shift_id: UUID) -> None:
        """Cross-module reference check, mirroring `_assert_grade_ownership` exactly — same
        lazy-import convention (`organisation.service` is the only surface this module may
        import from, Module Standard §2). Reuses `get_shift` verbatim: existence + tenant-scope
        only, no `is_active` gate, consistent with every sibling reference field
        (`docs/modules/employee/13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §7.4)."""
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_shift(company_id, shift_id)
        except NotFoundError as exc:
            raise InvalidShiftReferenceError() from exc

    async def _assert_manager_reference(
        self, company_id: UUID, employee_id: UUID, manager_id: UUID, *, field: str
    ) -> None:
        """Covers both `reporting_manager_id` and `dotted_line_manager_id` — must resolve to
        an existing, same-tenant, non-deleted `Employee`, and must not equal the assignment's
        own `employee_id` (a direct-self-reference guard only, not full cycle detection,
        plan §14.5)."""
        if manager_id == employee_id:
            raise InvalidReportingManagerError(
                field=field, message=f"{field} cannot reference the employee themselves"
            )
        manager = await self._employee_repo.get_employee(
            self._session, company_id=company_id, employee_id=manager_id
        )
        if manager is None:
            raise InvalidReportingManagerError(
                field=field, message=f"{field} does not reference a valid employee"
            )

    async def create_assignment(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: AssignmentCreate,
        *,
        expected_version: int | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AssignmentRead:
        await self._assert_employee_exists(company_id, employee_id)

        covering_employment = await self._employment_repo.get_employment_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=body.effective_from
        )
        if covering_employment is None:
            raise NoActiveEmploymentError()

        if body.change_type == "SHIFT_CHANGE" and body.shift_id is None:
            raise ShiftIdRequiredError()

        current = await self._repo.get_current_assignment(
            self._session, company_id=company_id, employee_id=employee_id
        )

        if current is None:
            missing = [
                field
                for field in ("branch_id", "department_id", "designation_id")
                if getattr(body, field) is None
            ]
            if missing:
                raise AssignmentFieldsRequiredError(missing)
            branch_id = body.branch_id
            department_id = body.department_id
            designation_id = body.designation_id
            grade_id = body.grade_id
            reporting_manager_id = body.reporting_manager_id
            dotted_line_manager_id = body.dotted_line_manager_id
            cost_centre_id = body.cost_centre_id
            shift_id = body.shift_id
            work_location_type: str | None = body.work_location_type
        else:
            if body.effective_from <= current.effective_from:
                raise InvalidEffectiveFromError()
            if expected_version is None:
                raise AssignmentVersionRequiredError()
            branch_id = body.branch_id if body.branch_id is not None else current.branch_id
            department_id = (
                body.department_id if body.department_id is not None else current.department_id
            )
            designation_id = (
                body.designation_id if body.designation_id is not None else current.designation_id
            )
            grade_id = body.grade_id if body.grade_id is not None else current.grade_id
            reporting_manager_id = (
                body.reporting_manager_id
                if body.reporting_manager_id is not None
                else current.reporting_manager_id
            )
            dotted_line_manager_id = (
                body.dotted_line_manager_id
                if body.dotted_line_manager_id is not None
                else current.dotted_line_manager_id
            )
            cost_centre_id = (
                body.cost_centre_id if body.cost_centre_id is not None else current.cost_centre_id
            )
            shift_id = body.shift_id if body.shift_id is not None else current.shift_id
            work_location_type = (
                body.work_location_type
                if body.work_location_type is not None
                else current.work_location_type
            )

        if branch_id is not None:
            await self._assert_branch_ownership(company_id, branch_id)
        if department_id is not None:
            await self._assert_department_ownership(company_id, department_id)
        if designation_id is not None:
            await self._assert_designation_ownership(company_id, designation_id)
        if grade_id is not None:
            await self._assert_grade_ownership(company_id, grade_id)
        if shift_id is not None:
            await self._assert_shift_ownership(company_id, shift_id)
        if reporting_manager_id is not None:
            await self._assert_manager_reference(
                company_id, employee_id, reporting_manager_id, field="reporting_manager_id"
            )
        if dotted_line_manager_id is not None:
            await self._assert_manager_reference(
                company_id, employee_id, dotted_line_manager_id, field="dotted_line_manager_id"
            )

        now = datetime.now(UTC)
        before_read = assignment_to_read(current) if current is not None else None

        if current is not None:
            assert expected_version is not None  # narrowed above
            closed = await self._repo.close_assignment(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                assignment_id=current.id,
                effective_to=body.effective_from - timedelta(days=1),
                expected_version=expected_version,
                now=now,
            )
            if closed is None:
                refreshed = await self._repo.get_assignment(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    assignment_id=current.id,
                )
                if refreshed is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This employee's current assignment has been modified by another request",
                    current=assignment_to_audit_dict(assignment_to_read(refreshed)),
                )

        assignment_id = uuid4()
        try:
            assignment = await self._repo.insert_assignment(
                self._session,
                data={
                    "id": assignment_id,
                    "company_id": company_id,
                    "employee_id": employee_id,
                    "branch_id": branch_id,
                    "department_id": department_id,
                    "designation_id": designation_id,
                    "grade_id": grade_id,
                    "reporting_manager_id": reporting_manager_id,
                    "dotted_line_manager_id": dotted_line_manager_id,
                    "cost_centre_id": cost_centre_id,
                    "shift_id": shift_id,
                    "work_location_type": work_location_type,
                    "change_type": body.change_type,
                    "change_reason": body.change_reason,
                    "effective_from": body.effective_from,
                    "effective_to": None,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            # `employee_assignment_no_overlap` GiST exclusion constraint — the race-condition
            # backstop, mirroring `EmploymentService.create_employment`'s exact pattern.
            raise AssignmentDatesOverlapError() from exc

        after_read = assignment_to_read(assignment)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ASSIGNMENT_CHANGED",
            entity_type="employee_assignment",
            entity_id=assignment_id,
            before=assignment_to_audit_dict(before_read) if before_read is not None else None,
            after=assignment_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def list_assignments(
        self, company_id: UUID, employee_id: UUID, *, as_of: date | None = None
    ) -> list[AssignmentRead]:
        await self._assert_employee_exists(company_id, employee_id)
        if as_of is not None:
            assignment = await self._repo.get_assignment_as_of(
                self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
            )
            return [assignment_to_read(assignment)] if assignment is not None else []
        assignments = await self._repo.list_assignments(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [assignment_to_read(assignment) for assignment in assignments]

    async def get_assignment(
        self, company_id: UUID, employee_id: UUID, assignment_id: UUID
    ) -> AssignmentRead:
        await self._assert_employee_exists(company_id, employee_id)
        assignment = await self._repo.get_assignment(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            assignment_id=assignment_id,
        )
        if assignment is None:
            raise NotFoundError("Resource not found")
        return assignment_to_read(assignment)

    async def get_assignment_as_of(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> AssignmentRead | None:
        """The shared cross-module contract (`docs/modules/employee/
        05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7/E) other modules will call once
        Attendance/Leave/Payroll exist. Does not assert employee existence — callers resolving
        an as-of-date placement for a bulk operation should not pay for that check per call;
        a nonexistent `employee_id` simply yields no covering row, same as an existing employee
        with no assignment history."""
        assignment = await self._repo.get_assignment_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
        )
        return assignment_to_read(assignment) if assignment is not None else None
