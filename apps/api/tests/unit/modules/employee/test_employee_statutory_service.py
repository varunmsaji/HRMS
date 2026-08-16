"""Unit tests for `EmployeeStatutoryService` — E-07 (employee statutory)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from hrms.core.errors.base import NotFoundError
from hrms.modules.employee.exceptions import (
    InvalidEffectiveFromError,
    NoActiveEmploymentError,
    StaleResourceError,
    StatutoryDatesOverlapError,
    StatutoryVersionRequiredError,
    TaxRegimeSwitchNotAllowedError,
)
from hrms.modules.employee.models import Employee, EmployeeStatutory, Employment
from hrms.modules.employee.schemas import StatutoryCreate
from hrms.modules.employee.service import EmployeeStatutoryService


def _employee(**overrides: object) -> Employee:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "user_id": None,
        "employee_code": "EMP-0001",
        "first_name": "Meera",
        "middle_name": None,
        "last_name": "Iyer",
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


def _statutory(**overrides: object) -> EmployeeStatutory:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "employee_id": uuid4(),
        "effective_from": date(2027, 6, 1),
        "effective_to": None,
        "is_pf_applicable": True,
        "pf_number": "PF1234567890",
        "pf_wage_ceiling_opt_out": False,
        "vpf_amount": None,
        "vpf_percentage": None,
        "is_esi_applicable": False,
        "esi_ip_number": None,
        "pt_state_code": None,
        "is_lwf_applicable": True,
        "tax_regime": "NEW",
        "is_director": False,
        "is_international_worker": False,
        "revision_reason": "Initial statutory profile",
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return EmployeeStatutory(**defaults)  # type: ignore[arg-type]


def _create_body(**overrides: object) -> StatutoryCreate:
    defaults: dict[str, object] = {
        "effective_from": date(2027, 6, 1),
        "is_pf_applicable": True,
        "pf_number": "PF1234567890",
        "is_esi_applicable": False,
        "is_lwf_applicable": True,
        "tax_regime": "NEW",
        "revision_reason": "Initial statutory profile",
    }
    defaults.update(overrides)
    return StatutoryCreate(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> EmployeeStatutoryService:
    session = MagicMock()
    svc = EmployeeStatutoryService(session)
    svc._repo = AsyncMock()
    svc._employee_repo = AsyncMock()
    svc._employment_repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


# --- Create: first statutory row (no current row) -------------------------------------------


@pytest.mark.asyncio
async def test_create_first_statutory_success(service: EmployeeStatutoryService) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_statutory.return_value = None
    service._repo.insert_statutory.return_value = _statutory(
        company_id=company_id, employee_id=employee_id
    )

    result = await service.create_statutory(
        company_id,
        employee_id,
        _create_body(),
        expected_version=None,
        actor_user_id=uuid4(),
    )

    assert result.tax_regime == "NEW"
    service._repo.close_statutory.assert_not_awaited()
    service._audit.record.assert_awaited_once()
    call = service._audit.record.call_args.kwargs
    assert call["action"] == "STATUTORY_REVISED"
    assert call["before"] is None


@pytest.mark.asyncio
async def test_create_statutory_no_covering_employment_rejected(
    service: EmployeeStatutoryService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = None

    with pytest.raises(NoActiveEmploymentError):
        await service.create_statutory(
            uuid4(),
            uuid4(),
            _create_body(),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.get_current_statutory.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_statutory_unknown_employee_rejected(
    service: EmployeeStatutoryService,
) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.create_statutory(
            uuid4(),
            uuid4(),
            _create_body(),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._employment_repo.get_employment_as_of.assert_not_awaited()


# --- Create: revision (current row exists) ---------------------------------------------------


@pytest.mark.asyncio
async def test_create_revision_closes_current_and_inserts_new(
    service: EmployeeStatutoryService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()

    current = _statutory(
        company_id=company_id,
        employee_id=employee_id,
        tax_regime="NEW",
        effective_from=date(2027, 6, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_statutory.return_value = current
    service._repo.close_statutory.return_value = _statutory(
        id=current.id, effective_to=date(2029, 5, 31), version=2
    )
    service._repo.insert_statutory.return_value = _statutory(
        company_id=company_id,
        employee_id=employee_id,
        is_esi_applicable=True,
        esi_ip_number="ESI9876543210",
        tax_regime="NEW",
        effective_from=date(2029, 6, 1),
    )

    result = await service.create_statutory(
        company_id,
        employee_id,
        _create_body(
            effective_from=date(2029, 6, 1),
            is_esi_applicable=True,
            esi_ip_number="ESI9876543210",
            revision_reason="ESI became applicable",
        ),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_esi_applicable is True
    insert_data = service._repo.insert_statutory.call_args.kwargs["data"]
    assert insert_data["is_esi_applicable"] is True
    assert insert_data["esi_ip_number"] == "ESI9876543210"
    close_kwargs = service._repo.close_statutory.call_args.kwargs
    assert close_kwargs["effective_to"] == date(2029, 5, 31)
    assert close_kwargs["expected_version"] == 1


@pytest.mark.asyncio
async def test_create_statutory_requires_if_match_when_current_exists(
    service: EmployeeStatutoryService,
) -> None:
    current = _statutory(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_statutory.return_value = current

    with pytest.raises(StatutoryVersionRequiredError):
        await service.create_statutory(
            uuid4(),
            uuid4(),
            _create_body(effective_from=date(2028, 1, 1)),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.close_statutory.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_statutory_effective_from_not_after_current_rejected(
    service: EmployeeStatutoryService,
) -> None:
    current = _statutory(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_statutory.return_value = current

    with pytest.raises(InvalidEffectiveFromError):
        await service.create_statutory(
            uuid4(),
            uuid4(),
            _create_body(effective_from=date(2027, 6, 1)),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_statutory_stale_version_conflict(
    service: EmployeeStatutoryService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    current = _statutory(
        company_id=company_id, employee_id=employee_id, effective_from=date(2027, 6, 1)
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_statutory.return_value = current
    service._repo.close_statutory.return_value = None
    service._repo.get_statutory.return_value = current

    with pytest.raises(StaleResourceError):
        await service.create_statutory(
            company_id,
            employee_id,
            _create_body(effective_from=date(2028, 1, 1)),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.insert_statutory.assert_not_awaited()


# --- Tax-regime once-per-FY switch rule (FR-PAY-006) ------------------------------------------


@pytest.mark.asyncio
async def test_tax_regime_switch_within_same_fy_rejected(
    service: EmployeeStatutoryService,
) -> None:
    current = _statutory(tax_regime="OLD", effective_from=date(2027, 6, 1), version=1)
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_statutory.return_value = current

    with pytest.raises(TaxRegimeSwitchNotAllowedError):
        await service.create_statutory(
            uuid4(),
            uuid4(),
            _create_body(effective_from=date(2027, 12, 1), tax_regime="NEW"),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.close_statutory.assert_not_awaited()


@pytest.mark.asyncio
async def test_tax_regime_switch_across_fy_allowed(service: EmployeeStatutoryService) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    current = _statutory(
        company_id=company_id,
        employee_id=employee_id,
        tax_regime="OLD",
        effective_from=date(2027, 6, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_statutory.return_value = current
    service._repo.close_statutory.return_value = _statutory(
        id=current.id, effective_to=date(2028, 3, 31), version=2
    )
    service._repo.insert_statutory.return_value = _statutory(
        company_id=company_id,
        employee_id=employee_id,
        tax_regime="NEW",
        effective_from=date(2028, 4, 1),
    )

    result = await service.create_statutory(
        company_id,
        employee_id,
        _create_body(effective_from=date(2028, 4, 1), tax_regime="NEW"),
        expected_version=1,
        actor_user_id=uuid4(),
    )
    assert result.tax_regime == "NEW"


@pytest.mark.asyncio
async def test_revision_without_tax_regime_change_ignores_fy_rule(
    service: EmployeeStatutoryService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    current = _statutory(
        company_id=company_id,
        employee_id=employee_id,
        tax_regime="OLD",
        effective_from=date(2027, 6, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_statutory.return_value = current
    service._repo.close_statutory.return_value = _statutory(
        id=current.id, effective_to=date(2027, 11, 30), version=2
    )
    service._repo.insert_statutory.return_value = _statutory(
        company_id=company_id,
        employee_id=employee_id,
        tax_regime="OLD",
        is_esi_applicable=True,
        effective_from=date(2027, 12, 1),
    )

    result = await service.create_statutory(
        company_id,
        employee_id,
        _create_body(effective_from=date(2027, 12, 1), tax_regime="OLD", is_esi_applicable=True),
        expected_version=1,
        actor_user_id=uuid4(),
    )
    assert result.tax_regime == "OLD"
    assert result.is_esi_applicable is True


# --- GiST exclusion constraint race backstop ---------------------------------------------------


@pytest.mark.asyncio
async def test_create_statutory_overlap_race_converted_to_domain_error(
    service: EmployeeStatutoryService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_statutory.return_value = None
    service._repo.insert_statutory.side_effect = IntegrityError("", {}, Exception())

    with pytest.raises(StatutoryDatesOverlapError):
        await service.create_statutory(
            uuid4(),
            uuid4(),
            _create_body(),
            expected_version=None,
            actor_user_id=uuid4(),
        )


# --- Schema validation --------------------------------------------------------------------


def test_statutory_create_mass_assignment_rejected() -> None:
    with pytest.raises(ValueError):
        StatutoryCreate(
            effective_from=date(2027, 6, 1),
            is_pf_applicable=True,
            is_esi_applicable=False,
            is_lwf_applicable=True,
            tax_regime="NEW",
            revision_reason="Initial statutory profile",
            version=99,  # type: ignore[call-arg]
        )


def test_statutory_create_negative_vpf_amount_rejected() -> None:
    with pytest.raises(ValueError):
        StatutoryCreate(
            effective_from=date(2027, 6, 1),
            is_pf_applicable=True,
            is_esi_applicable=False,
            is_lwf_applicable=True,
            tax_regime="NEW",
            revision_reason="Initial statutory profile",
            vpf_amount=-1,
        )


def test_statutory_create_invalid_tax_regime_rejected() -> None:
    with pytest.raises(ValueError):
        StatutoryCreate(
            effective_from=date(2027, 6, 1),
            is_pf_applicable=True,
            is_esi_applicable=False,
            is_lwf_applicable=True,
            tax_regime="FLAT",  # type: ignore[arg-type]
            revision_reason="Initial statutory profile",
        )


def test_statutory_create_pf_applicable_without_pf_number_allowed() -> None:
    """Plan §17/§26 items 6-7: applicability/identifier correlation is deliberately not
    enforced — this must succeed at the schema layer."""
    body = StatutoryCreate(
        effective_from=date(2027, 6, 1),
        is_pf_applicable=True,
        is_esi_applicable=True,
        is_lwf_applicable=True,
        tax_regime="NEW",
        revision_reason="Initial statutory profile",
    )
    assert body.pf_number is None
    assert body.esi_ip_number is None


# --- Read / list (incl. as-of) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_statutories_unknown_employee_rejected(
    service: EmployeeStatutoryService,
) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.list_statutories(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_list_statutories_as_of_returns_single_match(
    service: EmployeeStatutoryService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_statutory_as_of.return_value = _statutory()

    result = await service.list_statutories(uuid4(), uuid4(), as_of=date(2029, 8, 15))

    assert len(result) == 1
    service._repo.list_statutories.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_statutories_as_of_no_match_returns_empty(
    service: EmployeeStatutoryService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_statutory_as_of.return_value = None

    result = await service.list_statutories(uuid4(), uuid4(), as_of=date(2031, 1, 1))

    assert result == []


@pytest.mark.asyncio
async def test_get_statutory_not_found(service: EmployeeStatutoryService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_statutory.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_statutory(uuid4(), uuid4(), uuid4())


@pytest.mark.asyncio
async def test_get_statutory_as_of_does_not_require_employee_lookup(
    service: EmployeeStatutoryService,
) -> None:
    """The shared cross-module contract Payroll will call — does not assert employee
    existence, mirroring `EmployeeCompensationService.get_compensation_as_of`'s exact
    contract."""
    service._repo.get_statutory_as_of.return_value = None

    result = await service.get_statutory_as_of(uuid4(), uuid4(), date(2029, 8, 15))

    assert result is None
    service._employee_repo.get_employee.assert_not_awaited()
