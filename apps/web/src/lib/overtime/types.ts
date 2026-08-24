/** Mirrors `apps/api/src/hrms/modules/attendance/schemas.py` `OvertimeRecord*` (W7 — architecture
 * §13/§14). Overtime records are system-detected, never user-submitted: attendance calculation
 * creates one `OvertimeRecord` per attendance day when it detects overtime, and depending on the
 * resolved `OvertimePolicyVersion.approval_chain` it is either immediately `AUTO_APPROVED` or left
 * `PENDING` for a manager/HR to approve or reject. There is no create/submit flow here. */

export const OVERTIME_STATUSES = ["PENDING", "AUTO_APPROVED", "APPROVED", "REJECTED"] as const;
export type OvertimeStatus = (typeof OVERTIME_STATUSES)[number];

export const OVERTIME_APPROVAL_STAGES = ["MANAGER", "HR"] as const;
export type OvertimeApprovalStage = (typeof OVERTIME_APPROVAL_STAGES)[number];

export const OVERTIME_APPROVAL_CHAINS = ["AUTO", "MANAGER", "MANAGER_THEN_HR", "HR"] as const;
export type OvertimeApprovalChain = (typeof OVERTIME_APPROVAL_CHAINS)[number];

export const OVERTIME_DAY_CLASSES = ["NORMAL", "WEEKLY_OFF", "HOLIDAY", "NIGHT"] as const;
export type OvertimeDayClass = (typeof OVERTIME_DAY_CLASSES)[number];

export const OVERTIME_ACTIONS = [
  "DETECTED",
  "APPROVER_UNRESOLVED",
  "AUTO_APPROVED",
  "STAGE_APPROVED",
  "APPROVED",
  "REJECTED",
] as const;
export type OvertimeAction = (typeof OVERTIME_ACTIONS)[number];

export interface OvertimeActionEntry {
  id: string;
  action: OvertimeAction;
  actor_user_id: string | null;
  actor_employee_id: string | null;
  stage: OvertimeApprovalStage | null;
  comment: string | null;
  created_at: string;
}

export interface OvertimeRecord {
  id: string;
  company_id: string;
  employee_id: string;
  attendance_day_id: string;
  attendance_date: string;
  overtime_policy_version_id: string;

  day_class: OvertimeDayClass | null;
  classification_code: string | null;
  configured_multiplier: string | null;

  minutes_detected: number;
  minutes_approved: number;

  status: OvertimeStatus;
  approval_chain: OvertimeApprovalChain;
  approval_stage: OvertimeApprovalStage | null;
  resolved_approver_manager_id: string | null;

  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  reviewer_comment: string | null;
  rejection_reason: string | null;

  comp_off_minutes: number;
  comp_off_expiry_date: string | null;

  version: number;

  actions: OvertimeActionEntry[];

  created_at: string;
  updated_at: string;
}

/** Mirrors `OvertimeReviewInput`. */
export interface OvertimeReviewPayload {
  reviewer_comment?: string;
  rejection_reason?: string;
}

export const OVERTIME_STATUS_LABELS: Record<OvertimeStatus, string> = {
  PENDING: "Pending",
  AUTO_APPROVED: "Auto-approved",
  APPROVED: "Approved",
  REJECTED: "Rejected",
};

export const OVERTIME_DAY_CLASS_LABELS: Record<OvertimeDayClass, string> = {
  NORMAL: "Normal",
  WEEKLY_OFF: "Weekly off",
  HOLIDAY: "Holiday",
  NIGHT: "Night",
};

export const OVERTIME_APPROVAL_CHAIN_LABELS: Record<OvertimeApprovalChain, string> = {
  AUTO: "Auto-approved",
  MANAGER: "Manager",
  MANAGER_THEN_HR: "Manager, then HR",
  HR: "HR",
};
