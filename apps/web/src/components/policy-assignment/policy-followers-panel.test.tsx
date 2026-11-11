import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const permissions = { codes: new Set(["ATTENDANCE.POLICY_MANAGE", "ORG.CALENDAR.MANAGE"]) };
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: (code: string) => permissions.codes.has(code) }),
}));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/dates/use-company-date", () => ({ useCompanyDatePattern: () => "dd/MM/yyyy" }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/employee/use-employee-directory", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/employee/use-employee-directory")>()),
  useEmployeeDirectory: () => ({
    employees: [],
    total: 0,
    loading: false,
    loadingMore: false,
    error: null,
    hasMore: false,
    loadMore: vi.fn(),
    search: vi.fn(),
    reload: vi.fn(),
  }),
}));
vi.mock("@/components/work-calendar/change-impact-dialog", () => ({
  ChangeImpactDialog: ({ change, title }: { change: unknown; title: string }) =>
    change ? (
      <div role="dialog" aria-label={title}>
        impact preview {JSON.stringify(change)}
      </div>
    ) : null,
}));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { PolicyFollowersPanel } from "@/components/policy-assignment/policy-followers-panel";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);

const TODAY = "2026-06-15";

function assignment(overrides: Record<string, unknown>) {
  return {
    id: "a1",
    company_id: "c1",
    policy_kind: "ATTENDANCE_POLICY",
    policy_id: "p1",
    leave_type_id: null,
    scope_type: "COMPANY",
    scope_id: null,
    effective_from: "2026-01-01",
    effective_to: null,
    priority: 0,
    reason: null,
    is_active: true,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function serve(assignments: unknown[]) {
  mockedGetList.mockResolvedValue({
    data: assignments,
    pagination: { page: 1, per_page: 100, total: assignments.length, total_pages: 1 },
  } as never);
  mockedGet.mockImplementation(((path: string) => {
    if (path === "/branches") {
      return Promise.resolve([
        { id: "b1", name: "Pune", is_active: true },
        { id: "b2", name: "Mumbai", is_active: true },
      ]);
    }
    if (path.startsWith("/policy-assignments/coverage")) {
      return Promise.resolve({ scope_type: "BRANCH", scope_id: "b2", as_of: TODAY, rows: [] });
    }
    return Promise.resolve([]);
  }) as never);
}

function renderPanel(kind: "ATTENDANCE_POLICY" | "WORK_CALENDAR" = "ATTENDANCE_POLICY") {
  return render(
    <PolicyFollowersPanel
      policyKind={kind}
      policyId="p1"
      policyName="Office"
      today={TODAY}
      canManage
    />,
  );
}

describe("PolicyFollowersPanel", () => {
  beforeEach(() => {
    permissions.codes = new Set(["ATTENDANCE.POLICY_MANAGE", "ORG.CALENDAR.MANAGE"]);
  });
  afterEach(() => vi.clearAllMocks());

  it("lists who follows the policy today, by name, and leaves out ended assignments", async () => {
    serve([
      assignment({ id: "a1" }),
      assignment({ id: "a2", scope_type: "BRANCH", scope_id: "b1", version: 3 }),
      assignment({ id: "a3", scope_type: "BRANCH", scope_id: "b2", effective_to: "2026-03-31" }),
    ]);
    renderPanel();

    expect(await screen.findByText("Whole company")).toBeInTheDocument();
    expect(await screen.findByText("Branch: Pune")).toBeInTheDocument();
    expect(screen.queryByText("Branch: Mumbai")).not.toBeInTheDocument();
    expect(mockedGetList).toHaveBeenCalledWith("/policy-assignments", {
      policy_kind: "ATTENDANCE_POLICY",
      policy_id: "p1",
      live_on: "2026-06-15",
      per_page: 100,
    });

    // The company-wide row is everyone's fallback, so only the branch row can be ended.
    const rows = screen.getAllByRole("row");
    expect(within(rows[1]).queryByRole("button", { name: "End" })).not.toBeInTheDocument();
    expect(within(rows[2]).getByRole("button", { name: "End" })).toBeInTheDocument();
  });

  it("assigns the policy to another group without leaving the policy", async () => {
    serve([assignment({ id: "a1" })]);
    mockedPost.mockResolvedValue({} as never);
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: /add who follows it/i }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText(/^Branch/), "b2");
    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(expect.stringContaining("scope_id=b2")),
    );
    await user.click(within(dialog).getByRole("button", { name: "Assign" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/policy-assignments/batch", {
        scope_type: "BRANCH",
        scope_id: "b2",
        effective_from: TODAY,
        reason: null,
        changes: [
          {
            policy_kind: "ATTENDANCE_POLICY",
            policy_id: "p1",
            leave_type_id: null,
            expected_version: null,
          },
        ],
      }),
    );
  });

  it("sends calendar assignments through the impact preview instead of saving directly", async () => {
    serve([]);
    const user = userEvent.setup();
    renderPanel("WORK_CALENDAR");

    await user.click(await screen.findByRole("button", { name: /add who follows it/i }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText(/^Branch/), "b2");
    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(expect.stringContaining("scope_id=b2")),
    );
    await user.click(within(dialog).getByRole("button", { name: "Preview changes" }));

    expect(await screen.findByRole("dialog", { name: "Assign Office" })).toHaveTextContent(
      '"change_type":"ASSIGNMENT_CREATE"',
    );
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("offers no changes to someone who cannot manage assignments of this kind", async () => {
    permissions.codes = new Set(["ORG.CALENDAR.MANAGE"]);
    serve([assignment({ id: "a2", scope_type: "BRANCH", scope_id: "b1" })]);
    renderPanel();

    expect(await screen.findByText("Branch: Pune")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add who follows it/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End" })).not.toBeInTheDocument();
  });
});
