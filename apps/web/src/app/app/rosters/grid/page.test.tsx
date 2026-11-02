import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { company_timezone: "Asia/Kolkata" } }),
}));
vi.mock("@/lib/attendance/format", async (orig) => ({
  ...(await orig<typeof import("@/lib/attendance/format")>()),
  businessToday: () => "2026-10-26", // a Monday
}));
vi.mock("@/lib/auth/use-permissions", () => ({
  usePermissions: () => ({ can: () => true }),
}));
vi.mock("@/components/shift-roster/roster-entry-dialog", () => ({
  RosterEntryDialog: (p: { open: boolean; employeeId?: string; rosterDate?: string; roster?: { id: string } | null }) =>
    p.open ? (
      <div role="dialog">
        dialog:{p.employeeId}:{p.rosterDate}:{p.roster?.id ?? "new"}
      </div>
    ) : null,
}));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), getList: vi.fn() } }));

import RosterGridPage from "@/app/app/rosters/grid/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);

const EMPLOYEES = Array.from({ length: 120 }, (_, i) => ({
  id: `emp-${i + 1}`,
  first_name: `Person${String(i + 1).padStart(3, "0")}`,
  last_name: null,
  employee_code: `E${i + 1}`,
}));

function entry(n: number, employeeId: string, shiftId: string) {
  return {
    id: `r-${n}`,
    employee_id: employeeId,
    roster_date: "2026-10-26",
    shift_id: shiftId,
    is_week_off_override: false,
    is_holiday_working_override: false,
    status: "PUBLISHED",
  };
}

/** `entriesTotal` roster rows in the range, served in pages of `per_page`. Row #n belongs to a
 * filler employee (not on any visible page) except the explicitly placed ones. */
function serve({
  entriesTotal,
  placed,
}: {
  entriesTotal: number;
  placed: Record<number, [string, string]>;
}) {
  mockedGet.mockImplementation(((path: string) => {
    if (path === "/shifts") return Promise.resolve([{ id: "s-night", name: "Night", code: "NGT" }]);
    return Promise.reject(new Error(`Unexpected ${path}`));
  }) as never);
  mockedGetList.mockImplementation(((path: string, q: { page: number; per_page: number }) => {
    if (path === "/employees") {
      return Promise.resolve({
        data: EMPLOYEES.slice((q.page - 1) * q.per_page, q.page * q.per_page),
        pagination: { page: q.page, per_page: q.per_page, total: 120, total_pages: Math.ceil(120 / q.per_page) },
        meta: { request_id: "r" },
      });
    }
    if (path === "/rosters") {
      const start = (q.page - 1) * q.per_page;
      const end = Math.min(start + q.per_page, entriesTotal);
      const data = [];
      for (let n = start + 1; n <= end; n++) {
        const [emp, shift] = placed[n] ?? [`filler-${n}`, "s-night"];
        data.push(entry(n, emp, shift));
      }
      return Promise.resolve({
        data,
        pagination: { page: q.page, per_page: q.per_page, total: entriesTotal, total_pages: Math.ceil(entriesTotal / q.per_page) },
        meta: { request_id: "r" },
      });
    }
    return Promise.reject(new Error(`Unexpected ${path}`));
  }) as never);
}

describe("RosterGridPage with datasets beyond the old limits", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
  });

  it("shows a roster entry that sits beyond the first 500 (page 3 of the roster API)", async () => {
    // 1,200 entries => 3 server pages of 500. Entry #1100 (page 3) belongs to emp-2 on screen.
    serve({ entriesTotal: 1200, placed: { 1100: ["emp-2", "s-night"] } });
    render(<RosterGridPage />);

    await screen.findByText(/Person002/);
    expect(await within(await screen.findByRole("table")).findByText("NGT")).toBeInTheDocument();
    const rosterPages = mockedGetList.mock.calls
      .filter((c) => c[0] === "/rosters")
      .map((c) => (c[1] as { page: number }).page)
      .sort();
    expect(rosterPages).toEqual([1, 2, 3]);
    // Nothing was dropped, so there is no truncation warning.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reaches employees beyond the first 100 by paging the employee rows", async () => {
    serve({ entriesTotal: 3, placed: { 1: ["emp-120", "s-night"] } });
    const user = userEvent.setup();
    render(<RosterGridPage />);

    await screen.findByText(/Person001/);
    expect(screen.queryByText(/Person120/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await waitFor(() => expect(screen.getByText(/Person051/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    expect(await screen.findByText(/Person120/)).toBeInTheDocument();
    expect(await within(await screen.findByRole("table")).findByText("NGT")).toBeInTheDocument();
  });

  it("warns instead of silently truncating when the range exceeds the safety bound", async () => {
    serve({ entriesTotal: 6000, placed: {} });
    render(<RosterGridPage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/first 5,000 of 6,000/);
    // Only the bounded number of pages was pulled into memory.
    const pages = mockedGetList.mock.calls.filter((c) => c[0] === "/rosters").length;
    expect(pages).toBe(10);
  });

  it("filters only the current page of employees and says so", async () => {
    serve({ entriesTotal: 0, placed: {} });
    render(<RosterGridPage />);
    await screen.findByText(/Person001/);
    expect(screen.getByText(/searches the employees shown below/i)).toBeInTheDocument();
  });

  it("opens the entry dialog from a filled cell (edit) and from a blank cell (add)", async () => {
    serve({ entriesTotal: 1, placed: { 1: ["emp-1", "s-night"] } });
    const user = userEvent.setup();
    render(<RosterGridPage />);
    const table = await screen.findByRole("table");
    await user.click(await within(table).findByRole("button", { name: /Person001.*Night/ }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("dialog:emp-1:2026-10-26:r-1");
    const add = within(table).getAllByRole("button", { name: /Add roster entry for Person002/ })[0];
    await user.click(add);
    expect(screen.getByRole("dialog")).toHaveTextContent(/dialog:emp-2:2026-10-2\d:new/);
  });

  it("totals headcount per shift per day across all entries, not just the visible page", async () => {
    serve({ entriesTotal: 3, placed: { 1: ["emp-1", "s-night"] } });
    render(<RosterGridPage />);
    const table = await screen.findByRole("table");
    expect(await within(table).findByLabelText("Night on 2026-10-26: 3")).toHaveTextContent("3");
  });
});
