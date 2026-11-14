import { describe, expect, it } from "vitest";

import { makeSummaryDay, makeWeekdays } from "@/lib/attendance/__fixtures__/summary";
import {
  compareRates,
  groupOptions,
  periodProgress,
  sameWeekdayLastWeek,
  weekdayIndex,
  weekdayShort,
  worstWeekday,
} from "@/lib/attendance/insights";
import { toRatePoints } from "@/lib/attendance/summary";

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

describe("compareRates", () => {
  const points = toRatePoints([
    makeSummaryDay("2026-10-05", { expected: 2, present: 1 }),
    makeSummaryDay("2026-10-08"),
    makeSummaryDay("2026-10-12", { expected: 2, present: 2 }),
  ]);

  it("reports the change in percentage points against the baseline day", () => {
    expect(compareRates(points, "2026-10-12", "2026-10-05").delta).toBe(50);
  });

  it("has no delta when either day has no data", () => {
    expect(compareRates(points, "2026-10-12", "2026-10-08").delta).toBeNull();
    expect(compareRates(points, "2026-10-12", "2026-09-01").delta).toBeNull();
  });
});

describe("worstWeekday", () => {
  it("names the weekday with the highest absence rate", () => {
    expect(worstWeekday(makeWeekdays({ 0: [2, 1], 1: [2, 0] }))?.label).toBe("Mon");
  });

  it("names no worst day when there are no absences or nothing to compare", () => {
    expect(worstWeekday(makeWeekdays({ 0: [2, 0], 1: [2, 0] }))).toBeNull();
    expect(worstWeekday(makeWeekdays({ 0: [2, 1] }))).toBeNull();
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

describe("groupOptions", () => {
  const directory = [
    { department: "Sales", branch: "Pune", department_id: "d-sales", branch_id: "b-pune" },
    { department: "Engineering", branch: "Pune", department_id: "d-eng", branch_id: "b-pune" },
    { department: null, branch: null, department_id: null, branch_id: null },
  ];

  it("lists each current department once by id, A–Z, with Unassigned last", () => {
    expect(groupOptions(directory, "department")).toEqual([
      { key: "d-eng", name: "Engineering" },
      { key: "d-sales", name: "Sales" },
      { key: "unassigned", name: "Unassigned" },
    ]);
    expect(groupOptions(directory, "branch").map((o) => o.key)).toEqual(["b-pune", "unassigned"]);
  });

  it("adds the groups the summary's breakdown names, such as someone's department before a transfer", () => {
    const breakdown = [{ key: "d-ops", name: "Operations", headcount: 1, expected: 1, present: 1, absent: 0, leave: 0, late: 0, rate: 100 }];
    expect(groupOptions([], "department", breakdown)).toEqual([{ key: "d-ops", name: "Operations" }]);
  });
});
