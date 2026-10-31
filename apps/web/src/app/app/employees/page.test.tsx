import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({ user: { permissions: ["EMPLOYEE.CREATE"] }, session: { companyId: "c1" } }),
}));
vi.mock("@/components/common/toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ apiClient: { getList: vi.fn(), post: vi.fn() } }));

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
