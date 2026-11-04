/** Mirrors `hrms.modules.attendance.schemas` RegularizationPolicy* shapes (W3). */

export interface RegularizationPolicy {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  /** Filled by the list endpoint. */
  live_from?: string | null;
  has_draft?: boolean;
  assigned_company_wide?: boolean;
  assigned_group_count?: number;
}

export const APPROVAL_CHAINS = ["AUTO", "MANAGER", "MANAGER_THEN_HR", "HR"] as const;
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

export interface RegularizationPolicyAllowedType {
  id: string;
  regularization_type: (typeof REGULARIZATION_TYPES)[number];
  sort_order: number;
}

export interface RegularizationPolicyVersion {
  id: string;
  company_id: string;
  policy_id: string;
  status: "DRAFT" | "PUBLISHED";
  version: number;
  effective_from: string | null;
  effective_to: string | null;

  allow_employee_request: boolean;
  allow_manager_request: boolean;
  allow_hr_request: boolean;
  max_backdated_days: number | null;
  max_requests_per_month: number | null;
  reason_required: boolean;
  attachment_required: boolean;
  approval_chain: (typeof APPROVAL_CHAINS)[number];
  auto_approve_within_minutes: number | null;
  blocked_when_locked: boolean;

  allowed_types: RegularizationPolicyAllowedType[];

  publish_reason: string | null;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
}
