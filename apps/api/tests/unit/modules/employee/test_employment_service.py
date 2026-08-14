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
from hrms.modules.employee.models import Employee, Employment
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
        "status": "ACTIVE",
        "previous_employment_id": None,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Employment(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> EmploymentService:
    session = MagicMock()
    svc = EmploymentService(session)
    svc._repo = AsyncMock()
    svc._employee_repo = AsyncMock()
    svc._audit = AsyncMock()
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
