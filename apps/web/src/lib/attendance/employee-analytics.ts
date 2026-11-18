/** Pure view-model logic for the employee profile's attendance analytics: the "Today" strip, the
 * month tiles and the month calendar. Everything is derived from the persisted attendance days and
 * punches the API already serves, so the numbers match the attendance pages. */

import { bucketOf, type DayBucket } from "@/lib/attendance/dashboard";
import { monthDates } from "@/lib/attendance/hr-calendar";
import type { AttendanceDay, Punch } from "@/lib/attendance/types";

export { monthDates, shiftMonth } from "@/lib/attendance/hr-calendar";

/** Buckets on which the employee was expected to work. */
const EXPECTED: ReadonlySet<DayBucket> = new Set<DayBucket>([
  "PRESENT",
  "REMOTE",
  "ON_DUTY",
  "HALF_DAY",
  "ABSENT",
  "LEAVE",
  "INCOMPLETE",
]);

export interface MonthStats {
  /** Days the employee was expected to work, up to and including today. */
  expectedDays: number;
  /** Present, remote and on-duty days, a half day counting 0.5. */
  daysWorked: number;
  absent: number;
  leave: number;
  halfDays: number;
  /** Holidays and weekly offs in the month. */
  daysOff: number;
  lateDays: number;
  lateMinutes: number;
  earlyOutDays: number;
  earlyOutMinutes: number;
  workedMinutes: number;
  /** Average over days with a first punch; null when there are none. */
  avgWorkedMinutes: number | null;
  otDetectedMinutes: number;
  otApprovedMinutes: number;
  /** Share of days worked that were not late, 0-100; null when nothing was worked. */
  punctuality: number | null;
  missingPunch: number;
}

export function monthStats(days: AttendanceDay[], today: string): MonthStats {
  const s: MonthStats = {
    expectedDays: 0,
    daysWorked: 0,
    absent: 0,
    leave: 0,
    halfDays: 0,
    daysOff: 0,
    lateDays: 0,
    lateMinutes: 0,
    earlyOutDays: 0,
    earlyOutMinutes: 0,
    workedMinutes: 0,
    avgWorkedMinutes: null,
    otDetectedMinutes: 0,
    otApprovedMinutes: 0,
    punctuality: null,
    missingPunch: 0,
  };
  let checkedIn = 0;
  let onTimeWorked = 0;
  let workedDays = 0;
  for (const day of days) {
    if (day.attendance_date > today) continue;
    const bucket = bucketOf(day);
    if (EXPECTED.has(bucket)) s.expectedDays += 1;
    if (bucket === "PRESENT" || bucket === "REMOTE" || bucket === "ON_DUTY") {
      s.daysWorked += 1;
      workedDays += 1;
      if (!day.is_late) onTimeWorked += 1;
    } else if (bucket === "HALF_DAY") {
      s.daysWorked += 0.5;
      s.halfDays += 1;
      workedDays += 1;
      if (!day.is_late) onTimeWorked += 1;
    } else if (bucket === "ABSENT") s.absent += 1;
    else if (bucket === "LEAVE") s.leave += 1;
    else if (bucket === "HOLIDAY" || bucket === "WEEKLY_OFF") s.daysOff += 1;

    if (day.is_late) {
      s.lateDays += 1;
      s.lateMinutes += day.late_minutes;
    }
    if (day.is_early_out) {
      s.earlyOutDays += 1;
      s.earlyOutMinutes += day.early_departure_minutes;
    }
    if (day.missing_punch) s.missingPunch += 1;
    s.otDetectedMinutes += day.ot_minutes_detected;
    s.otApprovedMinutes += day.ot_minutes_approved;
    if (day.actual_first_in) {
      checkedIn += 1;
      s.workedMinutes += day.worked_minutes;
    }
  }
  if (checkedIn > 0) s.avgWorkedMinutes = Math.round(s.workedMinutes / checkedIn);
  if (workedDays > 0) s.punctuality = Math.round((onTimeWorked / workedDays) * 100);
  return s;
}

