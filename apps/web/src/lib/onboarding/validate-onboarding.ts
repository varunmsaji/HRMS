export interface OnboardingCaseFormValues {
  candidateFirstName: string;
  candidateLastName: string;
  personalEmail: string;
  personalMobile: string;
  designationId: string;
  departmentId: string;
  branchId: string;
  legalEntityId: string;
  proposedJoiningDate: string;
}

export type OnboardingCaseFormErrors = Partial<Record<keyof OnboardingCaseFormValues, string>>;

export const EMPTY_ONBOARDING_CASE_FORM_VALUES: OnboardingCaseFormValues = {
  candidateFirstName: "",
  candidateLastName: "",
  personalEmail: "",
  personalMobile: "",
  designationId: "",
  departmentId: "",
  branchId: "",
  legalEntityId: "",
  proposedJoiningDate: "",
};

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateOnboardingCaseForm(
  values: OnboardingCaseFormValues,
): OnboardingCaseFormErrors {
  const errors: OnboardingCaseFormErrors = {};

  if (!values.candidateFirstName.trim()) {
    errors.candidateFirstName = "First name is required.";
  }
  if (!values.personalEmail.trim()) {
    errors.personalEmail = "Personal email is required.";
  } else if (!EMAIL_PATTERN.test(values.personalEmail.trim())) {
    errors.personalEmail = "Enter a valid email address.";
  }
  if (!values.proposedJoiningDate) {
    errors.proposedJoiningDate = "Proposed joining date is required.";
  }

  return errors;
}

/** Full payload for `POST /onboarding-cases`. */
export function buildCreatePayload(values: OnboardingCaseFormValues): Record<string, unknown> {
  return {
    candidate_first_name: values.candidateFirstName.trim(),
    candidate_last_name: values.candidateLastName.trim() || null,
    personal_email: values.personalEmail.trim(),
    personal_mobile: values.personalMobile.trim() || null,
    designation_id: values.designationId || null,
    department_id: values.departmentId || null,
    branch_id: values.branchId || null,
    legal_entity_id: values.legalEntityId || null,
    proposed_joining_date: values.proposedJoiningDate,
  };
}
