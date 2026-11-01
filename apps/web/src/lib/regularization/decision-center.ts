/** Types and pure helpers for `GET /regularizations/decision-center`. Every figure is the backend's. */

export type RegularizationTab = "pending" | "approved" | "declined";

export interface RegularizationSummary {
  pending_count: number;
  oldest_pending_at: string | null;
  window_regularized_days: number;
  window_expected_days: number;
  window_rate_pct: number | null;
}

export interface RequestedPunch {
  direction: "IN" | "OUT" | string;
  time: string;
}

export interface RegularizationItem {
  id: string;
  version: number;
  employee_id: string;
  employee_name: string;
  employee_code: string;
  designation: string | null;
  department: string | null;
  attendance_date: string;
  timezone: string | null;
  shift_name: string | null;
  request_type: string;
  status: string;
  approval_stage: string | null;
  submitted_at: string;
  reason: string | null;
  recorded_first_in: string | null;
  recorded_last_out: string | null;
  recorded_worked_minutes: number | null;
  recorded_late_minutes: number | null;
  recorded_status: string | null;
  recorded_missing_punch: boolean | null;
  requested_punches: RequestedPunch[];
  requested_span_minutes: number | null;
}

export interface RegularizationDecisionData {
  today: string;
  summary: RegularizationSummary;
  counts: { pending: number; approved: number; declined: number };
  tab: RegularizationTab;
  items: RegularizationItem[];
}

export function regularizationDecisionPath(tab: RegularizationTab): string {
  return `/regularizations/decision-center?tab=${tab}`;
}

export function stageLabel(stage: string | null): string {
  if (stage === "HR") return "Pending HR review";
  if (stage === "MANAGER") return "Pending manager review";
  return "Pending review";
}

/** Requested time of the first punch in that direction, or null if the employee didn't ask for one. */
export function requestedTime(punches: RequestedPunch[], direction: "IN" | "OUT"): string | null {
  const times = punches.filter((p) => p.direction === direction).map((p) => p.time);
  if (times.length === 0) return null;
  return times.reduce((a, b) => (direction === "IN" ? (a < b ? a : b) : a > b ? a : b));
}
