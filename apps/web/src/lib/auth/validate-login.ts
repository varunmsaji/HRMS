import type { LoginRequest } from "@/lib/auth/types";
import { isValidEmail } from "@/lib/validation";

export interface LoginFormValues {
  /** An email address, or an employee ID (e.g. `EMP-0007`) together with `companyCode`. */
  identifier: string;
  companyCode: string;
  password: string;
}

export type LoginFormErrors = Partial<Record<keyof LoginFormValues, string>>;

/** Anything with an `@` is treated as an email; otherwise it is an employee ID, which needs the
 * company code too (employee IDs repeat across companies). */
export function isEmailIdentifier(identifier: string): boolean {
  return identifier.includes("@");
}

export function validateLoginForm(values: LoginFormValues): LoginFormErrors {
  const errors: LoginFormErrors = {};
  const identifier = values.identifier.trim();
  if (!identifier) {
    errors.identifier = "Email or employee ID is required.";
  } else if (isEmailIdentifier(identifier)) {
    if (!isValidEmail(identifier)) errors.identifier = "Enter a valid email address.";
  } else if (!values.companyCode.trim()) {
    errors.companyCode = "Company code is required to sign in with an employee ID.";
  }
  if (!values.password) errors.password = "Password is required.";
  return errors;
}

/** The `/auth/login` body for already-validated form values. */
export function toLoginRequest(values: LoginFormValues): LoginRequest {
  const identifier = values.identifier.trim();
  if (isEmailIdentifier(identifier)) return { email: identifier, password: values.password };
  return {
    company_code: values.companyCode.trim(),
    employee_code: identifier,
    password: values.password,
  };
}
