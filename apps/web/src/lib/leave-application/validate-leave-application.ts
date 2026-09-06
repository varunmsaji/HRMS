import type {
  LeaveApplicationCreatePayload,
  LeaveHalfDay,
} from "@/lib/leave-application/types";

export interface LeaveApplicationFormValues {
  leaveTypeId: string;
  startDate: string;
  endDate: string;
  halfDay: LeaveHalfDay | "";
  reason: string;
  attachmentReference: string;
  expectedDeliveryDate: string;
}

export type LeaveApplicationFormErrors = Partial<
  Record<"leaveTypeId" | "startDate" | "endDate" | "reason" | "attachment", string>
>;

export function emptyLeaveApplicationFormValues(
  overrides?: Partial<LeaveApplicationFormValues>,
): LeaveApplicationFormValues {
  return {
    leaveTypeId: "",
    startDate: "",
    endDate: "",
    halfDay: "",
    reason: "",
    attachmentReference: "",
    expectedDeliveryDate: "",
    ...overrides,
  };
}

/** Client-side checks only cover what's true regardless of policy config —
 * `reason_required`/`attachment_required`/`half_day_allowed`/balance sufficiency are
 * `LeavePolicyVersion` fields an ordinary employee's browser cannot read before submitting. The
 * backend remains the source of truth and returns a 422 with a field-level error the dialog
 * surfaces via `getFieldError`, same pattern as `RegularizationRequestDialog`. */
export function validateLeaveApplicationForm(
  values: LeaveApplicationFormValues,
): LeaveApplicationFormErrors {
  const errors: LeaveApplicationFormErrors = {};
  if (!values.leaveTypeId) errors.leaveTypeId = "Choose a leave type.";
  if (!values.startDate) errors.startDate = "Choose a start date.";
  if (!values.endDate) errors.endDate = "Choose an end date.";
  if (values.startDate && values.endDate && values.endDate < values.startDate) {
    errors.endDate = "End date must not be before start date.";
  }
  return errors;
}

export function buildLeaveApplicationCreatePayload(
  values: LeaveApplicationFormValues,
  employeeId?: string,
): LeaveApplicationCreatePayload {
  const payload: LeaveApplicationCreatePayload = {
    leave_type_id: values.leaveTypeId,
    start_date: values.startDate,
    end_date: values.endDate,
    reason: values.reason.trim() || undefined,
    attachment_reference: values.attachmentReference.trim() || undefined,
    expected_delivery_date: values.expectedDeliveryDate || undefined,
  };
  if (employeeId) payload.employee_id = employeeId;
  if (values.halfDay) payload.half_day = values.halfDay;
  return payload;
}
