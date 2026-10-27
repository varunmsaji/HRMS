import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/attendance/format", () => ({ businessToday: () => "2026-09-01" }));
vi.mock("@/lib/api/client", () => ({ apiClient: { post: vi.fn() } }));

import { ChangeImpactDialog } from "@/components/work-calendar/change-impact-dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { ImpactPreview, ProposedChange } from "@/lib/work-calendar/change-impact";

const post = vi.mocked(apiClient.post);

const CHANGE: ProposedChange = {
  change_type: "HOLIDAY_CREATE",
  holiday_calendar_id: "hc-1",
  body: { date: "2026-09-09", name: "Founders Day" },
};

function preview(overrides: Partial<ImpactPreview> = {}): ImpactPreview {
  return {
    change_type: "HOLIDAY_CREATE",
    window_from: "2026-09-01",
    window_to: "2027-02-27",
    population: { employees_in_scope: 2, employees_analysed: 2, groups_analysed: 1, complete: true },
    changed_date_count: 1,
    affected_employee_count: 2,
    rows: [
      {
        date: "2026-09-09",
        previous: { configured: true, day_type: "WORKING", label: null, weekly_off_fraction: null },
        proposed: { configured: true, day_type: "HOLIDAY", label: "Founders Day", weekly_off_fraction: null },
        affected_employee_count: 2,
      },
    ],
    rows_truncated: false,
    employee_samples: [],
    excluded_not_employed_employee_dates: 0,
    incomplete_configuration: { employees: 0, dates: 0 },
    leave_impact: {
      approved_day_records: 0,
      pending_day_records: 0,
      applications: 0,
      employees: 0,
      items: [],
      items_truncated: false,
      records_modified: 0,
    },
    protected_periods: [],
    warnings: [],
    requires_acknowledgement: false,
    impact_digest: "a".repeat(64),
    ...overrides,
  };
}

function setup(onApplied = vi.fn(), onClose = vi.fn()) {
  render(<ChangeImpactDialog change={CHANGE} title="Add holiday" onApplied={onApplied} onClose={onClose} />);
  return { onApplied, onClose };
}

beforeEach(() => post.mockReset());

