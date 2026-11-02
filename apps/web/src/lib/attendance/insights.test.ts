import { describe, expect, it } from "vitest";

import { makeAbsentDay, makeDay } from "@/lib/attendance/__fixtures__/day";
import {
  breakdownBy,
  compareRates,
  dailyAttendanceRate,
  frequentLateArrivals,
  groupNames,
  periodProgress,
  punctualitySummary,
  sameWeekdayLastWeek,
  weekdayAbsence,
  weekdayIndex,
  weekdayShort,
  worstWeekday,
} from "@/lib/attendance/insights";

// 2026-10-05 is a Monday.
describe("weekday helpers", () => {
  it("maps ISO dates to Monday-first indexes", () => {
    expect(weekdayIndex("2026-10-05")).toBe(0);
    expect(weekdayIndex("2026-10-11")).toBe(6);
    expect(weekdayShort("2026-10-07")).toBe("Wed");
  });

  it("compares a day with the same weekday a week earlier", () => {
    expect(sameWeekdayLastWeek("2026-10-12")).toBe("2026-10-05");
  });
});

describe("dailyAttendanceRate / compareRates", () => {
  const rows = [
    makeDay({ employee_id: "a", attendance_date: "2026-10-05" }),
    makeAbsentDay({ employee_id: "b", attendance_date: "2026-10-05" }),
    makeDay({ employee_id: "a", attendance_date: "2026-10-12" }),
    makeDay({ employee_id: "b", attendance_date: "2026-10-12" }),
  ];
  const points = dailyAttendanceRate(rows, { from: "2026-10-05", to: "2026-10-12" });

  it("returns one point per calendar day, with a null rate where nobody was expected", () => {
    expect(points).toHaveLength(8);
    expect(points[0]).toMatchObject({ date: "2026-10-05", present: 1, expected: 2, rate: 50 });
    expect(points[3]).toMatchObject({ date: "2026-10-08", expected: 0, rate: null });
    expect(points[7].rate).toBe(100);
  });

  it("reports the change in percentage points against the baseline day", () => {
    expect(compareRates(points, "2026-10-12", "2026-10-05").delta).toBe(50);
  });

  it("has no delta when either day has no data", () => {
    expect(compareRates(points, "2026-10-12", "2026-10-08").delta).toBeNull();
    expect(compareRates(points, "2026-10-12", "2026-09-01").delta).toBeNull();
  });
});

describe("punctualitySummary", () => {
  it("counts only checked-in days, bands lateness and averages late minutes over late days", () => {
    const rows = [
      makeDay({ employee_id: "a" }),
      makeDay({ employee_id: "b", is_late: true, late_minutes: 10 }),
      makeDay({ employee_id: "c", is_late: true, late_minutes: 45 }),
      makeDay({ employee_id: "d", is_late: true, late_minutes: 90 }),
      makeAbsentDay({ employee_id: "e" }),
    ];
    const s = punctualitySummary(rows);
    expect(s.checkedIn).toBe(4);
    expect(s.late).toBe(3);
    expect(s.onTime).toBe(1);
    expect(s.lateRate).toBe(75);
    expect(s.avgLateMinutes).toBeCloseTo(48.33, 1);
    expect(Object.fromEntries(s.bands.map((b) => [b.key, b.count]))).toEqual({
      "1_15": 1,
      "16_30": 0,
      "31_60": 1,
      "60_plus": 1,
    });
  });

  it("has no rates and no average when nobody checked in or was late", () => {
    const empty = punctualitySummary([makeAbsentDay()]);
    expect(empty.lateRate).toBeNull();
    expect(empty.avgLateMinutes).toBeNull();
    const punctual = punctualitySummary([makeDay()]);
    expect(punctual.lateRate).toBe(0);
    expect(punctual.avgLateMinutes).toBeNull();
  });

  it("puts a late day with no recorded minutes in the smallest band", () => {
    const s = punctualitySummary([makeDay({ is_late: true, late_minutes: 0 })]);
    expect(s.bands[0].count).toBe(1);
  });
});

describe("frequentLateArrivals", () => {
  const late = (employee_id: string, date: string, minutes: number) =>
    makeDay({ employee_id, attendance_date: date, is_late: true, late_minutes: minutes });

  it("ranks by late days then minutes and ignores one-offs", () => {
    const rows = [
      late("a", "2026-10-05", 5),
      late("a", "2026-10-06", 5),
      late("b", "2026-10-05", 20),
      late("b", "2026-10-06", 20),
      late("b", "2026-10-07", 20),
      late("c", "2026-10-05", 60),
    ];
    const result = frequentLateArrivals(rows);
    expect(result.map((r) => r.employeeId)).toEqual(["b", "a"]);
    expect(result[0]).toEqual({ employeeId: "b", lateDays: 3, totalLateMinutes: 60 });
  });

  it("respects the limit", () => {
    const rows = ["a", "b", "c"].flatMap((id) => [late(id, "2026-10-05", 1), late(id, "2026-10-06", 1)]);
    expect(frequentLateArrivals(rows, 2)).toHaveLength(2);
  });
});

