/** Mirrors `hrms.modules.attendance.schemas` (W3). */

export interface AttendancePolicy {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export const HOUR_BAND_STATUSES = ["PRESENT", "HALF_DAY", "ABSENT"] as const;
export type HourBandStatus = (typeof HOUR_BAND_STATUSES)[number];

export const LATE_CLASSIFICATIONS = ["NONE", "LATE", "HALF_DAY", "ABSENT"] as const;
export type LateClassification = (typeof LATE_CLASSIFICATIONS)[number];

export const EARLY_CLASSIFICATIONS = ["NONE", "EARLY_DEPARTURE", "HALF_DAY", "ABSENT"] as const;
export type EarlyClassification = (typeof EARLY_CLASSIFICATIONS)[number];

export interface AttendancePolicyHourBand {
  id: string;
  min_minutes: number;
  max_minutes: number | null;
  result_status: HourBandStatus;
  sort_order: number;
}

export interface AttendancePolicyLateBand {
  id: string;
  min_minutes: number;
  max_minutes: number | null;
  classification: LateClassification;
  counts_toward_cap: boolean;
  sort_order: number;
}

export interface AttendancePolicyEarlyDepartureBand {
  id: string;
  min_minutes: number;
  max_minutes: number | null;
  classification: EarlyClassification;
  counts_toward_cap: boolean;
  sort_order: number;
}

export const PUNCH_ROUNDING_OPTIONS = ["NONE", "NEAREST", "UP", "DOWN"] as const;
export const MISSING_PUNCH_BEHAVIOURS = [
  "INCOMPLETE",
  "ABSENT",
  "AUTO_CLOSE",
  "REQUIRE_REGULARIZATION",
] as const;
export const MISSING_SHIFT_BEHAVIOURS = ["INCOMPLETE", "ABSENT"] as const;
export const HALF_DAY_SPLITS = ["BY_HOURS", "BY_MIDPOINT"] as const;
export const MULTI_PUNCH_MODES = ["PAIR_ALL", "FIRST_IN_LAST_OUT"] as const;
export const CORE_HOURS_BREACH_BEHAVIOURS = ["IGNORE", "FLAG", "HALF_DAY", "ABSENT"] as const;
export const SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS = [
  "IGNORE",
  "HALF_DAY",
  "ABSENT",
  "REQUIRE_REGULARIZATION",
] as const;
export const WORK_ON_LEAVE_BEHAVIOURS = ["KEEP_LEAVE", "PRESENT_CANCEL_LEAVE_HINT"] as const;
export const EXCESS_BREAK_BEHAVIOURS = ["IGNORE", "DEDUCT", "FLAG", "REQUIRE_APPROVAL"] as const;
export const INCOMPLETE_AT_LOCK_BEHAVIOURS = [
  "TREAT_ABSENT",
  "TREAT_PRESENT",
  "KEEP_INCOMPLETE",
] as const;

export interface AttendancePolicyVersion {
  id: string;
  company_id: string;
  policy_id: string;
  status: "DRAFT" | "PUBLISHED";
  version: number;
  effective_from: string | null;
  effective_to: string | null;

  grace_in_minutes: number;
  grace_out_minutes: number;
  punch_rounding: (typeof PUNCH_ROUNDING_OPTIONS)[number];
  rounding_minutes: number | null;
  missing_punch_behaviour: (typeof MISSING_PUNCH_BEHAVIOURS)[number];
  auto_close_after_minutes: number | null;
  auto_close_uses_shift_end: boolean;
  missing_shift_behaviour: (typeof MISSING_SHIFT_BEHAVIOURS)[number];
  half_day_split: (typeof HALF_DAY_SPLITS)[number];
  half_day_boundary_minutes: number | null;
  multi_punch_mode: (typeof MULTI_PUNCH_MODES)[number];
  duplicate_punch_window_seconds: number;
  core_hours_breach_behaviour: (typeof CORE_HOURS_BREACH_BEHAVIOURS)[number];
  early_out_uses_core_end: boolean;
  split_shift_block_mandatory: boolean;
  split_shift_missed_block_behaviour: (typeof SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS)[number];
  split_shift_allow_hours_compensation: boolean;
  wfh_requires_punch: boolean;
  on_duty_requires_punch: boolean;
  wfh_uses_shift_hours: boolean;
  work_on_leave_behaviour: (typeof WORK_ON_LEAVE_BEHAVIOURS)[number];
  excess_break_behaviour: (typeof EXCESS_BREAK_BEHAVIOURS)[number];
  late_count_window: "MONTH";
  lates_to_half_day_count: number | null;
  early_departure_requires_approval: boolean;
  excess_break_count_window: "MONTH";
  excess_break_days_to_half_day_count: number | null;
  incomplete_at_lock_behaviour: (typeof INCOMPLETE_AT_LOCK_BEHAVIOURS)[number];

  hour_bands: AttendancePolicyHourBand[];
  late_bands: AttendancePolicyLateBand[];
  early_departure_bands: AttendancePolicyEarlyDepartureBand[];

  publish_reason: string | null;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface PolicyResolution {
  employee_id: string;
  date: string;
  policy_kind: "ATTENDANCE_POLICY" | "OVERTIME_POLICY" | "REGULARIZATION_POLICY";
  config_incomplete: boolean;
  resolved_policy_id: string | null;
  resolved_policy_name: string | null;
  resolved_policy_code: string | null;
  resolved_version_id: string | null;
  resolved_through: string | null;
}
