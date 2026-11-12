import { formatMinutes } from "@/lib/attendance/format";
import type { AttendanceDay, Punch } from "@/lib/attendance/types";

export interface BreakEventLite {
  id: string;
  event_type: string; // START | END
  event_time: string;
  break_name: string | null;
  source: string;
}

export interface TimelineItem {
  key: string;
  time: string | null;
  kind: "IN" | "OUT" | "BREAK_START" | "BREAK_END" | "MISSING_OUT";
  label: string;
  /** Where the record came from, e.g. "Web", "Regularization". */
  source: string | null;
}

const SOURCE_LABELS: Record<string, string> = {
  WEB: "Web",
  MOBILE: "Mobile app",
  DEVICE: "Device",
  IMPORT: "Import",
  ADMIN: "Entered by HR",
  API: "API",
  REGULARIZATION: "Regularization",
};

export function sourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return SOURCE_LABELS[source] ?? source.charAt(0) + source.slice(1).toLowerCase();
}

const SIX_HOURS = 6 * 3_600_000;

/** Punches that belong to this day. The list endpoint filters by calendar date, so for an overnight
 * shift it can include neighbouring punches; keep those within six hours of the day's own window. */
export function punchesForDay(punches: Punch[], day: AttendanceDay): Punch[] {
  const start = day.scheduled_start ?? day.actual_first_in;
  const end = day.scheduled_end ?? day.actual_last_out;
  // No window (an off day nobody punched on): the fetch spans the next day too, for overnight
  // shifts, so keep only this day's punches by the endpoint's own UTC-date rule.
  if (!start && !end) {
    return punches.filter((p) => new Date(p.punch_time).toISOString().startsWith(day.attendance_date));
  }
  const lo = start ? new Date(start).getTime() - SIX_HOURS : Number.NEGATIVE_INFINITY;
  const hi = end ? new Date(end).getTime() + SIX_HOURS : Number.POSITIVE_INFINITY;
  return punches.filter((p) => {
    const t = new Date(p.punch_time).getTime();
    return t >= lo && t <= hi;
  });
}

/** One chronological list of the day's punches and break events; a day flagged with a missing
 * punch ends with an explicit gap marker instead of silently stopping. */
export function buildTimeline(day: AttendanceDay, punches: Punch[], breakEvents: BreakEventLite[]): TimelineItem[] {
  const items: TimelineItem[] = [
    ...punchesForDay(punches, day).map((p): TimelineItem => ({
      key: `p-${p.id}`,
      time: p.punch_time,
      kind: p.direction === "IN" ? "IN" : "OUT",
      label: p.direction === "IN" ? "Punched in" : "Punched out",
      source: sourceLabel(p.source),
    })),
    ...breakEvents.map((e): TimelineItem => ({
      key: `b-${e.id}`,
      time: e.event_time,
      kind: e.event_type === "START" ? "BREAK_START" : "BREAK_END",
      label: `${e.event_type === "START" ? "Break started" : "Break ended"}${e.break_name ? ` — ${e.break_name}` : ""}`,
      source: sourceLabel(e.source),
    })),
  ].sort((a, b) => (a.time ?? "").localeCompare(b.time ?? ""));

  const last = [...items].reverse().find((i) => i.kind === "IN" || i.kind === "OUT");
  if (day.missing_punch && (!last || last.kind === "IN")) {
    items.push({ key: "missing-out", time: null, kind: "MISSING_OUT", label: "Punch-out missing", source: null });
  }
  return items;
}

export interface DaySummary {
  headline: string;
  /** Things that went wrong on the day. */
  problems: string[];
  /** Neutral context about how the day was treated. */
  context: string[];
}

