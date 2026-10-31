import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toastMock = vi.fn();
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: () => true }),
}));
vi.mock("@/lib/employee/use-employee-directory", () => ({
  useEmployeeDirectory: () => ({ employees: [] }),
}));
vi.mock("@/lib/employee/use-employee-names", () => ({
  useEmployeeNames: () => (id: string) => id,
}));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));
// The form's field widgets are not under test; this stub only drives the values the panel owns.
vi.mock("@/components/employee/assignment-form", () => ({
  AssignmentForm: ({ values, onChange }: { values: object; onChange: (v: object) => void }) => (
    <div>
      <button
        type="button"
        onClick={() =>
          onChange({ ...values, changeType: "MANAGER_CHANGE", effectiveFrom: "2026-11-01", reportingManagerId: "mgr-2" })
        }
      >
        pick new manager
      </button>
      <button
        type="button"
        onClick={() =>
          onChange({ ...values, changeType: "TRANSFER", effectiveFrom: "2026-11-01", departmentId: "dep-2" })
        }
      >
        pick transfer only
      </button>
    </div>
  ),
}));

import { AssignmentPanel } from "@/components/employee/assignment-panel";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const current = {
  id: "a1",
  company_id: "c1",
  employee_id: "e1",
  branch_id: null,
  department_id: null,
  designation_id: null,
  grade_id: null,
  reporting_manager_id: "mgr-1",
  dotted_line_manager_id: null,
  cost_centre_id: null,
  shift_id: null,
  work_location_type: null,
  change_type: "INITIAL",
  change_reason: null,
  effective_from: "2026-01-01",
  effective_to: null,
  version: 3,
  created_at: "",
  updated_at: "",
};

function impact(leave: number, reg: number, ot: number, token = "tok-1") {
  const total = leave + reg + ot;
  return {
    has_pending_requests: total > 0,
    total_pending_requests: total,
    requests: { leave, attendance_regularization: reg, overtime: ot },
    requires_confirmation: total > 0,
    impact_token: token,
  };
}

function conflict(leave: number, reg: number, ot: number, token: string) {
  const { requires_confirmation: _r, impact_token: _t, ...rest } = impact(leave, reg, ot, token);
  return new ApiError({
    status: 409,
    code: "MANAGER_CHANGE_REQUIRES_CONFIRMATION",
    message: "pending",
    details: [
      {
        field: "reporting_manager_id",
        code: "MANAGER_CHANGE_REQUIRES_CONFIRMATION",
        message: "pending",
        context: { impact: rest, impact_token: token },
      },
    ],
  });
}

let impactResponse: ReturnType<typeof impact> | Error;

beforeEach(() => {
  vi.clearAllMocks();
  impactResponse = impact(0, 0, 0);
  mockedGet.mockImplementation((path: string) => {
    if (path.includes("/manager-change-impact")) {
      return impactResponse instanceof Error ? Promise.reject(impactResponse) : Promise.resolve(impactResponse);
    }
    if (path.endsWith("/assignments")) return Promise.resolve([current]);
    return Promise.resolve([]);
  });
  mockedPost.mockResolvedValue({});
});

async function openAndPick(label: string) {
  const user = userEvent.setup();
  render(<AssignmentPanel employeeId="e1" />);
  await user.click(await screen.findByRole("button", { name: "Record a change" }));
  await user.click(await screen.findByRole("button", { name: label }));
  return user;
}

const impactCalls = () => mockedGet.mock.calls.filter(([p]) => String(p).includes("/manager-change-impact"));

