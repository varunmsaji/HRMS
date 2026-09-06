import type {
  LeaveType,
  LeaveTypeUpdatePayload,
  StatutoryLeaveCategory,
} from "@/lib/leave-type/types";

export interface LeaveTypeFormValues {
  code: string;
  name: string;
  isPaidDefault: boolean;
  requiresBalance: boolean;
  isCompOff: boolean;
  statutoryCategory: StatutoryLeaveCategory | "";
}

export const EMPTY_LEAVE_TYPE_FORM_VALUES: LeaveTypeFormValues = {
  code: "",
  name: "",
  isPaidDefault: true,
  requiresBalance: true,
  isCompOff: false,
  statutoryCategory: "",
};

export interface LeaveTypeFormErrors {
  code?: string;
  name?: string;
}

export function validateLeaveTypeForm(values: LeaveTypeFormValues): LeaveTypeFormErrors {
  const errors: LeaveTypeFormErrors = {};
  if (!values.code.trim()) errors.code = "Code is required.";
  if (!values.name.trim()) errors.name = "Name is required.";
  return errors;
}

export function buildLeaveTypeCreatePayload(values: LeaveTypeFormValues): Record<string, unknown> {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    is_paid_default: values.isPaidDefault,
    requires_balance: values.requiresBalance,
    is_comp_off: values.isCompOff,
    statutory_category: values.statutoryCategory === "" ? null : values.statutoryCategory,
  };
}

export function leaveTypeToFormValues(leaveType: LeaveType): LeaveTypeFormValues {
  return {
    code: leaveType.code,
    name: leaveType.name,
    isPaidDefault: leaveType.is_paid_default,
    requiresBalance: leaveType.requires_balance,
    isCompOff: leaveType.is_comp_off,
    statutoryCategory: leaveType.statutory_category ?? "",
  };
}

/** `code` is immutable after creation (no field for it in `LeaveTypeUpdate`) — only name and the
 * remaining flags/category can change. */
export function buildLeaveTypeUpdatePatch(
  values: LeaveTypeFormValues,
  current: LeaveType,
): LeaveTypeUpdatePayload {
  const patch: LeaveTypeUpdatePayload = {};
  if (values.name.trim() !== current.name) patch.name = values.name.trim();
  if (values.isPaidDefault !== current.is_paid_default) patch.is_paid_default = values.isPaidDefault;
  if (values.requiresBalance !== current.requires_balance) {
    patch.requires_balance = values.requiresBalance;
  }
  if (values.isCompOff !== current.is_comp_off) patch.is_comp_off = values.isCompOff;
  const statutoryCategory = values.statutoryCategory === "" ? null : values.statutoryCategory;
  if (statutoryCategory !== current.statutory_category) {
    patch.statutory_category = statutoryCategory;
  }
  return patch;
}
