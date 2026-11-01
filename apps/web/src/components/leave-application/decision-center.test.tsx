import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: { employee_id: "me" } }) }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/components/common/company-date", () => ({ CompanyDate: ({ value }: { value: string }) => <span>{value}</span> }));
vi.mock("@/components/leave-application/leave-application-review-dialog", () => ({
  LeaveApplicationReviewDialog: () => null,
}));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("@/hooks/use-api-resource", () => ({
  useApiResource: () => ({
    loading: false,
    error: null,
    retry: vi.fn(),
    data: {
      today: "2026-11-01",
      summary: {
        pending_count: 2,
        oldest_pending_at: "2026-10-30T10:00:00Z",
        on_leave_today: 1,
        on_leave_today_by_type: [["Casual Leave", 1]],
        active_staff: 40,
        available_pct: 97.5,
        upcoming_starts_7d: 0,
        peak_day: null,
        peak_day_away: 0,
      },
      counts: { pending: 2, approved: 5, declined: 1 },
      tab: "pending",
      items: [
        {
          id: "a1", version: 1, employee_id: "e1", employee_name: "Anjali Menon", employee_code: "EMP-0104",
          designation: "Designer", department: "Design", leave_type_id: "t", leave_type: "Casual Leave",
          start_date: "2026-11-12", end_date: "2026-11-14", total_days: "3.00", lop_days: "1.00",
          reason: "Conference", status: "SUBMITTED", approval_stage: "HR", submitted_at: "2026-10-31T10:00:00Z",
          current_balance: "6.00", post_approval_balance: "4.00", department_size: 6,
          colleagues_away: [{ name: "Rahul", start_date: "2026-11-12", end_date: "2026-11-12", status: "APPROVED" }],
        },
        {
          id: "a2", version: 1, employee_id: "me", employee_name: "Own Request", employee_code: "EMP-1",
          designation: null, department: null, leave_type_id: "t", leave_type: "Sick Leave",
          start_date: "2026-11-02", end_date: "2026-11-02", total_days: "1.00", lop_days: "0.00",
          reason: null, status: "SUBMITTED", approval_stage: "HR", submitted_at: "2026-10-31T10:00:00Z",
          current_balance: "5.00", post_approval_balance: "4.00", department_size: null, colleagues_away: [],
        },
      ],
    },
  }),
}));

import { LeaveDecisionCenter } from "@/components/leave-application/decision-center";

describe("LeaveDecisionCenter", () => {
  it("renders the backend's figures, balance ledger and clash warning", () => {
    render(<LeaveDecisionCenter />);
    expect(screen.getByText("Anjali Menon")).toBeInTheDocument();
    expect(screen.getByText("−2 days")).toBeInTheDocument(); // 3 total - 1 LOP = 2 paid
    expect(screen.getAllByText("4 days").length).toBeGreaterThan(0);
    expect(screen.getByText(/1 of 6 in Design also away: Rahul/)).toBeInTheDocument();
    expect(screen.getByText(/1 day will be treated as loss of pay/)).toBeInTheDocument();
    expect(screen.getByText("98%")).toBeInTheDocument();
  });

  it("does not offer approve/decline on the viewer's own request", () => {
    render(<LeaveDecisionCenter />);
    expect(screen.getAllByRole("button", { name: /Approve leave/ })).toHaveLength(1);
  });
});
