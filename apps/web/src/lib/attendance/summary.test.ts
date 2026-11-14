import { describe, expect, it } from "vitest";

import { DEFAULT_FILTERS } from "@/lib/attendance/dashboard";
import { makeKpis } from "@/lib/attendance/__fixtures__/summary";
import { summaryQuery, toDistribution, toFrequentLate, toGroupStats, toKpiSet } from "@/lib/attendance/summary";

describe("summaryQuery", () => {
  const window = { from: "2026-10-01", to: "2026-10-14" };

  it("asks for the window, whose last day is the focus date", () => {
    expect(summaryQuery(window, DEFAULT_FILTERS)).toEqual({ date_from: "2026-10-01", date_to: "2026-10-14" });
  });

  it("sends the population filters but not the drill-down, which narrows lists only", () => {
    const filters = {
      ...DEFAULT_FILTERS,
      employeeId: "e1",
      shiftId: "s1",
      employeeStatus: "ACTIVE",
      department: "unassigned",
      branch: "b1",
      bucket: "ABSENT" as const,
      flag: "late" as const,
    };
    expect(summaryQuery(window, filters)).toEqual({
      date_from: "2026-10-01",
      date_to: "2026-10-14",
      employee_id: "e1",
      shift_id: "s1",
      employee_status: "ACTIVE",
      department_id: "unassigned",
      branch_id: "b1",
    });
  });
});

describe("adapters", () => {
  it("maps the KPIs one to one", () => {
    const kpi = toKpiSet(makeKpis({ total_employees: 4, no_record: 1, not_checked_in: 2, overtime_minutes_detected: 30 }));
    expect(kpi).toMatchObject({ totalEmployees: 4, noRecord: 1, notCheckedIn: 2, overtimeMinutesDetected: 30, present: 0 });
  });

  it("lists every status in display order, with zeros the backend leaves out", () => {
    const distribution = toDistribution([
      { bucket: "ABSENT", count: 2 },
      { bucket: "PRESENT", count: 5 },
    ]);
    expect(distribution[0]).toEqual({ bucket: "PRESENT", label: "Present", count: 5 });
    expect(distribution.find((d) => d.bucket === "ABSENT")?.count).toBe(2);
    expect(distribution.find((d) => d.bucket === "LEAVE")?.count).toBe(0);
    expect(distribution).toHaveLength(12);
  });

  it("gives each breakdown group the filter value that selects it", () => {
    const group = { name: "", headcount: 1, expected: 1, present: 1, absent: 0, leave: 0, late: 0, rate: 100 };
    const stats = toGroupStats([
      { ...group, id: "d1", name: "Sales" },
      { ...group, id: null, name: "Unassigned" },
    ]);
    expect(stats.map((s) => [s.key, s.name])).toEqual([
      ["d1", "Sales"],
      ["unassigned", "Unassigned"],
    ]);
  });

  it("renames the frequent late-comers' fields", () => {
    expect(toFrequentLate([{ employee_id: "e1", late_days: 3, total_late_minutes: 45 }])).toEqual([
      { employeeId: "e1", lateDays: 3, totalLateMinutes: 45 },
    ]);
  });
});
