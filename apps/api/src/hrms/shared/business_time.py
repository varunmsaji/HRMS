"""The business-date helper every UTC-derived-date defect in this programme traces back to
(`TZ-06`/`NEW-02`/`NEW-05`/`SR-05`, execution gate §4, §9, §16).

`datetime.now(UTC).date()` and `date.today()` (under a `TZ=UTC` server, per `DEC-TZ-04`/`TZ-02`)
both return the **UTC** calendar date of the current instant. For any instant between 00:00 and
05:29 `Asia/Kolkata` wall-clock time, the UTC date is one day *behind* the correct India business
date — a shift of exactly the gap between UTC and `Asia/Kolkata` (+05:30, no DST). Every call site
that derives "today" or "this month" for a business decision (attendance-date default, leave-job
`as_of`, regularization future/backdating checks, the scheduled calculation trigger) must go
through this module instead, so the defect is fixed once and cannot be silently reintroduced at a
new call site by a future `datetime.now(UTC).date()`.

Deliberately not a facade over `datetime.now()` with the host's local timezone — that would tie
correctness to the server's `TZ` environment variable rather than to the resolved business
timezone, which is exactly the coupling `DEC-TZ-04`/`TZ-02` closes by pinning `TZ=UTC` everywhere
and deriving business dates explicitly instead."""

from datetime import UTC, date, datetime

from hrms.shared.timezone import resolve_zoneinfo


def business_today(tz_name: str) -> date:
    """The current calendar date in `tz_name`, computed from the server's own UTC clock — never
    the server OS's local timezone. This is the one correct replacement for both
    `datetime.now(UTC).date()` and `date.today()` wherever the derived value feeds a business
    decision rather than an audit timestamp."""
    return datetime.now(UTC).astimezone(resolve_zoneinfo(tz_name)).date()


def business_month_start(tz_name: str) -> date:
    """The first day of the current month in `tz_name`. A thin wrapper over `business_today`
    rather than a second `datetime.now(UTC)` call, so both helpers are provably consistent with
    each other for the same instant — computing the month boundary independently would reopen the
    exact class of two-slightly-different-"today"-values bug this module exists to prevent."""
    return business_today(tz_name).replace(day=1)
