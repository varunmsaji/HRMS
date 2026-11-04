import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/dates/use-company-date", () => ({ useCompanyDatePattern: () => "dd/MM/yyyy" }));
const toast = vi.fn();
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() },
}));

import PolicyAssignmentsPage from "@/app/app/policy-assignments/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);

const PAGE = { page: 1, per_page: 25, total: 1, total_pages: 1, has_next: false, has_prev: false };

const override = {
  id: "as-1",
  company_id: "c1",
  policy_kind: "ATTENDANCE_POLICY",
  policy_id: "ap-1",
  leave_type_id: null,
  scope_type: "DEPARTMENT",
  scope_id: "dep-1",
  effective_from: "2026-01-01",
  effective_to: null,
  priority: 0,
  reason: null,
  is_active: true,
  version: 3,
  created_at: "",
  updated_at: "",
};

describe("PolicyAssignmentsPage", () => {
  let open: typeof override | null;

  beforeEach(() => {
    open = null;
    mockedGet.mockImplementation(((path: string) => {
      if (path === "/attendance-policies") {
        return Promise.resolve([
          { id: "ap-1", name: "Office rules" },
          { id: "ap-draft", name: "Unpublished draft" },
        ]);
      }
      if (path === "/attendance-policies?assignable=true") {
        return Promise.resolve([{ id: "ap-1", name: "Office rules", is_active: true }]);
      }
      if (path === "/departments") return Promise.resolve([{ id: "dep-1", name: "Operations" }]);
      return Promise.resolve([]);
    }) as never);
    mockedGetList.mockImplementation(((path: string, query?: Record<string, unknown>) => {
      if (path === "/employees") {
        return Promise.resolve({ data: [], pagination: { ...PAGE, total: 0 } });
      }
      if (query?.current_only) {
        return Promise.resolve({ data: open ? [open] : [], pagination: PAGE });
      }
      return Promise.resolve({ data: [override], pagination: PAGE });
    }) as never);
    mockedPost.mockResolvedValue({} as never);
  });

  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
    mockedPost.mockReset();
    toast.mockReset();
  });

  async function createCompanyAssignment() {
    const user = userEvent.setup();
    render(<PolicyAssignmentsPage />);
    await user.click(await screen.findByRole("button", { name: /New Assignment/ }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Effective from/), "2027-02-01");
    const pick = within(dialog).getByLabelText("Attendance Policy");
    await within(pick).findByRole("option", { name: "Office rules" });
    await user.selectOptions(pick, "ap-1");
    await user.click(within(dialog).getByRole("button", { name: "Create assignment" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    return mockedPost.mock.calls[0];
  }

  it("shows names rather than ids", async () => {
    render(<PolicyAssignmentsPage />);
    expect(await screen.findByText(/Attendance Policy → Department: Operations/)).toBeInTheDocument();
    expect(await screen.findByText(/Office rules/)).toBeInTheDocument();
    expect(screen.queryByText(/ap-1/)).not.toBeInTheDocument();
  });

  it("sends the open assignment's version when replacing one", async () => {
    open = { ...override, scope_type: "COMPANY", scope_id: null as never, version: 7 };
    const [path, , options] = await createCompanyAssignment();
    expect(path).toBe("/policy-assignments");
    expect(options).toEqual({ ifMatch: "7" });
    expect(mockedGetList).toHaveBeenCalledWith(
      "/policy-assignments",
      expect.objectContaining({
        policy_kind: "ATTENDANCE_POLICY",
        scope_type: "COMPANY",
        current_only: "true",
      }),
    );
  });

  it("sends no version when there is nothing to replace", async () => {
    const [, , options] = await createCompanyAssignment();
    expect(options).toBeUndefined();
  });

  it("only offers published policies", async () => {
    const user = userEvent.setup();
    render(<PolicyAssignmentsPage />);
    await user.click(await screen.findByRole("button", { name: /New Assignment/ }));
    const pick = within(await screen.findByRole("dialog")).getByLabelText("Attendance Policy");
    await within(pick).findByRole("option", { name: "Office rules" });
    expect(within(pick).queryByRole("option", { name: "Unpublished draft" })).toBeNull();
  });

  it("ends an override with its version", async () => {
    const user = userEvent.setup();
    render(<PolicyAssignmentsPage />);
    await user.click(await screen.findByRole("button", { name: "End" }));
    const dialog = await screen.findByRole("dialog");
    const date = within(dialog).getByLabelText(/Last day/);
    await user.clear(date);
    await user.type(date, "2027-03-31");
    await user.click(within(dialog).getByRole("button", { name: "End assignment" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/policy-assignments/as-1/end",
        { effective_to: "2027-03-31" },
        { ifMatch: "3" },
      ),
    );
  });

  it.each([
    ["company-wide", { scope_type: "COMPANY", scope_id: null }],
    ["calendar", { policy_kind: "WORK_CALENDAR" }],
    ["already ended", { effective_to: "2026-06-30" }],
  ])("offers no End action for a %s assignment", async (_label, patch) => {
    mockedGetList.mockImplementation(((path: string) =>
      Promise.resolve(
        path === "/employees"
          ? { data: [], pagination: { ...PAGE, total: 0 } }
          : { data: [{ ...override, ...patch }], pagination: PAGE },
      )) as never);
    render(<PolicyAssignmentsPage />);
    await screen.findByText(/→/);
    expect(screen.queryByRole("button", { name: "End" })).toBeNull();
  });
});
