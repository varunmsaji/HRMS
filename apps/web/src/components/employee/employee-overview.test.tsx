import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/employee/employee-side-cards", () => ({ EmployeeSideCards: () => null }));
vi.mock("@/lib/dates/use-company-date", () => ({ useCompanyDatePattern: () => "DD/MM/YYYY" }));

import { EmployeeOverview, type OverviewActions } from "@/components/employee/employee-overview";
import type { Employee } from "@/lib/employee/types";
import type { EmployeeWorkSummary } from "@/lib/employee/use-employee-work-summary";

const employee = {
  id: "e1",
  first_name: "Asha",
  middle_name: null,
  last_name: "Rao",
  display_name: null,
  employee_code: "E-001",
  date_of_birth: "1990-04-02",
  gender: "Female",
  marital_status: null,
  blood_group: null,
  nationality: null,
  personal_email: "asha@example.com",
  personal_mobile: null,
} as unknown as Employee;

const work: EmployeeWorkSummary = {
  employment: {
    id: "m1",
    joining_date: "2024-01-10",
    probation_end_date: "2024-07-10",
    pay_basis: "MONTHLY",
  } as unknown as EmployeeWorkSummary["employment"],
  assignment: { work_location_type: "OFFICE" } as unknown as EmployeeWorkSummary["assignment"],
  company: "Acme",
  department: "Ops",
  designation: "Supervisor",
  branch: "Pune",
  shift: "General",
  manager: { id: "m2", name: "Ravi" },
};

function actions(overrides: Partial<OverviewActions> = {}): OverviewActions {
  return {
    canEditDetails: true,
    canChangeWork: true,
    onEditDetails: vi.fn(),
    onChangeWork: vi.fn(),
    onOpenSection: vi.fn(),
    ...overrides,
  };
}

function renderOverview(a?: OverviewActions) {
  return render(
    <EmployeeOverview employee={employee} work={work} workLoading={false} workError={null} actions={a} />,
  );
}

describe("EmployeeOverview edit actions", () => {
  it("offers no edit controls without actions (the employee's own read-only profile)", () => {
    renderOverview();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("General")).toBeInTheDocument();
  });

  it("opens the details editor from Personal details, and from the prompt to add what is missing", async () => {
    const a = actions();
    renderOverview(a);
    const user = userEvent.setup();
    const card = screen.getByRole("region", { name: "Personal details" });
    await user.click(within(card).getByRole("button", { name: "Edit personal details" }));
    await user.click(within(card).getByRole("button", { name: "Add details" }));
    expect(a.onEditDetails).toHaveBeenCalledTimes(2);
    // Contact is part of the same card now, and what is missing is listed once.
    expect(within(card).getByRole("region", { name: "Contact" })).toBeInTheDocument();
    expect(within(card).getByText(/marital status, blood group, nationality/i)).toBeInTheDocument();
  });

  it("shows only what is filled in, not a column of empty values", () => {
    renderOverview(actions());
    const card = screen.getByRole("region", { name: "Personal details" });
    expect(within(card).getByText("Asha Rao")).toBeInTheDocument();
    expect(within(card).getByText("asha@example.com")).toBeInTheDocument();
    expect(within(card).queryByText("Not provided")).not.toBeInTheDocument();
  });

  it("changes the shift from the Overview, with the shift change type selected", async () => {
    const a = actions();
    renderOverview(a);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Change shift" }));
    await user.click(screen.getByRole("button", { name: "Edit shift" }));
    expect(a.onChangeWork).toHaveBeenNthCalledWith(1, "SHIFT_CHANGE");
    expect(a.onChangeWork).toHaveBeenNthCalledWith(2, "SHIFT_CHANGE");
  });

  it("pre-selects the change type that fits each work field", async () => {
    const a = actions();
    renderOverview(a);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit department" }));
    await user.click(screen.getByRole("button", { name: "Edit branch" }));
    await user.click(screen.getByRole("button", { name: "Edit work location" }));
    await user.click(screen.getByRole("button", { name: "Edit designation" }));
    await user.click(screen.getByRole("button", { name: "Edit reporting manager" }));
    await user.click(screen.getByRole("button", { name: "Change assignment" }));
    expect(vi.mocked(a.onChangeWork).mock.calls.map((c) => c[0])).toEqual([
      "TRANSFER",
      "TRANSFER",
      "TRANSFER",
      "PROMOTION",
      "MANAGER_CHANGE",
      "",
    ]);
  });

  it("sends employment fields to the Employment section", async () => {
    const a = actions();
    renderOverview(a);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit joining date" }));
    await user.click(screen.getByRole("button", { name: "Edit probation ends" }));
    await user.click(screen.getByRole("button", { name: "Edit pay basis" }));
    await user.click(screen.getByRole("button", { name: "Edit employment" }));
    expect(vi.mocked(a.onOpenSection).mock.calls.map((c) => c[0])).toEqual([
      "employment",
      "employment",
      "employment",
      "employment",
    ]);
  });

  it("lists every other editable section and opens it", async () => {
    const a = actions();
    renderOverview(a);
    const user = userEvent.setup();
    const card = screen.getByRole("region", { name: "More to edit" });
    for (const name of ["Compensation", "Salary", "Statutory", "Banking", "Identity", "Experience", "Education", "Dependents", "Documents"]) {
      expect(within(card).getByRole("button", { name: new RegExp(`^${name}$`, "i") })).toBeInTheDocument();
    }
    await user.click(within(card).getByRole("button", { name: /^banking$/i }));
    expect(a.onOpenSection).toHaveBeenCalledWith("banking");
  });

  it("hides what the user may not do", () => {
    renderOverview(actions({ canEditDetails: false, canChangeWork: false }));
    expect(screen.queryByRole("button", { name: "Change shift" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change assignment" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit shift" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit department" })).not.toBeInTheDocument();
    const personal = screen.getByRole("region", { name: "Personal details" });
    expect(within(personal).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add details" })).not.toBeInTheDocument();
    // Employment and the other sections still open, and they decide for themselves.
    expect(screen.getByRole("button", { name: "Edit employment" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "More to edit" })).toBeInTheDocument();
  });
});
