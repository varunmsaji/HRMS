"""The canonical employment-coverage rule (D0-D3): pure, so every boundary is checked directly."""

from datetime import date
from uuid import uuid4

import pytest

from hrms.modules.employee.coverage import (
    EmploymentCoverageStatus as S,
)
from hrms.modules.employee.coverage import (
    evaluate_employment_coverage,
)

FIRST, SECOND = uuid4(), uuid4()


def d(text: str) -> date:
    return date.fromisoformat(text)


#: spell 1: 2026-03-02 .. 2026-09-30, gap 2026-10-01 .. 2026-11-01, spell 2: 2026-11-02 .. open
GAP = [(FIRST, d("2026-03-02"), d("2026-09-30")), (SECOND, d("2026-11-02"), None)]
#: back-to-back: last working day 2026-06-30, rejoin 2026-07-01, no uncovered date between
BACK_TO_BACK = [(FIRST, d("2026-03-02"), d("2026-06-30")), (SECOND, d("2026-07-01"), None)]
ENDED = [(FIRST, d("2026-03-02"), d("2026-09-30"))]
OPEN = [(FIRST, d("2026-03-02"), None)]


@pytest.mark.parametrize(
    ("spans", "start", "end", "status", "spell", "offending"),
    [
        (GAP, "2026-02-27", "2026-02-27", S.PRE_JOINING, None, "2026-02-27"),
        (GAP, "2026-03-02", "2026-03-02", S.VALID, FIRST, None),  # joining day
        (GAP, "2026-05-12", "2026-05-14", S.VALID, FIRST, None),
        (GAP, "2026-09-30", "2026-09-30", S.VALID, FIRST, None),  # last working day
        (GAP, "2026-10-01", "2026-10-01", S.REHIRE_GAP, None, "2026-10-01"),  # day after
        (GAP, "2026-10-15", "2026-10-16", S.REHIRE_GAP, None, "2026-10-15"),
        (GAP, "2026-11-01", "2026-11-01", S.REHIRE_GAP, None, "2026-11-01"),
        (GAP, "2026-11-02", "2026-11-02", S.VALID, SECOND, None),  # second spell, first day
        (GAP, "2027-02-01", "2027-02-03", S.VALID, SECOND, None),  # open spell has no end
        (GAP, "2026-09-29", "2026-11-03", S.REHIRE_GAP, None, "2026-10-01"),  # across the gap
        (GAP, "2026-02-25", "2026-03-03", S.PRE_JOINING, None, "2026-02-25"),
        (ENDED, "2026-10-01", "2026-10-01", S.AFTER_LAST_WORKING_DAY, None, "2026-10-01"),
        (ENDED, "2026-09-29", "2026-10-02", S.AFTER_LAST_WORKING_DAY, None, "2026-10-01"),
        (BACK_TO_BACK, "2026-06-29", "2026-07-02", S.CROSS_EMPLOYMENT_SPELL, None, "2026-07-01"),
        (BACK_TO_BACK, "2026-06-30", "2026-06-30", S.VALID, FIRST, None),
        (BACK_TO_BACK, "2026-07-01", "2026-07-01", S.VALID, SECOND, None),
        (OPEN, "2026-03-01", "2026-03-02", S.PRE_JOINING, None, "2026-03-01"),
        ([], "2026-05-12", "2026-05-12", S.NO_EMPLOYMENT, None, "2026-05-12"),
    ],
)
def test_coverage(
    spans: list, start: str, end: str, status: S, spell: object, offending: str | None
) -> None:
    result = evaluate_employment_coverage(spans, d(start), d(end))
    assert result.status is status
    assert result.employment_id == spell
    assert result.offending_date == (d(offending) if offending else None)
    assert result.is_valid is (status is S.VALID)


def test_single_date_form() -> None:
    assert evaluate_employment_coverage(GAP, d("2026-09-30")).is_valid
    assert evaluate_employment_coverage(GAP, d("2026-10-01")).status is S.REHIRE_GAP
