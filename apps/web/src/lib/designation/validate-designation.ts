import type { Designation } from "@/lib/designation/types";

export interface DesignationFormValues {
  title: string;
  departmentId: string;
  gradeId: string;
}

export type DesignationFormErrors = Partial<Record<keyof DesignationFormValues, string>>;

export const EMPTY_DESIGNATION_FORM_VALUES: DesignationFormValues = {
  title: "",
  departmentId: "",
  gradeId: "",
};

export function designationToFormValues(designation: Designation): DesignationFormValues {
  return {
    title: designation.title,
    departmentId: designation.department_id ?? "",
    gradeId: designation.grade_id ?? "",
  };
}

/** Full payload for `POST /designations` — every field the form collects. */
export function buildCreatePayload(values: DesignationFormValues): Record<string, unknown> {
  return {
    title: values.title.trim(),
    department_id: values.departmentId || null,
    grade_id: values.gradeId || null,
  };
}

/** Diff-only payload for `PATCH /designations/{id}` — mirrors `buildUpdatePatch` for Department. */
export function buildUpdatePatch(
  values: DesignationFormValues,
  designation: Designation,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.title.trim() !== designation.title) patch.title = values.title.trim();


  const currentDepartmentId = designation.department_id ?? "";
  if (values.departmentId !== currentDepartmentId) patch.department_id = values.departmentId || null;

  const currentGradeId = designation.grade_id ?? "";
  if (values.gradeId !== currentGradeId) patch.grade_id = values.gradeId || null;

  return patch;
}

export function validateDesignationForm(values: DesignationFormValues): DesignationFormErrors {
  const errors: DesignationFormErrors = {};

  if (!values.title.trim()) {
    errors.title = "Designation title is required.";
  }

  return errors;
}
