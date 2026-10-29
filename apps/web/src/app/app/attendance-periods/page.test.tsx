import { render, screen } from "@testing-library/react";
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

describe("AttendancePeriodsPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<AttendancePeriodsPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state when there are no periods", async () => {
    mockedGet.mockResolvedValue([]);
    render(<AttendancePeriodsPage />);
    expect(await screen.findByText(/no attendance periods yet/i)).toBeInTheDocument();
  });

  it("renders period rows once loaded", async () => {
    mockedGet.mockResolvedValue([samplePeriod]);
    render(<AttendancePeriodsPage />);

    expect(await screen.findByText("August 2026")).toBeInTheDocument();
    expect(screen.getByText(/01\/08\/2026/)).toBeInTheDocument();
    expect(screen.getByText(/31\/08\/2026/)).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("shows the New period action when the caller holds ATTENDANCE.LOCK", async () => {
    mockedGet.mockResolvedValue([samplePeriod]);
    render(<AttendancePeriodsPage />);
    await screen.findByText("August 2026");
    expect(screen.getByRole("button", { name: /new period/i })).toBeInTheDocument();
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
