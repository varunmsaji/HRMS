/** Pure helpers for the employee self-service dashboard. Every figure comes from the backend's
 * own rows (attendance days, leave balances, requests); nothing here recalculates policy. */
import { addDays, weekStart } from "@/lib/attendance/dashboard";
import type { AttendanceDay } from "@/lib/attendance/types";

export type MonthBucket = "present" | "on_leave" | "absent" | "other";

const PRESENT = new Set(["PRESENT", "HALF_DAY", "WFH", "ON_DUTY"]);
const NOT_COUNTED = new Set(["NOT_JOINED", "EXITED", "NOT_EXPECTED"]);

export interface MonthSummary {
  counts: Record<MonthBucket, number>;
  total: number;
  weeklyOffs: number;
  holidays: number;
}

export function summariseMonth(days: AttendanceDay[]): MonthSummary {
  const counts: Record<MonthBucket, number> = { present: 0, on_leave: 0, absent: 0, other: 0 };
  let weeklyOffs = 0;
  let holidays = 0;
  for (const d of days) {
    if (d.calendar_day_type === "WEEKLY_OFF") weeklyOffs += 1;
    if (d.calendar_day_type === "HOLIDAY") holidays += 1;
    const status = d.attendance_status;
    if (NOT_COUNTED.has(status)) continue;
    if (PRESENT.has(status)) counts.present += 1;
    else if (status === "LEAVE") counts.on_leave += 1;
    else if (status === "ABSENT") counts.absent += 1;
    else counts.other += 1;
  }
  const total = counts.present + counts.on_leave + counts.absent + counts.other;
  return { counts, total, weeklyOffs, holidays };
}

export interface WeekBar {
  date: string;
  label: string;
  hours: number;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Monday..Sunday of the week containing `today`; days with no record are zero hours. */
export function weekBars(days: AttendanceDay[], today: string): WeekBar[] {
  const start = weekStart(today);
  const byDate = new Map(days.map((d) => [d.attendance_date, d]));
  return WEEKDAYS.map((label, i) => {
    const date = addDays(start, i);
    const minutes = byDate.get(date)?.worked_minutes ?? 0;
    return { date, label, hours: Math.round((minutes / 60) * 10) / 10 };
  });
}

export type PunchState = "in" | "out" | "none";

export function punchState(day: AttendanceDay | null | undefined): PunchState {
  if (!day?.actual_first_in) return "none";
  return day.actual_last_out ? "out" : "in";
}

/** `09:12` in the business timezone (24h, no zone suffix) for compact dashboard tiles. */
export function clock(iso: string | null | undefined, tz: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: tz,
  }).format(new Date(iso));
}

/** `6h 40m` */
export function duration(minutes: number): string {
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export function sumBalances(balances: { balance: string }[]): number {
  return balances.reduce((sum, b) => sum + (Number(b.balance) || 0), 0);
}

export function trimNumber(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export function longDate(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  })
    .format(new Date(`${iso}T00:00:00Z`))
    .replace(/^(\w+),?/, "$1,");
}

export function shortDay(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  })
    .format(new Date(`${iso}T00:00:00Z`))
    .replace(",", "");
}

export function leaveRange(start: string, end: string, totalDays: string): string {
  const days = Number(totalDays);
  const label = `${days} ${days === 1 ? "day" : "days"}`;
  return start === end ? `${shortDay(start)} · ${label}` : `${shortDay(start)} – ${shortDay(end)} · ${label}`;
}
