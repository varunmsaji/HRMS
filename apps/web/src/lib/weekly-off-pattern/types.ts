/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::WeeklyOffRuleRead`. */
export interface WeeklyOffRule {
  id: string;
  weekday: number; // 0=Monday .. 6=Sunday (Python `date.weekday()` convention)
  nth_in_month: number | null;
  cycle_start_date: string | null;
  off_fraction: string;
  week_parity: "EVEN" | "ODD" | null;
}

/** Mirrors `apps/api/src/hrms/modules/organisation/schemas.py::WeeklyOffPatternRead`. */
export interface WeeklyOffPattern {
  id: string;
  company_id: string;
  name: string;
  code: string | null;
  pattern_kind: "FIXED_WEEKDAYS" | "NTH_WEEKDAY" | "ALTERNATE" | "CUSTOM";
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  rules: WeeklyOffRule[];
}

export const WEEKDAY_LABELS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

export const PATTERN_KINDS = ["FIXED_WEEKDAYS", "NTH_WEEKDAY", "ALTERNATE", "CUSTOM"] as const;
