"""The one authoritative answer to "does an employment spell cover this date range?".

Pure (no I/O) so it is unit-testable and shared by every caller through
`EmploymentService.check_employment_coverage`: Leave submission and approval, ledger adjustments and
encashments, the Attendance leave projection and the termination guard all ask this one function,
so the rule cannot drift between modules.

A range is valid only when EVERY calendar date in it is covered by employment AND all of them belong
to ONE spell. A back-to-back rehire (last working day d, new joining date d+1) leaves no uncovered
date but still crosses two spells, so it is `CROSS_EMPLOYMENT_SPELL`. The last working day and the
joining day themselves are covered. A `NULL` last working day is an open spell.

Dates are plain calendar dates: callers pass the dates the user chose (already company-local), and
no instant or timezone is involved here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from uuid import UUID


class EmploymentCoverageStatus(StrEnum):
    VALID = "VALID"
    #: The employee has no employment row at all.
    NO_EMPLOYMENT = "NO_EMPLOYMENT"
    PRE_JOINING = "PRE_JOINING"
    AFTER_LAST_WORKING_DAY = "AFTER_LAST_WORKING_DAY"
    REHIRE_GAP = "REHIRE_GAP"
    CROSS_EMPLOYMENT_SPELL = "CROSS_EMPLOYMENT_SPELL"


@dataclass(frozen=True)
class EmploymentCoverage:
    status: EmploymentCoverageStatus
    #: The one spell covering the whole range; set only when `status` is `VALID`.
    employment_id: UUID | None = None
    #: The first date that fails the rule (the first uncovered date, or the first date of the
    #: second spell for a crossing range); `None` when valid.
    offending_date: date | None = None

    @property
    def is_valid(self) -> bool:
        return self.status is EmploymentCoverageStatus.VALID


#: `(employment_id, joining_date, last_working_day)`; a `None` last working day is an open spell.
Span = tuple[UUID, date, date | None]


def _covering(spans: Sequence[Span], day: date) -> Span | None:
    for span in spans:
        _, joining, last = span
        if joining <= day and (last is None or last >= day):
            return span
    return None


def _uncovered(spans: Sequence[Span], day: date) -> EmploymentCoverage:
    if not spans:
        status = EmploymentCoverageStatus.NO_EMPLOYMENT
    elif not any(joining <= day for _, joining, _ in spans):
        status = EmploymentCoverageStatus.PRE_JOINING
    elif any(joining > day for _, joining, _ in spans):
        status = EmploymentCoverageStatus.REHIRE_GAP
    else:
        status = EmploymentCoverageStatus.AFTER_LAST_WORKING_DAY
    return EmploymentCoverage(status=status, offending_date=day)


def evaluate_employment_coverage(
    spans: Sequence[Span], start_date: date, end_date: date | None = None
) -> EmploymentCoverage:
    end = end_date if end_date is not None else start_date
    first = _covering(spans, start_date)
    if first is None:
        return _uncovered(spans, start_date)
    employment_id, _, last = first
    if last is None or last >= end:
        return EmploymentCoverage(
            status=EmploymentCoverageStatus.VALID, employment_id=employment_id
        )
    next_day = last + timedelta(days=1)
    if _covering(spans, next_day) is not None:
        return EmploymentCoverage(
            status=EmploymentCoverageStatus.CROSS_EMPLOYMENT_SPELL, offending_date=next_day
        )
    return _uncovered(spans, next_day)
