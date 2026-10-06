import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ employeeId: "emp-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "UTC", permissions: ["ATTENDANCE.VIEW_ALL"] } }),
}));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() },
}));

import EmployeeAttendanceProfilePage from "@/app/app/attendance/employee/[employeeId]/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { makeAbsentDay, makeDay } from "@/lib/attendance/__fixtures__/day";
import { businessToday } from "@/lib/attendance/format";

const mockedGet = vi.mocked(apiClient.get);
const TODAY = businessToday("UTC");
const MONTH = TODAY.slice(0, 7);

function mockApi(opts: { days?: unknown[] | Error; employee?: unknown | Error } = {}) {
  mockedGet.mockImplementation((path: string) => {
    if (path.startsWith("/employees/")) {
      return opts.employee instanceof Error
        ? Promise.reject(opts.employee)
        : Promise.resolve(opts.employee ?? { id: "emp-1", first_name: "Asha", last_name: "Rao", employee_code: "EMP-001" });
    }
    if (path.startsWith("/attendance/days?")) {
      return opts.days instanceof Error ? Promise.reject(opts.days) : Promise.resolve(opts.days ?? []);
    }
    if (path.startsWith("/attendance/punches?")) {
      return Promise.resolve([{ id: "p1", direction: "IN", punch_time: `${TODAY}T09:00:00Z` }]);
    }
    if (path.startsWith("/regularizations?")) {
      return Promise.resolve([
        { id: "r1", attendance_date: `${MONTH}-02`, request_type: "MISSED_PUNCH", status: "SUBMITTED" },
      ]);
    }
    return Promise.reject(new Error(`Unexpected GET ${path}`));
  });
}

describe("EmployeeAttendanceProfilePage", () => {
  afterEach(() => {
    cleanup();
    mockedGet.mockReset();
  });

  it("shows identity, today's punches, the month summary, calendar, issues and regularizations", async () => {
    mockApi({
      days: [
        makeDay({ employee_id: "emp-1", attendance_date: TODAY, id: "d-today", actual_last_out: null, is_late: true }),
        makeAbsentDay({ employee_id: "emp-1", attendance_date: `${MONTH}-01`, id: "d-1", missing_punch: true }),
      ],
    });
    render(<EmployeeAttendanceProfilePage />);

    expect(await screen.findByRole("heading", { name: "Asha Rao" })).toBeInTheDocument();
    expect(screen.getByText("Employee ID EMP-001")).toBeInTheDocument();
    expect(await screen.findByRole("list", { name: /today's punches/i })).toHaveTextContent("IN");
    expect(screen.getByText("Working")).toBeInTheDocument();

    const month = (await screen.findByRole("heading", { name: "Month" })).closest("[id='att-profile-month']") as HTMLElement;
    expect(within(month).getByText("Late arrivals").nextSibling).toHaveTextContent("1");
    expect(within(month).getByRole("grid", { name: new RegExp(`calendar for ${MONTH}`, "i") })).toBeInTheDocument();
    expect(within(month).getByText("Missing punch")).toBeInTheDocument();
    expect(await within(month).findByText("Submitted")).toBeInTheDocument();
  });

  it("still shows attendance when the employee record can't be read", async () => {
    mockApi({
      days: [makeDay({ employee_id: "emp-1", attendance_date: TODAY })],
      employee: new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "no" }),
    });
    render(<EmployeeAttendanceProfilePage />);
    expect(await screen.findByRole("heading", { name: /employee emp-1/i })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Month" })).toBeInTheDocument();
  });

  it("shows a retryable error — not the raw backend message — when attendance fails", async () => {
    mockApi({ days: new ApiError({ status: 500, code: "BOOM", message: "traceback..." }) });
    render(<EmployeeAttendanceProfilePage />);
    expect((await screen.findAllByText(/failed to load/i)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/traceback/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /try again/i }).length).toBeGreaterThan(0);
  });

  it("reloads the month's days when the month changes", async () => {
    mockApi({ days: [] });
    render(<EmployeeAttendanceProfilePage />);
    const input = await screen.findByLabelText("Month", { selector: "input" });
    fireEvent.change(input, { target: { value: "2026-01" } });
    await waitFor(() => {
      const calls = mockedGet.mock.calls.map((c) => c[0]).filter((p) => p.startsWith("/attendance/days?"));
      expect(calls.some((p) => p.includes("date_from=2026-01-01") && p.includes("date_to=2026-01-31"))).toBe(true);
    });
  });
});
