import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  computeInitials,
  EmployeeIdentityCell,
  splitEmployeeLabel,
} from "@/components/employee/employee-identity";

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

describe("splitEmployeeLabel", () => {
  it("splits a trailing employee code off the name", () => {
    expect(splitEmployeeLabel("Imran Shetty (EMP-0030)")).toEqual({ name: "Imran Shetty", code: "EMP-0030" });
    expect(splitEmployeeLabel("Nisha Agarwal (DEMO-011)")).toEqual({ name: "Nisha Agarwal", code: "DEMO-011" });
    expect(splitEmployeeLabel("Varun M Saji (EMP-VARUN01)")).toEqual({ name: "Varun M Saji", code: "EMP-VARUN01" });
  });

  it("leaves names that merely end in brackets, or have no suffix, alone", () => {
    expect(splitEmployeeLabel("Raj (Jr)")).toEqual({ name: "Raj (Jr)", code: null });
    expect(splitEmployeeLabel("Asha Rao (Finance)")).toEqual({ name: "Asha Rao (Finance)", code: null });
    expect(splitEmployeeLabel("Asha Rao")).toEqual({ name: "Asha Rao", code: null });
  });

  it("does not turn a label that is only a code into an empty name", () => {
    expect(splitEmployeeLabel("(EMP-1)")).toEqual({ name: "(EMP-1)", code: null });
  });
});

describe("EmployeeIdentityCell", () => {
  it("shows the name with the code on its own line when given a combined label", () => {
    render(<EmployeeIdentityCell name="Imran Shetty (EMP-0030)" />);
    expect(screen.getByText("Imran Shetty")).toBeInTheDocument();
    expect(screen.getByText("EMP-0030")).toHaveClass("font-mono");
    expect(screen.queryByText("Imran Shetty (EMP-0030)")).not.toBeInTheDocument();
  });

  it("prefers an explicit code over parsing the name", () => {
    render(<EmployeeIdentityCell name="Asha Rao" code="EMP-9" />);
    expect(screen.getByText("Asha Rao")).toBeInTheDocument();
    expect(screen.getByText("EMP-9")).toBeInTheDocument();
  });
});
