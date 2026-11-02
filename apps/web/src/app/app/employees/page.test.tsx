import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { permissions: ["EMPLOYEE.CREATE"] }, session: { companyId: "c1" } }),
}));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  apiClient: { getList: vi.fn(), post: vi.fn(), get: vi.fn().mockRejectedValue(new Error("not under test")) },
}));

import EmployeesPage from "@/app/app/employees/page";
import { apiClient } from "@/lib/api/client";
import type { PaginationMeta } from "@/lib/api/types";
import type { Employee } from "@/lib/employee/types";

const mockedGetList = vi.mocked(apiClient.getList);

function employee(name: string): Employee {
  return {
    id: name,
    employee_code: name.toUpperCase(),
    first_name: name,
    display_name: name,
    status: "ACTIVE",
    is_active: true,
    personal_email: null,
    personal_mobile: null,
  } as unknown as Employee;
}

const meta = (page: number): PaginationMeta => ({
  page,
  per_page: 1,
  total: 3,
  total_pages: 3,
});

function envelope(name: string, page: number) {
  return { data: [employee(name)], pagination: meta(page), meta: { request_id: "r" } } as never;
}

type Deferred = { resolve: (page: number, name: string) => void; signal?: AbortSignal };

function deferredPage(): Promise<{ data: Employee[]; pagination: PaginationMeta }> & Deferred {
  let resolver!: (v: { data: Employee[]; pagination: PaginationMeta }) => void;
  const promise = new Promise<{ data: Employee[]; pagination: PaginationMeta }>((r) => {
    resolver = r;
  }) as Promise<{ data: Employee[]; pagination: PaginationMeta }> & Deferred;
  promise.resolve = (page, name) => resolver({ data: [employee(name)], pagination: meta(page) });
  return promise;
}

describe("EmployeesPage loading behaviour", () => {
  afterEach(() => mockedGetList.mockReset());

  it("keeps the current rows on screen, dimmed, while the next page loads", async () => {
    const next = deferredPage();
    mockedGetList.mockResolvedValueOnce(envelope("alice", 1));
    mockedGetList.mockReturnValueOnce(next as never);
    const user = userEvent.setup();
    render(<EmployeesPage />);

    expect(await screen.findByText("alice")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /next/i }));

    // Old rows stay (no blank table / spinner swap), pagination stays but is disabled.
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();

    await act(async () => next.resolve(2, "bob"));
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(screen.queryByText("alice")).not.toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it("shows a skeleton, not stale or empty content, for the very first load", async () => {
    const first = deferredPage();
    mockedGetList.mockReturnValueOnce(first as never);
    render(<EmployeesPage />);

    expect(screen.getByRole("status", { name: /loading employees/i })).toBeInTheDocument();
    await act(async () => first.resolve(1, "alice"));
    expect(await screen.findByText("alice")).toBeInTheDocument();
  });

  it("cancels the in-flight request when the page unmounts", async () => {
    const second = deferredPage();
    mockedGetList.mockResolvedValueOnce(envelope("alice", 1));
    mockedGetList.mockReturnValueOnce(second as never);
    const user = userEvent.setup();
    const { unmount } = render(<EmployeesPage />);
    await screen.findByText("alice");

    await user.click(screen.getByRole("button", { name: /next/i }));
    const signal = mockedGetList.mock.calls[1]?.[2]?.signal as AbortSignal;
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(false);

    unmount();
    expect(signal.aborted).toBe(true);
  });
});

describe("EmployeesPage search", () => {
  afterEach(() => mockedGetList.mockReset());

  it("searches every page on the server, and returns to page 1 for a new search", async () => {
    mockedGetList.mockResolvedValue(envelope("alice", 1));
    const user = userEvent.setup();
    render(<EmployeesPage />);
    expect(await screen.findByText("alice")).toBeInTheDocument();

    // First request has no search term.
    expect(mockedGetList.mock.calls[0]?.[1]).toEqual({ page: 1 });

    await user.type(screen.getByRole("searchbox"), "varun m saji");

    await waitFor(() => {
      const params = mockedGetList.mock.calls.map((c) => c[1]);
      expect(params).toContainEqual({ page: 1, q: "varun m saji" });
    });
    // Debounced: one request for the whole phrase, not one per keystroke.
    const withQuery = mockedGetList.mock.calls.filter((c) => (c[1] as { q?: string }).q);
    expect(withQuery).toHaveLength(1);
  });
});

describe("EmployeesPage directory details", () => {
  const mockedGet = vi.mocked(apiClient.get);
  afterEach(() => {
    mockedGetList.mockReset();
    mockedGet.mockReset().mockRejectedValue(new Error("not under test"));
  });

  const placeholders = () => document.querySelectorAll("tbody .animate-pulse").length;

  it("shows a placeholder, not a dash, until the designation and department arrive", async () => {
    let resolveRows!: (rows: unknown) => void;
    mockedGet.mockImplementation((path: string) =>
      path.includes("/directory/rows")
        ? (new Promise((r) => {
            resolveRows = r;
          }) as never)
        : (Promise.reject(new Error("summary not under test")) as never),
    );
    mockedGetList.mockResolvedValueOnce(envelope("alice", 1));
    render(<EmployeesPage />);

    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(placeholders()).toBeGreaterThan(0);
    expect(screen.queryByText("Engineer")).not.toBeInTheDocument();

    await act(async () =>
      resolveRows([{ employee_id: "alice", designation: "Engineer", department: "Platform", branch: null, manager_name: "Meera", shift_name: "General" }]),
    );
    expect(await screen.findByText("Engineer")).toBeInTheDocument();
    expect(screen.getByText("Platform")).toBeInTheDocument();
    expect(placeholders()).toBe(0);
  });

  it("falls back to a dash, and stops showing placeholders, when the details can't be loaded", async () => {
    mockedGetList.mockResolvedValueOnce(envelope("alice", 1));
    render(<EmployeesPage />);
    expect(await screen.findByText("alice")).toBeInTheDocument();
    await waitFor(() => expect(placeholders()).toBe(0));
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows placeholders again for the next page instead of the previous page's details", async () => {
    const next = deferredPage();
    mockedGet.mockImplementation((path: string) =>
      path.includes("/directory/rows")
        ? (Promise.resolve([{ employee_id: path.includes("alice") ? "alice" : "bob", designation: path.includes("alice") ? "Engineer" : "Analyst", department: null, branch: null, manager_name: null, shift_name: null }]) as never)
        : (Promise.reject(new Error("summary not under test")) as never),
    );
    mockedGetList.mockResolvedValueOnce(envelope("alice", 1));
    mockedGetList.mockReturnValueOnce(next as never);
    const user = userEvent.setup();
    render(<EmployeesPage />);

    expect(await screen.findByText("Engineer")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /next/i }));
    await act(async () => next.resolve(2, "bob"));
    expect(await screen.findByText("Analyst")).toBeInTheDocument();
    expect(screen.queryByText("Engineer")).not.toBeInTheDocument();
  });
});
