import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let granted: string[] = [];

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/attendance/format", async (orig) => ({
  ...(await orig<typeof import("@/lib/attendance/format")>()),
  businessToday: () => "2026-10-26",
}));
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: (code: string) => granted.includes(code) }),
}));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), getList: vi.fn() } }));

import AttendanceCalendarPage from "@/app/app/attendance/calendar/page";
import { apiClient } from "@/lib/api/client";

const mockedGetList = vi.mocked(apiClient.getList);

afterEach(() => {
  vi.clearAllMocks();
  granted = [];
});

describe("AttendanceCalendarPage permissions", () => {
  it.each([
    ["the attendance read", ["ATTENDANCE.VIEW_ALL", "EMPLOYEE.VIEW_ALL"]],
    ["the employee directory read", ["ATTENDANCE.VIEW_ALL", "ATTENDANCE.VIEW"]],
  ])("does not load the month for a role without %s", (_label, codes) => {
    granted = codes;
    render(<AttendanceCalendarPage />);
    expect(screen.getByText(/available to people who can view everyone's attendance/)).toBeInTheDocument();
    expect(mockedGetList).not.toHaveBeenCalled();
  });

  it("loads days and employees when the role has all three grants", () => {
    granted = ["ATTENDANCE.VIEW_ALL", "ATTENDANCE.VIEW", "EMPLOYEE.VIEW_ALL"];
    mockedGetList.mockReturnValue(new Promise(() => {}) as never);
    render(<AttendanceCalendarPage />);
    const paths = mockedGetList.mock.calls.map((c) => c[0]);
    expect(paths).toContain("/attendance/days");
    expect(paths).toContain("/employees");
  });
});
