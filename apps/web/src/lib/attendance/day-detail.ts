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

/** The ids of the punches the backend assigned to this day (`computation_snapshot.inputs.punch_ids`),
 * or `null` when the row carries none (never calculated). */
export function ownedPunchIds(day: AttendanceDay): Set<string> | null {
  const inputs = (day.computation_snapshot as { inputs?: { punch_ids?: unknown } } | null)?.inputs;
  const ids = inputs?.punch_ids;
  return Array.isArray(ids) ? new Set(ids.filter((id): id is string => typeof id === "string")) : null;
}

/** Punches that belong to this day. The backend decides ownership (shift window, overnight shifts,
 * the company's business date) and records it on the row, so the screen shows exactly that set
 * instead of re-deriving it. A day that has never been calculated has no owned set; the fetched
 * list is shown as is. */
export function punchesForDay(punches: Punch[], day: AttendanceDay): Punch[] {
  const owned = ownedPunchIds(day);
  return owned === null ? punches : punches.filter((p) => owned.has(p.id));
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

/** The statuses the engine gives a day whose punches are missing or unfinished. */
const OPEN_STATUSES = new Set(["ABSENT", "INCOMPLETE"]);

/** True while today's shift is still running and the row's ABSENT / INCOMPLETE is only a placeholder.
 * The engine has no clock: an open check-in is a "missing punch" the moment it is calculated. The
 * company overview (`overview.py`) and the mobile day screen make the same call: no verdict until the
 * scheduled end (or, with no schedule, the end of the company's day, which `today` already bounds). */
export function isDayInProgress(day: AttendanceDay, today: string, now: Date): boolean {
  if (day.attendance_date !== today || day.is_locked) return false;
  if (!OPEN_STATUSES.has(day.attendance_status)) return false;
  return day.scheduled_end ? new Date(day.scheduled_end).getTime() > now.getTime() : true;
}

/** A plain-language account of the day, built only from the row's own facts. With `inProgress`
 * (see `isDayInProgress`) an unfinished day is described as running, not as missing a punch. */
export function summarizeDay(day: AttendanceDay, { inProgress = false }: { inProgress?: boolean } = {}): DaySummary {
  const problems: string[] = [];
  const context: string[] = [];
  if (day.missing_punch && !inProgress) problems.push("Missing punch");
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
  if (inProgress)
    headline = day.actual_first_in
      ? "Shift in progress — the day's result is worked out once the shift ends."
      : "Not checked in yet — the shift is still running.";
  else if (day.attendance_status === "LEAVE") headline = "On approved leave.";
  else if (
    day.attendance_status === "NOT_EXPECTED" ||
    day.calendar_day_type === "WEEKLY_OFF" ||
    (day.calendar_day_type === "HOLIDAY" && !day.actual_first_in)
  )
    headline = offDayHeadline(day);
  else if (day.attendance_status === "ABSENT") headline = "No attendance recorded for a scheduled day.";
  else if (day.attendance_status === "CONFIG_ERROR") headline = "This day could not be calculated — attendance setup needs attention.";
  else if (day.actual_first_in || day.worked_minutes > 0) {
    const scheduled = day.scheduled_minutes ? ` of ${formatMinutes(day.scheduled_minutes)} scheduled` : "";
    headline = `${formatMinutes(day.worked_minutes)} worked${scheduled}.`;
  } else headline = "No punches recorded yet.";

  return { headline, problems, context };
}

/** The headline for a day with no work expected, named by the calendar's own day type: a holiday is
 * never called a weekly off. */
function offDayHeadline(day: AttendanceDay): string {
  const worked = Boolean(day.actual_first_in);
  switch (day.calendar_day_type) {
    case "HOLIDAY": {
      const name = day.holiday_name ? ` — ${day.holiday_name}` : "";
      return worked ? `Worked on a holiday${name}.` : `Holiday${name}.`;
    }
    case "WEEKLY_OFF":
      return worked ? "Worked on a weekly off." : "Weekly off — no work expected.";
    case "SHUTDOWN":
      return worked ? "Worked during a company shutdown." : "Company shutdown — no work expected.";
    default:
      return worked ? "Worked on a day with no work scheduled." : "No work scheduled for this day.";
  }
}

function dayAmount(fraction: number): string {
  if (fraction === 1) return "Full day";
  if (fraction === 0.5) return "Half day";
  return `${fraction} day`;
}

/** What the day is worth to pay, in words, from the row's own fractions (the same ones the period
 * summary hands to Payroll). Never the raw "0.50". */
export function payEffect(day: AttendanceDay): string {
  if (day.attendance_status === "NOT_JOINED" || day.attendance_status === "EXITED") return "Not employed on this day";
  const paid = Number(day.paid_day_fraction) || 0;
  const lop = Number(day.lop_fraction) || 0;
  const leave = Number(day.leave_fraction) || 0;
  const unpaidOff = Number(day.unpaid_off_fraction) || 0;
  const parts: string[] = [];
  if (paid > 0) parts.push(`${dayAmount(paid)} paid`);
  if (lop > 0) parts.push(`${dayAmount(lop)} unpaid (loss of pay)`);
  if (unpaidOff > 0) parts.push(`${dayAmount(unpaidOff)} unpaid day off`);
  if (leave > 0) parts.push(`${dayAmount(leave)} on leave`);
  return parts.length > 0 ? parts.join(" · ") : "No pay effect";
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
