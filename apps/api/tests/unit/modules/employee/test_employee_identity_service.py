"""Unit tests for `EmployeeService.get_identity`/`update_identity` — E-02 (employee identity:
PAN/Aadhaar/UAN write path). Mirrors `test_employee_bank_service.py`'s DATA-01 encryption-boundary
tests exactly, substituting `employee.pan_number_enc`/`aadhaar_number_enc` for
`employee_bank.account_number_enc`."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.config.settings import get_settings
from hrms.core.crypto.aad import build_column_aad
from hrms.core.crypto.errors import DecryptionFailedError
from hrms.core.crypto.field import encrypt_value
from hrms.core.crypto.keys import DEV_KEY_VERSION, derive_dev_dek
from hrms.modules.employee.models import Employee
from hrms.modules.employee.schemas import EmployeeIdentityUpdate
from hrms.modules.employee.service import EmployeeService

_TEST_DEV_DEK = derive_dev_dek(get_settings().dev_encryption_key)


def _encrypted(plaintext: str, *, column: str, record_id: object) -> str:
    aad = build_column_aad(table="employee", column=column, record_id=record_id)
    return encrypt_value(plaintext, dek=_TEST_DEV_DEK, key_version=DEV_KEY_VERSION, aad=aad)


def _employee(**overrides: object) -> Employee:
    now = datetime.now(UTC)
    employee_id = overrides.get("id", uuid4())
    defaults: dict[str, object] = {
        "id": employee_id,
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


@pytest.fixture
def service() -> EmployeeService:
    session = MagicMock()
    svc = EmployeeService(session)
    svc._repo = AsyncMock()
    svc._assignment_repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_update_identity_persists_ciphertext_not_plaintext(service: EmployeeService) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    employee = _employee(id=employee_id, company_id=company_id)
    service._repo.get_employee.return_value = employee
    service._repo.update_employee.side_effect = lambda _session, **kwargs: _employee(
        id=employee_id,
        company_id=company_id,
        **kwargs["values"],
        version=kwargs["expected_version"] + 1,
    )

    await service.update_identity(
        company_id,
        employee_id,
        EmployeeIdentityUpdate(pan_number="ABCDE1234F", aadhaar_number="123456789012"),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    values = service._repo.update_employee.call_args.kwargs["values"]
    assert values["pan_number_enc"] != "ABCDE1234F"
    assert values["pan_number_enc"].startswith("v1:")
    assert values["aadhaar_number_enc"] != "123456789012"
    assert values["aadhaar_number_enc"].startswith("v1:")


@pytest.mark.asyncio
async def test_update_identity_omitted_field_leaves_column_untouched(
    service: EmployeeService,
) -> None:
    """Only fields explicitly present on `EmployeeIdentityUpdate` are written — mirrors
    `build_employee_update_values`'s own contract for the general update path."""
    company_id = uuid4()
    employee_id = uuid4()
    employee = _employee(id=employee_id, company_id=company_id)
    service._repo.get_employee.return_value = employee
    service._repo.update_employee.side_effect = lambda _session, **kwargs: _employee(
        id=employee_id,
        company_id=company_id,
        **kwargs["values"],
        version=kwargs["expected_version"] + 1,
    )

    await service.update_identity(
        company_id,
        employee_id,
        EmployeeIdentityUpdate(uan_number="100200300400"),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    values = service._repo.update_employee.call_args.kwargs["values"]
    assert values == {"uan_number": "100200300400"}


@pytest.mark.asyncio
async def test_get_identity_never_returns_ciphertext_as_plaintext(service: EmployeeService) -> None:
    company_id = uuid4()
    employee_id = uuid4()
    pan_plaintext = "ABCDE1234F"
    aadhaar_plaintext = "123456789012"
    employee = _employee(
        id=employee_id,
        company_id=company_id,
        pan_number_enc=_encrypted(pan_plaintext, column="pan_number_enc", record_id=employee_id),
        aadhaar_number_enc=_encrypted(
            aadhaar_plaintext, column="aadhaar_number_enc", record_id=employee_id
        ),
    )
    service._repo.get_employee.return_value = employee

    result = await service.get_identity(company_id, employee_id)

    assert result.pan_number == pan_plaintext
    assert result.aadhaar_number == aadhaar_plaintext
    assert result.pan_number != employee.pan_number_enc
    assert result.aadhaar_number != employee.aadhaar_number_enc


@pytest.mark.asyncio
async def test_two_identity_rows_cannot_decrypt_each_others_ciphertext(
    service: EmployeeService,
) -> None:
    """Plan §2.4/§11's cross-record ciphertext-substitution scenario, same as Bank's own test —
    a PAN encrypted under employee A's AAD must not decrypt under employee B's id."""
    company_id = uuid4()
    employee_id_a = uuid4()
    employee_id_b = uuid4()
    ciphertext_for_a = _encrypted("ABCDE1234F", column="pan_number_enc", record_id=employee_id_a)

    service._repo.get_employee.return_value = _employee(
        id=employee_id_b, company_id=company_id, pan_number_enc=ciphertext_for_a
    )

    with pytest.raises(DecryptionFailedError):
        await service.get_identity(company_id, employee_id_b)