/** "18", "17.5" - one decimal only when there is a half day. */
export function formatDayCount(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export interface CalendarCell {
  date: string;
  /** Day of month, 1-31. */
  dayOfMonth: number;
  day: AttendanceDay | null;
  bucket: DayBucket | null;
  isToday: boolean;
  isFuture: boolean;
}

/** The month as Monday-first weeks. Days outside the month are null so the grid stays aligned. */
export function monthWeeks(
  month: string,
  days: AttendanceDay[],
  today: string,
): (CalendarCell | null)[][] {
  const byDate = new Map(days.map((d) => [d.attendance_date, d]));
  const dates = monthDates(month);
  const cells: (CalendarCell | null)[] = [];
  // getUTCDay: 0 = Sunday. Shift so Monday = 0.
  const lead = (new Date(`${dates[0]}T00:00:00Z`).getUTCDay() + 6) % 7;
  for (let i = 0; i < lead; i += 1) cells.push(null);
  for (const date of dates) {
    const day = byDate.get(date) ?? null;
    cells.push({
      date,
      dayOfMonth: Number(date.slice(8, 10)),
      day,
      bucket: day ? bucketOf(day) : null,
      isToday: date === today,
      isFuture: date > today,
    });
  }
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (CalendarCell | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** First and last date of a YYYY-MM month. */
export function monthRange(month: string): { from: string; to: string } {
  const dates = monthDates(month);
  return { from: dates[0], to: dates[dates.length - 1] };
}

export type TodayState =
  | "WORKING"
  | "ON_BREAK"
  | "CHECKED_OUT"
  | "NOT_STARTED"
  | "NOT_CHECKED_IN"
  | "ON_LEAVE"
  | "HOLIDAY"
  | "WEEKLY_OFF"
  | "NO_SHIFT"
  | "NOT_EMPLOYED"
  | "ABSENT";

export interface TodayStatus {
  state: TodayState;
  /** Shown beside the state, e.g. "since 9:02 am" is built by the caller from these. */
  holidayName: string | null;
  /** Latest IN punch when the employee is in; the first IN otherwise. */
  firstIn: string | null;
  lastOut: string | null;
  /** Minutes since the first punch while still in, or the engine's worked minutes once out. */
  workedMinutes: number | null;
  scheduledStart: string | null;
  scheduledEnd: string | null;
  /** Minutes until the shift ends (negative once it is over); null with no schedule. */
  minutesToShiftEnd: number | null;
  minutesToShiftStart: number | null;
}

/** Where the employee is right now. `punches` are today's, in any order; `day` is today's
 * attendance row if it has been calculated. Punches win over the day's calendar type, so someone
 * working on a holiday shows as working. */
export function todayStatus(day: AttendanceDay | null, punches: Punch[], now: Date): TodayStatus {
  const sorted = punches.slice().sort((a, b) => a.punch_time.localeCompare(b.punch_time));
  const first = sorted.find((p) => p.direction === "IN") ?? null;
  const last = sorted.length ? sorted[sorted.length - 1] : null;
  const lastOut = [...sorted].reverse().find((p) => p.direction === "OUT") ?? null;
  const base: TodayStatus = {
    state: "NO_SHIFT",
    holidayName: day?.holiday_name ?? null,
    firstIn: first?.punch_time ?? day?.actual_first_in ?? null,
    lastOut: lastOut?.punch_time ?? day?.actual_last_out ?? null,
    workedMinutes: null,
    scheduledStart: day?.scheduled_start ?? null,
    scheduledEnd: day?.scheduled_end ?? null,
    minutesToShiftEnd: null,
    minutesToShiftStart: null,
  };
  if (day?.scheduled_end) {
    base.minutesToShiftEnd = Math.round((new Date(day.scheduled_end).getTime() - now.getTime()) / 60000);
  }
  if (day?.scheduled_start) {
    base.minutesToShiftStart = Math.round((new Date(day.scheduled_start).getTime() - now.getTime()) / 60000);
  }

  if (last) {
    if (last.direction === "IN") {
      const openBreak = day?.breaks.some((b) => b.break_start && !b.break_end) ?? false;
      base.state = openBreak ? "ON_BREAK" : "WORKING";
      base.firstIn = first?.punch_time ?? last.punch_time;
      base.workedMinutes = Math.max(
        0,
        Math.round((now.getTime() - new Date(base.firstIn).getTime()) / 60000),
      );
    } else {
      base.state = "CHECKED_OUT";
      base.workedMinutes = day?.worked_minutes ?? null;
    }
    return base;
  }

  const bucket = day ? bucketOf(day) : null;
  if (bucket === "LEAVE") base.state = "ON_LEAVE";
  else if (bucket === "HOLIDAY") base.state = "HOLIDAY";
  else if (bucket === "WEEKLY_OFF") base.state = "WEEKLY_OFF";
  else if (bucket === "NOT_EMPLOYED") base.state = "NOT_EMPLOYED";
  else if (bucket === "ABSENT") base.state = "ABSENT";
  else if (day?.scheduled_start) {
    base.state = (base.minutesToShiftStart ?? 0) > 0 ? "NOT_STARTED" : "NOT_CHECKED_IN";
  } else base.state = "NO_SHIFT";
  return base;
}

/** "2h 10m" / "45m" for a positive minute count. */
export function formatCountdown(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (h === 0) return `${rest}m`;
  return rest === 0 ? `${h}h` : `${h}h ${rest}m`;
}

export interface DailyHoursBar {
  date: string;
  dayOfMonth: number;
  minutes: number;
  bucket: DayBucket;
  isLate: boolean;
}

/** One bar per day that has worked time, up to today, plus the shift length to draw as a
 * reference line (the most common scheduled length that month; null when none is scheduled). */
export function dailyHours(
  days: AttendanceDay[],
  today: string,
): { bars: DailyHoursBar[]; scheduledMinutes: number | null } {
  const bars: DailyHoursBar[] = [];
  const lengths = new Map<number, number>();
  for (const day of days.slice().sort((a, b) => a.attendance_date.localeCompare(b.attendance_date))) {
    if (day.attendance_date > today) continue;
    if (day.scheduled_minutes) lengths.set(day.scheduled_minutes, (lengths.get(day.scheduled_minutes) ?? 0) + 1);
    if (!day.actual_first_in || day.worked_minutes <= 0) continue;
    bars.push({
      date: day.attendance_date,
      dayOfMonth: Number(day.attendance_date.slice(8, 10)),
      minutes: day.worked_minutes,
      bucket: bucketOf(day),
      isLate: day.is_late,
    });
  }
  let scheduledMinutes: number | null = null;
  let best = 0;
  for (const [len, n] of lengths) {
    if (n > best) {
      best = n;
      scheduledMinutes = len;
    }
  }
  return { bars, scheduledMinutes };
}

export interface MonthTrendPoint {
  month: string;
  expectedDays: number;
  daysWorked: number;
  lateDays: number;
  absent: number;
}

/** The last `count` months ending at `endMonth` (YYYY-MM), oldest first. */
export function monthlyTrend(
  days: AttendanceDay[],
  endMonth: string,
  count: number,
  today: string,
): MonthTrendPoint[] {
  const out: MonthTrendPoint[] = [];
  for (let i = count - 1; i >= 0; i -= 1) {
    const month = shiftMonthLocal(endMonth, -i);
    const rows = days.filter((d) => d.attendance_date.startsWith(month));
    const s = monthStats(rows, today);
    out.push({ month, expectedDays: s.expectedDays, daysWorked: s.daysWorked, lateDays: s.lateDays, absent: s.absent });
  }
  return out;
}

function shiftMonthLocal(month: string, delta: number): string {
  const d = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1 + delta, 1));
  return d.toISOString().slice(0, 7);
}
