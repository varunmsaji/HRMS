import { bucketOf } from "@/lib/attendance/dashboard";
import type { AttendanceDay } from "@/lib/attendance/types";
import type { OvertimeRecord } from "@/lib/overtime/types";

/** What each report counts, in one sentence (R-F01). Two reports can show different numbers for
 * the same month and both be right: one counts whole days, the other counts payroll days. */
export const REPORT_BASIS = {
  daily: "One row per stored day. Status is the day's own result; a half day is named Half day, never Present.",
  present_absent:
    "Whole days. Present includes work from home and on duty; a half day is counted on its own and not as present.",
  late_early: "Days with a late arrival or an early departure beyond grace, as the calculation recorded them.",
  hours: "Days with a first punch only. Worked time is after unpaid breaks; scheduled time is the shift's.",
  overtime:
    "Overtime records. Payroll pays the approved minutes only; pending minutes are paid only if they are approved before the period closes.",
  payroll:
    "Payroll days from the period summary: a half day is split into paid and unpaid halves (0.5 each), so these figures can differ from the whole-day reports.",
} as const;

export interface OvertimeTotals {
  found: number;
  approved: number;
  pending: number;
}

/** Pending is what is still waiting for a decision on a record in `PENDING`; a rejected record's
 * minutes are neither approved nor pending. */
export function overtimePending(record: Pick<OvertimeRecord, "status" | "minutes_detected" | "minutes_approved">): number {
  return record.status === "PENDING" ? Math.max(0, record.minutes_detected - record.minutes_approved) : 0;
}

export function overtimeTotals(records: readonly OvertimeRecord[]): OvertimeTotals {
  return records.reduce<OvertimeTotals>(
    (t, r) => ({
      found: t.found + r.minutes_detected,
      approved: t.approved + r.minutes_approved,
      pending: t.pending + overtimePending(r),
    }),
    { found: 0, approved: 0, pending: 0 },
  );
}

/** One employee's whole-day counts over the loaded days (the Present / absent and Work hours
 * reports). Mobile's `tallyByEmployee` and the server's `_tallies` count the same way; the shared
 * fixture `apps/api/tests/fixtures/attendance_metrics_parity.json` holds all three to it. */
export interface EmployeeTally {
  id: string;
  present: number;
  half: number;
  absent: number;
  leave: number;
  off: number;
  holiday: number;
  incomplete: number;
  /** Days with a first punch: the base for hours. */
  days: number;
  worked: number;
  scheduled: number;
}

export function tallyByEmployee(rows: readonly AttendanceDay[]): EmployeeTally[] {
  const map = new Map<string, EmployeeTally>();
  for (const day of rows) {
    const e = map.get(day.employee_id) ?? { id: day.employee_id, present: 0, half: 0, absent: 0, leave: 0, off: 0, holiday: 0, incomplete: 0, days: 0, worked: 0, scheduled: 0 };
    const bucket = bucketOf(day);
    if (bucket === "PRESENT" || bucket === "REMOTE" || bucket === "ON_DUTY") e.present += 1;
    if (bucket === "HALF_DAY") e.half += 1;
    if (bucket === "ABSENT") e.absent += 1;
    if (bucket === "LEAVE") e.leave += 1;
    if (bucket === "WEEKLY_OFF") e.off += 1;
    if (bucket === "HOLIDAY") e.holiday += 1;
    if (bucket === "INCOMPLETE") e.incomplete += 1;
    if (day.actual_first_in) {
      e.days += 1;
      e.worked += day.worked_minutes;
      e.scheduled += day.scheduled_minutes ?? 0;
    }
    map.set(day.employee_id, e);
  }
  return Array.from(map.values());
}
