import { describe, expect, it } from "vitest";

import { buildCoverage } from "./coverage";
import type { ShiftRoster } from "./types";

const entry = (over: Partial<ShiftRoster>): ShiftRoster => ({
  id: Math.random().toString(),
  company_id: "c",
  employee_id: "e1",
  roster_date: "2026-11-02",
  shift_id: "s1",
  is_week_off_override: false,
  is_holiday_working_override: false,
  status: "PUBLISHED",
  reason: null,
  version: 1,
  created_at: "",
  updated_at: "",
  ...over,
});

describe("buildCoverage", () => {
  const dates = ["2026-11-02", "2026-11-03"];
  const names = (id: string) => ({ s1: "General", s2: "Night" })[id as "s1" | "s2"];

  it("counts staff per shift per day and ignores dates outside the range", () => {
    const c = buildCoverage(
      [
        entry({ employee_id: "a" }),
        entry({ employee_id: "b" }),
        entry({ employee_id: "a", roster_date: "2026-11-03" }),
        entry({ employee_id: "c", shift_id: "s2" }),
        entry({ employee_id: "d", roster_date: "2026-12-01" }),
      ],
      dates,
      names,
    );
    const general = c.rows.find((r) => r.key === "s1");
    expect(general?.byDate.get("2026-11-02")).toBe(2);
    expect(general?.byDate.get("2026-11-03")).toBe(1);
    expect(general?.people).toBe(2);
    expect(c.rosteredEmployees).toBe(3);
    expect(c.totalEntries).toBe(4);
  });

  it("lists week offs last and counts drafts", () => {
    const c = buildCoverage(
      [entry({ employee_id: "a", shift_id: null, is_week_off_override: true }), entry({ status: "DRAFT" })],
      dates,
      names,
    );
    expect(c.rows.map((r) => r.label)).toEqual(["General", "Week off"]);
    expect(c.draftEntries).toBe(1);
  });
});
