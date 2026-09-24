import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "run-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const mockUser: { id: string; employee_id: string | null; permissions: string[] } = {
  id: "hr-user-1",
  employee_id: null,
  permissions: ["PAYROLL.RUN_VIEW", "PAYROLL.RUN_PROCESS"],
};

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    session: { companyId: "company-1", accessToken: "token" },
    user: mockUser,
  }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import PayRunDetailPage from "@/app/app/payroll/pay-runs/[id]/page";
import { apiClient } from "@/lib/api/client";
import type { PayRun, PayRunEmployee } from "@/lib/payroll/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const computedRun: PayRun = {
  id: "run-1",
  company_id: "company-1",
  legal_entity_id: "le-1",
  month: "2026-09",
  period_start: "2026-09-01",
  period_end: "2026-09-30",
  days_in_month: 30,
  status: "COMPUTED",
  pay_date: "2026-10-01",
  attendance_period_id: "period-1",
  variance_threshold_percent: "15",
  previous_pay_run_id: "run-0",
  employee_count: 1,
  gross_minor: 3_000_000,
  deductions_minor: 0,
  employer_contributions_minor: 0,
  net_minor: 3_000_000,
  error_count: 0,
  warning_count: 0,
  variance_flag_count: 1,
  variance_open_count: 1,
  created_by_user_id: "hr-user-1",
  inputs_locked_at: "2026-10-01T00:00:00Z",
  inputs_locked_by_user_id: "hr-user-1",
  computed_at: "2026-10-01T00:00:00Z",
  computed_by_user_id: "hr-user-1",
  approved_at: null,
  approved_by_user_id: null,
  finalised_at: null,
  finalised_by_user_id: null,
  paid_at: null,
  paid_by_user_id: null,
  last_rollback_reason: null,
  version: 3,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const flagged: PayRunEmployee = {
  id: "pre-1",
  employee_id: "emp-1",
  employee_code: "E001",
  employee_name: "Asha Rao",
  pay_basis: "MONTHLY",
  paid_days: "15",
  lop_days: "15",
  payable_days: "30",
  is_computed: true,
  gross_minor: 3_000_000,
  deductions_minor: 0,
  employer_contributions_minor: 0,
  rounding_minor: 0,
  net_minor: 3_000_000,
  issues: [],
  has_error: false,
  previous_net_minor: 6_000_000,
  variance_percent: "-50",
  variance_flagged: true,
  variance_reason: null,
  variance_acknowledged_by_user_id: null,
  variance_acknowledged_at: null,
};

function mockLoad(run: PayRun, employees: PayRunEmployee[]) {
  mockedGet.mockImplementation(async (path: string) => {
    if (path === "/payroll/pay-runs/run-1") return run;
    if (path === "/payroll/pay-runs/run-1/employees") return employees;
    if (path === "/legal-entities/le-1") return { id: "le-1", name: "Acme Pvt Ltd" };
    throw new Error(`unexpected GET ${path}`);
  });
}

describe("PayRunDetailPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
    mockUser.permissions = ["PAYROLL.RUN_VIEW", "PAYROLL.RUN_PROCESS"];
  });

  it("shows totals, the blocking banner and processor actions for a computed run", async () => {
    mockLoad(computedRun, [flagged]);
    render(<PayRunDetailPage />);

    expect(await screen.findByText("Pay run — September 2026")).toBeInTheDocument();
    expect(await screen.findByText(/Acme Pvt Ltd/)).toBeInTheDocument();
    expect(screen.getByText(/1 flagged variance\(s\) to acknowledge/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recompute" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Roll back" })).toBeInTheDocument();
    // A processor without RUN_APPROVE is never offered approval.
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText("-50%")).toBeInTheDocument();
  });

  it("acknowledges a flagged variance with a reason", async () => {
    mockLoad(computedRun, [flagged]);
    mockedPost.mockResolvedValue({ ...flagged, variance_reason: "Half month unpaid leave" });
    const user = userEvent.setup();
    render(<PayRunDetailPage />);

    await user.click(await screen.findByRole("button", { name: "Acknowledge" }));
    await user.type(screen.getByLabelText(/Reason/), "Half month unpaid leave");
    const buttons = screen.getAllByRole("button", { name: "Acknowledge" });
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/payroll/pay-runs/run-1/employees/emp-1/acknowledge-variance",
        { reason: "Half month unpaid leave" },
      ),
    );
  });

  it("finalises an approved run only after confirmation, sending its version", async () => {
    mockUser.permissions = ["PAYROLL.RUN_VIEW", "PAYROLL.RUN_APPROVE"];
    const approved = { ...computedRun, status: "APPROVED" as const, variance_open_count: 0 };
    mockLoad(approved, [{ ...flagged, variance_reason: "ok" }]);
    mockedPost.mockResolvedValue({ ...approved, status: "FINALISED" });
    const user = userEvent.setup();
    render(<PayRunDetailPage />);

    await user.click(await screen.findByRole("button", { name: "Finalise" }));
    expect(screen.getByText(/can never change/)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
    const buttons = screen.getAllByRole("button", { name: "Finalise" });
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/payroll/pay-runs/run-1/finalise", undefined, {
        ifMatch: "3",
      }),
    );
  });

  it("records a day correction on a finalised run", async () => {
    const finalised = { ...computedRun, status: "FINALISED" as const, variance_open_count: 0 };
    mockLoad(finalised, [{ ...flagged, variance_reason: "ok" }]);
    mockedPost.mockResolvedValue({});
    const user = userEvent.setup();
    render(<PayRunDetailPage />);

    await user.click(await screen.findByRole("button", { name: "Correct days" }));
    expect(screen.getByText(/paid for 15 of 30 days in September 2026/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Change in paid days/), "1.5");
    await user.type(screen.getByLabelText(/^Reason/), "Missed punches");
    await user.click(screen.getByRole("button", { name: "Record correction" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/payroll/adjustments", {
        source_pay_run_id: "run-1",
        employee_id: "emp-1",
        paid_days_delta: "1.5",
        reason: "Missed punches",
      }),
    );
  });
});
