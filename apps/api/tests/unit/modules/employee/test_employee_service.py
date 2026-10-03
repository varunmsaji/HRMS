"""Unit tests for `EmployeeService` — E-01 (identity foundation) only."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from hrms.core.errors.base import NotFoundError
from hrms.modules.employee.exceptions import EmployeeSeatLimitExceededError, StaleResourceError
from hrms.modules.employee.models import Employee
from hrms.modules.employee.schemas import EmployeeCreate, EmployeeUpdate
from hrms.modules.employee.service import EmployeeService


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
        "father_or_husband_name": None,
        "personal_email": None,
        "personal_mobile": None,
        "present_address_line1": None,
        "present_address_line2": None,
        "present_city": None,
        "present_state_code": None,
        "present_pincode": None,
        "present_country_code": None,
        "permanent_address_line1": None,
        "permanent_address_line2": None,
        "permanent_city": None,
        "permanent_state_code": None,
        "permanent_pincode": None,
        "permanent_country_code": None,
        "permanent_same_as_present": True,
        "emergency_contact_name": None,
        "emergency_contact_relationship": None,
        "emergency_contact_phone": None,
        "photo_url": None,
        "pan_number_enc": None,
        "aadhaar_number_enc": None,
        "uan_number": None,
        "status": "PRE_JOINING",
        "custom_fields": None,
        "is_active": True,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Employee(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> EmployeeService:
    session = MagicMock()
    svc = EmployeeService(session)
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


def _mock_unlimited_seats() -> AsyncMock:
    """Patches `OrganisationService` (imported lazily inside `_check_seat_limit`) so unit
    tests never touch a real DB/subscription — `seat_limit=None` means unlimited, matching
    `seed/plan_catalogue.py`'s own convention for the ENTERPRISE plan."""
    org_service = AsyncMock()
    org_service.get_subscription_summary = AsyncMock(return_value=MagicMock(seat_limit=None))
    return org_service


@pytest.mark.asyncio
async def test_create_employee_records_audit(service: EmployeeService) -> None:
    company_id = uuid4()
    employee = _employee(company_id=company_id)
    service._repo.allocate_employee_code.return_value = "EMP-0001"
    service._repo.insert_employee.return_value = employee

    with patch(
        "hrms.modules.organisation.service.OrganisationService",
        return_value=_mock_unlimited_seats(),
    ):
        result = await service.create_employee(
            company_id,
            EmployeeCreate(first_name="Asha", last_name="Verma"),
            actor_user_id=uuid4(),
        )

    assert result.first_name == "Asha"
    assert result.employee_code == "EMP-0001"
    assert result.status == "PRE_JOINING"
    assert result.is_active is True
    service._repo.allocate_employee_code.assert_awaited_once()
    service._audit.record.assert_awaited_once()
    assert service._audit.record.call_args.kwargs["action"] == "EMPLOYEE_CREATED"


@pytest.mark.asyncio
async def test_create_employee_seat_limit_exceeded_rejected(service: EmployeeService) -> None:
    company_id = uuid4()
    org_service = AsyncMock()
    org_service.get_subscription_summary = AsyncMock(return_value=MagicMock(seat_limit=5))
    service._repo.count_active_employees.return_value = 5

    with patch("hrms.modules.organisation.service.OrganisationService", return_value=org_service):
        with pytest.raises(EmployeeSeatLimitExceededError):
            await service.create_employee(
                company_id,
                EmployeeCreate(first_name="Asha"),
                actor_user_id=uuid4(),
            )
    service._repo.insert_employee.assert_not_awaited()
    service._repo.allocate_employee_code.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_employee_under_seat_limit_allowed(service: EmployeeService) -> None:
    company_id = uuid4()
    org_service = AsyncMock()
    org_service.get_subscription_summary = AsyncMock(return_value=MagicMock(seat_limit=5))
    service._repo.count_active_employees.return_value = 4
    service._repo.allocate_employee_code.return_value = "EMP-0005"
    service._repo.insert_employee.return_value = _employee(
        company_id=company_id, employee_code="EMP-0005"
    )

    with patch("hrms.modules.organisation.service.OrganisationService", return_value=org_service):
        result = await service.create_employee(
            company_id, EmployeeCreate(first_name="Asha"), actor_user_id=uuid4()
        )

    assert result.employee_code == "EMP-0005"


