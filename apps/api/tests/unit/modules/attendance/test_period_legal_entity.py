"""Unit tests for legal-entity period grain (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`
decisions 14 and 18) — which entity's period owns an employee-date, and the calendar-month
default on period create. No DB/HTTP."""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hrms.modules.attendance.schemas import AttendancePeriodCreate
from hrms.modules.attendance.service import _owning_legal_entity, _PeriodScope

_A = uuid4()
_B = uuid4()


def test_covering_employment_decides() -> None:
    spans = [(_A, date(2026, 1, 1), None)]
    assert _owning_legal_entity(spans, date(2026, 8, 10)) == _A


def test_mid_month_transfer_splits_the_month() -> None:
    spans = [(_A, date(2026, 1, 1), date(2026, 8, 10)), (_B, date(2026, 8, 11), None)]
    assert _owning_legal_entity(spans, date(2026, 8, 10)) == _A
    assert _owning_legal_entity(spans, date(2026, 8, 11)) == _B


def test_not_employed_days_have_exactly_one_owner() -> None:
    spans = [
        (_A, date(2026, 3, 1), date(2026, 5, 31)),
        (_B, date(2026, 7, 1), None),
    ]
    # Before joining: the first spell's entity.
    assert _owning_legal_entity(spans, date(2026, 2, 15)) == _A
    # A gap between spells: the spell that just ended.
    assert _owning_legal_entity(spans, date(2026, 6, 15)) == _A


def test_after_exit_belongs_to_the_last_entity() -> None:
    spans = [(_A, date(2026, 1, 1), date(2026, 8, 10))]
    assert _owning_legal_entity(spans, date(2026, 8, 20)) == _A


def test_no_employment_is_unknown() -> None:
    assert _owning_legal_entity([], date(2026, 8, 10)) is None


def test_period_scope_owns_only_its_entitys_dates() -> None:
    employee = uuid4()
    other = uuid4()
    scope = _PeriodScope(
        legal_entity_id=_A,
        spans_by_employee={
            employee: [(_A, date(2026, 1, 1), date(2026, 8, 10)), (_B, date(2026, 8, 11), None)],
            other: [(_B, date(2026, 1, 1), None)],
        },
        expected_dates={employee: {date(2026, 8, 10)}},
    )
    assert scope.owns(employee, date(2026, 8, 10))
    assert not scope.owns(employee, date(2026, 8, 11))
    assert not scope.owns(other, date(2026, 8, 10))


def test_month_expands_to_the_calendar_month_with_a_label() -> None:
    body = AttendancePeriodCreate(legal_entity_id=_A, month="2028-02")
    assert body.period_start == date(2028, 2, 1)
    assert body.period_end == date(2028, 2, 29)
    assert body.label == "February 2028"


def test_month_keeps_an_explicit_label() -> None:
    body = AttendancePeriodCreate(legal_entity_id=_A, month="2026-09", label="Sep payroll")
    assert body.label == "Sep payroll"


def test_explicit_range_still_accepted() -> None:
    body = AttendancePeriodCreate(
        legal_entity_id=_A, period_start=date(2026, 8, 26), period_end=date(2026, 9, 25)
    )
    assert body.period_start == date(2026, 8, 26)
    assert body.label is None


@pytest.mark.parametrize(
    "fields",
    [
        {"month": "2026-09", "period_start": date(2026, 9, 1)},
        {"period_start": date(2026, 9, 1)},
        {},
        {"month": "2026-13"},
        {"period_start": date(2026, 9, 2), "period_end": date(2026, 9, 1)},
    ],
)
def test_invalid_create_bodies_rejected(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AttendancePeriodCreate(legal_entity_id=_A, **fields)  # type: ignore[arg-type]


def test_legal_entity_required() -> None:
    with pytest.raises(ValidationError):
        AttendancePeriodCreate(month="2026-09")  # type: ignore[call-arg]
