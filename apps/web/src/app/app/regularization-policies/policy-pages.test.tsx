import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ id: "p1" }),
}));
vi.mock("@/lib/auth/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/dates/use-company-date", () => ({ useCompanyDatePattern: () => "dd/MM/yyyy" }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import NewPage from "@/app/app/regularization-policies/new/page";
import DetailPage from "@/app/app/regularization-policies/[id]/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);

const liveVersion = {
  id: "v1",
  status: "PUBLISHED",
  version: 2,
  effective_from: "2026-01-01",
  effective_to: null,
  allow_employee_request: true,
  allow_manager_request: false,
  allow_hr_request: true,
  max_backdated_days: 7,
  max_requests_per_month: null,
  reason_required: true,
  attachment_required: false,
  approval_chain: "MANAGER",
  auto_approve_within_minutes: null,
  blocked_when_locked: true,
  allowed_types: [
    { id: "t1", regularization_type: "MISSING_PUNCH", sort_order: 0 },
    { id: "t2", regularization_type: "WFH", sort_order: 1 },
  ],
};

describe("regularization policy pages", () => {
  beforeEach(() => {
    mockedGet.mockImplementation(((path: string) => {
      if (path.startsWith("/policy-assignments/coverage")) {
        return Promise.resolve({
          scope_type: "COMPANY",
          scope_id: null,
          as_of: "2026-06-01",
          rows: [{ policy_kind: "REGULARIZATION_POLICY", leave_type_id: null, leave_type_name: null, own: null, applied: null }],
        });
      }
      if (path.endsWith("/versions")) return Promise.resolve([liveVersion]);
      return Promise.resolve({ id: "p1", name: "Corrections", code: "R1", is_active: true, version: 1 });
    }) as never);
    mockedGetList.mockResolvedValue({ data: [], pagination: { page: 1, per_page: 100, total: 0, total_pages: 0, has_next: false, has_prev: false } } as never);
    mockedPost.mockResolvedValue({ policy: { id: "new-1" } } as never);
  });

  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
    mockedPost.mockReset();
    push.mockReset();
  });

  it("describes the live rules in words", async () => {
    render(<DetailPage />);
    expect(await screen.findByText(/Live rules since/)).toBeInTheDocument();
    expect(screen.getByText("Employees, HR")).toBeInTheDocument();
    expect(screen.getByText("Missing punch, Work from home")).toBeInTheDocument();
    expect(screen.getByText("7 days")).toBeInTheDocument();
    expect(screen.getByText("Manager approves")).toBeInTheDocument();
  });

  it("starts from a template that allows every kind of correction", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    expect(screen.getAllByRole("checkbox", { checked: true }).length).toBeGreaterThanOrEqual(8);
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByLabelText(/Who follows/)).toHaveValue("COMPANY"));
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockedPost.mock.calls[0] as [string, Record<string, never>];
    expect(path).toBe("/regularization-policies/setup");
    expect((body.rules as unknown as { allowed_types: unknown[] }).allowed_types).toHaveLength(8);
    expect(push).toHaveBeenCalledWith("/app/regularization-policies/new-1");
  });

  it("will not publish a policy that allows no correction at all", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    await user.click(screen.getByRole("radio", { name: /Start from scratch/ }));
    await user.type(screen.getByLabelText(/Policy name/), "Mine");
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    expect(await screen.findByText(/Allow at least one kind of correction/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Select all" }));
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("can save a draft that allows nothing yet", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    await user.click(screen.getByRole("radio", { name: /Start from scratch/ }));
    await user.type(screen.getByLabelText(/Policy name/), "Later");
    await user.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    expect(mockedPost.mock.calls[0][1]).toMatchObject({ publish: false, assign: null });
  });
});
