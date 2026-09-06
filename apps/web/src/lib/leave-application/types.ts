/** Mirrors `apps/api/src/hrms/modules/leave/schemas.py` `LeaveApplication*` (L4, decision log
 * LD-02/LD-05/LD-12/LD-13). */

export const LEAVE_APPLICATION_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"] as const;
export type LeaveApplicationStatus = (typeof LEAVE_APPLICATION_STATUSES)[number];

export const LEAVE_APPROVAL_STAGES = ["MANAGER", "HOD", "HR"] as const;
export type LeaveApprovalStage = (typeof LEAVE_APPROVAL_STAGES)[number];

export const LEAVE_HALF_DAY_VALUES = ["FIRST_HALF", "SECOND_HALF"] as const;
export type LeaveHalfDay = (typeof LEAVE_HALF_DAY_VALUES)[number];

export const LEAVE_APPLICATION_ACTIONS = [
  "SUBMITTED",
  "APPROVER_UNRESOLVED",
  "STAGE_APPROVED",
  "APPROVED",
  "REJECTED",
  "CANCELLED",
] as const;
export type LeaveApplicationActionType = (typeof LEAVE_APPLICATION_ACTIONS)[number];

export interface LeaveApplicationDay {
  id: string;
  calendar_date: string;
  fraction: string;
  half: LeaveHalfDay | null;
  is_sandwich_generated: boolean;
  leave_day_projection_id: string | null;
}

export interface LeaveApplicationActionEntry {
  id: string;
  action: LeaveApplicationActionType;
  actor_user_id: string | null;
  actor_employee_id: string | null;
  stage: LeaveApprovalStage | null;
  comment: string | null;
  created_at: string;
}

export interface LeaveApplication {
  id: string;
  company_id: string;
  employee_id: string;
  leave_type_id: string;
  leave_policy_version_id: string;

  start_date: string;
  end_date: string;
  total_days: string;
  reason: string | null;
  attachment_reference: string | null;
  expected_delivery_date: string | null;

  status: LeaveApplicationStatus;
  approval_chain: "AUTO" | "MANAGER" | "MANAGER_THEN_HR" | "MANAGER_THEN_HOD_THEN_HR" | "HR";
  approval_stage: LeaveApprovalStage | null;
  resolved_approver_manager_id: string | null;
  resolved_department_head_id: string | null;

  submitted_by_user_id: string | null;
  submitted_at: string;

  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  reviewer_comment: string | null;
  rejection_reason: string | null;

  cancelled_at: string | null;
  cancelled_by_user_id: string | null;

  version: number;

  days: LeaveApplicationDay[];
  actions: LeaveApplicationActionEntry[];

  created_at: string;
  updated_at: string;
}

/** Mirrors `LeaveApplicationCreate`. */
export interface LeaveApplicationCreatePayload {
  employee_id?: string;
  leave_type_id: string;
  start_date: string;
  end_date: string;
  half_day?: LeaveHalfDay;
  reason?: string;
  attachment_reference?: string;
  expected_delivery_date?: string;
}

/** Mirrors `LeaveApplicationReviewInput`. */
export interface LeaveApplicationReviewPayload {
  reviewer_comment?: string;
  rejection_reason?: string;
}

export const LEAVE_APPLICATION_STATUS_LABELS: Record<LeaveApplicationStatus, string> = {
  SUBMITTED: "Submitted",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CANCELLED: "Cancelled",
};
