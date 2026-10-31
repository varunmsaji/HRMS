import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const permissions = vi.hoisted(() => ({
  list: ["ATTENDANCE.VIEW", "LEAVE.APPLICATION_APPROVE"] as string[],
}));

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    session: { companyId: "c1" },
    user: { id: "u1", employee_id: "e1", company_timezone: "Asia/Kolkata", permissions: permissions.list },
  }),
}));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() },
}));

import { PendingApprovals } from "@/components/dashboard/pending-approvals";
import { QuickActions } from "@/components/dashboard/quick-actions";
import { WorkforceOverview } from "@/components/dashboard/workforce-overview";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AttendanceOverview } from "@/lib/dashboard/overview";

const get = vi.mocked(apiClient.get);
const getList = vi.mocked(apiClient.getList);

const overview: AttendanceOverview = {
  attendance_date: "2026-10-30",
  timezone: "Asia/Kolkata",
  is_today: true,
  generated_at: "2026-10-30T05:00:00Z",
  total: 10,
  expected_employees: 8,
  present: 5,
  absent: 1,
  on_leave: 1,
  on_duty: 0,
  remote_work: 0,
  not_checked_in: 1,
  incomplete: 0,
  not_expected: 1,
  no_record: 1,
  late: 2,
  half_day: 0,
  half_day_leave: 0,
  exceptions: 1,
  departments: [
    { department_id: "d1", department_name: "Engineering", total: 6, present: 4, absent: 1, on_leave: 0, on_duty: 0, remote_work: 0, not_checked_in: 1, incomplete: 0, not_expected: 0, no_record: 0 },
  ],
};

const props = { today: "2026-10-30", timezone: "Asia/Kolkata", departments: [{ id: "d1", name: "Engineering" }], branches: [] };

beforeEach(() => {
  vi.clearAllMocks();
  permissions.list = ["ATTENDANCE.VIEW", "LEAVE.APPLICATION_APPROVE"];
});

describe("WorkforceOverview", () => {
  it("shows backend figures as links into the filtered attendance view", async () => {
    get.mockResolvedValue(overview);
    render(<WorkforceOverview {...props} />);
    const present = await screen.findByRole("link", { name: /Present: 5/ });
    expect(present).toHaveAttribute("href", "/app/attendance?bucket=PRESENT");
    expect(screen.getByRole("link", { name: /Late arrivals: 2/ })).toHaveAttribute("href", "/app/attendance?flag=late");
    expect(screen.getByRole("link", { name: "Engineering" })).toHaveAttribute("href", "/app/departments/d1");
    expect(screen.getByText(/not guessed into any category/)).toBeInTheDocument();
    // Remote is hidden when the engine produced none.
    expect(screen.queryByRole("link", { name: /Remote:/ })).not.toBeInTheDocument();
  });

  it("shows an error with retry, and recovers", async () => {
    get.mockRejectedValueOnce(new ApiError({ status: 500, code: "X", message: "boom" }));
    get.mockResolvedValueOnce(overview);
    render(<WorkforceOverview {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("link", { name: /Present: 5/ })).toBeInTheDocument();
  });

  it("re-queries with the department filter and refresh, keeping figures on screen", async () => {
    get.mockResolvedValue(overview);
    render(<WorkforceOverview {...props} />);
    await screen.findByRole("link", { name: /Present: 5/ });
    await userEvent.selectOptions(screen.getByLabelText("Department"), "d1");
    await waitFor(() => expect(get).toHaveBeenCalledWith(expect.stringContaining("department_id=d1"), expect.anything()));
    expect(screen.getByRole("link", { name: /Present: 5/ })).toBeInTheDocument();
    const calls = get.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: /refresh workforce overview/i }));
    await waitFor(() => expect(get.mock.calls.length).toBe(calls + 1));
  });

  it("shows an empty state when no employees match", async () => {
    get.mockResolvedValue({ ...overview, total: 0, departments: [] });
    render(<WorkforceOverview {...props} />);
    expect(await screen.findByText(/No active employees match/)).toBeInTheDocument();
  });
});

describe("PendingApprovals", () => {
  const leave = {
    id: "l1", employee_id: "e2", leave_type_id: "t1", start_date: "2026-11-02", end_date: "2026-11-03",
    total_days: "2.0", submitted_at: "2026-10-29T05:00:00Z", approval_stage: "MANAGER", status: "SUBMITTED",
  };

  function mockLists(total: number) {
    getList.mockImplementation((path: string) =>
      Promise.resolve({
        data: path === "/leave-applications" && total > 0 ? [leave] : [],
        pagination: { page: 1, per_page: 5, total: path === "/leave-applications" ? total : 0, total_pages: 1 },
        meta: { request_id: "r" },
      }) as never,
    );
    get.mockImplementation((path: string) =>
      Promise.resolve(path === "/leave-types" ? [{ id: "t1", name: "Casual" }] : { id: "e2", first_name: "Asha" }) as never,
    );
  }

  it("shows the queue with the pending filter link, and only requests queues it may approve", async () => {
    mockLists(1);
    render(<PendingApprovals />);
    expect(await screen.findByText(/Casual/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Leave requests: 1 pending" })).toHaveAttribute(
      "href",
      "/app/leave-applications?status=SUBMITTED",
    );
    const paths = getList.mock.calls.map((c) => c[0]);
    expect(paths).toEqual(["/leave-applications"]);
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("lists only the latest requests until the user expands to all pending", async () => {
    mockLists(1);
    render(<PendingApprovals />);
    expect(await screen.findByRole("region", { name: "Latest pending requests" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Leave requests" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "View all pending requests (1)" }));
    expect(screen.getByRole("region", { name: "Leave requests" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Latest pending requests" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show latest only" }));
    expect(screen.getByRole("region", { name: "Latest pending requests" })).toBeInTheDocument();
  });

  it("shows the all-caught-up state", async () => {
    mockLists(0);
    render(<PendingApprovals />);
    expect(await screen.findByText(/No pending requests. You.re all caught up./)).toBeInTheDocument();
  });

  it("shows nothing actionable when the user can approve nothing", async () => {
    permissions.list = ["ATTENDANCE.VIEW"];
    mockLists(1);
    render(<PendingApprovals />);
    expect(await screen.findByText(/no approval queues/i)).toBeInTheDocument();
    expect(getList).not.toHaveBeenCalled();
  });
});

describe("QuickActions", () => {
  it("only offers shortcuts the user's permissions allow", () => {
    render(<QuickActions />);
    expect(screen.getByRole("link", { name: /View attendance/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Manage leave requests/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Add employee/ })).not.toBeInTheDocument();
  });
});
