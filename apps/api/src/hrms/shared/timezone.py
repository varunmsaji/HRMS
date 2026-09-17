"""India V1 timezone validation and canonicalisation (execution gate §4, §5).

Every `timezone`-accepting schema field in the codebase (`Company`, `Branch`, `ShiftVersion`)
should validate through `validate_iana_timezone`, in this exact order:

1. reject anything not a valid IANA identifier — `available_timezones()` membership,
2. canonicalise via `INDIA_TIMEZONE_ALIASES` (currently the one real alias, `Asia/Calcutta` ->
   `Asia/Kolkata`) — a real legacy IANA name a real browser can send, not a guessed abbreviation.

`ShiftVersion`/`Branch` accept any valid IANA zone (the engine stays zone-independent, `ED-1`); the
India-only *product* restriction is enforced separately, only at the two external entry points
that a non-admin party controls (`CompanyRegistrationRequest`, `CompanyProfileUpdate`), via
`validate_allowed_company_timezone`.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

# The only alias handled: a real IANA legacy name real browsers still emit (`timezones.ts`'s own
# fallback), not a guess at an abbreviation a user might have typed (`IST`, `UTC+05:30`, ...) —
# those remain rejected outright, per the execution gate's explicit instruction not to infer
# user-typed abbreviations (§4.5 "On silent abbreviation mapping").
INDIA_TIMEZONE_ALIASES: dict[str, str] = {"Asia/Calcutta": "Asia/Kolkata"}

# Every India-invariant check or allow-list must test membership in this set, never
# `== "Asia/Kolkata"` — protects rows written before canonicalisation shipped, in any environment
# not yet cleaned (execution gate §5.3 step 2).
INDIA_TIMEZONES: frozenset[str] = frozenset({"Asia/Kolkata", "Asia/Calcutta"})


def validate_iana_timezone(value: str) -> str:
    """Raises `ValueError` (→ 422 under a Pydantic field validator) unless `value` is a real IANA
    zone identifier; returns the canonicalised form otherwise. `NULL`/`None` is never passed
    through this function — callers with an optional timezone field check for `None` first, since
    it is WD-06's own "inherit from branch/company" signal, not an invalid value."""
    if value not in available_timezones():
        raise ValueError("timezone must be a valid IANA time zone identifier")
    return INDIA_TIMEZONE_ALIASES.get(value, value)


def validate_allowed_company_timezone(value: str, *, allowed: tuple[str, ...]) -> str:
    """The India V1 registration/profile gate (`DEC-TZ-02`, SELECTED). Runs the ordinary IANA
    check and canonicalisation first, then additionally rejects anything outside `allowed`. Order
    matters: canonicalising before the allow-list check means `Asia/Calcutta` — which resolves to
    an allowed zone — is accepted, not rejected for a spelling difference (execution gate §6.3)."""
    canonical = validate_iana_timezone(value)
    if canonical not in allowed:
        raise ValueError(f"timezone must be one of {sorted(allowed)}")
    return canonical


class TimezoneConfigurationError(Exception):
    """Raised when a *stored* timezone value cannot be resolved at calculation time.

    Distinct from the `ValueError` the schema validators above raise: this fires deep inside the
    calculation path, for a row that passed validation when written but has since become
    unresolvable (a `tzdata` downgrade, or — pre-Phase-2 — a row written before validation
    existed). The caller converts this into a `CONFIG_ERROR` attendance day, never a bare 500
    (`ED-10`, execution gate §4.3)."""


def resolve_zoneinfo(tz_name: str) -> ZoneInfo:
    """The one place `ZoneInfo(...)` should be constructed from a stored, previously-validated
    timezone string on the calculation path. Wraps the stdlib's `ZoneInfoNotFoundError` so a
    pre-existing invalid row degrades one employee-date to `CONFIG_ERROR`, never crashes the
    request with an unhandled 500 — which matters most once the scheduled job (Phase 8) hits the
    same row repeatedly, unattended."""
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise TimezoneConfigurationError(
            f"timezone {tz_name!r} is not a resolvable IANA zone"
        ) from exc
