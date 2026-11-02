import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useTeamBalances } from "@/lib/leave-ledger/use-team-balances";

const mockedGet = vi.mocked(apiClient.get);

const balance = (employeeId: string) => ({
  employee_id: employeeId,
  leave_type_id: "t-cl",
  leave_type_code: "CL",
  leave_type_name: "Casual",
  balance: "5",
  reserved_balance: "0",
});

function idOf(path: string): string {
  return path.split("employee_id=")[1] as string;
}

describe("useTeamBalances", () => {
  afterEach(() => mockedGet.mockReset());

  it("reads as loading until an employee's balances arrive, then ready", async () => {
    mockedGet.mockImplementation(((path: string) => Promise.resolve([balance(idOf(path))])) as never);
    const { result } = renderHook(() => useTeamBalances(["a"]));
    expect(result.current.rowFor("a").status).toBe("loading");
    await waitFor(() => expect(result.current.rowFor("a").status).toBe("ready"));
    expect(result.current.readyRows).toHaveLength(1);
  });

  it("never runs more than the allowed number of requests at once", async () => {
    let inFlight = 0;
    let peak = 0;
    const resolvers: Array<() => void> = [];
    mockedGet.mockImplementation(((path: string) => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      return new Promise((resolve) => {
        resolvers.push(() => {
          inFlight -= 1;
          resolve([balance(idOf(path))]);
        });
      });
    }) as never);

    const ids = ["a", "b", "c", "d", "e", "f"];
    const { result } = renderHook(() => useTeamBalances(ids, 2));
    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(2));
    expect(peak).toBe(2);

    while (resolvers.length) {
      await act(async () => resolvers.shift()?.());
    }
    await waitFor(() => expect(result.current.readyRows).toHaveLength(6));
    expect(peak).toBe(2);
  });

  it("fetches each employee once, even when they leave and re-enter the visible set", async () => {
    mockedGet.mockImplementation(((path: string) => Promise.resolve([balance(idOf(path))])) as never);
    const { result, rerender } = renderHook(({ ids }) => useTeamBalances(ids), {
      initialProps: { ids: ["a", "b"] },
    });
    await waitFor(() => expect(result.current.readyRows).toHaveLength(2));
    rerender({ ids: ["c"] });
    await waitFor(() => expect(result.current.rowFor("c").status).toBe("ready"));
    rerender({ ids: ["a", "b"] });
    expect(result.current.rowFor("a").status).toBe("ready");
    expect(mockedGet).toHaveBeenCalledTimes(3);
  });

  it("completes under StrictMode's mount/unmount/mount", async () => {
    mockedGet.mockImplementation(((path: string) => Promise.resolve([balance(idOf(path))])) as never);
    const { result } = renderHook(() => useTeamBalances(["a"]), { wrapper: StrictMode });
    await waitFor(() => expect(result.current.rowFor("a").status).toBe("ready"));
  });

  it("reports a 403 as 'No access' and other failures with their message, and can retry", async () => {
    mockedGet
      .mockRejectedValueOnce(new ApiError({ status: 403, code: "PERMISSION_DENIED", message: "nope" }))
      .mockResolvedValueOnce([balance("a")] as never);
    const { result } = renderHook(() => useTeamBalances(["a"]));
    await waitFor(() => expect(result.current.rowFor("a").status).toBe("error"));
    expect(result.current.rowFor("a")).toMatchObject({ forbidden: true, message: "No access" });

    act(() => result.current.retry("a"));
    await waitFor(() => expect(result.current.rowFor("a").status).toBe("ready"));
    expect(mockedGet).toHaveBeenCalledTimes(2);
  });
});
