import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, canAny: () => true }),
}));
vi.mock("@/lib/employee/use-employee-names", () => ({
  useEmployeeNames: () => () => "Asha Rao",
}));
vi.mock("@/components/dashboard/use-workforce-overview", () => ({
  useWorkforceOverview: () => ({
    data: {
      attendance_date: "2026-10-31",
      total: 45,
      present: 30,
      absent: 2,
      on_leave: 4,
      on_duty: 0,
      remote_work: 3,
      expected_employees: 40,
      late: 5,
      half_day_leave: 0,
      departments: [
        { department_id: "d1", department_name: "Engineering", total: 20 },
        { department_id: "d2", department_name: "Sales", total: 10 },
      ],
    },
  }),
}));
vi.mock("@/components/dashboard/use-pending-approvals", () => ({
  usePendingApprovals: () => ({
    data: {
      leave: {
        total: 3,
        error: null,
        items: [{ id: "l1", employee_id: "e1", submitted_at: "2026-10-30T10:00:00Z" }],
      },
      regularization: { total: 2, error: null, items: [] },
      overtime: null,
      onboardingHr: null,
      onboardingCandidate: null,
    },
  }),
}));
vi.mock("@/hooks/use-api-resource", () => ({
  useApiResource: () => ({
    loading: false,
    error: null,
    data: {
      today: "2026-10-31",
      kpi_comparison: {
        headcount_prev_month_end: 40,
        yesterday: "2026-10-30",
        yesterday_present: 0,
        yesterday_on_leave: 0,
      },
      headcount_trend: [
        { month: "2026-09", headcount: 44 },
        { month: "2026-10", headcount: 45 },
      ],
      leave_statistics: {
        scope: "month",
        period_start: "2026-10-01",
        period_end: "2026-10-31",
        total_days: 7.5,
        by_type: [
          { leave_type_id: "t1", name: "Sick Leave", code: "SL", days: 4, applications: 5 },
          { leave_type_id: "t2", name: "Earned Leave", code: "EL", days: 3.5, applications: 1 },
        ],
      },
      upcoming_birthdays: [
        { employee_id: "b1", name: "Ganesh Bose", designation: "Executive", photo_url: null, birthday: "2026-11-01", days_until: 1 },
      ],
      recent_activities: [
        { kind: "EMPLOYEE_CREATED", title: "New employee joined", subject: "Priya Nair", detail: null, occurred_at: "2026-10-30T10:00:00Z" },
      ],
    },
  }),
}));

import { DashboardOverview } from "@/components/dashboard/dashboard-overview";

describe("DashboardOverview", () => {
  it("renders KPIs and cards from the API data", () => {
    render(<DashboardOverview today="2026-10-31" />);

    expect(screen.getByText("Total Employees")).toBeInTheDocument();
    expect(screen.getByText("Present Today")).toBeInTheDocument();
    expect(screen.getByText("01 Oct 2026 – 31 Oct 2026")).toBeInTheDocument();
    // 40 -> overview total is the live figure; the chip compares it with the prior month-end.
    expect(screen.getByText("vs last month")).toBeInTheDocument();
    // yesterday's baseline is 0, so no invented "vs yesterday" chip is shown.
    expect(screen.queryByText("vs yesterday")).not.toBeInTheDocument();
    expect(screen.getByText("3 Leave · 2 Attendance")).toBeInTheDocument();
    expect(screen.getByText("Engineering")).toBeInTheDocument();
    expect(screen.getByText("Sick")).toBeInTheDocument();
    expect(screen.getByText("Ganesh Bose")).toBeInTheDocument();
    expect(screen.getByText("Tomorrow")).toBeInTheDocument();
    expect(screen.getByText("New employee joined")).toBeInTheDocument();
    expect(screen.getByText("Priya Nair")).toBeInTheDocument();
    expect(screen.getByText("Leave Request")).toBeInTheDocument();
  });

  it("links the shortcut tiles to their workspaces", () => {
    render(<DashboardOverview today="2026-10-31" />);
    expect(screen.getByRole("link", { name: /Process Payroll/ })).toHaveAttribute(
      "href",
      "/app/payroll/pay-runs",
    );
    expect(screen.getByRole("link", { name: /Manage Employees/ })).toHaveAttribute("href", "/app/employees");
  });
});
