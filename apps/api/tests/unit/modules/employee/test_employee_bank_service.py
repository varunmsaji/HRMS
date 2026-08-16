"""Unit tests for `EmployeeBankService` — E-08 (employee banking)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from hrms.core.errors.base import NotFoundError
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.employee.exceptions import (
    BankDatesOverlapError,
    BankVersionRequiredError,
    InvalidEffectiveFromError,
    NoActiveEmploymentError,
    StaleResourceError,
)
from hrms.modules.employee.models import Employee, EmployeeBank, Employment
from hrms.modules.employee.schemas import BankCreate
from hrms.modules.employee.service import EmployeeBankService


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


def _bank(**overrides: object) -> EmployeeBank:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "employee_id": uuid4(),
        "effective_from": date(2027, 6, 1),
        "effective_to": None,
        "account_holder_name": "Meera Iyer",
        "account_number_enc": "1234567890",
        "bank_name": "State Bank",
        "ifsc": "SBIN0001234",
        "branch_name": "MG Road",
        "payment_mode": "BANK",
        "is_primary": True,
        "verification_status": "PENDING",
        "penny_drop_reference": None,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return EmployeeBank(**defaults)  # type: ignore[arg-type]


def _create_body(**overrides: object) -> BankCreate:
    defaults: dict[str, object] = {
        "effective_from": date(2027, 6, 1),
        "account_holder_name": "Meera Iyer",
        "account_number_enc": "1234567890",
        "bank_name": "State Bank",
        "ifsc": "SBIN0001234",
        "branch_name": "MG Road",
        "payment_mode": "BANK",
    }
    defaults.update(overrides)
    return BankCreate(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> EmployeeBankService:
    session = MagicMock()
    svc = EmployeeBankService(session)
    svc._repo = AsyncMock()
    svc._employee_repo = AsyncMock()
    svc._employment_repo = AsyncMock()
    svc._employee_service = AsyncMock()
    svc._audit = AsyncMock()
    return svc


# --- Create: first bank row (no current row) --------------------------------------------------


@pytest.mark.asyncio
async def test_create_first_bank_success(service: EmployeeBankService) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_bank.return_value = None
    service._repo.insert_bank.return_value = _bank(company_id=company_id, employee_id=employee_id)

    result = await service.create_bank(
        company_id,
        employee_id,
        _create_body(),
        expected_version=None,
        actor_user_id=uuid4(),
    )

    assert result.bank_name == "State Bank"
    assert result.is_primary is True
    assert result.verification_status == "PENDING"
    service._repo.close_bank.assert_not_awaited()
    service._audit.record.assert_awaited_once()
    call = service._audit.record.call_args.kwargs
    assert call["action"] == "BANK_REVISED"
    assert call["entity_type"] == "employee_bank"
    assert call["before"] is None


@pytest.mark.asyncio
async def test_create_first_bank_system_managed_fields_not_client_controlled(
    service: EmployeeBankService,
) -> None:
    """`is_primary`/`verification_status`/`penny_drop_reference` are always system-set on
    insert, regardless of what the (schema-validated) body could ever carry — `BankCreate` has
    no fields for them at all (plan §13)."""
    company_id = uuid4()
    employee_id = uuid4()
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_bank.return_value = None
    service._repo.insert_bank.return_value = _bank(company_id=company_id, employee_id=employee_id)

    await service.create_bank(
        company_id,
        employee_id,
        _create_body(),
        expected_version=None,
        actor_user_id=uuid4(),
    )

    insert_data = service._repo.insert_bank.call_args.kwargs["data"]
    assert insert_data["is_primary"] is True
    assert insert_data["verification_status"] == "PENDING"
    assert insert_data["penny_drop_reference"] is None


@pytest.mark.asyncio
async def test_create_bank_no_covering_employment_rejected(
    service: EmployeeBankService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = None

    with pytest.raises(NoActiveEmploymentError):
        await service.create_bank(
            uuid4(),
            uuid4(),
            _create_body(),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.get_current_bank.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_bank_unknown_employee_rejected(service: EmployeeBankService) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.create_bank(
            uuid4(),
            uuid4(),
            _create_body(),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._employment_repo.get_employment_as_of.assert_not_awaited()


# --- Create: revision (current row exists) ------------------------------------------------------


@pytest.mark.asyncio
async def test_create_revision_closes_current_and_inserts_new(
    service: EmployeeBankService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()

    current = _bank(
        company_id=company_id,
        employee_id=employee_id,
        bank_name="State Bank",
        effective_from=date(2027, 6, 1),
        version=1,
    )
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_bank.return_value = current
    service._repo.close_bank.return_value = _bank(
        id=current.id, effective_to=date(2029, 5, 31), version=2
    )
    service._repo.insert_bank.return_value = _bank(
        company_id=company_id,
        employee_id=employee_id,
        bank_name="HDFC Bank",
        effective_from=date(2029, 6, 1),
    )

    result = await service.create_bank(
        company_id,
        employee_id,
        _create_body(effective_from=date(2029, 6, 1), bank_name="HDFC Bank"),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.bank_name == "HDFC Bank"
    insert_data = service._repo.insert_bank.call_args.kwargs["data"]
    assert insert_data["bank_name"] == "HDFC Bank"
    close_kwargs = service._repo.close_bank.call_args.kwargs
    assert close_kwargs["effective_to"] == date(2029, 5, 31)
    assert close_kwargs["expected_version"] == 1


@pytest.mark.asyncio
async def test_create_bank_requires_if_match_when_current_exists(
    service: EmployeeBankService,
) -> None:
    current = _bank(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_bank.return_value = current

    with pytest.raises(BankVersionRequiredError):
        await service.create_bank(
            uuid4(),
            uuid4(),
            _create_body(effective_from=date(2028, 1, 1)),
            expected_version=None,
            actor_user_id=uuid4(),
        )
    service._repo.close_bank.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_bank_effective_from_not_after_current_rejected(
    service: EmployeeBankService,
) -> None:
    current = _bank(effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_bank.return_value = current

    with pytest.raises(InvalidEffectiveFromError):
        await service.create_bank(
            uuid4(),
            uuid4(),
            _create_body(effective_from=date(2027, 6, 1)),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_bank_stale_version_conflict(service: EmployeeBankService) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    current = _bank(company_id=company_id, employee_id=employee_id, effective_from=date(2027, 6, 1))
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._employment_repo.get_employment_as_of.return_value = _employment(
        company_id=company_id, employee_id=employee_id
    )
    service._repo.get_current_bank.return_value = current
    service._repo.close_bank.return_value = None
    service._repo.get_bank.return_value = current

    with pytest.raises(StaleResourceError):
        await service.create_bank(
            company_id,
            employee_id,
            _create_body(effective_from=date(2028, 1, 1)),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.insert_bank.assert_not_awaited()


# --- GiST exclusion constraint race backstop ----------------------------------------------------


@pytest.mark.asyncio
async def test_create_bank_overlap_race_converted_to_domain_error(
    service: EmployeeBankService,
) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._employment_repo.get_employment_as_of.return_value = _employment()
    service._repo.get_current_bank.return_value = None
    service._repo.insert_bank.side_effect = IntegrityError("", {}, Exception())

    with pytest.raises(BankDatesOverlapError):
        await service.create_bank(
            uuid4(),
            uuid4(),
            _create_body(),
            expected_version=None,
            actor_user_id=uuid4(),
        )


# --- Schema validation ---------------------------------------------------------------------------


def test_bank_create_mass_assignment_rejected() -> None:
    with pytest.raises(ValueError):
        BankCreate(
            effective_from=date(2027, 6, 1),
            payment_mode="BANK",
            version=99,  # type: ignore[call-arg]
        )


def test_bank_create_is_primary_not_client_settable() -> None:
    with pytest.raises(ValueError):
        BankCreate(
            effective_from=date(2027, 6, 1),
            payment_mode="BANK",
            is_primary=False,  # type: ignore[call-arg]
        )


def test_bank_create_verification_status_not_client_settable() -> None:
    with pytest.raises(ValueError):
        BankCreate(
            effective_from=date(2027, 6, 1),
            payment_mode="BANK",
            verification_status="VERIFIED",  # type: ignore[call-arg]
        )


def test_bank_create_invalid_payment_mode_rejected() -> None:
    with pytest.raises(ValueError):
        BankCreate(
            effective_from=date(2027, 6, 1),
            payment_mode="CRYPTO",  # type: ignore[arg-type]
        )


def test_bank_create_missing_payment_mode_rejected() -> None:
    with pytest.raises(ValueError):
        BankCreate(effective_from=date(2027, 6, 1))  # type: ignore[call-arg]


def test_bank_create_minimal_fields_allowed() -> None:
    """Every field except `effective_from`/`payment_mode` is optional — no source document
    requires `account_number_enc`/`ifsc`/etc. to be present on every write."""
    body = BankCreate(effective_from=date(2027, 6, 1), payment_mode="CASH")
    assert body.account_number_enc is None
    assert body.ifsc is None


# --- Read / list (incl. as-of) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_banks_unknown_employee_rejected(service: EmployeeBankService) -> None:
    service._employee_repo.get_employee.return_value = None

    with pytest.raises(NotFoundError):
        await service.list_banks(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_list_banks_as_of_returns_single_match(service: EmployeeBankService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_bank_as_of.return_value = _bank()

    result = await service.list_banks(uuid4(), uuid4(), as_of=date(2029, 8, 15))

    assert len(result) == 1
    service._repo.list_banks.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_banks_as_of_no_match_returns_empty(service: EmployeeBankService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_bank_as_of.return_value = None

    result = await service.list_banks(uuid4(), uuid4(), as_of=date(2031, 1, 1))

    assert result == []


@pytest.mark.asyncio
async def test_get_bank_not_found(service: EmployeeBankService) -> None:
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.get_bank.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_bank(uuid4(), uuid4(), uuid4())


@pytest.mark.asyncio
async def test_get_bank_as_of_does_not_require_employee_lookup(
    service: EmployeeBankService,
) -> None:
    """The shared cross-module contract Payroll will call — does not assert employee
    existence, mirroring `EmployeeStatutoryService.get_statutory_as_of`'s exact contract."""
    service._repo.get_bank_as_of.return_value = None

    result = await service.get_bank_as_of(uuid4(), uuid4(), date(2029, 8, 15))

    assert result is None
    service._employee_repo.get_employee.assert_not_awaited()


