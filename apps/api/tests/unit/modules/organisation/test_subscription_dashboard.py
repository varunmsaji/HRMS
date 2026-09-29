"""Unit tests for C-11 subscription summary and C-12 dashboard aggregation."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.models import (
    CompanyFeatureFlag,
    CompanySetupProgress,
    Plan,
    PlanFeature,
    Subscription,
)
from hrms.modules.organisation.schemas import SetupStepDefinition
from hrms.modules.organisation.service import OrganisationService
from hrms.seed.plan_catalogue import SEAT_LIMIT_FEATURE_CODE


def _plan(**overrides: object) -> Plan:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "code": "FREE",
        "name": "Free",
        "description": "Trial",
        "is_active": True,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Plan(**defaults)  # type: ignore[arg-type]


def _subscription(*, plan_id: object, company_id: object, **overrides: object) -> Subscription:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": company_id,
        "plan_id": plan_id,
        "status": "TRIALING",
        "current_period_start": None,
        "current_period_end": None,
        "trial_ends_at": now,
        "canceled_at": None,
        "seat_limit_override": None,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Subscription(**defaults)  # type: ignore[arg-type]


def _plan_feature(*, plan_id: object, **overrides: object) -> PlanFeature:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "plan_id": plan_id,
        "feature_code": SEAT_LIMIT_FEATURE_CODE,
        "is_enabled": True,
        "limit_value": 5,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return PlanFeature(**defaults)  # type: ignore[arg-type]


def _company_flag(*, company_id: object, **overrides: object) -> CompanyFeatureFlag:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": company_id,
        "feature_code": "BETA_PAYROLL_V2",
        "is_enabled": True,
        "overrides_plan": True,
        "value": None,
        "created_by": None,
        "updated_by": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return CompanyFeatureFlag(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def service() -> OrganisationService:
    session = MagicMock()
    svc = OrganisationService(session)
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    svc._employee_repo = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_get_subscription_summary_plan_and_override_resolution(
    service: OrganisationService,
) -> None:
    company_id = uuid4()
    plan = _plan()
    subscription = _subscription(plan_id=plan.id, company_id=company_id)
    service._repo.get_active_subscription.return_value = subscription
    service._repo.get_plan.return_value = plan
    service._repo.get_plan_features.return_value = [
        _plan_feature(plan_id=plan.id),
        _plan_feature(
            plan_id=plan.id,
            feature_code="AI_RESUME_PARSING",
            is_enabled=False,
            limit_value=None,
        ),
    ]
    service._repo.get_company_feature_flags.return_value = [
        _company_flag(company_id=company_id),
    ]

    summary = await service.get_subscription_summary(company_id)

    assert summary.plan.code == "FREE"
    assert summary.status == "TRIALING"
    assert summary.seat_limit == 5
    by_code = {item.code: item for item in summary.features}
    assert by_code[SEAT_LIMIT_FEATURE_CODE].source == "PLAN"
    assert by_code[SEAT_LIMIT_FEATURE_CODE].is_enabled is True
    assert by_code["AI_RESUME_PARSING"].source == "PLAN"
    assert by_code["AI_RESUME_PARSING"].is_enabled is False
    assert by_code["BETA_PAYROLL_V2"].source == "COMPANY_OVERRIDE"
    assert by_code["BETA_PAYROLL_V2"].is_enabled is True


@pytest.mark.asyncio
async def test_get_subscription_summary_seat_limit_override_wins(
    service: OrganisationService,
) -> None:
    company_id = uuid4()
    plan = _plan()
    subscription = _subscription(plan_id=plan.id, company_id=company_id, seat_limit_override=50)
    service._repo.get_active_subscription.return_value = subscription
    service._repo.get_plan.return_value = plan
    service._repo.get_plan_features.return_value = [_plan_feature(plan_id=plan.id)]
    service._repo.get_company_feature_flags.return_value = []

    summary = await service.get_subscription_summary(company_id)

    assert summary.seat_limit == 50


@pytest.mark.asyncio
async def test_get_subscription_summary_ignores_non_override_orphan_flag(
    service: OrganisationService,
) -> None:
    """overrides_plan=false flags for features not on the plan are ignored on read."""
    company_id = uuid4()
    plan = _plan()
    subscription = _subscription(plan_id=plan.id, company_id=company_id)
    service._repo.get_active_subscription.return_value = subscription
    service._repo.get_plan.return_value = plan
    service._repo.get_plan_features.return_value = [_plan_feature(plan_id=plan.id)]
    service._repo.get_company_feature_flags.return_value = [
        _company_flag(
            company_id=company_id,
            feature_code="NOT_ON_PLAN",
            overrides_plan=False,
            is_enabled=True,
        )
    ]

    summary = await service.get_subscription_summary(company_id)

    assert all(item.code != "NOT_ON_PLAN" for item in summary.features)


@pytest.mark.asyncio
async def test_get_subscription_summary_missing_raises(service: OrganisationService) -> None:
    service._repo.get_active_subscription.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_subscription_summary(uuid4())


@pytest.mark.asyncio
async def test_get_subscription_summary_missing_plan_raises(
    service: OrganisationService,
) -> None:
    """An orphaned subscription (plan row deleted/never seeded) is a data-integrity gap,
    not a normal empty state — surfaced the same way as no subscription at all."""
    company_id = uuid4()
    subscription = _subscription(plan_id=uuid4(), company_id=company_id)
    service._repo.get_active_subscription.return_value = subscription
    service._repo.get_plan.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_subscription_summary(company_id)


@pytest.mark.asyncio
async def test_get_dashboard_summary_zero_sibling_counts(
    service: OrganisationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    company_id = uuid4()
    now = datetime.now(UTC)
    progress = CompanySetupProgress(
        id=uuid4(),
        company_id=company_id,
        steps_completed=[],
        current_step="COMPANY_PROFILE",
        status="IN_PROGRESS",
        started_at=now,
        completed_at=None,
        version=1,
        created_at=now,
        updated_at=now,
    )
    service._repo.get_setup_progress.return_value = progress

    async def _incomplete(repo: object, session: object, cid: object) -> bool:
        return False

    monkeypatch.setattr(
        "hrms.modules.organisation.service.SETUP_STEPS",
        [SetupStepDefinition(code="COMPANY_PROFILE", label="Company Profile", check=_incomplete)],
    )

    def _fake_update(
        session: object, *, company_id: object, now: object, **values: object
    ) -> object:
        return CompanySetupProgress(
            id=progress.id,
            company_id=company_id,  # type: ignore[arg-type]
            steps_completed=values.get("steps_completed", []),  # type: ignore[arg-type]
            current_step=values.get("current_step"),  # type: ignore[arg-type]
            status=values["status"],  # type: ignore[arg-type]
            started_at=progress.started_at,
            completed_at=values.get("completed_at"),  # type: ignore[arg-type]
            version=2,
            created_at=progress.created_at,
            updated_at=now,  # type: ignore[arg-type]
        )

    service._repo.update_setup_progress.side_effect = _fake_update
    service._repo.get_active_subscription.return_value = None
    service._repo.list_branches.return_value = []
    service._repo.list_departments.return_value = []
    service._employee_repo.count_employees.return_value = 0

    dashboard = await service.get_dashboard_summary(company_id)

    assert dashboard.setup_progress.status == "IN_PROGRESS"
    assert dashboard.setup_progress.steps_completed == 0
    assert dashboard.setup_progress.steps_total == 1
    assert dashboard.subscription is None
    assert dashboard.branch_count == 0
    assert dashboard.department_count == 0
    assert dashboard.employee_count == 0


@pytest.mark.asyncio
async def test_get_dashboard_summary_includes_subscription(
    service: OrganisationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    company_id = uuid4()
    now = datetime.now(UTC)
    progress = CompanySetupProgress(
        id=uuid4(),
        company_id=company_id,
        steps_completed=["COMPANY_PROFILE"],
        current_step=None,
        status="COMPLETE",
        started_at=now,
        completed_at=now,
        version=1,
        created_at=now,
        updated_at=now,
    )
    service._repo.get_setup_progress.return_value = progress

    async def _complete(repo: object, session: object, cid: object) -> bool:
        return True

    monkeypatch.setattr(
        "hrms.modules.organisation.service.SETUP_STEPS",
        [SetupStepDefinition(code="COMPANY_PROFILE", label="Company Profile", check=_complete)],
    )

    def _fake_update(
        session: object, *, company_id: object, now: object, **values: object
    ) -> object:
        return CompanySetupProgress(
            id=progress.id,
            company_id=company_id,  # type: ignore[arg-type]
            steps_completed=values.get("steps_completed", []),  # type: ignore[arg-type]
            current_step=values.get("current_step"),  # type: ignore[arg-type]
            status=values["status"],  # type: ignore[arg-type]
            started_at=progress.started_at,
            completed_at=progress.completed_at,
            version=2,
            created_at=progress.created_at,
            updated_at=now,  # type: ignore[arg-type]
        )

    service._repo.update_setup_progress.side_effect = _fake_update

    plan = _plan(code="STARTER", name="Starter")
    subscription = _subscription(plan_id=plan.id, company_id=company_id, status="ACTIVE")
    service._repo.get_active_subscription.return_value = subscription
    service._repo.get_plan.return_value = plan
    service._repo.get_plan_features.return_value = [_plan_feature(plan_id=plan.id, limit_value=25)]
    service._repo.get_company_feature_flags.return_value = []
    service._repo.list_branches.return_value = [MagicMock(), MagicMock()]
    service._repo.list_departments.return_value = [MagicMock()]
    service._employee_repo.count_employees.return_value = 5

    dashboard = await service.get_dashboard_summary(company_id)

    assert dashboard.setup_progress.status == "COMPLETE"
    assert dashboard.setup_progress.steps_completed == 1
    assert dashboard.subscription is not None
    assert dashboard.subscription.plan_code == "STARTER"
    assert dashboard.subscription.status == "ACTIVE"
    assert dashboard.branch_count == 2
    assert dashboard.department_count == 1
    assert dashboard.employee_count == 5
