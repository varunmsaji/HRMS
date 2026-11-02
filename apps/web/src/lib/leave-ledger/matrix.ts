import type { EmployeeOption } from "@/lib/employee/use-employee-directory";
import { employeeOptionName } from "@/lib/employee/use-employee-directory";
import type { LeaveBalance } from "@/lib/leave-ledger/types";

/** One column of the team balance matrix. */
export interface LeaveTypeColumn {
  id: string;
  code: string;
  name: string;
}

/** The distinct leave types across everyone's balances, ordered by code so columns never jump
 * around as more people's balances arrive. */
export function collectLeaveTypes(rows: Iterable<readonly LeaveBalance[]>): LeaveTypeColumn[] {
  const byId = new Map<string, LeaveTypeColumn>();
  for (const balances of rows) {
    for (const b of balances) {
      if (!byId.has(b.leave_type_id)) {
        byId.set(b.leave_type_id, { id: b.leave_type_id, code: b.leave_type_code, name: b.leave_type_name });
      }
    }
  }
  return [...byId.values()].sort((a, b) => a.code.localeCompare(b.code) || a.name.localeCompare(b.name));
}

/** "5.00" → "5", "4.50" → "4.5", "-1.250" → "-1.25". Anything that is not a number is returned
 * untouched rather than hidden. */
export function formatDays(value: string): string {
  const n = Number(value);
  if (value.trim() === "" || !Number.isFinite(n)) return value;
  return String(Math.round(n * 100) / 100);
}

export type BalanceTone = "negative" | "zero" | "positive";

export function balanceTone(value: string): BalanceTone {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "zero";
  return n < 0 ? "negative" : "positive";
}

/** True when there is a non-zero amount (used for the "pending" line under a balance). */
export function hasAmount(value: string): boolean {
  const n = Number(value);
  return Number.isFinite(n) && n !== 0;
}

/** Case-insensitive match on name or employee code. Only narrows what is already loaded. */
export function filterEmployees<T extends EmployeeOption>(employees: readonly T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...employees];
  return employees.filter((e) => employeeOptionName(e).toLowerCase().includes(q));
}

export interface PageSlice<T> {
  rows: T[];
  page: number;
  totalPages: number;
  total: number;
}

/** 1-based page of `items`; an out-of-range page is clamped (e.g. after a filter shrinks the list). */
export function pageSlice<T>(items: readonly T[], page: number, pageSize: number): PageSlice<T> {
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(Math.max(1, page), totalPages);
  const start = (current - 1) * pageSize;
  return { rows: items.slice(start, start + pageSize), page: current, totalPages, total };
}
