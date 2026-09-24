"""Business logic for the employee module — E-01 (identity foundation), E-03 (employment
lifecycle), E-04 (employee assignment), E-06 (employee compensation), E-07 (employee
statutory), and E-08 (employee banking)."""

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings, get_settings
from hrms.core.crypto.service import PiiCryptoService
from hrms.core.errors.base import NotFoundError
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.employee.exceptions import (
    AssignmentDatesOverlapError,
    AssignmentFieldsRequiredError,
    AssignmentVersionRequiredError,
    BankDatesOverlapError,
    BankVersionRequiredError,
    CompensationDatesOverlapError,
    CompensationVersionRequiredError,
    DuplicateEmployeeCodeError,
    EmployeeNotOnProbationError,
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
    NomineePercentageExceededError,
    ShiftIdRequiredError,
    StaleResourceError,
    StatutoryDatesOverlapError,
    StatutoryVersionRequiredError,
    TaxRegimeSwitchNotAllowedError,
)
from hrms.modules.employee.repository import (
    EmployeeAssignmentRepository,
    EmployeeBankRepository,
    EmployeeCompensationRepository,
    EmployeeDependentRepository,
    EmployeeEducationRepository,
    EmployeeExperienceRepository,
    EmployeeRepository,
    EmployeeStatutoryRepository,
    EmploymentRepository,
)
from hrms.modules.employee.schemas import (
    AssignmentCreate,
    AssignmentRead,
    BankCreate,
    BankRead,
    CompensationCreate,
    CompensationRead,
    EmployeeConfirmInput,
    EmployeeCreate,
    EmployeeDependentCreate,
    EmployeeDependentRead,
    EmployeeEducationCreate,
    EmployeeEducationRead,
    EmployeeExperienceCreate,
    EmployeeExperienceRead,
    EmployeeIdentityRead,
    EmployeeIdentityUpdate,
    EmployeeRead,
    EmployeeUpdate,
    EmploymentCreate,
    EmploymentRead,
    EmploymentTerminate,
    EmploymentUpdate,
    StatutoryCreate,
    StatutoryRead,
    assignment_to_audit_dict,
    assignment_to_read,
    bank_to_audit_dict,
    bank_to_read,
    build_employee_update_values,
    build_employment_update_values,
    compensation_to_audit_dict,
    compensation_to_read,
    employee_dependent_to_audit_dict,
    employee_dependent_to_read,
    employee_education_to_audit_dict,
    employee_education_to_read,
    employee_experience_to_audit_dict,
    employee_experience_to_read,
    employee_identity_to_audit_dict,
    employee_identity_to_read,
    employee_to_audit_dict,
    employee_to_read,
    employment_to_audit_dict,
    employment_to_read,
    statutory_to_audit_dict,
    statutory_to_read,
)
from hrms.shared.pagination import PageParams

if TYPE_CHECKING:
    from hrms.modules.employee.models import EmployeeBank, EmployeeDependent


