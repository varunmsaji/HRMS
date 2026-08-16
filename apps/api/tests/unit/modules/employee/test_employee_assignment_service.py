"""Unit tests for `EmployeeAssignmentService` — E-04 (employee assignment)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from hrms.core.errors.base import NotFoundError
from hrms.modules.employee.exceptions import (
    AssignmentDatesOverlapError,
    AssignmentFieldsRequiredError,
    AssignmentVersionRequiredError,
    InvalidBranchReferenceError,
    InvalidDepartmentReferenceError,
    InvalidDesignationReferenceError,
    InvalidEffectiveFromError,
    InvalidGradeReferenceError,
    InvalidReportingManagerError,
    InvalidShiftReferenceError,
    NoActiveEmploymentError,
    ShiftIdRequiredError,
    StaleResourceError,
)
from hrms.modules.employee.models import Employee, EmployeeAssignment, Employment
from hrms.modules.employee.schemas import AssignmentCreate
from hrms.modules.employee.service import EmployeeAssignmentService


def _employee(**overrides: object) -> Employee:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "user_id": None,
        "employee_code": "EMP-0001",
        "first_name": "Asha",
        "middle_name": None,
        "last_name": "Verma",
        "display_name": None,
        "date_of_birth": None,
        "gender": None,
        "blood_group": None,
        "marital_status": None,
        "nationality": None,
        "personal_email": None,
        "personal_mobile": None,
        "photo_url": None,
        "pan_number_enc": None,
        "aadhaar_number_enc": None,
        "uan_number": None,
        "status": "ACTIVE",
        "custom_fields": None,
        "is_active": True,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Employee(**defaults)  # type: ignore[arg-type]


def _employment(**overrides: object) -> Employment:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "employee_id": uuid4(),
        "legal_entity_id": uuid4(),
        "joining_date": date(2027, 6, 1),
        "last_working_day": None,
        "status": "ACTIVE",
        "previous_employment_id": None,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Employment(**defaults)  # type: ignore[arg-type]


def _assignment(**overrides: object) -> EmployeeAssignment:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "employee_id": uuid4(),
        "branch_id": uuid4(),
        "department_id": uuid4(),
        "designation_id": uuid4(),
        "grade_id": None,
        "reporting_manager_id": None,
        "dotted_line_manager_id": None,
        "cost_centre_id": None,
        "shift_id": None,
        "work_location_type": None,
        "change_type": "INITIAL",
        "change_reason": None,
        "effective_from": date(2027, 6, 1),
        "effective_to": None,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return EmployeeAssignment(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> EmployeeAssignmentService:
    session = MagicMock()
    svc = EmployeeAssignmentService(session)
    svc._repo = AsyncMock()
    svc._employee_repo = AsyncMock()
    svc._employment_repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


def _mock_organisation_ok() -> AsyncMock:
    org_service = AsyncMock()
    org_service.get_branch = AsyncMock(return_value=MagicMock())
    org_service.get_department = AsyncMock(return_value=MagicMock())
    org_service.get_designation = AsyncMock(return_value=MagicMock())
    org_service.get_grade = AsyncMock(return_value=MagicMock())
    org_service.get_shift = AsyncMock(return_value=MagicMock())
    return org_service


def _mock_organisation_missing(*, missing: str) -> AsyncMock:
    org_service = _mock_organisation_ok()
    getattr(org_service, f"get_{missing}").side_effect = NotFoundError("Resource not found")
    return org_service


def _patch_organisation(mock: AsyncMock):  # type: ignore[no-untyped-def]
    return patch("hrms.modules.organisation.service.OrganisationService", return_value=mock)


# --- Create: first assignment (no current row) --------------------------------------------


@pytest.mark.asyncio
async def test_create_first_assignment_success(service: EmployeeAssignmentService) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_assignment.return_value = None
    service._repo.insert_assignment.return_value = _assignment(
        company_id=company_id, employee_id=employee_id
    )

    with _patch_organisation(_mock_organisation_ok()):
        result = await service.create_assignment(
            company_id,
            employee_id,
            AssignmentCreate(
                effective_from=date(2027, 6, 1),
                change_type="INITIAL",
                branch_id=uuid4(),
                department_id=uuid4(),
                designation_id=uuid4(),
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )

    assert result.change_type == "INITIAL"
    service._repo.close_assignment.assert_not_awaited()
    service._audit.record.assert_awaited_once()
    call = service._audit.record.call_args.kwargs
    assert call["action"] == "ASSIGNMENT_CHANGED"
    assert call["before"] is None


@pytest.mark.asyncio
async def test_create_first_assignment_missing_mandatory_fields_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None

    with pytest.raises(AssignmentFieldsRequiredError):
        await service.create_assignment(
            uuid4(),
            uuid4(),
            AssignmentCreate(
                effective_from=date(2027, 6, 1),
                change_type="INITIAL",
                branch_id=uuid4(),
                # department_id/designation_id omitted
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.insert_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_assignment_no_covering_employment_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = None

    with pytest.raises(NoActiveEmploymentError):
        await service.create_assignment(
            uuid4(),
            uuid4(),
            AssignmentCreate(
                effective_from=date(2027, 6, 1),
                change_type="INITIAL",
                branch_id=uuid4(),
                department_id=uuid4(),
                designation_id=uuid4(),
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.get_current_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_assignment_unknown_employee_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.create_assignment(
            uuid4(),
            uuid4(),
            AssignmentCreate(
                effective_from=date(2027, 6, 1),
                change_type="INITIAL",
                branch_id=uuid4(),
                department_id=uuid4(),
                designation_id=uuid4(),
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._employment_repo.get_employment_as_of.assert_not_awaited()


# --- Create: transfer/promotion (current row exists, carry-forward) -----------------------


@pytest.mark.asyncio
async def test_create_transfer_carries_forward_unspecified_fields(
    service: EmployeeAssignmentService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    current_branch = uuid4()
    current_designation = uuid4()
    new_department = uuid4()

    current = _assignment(
        company_id=company_id,
        employee_id=employee_id,
        branch_id=current_branch,
        department_id=uuid4(),
        designation_id=current_designation,
        effective_from=date(2027, 6, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_assignment.return_value = current
    service._repo.close_assignment.return_value = _assignment(
        id=current.id, effective_to=date(2028, 3, 31), version=2
    )
    service._repo.insert_assignment.return_value = _assignment(
        company_id=company_id,
        employee_id=employee_id,
        branch_id=current_branch,
        department_id=new_department,
        designation_id=current_designation,
        change_type="TRANSFER",
        effective_from=date(2028, 4, 1),
    )

    with _patch_organisation(_mock_organisation_ok()):
        result = await service.create_assignment(
            company_id,
            employee_id,
            AssignmentCreate(
                effective_from=date(2028, 4, 1),
                change_type="TRANSFER",
                department_id=new_department,
            ),
            expected_version=1,
            actor_user_id=uuid4(),
        )

    assert result.department_id == new_department
    insert_data = service._repo.insert_assignment.call_args.kwargs["data"]
    assert insert_data["branch_id"] == current_branch
    assert insert_data["designation_id"] == current_designation
    close_kwargs = service._repo.close_assignment.call_args.kwargs
    assert close_kwargs["effective_to"] == date(2028, 3, 31)
    assert close_kwargs["expected_version"] == 1


@pytest.mark.asyncio
async def test_create_assignment_requires_if_match_when_current_exists(
    service: EmployeeAssignmentService,
) -> None:
    current = _assignment(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = current

    with pytest.raises(AssignmentVersionRequiredError):
        await service.create_assignment(
            uuid4(),
            uuid4(),
            AssignmentCreate(effective_from=date(2028, 1, 1), change_type="TRANSFER"),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.close_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_assignment_effective_from_not_after_current_rejected(
    service: EmployeeAssignmentService,
) -> None:
    current = _assignment(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = current

    with pytest.raises(InvalidEffectiveFromError):
        await service.create_assignment(
            uuid4(),
            uuid4(),
            AssignmentCreate(effective_from=date(2027, 6, 1), change_type="TRANSFER"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_assignment_stale_version_conflict(
    service: EmployeeAssignmentService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    current = _assignment(
        company_id=company_id, employee_id=employee_id, effective_from=date(2027, 6, 1)
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_assignment.return_value = current
    service._repo.close_assignment.return_value = None
    service._repo.get_assignment.return_value = current

    with _patch_organisation(_mock_organisation_ok()):
        with pytest.raises(StaleResourceError):
            await service.create_assignment(
                company_id,
                employee_id,
                AssignmentCreate(effective_from=date(2028, 1, 1), change_type="TRANSFER"),
                expected_version=1,
                actor_user_id=uuid4(),
            )
    service._repo.insert_assignment.assert_not_awaited()


# --- Reference validation -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_assignment_invalid_branch_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None

    with _patch_organisation(_mock_organisation_missing(missing="branch")):
        with pytest.raises(InvalidBranchReferenceError):
            await service.create_assignment(
                uuid4(),
                uuid4(),
                AssignmentCreate(
                    effective_from=date(2027, 6, 1),
                    change_type="INITIAL",
                    branch_id=uuid4(),
                    department_id=uuid4(),
                    designation_id=uuid4(),
                ),
                expected_version=None,
                actor_user_id=uuid4(),
            )
    service._repo.insert_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_assignment_invalid_department_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None

    with _patch_organisation(_mock_organisation_missing(missing="department")):
        with pytest.raises(InvalidDepartmentReferenceError):
            await service.create_assignment(
                uuid4(),
                uuid4(),
                AssignmentCreate(
                    effective_from=date(2027, 6, 1),
                    change_type="INITIAL",
                    branch_id=uuid4(),
                    department_id=uuid4(),
                    designation_id=uuid4(),
                ),
                expected_version=None,
                actor_user_id=uuid4(),
            )


@pytest.mark.asyncio
async def test_create_assignment_invalid_designation_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None

    with _patch_organisation(_mock_organisation_missing(missing="designation")):
        with pytest.raises(InvalidDesignationReferenceError):
            await service.create_assignment(
                uuid4(),
                uuid4(),
                AssignmentCreate(
                    effective_from=date(2027, 6, 1),
                    change_type="INITIAL",
                    branch_id=uuid4(),
                    department_id=uuid4(),
                    designation_id=uuid4(),
                ),
                expected_version=None,
                actor_user_id=uuid4(),
            )


@pytest.mark.asyncio
async def test_create_assignment_invalid_grade_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None

    with _patch_organisation(_mock_organisation_missing(missing="grade")):
        with pytest.raises(InvalidGradeReferenceError):
            await service.create_assignment(
                uuid4(),
                uuid4(),
                AssignmentCreate(
                    effective_from=date(2027, 6, 1),
                    change_type="INITIAL",
                    branch_id=uuid4(),
                    department_id=uuid4(),
                    designation_id=uuid4(),
                    grade_id=uuid4(),
                ),
                expected_version=None,
                actor_user_id=uuid4(),
            )


# --- Shift change (E-05) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shift_change_with_valid_shift_succeeds(
    service: EmployeeAssignmentService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    shift_id = uuid4()
    current = _assignment(
        company_id=company_id,
        employee_id=employee_id,
        effective_from=date(2027, 6, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_assignment.return_value = current
    service._repo.close_assignment.return_value = _assignment(id=current.id, version=2)
    service._repo.insert_assignment.return_value = _assignment(
        company_id=company_id,
        employee_id=employee_id,
        shift_id=shift_id,
        change_type="SHIFT_CHANGE",
        effective_from=date(2028, 4, 1),
    )

    with _patch_organisation(_mock_organisation_ok()):
        result = await service.create_assignment(
            company_id,
            employee_id,
            AssignmentCreate(
                effective_from=date(2028, 4, 1), change_type="SHIFT_CHANGE", shift_id=shift_id
            ),
            expected_version=1,
            actor_user_id=uuid4(),
        )

    assert result.shift_id == shift_id
    assert result.change_type == "SHIFT_CHANGE"
    insert_data = service._repo.insert_assignment.call_args.kwargs["data"]
    assert insert_data["shift_id"] == shift_id
    audit_call = service._audit.record.call_args.kwargs
    assert audit_call["after"]["shift_id"] == str(shift_id)


@pytest.mark.asyncio
async def test_shift_change_missing_shift_id_rejected(
    service: EmployeeAssignmentService,
) -> None:
    current = _assignment(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = current

    with pytest.raises(ShiftIdRequiredError):
        await service.create_assignment(
            uuid4(),
            uuid4(),
            AssignmentCreate(effective_from=date(2028, 1, 1), change_type="SHIFT_CHANGE"),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.get_current_assignment.assert_not_awaited()
    service._repo.insert_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_assignment_invalid_shift_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None

    with _patch_organisation(_mock_organisation_missing(missing="shift")):
        with pytest.raises(InvalidShiftReferenceError):
            await service.create_assignment(
                uuid4(),
                uuid4(),
                AssignmentCreate(
                    effective_from=date(2027, 6, 1),
                    change_type="INITIAL",
                    branch_id=uuid4(),
                    department_id=uuid4(),
                    designation_id=uuid4(),
                    shift_id=uuid4(),
                ),
                expected_version=None,
                actor_user_id=uuid4(),
            )
    service._repo.insert_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_assignment_shift_id_optional(
    service: EmployeeAssignmentService,
) -> None:
    """`shift_id` is not in the mandatory-at-first-placement set — an employee can have no
    shift from day one (plan §5)."""
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None
    service._repo.insert_assignment.return_value = _assignment(shift_id=None)

    with _patch_organisation(_mock_organisation_ok()):
        result = await service.create_assignment(
            uuid4(),
            uuid4(),
            AssignmentCreate(
                effective_from=date(2027, 6, 1),
                change_type="INITIAL",
                branch_id=uuid4(),
                department_id=uuid4(),
                designation_id=uuid4(),
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )

    assert result.shift_id is None
    insert_data = service._repo.insert_assignment.call_args.kwargs["data"]
    assert insert_data["shift_id"] is None


@pytest.mark.asyncio
async def test_transfer_carries_forward_shift_id_when_omitted(
    service: EmployeeAssignmentService,
) -> None:
    """`shift_id` follows the same carry-forward rule as every other optional field: an
    unrelated `TRANSFER` that omits `shift_id` must not clear it."""
    company_id = uuid4()
    employee_id = uuid4()
    current_shift = uuid4()
    new_department = uuid4()

    current = _assignment(
        company_id=company_id,
        employee_id=employee_id,
        shift_id=current_shift,
        effective_from=date(2027, 6, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_assignment.return_value = current
    service._repo.close_assignment.return_value = _assignment(id=current.id, version=2)
    service._repo.insert_assignment.return_value = _assignment(
        company_id=company_id,
        employee_id=employee_id,
        shift_id=current_shift,
        department_id=new_department,
        change_type="TRANSFER",
        effective_from=date(2028, 4, 1),
    )

    with _patch_organisation(_mock_organisation_ok()):
        await service.create_assignment(
            company_id,
            employee_id,
            AssignmentCreate(
                effective_from=date(2028, 4, 1),
                change_type="TRANSFER",
                department_id=new_department,
            ),
            expected_version=1,
            actor_user_id=uuid4(),
        )

    insert_data = service._repo.insert_assignment.call_args.kwargs["data"]
    assert insert_data["shift_id"] == current_shift


@pytest.mark.asyncio
async def test_create_assignment_self_reporting_manager_rejected(
    service: EmployeeAssignmentService,
) -> None:
    employee_id = uuid4()
    service._employee_repo.get_employee.return_value = _employee(id=employee_id)
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None

    with _patch_organisation(_mock_organisation_ok()):
        with pytest.raises(InvalidReportingManagerError):
            await service.create_assignment(
                uuid4(),
                employee_id,
                AssignmentCreate(
                    effective_from=date(2027, 6, 1),
                    change_type="INITIAL",
                    branch_id=uuid4(),
                    department_id=uuid4(),
                    designation_id=uuid4(),
                    reporting_manager_id=employee_id,
                ),
                expected_version=None,
                actor_user_id=uuid4(),
            )


@pytest.mark.asyncio
async def test_create_assignment_unknown_reporting_manager_rejected(
    service: EmployeeAssignmentService,
) -> None:
    employee_id = uuid4()

    async def _get_employee(
        _session: object,
        *,
        company_id: object,
        employee_id: object,
        visible_employee_ids: object = None,
    ) -> object:
        # First call resolves the assignment's own employee (via `_assert_employee_visible`);
        # second call resolves the manager (`None` — does not exist).
        if _get_employee.calls == 0:  # type: ignore[attr-defined]
            _get_employee.calls += 1  # type: ignore[attr-defined]
            return _employee(id=employee_id)
        return None

    _get_employee.calls = 0  # type: ignore[attr-defined]
    service._employee_repo.get_employee.side_effect = _get_employee
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None

    with _patch_organisation(_mock_organisation_ok()):
        with pytest.raises(InvalidReportingManagerError):
            await service.create_assignment(
                uuid4(),
                employee_id,
                AssignmentCreate(
                    effective_from=date(2027, 6, 1),
                    change_type="INITIAL",
                    branch_id=uuid4(),
                    department_id=uuid4(),
                    designation_id=uuid4(),
                    reporting_manager_id=uuid4(),
                ),
                expected_version=None,
                actor_user_id=uuid4(),
            )


# --- GiST exclusion constraint race backstop ------------------------------------------------


@pytest.mark.asyncio
async def test_create_assignment_overlap_race_converted_to_domain_error(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_assignment.return_value = None
    service._repo.insert_assignment.side_effect = IntegrityError("", {}, Exception())

    with _patch_organisation(_mock_organisation_ok()):
        with pytest.raises(AssignmentDatesOverlapError):
            await service.create_assignment(
                uuid4(),
                uuid4(),
                AssignmentCreate(
                    effective_from=date(2027, 6, 1),
                    change_type="INITIAL",
                    branch_id=uuid4(),
                    department_id=uuid4(),
                    designation_id=uuid4(),
                ),
                expected_version=None,
                actor_user_id=uuid4(),
            )


# --- Read / list (incl. as-of) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_assignments_unknown_employee_rejected(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.list_assignments(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_list_assignments_as_of_returns_single_match(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_assignment_as_of.return_value = _assignment()

    result = await service.list_assignments(uuid4(), uuid4(), as_of=date(2029, 8, 15))

    assert len(result) == 1
    service._repo.list_assignments.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_assignments_as_of_no_match_returns_empty(
    service: EmployeeAssignmentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_assignment_as_of.return_value = None

    result = await service.list_assignments(uuid4(), uuid4(), as_of=date(2031, 1, 1))

    assert result == []


@pytest.mark.asyncio
async def test_get_assignment_not_found(service: EmployeeAssignmentService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_assignment.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_assignment(uuid4(), uuid4(), uuid4())


@pytest.mark.asyncio
async def test_get_assignment_as_of_does_not_require_employee_lookup(
    service: EmployeeAssignmentService,
) -> None:
    """The shared cross-module contract other modules will call — does not assert employee
    existence, matching the plan's own note (§9): a nonexistent `employee_id` simply yields no
    covering row."""
    service._repo.get_assignment_as_of.return_value = None

    result = await service.get_assignment_as_of(uuid4(), uuid4(), date(2029, 8, 15))

    assert result is None
    service._employee_repo.get_employee.assert_not_awaited()
