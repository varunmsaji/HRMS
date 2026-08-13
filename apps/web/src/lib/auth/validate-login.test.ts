import { describe, expect, it } from "vitest";

import { validateLoginForm } from "@/lib/auth/validate-login";

describe("validateLoginForm", () => {
  it("passes for a valid email and non-empty password", () => {
    expect(validateLoginForm({ email: "user@example.com", password: "anything" })).toEqual({});
  });

  it("requires an email", () => {
    const errors = validateLoginForm({ email: "", password: "anything" });
    expect(errors.email).toBeDefined();
  });

  it("rejects a malformed email", () => {
    const errors = validateLoginForm({ email: "not-an-email", password: "anything" });
    expect(errors.email).toBeDefined();
  });

  it("requires a password", () => {
    const errors = validateLoginForm({ email: "user@example.com", password: "" });
    expect(errors.password).toBeDefined();
  });
});
