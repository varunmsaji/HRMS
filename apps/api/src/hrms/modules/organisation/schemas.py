"""Pydantic request/response shapes for the organisation module."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from hrms.core.auth.passwords import PASSWORD_MAX_LENGTH
from hrms.core.config.settings import get_settings
from hrms.core.db.models.identity import Company
from hrms.shared.limits import MAX_INT32, MAX_MONEY_MINOR
from hrms.shared.timezone import validate_allowed_company_timezone, validate_iana_timezone

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from hrms.modules.organisation.models import (
        Branch,
        CalendarException,
        CompanySetupProgress,
        Department,
        Designation,
        Grade,
        Holiday,
        HolidayCalendar,
        LegalEntity,
        PolicyAssignment,
        Shift,
        ShiftBreak,
        ShiftDutyBlock,
        ShiftVersion,
        WeeklyOffPattern,
        WeeklyOffRule,
        WorkCalendar,
    )
    from hrms.modules.organisation.repository import OrganisationRepository

_COMPANY_SIZE_BANDS = ("1-10", "11-50", "51-200", "201-500", "501-1000", "1000+")
_DAYS_OF_WEEK = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

# docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:966 — "PAN format regex ([A-Z]{5}[0-9]{4}[A-Z]{1}),
# GSTIN format regex" (pattern itself not spelled out for GSTIN; the standard official 15-char
# GSTIN structure is used below: 2-digit state code + 10-char PAN + 1-digit entity code + 'Z' +
# 1 checksum char).
_PAN_PATTERN = r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"
_GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"

# docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:423 — "state_code validated against the ISO
# 3166-2:IN state list." No such constant existed anywhere in the codebase prior to the
# Branch slice (28 states + 8 union territories, including the 2020 Dadra & Nagar Haveli /
# Daman & Diu merger and the 2019 Jammu & Kashmir / Ladakh split).
INDIA_STATE_CODES: dict[str, str] = {
    "AN": "Andaman and Nicobar Islands",
    "AP": "Andhra Pradesh",
    "AR": "Arunachal Pradesh",
    "AS": "Assam",
    "BR": "Bihar",
    "CH": "Chandigarh",
    "CT": "Chhattisgarh",
    "DN": "Dadra and Nagar Haveli and Daman and Diu",
    "DL": "Delhi",
    "GA": "Goa",
    "GJ": "Gujarat",
    "HR": "Haryana",
    "HP": "Himachal Pradesh",
    "JK": "Jammu and Kashmir",
    "JH": "Jharkhand",
    "KA": "Karnataka",
    "KL": "Kerala",
    "LA": "Ladakh",
    "LD": "Lakshadweep",
    "MP": "Madhya Pradesh",
    "MH": "Maharashtra",
    "MN": "Manipur",
    "ML": "Meghalaya",
    "MZ": "Mizoram",
    "NL": "Nagaland",
    "OR": "Odisha",
    "PY": "Puducherry",
    "PB": "Punjab",
    "RJ": "Rajasthan",
    "SK": "Sikkim",
    "TN": "Tamil Nadu",
    "TG": "Telangana",
    "TR": "Tripura",
    "UP": "Uttar Pradesh",
    "UT": "Uttarakhand",
    "WB": "West Bengal",
}
_PINCODE_PATTERN = r"^[1-9][0-9]{5}$"


class RegistrationConfigRead(BaseModel):
    """Body for the public, unauthenticated `GET /companies/registration-config` — lets the
    sign-up page narrow its timezone `<select>` to what the server will actually accept, fetched
    from the API rather than duplicated as a second, independently-maintained TypeScript list
    (execution gate §6.3: "two independently maintained lists is how they drift"). Read-only;
    changing the allowed set is a `settings.allowed_company_timezones` configuration change, not
    a schema change."""

    allowed_company_timezones: list[str]


class CompanyRegistrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry_code: str | None = Field(default=None, max_length=40)
    country_code: str = Field(default="IN", min_length=2, max_length=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Kolkata")
    fy_start_month: int = Field(default=4, ge=1, le=12)
    company_size: str | None = None
    admin_first_name: str = Field(min_length=1, max_length=100)
    admin_last_name: str = Field(min_length=1, max_length=100)
    admin_email: EmailStr
    admin_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        # `DEC-TZ-02` (SELECTED) — this is the public, unauthenticated entry point (`NEW-04`);
        # the India-only gate must be enforced here regardless of what the shipped web client's
        # `<select>` happens to show, because any caller can post any valid IANA zone directly.
        # `settings.allowed_company_timezones` (default `("Asia/Kolkata",)`) is a setting, not a
        # hard-coded constant, so international expansion is a configuration change (§6.3).
        return validate_allowed_company_timezone(
            value, allowed=get_settings().allowed_company_timezones
        )

    @field_validator("currency", "country_code")
    @classmethod
    def validate_upper_alpha(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("must contain only letters")
        return value.upper()

    @field_validator("company_size")
    @classmethod
    def validate_company_size(cls, value: str | None) -> str | None:
        if value is not None and value not in _COMPANY_SIZE_BANDS:
            raise ValueError(f"company_size must be one of {_COMPANY_SIZE_BANDS}")
        return value


class AddressSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line1: str | None = Field(default=None, max_length=255)
    line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isalpha():
            raise ValueError("country_code must contain only letters")
        return value.upper()


class ContactInfoSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    website: str | None = Field(default=None, max_length=255)


class LocaleSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_code: str = Field(min_length=2, max_length=10)
    date_format: str = Field(min_length=1, max_length=20)


class FiscalYearSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_month: int = Field(ge=1, le=12)


class WorkingDaySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str
    is_working: bool
    is_alternate: bool = False

    @field_validator("day")
    @classmethod
    def validate_day(cls, value: str) -> str:
        if value not in _DAYS_OF_WEEK:
            raise ValueError(f"day must be one of {_DAYS_OF_WEEK}")
        return value


class BusinessHoursSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self


class ThemeSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_color: str | None = Field(default=None, max_length=32)


class BrandingSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo_url: str | None = Field(default=None, max_length=2048)
    theme: ThemeSchema | None = None


class CompanyProfileRead(BaseModel):
    id: UUID
    name: str
    legal_name: str | None
    registration_number: str | None
    subdomain: str | None
    contact: ContactInfoSchema
    address: AddressSchema
    industry_code: str | None
    company_size: str | None
    country_code: str
    currency: str
    timezone: str
    locale: LocaleSchema
    fiscal_year: FiscalYearSchema
    working_days: list[WorkingDaySchema]
    business_hours: BusinessHoursSchema | None
    branding: BrandingSchema
    status: str
    primary_legal_entity: None = None
    onboarded_at: str | None
    trial_ends_at: str | None
    version: int


class CompanyProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    registration_number: str | None = Field(default=None, max_length=64)
    industry_code: str | None = Field(default=None, max_length=40)
    company_size: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = None
    contact: ContactInfoSchema | None = None
    address: AddressSchema | None = None
    locale: LocaleSchema | None = None
    fiscal_year: FiscalYearSchema | None = None
    working_days: list[WorkingDaySchema] | None = None
    business_hours: BusinessHoursSchema | None = None
    branding: BrandingSchema | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        # `DEC-TZ-02` (SELECTED) — the SAME authenticated admin-edit path, gated by the SAME
        # allow-list, in the SAME canonicalise-then-check order as registration above. This is
        # NOT the "may it change at all" guard (`DEC-TZ-04`/Phase 3) — that answers a different
        # question and is checked separately, in the service layer, after this validator runs.
        if value is None:
            return None
        return validate_allowed_company_timezone(
            value, allowed=get_settings().allowed_company_timezones
        )

    @field_validator("currency", "country_code")
    @classmethod
    def validate_upper_alpha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isalpha():
            raise ValueError("must contain only letters")
        return value.upper()

    @field_validator("company_size")
    @classmethod
    def validate_company_size(cls, value: str | None) -> str | None:
        if value is not None and value not in _COMPANY_SIZE_BANDS:
            raise ValueError(f"company_size must be one of {_COMPANY_SIZE_BANDS}")
        return value


def _format_time(value: time | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M")


def _format_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    iso = str(value.isoformat())
    return iso.replace("+00:00", "Z")


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def company_to_profile_read(company: Company) -> CompanyProfileRead:
    theme: ThemeSchema | None = None
    if company.theme_json:
        theme = ThemeSchema.model_validate(company.theme_json)

    business_hours: BusinessHoursSchema | None = None
    start = _format_time(company.business_hours_start)
    end = _format_time(company.business_hours_end)
    if start is not None and end is not None:
        business_hours = BusinessHoursSchema(start_time=start, end_time=end)

    working_days = [
        WorkingDaySchema(
            day=str(entry["day"]),
            is_working=bool(entry.get("is_working", False)),
            is_alternate=bool(entry.get("is_alternate", False)),
        )
        for entry in company.working_days_pattern
    ]

    return CompanyProfileRead(
        id=company.id,
        name=company.name,
        legal_name=company.legal_name,
        registration_number=company.registration_number,
        subdomain=company.subdomain,
        contact=ContactInfoSchema(
            email=company.contact_email,
            phone=company.contact_phone,
            website=company.website,
        ),
        address=AddressSchema(
            line1=company.address_line1,
            line2=company.address_line2,
            city=company.address_city,
            state=company.address_state,
            postal_code=company.address_postal_code,
            country_code=company.address_country_code,
        ),
        industry_code=company.industry_code,
        company_size=company.company_size,
        country_code=company.country_code,
        currency=company.currency,
        timezone=company.timezone,
        locale=LocaleSchema(
            language_code=company.locale_language_code,
            date_format=company.date_format,
        ),
        fiscal_year=FiscalYearSchema(start_month=company.fy_start_month),
        working_days=working_days,
        business_hours=business_hours,
        branding=BrandingSchema(logo_url=company.logo_url, theme=theme),
        status=company.status,
        primary_legal_entity=None,
        onboarded_at=_format_timestamp(company.onboarded_at),
        trial_ends_at=_format_timestamp(company.trial_ends_at),
        version=company.version,
    )


def profile_to_audit_dict(profile: CompanyProfileRead) -> dict[str, Any]:
    return profile.model_dump(mode="json")


def build_update_values(
    company: Company,
    patch: CompanyProfileUpdate,
) -> dict[str, Any]:
    """Merge a partial API patch into flat DB column values."""
    values: dict[str, Any] = {}

    if patch.name is not None:
        values["name"] = patch.name
    if patch.legal_name is not None:
        values["legal_name"] = patch.legal_name
    if patch.registration_number is not None:
        values["registration_number"] = patch.registration_number
    if patch.industry_code is not None:
        values["industry_code"] = patch.industry_code
    if patch.company_size is not None:
        values["company_size"] = patch.company_size
    if patch.country_code is not None:
        values["country_code"] = patch.country_code
    if patch.currency is not None:
        values["currency"] = patch.currency
    if patch.timezone is not None:
        values["timezone"] = patch.timezone

    if patch.contact is not None:
        values["contact_email"] = str(patch.contact.email) if patch.contact.email else None
        values["contact_phone"] = patch.contact.phone
        values["website"] = patch.contact.website

    if patch.address is not None:
        values["address_line1"] = patch.address.line1
        values["address_line2"] = patch.address.line2
        values["address_city"] = patch.address.city
        values["address_state"] = patch.address.state
        values["address_postal_code"] = patch.address.postal_code
        values["address_country_code"] = patch.address.country_code

    if patch.locale is not None:
        values["locale_language_code"] = patch.locale.language_code
        values["date_format"] = patch.locale.date_format

    if patch.fiscal_year is not None:
        values["fy_start_month"] = patch.fiscal_year.start_month

    if patch.working_days is not None:
        values["working_days_pattern"] = [
            {
                "day": day.day,
                "is_working": day.is_working,
                "is_alternate": day.is_alternate,
            }
            for day in patch.working_days
        ]

    if patch.business_hours is not None:
        values["business_hours_start"] = _parse_time(patch.business_hours.start_time)
        values["business_hours_end"] = _parse_time(patch.business_hours.end_time)
    elif "business_hours" in patch.model_fields_set:
        values["business_hours_start"] = None
        values["business_hours_end"] = None

    if patch.branding is not None:
        values["logo_url"] = patch.branding.logo_url
        values["theme_json"] = (
            patch.branding.theme.model_dump(mode="json") if patch.branding.theme else None
        )

    return values


def count_working_days(company: Company, patch: CompanyProfileUpdate) -> int:
    if patch.working_days is not None:
        return sum(1 for day in patch.working_days if day.is_working)
    return sum(1 for entry in company.working_days_pattern if entry.get("is_working"))


class SetupStepSummary(BaseModel):
    code: str
    label: str
    is_complete: bool


class CompanySetupProgressSummary(BaseModel):
    status: str
    current_step: str | None
    steps: list[SetupStepSummary]
    started_at: str
    completed_at: str | None


@dataclass(frozen=True)
class SetupStepDefinition:
    """One entry in the setup-step registry (`OrganisationService.SETUP_STEPS`).

    Not a wire schema — `check` is the step's completion predicate, delegated to the
    owning sub-domain's repository method (Company only aggregates the answer; see
    `05_Backend_Architecture.md` §3.1).
    """

    code: str
    label: str
    check: Callable[["OrganisationRepository", "AsyncSession", UUID], Awaitable[bool]]


def setup_progress_to_summary(
    progress: "CompanySetupProgress", steps: list[SetupStepSummary]
) -> CompanySetupProgressSummary:
    started_at = _format_timestamp(progress.started_at)
    assert started_at is not None  # NOT NULL column, always set at registration
    return CompanySetupProgressSummary(
        status=progress.status,
        current_step=progress.current_step,
        steps=steps,
        started_at=started_at,
        completed_at=_format_timestamp(progress.completed_at),
    )


class PlanSummary(BaseModel):
    code: str
    name: str


class FeatureFlagView(BaseModel):
    code: str
    is_enabled: bool
    source: str  # PLAN | COMPANY_OVERRIDE
    limit_value: int | None = None


class SubscriptionSummary(BaseModel):
    plan: PlanSummary
    status: str
    current_period_start: str | None
    current_period_end: str | None
    trial_ends_at: str | None
    seat_limit: int | None
    features: list[FeatureFlagView]


class DashboardSetupProgress(BaseModel):
    status: str
    steps_completed: int
    steps_total: int


class DashboardSubscription(BaseModel):
    plan_code: str
    status: str
    trial_ends_at: str | None


class CompanyDashboardSummary(BaseModel):
    """Stable dashboard DTO — sibling counts stay null until those modules ship
    (04_API_Design.md §7). Additive optional fields may be added later without
    breaking this contract."""

    setup_progress: DashboardSetupProgress
    subscription: DashboardSubscription | None
    branch_count: int | None
    department_count: int | None
    employee_count: int | None


class LegalEntityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    registered_address: str | None = Field(default=None, max_length=4000)
    pan: str | None = Field(default=None, max_length=20)
    tan: str | None = Field(default=None, max_length=20)
    cin: str | None = Field(default=None, max_length=30)
    gstin: str | None = Field(default=None, max_length=20)
    pf_code: str | None = Field(default=None, max_length=30)
    esi_code: str | None = Field(default=None, max_length=30)
    lwf_reg: str | None = Field(default=None, max_length=30)
    signatory_name: str | None = Field(default=None, max_length=150)
    signatory_designation: str | None = Field(default=None, max_length=150)
    signature_image_url: str | None = Field(default=None, max_length=2048)

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, value: str | None) -> str | None:
        return _validate_pattern(value, _PAN_PATTERN, "pan")

    @field_validator("gstin")
    @classmethod
    def validate_gstin(cls, value: str | None) -> str | None:
        return _validate_pattern(value, _GSTIN_PATTERN, "gstin")


class LegalEntityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    registered_address: str | None = Field(default=None, max_length=4000)
    pan: str | None = Field(default=None, max_length=20)
    tan: str | None = Field(default=None, max_length=20)
    cin: str | None = Field(default=None, max_length=30)
    gstin: str | None = Field(default=None, max_length=20)
    pf_code: str | None = Field(default=None, max_length=30)
    esi_code: str | None = Field(default=None, max_length=30)
    lwf_reg: str | None = Field(default=None, max_length=30)
    signatory_name: str | None = Field(default=None, max_length=150)
    signatory_designation: str | None = Field(default=None, max_length=150)
    signature_image_url: str | None = Field(default=None, max_length=2048)
    is_active: bool | None = None

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, value: str | None) -> str | None:
        return _validate_pattern(value, _PAN_PATTERN, "pan")

    @field_validator("gstin")
    @classmethod
    def validate_gstin(cls, value: str | None) -> str | None:
        return _validate_pattern(value, _GSTIN_PATTERN, "gstin")


class LegalEntityRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    registered_address: str | None
    pan: str | None
    tan: str | None
    cin: str | None
    gstin: str | None
    pf_code: str | None
    esi_code: str | None
    lwf_reg: str | None
    signatory_name: str | None
    signatory_designation: str | None
    signature_image_url: str | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def _validate_pattern(value: str | None, pattern: str, field: str) -> str | None:
    if value is None or value == "":
        return None
    normalized = value.strip().upper()
    if not re.match(pattern, normalized):
        raise ValueError(f"{field} is not a valid format")
    return normalized


def legal_entity_to_read(entity: "LegalEntity") -> LegalEntityRead:
    return LegalEntityRead(
        id=entity.id,
        company_id=entity.company_id,
        name=entity.name,
        registered_address=entity.registered_address,
        pan=entity.pan,
        tan=entity.tan,
        cin=entity.cin,
        gstin=entity.gstin,
        pf_code=entity.pf_code,
        esi_code=entity.esi_code,
        lwf_reg=entity.lwf_reg,
        signatory_name=entity.signatory_name,
        signatory_designation=entity.signatory_designation,
        signature_image_url=entity.signature_image_url,
        is_active=entity.is_active,
        version=entity.version,
        created_at=_format_timestamp(entity.created_at) or "",
        updated_at=_format_timestamp(entity.updated_at) or "",
    )


def legal_entity_to_audit_dict(entity: LegalEntityRead) -> dict[str, Any]:
    return entity.model_dump(mode="json")


def build_legal_entity_update_values(patch: LegalEntityUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — unset fields must not
    clobber existing values (mirrors `build_update_values` for Company)."""
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        values[field] = getattr(patch, field)
    return values


