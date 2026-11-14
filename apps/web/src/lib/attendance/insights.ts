/** Types and small pure helpers behind the attendance dashboard's insight panels (pulse,
 * punctuality, weekday pattern, payroll readiness, department / branch breakdown). The figures
 * themselves are the backend's (`GET /v1/attendance/summary`, see `summary.ts`); nothing here
 * re-counts attendance days. A rate with no denominator is `null`, never a made-up 0%. */

import { addDays, dayDiff, groupName, UNASSIGNED, UNASSIGNED_KEY } from "@/lib/attendance/dashboard";
import type { AttendancePeriod } from "@/lib/attendance-period/types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

/** 0 = Monday … 6 = Sunday, for an ISO date (calendar maths in UTC, so no timezone drift). */
export function weekdayIndex(iso: string): number {
  return (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7;
}

export function weekdayShort(iso: string): string {
  return WEEKDAYS[weekdayIndex(iso)];
}

// ---------------------------------------------------------------------------
// Attendance rate: today's figure, its trend, and how it compares
// ---------------------------------------------------------------------------

export interface RatePoint {
  date: string;
  /** Present ÷ expected, 0–100. `null` when nobody was expected (weekend, holiday). */
  rate: number | null;
  expected: number;
  present: number;
}

export interface RateComparison {
  /** Percentage points, current − baseline. `null` when either side has no data. */
  delta: number | null;
  baselineDate: string;
  baselineRate: number | null;
}

/** Compare two days' rates. The baseline is normally the same weekday a week earlier, so a Monday
 * is never judged against a Sunday. */
export function compareRates(points: RatePoint[], date: string, baselineDate: string): RateComparison {
  const current = points.find((p) => p.date === date)?.rate ?? null;
  const baselineRate = points.find((p) => p.date === baselineDate)?.rate ?? null;
  return {
    delta: current !== null && baselineRate !== null ? current - baselineRate : null,
    baselineDate,
    baselineRate,
  };
}

export function sameWeekdayLastWeek(date: string): string {
  return addDays(date, -7);
}

// ---------------------------------------------------------------------------
// Punctuality
// ---------------------------------------------------------------------------

export interface PunctualitySummary {
  checkedIn: number;
  onTime: number;
  late: number;
  /** Late ÷ checked in, 0–100. */
  lateRate: number | null;
  onTimeRate: number | null;
  /** Average of `late_minutes` over late days only; `null` when nobody was late. */
  avgLateMinutes: number | null;
  bands: { key: string; label: string; count: number }[];
}

export interface FrequentLate {
  employeeId: string;
  lateDays: number;
  totalLateMinutes: number;
}

// ---------------------------------------------------------------------------
// Weekday pattern
// ---------------------------------------------------------------------------

export interface WeekdayStat {
  index: number;
  label: string;
  expected: number;
  absent: number;
  /** Absent ÷ expected, 0–100; `null` when that weekday never had anyone expected. */
  rate: number | null;
}

/** The weekday with the highest absence rate, or `null` when there's no signal worth naming
 * (no absences at all, or fewer than two weekdays with data to compare). */
export function worstWeekday(stats: WeekdayStat[]): WeekdayStat | null {
  const withData = stats.filter((s) => s.rate !== null);
  if (withData.length < 2) return null;
  const worst = withData.reduce((a, b) => ((b.rate ?? 0) > (a.rate ?? 0) ? b : a));
  return (worst.rate ?? 0) > 0 ? worst : null;
}

// ---------------------------------------------------------------------------
// Payroll readiness
// ---------------------------------------------------------------------------

export interface PeriodProgress {
  totalDays: number;
  /** Days of the period already behind us, clamped to 0…totalDays. */
  elapsedDays: number;
  /** Days until the period ends (0 = ends today); negative once it has ended. */
  daysLeft: number;
  /** 0–100. */
  percent: number;
}

export function periodProgress(period: Pick<AttendancePeriod, "period_start" | "period_end">, today: string): PeriodProgress {
  const totalDays = dayDiff(period.period_start, period.period_end) + 1;
  const elapsed = dayDiff(period.period_start, today) + 1;
  const elapsedDays = Math.min(totalDays, Math.max(0, elapsed));
  return {
    totalDays,
    elapsedDays,
    daysLeft: dayDiff(today, period.period_end),
    percent: totalDays > 0 ? (elapsedDays / totalDays) * 100 : 0,
  };
}

// ---------------------------------------------------------------------------
// Department / branch breakdown
// ---------------------------------------------------------------------------

export type BreakdownKey = "department" | "branch";

export interface GroupStat {
  /** The department / branch filter value: its id, or "unassigned". */
  key: string;
  name: string;
  /** Employees with a record on the day. */
  headcount: number;
  /** Of those, expected to work (not on a holiday, weekly off or not yet employed). */
  expected: number;
  present: number;
  absent: number;
  leave: number;
  late: number;
  /** Present ÷ expected, 0–100; `null` when nobody in the group was expected. */
  rate: number | null;
}

export interface GroupOption {
  /** The filter value: a department / branch id, or "unassigned". */
  key: string;
  name: string;
}

/** Departments (or branches) to filter by: everyone's current one from the employee directory, plus
 * any the summary's breakdown names (someone's group on that day), A–Z with "Unassigned" last.
 * Empty when nobody has one at all: a filter offering only "Unassigned" would be noise. */
export function groupOptions(
  directory: Iterable<{ department: string | null; branch: string | null; department_id?: string | null; branch_id?: string | null }>,
  key: BreakdownKey,
  breakdown: GroupStat[] = [],
): GroupOption[] {
  const options = new Map<string, string>();
  for (const row of directory) {
    const id = key === "department" ? row.department_id : row.branch_id;
    options.set(id ?? UNASSIGNED_KEY, id ? groupName(row[key]) : UNASSIGNED);
  }
  for (const group of breakdown) options.set(group.key, group.name);
  if (![...options.keys()].some((k) => k !== UNASSIGNED_KEY)) return [];
  return Array.from(options, ([k, name]) => ({ key: k, name })).sort((a, b) =>
    a.key === UNASSIGNED_KEY ? 1 : b.key === UNASSIGNED_KEY ? -1 : a.name.localeCompare(b.name),
  );
}
