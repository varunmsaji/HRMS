export interface EmploymentFormValues {
  legalEntityId: string;
  joiningDate: string;
}

export type EmploymentFormErrors = Partial<Record<keyof EmploymentFormValues, string>>;

export const EMPTY_EMPLOYMENT_FORM_VALUES: EmploymentFormValues = {
  legalEntityId: "",
  joiningDate: "",
};

/** Full payload for `POST /employees/{id}/employments` — covers both first hire and rehire. */
export function buildEmploymentCreatePayload(values: EmploymentFormValues): Record<string, unknown> {
  return {
    legal_entity_id: values.legalEntityId,
    joining_date: values.joiningDate,
  };
}

export function validateEmploymentForm(values: EmploymentFormValues): EmploymentFormErrors {
  const errors: EmploymentFormErrors = {};
  if (!values.legalEntityId) errors.legalEntityId = "Select a legal entity.";
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
}

/** Diff-only payload for `PATCH /employees/{id}/employments/{employmentId}` — only
 * `legal_entity_id` is correctable post-creation. */
export function buildEmploymentCorrectionPatch(
  values: EmploymentCorrectionValues,
  employment: { legal_entity_id: string },
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.legalEntityId && values.legalEntityId !== employment.legal_entity_id) {
    patch.legal_entity_id = values.legalEntityId;
  }
  return patch;
}
