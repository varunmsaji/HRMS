import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));

import { TeamBalanceMatrix } from "@/components/leave-balances/team-balance-matrix";
import { apiClient } from "@/lib/api/client";
import type { EmployeeDirectory } from "@/lib/employee/use-employee-directory";

const mockedGet = vi.mocked(apiClient.get);

const people = Array.from({ length: 25 }, (_, i) => ({
  id: `e${i + 1}`,
  first_name: i === 0 ? "Asha" : i === 1 ? "Bala" : `Person${i + 1}`,
  last_name: "Test",
  employee_code: `EMP-${String(i + 1).padStart(4, "0")}`,
}));

function directory(overrides: Partial<EmployeeDirectory> = {}): EmployeeDirectory {
  return {
    employees: people,
    total: people.length,
    hasMore: false,
    loading: false,
    loadingMore: false,
    error: null,
    loadMore: vi.fn(),
    retry: vi.fn(),
    ...overrides,
  };
}

const type = (id: string, code: string, name: string, balance: string, reserved = "0") => ({
  employee_id: "x",
  leave_type_id: id,
  leave_type_code: code,
  leave_type_name: name,
  balance,
  reserved_balance: reserved,
});

function serve(perEmployee: Record<string, ReturnType<typeof type>[]> = {}) {
  mockedGet.mockImplementation(((path: string) => {
    const id = path.split("employee_id=")[1] as string;
    return Promise.resolve(perEmployee[id] ?? [type("t-cl", "CL", "Casual Leave", "5.00"), type("t-sl", "SL", "Sick Leave", "0")]);
  }) as never);
}

describe("TeamBalanceMatrix", () => {
  afterEach(() => mockedGet.mockReset());

  it("shows a column per leave type and a formatted balance per employee", async () => {
    serve({ e1: [type("t-cl", "CL", "Casual Leave", "4.50", "1"), type("t-sl", "SL", "Sick Leave", "-2")] });
    render(<TeamBalanceMatrix directory={directory()} onSelectEmployee={vi.fn()} />);

    expect(await screen.findByRole("columnheader", { name: "Casual Leave" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Sick Leave" })).toBeInTheDocument();

    const row = screen.getByRole("button", { name: /Open Asha Test's leave ledger/ }).closest("tr") as HTMLElement;
    expect(within(row).getByText("4.5")).toBeInTheDocument();
    expect(within(row).getByText("1 pending")).toBeInTheDocument();
    expect(within(row).getByText("-2")).toHaveClass("text-danger");
  });

  it("fetches balances only for the visible page", async () => {
    serve();
    render(<TeamBalanceMatrix directory={directory()} onSelectEmployee={vi.fn()} />);
    await screen.findByRole("columnheader", { name: "Casual Leave" });
    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(20));
    expect(mockedGet.mock.calls.some(([path]) => String(path).endsWith("employee_id=e21"))).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(25));
  });

  it("opens an employee's ledger when their row is chosen", async () => {
    serve();
    const onSelect = vi.fn();
    render(<TeamBalanceMatrix directory={directory()} onSelectEmployee={onSelect} />);
    await userEvent.click(await screen.findByRole("button", { name: /Open Bala Test's leave ledger/ }));
    expect(onSelect).toHaveBeenCalledWith("e2");
  });

  it("narrows by name or code, and says so when nothing matches", async () => {
    serve();
    render(<TeamBalanceMatrix directory={directory()} onSelectEmployee={vi.fn()} />);
    await screen.findByRole("columnheader", { name: "Casual Leave" });

    await userEvent.type(screen.getByRole("searchbox", { name: "Find an employee" }), "asha");
    expect(screen.getAllByRole("button", { name: /^Open .* leave ledger$/ })).toHaveLength(1);

    await userEvent.clear(screen.getByRole("searchbox", { name: "Find an employee" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Find an employee" }), "zzzz");
    expect(await screen.findByText("No employee matches your search.")).toBeInTheDocument();
  });

  it("is honest that only the loaded employees are shown, and offers to load more", async () => {
    serve();
    const loadMore = vi.fn();
    render(<TeamBalanceMatrix directory={directory({ hasMore: true, total: 342, loadMore })} onSelectEmployee={vi.fn()} />);
    expect(screen.getByText(/Showing the first 25 of 342 employees/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(loadMore).toHaveBeenCalled();
  });

  it("shows a per-row error with a retry instead of breaking the whole table", async () => {
    mockedGet.mockImplementation(((path: string) =>
      path.endsWith("employee_id=e1")
        ? Promise.reject(new Error("boom"))
        : Promise.resolve([type("t-cl", "CL", "Casual Leave", "3")])) as never);
    render(<TeamBalanceMatrix directory={directory()} onSelectEmployee={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(await screen.findByRole("columnheader", { name: "Casual Leave" })).toBeInTheDocument();
  });

  it("shows the loading and error states of the directory itself", () => {
    const { rerender } = render(
      <TeamBalanceMatrix directory={directory({ employees: [], loading: true })} onSelectEmployee={vi.fn()} />,
    );
    expect(screen.getByRole("status", { name: "Loading employees" })).toBeInTheDocument();

    rerender(
      <TeamBalanceMatrix
        directory={directory({ employees: [], loading: false, error: { status: 500, code: "X", message: "m" } as never })}
        onSelectEmployee={vi.fn()}
      />,
    );
    expect(screen.getByText("Could not load employees.")).toBeInTheDocument();
  });
});
