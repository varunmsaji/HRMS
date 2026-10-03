"""Unit tests for organisation service Department methods."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.exceptions import (
    DepartmentCycleDetectedError,
    DepartmentMaxDepthExceededError,
    InvalidBranchError,
    InvalidParentDepartmentError,
    StaleResourceError,
)
from hrms.modules.organisation.models import Branch, Department
from hrms.modules.organisation.schemas import DepartmentCreate, DepartmentUpdate
from hrms.modules.organisation.service import OrganisationService


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


def _branch(**overrides: object) -> Branch:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "legal_entity_id": uuid4(),
        "name": "HQ",
        "code": None,
        "address_line1": None,
        "address_line2": None,
        "city": None,
        "state_code": None,
        "pincode": None,
        "timezone": None,
        "latitude": None,
        "longitude": None,
        "geofence_radius_m": None,
        "is_active": True,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Branch(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> OrganisationService:
    session = MagicMock()
    svc = OrganisationService(session)
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    svc._assert_master_not_in_use = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_create_department_records_audit(service: OrganisationService) -> None:
    company_id = uuid4()
    department = _department(company_id=company_id)
    service._repo.insert_department.return_value = department

    result = await service.create_department(
        company_id,
        DepartmentCreate(name="Engineering"),
        actor_user_id=uuid4(),
    )

    assert result.name == "Engineering"
    assert result.is_active is True
    service._audit.record.assert_awaited_once()
    assert service._audit.record.call_args.kwargs["action"] == "DEPARTMENT_CREATED"
    service._repo.get_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_department_validates_branch_ownership(service: OrganisationService) -> None:
    company_id = uuid4()
    branch = _branch(company_id=company_id)
    service._repo.get_branch.return_value = branch
    service._repo.insert_department.return_value = _department(
        company_id=company_id, branch_id=branch.id
    )

    result = await service.create_department(
        company_id,
        DepartmentCreate(name="Engineering", branch_id=branch.id),
        actor_user_id=uuid4(),
    )

    assert result.branch_id == branch.id
    service._repo.get_branch.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_department_invalid_branch_rejected(service: OrganisationService) -> None:
    service._repo.get_branch.return_value = None

    with pytest.raises(InvalidBranchError):
        await service.create_department(
            uuid4(),
            DepartmentCreate(name="Engineering", branch_id=uuid4()),
            actor_user_id=uuid4(),
        )
    service._repo.insert_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_department_invalid_parent_rejected(service: OrganisationService) -> None:
    service._repo.get_department.return_value = None

    with pytest.raises(InvalidParentDepartmentError):
        await service.create_department(
            uuid4(),
            DepartmentCreate(name="Sub-team", parent_id=uuid4()),
            actor_user_id=uuid4(),
        )
    service._repo.insert_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_department_max_depth_exceeded_rejected(service: OrganisationService) -> None:
    company_id = uuid4()
    parent = _department(company_id=company_id)
    service._repo.get_department.return_value = parent
    service._repo.get_department_ancestor_chain.return_value = [
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    ]

    with pytest.raises(DepartmentMaxDepthExceededError):
        await service.create_department(
            company_id,
            DepartmentCreate(name="Too deep", parent_id=parent.id),
            actor_user_id=uuid4(),
        )
    service._repo.insert_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_department_self_parent_rejected_as_cycle(
    service: OrganisationService,
) -> None:
    department = _department()
    service._repo.get_department.return_value = department

    with pytest.raises(DepartmentCycleDetectedError):
        await service.update_department(
            department.company_id,
            department.id,
            DepartmentUpdate(parent_id=department.id),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_department_ancestor_cycle_rejected(service: OrganisationService) -> None:
    department = _department()
    candidate_parent = _department(company_id=department.company_id)

    async def get_department_side_effect(*_args: object, **kwargs: object) -> Department | None:
        department_id = kwargs["department_id"]
        if department_id == department.id:
            return department
        if department_id == candidate_parent.id:
            return candidate_parent
        return None

    service._repo.get_department.side_effect = get_department_side_effect
    # department is an ancestor of candidate_parent -> making candidate_parent the new
    # parent of department would create a cycle.
    service._repo.get_department_ancestor_chain.return_value = [candidate_parent.id, department.id]

    with pytest.raises(DepartmentCycleDetectedError):
        await service.update_department(
            department.company_id,
            department.id,
            DepartmentUpdate(parent_id=candidate_parent.id),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_department_not_found(service: OrganisationService) -> None:
    service._repo.get_department.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_department(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_update_department_not_found(service: OrganisationService) -> None:
    service._repo.get_department.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_department(
            uuid4(),
            uuid4(),
            DepartmentUpdate(name="New Name"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_deactivate_department_not_blocked_by_anything(
    service: OrganisationService,
) -> None:
    """No documented dependency-blocking rule applies to Department this slice — see
    docs/modules/department/00_DEPARTMENT_AUDIT.md §5.3."""
    department = _department(is_active=True)
    service._repo.get_department.return_value = department
    service._repo.update_department.return_value = _department(
        id=department.id, company_id=department.company_id, is_active=False, version=2
    )

    result = await service.update_department(
        department.company_id,
        department.id,
        DepartmentUpdate(is_active=False),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is False
    assert service._audit.record.call_args.kwargs["action"] == "DEPARTMENT_DEACTIVATED"


@pytest.mark.asyncio
async def test_reactivate_records_distinct_audit_action(service: OrganisationService) -> None:
    department = _department(is_active=False)
    service._repo.get_department.return_value = department
    service._repo.update_department.return_value = _department(
        id=department.id, company_id=department.company_id, is_active=True, version=2
    )

    result = await service.update_department(
        department.company_id,
        department.id,
        DepartmentUpdate(is_active=True),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is True
    assert service._audit.record.call_args.kwargs["action"] == "DEPARTMENT_REACTIVATED"


@pytest.mark.asyncio
async def test_update_department_stale_version_conflict(service: OrganisationService) -> None:
    department = _department()
    service._repo.get_department.return_value = department
    service._repo.update_department.return_value = None

    with pytest.raises(StaleResourceError):
        await service.update_department(
            department.company_id,
            department.id,
            DepartmentUpdate(name="Renamed"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_department_noop_when_patch_empty(service: OrganisationService) -> None:
    department = _department()
    service._repo.get_department.return_value = department

    result = await service.update_department(
        department.company_id,
        department.id,
        DepartmentUpdate(),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.name == department.name
    service._repo.update_department.assert_not_awaited()
    service._audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_department_blocked_while_employees_assigned(
    service: OrganisationService,
) -> None:
    from hrms.modules.organisation.exceptions import MasterDataInUseError

    service._assert_master_not_in_use = AsyncMock(
        side_effect=MasterDataInUseError(kind="department", active_employee_count=2)
    )
    department = _department(is_active=True)
    service._repo.get_department.return_value = department

    with pytest.raises(MasterDataInUseError) as exc_info:
        await service.update_department(
            department.company_id,
            department.id,
            DepartmentUpdate(is_active=False),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    assert exc_info.value.code == "MASTER_DATA_HAS_ACTIVE_EMPLOYEES"
    service._repo.update_department.assert_not_called()
