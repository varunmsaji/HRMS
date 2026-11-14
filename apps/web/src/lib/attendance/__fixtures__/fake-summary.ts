/** A stand-in for `GET /v1/attendance/summary` in page tests: counts a test's attendance days the
 * way the backend does (`apps/api/src/hrms/modules/attendance/summary.py`, whose integration tests
 * are the real check of every figure), so a page test can serve one set of rows and see the same
 * totals the API would give. Never imported by app code. */

import {
  addDays,
  bucketOf,
  DAY_BUCKETS,
  eachDate,
  hasException,
  isAttending,
  isEmployedOn,
  isExpectedBucket,
  isNotCheckedIn,
  pct,
  UNASSIGNED,
  UNASSIGNED_KEY,
  type DayBucket,
  type EmployeeLite,
} from "@/lib/attendance/dashboard";
import { weekdayIndex } from "@/lib/attendance/insights";
import type { AttendanceSummary, SummaryGroup, SummaryKpis } from "@/lib/attendance/summary";
import type { AttendanceDay } from "@/lib/attendance/types";

/** An employee's department / branch as the backend knows it. */
export interface FakeOrg {
  department_id: string | null;
  department: string | null;
  branch_id: string | null;
  branch: string | null;
}

const BANDS = [
  { key: "1_15", label: "1–15 min", min: 1, max: 15 },
  { key: "16_30", label: "16–30 min", min: 16, max: 30 },
  { key: "31_60", label: "31–60 min", min: 31, max: 60 },
  { key: "60_plus", label: "Over an hour", min: 61, max: Infinity },
];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function kpis(rows: AttendanceDay[], noRecord: number): SummaryKpis {
  const k: SummaryKpis = {
    total_employees: 0, no_record: noRecord, present: 0, remote: 0, on_duty: 0, absent: 0, leave: 0, half_day: 0,
    holiday: 0, weekly_off: 0, incomplete: 0, late: 0, not_checked_in: noRecord, checked_in: 0, exceptions: 0,
    overtime_employees: 0, overtime_minutes_detected: 0, overtime_minutes_approved: 0, not_employed: 0,
  }; // prettier-ignore
  const field: Partial<Record<DayBucket, keyof SummaryKpis>> = {
    PRESENT: "present", REMOTE: "remote", ON_DUTY: "on_duty", ABSENT: "absent", LEAVE: "leave",
    HALF_DAY: "half_day", HOLIDAY: "holiday", WEEKLY_OFF: "weekly_off", INCOMPLETE: "incomplete",
  }; // prettier-ignore
  let employed = 0;
  for (const day of rows) {
    const bucket = bucketOf(day);
    if (bucket === "NOT_EMPLOYED") {
      k.not_employed += 1;
      continue;
    }
    employed += 1;
    const f = field[bucket];
    if (f) k[f] += 1;
    if (day.actual_first_in) k.checked_in += 1;
    if (day.is_late) k.late += 1;
    if (isNotCheckedIn(day)) k.not_checked_in += 1;
    if (hasException(day)) k.exceptions += 1;
    if (day.ot_minutes_detected > 0) {
      k.overtime_employees += 1;
      k.overtime_minutes_detected += day.ot_minutes_detected;
      k.overtime_minutes_approved += day.ot_minutes_approved;
    }
  }
  k.total_employees = employed + noRecord;
  return k;
}

function breakdown(rows: AttendanceDay[], orgOf: (id: string) => FakeOrg | undefined, key: "department" | "branch"): SummaryGroup[] {
  const groups = new Map<string, SummaryGroup>();
  for (const day of rows) {
    const org = orgOf(day.employee_id);
    const id = (key === "department" ? org?.department_id : org?.branch_id) ?? null;
    const name = id ? ((key === "department" ? org?.department : org?.branch) ?? UNASSIGNED) : UNASSIGNED;
    const g = groups.get(id ?? "") ?? { id, name, headcount: 0, expected: 0, present: 0, absent: 0, leave: 0, late: 0, rate: null };
    const bucket = bucketOf(day);
    g.headcount += 1;
    if (isExpectedBucket(bucket)) g.expected += 1;
    if (isAttending(bucket)) g.present += 1;
    if (bucket === "ABSENT") g.absent += 1;
    if (bucket === "LEAVE") g.leave += 1;
    if (day.is_late) g.late += 1;
    groups.set(id ?? "", g);
  }
  const stats = Array.from(groups.values());
  for (const g of stats) g.rate = pct(g.present, g.expected);
  return stats.sort((a, b) => {
    if (a.rate === null || b.rate === null) return a.rate === b.rate ? a.name.localeCompare(b.name) : a.rate === null ? 1 : -1;
    return a.rate - b.rate || b.headcount - a.headcount || a.name.localeCompare(b.name);
  });
}

