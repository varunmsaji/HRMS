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

import DetailPage from "@/app/app/leave-policies/[id]/page";
import ListPage from "@/app/app/leave-policies/page";
import NewPage from "@/app/app/leave-policies/new/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);

const leaveTypes = [
  { id: "lt1", code: "CL", name: "Casual Leave", is_active: true },
  { id: "lt2", code: "OLD", name: "Retired Leave", is_active: false },
];

const coverage = {
  scope_type: "COMPANY",
  scope_id: null,
  as_of: "2026-06-01",
  rows: [
    { policy_kind: "LEAVE_POLICY", leave_type_id: "lt1", leave_type_name: "Casual Leave", own: null, applied: null },
  ],
};

const liveVersion = {
  id: "v1",
  status: "PUBLISHED",
  version: 2,
  effective_from: "2026-01-01",
  effective_to: null,
  allow_employee_request: true,
  allow_manager_request_on_behalf: true,
  allow_hr_request_on_behalf: false,
  max_backdated_days: 7,
  max_requests_per_month: null,
  reason_required: true,
  attachment_required: false,
  approval_chain: "MANAGER_THEN_HR",
  half_day_allowed: true,
  accrual_frequency: "MONTHLY",
  accrual_rate_per_cycle: "1.5",
  max_carry_forward_days: "30",
  encashment_allowed: false,
  allow_negative_balance: false,
  negative_balance_floor: null,
  year_end_action: "CARRY_FORWARD",
  sandwich_rule_enabled: true,
  reserve_balance_on_submission: false,
  pre_delivery_days: null,
  post_delivery_days: null,
  allowed_during_probation: true,
  accrue_during_probation: false,
  max_encashment_days: null,
  min_balance_after_encashment: null,
  encashment_frequency: null,
  encashment_calculation_basis: null,
};

describe("leave policy pages", () => {
  beforeEach(() => {
    mockedGet.mockImplementation(((path: string) => {
      if (path.startsWith("/policy-assignments/coverage")) return Promise.resolve(coverage);
      if (path === "/leave-types") return Promise.resolve(leaveTypes);
      if (path === "/leave-policies") {
        return Promise.resolve([
          { id: "p1", name: "Casual leave", code: "LVP1", leave_type_id: "lt1", is_active: true, version: 1, live_from: "2026-01-01", assigned_company_wide: true, assigned_group_count: 0 },
        ]);
      }
      if (path.endsWith("/versions")) return Promise.resolve([liveVersion]);
      return Promise.resolve({ id: "p1", name: "Casual leave", code: "LVP1", leave_type_id: "lt1", is_active: true, version: 1 });
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

  it("lists each policy with its leave type, status and who it applies to", async () => {
    render(<ListPage />);
    expect(await screen.findByText("Casual leave")).toBeInTheDocument();
    expect(await screen.findByText("Casual Leave")).toBeInTheDocument();
    expect(screen.getByText(/Live since/)).toHaveTextContent("01/01/2026");
    expect(screen.getByText("Whole company")).toBeInTheDocument();
  });

  it("describes the live rules in words and names the leave type", async () => {
    render(<DetailPage />);
    expect(await screen.findByText(/Live rules since/)).toBeInTheDocument();
    expect(await screen.findByText("Leave type: Casual Leave")).toBeInTheDocument();
    expect(screen.getByText("Employees, Managers for their reports")).toBeInTheDocument();
    expect(screen.getByText("Manager approves, then HR")).toBeInTheDocument();
    expect(screen.getByText("1.5 each month")).toBeInTheDocument();
    expect(screen.getByText("7 days")).toBeInTheDocument();
  });

  it("needs a leave type before saving", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    await user.click(screen.getByRole("button", { name: "Save as draft" }));
    expect(await screen.findByText("Choose a leave type.")).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("offers only active leave types", async () => {
    render(<NewPage />);
    expect(await screen.findByRole("option", { name: "Casual Leave (CL)" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Retired Leave/ })).toBeNull();
  });

  it("publishes a template for a leave type, assigned company-wide, in one call", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    await screen.findByRole("option", { name: "Casual Leave (CL)" });
    await user.selectOptions(screen.getByLabelText(/Leave type/), "lt1");
    await user.click(screen.getByRole("radio", { name: /Earned leave/ }));
    expect(screen.getByLabelText(/Policy name/)).toHaveValue("Earned leave");

    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByLabelText(/Who follows/)).toHaveValue("COMPANY"));
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockedPost.mock.calls[0] as [string, Record<string, never>];
    expect(path).toBe("/leave-policies/setup");
    expect(body).toMatchObject({
      leave_type_id: "lt1",
      name: "Earned leave",
      publish: true,
      assign: { scope_type: "COMPANY", scope_id: null, expected_version: null },
    });
    expect(body.rules).toMatchObject({
      accrual_frequency: "MONTHLY",
      accrual_rate_per_cycle: "1.5",
      max_carry_forward_days: "30",
      year_end_action: "CARRY_FORWARD",
    });
    expect(push).toHaveBeenCalledWith("/app/leave-policies/new-1");
  });

  it("asks how many days are credited once a schedule is chosen", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    await user.click(screen.getByRole("radio", { name: /Start from scratch/ }));
    expect(screen.queryByLabelText(/Days credited each time/)).toBeNull();
    await user.selectOptions(screen.getByLabelText(/Days are credited/), "MONTHLY");
    expect(screen.getByLabelText(/Days credited each time/)).toBeInTheDocument();
  });

  it("only asks for a carry-forward cap when days can carry forward", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    await user.click(screen.getByRole("radio", { name: /Casual leave/ }));
    expect(screen.queryByLabelText(/Most days that carry forward/)).toBeNull();
    await user.selectOptions(
      screen.getByLabelText(/At the end of the leave year/),
      "ENCASH_EXCESS",
    );
    expect(screen.getByLabelText(/Most days that carry forward/)).toBeInTheDocument();
  });
});
