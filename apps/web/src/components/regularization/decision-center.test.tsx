import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("@/lib/auth/auth-context", () => ({ useAuth: () => ({ user: { employee_id: "me" } }) }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/components/common/company-date", () => ({ CompanyDate: ({ value }: { value: string }) => <span>{value}</span> }));
vi.mock("@/components/regularization/regularization-review-dialog", () => ({
  RegularizationReviewDialog: () => null,
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
        window_regularized_days: 26,
        window_expected_days: 753,
        window_rate_pct: 3.5,
      },
      counts: { pending: 2, approved: 49, declined: 1 },
      tab: "pending",
      items: [
        {
          id: "r1", version: 1, employee_id: "e1", employee_name: "Fathima Rasheed", employee_code: "EMP-0112",
          designation: "HR Executive", department: "People", attendance_date: "2026-10-29",
          timezone: "Asia/Kolkata", shift_name: "General Shift", request_type: "MISSING_PUNCH", status: "SUBMITTED",
          approval_stage: "HR", submitted_at: "2026-10-30T10:15:00Z", reason: "Kiosk was offline",
          recorded_first_in: "2026-10-29T04:12:00Z", recorded_last_out: null, recorded_worked_minutes: 0,
          recorded_late_minutes: 0, recorded_status: "INCOMPLETE", recorded_missing_punch: true,
          requested_punches: [{ direction: "OUT", time: "2026-10-29T12:35:00Z" }], requested_span_minutes: 503,
        },
        {
          id: "r2", version: 1, employee_id: "me", employee_name: "Own Request", employee_code: "EMP-1",
          designation: null, department: null, attendance_date: "2026-10-28", timezone: null, shift_name: null,
          request_type: "WRONG_PUNCH", status: "SUBMITTED", approval_stage: "MANAGER",
          submitted_at: "2026-10-30T10:15:00Z", reason: null, recorded_first_in: null, recorded_last_out: null,
          recorded_worked_minutes: null, recorded_late_minutes: null, recorded_status: null,
          recorded_missing_punch: null, requested_punches: [], requested_span_minutes: null,
        },
      ],
    },
  }),
}));

import { RegularizationDecisionCenter } from "@/components/regularization/decision-center";

describe("RegularizationDecisionCenter", () => {
  it("shows the recorded day beside the requested correction", () => {
    render(<RegularizationDecisionCenter />);
    expect(screen.getByText("Fathima Rasheed")).toBeInTheDocument();
    expect(screen.getAllByText("Missing").length).toBeGreaterThan(0); // no recorded punch out
    expect(screen.getByText("8h 23m")).toBeInTheDocument(); // 503-minute projected span
    expect(screen.getByText("3.5%")).toBeInTheDocument();
    expect(screen.getByText("Pending HR review")).toBeInTheDocument();
    expect(screen.getByText(/Kiosk was offline/)).toBeInTheDocument();
  });

  it("does not offer approve/decline on the viewer's own request", () => {
    render(<RegularizationDecisionCenter />);
    expect(screen.getAllByRole("button", { name: /Approve regularization/ })).toHaveLength(1);
  });
});
