import { describe, expect, it } from "vitest";

import { toLoginRequest, validateLoginForm } from "@/lib/auth/validate-login";

const base = { identifier: "user@example.com", companyCode: "", password: "anything" };

describe("validateLoginForm", () => {
  it("passes for a valid email and non-empty password", () => {
    expect(validateLoginForm(base)).toEqual({});
  });

  it("requires an email or employee ID", () => {
    const errors = validateLoginForm({ ...base, identifier: "" });
    expect(errors.identifier).toBeDefined();
  });

  it("rejects a malformed email", () => {
    const errors = validateLoginForm({ ...base, identifier: "not@an-email" });
    expect(errors.identifier).toBeDefined();
  });

  it("requires a company code with an employee ID", () => {
    const errors = validateLoginForm({ ...base, identifier: "EMP-0007" });
    expect(errors.companyCode).toBeDefined();
    expect(validateLoginForm({ ...base, identifier: "EMP-0007", companyCode: "ACME" })).toEqual({});
  });

  it("requires a password", () => {
    const errors = validateLoginForm({ ...base, password: "" });
    expect(errors.password).toBeDefined();
  });
});

describe("toLoginRequest", () => {
  it("sends an email login for an email", () => {
    expect(toLoginRequest({ ...base, identifier: " user@example.com ", companyCode: "ACME" })).toEqual({
      email: "user@example.com",
      password: "anything",
    });
  });

  it("sends the company code and employee ID otherwise", () => {
    expect(toLoginRequest({ ...base, identifier: " EMP-0007 ", companyCode: " acme " })).toEqual({
      company_code: "acme",
      employee_code: "EMP-0007",
      password: "anything",
    });
  });
});