/** A plain-language account of the day, built only from the row's own facts. */
export function summarizeDay(day: AttendanceDay): DaySummary {
  const problems: string[] = [];
  const context: string[] = [];
  if (day.missing_punch) problems.push("Missing punch");
  if (day.is_late) problems.push(day.late_minutes > 0 ? `Late by ${formatMinutes(day.late_minutes)}` : "Late");
  if (day.is_early_out)
    problems.push(
      day.early_departure_minutes > 0 ? `Left ${formatMinutes(day.early_departure_minutes)} early` : "Left early",
    );
  if (day.is_core_hours_breach) problems.push("Core hours breach");
  if (day.work_on_leave_flagged && !day.work_on_leave_resolution) problems.push("Worked on leave — needs HR decision");
  if (day.is_pending_approval) problems.push("Awaiting approval");

  if (day.is_overtime) context.push(`Overtime ${formatMinutes(day.ot_minutes_detected)}`);
  if (day.is_regularized) context.push("Regularized");
  if (day.worked_on_holiday) context.push("Worked on a holiday");
  if (day.worked_on_weekly_off) context.push("Worked on a weekly off");
  if (day.on_duty) context.push("On duty");
  if (day.work_on_leave_flagged && day.work_on_leave_resolution === "KEEP_LEAVE") context.push("Leave kept by HR");
  if (day.is_locked) context.push("Locked for payroll");

  let headline: string;
  if (day.attendance_status === "LEAVE") headline = "On approved leave.";
  else if (day.attendance_status === "NOT_EXPECTED" || day.calendar_day_type === "WEEKLY_OFF")
    headline = day.actual_first_in ? "Worked on a weekly off." : "Weekly off — no work expected.";
  else if (day.calendar_day_type === "HOLIDAY" && !day.actual_first_in)
    headline = `Holiday${day.holiday_name ? ` — ${day.holiday_name}` : ""}.`;
  else if (day.attendance_status === "ABSENT") headline = "No attendance recorded for a scheduled day.";
  else if (day.attendance_status === "CONFIG_ERROR") headline = "This day could not be calculated — attendance setup needs attention.";
  else if (day.actual_first_in || day.worked_minutes > 0) {
    const scheduled = day.scheduled_minutes ? ` of ${formatMinutes(day.scheduled_minutes)} scheduled` : "";
    headline = `${formatMinutes(day.worked_minutes)} worked${scheduled}.`;
  } else headline = "No punches recorded yet.";

  return { headline, problems, context };
}

/** Short labels for what is wrong with a day, for tables and lists. Empty when nothing is. */
export function exceptionLabels(day: AttendanceDay): string[] {
  const labels: string[] = [];
  if (day.missing_punch) labels.push("Missing punch");
  if (day.attendance_status === "CONFIG_ERROR") labels.push("Config error");
  if (day.attendance_status === "INCOMPLETE" && !day.missing_punch) labels.push("Incomplete");
  if (day.is_pending_approval) labels.push("Pending approval");
  if (day.work_on_leave_flagged && day.work_on_leave_resolution === null) labels.push("Worked on leave");
  return labels;
}

/** Whole minutes between a check-in and `now`; null when there is no check-in or it is in the future. */
export function minutesSince(iso: string | null | undefined, now: Date): number | null {
  if (!iso) return null;
  const ms = now.getTime() - new Date(iso).getTime();
  return ms >= 0 ? Math.floor(ms / 60_000) : null;
}

export interface RangePreset {
  key: string;
  label: string;
  from: string;
  to: string;
}

function addIsoDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Quick date ranges, all computed from the company's business date (never the browser's). */
export function rangePresets(today: string): RangePreset[] {
  const monthStart = `${today.slice(0, 7)}-01`;
  const lastMonthEnd = addIsoDays(monthStart, -1);
  return [
    { key: "7d", label: "Last 7 days", from: addIsoDays(today, -6), to: today },
    { key: "month", label: "This month", from: monthStart, to: today },
    { key: "last-month", label: "Last month", from: `${lastMonthEnd.slice(0, 7)}-01`, to: lastMonthEnd },
  ];
}