# --- Data-scope wiring (PD-1: SELF-scoped, unlike Statutory's COMPANY-only) -----------------------


@pytest.mark.asyncio
async def test_list_banks_scope_none_preserves_unscoped_behavior(
    service: EmployeeBankService,
) -> None:
    """`scope=None` (every internal caller except the `GET .../bank` route itself) must not
    resolve a visible-ID set at all — identical to this service's pre-data-scope behavior."""
    service._employee_repo.get_employee.return_value = _employee()
    service._repo.list_banks.return_value = []

    await service.list_banks(uuid4(), uuid4())

    service._employee_service.resolve_visible_employee_ids.assert_not_awaited()
    kwargs = service._employee_repo.get_employee.call_args.kwargs
    assert kwargs["visible_employee_ids"] is None


@pytest.mark.asyncio
async def test_list_banks_with_self_scope_resolves_and_passes_visible_ids(
    service: EmployeeBankService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    caller_id = uuid4()
    scope = DataScope(levels=frozenset({DataScopeLevel.SELF}))
    service._employee_service.resolve_visible_employee_ids.return_value = frozenset({caller_id})
    service._employee_repo.get_employee.return_value = None  # out of scope -> 404

    with pytest.raises(NotFoundError):
        await service.list_banks(company_id, employee_id, scope=scope, caller_employee_id=caller_id)

    service._employee_service.resolve_visible_employee_ids.assert_awaited_once_with(
        company_id, scope, caller_id
    )
    kwargs = service._employee_repo.get_employee.call_args.kwargs
    assert kwargs["visible_employee_ids"] == frozenset({caller_id})


@pytest.mark.asyncio
async def test_get_bank_with_self_scope_own_record_visible(
    service: EmployeeBankService,
) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    caller_id = employee_id
    scope = DataScope(levels=frozenset({DataScopeLevel.SELF}))
    service._employee_service.resolve_visible_employee_ids.return_value = frozenset({caller_id})
    service._employee_repo.get_employee.return_value = _employee(
        id=employee_id, company_id=company_id
    )
    service._repo.get_bank.return_value = _bank(company_id=company_id, employee_id=employee_id)

    result = await service.get_bank(
        company_id, employee_id, uuid4(), scope=scope, caller_employee_id=caller_id
    )

    assert result.employee_id == employee_id
