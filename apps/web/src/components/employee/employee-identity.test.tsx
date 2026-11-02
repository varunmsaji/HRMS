import { describe, expect, it } from "vitest";

import { computeInitials } from "@/components/employee/employee-identity";

describe("computeInitials", () => {
  it("uses the first and last name", () => {
    expect(computeInitials("Imran Shetty")).toBe("IS");
    expect(computeInitials("Anil Kumar Pillai")).toBe("AP");
  });

  it("ignores a trailing (employee code) added by pickers and queues", () => {
    expect(computeInitials("Imran Shetty (EMP-0030)")).toBe("IS");
    expect(computeInitials("Meera (EMP-0031)")).toBe("ME");
  });

  it("falls back to the code, then a placeholder, when there is no usable name", () => {
    expect(computeInitials("", "emp-9")).toBe("EM");
    expect(computeInitials("(EMP-1)", "xy-1")).toBe("XY");
    expect(computeInitials(null, null)).toBe("EM");
  });
});
