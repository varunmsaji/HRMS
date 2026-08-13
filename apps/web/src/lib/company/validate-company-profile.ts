import type { CompanyProfile } from "@/lib/company/types";

export interface CompanyProfileFormValues {
  name: string;
  legalName: string;
  registrationNumber: string;
  industryCode: string;
  companySize: string;
  countryCode: string;
  currency: string;
  timezone: string;
  contactEmail: string;
  contactPhone: string;
  website: string;
  addressLine1: string;
  addressLine2: string;
  addressCity: string;
  addressState: string;
  addressPostalCode: string;
  addressCountryCode: string;
  languageCode: string;
  dateFormat: string;
  fiscalYearStartMonth: string;
  businessHoursStart: string;
  businessHoursEnd: string;
  logoUrl: string;
  primaryColor: string;
  workingDays: Record<string, boolean>;
}

export type CompanyProfileFormErrors = Partial<Record<keyof CompanyProfileFormValues, string>>;

const TIME_PATTERN = /^\d{2}:\d{2}$/;

export function profileToFormValues(profile: CompanyProfile): CompanyProfileFormValues {
  const workingDays: Record<string, boolean> = {};
  for (const day of profile.working_days) {
    workingDays[day.day] = day.is_working;
  }

  return {
    name: profile.name,
    legalName: profile.legal_name ?? "",
    registrationNumber: profile.registration_number ?? "",
    industryCode: profile.industry_code ?? "",
    companySize: profile.company_size ?? "",
    countryCode: profile.country_code,
    currency: profile.currency,
    timezone: profile.timezone,
    contactEmail: profile.contact?.email ?? "",
    contactPhone: profile.contact?.phone ?? "",
    website: profile.contact?.website ?? "",
    addressLine1: profile.address?.line1 ?? "",
    addressLine2: profile.address?.line2 ?? "",
    addressCity: profile.address?.city ?? "",
    addressState: profile.address?.state ?? "",
    addressPostalCode: profile.address?.postal_code ?? "",
    addressCountryCode: profile.address?.country_code ?? "",
    languageCode: profile.locale?.language_code ?? "en-IN",
    dateFormat: profile.locale?.date_format ?? "DD/MM/YYYY",
    fiscalYearStartMonth: String(profile.fiscal_year?.start_month ?? 4),
    businessHoursStart: profile.business_hours?.start_time ?? "",
    businessHoursEnd: profile.business_hours?.end_time ?? "",
    logoUrl: profile.branding?.logo_url ?? "",
    primaryColor: profile.branding?.theme?.primary_color ?? "",
    workingDays,
  };
}

