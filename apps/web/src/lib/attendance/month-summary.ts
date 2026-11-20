/** `GET /v1/attendance/month-summary`: one month of the payroll arithmetic (R-B03). The API runs
 * the same code that finalizes a pay period, and returns the frozen figures once the month is
 * closed, so a screen never re-adds day rows to show paid / LOP / leave days. */

export interface MonthSummaryRow {
  employee_id: string;
  present_days: string;
  absent_days: string;
  leave_days: string;
  holiday_days: string;
  weekly_off_days: string;
  half_days: string;
  lop_days: string;
  on_duty_days: string | null;
  paid_days: string | null;
  payable_days: string | null;
  late_count: number;
  ot_minutes_normal: number;
  ot_minutes_weekly_off: number;
  ot_minutes_holiday: number;
  ot_minutes_night: number;
  /** True once a closed pay period covers this month: these are the figures payroll reads. */
  frozen: boolean;
}

export interface MonthSummaryResponse {
  month: string;
  summaries: MonthSummaryRow[];
}

export function monthSummaryPath(month: string, employeeIds: string[]): string {
  const params = new URLSearchParams({ month });
  for (const id of employeeIds) params.append("employee_id", id);
  return `/attendance/month-summary?${params.toString()}`;
}

/** Days as a short figure: "21", "1.5" (never "1.50"). */
export function formatPayrollDays(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const n = Number(value);
  return Number.isFinite(n) ? String(Number(n.toFixed(2))) : "–";
}

/** Approved overtime across every class, in minutes. */
export function approvedOvertimeMinutes(row: MonthSummaryRow): number {
  return row.ot_minutes_normal + row.ot_minutes_weekly_off + row.ot_minutes_holiday + row.ot_minutes_night;
}