describe("manager change warning", () => {
  it("saves without a dialog when no requests are pending", async () => {
    const user = await openAndPick("pick new manager");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("manager-change-impact-dialog")).toBeNull();
    const body = mockedPost.mock.calls[0][1] as Record<string, unknown>;
    expect(body.confirm_pending_request_impact).toBeUndefined();
    expect(mockedPost.mock.calls[0][2]).toEqual({ ifMatch: "3" });
    expect(impactCalls()[0][0]).toContain("reporting_manager_id=mgr-2");
  });

  it("does not preview when the manager is not changing", async () => {
    const user = await openAndPick("pick transfer only");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(impactCalls()).toHaveLength(0);
  });

  it("shows per-type counts and posts nothing until the user confirms", async () => {
    impactResponse = impact(2, 1, 3);
    const user = await openAndPick("pick new manager");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    const dialog = await screen.findByTestId("manager-change-impact-dialog");
    expect(within(dialog).getByText("Leave requests").nextSibling).toHaveTextContent("2");
    expect(within(dialog).getByText("Attendance corrections").nextSibling).toHaveTextContent("1");
    expect(within(dialog).getByText("Overtime requests").nextSibling).toHaveTextContent("3");
    expect(within(dialog).getByTestId("impact-total")).toHaveTextContent("6");
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("cancel closes the warning without saving", async () => {
    impactResponse = impact(1, 0, 0);
    const user = await openAndPick("pick new manager");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    const dialog = await screen.findByTestId("manager-change-impact-dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByTestId("manager-change-impact-dialog")).toBeNull());
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("confirm posts the flag and token with If-Match, once even on a double click", async () => {
    impactResponse = impact(1, 0, 0, "tok-A");
    let release!: () => void;
    mockedPost.mockImplementation(() => new Promise((resolve) => { release = () => resolve({}); }));
    const user = await openAndPick("pick new manager");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    const dialog = await screen.findByTestId("manager-change-impact-dialog");
    const confirm = within(dialog).getByRole("button", { name: "Change Manager Anyway" });
    await user.dblClick(confirm);
    expect(await within(dialog).findByRole("button", { name: "Changing Manager…" })).toBeDisabled();
    expect(mockedPost).toHaveBeenCalledTimes(1);
    const [, body, opts] = mockedPost.mock.calls[0];
    expect(body).toMatchObject({ confirm_pending_request_impact: true, pending_impact_token: "tok-A" });
    expect(opts).toEqual({ ifMatch: "3" });
    release();
    await waitFor(() => expect(screen.queryByTestId("manager-change-impact-dialog")).toBeNull());
  });

  it("a stale token re-shows the new counts, asks again and never reuses the old token", async () => {
    impactResponse = impact(1, 0, 0, "tok-A");
    mockedPost.mockRejectedValueOnce(conflict(1, 2, 0, "tok-B")).mockResolvedValueOnce({});
    const user = await openAndPick("pick new manager");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    let dialog = await screen.findByTestId("manager-change-impact-dialog");
    await user.click(within(dialog).getByRole("button", { name: "Change Manager Anyway" }));
    dialog = await screen.findByTestId("manager-change-impact-dialog");
    await within(dialog).findByText(/changed while you were reviewing/i);
    expect(within(dialog).getByTestId("impact-total")).toHaveTextContent("3");
    expect(toastMock).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Change Manager Anyway" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(2));
    expect(mockedPost.mock.calls[1][1]).toMatchObject({ pending_impact_token: "tok-B" });
  });

  it("an impact preview failure shows an error and saves nothing", async () => {
    impactResponse = new ApiError({ status: 500, code: "INTERNAL", message: "boom" });
    const user = await openAndPick("pick new manager");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ variant: "danger" })));
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("keeps the existing optimistic-lock banner on STALE_RESOURCE", async () => {
    mockedPost.mockRejectedValueOnce(new ApiError({ status: 409, code: "STALE_RESOURCE", message: "stale" }));
    const user = await openAndPick("pick new manager");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
  });

  it("keeps the existing 403 behaviour", async () => {
    mockedPost.mockRejectedValueOnce(new ApiError({ status: 403, code: "FORBIDDEN", message: "no" }));
    const user = await openAndPick("pick new manager");
    await user.click(screen.getByRole("button", { name: "Save change" }));
    await waitFor(() =>
      expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ title: "You don't have permission to do that" })),
    );
  });
});
