import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u1", email: "p@x.com", employee_id: "e1", company_timezone: "Asia/Kolkata", permissions: ["ATTENDANCE.PUNCH"] },
  }),
}));
vi.mock("@/components/attendance/punch-entry-dialog", () => ({ PunchEntryDialog: () => null }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

import { EmployeeDashboard } from "@/components/dashboard/employee-dashboard";
import { apiClient } from "@/lib/api/client";

const get = vi.mocked(apiClient.get);

const day = (over: Record<string, unknown>) => ({
  id: "d1",
  attendance_date: "2026-10-31",
  attendance_status: "PRESENT",
  calendar_day_type: "WORKING",
  actual_first_in: "2026-10-31T03:42:00Z", // 09:12 IST
  actual_last_out: null,
  worked_minutes: 400,
  missing_punch: false,
  ...over,
});

function respond() {
  get.mockImplementation(async (path: string) => {
    if (path.endsWith("/assignments")) return [{ effective_to: null, designation_id: "g1", department_id: "p1" }];
    if (path.startsWith("/designations/")) return { id: "g1", title: "UI/UX Designer" };
    if (path.startsWith("/departments/")) return { id: "p1", name: "Engineering" };
    if (path.startsWith("/employees/")) return { id: "e1", first_name: "Priya", display_name: "Priya", employee_code: "EMP-1042" };
    if (path.startsWith("/attendance/days")) return [day({}), day({ id: "d0", attendance_date: "2026-10-30", actual_last_out: "2026-10-30T12:40:00Z" })];
    if (path.startsWith("/leave-balances"))
      return [
        { leave_type_id: "t1", leave_type_name: "Casual", balance: "8", reserved_balance: "0" },
        { leave_type_id: "t2", leave_type_name: "Sick", balance: "6", reserved_balance: "0" },
        { leave_type_id: "t3", leave_type_name: "Earned", balance: "4.5", reserved_balance: "0" },
      ];
    if (path.startsWith("/leave-applications"))
      return [{ id: "l1", leave_type_id: "t1", start_date: "2026-11-12", end_date: "2026-11-13", total_days: "2", status: "SUBMITTED", submitted_at: "2026-10-31T01:00:00Z" }];
    if (path.startsWith("/regularizations")) return [];
    if (path === "/me/payslips") return [{ pay_run_id: "r1", month: "2026-09", pay_date: "2026-10-01", net_minor: 8642000, status: "PAID" }];
    throw new Error(path);
  });
}

describe("EmployeeDashboard", () => {
  afterEach(() => get.mockReset());

  it("shows the employee's own punch, leave, request and payslip facts", async () => {
    respond();
    render(<EmployeeDashboard employeeId="e1" today="2026-10-31" timezone="Asia/Kolkata" />);

    expect(await screen.findByText("Punched in")).toBeInTheDocument();
    expect(screen.getByText("Since 09:12")).toBeInTheDocument();
    expect(screen.getAllByText("6h 40m").length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getAllByText("18.5").length).toBeGreaterThan(0));
    expect(screen.getByText("1 leave · 0 correction")).toBeInTheDocument();
    expect(screen.getByText("₹86,420")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /punch out/i })).toBeInTheDocument();
    expect(await screen.findByText("EMP-1042 · UI/UX Designer · Engineering")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith(expect.stringContaining("employee_id=e1"));
  });

  it("keeps the rest of the page when one section fails", async () => {
    respond();
    const ok = get.getMockImplementation()!;
    get.mockImplementation(async (path: string) => {
      if (path === "/me/payslips") throw new Error("boom");
      return ok(path);
    });
    render(<EmployeeDashboard employeeId="e1" today="2026-10-31" timezone="Asia/Kolkata" />);
    expect(await screen.findByText(/Payslip couldn.t be loaded/)).toBeInTheDocument();
    expect(await screen.findByText("Punched in")).toBeInTheDocument();
  });
});
