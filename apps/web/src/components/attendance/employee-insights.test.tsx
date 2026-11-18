import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "UTC" } }),
}));

import { EmployeeInsights } from "@/components/attendance/employee-insights";
import { apiClient } from "@/lib/api/client";
import { makeDay } from "@/lib/attendance/__fixtures__/day";

const mockedGet = vi.mocked(apiClient.get);

const NOW = new Date("2026-08-10T10:00:00Z");

function route(opts: { punches?: unknown[]; days?: unknown[]; reject?: { status: number } } = {}) {
  mockedGet.mockImplementation(async (url: string) => {
    if (opts.reject) throw Object.assign(new Error("x"), opts.reject);
    if (url.startsWith("/attendance/punches")) return (opts.punches ?? []) as never;
    const m = /date_from=(\S+)&date_to=(\S+)/.exec(url)!;
    const all = (opts.days ?? []) as ReturnType<typeof makeDay>[];
    return all.filter((d) => d.attendance_date >= m[1] && d.attendance_date <= m[2]) as never;
  });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  mockedGet.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("EmployeeInsights", () => {
  it("shows the live status, the month tiles and the calendar", async () => {
    route({
      days: [
        makeDay({ attendance_date: "2026-08-10", actual_last_out: null }),
        makeDay({ attendance_date: "2026-08-07", is_late: true, late_minutes: 15 }),
        makeDay({ attendance_date: "2026-08-06", attendance_status: "ABSENT", actual_first_in: null }),
      ],
      punches: [
        {
          id: "p1",
          company_id: "c",
          employee_id: "emp-1",
          punch_time: "2026-08-10T09:00:00Z",
          direction: "IN",
          source: "WEB",
          idempotency_key: null,
          recorded_by_user_id: null,
          reference: null,
          created_at: "2026-08-10T09:00:00Z",
        },
      ],
    });
    render(<EmployeeInsights employeeId="emp-1" shiftName="General" />);

    expect(await screen.findByTestId("today-state")).toHaveTextContent("Working");
    expect(screen.getByText(/In since/)).toBeInTheDocument();
    expect(screen.getByText("General")).toBeInTheDocument();

    expect(await screen.findByText("Days worked")).toBeInTheDocument();
    expect(screen.getByText("of 3 working days")).toBeInTheDocument();
    expect(screen.getByRole("grid", { name: /Attendance for August 2026/ })).toBeInTheDocument();
    expect(screen.getByRole("gridcell", { name: "2026-08-06, Absent" })).toBeInTheDocument();
  });

  it("opens a day's details when its cell is clicked", async () => {
    route({ days: [makeDay({ attendance_date: "2026-08-07", is_late: true, late_minutes: 15 })] });
    render(<EmployeeInsights employeeId="emp-1" shiftName={null} />);

    await userEvent.click(await screen.findByRole("gridcell", { name: "2026-08-07, Present" }));
    const detail = await screen.findByTestId("day-detail");
    expect(detail).toHaveTextContent("Friday, August 7");
    expect(detail).toHaveTextContent("0h 15m");
    expect(screen.getByRole("link", { name: "Open the full day" })).toHaveAttribute(
      "href",
      "/app/attendance/day-emp-1-2026-08-07",
    );

    await userEvent.click(screen.getByRole("gridcell", { name: "2026-08-20, upcoming" }));
    expect(screen.getByTestId("day-detail")).toHaveTextContent("has not happened yet");
  });

  it("moves between months but not past the current one", async () => {
    route({ days: [makeDay({ attendance_date: "2026-07-15" })] });
    render(<EmployeeInsights employeeId="emp-1" shiftName={null} />);

    expect(await screen.findByRole("button", { name: "Next month" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(await screen.findByRole("grid", { name: /July 2026/ })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("gridcell", { name: "2026-07-15, Present" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Next month" })).toBeEnabled();
  });

  it("renders nothing when the viewer may not see this employee's attendance", async () => {
    route({ reject: { status: 403 } });
    const { container } = render(<EmployeeInsights employeeId="emp-1" shiftName={null} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("says so when the figures cannot be loaded", async () => {
    route({ reject: { status: 500 } });
    render(<EmployeeInsights employeeId="emp-1" shiftName={null} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
  });
});