describe("weekdayAbsence / worstWeekday", () => {
  it("computes the absence rate per weekday over expected days only", () => {
    const rows = [
      makeAbsentDay({ employee_id: "a", attendance_date: "2026-10-05" }), // Mon
      makeDay({ employee_id: "b", attendance_date: "2026-10-05" }),
      makeDay({ employee_id: "a", attendance_date: "2026-10-06" }), // Tue
    ];
    const stats = weekdayAbsence(rows);
    expect(stats.map((s) => s.label)).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
    expect(stats[0]).toMatchObject({ expected: 2, absent: 1, rate: 50 });
    expect(stats[1]).toMatchObject({ expected: 1, absent: 0, rate: 0 });
    expect(stats[2].rate).toBeNull();
    expect(worstWeekday(stats)?.label).toBe("Mon");
  });

  it("names no worst day when there are no absences or nothing to compare", () => {
    const allPresent = weekdayAbsence([
      makeDay({ attendance_date: "2026-10-05" }),
      makeDay({ attendance_date: "2026-10-06" }),
    ]);
    expect(worstWeekday(allPresent)).toBeNull();
    expect(worstWeekday(weekdayAbsence([makeAbsentDay({ attendance_date: "2026-10-05" })]))).toBeNull();
  });
});

describe("periodProgress", () => {
  const period = { period_start: "2026-10-01", period_end: "2026-10-31" };

  it("reports elapsed and remaining days inside the period", () => {
    const p = periodProgress(period, "2026-10-10");
    expect(p).toMatchObject({ totalDays: 31, elapsedDays: 10, daysLeft: 21 });
    expect(p.percent).toBeCloseTo(32.26, 1);
  });

  it("clamps before the start and goes negative after the end", () => {
    expect(periodProgress(period, "2026-09-20")).toMatchObject({ elapsedDays: 0, percent: 0 });
    const after = periodProgress(period, "2026-11-03");
    expect(after).toMatchObject({ elapsedDays: 31, daysLeft: -3, percent: 100 });
  });

  it("shows 0 days left on the last day", () => {
    expect(periodProgress(period, "2026-10-31").daysLeft).toBe(0);
  });
});

describe("breakdownBy / groupNames", () => {
  const directory = new Map([
    ["a", { department: "Engineering", branch: "Pune" }],
    ["b", { department: "Engineering", branch: "Pune" }],
    ["c", { department: "Sales", branch: "Mumbai" }],
    ["d", { department: null, branch: null }],
  ]);
  const rows = [
    makeDay({ employee_id: "a" }),
    makeDay({ employee_id: "b", is_late: true, late_minutes: 5 }),
    makeAbsentDay({ employee_id: "c" }),
    makeDay({ employee_id: "d" }),
  ];

  it("counts people per department and ranks the lowest attendance first", () => {
    const stats = breakdownBy(rows, directory, "department");
    expect(stats.map((s) => s.name)).toEqual(["Sales", "Engineering", "Unassigned"]);
    expect(stats[0]).toMatchObject({ headcount: 1, expected: 1, present: 0, absent: 1, rate: 0 });
    expect(stats[1]).toMatchObject({ headcount: 2, present: 2, late: 1, rate: 100 });
  });

  it("groups employees with no department, or missing from the directory, as Unassigned", () => {
    const stats = breakdownBy([...rows, makeDay({ employee_id: "ghost" })], directory, "department");
    expect(stats.find((s) => s.name === "Unassigned")).toMatchObject({ headcount: 2 });
  });

  it("works for branches too, and does not rate a group nobody was expected in", () => {
    expect(breakdownBy(rows, directory, "branch").map((s) => s.name)).toEqual(["Mumbai", "Pune", "Unassigned"]);
    const off = makeDay({ employee_id: "c", attendance_status: "NOT_EXPECTED", calendar_day_type: "WEEKLY_OFF", actual_first_in: null, actual_last_out: null });
    const stats = breakdownBy([off, makeDay({ employee_id: "a" })], directory, "department");
    expect(stats.at(-1)).toMatchObject({ name: "Sales", expected: 0, rate: null });
  });

  it("lists distinct names A–Z with Unassigned last", () => {
    expect(groupNames(directory, "department")).toEqual(["Engineering", "Sales", "Unassigned"]);
    expect(groupNames(directory, "branch")).toEqual(["Mumbai", "Pune", "Unassigned"]);
  });
});
