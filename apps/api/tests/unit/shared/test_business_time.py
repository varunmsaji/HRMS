"""`TZ-06`/`NEW-02` (execution gate §4, §9) — pure-function coverage for `business_today()`/
`business_month_start()` at the exact 05:00/05:29/05:30 IST boundary the UTC-date defect hinges
on. No database required; every case pins a UTC instant, sidestepping the host's own clock and
`TZ` setting entirely."""

from datetime import UTC, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from hrms.shared.business_time import business_month_start, business_today
from hrms.shared.timezone import TimezoneConfigurationError


def _frozen_now(instant: datetime):
    return patch(
        "hrms.shared.business_time.datetime", wraps=datetime, **{"now.return_value": instant}
    )


@pytest.mark.parametrize(
    ("utc_instant", "expected_ist_date"),
    [
        # The entire defect lives in this table (execution gate §10.2): for any instant whose
        # IST wall-clock time is before 05:30, the UTC calendar date is one day BEHIND the
        # correct IST business date.
        ("2026-10-01T00:00:00+00:00", "2026-10-01"),  # 05:30 IST -> UTC date already rolled over
        ("2026-09-30T23:59:00+00:00", "2026-10-01"),  # 05:29 IST -> UTC date still 30 Sep
        ("2026-09-30T21:30:00+00:00", "2026-10-01"),  # 03:00 IST
        ("2026-09-30T20:00:00+00:00", "2026-10-01"),  # 01:30 IST
        ("2026-09-30T19:00:00+00:00", "2026-10-01"),  # 00:30 IST
        ("2026-09-30T12:00:00+00:00", "2026-09-30"),  # 17:30 IST — ordinary daytime, no skew
    ],
)
def test_business_today_ist_boundary(utc_instant: str, expected_ist_date: str) -> None:
    instant = datetime.fromisoformat(utc_instant)
    with _frozen_now(instant):
        assert business_today("Asia/Kolkata").isoformat() == expected_ist_date


def test_business_today_utc_server_has_no_skew() -> None:
    """Regression guard: for `tz_name="UTC"` (the 22 live non-IST rows, `UTC` test literals),
    `business_today` must be identical to the old `datetime.now(UTC).date()` — this module fixes
    the IST-specific defect without changing behaviour for a tenant actually configured for UTC."""
    instant = datetime(2026, 9, 30, 23, 59, tzinfo=UTC)
    with _frozen_now(instant):
        assert business_today("UTC").isoformat() == "2026-09-30"


def test_business_today_non_ist_non_dst_zone() -> None:
    """A non-IST server/tenant timezone is still handled correctly — the helper is generically
    timezone-aware, not IST-hardcoded, per the India V1 scope note that the engine stays
    zone-independent (`PC-01`)."""
    instant = datetime(
        2026, 9, 30, 1, 0, tzinfo=UTC
    )  # 20:00 the previous day in New York (EDT, -4)
    with _frozen_now(instant):
        assert business_today("America/New_York").isoformat() == "2026-09-29"


def test_business_today_rejects_unresolvable_timezone() -> None:
    with pytest.raises(TimezoneConfigurationError):
        business_today("IST")


def test_business_month_start_at_month_boundary() -> None:
    """01:00 IST on 1 Oct is 19:30 UTC on 30 Sep — `business_month_start` must return October,
    not September, at exactly the instant `SR-05`'s monthly leave accrual job fires."""
    instant = datetime(2026, 9, 30, 19, 30, tzinfo=UTC)
    with _frozen_now(instant):
        assert business_month_start("Asia/Kolkata").isoformat() == "2026-10-01"


def test_business_month_start_consistent_with_business_today() -> None:
    """Both helpers must derive from the same instant — computing the month boundary via a
    second, independent `datetime.now(UTC)` call would reopen the class of bug this module
    exists to close (two slightly-different "today" values in the same request)."""
    instant = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
    with _frozen_now(instant):
        today = business_today("Asia/Kolkata")
        month_start = business_month_start("Asia/Kolkata")
    assert month_start == today.replace(day=1)


def test_zoneinfo_offset_sanity() -> None:
    """Confirms the fixture instants above are calculated against the real, current IANA
    +05:30 offset for Asia/Kolkata — not an assumption baked only into this test file."""
    tz = ZoneInfo("Asia/Kolkata")
    instant = datetime(2026, 9, 30, 23, 59, tzinfo=UTC).astimezone(tz)
    assert instant.strftime("%H:%M") == "05:29"
