import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

let authUser: Record<string, unknown> = {};
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ session: { companyId: "company-1", accessToken: "token" }, user: authUser }),
}));

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

// Pin "today" so the initial month is deterministic.
vi.mock("@/lib/attendance/format", () => ({ businessToday: () => "2026-09-10" }));

import MyCalendarPage from "@/app/app/me/calendar/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { gridRangeForMonth, weeksBetween } from "@/lib/employee-calendar/month";
import type { EmployeeCalendar, EmployeeCalendarDay } from "@/lib/employee-calendar/types";

const mockedGet = vi.mocked(apiClient.get);

function day(date: string, overrides: Partial<EmployeeCalendarDay> = {}): EmployeeCalendarDay {
  return {
    date,
    configured: true,
    day_type: "WORKING",
    holiday_name: null,
    holiday_type: null,
    holiday_on_weekly_off: false,
    is_holiday_named: false,
    optional_holiday_name: null,
    restricted_holiday_name: null,
    exception_type: null,
    weekly_off_fraction: null,
    leave: [],
    ...overrides,
  };
}

/** A full server-shaped response for the month grid of `month`, with per-date overrides. */
function calendarFor(
  month: string,
  overrides: Record<string, Partial<EmployeeCalendarDay>> = {},
  extra: Partial<EmployeeCalendar> = {},
): EmployeeCalendar {
  const { from, to } = gridRangeForMonth(month);
  const days = weeksBetween(from, to)
    .flat()
    .map((date) => {
      const weekday = new Date(`${date}T00:00:00Z`).getUTCDay();
      const base = weekday === 0 ? { day_type: "WEEKLY_OFF" as const } : {};
      return day(date, { ...base, ...overrides[date] });
    });
  return { from_date: from, to_date: to, configuration: "COMPLETE", leave_included: true, days, ...extra };
}

beforeEach(() => {
  mockedGet.mockReset();
  authUser = { employee_id: "emp-1", company_timezone: "Asia/Kolkata" };
});

