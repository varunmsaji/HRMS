import type { AssignmentChangeType, WorkLocationType } from "@/lib/employee/types";

export interface AssignmentFormValues {
  effectiveFrom: string;
  changeType: AssignmentChangeType | "";
  changeReason: string;
  branchId: string;
  departmentId: string;
  designationId: string;
  gradeId: string;
  reportingManagerId: string;
  dottedLineManagerId: string;
  costCentreId: string;
  shiftId: string;
  workLocationType: WorkLocationType | "";
}

export type AssignmentFormErrors = Partial<Record<keyof AssignmentFormValues, string>>;

export function emptyAssignmentFormValues(defaultChangeType: AssignmentChangeType | "" = ""): AssignmentFormValues {
  return {
    effectiveFrom: "",
    changeType: defaultChangeType,
    changeReason: "",
    branchId: "",
    departmentId: "",
    designationId: "",
    gradeId: "",
    reportingManagerId: "",
    dottedLineManagerId: "",
    costCentreId: "",
    shiftId: "",
    workLocationType: "",
  };
}

/** Full payload for `POST /employees/{id}/assignments`. Blank optional fields are sent as
 * `null` — identical on the wire to omitting the key, since every optional field in
 * `AssignmentCreate` defaults to `None`; when a current assignment row exists, `null` is what
 * tells the server to carry the prior value forward. */
export function buildAssignmentCreatePayload(values: AssignmentFormValues): Record<string, unknown> {
  return {
    effective_from: values.effectiveFrom,
    change_type: values.changeType,
    change_reason: values.changeReason.trim() || null,
    branch_id: values.branchId || null,
    department_id: values.departmentId || null,
    designation_id: values.designationId || null,
    grade_id: values.gradeId || null,
    reporting_manager_id: values.reportingManagerId || null,
    dotted_line_manager_id: values.dottedLineManagerId || null,
    cost_centre_id: values.costCentreId || null,
    shift_id: values.shiftId || null,
    work_location_type: values.workLocationType || null,
  };
}

/** Client-side checks mirroring the service's own required-field rules
 * (`EmployeeAssignmentService.create_assignment`) — not exhaustive (reference-existence and
 * self-reporting checks are still enforced server-side), just enough to avoid an obvious
 * round-trip failure. */
export function validateAssignmentForm(
  values: AssignmentFormValues,
  hasCurrentAssignment: boolean,
): AssignmentFormErrors {
  const errors: AssignmentFormErrors = {};

  if (!values.effectiveFrom) errors.effectiveFrom = "Effective date is required.";
  if (!values.changeType) errors.changeType = "Select a change type.";

  if (values.changeType === "SHIFT_CHANGE" && !values.shiftId) {
    errors.shiftId = "Shift is required for a shift change.";
  }

  if (!hasCurrentAssignment) {
    if (!values.branchId) errors.branchId = "Branch is required for the first assignment.";
    if (!values.departmentId) errors.departmentId = "Department is required for the first assignment.";
    if (!values.designationId) errors.designationId = "Designation is required for the first assignment.";
  }

  return errors;
}

export const CHANGE_TYPE_LABELS: Record<AssignmentChangeType, string> = {
  INITIAL: "Initial placement",
  TRANSFER: "Transfer",
  PROMOTION: "Promotion",
  MANAGER_CHANGE: "Manager change",
  SHIFT_CHANGE: "Shift change",
};

export const WORK_LOCATION_LABELS: Record<WorkLocationType, string> = {
  OFFICE: "Office",
  WFH: "Work from home",
  HYBRID: "Hybrid",
  FIELD: "Field",
};
