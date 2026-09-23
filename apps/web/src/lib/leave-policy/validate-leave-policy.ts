import type { ErrorDetail } from "@/lib/api/types";
import type { LeavePolicy, LeavePolicyVersion } from "@/lib/leave-policy/types";

// ---------------------------------------------------------------------------
// Identity form (leave type / name / code) — leave_type_id is fixed at creation, never edited
// (LD-10: the binding doesn't change across a policy's versions).
// ---------------------------------------------------------------------------

export interface LeavePolicyFormValues {
  leaveTypeId: string;
  name: string;
  code: string;
}

export const EMPTY_LEAVE_POLICY_FORM_VALUES: LeavePolicyFormValues = {
  leaveTypeId: "",
  name: "",
  code: "",
};

export interface LeavePolicyFormErrors {
  leaveTypeId?: string;
  name?: string;
  code?: string;
}

export function validateLeavePolicyForm(values: LeavePolicyFormValues): LeavePolicyFormErrors {
  const errors: LeavePolicyFormErrors = {};
  if (!values.leaveTypeId) errors.leaveTypeId = "Choose a leave type.";
  if (!values.name.trim()) errors.name = "Name is required.";
  return errors;
}

export function buildLeavePolicyCreatePayload(values: LeavePolicyFormValues): Record<string, unknown> {
  return {
    leave_type_id: values.leaveTypeId,
    name: values.name.trim(),
    code: values.code.trim() || null,
  };
}

export function buildLeavePolicyUpdatePatch(
  values: LeavePolicyFormValues,
  current: LeavePolicy,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.name.trim() !== current.name) patch.name = values.name.trim();
  const code = values.code.trim() || null;
  if (code !== current.code) patch.code = code;
  return patch;
}

// ---------------------------------------------------------------------------
// Version (draft) form
// ---------------------------------------------------------------------------

export interface LeavePolicyVersionFormValues {
  effectiveFrom: string;
  allowEmployeeRequest: boolean;
  allowManagerRequestOnBehalf: boolean;
  allowHrRequestOnBehalf: boolean;
  maxBackdatedDays: string;
  maxRequestsPerMonth: string;
  reasonRequired: boolean;
  attachmentRequired: boolean;
  approvalChain: string;
  halfDayAllowed: boolean;
  accrualFrequency: string;
  accrualRatePerCycle: string;
  maxCarryForwardDays: string;
  encashmentAllowed: boolean;
  allowNegativeBalance: boolean;
  negativeBalanceFloor: string;
  yearEndAction: string;
  sandwichRuleEnabled: boolean;
  reserveBalanceOnSubmission: boolean;
  preDeliveryDays: string;
  postDeliveryDays: string;
  allowedDuringProbation: boolean;
  accrueDuringProbation: boolean;
  maxEncashmentDays: string;
  minBalanceAfterEncashment: string;
  encashmentFrequency: string;
  encashmentCalculationBasis: string;
}

export const EMPTY_LEAVE_POLICY_VERSION_FORM_VALUES: LeavePolicyVersionFormValues = {
  effectiveFrom: "",
  allowEmployeeRequest: true,
  allowManagerRequestOnBehalf: true,
  allowHrRequestOnBehalf: true,
  maxBackdatedDays: "",
  maxRequestsPerMonth: "",
  reasonRequired: true,
  attachmentRequired: false,
  approvalChain: "MANAGER",
  halfDayAllowed: true,
  accrualFrequency: "NONE",
  accrualRatePerCycle: "",
  maxCarryForwardDays: "",
  encashmentAllowed: false,
  allowNegativeBalance: false,
  negativeBalanceFloor: "",
  yearEndAction: "CARRY_FORWARD",
  sandwichRuleEnabled: true,
  reserveBalanceOnSubmission: false,
  preDeliveryDays: "",
  postDeliveryDays: "",
  allowedDuringProbation: true,
  accrueDuringProbation: true,
  maxEncashmentDays: "",
  minBalanceAfterEncashment: "",
  encashmentFrequency: "",
  encashmentCalculationBasis: "",
};

export interface LeavePolicyVersionFormErrors {
  effectiveFrom?: string;
  accrualRatePerCycle?: string;
  maxCarryForwardDays?: string;
  negativeBalanceFloor?: string;
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) return null;
  return Math.trunc(parsed);
}

function decimalOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function leavePolicyVersionToFormValues(
  version: LeavePolicyVersion,
): LeavePolicyVersionFormValues {
  return {
    effectiveFrom: version.effective_from ?? "",
    allowEmployeeRequest: version.allow_employee_request,
    allowManagerRequestOnBehalf: version.allow_manager_request_on_behalf,
    allowHrRequestOnBehalf: version.allow_hr_request_on_behalf,
    maxBackdatedDays: version.max_backdated_days === null ? "" : String(version.max_backdated_days),
    maxRequestsPerMonth:
      version.max_requests_per_month === null ? "" : String(version.max_requests_per_month),
    reasonRequired: version.reason_required,
    attachmentRequired: version.attachment_required,
    approvalChain: version.approval_chain,
    halfDayAllowed: version.half_day_allowed,
    accrualFrequency: version.accrual_frequency,
    accrualRatePerCycle: version.accrual_rate_per_cycle ?? "",
    maxCarryForwardDays: version.max_carry_forward_days ?? "",
    encashmentAllowed: version.encashment_allowed,
    allowNegativeBalance: version.allow_negative_balance,
    negativeBalanceFloor: version.negative_balance_floor ?? "",
    yearEndAction: version.year_end_action,
    sandwichRuleEnabled: version.sandwich_rule_enabled,
    reserveBalanceOnSubmission: version.reserve_balance_on_submission,
    preDeliveryDays: version.pre_delivery_days === null ? "" : String(version.pre_delivery_days),
    postDeliveryDays:
      version.post_delivery_days === null ? "" : String(version.post_delivery_days),
    allowedDuringProbation: version.allowed_during_probation,
    accrueDuringProbation: version.accrue_during_probation,
    maxEncashmentDays: version.max_encashment_days ?? "",
    minBalanceAfterEncashment: version.min_balance_after_encashment ?? "",
    encashmentFrequency: version.encashment_frequency ?? "",
    encashmentCalculationBasis: version.encashment_calculation_basis ?? "",
  };
}

/** Builds the `POST/PATCH .../leave-policies/{id}/versions*` body. Drafts have no external
 * readers before publish, so (mirroring `buildAttendancePolicyVersionPayload`) every field is
 * resent unconditionally rather than diffed. */
export function buildLeavePolicyVersionPayload(
  values: LeavePolicyVersionFormValues,
): Record<string, unknown> {
  return {
    effective_from: values.effectiveFrom || null,
    allow_employee_request: values.allowEmployeeRequest,
    allow_manager_request_on_behalf: values.allowManagerRequestOnBehalf,
    allow_hr_request_on_behalf: values.allowHrRequestOnBehalf,
    max_backdated_days: intOrNull(values.maxBackdatedDays),
    max_requests_per_month: intOrNull(values.maxRequestsPerMonth),
    reason_required: values.reasonRequired,
    attachment_required: values.attachmentRequired,
    approval_chain: values.approvalChain,
    half_day_allowed: values.halfDayAllowed,
    accrual_frequency: values.accrualFrequency,
    accrual_rate_per_cycle: decimalOrNull(values.accrualRatePerCycle),
    max_carry_forward_days: decimalOrNull(values.maxCarryForwardDays),
    encashment_allowed: values.encashmentAllowed,
    allow_negative_balance: values.allowNegativeBalance,
    negative_balance_floor: values.allowNegativeBalance
      ? decimalOrNull(values.negativeBalanceFloor)
      : null,
    year_end_action: values.yearEndAction,
    sandwich_rule_enabled: values.sandwichRuleEnabled,
    reserve_balance_on_submission: values.reserveBalanceOnSubmission,
    pre_delivery_days: intOrNull(values.preDeliveryDays),
    post_delivery_days: intOrNull(values.postDeliveryDays),
    allowed_during_probation: values.allowedDuringProbation,
    accrue_during_probation: values.accrueDuringProbation,
    max_encashment_days: decimalOrNull(values.maxEncashmentDays),
    min_balance_after_encashment: decimalOrNull(values.minBalanceAfterEncashment),
    encashment_frequency: values.encashmentFrequency.trim() || null,
    encashment_calculation_basis: values.encashmentCalculationBasis.trim() || null,
  };
}

/** Light client-side pre-check — the backend is authoritative. */
export function validateLeavePolicyVersionForm(
  values: LeavePolicyVersionFormValues,
): LeavePolicyVersionFormErrors {
  const errors: LeavePolicyVersionFormErrors = {};
  if (values.allowNegativeBalance) {
    const floor = Number(values.negativeBalanceFloor.trim());
    if (!values.negativeBalanceFloor.trim() || Number.isNaN(floor) || floor <= 0) {
      errors.negativeBalanceFloor = "Enter how many days below zero the balance may go.";
    }
  }
  if (values.yearEndAction === "ENCASH_EXCESS" && !values.maxCarryForwardDays.trim()) {
    errors.maxCarryForwardDays = "Set a cap — the days above it are encashed at year end.";
  }
  return errors;
}

export function mapLeavePolicyVersionApiErrors(details: ErrorDetail[]): LeavePolicyVersionFormErrors {
  const errors: LeavePolicyVersionFormErrors = {};
  for (const detail of details) {
    if (detail.field === "effective_from") errors.effectiveFrom = detail.message;
    if (detail.field === "negative_balance_floor") errors.negativeBalanceFloor = detail.message;
  }
  return errors;
}