export function buildProfilePatch(
  values: CompanyProfileFormValues,
  profile: CompanyProfile,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.name !== profile.name) patch.name = values.name;
  if (values.legalName !== (profile.legal_name ?? "")) {
    patch.legal_name = values.legalName || null;
  }
  if (values.registrationNumber !== (profile.registration_number ?? "")) {
    patch.registration_number = values.registrationNumber || null;
  }
  if (values.industryCode !== (profile.industry_code ?? "")) {
    patch.industry_code = values.industryCode || null;
  }
  if (values.companySize !== (profile.company_size ?? "")) {
    patch.company_size = values.companySize || null;
  }
  if (values.countryCode !== profile.country_code) patch.country_code = values.countryCode;
  if (values.currency !== profile.currency) patch.currency = values.currency;
  if (values.timezone !== profile.timezone) patch.timezone = values.timezone;

  const contactChanged =
    values.contactEmail !== (profile.contact?.email ?? "") ||
    values.contactPhone !== (profile.contact?.phone ?? "") ||
    values.website !== (profile.contact?.website ?? "");
  if (contactChanged) {
    patch.contact = {
      email: values.contactEmail || null,
      phone: values.contactPhone || null,
      website: values.website || null,
    };
  }

  const addressChanged =
    values.addressLine1 !== (profile.address?.line1 ?? "") ||
    values.addressLine2 !== (profile.address?.line2 ?? "") ||
    values.addressCity !== (profile.address?.city ?? "") ||
    values.addressState !== (profile.address?.state ?? "") ||
    values.addressPostalCode !== (profile.address?.postal_code ?? "") ||
    values.addressCountryCode !== (profile.address?.country_code ?? "");
  if (addressChanged) {
    patch.address = {
      line1: values.addressLine1 || null,
      line2: values.addressLine2 || null,
      city: values.addressCity || null,
      state: values.addressState || null,
      postal_code: values.addressPostalCode || null,
      country_code: values.addressCountryCode || null,
    };
  }

  const localeChanged =
    values.languageCode !== (profile.locale?.language_code ?? "") ||
    values.dateFormat !== (profile.locale?.date_format ?? "");
  if (localeChanged) {
    patch.locale = { language_code: values.languageCode, date_format: values.dateFormat };
  }

  const fiscalMonth = Number(values.fiscalYearStartMonth);
  if (fiscalMonth !== profile.fiscal_year?.start_month) {
    patch.fiscal_year = { start_month: fiscalMonth };
  }

  const workingDaysChanged = profile.working_days.some(
    (day) => values.workingDays[day.day] !== day.is_working,
  );
  if (workingDaysChanged) {
    patch.working_days = Object.entries(values.workingDays).map(([day, is_working]) => ({
      day,
      is_working,
      is_alternate: false,
    }));
  }

  const start = values.businessHoursStart;
  const end = values.businessHoursEnd;
  const hadHours = Boolean(profile.business_hours);
  const hasHours = Boolean(start && end);
  if (
    start !== (profile.business_hours?.start_time ?? "") ||
    end !== (profile.business_hours?.end_time ?? "")
  ) {
    patch.business_hours = hasHours ? { start_time: start, end_time: end } : null;
  } else if (!hasHours && hadHours) {
    patch.business_hours = null;
  }

  const brandingChanged =
    values.logoUrl !== (profile.branding?.logo_url ?? "") ||
    values.primaryColor !== (profile.branding?.theme?.primary_color ?? "");
  if (brandingChanged) {
    patch.branding = {
      logo_url: values.logoUrl || null,
      theme: values.primaryColor ? { primary_color: values.primaryColor } : null,
    };
  }

  return patch;
}

export function validateCompanyProfileForm(
  values: CompanyProfileFormValues,
): CompanyProfileFormErrors {
  const errors: CompanyProfileFormErrors = {};

  if (!values.name.trim()) errors.name = "Company name is required.";

  const fiscalMonth = Number(values.fiscalYearStartMonth);
  if (!Number.isInteger(fiscalMonth) || fiscalMonth < 1 || fiscalMonth > 12) {
    errors.fiscalYearStartMonth = "Fiscal year start month must be between 1 and 12.";
  }

  const workingCount = Object.values(values.workingDays).filter(Boolean).length;
  if (workingCount < 1) {
    errors.workingDays = "Select at least one working day.";
  }

  const hasStart = Boolean(values.businessHoursStart);
  const hasEnd = Boolean(values.businessHoursEnd);
  if (hasStart !== hasEnd) {
    errors.businessHoursStart = "Provide both start and end times, or leave both empty.";
    errors.businessHoursEnd = "Provide both start and end times, or leave both empty.";
  } else if (hasStart && hasEnd) {
    if (!TIME_PATTERN.test(values.businessHoursStart) || !TIME_PATTERN.test(values.businessHoursEnd)) {
      errors.businessHoursStart = "Use HH:mm format.";
      errors.businessHoursEnd = "Use HH:mm format.";
    } else if (values.businessHoursEnd <= values.businessHoursStart) {
      errors.businessHoursEnd = "End time must be later than start time.";
    }
  }

  return errors;
}
