"""Unit tests for `EmploymentService` — E-03 (employment lifecycle)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from hrms.core.errors.base import NotFoundError
from hrms.modules.employee.exceptions import (
    EmploymentDatesOverlapError,
    EmploymentNotActiveError,
    InvalidLastWorkingDayError,
    InvalidLegalEntityReferenceError,
    StaleResourceError,
)
from hrms.modules.employee.models import (
    Employee,
    EmployeeAssignment,
    EmployeeCompensation,
    Employment,
)
from hrms.modules.employee.schemas import EmploymentCreate, EmploymentTerminate, EmploymentUpdate
from hrms.modules.employee.service import EmploymentService


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
        "pay_basis": "MONTHLY",
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


def _compensation(**overrides: object) -> EmployeeCompensation:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "employee_id": uuid4(),
        "annual_ctc_minor": 12_00_000_00,
        "currency": "INR",
        "revision_type": "JOINING",
        "revision_reason": "Initial hire",
        "effective_from": date(2027, 6, 1),
        "effective_to": None,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return EmployeeCompensation(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> EmploymentService:
    session = MagicMock()
    svc = EmploymentService(session)
    svc._repo = AsyncMock()
    svc._employee_repo = AsyncMock()
    svc._assignment_repo = AsyncMock()
    svc._compensation_repo = AsyncMock()
    svc._statutory_repo = AsyncMock()
    svc._audit = AsyncMock()
    # Far in the past, so a test's termination date is always in the future and the immediate
    # access-revocation branch (covered by integration tests) stays out of these unit tests.
    svc._company_today = AsyncMock(return_value=date(2000, 1, 1))
    # Default: no current assignment/compensation/statutory row — most termination tests don't
    # exercise the E-04/E-06/E-07 closure path, mirroring how `_repo`/`_employee_repo` default to
    # unset `AsyncMock` return values that individual tests override as needed.
    svc._assignment_repo.get_current_assignment.return_value = None
    svc._compensation_repo.get_current_compensation.return_value = None
    svc._statutory_repo.get_current_statutory.return_value = None
    return svc


def _mock_legal_entity_ok() -> AsyncMock:
    org_service = AsyncMock()
    org_service.get_legal_entity = AsyncMock(return_value=MagicMock())
    return org_service


def _mock_legal_entity_missing() -> AsyncMock:
    org_service = AsyncMock()
    org_service.get_legal_entity = AsyncMock(side_effect=NotFoundError("Resource not found"))
    return org_service


# --- Create (first hire / rehire) -----------------------------------------------------


@pytest.mark.asyncio
async def test_create_employment_first_hire_records_started_audit(
    service: EmploymentService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._repo.get_latest_employment.return_value = None
    service._repo.insert_employment.return_value = _employment(
        company_id=company_id, employee_id=employee_id, previous_employment_id=None
    )

    with patch(
        "hrms.modules.organisation.service.OrganisationService",
        return_value=_mock_legal_entity_ok(),
    ):
        result = await service.create_employment(
            company_id,
            employee_id,
            EmploymentCreate(legal_entity_id=uuid4(), joining_date=date(2027, 6, 1)),
            actor_user_id=uuid4(),
        )

    assert result.status == "ACTIVE"
    assert result.previous_employment_id is None
    service._audit.record.assert_awaited_once()
    assert service._audit.record.call_args.kwargs["action"] == "EMPLOYMENT_STARTED"


@pytest.mark.asyncio
async def test_create_employment_rehire_links_previous_and_records_rehired_audit(
    service: EmploymentService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    previous = _employment(
        company_id=company_id,
        employee_id=employee_id,
        status="TERMINATED",
        joining_date=date(2027, 6, 1),
        last_working_day=date(2030, 9, 30),
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._repo.get_latest_employment.return_value = previous
    service._repo.insert_employment.return_value = _employment(
        company_id=company_id,
        employee_id=employee_id,
        previous_employment_id=previous.id,
        joining_date=date(2034, 2, 1),
    )

    with patch(
        "hrms.modules.organisation.service.OrganisationService",
        return_value=_mock_legal_entity_ok(),
    ):
        result = await service.create_employment(
            company_id,
            employee_id,
            EmploymentCreate(legal_entity_id=uuid4(), joining_date=date(2034, 2, 1)),
            actor_user_id=uuid4(),
        )

    assert result.previous_employment_id == previous.id
    assert service._audit.record.call_args.kwargs["action"] == "EMPLOYMENT_REHIRED"
    # `previous_employment_id` is server-computed only — never accepted as client input
    # (`EmploymentCreate` has no such field at all, enforced by `extra="forbid"`).
    insert_data = service._repo.insert_employment.call_args.kwargs["data"]
    assert insert_data["previous_employment_id"] == previous.id


@pytest.mark.asyncio
async def test_create_employment_unknown_employee_rejected(service: EmploymentService) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.create_employment(
            uuid4(),
            uuid4(),
            EmploymentCreate(legal_entity_id=uuid4(), joining_date=date(2027, 6, 1)),
            actor_user_id=uuid4(),
        )
    service._repo.insert_employment.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_employment_invalid_legal_entity_rejected(
    service: EmploymentService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()

    with patch(
        "hrms.modules.organisation.service.OrganisationService",
        return_value=_mock_legal_entity_missing(),
    ):
        with pytest.raises(InvalidLegalEntityReferenceError):
            await service.create_employment(
                uuid4(),
                uuid4(),
                EmploymentCreate(legal_entity_id=uuid4(), joining_date=date(2027, 6, 1)),
                actor_user_id=uuid4(),
            )
    service._repo.insert_employment.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_employment_overlap_race_converted_to_domain_error(
    service: EmploymentService,
) -> None:
    """The `employment_no_overlap` GiST exclusion constraint is the race-condition backstop
    for "employee already has an active employment" — a raw `IntegrityError` must never leak
    as an opaque 500."""
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_latest_employment.return_value = None
    service._repo.insert_employment.side_effect = IntegrityError("", {}, Exception())

    with patch(
        "hrms.modules.organisation.service.OrganisationService",
        return_value=_mock_legal_entity_ok(),
    ):
        with pytest.raises(EmploymentDatesOverlapError):
            await service.create_employment(
                uuid4(),
                uuid4(),
                EmploymentCreate(legal_entity_id=uuid4(), joining_date=date(2027, 6, 1)),
                actor_user_id=uuid4(),
            )


# --- Read / list (incl. as-of) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_employments_unknown_employee_rejected(service: EmploymentService) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.list_employments(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_list_employments_as_of_returns_single_match(service: EmploymentService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment_as_of.return_value = _employment()

    result = await service.list_employments(uuid4(), uuid4(), as_of=date(2029, 8, 15))

    assert len(result) == 1
    service._repo.list_employments.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_employments_as_of_no_match_returns_empty(service: EmploymentService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment_as_of.return_value = None

    result = await service.list_employments(uuid4(), uuid4(), as_of=date(2031, 1, 1))

    assert result == []


@pytest.mark.asyncio
async def test_get_employment_not_found(service: EmploymentService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_employment(uuid4(), uuid4(), uuid4())


# --- Update ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_employment_not_found(service: EmploymentService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_employment(
            uuid4(),
            uuid4(),
            uuid4(),
            EmploymentUpdate(legal_entity_id=uuid4()),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_employment_noop_when_patch_empty(service: EmploymentService) -> None:
    employment = _employment()
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment

    result = await service.update_employment(
        employment.company_id,
        employment.employee_id,
        employment.id,
        EmploymentUpdate(),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.id == employment.id
    service._repo.update_employment.assert_not_awaited()
    service._audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_terminated_employment_rejected(service: EmploymentService) -> None:
    employment = _employment(status="TERMINATED", last_working_day=date(2030, 9, 30))
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment

    with pytest.raises(EmploymentNotActiveError):
        await service.update_employment(
            employment.company_id,
            employment.employee_id,
            employment.id,
            EmploymentUpdate(legal_entity_id=uuid4()),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_employment.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_employment_stale_version_conflict(service: EmploymentService) -> None:
    employment = _employment()
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._repo.update_employment.return_value = None

    with patch(
        "hrms.modules.organisation.service.OrganisationService",
        return_value=_mock_legal_entity_ok(),
    ):
        with pytest.raises(StaleResourceError):
            await service.update_employment(
                employment.company_id,
                employment.employee_id,
                employment.id,
                EmploymentUpdate(legal_entity_id=uuid4()),
                expected_version=1,
                actor_user_id=uuid4(),
            )


# --- Termination -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_employment_records_audit_and_transitions_status(
    service: EmploymentService,
) -> None:
    employment = _employment(joining_date=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._repo.update_employment.return_value = _employment(
        id=employment.id,
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        status="TERMINATED",
        last_working_day=date(2030, 9, 30),
        version=2,
    )

    result = await service.terminate_employment(
        employment.company_id,
        employment.employee_id,
        employment.id,
        EmploymentTerminate(last_working_day=date(2030, 9, 30)),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.status == "TERMINATED"
    assert result.last_working_day == date(2030, 9, 30)
    assert service._audit.record.call_args.kwargs["action"] == "EMPLOYMENT_TERMINATED"


@pytest.mark.asyncio
async def test_terminate_already_terminated_employment_rejected(
    service: EmploymentService,
) -> None:
    employment = _employment(status="TERMINATED", last_working_day=date(2030, 9, 30))
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment

    with pytest.raises(EmploymentNotActiveError):
        await service.terminate_employment(
            employment.company_id,
            employment.employee_id,
            employment.id,
            EmploymentTerminate(last_working_day=date(2030, 12, 31)),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_employment.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminate_employment_last_working_day_before_joining_rejected(
    service: EmploymentService,
) -> None:
    employment = _employment(joining_date=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment

    with pytest.raises(InvalidLastWorkingDayError):
        await service.terminate_employment(
            employment.company_id,
            employment.employee_id,
            employment.id,
            EmploymentTerminate(last_working_day=date(2027, 1, 1)),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_employment.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminate_employment_stale_version_conflict(service: EmploymentService) -> None:
    employment = _employment(joining_date=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._repo.update_employment.return_value = None

    with pytest.raises(StaleResourceError):
        await service.terminate_employment(
            employment.company_id,
            employment.employee_id,
            employment.id,
            EmploymentTerminate(last_working_day=date(2030, 9, 30)),
            expected_version=1,
            actor_user_id=uuid4(),
        )


# --- Termination closes assignment/compensation (E-03 -> E-04/E-06 lifecycle fix) --------
#
# `docs/modules/employee/22_TERMINATION_ASSIGNMENT_COMPENSATION_PLAN.md` §7/§21: reuses
# `EmployeeAssignmentRepository.close_assignment`/`EmployeeCompensationRepository.
# close_compensation` verbatim, server-read `version` (never client-supplied), inside the same
# transaction as the `employment` update.


@pytest.mark.asyncio
async def test_terminate_employment_closes_current_assignment_and_compensation(
    service: EmploymentService,
) -> None:
    employment = _employment(joining_date=date(2027, 6, 1))
    assignment = _assignment(
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        effective_from=date(2027, 6, 1),
        version=3,
    )
    compensation = _compensation(
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        effective_from=date(2027, 6, 1),
        version=5,
    )
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._assignment_repo.get_current_assignment.return_value = assignment
    service._compensation_repo.get_current_compensation.return_value = compensation
    service._assignment_repo.close_assignment.return_value = _assignment(
        id=assignment.id,
        company_id=assignment.company_id,
        employee_id=assignment.employee_id,
        effective_from=assignment.effective_from,
        effective_to=date(2030, 9, 30),
        version=4,
    )
    service._compensation_repo.close_compensation.return_value = _compensation(
        id=compensation.id,
        company_id=compensation.company_id,
        employee_id=compensation.employee_id,
        effective_from=compensation.effective_from,
        effective_to=date(2030, 9, 30),
        version=6,
    )
    service._repo.update_employment.return_value = _employment(
        id=employment.id,
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        status="TERMINATED",
        last_working_day=date(2030, 9, 30),
        version=2,
    )

    result = await service.terminate_employment(
        employment.company_id,
        employment.employee_id,
        employment.id,
        EmploymentTerminate(last_working_day=date(2030, 9, 30)),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.status == "TERMINATED"
    service._assignment_repo.close_assignment.assert_awaited_once()
    assignment_close_kwargs = service._assignment_repo.close_assignment.call_args.kwargs
    assert assignment_close_kwargs["assignment_id"] == assignment.id
    assert assignment_close_kwargs["effective_to"] == date(2030, 9, 30)
    # Server-read version, not client-supplied — the terminate endpoint never accepts an
    # assignment/compensation `If-Match` at all (plan §11/§15).
    assert assignment_close_kwargs["expected_version"] == 3

    service._compensation_repo.close_compensation.assert_awaited_once()
    compensation_close_kwargs = service._compensation_repo.close_compensation.call_args.kwargs
    assert compensation_close_kwargs["compensation_id"] == compensation.id
    assert compensation_close_kwargs["effective_to"] == date(2030, 9, 30)
    assert compensation_close_kwargs["expected_version"] == 5

    actions = [call.kwargs["action"] for call in service._audit.record.call_args_list]
    assert actions == ["ASSIGNMENT_CHANGED", "COMPENSATION_REVISED", "EMPLOYMENT_TERMINATED"]

    assignment_audit_call = service._audit.record.call_args_list[0]
    assert assignment_audit_call.kwargs["entity_type"] == "employee_assignment"
    assert assignment_audit_call.kwargs["entity_id"] == assignment.id
    assert assignment_audit_call.kwargs["before"]["effective_to"] is None
    assert assignment_audit_call.kwargs["after"]["effective_to"] == "2030-09-30"

    compensation_audit_call = service._audit.record.call_args_list[1]
    assert compensation_audit_call.kwargs["entity_type"] == "employee_compensation"
    assert compensation_audit_call.kwargs["entity_id"] == compensation.id
    assert compensation_audit_call.kwargs["before"]["effective_to"] is None
    assert compensation_audit_call.kwargs["after"]["effective_to"] == "2030-09-30"


@pytest.mark.asyncio
async def test_terminate_employment_no_current_assignment_succeeds(
    service: EmploymentService,
) -> None:
    employment = _employment(joining_date=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._assignment_repo.get_current_assignment.return_value = None
    service._repo.update_employment.return_value = _employment(
        id=employment.id,
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        status="TERMINATED",
        last_working_day=date(2030, 9, 30),
        version=2,
    )

    result = await service.terminate_employment(
        employment.company_id,
        employment.employee_id,
        employment.id,
        EmploymentTerminate(last_working_day=date(2030, 9, 30)),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.status == "TERMINATED"
    service._assignment_repo.close_assignment.assert_not_awaited()
    actions = [call.kwargs["action"] for call in service._audit.record.call_args_list]
    assert "ASSIGNMENT_CHANGED" not in actions
    assert actions == ["EMPLOYMENT_TERMINATED"]


@pytest.mark.asyncio
async def test_terminate_employment_no_current_compensation_succeeds(
    service: EmploymentService,
) -> None:
    employment = _employment(joining_date=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._compensation_repo.get_current_compensation.return_value = None
    service._repo.update_employment.return_value = _employment(
        id=employment.id,
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        status="TERMINATED",
        last_working_day=date(2030, 9, 30),
        version=2,
    )

    result = await service.terminate_employment(
        employment.company_id,
        employment.employee_id,
        employment.id,
        EmploymentTerminate(last_working_day=date(2030, 9, 30)),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.status == "TERMINATED"
    service._compensation_repo.close_compensation.assert_not_awaited()
    actions = [call.kwargs["action"] for call in service._audit.record.call_args_list]
    assert "COMPENSATION_REVISED" not in actions
    assert actions == ["EMPLOYMENT_TERMINATED"]


@pytest.mark.asyncio
async def test_terminate_employment_future_dated_assignment_left_open(
    service: EmploymentService,
) -> None:
    """OD-1 (`22_TERMINATION_ASSIGNMENT_COMPENSATION_PLAN.md` §8/§19) — the current assignment
    row's `effective_from` is after the new `last_working_day` (a future transfer already
    entered before an unexpected early exit). Closing it would produce an invalid
    `effective_to < effective_from` range, and no source document resolves what else should
    happen — this deliberately leaves the row open rather than inventing a rule; termination
    itself still succeeds."""
    employment = _employment(joining_date=date(2027, 6, 1))
    future_assignment = _assignment(
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        effective_from=date(2031, 1, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._assignment_repo.get_current_assignment.return_value = future_assignment
    service._repo.update_employment.return_value = _employment(
        id=employment.id,
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        status="TERMINATED",
        last_working_day=date(2030, 9, 30),
        version=2,
    )

    result = await service.terminate_employment(
        employment.company_id,
        employment.employee_id,
        employment.id,
        EmploymentTerminate(last_working_day=date(2030, 9, 30)),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.status == "TERMINATED"
    service._assignment_repo.close_assignment.assert_not_awaited()
    actions = [call.kwargs["action"] for call in service._audit.record.call_args_list]
    assert "ASSIGNMENT_CHANGED" not in actions


@pytest.mark.asyncio
async def test_terminate_employment_future_dated_compensation_left_open(
    service: EmploymentService,
) -> None:
    """Mirrors `test_terminate_employment_future_dated_assignment_left_open` for
    `employee_compensation` — same OD-1 rule, same unresolved-by-design behavior."""
    employment = _employment(joining_date=date(2027, 6, 1))
    future_compensation = _compensation(
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        effective_from=date(2031, 1, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._compensation_repo.get_current_compensation.return_value = future_compensation
    service._repo.update_employment.return_value = _employment(
        id=employment.id,
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        status="TERMINATED",
        last_working_day=date(2030, 9, 30),
        version=2,
    )

    result = await service.terminate_employment(
        employment.company_id,
        employment.employee_id,
        employment.id,
        EmploymentTerminate(last_working_day=date(2030, 9, 30)),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.status == "TERMINATED"
    service._compensation_repo.close_compensation.assert_not_awaited()
    actions = [call.kwargs["action"] for call in service._audit.record.call_args_list]
    assert "COMPENSATION_REVISED" not in actions


@pytest.mark.asyncio
async def test_terminate_employment_assignment_stale_version_raises(
    service: EmploymentService,
) -> None:
    employment = _employment(joining_date=date(2027, 6, 1))
    assignment = _assignment(
        company_id=employment.company_id, employee_id=employment.employee_id, version=3
    )
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._assignment_repo.get_current_assignment.return_value = assignment
    service._assignment_repo.close_assignment.return_value = None
    service._assignment_repo.get_assignment.return_value = assignment

    with pytest.raises(StaleResourceError):
        await service.terminate_employment(
            employment.company_id,
            employment.employee_id,
            employment.id,
            EmploymentTerminate(last_working_day=date(2030, 9, 30)),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    # Nothing later in the method runs — no compensation close attempted, `employment` itself
    # never updated. The request-scoped session is never committed on this exception path
    # (`core/db/session.py` `get_session`), so this is what makes the whole operation
    # transactional in practice; verified end-to-end against a real DB in
    # `test_employment.py::test_terminate_employment_rolls_back_on_compensation_close_failure`.
    service._compensation_repo.close_compensation.assert_not_awaited()
    service._repo.update_employment.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminate_employment_compensation_stale_version_raises_after_assignment_closed(
    service: EmploymentService,
) -> None:
    """The dangerous partial-write ordering: assignment closes successfully, *then*
    compensation's close loses a concurrency race. `update_employment` must never be reached —
    the exception must propagate uncaught so the request-scoped session rolls back everything,
    including the assignment close that already "succeeded" in this transaction."""
    employment = _employment(joining_date=date(2027, 6, 1))
    assignment = _assignment(
        company_id=employment.company_id, employee_id=employment.employee_id, version=3
    )
    compensation = _compensation(
        company_id=employment.company_id, employee_id=employment.employee_id, version=5
    )
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_employment.return_value = employment
    service._assignment_repo.get_current_assignment.return_value = assignment
    service._assignment_repo.close_assignment.return_value = _assignment(
        id=assignment.id,
        company_id=assignment.company_id,
        employee_id=assignment.employee_id,
        effective_to=date(2030, 9, 30),
        version=4,
    )
    service._compensation_repo.get_current_compensation.return_value = compensation
    service._compensation_repo.close_compensation.return_value = None
    service._compensation_repo.get_compensation.return_value = compensation

    with pytest.raises(StaleResourceError):
        await service.terminate_employment(
            employment.company_id,
            employment.employee_id,
            employment.id,
            EmploymentTerminate(last_working_day=date(2030, 9, 30)),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._assignment_repo.close_assignment.assert_awaited_once()
    service._repo.update_employment.assert_not_awaited()
    # Only the assignment's own audit record was ever queued — `COMPENSATION_REVISED` and
    # `EMPLOYMENT_TERMINATED` never fire on this path.
    actions = [call.kwargs["action"] for call in service._audit.record.call_args_list]
    assert actions == ["ASSIGNMENT_CHANGED"]
