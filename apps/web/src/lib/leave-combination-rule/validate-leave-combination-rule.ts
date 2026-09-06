import type { LeaveCombinationRuleCreatePayload } from "@/lib/leave-combination-rule/types";

export interface LeaveCombinationRuleFormValues {
  leaveTypeIdA: string;
  leaveTypeIdB: string;
  allowed: boolean;
  reason: string;
}

export const EMPTY_LEAVE_COMBINATION_RULE_FORM_VALUES: LeaveCombinationRuleFormValues = {
  leaveTypeIdA: "",
  leaveTypeIdB: "",
  allowed: false,
  reason: "",
};

export interface LeaveCombinationRuleFormErrors {
  leaveTypeIdA?: string;
  leaveTypeIdB?: string;
}

export function validateLeaveCombinationRuleForm(
  values: LeaveCombinationRuleFormValues,
): LeaveCombinationRuleFormErrors {
  const errors: LeaveCombinationRuleFormErrors = {};
  if (!values.leaveTypeIdA) errors.leaveTypeIdA = "Choose a leave type.";
  if (!values.leaveTypeIdB) errors.leaveTypeIdB = "Choose a leave type.";
  if (values.leaveTypeIdA && values.leaveTypeIdA === values.leaveTypeIdB) {
    errors.leaveTypeIdB = "Choose a different leave type than the first one.";
  }
  return errors;
}

export function buildLeaveCombinationRuleCreatePayload(
  values: LeaveCombinationRuleFormValues,
): LeaveCombinationRuleCreatePayload {
  return {
    leave_type_id_a: values.leaveTypeIdA,
    leave_type_id_b: values.leaveTypeIdB,
    allowed: values.allowed,
    reason: values.reason.trim() || null,
  };
}
