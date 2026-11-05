import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "ot-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const mockUser: {
  id: string;
  employee_id: string | null;
  permissions: string[];
} = {
  id: "manager-user-1",
  employee_id: "manager-1",
  permissions: ["ATTENDANCE.OVERTIME_APPROVE"],
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

import OvertimeDetailPage from "@/app/app/overtime/[id]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { OvertimeRecord } from "@/lib/overtime/types";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const pendingRecord: OvertimeRecord = {
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
  comp_off_minutes: 120,
  comp_off_expiry_date: "2026-11-08",
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

describe("OvertimeDetailPage", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedPost.mockReset();
    toastMock.mockReset();
    mockUser.id = "manager-user-1";
    mockUser.employee_id = "manager-1";
    mockUser.permissions = ["ATTENDANCE.OVERTIME_APPROVE"];
  });

  it("shows a loading state before data resolves", () => {
    mockedGet.mockReturnValue(new Promise(() => {}));
    render(<OvertimeDetailPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders the record's fields once loaded, including comp-off", async () => {
    mockedGet.mockResolvedValue(pendingRecord);
    render(<OvertimeDetailPage />);

    expect((await screen.findAllByText("Holiday")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
    expect(screen.getByText(/OT_HOLIDAY \(1.5000x\)/)).toBeInTheDocument();
    expect(screen.getByText(/expires 08\/11\/2026/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^approve$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^reject$/i })).toBeInTheDocument();
  });

  it("hides comp-off field when comp_off_minutes is zero", async () => {
    mockedGet.mockResolvedValue({ ...pendingRecord, comp_off_minutes: 0, comp_off_expiry_date: null });
    render(<OvertimeDetailPage />);

    await screen.findAllByText("Holiday");
    expect(screen.queryByText(/comp-off/i)).not.toBeInTheDocument();
  });

  it("shows a not-found message on 404", async () => {
    mockedGet.mockRejectedValue(new ApiError({ status: 404, code: "NOT_FOUND", message: "nope" }));
    render(<OvertimeDetailPage />);

    expect(await screen.findByText(/was not found, or you don't have access/i)).toBeInTheDocument();
  });

  it("does not show approve/reject for the record's own employee (self-approval blocked client-side too)", async () => {
    mockUser.employee_id = "emp-1"; // same as pendingRecord.employee_id
    mockedGet.mockResolvedValue(pendingRecord);
    render(<OvertimeDetailPage />);

    await screen.findAllByText("Holiday");
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it("does not show approve/reject once the record is terminal", async () => {
    mockedGet.mockResolvedValue({ ...pendingRecord, status: "APPROVED", approval_stage: null });
    render(<OvertimeDetailPage />);

    await screen.findAllByText("Holiday");
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it("does not show approve/reject for an auto-approved record", async () => {
    mockedGet.mockResolvedValue({
      ...pendingRecord,
      status: "AUTO_APPROVED",
      approval_stage: null,
      approval_chain: "AUTO",
    });
    render(<OvertimeDetailPage />);

    await screen.findAllByText("Holiday");
    expect(screen.queryByRole("button", { name: /^approve$/i })).not.toBeInTheDocument();
  });

  it("approves the record", async () => {
    mockedGet.mockResolvedValue(pendingRecord);
    mockedPost.mockResolvedValue({
      ...pendingRecord,
      status: "APPROVED",
      approval_stage: null,
      minutes_approved: 120,
      version: 2,
    });
    const user = userEvent.setup();
    render(<OvertimeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^approve$/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/overtime/ot-1/approve",
        expect.any(Object),
        { ifMatch: "1" },
      );
    });
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: "Overtime approved" }));
  });

  it("approves fewer minutes with a comment", async () => {
    mockedGet.mockResolvedValue({ ...pendingRecord, employee_id: "someone-else" });
    mockedPost.mockResolvedValue({
      ...pendingRecord,
      status: "APPROVED",
      approval_stage: null,
      minutes_approved: 60,
    });
    const user = userEvent.setup();
    render(<OvertimeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    const minutes = within(dialog).getByLabelText(/minutes to approve/i);
    expect(minutes).toHaveValue(120);
    await user.clear(minutes);
    await user.type(minutes, "60");
    await user.type(within(dialog).getByLabelText(/comment/i), "Stayed one hour");
    await user.click(within(dialog).getByRole("button", { name: /^approve$/i }));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/overtime/ot-1/approve",
        expect.objectContaining({ minutes_approved: 60, reviewer_comment: "Stayed one hour" }),
        { ifMatch: "1" },
      );
    });
  });

  it("does not send minutes when they are left as detected", async () => {
    mockedGet.mockResolvedValue({ ...pendingRecord, employee_id: "someone-else" });
    mockedPost.mockResolvedValue({ ...pendingRecord, status: "APPROVED", approval_stage: null });
    const user = userEvent.setup();
    render(<OvertimeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^approve$/i }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalled());
    expect(mockedPost.mock.calls[0][1]).toEqual(
      expect.objectContaining({ minutes_approved: undefined }),
    );
  });

  it.each([
    ["more than detected", "121", "Stayed", /whole minutes from 1 to 120/i],
    ["zero", "0", "Stayed", /whole minutes from 1 to 120/i],
    ["changed without a comment", "60", "", /add a comment/i],
  ])("refuses minutes that are %s", async (_name, entered, comment, message) => {
    mockedGet.mockResolvedValue({ ...pendingRecord, employee_id: "someone-else" });
    const user = userEvent.setup();
    render(<OvertimeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    const minutes = within(dialog).getByLabelText(/minutes to approve/i);
    await user.clear(minutes);
    await user.type(minutes, entered);
    if (comment) await user.type(within(dialog).getByLabelText(/comment/i), comment);
    await user.click(within(dialog).getByRole("button", { name: /^approve$/i }));

    expect(await within(dialog).findByText(message)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("does not offer minutes at the manager step of a two-step chain", async () => {
    mockedGet.mockResolvedValue({
      ...pendingRecord,
      employee_id: "someone-else",
      approval_chain: "MANAGER_THEN_HR",
      approval_stage: "MANAGER",
    });
    const user = userEvent.setup();
    render(<OvertimeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText(/minutes to approve/i)).not.toBeInTheDocument();
  });

  it("shows a self-approval error message from the backend", async () => {
    mockedGet.mockResolvedValue({ ...pendingRecord, employee_id: "someone-else" });
    mockedPost.mockRejectedValue(
      new ApiError({
        status: 403,
        code: "OVERTIME_SELF_APPROVAL_NOT_ALLOWED",
        message: "denied",
      }),
    );
    const user = userEvent.setup();
    render(<OvertimeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^approve$/i }));

    expect(
      await screen.findByText(/you cannot approve or reject your own overtime record/i),
    ).toBeInTheDocument();
  });

  it("shows a stale-transition error message from the backend", async () => {
    mockedGet.mockResolvedValue({ ...pendingRecord, employee_id: "someone-else" });
    mockedPost.mockRejectedValue(
      new ApiError({
        status: 409,
        code: "OVERTIME_INVALID_TRANSITION",
        message: "already left pending",
      }),
    );
    const user = userEvent.setup();
    render(<OvertimeDetailPage />);

    await user.click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^approve$/i }));

    expect(
      await screen.findByText(/already left the pending state/i),
    ).toBeInTheDocument();
  });
});
