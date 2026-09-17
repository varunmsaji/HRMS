"""`NEW-01`/`NEW-03` (execution gate §4, §5) — pure-function coverage for the shared timezone
validation/canonicalisation helpers. No database required."""

import pytest

from hrms.shared.timezone import (
    INDIA_TIMEZONES,
    TimezoneConfigurationError,
    resolve_zoneinfo,
    validate_allowed_company_timezone,
    validate_iana_timezone,
)


class TestValidateIanaTimezone:
    def test_accepts_asia_kolkata(self) -> None:
        assert validate_iana_timezone("Asia/Kolkata") == "Asia/Kolkata"

    def test_accepts_utc_regression_guard(self) -> None:
        """15 existing test literals and 22 live dev rows carry `UTC` — must remain accepted
        (execution gate §4.1, Option 1's rejection)."""
        assert validate_iana_timezone("UTC") == "UTC"

    def test_canonicalises_asia_calcutta(self) -> None:
        """The one real IANA legacy alias, not a guessed abbreviation (§5.3 step 1)."""
        assert validate_iana_timezone("Asia/Calcutta") == "Asia/Kolkata"

    @pytest.mark.parametrize("value", ["IST", "UTC+05:30", "not-a-timezone", "", "Asia/NotReal"])
    def test_rejects_invalid_values(self, value: str) -> None:
        """`IST` is the single most likely value an Indian HR user would type for their own
        zone (`SR-09`) — must be rejected, not silently mapped."""
        with pytest.raises(ValueError, match="valid IANA time zone"):
            validate_iana_timezone(value)


class TestValidateAllowedCompanyTimezone:
    def test_accepts_allowed_zone(self) -> None:
        assert (
            validate_allowed_company_timezone("Asia/Kolkata", allowed=("Asia/Kolkata",))
            == "Asia/Kolkata"
        )

    def test_canonicalises_before_allow_list_check(self) -> None:
        """`Asia/Calcutta` must be accepted when `Asia/Kolkata` is allowed — canonicalisation
        runs before the allow-list comparison (execution gate §6.3's explicit ordering)."""
        assert (
            validate_allowed_company_timezone("Asia/Calcutta", allowed=("Asia/Kolkata",))
            == "Asia/Kolkata"
        )

    def test_rejects_non_indian_zone(self) -> None:
        """`DEC-TZ-02` (SELECTED) — an anonymous registrant may not create a company on
        `America/Los_Angeles` in India V1."""
        with pytest.raises(ValueError, match="must be one of"):
            validate_allowed_company_timezone("America/Los_Angeles", allowed=("Asia/Kolkata",))

    def test_rejects_invalid_iana_value_before_allow_list(self) -> None:
        with pytest.raises(ValueError, match="valid IANA time zone"):
            validate_allowed_company_timezone("IST", allowed=("Asia/Kolkata",))


class TestIndiaTimezones:
    def test_membership_not_equality(self) -> None:
        """§5.3 step 2 — every India-invariant check must test membership in `INDIA_TIMEZONES`,
        never `== "Asia/Kolkata"`, so a not-yet-canonicalised legacy row is still recognised."""
        assert "Asia/Kolkata" in INDIA_TIMEZONES
        assert "Asia/Calcutta" in INDIA_TIMEZONES
        assert "America/Los_Angeles" not in INDIA_TIMEZONES


class TestResolveZoneinfo:
    def test_resolves_valid_zone(self) -> None:
        tz = resolve_zoneinfo("Asia/Kolkata")
        assert str(tz) == "Asia/Kolkata"

    def test_raises_typed_error_for_unresolvable_zone(self) -> None:
        """`ED-10` — the calculation path converts this into a `CONFIG_ERROR` day, never lets a
        bare `ZoneInfoNotFoundError` escape as an unhandled 500."""
        with pytest.raises(TimezoneConfigurationError):
            resolve_zoneinfo("IST")
