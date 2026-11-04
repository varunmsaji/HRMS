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

import NewPage from "@/app/app/overtime-policies/new/page";
import DetailPage from "@/app/app/overtime-policies/[id]/page";
import ListPage from "@/app/app/overtime-policies/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPost = vi.mocked(apiClient.post);

const coverage = {
  scope_type: "COMPANY",
  scope_id: null,
  as_of: "2026-06-01",
  rows: [
    { policy_kind: "OVERTIME_POLICY", leave_type_id: null, leave_type_name: null, own: null, applied: null },
  ],
};

const liveVersion = {
  id: "v1",
  status: "PUBLISHED",
  version: 2,
  effective_from: "2026-01-01",
  effective_to: null,
  eligibility: "SHIFT_FLAG",
  min_ot_minutes: 30,
  rounding_minutes: 15,
  rounding_mode: "NEAREST",
  requires_pre_approval: false,
  requires_post_approval: true,
  daily_cap_minutes: 240,
  weekly_cap_minutes: null,
  monthly_cap_minutes: null,
  comp_off_instead_of_pay: false,
  comp_off_expiry_days: null,
  comp_off_day_length_minutes: null,
  night_ot_mode: "SHIFT_FLAG",
  night_window_start: null,
  night_window_end: null,
  approval_chain: "MANAGER_THEN_HR",
  rate_rows: [{ id: "r1", day_class: "HOLIDAY", classification_code: "OT_HOLIDAY", multiplier_decimal: "2.0000", sort_order: 0 }],
};

describe("overtime policy pages", () => {
  beforeEach(() => {
    mockedGet.mockImplementation(((path: string) => {
      if (path.startsWith("/policy-assignments/coverage")) return Promise.resolve(coverage);
      if (path === "/overtime-policies") {
        return Promise.resolve([
          { id: "p1", name: "OT standard", code: "OT1", is_active: true, version: 1, live_from: "2026-01-01", assigned_company_wide: true, assigned_group_count: 2 },
        ]);
      }
      if (path.endsWith("/versions")) return Promise.resolve([liveVersion]);
      return Promise.resolve({ id: "p1", name: "OT standard", code: "OT1", is_active: true, version: 1 });
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

  it("lists status and who each policy applies to", async () => {
    render(<ListPage />);
    expect(await screen.findByText("OT standard")).toBeInTheDocument();
    expect(screen.getByText(/Live since/)).toHaveTextContent("01/01/2026");
    expect(screen.getByText("Whole company and 2 groups")).toBeInTheDocument();
  });

  it("describes the live rules in words", async () => {
    render(<DetailPage />);
    expect(await screen.findByText(/Live rules since/)).toBeInTheDocument();
    expect(screen.getByText("Only shifts marked as overtime-eligible")).toBeInTheDocument();
    expect(screen.getByText("Manager approves, then HR, after it is worked")).toBeInTheDocument();
    expect(screen.getByText("30 minutes")).toBeInTheDocument();
    expect(screen.getByText("Holiday: OT_HOLIDAY (×2.0000)")).toBeInTheDocument();
  });

  it("publishes a template with payroll labels in one call", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    expect(screen.getByLabelText(/Policy name/)).toHaveValue("Manager approves overtime");
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByLabelText(/Who follows/)).toHaveValue("COMPANY"));
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockedPost.mock.calls[0] as [string, Record<string, never>];
    expect(path).toBe("/overtime-policies/setup");
    expect(body).toMatchObject({
      publish: true,
      assign: { scope_type: "COMPANY", scope_id: null, expected_version: null },
    });
    expect(body.rules).toMatchObject({ approval_chain: "MANAGER", eligibility: "SHIFT_FLAG" });
    expect((body.rules as unknown as { rate_rows: unknown[] }).rate_rows).toHaveLength(3);
    expect(push).toHaveBeenCalledWith("/app/overtime-policies/new-1");
  });

  it("the no-overtime template switches eligibility off", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    await user.click(screen.getByRole("radio", { name: /Overtime not allowed/ }));
    expect(screen.getByLabelText(/Who can earn overtime/)).toHaveValue("NEVER");
    expect(screen.getByLabelText(/Policy name/)).toHaveValue("No overtime");
  });

  it("only shows extra fields when they apply", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    expect(screen.queryByLabelText(/Days to use a comp-off/)).toBeNull();
    await user.click(screen.getByLabelText(/Give comp-off days/));
    expect(screen.getByLabelText(/Days to use a comp-off/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Round to \(minutes\)/)).toBeNull();
  });

  it("asks for both ends of the night window", async () => {
    const user = userEvent.setup();
    render(<NewPage />);
    await user.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() => expect(mockedPost).toHaveBeenCalled());
    mockedPost.mockClear();

    await user.click(screen.getByText("Advanced settings"));
    await user.selectOptions(screen.getByLabelText(/What counts as night overtime/), "WINDOW");
    await user.type(screen.getByLabelText(/Night starts/), "22:00");
    await user.click(screen.getByRole("button", { name: "Save as draft" }));
    expect(await screen.findByText(/must be given together/)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });
});
