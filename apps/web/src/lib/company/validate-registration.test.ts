import { describe, expect, it } from "vitest";

import {
  buildRegistrationPayload,
  emptyRegistrationForm,
  validateRegistrationForm,
  type RegistrationFormValues,
} from "@/lib/company/validate-registration";

function values(overrides: Partial<RegistrationFormValues> = {}): RegistrationFormValues {
  return {
    ...emptyRegistrationForm,
    name: "Acme Manufacturing",
    adminFirstName: "Priya",
    adminLastName: "Sharma",
    adminEmail: "priya@acme.example",
    adminPassword: "letmein1",
    confirmPassword: "letmein1",
    ...overrides,
  };
}

describe("validateRegistrationForm", () => {
  it("passes for a fully valid form", () => {
    expect(validateRegistrationForm(values())).toEqual({});
  });

  it("requires the company name", () => {
    const errors = validateRegistrationForm(values({ name: "  " }));
    expect(errors.name).toBeDefined();
  });

  it("requires admin first and last name", () => {
    const errors = validateRegistrationForm(values({ adminFirstName: "", adminLastName: "" }));
    expect(errors.adminFirstName).toBeDefined();
    expect(errors.adminLastName).toBeDefined();
  });

  it("rejects an invalid email", () => {
    const errors = validateRegistrationForm(values({ adminEmail: "not-an-email" }));
    expect(errors.adminEmail).toBeDefined();
  });

  it("rejects a password shorter than 8 characters", () => {
    const errors = validateRegistrationForm(values({ adminPassword: "a1", confirmPassword: "a1" }));
    expect(errors.adminPassword).toBeDefined();
  });

  it("rejects a password without a digit", () => {
    const errors = validateRegistrationForm(values({ adminPassword: "abcdefgh", confirmPassword: "abcdefgh" }));
    expect(errors.adminPassword).toBeDefined();
  });

  it("rejects mismatched password confirmation", () => {
    const errors = validateRegistrationForm(values({ confirmPassword: "different1" }));
    expect(errors.confirmPassword).toBeDefined();
  });

  it("rejects a country code that isn't 2 letters", () => {
    const errors = validateRegistrationForm(values({ countryCode: "IND" }));
    expect(errors.countryCode).toBeDefined();
  });

  it("rejects a currency code that isn't 3 letters", () => {
    const errors = validateRegistrationForm(values({ currency: "RS" }));
    expect(errors.currency).toBeDefined();
  });
});

describe("buildRegistrationPayload", () => {
  it("omits optional empty fields so the backend applies its own defaults", () => {
    const payload = buildRegistrationPayload(values({ industryCode: "", companySize: "" }));
    expect(payload.industry_code).toBeUndefined();
    expect(payload.company_size).toBeUndefined();
  });

  it("trims and uppercases codes, and carries required fields through", () => {
    const payload = buildRegistrationPayload(
      values({ name: "  Acme  ", countryCode: "in", currency: "inr" }),
    );
    expect(payload.name).toBe("Acme");
    expect(payload.country_code).toBe("IN");
    expect(payload.currency).toBe("INR");
    expect(payload.admin_email).toBe("priya@acme.example");
  });
});
