/** Types and pure helpers for `GET /leave-applications/decision-center`. Every figure is the backend's. */

export type DecisionTab = "pending" | "approved" | "declined";

export interface DecisionSummary {
  pending_count: number;
  oldest_pending_at: string | null;
  on_leave_today: number;
  on_leave_today_by_type: [string, number][];
  active_staff: number;
  available_pct: number | null;
  upcoming_starts_7d: number;
  peak_day: string | null;
  peak_day_away: number;
}

export interface Colleague {
  name: string;
  start_date: string;
  end_date: string;
  status: string;
}

export interface DecisionItem {
  id: string;
  version: number;
  employee_id: string;
  employee_name: string;
  employee_code: string;
  designation: string | null;
  department: string | null;
  leave_type_id: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  total_days: string;
  lop_days: string;
  reason: string | null;
  status: string;
  approval_stage: string | null;
  submitted_at: string;
  current_balance: string | null;
  post_approval_balance: string | null;
  department_size: number | null;
  colleagues_away: Colleague[];
}

export interface DecisionCenterData {
  today: string;
  summary: DecisionSummary;
  counts: { pending: number; approved: number; declined: number };
  tab: DecisionTab;
  items: DecisionItem[];
}

export function decisionCenterPath(tab: DecisionTab): string {
  return `/leave-applications/decision-center?tab=${tab}`;
}

/** Decimal strings ("6.00") shown without trailing zeros: "6", "2.5". */
export function days(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return String(Number(value));
}

/** One line about teammates who are also away during the request, or null when nobody is. */
export function clashSummary(item: Pick<DecisionItem, "colleagues_away" | "department" | "department_size">): {
  clash: boolean;
  text: string;
} {
  const names = [...new Set(item.colleagues_away.map((c) => c.name))];
  const where = item.department ?? "the same department";
  if (names.length === 0) {
    return { clash: false, text: `No one else in ${where} is away during this period.` };
  }
  const shown = names.slice(0, 3).join(", ") + (names.length > 3 ? ` and ${names.length - 3} more` : "");
  const of = item.department_size ? ` of ${item.department_size}` : "";
  return { clash: true, text: `${names.length}${of} in ${where} also away: ${shown}.` };
}
