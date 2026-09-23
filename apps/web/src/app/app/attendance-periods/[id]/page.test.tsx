import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "period-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const mockUser: { id: string; employee_id: string | null; permissions: string[] } = {
  id: "hr-user-1",
  employee_id: null,
  permissions: ["ATTENDANCE.LOCK", "ATTENDANCE.UNLOCK"],
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
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

import AttendancePeriodDetailPage from "@/app/app/attendance-periods/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type {
  AttendancePeriod,
  AttendancePeriodSummaryRow,
  AttendancePeriodValidation,
} from "@/lib/attendance-period/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const openPeriod: AttendancePeriod = {
  id: "period-1",
  company_id: "company-1",
  legal_entity_id: "le-1",
  period_start: "2026-08-01",
  period_end: "2026-08-31",
  label: "August 2026",
  status: "OPEN",
  opened_by_user_id: "hr-user-1",
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
      actor_user_id: "hr-user-1",
      comment: null,
      created_at: "2026-08-01T00:00:00Z",
    },
  ],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const closedPeriod: AttendancePeriod = {
  ...openPeriod,
  status: "CLOSED",
  closed_by_user_id: "hr-user-1",
  closed_at: "2026-09-01T00:00:00Z",
  version: 2,
  actions: [...openPeriod.actions, {
    id: "a2",
    action: "CLOSED",
    actor_user_id: "hr-user-1",
    comment: null,
    created_at: "2026-09-01T00:00:00Z",
  }],
};

const summaryRow: AttendancePeriodSummaryRow = {
  employee_id: "emp-1",
  present_days: "20.00",
  absent_days: "1.00",
  leave_days: "0.00",
  holiday_days: "2.00",
  weekly_off_days: "8.00",
  half_days: "0.00",
  lop_days: "1.00",
  on_duty_days: "0.00",
  incomplete_days: "0.00",
  not_employed_days: "0.00",
  unpaid_off_days: "0.00",
  paid_days: "30.00",
  payable_days: "31.00",
  ot_minutes_normal: 60,
  ot_minutes_weekly_off: 0,
  ot_minutes_holiday: 0,
  ot_minutes_night: 0,
  comp_off_minutes_earned: 0,
  late_count: 2,
  worked_minutes_total: 9600,
  generated_at: "2026-08-15T00:00:00Z",
  frozen: false,
};

function mockLoad(period: AttendancePeriod, summary: AttendancePeriodSummaryRow[] = [summaryRow]) {
  mockedGet.mockImplementation((path: string) => {
    if (path === `/attendance-periods/${period.id}`) return Promise.resolve(period);
    if (path === `/attendance-periods/${period.id}/summary`) return Promise.resolve(summary);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("AttendancePeriodDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
    mockUser.id = "hr-user-1";
    mockUser.employee_id = null;
    mockUser.permissions = ["ATTENDANCE.LOCK", "ATTENDANCE.UNLOCK"];
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<AttendancePeriodDetailPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows a not-found message on 404", async () => {
    mockedGet.mockRejectedValue(new ApiError({ status: 404, code: "NOT_FOUND", message: "nope" }));
    render(<AttendancePeriodDetailPage />);

    expect(await screen.findByText(/was not found, or you don't have access/i)).toBeInTheDocument();
  });

  it("renders period fields and the live-preview summary for an OPEN period", async () => {
    mockLoad(openPeriod);
    render(<AttendancePeriodDetailPage />);

    expect(await screen.findByText("August 2026")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText(/live preview/i)).toBeInTheDocument();
    expect(screen.getByText("20.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /finalize & lock/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^reopen$/i })).not.toBeInTheDocument();
  });

  it("shows the locked banner and Reopen action, not Finalize, for a CLOSED period", async () => {
    mockLoad(closedPeriod, [{ ...summaryRow, frozen: true }]);
    render(<AttendancePeriodDetailPage />);

    expect(await screen.findByText("Closed & locked")).toBeInTheDocument();
    expect(screen.getByText(/historical attendance in this range is immutable/i)).toBeInTheDocument();
    expect(screen.getByText(/\(frozen\)/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^reopen$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /finalize & lock/i })).not.toBeInTheDocument();
  });

  it("does not show Finalize/Reopen actions without the matching permission", async () => {
    mockUser.permissions = [];
    mockLoad(openPeriod);
    render(<AttendancePeriodDetailPage />);

    await screen.findByText("August 2026");
    expect(screen.queryByRole("button", { name: /finalize & lock/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /validate/i })).not.toBeInTheDocument();
  });

  it("runs validation and shows blocking reasons", async () => {
    mockLoad(openPeriod);
    const validation: AttendancePeriodValidation = {
      status: "BLOCKED",
      reasons: [
        {
          code: "PENDING_REGULARIZATION",
          message: "Some regularization requests in this period are still awaiting a decision",
          count: 1,
          sample: ["emp-1:2026-08-10"],
        },
      ],
      validated_at: "2026-08-15T00:00:00Z",
    };
    mockedPost.mockResolvedValue(validation);
    const user = userEvent.setup();
    render(<AttendancePeriodDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^validate$/i }));

    expect(await screen.findByText("BLOCKED")).toBeInTheDocument();
    expect(screen.getByText(/pending regularization requests/i)).toBeInTheDocument();
  });

  it("finalizes the period through the confirmation dialog", async () => {
    mockLoad(openPeriod);
    mockedPost.mockResolvedValue({ ...closedPeriod });
    const user = userEvent.setup();
    render(<AttendancePeriodDetailPage />);

    await user.click(await screen.findByRole("button", { name: /finalize & lock/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /finalize & lock/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/attendance-periods/period-1/finalize",
        {},
        { ifMatch: "1" },
      );
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Period finalized and locked" }),
    );
  });

  it("shows blocking reasons inline when finalize is refused", async () => {
    mockLoad(openPeriod);
    mockedPost.mockRejectedValue(
      new ApiError({
        status: 409,
        code: "ATTENDANCE_FINALIZATION_BLOCKED",
        message: "blocked",
        details: [
          {
            field: "status",
            code: "ATTENDANCE_FINALIZATION_BLOCKED",
            message: "blocked",
            context: {
              reasons: [
                {
                  code: "PENDING_OVERTIME_APPROVAL",
                  message: "Some detected overtime in this period is still awaiting approval",
                  count: 2,
                  sample: ["emp-1:2026-08-10"],
                },
              ],
            },
          },
        ],
      }),
    );
    const user = userEvent.setup();
    render(<AttendancePeriodDetailPage />);

    await user.click(await screen.findByRole("button", { name: /finalize & lock/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /finalize & lock/i }));

    expect(await screen.findByText(/pending overtime approvals/i)).toBeInTheDocument();
  });

  it("reopens a closed period with a reason", async () => {
    mockLoad(closedPeriod, [{ ...summaryRow, frozen: true }]);
    mockedPost.mockResolvedValue({ ...openPeriod, version: 3 });
    const user = userEvent.setup();
    render(<AttendancePeriodDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^reopen$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/reason/i), "fixing a punch");
    await user.click(within(dialog).getByRole("button", { name: /^reopen period$/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/attendance-periods/period-1/reopen",
        { reason: "fixing a punch" },
        { ifMatch: "2" },
      );
    });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: "Period reopened" }));
  });
});
