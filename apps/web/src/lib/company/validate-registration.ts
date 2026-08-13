import { isPasswordStrongEnough, isValidEmail, passwordRequirementMessage } from "@/lib/validation";
import type { CompanyRegistrationRequest } from "@/lib/company/types";

export interface RegistrationFormValues {
  name: string;
  industryCode: string;
  countryCode: string;
  currency: string;
  timezone: string;
  fyStartMonth: number;
  companySize: string;
  adminFirstName: string;
  adminLastName: string;
  adminEmail: string;
  adminPassword: string;
  confirmPassword: string;
}

export const emptyRegistrationForm: RegistrationFormValues = {
  name: "",
  industryCode: "",
  countryCode: "IN",
  currency: "INR",
  timezone: "Asia/Kolkata",
  fyStartMonth: 4,
  companySize: "",
  adminFirstName: "",
  adminLastName: "",
  adminEmail: "",
  adminPassword: "",
  confirmPassword: "",
};

export type RegistrationFormErrors = Partial<Record<keyof RegistrationFormValues, string>>;

/** Client-side mirror of `CompanyRegistrationRequest`'s Pydantic validators — a fast first pass
 * only. The backend re-validates everything; this just avoids an obviously-doomed round trip. */
export function validateRegistrationForm(values: RegistrationFormValues): RegistrationFormErrors {
  const errors: RegistrationFormErrors = {};

  if (!values.name.trim()) {
    errors.name = "Company name is required.";
  } else if (values.name.length > 200) {
    errors.name = "Must be 200 characters or fewer.";
  }

  if (!values.adminFirstName.trim()) errors.adminFirstName = "First name is required.";
  if (!values.adminLastName.trim()) errors.adminLastName = "Last name is required.";

  if (!values.adminEmail.trim()) {
    errors.adminEmail = "Email is required.";
  } else if (!isValidEmail(values.adminEmail)) {
    errors.adminEmail = "Enter a valid email address.";
  }

  if (!values.adminPassword) {
    errors.adminPassword = "Password is required.";
  } else if (!isPasswordStrongEnough(values.adminPassword)) {
    errors.adminPassword = passwordRequirementMessage();
  }

  if (values.confirmPassword !== values.adminPassword) {
    errors.confirmPassword = "Passwords do not match.";
  }

  if (values.countryCode && !/^[A-Za-z]{2}$/.test(values.countryCode)) {
    errors.countryCode = "Use a 2-letter country code.";
  }

  if (values.currency && !/^[A-Za-z]{3}$/.test(values.currency)) {
    errors.currency = "Use a 3-letter currency code.";
  }

  if (!values.timezone) errors.timezone = "Select a timezone.";

  return errors;
}

export function buildRegistrationPayload(values: RegistrationFormValues): CompanyRegistrationRequest {
  return {
    name: values.name.trim(),
    industry_code: values.industryCode.trim() || undefined,
    country_code: values.countryCode.trim().toUpperCase() || undefined,
    currency: values.currency.trim().toUpperCase() || undefined,
    timezone: values.timezone || undefined,
    fy_start_month: values.fyStartMonth,
    company_size: values.companySize || undefined,
    admin_first_name: values.adminFirstName.trim(),
    admin_last_name: values.adminLastName.trim(),
    admin_email: values.adminEmail.trim(),
    admin_password: values.adminPassword,
  };
}
