"""Unit tests for organisation service Branch methods."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.exceptions import (
    BranchDeactivationBlockedError,
    InvalidLegalEntityError,
    StaleResourceError,
)
from hrms.modules.organisation.models import Branch, LegalEntity
from hrms.modules.organisation.schemas import BranchCreate, BranchUpdate
from hrms.modules.organisation.service import OrganisationService


def _branch(**overrides: object) -> Branch:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "legal_entity_id": uuid4(),
        "name": "HQ Branch",
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


def _legal_entity(**overrides: object) -> LegalEntity:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "name": "Acme Pvt Ltd",
        "registered_address": None,
        "pan": None,
        "tan": None,
        "cin": None,
        "gstin": None,
        "pf_code": None,
        "esi_code": None,
        "lwf_reg": None,
        "signatory_name": None,
        "signatory_designation": None,
        "signature_image_url": None,
        "is_active": True,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return LegalEntity(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> OrganisationService:
    session = MagicMock()
    svc = OrganisationService(session)
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_create_branch_records_audit(service: OrganisationService) -> None:
    company_id = uuid4()
    entity = _legal_entity(company_id=company_id)
    branch = _branch(company_id=company_id, legal_entity_id=entity.id)
    service._repo.get_legal_entity.return_value = entity
    service._repo.insert_branch.return_value = branch

    result = await service.create_branch(
        company_id,
        BranchCreate(legal_entity_id=entity.id, name="HQ Branch"),
        actor_user_id=uuid4(),
    )

    assert result.name == "HQ Branch"
    assert result.is_active is True
    service._audit.record.assert_awaited_once()
    assert service._audit.record.call_args.kwargs["action"] == "BRANCH_CREATED"


@pytest.mark.asyncio
async def test_create_branch_invalid_legal_entity_rejected(service: OrganisationService) -> None:
    service._repo.get_legal_entity.return_value = None

    with pytest.raises(InvalidLegalEntityError):
        await service.create_branch(
            uuid4(),
            BranchCreate(legal_entity_id=uuid4(), name="HQ Branch"),
            actor_user_id=uuid4(),
        )
    service._repo.insert_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_branch_not_found(service: OrganisationService) -> None:
    service._repo.get_branch.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_branch(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_update_branch_not_found(service: OrganisationService) -> None:
    service._repo.get_branch.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_branch(
            uuid4(),
            uuid4(),
            BranchUpdate(name="New Name"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_branch_invalid_legal_entity_rejected(service: OrganisationService) -> None:
    branch = _branch()
    service._repo.get_branch.return_value = branch
    service._repo.get_legal_entity.return_value = None

    with pytest.raises(InvalidLegalEntityError):
        await service.update_branch(
            branch.company_id,
            branch.id,
            BranchUpdate(legal_entity_id=uuid4()),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_blocked_when_active_departments_exist(
    service: OrganisationService,
) -> None:
    branch = _branch(is_active=True)
    service._repo.get_branch.return_value = branch
    service._repo.count_active_departments_for_branch.return_value = 3

    with pytest.raises(BranchDeactivationBlockedError):
        await service.update_branch(
            branch.company_id,
            branch.id,
            BranchUpdate(is_active=False),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_allowed_when_no_active_departments(
    service: OrganisationService,
) -> None:
    branch = _branch(is_active=True)
    service._repo.get_branch.return_value = branch
    service._repo.count_active_departments_for_branch.return_value = 0
    service._repo.update_branch.return_value = _branch(
        id=branch.id,
        company_id=branch.company_id,
        legal_entity_id=branch.legal_entity_id,
        is_active=False,
        version=2,
    )

    result = await service.update_branch(
        branch.company_id,
        branch.id,
        BranchUpdate(is_active=False),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is False
    assert service._audit.record.call_args.kwargs["action"] == "BRANCH_DEACTIVATED"


@pytest.mark.asyncio
async def test_reactivate_records_distinct_audit_action(service: OrganisationService) -> None:
    branch = _branch(is_active=False)
    service._repo.get_branch.return_value = branch
    service._repo.update_branch.return_value = _branch(
        id=branch.id,
        company_id=branch.company_id,
        legal_entity_id=branch.legal_entity_id,
        is_active=True,
        version=2,
    )

    result = await service.update_branch(
        branch.company_id,
        branch.id,
        BranchUpdate(is_active=True),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is True
    assert service._audit.record.call_args.kwargs["action"] == "BRANCH_REACTIVATED"
    service._repo.count_active_departments_for_branch.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_branch_stale_version_conflict(service: OrganisationService) -> None:
    branch = _branch()
    service._repo.get_branch.return_value = branch
    service._repo.update_branch.return_value = None

    with pytest.raises(StaleResourceError):
        await service.update_branch(
            branch.company_id,
            branch.id,
            BranchUpdate(name="Renamed"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_branch_noop_when_patch_empty(service: OrganisationService) -> None:
    branch = _branch()
    service._repo.get_branch.return_value = branch

    result = await service.update_branch(
        branch.company_id,
        branch.id,
        BranchUpdate(),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.name == branch.name
    service._repo.update_branch.assert_not_awaited()
    service._audit.record.assert_not_awaited()
