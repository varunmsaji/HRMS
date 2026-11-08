import { render, screen, waitFor, within } from "@testing-library/react";
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

  it("shows one card per area, each with its setup progress", async () => {
    mockedGet.mockResolvedValue(checklist(["SHIFT", "WORK_CALENDAR"]) as never);
    render(<SettingsPage />);

    const attendance = screen.getByRole("link", { name: /^Attendance/ });
    expect(attendance).toHaveAttribute("href", "/app/settings/attendance");
    expect(await within(attendance).findByText("2 of 4 setup steps done")).toBeInTheDocument();
    for (const name of [/^Company & structure/, /^Leave/, /^Payroll/, /^Access & setup/]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    // Rarely needed screens aren't named on the card.
    expect(screen.getByRole("link", { name: /^Leave/ })).not.toHaveTextContent("Leave Year");
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
    await screen.findByText("3 of 4 setup steps done");
    expect(screen.queryByText(/essentials done/)).toBeNull();
    unmount();

    mockedGet.mockRejectedValue(new Error("403"));
    render(<SettingsPage />);
    await waitFor(() => expect(mockedGet).toHaveBeenCalled());
    expect(screen.getByRole("link", { name: /^Attendance/ })).toBeInTheDocument();
    expect(screen.queryByText(/essentials done/)).toBeNull();
  });
});
