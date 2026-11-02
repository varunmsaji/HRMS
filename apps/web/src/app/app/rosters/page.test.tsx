import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    user: { company_timezone: "Asia/Kolkata", permissions: ["ATTENDANCE.ROSTER_MANAGE"] },
    session: { companyId: "c1" },
  }),
}));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn(), delete: vi.fn() } }));

import RostersPage from "@/app/app/rosters/page";
import { apiClient } from "@/lib/api/client";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);

const DIRECTORY_TOTAL = 205;
const directoryPage = (page: number, perPage: number) =>
  Array.from({ length: DIRECTORY_TOTAL }, (_, i) => ({
    id: `emp-${i + 1}`,
    first_name: `Person${i + 1}`,
    last_name: null,
    employee_code: `E${i + 1}`,
  })).slice((page - 1) * perPage, page * perPage);

function rosterRow(n: number, employeeId: string) {
  return {
    id: `r-${n}`,
    employee_id: employeeId,
    roster_date: "2026-10-26",
    shift_id: null,
    is_week_off_override: true,
    is_holiday_working_override: false,
    status: "DRAFT",
    version: 1,
  };
}

describe("RostersPage with more than one page of data", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
  });

  function serve() {
    mockedGet.mockImplementation(((path: string) => {
      if (path === "/shifts") return Promise.resolve([]);
      if (path === "/employees/emp-205") {
        return Promise.resolve({ id: "emp-205", first_name: "Person205", last_name: null, employee_code: "E205" });
      }
      return Promise.reject(new Error(`Unexpected ${path}`));
    }) as never);
    mockedGetList.mockImplementation(((path: string, q: { page: number; per_page: number }) => {
      if (path === "/employees") {
        return Promise.resolve({
          data: directoryPage(q.page, q.per_page),
          pagination: { page: q.page, per_page: q.per_page, total: DIRECTORY_TOTAL, total_pages: 3 },
          meta: { request_id: "r" },
        });
      }
      if (path === "/rosters") {
        // 130 entries total, 100 per page: page 2 holds the last 30, the first of which is emp-205.
        const rows =
          q.page === 1
            ? Array.from({ length: 100 }, (_, i) => rosterRow(i, "emp-1"))
            : [rosterRow(100, "emp-205"), ...Array.from({ length: 29 }, (_, i) => rosterRow(101 + i, "emp-1"))];
        return Promise.resolve({
          data: rows,
          pagination: { page: q.page, per_page: q.per_page, total: 130, total_pages: 2 },
          meta: { request_id: "r" },
        });
      }
      return Promise.reject(new Error(`Unexpected ${path}`));
    }) as never);
  }

  it("paginates the roster list instead of showing only the first page as everything", async () => {
    serve();
    const user = userEvent.setup();
    render(<RostersPage />);

    expect(await screen.findByText("130")).toBeInTheDocument();
    expect(screen.getAllByText(/Person1 \(E1\)/).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await waitFor(() =>
      expect(mockedGetList.mock.calls.some((c) => c[0] === "/rosters" && (c[1] as { page: number }).page === 2)).toBe(true),
    );
  });

  it("names an employee who is beyond the first 100 loaded, instead of showing a raw id", async () => {
    serve();
    const user = userEvent.setup();
    render(<RostersPage />);
    await screen.findByText("130");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    // The identity cell shows the name with the code on its own line.
    expect(await screen.findByText("Person205")).toBeInTheDocument();
    expect(screen.getByText("E205")).toBeInTheDocument();
    expect(screen.queryByText("emp-205")).not.toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("/employees/emp-205");
  });

  it("offers the employee filter beyond the first 100 through Load more", async () => {
    serve();
    const user = userEvent.setup();
    render(<RostersPage />);
    expect(await screen.findByText(/showing 100 of 205 employees/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /load more/i }));
    await waitFor(() => expect(screen.getByText(/showing 200 of 205/i)).toBeInTheDocument());
  });
});