class EmployeeService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeRepository()
        self._assignment_repo = EmployeeAssignmentRepository()
        self._audit = AuditService()
        self._crypto = PiiCryptoService(self._settings)

    async def resolve_visible_employee_ids(
        self,
        company_id: UUID,
        scope: DataScope,
        caller_employee_id: UUID | None,
    ) -> frozenset[UUID] | None:
        """Turns a `core.rbac` `DataScope` (scope *levels* only — `core/rbac` cannot know about
        `employee_assignment`, `hrms.core` may not import `hrms.modules`,
        `apps/api/.importlinter`) into a concrete set of visible employee IDs. `None` means
        `COMPANY` scope — no filter, identical to this module's pre-data-scope behavior; a
        (possibly empty) `frozenset` means the caller may only see those specific employees.

        Public and reusable — this is the exact seam a future Attendance/Leave/Payroll module
        would call via `employee.service.EmployeeService` (Module Standard's cross-module
        `other_module.service` rule) to resolve "which employee IDs can this caller see," reusing
        this reporting-hierarchy logic rather than re-deriving it
        (`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §7).

        Union semantics for multiple granted levels (`RBAC_DATA_SCOPE_DECISIONS.md` Decision A /
        `25_...IMPLEMENTATION_PLAN.md` §12): `SELF` and `REPORTEES` are not nested (a manager's
        own ID is never a member of their own `REPORTEES` set), so a caller holding both grants
        (e.g. via two roles) must see the union, not just the "widest-sounding" level alone.
        `COMPANY` always short-circuits to "no filter," regardless of what else is granted, and
        regardless of `caller_employee_id`. `BRANCH` is independent of the REPORTEES/REPORTEE_TREE
        axis (a caller can hold both, e.g. REPORTEE_TREE for cross-branch reports plus BRANCH for
        the rest of their own branch) so it is resolved in its own, separately-unioned branch.
        """
        if DataScopeLevel.COMPANY in scope.levels:
            return None

        visible: set[UUID] = set()

        if DataScopeLevel.SELF in scope.levels and caller_employee_id is not None:
            visible.add(caller_employee_id)

        if caller_employee_id is not None:
            if DataScopeLevel.REPORTEE_TREE in scope.levels:
                # Superset of REPORTEES for the same root — no need to also run REPORTEES.
                visible |= await self._assignment_repo.get_reportee_tree_ids(
                    self._session, company_id=company_id, manager_employee_id=caller_employee_id
                )
            elif DataScopeLevel.REPORTEES in scope.levels:
                visible |= await self._assignment_repo.get_direct_report_ids(
                    self._session, company_id=company_id, manager_employee_id=caller_employee_id
                )

            if DataScopeLevel.BRANCH in scope.levels:
                caller_assignment = await self._assignment_repo.get_current_assignment(
                    self._session, company_id=company_id, employee_id=caller_employee_id
                )
                # No current assignment, or one with no `branch_id` set, yields no BRANCH grant —
                # fails closed (no colleagues resolved), never an error and never COMPANY.
                if caller_assignment is not None and caller_assignment.branch_id is not None:
                    visible |= await self._assignment_repo.get_branch_colleague_ids(
                        self._session,
                        company_id=company_id,
                        branch_id=caller_assignment.branch_id,
                    )

        # `caller_employee_id is None` with only SELF/REPORTEES/REPORTEE_TREE/BRANCH granted (no
        # Employee record for this user — Decisions doc, Decision B edge case): every branch
        # above is skipped, `visible` stays empty — fails closed, never falls back to COMPANY.
        return frozenset(visible)

    async def resolve_employee_id_for_user(self, company_id: UUID, user_id: UUID) -> UUID | None:
        """Resolves the `employee_id` claim that login/refresh embeds in the JWT
        (`hrms.modules.identity.service.IdentityService.issue_tokens_for` — cross-module
        seam, same lazy-import convention as `attendance.service._resolve_visible_employee_ids`).
        Returns `None` for users with no linked `Employee` row in this company (company admins
        without an employee record are a valid, expected case, not an error)."""
        employee = await self._repo.get_employee_by_user_id(
            self._session, company_id=company_id, user_id=user_id
        )
        return employee.id if employee is not None else None

    async def get_uan_number(self, company_id: UUID, employee_id: UUID) -> str | None:
        """Payroll 5.3 — the UAN a PF-applicable employee is reported under. Internal, unscoped
        cross-module fact (UAN is stored in plain text, like `EmployeeIdentityRead.uan_number`)."""
        employee = await self._repo.get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return employee.uan_number if employee is not None else None

    async def has_pan(self, company_id: UUID, employee_id: UUID) -> bool:
        """Payroll 5.6 — whether a PAN is on file, for the TDS engine's Section 206AA check.
        Never decrypts; the ciphertext's mere presence is all that's needed."""
        employee = await self._repo.get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return bool(employee is not None and employee.pan_number_enc)

    async def get_masked_pan(self, company_id: UUID, employee_id: UUID) -> str | None:
        """Payroll 5.4 — the PAN as printed on a payslip: all but the last four characters
        masked. Decrypts only the PAN (never Aadhaar); the plaintext never leaves this method."""
        employee = await self._repo.get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if employee is None or not employee.pan_number_enc:
            return None
        pan = await self._crypto.decrypt_column(
            self._session,
            ciphertext=employee.pan_number_enc,
            table="employee",
            column="pan_number_enc",
            record_id=employee.id,
        )
        return ("*" * (len(pan) - 4) + pan[-4:]) if pan else None

    async def find_employee_by_code_or_email(
        self, company_id: UUID, value: str
    ) -> EmployeeRead | None:
        """Public lookup for `modules/employee_import`'s `reporting_manager` column resolution
        — matches by `employee_code` first, `personal_email` (case-insensitive) otherwise. Not
        exposed via a route: internal cross-module use only, same convention as this module's
        other `service.py`-only public methods."""
        employee = await self._repo.get_by_code_or_email(
            self._session, company_id=company_id, value=value
        )
        return employee_to_read(employee) if employee is not None else None

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
        employee_code_override: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeRead:
        """`employee_code_override` exists only for internal callers (bulk import,
        `modules/employee_import/service.py`) migrating a client's existing employee IDs — it is
        deliberately not a field on `EmployeeCreate` itself (see module docstring: `employee_code`
        is "system-generated ... never client-settable" for the interactive API). When omitted,
        behavior is unchanged: the `number_series` allocator assigns the next code."""
        await self._check_seat_limit(company_id)

        if employee_code_override is not None:
            employee_code = employee_code_override
        else:
            employee_code = await self._repo.allocate_employee_code(
                self._session, company_id=company_id
            )

        now = datetime.now(UTC)
        employee_id = uuid4()
        try:
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
                    "father_or_husband_name": body.father_or_husband_name,
                    "personal_email": body.personal_email,
                    "personal_mobile": body.personal_mobile,
                    "present_address_line1": body.present_address_line1,
                    "present_address_line2": body.present_address_line2,
                    "present_city": body.present_city,
                    "present_state_code": body.present_state_code,
                    "present_pincode": body.present_pincode,
                    "present_country_code": body.present_country_code,
                    "permanent_address_line1": body.permanent_address_line1,
                    "permanent_address_line2": body.permanent_address_line2,
                    "permanent_city": body.permanent_city,
                    "permanent_state_code": body.permanent_state_code,
                    "permanent_pincode": body.permanent_pincode,
                    "permanent_country_code": body.permanent_country_code,
                    "permanent_same_as_present": body.permanent_same_as_present,
                    "emergency_contact_name": body.emergency_contact_name,
                    "emergency_contact_relationship": body.emergency_contact_relationship,
                    "emergency_contact_phone": body.emergency_contact_phone,
                    "photo_url": body.photo_url,
                    "custom_fields": body.custom_fields,
                    "status": "PRE_JOINING",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            # Only reachable via `employee_code_override` — the allocator path never collides.
            raise DuplicateEmployeeCodeError(employee_code=employee_code) from exc

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

    async def list_employees(
        self,
        company_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        page: PageParams | None = None,
    ) -> tuple[list[EmployeeRead], int]:
        """`scope=None` (every caller except `GET /employees`) preserves this module's
        pre-data-scope behavior exactly — company-wide, no filter. `GET /employees` passes its
        resolved `DataScope` (`router.py`), narrowing the result per
        `resolve_visible_employee_ids`.

        `page=None` returns every visible row, unpaginated, and a `total` equal to `len(...)` of
        that same list — the exact shape every pre-API-01 caller of this method still gets.
        `GET /employees` (API-01) always passes `page`, so authorization narrows the visible-ID
        set *before* the SQL-level `LIMIT`/`OFFSET` ever runs — a caller can only page through
        rows already inside their own `DataScope`, never around it."""
        visible_ids = (
            await self.resolve_visible_employee_ids(company_id, scope, caller_employee_id)
            if scope is not None
            else None
        )
        if page is None:
            employees = await self._repo.list_employees(
                self._session, company_id=company_id, visible_employee_ids=visible_ids
            )
            reads = [employee_to_read(employee) for employee in employees]
            return reads, len(reads)

        # Sequential, not `asyncio.gather` — a single `AsyncSession` cannot run two statements
        # concurrently.
        employees = await self._repo.list_employees(
            self._session,
            company_id=company_id,
            visible_employee_ids=visible_ids,
            limit=page.limit,
            offset=page.offset,
        )
        total = await self._repo.count_employees(
            self._session, company_id=company_id, visible_employee_ids=visible_ids
        )
        return [employee_to_read(employee) for employee in employees], total

    async def get_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> EmployeeRead:
        """`scope=None` preserves pre-data-scope behavior exactly (every internal caller of this
        service method except `GET /employees/{id}` itself). An out-of-scope target raises the
        same `NotFoundError` → `404` a nonexistent or cross-tenant ID already raises — no new
        branching, matching the existing cross-tenant convention
        (`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §15)."""
        visible_ids = (
            await self.resolve_visible_employee_ids(company_id, scope, caller_employee_id)
            if scope is not None
            else None
        )
        employee = await self._repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
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
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeRead:
        """`scope=None` preserves pre-data-scope behavior exactly (every internal caller of
        this service except `PATCH`/`DELETE /employees/{id}` themselves) — company-wide, no
        filter. An out-of-scope target raises the same `NotFoundError` -> `404` a nonexistent or
        cross-tenant ID already raises, matching every read-path route's convention
        (`docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2)."""
        visible_ids = (
            await self.resolve_visible_employee_ids(company_id, scope, caller_employee_id)
            if scope is not None
            else None
        )
        employee = await self._repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
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

    async def get_identity(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> EmployeeIdentityRead:
        """E-02 — `GET /employees/{id}/identity`. Decrypts `pan_number_enc`/`aadhaar_number_enc`
        only after the caller's own permission check has already run (the router's
        `require_permission(EMPLOYEE_VIEW_SENSITIVE)` dependency, resolved before this method is
        ever called) — mirrors `EmployeeBankService._decrypt_bank`'s exact contract."""
        visible_ids = (
            await self.resolve_visible_employee_ids(company_id, scope, caller_employee_id)
            if scope is not None
            else None
        )
        employee = await self._repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")

        pan_number = await self._crypto.decrypt_column(
            self._session,
            ciphertext=employee.pan_number_enc,
            table="employee",
            column="pan_number_enc",
            record_id=employee.id,
        )
        aadhaar_number = await self._crypto.decrypt_column(
            self._session,
            ciphertext=employee.aadhaar_number_enc,
            table="employee",
            column="aadhaar_number_enc",
            record_id=employee.id,
        )
        return employee_identity_to_read(
            employee, pan_number=pan_number, aadhaar_number=aadhaar_number
        )

    async def update_identity(
        self,
        company_id: UUID,
        employee_id: UUID,
        patch: EmployeeIdentityUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeIdentityRead:
        """E-02 — `PATCH /employees/{id}/identity`. Unlike Bank/Statutory/Compensation, this is
        a plain update-in-place on `Employee` itself (like `update_employee`), not an
        insert-a-new-row history write — PAN/Aadhaar/UAN are single current-value facts, not
        effective-dated history. Only fields explicitly present in the request are applied,
        mirroring `build_employee_update_values`; an omitted field leaves the existing
        (possibly-encrypted) column untouched rather than clobbering it with `None`."""
        visible_ids = (
            await self.resolve_visible_employee_ids(company_id, scope, caller_employee_id)
            if scope is not None
            else None
        )
        employee = await self._repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")

        before_pan = await self._crypto.decrypt_column(
            self._session,
            ciphertext=employee.pan_number_enc,
            table="employee",
            column="pan_number_enc",
            record_id=employee.id,
        )
        before_aadhaar = await self._crypto.decrypt_column(
            self._session,
            ciphertext=employee.aadhaar_number_enc,
            table="employee",
            column="aadhaar_number_enc",
            record_id=employee.id,
        )
        before_read = employee_identity_to_read(
            employee, pan_number=before_pan, aadhaar_number=before_aadhaar
        )

        fields_set = patch.model_fields_set
        values: dict[str, object] = {}
        if "pan_number" in fields_set:
            values["pan_number_enc"] = await self._crypto.encrypt_column(
                self._session,
                plaintext=patch.pan_number,
                table="employee",
                column="pan_number_enc",
                record_id=employee.id,
            )
        if "aadhaar_number" in fields_set:
            values["aadhaar_number_enc"] = await self._crypto.encrypt_column(
                self._session,
                plaintext=patch.aadhaar_number,
                table="employee",
                column="aadhaar_number_enc",
                record_id=employee.id,
            )
        if "uan_number" in fields_set:
            values["uan_number"] = patch.uan_number
        if "father_or_husband_name" in fields_set:
            values["father_or_husband_name"] = patch.father_or_husband_name

        if not values:
            return before_read

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
            current_pan = await self._crypto.decrypt_column(
                self._session,
                ciphertext=current.pan_number_enc,
                table="employee",
                column="pan_number_enc",
                record_id=current.id,
            )
            current_aadhaar = await self._crypto.decrypt_column(
                self._session,
                ciphertext=current.aadhaar_number_enc,
                table="employee",
                column="aadhaar_number_enc",
                record_id=current.id,
            )
            raise StaleResourceError(
                "This employee has been modified by another request",
                current=employee_identity_to_audit_dict(
                    employee_identity_to_read(
                        current, pan_number=current_pan, aadhaar_number=current_aadhaar
                    )
                ),
            )

        after_pan = patch.pan_number if "pan_number" in fields_set else before_pan
        after_aadhaar = patch.aadhaar_number if "aadhaar_number" in fields_set else before_aadhaar
        after_read = employee_identity_to_read(
            updated, pan_number=after_pan, aadhaar_number=after_aadhaar
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_IDENTITY_UPDATED",
            entity_type="employee",
            entity_id=employee_id,
            before=employee_identity_to_audit_dict(before_read),
            after=employee_identity_to_audit_dict(after_read),
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
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
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
            scope=scope,
            caller_employee_id=caller_employee_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def confirm_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmployeeConfirmInput,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeRead:
        """`POST /employees/{id}/confirm` — one-way `PROBATION` -> `ACTIVE`. Minimal
        confirmation slice: no reminders, no manager-recommendation routing, no auto-extend/
        auto-confirm rules, no letter generation (full FR-EMP-010 scope, deliberately not built
        here). Mirrors `EmploymentService.terminate_employment`'s shape — a dedicated
        precondition-guarded action, not a generic-`PATCH`-reachable field, since `status` isn't
        settable via `EmployeeUpdate` at all."""
        visible_ids = (
            await self.resolve_visible_employee_ids(company_id, scope, caller_employee_id)
            if scope is not None
            else None
        )
        employee = await self._repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")
        if employee.status != "PROBATION":
            raise EmployeeNotOnProbationError()

        before_read = employee_to_read(employee)
        now = datetime.now(UTC)
        updated = await self._repo.update_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            values={"status": "ACTIVE"},
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
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_CONFIRMED",
            entity_type="employee",
            entity_id=employee_id,
            before=employee_to_audit_dict(before_read),
            after=employee_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read


class EmploymentService:
    """E-03 — employment lifecycle. Create (first hire or rehire), read/list (incl. as-of-date),
    update (the one correctable field, `legal_entity_id`), and terminate (one-way `ACTIVE` →
    `TERMINATED`)."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmploymentRepository()
        self._employee_repo = EmployeeRepository()
        self._assignment_repo = EmployeeAssignmentRepository()
        self._compensation_repo = EmployeeCompensationRepository()
        self._statutory_repo = EmployeeStatutoryRepository()
        self._employee_service = EmployeeService(session, self._settings)
        self._audit = AuditService()

    async def _assert_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        """`scope=None` preserves this method's pre-data-scope "exists" behavior exactly (every
        internal caller of this service except the routes that now resolve a real `DataScope`).
        An out-of-scope target raises the same `NotFoundError` -> `404` a nonexistent or
        cross-tenant ID already raises — no new branching, mirroring
        `EmployeeCompensationService._assert_employee_visible`'s exact pattern
        (`docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 1/2)."""
        visible_ids = (
            await self._employee_service.resolve_visible_employee_ids(
                company_id, scope, caller_employee_id
            )
            if scope is not None
            else None
        )
        employee = await self._employee_repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
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

    async def list_spans_overlapping(
        self, company_id: UUID, *, date_from: date, date_to: date
    ) -> list[tuple[UUID, date, date | None]]:
        """`(employee_id, joining_date, last_working_day)` for every employment spell
        overlapping `[date_from, date_to]`, company-wide (no `DataScope` — this is an internal
        cross-module fact query, not an API-facing list). Consumed by
        `AttendancePeriodService`'s finalization validation (W8) to determine which employees
        are in scope for a period and how many calendar days each was actually employed within
        it; never exposes the `Employment` ORM row itself across the module boundary (Module
        Standard §2)."""
        rows = await self._repo.list_spans_overlapping(
            self._session, company_id=company_id, date_from=date_from, date_to=date_to
        )
        return [(row.employee_id, row.joining_date, row.last_working_day) for row in rows]

    async def list_legal_entity_spans(
        self,
        company_id: UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        employee_id: UUID | None = None,
    ) -> list[tuple[UUID, UUID, date, date | None]]:
        """`(employee_id, legal_entity_id, joining_date, last_working_day)` for every employment
        spell — overlapping `[date_from, date_to]` when both are given, otherwise all of them —
        optionally for one employee. The fact query behind Attendance's legal-entity period
        grain (`PAYROLL_BUSINESS_DECISIONS.md` decision 14): which entity's period owns an
        employee-date. Same internal, unscoped posture as `list_spans_overlapping`."""
        rows = await self._repo.list_spans_overlapping(
            self._session,
            company_id=company_id,
            date_from=date_from,
            date_to=date_to,
            employee_id=employee_id,
        )
        return [
            (row.employee_id, row.legal_entity_id, row.joining_date, row.last_working_day)
            for row in rows
        ]

    async def create_employment(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmploymentCreate,
        *,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmploymentRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
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
                    "probation_end_date": body.probation_end_date,
                    "pay_basis": body.pay_basis,
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

        # Employee confirmation (minimal slice) — "pre-joining" ends once they actually join.
        # Guarded to only fire from `PRE_JOINING` so a rejoin/transfer never resets an
        # already-`ACTIVE` employee back into probation. Best-effort: a concurrent-update race
        # on the employee row here just skips the transition rather than failing employment
        # creation over it — this is a side effect of joining, not the primary action.
        employee = await self._employee_repo.get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if employee is not None and employee.status == "PRE_JOINING":
            employee_before = employee_to_read(employee)
            confirmed_employee = await self._employee_repo.update_employee(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                values={"status": "PROBATION"},
                expected_version=employee.version,
                now=now,
            )
            if confirmed_employee is not None:
                employee_after = employee_to_read(confirmed_employee)
                await self._audit.record(
                    self._session,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    action="EMPLOYEE_PROBATION_STARTED",
                    entity_type="employee",
                    entity_id=employee_id,
                    before=employee_to_audit_dict(employee_before),
                    after=employee_to_audit_dict(employee_after),
                    ip=ip_address,
                    user_agent=user_agent,
                )

        return read

    async def list_employments(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        as_of: date | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> list[EmploymentRead]:
        """`scope=None` preserves this service's pre-data-scope behavior exactly (every internal
        caller except `GET .../employments` itself). `GET .../employments` passes its resolved
        `DataScope` (`router.py`), narrowing visibility to `SELF`/`REPORTEES`/`REPORTEE_TREE`/
        `COMPANY` per `_assert_employee_visible`, resolved *before* the `as_of` branch so
        `as_of` cannot bypass scope."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
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
        self,
        company_id: UUID,
        employee_id: UUID,
        employment_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> EmploymentRead:
        """`scope=None` preserves pre-data-scope behavior exactly, mirroring
        `list_employments`."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
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
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmploymentRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
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
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmploymentRead:
        """Transitions the current episode `ACTIVE` → `TERMINATED`, one-way — there is no
        action anywhere in this module that reopens a terminated employment. A later rejoin is
        always a new `create_employment` call, never a reversal of this one
        (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B2).

        Also closes the employee's currently-open `employee_assignment`/`employee_compensation`
        row (if any) at `effective_to = last_working_day`, reusing
        `EmployeeAssignmentRepository.close_assignment`/`EmployeeCompensationRepository.
        close_compensation` verbatim — the same "close current" mutation `create_assignment`/
        `create_compensation` already use, just triggered here instead
        (`docs/modules/employee/22_TERMINATION_ASSIGNMENT_COMPENSATION_PLAN.md` §7/§21). If the
        open row's `effective_from` is after `last_working_day`, it is left open: closing it
        would produce an invalid `effective_to < effective_from` range, and no source document
        resolves what should happen instead (plan §8/§19 OD-1, deliberately left unresolved
        here rather than inventing a rule)."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
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

        current_assignment = await self._assignment_repo.get_current_assignment(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if (
            current_assignment is not None
            and current_assignment.effective_from <= body.last_working_day
        ):
            assignment_before = assignment_to_read(current_assignment)
            closed_assignment = await self._assignment_repo.close_assignment(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                assignment_id=current_assignment.id,
                effective_to=body.last_working_day,
                expected_version=current_assignment.version,
                now=now,
            )
            if closed_assignment is None:
                refreshed_assignment = await self._assignment_repo.get_assignment(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    assignment_id=current_assignment.id,
                )
                if refreshed_assignment is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This employee's current assignment has been modified by another request",
                    current=assignment_to_audit_dict(assignment_to_read(refreshed_assignment)),
                )
            await self._audit.record(
                self._session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="ASSIGNMENT_CHANGED",
                entity_type="employee_assignment",
                entity_id=current_assignment.id,
                before=assignment_to_audit_dict(assignment_before),
                after=assignment_to_audit_dict(assignment_to_read(closed_assignment)),
                ip=ip_address,
                user_agent=user_agent,
            )

        current_compensation = await self._compensation_repo.get_current_compensation(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if (
            current_compensation is not None
            and current_compensation.effective_from <= body.last_working_day
        ):
            compensation_before = compensation_to_read(current_compensation)
            closed_compensation = await self._compensation_repo.close_compensation(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                compensation_id=current_compensation.id,
                effective_to=body.last_working_day,
                expected_version=current_compensation.version,
                now=now,
            )
            if closed_compensation is None:
                refreshed_compensation = await self._compensation_repo.get_compensation(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    compensation_id=current_compensation.id,
                )
                if refreshed_compensation is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This employee's current compensation has been modified by another request",
                    current=compensation_to_audit_dict(
                        compensation_to_read(refreshed_compensation)
                    ),
                )
            await self._audit.record(
                self._session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="COMPENSATION_REVISED",
                entity_type="employee_compensation",
                entity_id=current_compensation.id,
                before=compensation_to_audit_dict(compensation_before),
                after=compensation_to_audit_dict(compensation_to_read(closed_compensation)),
                ip=ip_address,
                user_agent=user_agent,
            )

        # Statutory rows survive exit rather than being deleted/merged, but the currently-open
        # row is closed at the termination date — the same "last row closed" contract Assignment/
        # Compensation already have (`docs/modules/employee/
        # 29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §9), reusing `EmployeeStatutoryRepository.
        # close_statutory` verbatim.
        current_statutory = await self._statutory_repo.get_current_statutory(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if (
            current_statutory is not None
            and current_statutory.effective_from <= body.last_working_day
        ):
            statutory_before = statutory_to_read(current_statutory)
            closed_statutory = await self._statutory_repo.close_statutory(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                statutory_id=current_statutory.id,
                effective_to=body.last_working_day,
                expected_version=current_statutory.version,
                now=now,
            )
            if closed_statutory is None:
                refreshed_statutory = await self._statutory_repo.get_statutory(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    statutory_id=current_statutory.id,
                )
                if refreshed_statutory is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This employee's current statutory record has been modified by another request",
                    current=statutory_to_audit_dict(statutory_to_read(refreshed_statutory)),
                )
            await self._audit.record(
                self._session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                action="STATUTORY_REVISED",
                entity_type="employee_statutory",
                entity_id=current_statutory.id,
                before=statutory_to_audit_dict(statutory_before),
                after=statutory_to_audit_dict(statutory_to_read(closed_statutory)),
                ip=ip_address,
                user_agent=user_agent,
            )

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

    async def get_employment_as_of(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> EmploymentRead | None:
        """The shared cross-module contract (`docs/modules/employee/
        05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7/E) other modules will call once
        Attendance/Leave/Payroll exist — mirrors `EmployeeAssignmentService.get_assignment_as_of`
        exactly (same "does not assert employee existence" posture). `None` means no employment
        episode covers `as_of` (the population gate fails, architecture §19.1 step 1); a caller
        needing to distinguish `NOT_JOINED` from `EXITED` should also call
        `get_latest_employment_on_or_before`."""
        employment = await self._repo.get_employment_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
        )
        return employment_to_read(employment) if employment is not None else None

    async def get_latest_employment_on_or_before(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> EmploymentRead | None:
        """Most recent employment episode (possibly `TERMINATED`) with `joining_date <= as_of`.
        Paired with `get_employment_as_of` to distinguish the population gate's two failure
        modes (architecture §19.1 step 1, WD-21): no matching episode at all means
        `NOT_JOINED`; a matching episode whose `last_working_day` already passed means
        `EXITED`."""
        employments = await self._repo.list_employments(
            self._session, company_id=company_id, employee_id=employee_id
        )
        candidates = [e for e in employments if e.joining_date <= as_of]
        if not candidates:
            return None
        latest = max(candidates, key=lambda e: e.joining_date)
        return employment_to_read(latest)


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
        self._employee_service = EmployeeService(session, self._settings)
        self._audit = AuditService()

    async def _assert_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        """`scope=None` preserves this method's pre-data-scope "exists" behavior exactly (every
        internal caller of this service except the routes that now resolve a real `DataScope`).
        An out-of-scope target raises the same `NotFoundError` -> `404` a nonexistent or
        cross-tenant ID already raises — no new branching, mirroring
        `EmployeeCompensationService._assert_employee_visible`'s exact pattern
        (`docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 1B/2)."""
        visible_ids = (
            await self._employee_service.resolve_visible_employee_ids(
                company_id, scope, caller_employee_id
            )
            if scope is not None
            else None
        )
        employee = await self._employee_repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
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
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AssignmentRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

        covering_employment = await self._employment_repo.get_employment_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=body.effective_from
        )
        if covering_employment is None:
            raise NoActiveEmploymentError()

        if (
            body.reporting_manager_id is not None
            and caller_employee_id is not None
            and body.reporting_manager_id == caller_employee_id
        ):
            # Self-elevation guard (`docs/modules/employee/27_REPORTING_MANAGER_SECURITY_AUDIT.md`):
            # `reporting_manager_id` is the sole input to `REPORTEES`/`REPORTEE_TREE` data-scope
            # resolution, so naming the acting user as the new manager is a scope-widening write,
            # not an ordinary field change. Rejected unconditionally, regardless of which
            # permission authorized this write, since no permission in the current catalogue is
            # scoped to "may expand my own data scope."
            raise InvalidReportingManagerError(
                field="reporting_manager_id",
                message="reporting_manager_id cannot be set to the acting user's own employee_id",
            )

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
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        as_of: date | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> list[AssignmentRead]:
        """`scope=None` preserves this service's pre-data-scope behavior exactly (every internal
        caller except `GET .../assignments` itself). `GET .../assignments` passes its resolved
        `DataScope` (`router.py`), narrowing visibility to `SELF`/`REPORTEES`/`REPORTEE_TREE`/
        `COMPANY` per `_assert_employee_visible`, resolved *before* the `as_of` branch so
        `as_of` cannot bypass scope."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
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
        self,
        company_id: UUID,
        employee_id: UUID,
        assignment_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> AssignmentRead:
        """`scope=None` preserves pre-data-scope behavior exactly, mirroring
        `list_assignments`."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
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

    async def list_distinct_employee_ids_for_branch(
        self, company_id: UUID, branch_id: UUID
    ) -> list[UUID]:
        """`ED-12` (execution gate §12.4) — another shared cross-module contract, alongside
        `get_assignment_as_of` above: `organisation.service`'s branch-scope timezone-change guard
        calls this to resolve every employee who has ever been assigned to a branch, not just its
        current roster, before checking whether any of them has computed attendance."""
        return await self._repo.list_distinct_employee_ids_for_branch(
            self._session, company_id=company_id, branch_id=branch_id
        )


class EmployeeCompensationService:
    """E-06 — employee compensation (pay history). One write operation, `create_compensation`,
    covering an employee's first CTC and every later revision alike
    (`docs/modules/employee/17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` §6) — each is an
    insert of a new effective-dated row, never a column update. No `update_compensation`/
    `delete_compensation` exists; there is no other mutation path.

    Deliberately does **not** validate `annual_ctc_minor` against the employee's current
    assignment's grade `min_ctc`/`max_ctc` band — PD-1 (plan §16), no document names this
    enforcement anywhere, and Grade's CTC fields are informational bands only
    (`docs/modules/grade/01_Grade_Module.md:141`). Also deliberately does not offer
    carry-forward semantics for any field (plan §17.2) — every write states the full new CTC
    explicitly."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeCompensationRepository()
        self._employee_repo = EmployeeRepository()
        self._employment_repo = EmploymentRepository()
        self._employee_service = EmployeeService(session, self._settings)
        self._audit = AuditService()

    async def _assert_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        """`scope=None` preserves this method's pre-data-scope "exists" behavior exactly (every
        internal caller of this service except the two `GET` routes and `create_compensation`,
        all of which now resolve a real `DataScope`). An out-of-scope target raises the same
        `NotFoundError` -> `404` a nonexistent or cross-tenant ID already raises — no new
        branching, mirroring `EmployeeBankService._assert_employee_visible`'s exact pattern."""
        visible_ids = (
            await self._employee_service.resolve_visible_employee_ids(
                company_id, scope, caller_employee_id
            )
            if scope is not None
            else None
        )
        employee = await self._employee_repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")

    async def create_compensation(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: CompensationCreate,
        *,
        expected_version: int | None,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CompensationRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

        covering_employment = await self._employment_repo.get_employment_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=body.effective_from
        )
        if covering_employment is None:
            raise NoActiveEmploymentError()

        current = await self._repo.get_current_compensation(
            self._session, company_id=company_id, employee_id=employee_id
        )

        if current is not None:
            if body.effective_from <= current.effective_from:
                raise InvalidEffectiveFromError()
            if expected_version is None:
                raise CompensationVersionRequiredError()

        now = datetime.now(UTC)
        before_read = compensation_to_read(current) if current is not None else None

        if current is not None:
            assert expected_version is not None  # narrowed above
            closed = await self._repo.close_compensation(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                compensation_id=current.id,
                effective_to=body.effective_from - timedelta(days=1),
                expected_version=expected_version,
                now=now,
            )
            if closed is None:
                refreshed = await self._repo.get_compensation(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    compensation_id=current.id,
                )
                if refreshed is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This employee's current compensation has been modified by another request",
                    current=compensation_to_audit_dict(compensation_to_read(refreshed)),
                )

        compensation_id = uuid4()
        try:
            compensation = await self._repo.insert_compensation(
                self._session,
                data={
                    "id": compensation_id,
                    "company_id": company_id,
                    "employee_id": employee_id,
                    "annual_ctc_minor": body.annual_ctc_minor,
                    "currency": body.currency,
                    "revision_type": body.revision_type,
                    "revision_reason": body.revision_reason,
                    "effective_from": body.effective_from,
                    "effective_to": None,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            # `employee_compensation_no_overlap` GiST exclusion constraint — the race-condition
            # backstop, mirroring `EmployeeAssignmentService.create_assignment`'s exact pattern.
            raise CompensationDatesOverlapError() from exc

        after_read = compensation_to_read(compensation)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="COMPENSATION_REVISED",
            entity_type="employee_compensation",
            entity_id=compensation_id,
            before=compensation_to_audit_dict(before_read) if before_read is not None else None,
            after=compensation_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def list_compensations(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        as_of: date | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> list[CompensationRead]:
        """`scope=None` preserves this service's pre-data-scope behavior exactly (every internal
        caller except `GET .../compensation` itself). `GET .../compensation` passes its resolved
        `DataScope` (`router.py`), narrowing visibility to `SELF`/`REPORTEES`/`REPORTEE_TREE`/
        `COMPANY` per `_assert_employee_visible`."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        if as_of is not None:
            compensation = await self._repo.get_compensation_as_of(
                self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
            )
            return [compensation_to_read(compensation)] if compensation is not None else []
        compensations = await self._repo.list_compensations(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [compensation_to_read(compensation) for compensation in compensations]

    async def get_compensation(
        self,
        company_id: UUID,
        employee_id: UUID,
        compensation_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> CompensationRead:
        """`scope=None` preserves pre-data-scope behavior exactly, mirroring
        `list_compensations`."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        compensation = await self._repo.get_compensation(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            compensation_id=compensation_id,
        )
        if compensation is None:
            raise NotFoundError("Resource not found")
        return compensation_to_read(compensation)

    async def get_compensation_as_of(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> CompensationRead | None:
        """The shared cross-module contract (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7/F)
        Payroll will call once it exists. Does not assert employee existence, mirroring
        `EmployeeAssignmentService.get_assignment_as_of`'s exact contract."""
        compensation = await self._repo.get_compensation_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
        )
        return compensation_to_read(compensation) if compensation is not None else None


def _fiscal_year(day: date) -> int:
    """India-centric April-March FY, identified by its starting calendar year — this task's own
    engineering assumption for FR-PAY-006's "once per FY" rule (`docs/modules/employee/
    29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §26 item 5); no source document defines the FY
    boundary."""
    return day.year if day.month >= 4 else day.year - 1


class EmployeeStatutoryService:
    """E-07 — employee statutory (PF/ESI/PT/LWF/tax-regime profile). One write operation,
    `create_statutory`, covering an employee's first statutory row and every later revision
    alike (`docs/modules/employee/29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §20) — each is
    an insert of a new effective-dated row, never a column update. No `update_statutory`/
    `delete_statutory` exists; there is no other mutation path.

    Deliberately does **not** validate `is_pf_applicable`/`is_esi_applicable` against their
    corresponding identifier fields (`pf_number`/`esi_ip_number`), nor against the employing
    legal entity's own PF/ESI registration — both remain open, undocumented product questions
    (plan §17, §26 items 6-7), not invented here."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeStatutoryRepository()
        self._employee_repo = EmployeeRepository()
        self._employment_repo = EmploymentRepository()
        self._employee_service = EmployeeService(session, self._settings)
        self._audit = AuditService()

    async def _assert_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        """`scope=None` preserves this method's pre-data-scope "exists" behavior exactly (every
        internal caller of this service except the two `GET` routes and `create_statutory`, all
        of which now resolve a real `DataScope`). An out-of-scope target raises the same
        `NotFoundError` -> `404` a nonexistent or cross-tenant ID already raises — no new
        branching, mirroring `EmployeeBankService._assert_employee_visible`'s exact pattern."""
        visible_ids = (
            await self._employee_service.resolve_visible_employee_ids(
                company_id, scope, caller_employee_id
            )
            if scope is not None
            else None
        )
        employee = await self._employee_repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")

    async def create_statutory(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: StatutoryCreate,
        *,
        expected_version: int | None,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StatutoryRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

        covering_employment = await self._employment_repo.get_employment_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=body.effective_from
        )
        if covering_employment is None:
            raise NoActiveEmploymentError()

        current = await self._repo.get_current_statutory(
            self._session, company_id=company_id, employee_id=employee_id
        )

        if current is not None:
            if body.effective_from <= current.effective_from:
                raise InvalidEffectiveFromError()
            if expected_version is None:
                raise StatutoryVersionRequiredError()
            if body.tax_regime != current.tax_regime and _fiscal_year(
                current.effective_from
            ) == _fiscal_year(body.effective_from):
                raise TaxRegimeSwitchNotAllowedError()

        now = datetime.now(UTC)
        before_read = statutory_to_read(current) if current is not None else None

        if current is not None:
            assert expected_version is not None  # narrowed above
            closed = await self._repo.close_statutory(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                statutory_id=current.id,
                effective_to=body.effective_from - timedelta(days=1),
                expected_version=expected_version,
                now=now,
            )
            if closed is None:
                refreshed = await self._repo.get_statutory(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    statutory_id=current.id,
                )
                if refreshed is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This employee's current statutory record has been modified by another request",
                    current=statutory_to_audit_dict(statutory_to_read(refreshed)),
                )

        statutory_id = uuid4()
        try:
            statutory = await self._repo.insert_statutory(
                self._session,
                data={
                    "id": statutory_id,
                    "company_id": company_id,
                    "employee_id": employee_id,
                    "effective_from": body.effective_from,
                    "effective_to": None,
                    "is_pf_applicable": body.is_pf_applicable,
                    "pf_number": body.pf_number,
                    "pf_wage_ceiling_opt_out": body.pf_wage_ceiling_opt_out,
                    "vpf_amount": body.vpf_amount,
                    "vpf_percentage": body.vpf_percentage,
                    "is_esi_applicable": body.is_esi_applicable,
                    "esi_ip_number": body.esi_ip_number,
                    "pt_state_code": body.pt_state_code,
                    "is_lwf_applicable": body.is_lwf_applicable,
                    "tax_regime": body.tax_regime,
                    "is_director": body.is_director,
                    "is_international_worker": body.is_international_worker,
                    "revision_reason": body.revision_reason,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            # `employee_statutory_no_overlap` GiST exclusion constraint — the race-condition
            # backstop, mirroring `EmployeeCompensationService.create_compensation`'s exact
            # pattern.
            raise StatutoryDatesOverlapError() from exc

        after_read = statutory_to_read(statutory)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="STATUTORY_REVISED",
            entity_type="employee_statutory",
            entity_id=statutory_id,
            before=statutory_to_audit_dict(before_read) if before_read is not None else None,
            after=statutory_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def list_statutories(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        as_of: date | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> list[StatutoryRead]:
        """`scope=None` preserves this service's pre-data-scope behavior exactly (every internal
        caller except `GET .../statutory` itself). `GET .../statutory` passes its resolved
        `DataScope` (`router.py`), narrowing visibility to `SELF`/`REPORTEES`/`REPORTEE_TREE`/
        `COMPANY` per `_assert_employee_visible`."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        if as_of is not None:
            statutory = await self._repo.get_statutory_as_of(
                self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
            )
            return [statutory_to_read(statutory)] if statutory is not None else []
        statutories = await self._repo.list_statutories(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [statutory_to_read(statutory) for statutory in statutories]

    async def get_statutory(
        self,
        company_id: UUID,
        employee_id: UUID,
        statutory_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> StatutoryRead:
        """`scope=None` preserves pre-data-scope behavior exactly, mirroring `list_statutories`."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        statutory = await self._repo.get_statutory(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            statutory_id=statutory_id,
        )
        if statutory is None:
            raise NotFoundError("Resource not found")
        return statutory_to_read(statutory)

    async def get_statutory_as_of(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> StatutoryRead | None:
        """The cross-module contract (plan §13) Payroll will call, once per pay run, at
        snapshot time — `get_statutory_as_of(employee_id, date)`. Does not assert employee
        existence, mirroring `EmployeeCompensationService.get_compensation_as_of`'s exact
        contract."""
        statutory = await self._repo.get_statutory_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
        )
        return statutory_to_read(statutory) if statutory is not None else None


class EmployeeBankService:
    """E-08 — employee banking (payout-account facts). One write operation, `create_bank`,
    covering an employee's first bank row and every later revision alike
    (`docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §19) — each is an insert
    of a new effective-dated row, never a column update. No `update_bank`/`delete_bank` exists;
    there is no other mutation path.

    Reuses `EmploymentRepository.get_employment_as_of` for the covering-employment check exactly
    as `EmployeeStatutoryService.create_statutory` does (plan §15 PD-2 Option 1) — a write dated
    on-or-before a `TERMINATED` employment's `last_working_day` succeeds (it falls within the
    closed episode's range); a write dated strictly after `last_working_day` still has no
    covering episode and is rejected. This is a known, named limitation for the
    full-and-final-settlement-correction-after-exit scenario (plan §9), not resolved here since
    no source document specifies a rule beyond it.

    Deliberately does **not** close the employee's current bank row when
    `EmploymentService.terminate_employment` runs — unlike Assignment/Compensation/Statutory,
    the current row must remain open through and after exit for F&F settlement payout (plan §7,
    `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C "Employee Bank"). No change was made to
    `EmploymentService.terminate_employment` for this slice.

    Same as `EmployeeCompensationService`/`EmployeeStatutoryService`, the two `GET` routes and
    `create_bank` all accept a resolved `DataScope` and bind it via `EmployeeService.
    resolve_visible_employee_ids` — `RBAC_DATA_SCOPE_DECISIONS.md` Decision E is **LOCKED** and
    explicitly names `SELF`-scoped self-service as Banking's intended default (plan §8/§15 PD-1
    Option 2); write-path scoping was closed per `docs/modules/employee/
    39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeBankRepository()
        self._employee_repo = EmployeeRepository()
        self._employment_repo = EmploymentRepository()
        self._employee_service = EmployeeService(session, self._settings)
        self._audit = AuditService()
        self._crypto = PiiCryptoService(self._settings)

    async def _decrypt_bank(self, bank: "EmployeeBank") -> BankRead:
        """DATA-01 (plan §2.5) — the one place `EmployeeBank.account_number_enc` ciphertext is
        turned into plaintext, always after the caller's own permission check has already run
        (every method below only reaches this after `_assert_employee_visible`)."""
        plaintext = await self._crypto.decrypt_column(
            self._session,
            ciphertext=bank.account_number_enc,
            table="employee_bank",
            column="account_number_enc",
            record_id=bank.id,
        )
        return bank_to_read(bank, decrypted_account_number=plaintext)

    async def _assert_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        """`scope=None` preserves this method's pre-data-scope "exists" behavior exactly (every
        internal caller of this service except the two `GET` routes and `create_bank`, all of
        which now resolve a real `DataScope`). An out-of-scope target raises the same
        `NotFoundError` → `404` a nonexistent or cross-tenant ID already raises — no new
        branching, mirroring `EmployeeService.get_employee`'s own data-scope convention."""
        visible_ids = (
            await self._employee_service.resolve_visible_employee_ids(
                company_id, scope, caller_employee_id
            )
            if scope is not None
            else None
        )
        employee = await self._employee_repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")

    async def create_bank(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: BankCreate,
        *,
        expected_version: int | None,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BankRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

        covering_employment = await self._employment_repo.get_employment_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=body.effective_from
        )
        if covering_employment is None:
            raise NoActiveEmploymentError()

        current = await self._repo.get_current_bank(
            self._session, company_id=company_id, employee_id=employee_id
        )

        if current is not None:
            if body.effective_from <= current.effective_from:
                raise InvalidEffectiveFromError()
            if expected_version is None:
                raise BankVersionRequiredError()

        now = datetime.now(UTC)
        before_read = await self._decrypt_bank(current) if current is not None else None

        if current is not None:
            assert expected_version is not None  # narrowed above
            closed = await self._repo.close_bank(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                bank_id=current.id,
                effective_to=body.effective_from - timedelta(days=1),
                expected_version=expected_version,
                now=now,
            )
            if closed is None:
                refreshed = await self._repo.get_bank(
                    self._session,
                    company_id=company_id,
                    employee_id=employee_id,
                    bank_id=current.id,
                )
                if refreshed is None:
                    raise NotFoundError("Resource not found")
                raise StaleResourceError(
                    "This employee's current bank record has been modified by another request",
                    current=bank_to_audit_dict(await self._decrypt_bank(refreshed)),
                )

        # DATA-01 (plan §2.4/§2.5) — `bank_id` is generated up front (this codebase's own
        # `id=uuid4()`-at-construction convention) specifically so it is available to bind the
        # AAD before the row is ever persisted: encryption happens here, explicitly, in the
        # authorized service method, never inside the ORM/repository layer.
        bank_id = uuid4()
        encrypted_account_number = await self._crypto.encrypt_column(
            self._session,
            plaintext=body.account_number_enc,
            table="employee_bank",
            column="account_number_enc",
            record_id=bank_id,
        )
        try:
            bank = await self._repo.insert_bank(
                self._session,
                data={
                    "id": bank_id,
                    "company_id": company_id,
                    "employee_id": employee_id,
                    "effective_from": body.effective_from,
                    "effective_to": None,
                    "account_holder_name": body.account_holder_name,
                    "account_number_enc": encrypted_account_number,
                    "bank_name": body.bank_name,
                    "ifsc": body.ifsc,
                    "branch_name": body.branch_name,
                    "payment_mode": body.payment_mode,
                    "is_primary": True,
                    "verification_status": "PENDING",
                    "penny_drop_reference": None,
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            # `employee_bank_no_overlap` GiST exclusion constraint — the race-condition
            # backstop, mirroring `EmployeeStatutoryService.create_statutory`'s exact pattern.
            raise BankDatesOverlapError() from exc

        # Reuses the plaintext already in hand (`body.account_number_enc`) rather than issuing an
        # immediate, redundant decrypt of what this same call just encrypted.
        after_read = bank_to_read(bank, decrypted_account_number=body.account_number_enc)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="BANK_REVISED",
            entity_type="employee_bank",
            entity_id=bank_id,
            before=bank_to_audit_dict(before_read) if before_read is not None else None,
            after=bank_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def list_banks(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        as_of: date | None = None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> list[BankRead]:
        """`scope=None` preserves this service's pre-data-scope behavior exactly (every internal
        caller except `GET .../bank` itself). `GET .../bank` passes its resolved `DataScope`
        (`router.py`), narrowing visibility to `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` per
        `_assert_employee_visible` — see class docstring."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        if as_of is not None:
            bank = await self._repo.get_bank_as_of(
                self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
            )
            return [await self._decrypt_bank(bank)] if bank is not None else []
        banks = await self._repo.list_banks(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [await self._decrypt_bank(bank) for bank in banks]

    async def get_bank(
        self,
        company_id: UUID,
        employee_id: UUID,
        bank_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> BankRead:
        """`scope=None` preserves pre-data-scope behavior exactly, mirroring `list_banks`."""
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        bank = await self._repo.get_bank(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            bank_id=bank_id,
        )
        if bank is None:
            raise NotFoundError("Resource not found")
        return await self._decrypt_bank(bank)

    async def get_bank_as_of(
        self, company_id: UUID, employee_id: UUID, as_of: date
    ) -> BankRead | None:
        """The cross-module contract (plan §11) Payroll will call at bank-advice-generation
        time — `get_bank_as_of(employee_id, date)`. Does not assert employee existence,
        mirroring `EmployeeStatutoryService.get_statutory_as_of`'s exact contract."""
        bank = await self._repo.get_bank_as_of(
            self._session, company_id=company_id, employee_id=employee_id, as_of=as_of
        )
        return await self._decrypt_bank(bank) if bank is not None else None


class EmployeeExperienceService:
    """Previous employment / PF continuity (market-parity onboarding-data pass, part 4) — a
    plain one-to-many list, not effective-dated history like Statutory/Bank/Compensation.
    `create_experience` always inserts a new independent row (no "current row" to close, no
    `expected_version` on create); `delete_experience` is the only mutation path after that,
    gated by the row's own `version` for optimistic concurrency, mirroring `close_statutory`'s
    shape but as a soft-delete rather than a field update. No covering-employment check (unlike
    Bank/Statutory/Compensation) — a candidate's past-employer history has no relationship to
    their own current employment period."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeExperienceRepository()
        self._employee_repo = EmployeeRepository()
        self._employee_service = EmployeeService(session, self._settings)
        self._audit = AuditService()

    async def _assert_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        visible_ids = (
            await self._employee_service.resolve_visible_employee_ids(
                company_id, scope, caller_employee_id
            )
            if scope is not None
            else None
        )
        employee = await self._employee_repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")

    async def create_experience(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmployeeExperienceCreate,
        *,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeExperienceRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

        now = datetime.now(UTC)
        experience_id = uuid4()
        experience = await self._repo.insert_experience(
            self._session,
            data={
                "id": experience_id,
                "company_id": company_id,
                "employee_id": employee_id,
                "company_name": body.company_name,
                "designation": body.designation,
                "from_date": body.from_date,
                "to_date": body.to_date,
                "last_ctc_minor": body.last_ctc_minor,
                "reason_for_leaving": body.reason_for_leaving,
                "had_prior_pf_membership": body.had_prior_pf_membership,
                "previous_uan": body.previous_uan,
                "previous_pf_account_number": body.previous_pf_account_number,
                "previous_esi_ip_number": body.previous_esi_ip_number,
                "document_id": body.document_id,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        read = employee_experience_to_read(experience)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_EXPERIENCE_CREATED",
            entity_type="employee_experience",
            entity_id=experience_id,
            after=employee_experience_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_experiences(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> list[EmployeeExperienceRead]:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        experiences = await self._repo.list_experiences(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [employee_experience_to_read(e) for e in experiences]

    async def get_experience(
        self,
        company_id: UUID,
        employee_id: UUID,
        experience_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> EmployeeExperienceRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        experience = await self._repo.get_experience(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            experience_id=experience_id,
        )
        if experience is None:
            raise NotFoundError("Resource not found")
        return employee_experience_to_read(experience)

    async def delete_experience(
        self,
        company_id: UUID,
        employee_id: UUID,
        experience_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        current = await self._repo.get_experience(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            experience_id=experience_id,
        )
        if current is None:
            raise NotFoundError("Resource not found")

        now = datetime.now(UTC)
        deleted = await self._repo.delete_experience(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            experience_id=experience_id,
            expected_version=expected_version,
            now=now,
        )
        if deleted is None:
            refreshed = await self._repo.get_experience(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                experience_id=experience_id,
            )
            if refreshed is None:
                raise NotFoundError("Resource not found")
            raise StaleResourceError(
                "This experience record has been modified by another request",
                current=employee_experience_to_audit_dict(employee_experience_to_read(refreshed)),
            )

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_EXPERIENCE_DELETED",
            entity_type="employee_experience",
            entity_id=experience_id,
            before=employee_experience_to_audit_dict(employee_experience_to_read(current)),
            ip=ip_address,
            user_agent=user_agent,
        )


class EmployeeEducationService:
    """Education history (market-parity onboarding-data pass, part 5) — mirrors
    `EmployeeExperienceService`'s exact shape (plain one-to-many list, no covering-employment
    check, soft-delete the only mutation path after insert)."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeEducationRepository()
        self._employee_repo = EmployeeRepository()
        self._employee_service = EmployeeService(session, self._settings)
        self._audit = AuditService()

    async def _assert_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        visible_ids = (
            await self._employee_service.resolve_visible_employee_ids(
                company_id, scope, caller_employee_id
            )
            if scope is not None
            else None
        )
        employee = await self._employee_repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")

    async def create_education(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmployeeEducationCreate,
        *,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeEducationRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )

        now = datetime.now(UTC)
        education_id = uuid4()
        education = await self._repo.insert_education(
            self._session,
            data={
                "id": education_id,
                "company_id": company_id,
                "employee_id": employee_id,
                "qualification": body.qualification,
                "institution_name": body.institution_name,
                "year_of_passing": body.year_of_passing,
                "document_id": body.document_id,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        read = employee_education_to_read(education)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_EDUCATION_CREATED",
            entity_type="employee_education",
            entity_id=education_id,
            after=employee_education_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_educations(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> list[EmployeeEducationRead]:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        educations = await self._repo.list_educations(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [employee_education_to_read(e) for e in educations]

    async def get_education(
        self,
        company_id: UUID,
        employee_id: UUID,
        education_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> EmployeeEducationRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        education = await self._repo.get_education(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            education_id=education_id,
        )
        if education is None:
            raise NotFoundError("Resource not found")
        return employee_education_to_read(education)

    async def delete_education(
        self,
        company_id: UUID,
        employee_id: UUID,
        education_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        current = await self._repo.get_education(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            education_id=education_id,
        )
        if current is None:
            raise NotFoundError("Resource not found")

        now = datetime.now(UTC)
        deleted = await self._repo.delete_education(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            education_id=education_id,
            expected_version=expected_version,
            now=now,
        )
        if deleted is None:
            refreshed = await self._repo.get_education(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                education_id=education_id,
            )
            if refreshed is None:
                raise NotFoundError("Resource not found")
            raise StaleResourceError(
                "This education record has been modified by another request",
                current=employee_education_to_audit_dict(employee_education_to_read(refreshed)),
            )

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_EDUCATION_DELETED",
            entity_type="employee_education",
            entity_id=education_id,
            before=employee_education_to_audit_dict(employee_education_to_read(current)),
            ip=ip_address,
            user_agent=user_agent,
        )


class EmployeeDependentService:
    """PF/Gratuity nominee declaration + ESI family details (market-parity onboarding-data
    pass, part 6) — mirrors `EmployeeEducationService`'s exact shape (plain one-to-many list, no
    covering-employment check, soft-delete the only mutation path after insert), plus two things
    neither Experience nor Education need: `aadhaar_number_enc` is DATA-01-encrypted at create
    time (same `create_bank`-style up-front-id-then-encrypt pattern), and each nominee scheme's
    (`is_pf_nominee`/`is_gratuity_nominee`) share percentage is validated against the sum of the
    employee's *other* nominee dependents in that same scheme before insert — a DB `CHECK` cannot
    aggregate across sibling rows, so this is the one place that rule can live."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = EmployeeDependentRepository()
        self._employee_repo = EmployeeRepository()
        self._employee_service = EmployeeService(session, self._settings)
        self._audit = AuditService()
        self._crypto = PiiCryptoService(self._settings)

    async def _decrypt_dependent(self, dependent: "EmployeeDependent") -> EmployeeDependentRead:
        plaintext = await self._crypto.decrypt_column(
            self._session,
            ciphertext=dependent.aadhaar_number_enc,
            table="employee_dependent",
            column="aadhaar_number_enc",
            record_id=dependent.id,
        )
        return employee_dependent_to_read(dependent, decrypted_aadhaar_number=plaintext)

    async def _assert_employee_visible(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None,
        caller_employee_id: UUID | None,
    ) -> None:
        visible_ids = (
            await self._employee_service.resolve_visible_employee_ids(
                company_id, scope, caller_employee_id
            )
            if scope is not None
            else None
        )
        employee = await self._employee_repo.get_employee(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            visible_employee_ids=visible_ids,
        )
        if employee is None:
            raise NotFoundError("Resource not found")

    async def _assert_percentage_within_limit(
        self, company_id: UUID, employee_id: UUID, body: EmployeeDependentCreate
    ) -> None:
        if body.is_pf_nominee:
            existing = await self._repo.sum_pf_nominee_percentage(
                self._session, company_id=company_id, employee_id=employee_id
            )
            total = existing + (body.pf_nominee_share_percentage or 0)
            if total > 100:
                raise NomineePercentageExceededError(
                    field="pf_nominee_share_percentage", scheme="PF", total=total
                )
        if body.is_gratuity_nominee:
            existing = await self._repo.sum_gratuity_nominee_percentage(
                self._session, company_id=company_id, employee_id=employee_id
            )
            total = existing + (body.gratuity_nominee_share_percentage or 0)
            if total > 100:
                raise NomineePercentageExceededError(
                    field="gratuity_nominee_share_percentage", scheme="Gratuity", total=total
                )

    async def create_dependent(
        self,
        company_id: UUID,
        employee_id: UUID,
        body: EmployeeDependentCreate,
        *,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeDependentRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        await self._assert_percentage_within_limit(company_id, employee_id, body)

        now = datetime.now(UTC)
        # DATA-01 (plan §2.4/§2.5) — `dependent_id` is generated up front, same convention
        # `EmployeeBankService.create_bank` uses for `account_number_enc`, so it is available to
        # bind the AAD before the row is ever persisted.
        dependent_id = uuid4()
        encrypted_aadhaar = await self._crypto.encrypt_column(
            self._session,
            plaintext=body.aadhaar_number_enc,
            table="employee_dependent",
            column="aadhaar_number_enc",
            record_id=dependent_id,
        )
        dependent = await self._repo.insert_dependent(
            self._session,
            data={
                "id": dependent_id,
                "company_id": company_id,
                "employee_id": employee_id,
                "full_name": body.full_name,
                "relationship": body.relationship,
                "date_of_birth": body.date_of_birth,
                "gender": body.gender,
                "is_minor": body.is_minor,
                "guardian_name": body.guardian_name,
                "guardian_relationship": body.guardian_relationship,
                "aadhaar_number_enc": encrypted_aadhaar,
                "is_pf_nominee": body.is_pf_nominee,
                "pf_nominee_share_percentage": body.pf_nominee_share_percentage,
                "is_gratuity_nominee": body.is_gratuity_nominee,
                "gratuity_nominee_share_percentage": body.gratuity_nominee_share_percentage,
                "is_esi_dependent": body.is_esi_dependent,
                "document_id": body.document_id,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        # Reuses the plaintext already in hand (`body.aadhaar_number_enc`) rather than issuing an
        # immediate, redundant decrypt of what this same call just encrypted.
        read = employee_dependent_to_read(
            dependent, decrypted_aadhaar_number=body.aadhaar_number_enc
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_DEPENDENT_CREATED",
            entity_type="employee_dependent",
            entity_id=dependent_id,
            after=employee_dependent_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_dependents(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> list[EmployeeDependentRead]:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        dependents = await self._repo.list_dependents(
            self._session, company_id=company_id, employee_id=employee_id
        )
        return [await self._decrypt_dependent(d) for d in dependents]

    async def get_dependent(
        self,
        company_id: UUID,
        employee_id: UUID,
        dependent_id: UUID,
        *,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
    ) -> EmployeeDependentRead:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        dependent = await self._repo.get_dependent(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            dependent_id=dependent_id,
        )
        if dependent is None:
            raise NotFoundError("Resource not found")
        return await self._decrypt_dependent(dependent)

    async def delete_dependent(
        self,
        company_id: UUID,
        employee_id: UUID,
        dependent_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        scope: DataScope | None = None,
        caller_employee_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        await self._assert_employee_visible(
            company_id, employee_id, scope=scope, caller_employee_id=caller_employee_id
        )
        current = await self._repo.get_dependent(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            dependent_id=dependent_id,
        )
        if current is None:
            raise NotFoundError("Resource not found")
        current_read = await self._decrypt_dependent(current)

        now = datetime.now(UTC)
        deleted = await self._repo.delete_dependent(
            self._session,
            company_id=company_id,
            employee_id=employee_id,
            dependent_id=dependent_id,
            expected_version=expected_version,
            now=now,
        )
        if deleted is None:
            refreshed = await self._repo.get_dependent(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                dependent_id=dependent_id,
            )
            if refreshed is None:
                raise NotFoundError("Resource not found")
            raise StaleResourceError(
                "This dependent record has been modified by another request",
                current=employee_dependent_to_audit_dict(await self._decrypt_dependent(refreshed)),
            )

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="EMPLOYEE_DEPENDENT_DELETED",
            entity_type="employee_dependent",
            entity_id=dependent_id,
            before=employee_dependent_to_audit_dict(current_read),
            ip=ip_address,
            user_agent=user_agent,
        )
