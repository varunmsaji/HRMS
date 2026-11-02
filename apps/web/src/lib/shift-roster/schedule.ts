/** Mirrors `apps/api/src/hrms/modules/attendance/schedule_service.py` — the weekly operational
 * schedule and shift-swap requests. Every figure is computed server-side from stored roster data. */

export interface SchedulePerson {
  id: string;
  name: string;
  initials: string;
}

export interface ScheduleCell {
  date: string;
  count: number;
  /** null when the shift has no coverage target. */
  met: boolean | null;
  people: SchedulePerson[];
  has_pending_swap: boolean;
}

export interface ScheduleShift {
  id: string;
  name: string;
  code: string | null;
  start_time: string | null;
  end_time: string | null;
  is_night_shift: boolean;
  daily_hours: number;
  weekly_hours: number;
  min_staff: number | null;
  peak_staff: number;
  departments: string[];
  days_below_target: number;
  cells: ScheduleCell[];
}

export interface ScheduleTotals {
  active_headcount: number;
  rostered_staff: number;
  coverage_pct: number | null;
  shifts_with_target: number;
  cells_below_target: number;
  night_staff: number;
  night_shift_count: number;
  pending_swaps: number;
  allocated_hours: number;
  last_roster_update: string | null;
}

export interface WeeklySchedule {
  week_start: string;
  week_end: string;
  days: string[];
  shifts: ScheduleShift[];
  totals: ScheduleTotals;
}

export interface SwapParty {
  employee_id: string;
  name: string;
  code: string;
  department: string | null;
  shift_id: string;
  shift_name: string;
  shift_start: string | null;
  shift_end: string | null;
}

export interface SwapRequest {
  id: string;
  reference: string;
  swap_date: string;
  status: "PENDING" | "APPROVED" | "DECLINED";
  reason: string | null;
  counterpart_consented: boolean;
  coverage_ok: boolean;
  requester: SwapParty;
  counterpart: SwapParty;
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
}

export function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function mondayOf(iso: string): string {
  const dow = (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7;
  return addDays(iso, -dow);
}

/** ISO-8601 week number (the "Week 44" in the header). */
export function isoWeek(iso: string): number {
  const d = new Date(`${iso}T00:00:00Z`);
  const day = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - day + 3);
  const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  const diff = (d.getTime() - firstThursday.getTime()) / 86_400_000;
  return 1 + Math.round((diff - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
}

/** "09:30:00" -> "09:30". */
export function hhmm(time: string | null): string {
  return time ? time.slice(0, 5) : "—";
}

export function timeRange(start: string | null, end: string | null): string {
  return start && end ? `${hhmm(start)} – ${hhmm(end)}` : "—";
}

export function formatHours(hours: number): string {
  return Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Mon 02 Nov" — built by hand so the label never varies with the runtime's ICU data. */
export function shortDate(iso: string, withYear = false): string {
  const d = new Date(`${iso}T00:00:00Z`);
  const base = `${WEEKDAYS[d.getUTCDay()]} ${String(d.getUTCDate()).padStart(2, "0")} ${MONTHS[d.getUTCMonth()]}`;
  return withYear ? `${base} ${d.getUTCFullYear()}` : base;
}

export function weekLabel(start: string, end: string): string {
  return `Week ${isoWeek(start)}: ${shortDate(start)} – ${shortDate(end, true)}`;
}
