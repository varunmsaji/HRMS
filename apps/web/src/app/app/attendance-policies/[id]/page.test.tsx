import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "p1" }) }));
vi.mock("@/lib/auth/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/dates/use-company-date", () => ({ useCompanyDatePattern: () => "dd/MM/yyyy" }));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import AttendancePolicyDetailPage from "@/app/app/attendance-policies/[id]/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);
const mockedPatch = vi.mocked(apiClient.patch);
const mockedPost = vi.mocked(apiClient.post);

const version = {
  company_id: "c1",
  policy_id: "p1",
  effective_to: null,
  grace_in_minutes: 5,
  grace_out_minutes: 0,
  early_in_allowance_minutes: null,
  punch_rounding: "NONE",
  rounding_minutes: null,
  missing_punch_behaviour: "INCOMPLETE",
  auto_close_after_minutes: null,
  auto_close_uses_shift_end: true,
  missing_shift_behaviour: "INCOMPLETE",
  half_day_split: "BY_HOURS",
  half_day_boundary_minutes: null,
  multi_punch_mode: "PAIR_ALL",
  duplicate_punch_window_seconds: 60,
  core_hours_breach_behaviour: "FLAG",
  early_out_uses_core_end: false,
  split_shift_block_mandatory: true,
  split_shift_missed_block_behaviour: "HALF_DAY",
  split_shift_allow_hours_compensation: false,
  wfh_requires_punch: true,
  on_duty_requires_punch: false,
  wfh_uses_shift_hours: true,
  work_on_leave_behaviour: "KEEP_LEAVE",
  excess_break_behaviour: "FLAG",
  lates_to_half_day_count: 3,
  excess_break_days_to_half_day_count: null,
  early_departure_requires_approval: false,
  incomplete_at_lock_behaviour: "TREAT_ABSENT",
  geofence_mode: "DISABLED",
  geofence_max_accuracy_m: 100,
  geofence_max_age_seconds: 60,
  hour_bands: [{ id: "b1", min_minutes: 480, max_minutes: null, result_status: "PRESENT", sort_order: 0 }],
  late_bands: [],
  early_departure_bands: [],
};

const live = { ...version, id: "v1", status: "PUBLISHED", version: 4, effective_from: "2026-01-01" };
const draft = { ...version, id: "v2", status: "DRAFT", version: 2, effective_from: "2027-06-01" };

function serve(versions: unknown[], shiftTypes: string[] = ["FIXED"]) {
  mockedGet.mockImplementation(((path: string) => {
    if (path === "/attendance-policies/form-context") {
      return Promise.resolve({ shift_types_in_use: shiftTypes });
    }
    if (path.endsWith("/versions")) return Promise.resolve(versions);
    if (path.startsWith("/policy-assignments/coverage")) {
      return Promise.resolve({
        scope_type: "COMPANY",
        scope_id: null,
        as_of: "2026-06-01",
        rows: [
          {
            policy_kind: "ATTENDANCE_POLICY",
            leave_type_id: null,
            leave_type_name: null,
            own: { assignment_id: "a1", policy_id: "p1", policy_name: "Office", effective_from: "2026-01-01", version: 1 },
            applied: null,
          },
        ],
      });
    }
    return Promise.resolve({ id: "p1", name: "Office", code: "AP1", is_active: true, version: 1 });
  }) as never);
  mockedGetList.mockResolvedValue({ data: [], pagination: { page: 1, per_page: 100, total: 0, total_pages: 0, has_next: false, has_prev: false } } as never);
}

