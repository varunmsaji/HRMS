import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      employee_id: "me",
      company_timezone: "Asia/Kolkata",
      permissions: ["LEAVE.BALANCE_VIEW_ALL"],
    },
  }),
}));
vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), getList: vi.fn(), post: vi.fn() },
  newIdempotencyKey: () => "key",
}));

import LeaveBalancesPage from "@/app/app/leave-balances/page";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

const mockedGet = vi.mocked(apiClient.get);
const mockedGetList = vi.mocked(apiClient.getList);

const balance = (employeeId: string, name: string) => ({
  employee_id: employeeId,
  leave_type_id: `lt-${employeeId}`,
  leave_type_code: "CL",
  leave_type_name: name,
  balance: "5.0",
  reserved_balance: "0",
});
const ledgerEntry = (id: string, reason: string) => ({
  id,
  effective_date: "2026-10-01",
  entry_type: "ACCRUAL",
  amount: "1.0",
  reason,
  created_at: "2026-10-01T00:00:00Z",
});

type Pending<T> = { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void; signal?: AbortSignal };
function pending<T>(): Pending<T> {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const EMPLOYEES = [
  { id: "emp-a", first_name: "Asha", last_name: null, employee_code: "A1" },
  { id: "emp-b", first_name: "Bala", last_name: null, employee_code: "B1" },
];
const list = (data: unknown[], page = 1, totalPages = 1) =>
  ({ data, pagination: { page, per_page: 20, total: data.length, total_pages: totalPages }, meta: { request_id: "r" } }) as never;

describe("LeaveBalancesPage loading behaviour", () => {
  afterEach(() => {
    mockedGet.mockReset();
    mockedGetList.mockReset();
  });

  /** Per-employee controllable responses. */
  function setup() {
    const balances: Record<string, Pending<unknown>> = { "emp-a": pending(), "emp-b": pending() };
    const ledgers: Record<string, Pending<unknown>[]> = { "emp-a": [pending()], "emp-b": [pending()] };
    const signals: Record<string, AbortSignal[]> = { "emp-a": [], "emp-b": [] };
    mockedGet.mockImplementation(((path: string, opts?: { signal?: AbortSignal }) => {
      const id = path.split("employee_id=")[1] as string;
      if (opts?.signal) signals[id]?.push(opts.signal);
      return balances[id]!.promise;
    }) as never);
    mockedGetList.mockImplementation(((path: string, q: { employee_id?: string; page?: number }) => {
      if (path === "/employees") return Promise.resolve(list(EMPLOYEES));
      return (ledgers[q.employee_id as string]![(q.page ?? 1) - 1] ?? pending()).promise;
    }) as never);
    return { balances, ledgers, signals };
  }

  /** Team view opens on the matrix of everyone; choosing a person opens their ledger. */
  async function choose(user: ReturnType<typeof userEvent.setup>, id: string) {
    const name = id === "emp-a" ? "Asha" : "Bala";
    await user.click(await screen.findByRole("button", { name: new RegExp(`Open ${name}`) }));
  }

  it("shows a skeleton for the first load of a selected employee", async () => {
    setup();
    const user = userEvent.setup();
    render(<LeaveBalancesPage />);
    await choose(user, "emp-a");
    expect(await screen.findByRole("status", { name: /loading balances/i })).toBeInTheDocument();
  });

  it("never lets a slow response for the previous employee overwrite the current one", async () => {
    const { balances, ledgers, signals } = setup();
    const user = userEvent.setup();
    render(<LeaveBalancesPage />);

    await choose(user, "emp-a");
    await waitFor(() => expect(signals["emp-a"]).toHaveLength(1));
    await user.selectOptions(screen.getByRole("combobox"), "emp-b");
    await waitFor(() => expect(signals["emp-b"]).toHaveLength(1));
    // The request for A was cancelled the moment B was chosen.
    expect(signals["emp-a"]![0]!.aborted).toBe(true);

    await act(async () => {
      balances["emp-b"]!.resolve([balance("emp-b", "Bala leave")]);
      ledgers["emp-b"]![0]!.resolve(list([ledgerEntry("l-b", "B accrual")]));
    });
    expect(await screen.findByText("Bala leave")).toBeInTheDocument();

    // A's (late) answer arrives after B's — it must be ignored.
    await act(async () => {
      balances["emp-a"]!.resolve([balance("emp-a", "Asha leave")]);
      ledgers["emp-a"]![0]!.resolve(list([ledgerEntry("l-a", "A accrual")]));
    });
    expect(screen.getByText("Bala leave")).toBeInTheDocument();
    expect(screen.queryByText("Asha leave")).not.toBeInTheDocument();
    expect(screen.queryByText("A accrual")).not.toBeInTheDocument();
  });

  it("drops the previous employee's balances immediately on a change (no stale protected data)", async () => {
    const { balances, ledgers } = setup();
    const user = userEvent.setup();
    render(<LeaveBalancesPage />);
    await choose(user, "emp-a");
    await act(async () => {
      balances["emp-a"]!.resolve([balance("emp-a", "Asha leave")]);
      ledgers["emp-a"]![0]!.resolve(list([ledgerEntry("l-a", "A accrual")]));
    });
    expect(await screen.findByText("Asha leave")).toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox"), "emp-b");
    expect(screen.queryByText("Asha leave")).not.toBeInTheDocument();
    expect(screen.queryByText("A accrual")).not.toBeInTheDocument();
    expect(await screen.findByRole("status", { name: /loading balances/i })).toBeInTheDocument();
  });

  it("keeps the ledger visible, dimmed, while paging the same employee", async () => {
    const { balances, ledgers } = setup();
    ledgers["emp-a"]!.push(pending());
    const user = userEvent.setup();
    render(<LeaveBalancesPage />);
    await choose(user, "emp-a");
    await act(async () => {
      balances["emp-a"]!.resolve([balance("emp-a", "Asha leave")]);
      ledgers["emp-a"]![0]!.resolve(list([ledgerEntry("l1", "first page row")], 1, 2));
    });
    expect(await screen.findByText("first page row")).toBeInTheDocument();

    // Balances are re-requested together with the ledger page.
    balances["emp-a"] = pending();
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    expect(screen.getByText("first page row")).toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.getByRole("button", { name: /^next$/i })).toBeDisabled();
  });

  it("shows an error, not stale or false-success content, when a refresh fails", async () => {
    const { balances, ledgers } = setup();
    ledgers["emp-a"]!.push(pending());
    const user = userEvent.setup();
    render(<LeaveBalancesPage />);
    await choose(user, "emp-a");
    await act(async () => {
      balances["emp-a"]!.resolve([balance("emp-a", "Asha leave")]);
      ledgers["emp-a"]![0]!.resolve(list([ledgerEntry("l1", "first page row")], 1, 2));
    });
    await screen.findByText("first page row");

    balances["emp-a"] = pending();
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await act(async () => {
      balances["emp-a"]!.reject(new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Backend down" }));
      ledgers["emp-a"]![1]!.reject(new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "Backend down" }));
    });
    expect(await screen.findByText(/backend down/i)).toBeInTheDocument();
    expect(screen.queryByText("first page row")).not.toBeInTheDocument();
    expect(screen.queryByText("Asha leave")).not.toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it("aborts the in-flight request on unmount", async () => {
    const { signals } = setup();
    const user = userEvent.setup();
    const { unmount } = render(<LeaveBalancesPage />);
    await choose(user, "emp-a");
    await waitFor(() => expect(signals["emp-a"]).toHaveLength(1));
    expect(signals["emp-a"]![0]!.aborted).toBe(false);
    unmount();
    expect(signals["emp-a"]![0]!.aborted).toBe(true);
  });

  it("opens on everyone's balances, drills into a person, and returns to the list", async () => {
    setup();
    const user = userEvent.setup();
    render(<LeaveBalancesPage />);

    expect(await screen.findByText("Leave balances by employee")).toBeInTheDocument();
    await choose(user, "emp-a");
    expect(screen.queryByText("Leave balances by employee")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All employees" }));
    expect(await screen.findByText("Leave balances by employee")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "All employees" })).not.toBeInTheDocument();
  });
});