def _validate_state_code(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    normalized = value.strip().upper()
    if normalized not in INDIA_STATE_CODES:
        raise ValueError("state_code is not a recognized ISO 3166-2:IN state/UT code")
    return normalized


def _validate_pincode(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    normalized = value.strip()
    if not re.match(_PINCODE_PATTERN, normalized):
        raise ValueError("pincode must be a valid 6-digit Indian PIN code")
    return normalized


class BranchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_entity_id: UUID
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=30)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state_code: str | None = Field(default=None, max_length=10)
    pincode: str | None = Field(default=None, max_length=10)
    timezone: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    geofence_radius_m: int | None = Field(default=None, gt=0, le=100_000)

    @field_validator("state_code")
    @classmethod
    def validate_state_code(cls, value: str | None) -> str | None:
        return _validate_state_code(value)

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, value: str | None) -> str | None:
        return _validate_pincode(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        # Branch stays a fully general IANA surface, not India-gated — WD-06 (Shift > Branch >
        # Company) means a correctly-gated company timezone already makes every unset branch
        # resolve to Asia/Kolkata; gating this too would only cost future non-India tenants.
        if value is None:
            return None
        return validate_iana_timezone(value)


class BranchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_entity_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=30)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state_code: str | None = Field(default=None, max_length=10)
    pincode: str | None = Field(default=None, max_length=10)
    timezone: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    geofence_radius_m: int | None = Field(default=None, gt=0, le=100_000)
    is_active: bool | None = None

    @field_validator("state_code")
    @classmethod
    def validate_state_code(cls, value: str | None) -> str | None:
        return _validate_state_code(value)

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, value: str | None) -> str | None:
        return _validate_pincode(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        # Branch stays a fully general IANA surface, not India-gated — WD-06 (Shift > Branch >
        # Company) means a correctly-gated company timezone already makes every unset branch
        # resolve to Asia/Kolkata; gating this too would only cost future non-India tenants.
        if value is None:
            return None
        return validate_iana_timezone(value)


class BranchRead(BaseModel):
    id: UUID
    company_id: UUID
    legal_entity_id: UUID
    name: str
    code: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    state_code: str | None
    pincode: str | None
    timezone: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    geofence_radius_m: int | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def branch_to_read(branch: "Branch") -> BranchRead:
    return BranchRead(
        id=branch.id,
        company_id=branch.company_id,
        legal_entity_id=branch.legal_entity_id,
        name=branch.name,
        code=branch.code,
        address_line1=branch.address_line1,
        address_line2=branch.address_line2,
        city=branch.city,
        state_code=branch.state_code,
        pincode=branch.pincode,
        timezone=branch.timezone,
        latitude=branch.latitude,
        longitude=branch.longitude,
        geofence_radius_m=branch.geofence_radius_m,
        is_active=branch.is_active,
        version=branch.version,
        created_at=_format_timestamp(branch.created_at) or "",
        updated_at=_format_timestamp(branch.updated_at) or "",
    )


def branch_to_audit_dict(branch: BranchRead) -> dict[str, Any]:
    return branch.model_dump(mode="json")


def build_branch_update_values(patch: BranchUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — unset fields must not
    clobber existing values (mirrors `build_legal_entity_update_values`)."""
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        values[field] = getattr(patch, field)
    return values


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    branch_id: UUID | None = None
    parent_id: UUID | None = None
    head_employee_id: UUID | None = None


class DepartmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    branch_id: UUID | None = None
    parent_id: UUID | None = None
    head_employee_id: UUID | None = None
    is_active: bool | None = None


class DepartmentRead(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    parent_id: UUID | None
    name: str
    code: str | None
    head_employee_id: UUID | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def department_to_read(department: "Department") -> DepartmentRead:
    return DepartmentRead(
        id=department.id,
        company_id=department.company_id,
        branch_id=department.branch_id,
        parent_id=department.parent_id,
        name=department.name,
        code=department.code,
        head_employee_id=department.head_employee_id,
        is_active=department.is_active,
        version=department.version,
        created_at=_format_timestamp(department.created_at) or "",
        updated_at=_format_timestamp(department.updated_at) or "",
    )


def department_to_audit_dict(department: DepartmentRead) -> dict[str, Any]:
    return department.model_dump(mode="json")


def build_department_update_values(patch: DepartmentUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — unset fields must not
    clobber existing values (mirrors `build_branch_update_values`)."""
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        values[field] = getattr(patch, field)
    return values


class DesignationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    department_id: UUID | None = None
    grade_id: UUID | None = None


class DesignationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    department_id: UUID | None = None
    grade_id: UUID | None = None
    is_active: bool | None = None


class DesignationRead(BaseModel):
    id: UUID
    company_id: UUID
    department_id: UUID | None
    grade_id: UUID | None
    title: str
    code: str | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def designation_to_read(designation: "Designation") -> DesignationRead:
    return DesignationRead(
        id=designation.id,
        company_id=designation.company_id,
        department_id=designation.department_id,
        grade_id=designation.grade_id,
        title=designation.title,
        code=designation.code,
        is_active=designation.is_active,
        version=designation.version,
        created_at=_format_timestamp(designation.created_at) or "",
        updated_at=_format_timestamp(designation.updated_at) or "",
    )


def designation_to_audit_dict(designation: DesignationRead) -> dict[str, Any]:
    return designation.model_dump(mode="json")


def build_designation_update_values(patch: DesignationUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — unset fields must not
    clobber existing values (mirrors `build_department_update_values`)."""
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        values[field] = getattr(patch, field)
    return values


class GradeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    level: int | None = Field(default=None, ge=0, le=MAX_INT32)
    min_ctc: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    max_ctc: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    notice_period_days: int | None = Field(default=None, ge=0, le=3650)
    probation_days: int | None = Field(default=None, ge=0, le=3650)
    approval_limit: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)


class GradeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    level: int | None = Field(default=None, ge=0, le=MAX_INT32)
    min_ctc: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    max_ctc: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    notice_period_days: int | None = Field(default=None, ge=0, le=3650)
    probation_days: int | None = Field(default=None, ge=0, le=3650)
    approval_limit: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    is_active: bool | None = None


class GradeRead(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    name: str
    level: int | None
    min_ctc: int | None
    max_ctc: int | None
    notice_period_days: int | None
    probation_days: int | None
    approval_limit: int | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def grade_to_read(grade: "Grade") -> GradeRead:
    return GradeRead(
        id=grade.id,
        company_id=grade.company_id,
        code=grade.code,
        name=grade.name,
        level=grade.level,
        min_ctc=grade.min_ctc,
        max_ctc=grade.max_ctc,
        notice_period_days=grade.notice_period_days,
        probation_days=grade.probation_days,
        approval_limit=grade.approval_limit,
        is_active=grade.is_active,
        version=grade.version,
        created_at=_format_timestamp(grade.created_at) or "",
        updated_at=_format_timestamp(grade.updated_at) or "",
    )


def grade_to_audit_dict(grade: GradeRead) -> dict[str, Any]:
    return grade.model_dump(mode="json")


def build_grade_update_values(patch: GradeUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — unset fields must not
    clobber existing values (mirrors `build_designation_update_values`)."""
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        values[field] = getattr(patch, field)
    return values


_TIME_PATTERN = r"^\d{2}:\d{2}$"


class ShiftCreate(BaseModel):
    """W2 — trimmed to identity-only (name/code). The nine schedule/evaluation fields the
    legacy `Shift` used to accept here now live on `ShiftVersion`
    (docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §9-§10)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)


class ShiftUpdate(BaseModel):
    """W2 — trimmed to identity-only (name/code/is_active). See `ShiftCreate`."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None


class ShiftRead(BaseModel):
    """The nine legacy schedule/evaluation fields below are **deprecated, read-only, and
    frozen at W2-migration time** — kept for audit/back-compat continuity only, never written
    again by W2+ code (superseded by `ShiftVersion`/`ShiftBreak`, see field-level
    descriptions). `current_version_id`/`draft_version_id` are cheap lookups so a caller knows
    schedule state without a second round trip."""

    id: UUID
    company_id: UUID
    name: str
    code: str | None
    start_time: str = Field(
        description="Deprecated — frozen at W2 migration time, superseded by "
        "ShiftVersion.start_time. Never written again."
    )
    end_time: str = Field(
        description="Deprecated — frozen at W2 migration time, superseded by "
        "ShiftVersion.end_time. Never written again."
    )
    break_minutes_paid: int = Field(
        description="Deprecated — frozen at W2 migration time, superseded by ShiftBreak rows "
        "(is_paid=true). Never written again."
    )
    break_minutes_unpaid: int = Field(
        description="Deprecated — frozen at W2 migration time, superseded by ShiftBreak rows "
        "(is_paid=false). Never written again."
    )
    grace_in_minutes: int = Field(
        description="Deprecated — frozen at W2 migration time; grace-period fields migrate "
        "off Shift in W3 (AttendancePolicy). Never written again."
    )
    grace_out_minutes: int = Field(
        description="Deprecated — frozen at W2 migration time; grace-period fields migrate "
        "off Shift in W3 (AttendancePolicy). Never written again."
    )
    half_day_threshold_hours: Decimal | None = Field(
        description="Deprecated — frozen at W2 migration time; half-day/min-hours fields "
        "migrate off Shift in W3 (AttendancePolicy). Never written again."
    )
    min_hours_full_day: Decimal | None = Field(
        description="Deprecated — frozen at W2 migration time; half-day/min-hours fields "
        "migrate off Shift in W3 (AttendancePolicy). Never written again."
    )
    is_night_shift: bool = Field(
        description="Deprecated — frozen at W2 migration time, superseded by "
        "ShiftVersion.is_night_shift. Never written again."
    )
    is_cross_midnight: bool = Field(
        description="Deprecated — frozen at W2 migration time, superseded by "
        "ShiftVersion.is_cross_midnight. Never written again."
    )
    is_ot_eligible: bool = Field(
        description="Deprecated — frozen at W2 migration time, superseded by "
        "ShiftVersion.is_ot_eligible. Never written again."
    )
    is_active: bool
    version: int
    created_at: str
    updated_at: str
    current_version_id: UUID | None = None
    draft_version_id: UUID | None = None


def shift_to_read(
    shift: "Shift",
    *,
    current_version_id: UUID | None = None,
    draft_version_id: UUID | None = None,
) -> ShiftRead:
    return ShiftRead(
        id=shift.id,
        company_id=shift.company_id,
        name=shift.name,
        code=shift.code,
        start_time=_format_time(shift.start_time) or "",
        end_time=_format_time(shift.end_time) or "",
        break_minutes_paid=shift.break_minutes_paid,
        break_minutes_unpaid=shift.break_minutes_unpaid,
        grace_in_minutes=shift.grace_in_minutes,
        grace_out_minutes=shift.grace_out_minutes,
        half_day_threshold_hours=shift.half_day_threshold_hours,
        min_hours_full_day=shift.min_hours_full_day,
        is_night_shift=shift.is_night_shift,
        is_cross_midnight=shift.is_cross_midnight,
        is_ot_eligible=shift.is_ot_eligible,
        is_active=shift.is_active,
        version=shift.version,
        created_at=_format_timestamp(shift.created_at) or "",
        updated_at=_format_timestamp(shift.updated_at) or "",
        current_version_id=current_version_id,
        draft_version_id=draft_version_id,
    )


def shift_to_audit_dict(shift: ShiftRead) -> dict[str, Any]:
    return shift.model_dump(mode="json")


def build_shift_update_values(patch: ShiftUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — unset fields must not
    clobber existing values (mirrors `build_grade_update_values`)."""
    return {field: getattr(patch, field) for field in patch.model_fields_set}


# ---------------------------------------------------------------------------
# Shift + Break System (W2) — ShiftVersion, ShiftBreak, ShiftDutyBlock.
# docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §9-§10.
# ---------------------------------------------------------------------------

_SHIFT_VERSION_TYPES = ("FIXED", "FLEXIBLE", "SPLIT")
_SHIFT_BREAK_KINDS = ("FIXED_WINDOW", "FLEXIBLE_DURATION")


class ShiftBreakCreate(BaseModel):
    """Nested input for `ShiftVersionCreate.breaks`/`ShiftVersionUpdate.breaks` — no
    independent lifecycle, no standalone endpoint (full-replace only). `crosses_midnight` is
    not client-settable — server-derived from the time comparison, same posture as
    `ShiftVersion.is_cross_midnight`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    break_kind: str
    start_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    end_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    window_start: str | None = Field(default=None, pattern=_TIME_PATTERN)
    window_end: str | None = Field(default=None, pattern=_TIME_PATTERN)
    min_minutes: int | None = Field(default=None, ge=0)
    max_minutes: int | None = Field(default=None, ge=0)
    scheduled_minutes: int | None = Field(default=None, ge=0)
    is_paid: bool = False
    is_mandatory: bool = True
    allows_split: bool = False
    sort_order: int = 0

    @field_validator("break_kind")
    @classmethod
    def validate_break_kind(cls, value: str) -> str:
        if value not in _SHIFT_BREAK_KINDS:
            raise ValueError(f"break_kind must be one of {_SHIFT_BREAK_KINDS}")
        return value


class ShiftBreakRead(BaseModel):
    id: UUID
    shift_version_id: UUID
    name: str
    break_kind: str
    start_time: str | None
    end_time: str | None
    window_start: str | None
    window_end: str | None
    min_minutes: int | None
    max_minutes: int | None
    scheduled_minutes: int | None
    is_paid: bool
    is_mandatory: bool
    allows_split: bool
    crosses_midnight: bool
    sort_order: int


def shift_break_to_read(row: "ShiftBreak") -> ShiftBreakRead:
    return ShiftBreakRead(
        id=row.id,
        shift_version_id=row.shift_version_id,
        name=row.name,
        break_kind=row.break_kind,
        start_time=_format_time(row.start_time),
        end_time=_format_time(row.end_time),
        window_start=_format_time(row.window_start),
        window_end=_format_time(row.window_end),
        min_minutes=row.min_minutes,
        max_minutes=row.max_minutes,
        scheduled_minutes=row.scheduled_minutes,
        is_paid=row.is_paid,
        is_mandatory=row.is_mandatory,
        allows_split=row.allows_split,
        crosses_midnight=row.crosses_midnight,
        sort_order=row.sort_order,
    )


class ShiftDutyBlockCreate(BaseModel):
    """Nested input for `ShiftVersionCreate.duty_blocks`/`ShiftVersionUpdate.duty_blocks` —
    SPLIT shift types only, no independent lifecycle. `crosses_midnight` is not
    client-settable — server-derived from the time comparison."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    start_time: str = Field(pattern=_TIME_PATTERN)
    end_time: str = Field(pattern=_TIME_PATTERN)


class ShiftDutyBlockRead(BaseModel):
    id: UUID
    shift_version_id: UUID
    sequence: int
    start_time: str
    end_time: str
    crosses_midnight: bool


def shift_duty_block_to_read(row: "ShiftDutyBlock") -> ShiftDutyBlockRead:
    return ShiftDutyBlockRead(
        id=row.id,
        shift_version_id=row.shift_version_id,
        sequence=row.sequence,
        start_time=_format_time(row.start_time) or "",
        end_time=_format_time(row.end_time) or "",
        crosses_midnight=row.crosses_midnight,
    )


class ShiftVersionCreate(BaseModel):
    """Creates a new open DRAFT `ShiftVersion` for a shift (409
    `SHIFT_VERSION_DRAFT_ALREADY_EXISTS` if one is already open). All fields are optional —
    a draft may be incomplete mid-edit; only `POST .../publish` enforces the full,
    type-specific field set. `is_cross_midnight` is never client-settable — always
    server-derived from the time fields. `is_night_shift` IS client-settable: architecture
    §9.5 is explicit that it "is an explicit flag (night OT classification), not inferred
    solely from times" — unlike `is_cross_midnight`, which the same section says "must be
    consistent with start/end (already validated)"."""

    model_config = ConfigDict(extra="forbid")

    shift_type: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    effective_from: date | None = None
    start_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    end_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    window_start: str | None = Field(default=None, pattern=_TIME_PATTERN)
    window_end: str | None = Field(default=None, pattern=_TIME_PATTERN)
    core_start: str | None = Field(default=None, pattern=_TIME_PATTERN)
    core_end: str | None = Field(default=None, pattern=_TIME_PATTERN)
    required_minutes: int | None = Field(default=None, ge=0)
    scheduled_minutes: int | None = Field(default=None, ge=0)
    min_scheduled_minutes: int | None = Field(default=None, ge=0)
    max_scheduled_minutes: int | None = Field(default=None, ge=0)
    is_night_shift: bool = False
    is_ot_eligible: bool = False
    operates_on_holiday: bool = False
    operates_on_weekly_off: bool = False
    weekly_off_pattern_id: UUID | None = None
    breaks: list[ShiftBreakCreate] | None = None
    duty_blocks: list[ShiftDutyBlockCreate] | None = None

    @field_validator("shift_type")
    @classmethod
    def validate_shift_type(cls, value: str | None) -> str | None:
        if value is not None and value not in _SHIFT_VERSION_TYPES:
            raise ValueError(f"shift_type must be one of {_SHIFT_VERSION_TYPES}")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        # `NEW-01`/`SR-09` (execution gate §4) — this field previously had no validator at all
        # (`max_length=64` only), so a value like `IST` — the exact abbreviation an Indian HR user
        # would type — was accepted at create/update and failed only at calculation time as an
        # unhandled `ZoneInfoNotFoundError` -> HTTP 500. `NULL` remains valid: it is WD-06's
        # "inherit from branch/company" signal, not an invalid value, so it is excluded here
        # before the IANA check ever runs.
        if value is None:
            return None
        return validate_iana_timezone(value)


class ShiftVersionUpdate(BaseModel):
    """Draft-only PATCH (409 `SHIFT_VERSION_NOT_DRAFT` once published). `breaks`/
    `duty_blocks`, when present, **replace** the entire nested collection atomically — no
    separate sub-resource CRUD, since they have no independent lifecycle (mirrors
    `WeeklyOffPatternUpdate.rules`)."""

    model_config = ConfigDict(extra="forbid")

    shift_type: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    effective_from: date | None = None
    start_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    end_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    window_start: str | None = Field(default=None, pattern=_TIME_PATTERN)
    window_end: str | None = Field(default=None, pattern=_TIME_PATTERN)
    core_start: str | None = Field(default=None, pattern=_TIME_PATTERN)
    core_end: str | None = Field(default=None, pattern=_TIME_PATTERN)
    required_minutes: int | None = Field(default=None, ge=0)
    scheduled_minutes: int | None = Field(default=None, ge=0)
    min_scheduled_minutes: int | None = Field(default=None, ge=0)
    max_scheduled_minutes: int | None = Field(default=None, ge=0)
    is_night_shift: bool | None = None
    is_ot_eligible: bool | None = None
    operates_on_holiday: bool | None = None
    operates_on_weekly_off: bool | None = None
    weekly_off_pattern_id: UUID | None = None
    breaks: list[ShiftBreakCreate] | None = None
    duty_blocks: list[ShiftDutyBlockCreate] | None = None

    @field_validator("shift_type")
    @classmethod
    def validate_shift_type(cls, value: str | None) -> str | None:
        if value is not None and value not in _SHIFT_VERSION_TYPES:
            raise ValueError(f"shift_type must be one of {_SHIFT_VERSION_TYPES}")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_iana_timezone(value)


class ShiftVersionPublishRequest(BaseModel):
    """Body for `POST /shifts/{shift_id}/versions/{version_id}/publish`. `If-Match` (header,
    handled at the router layer) carries the draft's own `expected_version`;
    `expected_previous_version` is the **second** concurrency token in this two-token flow —
    required only when an open PUBLISHED version already exists for this shift, so it can be
    closed as part of the same publish (mirrors `create_policy_assignment`'s insert-new/
    close-previous idiom exactly, just with two tokens instead of one since two different rows
    are being mutated)."""

    model_config = ConfigDict(extra="forbid")

    publish_reason: str | None = None
    expected_previous_version: int | None = None


class ShiftVersionRead(BaseModel):
    id: UUID
    company_id: UUID
    shift_id: UUID
    status: str
    version: int
    effective_from: date | None
    effective_to: date | None
    shift_type: str | None
    timezone: str | None
    start_time: str | None
    end_time: str | None
    window_start: str | None
    window_end: str | None
    core_start: str | None
    core_end: str | None
    required_minutes: int | None
    scheduled_minutes: int | None
    min_scheduled_minutes: int | None
    max_scheduled_minutes: int | None
    is_night_shift: bool
    is_cross_midnight: bool
    is_ot_eligible: bool
    operates_on_holiday: bool
    operates_on_weekly_off: bool
    weekly_off_pattern_id: UUID | None
    publish_reason: str | None
    published_at: str | None
    published_by: UUID | None
    created_at: str
    updated_at: str
    breaks: list[ShiftBreakRead]
    duty_blocks: list[ShiftDutyBlockRead]


def shift_version_to_read(
    row: "ShiftVersion",
    breaks: list["ShiftBreak"],
    duty_blocks: list["ShiftDutyBlock"],
) -> ShiftVersionRead:
    return ShiftVersionRead(
        id=row.id,
        company_id=row.company_id,
        shift_id=row.shift_id,
        status=row.status,
        version=row.version,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        shift_type=row.shift_type,
        timezone=row.timezone,
        start_time=_format_time(row.start_time),
        end_time=_format_time(row.end_time),
        window_start=_format_time(row.window_start),
        window_end=_format_time(row.window_end),
        core_start=_format_time(row.core_start),
        core_end=_format_time(row.core_end),
        required_minutes=row.required_minutes,
        scheduled_minutes=row.scheduled_minutes,
        min_scheduled_minutes=row.min_scheduled_minutes,
        max_scheduled_minutes=row.max_scheduled_minutes,
        is_night_shift=row.is_night_shift,
        is_cross_midnight=row.is_cross_midnight,
        is_ot_eligible=row.is_ot_eligible,
        operates_on_holiday=row.operates_on_holiday,
        operates_on_weekly_off=row.operates_on_weekly_off,
        weekly_off_pattern_id=row.weekly_off_pattern_id,
        publish_reason=row.publish_reason,
        published_at=_format_timestamp(row.published_at),
        published_by=row.published_by,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
        breaks=[shift_break_to_read(b) for b in breaks],
        duty_blocks=[shift_duty_block_to_read(d) for d in duty_blocks],
    )


def shift_version_to_audit_dict(row: ShiftVersionRead) -> dict[str, Any]:
    return row.model_dump(mode="json")


def build_shift_version_update_values(patch: ShiftVersionUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied; `breaks`/`duty_blocks` are
    handled separately (full-replace), never passed through to the `shift_version` row
    update."""
    return {
        field: getattr(patch, field)
        for field in patch.model_fields_set
        if field not in ("breaks", "duty_blocks")
    }


# ---------------------------------------------------------------------------
# Workforce Calendar (W1) — HolidayCalendar, Holiday, WeeklyOffPattern,
# WorkCalendar, CalendarException, PolicyAssignment.
# docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §§6-8, 15-16.
# ---------------------------------------------------------------------------

_HOLIDAY_CALENDAR_KINDS = ("NATIONAL", "REGIONAL", "COMPANY", "LOCATION")
_HOLIDAY_TYPES = ("PUBLIC", "COMPANY", "OPTIONAL", "RESTRICTED", "WORKING_HOLIDAY")
_WEEKLY_OFF_PATTERN_KINDS = ("FIXED_WEEKDAYS", "NTH_WEEKDAY", "ALTERNATE", "CUSTOM")
_CALENDAR_EXCEPTION_TYPES = ("SPECIAL_WORKING", "SHUTDOWN", "SUBSTITUTE_HOLIDAY", "CANCEL_HOLIDAY")
_POLICY_KINDS = (
    "WORK_CALENDAR",
    "WEEKLY_OFF",
    "ATTENDANCE_POLICY",
    "OVERTIME_POLICY",
    "REGULARIZATION_POLICY",
    "LEAVE_POLICY",
)
_SCOPE_TYPES = (
    "COMPANY",
    "LEGAL_ENTITY",
    "BRANCH",
    "DEPARTMENT",
    "GRADE",
    "DESIGNATION",
    "SHIFT",
    "EMPLOYEE",
)
_CALENDAR_DAY_TYPES = ("WORKING", "WEEKLY_OFF", "HOLIDAY", "SPECIAL_WORKING", "SHUTDOWN")


class HolidayCalendarCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    kind: str = "COMPANY"
    state_code: str | None = Field(default=None, max_length=10)
    valid_from: date | None = None
    valid_to: date | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in _HOLIDAY_CALENDAR_KINDS:
            raise ValueError(f"kind must be one of {_HOLIDAY_CALENDAR_KINDS}")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> "HolidayCalendarCreate":
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_from > self.valid_to
        ):
            raise ValueError("valid_from must not be after valid_to")
        return self


class HolidayCalendarUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    kind: str | None = None
    state_code: str | None = Field(default=None, max_length=10)
    valid_from: date | None = None
    valid_to: date | None = None
    is_active: bool | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in _HOLIDAY_CALENDAR_KINDS:
            raise ValueError(f"kind must be one of {_HOLIDAY_CALENDAR_KINDS}")
        return value


class HolidayCalendarRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    code: str | None
    kind: str
    state_code: str | None
    valid_from: date | None
    valid_to: date | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def holiday_calendar_to_read(row: "HolidayCalendar") -> HolidayCalendarRead:
    return HolidayCalendarRead(
        id=row.id,
        company_id=row.company_id,
        name=row.name,
        code=row.code,
        kind=row.kind,
        state_code=row.state_code,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def holiday_calendar_to_audit_dict(row: HolidayCalendarRead) -> dict[str, Any]:
    return row.model_dump(mode="json")


def build_holiday_calendar_update_values(patch: HolidayCalendarUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


class HolidayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    name: str = Field(min_length=1, max_length=150)
    holiday_type: str = "PUBLIC"
    is_paid: bool = True
    is_working: bool = False
    region_note: str | None = Field(default=None, max_length=200)
    replaced_holiday_id: UUID | None = None

    @field_validator("holiday_type")
    @classmethod
    def validate_holiday_type(cls, value: str) -> str:
        if value not in _HOLIDAY_TYPES:
            raise ValueError(f"holiday_type must be one of {_HOLIDAY_TYPES}")
        return value


class HolidayUpdate(BaseModel):
    """Never accepts `date`/`calendar_id` — a holiday's date is immutable after creation
    (architecture §25: "no PATCH of used dates"). Correcting a wrong date is deactivate this
    row + create a new one, preserving history."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    holiday_type: str | None = None
    is_paid: bool | None = None
    is_working: bool | None = None
    region_note: str | None = Field(default=None, max_length=200)
    replaced_holiday_id: UUID | None = None
    is_active: bool | None = None

    @field_validator("holiday_type")
    @classmethod
    def validate_holiday_type(cls, value: str | None) -> str | None:
        if value is not None and value not in _HOLIDAY_TYPES:
            raise ValueError(f"holiday_type must be one of {_HOLIDAY_TYPES}")
        return value


class HolidayRead(BaseModel):
    id: UUID
    company_id: UUID
    calendar_id: UUID
    date: date
    name: str
    is_optional: bool
    holiday_type: str
    is_paid: bool
    is_working: bool
    region_note: str | None
    replaced_holiday_id: UUID | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def holiday_to_read(row: "Holiday") -> HolidayRead:
    return HolidayRead(
        id=row.id,
        company_id=row.company_id,
        calendar_id=row.calendar_id,
        date=row.date,
        name=row.name,
        is_optional=row.is_optional,
        holiday_type=row.holiday_type,
        is_paid=row.is_paid,
        is_working=row.is_working,
        region_note=row.region_note,
        replaced_holiday_id=row.replaced_holiday_id,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def holiday_to_audit_dict(row: HolidayRead) -> dict[str, Any]:
    return row.model_dump(mode="json")


def build_holiday_update_values(patch: HolidayUpdate) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        values[field] = getattr(patch, field)
    # `is_optional` is a deprecated shadow of `holiday_type == 'OPTIONAL'` (§7.2) — kept in
    # lockstep whenever `holiday_type` changes so old readers of the legacy column don't see
    # stale data.
    if "holiday_type" in values:
        values["is_optional"] = values["holiday_type"] == "OPTIONAL"
    return values


class WeeklyOffRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: int = Field(ge=0, le=6)
    nth_in_month: int | None = None
    cycle_start_date: date | None = None
    off_fraction: Decimal = Decimal("1.00")
    week_parity: str | None = None

    @field_validator("nth_in_month")
    @classmethod
    def validate_nth_in_month(cls, value: int | None) -> int | None:
        if value is not None and value not in (-1, 1, 2, 3, 4, 5):
            raise ValueError("nth_in_month must be one of -1, 1, 2, 3, 4, 5")
        return value

    @field_validator("off_fraction")
    @classmethod
    def validate_off_fraction(cls, value: Decimal) -> Decimal:
        if value not in (Decimal("0.50"), Decimal("1.00")):
            raise ValueError("off_fraction must be 0.50 or 1.00")
        return value

    @field_validator("week_parity")
    @classmethod
    def validate_week_parity(cls, value: str | None) -> str | None:
        if value is not None and value not in ("EVEN", "ODD"):
            raise ValueError("week_parity must be EVEN or ODD")
        return value


class WeeklyOffRuleRead(BaseModel):
    id: UUID
    weekday: int
    nth_in_month: int | None
    cycle_start_date: date | None
    off_fraction: Decimal
    week_parity: str | None


def weekly_off_rule_to_read(row: "WeeklyOffRule") -> WeeklyOffRuleRead:
    return WeeklyOffRuleRead(
        id=row.id,
        weekday=row.weekday,
        nth_in_month=row.nth_in_month,
        cycle_start_date=row.cycle_start_date,
        off_fraction=row.off_fraction,
        week_parity=row.week_parity,
    )


class WeeklyOffPatternCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    pattern_kind: str
    rules: list[WeeklyOffRuleInput] = Field(default_factory=list, min_length=1)

    @field_validator("pattern_kind")
    @classmethod
    def validate_pattern_kind(cls, value: str) -> str:
        if value not in _WEEKLY_OFF_PATTERN_KINDS:
            raise ValueError(f"pattern_kind must be one of {_WEEKLY_OFF_PATTERN_KINDS}")
        return value


class WeeklyOffPatternUpdate(BaseModel):
    """`rules`, when present, **replaces** the entire rule set atomically (simpler and safer
    than diffing individual rule rows for a typed-but-small child collection)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    pattern_kind: str | None = None
    rules: list[WeeklyOffRuleInput] | None = None
    is_active: bool | None = None

    @field_validator("pattern_kind")
    @classmethod
    def validate_pattern_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in _WEEKLY_OFF_PATTERN_KINDS:
            raise ValueError(f"pattern_kind must be one of {_WEEKLY_OFF_PATTERN_KINDS}")
        return value


class WeeklyOffPatternRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    code: str | None
    pattern_kind: str
    is_active: bool
    version: int
    created_at: str
    updated_at: str
    rules: list[WeeklyOffRuleRead]


def weekly_off_pattern_to_read(
    row: "WeeklyOffPattern", rules: list["WeeklyOffRule"]
) -> WeeklyOffPatternRead:
    return WeeklyOffPatternRead(
        id=row.id,
        company_id=row.company_id,
        name=row.name,
        code=row.code,
        pattern_kind=row.pattern_kind,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
        rules=[weekly_off_rule_to_read(r) for r in rules],
    )


def weekly_off_pattern_to_audit_dict(row: WeeklyOffPatternRead) -> dict[str, Any]:
    return row.model_dump(mode="json")


def build_weekly_off_pattern_update_values(patch: WeeklyOffPatternUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set if field != "rules"}


class WorkCalendarCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    description: str | None = None
    weekly_off_pattern_id: UUID | None = None
    restricted_holidays_are_off_by_default: bool = False
    holiday_calendar_ids: list[UUID] = Field(default_factory=list)


class WorkCalendarUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    description: str | None = None
    weekly_off_pattern_id: UUID | None = None
    restricted_holidays_are_off_by_default: bool | None = None
    holiday_calendar_ids: list[UUID] | None = None
    is_active: bool | None = None


class WorkCalendarRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    code: str | None
    description: str | None
    weekly_off_pattern_id: UUID | None
    restricted_holidays_are_off_by_default: bool
    is_active: bool
    version: int
    created_at: str
    updated_at: str
    holiday_calendar_ids: list[UUID]


def work_calendar_to_read(
    row: "WorkCalendar", holiday_calendar_ids: list[UUID]
) -> WorkCalendarRead:
    return WorkCalendarRead(
        id=row.id,
        company_id=row.company_id,
        name=row.name,
        code=row.code,
        description=row.description,
        weekly_off_pattern_id=row.weekly_off_pattern_id,
        restricted_holidays_are_off_by_default=row.restricted_holidays_are_off_by_default,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
        holiday_calendar_ids=holiday_calendar_ids,
    )


def work_calendar_to_audit_dict(row: WorkCalendarRead) -> dict[str, Any]:
    return row.model_dump(mode="json")


def build_work_calendar_update_values(patch: WorkCalendarUpdate) -> dict[str, Any]:
    return {
        field: getattr(patch, field)
        for field in patch.model_fields_set
        if field != "holiday_calendar_ids"
    }


class CalendarExceptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_date: date
    exception_type: str
    name: str | None = Field(default=None, max_length=150)
    reason: str | None = None
    is_paid: bool | None = None

    @field_validator("exception_type")
    @classmethod
    def validate_exception_type(cls, value: str) -> str:
        if value not in _CALENDAR_EXCEPTION_TYPES:
            raise ValueError(f"exception_type must be one of {_CALENDAR_EXCEPTION_TYPES}")
        return value


class CalendarExceptionUpdate(BaseModel):
    """Never accepts `exception_date`/`exception_type` — corrections are deactivate-then-
    insert (architecture §7.3), matching `HolidayUpdate`'s immutable-date posture."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=150)
    reason: str | None = None
    is_paid: bool | None = None
    is_active: bool | None = None


class CalendarExceptionRead(BaseModel):
    id: UUID
    company_id: UUID
    work_calendar_id: UUID
    exception_date: date
    exception_type: str
    name: str | None
    reason: str | None
    is_paid: bool | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def calendar_exception_to_read(row: "CalendarException") -> CalendarExceptionRead:
    return CalendarExceptionRead(
        id=row.id,
        company_id=row.company_id,
        work_calendar_id=row.work_calendar_id,
        exception_date=row.exception_date,
        exception_type=row.exception_type,
        name=row.name,
        reason=row.reason,
        is_paid=row.is_paid,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def calendar_exception_to_audit_dict(row: CalendarExceptionRead) -> dict[str, Any]:
    return row.model_dump(mode="json")


def build_calendar_exception_update_values(patch: CalendarExceptionUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


class PolicyAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_kind: str
    policy_id: UUID
    leave_type_id: UUID | None = None
    scope_type: str
    scope_id: UUID | None = None
    effective_from: date
    effective_to: date | None = None
    priority: int = 0
    reason: str | None = None

    @field_validator("policy_kind")
    @classmethod
    def validate_policy_kind(cls, value: str) -> str:
        if value not in _POLICY_KINDS:
            raise ValueError(f"policy_kind must be one of {_POLICY_KINDS} in this slice")
        return value

    @field_validator("scope_type")
    @classmethod
    def validate_scope_type(cls, value: str) -> str:
        if value not in _SCOPE_TYPES:
            raise ValueError(f"scope_type must be one of {_SCOPE_TYPES}")
        return value

    @model_validator(mode="after")
    def validate_scope_id_matches_scope_type(self) -> Self:
        if self.scope_type == "COMPANY" and self.scope_id is not None:
            raise ValueError("scope_id must be omitted when scope_type is COMPANY")
        if self.scope_type != "COMPANY" and self.scope_id is None:
            raise ValueError("scope_id is required unless scope_type is COMPANY")
        return self

    @model_validator(mode="after")
    def validate_leave_type_id_matches_policy_kind(self) -> Self:
        # LD-11: leave_type_id is the extra partition dimension only LEAVE_POLICY needs — a
        # company may have multiple simultaneous leave policies at the same scope, one per leave
        # type, unlike every other policy_kind where exactly one policy governs a scope.
        if self.policy_kind == "LEAVE_POLICY" and self.leave_type_id is None:
            raise ValueError("leave_type_id is required when policy_kind is LEAVE_POLICY")
        if self.policy_kind != "LEAVE_POLICY" and self.leave_type_id is not None:
            raise ValueError("leave_type_id must be omitted unless policy_kind is LEAVE_POLICY")
        return self


class PolicyAssignmentRead(BaseModel):
    id: UUID
    company_id: UUID
    policy_kind: str
    policy_id: UUID
    leave_type_id: UUID | None
    scope_type: str
    scope_id: UUID | None
    effective_from: date
    effective_to: date | None
    priority: int
    reason: str | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def policy_assignment_to_read(row: "PolicyAssignment") -> PolicyAssignmentRead:
    return PolicyAssignmentRead(
        id=row.id,
        company_id=row.company_id,
        policy_kind=row.policy_kind,
        policy_id=row.policy_id,
        leave_type_id=row.leave_type_id,
        scope_type=row.scope_type,
        scope_id=row.scope_id,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        priority=row.priority,
        reason=row.reason,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def policy_assignment_to_audit_dict(row: PolicyAssignmentRead) -> dict[str, Any]:
    return row.model_dump(mode="json")


class DayTypeRead(BaseModel):
    """Computed classification of a single date against a WorkCalendar — never persisted (no
    `AttendanceDay` exists yet). See `calendar_resolution.classify_work_calendar_date`."""

    date: date
    day_type: str
    holiday_name: str | None = None
    exception_type: str | None = None
    holiday_on_weekly_off: bool = False
    is_holiday_named: bool = False
    optional_holiday_name: str | None = None
    restricted_holiday_name: str | None = None
    # PAY-012 — set only when `day_type == "WEEKLY_OFF"`: `1.00` full day off, `0.50` half.
    weekly_off_fraction: Decimal | None = None
    # BUS-001 — set only for a day off because of a holiday (`HOLIDAY`, or `WEEKLY_OFF` with
    # `holiday_on_weekly_off`): the holiday's type (`SUBSTITUTE` for a substitute-holiday
    # exception) and its `is_paid` flag.
    holiday_type: str | None = None
    holiday_is_paid: bool | None = None


class CalendarResolutionRead(BaseModel):
    """Response for `GET /calendar-resolution?employee_id=&date=` — the full WD-09 precedence
    walk plus the resulting day-type classification, or `config_incomplete=true` (fail-closed,
    WD-21) when no WorkCalendar resolves for this employee+date."""

    employee_id: UUID
    date: date
    config_incomplete: bool
    work_calendar_id: UUID | None = None
    work_calendar_name: str | None = None
    resolved_scope_type: str | None = None
    weekly_off_pattern_id: UUID | None = None
    weekly_off_resolved_scope_type: str | None = None
    day_type: DayTypeRead | None = None
