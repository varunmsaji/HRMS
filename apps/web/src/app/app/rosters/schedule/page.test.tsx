import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: (p: string) => p === "ATTENDANCE.ROSTER_MANAGE" }),
}));
vi.mock("@/lib/attendance/format", async (orig) => ({
  ...(await orig<typeof import("@/lib/attendance/format")>()),
  businessToday: () => "2026-11-04",
}));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/components/shift-roster/roster-entry-dialog", () => ({ RosterEntryDialog: () => null }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

import ShiftSchedulePage from "@/app/app/rosters/schedule/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

const DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"];

function shift(name: string, counts: number[], min: number | null, night = false) {
  return {
    id: name,
    name,
    code: null,
    start_time: "09:00:00",
    end_time: "18:00:00",
    is_night_shift: night,
    daily_hours: 9,
    weekly_hours: 45,
    min_staff: min,
    peak_staff: Math.max(...counts),
    departments: ["Product", "Finance"],
    days_below_target: min ? counts.filter((c) => c > 0 && c < min).length : 0,
    cells: DAYS.map((date, i) => ({
      date,
      count: counts[i],
      met: min && counts[i] > 0 ? counts[i] >= min : null,
      people: counts[i] > 0 ? [{ id: `${name}-${i}`, name: "Asha Rao", initials: "AR" }] : [],
      has_pending_swap: false,
    })),
  };
}

const SCHEDULE = {
  week_start: "2026-11-02",
  week_end: "2026-11-08",
  days: DAYS,
  shifts: [shift("General Shift", [22, 22, 22, 22, 22, 0, 0], 20), shift("Night Shift", [4, 4, 4, 4, 4, 4, 0], 4, true)],
  totals: {
    active_headcount: 48,
    rostered_staff: 48,
    coverage_pct: 100,
    shifts_with_target: 2,
    cells_below_target: 0,
    night_staff: 4,
    night_shift_count: 1,
    pending_swaps: 1,
    allocated_hours: 2070,
    last_roster_update: null,
  },
};

const SWAP = {
  id: "swap-1",
  reference: "SW-208",
  swap_date: "2026-11-05",
  status: "PENDING",
  reason: "Family travel",
  counterpart_consented: true,
  coverage_ok: true,
  requester: { employee_id: "a", name: "Meera Pillai", code: "EMP-0128", department: "Support", shift_id: "s1", shift_name: "Evening", shift_start: "14:00:00", shift_end: "22:30:00" },
  counterpart: { employee_id: "b", name: "Devendra Patil", code: "EMP-0074", department: "Operations", shift_id: "s2", shift_name: "General", shift_start: "09:00:00", shift_end: "18:00:00" },
  created_at: "2026-11-03T10:00:00Z",
  decided_at: null,
  decision_note: null,
};

function serve() {
  mockedGet.mockImplementation(((path: string) => {
    if (path.startsWith("/rosters/weekly-schedule")) return Promise.resolve(SCHEDULE);
    if (path.startsWith("/rosters/swap-requests")) return Promise.resolve([SWAP]);
    if (path === "/branches") return Promise.resolve([{ id: "b1", name: "HQ" }]);
    if (path === "/departments") return Promise.resolve([{ id: "d1", name: "Product" }]);
    return Promise.reject(new Error(`Unexpected ${path}`));
  }) as never);
}

afterEach(() => vi.clearAllMocks());

describe("Shift schedule page", () => {
  it("renders the KPIs, the weekly schedule and the pending swaps from the API", async () => {
    serve();
    render(<ShiftSchedulePage />);
    expect(await screen.findByText("Weekly Operational Schedule")).toBeInTheDocument();
    expect(screen.getByText("48 of 48 active headcount assigned")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("General Shift")).toBeInTheDocument();
    // five weekday cells plus the shift header badge showing the peak headcount
    expect(screen.getAllByText("22 Staff").length).toBe(6);
    expect(screen.getByText("TODAY")).toBeInTheDocument();
    expect(screen.getByText("Swap Request #SW-208")).toBeInTheDocument();
    expect(screen.getByText(/Mutual consent verified/)).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith(
      expect.stringContaining("week_start=2026-11-02"),
      expect.anything(),
    );
  });

  it("approves a swap and reloads", async () => {
    serve();
    mockedPost.mockResolvedValue(SWAP as never);
    render(<ShiftSchedulePage />);
    await userEvent.click(await screen.findByRole("button", { name: /approve swap/i }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/rosters/swap-requests/swap-1/approve", {}),
    );
  });

  it("moves to the next week", async () => {
    serve();
    render(<ShiftSchedulePage />);
    await userEvent.click(await screen.findByRole("button", { name: "Next week" }));
    await waitFor(() =>
      expect(mockedGet).toHaveBeenCalledWith(
        expect.stringContaining("week_start=2026-11-09"),
        expect.anything(),
      ),
    );
  });
});
