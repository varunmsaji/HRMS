"""Unit tests for organisation service profile methods."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.db.models.identity import Company
from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.exceptions import (
    CompanyWriteBlockedError,
    CurrencyLockedError,
    InvalidWorkingDaysError,
    StaleResourceError,
)
from hrms.modules.organisation.models import CompanySetupProgress
from hrms.modules.organisation.schemas import (
    CompanyProfileUpdate,
    ContactInfoSchema,
    SetupStepDefinition,
)
from hrms.modules.organisation.service import OrganisationService


def _company(**overrides: object) -> Company:
    now = datetime.now(UTC)
    company_id = uuid4()
    defaults: dict[str, object] = {
        "id": company_id,
        "name": "Acme",
        "legal_name": None,
        "subdomain": None,
        "industry_code": None,
        "country_code": "IN",
        "currency": "INR",
        "timezone": "Asia/Kolkata",
        "fy_start_month": 4,
        "logo_url": None,
        "theme_json": None,
        "status": "TRIAL",
        "onboarded_at": None,
        "trial_ends_at": now,
        "registration_number": None,
        "contact_email": None,
        "contact_phone": None,
        "website": None,
        "company_size": None,
        "address_line1": None,
        "address_line2": None,
        "address_city": None,
        "address_state": None,
        "address_postal_code": None,
        "address_country_code": None,
        "locale_language_code": "en-IN",
        "date_format": "DD/MM/YYYY",
        "working_days_pattern": [
            {"day": "MON", "is_working": True},
            {"day": "TUE", "is_working": True},
            {"day": "WED", "is_working": True},
            {"day": "THU", "is_working": True},
            {"day": "FRI", "is_working": True},
            {"day": "SAT", "is_working": False},
            {"day": "SUN", "is_working": False},
        ],
        "business_hours_start": None,
        "business_hours_end": None,
        "created_by": None,
        "updated_by": None,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Company(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> OrganisationService:
    session = MagicMock()
    svc = OrganisationService(session)
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_get_company_profile_maps_primary_legal_entity_null(
    service: OrganisationService,
) -> None:
    company = _company()
    service._repo.get_company.return_value = company

    profile = await service.get_company_profile(company.id)

    assert profile.primary_legal_entity is None
    assert profile.name == "Acme"


@pytest.mark.asyncio
async def test_update_company_profile_currency_locked_when_active(
    service: OrganisationService,
) -> None:
    company = _company(status="ACTIVE")
    service._repo.get_company.return_value = company

    with pytest.raises(CurrencyLockedError):
        await service.update_company_profile(
            company.id,
            CompanyProfileUpdate(currency="USD"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_company_profile_rejects_zero_working_days(
    service: OrganisationService,
) -> None:
    company = _company()
    service._repo.get_company.return_value = company

    with pytest.raises(InvalidWorkingDaysError):
        await service.update_company_profile(
            company.id,
            CompanyProfileUpdate(
                working_days=[
                    {"day": "MON", "is_working": False, "is_alternate": False},
                    {"day": "TUE", "is_working": False, "is_alternate": False},
                    {"day": "WED", "is_working": False, "is_alternate": False},
                    {"day": "THU", "is_working": False, "is_alternate": False},
                    {"day": "FRI", "is_working": False, "is_alternate": False},
                    {"day": "SAT", "is_working": False, "is_alternate": False},
                    {"day": "SUN", "is_working": False, "is_alternate": False},
                ]
            ),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_company_profile_suspended_company_blocked(
    service: OrganisationService,
) -> None:
    company = _company(status="SUSPENDED")
    service._repo.get_company.return_value = company

    with pytest.raises(CompanyWriteBlockedError):
        await service.update_company_profile(
            company.id,
            CompanyProfileUpdate(legal_name="Blocked"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_company_profile_stale_version_raises(
    service: OrganisationService,
) -> None:
    company = _company()
    current = _company(legal_name="Current", version=2)
    service._repo.get_company.side_effect = [company, current]
    service._repo.update_company.return_value = None

    with pytest.raises(StaleResourceError) as exc_info:
        await service.update_company_profile(
            company.id,
            CompanyProfileUpdate(legal_name="New"),
            expected_version=1,
            actor_user_id=uuid4(),
        )

    assert exc_info.value.details[0]["context"]["current"]["legal_name"] == "Current"


@pytest.mark.asyncio
async def test_update_company_profile_value_object_replacement(
    service: OrganisationService,
) -> None:
    company = _company(contact_email="old@example.com")
    updated = _company(contact_email="new@example.com", version=2)
    service._repo.get_company.return_value = company
    service._repo.update_company.return_value = updated

    result = await service.update_company_profile(
        company.id,
        CompanyProfileUpdate(
            contact=ContactInfoSchema(email="new@example.com", phone=None, website=None)
        ),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.contact.email == "new@example.com"
    service._repo.update_company.assert_awaited_once()
    service._audit.record.assert_awaited_once()


def _setup_progress(**overrides: object) -> CompanySetupProgress:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "steps_completed": [],
        "current_step": None,
        "status": "IN_PROGRESS",
        "started_at": now,
        "completed_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return CompanySetupProgress(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_get_setup_progress_not_found_raises(service: OrganisationService) -> None:
    service._repo.get_setup_progress.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_setup_progress(uuid4())


def _fake_update_setup_progress(**overrides: object) -> object:
    def _update(session: object, *, company_id: object, now: object, **values: object) -> object:
        return _setup_progress(company_id=company_id, **values)  # type: ignore[arg-type]

    return _update


@pytest.mark.asyncio
async def test_get_setup_progress_registry_driven_aggregation(
    service: OrganisationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-10 acceptance criteria: a fake `SetupStepDefinition` with a controllable predicate
    correctly flips `status` between IN_PROGRESS/COMPLETE without editing the aggregation
    loop in `service.py` — proving the registry, not hardcoded step logic, drives the result.
    """
    progress = _setup_progress()
    service._repo.get_setup_progress.return_value = progress
    service._repo.update_setup_progress.side_effect = _fake_update_setup_progress()

    async def _incomplete(repo: object, session: object, company_id: object) -> bool:
        return False

    monkeypatch.setattr(
        "hrms.modules.organisation.service.SETUP_STEPS",
        [SetupStepDefinition(code="FAKE_STEP", label="Fake Step", check=_incomplete)],
    )

    result = await service.get_setup_progress(progress.company_id)

    assert result.status == "IN_PROGRESS"
    assert len(result.steps) == 1
    assert result.steps[0].code == "FAKE_STEP"
    assert result.steps[0].is_complete is False
    assert result.current_step == "FAKE_STEP"
    service._repo.mark_company_onboarded.assert_not_awaited()

    async def _complete(repo: object, session: object, company_id: object) -> bool:
        return True

    monkeypatch.setattr(
        "hrms.modules.organisation.service.SETUP_STEPS",
        [SetupStepDefinition(code="FAKE_STEP", label="Fake Step", check=_complete)],
    )

    result = await service.get_setup_progress(progress.company_id)

    assert result.status == "COMPLETE"
    assert result.current_step is None
    assert result.steps[0].is_complete is True
    service._repo.mark_company_onboarded.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_setup_progress_already_complete_keeps_completed_at(
    service: OrganisationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed_at = datetime.now(UTC)
    progress = _setup_progress(status="COMPLETE", completed_at=completed_at)
    service._repo.get_setup_progress.return_value = progress

    async def _complete(repo: object, session: object, company_id: object) -> bool:
        return True

    monkeypatch.setattr(
        "hrms.modules.organisation.service.SETUP_STEPS",
        [SetupStepDefinition(code="FAKE_STEP", label="Fake Step", check=_complete)],
    )

    captured: dict[str, object] = {}

    def _fake_update(
        session: object, *, company_id: object, now: object, **values: object
    ) -> object:
        captured.update(values)
        return _setup_progress(company_id=company_id, **values)  # type: ignore[arg-type]

    service._repo.update_setup_progress.side_effect = _fake_update

    await service.get_setup_progress(progress.company_id)

    assert captured["completed_at"] == completed_at
    service._repo.mark_company_onboarded.assert_not_awaited()
