import { describe, expect, it } from "vitest";

import { employeeFullName, employeeNameSearchText } from "@/lib/employee/names";

describe("employeeFullName", () => {
  it("includes the middle name", () => {
    expect(employeeFullName({ first_name: "Rahul", middle_name: "Dev", last_name: "Kumar" })).toBe("Rahul Dev Kumar");
  });

  it("skips missing or blank parts", () => {
    expect(employeeFullName({ first_name: "Asha", middle_name: "  ", last_name: null })).toBe("Asha");
    expect(employeeFullName({ first_name: "Asha", last_name: "Rao" })).toBe("Asha Rao");
  });

  it("prefers a display name when one is set", () => {
    expect(employeeFullName({ first_name: "Rahul", middle_name: "Dev", last_name: "Kumar", display_name: " RD " })).toBe("RD");
    expect(employeeFullName({ first_name: "Rahul", last_name: null, display_name: "" })).toBe("Rahul");
  });
});

describe("employeeNameSearchText", () => {
  it("keeps the legal name searchable alongside a display name", () => {
    expect(employeeNameSearchText({ first_name: "Rahul", middle_name: "Dev", last_name: "Kumar", display_name: "RD" })).toBe(
      "RD Rahul Dev Kumar",
    );
    expect(employeeNameSearchText({ first_name: "Asha", last_name: null, display_name: " " })).toBe("Asha");
  });
});
