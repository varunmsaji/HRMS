import type { MonthSummaryRow } from "@/lib/attendance/month-summary";
import { bucketOf, eachDate, addDays, employeeName, type DayBucket, type EmployeeLite } from "@/lib/attendance/dashboard";
import type { AttendanceDay } from "@/lib/attendance/types";

export interface CalendarRow {
  employeeId: string;
  name: string;
  code: string | null;
  cells: Map<string, AttendanceDay>;
  present: number;
  absent: number;
  leave: number;
  late: number;
}

/**
 * Who can open the HR calendar. It is an HR view (VIEW_ALL), and it loads `/attendance/days`
 * (ATTENDANCE.VIEW) and `/employees` (EMPLOYEE.VIEW_ALL), so a role missing either read would see
 * only an error.
 */
export const HR_CALENDAR_PERMISSIONS = ["ATTENDANCE.VIEW_ALL", "ATTENDANCE.VIEW", "EMPLOYEE.VIEW_ALL"] as const;

/** First and last date of a YYYY-MM month, and every date in between. */
export function monthDates(month: string): string[] {
  const first = `${month}-01`;
  const next = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 1));
  return eachDate(first, addDays(next.toISOString().slice(0, 10), -1));
}

export function shiftMonth(month: string, delta: number): string {
  const d = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1 + delta, 1));
  return d.toISOString().slice(0, 7);
}

const PRESENT_BUCKETS: DayBucket[] = ["PRESENT", "REMOTE", "ON_DUTY", "HALF_DAY"];

/** One row per employee (everyone in the directory, even with no records), with the month's counts.
 * Employees who appear only in the day rows (outside the loaded directory) are added too. */
export function buildHrCalendar(
  days: AttendanceDay[],
  employees: EmployeeLite[],
  dates: string[],
): CalendarRow[] {
  const inRange = new Set(dates);
  const byId = new Map(employees.map((e) => [e.id, e]));
  const rows = new Map<string, CalendarRow>();
  const ensure = (id: string): CalendarRow => {
    let row = rows.get(id);
    if (!row) {
      const emp = byId.get(id);
      row = {
        employeeId: id,
        name: employeeName(emp, id),
        code: emp?.employee_code ?? null,
        cells: new Map(),
        present: 0,
        absent: 0,
        leave: 0,
        late: 0,
      };
      rows.set(id, row);
    }
    return row;
  };
  for (const e of employees) ensure(e.id);
  for (const day of days) {
    if (!inRange.has(day.attendance_date)) continue;
    const row = ensure(day.employee_id);
    row.cells.set(day.attendance_date, day);
    const bucket = bucketOf(day);
    if (PRESENT_BUCKETS.includes(bucket)) row.present += bucket === "HALF_DAY" ? 0.5 : 1;
    if (bucket === "ABSENT") row.absent += 1;
    if (bucket === "LEAVE") row.leave += 1;
    if (day.is_late) row.late += 1;
  }
  return [...rows.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** Replace each row's totals with the payroll month figures from the API (R-B03), so the grid
 * adds up the way payroll will: a half-day leave with the other half worked is half leave and
 * half present, a band half day is half a day. Rows without a payroll entry keep their own
 * totals. The cells (one box per day) are untouched. */
export function withPayrollTotals(rows: CalendarRow[], summaries: MonthSummaryRow[]): CalendarRow[] {
  const byId = new Map(summaries.map((s) => [s.employee_id, s]));
  return rows.map((row) => {
    const p = byId.get(row.employeeId);
    if (!p) return row;
    return {
      ...row,
      present: Number(p.present_days) + Number(p.on_duty_days ?? 0) + Number(p.half_days) / 2,
      absent: Number(p.absent_days),
      leave: Number(p.leave_days),
      late: p.late_count,
    };
  });
}

export function filterRows(rows: CalendarRow[], query: string): CalendarRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((r) => r.name.toLowerCase().includes(q) || (r.code ?? "").toLowerCase().includes(q));
}
