import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    session: { companyId: "company-1", accessToken: "token" },
    user: {
      id: "user-1",
      employee_id: "emp-1",
      permissions: ["ATTENDANCE.OVERTIME_APPROVE"],
    },
  }),
}));

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({
  useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() },
}));

import OvertimePage from "@/app/app/overtime/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { OvertimeRecord } from "@/lib/overtime/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);

const sampleRecord: OvertimeRecord = {
  id: "ot-1",
  company_id: "company-1",
  employee_id: "emp-1",
  attendance_day_id: "day-1",
  attendance_date: "2026-08-10",
  overtime_policy_version_id: "policy-version-1",
  day_class: "HOLIDAY",
  classification_code: "OT_HOLIDAY",
  configured_multiplier: "1.5000",
  minutes_detected: 120,
  minutes_approved: 0,
  status: "PENDING",
  approval_chain: "MANAGER",
  approval_stage: "MANAGER",
  resolved_approver_manager_id: "manager-1",
  reviewed_by_user_id: null,
  reviewed_at: null,
  reviewer_comment: null,
  rejection_reason: null,
  comp_off_minutes: 0,
  comp_off_expiry_date: null,
  version: 1,
  actions: [
    {
      id: "a1",
      action: "DETECTED",
      actor_user_id: null,
      actor_employee_id: null,
      stage: null,
      comment: null,
      created_at: "2026-08-10T19:00:00Z",
    },
  ],
  created_at: "2026-08-10T19:00:00Z",
  updated_at: "2026-08-10T19:00:00Z",
};

function mockLoad(records: OvertimeRecord[]) {
  mockedGet.mockImplementation((path: string) => {
    if (path.startsWith("/overtime?")) return Promise.resolve(records);
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
  mockedGetList.mockImplementation((path: string) => {
    if (path === "/employees") {
      return Promise.resolve({
        data: [{ id: "emp-1", first_name: "Asha", last_name: null, employee_code: "EMP-001" }],
        pagination: { page: 1, per_page: 100, total: 1, total_pages: 1 },
        meta: { request_id: "r1" },
      });
    }
    return Promise.reject(new Error(`Unexpected path ${path}`));
  });
}

describe("OvertimePage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    mockedGetList.mockReturnValue(new Promise(() => {}));
    render(<OvertimePage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state when there are no records", async () => {
    mockLoad([]);
    render(<OvertimePage />);
    expect(await screen.findByText(/no overtime records in this range/i)).toBeInTheDocument();
  });

  it("does not render a create/submit action anywhere on the page", async () => {
    mockLoad([sampleRecord]);
    render(<OvertimePage />);
    await screen.findByText("10/08/2026");
    expect(screen.queryByRole("button", { name: /new/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create/i })).not.toBeInTheDocument();
  });

  it("renders record rows once loaded", async () => {
    mockLoad([sampleRecord]);
    render(<OvertimePage />);

    expect(await screen.findByText("10/08/2026")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Holiday")).toBeInTheDocument();
  });

  it("shows the permission-denied message on a 403", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path.startsWith("/overtime?")) {
        return Promise.reject(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "nope" }));
      }
      return Promise.resolve([]);
    });
    mockedGetList.mockResolvedValue({
      data: [],
      pagination: { page: 1, per_page: 100, total: 0, total_pages: 0 },
      meta: { request_id: "r1" },
    });
    render(<OvertimePage />);

    expect(
      await screen.findByText(/you do not have permission to view these overtime records/i),
    ).toBeInTheDocument();
  });

  it("switches between My overtime and Team overtime views", async () => {
    mockLoad([sampleRecord]);
    const user = userEvent.setup();
    render(<OvertimePage />);
    await screen.findByText("10/08/2026");

    await user.click(screen.getByRole("button", { name: /my overtime/i }));
    expect(mockedGet).toHaveBeenCalledWith(expect.stringContaining("employee_id=emp-1"));
  });
});
