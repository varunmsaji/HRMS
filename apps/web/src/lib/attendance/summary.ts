/** `GET /v1/attendance/summary`: the dashboard totals, counted by the backend over every attendance
 * day in the window. The page only reshapes them for its panels here; it never re-adds rows, so the
 * web and mobile dashboards show the same figures. */

import {
  BUCKET_LABELS,
  DAY_BUCKETS,
  type DashboardFilters,
  type DateRange,
  type DayBucket,
  type DistributionEntry,
  type KpiSet,
  UNASSIGNED_KEY,
} from "@/lib/attendance/dashboard";
import type { FrequentLate, GroupStat, PunctualitySummary, RatePoint, WeekdayStat } from "@/lib/attendance/insights";

/** One calendar day of the window. `rate` = present ÷ expected, `null` when nobody was expected. */
export interface SummaryDay {
  date: string;
  expected: number;
  present: number;
  rate: number | null;
  remote: number;
  absent: number;
  leave: number;
  late: number;
  checked_in: number;
  worked_minutes: number;
}

export interface SummaryKpis {
  total_employees: number;
  no_record: number;
  present: number;
  remote: number;
  on_duty: number;
  absent: number;
  leave: number;
  half_day: number;
  holiday: number;
  weekly_off: number;
  incomplete: number;
  late: number;
  not_checked_in: number;
  checked_in: number;
  exceptions: number;
  overtime_employees: number;
  overtime_minutes_detected: number;
  overtime_minutes_approved: number;
  not_employed: number;
}

export interface SummaryGroup {
  /** `null` for "Unassigned". */
  id: string | null;
  name: string;
  headcount: number;
  expected: number;
  present: number;
  absent: number;
  leave: number;
  late: number;
  rate: number | null;
}

export interface AttendanceSummary {
  date_from: string;
  date_to: string;
  focus_date: string;
  compare_date: string;
  is_today: boolean;
  row_count: number;
  daily: SummaryDay[];
  focus: SummaryKpis;
  compare: SummaryKpis | null;
  /** Only the buckets with at least one day, in display order. */
  distribution: { bucket: string; count: number }[];
  punctuality: {
    checked_in: number;
    on_time: number;
    late: number;
    late_rate: number | null;
    on_time_rate: number | null;
    avg_late_minutes: number | null;
    bands: { key: string; label: string; count: number }[];
  };
  frequent_late: { employee_id: string; late_days: number; total_late_minutes: number }[];
  weekday_absence: WeekdayStat[];
  by_department: SummaryGroup[];
  by_branch: SummaryGroup[];
}

/** The filter value a breakdown group selects. */
export function groupKey(id: string | null): string {
  return id ?? UNASSIGNED_KEY;
}

/** The summary request for `window` (its last day is the focus date) and the population filters.
 * The drill-down filters (`bucket`, `flag`) narrow lists only, so they are not sent. */
export function summaryQuery(window: DateRange, filters: DashboardFilters): Record<string, string> {
  const query: Record<string, string> = { date_from: window.from, date_to: window.to };
  if (filters.employeeId) query.employee_id = filters.employeeId;
  if (filters.shiftId) query.shift_id = filters.shiftId;
  if (filters.employeeStatus) query.employee_status = filters.employeeStatus;
  if (filters.department) query.department_id = filters.department;
  if (filters.branch) query.branch_id = filters.branch;
  return query;
}

export function toKpiSet(k: SummaryKpis): KpiSet {
  return {
    totalEmployees: k.total_employees,
    noRecord: k.no_record,
    present: k.present,
    remote: k.remote,
    onDuty: k.on_duty,
    absent: k.absent,
    leave: k.leave,
    halfDay: k.half_day,
    holiday: k.holiday,
    weeklyOff: k.weekly_off,
    incomplete: k.incomplete,
    late: k.late,
    notCheckedIn: k.not_checked_in,
    checkedIn: k.checked_in,
    exceptions: k.exceptions,
    overtimeEmployees: k.overtime_employees,
    overtimeMinutesDetected: k.overtime_minutes_detected,
    overtimeMinutesApproved: k.overtime_minutes_approved,
    notEmployed: k.not_employed,
  };
}

/** Every bucket, in display order, with a zero where the summary had none. */
export function toDistribution(entries: AttendanceSummary["distribution"]): DistributionEntry[] {
  const counts = new Map(entries.map((e) => [e.bucket, e.count]));
  return DAY_BUCKETS.map((bucket: DayBucket) => ({ bucket, label: BUCKET_LABELS[bucket], count: counts.get(bucket) ?? 0 }));
}

export function toRatePoints(daily: SummaryDay[]): RatePoint[] {
  return daily.map((d) => ({ date: d.date, rate: d.rate, expected: d.expected, present: d.present }));
}

export function toPunctuality(p: AttendanceSummary["punctuality"]): PunctualitySummary {
  return {
    checkedIn: p.checked_in,
    onTime: p.on_time,
    late: p.late,
    lateRate: p.late_rate,
    onTimeRate: p.on_time_rate,
    avgLateMinutes: p.avg_late_minutes,
    bands: p.bands,
  };
}

export function toFrequentLate(list: AttendanceSummary["frequent_late"]): FrequentLate[] {
  return list.map((f) => ({ employeeId: f.employee_id, lateDays: f.late_days, totalLateMinutes: f.total_late_minutes }));
}

export function toGroupStats(groups: SummaryGroup[]): GroupStat[] {
  return groups.map(({ id, ...rest }) => ({ ...rest, key: groupKey(id) }));
}
