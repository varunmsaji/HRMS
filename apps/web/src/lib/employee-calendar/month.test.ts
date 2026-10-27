import { afterEach, describe, expect, it } from "vitest";

import {
  formatLongDate,
  formatMonthLabel,
  gridRangeForMonth,
  monthKeyOf,
  shiftMonth,
  weeksBetween,
} from "./month";

const ORIGINAL_TZ = process.env.TZ;

afterEach(() => {
  if (ORIGINAL_TZ === undefined) delete process.env.TZ;
  else process.env.TZ = ORIGINAL_TZ;
});

describe("month navigation", () => {
  it("shifts across year boundaries", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-03", 0)).toBe("2026-03");
    expect(monthKeyOf("2026-09-30")).toBe("2026-09");
  });

  it("covers a month with Monday-first whole weeks", () => {
    // September 2026: 1 Sep is a Tuesday, 30 Sep a Wednesday.
    expect(gridRangeForMonth("2026-09")).toEqual({ from: "2026-08-31", to: "2026-10-04" });
    // February 2027 starts on a Monday and ends on a Sunday: exactly four weeks.
    expect(gridRangeForMonth("2027-02")).toEqual({ from: "2027-02-01", to: "2027-02-28" });
  });

  it("never needs more than the API's 100-day limit", () => {
    for (let i = 0; i < 48; i++) {
      const { from, to } = gridRangeForMonth(shiftMonth("2026-01", i));
      const days = weeksBetween(from, to).flat();
      expect(days.length).toBeLessThanOrEqual(42);
      expect(days.length % 7).toBe(0);
    }
  });

  it("groups dates into weeks of seven", () => {
    const weeks = weeksBetween("2026-08-31", "2026-10-04");
    expect(weeks).toHaveLength(5);
    expect(weeks[0][0]).toBe("2026-08-31");
    expect(weeks[4][6]).toBe("2026-10-04");
  });
});

describe("date-only values do not shift with the viewer's timezone", () => {
  it.each(["Pacific/Kiritimati", "Pacific/Pago_Pago", "Asia/Kolkata", "America/Los_Angeles", "UTC"])(
    "is stable in %s",
    (tz) => {
      process.env.TZ = tz;
      expect(gridRangeForMonth("2026-09")).toEqual({ from: "2026-08-31", to: "2026-10-04" });
      expect(shiftMonth("2026-10", -1)).toBe("2026-09");
      expect(weeksBetween("2026-10-25", "2026-11-01").flat()).toHaveLength(8);
      expect(weeksBetween("2026-10-25", "2026-11-01")[1]).toEqual(["2026-11-01"]);
      expect(formatMonthLabel("2026-09")).toBe("September 2026");
      expect(formatLongDate("2026-09-09")).toContain("9 September 2026");
      expect(formatLongDate("2026-09-09")).toContain("Wednesday");
    },
  );
});
