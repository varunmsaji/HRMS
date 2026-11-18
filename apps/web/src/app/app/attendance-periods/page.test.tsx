import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    session: { companyId: "company-1", accessToken: "token" },
    user: { id: "user-1", employee_id: null, permissions: ["ATTENDANCE.LOCK"] },
  }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import AttendancePeriodsPage from "@/app/app/attendance-periods/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AttendancePeriod } from "@/lib/attendance-period/types";

const mockedGet = vi.mocked(apiClient.get);

const samplePeriod: AttendancePeriod = {
  id: "period-1",
  company_id: "company-1",
  legal_entity_id: "le-1",
  period_start: "2026-08-01",
  period_end: "2026-08-31",
  label: "August 2026",
  status: "OPEN",
  opened_by_user_id: "user-1",
  opened_at: "2026-08-01T00:00:00Z",
  last_validated_at: null,
  last_validation_status: null,
  closed_by_user_id: null,
  closed_at: null,
  reopened_by_user_id: null,
  reopened_at: null,
  reopen_reason: null,
  version: 1,
  actions: [
    {
      id: "a1",
      action: "OPENED",
      actor_user_id: "user-1",
      comment: null,
      created_at: "2026-08-01T00:00:00Z",
    },
  ],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

/** The periods list, the legal entities, and a period's own summary come from different paths. */
function mockApi(periods: AttendancePeriod[], summary: unknown[] = []) {
  mockedGet.mockImplementation((path: string) => {
    if (/^\/attendance-periods\/[^/]+\/summary/.test(path)) return Promise.resolve(summary);
    if (path === "/legal-entities") return Promise.resolve([]);
    return Promise.resolve(periods);
  });
}

describe("AttendancePeriodsPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<AttendancePeriodsPage />);
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });

  it("shows the empty state when there are no periods", async () => {
    mockApi([]);
    render(<AttendancePeriodsPage />);
    expect(await screen.findByText(/no attendance periods yet/i)).toBeInTheDocument();
  });

  it("renders period rows once loaded", async () => {
    mockApi([samplePeriod]);
    render(<AttendancePeriodsPage />);

    expect(await screen.findByText("August 2026")).toBeInTheDocument();
    expect(screen.getByText(/01\/08\/2026/)).toBeInTheDocument();
    expect(screen.getByText(/31\/08\/2026/)).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("shows the New period action when the caller holds ATTENDANCE.LOCK", async () => {
    mockApi([samplePeriod]);
    render(<AttendancePeriodsPage />);
    await screen.findByText("August 2026");
    expect(screen.getByRole("button", { name: /new period/i })).toBeInTheDocument();
  });

  it("sends people back to Payroll, where closing the month leads to a pay run", async () => {
    mockApi([samplePeriod]);
    render(<AttendancePeriodsPage />);
    await screen.findByText("August 2026");
    expect(screen.getByRole("link", { name: /payroll/i })).toHaveAttribute("href", "/app/payroll/pay-runs");
  });

  it("totals the period summary under the list, as Payroll will read it", async () => {
    mockApi(
      [samplePeriod],
      [
        { employee_id: "emp-1", present_days: "20", absent_days: "1", leave_days: "2", holiday_days: "1", weekly_off_days: "4", half_days: "0", lop_days: "1", on_duty_days: "0", incomplete_days: "0", not_employed_days: "0", unpaid_off_days: "0", paid_days: "29", payable_days: "29", ot_minutes_normal: 60, ot_minutes_weekly_off: 0, ot_minutes_holiday: 0, ot_minutes_night: 0, comp_off_minutes_earned: 0, late_count: 2, worked_minutes_total: 9000, generated_at: "x", frozen: false },
      ],
    );
    render(<AttendancePeriodsPage />);
    const section = (await screen.findByRole("heading", { name: /monthly attendance summary/i })).closest("[id='att-monthly']") as HTMLElement;
    expect(await within(section).findByText("Live preview")).toBeInTheDocument();
    expect(within(section).getByText("Payable days").nextSibling).toHaveTextContent("29");
    expect(within(section).getByText("LOP").nextSibling).toHaveTextContent("1");
  });

  it("does not show the summary when the periods could not be loaded", async () => {
    mockedGet.mockRejectedValue(new ApiError({ status: 500, code: "BOOM", message: "x" }));
    render(<AttendancePeriodsPage />);
    await screen.findByRole("button", { name: /try again/i });
    expect(screen.queryByRole("heading", { name: /monthly attendance summary/i })).not.toBeInTheDocument();
  });

  it("shows the permission-denied message on a 403", async () => {
    mockedGet.mockRejectedValue(
      new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "nope" }),
    );
    render(<AttendancePeriodsPage />);

    expect(
      await screen.findByText(/you do not have permission to view attendance periods/i),
    ).toBeInTheDocument();
  });
});