@pytest.mark.asyncio
async def test_create_employee_no_subscription_fails_open(service: EmployeeService) -> None:
    """No subscription resolvable → the seat check is skipped rather than blocking creation
    (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §2.4) — a data-integrity anomaly unrelated to seats
    should not brick employee creation for that company."""
    company_id = uuid4()
    org_service = AsyncMock()
    org_service.get_subscription_summary = AsyncMock(
        side_effect=NotFoundError("Resource not found")
    )
    service._repo.allocate_employee_code.return_value = "EMP-0001"
    service._repo.insert_employee.return_value = _employee(company_id=company_id)

    with patch("hrms.modules.organisation.service.OrganisationService", return_value=org_service):
        result = await service.create_employee(
            company_id, EmployeeCreate(first_name="Asha"), actor_user_id=uuid4()
        )

    assert result.first_name == "Asha"
    service._repo.count_active_employees.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_employee_not_found(service: EmployeeService) -> None:
    service._repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_employee(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_update_employee_not_found(service: EmployeeService) -> None:
    service._repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_employee(
            uuid4(),
            uuid4(),
            EmployeeUpdate(last_name="New"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_employee_noop_when_patch_empty(service: EmployeeService) -> None:
    employee = _employee()
    service._repo.get_employee.return_value = employee

    result = await service.update_employee(
        employee.company_id,
        employee.id,
        EmployeeUpdate(),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.last_name == employee.last_name
    service._repo.update_employee.assert_not_awaited()
    service._audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_employee_stale_version_conflict(service: EmployeeService) -> None:
    employee = _employee()
    service._repo.get_employee.return_value = employee
    service._repo.update_employee.return_value = None

    with pytest.raises(StaleResourceError):
        await service.update_employee(
            employee.company_id,
            employee.id,
            EmployeeUpdate(last_name="Renamed"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_deactivate_employee_records_distinct_audit_action(
    service: EmployeeService,
) -> None:
    employee = _employee(is_active=True)
    service._repo.get_employee.return_value = employee
    service._repo.update_employee.return_value = _employee(
        id=employee.id, company_id=employee.company_id, is_active=False, version=2
    )

    result = await service.update_employee(
        employee.company_id,
        employee.id,
        EmployeeUpdate(is_active=False),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is False
    assert service._audit.record.call_args.kwargs["action"] == "EMPLOYEE_DEACTIVATED"


@pytest.mark.asyncio
async def test_reactivate_employee_records_distinct_audit_action(
    service: EmployeeService,
) -> None:
    employee = _employee(is_active=False)
    service._repo.get_employee.return_value = employee
    service._repo.update_employee.return_value = _employee(
        id=employee.id, company_id=employee.company_id, is_active=True, version=2
    )

    # Reactivation takes a seat again, so it consults the plan limit like a create does.
    with patch(
        "hrms.modules.organisation.service.OrganisationService",
        return_value=_mock_unlimited_seats(),
    ):
        result = await service.update_employee(
            employee.company_id,
            employee.id,
            EmployeeUpdate(is_active=True),
            expected_version=1,
            actor_user_id=uuid4(),
        )

    assert result.is_active is True
    assert service._audit.record.call_args.kwargs["action"] == "EMPLOYEE_REACTIVATED"


@pytest.mark.asyncio
async def test_reactivate_employee_is_refused_when_the_seat_limit_is_full(
    service: EmployeeService,
) -> None:
    from hrms.modules.employee.exceptions import EmployeeSeatLimitExceededError

    employee = _employee(is_active=False)
    service._repo.get_employee.return_value = employee
    service._repo.count_active_employees.return_value = 5
    org_service = AsyncMock()
    org_service.get_subscription_summary = AsyncMock(return_value=MagicMock(seat_limit=5))

    with (
        patch("hrms.modules.organisation.service.OrganisationService", return_value=org_service),
        pytest.raises(EmployeeSeatLimitExceededError),
    ):
        await service.update_employee(
            employee.company_id,
            employee.id,
            EmployeeUpdate(is_active=True),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_employee.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_employee_wraps_update(service: EmployeeService) -> None:
    employee = _employee(is_active=True)
    service._repo.get_employee.return_value = employee
    service._repo.update_employee.return_value = _employee(
        id=employee.id, company_id=employee.company_id, is_active=False, version=2
    )

    result = await service.deactivate_employee(
        employee.company_id, employee.id, expected_version=1, actor_user_id=uuid4()
    )

    assert result.is_active is False
