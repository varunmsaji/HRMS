import type { ErrorDetail } from "@/lib/api/types";
import type {
  RegularizationPolicy,
  RegularizationPolicyVersion,
} from "@/lib/regularization-policy/types";

export interface RegularizationPolicyFormValues {
  name: string;
}

export const EMPTY_REGULARIZATION_POLICY_FORM_VALUES: RegularizationPolicyFormValues = {
  name: "",
};

export interface RegularizationPolicyFormErrors {
  name?: string;
}

export function validateRegularizationPolicyForm(
  values: RegularizationPolicyFormValues,
): RegularizationPolicyFormErrors {
  const errors: RegularizationPolicyFormErrors = {};
  if (!values.name.trim()) errors.name = "Name is required.";
  return errors;
}

export function buildRegularizationPolicyCreatePayload(
  values: RegularizationPolicyFormValues,
): Record<string, unknown> {
  return { name: values.name.trim() };
}

export function buildRegularizationPolicyUpdatePatch(
  values: RegularizationPolicyFormValues,
  current: RegularizationPolicy,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (values.name.trim() !== current.name) patch.name = values.name.trim();
  return patch;
}

export interface RegularizationPolicyVersionFormValues {
  effectiveFrom: string;
  allowEmployeeRequest: boolean;
  allowManagerRequest: boolean;
  allowHrRequest: boolean;
  maxBackdatedDays: string;
  maxRequestsPerMonth: string;
  reasonRequired: boolean;
  attachmentRequired: boolean;
  approvalChain: string;
  autoApproveWithinMinutes: string;
  blockedWhenLocked: boolean;
  allowedTypes: string[];
}

export const EMPTY_REGULARIZATION_POLICY_VERSION_FORM_VALUES: RegularizationPolicyVersionFormValues =
  {
    effectiveFrom: "",
    allowEmployeeRequest: true,
    allowManagerRequest: true,
    allowHrRequest: true,
    maxBackdatedDays: "",
    maxRequestsPerMonth: "",
    reasonRequired: true,
    attachmentRequired: false,
    approvalChain: "MANAGER",
    autoApproveWithinMinutes: "",
    blockedWhenLocked: true,
    allowedTypes: [],
  };

export interface RegularizationPolicyVersionFormErrors {
  effectiveFrom?: string;
  allowedTypes?: string;
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) return null;
  return Math.trunc(parsed);
}

export function regularizationPolicyVersionToFormValues(
  version: RegularizationPolicyVersion,
): RegularizationPolicyVersionFormValues {
  return {
    effectiveFrom: version.effective_from ?? "",
    allowEmployeeRequest: version.allow_employee_request,
    allowManagerRequest: version.allow_manager_request,
    allowHrRequest: version.allow_hr_request,
    maxBackdatedDays: version.max_backdated_days === null ? "" : String(version.max_backdated_days),
    maxRequestsPerMonth:
      version.max_requests_per_month === null ? "" : String(version.max_requests_per_month),
    reasonRequired: version.reason_required,
    attachmentRequired: version.attachment_required,
    approvalChain: version.approval_chain,
    autoApproveWithinMinutes:
      version.auto_approve_within_minutes === null
        ? ""
        : String(version.auto_approve_within_minutes),
    blockedWhenLocked: version.blocked_when_locked,
    allowedTypes: version.allowed_types
      .slice()
      .sort((a, b) => a.sort_order - b.sort_order)
      .map((t) => t.regularization_type),
  };
}

export function buildRegularizationPolicyVersionPayload(
  values: RegularizationPolicyVersionFormValues,
): Record<string, unknown> {
  return {
    effective_from: values.effectiveFrom || null,
    allow_employee_request: values.allowEmployeeRequest,
    allow_manager_request: values.allowManagerRequest,
    allow_hr_request: values.allowHrRequest,
    max_backdated_days: intOrNull(values.maxBackdatedDays),
    max_requests_per_month: intOrNull(values.maxRequestsPerMonth),
    reason_required: values.reasonRequired,
    attachment_required: values.attachmentRequired,
    approval_chain: values.approvalChain,
    auto_approve_within_minutes: intOrNull(values.autoApproveWithinMinutes),
    blocked_when_locked: values.blockedWhenLocked,
    allowed_types: values.allowedTypes.map((type, index) => ({
      regularization_type: type,
      sort_order: index,
    })),
  };
}

/** Light client-side pre-check — the backend is authoritative. */
export function validateRegularizationPolicyVersionForm(
  _values: RegularizationPolicyVersionFormValues,
): RegularizationPolicyVersionFormErrors {
  return {};
}

export function mapRegularizationPolicyVersionApiErrors(
  details: ErrorDetail[],
): RegularizationPolicyVersionFormErrors {
  const errors: RegularizationPolicyVersionFormErrors = {};
  for (const detail of details) {
    if (detail.field === "allowed_types") errors.allowedTypes = detail.message;
    if (detail.field === "effective_from") errors.effectiveFrom = detail.message;
  }
  return errors;
}

/** Publishing needs a correction type, or the policy would allow nothing. */
export function validateRegularizationPolicyForPublish(
  values: RegularizationPolicyVersionFormValues,
): RegularizationPolicyVersionFormErrors {
  const errors = validateRegularizationPolicyVersionForm(values);
  if (values.allowedTypes.length === 0) {
    errors.allowedTypes = "Allow at least one kind of correction to publish.";
  }
  return errors;
}