describe("My Calendar page", () => {
  it("requests the visible month grid and renders each day type with text labels", async () => {
    mockedGet.mockResolvedValue(
      calendarFor("2026-09", {
        "2026-09-09": { day_type: "HOLIDAY", holiday_name: "Founders Day", holiday_type: "COMPANY" },
        "2026-09-14": { day_type: "SHUTDOWN", holiday_name: "Plant shutdown", exception_type: "SHUTDOWN" },
      }),
    );
    render(<MyCalendarPage />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading your calendar");
    await screen.findByRole("table");

    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(mockedGet).toHaveBeenCalledWith("/employee-calendar/me?from=2026-08-31&to=2026-10-04");

    const holiday = document.querySelector('[data-date="2026-09-09"]') as HTMLElement;
    expect(holiday).toHaveAttribute("data-day-kind", "HOLIDAY");
    expect(within(holiday).getAllByText(/Founders Day/).length).toBeGreaterThan(0);
    expect(document.querySelector('[data-date="2026-09-06"]')).toHaveAttribute("data-day-kind", "WEEKLY_OFF");
    expect(document.querySelector('[data-date="2026-09-14"]')).toHaveAttribute("data-day-kind", "SHUTDOWN");
    expect(document.querySelector('[data-date="2026-09-08"]')).toHaveAttribute("data-day-kind", "WORKING");

    // Today is marked in text, not just colour, and exposed to assistive tech.
    const today = document.querySelector('[data-date="2026-09-10"]') as HTMLElement;
    expect(today).toHaveAttribute("aria-current", "date");
    expect(within(today).getByText("Today")).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "September 2026" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("Pending leave");
    // The employee view carries no administration actions.
    expect(screen.queryByRole("link", { name: /manage|edit|configure/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /edit|save|delete|configure/i })).toBeNull();
  });

  it("navigates to the next and previous month with the matching date range", async () => {
    const user = userEvent.setup();
    mockedGet.mockImplementation(async (path: string) => {
      // Recover the month being shown from the first grid day requested.
      const month = path.includes("from=2026-08-31") ? "2026-09" : path.includes("from=2026-09-28") ? "2026-10" : "2026-08";
      return calendarFor(month);
    });
    render(<MyCalendarPage />);
    await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: "Next month" }));
    await screen.findByRole("heading", { name: "October 2026" });
    await waitFor(() =>
      expect(mockedGet).toHaveBeenLastCalledWith("/employee-calendar/me?from=2026-09-28&to=2026-11-01"),
    );

    await user.click(screen.getByRole("button", { name: "Previous month" }));
    await user.click(screen.getByRole("button", { name: "Previous month" }));
    await screen.findByRole("heading", { name: "August 2026" });
    await waitFor(() =>
      expect(mockedGet).toHaveBeenLastCalledWith("/employee-calendar/me?from=2026-07-27&to=2026-09-06"),
    );

    await user.click(screen.getByRole("button", { name: "This month" }));
    await screen.findByRole("heading", { name: "September 2026" });
  });

  it("distinguishes approved, pending and half-day leave by text and glyph", async () => {
    mockedGet.mockResolvedValue(
      calendarFor("2026-09", {
        "2026-09-08": { leave: [{ status: "APPROVED", fraction: "1.00", half: null }] },
        "2026-09-09": { leave: [{ status: "APPROVED", fraction: "0.50", half: "FIRST_HALF" }] },
        "2026-09-15": { leave: [{ status: "PENDING", fraction: "1.00", half: null }] },
      }),
    );
    render(<MyCalendarPage />);
    await screen.findByRole("table");

    const approved = document.querySelector('[data-date="2026-09-08"]') as HTMLElement;
    expect(within(approved).getAllByText(/Approved leave/).length).toBeGreaterThan(0);
    const half = document.querySelector('[data-date="2026-09-09"]') as HTMLElement;
    expect(within(half).getAllByText(/Approved leave \(first half\)/).length).toBeGreaterThan(0);
    const pending = document.querySelector('[data-date="2026-09-15"]') as HTMLElement;
    expect(within(pending).getAllByText(/Pending leave/).length).toBeGreaterThan(0);
    expect(within(pending).queryByText(/Approved/)).toBeNull();
    // Screen-reader text names the full date and the leave state.
    expect(pending).toHaveTextContent("Tuesday, 15 September 2026");

    expect(screen.getByTestId("month-summary")).toHaveTextContent("2 approved leave days");
    expect(screen.getByTestId("month-summary")).toHaveTextContent("1 pending leave day");
  });

  it("shows the incomplete-configuration state instead of working days", async () => {
    mockedGet.mockResolvedValue(
      calendarFor("2026-09", {}, { configuration: "INCOMPLETE" }),
    );
    render(<MyCalendarPage />);
    expect(await screen.findByText("Your work calendar is not set up yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("flags partially configured months and marks unresolved dates", async () => {
    mockedGet.mockResolvedValue(
      calendarFor(
        "2026-09",
        { "2026-09-02": { configured: false, day_type: null } },
        { configuration: "PARTIAL" },
      ),
    );
    render(<MyCalendarPage />);
    await screen.findByRole("table");
    expect(screen.getByText(/applies to you only for part of this month/)).toBeInTheDocument();
    const unresolved = document.querySelector('[data-date="2026-09-02"]') as HTMLElement;
    expect(unresolved).toHaveAttribute("data-day-kind", "UNCONFIGURED");
    expect(within(unresolved).getByText("Not set up")).toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    const user = userEvent.setup();
    mockedGet.mockRejectedValueOnce(new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Boom" }));
    mockedGet.mockResolvedValueOnce(calendarFor("2026-09"));
    render(<MyCalendarPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("table");
    expect(mockedGet).toHaveBeenCalledTimes(2);
  });

  it("shows an empty state, without calling the API, when the account has no employee record", () => {
    authUser = { employee_id: null, company_timezone: "Asia/Kolkata" };
    render(<MyCalendarPage />);
    expect(screen.getByText("No employee record")).toBeInTheDocument();
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("notes when leave is not available for the account", async () => {
    mockedGet.mockResolvedValue(calendarFor("2026-09", {}, { leave_included: false }));
    render(<MyCalendarPage />);
    await screen.findByRole("table");
    expect(screen.getByText("Leave is not shown for your account.")).toBeInTheDocument();
  });

  it("renders the same dates regardless of the viewer's timezone", async () => {
    const original = process.env.TZ;
    try {
      process.env.TZ = "Pacific/Kiritimati"; // UTC+14: local midnight is the previous UTC day
      mockedGet.mockResolvedValue(
        calendarFor("2026-09", { "2026-09-09": { day_type: "HOLIDAY", holiday_name: "Founders Day" } }),
      );
      render(<MyCalendarPage />);
      await screen.findByRole("table");
      const cell = document.querySelector('[data-date="2026-09-09"]') as HTMLElement;
      expect(cell).toHaveTextContent("Wednesday, 9 September 2026");
      expect(cell).toHaveAttribute("data-day-kind", "HOLIDAY");
      expect(mockedGet).toHaveBeenCalledWith("/employee-calendar/me?from=2026-08-31&to=2026-10-04");
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });
});
