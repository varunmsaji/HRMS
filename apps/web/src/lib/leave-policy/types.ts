/** Mirrors `apps/api/src/hrms/modules/leave/schemas.py` `LeavePolicy*` (L1/L3/L6). */

export const APPROVAL_CHAINS = [
  "AUTO",
  "MANAGER",
  "MANAGER_THEN_HR",
  "MANAGER_THEN_HOD_THEN_HR",
  "HR",
] as const;
export type ApprovalChain = (typeof APPROVAL_CHAINS)[number];

export const ACCRUAL_FREQUENCIES = ["NONE", "MONTHLY", "YEARLY"] as const;
export type AccrualFrequency = (typeof ACCRUAL_FREQUENCIES)[number];

/** Decision 11 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`) — balance handling at leave-year start. */
export const YEAR_END_ACTIONS = ["CARRY_FORWARD", "LAPSE", "ENCASH_EXCESS"] as const;
export type YearEndAction = (typeof YEAR_END_ACTIONS)[number];
export const YEAR_END_ACTION_LABELS: Record<YearEndAction, string> = {
  CARRY_FORWARD: "Carry forward up to the cap, the rest lapses",
  LAPSE: "Lapse — the whole balance is forfeited",
  ENCASH_EXCESS: "Carry forward up to the cap, encash the rest",
};

export interface LeavePolicy {
  id: string;
  company_id: string;
  leave_type_id: string;
  name: string;
  code: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface LeavePolicyVersion {
  id: string;
  company_id: string;
  policy_id: string;
  status: "DRAFT" | "PUBLISHED";
  version: number;
  effective_from: string | null;
  effective_to: string | null;

  allow_employee_request: boolean;
  allow_manager_request_on_behalf: boolean;
  allow_hr_request_on_behalf: boolean;
  max_backdated_days: number | null;
  max_requests_per_month: number | null;
  reason_required: boolean;
  attachment_required: boolean;
  approval_chain: ApprovalChain;
  half_day_allowed: boolean;

  accrual_frequency: AccrualFrequency;
  accrual_rate_per_cycle: string | null;
  max_carry_forward_days: string | null;
  encashment_allowed: boolean;
  allow_negative_balance: boolean;
  /** PAY-011 — days below zero allowed when `allow_negative_balance` is on. */
  negative_balance_floor: string | null;
  year_end_action: YearEndAction;
  sandwich_rule_enabled: boolean;
  reserve_balance_on_submission: boolean;
  pre_delivery_days: number | null;
  post_delivery_days: number | null;
  allowed_during_probation: boolean;
  accrue_during_probation: boolean;
  max_encashment_days: string | null;
  min_balance_after_encashment: string | null;
  encashment_frequency: string | null;
  encashment_calculation_basis: string | null;

  publish_reason: string | null;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
}

/** Mirrors `LeavePolicyCreate`. */
export interface LeavePolicyCreatePayload {
  leave_type_id: string;
  name: string;
  code?: string | null;
}

/** Mirrors `LeavePolicyUpdate`. */
export interface LeavePolicyUpdatePayload {
  name?: string;
  code?: string | null;
  is_active?: boolean;
}
