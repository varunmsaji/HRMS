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
