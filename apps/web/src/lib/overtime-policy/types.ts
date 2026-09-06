/** Mirrors `hrms.modules.attendance.schemas` OvertimePolicy* shapes (W3). */

export interface OvertimePolicy {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export const OT_ELIGIBILITY_OPTIONS = [
  "SHIFT_FLAG",
  "ALWAYS",
  "NEVER",
  "GRADE_VIA_ASSIGNMENT",
] as const;
export const OT_ROUNDING_MODES = ["NONE", "NEAREST", "UP", "DOWN"] as const;
export const NIGHT_OT_MODES = ["SHIFT_FLAG", "WINDOW", "BOTH"] as const;
export const APPROVAL_CHAINS = ["AUTO", "MANAGER", "MANAGER_THEN_HR", "HR"] as const;
export const DAY_CLASSES = ["NORMAL", "WEEKLY_OFF", "HOLIDAY", "NIGHT"] as const;

export interface OvertimePolicyRateRow {
  id: string;
  day_class: (typeof DAY_CLASSES)[number];
  classification_code: string;
  multiplier_decimal: string | null;
  sort_order: number;
}

export interface OvertimePolicyVersion {
  id: string;
  company_id: string;
  policy_id: string;
  status: "DRAFT" | "PUBLISHED";
  version: number;
  effective_from: string | null;
  effective_to: string | null;

  eligibility: (typeof OT_ELIGIBILITY_OPTIONS)[number];
  min_ot_minutes: number;
  rounding_minutes: number | null;
  rounding_mode: (typeof OT_ROUNDING_MODES)[number];
  requires_pre_approval: boolean;
  requires_post_approval: boolean;
  daily_cap_minutes: number | null;
  weekly_cap_minutes: number | null;
  monthly_cap_minutes: number | null;
  comp_off_instead_of_pay: boolean;
  comp_off_expiry_days: number | null;
  comp_off_day_length_minutes: number | null;
  night_ot_mode: (typeof NIGHT_OT_MODES)[number];
  night_window_start: string | null;
  night_window_end: string | null;
  approval_chain: (typeof APPROVAL_CHAINS)[number];

  rate_rows: OvertimePolicyRateRow[];

  publish_reason: string | null;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
}
