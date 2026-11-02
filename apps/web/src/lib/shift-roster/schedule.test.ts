import { describe, expect, it } from "vitest";

import { addDays, formatHours, hhmm, isoWeek, mondayOf, timeRange, weekLabel } from "@/lib/shift-roster/schedule";

describe("schedule helpers", () => {
  it("finds the Monday of any day in the week", () => {
    expect(mondayOf("2026-11-01")).toBe("2026-10-26"); // Sunday
    expect(mondayOf("2026-11-02")).toBe("2026-11-02"); // Monday
    expect(mondayOf("2026-11-04")).toBe("2026-11-02");
  });

  it("adds days across month ends", () => {
    expect(addDays("2026-10-30", 3)).toBe("2026-11-02");
    expect(addDays("2026-11-02", -7)).toBe("2026-10-26");
  });

  it("computes the ISO week number", () => {
    expect(isoWeek("2026-11-02")).toBe(45);
    expect(isoWeek("2026-01-01")).toBe(1);
    expect(isoWeek("2026-12-31")).toBe(53);
  });

  it("formats times and hours", () => {
    expect(hhmm("09:30:00")).toBe("09:30");
    expect(hhmm(null)).toBe("—");
    expect(timeRange("21:00:00", "06:00:00")).toBe("21:00 – 06:00");
    expect(timeRange(null, null)).toBe("—");
    expect(formatHours(45)).toBe("45");
    expect(formatHours(42.5)).toBe("42.5");
  });

  it("labels a week", () => {
    expect(weekLabel("2026-11-02", "2026-11-08")).toBe("Week 45: Mon 02 Nov – Sun 08 Nov 2026");
  });
});
