import type { PayBasis } from "@/lib/employee/types";

export interface EmploymentFormValues {
  legalEntityId: string;
  joiningDate: string;
  probationEndDate: string;
  payBasis: PayBasis;
}

export type EmploymentFormErrors = Partial<Record<keyof EmploymentFormValues, string>>;

export const EMPTY_EMPLOYMENT_FORM_VALUES: EmploymentFormValues = {
  legalEntityId: "",
  joiningDate: "",
  probationEndDate: "",
  payBasis: "MONTHLY",
};

/** Full payload for `POST /employees/{id}/employments` — covers both first hire and rehire.
 * `probation_end_date` is optional: the last day of probation. Monthly leave accrual leaves out
 * the days up to it, and confirming the employee records it if none is set. */
export function buildEmploymentCreatePayload(values: EmploymentFormValues): Record<string, unknown> {
  return {
    legal_entity_id: values.legalEntityId,
    joining_date: values.joiningDate,
    probation_end_date: values.probationEndDate || null,
    pay_basis: values.payBasis,
  };
}

export function validateEmploymentForm(values: EmploymentFormValues): EmploymentFormErrors {
  const errors: EmploymentFormErrors = {};
  if (!values.legalEntityId) errors.legalEntityId = "Select a company.";
  if (!values.joiningDate) errors.joiningDate = "Joining date is required.";
  return errors;
}

export interface TerminateFormValues {
  lastWorkingDay: string;
}

export const EMPTY_TERMINATE_FORM_VALUES: TerminateFormValues = { lastWorkingDay: "" };

export function validateTerminateForm(values: TerminateFormValues): Partial<Record<"lastWorkingDay", string>> {
  const errors: Partial<Record<"lastWorkingDay", string>> = {};
  if (!values.lastWorkingDay) errors.lastWorkingDay = "Last working day is required.";
  return errors;
}

export interface EmploymentCorrectionValues {
  legalEntityId: string;
  probationEndDate: string;
  payBasis: PayBasis;
}

/** Diff-only payload for `PATCH /employees/{id}/employments/{employmentId}` — only
 * `legal_entity_id`, `probation_end_date` and `pay_basis` are correctable post-creation
 * (see `EmploymentUpdate` on the backend). */
export function buildEmploymentCorrectionPatch(
  values: EmploymentCorrectionValues,
  employment: { legal_entity_id: string; probation_end_date: string | null; pay_basis: PayBasis },
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.legalEntityId && values.legalEntityId !== employment.legal_entity_id) {
    patch.legal_entity_id = values.legalEntityId;
  }
  const probationEndDate = values.probationEndDate || null;
  if (probationEndDate !== employment.probation_end_date) {
    patch.probation_end_date = probationEndDate;
  }
  if (values.payBasis !== employment.pay_basis) {
    patch.pay_basis = values.payBasis;
  }
  return patch;
}
