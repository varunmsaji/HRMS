import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/common/company-date", () => ({ CompanyDate: ({ value }: { value: string }) => <span>{value}</span> }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import { EmployeeProfileHero, tenureLabel } from "@/components/employee/employee-profile-hero";
import type { Employee } from "@/lib/employee/types";
import type { EmployeeWorkSummary } from "@/lib/employee/use-employee-work-summary";

const employee = {
  id: "e1",
  first_name: "Sanjana",
  middle_name: null,
  last_name: "Kapoor",
  employee_code: "DEMO-004",
  status: "ACTIVE",
  is_active: true,
  photo_url: null,
  personal_email: "sanjana@example.com",
  personal_mobile: "+91 98450 00548",
} as unknown as Employee;

const work: EmployeeWorkSummary = {
  employment: { joining_date: "2020-09-07" } as unknown as EmployeeWorkSummary["employment"],
  assignment: { work_location_type: "OFFICE" } as unknown as EmployeeWorkSummary["assignment"],
  company: "Varun Company",
  department: "Sales",
  designation: "Sales Manager",
  branch: "Mumbai Office",
  shift: "General Shift",
  manager: { id: "m1", name: "Ravi Menon" },
};

describe("tenureLabel", () => {
  const today = new Date(2026, 10, 18); // 18 Nov 2026
  it.each([
    ["2020-09-07", "6 yrs 2 mos"],
    ["2020-11-18", "6 yrs"],
    ["2026-04-18", "7 mos"],
    ["2025-11-19", "11 mos"],
    ["2026-10-20", "Less than a month"],
    ["2025-12-01", "11 mos"],
    ["2025-11-18", "1 yr"],
  ])("%s -> %s", (joined, expected) => {
    expect(tenureLabel(joined, today)).toBe(expected);
  });

  it("is empty for a joining date in the future or one that is not a date", () => {
    expect(tenureLabel("2026-12-01", today)).toBeNull();
    expect(tenureLabel("not-a-date", today)).toBeNull();
  });
});

describe("EmployeeProfileHero", () => {
  it("shows the person's role, place and the facts that matter at a glance", () => {
    render(<EmployeeProfileHero employee={employee} work={work} workLoading={false} />);
    expect(screen.getByRole("heading", { name: "Sanjana Kapoor" })).toBeInTheDocument();
    expect(screen.getByText("Sales Manager")).toBeInTheDocument();
    expect(screen.getByText(/Sales$/)).toBeInTheDocument();
    expect(screen.getByText("DEMO-004")).toBeInTheDocument();
    expect(screen.getByText("Mumbai Office")).toBeInTheDocument();
    expect(screen.getByText("Office")).toBeInTheDocument();
    expect(screen.getByText("General Shift")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ravi Menon" })).toHaveAttribute("href", "/app/employees/m1");
    expect(screen.getByRole("link", { name: /sanjana@example.com/ })).toHaveAttribute("href", "mailto:sanjana@example.com");
    expect(screen.getByRole("link", { name: /98450/ })).toHaveAttribute("href", "tel:+91 98450 00548");
  });

  it("says what is missing instead of leaving a blank", () => {
    render(
      <EmployeeProfileHero
        employee={employee}
        work={{ ...work, manager: null, shift: null, designation: null, department: null }}
        workLoading={false}
      />,
    );
    expect(screen.getAllByText("Not set")).toHaveLength(2);
    expect(screen.getByText(/no designation or department yet/i)).toBeInTheDocument();
  });

  it("offers no contact links when there are no contact details", () => {
    render(
      <EmployeeProfileHero
        employee={{ ...employee, personal_email: null, personal_mobile: null } as Employee}
        work={work}
        workLoading={false}
      />,
    );
    expect(screen.queryByRole("link", { name: /@/ })).not.toBeInTheDocument();
  });

  it("renders the actions it is given", () => {
    render(<EmployeeProfileHero employee={employee} work={work} workLoading={false} actions={<button type="button">Edit</button>} />);
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });
});
