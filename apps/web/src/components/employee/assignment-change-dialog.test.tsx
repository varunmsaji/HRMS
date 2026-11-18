import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toastMock = vi.fn();
let mockCan: (code: string) => boolean = () => true;
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock("@/lib/auth/use-permissions", () => ({ usePermissions: () => ({ can: (c: string) => mockCan(c) }) }));
vi.mock("@/lib/employee/use-employee-directory", () => ({ useEmployeeDirectory: () => ({ employees: [] }) }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
// The field widgets are not under test: this stub shows the values the dialog owns.
vi.mock("@/components/employee/assignment-form", () => ({
  AssignmentForm: ({
    values,
    onChange,
    allowedChangeTypes,
  }: {
    values: { changeType: string };
    onChange: (v: object) => void;
    allowedChangeTypes: string[];
  }) => (
    <div>
      <p data-testid="change-type">{values.changeType || "none"}</p>
      <p data-testid="allowed">{allowedChangeTypes.join(",")}</p>
      <button
        type="button"
        onClick={() => onChange({ ...values, changeType: "SHIFT_CHANGE", effectiveFrom: "2026-12-01", shiftId: "shift-2" })}
      >
        pick shift
      </button>
    </div>
  ),
}));

import { AssignmentChangeDialog } from "@/components/employee/assignment-change-dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const row = {
  id: "a1",
  employee_id: "e1",
  reporting_manager_id: "mgr-1",
  shift_id: "shift-1",
  effective_from: "2026-01-01",
  effective_to: null,
  version: 4,
};

let assignments: object[];

beforeEach(() => {
  vi.clearAllMocks();
  mockCan = () => true;
  assignments = [row];
  mockedGet.mockImplementation((path: string) =>
    Promise.resolve(path.endsWith("/assignments") ? assignments : []),
  );
  mockedPost.mockResolvedValue({});
});

function renderDialog(props: Partial<React.ComponentProps<typeof AssignmentChangeDialog>> = {}) {
  const onOpenChange = vi.fn();
  const onSaved = vi.fn();
  render(
    <AssignmentChangeDialog employeeId="e1" open onOpenChange={onOpenChange} onSaved={onSaved} {...props} />,
  );
  return { onOpenChange, onSaved };
}

describe("AssignmentChangeDialog", () => {
  it("loads the current assignment and pre-selects the requested change type", async () => {
    renderDialog({ initialChangeType: "SHIFT_CHANGE" });
    await waitFor(() => expect(screen.getByTestId("change-type")).toHaveTextContent("SHIFT_CHANGE"));
    expect(mockedGet).toHaveBeenCalledWith("/employees/e1/assignments");
  });

  it("starts with no change type when none is requested", async () => {
    renderDialog();
    await waitFor(() => expect(screen.getByTestId("allowed")).toHaveTextContent("INITIAL"));
    expect(screen.getByTestId("change-type")).toHaveTextContent("none");
  });

  it("ignores a requested type the user may not record", async () => {
    mockCan = (code) => code === "EMPLOYEE.TRANSFER";
    renderDialog({ initialChangeType: "PROMOTION" });
    await waitFor(() => expect(screen.getByTestId("allowed")).toHaveTextContent("TRANSFER"));
    expect(screen.getByTestId("change-type")).toHaveTextContent("none");
  });

  it("makes the first placement INITIAL for an employee with no assignment", async () => {
    assignments = [];
    renderDialog({ initialChangeType: "SHIFT_CHANGE" });
    await waitFor(() => expect(screen.getByTestId("change-type")).toHaveTextContent("INITIAL"));
  });

  it("saves against the latest row's version, closes, and tells the caller", async () => {
    const { onOpenChange, onSaved } = renderDialog({ initialChangeType: "SHIFT_CHANGE" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "pick shift" }));
    await user.click(screen.getByRole("button", { name: "Save change" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    const [path, body, options] = mockedPost.mock.calls[0];
    expect(path).toBe("/employees/e1/assignments");
    expect(body).toMatchObject({ change_type: "SHIFT_CHANGE", shift_id: "shift-2", effective_from: "2026-12-01" });
    expect(options).toEqual({ ifMatch: "4" });
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does not save a change with no type or date", async () => {
    renderDialog();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Save change" }));
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("keeps the dialog open and does not report success when the row changed under it", async () => {
    mockedPost.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "STALE_RESOURCE", message: "stale", details: [] }),
    );
    const { onOpenChange, onSaved } = renderDialog({ initialChangeType: "SHIFT_CHANGE" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "pick shift" }));
    await user.click(screen.getByRole("button", { name: "Save change" }));
    expect(await screen.findByText(/changed by someone else/i)).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("shows a message and no form when the assignment cannot be read", async () => {
    mockedGet.mockImplementation((path: string) =>
      path.endsWith("/assignments")
        ? Promise.reject(new ApiError({ status: 403, code: "FORBIDDEN", message: "no", details: [] }))
        : Promise.resolve([]),
    );
    renderDialog();
    expect(await screen.findByText(/do not have permission to view or change/i)).toBeInTheDocument();
    expect(screen.queryByTestId("change-type")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save change" })).toBeDisabled();
  });

  it("loads nothing while closed", () => {
    render(<AssignmentChangeDialog employeeId="e1" open={false} onOpenChange={vi.fn()} onSaved={vi.fn()} />);
    expect(mockedGet).not.toHaveBeenCalled();
  });
});
