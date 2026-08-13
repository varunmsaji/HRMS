import { describe, expect, it } from "vitest";

import type { CompanyProfile } from "@/lib/company/types";
import {
  buildProfilePatch,
  profileToFormValues,
  validateCompanyProfileForm,
} from "@/lib/company/validate-company-profile";

const profile: CompanyProfile = {
  id: "1",
  name: "Acme",
  legal_name: null,
  registration_number: null,
  subdomain: null,
  contact: { email: null, phone: null, website: null },
  address: {
    line1: null,
    line2: null,
    city: null,
    state: null,
    postal_code: null,
    country_code: null,
  },
  industry_code: null,
  company_size: null,
  country_code: "IN",
  currency: "INR",
  timezone: "Asia/Kolkata",
  locale: { language_code: "en-IN", date_format: "DD/MM/YYYY" },
  fiscal_year: { start_month: 4 },
  working_days: [
    { day: "MON", is_working: true, is_alternate: false },
    { day: "TUE", is_working: true, is_alternate: false },
    { day: "WED", is_working: true, is_alternate: false },
    { day: "THU", is_working: true, is_alternate: false },
    { day: "FRI", is_working: true, is_alternate: false },
    { day: "SAT", is_working: false, is_alternate: false },
    { day: "SUN", is_working: false, is_alternate: false },
  ],
  business_hours: null,
  branding: { logo_url: null, theme: null },
  status: "TRIAL",
  primary_legal_entity: null,
  onboarded_at: null,
  trial_ends_at: null,
  version: 1,
};

describe("validate-company-profile", () => {
  it("maps profile to form values and back into a patch", () => {
    const values = profileToFormValues(profile);
    values.legalName = "Acme Private Limited";
    const patch = buildProfilePatch(values, profile);
    expect(patch).toEqual({ legal_name: "Acme Private Limited" });
  });

  it("rejects zero working days", () => {
    const values = profileToFormValues(profile);
    for (const day of Object.keys(values.workingDays)) {
      values.workingDays[day] = false;
    }
    const errors = validateCompanyProfileForm(values);
    expect(errors.workingDays).toBeTruthy();
  });

  it("rejects invalid business hours", () => {
    const values = profileToFormValues(profile);
    values.businessHoursStart = "18:00";
    values.businessHoursEnd = "09:00";
    const errors = validateCompanyProfileForm(values);
    expect(errors.businessHoursEnd).toBeTruthy();
  });
});
