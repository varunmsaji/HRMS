/** Pure calculations behind the attendance dashboard's insight panels (pulse, punctuality,
 * weekday pattern, payroll readiness). Everything derives from the attendance days the page has
 * already loaded — no extra requests. A rate with no denominator is `null`, never a made-up 0%. */

import {
  addDays,
  bucketOf,
  dayDiff,
  eachDate,
  groupName,
  isAttending,
  isExpectedBucket,
  pct,
  UNASSIGNED,
  type DateRange,
} from "@/lib/attendance/dashboard";
import type { AttendancePeriod } from "@/lib/attendance-period/types";
import type { AttendanceDay } from "@/lib/attendance/types";

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

/** One point per calendar day in `range`, in order. */
export function dailyAttendanceRate(rows: AttendanceDay[], range: DateRange): RatePoint[] {
  const tallies = new Map<string, { expected: number; present: number }>();
  for (const date of eachDate(range.from, range.to)) tallies.set(date, { expected: 0, present: 0 });
  for (const day of rows) {
    const tally = tallies.get(day.attendance_date);
    if (!tally) continue;
    const bucket = bucketOf(day);
    if (isExpectedBucket(bucket)) tally.expected += 1;
    if (isAttending(bucket)) tally.present += 1;
  }
  return Array.from(tallies.entries()).map(([date, t]) => ({
    date,
    rate: pct(t.present, t.expected),
    expected: t.expected,
    present: t.present,
  }));
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

export const LATE_BANDS = [
  { key: "1_15", label: "1–15 min", min: 1, max: 15 },
  { key: "16_30", label: "16–30 min", min: 16, max: 30 },
  { key: "31_60", label: "31–60 min", min: 31, max: 60 },
  { key: "60_plus", label: "Over an hour", min: 61, max: Infinity },
] as const;

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

export function punctualitySummary(rows: AttendanceDay[]): PunctualitySummary {
  let checkedIn = 0;
  let late = 0;
  let lateMinutes = 0;
  const counts = new Map<string, number>(LATE_BANDS.map((b) => [b.key, 0]));
  for (const day of rows) {
    if (!day.actual_first_in) continue;
    checkedIn += 1;
    if (!day.is_late) continue;
    late += 1;
    lateMinutes += day.late_minutes;
    // A late day with no minutes recorded is still late; it lands in the smallest band.
    const minutes = Math.max(1, day.late_minutes);
    const band = LATE_BANDS.find((b) => minutes >= b.min && minutes <= b.max);
    if (band) counts.set(band.key, (counts.get(band.key) ?? 0) + 1);
  }
  const onTime = checkedIn - late;
  return {
    checkedIn,
    onTime,
    late,
    lateRate: pct(late, checkedIn),
    onTimeRate: pct(onTime, checkedIn),
    avgLateMinutes: late > 0 ? lateMinutes / late : null,
    bands: LATE_BANDS.map((b) => ({ key: b.key, label: b.label, count: counts.get(b.key) ?? 0 })),
  };
}

export interface FrequentLate {
  employeeId: string;
  lateDays: number;
  totalLateMinutes: number;
}

/** Employees who were late on at least `minDays` days, most first (ties: more minutes first). */
export function frequentLateArrivals(rows: AttendanceDay[], limit = 5, minDays = 2): FrequentLate[] {
  const byEmployee = new Map<string, FrequentLate>();
  for (const day of rows) {
    if (!day.is_late) continue;
    const entry = byEmployee.get(day.employee_id) ?? {
      employeeId: day.employee_id,
      lateDays: 0,
      totalLateMinutes: 0,
    };
    entry.lateDays += 1;
    entry.totalLateMinutes += day.late_minutes;
    byEmployee.set(day.employee_id, entry);
  }
  return Array.from(byEmployee.values())
    .filter((e) => e.lateDays >= minDays)
    .sort((a, b) => b.lateDays - a.lateDays || b.totalLateMinutes - a.totalLateMinutes)
    .slice(0, limit);
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

/** Absence rate for each weekday over the rows given (Mon → Sun). */
export function weekdayAbsence(rows: AttendanceDay[]): WeekdayStat[] {
  const stats: WeekdayStat[] = WEEKDAYS.map((label, index) => ({ index, label, expected: 0, absent: 0, rate: null }));
  for (const day of rows) {
    const bucket = bucketOf(day);
    if (!isExpectedBucket(bucket)) continue;
    const stat = stats[weekdayIndex(day.attendance_date)];
    stat.expected += 1;
    if (bucket === "ABSENT") stat.absent += 1;
  }
  for (const stat of stats) stat.rate = pct(stat.absent, stat.expected);
  return stats;
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

/** Attendance for each department (or branch) on one day. `rows` should be a single day's rows —
 * one per employee — so headcount means people, not person-days. Lowest attendance comes first,
 * groups nobody was expected in last, so the places that need a look are at the top. */
export function breakdownBy(
  rows: AttendanceDay[],
  directory: Map<string, { department: string | null; branch: string | null }>,
  key: BreakdownKey,
): GroupStat[] {
  const groups = new Map<string, GroupStat>();
  for (const day of rows) {
    const bucket = bucketOf(day);
    const name = groupName(directory.get(day.employee_id)?.[key]);
    const g = groups.get(name) ?? { name, headcount: 0, expected: 0, present: 0, absent: 0, leave: 0, late: 0, rate: null };
    g.headcount += 1;
    if (isExpectedBucket(bucket)) g.expected += 1;
    if (isAttending(bucket)) g.present += 1;
    if (bucket === "ABSENT") g.absent += 1;
    if (bucket === "LEAVE") g.leave += 1;
    if (day.is_late) g.late += 1;
    groups.set(name, g);
  }
  const stats = Array.from(groups.values());
  for (const g of stats) g.rate = pct(g.present, g.expected);
  return stats.sort((a, b) => {
    if (a.rate === null && b.rate === null) return a.name.localeCompare(b.name);
    if (a.rate === null) return 1;
    if (b.rate === null) return -1;
    return a.rate - b.rate || b.headcount - a.headcount || a.name.localeCompare(b.name);
  });
}

/** Distinct department / branch names present in the directory, A–Z, "Unassigned" last. */
export function groupNames(
  directory: Map<string, { department: string | null; branch: string | null }>,
  key: BreakdownKey,
): string[] {
  const names = new Set<string>();
  for (const row of directory.values()) names.add(groupName(row[key]));
  return Array.from(names).sort((a, b) =>
    a === UNASSIGNED ? 1 : b === UNASSIGNED ? -1 : a.localeCompare(b),
  );
}
