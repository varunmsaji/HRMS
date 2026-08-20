import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "request-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const mockUser: {
  id: string;
  employee_id: string | null;
  permissions: string[];
} = {
  id: "manager-user-1",
  employee_id: "manager-1",
  permissions: ["ATTENDANCE.REGULARIZATION_APPROVE"],
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

import RegularizationDetailPage from "@/app/app/regularizations/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { RegularizationRequest } from "@/lib/regularization/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const pendingRequest: RegularizationRequest = {
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
  submitted_by_user_id: "employee-user-1",
  submitted_at: "2026-08-10T19:00:00Z",
  reviewed_by_user_id: null,
  reviewed_at: null,
  reviewer_comment: null,
  rejection_reason: null,
  applied_at: null,
  cancelled_at: null,
  cancelled_by_user_id: null,
  version: 1,
  requested_punches: [
    { id: "p1", direction: "IN", requested_time: "2026-08-10T09:00:00Z", sort_order: 0 },
    { id: "p2", direction: "OUT", requested_time: "2026-08-10T18:00:00Z", sort_order: 1 },
  ],
  actions: [
    {
      id: "a1",
      action: "SUBMITTED",
      actor_user_id: "employee-user-1",
      actor_employee_id: "emp-1",
      stage: null,
      comment: "Forgot to punch",
      created_at: "2026-08-10T19:00:00Z",
    },
  ],
  created_at: "2026-08-10T19:00:00Z",
  updated_at: "2026-08-10T19:00:00Z",
};

describe("RegularizationDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
    mockUser.id = "manager-user-1";
    mockUser.employee_id = "manager-1";
    mockUser.permissions = ["ATTENDANCE.REGULARIZATION_APPROVE"];
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<RegularizationDetailPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the request's fields once loaded", async () => {
    mockedGet.mockResolvedValue(pendingRequest);
    render(<RegularizationDetailPage />);

    expect((await screen.findAllByText("Forgot to punch")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Submitted").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /^approve$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^reject$/i })).toBeInTheDocument();
  });

  it("shows a not-found message on 404", async () => {
    mockedGet.mockRejectedValue(new ApiError({ status: 404, code: "NOT_FOUND", message: "nope" }));
    render(<RegularizationDetailPage />);

    expect(await screen.findByText(/was not found, or you don't have access/i)).toBeInTheDocument();
  });

  it("does not show approve/reject for the request's own employee (self-approval blocked client-side too)", async () => {
    mockUser.employee_id = "emp-1"; // same as pendingRequest.employee_id
    mockedGet.mockResolvedValue(pendingRequest);
    render(<RegularizationDetailPage />);

    await screen.findAllByText("Forgot to punch");
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it("does not show approve/reject once the request is terminal", async () => {
    mockedGet.mockResolvedValue({ ...pendingRequest, status: "APPROVED", approval_stage: null });
    render(<RegularizationDetailPage />);

    await screen.findAllByText("Forgot to punch");
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it("approves the request and shows the applied correction", async () => {
    mockedGet.mockResolvedValue(pendingRequest);
    mockedPost.mockResolvedValue({
      ...pendingRequest,
      status: "APPROVED",
      approval_stage: null,
      applied_at: "2026-08-10T20:00:00Z",
      version: 2,
    });
    const user = userEvent.setup();
    render(<RegularizationDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^approve$/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/regularizations/request-1/approve",
        expect.any(Object),
        { ifMatch: "1" },
      );
    });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: "Request approved" }));
  });

  it("shows a self-approval error message from the backend", async () => {
    mockedGet.mockResolvedValue({ ...pendingRequest, employee_id: "someone-else" });
    mockedPost.mockRejectedValue(
      new ApiError({
        status: 403,
        code: "REGULARIZATION_SELF_APPROVAL_NOT_ALLOWED",
        message: "denied",
      }),
    );
    const user = userEvent.setup();
    render(<RegularizationDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^approve$/i }));

    expect(
      await screen.findByText(/you cannot approve or reject your own request/i),
    ).toBeInTheDocument();
  });

  it("shows a cancel action only for the original submitter", async () => {
    mockUser.id = "employee-user-1"; // matches submitted_by_user_id
    mockedGet.mockResolvedValue(pendingRequest);
    render(<RegularizationDetailPage />);

    expect(await screen.findByRole("button", { name: /cancel request/i })).toBeInTheDocument();
  });
});
