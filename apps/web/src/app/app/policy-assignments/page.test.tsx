import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
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
import { ApiError } from "@/lib/api/errors";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);

const PAGE = { page: 1, per_page: 25, total: 1, total_pages: 1, has_next: false, has_prev: false };

const assignment = {
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

const companyApplied = {
  policy_id: "ap-1",
  policy_name: "Office rules",
  scope_type: "COMPANY",
  scope_id: null,
  scope_name: null,
  effective_from: "2026-01-01",
  effective_to: null,
  has_rules: true,
};

const own = {
  assignment_id: "as-1",
  policy_id: "ap-1",
  policy_name: "Office rules",
  effective_from: "2026-01-01",
  version: 7,
};

function coverageRows(scope: string) {
  if (scope === "DEPARTMENT") {
    return [
      {
        policy_kind: "ATTENDANCE_POLICY",
        leave_type_id: null,
        leave_type_name: null,
        own: null,
        applied: companyApplied,
      },
      {
        policy_kind: "OVERTIME_POLICY",
        leave_type_id: null,
        leave_type_name: null,
        own: { ...own, assignment_id: "as-2", policy_id: "ot-1", policy_name: "OT plan", version: 2 },
        applied: {
          ...companyApplied,
          policy_id: "ot-1",
          policy_name: "OT plan",
          scope_type: "DEPARTMENT",
          scope_id: "dep-1",
          scope_name: "Operations",
        },
      },
    ];
  }
  return [
    {
      policy_kind: "ATTENDANCE_POLICY",
      leave_type_id: null,
      leave_type_name: null,
      own,
      applied: companyApplied,
    },
    {
      policy_kind: "WORK_CALENDAR",
      leave_type_id: null,
      leave_type_name: null,
      own: null,
      applied: null,
    },
    {
      policy_kind: "LEAVE_POLICY",
      leave_type_id: "lt-1",
      leave_type_name: "Casual",
      own: null,
      applied: null,
    },
  ];
}

describe("PolicyAssignmentsPage", () => {
  beforeEach(() => {
    mockedGet.mockImplementation(((path: string) => {
      if (path.startsWith("/policy-assignments/coverage")) {
        const scope = new URLSearchParams(path.split("?")[1]).get("scope_type") ?? "";
        return Promise.resolve({ scope_type: scope, scope_id: null, as_of: "2026-06-01", rows: coverageRows(scope) });
      }
      if (path === "/attendance-policies") {
        return Promise.resolve([
          { id: "ap-1", name: "Office rules" },
          { id: "ap-draft", name: "Unpublished draft" },
        ]);
      }
      if (path === "/attendance-policies?assignable=true") {
        return Promise.resolve([
          { id: "ap-1", name: "Office rules", is_active: true },
          { id: "ap-2", name: "Strict rules", is_active: true },
        ]);
      }
      if (path === "/leave-policies?assignable=true") {
        return Promise.resolve([
          { id: "lp-1", name: "Casual plan", leave_type_id: "lt-1" },
          { id: "lp-2", name: "Earned plan", leave_type_id: "lt-2" },
        ]);
      }
      if (path === "/work-calendars") return Promise.resolve([{ id: "wc-1", name: "Main calendar" }]);
      if (path === "/departments") return Promise.resolve([{ id: "dep-1", name: "Operations" }]);
      return Promise.resolve([]);
    }) as never);
    mockedGetList.mockImplementation(((path: string) =>
      Promise.resolve(
        path === "/employees"
          ? { data: [], pagination: { ...PAGE, total: 0 } }
          : { data: [assignment], pagination: PAGE },
      )) as never);
    mockedPost.mockResolvedValue([] as never);
  });

  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
    mockedPost.mockReset();
    toast.mockReset();
  });

  async function setEffective(user: ReturnType<typeof userEvent.setup>, value: string) {
    const date = screen.getByLabelText(/Effective from/);
    await user.clear(date);
    await user.type(date, value);
  }

  describe("Set policies", () => {
    it("starts on the whole company and shows what applies", async () => {
      render(<PolicyAssignmentsPage />);
      expect(await screen.findByText("Set here since", { exact: false })).toBeInTheDocument();
      expect(screen.getAllByText("Not set").length).toBeGreaterThan(0);
      expect(mockedGet).toHaveBeenCalledWith(
        expect.stringMatching(/^\/policy-assignments\/coverage\?scope_type=COMPANY&as_of=/),
      );
    });

    it("shows where an inherited policy comes from, and ends a local one", async () => {
      const user = userEvent.setup();
      render(<PolicyAssignmentsPage />);
      await user.selectOptions(await screen.findByLabelText(/Who does this apply to/), "DEPARTMENT");
      await within(await screen.findByLabelText(/^Department/)).findByRole("option", {
        name: "Operations",
      });
      await user.selectOptions(screen.getByLabelText(/^Department/), "dep-1");

      expect(await screen.findByText("Inherited from Whole company")).toBeInTheDocument();
      expect(screen.getAllByRole("option", { name: "Keep inherited" }).length).toBe(1);

      await user.click(screen.getByRole("button", { name: "Return to inherited" }));
      const dialog = await screen.findByRole("dialog");
      const date = within(dialog).getByLabelText(/Last day/);
      await user.clear(date);
      await user.type(date, "2027-03-31");
      await user.click(within(dialog).getByRole("button", { name: "End assignment" }));
      await waitFor(() =>
        expect(mockedPost).toHaveBeenCalledWith(
          "/policy-assignments/as-2/end",
          { effective_to: "2027-03-31" },
          { ifMatch: "2" },
        ),
      );
    });

    it("says when a setting here is ending", async () => {
      mockedGet.mockImplementation(((path: string) =>
        Promise.resolve(
          path.startsWith("/policy-assignments/coverage")
            ? {
                scope_type: "COMPANY",
                scope_id: null,
                as_of: "2026-06-01",
                rows: [
                  {
                    policy_kind: "ATTENDANCE_POLICY",
                    leave_type_id: null,
                    leave_type_name: null,
                    own: null,
                    applied: { ...companyApplied, effective_to: "2026-06-30" },
                  },
                ],
              }
            : [],
        )) as never);
      render(<PolicyAssignmentsPage />);
      expect(await screen.findByText(/Set here until/)).toHaveTextContent(
        "Set here until 30/06/2026, then inherited",
      );
    });

    it("saves changed rows together, with the version of what they replace", async () => {
      const user = userEvent.setup();
      render(<PolicyAssignmentsPage />);
      const attendance = await screen.findByLabelText("Change Attendance Policy");
      await within(attendance).findByRole("option", { name: "Strict rules" });
      expect(screen.getByRole("button", { name: "No changes" })).toBeDisabled();

      await user.selectOptions(attendance, "ap-2");
      const leave = screen.getByLabelText("Change Leave Policy — Casual");
      expect(within(leave).queryByRole("option", { name: "Earned plan" })).toBeNull();
      await user.selectOptions(leave, "lp-1");
      await setEffective(user, "2027-02-01");

      await user.click(screen.getByRole("button", { name: "Review 2 changes" }));
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText("Office rules → Strict rules")).toBeInTheDocument();
      expect(within(dialog).getByText("Not set → Casual plan")).toBeInTheDocument();
      await user.click(within(dialog).getByRole("button", { name: "Confirm" }));

      await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
      const [path, body] = mockedPost.mock.calls[0];
      expect(path).toBe("/policy-assignments/batch");
      expect(body).toMatchObject({
        scope_type: "COMPANY",
        scope_id: null,
        effective_from: "2027-02-01",
        changes: [
          { policy_kind: "ATTENDANCE_POLICY", policy_id: "ap-2", leave_type_id: null, expected_version: 7 },
          { policy_kind: "LEAVE_POLICY", policy_id: "lp-1", leave_type_id: "lt-1", expected_version: null },
        ],
      });
    });

    it("does not count picking the current policy again as a change", async () => {
      const user = userEvent.setup();
      render(<PolicyAssignmentsPage />);
      const attendance = await screen.findByLabelText("Change Attendance Policy");
      await within(attendance).findByRole("option", { name: "Strict rules" });
      await user.selectOptions(attendance, "ap-2");
      await user.selectOptions(attendance, "ap-1");
      expect(screen.getByRole("button", { name: "No changes" })).toBeDisabled();
    });

    it("refuses a date that is not after the current assignment's start", async () => {
      const user = userEvent.setup();
      render(<PolicyAssignmentsPage />);
      const attendance = await screen.findByLabelText("Change Attendance Policy");
      await within(attendance).findByRole("option", { name: "Strict rules" });
      await user.selectOptions(attendance, "ap-2");
      await setEffective(user, "2026-01-01");
      await user.click(screen.getByRole("button", { name: "Review 1 change" }));
      expect(await screen.findByText(/must start after 01\/01\/2026/)).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("names the failed row and says nothing was saved", async () => {
      mockedPost.mockRejectedValue(
        new ApiError({
          status: 422,
          code: "POLICY_NOT_PUBLISHED",
          message: "Publish this policy before assigning it",
          details: [
            {
              field: "changes",
              code: "POLICY_NOT_PUBLISHED",
              message: "Publish this policy before assigning it",
              context: { policy_kind: "ATTENDANCE_POLICY", leave_type_id: null },
            },
          ],
        }),
      );
      const user = userEvent.setup();
      render(<PolicyAssignmentsPage />);
      const attendance = await screen.findByLabelText("Change Attendance Policy");
      await within(attendance).findByRole("option", { name: "Strict rules" });
      await user.selectOptions(attendance, "ap-2");
      await setEffective(user, "2027-02-01");
      await user.click(screen.getByRole("button", { name: "Review 1 change" }));
      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: "Confirm" }));
      expect(
        await within(dialog).findByText(/Nothing was saved\. Attendance Policy: Publish this policy/),
      ).toBeInTheDocument();
    });

    it("sends calendar changes to the impact preview, not the batch", async () => {
      // The preview stays pending: this test only checks where the change is sent.
      mockedPost.mockImplementation((() => new Promise(() => {})) as never);
      const user = userEvent.setup();
      render(<PolicyAssignmentsPage />);
      const calendar = await screen.findByLabelText("Change Work Calendar");
      await within(calendar).findByRole("option", { name: "Main calendar" });
      await user.selectOptions(calendar, "wc-1");
      await setEffective(user, "2027-02-01");
      await user.click(screen.getByRole("button", { name: "Review 1 change" }));
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText(/open an impact preview next/)).toBeInTheDocument();
      await user.click(within(dialog).getByRole("button", { name: "Confirm" }));
      await waitFor(() =>
        expect(mockedPost).toHaveBeenCalledWith(
          "/work-calendar-changes/preview",
          expect.objectContaining({
            change: expect.objectContaining({ change_type: "ASSIGNMENT_CREATE" }),
          }),
        ),
      );
      expect(mockedPost).not.toHaveBeenCalledWith("/policy-assignments/batch", expect.anything());
    });
  });

  describe("All assignments", () => {
    async function openTab() {
      const user = userEvent.setup();
      render(<PolicyAssignmentsPage />);
      await user.click(screen.getByRole("tab", { name: "All assignments" }));
      return user;
    }

    it("groups by who it applies to and shows names rather than ids", async () => {
      await openTab();
      expect(await screen.findByText("Department: Operations")).toBeInTheDocument();
      expect(await screen.findByText(/Office rules/)).toBeInTheDocument();
      expect(screen.queryByText(/ap-1/)).not.toBeInTheDocument();
    });

    it("ends an override with its version", async () => {
      const user = await openTab();
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
            : { data: [{ ...assignment, ...patch }], pagination: PAGE },
        )) as never);
      await openTab();
      await screen.findByText(/2026|open/);
      expect(screen.queryByRole("button", { name: "End" })).toBeNull();
    });
  });

  describe("Check an employee", () => {
    it("shows each policy and where it comes from for a chosen date", async () => {
      mockedGetList.mockImplementation((() =>
        Promise.resolve({
          data: [{ id: "e1", first_name: "Asha", last_name: "Rao", employee_code: "E1" }],
          pagination: PAGE,
        })) as never);
      mockedGet.mockImplementation(((path: string) =>
        Promise.resolve(
          path.startsWith("/policy-assignments/coverage")
            ? {
                scope_type: "EMPLOYEE",
                scope_id: "e1",
                as_of: "2026-06-01",
                rows: [
                  {
                    policy_kind: "ATTENDANCE_POLICY",
                    leave_type_id: null,
                    leave_type_name: null,
                    own: null,
                    applied: { ...companyApplied, has_rules: false },
                  },
                  {
                    policy_kind: "OVERTIME_POLICY",
                    leave_type_id: null,
                    leave_type_name: null,
                    own: null,
                    applied: null,
                  },
                ],
              }
            : [],
        )) as never);
      const user = userEvent.setup();
      render(<PolicyAssignmentsPage />);
      await user.click(screen.getByRole("tab", { name: "Check a person" }));
      const select = await screen.findByRole("combobox");
      await within(select).findByRole("option", { name: "Asha Rao (E1)" });
      await user.selectOptions(select, "e1");
      await user.click(screen.getByRole("button", { name: "Check" }));

      expect(await screen.findByText("Office rules")).toBeInTheDocument();
      expect(screen.getByText(/No published rules on this date/)).toBeInTheDocument();
      expect(screen.getByText("Nothing assigned at any level")).toBeInTheDocument();
      const call = mockedGet.mock.calls.map((c) => c[0] as string).find((p) => p.includes("scope_type=EMPLOYEE"));
      expect(call).toContain("scope_id=e1");
    });
  });
});
