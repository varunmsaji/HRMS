"""Unit tests for `EmployeeCompensationService` — E-06 (employee compensation)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from hrms.core.errors.base import NotFoundError
from hrms.modules.employee.exceptions import (
    CompensationCurrencyMismatchError,
    CompensationDatesOverlapError,
    CompensationVersionRequiredError,
    InvalidEffectiveFromError,
    NoActiveEmploymentError,
    StaleResourceError,
)
from hrms.modules.employee.models import Employee, EmployeeCompensation, Employment
from hrms.modules.employee.schemas import CompensationCreate
from hrms.modules.employee.service import EmployeeCompensationService


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
def service() -> EmployeeCompensationService:
    session = MagicMock()
    svc = EmployeeCompensationService(session)
    svc._repo = AsyncMock()
    svc._employee_repo = AsyncMock()
    svc._employment_repo = AsyncMock()
    svc._audit = AsyncMock()
    svc._company_currency = AsyncMock(return_value="INR")
    return svc


# --- Create: first compensation row (no current row) ---------------------------------------


@pytest.mark.asyncio
async def test_create_first_compensation_success(service: EmployeeCompensationService) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_compensation.return_value = None
    service._repo.insert_compensation.return_value = _compensation(
        company_id=company_id, employee_id=employee_id
    )

    result = await service.create_compensation(
        company_id,
        employee_id,
        CompensationCreate(
            effective_from=date(2027, 6, 1),
            annual_ctc_minor=12_00_000_00,
            currency="INR",
            revision_type="JOINING",
            revision_reason="Initial hire",
        ),
        expected_version=None,
        actor_user_id=uuid4(),
    )

    assert result.revision_type == "JOINING"
    service._repo.close_compensation.assert_not_awaited()
    service._audit.record.assert_awaited_once()
    call = service._audit.record.call_args.kwargs
    assert call["action"] == "COMPENSATION_REVISED"
    assert call["before"] is None


@pytest.mark.asyncio
async def test_create_compensation_no_covering_employment_rejected(
    service: EmployeeCompensationService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = None

    with pytest.raises(NoActiveEmploymentError):
        await service.create_compensation(
            uuid4(),
            uuid4(),
            CompensationCreate(
                effective_from=date(2027, 6, 1),
                annual_ctc_minor=12_00_000_00,
                currency="INR",
                revision_type="JOINING",
                revision_reason="Initial hire",
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.get_current_compensation.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_compensation_unknown_employee_rejected(
    service: EmployeeCompensationService,
) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.create_compensation(
            uuid4(),
            uuid4(),
            CompensationCreate(
                effective_from=date(2027, 6, 1),
                annual_ctc_minor=12_00_000_00,
                currency="INR",
                revision_type="JOINING",
                revision_reason="Initial hire",
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._employment_repo.get_employment_as_of.assert_not_awaited()


# --- Create: revision (current row exists) --------------------------------------------------


@pytest.mark.asyncio
async def test_create_revision_closes_current_and_inserts_new(
    service: EmployeeCompensationService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()

    current = _compensation(
        company_id=company_id,
        employee_id=employee_id,
        annual_ctc_minor=12_00_000_00,
        effective_from=date(2027, 6, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_compensation.return_value = current
    service._repo.close_compensation.return_value = _compensation(
        id=current.id, effective_to=date(2028, 12, 31), version=2
    )
    service._repo.insert_compensation.return_value = _compensation(
        company_id=company_id,
        employee_id=employee_id,
        annual_ctc_minor=15_00_000_00,
        revision_type="ANNUAL",
        effective_from=date(2029, 1, 1),
    )

    result = await service.create_compensation(
        company_id,
        employee_id,
        CompensationCreate(
            effective_from=date(2029, 1, 1),
            annual_ctc_minor=15_00_000_00,
            currency="INR",
            revision_type="ANNUAL",
            revision_reason="Annual increment",
        ),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.annual_ctc_minor == 15_00_000_00
    insert_data = service._repo.insert_compensation.call_args.kwargs["data"]
    assert insert_data["annual_ctc_minor"] == 15_00_000_00
    assert insert_data["revision_type"] == "ANNUAL"
    close_kwargs = service._repo.close_compensation.call_args.kwargs
    assert close_kwargs["effective_to"] == date(2028, 12, 31)
    assert close_kwargs["expected_version"] == 1


@pytest.mark.asyncio
async def test_create_compensation_requires_if_match_when_current_exists(
    service: EmployeeCompensationService,
) -> None:
    current = _compensation(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_compensation.return_value = current

    with pytest.raises(CompensationVersionRequiredError):
        await service.create_compensation(
            uuid4(),
            uuid4(),
            CompensationCreate(
                effective_from=date(2028, 1, 1),
                annual_ctc_minor=15_00_000_00,
                currency="INR",
                revision_type="ANNUAL",
                revision_reason="Annual increment",
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.close_compensation.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_compensation_effective_from_not_after_current_rejected(
    service: EmployeeCompensationService,
) -> None:
    current = _compensation(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_compensation.return_value = current

    with pytest.raises(InvalidEffectiveFromError):
        await service.create_compensation(
            uuid4(),
            uuid4(),
            CompensationCreate(
                effective_from=date(2027, 6, 1),
                annual_ctc_minor=15_00_000_00,
                currency="INR",
                revision_type="ANNUAL",
                revision_reason="Annual increment",
            ),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_compensation_stale_version_conflict(
    service: EmployeeCompensationService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    current = _compensation(
        company_id=company_id, employee_id=employee_id, effective_from=date(2027, 6, 1)
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_compensation.return_value = current
    service._repo.close_compensation.return_value = None
    service._repo.get_compensation.return_value = current

    with pytest.raises(StaleResourceError):
        await service.create_compensation(
            company_id,
            employee_id,
            CompensationCreate(
                effective_from=date(2028, 1, 1),
                annual_ctc_minor=15_00_000_00,
                currency="INR",
                revision_type="ANNUAL",
                revision_reason="Annual increment",
            ),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.insert_compensation.assert_not_awaited()


# --- GiST exclusion constraint race backstop ------------------------------------------------


@pytest.mark.asyncio
async def test_create_compensation_overlap_race_converted_to_domain_error(
    service: EmployeeCompensationService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_compensation.return_value = None
    service._repo.insert_compensation.side_effect = IntegrityError("", {}, Exception())

    with pytest.raises(CompensationDatesOverlapError):
        await service.create_compensation(
            uuid4(),
            uuid4(),
            CompensationCreate(
                effective_from=date(2027, 6, 1),
                annual_ctc_minor=12_00_000_00,
                currency="INR",
                revision_type="JOINING",
                revision_reason="Initial hire",
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )


# --- Money / schema validation ---------------------------------------------------------------


def test_negative_annual_ctc_minor_rejected_at_schema_layer() -> None:
    with pytest.raises(ValueError):
        CompensationCreate(
            effective_from=date(2027, 6, 1),
            annual_ctc_minor=-1,
            currency="INR",
            revision_type="JOINING",
            revision_reason="Initial hire",
        )


def test_compensation_create_mass_assignment_rejected() -> None:
    with pytest.raises(ValueError):
        CompensationCreate(
            effective_from=date(2027, 6, 1),
            annual_ctc_minor=12_00_000_00,
            currency="INR",
            revision_type="JOINING",
            revision_reason="Initial hire",
            version=99,  # type: ignore[call-arg]
        )


# --- Read / list (incl. as-of) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_compensations_unknown_employee_rejected(
    service: EmployeeCompensationService,
) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.list_compensations(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_list_compensations_as_of_returns_single_match(
    service: EmployeeCompensationService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_compensation_as_of.return_value = _compensation()

    result = await service.list_compensations(uuid4(), uuid4(), as_of=date(2029, 8, 15))

    assert len(result) == 1
    service._repo.list_compensations.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_compensations_as_of_no_match_returns_empty(
    service: EmployeeCompensationService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_compensation_as_of.return_value = None

    result = await service.list_compensations(uuid4(), uuid4(), as_of=date(2031, 1, 1))

    assert result == []


@pytest.mark.asyncio
async def test_get_compensation_not_found(service: EmployeeCompensationService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_compensation.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_compensation(uuid4(), uuid4(), uuid4())


@pytest.mark.asyncio
async def test_get_compensation_as_of_does_not_require_employee_lookup(
    service: EmployeeCompensationService,
) -> None:
    """The shared cross-module contract Payroll will call — does not assert employee
    existence, mirroring `EmployeeAssignmentService.get_assignment_as_of`'s exact contract."""
    service._repo.get_compensation_as_of.return_value = None

    result = await service.get_compensation_as_of(uuid4(), uuid4(), date(2029, 8, 15))

    assert result is None
    service._employee_repo.get_employee.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_compensation_rejects_currency_other_than_company_currency(
    service: EmployeeCompensationService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_compensation.return_value = None

    with pytest.raises(CompensationCurrencyMismatchError):
        await service.create_compensation(
            company_id,
            employee_id,
            CompensationCreate(
                effective_from=date(2027, 6, 1),
                annual_ctc_minor=1_000_000,
                currency="USD",
                revision_type="JOINING",
                revision_reason="Joining",
            ),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.insert_compensation.assert_not_called()