export function fakeSummary(
  query: URLSearchParams,
  days: AttendanceDay[],
  employees: EmployeeLite[],
  orgOf: (employeeId: string) => FakeOrg | undefined,
  today: string,
): AttendanceSummary {
  const from = query.get("date_from") ?? today;
  const to = query.get("date_to") ?? today;
  const byId = new Map(employees.map((e) => [e.id, e]));
  const groupMatches = (employeeId: string, key: "department" | "branch", value: string | null) => {
    if (!value) return true;
    const org = orgOf(employeeId);
    return ((key === "department" ? org?.department_id : org?.branch_id) ?? UNASSIGNED_KEY) === value;
  };
  const inPopulation = (day: AttendanceDay, orgFilters: boolean) => {
    if (query.get("employee_id") && day.employee_id !== query.get("employee_id")) return false;
    if (query.get("shift_id") && day.shift_id !== query.get("shift_id")) return false;
    if (query.get("employee_status") && byId.get(day.employee_id)?.status !== query.get("employee_status")) return false;
    if (orgFilters && !groupMatches(day.employee_id, "department", query.get("department_id"))) return false;
    if (orgFilters && !groupMatches(day.employee_id, "branch", query.get("branch_id"))) return false;
    return true;
  };
  const rows = days.filter((d) => d.attendance_date >= from && d.attendance_date <= to && inPopulation(d, true));
  const on = (date: string) => rows.filter((d) => d.attendance_date === date);

  const daily = eachDate(from, to).map((date) => {
    const t = { date, expected: 0, present: 0, remote: 0, absent: 0, leave: 0, late: 0, checked_in: 0, worked_minutes: 0 };
    for (const day of on(date)) {
      const bucket = bucketOf(day);
      if (isExpectedBucket(bucket)) t.expected += 1;
      if (isAttending(bucket)) t.present += 1;
      if (bucket === "REMOTE") t.remote += 1;
      if (bucket === "ABSENT") t.absent += 1;
      if (bucket === "LEAVE") t.leave += 1;
      if (day.is_late) t.late += 1;
      if (day.actual_first_in) {
        t.checked_in += 1;
        t.worked_minutes += day.worked_minutes;
      }
    }
    return { ...t, rate: pct(t.present, t.expected) };
  });

  let noRecord = 0;
  if (to === today && !query.get("shift_id")) {
    const seen = new Set(on(to).map((d) => d.employee_id));
    noRecord = employees.filter(
      (e) =>
        !seen.has(e.id) &&
        e.is_active !== false &&
        isEmployedOn(e, to) &&
        (!query.get("employee_id") || e.id === query.get("employee_id")) &&
        (!query.get("employee_status") || e.status === query.get("employee_status")) &&
        groupMatches(e.id, "department", query.get("department_id")) &&
        groupMatches(e.id, "branch", query.get("branch_id")),
    ).length;
  }

  const compareDate = addDays(to, -7);
  const compareRows =
    compareDate >= from
      ? on(compareDate)
      : days.filter((d) => d.attendance_date === compareDate && inPopulation(d, true));

  const focusRows = on(to);
  const counts = new Map<string, number>();
  for (const day of focusRows) counts.set(bucketOf(day), (counts.get(bucketOf(day)) ?? 0) + 1);

  const complete = rows.filter((d) => d.actual_first_in && d.actual_last_out);
  const lateDays = complete.filter((d) => d.is_late);
  const lateMinutes = lateDays.reduce((sum, d) => sum + d.late_minutes, 0);

  const lateBy = new Map<string, { employee_id: string; late_days: number; total_late_minutes: number }>();
  for (const day of rows.filter((d) => d.is_late)) {
    const e = lateBy.get(day.employee_id) ?? { employee_id: day.employee_id, late_days: 0, total_late_minutes: 0 };
    e.late_days += 1;
    e.total_late_minutes += day.late_minutes;
    lateBy.set(day.employee_id, e);
  }

  const weekdays = WEEKDAYS.map((label, index) => ({ index, label, expected: 0, absent: 0, rate: null as number | null }));
  for (const day of rows) {
    const bucket = bucketOf(day);
    if (!isExpectedBucket(bucket)) continue;
    const w = weekdays[weekdayIndex(day.attendance_date)];
    w.expected += 1;
    if (bucket === "ABSENT") w.absent += 1;
  }
  for (const w of weekdays) w.rate = pct(w.absent, w.expected);

  const peers = days.filter((d) => d.attendance_date === to && inPopulation(d, false));
  const checkedIn = complete.length;
  return {
    date_from: from,
    date_to: to,
    focus_date: to,
    compare_date: compareDate,
    is_today: to === today,
    row_count: rows.length,
    daily,
    focus: kpis(focusRows, noRecord),
    compare: compareRows.length > 0 ? kpis(compareRows, 0) : null,
    distribution: DAY_BUCKETS.filter((b) => counts.get(b)).map((bucket) => ({ bucket, count: counts.get(bucket) ?? 0 })),
    punctuality: {
      checked_in: checkedIn,
      on_time: checkedIn - lateDays.length,
      late: lateDays.length,
      late_rate: pct(lateDays.length, checkedIn),
      on_time_rate: pct(checkedIn - lateDays.length, checkedIn),
      avg_late_minutes: lateDays.length ? lateMinutes / lateDays.length : null,
      bands: BANDS.map((b) => ({
        key: b.key,
        label: b.label,
        count: lateDays.filter((d) => Math.max(1, d.late_minutes) >= b.min && Math.max(1, d.late_minutes) <= b.max).length,
      })),
    },
    frequent_late: Array.from(lateBy.values())
      .filter((e) => e.late_days >= 2)
      .sort((a, b) => b.late_days - a.late_days || b.total_late_minutes - a.total_late_minutes)
      .slice(0, 5),
    weekday_absence: weekdays,
    by_department: breakdown(peers, orgOf, "department"),
    by_branch: breakdown(peers, orgOf, "branch"),
  };
}
