import { describe, expect, it } from "vitest";

import { clashSummary, days } from "./decision-center";

describe("days", () => {
  it("drops trailing zeros and dashes a missing value", () => {
    expect(days("6.00")).toBe("6");
    expect(days("2.50")).toBe("2.5");
    expect(days(null)).toBe("—");
  });
});

describe("clashSummary", () => {
  const base = { department: "Design", department_size: 6 };
  it("says nobody is away when there are no overlaps", () => {
    expect(clashSummary({ ...base, colleagues_away: [] })).toEqual({
      clash: false,
      text: "No one else in Design is away during this period.",
    });
  });
  it("names colleagues once each and caps the list", () => {
    const c = (name: string) => ({ name, start_date: "2026-11-12", end_date: "2026-11-13", status: "APPROVED" });
    const r = clashSummary({ ...base, colleagues_away: [c("A"), c("A"), c("B"), c("C"), c("D")] });
    expect(r.clash).toBe(true);
    expect(r.text).toBe("4 of 6 in Design also away: A, B, C and 1 more.");
  });
});
