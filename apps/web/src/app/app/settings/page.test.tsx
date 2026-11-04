import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));

import SettingsPage from "@/app/app/settings/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);

function checklist(complete: string[]) {
  const items = [
    ["SHIFT", "Create a shift", true, "/app/shifts"],
    ["WORK_CALENDAR", "Set working days and holidays", true, "/app/work-calendars/setup"],
    ["ATTENDANCE_POLICY", "Set attendance rules for the whole company", true, "/app/attendance-policies/new"],
    ["OVERTIME_POLICY", "Set overtime rules", false, "/app/overtime-policies/new"],
  ].map(([code, label, required, path]) => ({
    code,
    label,
    description: `About ${label}.`,
    required,
    is_complete: complete.includes(code as string),
    path,
  }));
  const open = items.filter((i) => !i.is_complete);
  return {
    items,
    required_total: 3,
    required_complete: items.filter((i) => i.required && i.is_complete).length,
    next_code: (open.find((i) => i.required) ?? open[0])?.code ?? null,
  };
}

describe("Settings page", () => {
  afterEach(() => mockedGet.mockReset());

  it("groups settings by task, with leave extras tucked away", async () => {
    mockedGet.mockResolvedValue(checklist(["SHIFT", "WORK_CALENDAR", "ATTENDANCE_POLICY"]) as never);
    const user = userEvent.setup();
    render(<SettingsPage />);

    for (const heading of ["Company", "Working time", "Attendance rules", "Who follows what"]) {
      expect(screen.getByRole("heading", { name: heading, level: 2 })).toBeInTheDocument();
    }
    const leave = screen.getByRole("heading", { name: "Leave", level: 2 }).closest("section")!;
    expect(within(leave).getByText("Leave Policies")).toBeInTheDocument();
    expect(within(leave).queryByText("Leave Year")).toBeNull();

    await user.click(within(leave).getByRole("button", { name: "Show 3 more" }));
    expect(within(leave).getByText("Leave Year")).toBeInTheDocument();
    expect(within(leave).getByText("Statutory Minimums")).toBeInTheDocument();
  });

  it("finds a tucked-away setting by searching", async () => {
    mockedGet.mockResolvedValue(checklist([]) as never);
    const user = userEvent.setup();
    render(<SettingsPage />);
    await user.type(screen.getByRole("searchbox", { name: "Search settings" }), "statutory");
    expect(screen.getByText("Statutory Minimums")).toBeInTheDocument();
  });

  it("points at the next essential step until the essentials are done", async () => {
    mockedGet.mockResolvedValue(checklist(["SHIFT"]) as never);
    render(<SettingsPage />);
    expect(await screen.findByText(/1 of 3 essentials done/)).toBeInTheDocument();
    expect(screen.getByText(/Next: Set working days and holidays/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Go/ })).toHaveAttribute(
      "href",
      "/app/work-calendars/setup",
    );
  });

  it("stays quiet once the essentials are done, and when the checklist is unavailable", async () => {
    mockedGet.mockResolvedValue(checklist(["SHIFT", "WORK_CALENDAR", "ATTENDANCE_POLICY"]) as never);
    const { unmount } = render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Company", level: 2 });
    expect(screen.queryByText(/essentials done/)).toBeNull();
    unmount();

    mockedGet.mockRejectedValue(new Error("403"));
    render(<SettingsPage />);
    await screen.findByRole("heading", { name: "Company", level: 2 });
    expect(screen.queryByText(/essentials done/)).toBeNull();
  });
});
