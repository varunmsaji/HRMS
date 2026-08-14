"""Pydantic request/response shapes for the organisation module."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Self
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from hrms.core.db.models.identity import Company

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from hrms.modules.organisation.models import (
        Branch,
        CompanySetupProgress,
        Department,
        Designation,
        Grade,
        LegalEntity,
        Shift,
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
    admin_password: str = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        if value not in available_timezones():
            raise ValueError("timezone must be a valid IANA time zone identifier")
        return value

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
        if value is not None and value not in available_timezones():
            raise ValueError("timezone must be a valid IANA time zone identifier")
        return value

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
    geofence_radius_m: int | None = Field(default=None, gt=0)

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
        if value is not None and value not in available_timezones():
            raise ValueError("timezone must be a valid IANA time zone identifier")
        return value


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
    geofence_radius_m: int | None = Field(default=None, gt=0)
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
        if value is not None and value not in available_timezones():
            raise ValueError("timezone must be a valid IANA time zone identifier")
        return value


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


class DepartmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    branch_id: UUID | None = None
    parent_id: UUID | None = None
    is_active: bool | None = None


class DepartmentRead(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    parent_id: UUID | None
    name: str
    code: str | None
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
    level: int | None = None
    min_ctc: int | None = Field(default=None, ge=0)
    max_ctc: int | None = Field(default=None, ge=0)
    notice_period_days: int | None = Field(default=None, ge=0)
    probation_days: int | None = Field(default=None, ge=0)
    approval_limit: int | None = Field(default=None, ge=0)


class GradeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    level: int | None = None
    min_ctc: int | None = Field(default=None, ge=0)
    max_ctc: int | None = Field(default=None, ge=0)
    notice_period_days: int | None = Field(default=None, ge=0)
    probation_days: int | None = Field(default=None, ge=0)
    approval_limit: int | None = Field(default=None, ge=0)
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
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    start_time: str = Field(pattern=_TIME_PATTERN)
    end_time: str = Field(pattern=_TIME_PATTERN)
    break_minutes_paid: int = Field(default=0, ge=0)
    break_minutes_unpaid: int = Field(default=0, ge=0)
    grace_in_minutes: int = Field(default=0, ge=0)
    grace_out_minutes: int = Field(default=0, ge=0)
    half_day_threshold_hours: Decimal | None = Field(default=None, ge=0)
    min_hours_full_day: Decimal | None = Field(default=None, ge=0)
    is_night_shift: bool = False
    is_cross_midnight: bool = False
    is_ot_eligible: bool = False


class ShiftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    start_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    end_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    break_minutes_paid: int | None = Field(default=None, ge=0)
    break_minutes_unpaid: int | None = Field(default=None, ge=0)
    grace_in_minutes: int | None = Field(default=None, ge=0)
    grace_out_minutes: int | None = Field(default=None, ge=0)
    half_day_threshold_hours: Decimal | None = Field(default=None, ge=0)
    min_hours_full_day: Decimal | None = Field(default=None, ge=0)
    is_night_shift: bool | None = None
    is_cross_midnight: bool | None = None
    is_ot_eligible: bool | None = None
    is_active: bool | None = None


class ShiftRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    code: str | None
    start_time: str
    end_time: str
    break_minutes_paid: int
    break_minutes_unpaid: int
    grace_in_minutes: int
    grace_out_minutes: int
    half_day_threshold_hours: Decimal | None
    min_hours_full_day: Decimal | None
    is_night_shift: bool
    is_cross_midnight: bool
    is_ot_eligible: bool
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def shift_to_read(shift: "Shift") -> ShiftRead:
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
    )


def shift_to_audit_dict(shift: ShiftRead) -> dict[str, Any]:
    return shift.model_dump(mode="json")


def build_shift_update_values(patch: ShiftUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — unset fields must not
    clobber existing values (mirrors `build_grade_update_values`). `start_time`/`end_time`
    are parsed from `"HH:MM"` to `datetime.time` here, mirroring `CompanyProfileUpdate`'s own
    `business_hours` handling."""
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        value = getattr(patch, field)
        if field in ("start_time", "end_time") and value is not None:
            value = _parse_time(value)
        values[field] = value
    return values
