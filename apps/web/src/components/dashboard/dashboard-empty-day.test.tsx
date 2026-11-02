import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, canAny: () => true }),
}));
vi.mock("@/lib/employee/use-employee-names", () => ({
  useEmployeeNames: () => () => "Asha Rao (EMP-0001)",
}));
vi.mock("@/components/dashboard/use-workforce-overview", () => ({
  useWorkforceOverview: () => ({
    data: {
      attendance_date: "2026-11-02",
      total: 64,
      present: 0,
      absent: 0,
      on_leave: 0,
      on_duty: 0,
      remote_work: 0,
      expected_employees: 60,
      late: 0,
      half_day_leave: 0,
      departments: [{ department_id: "d1", department_name: "Customer Support", total: 9 }],
    },
  }),
}));
vi.mock("@/components/dashboard/use-pending-approvals", () => ({
  usePendingApprovals: () => ({
    data: {
      leave: { total: 1, error: null, items: [{ id: "l1", employee_id: "e1", submitted_at: "2026-10-30T10:00:00Z" }] },
      regularization: null,
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
      today: "2026-11-02",
      kpi_comparison: { headcount_prev_month_end: 64, yesterday: "2026-11-01", yesterday_present: 0, yesterday_on_leave: 0 },
      headcount_trend: [{ month: "2026-10", headcount: 64 }],
      leave_statistics: { scope: "month", period_start: "2026-11-01", period_end: "2026-11-30", total_days: 0, by_type: [] },
      upcoming_birthdays: [],
      recent_activities: [],
    },
  }),
}));

import { DashboardOverview } from "@/components/dashboard/dashboard-overview";

describe("DashboardOverview before anyone has checked in", () => {
  it("shows a clear no-check-ins message instead of a single grey 'Others 100%' ring", () => {
    render(<DashboardOverview today="2026-11-02" />);
    expect(screen.getByText("No check-ins recorded yet")).toBeInTheDocument();
    expect(screen.getByText(/64 employees · 60 expected to work today/)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Attendance distribution" })).not.toBeInTheDocument();
    expect(screen.queryByText("Others")).not.toBeInTheDocument();
  });

  it("shows an employee's name in the approvals list without their code", () => {
    render(<DashboardOverview today="2026-11-02" />);
    expect(screen.getByText(/^Asha Rao · /)).toBeInTheDocument();
    expect(screen.queryByText(/EMP-0001/)).not.toBeInTheDocument();
  });

  it("gives every shortcut the same treatment", () => {
    render(<DashboardOverview today="2026-11-02" />);
    const links = screen.getAllByRole("link").filter((l) => /Manage Employees|Track Attendance|Process Payroll|View Reports/.test(l.textContent ?? ""));
    expect(links).toHaveLength(4);
    for (const link of links) {
      expect(link).toHaveClass("bg-surface");
      expect(link.className).not.toMatch(/gradient/);
    }
  });

  it("links the pending-approvals figure to the queue", () => {
    render(<DashboardOverview today="2026-11-02" />);
    expect(screen.getByRole("link", { name: /Pending Approvals/ })).toHaveAttribute(
      "href",
      "/app/leave-applications?status=SUBMITTED",
    );
  });
});
