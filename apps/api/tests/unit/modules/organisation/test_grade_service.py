"""Unit tests for organisation service Grade methods."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from hrms.core.errors.base import NotFoundError
from hrms.modules.organisation.exceptions import (
    GradeCodeAlreadyExistsError,
    InvalidCtcRangeError,
    InvalidGradeError,
    StaleResourceError,
)
from hrms.modules.organisation.models import Designation, Grade
from hrms.modules.organisation.schemas import DesignationCreate, GradeCreate, GradeUpdate
from hrms.modules.organisation.service import OrganisationService


def _grade(**overrides: object) -> Grade:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "code": "L5",
        "name": "Senior Engineer",
        "level": 5,
        "min_ctc": None,
        "max_ctc": None,
        "notice_period_days": None,
        "probation_days": None,
        "approval_limit": None,
        "is_active": True,
        "deleted_at": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Grade(**defaults)  # type: ignore[arg-type]


def _designation(**overrides: object) -> Designation:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "department_id": None,
        "grade_id": None,
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


@pytest.fixture
def service() -> OrganisationService:
    session = MagicMock()
    svc = OrganisationService(session)
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_create_grade_records_audit(service: OrganisationService) -> None:
    company_id = uuid4()
    grade = _grade(company_id=company_id)
    service._repo.insert_grade.return_value = grade

    result = await service.create_grade(
        company_id,
        GradeCreate(code="L5", name="Senior Engineer"),
        actor_user_id=uuid4(),
    )

    assert result.code == "L5"
    assert result.is_active is True
    service._audit.record.assert_awaited_once()
    assert service._audit.record.call_args.kwargs["action"] == "GRADE_CREATED"


@pytest.mark.asyncio
async def test_create_grade_invalid_ctc_range_rejected(service: OrganisationService) -> None:
    with pytest.raises(InvalidCtcRangeError):
        await service.create_grade(
            uuid4(),
            GradeCreate(code="L5", name="Senior Engineer", min_ctc=2_000_000, max_ctc=1_000_000),
            actor_user_id=uuid4(),
        )
    service._repo.insert_grade.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_grade_equal_min_max_ctc_allowed(service: OrganisationService) -> None:
    company_id = uuid4()
    service._repo.insert_grade.return_value = _grade(
        company_id=company_id, min_ctc=1_000_000, max_ctc=1_000_000
    )

    result = await service.create_grade(
        company_id,
        GradeCreate(code="L5", name="Senior Engineer", min_ctc=1_000_000, max_ctc=1_000_000),
        actor_user_id=uuid4(),
    )

    assert result.min_ctc == result.max_ctc == 1_000_000


@pytest.mark.asyncio
async def test_create_grade_duplicate_code_rejected(service: OrganisationService) -> None:
    service._repo.insert_grade.side_effect = IntegrityError("stmt", {}, Exception("dup"))

    with pytest.raises(GradeCodeAlreadyExistsError):
        await service.create_grade(
            uuid4(),
            GradeCreate(code="L5", name="Senior Engineer"),
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_get_grade_not_found(service: OrganisationService) -> None:
    service._repo.get_grade.return_value = None

    with pytest.raises(NotFoundError):
        await service.get_grade(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_update_grade_not_found(service: OrganisationService) -> None:
    service._repo.get_grade.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_grade(
            uuid4(),
            uuid4(),
            GradeUpdate(name="New Name"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_grade_invalid_ctc_range_rejected_against_existing_value(
    service: OrganisationService,
) -> None:
    """Patching only `min_ctc` above the *existing* `max_ctc` must still be rejected —
    the effective range is validated, not just the fields present in the patch."""
    grade = _grade(min_ctc=None, max_ctc=1_000_000)
    service._repo.get_grade.return_value = grade

    with pytest.raises(InvalidCtcRangeError):
        await service.update_grade(
            grade.company_id,
            grade.id,
            GradeUpdate(min_ctc=2_000_000),
            expected_version=1,
            actor_user_id=uuid4(),
        )
    service._repo.update_grade.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_grade_not_blocked_by_anything(service: OrganisationService) -> None:
    """No documented dependency-blocking rule applies to Grade this slice — see
    docs/modules/grade/00_GRADE_AUDIT.md §6.3."""
    grade = _grade(is_active=True)
    service._repo.get_grade.return_value = grade
    service._repo.update_grade.return_value = _grade(
        id=grade.id, company_id=grade.company_id, is_active=False, version=2
    )

    result = await service.update_grade(
        grade.company_id,
        grade.id,
        GradeUpdate(is_active=False),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is False
    assert service._audit.record.call_args.kwargs["action"] == "GRADE_DEACTIVATED"


@pytest.mark.asyncio
async def test_reactivate_grade_records_distinct_audit_action(service: OrganisationService) -> None:
    grade = _grade(is_active=False)
    service._repo.get_grade.return_value = grade
    service._repo.update_grade.return_value = _grade(
        id=grade.id, company_id=grade.company_id, is_active=True, version=2
    )

    result = await service.update_grade(
        grade.company_id,
        grade.id,
        GradeUpdate(is_active=True),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.is_active is True
    assert service._audit.record.call_args.kwargs["action"] == "GRADE_REACTIVATED"


@pytest.mark.asyncio
async def test_update_grade_stale_version_conflict(service: OrganisationService) -> None:
    grade = _grade()
    service._repo.get_grade.return_value = grade
    service._repo.update_grade.return_value = None

    with pytest.raises(StaleResourceError):
        await service.update_grade(
            grade.company_id,
            grade.id,
            GradeUpdate(name="Renamed"),
            expected_version=1,
            actor_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_update_grade_noop_when_patch_empty(service: OrganisationService) -> None:
    grade = _grade()
    service._repo.get_grade.return_value = grade

    result = await service.update_grade(
        grade.company_id,
        grade.id,
        GradeUpdate(),
        expected_version=1,
        actor_user_id=uuid4(),
    )

    assert result.name == grade.name
    service._repo.update_grade.assert_not_awaited()
    service._audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_designation_validates_grade_ownership(service: OrganisationService) -> None:
    company_id = uuid4()
    grade = _grade(company_id=company_id)
    service._repo.get_grade.return_value = grade
    service._repo.insert_designation.return_value = _designation(
        company_id=company_id, grade_id=grade.id
    )

    result = await service.create_designation(
        company_id,
        DesignationCreate(title="Software Engineer", grade_id=grade.id),
        actor_user_id=uuid4(),
    )

    assert result.grade_id == grade.id
    service._repo.get_grade.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_designation_invalid_grade_rejected(service: OrganisationService) -> None:
    service._repo.get_grade.return_value = None

    with pytest.raises(InvalidGradeError):
        await service.create_designation(
            uuid4(),
            DesignationCreate(title="Software Engineer", grade_id=uuid4()),
            actor_user_id=uuid4(),
        )
    service._repo.insert_designation.assert_not_awaited()
