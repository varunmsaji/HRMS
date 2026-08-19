import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    session: { companyId: "company-1", accessToken: "token" },
    user: { permissions: ["ATTENDANCE.VIEW_ALL", "ATTENDANCE.PUNCH_ON_BEHALF"] },
  }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import AttendanceDashboardPage from "@/app/app/attendance/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AttendanceDay } from "@/lib/attendance/types";

const mockedGet = vi.mocked(apiClient.get);

const sampleDay: AttendanceDay = {
  id: "day-1",
  company_id: "company-1",
  employee_id: "emp-1",
  attendance_date: "2026-08-10",
  timezone: "UTC",
  shift_id: null,
  shift_version_id: null,
  work_calendar_id: null,
  attendance_policy_version_id: null,
  overtime_policy_version_id: null,
  regularization_policy_version_id: null,
  calendar_day_type: "WORKING",
  holiday_name: null,
  holiday_on_weekly_off: false,
  scheduled_start: "2026-08-10T09:00:00Z",
  scheduled_end: "2026-08-10T18:00:00Z",
  scheduled_minutes: 540,
  actual_first_in: "2026-08-10T09:00:00Z",
  actual_last_out: "2026-08-10T18:00:00Z",
  worked_minutes: 540,
  unpaid_break_minutes: 0,
  paid_break_minutes: 0,
  excess_break_minutes: 0,
  attendance_status: "PRESENT",
  late_minutes: 0,
  early_departure_minutes: 0,
  late_classification: null,
  early_departure_classification: null,
  missing_punch: false,
  auto_closed: false,
  is_late: false,
  is_early_out: false,
  is_overtime: false,
  is_regularized: false,
  is_pending_approval: false,
  worked_on_holiday: false,
  worked_on_weekly_off: false,
  paid_day_fraction: "1",
  lop_fraction: "0",
  ot_minutes_detected: 0,
  ot_minutes_approved: 0,
  ot_pending: false,
  ot_classification: null,
  comp_off_minutes_earned: 0,
  calculation_version: 1,
  computation_snapshot: {},
  calculated_at: "2026-08-10T18:05:00Z",
  is_locked: false,
  locked_at: null,
  locked_by: null,
  breaks: [],
  created_at: "2026-08-10T18:05:00Z",
  updated_at: "2026-08-10T18:05:00Z",
};

function mockLoad(days: AttendanceDay[]) {
  mockedGet.mockImplementation((path: string) => {
    if (path.startsWith("/attendance/days?")) return Promise.resolve(days);
    if (path === "/employees") {
      return Promise.resolve([
        { id: "emp-1", first_name: "Asha", last_name: null, employee_code: "EMP-001" },
      ]);
    }
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("AttendanceDashboardPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<AttendanceDashboardPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state when there are no attendance days for the date", async () => {
    mockLoad([]);
    render(<AttendanceDashboardPage />);

    expect(await screen.findByText(/no attendance days match these filters/i)).toBeInTheDocument();
  });

  it("renders the day's status and summary tiles once loaded", async () => {
    mockLoad([sampleDay]);
    render(<AttendanceDashboardPage />);

    expect((await screen.findAllByText("Asha (EMP-001)")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Present").length).toBeGreaterThan(0);
    // Present tile counts 1.
    await waitFor(() => {
      expect(screen.getByText("1")).toBeInTheDocument();
    });
  });

  it("shows the permission-denied message on a 403", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path.startsWith("/attendance/days?")) {
        return Promise.reject(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "nope" }));
      }
      return Promise.resolve([]);
    });
    render(<AttendanceDashboardPage />);

    expect(
      await screen.findByText(/you do not have permission to view attendance/i),
    ).toBeInTheDocument();
  });

  it("opens the punch entry dialog from the header action", async () => {
    mockLoad([]);
    const user = userEvent.setup();
    render(<AttendanceDashboardPage />);
    await screen.findByText(/no attendance days match these filters/i);

    await user.click(screen.getByRole("button", { name: /record punch/i }));
    expect(await screen.findByLabelText(/punch time/i)).toBeInTheDocument();
  });
});
