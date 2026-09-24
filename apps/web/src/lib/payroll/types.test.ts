import { describe, expect, it } from "vitest";

import { formatInr, formatPayMonth, payRunActions, rupeesToMinor } from "@/lib/payroll/types";

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

describe("pay run helpers", () => {
  it("labels a pay month", () => {
    expect(formatPayMonth("2026-09")).toBe("September 2026");
  });

  it("offers only the actions a status allows", () => {
    expect(payRunActions("DRAFT")).toMatchObject({
      lockInputs: true,
      compute: false,
      rollbackTo: [],
      remove: true,
    });
    expect(payRunActions("COMPUTED")).toMatchObject({
      compute: true,
      approve: true,
      rollbackTo: ["INPUTS_LOCKED", "DRAFT"],
    });
    const finalised = payRunActions("FINALISED");
    expect(finalised.markPaid).toBe(true);
    expect(finalised.rollbackTo).toEqual([]);
    expect(finalised.editPayDate).toBe(false);
    expect(payRunActions("PAID").markPaid).toBe(false);
  });
});
