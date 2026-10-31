import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiClient: { get: vi.fn() } }));

import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";

const mockedGet = vi.mocked(apiClient.get);
const known = [{ id: "emp-1", first_name: "Asha", last_name: null, employee_code: "E1" }];

describe("useEmployeeNames", () => {
  afterEach(() => mockedGet.mockReset());

  it("uses the loaded directory without any request", () => {
    const { result } = renderHook(() => useEmployeeNames(["emp-1"], known));
    expect(result.current("emp-1")).toBe("Asha (E1)");
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("resolves an employee beyond the loaded pages with one lookup, instead of showing a raw id", async () => {
    mockedGet.mockResolvedValue({ id: "emp-342", first_name: "Zed", last_name: "Z", employee_code: "E342" } as never);
    const { result, rerender } = renderHook(({ ids }) => useEmployeeNames(ids, known), {
      initialProps: { ids: ["emp-1", "emp-342"] },
    });
    expect(result.current("emp-342")).toBe("Loading…");
    await waitFor(() => expect(result.current("emp-342")).toBe("Zed Z (E342)"));

    rerender({ ids: ["emp-342", "emp-1"] });
    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(mockedGet).toHaveBeenCalledWith("/employees/emp-342");
  });

  it("marks an employee the caller may not see as unavailable and does not retry", async () => {
    mockedGet.mockRejectedValue(new ApiError({ status: 403, code: "FORBIDDEN", message: "no" }));
    const { result, rerender } = renderHook(({ ids }) => useEmployeeNames(ids, known), {
      initialProps: { ids: ["emp-9"] },
    });
    await waitFor(() => expect(result.current("emp-9")).toBe("Unavailable employee"));
    rerender({ ids: ["emp-9"] });
    expect(mockedGet).toHaveBeenCalledTimes(1);
  });
});