describe("attendance policy detail", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
    mockedPatch.mockReset();
    mockedPost.mockReset();
  });

  it("shows the live rules in words without opening an editor", async () => {
    serve([live]);
    render(<AttendancePolicyDetailPage />);
    expect(await screen.findByText(/Live rules since/)).toBeInTheDocument();
    expect(screen.getByText("8 hours or more: Present")).toBeInTheDocument();
    expect(screen.getByText("5 minutes late, 0 minutes early")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Late arrival grace/)).toBeNull();
  });

  it("publishes edits with one flow: saves, then publishes the saved version", async () => {
    serve([live]);
    mockedPost.mockImplementation(((path: string) =>
      Promise.resolve(path.endsWith("/versions") ? { ...draft, id: "v3", version: 1 } : {})) as never);
    const user = userEvent.setup();
    render(<AttendancePolicyDetailPage />);
    await user.click(await screen.findByRole("button", { name: "Edit rules" }));

    const grace = screen.getByLabelText(/Late arrival grace/);
    await user.clear(grace);
    await user.type(grace, "15");
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));

    const dialog = await screen.findByRole("dialog");
    const date = within(dialog).getByLabelText(/Rules start on/);
    await user.clear(date);
    await user.type(date, "2027-02-01");
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/attendance-policies/p1/versions/v3/publish",
        { publish_reason: null, expected_previous_version: 4 },
        { ifMatch: "1" },
      ),
    );
    const created = mockedPost.mock.calls.find(([path]) => path === "/attendance-policies/p1/versions");
    expect(created?.[1]).toMatchObject({ grace_in_minutes: 15, effective_from: "2027-02-01" });
  });

  it("refuses a start date that is not after the live rules' start", async () => {
    serve([live]);
    const user = userEvent.setup();
    render(<AttendancePolicyDetailPage />);
    await user.click(await screen.findByRole("button", { name: "Edit rules" }));
    await user.click(screen.getByRole("button", { name: /Save & publish/ }));
    const dialog = await screen.findByRole("dialog");
    const date = within(dialog).getByLabelText(/Rules start on/);
    await user.clear(date);
    await user.type(date, "2026-01-01");
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    expect(await within(dialog).findByText(/Must be after 01\/01\/2026/)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("stops at the form when saving fails, with nothing published", async () => {
    serve([draft]);
    mockedPatch.mockRejectedValue(new Error("nope"));
    const user = userEvent.setup();
    render(<AttendancePolicyDetailPage />);
    await user.click(await screen.findByRole("button", { name: "Publish…" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(mockedPatch).toHaveBeenCalled());
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it("publishes a saved draft from the banner without touching the name", async () => {
    serve([draft]);
    mockedPatch.mockResolvedValue({ ...draft, version: 3 } as never);
    mockedPost.mockResolvedValue({} as never);
    const user = userEvent.setup();
    render(<AttendancePolicyDetailPage />);
    await user.click(await screen.findByRole("button", { name: "Publish…" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Rules start on/)).toHaveValue("2027-06-01");
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith(
        "/attendance-policies/p1/versions/v2/publish",
        { publish_reason: null },
        { ifMatch: "3" },
      ),
    );
    expect(mockedPatch).toHaveBeenCalledTimes(1);
    expect(mockedPatch.mock.calls[0][0]).toBe("/attendance-policies/p1/versions/v2");
  });

  it("does not offer a draft's rules on the screen as if they were live", async () => {
    serve([draft]);
    render(<AttendancePolicyDetailPage />);
    expect(await screen.findByText("No live rules today")).toBeInTheDocument();
    expect(screen.getByText(/unpublished draft/)).toBeInTheDocument();
  });

  it("keeps today's rules as live when newer rules start later", async () => {
    const closed = { ...live, effective_to: "2099-12-31" };
    const later = { ...live, id: "v5", effective_from: "2100-01-01", grace_in_minutes: 25 };
    serve([closed, later]);
    render(<AttendancePolicyDetailPage />);
    expect(await screen.findByText(/Live rules since/)).toHaveTextContent("01/01/2026");
    expect(screen.getByText(/New rules from/)).toHaveTextContent("01/01/2100");
    expect(screen.getByText("5 minutes late, 0 minutes early")).toBeInTheDocument();
    expect(screen.getByText("25 minutes late, 0 minutes early")).toBeInTheDocument();
  });

  it("does not claim rules are live before their first start date", async () => {
    serve([{ ...live, effective_from: "2100-01-01" }]);
    render(<AttendancePolicyDetailPage />);
    expect(await screen.findByText("No live rules today")).toBeInTheDocument();
    expect(screen.getByText(/New rules from/)).toBeInTheDocument();
  });

  it("hides shift-type settings the company cannot use", async () => {
    serve([live], ["FIXED"]);
    const user = userEvent.setup();
    render(<AttendancePolicyDetailPage />);
    await user.click(await screen.findByRole("button", { name: "Edit rules" }));
    expect(screen.queryByLabelText(/Flexible shifts/)).toBeNull();
    expect(screen.queryByLabelText(/Split shifts/)).toBeNull();
  });

  it("shows shift-type settings when such shifts exist", async () => {
    serve([live], ["FIXED", "FLEXIBLE", "SPLIT"]);
    const user = userEvent.setup();
    render(<AttendancePolicyDetailPage />);
    await user.click(await screen.findByRole("button", { name: "Edit rules" }));
    await screen.findByLabelText(/Flexible shifts/);
    expect(screen.getByLabelText(/Split shifts/)).toBeInTheDocument();
  });
});
