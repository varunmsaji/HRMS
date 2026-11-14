import { eachDate } from "@/lib/attendance/dashboard";
import type { WeekdayStat } from "@/lib/attendance/insights";
import type { AttendanceSummary, SummaryDay, SummaryKpis } from "@/lib/attendance/summary";

/** `GET /v1/attendance/summary` payloads for tests: zeros everywhere unless a test says otherwise. */

export function makeKpis(overrides: Partial<SummaryKpis> = {}): SummaryKpis {
  return {
    total_employees: 0,
    no_record: 0,
    present: 0,
    remote: 0,
    on_duty: 0,
    absent: 0,
    leave: 0,
    half_day: 0,
    holiday: 0,
    weekly_off: 0,
    incomplete: 0,
    late: 0,
    not_checked_in: 0,
    checked_in: 0,
    exceptions: 0,
    overtime_employees: 0,
    overtime_minutes_detected: 0,
    overtime_minutes_approved: 0,
    not_employed: 0,
    ...overrides,
  };
}

export function makeSummaryDay(date: string, overrides: Partial<SummaryDay> = {}): SummaryDay {
  const day = { date, expected: 0, present: 0, remote: 0, absent: 0, leave: 0, late: 0, checked_in: 0, worked_minutes: 0, ...overrides };
  return { ...day, rate: overrides.rate !== undefined ? overrides.rate : day.expected > 0 ? (day.present / day.expected) * 100 : null };
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Mon → Sun; `overrides` sets `[expected, absent]` for a weekday index. */
export function makeWeekdays(overrides: Record<number, [number, number]> = {}): WeekdayStat[] {
  return WEEKDAYS.map((label, index) => {
    const [expected, absent] = overrides[index] ?? [0, 0];
    return { index, label, expected, absent, rate: expected > 0 ? (absent / expected) * 100 : null };
  });
}

/** A summary for `from`…`to` (the focus date); `days` replaces individual days of the series. */
export function makeSummary(
  from: string,
  to: string,
  overrides: Partial<Omit<AttendanceSummary, "daily">> & { days?: SummaryDay[] } = {},
): AttendanceSummary {
  const { days = [], ...rest } = overrides;
  const byDate = new Map(days.map((d) => [d.date, d]));
  return {
    date_from: from,
    date_to: to,
    focus_date: to,
    compare_date: to,
    is_today: true,
    row_count: 0,
    daily: eachDate(from, to).map((date) => byDate.get(date) ?? makeSummaryDay(date)),
    focus: makeKpis(),
    compare: null,
    distribution: [],
    punctuality: {
      checked_in: 0,
      on_time: 0,
      late: 0,
      late_rate: null,
      on_time_rate: null,
      avg_late_minutes: null,
      bands: [
        { key: "1_15", label: "1–15 min", count: 0 },
        { key: "16_30", label: "16–30 min", count: 0 },
        { key: "31_60", label: "31–60 min", count: 0 },
        { key: "60_plus", label: "Over an hour", count: 0 },
      ],
    },
    frequent_late: [],
    weekday_absence: makeWeekdays(),
    by_department: [],
    by_branch: [],
    ...rest,
  };
}
