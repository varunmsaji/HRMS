import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "day-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    session: { companyId: "company-1", accessToken: "token" },
    user: { permissions: ["ATTENDANCE.RECOMPUTE"] },
  }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import AttendanceDayDetailPage from "@/app/app/attendance/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AttendanceDay } from "@/lib/attendance/types";
import type { LeaveDayProjection } from "@/lib/leave-projection/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

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
  work_on_leave_flagged: false,
  work_on_leave_resolution: null,
  work_on_leave_resolution_reason: null,
  work_on_leave_resolved_by: null,
  work_on_leave_resolved_at: null,
  is_core_hours_breach: false,
  on_duty: false,
  on_duty_regularization_id: null,
  paid_day_fraction: "1",
  leave_fraction: "0",
  weekly_off_fraction: "0",
  unpaid_off_fraction: "0",
  lop_fraction: "0",
  ot_minutes_detected: 0,
  ot_minutes_approved: 0,
  ot_pending: false,
  ot_classification: null,
  ot_day_class: null,
  comp_off_minutes_earned: 0,
  calculation_version: 1,
  computation_snapshot: { steps: ["employment_gate"] },
  calculated_at: "2026-08-10T18:05:00Z",
  is_locked: false,
  locked_at: null,
  locked_by: null,
  breaks: [],
  created_at: "2026-08-10T18:05:00Z",
  updated_at: "2026-08-10T18:05:00Z",
};

function mockDayAndProjections(
  day: AttendanceDay,
  projections: LeaveDayProjection[] = [],
): void {
  mockedGet.mockImplementation((url: string) =>
    url.startsWith("/leave-projections")
      ? Promise.resolve(projections)
      : Promise.resolve(day),
  );
}

const sampleProjection: LeaveDayProjection = {
  id: "projection-1",
  company_id: "company-1",
  employee_id: "emp-1",
  attendance_date: "2026-08-10",
  leave_application_id: "leave-app-1",
  leave_type_id: null,
  leave_type_code: "EL",
  fraction: "1.00",
  half: null,
  is_paid: true,
  status: "APPROVED",
  source_version: 1,
  synced_at: "2026-08-10T08:00:00Z",
  cancelled_at: null,
  cancelled_reason: null,
  version: 1,
  created_at: "2026-08-10T08:00:00Z",
  updated_at: "2026-08-10T08:00:00Z",
};

describe("AttendanceDayDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<AttendanceDayDetailPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the day's fields once loaded", async () => {
    mockDayAndProjections(sampleDay);
    render(<AttendanceDayDetailPage />);

    expect(await screen.findByText("WORKING")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /recompute/i })).toBeEnabled();
  });

  it("disables recompute for a locked day", async () => {
    mockDayAndProjections({
      ...sampleDay,
      is_locked: true,
      locked_at: "2026-08-11T00:00:00Z",
    });
    render(<AttendanceDayDetailPage />);

    const recompute = await screen.findByRole("button", { name: /recompute/i });
    expect(recompute).toBeDisabled();
  });

  it("shows a not-found message on 404", async () => {
    mockedGet.mockRejectedValue(new ApiError({ status: 404, code: "NOT_FOUND", message: "nope" }));
    render(<AttendanceDayDetailPage />);

    expect(await screen.findByText(/was not found, or you don't have access/i)).toBeInTheDocument();
  });

  it("recomputes and shows a success toast", async () => {
    mockDayAndProjections(sampleDay);
    mockedPost.mockResolvedValue({ ...sampleDay, calculation_version: 2 });
    const user = userEvent.setup();
    render(<AttendanceDayDetailPage />);

    await user.click(await screen.findByRole("button", { name: /recompute/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^recompute$/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith("/attendance/days/day-1/recompute");
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Attendance day recomputed" }),
    );
  });

  it("shows the leave overlay card when an approved projection covers the day", async () => {
    mockDayAndProjections({ ...sampleDay, attendance_status: "LEAVE" }, [sampleProjection]);
    render(<AttendanceDayDetailPage />);

    expect(await screen.findByText(/leave overlay/i)).toBeInTheDocument();
    expect(screen.getByText("leave-app-1")).toBeInTheDocument();
  });

  it("shows the needs-HR-decision badge when work_on_leave_flagged is unresolved", async () => {
    mockDayAndProjections({ ...sampleDay, work_on_leave_flagged: true }, [sampleProjection]);
    render(<AttendanceDayDetailPage />);

    expect(await screen.findByText(/worked on leave — needs hr decision/i)).toBeInTheDocument();
  });

  it("shows the leave-kept badge once HR resolved the conflict", async () => {
    mockDayAndProjections(
      {
        ...sampleDay,
        work_on_leave_flagged: true,
        work_on_leave_resolution: "KEEP_LEAVE",
        work_on_leave_resolution_reason: "Handover only",
      },
      [sampleProjection],
    );
    render(<AttendanceDayDetailPage />);

    expect(await screen.findByText(/leave kept by hr/i)).toBeInTheDocument();
    expect(screen.queryByText(/needs hr decision/i)).not.toBeInTheDocument();
  });
});