describe("ChangeImpactDialog", () => {
  it("previews the change for the default window and shows previous vs proposed in text", async () => {
    post.mockResolvedValueOnce(preview());
    setup();

    expect(await screen.findByTestId("impact-summary")).toHaveTextContent(
      "2 employees affected on 1 date between 2026-09-01 and 2027-02-27.",
    );
    expect(post).toHaveBeenCalledWith("/work-calendar-changes/preview", {
      change: CHANGE,
      window_from: "2026-09-01",
      window_to: "2027-02-27",
    });
    const table = screen.getByRole("table");
    const row = within(table).getByText(/Wednesday, 9 September 2026/).closest("tr") as HTMLElement;
    expect(within(row).getByText("Working day")).toBeInTheDocument();
    expect(within(row).getByText("Holiday — Founders Day")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm change" })).toBeEnabled();
    expect(post).toHaveBeenCalledTimes(1); // nothing confirmed by merely previewing
  });

  it("confirms with the digest and the previewed window, then reports success", async () => {
    const user = userEvent.setup();
    post.mockResolvedValueOnce(preview());
    const { onApplied } = setup();
    await screen.findByTestId("impact-summary");

    post.mockResolvedValueOnce({ change_type: "HOLIDAY_CREATE", entity_id: "h-1" });
    await user.click(screen.getByRole("button", { name: "Confirm change" }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenLastCalledWith("/work-calendar-changes/confirm", {
      change: CHANGE,
      window_from: "2026-09-01",
      window_to: "2027-02-27",
      impact_digest: "a".repeat(64),
      acknowledge_protected_impact: false,
    });
  });

  it("shows leave and locked-period impact and requires acknowledgement before confirming", async () => {
    const user = userEvent.setup();
    post.mockResolvedValueOnce(
      preview({
        requires_acknowledgement: true,
        leave_impact: {
          approved_day_records: 1,
          pending_day_records: 1,
          applications: 2,
          employees: 1,
          items: [
            {
              application_id: "app-1",
              employee_id: "e-1",
              employee_code: "EMP-001",
              date: "2026-09-09",
              status: "APPROVED",
              previous_day_type: "WORKING",
              proposed_day_type: "HOLIDAY",
            },
          ],
          items_truncated: false,
          records_modified: 0,
        },
        protected_periods: [
          {
            id: "p-1",
            kind: "ATTENDANCE_PERIOD",
            legal_entity_id: "le-1",
            period_start: "2026-09-01",
            period_end: "2026-09-30",
            status: "CLOSED",
            changed_dates_in_period: 1,
          },
          {
            id: "r-1",
            kind: "PAY_RUN",
            legal_entity_id: "le-1",
            period_start: "2026-09-01",
            period_end: "2026-09-30",
            status: "FINALISED",
            changed_dates_in_period: 1,
          },
        ],
      }),
    );
    const { onApplied } = setup();
    await screen.findByTestId("impact-summary");

    expect(screen.getByTestId("leave-impact")).toHaveTextContent("1 approved and 1 pending");
    expect(screen.getByText(/EMP-001/)).toHaveTextContent("Approved leave");
    expect(screen.getByTestId("protected-periods")).toHaveTextContent("Attendance period");
    expect(screen.getByTestId("protected-periods")).toHaveTextContent("Pay run");

    const confirm = screen.getByRole("button", { name: "Confirm change" });
    expect(confirm).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    expect(confirm).toBeEnabled();

    post.mockResolvedValueOnce({});
    await user.click(confirm);
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
    expect(post.mock.calls.at(-1)?.[1]).toMatchObject({ acknowledge_protected_impact: true });
  });

  it("flags a stale preview, applies nothing and offers a refresh", async () => {
    const user = userEvent.setup();
    post.mockResolvedValueOnce(preview());
    const { onApplied } = setup();
    await screen.findByTestId("impact-summary");

    post.mockRejectedValueOnce(
      new ApiError({ status: 409, code: "CALENDAR_PREVIEW_STALE", message: "stale" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm change" }));

    expect(await screen.findByText("This preview is out of date.")).toBeInTheDocument();
    expect(onApplied).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Confirm change" })).toBeDisabled();

    post.mockResolvedValueOnce(preview({ impact_digest: "b".repeat(64) }));
    await user.click(screen.getByRole("button", { name: "Refresh preview" }));
    await waitFor(() => expect(screen.queryByText("This preview is out of date.")).toBeNull());
    expect(screen.getByRole("button", { name: "Confirm change" })).toBeEnabled();
  });

  it("shows validation errors from the preview and does not allow confirmation", async () => {
    post.mockRejectedValueOnce(
      new ApiError({
        status: 422,
        code: "CALENDAR_PREVIEW_INVALID",
        message: "An active holiday already exists on this date in the calendar",
      }),
    );
    setup();
    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists on this date/);
    expect(screen.getByRole("button", { name: "Confirm change" })).toBeDisabled();
  });

  it("states that counts are a lower bound when the population is incomplete", async () => {
    post.mockResolvedValueOnce(
      preview({
        population: { employees_in_scope: 5000, employees_analysed: 5000, groups_analysed: 300, complete: false },
        warnings: [{ code: "POPULATION_INCOMPLETE", message: "Counts are a lower bound." }],
        incomplete_configuration: { employees: 3, dates: 10 },
      }),
    );
    setup();
    expect(await screen.findByTestId("impact-summary")).toHaveTextContent(/^At least 2 employees/);
    expect(screen.getByText(/Counts are a lower bound\./)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Incomplete configuration: 3 employee(s)");
  });

  it("Back closes without confirming anything", async () => {
    const user = userEvent.setup();
    post.mockResolvedValueOnce(preview());
    const { onClose, onApplied } = setup();
    await screen.findByTestId("impact-summary");
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(onClose).toHaveBeenCalled();
    expect(onApplied).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("re-previews when the window changes", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue(preview());
    setup();
    await screen.findByTestId("impact-summary");
    const to = screen.getByLabelText("Preview to");
    await user.clear(to);
    await user.type(to, "2026-12-31");
    await waitFor(() =>
      expect(post).toHaveBeenLastCalledWith("/work-calendar-changes/preview", {
        change: CHANGE,
        window_from: "2026-09-01",
        window_to: "2026-12-31",
      }),
    );
  });
});
