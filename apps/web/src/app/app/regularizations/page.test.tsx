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
      permissions: ["ATTENDANCE.REGULARIZATION_REQUEST", "ATTENDANCE.REGULARIZATION_APPROVE"],
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

import RegularizationsPage from "@/app/app/regularizations/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { RegularizationRequest } from "@/lib/regularization/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);

const sampleRequest: RegularizationRequest = {
  id: "request-1",
  company_id: "company-1",
  employee_id: "emp-1",
  attendance_day_id: "day-1",
  attendance_date: "2026-08-10",
  request_type: "MISSING_PUNCH",
  reason: "Forgot to punch",
  requested_shift_id: null,
  attachment_reference: null,
  status: "SUBMITTED",
  approval_chain: "MANAGER",
  approval_stage: "MANAGER",
  regularization_policy_version_id: "policy-version-1",
  resolved_approver_manager_id: "manager-1",
  submitted_by_user_id: "user-1",
  submitted_at: "2026-08-10T19:00:00Z",
  reviewed_by_user_id: null,
  reviewed_at: null,
  reviewer_comment: null,
  rejection_reason: null,
  applied_at: null,
  cancelled_at: null,
  cancelled_by_user_id: null,
  version: 1,
  requested_punches: [{ id: "p1", direction: "IN", requested_time: "2026-08-10T09:00:00Z", sort_order: 0 }],
  actions: [{ id: "a1", action: "SUBMITTED", actor_user_id: "user-1", actor_employee_id: "emp-1", stage: null, comment: null, created_at: "2026-08-10T19:00:00Z" }],
  created_at: "2026-08-10T19:00:00Z",
  updated_at: "2026-08-10T19:00:00Z",
};

function mockLoad(requests: RegularizationRequest[]) {
  mockedGet.mockImplementation((path: string) => {
    if (path.startsWith("/regularizations?")) return Promise.resolve(requests);
    if (path === "/shifts") return Promise.resolve([]);
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

describe("RegularizationsPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
    toastMock.mockReset();
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    mockedGetList.mockReturnValue(new Promise(() => {}));
    render(<RegularizationsPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state when there are no requests", async () => {
    mockLoad([]);
    render(<RegularizationsPage />);
    expect(await screen.findByText(/no regularization requests in this range/i)).toBeInTheDocument();
  });

  it("renders request rows once loaded", async () => {
    mockLoad([sampleRequest]);
    render(<RegularizationsPage />);

    expect(await screen.findByText("Missing punch")).toBeInTheDocument();
    expect(screen.getByText("Submitted")).toBeInTheDocument();
    expect(screen.getByText("2026-08-10")).toBeInTheDocument();
  });

  it("shows the permission-denied message on a 403", async () => {
    mockedGet.mockImplementation((path: string) => {
      if (path.startsWith("/regularizations?")) {
        return Promise.reject(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "nope" }));
      }
      return Promise.resolve([]);
    });
    mockedGetList.mockResolvedValue({
      data: [],
      pagination: { page: 1, per_page: 100, total: 0, total_pages: 0 },
      meta: { request_id: "r1" },
    });
    render(<RegularizationsPage />);

    expect(
      await screen.findByText(/you do not have permission to view these requests/i),
    ).toBeInTheDocument();
  });

  it("opens the new-request dialog from the header action", async () => {
    mockLoad([]);
    const user = userEvent.setup();
    render(<RegularizationsPage />);
    await screen.findByText(/no regularization requests in this range/i);

    // Default view is "Team" (the mock user holds REGULARIZATION_APPROVE); "New request" only
    // shows there with an on-behalf grant, which this mock doesn't have — switch to "My
    // requests" first, matching the SELF-submit permission the mock does hold.
    await user.click(screen.getByRole("button", { name: /my requests/i }));
    // Both the header action and the empty-state CTA render "New request" simultaneously when
    // the list is empty — same pattern as `RostersPage`'s header + `EmptyState` CTA duplication.
    const [newRequestButton] = screen.getAllByRole("button", { name: /new request/i });
    await user.click(newRequestButton);
    expect(await screen.findByText(/raise a regularization request/i)).toBeInTheDocument();
  });

  it("switches between My requests and Team requests views", async () => {
    mockLoad([sampleRequest]);
    const user = userEvent.setup();
    render(<RegularizationsPage />);
    await screen.findByText("Missing punch");

    await user.click(screen.getByRole("button", { name: /team requests/i }));
    expect(mockedGetList).toHaveBeenCalledWith("/employees", { per_page: 100 });
  });
});
