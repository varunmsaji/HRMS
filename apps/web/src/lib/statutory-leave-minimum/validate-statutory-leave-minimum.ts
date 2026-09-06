import type { StatutoryLeaveCategory } from "@/lib/leave-type/types";
import type { StatutoryLeaveMinimumCreatePayload } from "@/lib/statutory-leave-minimum/types";

export interface StatutoryLeaveMinimumFormValues {
  stateCode: string;
  establishmentType: string;
  leaveCategory: StatutoryLeaveCategory | "";
  minDaysPerYear: string;
  note: string;
}

export const EMPTY_STATUTORY_LEAVE_MINIMUM_FORM_VALUES: StatutoryLeaveMinimumFormValues = {
  stateCode: "",
  establishmentType: "",
  leaveCategory: "",
  minDaysPerYear: "",
  note: "",
};

export interface StatutoryLeaveMinimumFormErrors {
  leaveCategory?: string;
  minDaysPerYear?: string;
}

export function validateStatutoryLeaveMinimumForm(
  values: StatutoryLeaveMinimumFormValues,
): StatutoryLeaveMinimumFormErrors {
  const errors: StatutoryLeaveMinimumFormErrors = {};
  if (!values.leaveCategory) errors.leaveCategory = "Choose a leave category.";
  const days = Number(values.minDaysPerYear);
  if (!values.minDaysPerYear.trim() || Number.isNaN(days) || days <= 0) {
    errors.minDaysPerYear = "Enter a number of days greater than 0.";
  }
  return errors;
}

export function buildStatutoryLeaveMinimumCreatePayload(
  values: StatutoryLeaveMinimumFormValues,
): StatutoryLeaveMinimumCreatePayload {
  return {
    state_code: values.stateCode.trim() || null,
    establishment_type: values.establishmentType.trim() || null,
    leave_category: values.leaveCategory as StatutoryLeaveCategory,
    min_days_per_year: values.minDaysPerYear.trim(),
    note: values.note.trim() || null,
  };
}
