import { describe, expect, it } from "vitest";

import { formatInr, rupeesToMinor } from "@/lib/payroll/types";

describe("payroll money helpers", () => {
  it("formats paise as rupees with Indian grouping", () => {
    expect(formatInr(120_000_000)).toBe("₹12,00,000");
    expect(formatInr(12_345)).toBe("₹123.45");
  });

  it("parses rupee input into paise", () => {
    expect(rupeesToMinor("12,00,000")).toBe(120_000_000);
    expect(rupeesToMinor("1800.5")).toBe(180_050);
    expect(rupeesToMinor("abc")).toBeNull();
    expect(rupeesToMinor("-5")).toBeNull();
  });
});
