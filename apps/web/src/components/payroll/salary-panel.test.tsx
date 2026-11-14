import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/attendance/format", () => ({ businessToday: () => "2026-09-24" }));
const permissions = vi.hoisted(() => ({ codes: [] as string[] }));
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: (code: string) => permissions.codes.includes(code) }),
}));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

import { SalaryPanel } from "@/components/payroll/salary-panel";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { EmployeeSalaryBreakup } from "@/lib/payroll/types";

const mockedGet = vi.mocked(apiClient.get);

const breakup: EmployeeSalaryBreakup = {
  employee_id: "emp-1",
  as_of: "2026-09-24",
  pay_basis: "MONTHLY",
  salary_structure_id: "st-1",
  salary_structure_version_id: "v-1",
  daily_rate_minor: null,
  pf_applicable: true,
  esi_applicable: false,
  breakup: {
    annual_ctc_minor: 120_000_000,
    monthly_ctc_minor: 10_000_000,
    gross_monthly_minor: 9_820_000,
    employer_contributions_monthly_minor: 180_000,
    lines: [
      { component_code: "BASIC", component_name: "Basic", component_type: "EARNING",
        monthly_minor: 4_910_000, annual_minor: 58_920_000, basis: "50% of gross" },
      { component_code: "EMPLOYER_PF", component_name: "Employer PF contribution",
        component_type: "EMPLOYER_CONTRIBUTION", monthly_minor: 180_000,
        annual_minor: 2_160_000, basis: "12% of BASIC, capped at 1800.00" },
    ],
  },
};

describe("SalaryPanel", () => {
  afterEach(() => {
    mockedGet.mockReset();
    permissions.codes = [];
  });

  it("shows the breakup with gross and CTC totals", async () => {
    mockedGet.mockImplementation((path: string) =>
      Promise.resolve(path.includes("/breakup") ? breakup : []),
    );
    render(<SalaryPanel employeeId="emp-1" />);

    expect(await screen.findByText("Basic")).toBeInTheDocument();
    expect(screen.getByText("₹49,100")).toBeInTheDocument();
    expect(screen.getByText("Gross")).toBeInTheDocument();
    expect(screen.getByText("₹1,00,000")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /assign salary/i })).not.toBeInTheDocument();
  });

  it("explains why there is no breakup yet", async () => {
    mockedGet.mockImplementation((path: string) =>
      path.includes("/breakup")
        ? Promise.reject(
            new ApiError({
              status: 422,
              code: "SALARY_BREAKUP_UNAVAILABLE",
              message: "No salary structure is assigned on 2026-09-24",
            }),
          )
        : Promise.resolve([]),
    );
    permissions.codes = ["PAYROLL.SETUP_MANAGE"];
    render(<SalaryPanel employeeId="emp-1" />);

    expect(await screen.findByText(/no salary structure is assigned/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /assign salary/i })).toBeInTheDocument();
  });

  it("the Assign dialog says what is missing instead of silently refusing", async () => {
    // Assign only, without the compensation permission, so the plain dialog is used.
    permissions.codes = ["PAYROLL.SETUP_MANAGE"];
    mockedGet.mockImplementation((path: string) =>
      Promise.resolve(path.includes("/breakup") ? breakup : []),
    );
    render(<SalaryPanel employeeId="emp-1" />);

    fireEvent.click(await screen.findByRole("button", { name: /assign salary/i }));
    const assign = screen.getByRole("button", { name: "Assign" });
    expect(assign).toBeEnabled();
    fireEvent.click(assign);

    expect(
      screen.getByText("Before assigning, add a structure and a reason."),
    ).toBeInTheDocument();
    expect(screen.getByText(/No active salary structure exists yet/)).toBeInTheDocument();
    expect(vi.mocked(apiClient.post)).not.toHaveBeenCalled();
  });
});
