"""Unit tests for organisation service Designation methods."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.exceptions import (
    InvalidDepartmentError,
    StaleResourceError,
)
from hrms.modules.organisation.models import Department, Designation
from hrms.modules.organisation.schemas import DesignationCreate, DesignationUpdate
from hrms.modules.organisation.service import OrganisationService


def _designation(**overrides: object) -> Designation:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "department_id": None,
        "next_designation_id": None,
        "title": "Software Engineer",
        "code": None,
        "is_active": True,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Designation(**defaults)  # type: ignore[arg-type]


def _department(**overrides: object) -> Department:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "branch_id": None,
        "parent_id": None,
        "name": "Engineering",
        "code": None,
        "head_employee_id": None,
        "is_active": True,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Department(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> OrganisationService:
    session = MagicMock()
    svc = OrganisationService(session)
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    svc._assert_master_not_in_use = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_create_designation_records_audit(service: OrganisationService) -> None:
    company_id = uuid4()
    designation = _designation(company_id=company_id)
    service._repo.insert_designation.return_value = designation

    result = await service.create_designation(
        company_id,
        DesignationCreate(title="Software Engineer"),
        actor_user_id=uuid4(),
    )

    assert result.title == "Software Engineer"
    assert result.is_active is True
    service._audit.record.assert_awaited_once()
    assert service._audit.record.call_args.kwargs["action"] == "DESIGNATION_CREATED"
    service._repo.get_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_designation_validates_department_ownership(
    service: OrganisationService,
) -> None:
    company_id = uuid4()
    department = _department(company_id=company_id)
    service._repo.get_department.return_value = department
    service._repo.insert_designation.return_value = _designation(
        company_id=company_id, department_id=department.id
    )

    result = await service.create_designation(
        company_id,
        DesignationCreate(title="Software Engineer", department_id=department.id),
        actor_user_id=uuid4(),
    )

    assert result.department_id == department.id
    service._repo.get_department.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_designation_invalid_department_rejected(
    service: OrganisationService,
) -> None:
    service._repo.get_department.return_value = None

    with pytest.raises(InvalidDepartmentError):
        await service.create_designation(
            uuid4(),
            DesignationCreate(title="Software Engineer", department_id=uuid4()),
            actor_user_id=uuid4(),
        )
    service._repo.insert_designation.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_designation_not_found(service: OrganisationService) -> None:
    service._repo.get_designation.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_designation(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_update_designation_not_found(service: OrganisationService) -> None:
    service._repo.get_designation.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_designation(
            uuid4(),
            uuid4(),
            DesignationUpdate(title="New Title"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_designation_invalid_department_rejected(
    service: OrganisationService,
) -> None:
    designation = _designation()
    service._repo.get_designation.return_value = designation
    service._repo.get_department.return_value = None

    with pytest.raises(InvalidDepartmentError):
        await service.update_designation(
            designation.company_id,
            designation.id,
            DesignationUpdate(department_id=uuid4()),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_designation.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_designation_not_blocked_by_anything(
    service: OrganisationService,
) -> None:
    """No documented dependency-blocking rule applies to Designation this slice — see
    docs/modules/designation/00_DESIGNATION_AUDIT.md §5.3/§5.4."""
    designation = _designation(is_active=True)
    service._repo.get_designation.return_value = designation
    service._repo.update_designation.return_value = _designation(
        id=designation.id, company_id=designation.company_id, is_active=False, version=2
    )

    result = await service.update_designation(
        designation.company_id,
        designation.id,
        DesignationUpdate(is_active=False),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is False
    assert service._audit.record.call_args.kwargs["action"] == "DESIGNATION_DEACTIVATED"


@pytest.mark.asyncio
async def test_reactivate_records_distinct_audit_action(service: OrganisationService) -> None:
    designation = _designation(is_active=False)
    service._repo.get_designation.return_value = designation
    service._repo.update_designation.return_value = _designation(
        id=designation.id, company_id=designation.company_id, is_active=True, version=2
    )

    result = await service.update_designation(
        designation.company_id,
        designation.id,
        DesignationUpdate(is_active=True),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is True
    assert service._audit.record.call_args.kwargs["action"] == "DESIGNATION_REACTIVATED"


@pytest.mark.asyncio
async def test_update_designation_stale_version_conflict(service: OrganisationService) -> None:
    designation = _designation()
    service._repo.get_designation.return_value = designation
    service._repo.update_designation.return_value = None

    with pytest.raises(StaleResourceError):
        await service.update_designation(
            designation.company_id,
            designation.id,
            DesignationUpdate(title="Renamed"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_designation_noop_when_patch_empty(service: OrganisationService) -> None:
    designation = _designation()
    service._repo.get_designation.return_value = designation

    result = await service.update_designation(
        designation.company_id,
        designation.id,
        DesignationUpdate(),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.title == designation.title
    service._repo.update_designation.assert_not_awaited()
    service._audit.record.assert_not_awaited()
