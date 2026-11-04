import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { getList: vi.fn(), get: vi.fn() } }));

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";

const mockedGetList = vi.mocked(apiClient.getList);

const TOTAL = 342; // more than three server pages of 100
const ALL = Array.from({ length: TOTAL }, (_, i) => ({
  id: `emp-${i + 1}`,
  first_name: `First${i + 1}`,
  last_name: "Last",
  employee_code: `E${i + 1}`,
}));

function servePages() {
  mockedGetList.mockImplementation(((path: string, query: { page: number; per_page: number }) => {
    expect(path).toBe("/employees");
    const start = (query.page - 1) * query.per_page;
    return Promise.resolve({
      data: ALL.slice(start, start + query.per_page),
      pagination: {
        page: query.page,
        per_page: query.per_page,
        total: TOTAL,
        total_pages: Math.ceil(TOTAL / query.per_page),
      },
      meta: { request_id: "r" },
    });
  }) as never);
}

describe("useEmployeeDirectory", () => {
  afterEach(() => mockedGetList.mockReset());

  it("does not treat the first 100 as the whole company: reports total and hasMore", async () => {
    servePages();
    const { result } = renderHook(() => useEmployeeDirectory());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.employees).toHaveLength(100);
    expect(result.current.total).toBe(342);
    expect(result.current.hasMore).toBe(true);
    // Memory stays bounded by user action: only page 1 was requested.
    expect(mockedGetList).toHaveBeenCalledTimes(1);
  });

  it("reaches employees beyond the first 100 by loading further pages, without duplicates", async () => {
    servePages();
    const { result } = renderHook(() => useEmployeeDirectory());
    await waitFor(() => expect(result.current.loading).toBe(false));

    for (const expected of [200, 300, 342]) {
      act(() => result.current.loadMore());
      await waitFor(() => expect(result.current.employees).toHaveLength(expected));
    }
    expect(result.current.hasMore).toBe(false);
    expect(result.current.employees.at(-1)?.id).toBe("emp-342");
    expect(new Set(result.current.employees.map((e) => e.id)).size).toBe(342);
    expect(mockedGetList.mock.calls.map((c) => (c[1] as { page: number }).page)).toEqual([1, 2, 3, 4]);
  });

  it("ignores loadMore while a page is already in flight (no duplicate requests)", async () => {
    servePages();
    const { result } = renderHook(() => useEmployeeDirectory());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.loadMore();
      result.current.loadMore();
      result.current.loadMore();
    });
    await waitFor(() => expect(result.current.employees).toHaveLength(200));
    expect(mockedGetList).toHaveBeenCalledTimes(2);
  });

  it("keeps what is loaded when a later page fails, and can retry that page", async () => {
    servePages();
    const { result } = renderHook(() => useEmployeeDirectory());
    await waitFor(() => expect(result.current.loading).toBe(false));

    mockedGetList.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL_ERROR", message: "boom" }),
    );
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.employees).toHaveLength(100);
    expect(result.current.hasMore).toBe(true);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.employees).toHaveLength(200));
    expect(result.current.error).toBeNull();
  });

  it("does not fetch while disabled, and aborts its request on unmount", async () => {
    const { result, rerender } = renderHook(({ enabled }) => useEmployeeDirectory({ enabled }), {
      initialProps: { enabled: false },
    });
    expect(mockedGetList).not.toHaveBeenCalled();
    expect(result.current.employees).toEqual([]);

    mockedGetList.mockReturnValue(new Promise(() => {}) as never);
    rerender({ enabled: true });
    await waitFor(() => expect(mockedGetList).toHaveBeenCalledTimes(1));
    const signal = (mockedGetList.mock.calls[0]?.[2] as { signal: AbortSignal }).signal;
    expect(signal.aborted).toBe(false);
  });

  it("finishes loading under StrictMode's mount/unmount/mount, where the first request is aborted", async () => {
    mockedGetList.mockImplementation(((_path: string, query: { page: number; per_page: number }, opts: { signal: AbortSignal }) =>
      new Promise((resolve, reject) => {
        opts.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        setTimeout(
          () =>
            resolve({
              data: ALL.slice(0, query.per_page),
              pagination: { page: 1, per_page: query.per_page, total: TOTAL, total_pages: 4 },
              meta: { request_id: "r" },
            }),
          0,
        );
      })) as never);

    const { result } = renderHook(() => useEmployeeDirectory(), { wrapper: StrictMode });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.employees).toHaveLength(100);
  });
});
