/** Mirrors `apps/api/src/hrms/modules/attendance/schemas.py` `RegularizationRequest*` (W6 —
 * architecture §13/§14, decision log WD-28). */

export const REGULARIZATION_TYPES = [
  "MISSING_PUNCH",
  "WRONG_PUNCH",
  "WRONG_SHIFT",
  "WRONG_STATUS",
  "WFH",
  "ON_DUTY",
  "EXCESS_BREAK",
  "FULL_DAY",
] as const;
export type RegularizationType = (typeof REGULARIZATION_TYPES)[number];

export const REGULARIZATION_TYPE_LABELS: Record<RegularizationType, string> = {
  MISSING_PUNCH: "Missing punch",
  WRONG_PUNCH: "Wrong punch time",
  WRONG_SHIFT: "Wrong shift",
  WRONG_STATUS: "Wrong status",
  WFH: "Work from home",
  ON_DUTY: "On duty",
  EXCESS_BREAK: "Excess break",
  FULL_DAY: "Full day correction",
};

export const REGULARIZATION_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"] as const;
export type RegularizationStatus = (typeof REGULARIZATION_STATUSES)[number];

export const APPROVAL_STAGES = ["MANAGER", "HR"] as const;
export type ApprovalStage = (typeof APPROVAL_STAGES)[number];

export const REGULARIZATION_ACTIONS = [
  "SUBMITTED",
  "APPROVER_UNRESOLVED",
  "STAGE_APPROVED",
  "APPROVED",
  "REJECTED",
  "CANCELLED",
  "APPLIED",
] as const;
export type RegularizationAction = (typeof REGULARIZATION_ACTIONS)[number];

export interface RegularizationRequestedPunch {
  id: string;
  direction: "IN" | "OUT";
  requested_time: string;
  sort_order: number;
}

export interface RegularizationRequestedPunchInput {
  direction: "IN" | "OUT";
  requested_time: string;
}

export interface RegularizationActionEntry {
  id: string;
  action: RegularizationAction;
  actor_user_id: string | null;
  actor_employee_id: string | null;
  stage: ApprovalStage | null;
  comment: string | null;
  created_at: string;
}

export interface RegularizationRequest {
  id: string;
  company_id: string;
  employee_id: string;
  attendance_day_id: string | null;
  attendance_date: string;

  request_type: RegularizationType;
  reason: string | null;
  requested_shift_id: string | null;
  attachment_reference: string | null;

  status: RegularizationStatus;
  approval_chain: "AUTO" | "MANAGER" | "MANAGER_THEN_HR" | "HR";
  approval_stage: ApprovalStage | null;
  regularization_policy_version_id: string;
  resolved_approver_manager_id: string | null;

  submitted_by_user_id: string | null;
  submitted_at: string;

  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  reviewer_comment: string | null;
  rejection_reason: string | null;

  applied_at: string | null;
  cancelled_at: string | null;
  cancelled_by_user_id: string | null;

  version: number;

  requested_punches: RegularizationRequestedPunch[];
  actions: RegularizationActionEntry[];

  created_at: string;
  updated_at: string;
}

/** Mirrors `RegularizationRequestCreate`. */
export interface RegularizationRequestCreatePayload {
  employee_id?: string;
  attendance_date: string;
  request_type: RegularizationType;
  reason?: string;
  requested_shift_id?: string;
  attachment_reference?: string;
  requested_punches?: RegularizationRequestedPunchInput[];
}

/** Mirrors `RegularizationReviewInput`. */
export interface RegularizationReviewPayload {
  reviewer_comment?: string;
  rejection_reason?: string;
}

export const REGULARIZATION_STATUS_LABELS: Record<RegularizationStatus, string> = {
  SUBMITTED: "Submitted",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CANCELLED: "Cancelled",
};
