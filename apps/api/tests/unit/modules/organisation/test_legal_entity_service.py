"""Unit tests for organisation service Legal Entity methods."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.exceptions import (
    LegalEntityDeactivationBlockedError,
    StaleResourceError,
)
from hrms.modules.organisation.models import LegalEntity
from hrms.modules.organisation.schemas import LegalEntityUpdate
from hrms.modules.organisation.service import OrganisationService


def _entity(**overrides: object) -> LegalEntity:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "name": "Acme Technologies Pvt Ltd",
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
async def test_create_legal_entity_records_audit(service: OrganisationService) -> None:
    company_id = uuid4()
    entity = _entity(company_id=company_id)
    service._repo.insert_legal_entity.return_value = entity

    from hrms.modules.organisation.schemas import LegalEntityCreate

    result = await service.create_legal_entity(
        company_id,
        LegalEntityCreate(name="Acme Technologies Pvt Ltd"),
        actor_user_id=uuid4(),
    )

    assert result.name == "Acme Technologies Pvt Ltd"
    assert result.is_active is True
    service._audit.record.assert_awaited_once()
    assert service._audit.record.call_args.kwargs["action"] == "LEGAL_ENTITY_CREATED"


@pytest.mark.asyncio
async def test_get_legal_entity_not_found(service: OrganisationService) -> None:
    service._repo.get_legal_entity.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_legal_entity(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_update_legal_entity_not_found(service: OrganisationService) -> None:
    service._repo.get_legal_entity.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_legal_entity(
            uuid4(),
            uuid4(),
            LegalEntityUpdate(name="New Name"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_deactivate_blocked_when_active_branches_exist(
    service: OrganisationService,
) -> None:
    entity = _entity(is_active=True)
    service._repo.get_legal_entity.return_value = entity
    service._repo.count_active_branches_for_legal_entity.return_value = 2

    with pytest.raises(LegalEntityDeactivationBlockedError):
        await service.update_legal_entity(
            entity.company_id,
            entity.id,
            LegalEntityUpdate(is_active=False),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_legal_entity.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_allowed_when_no_active_branches(
    service: OrganisationService,
) -> None:
    entity = _entity(is_active=True)
    service._repo.get_legal_entity.return_value = entity
    service._repo.count_active_branches_for_legal_entity.return_value = 0
    service._repo.update_legal_entity.return_value = _entity(
        id=entity.id, company_id=entity.company_id, is_active=False, version=2
    )

    result = await service.update_legal_entity(
        entity.company_id,
        entity.id,
        LegalEntityUpdate(is_active=False),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is False
    assert service._audit.record.call_args.kwargs["action"] == "LEGAL_ENTITY_DEACTIVATED"


@pytest.mark.asyncio
async def test_reactivate_records_distinct_audit_action(
    service: OrganisationService,
) -> None:
    entity = _entity(is_active=False)
    service._repo.get_legal_entity.return_value = entity
    service._repo.update_legal_entity.return_value = _entity(
        id=entity.id, company_id=entity.company_id, is_active=True, version=2
    )

    result = await service.update_legal_entity(
        entity.company_id,
        entity.id,
        LegalEntityUpdate(is_active=True),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is True
    assert service._audit.record.call_args.kwargs["action"] == "LEGAL_ENTITY_REACTIVATED"
    service._repo.count_active_branches_for_legal_entity.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_legal_entity_stale_version_conflict(
    service: OrganisationService,
) -> None:
    entity = _entity()
    service._repo.get_legal_entity.return_value = entity
    service._repo.update_legal_entity.return_value = None

    with pytest.raises(StaleResourceError):
        await service.update_legal_entity(
            entity.company_id,
            entity.id,
            LegalEntityUpdate(name="Renamed"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_legal_entity_noop_when_patch_empty(
    service: OrganisationService,
) -> None:
    entity = _entity()
    service._repo.get_legal_entity.return_value = entity

    result = await service.update_legal_entity(
        entity.company_id,
        entity.id,
        LegalEntityUpdate(),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.name == entity.name
    service._repo.update_legal_entity.assert_not_awaited()
    service._audit.record.assert_not_awaited()
