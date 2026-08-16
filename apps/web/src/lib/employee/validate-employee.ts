import type { Employee } from "@/lib/employee/types";

export interface EmployeeFormValues {
  firstName: string;
  middleName: string;
  lastName: string;
  dateOfBirth: string;
  gender: string;
  bloodGroup: string;
  maritalStatus: string;
  nationality: string;
  personalEmail: string;
  personalMobile: string;
}

export type EmployeeFormErrors = Partial<Record<keyof EmployeeFormValues, string>>;

export const EMPTY_EMPLOYEE_FORM_VALUES: EmployeeFormValues = {
  firstName: "",
  middleName: "",
  lastName: "",
  dateOfBirth: "",
  gender: "",
  bloodGroup: "",
  maritalStatus: "",
  nationality: "",
  personalEmail: "",
  personalMobile: "",
};

// EmployeeCreate/EmployeeUpdate store gender/blood_group/marital_status as free-text (max-length
// only, no backend enum) — these are just convenience options for the picker, not a schema.
export const GENDER_OPTIONS = ["Male", "Female", "Other", "Prefer not to say"];
export const BLOOD_GROUP_OPTIONS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];
export const MARITAL_STATUS_OPTIONS = ["Single", "Married", "Divorced", "Widowed"];

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function employeeToFormValues(employee: Employee): EmployeeFormValues {
  return {
    firstName: employee.first_name,
    middleName: employee.middle_name ?? "",
    lastName: employee.last_name ?? "",
    dateOfBirth: employee.date_of_birth ?? "",
    gender: employee.gender ?? "",
    bloodGroup: employee.blood_group ?? "",
    maritalStatus: employee.marital_status ?? "",
    nationality: employee.nationality ?? "",
    personalEmail: employee.personal_email ?? "",
    personalMobile: employee.personal_mobile ?? "",
  };
}

/** Full payload for `POST /employees` — every field the form collects. */
export function buildCreatePayload(values: EmployeeFormValues): Record<string, unknown> {
  return {
    first_name: values.firstName.trim(),
    middle_name: values.middleName.trim() || null,
    last_name: values.lastName.trim() || null,
    date_of_birth: values.dateOfBirth || null,
    gender: values.gender.trim() || null,
    blood_group: values.bloodGroup.trim() || null,
    marital_status: values.maritalStatus.trim() || null,
    nationality: values.nationality.trim() || null,
    personal_email: values.personalEmail.trim() || null,
    personal_mobile: values.personalMobile.trim() || null,
  };
}

/** Diff-only payload for `PATCH /employees/{id}`. */
export function buildUpdatePatch(values: EmployeeFormValues, employee: Employee): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.firstName.trim() !== employee.first_name) patch.first_name = values.firstName.trim();

  const fieldMap: Array<[keyof EmployeeFormValues, keyof Employee, string]> = [
    ["middleName", "middle_name", "middle_name"],
    ["lastName", "last_name", "last_name"],
    ["gender", "gender", "gender"],
    ["bloodGroup", "blood_group", "blood_group"],
    ["maritalStatus", "marital_status", "marital_status"],
    ["nationality", "nationality", "nationality"],
    ["personalEmail", "personal_email", "personal_email"],
    ["personalMobile", "personal_mobile", "personal_mobile"],
  ];

  for (const [formKey, entityKey, apiKey] of fieldMap) {
    const current = (employee[entityKey] as string | null) ?? "";
    const next = values[formKey].trim();
    if (next !== current) {
      patch[apiKey] = next || null;
    }
  }

  const currentDob = employee.date_of_birth ?? "";
  if (values.dateOfBirth !== currentDob) {
    patch.date_of_birth = values.dateOfBirth || null;
  }

  return patch;
}

export function validateEmployeeForm(values: EmployeeFormValues): EmployeeFormErrors {
  const errors: EmployeeFormErrors = {};

  if (!values.firstName.trim()) {
    errors.firstName = "First name is required.";
  }

  if (values.personalEmail.trim() && !EMAIL_PATTERN.test(values.personalEmail.trim())) {
    errors.personalEmail = "Enter a valid email address.";
  }

  return errors;
}
